"""Everything this product asks of the Codex CLI, and the checks it asks it first.

A Codex update bumps the version string, which alone must not disable auto-resume - so every
build, a Compatibility Registry VERIFIED one included, has to prove it still offers the exact
interface this tool drives. A failed local check always wins over what the registry says.
"""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import re
import subprocess as S

from .. import machine
from ..domain import ids, vocabulary
from ..win.inventory import resource_users
from ..win.kernel import NO_WINDOW
from .pairing import app_running, desktop_pair, engines_instead, inventory, own_holder, session_kind
from .appserver import PROTOCOL_METHODS, Protocol
from .errors import AdapterError
from .usage import parse_usage


# A Codex update bumps the version string, which alone must not disable auto-resume.
# Every build - a verified one included - has to prove it still offers the exact interface
# this tool drives. Anything that cannot prove it is refused: a failed local check always
# wins, whatever the Compatibility Registry says about the version.
REQUIRED_QUEUE_FLAGS = ("--thread", "--message")
# The only App Server methods the finite helper may call.


# The Compatibility Registry's local-check words, which the adapter's own probes answer with.
PASS, FAIL, UNAVAILABLE = (vocabulary.LocalResult.PASS, vocabulary.LocalResult.FAIL,
                           vocabulary.LocalResult.UNAVAILABLE)
_VERIFIED = None


def verified_versions() -> tuple:
    """Engine versions the bundled Compatibility Registry marks VERIFIED for sending.

    This used to be a constant naming codex-cli 0.153.4. The registry replaced it, and its
    evidence rule - a VERIFIED entry cites a recording that states the version it was made
    on - leaves it empty until such a recording exists. Nothing is "verified" by its version
    string alone, and nothing about recovery depends on it: an unverified build that passes
    the checks is COMPATIBLE, which is what the gate has always accepted.
    """
    global _VERIFIED
    if _VERIFIED is None:
        try:
            # compat/files.py directly, not the compatio front: through the front this
            # loaded the registry's whole io half, whose probes import this adapter back.
            from ..compat import files as registry_files
            _VERIFIED = tuple(registry_files.bundled_verified_versions())
        except Exception:
            _VERIFIED = ()
    return _VERIFIED


def canonical_uuid(value):
    if not ids.is_uuid(value):
        raise ValueError("invalid_uuid")
    return value


