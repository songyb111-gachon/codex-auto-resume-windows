# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Counting the usage windows' resets and fills (v0.6.14): what "the Nth next 5-hour limit" is, across restarts.

A person picks an occasion - a window family, a bucket and a length in minutes, and which of its next
resets or fills (an ordinal) - and the reset actions act at it: a reset credit when the window fills,
their own message when it resets (engine/credits.py, engine/resetmessage.py). Codex says nothing of a
window's history, only how full each window is now and when it resets, so this counts. One row a family
(state/resets.py, `windows`), kept while a pending rule names it, and on each successful reading at time t
(`advance`, pure):

1. Closed by time: a window open until R is closed at t >= R + 60 - one reset more.
2. Replaced early: its reset time is now another, by more than TOL, or none - a credit, ours or one a
   person redeemed in Codex's /usage, ended it early - one reset more, and the new one may open (3).
   Only where MU did not fail on the Codex in force: the narrowed route counts a window's end by time
   (1) and by our own reset (5) alone.
3. Opened: nothing open, used above 0 % and a reset ahead that is not the one last closed - opened. An
   idle window (0 %) opens nothing, whatever reset time Codex shows for it.
4. Filled: open, at 100 % or more, and not filled already - one fill more.
5. Our own credit's `reset` outcome closes the open window at once (`closed`), so (2) never counts it
   twice.

Both counts only ever grow. A rule counts from its adoption - the errand's own fresh reading after it was
made sets its base - so a window already full when a rule is made is not its next limit, and one open then
is its first reset. A reading that failed, or whose windows fail core's allowlist, changes nothing (E1).
Two successful readings of a family further apart than its length could hide an occasion whole: its rules
are held (count_gap) until a person says go on or cancel, never a guess (E1, E2). A family missing from
three successful readings in a row is gone (window_gone): Codex changed its windows, and a new length is a
new family.

Readings (`Watch.step`): core's own last reading is free (the view's `last_usage`); this edition's own is
one finite session for the capability that asks, at most one in five minutes for both, when a rule waits
to be adopted, a minute after an open window's reset, when core has noticed a usage limit since the last
look, and every fifteen minutes while any rule is pending. None while nothing is pending, and none while
recovery is paused - P8 is not asked then.
"""
from __future__ import annotations

from codex_auto_resume import failures, machine

from ..codex import credits
from ..state.resets import CREDIT, StateError
from ..vocabulary import RuleReason, RuleState

# How far a window's reset time may move before it is another window: ten minutes, until MU has measured
# how still Codex keeps it (the harness keeps no number, so this stays).
TOL = 600
# A window open until R is closed by time this long after R.
CLOSE_AFTER = 60
# This edition's own readings: at most one in five minutes, every fifteen while a rule is pending.
READ_SPACING = 300
POLL = 900
# Successful readings in a row a family may be missing from before it is gone.
MISSES = 3


def blank(bucket, minutes) -> dict:
    """A family nothing has been counted of yet."""
    return {"bucket": bucket, "minutes": minutes, "open_reset_at": None, "open_full": False,
            "last_closed_at": None, "resets": 0, "hits": 0, "seen_at": None, "misses": 0}


def by_time(row, now) -> tuple:
    """Step 1 alone, which needs no reading: (row, whether it reset)."""
    opened = row["open_reset_at"]
    if opened is not None and now >= opened + CLOSE_AFTER:
        return dict(row, resets=row["resets"] + 1, last_closed_at=opened, open_reset_at=None,
                    open_full=False), True
    return row, False


def closed(row, now) -> dict:
    """Step 5: this edition's own credit reset the open window at `now`."""
    if row["open_reset_at"] is None:
        return row
    return dict(row, resets=row["resets"] + 1, last_closed_at=int(now), open_reset_at=None, open_full=False)


