# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Use a reset credit when the limit a person picked is reached (v0.6.14): reset_credit, at P8 and P7.

Codex gives some accounts reset credits: one spent resets a usage window that is full, and a person can
spend one in Codex's /usage. The standard edition never spends one and never reads how many there are
(B3, B4, B10). With this on, a person picks an occasion in the Dashboard - "the next 5-hour limit", "the
3rd from now", "the weekly limit" - and when that window fills (engine/resetwatch.py), and only while a
recovery waits for usage (the owner's rule), the watcher's errand at P8 spends one:

1. a fresh, detailed usage read: the window it waited for still open and full, or the rule lapses;
2. how many credits there are, and when the soonest expires, both readable - or it asks the person, and
   spends nothing (the owner's rule); none left, and it is done;
3. two spent in a day and seven in a week at most, and never two for one filling of a window;
4. on its own only where MR passed for the Codex in force and the person did not choose Ask me first -
   otherwise the Dashboard's Use a reset credit now spends it, at a click (control/resets.py), and that
   too only while a recovery waits for usage;
5. the spend written, with a key of its own, before Codex is asked (A5's analogue);
6. the one request written inside core's errand guard, so a Pause, Observe only or quiet hours that
   committed first stop it; its answer waited for outside;
7. what came of it kept: reset - the window closes at once, and for fifteen minutes the waiting
   recoveries are looked at early (P7, EARLY) -, nothing to reset, no credit, or unknown.

An outcome that is not known ten minutes on - no answer in time, a crash between the write and the answer,
an error from Codex but its having no such method (-32601) - is asked once more with the same key, where
MR's retry passed (alreadyRedeemed spends nothing twice);
otherwise, or if that is unknown too, the rule ends unknown and the capability turns itself off, as a send
it paid for gone submission_unknown turns one off (K7) - never a second key for one occasion. No credit id
is ever held: Codex picks the credit (`creditId` left out).

It sends nothing to Codex but that one request, and never a turn to open or keep a window (the plan's
exclusion).
"""
from __future__ import annotations

import uuid

from codex_auto_resume import failures, ladder, machine
from codex_auto_resume.codex.errors import AdapterError
from codex_auto_resume.domain.plug import DEFER, Alternative

from ..codex import credits
from ..vocabulary import Measurement, OffReason, RuleReason, RuleState, SpendOutcome
from . import resetwatch
from .resetwatch import Watch

CAPABILITY = "reset_credit"
# The bounds: one spend for each filling of a window (the table's own), two in a day, seven in a week.
DAILY, WEEKLY = 2, 7
DAY, WEEK = 86400, 7 * 86400
# A spend whose outcome is not known this long after it was written is unknown.
UNKNOWN_AFTER = 600
# How long a person's Use now stands, and how long after a reset waiting recoveries are looked at early.
USE_NOW = 900
EARLY_FOR = 900
# What a due rule waits for a person for: their click (Ask me first, or MR not passed), or Codex's /usage, where this
# Codex has no way to spend one from here. It reads nothing more for its occasion.
WAITS_FOR_A_PERSON = (RuleReason.ASK_FIRST, RuleReason.NO_METHOD)
# The outcomes that spent a credit, or may have.
SPENDING = (SpendOutcome.RESET, SpendOutcome.ALREADY_REDEEMED, SpendOutcome.UNKNOWN, None)
# Codex's error code for a method it does not have: the one error that says nothing was spent (no_method).
# Any other error it answers with says nothing of what it spent, and is an unknown answer.
METHOD_NOT_FOUND = -32601
# What each of Codex's outcomes ends a rule with, and the word its journal counts.
OUTCOME_REASONS = {SpendOutcome.RESET: RuleReason.SPENT, SpendOutcome.ALREADY_REDEEMED: RuleReason.SPENT,
                   SpendOutcome.NOTHING_TO_RESET: RuleReason.NOTHING_TO_RESET,
                   SpendOutcome.NO_CREDIT: RuleReason.NO_CREDIT}
OUTCOME_CODES = {SpendOutcome.RESET: "spent", SpendOutcome.ALREADY_REDEEMED: "spent",
                 SpendOutcome.NOTHING_TO_RESET: "nothing", SpendOutcome.NO_CREDIT: "no_credit"}


def awaits_usage(view) -> bool:
    """Whether a recovery waits for usage now: a usage-limit record of core's that waits (the owner's
    rule: a credit is spent only for one)."""
    try:
        rows = view.records_in(machine.WAITING)
    except Exception:
        return False
    return any(row.get("category") == failures.USAGE_LIMIT for row in rows)


class _Errand:
    """P8's errand: one look, run by core last in the tick with its guards (domain/plughands.Errand)."""
    __slots__ = ("code", "view")

    def __init__(self, code, view):
        self.code, self.view = code, view

    def run(self, guard):
        return self.code.look(self.view, guard)


class ResetCredit:
    """The capability's code: its hooks at P8 and P7. `bind` gives it its view of the state (state.Scoped:
    the reset rules, windows and spends, writes only while it is on, and which measurements passed)."""
    __slots__ = ("paths", "_scoped", "_open", "_tried")

    def __init__(self, paths, *, session=None):
        self.paths = paths
        self._scoped = None
        self._open = session
        self._tried = {}                     # {rule id: when its spend last read usage}, in this process

    def bind(self, scoped):
        self._scoped = scoped

    # ------------------------------------------------------------------ P7
    def schedule(self, record, due):
        """P7: EARLY for a usage-limited record core holds as waiting for its reset, for fifteen minutes
        after one of this capability's spends reset a window; DEFER for everything else."""
        scoped = self._scoped
        if (scoped is None or not isinstance(record, dict) or record.get("category") != failures.USAGE_LIMIT
                or record.get("state") not in ladder.EARLY_STATES or not isinstance(due, (int, float))):
            return DEFER
        try:
            now = scoped.now()
            if due <= now:
                return DEFER                             # due by core's own schedule: nothing to look early at
            recent = scoped.resets.credit_spends(since=now - EARLY_FOR)
        except Exception:
            return DEFER
        reset = any(spend["outcome"] == SpendOutcome.RESET and spend["finished_at"] is not None
                    and 0 <= now - spend["finished_at"] < EARLY_FOR for spend in recent)
        return Alternative.EARLY if reset else DEFER

    # ------------------------------------------------------------------ P8
    def tick(self, view):
        """P8: an errand, while a rule of this capability waits; DEFER otherwise."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            pending = scoped.resets.reset_rules(capability=CAPABILITY)
        except Exception:
            return DEFER
        return _Errand(self, view) if pending else DEFER

    def look(self, view, guard):
        """The errand: count, then act on every rule that is due. What it asks to be done of the runtime -
        a trip - it returns ({"trip": reason})."""
        scoped = self._scoped
        handle = scoped.resets
        if not handle.on():
            return None
        session = _Lazy(self._session)
        try:
            watch = Watch(handle, scoped.now, reader=lambda params: session().call(credits.READ, params),
                          early=not scoped.failed(Measurement.MU), light=scoped.passed(Measurement.MU),
                          keep_credits=True)
            looked = watch.step(view)
            now = handle.now()
            self._tried = {rule: at for rule, at in self._tried.items() if 0 <= now - at < resetwatch.READ_SPACING}
            trip = self._spend_unknown(handle, session, guard, watch)
            for rule in handle.reset_rules(capability=CAPABILITY):
                found = self._consider(rule, looked, handle, session, guard, watch, view)
                trip = trip or found
            return {"trip": trip} if trip else None
        finally:
            session.close()

    # ------------------------------------------------------------------ one rule
    def _consider(self, rule, looked, handle, session, guard, watch, view):
        family = (rule["bucket"], rule["minutes"])
        row = looked["rows"].get(family)
        now = handle.now()
        for event in looked["events"].get(family, ()):
            if event in ("gap", "gone"):
                self._count({"gap": "gap", "gone": "gone"}[event])
        if row is None or rule["state"] == RuleState.HELD:
            return None
        if rule["ordinal"] == 0:                       # a person's Use now
            if now - rule["created_at"] >= USE_NOW or not (row["open_reset_at"] and row["open_full"]):
                return self._lapse(rule, row, handle)
            if not awaits_usage(view):                   # a click spends only while a recovery waits too
                self._ready(handle, rule, RuleReason.NOTHING_WAITING)
                return None
            return self._spend(rule, row, handle, session, guard, watch, looked, clicked=True)
        if rule["state"] == RuleState.COUNTING:
            if not resetwatch.due(rule, row):
                return None
            self._count("hit")
            handle.change_rule(rule["rule_id"], expect=RuleState.COUNTING, state=RuleState.READY, due_at=now,
                               reason=None)
            rule = dict(rule, state=RuleState.READY, due_at=now)
        if not (row["open_reset_at"] and row["open_full"]):
            return self._lapse(rule, row, handle)
        if rule["reason"] in WAITS_FOR_A_PERSON:
            return None                                  # a click spends it (control/resets.py), or the window resets
        if not awaits_usage(view):
            self._ready(handle, rule, RuleReason.NOTHING_WAITING)
            return None
        return self._spend(rule, row, handle, session, guard, watch, looked, clicked=False)

    def _ready(self, handle, rule, reason) -> None:
        if rule["reason"] != reason:
            handle.change_rule(rule["rule_id"], expect=RuleState.READY, reason=reason)
            if reason == RuleReason.ASK_FIRST:
                self._count("asked")

    def _lapse(self, rule, row, handle):
        """The window reset before anything was spent: once ends it, every time counts again."""
        self._count("lapsed")
        self._finished(rule, row, handle, RuleReason.LAPSED)
        return None

    def _finished(self, rule, row, handle, reason) -> None:
        """A rule that fired: done - or, every time, counting the next fill of its window from now."""
        if rule["repeat"] and rule["ordinal"] > 0:
            handle.change_rule(rule["rule_id"], state=RuleState.COUNTING, reason=None, base=row["hits"], ordinal=1,
                               adopted_at=handle.now(), due_at=None)
        else:
            handle.end_rule(rule["rule_id"], RuleState.DONE, reason)

    def _spend(self, rule, row, handle, session, guard, watch, looked, *, clicked):
        """Steps 1 to 7 for one due rule (the module's docstring). Returns a trip's reason, or None. A rule that
        could not spend at its last look - a count it could not read, a bound, a guard that refused, an answer
        awaited - reads usage again five minutes on, not before: one fresh reading a look serves every rule, and
        each rule asks for one at most once in five minutes."""
        now = handle.now()
        if "detailed" not in looked:
            last = self._tried.get(rule["rule_id"])
            if last is not None and 0 <= now - last < resetwatch.READ_SPACING:
                return None
            looked["detailed"] = watch.read(credits.DETAILED)          # (1) fresh and detailed
        self._tried[rule["rule_id"]] = now
        reading = looked["detailed"]
        if reading is None:
            self._ready(handle, rule, RuleReason.COUNT_UNKNOWN)
            return None
        handle.set_reading(credits=reading["credits"], expiry_known=int(reading["expiry_known"]),
                           nearest_expiry=reading["nearest_expiry"], read_at=handle.now())
        window = resetwatch.family_window(reading["windows"], (rule["bucket"], rule["minutes"]))
        if window is None or window["used_percent"] < 100 or window["reset_at"] is None:
            return self._lapse(rule, row, handle)
        if reading["credits"] is None:                                  # (2) the count and the expiry
            self._ready(handle, rule, RuleReason.COUNT_UNKNOWN)
            return None
        if not reading["expiry_known"]:
            self._ready(handle, rule, RuleReason.EXPIRY_UNKNOWN)
            return None
        if reading["credits"] == 0:
            self._count("no_credit")
            self._finished(rule, row, handle, RuleReason.NO_CREDIT)
            return None
        now = handle.now()
        recent = handle.credit_spends(since=now - WEEK)
        mine = next((spend for spend in recent if (spend["bucket"], spend["minutes"], spend["occasion"])
                     == (rule["bucket"], rule["minutes"], row["hits"])), None)
        if mine is not None:                                            # one for each filling of a window
            return self._settled(rule, row, handle, mine["outcome"])
        spent = [spend for spend in recent if spend["outcome"] in SPENDING]
        if (len([spend for spend in spent if now - spend["created_at"] < DAY]) >= DAILY
                or len(spent) >= WEEKLY):                               # (3) the bounds
            self._ready(handle, rule, RuleReason.BOUND)
            return None
        if not clicked and (rule["ask_first"] or not self._scoped.passed(Measurement.MR)):
            self._ready(handle, rule, RuleReason.ASK_FIRST)             # (4) asked, or measured
            return None
        key = str(uuid.uuid4())                                          # (5) written before it is asked
        spend = handle.add_credit_spend(rule["rule_id"], rule["bucket"], rule["minutes"], row["hits"], key)
        if spend is None:
            return None
        return self._ask(rule, row, handle, session, guard, watch, spend, key)

    def _settled(self, rule, row, handle, outcome):
        """A rule whose occasion has a spend already: waiting for that spend's answer, or finished by it."""
        if outcome is None:
            return None                                                 # its answer is awaited (`_spend_unknown`)
        if outcome == SpendOutcome.UNKNOWN:
            handle.end_rule(rule["rule_id"], RuleState.DONE, RuleReason.UNKNOWN)
        else:
            self._finished(rule, row, handle, OUTCOME_REASONS[outcome])
        return None

    def _ask(self, rule, row, handle, session, guard, watch, spend, key, retry=False):
        """(6) and (7): the one request inside the guard, its answer outside it."""
        try:
            opened = session()
        except Exception:
            opened = None
        sequence = None
        if opened is not None:
            try:
                with guard() as permitted:
                    if permitted is True:
                        sequence = opened.submit(credits.CONSUME, {"idempotencyKey": key})
            except AdapterError:
                sequence = None
        if sequence is None:
            if not retry:
                handle.drop_credit_spend(spend)                          # nothing was asked: next look tries again
            return None
        try:
            outcome = credits.outcome(opened.receive(credits.CONSUME, sequence))
        except AdapterError as exc:
            if getattr(exc, "code", None) != METHOD_NOT_FOUND:
                # No answer, or an error that says nothing of what was spent: unknown, looked at again ten minutes
                # on - the same key once more where MR passed, else the rule ends unknown - never a second key.
                return None
            # Codex answered that it has no such method: nothing was spent, and none is asked again.
            if not handle.drop_credit_spend(spend):
                handle.finish_credit_spend(spend, SpendOutcome.NOTHING_TO_RESET)
            self._ready(handle, rule, RuleReason.NO_METHOD)
            return None
        if outcome == SpendOutcome.UNKNOWN:
            return None
        handle.finish_credit_spend(spend, outcome)
        if outcome in (SpendOutcome.RESET, SpendOutcome.ALREADY_REDEEMED):
            watch.own_reset((rule["bucket"], rule["minutes"]), handle.now())
        self._count(OUTCOME_CODES[outcome])
        self._finished(rule, row, handle, OUTCOME_REASONS[outcome])
        return None

    def _spend_unknown(self, handle, session, guard, watch):
        """Every spend with no outcome ten minutes on: asked once more with its key where MR passed, else -
        or a second time unknown - its rule ends unknown and the capability turns itself off."""
        now = handle.now()
        for spend in handle.credit_spends(since=now - WEEK):
            if spend["outcome"] is not None or now - spend["created_at"] < UNKNOWN_AFTER * spend["tries"]:
                continue
            rule = handle.reset_rule(spend["rule_id"])
            if spend["tries"] == 1 and self._scoped.passed(Measurement.MR) and rule is not None \
                    and handle.retry_credit_spend(spend["spend_id"]):
                row = handle.windows().get((spend["bucket"], spend["minutes"])) or resetwatch.blank(
                    spend["bucket"], spend["minutes"])
                self._ask(rule, row, handle, session, guard, watch, spend["spend_id"], spend["attempt_id"], retry=True)
                continue
            handle.finish_credit_spend(spend["spend_id"], SpendOutcome.UNKNOWN)
            if rule is not None and rule["state"] in (RuleState.COUNTING, RuleState.READY, RuleState.HELD):
                handle.end_rule(rule["rule_id"], RuleState.DONE, RuleReason.UNKNOWN)
            self._count("unknown")
            return OffReason.SUBMISSION_UNKNOWN
        return None

    # ------------------------------------------------------------------ helpers
    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass

    def _session(self):
        if self._open is not None:
            return self._open()
        from ..codex import inuse
        from ..codex.protocol import Session
        return Session(inuse.backend(self.paths), capability=CAPABILITY)


class _Lazy:
    """One session for one look, opened the first time it is needed and closed at the look's end."""
    __slots__ = ("_make", "_session")

    def __init__(self, make):
        self._make, self._session = make, None

    def __call__(self):
        if self._session is None:
            made = self._make()
            made.__enter__()
            self._session = made
        return self._session

    def close(self):
        if self._session is not None:
            try:
                self._session.__exit__(None, None, None)
            except Exception:
                pass
            self._session = None


def make(paths) -> ResetCredit:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return ResetCredit(paths)
