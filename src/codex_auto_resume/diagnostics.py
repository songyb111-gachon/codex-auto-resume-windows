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

from . import config, logbook, machine

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# Record ids are 64 hex characters; the log prints their first 12. Any run of 12 to 64
# hex characters is aliased: over-redacting a hash is harmless, missing an id is not.
KEY_RE = re.compile(r"\b[0-9a-f]{12,64}\b")
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


def collect(control, *, now=None) -> dict:
    """The whole bundle, redacted. Works with the watcher stopped and Codex closed."""
    redact = Redactor()
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
    logs = control.paths.logs_dir
    bundle["logs"] = {name: _tail(logs / name, redact)
                      for name in ("auto-resume.log", "errors.log", "launcher.log")
                      if (logs / name).is_file()}
    return bundle


def write(control, target: Path) -> Path:
    """Write the bundle as one JSON file. Refuses to overwrite anything."""
    target = Path(target)
    if target.exists():
        raise FileExistsError("refusing to overwrite %s" % target.name)
    bundle = collect(control)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(bundle, stream, indent=1, ensure_ascii=False, default=str)
    return target


def default_name(now=None) -> str:
    return "codex-auto-resume-diagnostics-%s.json" % time.strftime("%Y%m%d-%H%M%S",
                                                                   time.localtime(now or time.time()))