def advance(row, window, now, *, early=True) -> tuple:
    """One successful reading at `now` applied to one family's row: (the row after, the events), each
    event "gap", "reset", "opened", "hit", "missing" or "gone". `window` is the family's window in the
    reading - core's kept form - or None where the reading did not show it. `early` is step 2."""
    events = []
    seen = row["seen_at"]
    if seen is not None and now - seen > row["minutes"] * 60:
        events.append("gap")
    row, reset = by_time(row, now)
    if reset:
        events.append("reset")
    if window is None:
        row = dict(row, misses=row["misses"] + 1)
        events.append("gone" if row["misses"] >= MISSES else "missing")
        return row, tuple(events)
    row = dict(row, misses=0, seen_at=now)
    used, reset_at = window["used_percent"], window["reset_at"]
    opened = row["open_reset_at"]
    if early and opened is not None and (reset_at is None or abs(reset_at - opened) > TOL):
        row = dict(row, resets=row["resets"] + 1, last_closed_at=int(now), open_reset_at=None, open_full=False)
        events.append("reset")
    if (row["open_reset_at"] is None and used > 0 and reset_at is not None and reset_at > now
            and reset_at > (row["last_closed_at"] or 0) + TOL):
        row = dict(row, open_reset_at=reset_at, open_full=False)
        events.append("opened")
    if row["open_reset_at"] is not None and used >= 100 and not row["open_full"]:
        row = dict(row, open_full=True, hits=row["hits"] + 1)
        events.append("hit")
    return row, tuple(events)


def family_window(windows, family):
    """The family's window in a reading's windows - the fullest, should a bucket list one length twice -
    or None."""
    found = [window for window in windows or () if (window["bucket"], window["window_minutes"]) == family]
    return max(found, key=lambda window: window["used_percent"]) if found else None


def count(rule, row) -> int:
    """What a rule counts on its family's row: fills for a credit, resets for a message."""
    return row["hits"] if rule["capability"] == CREDIT else row["resets"]


def due(rule, row) -> bool:
    """Whether a rule's occasion has come: adopted, and its family's count past its base by its ordinal."""
    return (rule["state"] == RuleState.COUNTING and rule["base"] is not None and row is not None
            and count(rule, row) >= rule["base"] + rule["ordinal"])


