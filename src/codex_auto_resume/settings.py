"""The one authoritative definition of configurable policy.

Every front end - the command line, the Codex skill, the MCP server and the standalone
Windows settings window - reads and writes through this module. There is exactly one
schema, one set of defaults, one validator, one persistence path and one migration, so
a value set in any interface is the same value everywhere.

Two rules shape what may live here:

* Only *policy* is configurable. Safety properties are not settings. There is no field
  that can retry an unknown failure, resolve a thread by title, skip revalidation or
  resend an uncertain submission - those are invariants of the engine, not preferences.
* An invalid or unknown value is never fatal and never silently widens behaviour. It
  falls back to the default, which is always the conservative choice.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from . import failures

CONFIG_VERSION = 2
MAX_SETTINGS_BYTES = 256 * 1024

# Recovery categories a user may turn off. The set is intentionally exactly the
# categories the classifier can already recover: enabling something here can never
# introduce a new class of automatic action.
CONFIGURABLE_CATEGORIES = (
    failures.USAGE_LIMIT,
    "network_transient",
    "timeout",
    "rate_limit_transient",
    "server_5xx",
    "stream_interrupted",
)

# Notification events, each independently suppressible.
NOTIFICATION_EVENTS = ("interruption", "starting", "result", "stopped")

# Retry timing presets. Raw ladders are not exposed: a preset cannot produce a zero
# delay or an unbounded one, which a free-form number could.
RETRY_TIMING = {
    "conservative": (15, 45, 120, 300, 600),
    "normal": (5, 15, 30, 60, 120),
    "aggressive": (3, 8, 20, 45, 90),
}
DEFAULT_TIMING = "normal"


class SettingsError(ValueError):
    """A rejected write. Reads never raise; they fall back to defaults."""


def _boolean(value, default):
    return value if isinstance(value, bool) else default


def _bounded_int(value, default, low, high):
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if low <= value <= high else default


def _bounded_number(value, default, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value) if low <= value <= high else default


def _choice(value, default, allowed):
    return value if isinstance(value, str) and value in allowed else default


def _optional_text(value, default):
    return value if isinstance(value, str) and value.strip() else default


# name -> (default, coercer). The coercer takes (raw, default) and always returns a
# valid value; that is what makes a malformed file harmless.
FIELDS = {
    "max_recovery_attempts": (4, lambda v, d: _bounded_int(v, d, 1, 20)),
    "max_no_progress": (3, lambda v, d: _bounded_int(v, d, 1, 10)),
    # How many continuations one task may receive in total, across every failure of it.
    # Never above 10, whatever the other limits say.
    "max_chain_continuations": (6, lambda v, d: _bounded_int(v, d, 1, 10)),
    "retry_timing": (DEFAULT_TIMING, lambda v, d: _choice(v, d, RETRY_TIMING)),
    "detection_lookback_hours": (6.0, lambda v, d: _bounded_number(v, d, 0.0, 24 * 7)),
    "notifications": (True, _boolean),
    # The watcher's notification-area icon. Showing it changes nothing about recovery.
    "show_tray": (True, _boolean),
    "codex_exe": (None, _optional_text),
}
# Every configurable category defaults ON: these are the failures already proven safe
# to recover, and a fresh install should recover them.
for _category in CONFIGURABLE_CATEGORIES:
    FIELDS["recover_" + _category] = (True, _boolean)
for _event in NOTIFICATION_EVENTS:
    FIELDS["notify_" + _event] = (True, _boolean)

DEFAULTS = {name: default for name, (default, _coerce) in FIELDS.items()}

# Ranges published to the user interfaces so a slider or spin box cannot offer a value
# the validator would reject.
RANGES = {
    "max_recovery_attempts": {"min": 1, "max": 20},
    "max_no_progress": {"min": 1, "max": 10},
    "max_chain_continuations": {"min": 1, "max": 10},
    "detection_lookback_hours": {"min": 0.0, "max": float(24 * 7)},
    "retry_timing": {"choices": list(RETRY_TIMING)},
}


def defaults() -> dict:
    return dict(DEFAULTS)


def coerce(raw) -> dict:
    """Validate a candidate mapping into a complete settings dict.

    Unknown keys are dropped and invalid values fall back to their default, so neither
    a hand-edited file nor a newer version's file can break the running watcher.
    """
    values = dict(DEFAULTS)
    if isinstance(raw, dict):
        for name, (default, coercer) in FIELDS.items():
            if name in raw:
                values[name] = coercer(raw[name], default)
    return values


def validate_update(changes) -> dict:
    """Strictly validate an explicit user edit. Unlike `coerce`, this rejects.

    A write is a deliberate act, so a bad value is reported rather than quietly
    replaced - otherwise a user would set 999 and be told it worked.
    """
    if not isinstance(changes, dict):
        raise SettingsError("settings must be an object")
    unknown = sorted(set(changes) - set(FIELDS))
    if unknown:
        raise SettingsError("unknown setting: %s" % ", ".join(unknown))
    clean = {}
    for name, value in changes.items():
        default, coercer = FIELDS[name]
        coerced = coercer(value, default)
        if coerced != value and not (name == "codex_exe" and value is None):
            raise SettingsError("invalid value for %s" % name)
        clean[name] = coerced
    return clean


def timing_ladder(values) -> tuple:
    name = _choice((values or {}).get("retry_timing"), DEFAULT_TIMING, RETRY_TIMING)
    return RETRY_TIMING[name]


def category_enabled(values, category: str) -> bool:
    """Whether automatic recovery is allowed for one failure category.

    A category this build does not expose is treated as enabled: the classifier already
    decided it is recoverable, and the absence of a toggle is not a instruction to stop.
    """
    key = "recover_" + str(category)
    if key not in FIELDS:
        return True
    return bool((values or {}).get(key, DEFAULTS[key]))


def notification_enabled(values, event: str) -> bool:
    values = values or {}
    if not values.get("notifications", DEFAULTS["notifications"]):
        return False
    key = "notify_" + str(event)
    return bool(values.get(key, DEFAULTS.get(key, True)))


# --------------------------------------------------------------------- persistence
def _migrate(raw) -> dict:
    """Bring an older settings file forward without losing what the user chose."""
    if not isinstance(raw, dict):
        return {}
    version = raw.get("config_version")
    if not isinstance(version, int) or version < 1:
        # v0.4.x wrote a flat file with no version marker. Its field names that still
        # exist keep their values; everything else takes the new default.
        return {name: raw[name] for name in FIELDS if name in raw}
    return raw


def load(path: Path) -> dict:
    """Read settings, falling back to defaults for anything missing or malformed."""
    try:
        target = Path(path)
        if (not target.is_file() or target.is_symlink()
                or target.stat().st_size > MAX_SETTINGS_BYTES):
            return defaults()
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return defaults()
    return coerce(_migrate(raw))


def save(path: Path, values: dict) -> dict:
    """Persist a complete settings dict atomically. Returns what was written."""
    target = Path(path)
    complete = coerce(values)
    payload = dict(complete, config_version=CONFIG_VERSION)
    target.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp + replace: a reader never observes a half-written file, and a pre-planted
    # symlink at a predictable temp name cannot be followed.
    descriptor, temporary = tempfile.mkstemp(dir=str(target.parent), prefix="settings.", suffix=".json.tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise SettingsError("cannot save settings") from exc
    return complete


def update(path: Path, changes: dict) -> dict:
    """Validate and merge an edit into the stored settings."""
    clean = validate_update(changes)
    return save(path, dict(load(path), **clean))


def describe() -> list:
    """Machine-readable schema for the settings interfaces.

    The user interfaces render themselves from this, so a field added here appears in
    every front end at once instead of being wired up three times.
    """
    described = []
    for name, (default, _coerce) in FIELDS.items():
        entry = {"name": name, "default": default,
                 "type": "boolean" if isinstance(default, bool)
                         else "integer" if isinstance(default, int)
                         else "number" if isinstance(default, float)
                         else "string"}
        if name in RANGES:
            entry.update(RANGES[name])
        if name.startswith("recover_"):
            entry["group"] = "recovery"
            entry["category"] = name[len("recover_"):]
        elif name.startswith("notify_") or name == "notifications":
            entry["group"] = "notifications"
            entry["master"] = name == "notifications"
        elif name == "show_tray":
            # A desktop preference, beside "run at sign-in" - not a notification, and
            # not something the notifications switch governs.
            entry["group"] = "windows"
        elif name in ("max_recovery_attempts", "max_no_progress", "max_chain_continuations",
                      "retry_timing"):
            entry["group"] = "limits"
        else:
            entry["group"] = "advanced"
        described.append(entry)
    return described
