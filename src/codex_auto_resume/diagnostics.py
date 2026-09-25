"""A diagnostics bundle a person can read before deciding whether to share it.

Built locally and written to a file the user picks; nothing here sends anything. It
holds what is needed to understand a recovery that went wrong - versions, the watcher's
health, settings, every record's state, reason and gates, the content-free journal and
the tail of the logs - and it is redacted before it is written:

* conversation and interruption ids become aliases that are consistent inside one
  bundle, so a timeline can be followed, but that no one can map back to a real id -
  the key is random and discarded with the bundle;
* file-system paths, the Windows user name and anything shaped like an e-mail address
  are replaced.

The logs never contained prompts, replies or tool output. `errors.log` holds exception
tracebacks whose messages are not filtered; they are redacted the same way, and the
bundle says so, so the reader knows to look before sharing.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import sys
import time

from . import config, interface, logbook, machine, startup
from .domain import ids
from .settings import is_custom_text

# A conversation id wherever a line holds one, in either case.
UUID_RE = re.compile(r"\b" + ids.uuid_pattern(any_case=True) + r"\b")
# Record ids are 64 hex characters; the log prints their first 12. Any run of 12 to 64
# hex characters is aliased: over-redacting a hash is harmless, missing an id is not.
KEY_RE = re.compile(r"\b[0-9a-f]{12,%d}\b" % ids.INTERRUPTION_ID_LENGTH)
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\\?\\|\\\\)[^\s'\"<>|]*")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LOG_LINES = 300


class Redactor:
    """Aliases and replacements for one bundle. The key never leaves this object."""

    def __init__(self):
        self._key = secrets.token_bytes(16)
        user = os.environ.get("USERNAME") or ""
        self._user = user if len(user) >= 3 else None

    def alias(self, value: str, prefix: str) -> str:
        digest = hashlib.sha256(self._key + str(value).lower().encode("utf-8")).hexdigest()
        return "%s-%s" % (prefix, digest[:8])

    def text(self, value: str) -> str:
        value = UUID_RE.sub(lambda m: self.alias(m.group(0), "thread"), value)
        value = KEY_RE.sub(lambda m: self.alias(m.group(0), "record"), value)
        value = EMAIL_RE.sub("<email>", value)
        value = PATH_RE.sub("<path>", value)
        if self._user:
            value = re.sub(re.escape(self._user), "<user>", value, flags=re.IGNORECASE)
        return value

    def unexpected(self, value) -> str:
        """What the bundle writes for a value that is not JSON - there should be none: its
        text, redacted like a log line, so a path or a user name in it never reaches the file
        and an odd value never costs the export."""
        return self.text(str(value))


def _record(row, redact: Redactor) -> dict:
    gates = machine.decode_gates(row.get("gate_eval")) if row.get("gate_eval") else None
    return {
        "record": redact.alias(row["interruption_id"], "record"),
        "thread": redact.alias(row["thread_id"], "thread"),
        "chain": redact.alias(row["chain_origin_id"], "record"),
        "state": row["state"], "code": machine.public_code(row), "reason": machine.public_reason(row),
        "category": row["category"], "detected_at": row["detected_at"], "next_retry_at": row["next_retry_at"],
        "reset_at": row["reset_at"], "submitted_at": row["submitted_at"],
        "first_queued_at": row["first_queued_at"], "turn_started_at": row["turn_started_at"],
        "outcome_at": row["outcome_at"], "recovery_turn_status": row["recovery_turn_status"],
        "attempts": row["attempt_count"], "recovery_attempts": row["recovery_attempts"],
        "no_progress_count": row["no_progress_count"], "chain_continuations": row["chain_continuations"],
        "budget_resets": row["budget_resets"], "cancel_requested": bool(row["cancel_requested"]),
        "user_joined": bool(row["user_joined"]), "after_user_work": bool(row["after_user_work"]),
        "legacy": bool(row["legacy"]), "hidden": row["history_hidden_at"] is not None,
        "gates": {name: list(result) for name, result in gates.items()} if gates else None,
    }


def _event(event, redact: Redactor) -> dict:
    event = dict(event)
    if event.get("interruption_id"):
        event["interruption_id"] = redact.alias(event["interruption_id"], "record")
    return event


def _tail(path: Path, redact: Redactor) -> list:
    try:
        lines = logbook.tail(path, LOG_LINES)
    except OSError:
        return []
    return [redact.text(line) for line in lines]


def _installation(control) -> dict:
    """Whether the pieces outside the state file are where they should be.

    Not paths, and not what they contain: only whether each one is there, and whether the
    one that names an owner names this installation. These are the first four questions
    asked of a machine where something is not happening - the sign-in entry is missing, the
    notification handler belongs to another copy, the MCP launcher was never unpacked, the
    window is speaking the wrong language - and each of them used to need a person to walk
    somebody through the registry over a support thread.
    """
    found = {}
    try:
        # What the settings choose, not what this process adopted: an export from the
        # command line never adopts the Interface language, and an open Dashboard adopted
        # it when it opened, which may be a language ago.
        found["language"] = interface.resolve(control.get_settings().get("interface_language"))
    except Exception:
        found["language"] = None
    for name, read in (("startup_entry", lambda: startup.current_value()),
                       ("protocol_handler", lambda: startup.protocol_value())):
        try:
            value = read()
        except Exception:
            found[name] = "unreadable"
            continue
        if not value:
            found[name] = "absent"
        else:
            # Whether it points at this installation, never where it points.
            try:
                found[name] = "ours" if startup.belongs_to(value, control.paths.home) else "another"
            except Exception:
                found[name] = "unreadable"
    try:
        found["notification_identity"] = {True: "ours", False: "another", None: "absent"}[
            startup.notification_identity_owner(control.paths.home)]
    except Exception:
        found["notification_identity"] = "unreadable"
    home = Path(control.paths.home)
    for name, relative in (("owner_marker", config.OWNER_MARKER),
                           ("runtime_record", "runtime.json"),
                           ("mcp_manifest", "app/.mcp.json"),
                           ("mcp_launcher", "app/mcp/codex-auto-resume-mcp.exe"),
                           ("settings_window", "CodexAutoResumeSettings.exe"),
                           ("bundled_runtime", "runtime/python.exe")):
        try:
            found[name] = (home / relative).exists()
        except OSError:
            found[name] = None
    return found


def _compatibility(control) -> dict:
    """The Compatibility Registry's view, as the watcher last wrote it and a reader checks it.

    Content-free by construction: states, reasons and check results from closed sets, a
    version string the log already carries, a timestamp, and since v0.6.10 what others report
    of that version - a word from a closed set and five counts that ship with the release, so
    nothing of this machine. The report's binding to the
    engine - a digest of its path and its size and time - stays out, because a digest of a
    path that holds the user name is a guessable one.
    """
    try:
        from . import compatio
        explicit = {"codex_exe": control.get_settings().get("codex_exe")}
        return compatio.reader_view(control.paths, settings=explicit)
    except Exception as exc:
        return {"status": "invalid", "error": type(exc).__name__}


def collect(control, *, now=None, redact=None) -> dict:
    """The whole bundle, redacted. Works with the watcher stopped and Codex closed."""
    redact = redact or Redactor()
    now = time.time() if now is None else now
    bundle = {
        "format": "codex-auto-resume-diagnostics/1",
        "created_at": now,
        "note": ("Redacted: ids are aliases valid only inside this file; paths, the Windows user "
                 "name and e-mail addresses are removed. The logs never held prompts or replies. "
                 "errors.log holds exception messages that are not filtered - read it before "
                 "sharing this file."),
        "product": {"version": config.version()},
        "system": {"windows": platform.version(), "python": sys.version.split()[0],
                   "machine": platform.machine()},
    }
    settings = control.get_settings()
    settings = dict(settings, codex_exe="<set>" if settings.get("codex_exe") else None)
    # A Custom message is the user's own writing and may say anything, so the bundle records
    # only whether each one is set. What was sent is not something a bug report needs.
    for name in list(settings):
        if is_custom_text(name):
            settings[name] = "<set>" if settings.get(name) else None
    bundle["settings"] = settings
    try:
        status = control.get_status()
        bundle["status"] = {key: status[key] for key in
                            ("enabled", "watcher", "upgrade_pending", "startup_enabled", "pending",
                             "states", "codes")}
    except Exception as exc:
        bundle["status"] = {"error": redact.text(str(exc))[:200]}
    try:
        with control._open() as store:
            bundle["schema_version"] = store.schema_version()
            bundle["records"] = [_record(row, redact) for row in store.all_records()]
            bundle["events"] = [_event(event, redact) for event in store.events(limit=2000)]
            bundle["statistics"] = store.statistics()
    except Exception as exc:
        bundle["records"] = []
        bundle["events"] = []
        bundle["state_error"] = redact.text(str(exc))[:200]
    bundle["installation"] = _installation(control)
    bundle["compatibility"] = _compatibility(control)
    logs = control.paths.logs_dir
    bundle["logs"] = {name: _tail(logs / name, redact)
                      for name in ("auto-resume.log", "errors.log", "launcher.log", "codex-start.log")
                      if (logs / name).is_file()}
    return bundle


def write(control, target: Path) -> Path:
    """Write the bundle as one JSON file. Refuses to overwrite anything."""
    target = Path(target)
    if target.exists():
        raise FileExistsError("refusing to overwrite %s" % target.name)
    redact = Redactor()
    # Written whole or not at all: the text is made before the file is, so a value that
    # cannot be written leaves no half a bundle behind to block the next attempt's name.
    text = json.dumps(collect(control, redact=redact), indent=1, ensure_ascii=False, allow_nan=False,
                      default=redact.unexpected)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(text)
    return target


def default_name(now=None) -> str:
    return "codex-auto-resume-diagnostics-%s.json" % time.strftime("%Y%m%d-%H%M%S",
                                                                   time.localtime(now or time.time()))
