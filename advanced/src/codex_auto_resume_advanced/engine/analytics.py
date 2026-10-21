# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Usage and token analytics (v0.6.19; plans/v0619-design/D-analytics.md): how many tokens each project used a day,
and at what pace a usage window fills - shown on the Advanced features page, never acted on.

At P8, at most every INGEST_EVERY and only as an errand - the last thing a tick does, after every send's claim - it
reads what the watched Codex homes' rollouts added since the last pass (codex/tokens.py): at most FILE_BYTES of one file
and PASS_BYTES in all, and no longer than PASS_SECONDS, newest first, so the first pass over a long history takes
several ticks. What it read goes into token_days and token_files (state/analytics.py) - numbers by local day, under the
conversation's project key: core's own (codex/history.project_key - Codex's project id, else the folder), cut to 16 hex
digits, else the digest of the folder the rollout's first line names, else none ("other"). A Pause stops it: core
does not ask P8 then. A pass that raises costs itself alone (runtime._Errands).

Which source (the design's "Sources, in order"):
1. an official per-conversation token read in Codex's app-server schema - none: the 0.163 survey listed none, and MTOK
   records whether one appears; until a pass of MTOK names one, nothing here asks Codex anything;
2. the rollouts, as above - while MTOK has passed or is not measured yet (then the statement warns, K6);
3. `threads.tokens_used`, the conversation's lifetime total (core's codex/history.task_facts) - the narrower route
   where MTOK FAILED on the Codex in force: no rollout is read, and the card shows lifetime totals alone, read when the
   Dashboard asks (control/analytics.py). Source 3 also fills in, on the card, a conversation the rollouts gave nothing
   for.

The pace (`pace`) is the meter's: each reading the meter makes while this stands on is kept as a sample
(engine/usage.py, state usage_samples). It reads nothing more of Codex.

Nothing about recovery changes: no gate, dispatch or plug answer reads any of it (E11), nothing is sent to Codex, and
nothing leaves the PC.
"""
from __future__ import annotations

import time

from codex_auto_resume.domain.plug import DEFER

from ..codex import tokens
from ..vocabulary import Measurement, OptionKey

CAPABILITY = "usage_analytics"
# How often a pass may run, in seconds, and how long one may take.
INGEST_EVERY = 600
PASS_SECONDS = 2.0
# The days the card may show, the default first offered; the journal keeps 90 (state/journal.TOKENS_MAX_AGE).
DAYS = (7, 30, 90)
DEFAULT_DAYS = 7
# The pace: the samples of the last PACE_SECONDS of the current window, at least PACE_SAMPLES over at least
# PACE_SPAN seconds, with a rising slope.
PACE_SECONDS = 3600
PACE_SAMPLES = 3
PACE_SPAN = 900
# Its journal words.
INGESTED, CAPPED, UNREADABLE = "ingested", "capped", "unreadable"


def route(verdict) -> str:
    """Which source the analytics read on the Codex in force, from MTOK's verdict there: the rollouts per day
    ("per_day") while it passed or is unmeasured, the lifetime totals alone ("lifetime") where it failed."""
    return "lifetime" if verdict == "fail" else "per_day"


def pace(samples, row, now) -> dict:
    """The pace of one usage window - `row`, the meter's last reading of it (bucket, minutes, used_percent, reset_at)
    - from `samples` (usage_samples rows): its share now, the change over the last hour, and when it would be full at
    this pace (`eta`), given only with PACE_SAMPLES samples over PACE_SPAN at least in the last PACE_SECONDS since its
    last reset, a rising least-squares slope, and an answer before the window resets (never a promise: the card says
    "around", beside the reset). Pure."""
    used, reset = row.get("used_percent"), row.get("reset_at")
    found = {"bucket": row.get("bucket"), "minutes": row.get("minutes"), "used": used, "reset_at": reset,
             "change_hour": None, "eta": None, "enough": False}
    start = now - PACE_SECONDS
    if type(reset) is int and type(row.get("minutes")) is int:
        start = max(start, reset - row["minutes"] * 60)          # this window's samples alone, after its last reset
    points = sorted((sample["at"], float(sample["used_percent"])) for sample in samples
                    if sample.get("bucket") == row.get("bucket") and sample.get("minutes") == row.get("minutes")
                    and start <= sample.get("at", 0) <= now
                    and (reset is None or sample.get("reset_at") in (None, reset)))
    if points and isinstance(used, (int, float)):
        found["change_hour"] = round(float(used) - points[0][1], 1)
    if len(points) < PACE_SAMPLES or points[-1][0] - points[0][0] < PACE_SPAN:
        return found
    found["enough"] = True
    count = len(points)
    mean_t = sum(at for at, _ in points) / count
    mean_u = sum(share for _, share in points) / count
    spread = sum((at - mean_t) ** 2 for at, _ in points)
    if spread <= 0:
        return found
    slope = sum((at - mean_t) * (share - mean_u) for at, share in points) / spread    # percent a second
    if slope <= 0 or not isinstance(used, (int, float)):
        return found
    eta = now + max(0.0, 100.0 - float(used)) / slope
    if type(reset) is int and eta >= reset:
        return found                                              # full only after it resets: no estimate
    found["eta"] = int(eta)
    return found


class _Errand:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def run(self, guard):
        return self.code.ingest()


class UsageAnalytics:
    """usage_analytics' code: its P8 errand, a pass over the rollouts. `homes`, `source` and `clock` are seams a test
    fills: the Codex homes to read (codex/tokens.watched_homes' shape), core's reader of one home for its project key
    (`source(home)` with `project_key(thread)`), and the clock a pass measures its own time by."""
    __slots__ = ("paths", "_scoped", "_homes", "_source", "_clock", "_local", "_looked")

    def __init__(self, paths, *, homes=None, source=None, clock=time.monotonic, local=time.localtime):
        self.paths = paths
        self._scoped = None
        self._homes = homes
        self._source = source
        self._clock = clock
        self._local = local
        self._looked = None

    def bind(self, scoped):
        self._scoped = scoped

    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            now = scoped.now()
            if self._looked is not None and 0 <= now - self._looked < INGEST_EVERY:
                return DEFER
            last = scoped.stamped(OptionKey.LAST_INGEST)
            if type(last) is int and 0 <= now - last < INGEST_EVERY:
                return DEFER
        except Exception:
            return DEFER
        return _Errand(self)

    def _watched(self) -> list:
        if self._homes is not None:
            return list(self._homes())
        return tokens.watched_homes(self.paths)

    def _project(self, home, thread, fallback):
        """The conversation's project key: core's (its project id, else its folder), cut to 16 hex digits, else the
        digest of the folder its rollout names, else None."""
        try:
            if self._source is not None:
                source = self._source(home)
            else:
                from codex_auto_resume.codex import LocalSource
                source = LocalSource(home)
            key = source.project_key(thread)
        except Exception:
            key = None
        return key[:16] if isinstance(key, str) and len(key) >= 16 else fallback

    def ingest(self):
        scoped = self._scoped
        handle = scoped.analytics
        if not handle.on():
            return None
        now = scoped.now()
        self._looked = now
        try:
            failed = scoped.failed(Measurement.MTOK)
        except Exception:
            failed = False
        if failed:
            # The narrower route (MTOK failed): no rollout is read; the card shows the lifetime totals alone.
            scoped.stamp(OptionKey.LAST_INGEST, max(1, int(now)))
            return None
        started = self._clock()
        budget = tokens.PASS_BYTES
        known = handle.files()
        projects = {}
        capped = unreadable = ingested = False
        for rollout in tokens.rollouts(self._watched(), now):
            row = known.get(rollout.key)
            if tokens.unchanged(rollout, row):
                continue
            if budget <= 0 or self._clock() - started >= PASS_SECONDS:
                capped = True
                break
            read = tokens.read(rollout, row, budget, local=self._local)
            budget -= read.consumed
            if read.outcome == tokens.UNREADABLE or read.thread_id is None:
                unreadable = True                      # tried again once it changes, or at the next pass
                continue
            if read.outcome == tokens.CAPPED:
                capped = True
            key = projects.get(read.thread_id)
            if key is None and read.days:
                key = projects[read.thread_id] = self._project(rollout.home, read.thread_id, read.project_key)
            try:
                handle.ingest(rollout.key, read.thread_id, size=read.size, offset=read.offset,
                              mtime_ns=read.mtime_ns, days=read.days, project_key=key, at=now)
            except Exception:
                unreadable = True
                continue
            ingested = ingested or bool(read.days)
        scoped.stamp(OptionKey.LAST_INGEST, max(1, int(now)))
        for flag, code in ((ingested, INGESTED), (capped, CAPPED), (unreadable, UNREADABLE)):
            if flag:
                self._count(code)
        return None

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass


def make(paths):
    return UsageAnalytics(paths)
