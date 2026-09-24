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
from .pairing import desktop_pair, inventory
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
    def __init__(self, codex_home: Path, codex_exe: Path):
        self.codex_home = Path(codex_home).resolve()
        self.codex_exe = Path(codex_exe).resolve()
        self._version_signature = None
        self._last_checks = None
        self.engine_version = None
        self.engine_verified = False

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
        return all(flag in text for flag in REQUIRED_QUEUE_FLAGS)

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
                           text=True, encoding="utf-8", timeout=10, creationflags=NO_WINDOW,
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
        try:
            self._compatible()
            return desktop_pair(inventory(), self.codex_exe)
        except (AdapterError, OSError, KeyError, TypeError):
            return None

    def loaded(self, thread_id, app_identity):
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
            if users != [expected] or self.app_identity() != app_identity:
                return "unknown"
            return "loaded"
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
        process = None
        try:
            with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
                if permitted is not True:
                    return {"outcome": "not_started", "error_code": "queue_consent_refused"}
                process = S.Popen(self._argv() + ["queue", "--thread", thread_id, "--message", prompt],
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
            return {"outcome": "unknown", "error_code": "queue_response_unconfirmed"}
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
