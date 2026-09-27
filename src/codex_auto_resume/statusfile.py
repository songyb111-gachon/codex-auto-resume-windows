r"""A status file for other tools (v0.6.11): what the watcher is doing, in a file it rewrites each tick.

Off by default (the setting `status_file`), and an administrator's DisableStatusFile keeps it off
(managed.py). While it is on, the watcher writes `config\status.json` in its own state directory
after every tick, and once more as it stops, and nothing in this product ever reads it back: it is
for a status bar, a script or a dashboard of a person's own, which can read it without asking this
product anything and without a listener of any kind (no port, no socket - B14).

It is written whole or not at all (a temporary file beside it, then a replace), and it holds exactly
the keys below and nothing else - no conversation or record id, no label or title, no path, no text
anyone wrote:

    format          "codex-auto-resume/status/1"
    written_at      when it was written, seconds since 1970
    version         this product's version
    watcher         running, or stopped (written as the watcher stops on purpose; a file that says
                    running and has not been written for minutes belongs to a watcher that is gone)
    recovery        on, paused, or observe_only
    engine          the compatibility word the send gate reads (verified, checked,
                    structurally_compatible, incompatible, failed_here, unknown)
    pending         how many recoveries are pending
    states          how many of them are at each public code (a closed list)
    next_check_at   the soonest time a waiting one is looked at again, or null
    usage           Codex's usage as last read - when, and its allowlisted windows (domain/usage.py) -
                    or null

Turned off, the file is removed - only a regular file, in this directory, that says it is this one.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile

from . import machine
from .domain import usage as readings
from .domain.vocabulary import EngineState

FIELD = "status_file"
NAME = "status.json"
FORMAT = "codex-auto-resume/status/1"
# Every key the file may hold, in the order it is written. Anything else is never written.
KEYS = ("format", "written_at", "version", "watcher", "recovery", "engine", "pending", "states",
        "next_check_at", "usage")
WATCHER_WORDS = ("running", "stopped")
RECOVERY_WORDS = ("on", "paused", "observe_only")
# The heartbeat's word for the engine, which the send gate reads (store.ENGINE_STATES).
ENGINE_WORDS = tuple(EngineState)
MAX_BYTES = 16 * 1024


def wanted(values) -> bool:
    """Whether the file is written: only while the setting is on."""
    return isinstance(values, dict) and values.get(FIELD) is True


def _time(value):
    return float(value) if machine.epoch(value, *machine.EPOCH_STORE) else None


def content(*, now, version, running, enabled, observe_only, engine, rows, reading) -> dict:
    """The file's content, from what the watcher already has: every pending record (as the store
    keeps it), whether recovery is on and observe only, the engine's word and the last usage reading
    as the heartbeat keeps it ({"read_at", "windows"} or None)."""
    states = {}
    soonest = None
    for row in rows or ():
        code = machine.public_code(row)
        states[code] = states.get(code, 0) + 1
        due = machine.eligible_at(row)
        if isinstance(due, (int, float)) and not isinstance(due, bool) and math.isfinite(due):
            soonest = due if soonest is None else min(soonest, due)
    usage = None
    if isinstance(reading, dict):
        windows = readings.windows_of({"windows": reading.get("windows")})
        read_at = _time(reading.get("read_at"))
        if windows is not None and read_at is not None:
            usage = {"read_at": read_at, "windows": windows}
    return clean({
        "format": FORMAT,
        "written_at": float(now),
        "version": str(version),
        "watcher": "running" if running else "stopped",
        "recovery": "paused" if not enabled else "observe_only" if observe_only else "on",
        "engine": engine if engine in ENGINE_WORDS else "unknown",
        "pending": sum(states.values()),
        "states": {code: states[code] for code in sorted(states)},
        "next_check_at": _time(soonest),
        "usage": usage,
    })


def clean(value) -> dict:
    """`value` exactly as the file may hold it, or ValueError: the allowlist, checked key by key."""
    if not isinstance(value, dict) or tuple(value) != KEYS:
        raise ValueError("status keys")
    if value["format"] != FORMAT or value["watcher"] not in WATCHER_WORDS \
            or value["recovery"] not in RECOVERY_WORDS or value["engine"] not in ENGINE_WORDS:
        raise ValueError("status words")
    if _time(value["written_at"]) is None or (value["next_check_at"] is not None
                                              and _time(value["next_check_at"]) is None):
        raise ValueError("status times")
    version = value["version"]
    if not isinstance(version, str) or not version or len(version) > 32 \
            or any(not (ch.isalnum() or ch in ".-+") for ch in version):
        raise ValueError("status version")
    states = value["states"]
    if not isinstance(states, dict) or any(code not in machine.PUBLIC_CODES or type(count) is not int
                                           or count < 1 for code, count in states.items()):
        raise ValueError("status states")
    if type(value["pending"]) is not int or value["pending"] != sum(states.values()):
        raise ValueError("status pending")
    usage = value["usage"]
    if usage is not None and (not isinstance(usage, dict) or tuple(usage) != ("read_at", "windows")
                              or _time(usage["read_at"]) is None
                              or readings.windows_of({"windows": usage["windows"]}) != usage["windows"]):
        raise ValueError("status usage")
    return value


def _ours(target: Path) -> bool:
    """A regular file, not a link, that says it is this product's status file."""
    try:
        if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_BYTES:
            return False
        return json.loads(target.read_text(encoding="utf-8")).get("format") == FORMAT
    except (OSError, ValueError, AttributeError):
        return False


def write(target, value) -> None:
    """Replace the file with `value` whole: a reader sees the old file or the new, never half of one.
    Refuses (OSError) where something that is not this file stands in its place."""
    target = Path(target)
    text = json.dumps(clean(value), indent=2, allow_nan=False) + "\n"
    if target.is_symlink() or (target.exists() and not _ours(target)):
        raise OSError("not the status file")
    descriptor, temporary = tempfile.mkstemp(dir=str(target.parent), prefix="status.", suffix=".json.tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def remove(target) -> bool:
    """Remove the file if it is there and ours. Returns whether it was removed."""
    target = Path(target)
    if not _ours(target):
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True
