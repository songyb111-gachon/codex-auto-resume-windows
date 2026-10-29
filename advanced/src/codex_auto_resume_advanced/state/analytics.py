# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What usage_analytics keeps (v0.6.20; advanced state version 8, the groundwork's tables).

    usage_samples  each usage window's share at each reading the meter made while the analytics stood on: the window
                   (a bucket and its length in minutes), when, how full, and when it resets - for the pace (burn rate)
    token_days     the tokens a conversation used on a local day, by kind - input, cached input, output, reasoning -
                   and how many turns began that day, under its project's 16-hex key - never a word of it, never a path
    token_files    how far each rollout was read, under a digest of its path (codex/tokens.file_key) and never the path

Numbers, ids, digests and closed words only (D2). The journal's pruning pass bounds all three (state/journal.py): 90
days, the samples 20,000 rows at most. Nothing core decides, and no gate of this edition, reads any of it
(advanced/tests/test_advanced_analytics.py holds that by the source): the card on the Advanced features page and its CSV
are its only readers (control/analytics.py).
"""
from __future__ import annotations

import math
import re

from codex_auto_resume.domain import ids

from .schema import BUCKETS
from .session import StateError

CAPABILITY = "usage_analytics"
METER = "usage_meter"
# The longest window a sample may name, in minutes (the schema's CHECK).
MAX_MINUTES = 100800
# A count larger than this is refused: no conversation uses that many tokens in a day.
MOST = 10 ** 13
DAY = re.compile(r"\A[0-9]{4}-[01][0-9]-[0-3][0-9]\Z")
HEX16 = re.compile(r"\A[0-9a-f]{16}\Z")
_DAY_COLUMNS = ("day", "thread_id", "project_digest", "input", "cached", "output", "reasoning", "turns")
_FILE_COLUMNS = ("file_digest", "thread_id", "size", "offset", "mtime_ns", "read_at")
_SAMPLE_COLUMNS = ("bucket", "minutes", "at", "used_percent", "reset_at")


def _count(value, what) -> int:
    if type(value) is not int or not 0 <= value <= MOST:
        raise StateError("invalid %s" % what)
    return value


def _hex16(value, what, null=False):
    if value is None and null:
        return None
    if not isinstance(value, str) or not HEX16.match(value):
        raise StateError("invalid %s" % what)
    return value


def _uuid(value):
    if not ids.is_uuid(value) or value != value.lower():
        raise StateError("invalid thread id")
    return value


class AnalyticsMixin:
    # ------------------------------------------------------------------ token_files
    def token_files(self) -> dict:
        """{file_key: row} of every rollout read so far; empty with no file."""
        with self._read() as connection:
            if connection is None:
                return {}
            rows = connection.execute("SELECT %s FROM token_files" % ", ".join(_FILE_COLUMNS)).fetchall()
        return {row["file_digest"]: dict(row) for row in rows}

    def ingest_file(self, file_key, thread_id, *, size, offset, changed_ns, days, project_key, at=None) -> int:
        """One rollout's pass written in one transaction: where it now stands (token_files), and the numbers it read
        added to each day's row of its conversation (token_days) - its project key kept where the pass names one.
        `days` is {day: [input, cached, output, reasoning, turns]}. How many day rows it touched."""
        _hex16(file_key, "file key")
        _uuid(thread_id)
        _hex16(project_key, "project key", null=True)
        _count(size, "size")
        _count(offset, "offset")
        if type(changed_ns) is not int or changed_ns < 0:
            raise StateError("invalid mtime")
        now = self._now(at)
        rows = []
        for day, numbers in (days or {}).items():
            if not isinstance(day, str) or not DAY.match(day):
                raise StateError("invalid day")
            if not isinstance(numbers, (list, tuple)) or len(numbers) != 5:
                raise StateError("invalid numbers")
            rows.append((day, *[_count(number, "count") for number in numbers]))
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO token_files (file_digest, thread_id, size, offset, mtime_ns, read_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(file_digest) DO UPDATE SET thread_id=excluded.thread_id, size=excluded.size, "
                "offset=excluded.offset, mtime_ns=excluded.mtime_ns, read_at=excluded.read_at",
                (file_key, thread_id, size, offset, changed_ns, now))
            for day, input_, cached, output, reasoning, turns in rows:
                connection.execute(
                    "INSERT INTO token_days (day, thread_id, project_digest, input, cached, output, reasoning, turns) "
                    "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(day, thread_id) DO UPDATE SET "
                    "project_digest=coalesce(excluded.project_digest, project_digest), input=min(input+excluded.input, ?), "
                    "cached=min(cached+excluded.cached, ?), output=min(output+excluded.output, ?), "
                    "reasoning=min(reasoning+excluded.reasoning, ?), turns=min(turns+excluded.turns, ?)",
                    (day, thread_id, project_key, input_, cached, output, reasoning, turns, MOST, MOST, MOST, MOST,
                     MOST))
        return len(rows)

    # ------------------------------------------------------------------ token_days
    def token_days(self, since_day=None) -> list:
        """Every token_days row from `since_day` (YYYY-MM-DD) on, the oldest day first; empty with no file."""
        if since_day is not None and (not isinstance(since_day, str) or not DAY.match(since_day)):
            raise StateError("invalid day")
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute(
                "SELECT %s FROM token_days WHERE day >= ? ORDER BY day, thread_id" % ", ".join(_DAY_COLUMNS),
                (since_day or "0000-00-00",)).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ usage_samples
    def add_samples(self, windows, *, at=None) -> int:
        """One meter reading's windows (core's kept form - bucket, window_minutes, used_percent, reset_at) appended as
        samples at `at`: each window once, its fullest where a reading names it twice. How many it kept."""
        now = self._now(at)
        kept = {}
        for window in windows or ():
            if not isinstance(window, dict):
                continue
            used, bucket, minutes = window.get("used_percent"), window.get("bucket"), window.get("window_minutes")
            reset = window.get("reset_at")
            if (type(used) not in (int, float) or not math.isfinite(used) or used < 0 or bucket not in BUCKETS
                    or type(minutes) is not int or not 1 <= minutes <= MAX_MINUTES
                    or not (reset is None or (type(reset) is int and reset >= 0))):
                continue
            if (bucket, minutes) not in kept or used > kept[(bucket, minutes)][0]:
                kept[(bucket, minutes)] = (float(used), reset)
        if not kept:
            return 0
        with self._transaction() as connection:
            for (bucket, minutes), (used, reset) in kept.items():
                connection.execute("INSERT OR REPLACE INTO usage_samples (bucket, minutes, at, used_percent, reset_at) "
                                   "VALUES (?,?,?,?,?)", (bucket, minutes, now, used, reset))
        return len(kept)

    def usage_samples(self, since=None) -> list:
        """Every sample taken at or after `since` (seconds), the oldest first; empty with no file."""
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute(
                "SELECT %s FROM usage_samples WHERE at >= ? ORDER BY at" % ", ".join(_SAMPLE_COLUMNS),
                (float(since or 0),)).fetchall()
        return [dict(row) for row in rows]


def _not_this_one(*_arguments, **_keywords):
    raise StateError("the capability may not write the analytics")


class AnalyticsHandle:
    """What a capability's code is given of the analytics (state.Scoped's `analytics`): the files read so far for
    usage_analytics, and two writes - each only while the runtime has the writer on: a pass's numbers, usage_analytics'
    alone; and a meter reading's samples, the meter's alone and only while usage_analytics stands on too (`armed`), so
    the meter by itself keeps writing only its last reading. Held in a closure, as the Scoped view is."""
    __slots__ = ("capability", "_calls")

    def __init__(self, state, capability, on, armed=None):
        self.capability = capability

        def standing():
            return on is not None and on() is True

        def ingest(*arguments, **keywords):
            if capability != CAPABILITY or not standing():
                raise StateError("the capability may not write the analytics now")
            return state.ingest_file(*arguments, **keywords)

        def sample(windows, **keywords):
            if capability != METER or not standing() or armed is None or armed(CAPABILITY) is not True:
                raise StateError("the meter may not keep samples now")
            return state.add_samples(windows, **keywords)
        self._calls = {
            "on": standing,
            "files": state.token_files if capability == CAPABILITY else (lambda: {}),
            "ingest": ingest if capability == CAPABILITY else _not_this_one,
            "sample": sample if capability == METER else _not_this_one,
        }

    def __getattr__(self, name):
        calls = object.__getattribute__(self, "_calls")
        if name in calls:
            return calls[name]
        raise AttributeError(name)