class Watch:
    """The runner: the windows table kept, readings taken and applied, rules adopted and held.

    `state` is the advanced state; `reader` makes this edition's own reading (a callable given the read's
    params, answering Codex's reply or raising); `early` whether step 2 holds (MU not failed); `light`
    whether a poll may leave the credits' details out (MU passed); `keep_credits` whether the count and
    the soonest expiry may be written (reset_credit on, B10)."""

    def __init__(self, state, clock, *, reader=None, early=True, light=False, keep_credits=False):
        self.state, self.clock, self.reader = state, clock, reader
        self.early, self.light, self.keep_credits = early, light, keep_credits

    def rows(self, rules) -> dict:
        """{family: row} for every family a pending rule names, as counted so far."""
        stored = self.state.windows()
        return {family: stored.get(family) or blank(*family)
                for family in {(rule["bucket"], rule["minutes"]) for rule in rules}}

    def by_time(self) -> dict:
        """Step 1 for every family a pending rule names, with no reading: {family: row}. What P2 asks
        first, so a message is due at the very tick its window closes (engine/resetmessage.py)."""
        rules = self.state.reset_rules()
        rows = {family: by_time(row, self.clock())[0] for family, row in self.rows(rules).items()}
        self.state.save_windows(list(rows.values()))
        return rows

    def wanted(self, rules, rows, reading, view, now) -> bool:
        """Whether this edition's own reading is due now (see the module's docstring)."""
        asked = reading.get("asked_at")
        if asked is not None and 0 <= now - asked < READ_SPACING:
            return False
        if any(rule["state"] == RuleState.COUNTING and rule["adopted_at"] is None for rule in rules):
            return True
        for row in rows.values():
            opened = row["open_reset_at"]
            if opened is not None and now >= opened + CLOSE_AFTER and (row["seen_at"] or 0) < opened + CLOSE_AFTER:
                return True
            if row["last_closed_at"] is not None and (row["seen_at"] or 0) < row["last_closed_at"] + CLOSE_AFTER:
                return True
        if self._signal(view, reading) is not None:
            return True
        read = reading.get("read_at")
        return read is None or now - read >= POLL

    @staticmethod
    def _signal(view, reading):
        """The newest usage-limit record core noticed since this edition last looked, or None."""
        try:
            waiting = view.records_in(machine.WAITING) if view is not None else []
        except Exception:
            return None
        newest = max((row["detected_at"] for row in waiting
                      if row.get("category") == failures.USAGE_LIMIT and row.get("detected_at") is not None),
                     default=None)
        since = reading.get("signal_at")
        return newest if newest is not None and (since is None or newest > since) else None

    def read(self, params):
        """This edition's own reading: (Codex's reply parsed, or None for one that failed)."""
        if self.reader is None:
            return None
        try:
            parsed = credits.parse(self.reader(dict(params)))
        except Exception:
            return None
        return parsed if parsed["windows"] is not None else None

    def step(self, view=None, *, now=None, fresh=False) -> dict:
        """One look: the families kept, step 1 by time, core's free reading applied, this edition's own
        taken where it is due - or where `fresh` asks one regardless of anything but the spacing - and
        applied, rules adopted where this look read usage itself, held over a gap or a window gone.
        Returns {"rows": {family: row}, "events": {family: events}, "reading": what this look read
        itself (credits.parse), or None}."""
        now = self.clock() if now is None else now
        rules = self.state.reset_rules()
        if not rules:
            self.state.save_windows([])
            return {"rows": {}, "events": {}, "reading": None}
        rows = self.rows(rules)
        events = {family: [] for family in rows}
        for family, row in list(rows.items()):
            rows[family], reset = by_time(row, now)
            if reset:
                events[family].append("reset")
        reading = self.state.reading()
        core = None
        try:
            core = view.last_usage() if view is not None else None
        except Exception:
            core = None
        if (isinstance(core, tuple) and len(core) == 2 and isinstance(core[0], (int, float))
                and (reading.get("applied_at") is None or core[0] > reading["applied_at"]) and core[0] <= now):
            self._apply(rows, events, core[1], core[0])
            self.state.set_reading(applied_at=core[0])
        own = None
        signal = self._signal(view, reading)
        if self.wanted(rules, rows, reading, view, now) or (fresh and not (
                reading.get("asked_at") is not None and 0 <= now - reading["asked_at"] < READ_SPACING)):
            own = self.read(credits.LIGHT if self.light and not fresh else credits.DETAILED)
            written = {"asked_at": now}
            if signal is not None:
                written["signal_at"] = signal
            if own is not None:
                self._apply(rows, events, own["windows"], now)
                written.update(read_at=now, applied_at=now)
                if self.keep_credits and own["credits"] is not None:
                    written.update(credits=own["credits"], expiry_known=int(own["expiry_known"]),
                                   nearest_expiry=own["nearest_expiry"])
            self.state.set_reading(**written)
        self.state.save_windows(list(rows.values()))
        self._rules(rules, rows, events, adopt=own is not None, now=now)
        return {"rows": rows, "events": events, "reading": own}

    def _apply(self, rows, events, windows, at) -> None:
        for family, row in list(rows.items()):
            rows[family], found = advance(row, family_window(windows, family), at, early=self.early)
            events[family] += [event for event in found if event not in ("missing",)]

    def _rules(self, rules, rows, events, *, adopt, now) -> None:
        """Rules adopted on this look's own reading, and held where their family had a gap or is gone."""
        for rule in rules:
            family = (rule["bucket"], rule["minutes"])
            row, seen = rows.get(family), events.get(family, ())
            if rule["state"] not in (RuleState.COUNTING, RuleState.READY) or row is None:
                continue
            held = "gone" in seen and RuleReason.WINDOW_GONE or "gap" in seen and RuleReason.COUNT_GAP
            try:
                if held and rule["state"] == RuleState.COUNTING:
                    counted = count(rule, row) - rule["base"] if rule["base"] is not None else 0
                    self.state.change_rule(rule["rule_id"], expect=RuleState.COUNTING, state=RuleState.HELD,
                                           reason=held, ordinal=max(1, rule["ordinal"] - max(0, counted)),
                                           base=None, adopted_at=None)
                elif adopt and rule["state"] == RuleState.COUNTING and rule["adopted_at"] is None:
                    self.state.change_rule(rule["rule_id"], expect=RuleState.COUNTING, base=count(rule, row),
                                           adopted_at=now)
            except StateError:
                continue                     # tried again at the next look

    def own_reset(self, family, now) -> None:
        """Step 5, written: this edition's credit reset the family's open window."""
        stored = self.state.windows().get(family)
        if stored is not None:
            self.state.save_windows([closed(stored, now) if key == family else row
                                     for key, row in self.state.windows().items()])
