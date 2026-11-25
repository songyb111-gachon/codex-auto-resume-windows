"""Codex's usage, the last reading (v0.6.11): what the watcher keeps of it, and how it is said.

The engine reads usage only when a recovery is due, and reuses a reading for 30 seconds
(engine/freshness.py); that has not changed, and nothing here reads anything (C4, C9). What is new
is that the watcher's heartbeat keeps the last reading that had windows, so every surface can show
it with its age. It keeps the allowlisted numbers the reply was already cut down to
(codex/usage.py) and nothing else (B10, D2):

    bucket          codex, premium, legacy or other - never the account's own name for it
    window          primary or secondary
    used_percent    a finite number, 0 or more
    window_minutes  a whole number of minutes, or None
    reset_at        whole seconds since 1970, or None

No account, plan, credit, banner or reason is kept, and a reading that holds anything else - or is
not what these rules make - is no reading at all. Pure: the standard library only.
"""
from __future__ import annotations

import json
import math

from .states import EPOCH_USAGE, epoch

BUCKETS = ("codex", "premium", "legacy", "other")
SLOTS = ("primary", "secondary")
KEYS = ("bucket", "window", "used_percent", "window_minutes", "reset_at")
# At most every bucket's two windows; a reply that names more is not one this product reads.
MAX_WINDOWS = len(BUCKETS) * len(SLOTS)
# What the stored text may come to, at most: eight windows of five numbers and words.
MAX_TEXT = 2048
# A week, in minutes: no window is kept that is ten of them or longer.
WEEK_MINUTES = 7 * 24 * 60


def _window(value):
    """One window as it is kept, or None when it is not exactly one."""
    if not isinstance(value, dict) or set(value) != set(KEYS):
        return None
    used, minutes, reset = value["used_percent"], value["window_minutes"], value["reset_at"]
    if value["bucket"] not in BUCKETS or value["window"] not in SLOTS:
        return None
    if type(used) not in (int, float) or not math.isfinite(used) or used < 0 or used > 10000:
        return None
    if minutes is not None and (type(minutes) is not int or not 0 < minutes <= 10 * WEEK_MINUTES):
        return None
    if reset is not None and not epoch(reset, *EPOCH_USAGE, integer=True, exact=True, finite=False):
        return None
    return {key: value[key] for key in KEYS}


def windows_of(reply) -> list | None:
    """The windows of one usage reply (codex/usage.py: parse_usage), as they are kept - or None when
    the reply has none, or any one of them is not what the allowlist keeps."""
    found = reply.get("windows") if isinstance(reply, dict) else None
    if not isinstance(found, list) or not found or len(found) > MAX_WINDOWS:
        return None
    kept = [_window(entry) for entry in found]
    return None if any(entry is None for entry in kept) else kept


def encode(windows) -> str | None:
    """The windows as the heartbeat stores them: compact JSON, or None when they are not a reading."""
    kept = windows_of({"windows": windows})
    if kept is None:
        return None
    text = json.dumps(kept, separators=(",", ":"), allow_nan=False)
    return text if len(text) <= MAX_TEXT else None


def decode(text) -> list | None:
    """The windows the heartbeat stored, or None for anything that is not exactly a reading."""
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return windows_of({"windows": value})


def newest(reading, added):
    """The last reading every surface says (v0.6.26 final, from the popup's newest_reading of v0.6.16-beta.3, issue
    #29): the watcher's own `reading` - or, where the advanced edition's usage meter read later, the meter's, which its
    plug adds to the status under its one key (`added`, the status's domain/plug.EXTRA), in core's own shape
    (meter_windows) and only where that shape is what windows_of keeps. The standard edition adds nothing there, so this
    is the watcher's reading, the very object, as it always was."""
    meter = added.get("meter") if isinstance(added, dict) else None
    if not (isinstance(meter, dict) and isinstance(meter.get("windows"), list)
            and type(meter.get("read_at")) in (int, float)):
        return reading
    if isinstance(reading, dict) and type(reading.get("read_at")) in (int, float) and reading["read_at"] >= meter["read_at"]:
        return reading
    windows = meter_windows(meter["windows"], reading)
    return reading if windows is None else {"read_at": meter["read_at"], "windows": windows}


def meter_windows(found, reading) -> list | None:
    """The meter's windows as core keeps a window (KEYS), or None where they are not a reading windows_of keeps. The
    meter keeps a window by its bucket and length and no slot, and adds its own band: the band is left out, and the slot
    is the one the watcher's `reading` gave the window of that bucket and length - or, where it has none, the shorter
    window of a bucket its primary and the longer its secondary, as Codex reports them."""
    if not isinstance(found, list):
        return None
    known = {}
    for window in (reading.get("windows") if isinstance(reading, dict) else None) or ():
        if isinstance(window, dict):
            known[(window.get("bucket"), window.get("window_minutes"))] = window.get("window")
    lengths = {}
    for window in found:
        if not isinstance(window, dict):
            return None
        lengths.setdefault(window.get("bucket"), []).append(window.get("window_minutes"))
    shaped = []
    for window in found:
        bucket, minutes = window.get("bucket"), window.get("window_minutes")
        slot = known.get((bucket, minutes))
        if slot not in SLOTS:
            ordered = sorted(lengths[bucket], key=lambda each: (each is None, each if type(each) is int else 0))
            slot = SLOTS[0] if ordered.index(minutes) == 0 else SLOTS[1]
        shaped.append({"bucket": bucket, "window": slot, "used_percent": window.get("used_percent"),
                       "window_minutes": minutes, "reset_at": window.get("reset_at")})
    return windows_of({"windows": shaped})