class Backend:
    def __init__(self, codex_home: Path, codex_exe: Path, require_holder: bool = False):
        self.codex_home = Path(codex_home).resolve()
        self.codex_exe = Path(codex_exe).resolve()
        # v0.6.15-beta: a Codex home other than the default is the app's only while its server holds that
        # home's database open (codex/pairing.py); the default home is paired as it always was.
        self.require_holder = require_holder
        # v0.6.16-beta.4: the one holder - its pid and creation time - of the conversation the last loaded() said is
        # "elsewhere", and None after any other answer: what the re-check under the dispatch lock holds a continuation
        # sent to another Codex session to (engine/tosession.py).
        self.session_holder = None
        self._version_signature = None
        self._last_checks = None
        self.engine_version = None
        self.engine_verified = False
        # Explicit local-daemon routing only on builds with the --remote flag.
        self.queue_remote_supported = False
        # v0.6.13: the codex.exe paths the app main was last seen running as its children where
        # none of them ran this engine - an update that started the app's server from another
        # build - and nothing whenever that is not what the last pairing saw (app_identity).
        self.served_elsewhere = frozenset()
        # v0.6.16-beta.4: the inventory rows the last app_identity() read - in memory only, for loaded() and holder()
        # to tell another Codex session holding a conversation from anything unknown without reading them again -
        # or None where that look could not read them.
        self._rows = None

    def _environment(self):
        env = os.environ.copy()
        env["CODEX_HOME"] = str(self.codex_home)
        # The binary reuses its own authenticated context; Python reads no auth file.
        env["OTEL_SDK_DISABLED"] = "true"
        return env

    def _argv(self):
        return [str(self.codex_exe), "-c", "analytics.enabled=false",
                "-c", 'otel.exporter="none"', "-c", 'otel.trace_exporter="none"',
                "-c", 'otel.metrics_exporter="none"', "-c", "otel.log_user_prompt=false",
                "-c", 'chatgpt_base_url="https://chatgpt.com/backend-api/"']

    def _queue_interface_ok(self):
        """Prove `codex queue` still takes the exact flags we drive it with."""
        result = S.run([str(self.codex_exe), "queue", "--help"], stdout=S.PIPE, stderr=S.DEVNULL,
                       text=True, encoding="utf-8", errors="replace", timeout=20,
                       creationflags=NO_WINDOW, shell=False, env=self._environment())
        if result.returncode != 0:
            return False
        text = result.stdout
        self.queue_remote_supported = "--remote" in text
        return all(flag in text for flag in REQUIRED_QUEUE_FLAGS)

    def _queue_daemon_remote(self) -> bool:
        """Choose the local managed daemon explicitly when Codex offers that route.

        Recent Codex refuses an embedded queue server with any -c override
        while a managed app-server daemon runs. Removing overrides would weaken
        the telemetry safeguards. --remote unix:// retains all the overrides.
        Fail closed to the existing invocation if the home or process is unknown.
        Never try both routes for one send, since delivery could be uncertain.
        """
        if not self.queue_remote_supported:
            return False
        prefix = str(self.codex_home / "packages" / "app-server-daemon" / "releases").casefold() + "\\"
        try:
            rows = inventory()
        except (AdapterError, OSError, ValueError):
            return False
        return any(
            isinstance(row, dict)
            and type(row.get("pid")) is int and row["pid"] > 0
            and isinstance(row.get("path"), str)
            and row["path"].casefold().startswith(prefix)
            and bool(re.fullmatch(r"[^\\]+\\bin\\codex\.exe",
                                  row["path"][len(prefix):], re.I))
            for row in rows
        )

    def engine_checks(self) -> dict:
        """The engine's three structural checks, as the Compatibility Registry reads them.

        E1 `official_location` - the binary sits at the official, content-addressed path;
        E2 `version_runs` - `codex --version` runs and exits 0;
        E4 `queue_flags` - `codex queue --help` exits 0 and offers --thread and --message.

        Each is PASS, FAIL (it ran and said no) or UNAVAILABLE (it could not run - the
        binary vanished, a process failed to start or timed out). Returns them with the
        version and the binary's (size, mtime_ns) signature they were made on. Never raises
        for a process or file failure; that is what UNAVAILABLE is for.

        Probes run only when the signature differs from the last accepted one, exactly as
        `_compatible()` always did, and a full PASS is what `_compatible()` accepts - so the
        registry and the adapter can never disagree about the binary in use.
        """
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
        expected = re.compile(re.escape(str(local)) + r"\\[0-9a-f]+\\codex\.exe", re.I)
        checks = {"official_location": FAIL, "version_runs": UNAVAILABLE,
                  "queue_flags": UNAVAILABLE, "version": None, "signature": None}
        if not expected.fullmatch(str(self.codex_exe)):
            self._last_checks = checks
            return dict(checks)
        checks["official_location"] = PASS
        try:
            stat = self.codex_exe.stat()
        except OSError:
            self._last_checks = checks
            return dict(checks)
        signature = (stat.st_size, stat.st_mtime_ns)
        checks["signature"] = signature
        if signature == self._version_signature:
            checks.update(version_runs=PASS, queue_flags=PASS, version=self.engine_version)
            self._last_checks = checks
            return dict(checks)
        try:
            result = S.run([str(self.codex_exe), "--version"], stdout=S.PIPE, stderr=S.DEVNULL,
                           text=True, encoding="utf-8", errors="replace", timeout=10, creationflags=NO_WINDOW,
                           shell=False, env=self._environment())
        except (OSError, S.SubprocessError):
            self._last_checks = checks
            return dict(checks)
        if result.returncode != 0:
            self._last_checks = checks
            return dict(checks)
        version = result.stdout.strip()
        checks.update(version_runs=PASS, version=version)
        try:
            flags = self._queue_interface_ok()
        except (OSError, S.SubprocessError):
            self._last_checks = checks
            return dict(checks)
        if not flags:
            checks["queue_flags"] = FAIL
            self._last_checks = checks
            return dict(checks)
        checks["queue_flags"] = PASS
        # Accepted: every build, the ones the registry calls verified included, has now
        # shown it still offers the interface this tool drives. Delivery is still proven per
        # interruption, by the marker, before anything is called resumed.
        self.engine_version = version
        self.engine_verified = version in verified_versions()
        self._version_signature = signature
        self._last_checks = checks
        return dict(checks)

    def last_checks(self):
        """The result of the most recent `engine_checks()`, or None before the first."""
        return dict(self._last_checks) if self._last_checks is not None else None

    def _compatible(self):
        checks = self.engine_checks()
        if checks["official_location"] != PASS:
            raise AdapterError("unsupported_codex_location")
        if checks["version_runs"] != PASS or checks["queue_flags"] == UNAVAILABLE:
            raise AdapterError("codex_binary_unavailable")
        if checks["queue_flags"] != PASS:
            raise AdapterError("unsupported_codex_version")

    def app_identity(self):
        self.served_elsewhere = frozenset()
        try:
            self._compatible()
            self._rows = None
            rows = self._rows = inventory()
            try:
                if self.require_holder:
                    return desktop_pair(rows, self.codex_exe, self.codex_home, require_holder=True)
                return desktop_pair(rows, self.codex_exe, self.codex_home)
            except AdapterError:
                # The same rows, read again for one thing: the paths the app main runs instead,
                # which the watcher asks before its next tick (runtime/app.py, engine_moved).
                self.served_elsewhere = engines_instead(rows, self.codex_exe)
                raise
        except (AdapterError, OSError, KeyError, TypeError):
            return None

    def loaded(self, thread_id, app_identity):
        self.session_holder = None
        try:
            canonical_uuid(thread_id)
            self._compatible()
            if not app_identity or self.app_identity() != app_identity:
                return "unknown"
            path = self.codex_home / "thread-writer-locks" / (thread_id + ".lock")
            # Identify who holds the lock file OPEN via Restart Manager first. This never
            # acquires a byte lock, so it cannot race the app's own exclusive writer lock.
            # An empty inventory (absent file, or a stale file no process holds) is notLoaded.
            users = resource_users(path)
            if not users:
                return "notLoaded"
            expected = {key: app_identity["server"][key] for key in ("pid", "created")}
            # Exactly the app's own Codex server holds it, and app identity is stable.
            # A CLI-owned writer, missing identity or ambiguity fails closed.
            #
            # Ownership is decided PURELY by Restart Manager: the upstream writer lock
            # guard holds the file open for exactly as long as it holds the byte lock
            # (it closes and deletes the file on drop), so "the app server has this file
            # open" already means "the app server holds the writer lock". We deliberately
            # do NOT probe with LockFileEx: on a momentarily free range that call would
            # ACQUIRE the app's own exclusive lock and could make the app's try_lock fail.
            if users == [expected] and self.app_identity() == app_identity:
                return "loaded"
            # v0.6.16-beta.4: one holder that is another Codex session - a terminal's TUI or VS Code's server
            # (pairing.session_kind), with the app identity still the same - is "elsewhere": it waits with its
            # own reason, and nothing is sent. Anything else fails closed, as always.
            if (len(users) == 1 and users != [expected] and self.app_identity() == app_identity
                    and session_kind(self._rows, users[0], self.codex_exe)):
                self.session_holder = (users[0]["pid"], users[0]["created"])
                return "elsewhere"
            return "unknown"
        except (AdapterError, ValueError, OSError, KeyError, TypeError):
            return "unknown"

    def holder(self, thread_id):
        """v0.6.16-beta.4: who holds conversation `thread_id`'s writer lock while the Codex app is not running - asked
        by the engine only where its plug wants P16 (engine/delivery.py): "none" - the last app_identity() read the
        processes and found no process of the app's package, and the Restart Manager finds no holder (B12) -;
        "session", one holder that is another Codex session (pairing.session_kind); "ours", one holder that is an app
        server this process started and still holds, by the pid and creation time of our own spawn (pairing.own_holder):
        what a route that has just resumed the conversation on its own server meets at its last look; and "unknown" for
        anything else, a failure included. The rows are the ones the app's pairing read: no process is started for it."""
        try:
            canonical_uuid(thread_id)
            self._compatible()
            rows = self._rows
            if rows is None or app_running(rows):
                return "unknown"
            users = resource_users(self.codex_home / "thread-writer-locks" / (thread_id + ".lock"))
            if not users:
                return "none"
            if len(users) == 1 and session_kind(rows, users[0], self.codex_exe):
                return "session"
            if len(users) == 1 and own_holder(users[0]):
                return "ours"
            return "unknown"
        except (AdapterError, ValueError, OSError, KeyError, TypeError):
            return "unknown"

    def usage(self):
        try:
            with Protocol(self) as client:
                return parse_usage(client.call("account/rateLimits/read"))
        except (AdapterError, OSError, S.SubprocessError, ValueError):
            return {"available": None, "reset_at": None, "limit_type": "unknown", "reason": "usage_probe_unavailable"}

    def send(self, thread_id, prompt, *, launch_guard=None):
        """Only spawn failure permits retry. Every post-spawn uncertainty is terminal."""
        try:
            canonical_uuid(thread_id)
            if not isinstance(prompt, str) or not prompt or len(prompt) > 8192 or "\0" in prompt:
                raise ValueError("invalid_prompt")
            self._compatible()
        except (AdapterError, ValueError):
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        remote = self._queue_daemon_remote()
        process = None
        try:
            with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
                if permitted is not True:
                    return {"outcome": "not_started", "error_code": "queue_consent_refused"}
                # v0.6.18: the message as one `--message=` argument - a person's text that starts with "-" ("- keep
                # going", "---") is then never read as an option, whatever the parser's defaults.
                queue_args = (["queue", "--thread", thread_id, "--message=" + prompt]
                              + (["--remote", "unix://"] if remote else []))
                process = S.Popen(self._argv() + queue_args,
                                  stdin=S.DEVNULL, stdout=S.PIPE, stderr=S.DEVNULL, text=True,
                                  encoding="utf-8", errors="replace", shell=False, close_fds=True,
                                  creationflags=NO_WINDOW, cwd=str(self.codex_home), env=self._environment())
        except Exception:
            if process is None:
                return {"outcome": "not_started", "error_code": "queue_spawn_failed"}
            # A guard exit can fail after Popen. The process already exists: read its
            # receipt below, never call this an unsent attempt or launch it again.
        try:
            stdout, _ = process.communicate(timeout=45)
            match = re.fullmatch(r"Queued message ([0-9a-f-]{36}) for thread " + re.escape(thread_id) + r"\.", stdout.strip())
            if process.returncode == 0 and match:
                queue_id = canonical_uuid(match.group(1))
                return {"outcome": "accepted", "queue_id": queue_id}
            # Only the documented single-line receipt confirms delivery. Diagnostic fields are
            # fixed words and an exit code; never return stdout, stderr, or the user's prompt.
            # Even exit != 0 is uncertain after Popen: Codex may have queued the message first.
            if process.returncode != 0:
                if type(process.returncode) is int and 0 <= process.returncode <= 255:
                    return {"outcome": "unknown", "error_code": "queue_response_unconfirmed",
                            "receipt_detail": "nonzero_exit", "exit_code": process.returncode}
                return {"outcome": "unknown", "error_code": "queue_response_unconfirmed",
                        "receipt_detail": "nonzero_exit"}
            if not stdout.strip():
                return {"outcome": "unknown", "error_code": "queue_response_unconfirmed",
                        "receipt_detail": "empty_stdout"}
            return {"outcome": "unknown", "error_code": "queue_response_unconfirmed",
                    "receipt_detail": "unrecognized_stdout"}
        except S.TimeoutExpired:
            try:
                process.kill()  # only this helper; accepted delivery is still possible
                process.communicate(timeout=5)
            except (OSError, S.SubprocessError):
                pass
            return {"outcome": "unknown", "error_code": "queue_timeout"}
        except (OSError, ValueError, S.SubprocessError):
            return {"outcome": "unknown", "error_code": "queue_result_unknown"}
        finally:
            if process.stdout:
                process.stdout.close()

    def delete_queue(self, thread_id, queue_id):
        try:
            canonical_uuid(thread_id)
            canonical_uuid(queue_id)
            with Protocol(self) as client:
                result = client.call("thread/queue/delete", {"threadId": thread_id, "queuedSubmissionId": queue_id})
            return isinstance(result, dict) and result.get("deleted") is True
        except (AdapterError, ValueError, OSError, S.SubprocessError):
            return False
