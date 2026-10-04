# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Failures the standard edition never recovers alone, taken up: the advanced edition's answers at P17
and P3 (v0.6.13, stage 3b).

Core puts such a failure to the plug at P17 only once it passed every check core makes of one, and
only with the answers core would carry out for it (`takes`, failures.admits: a tagged code of Codex's
that names no decision, never a 403, never a code without a status or a message alone). Taken up, it
is a core record of its true kind, which waits core's own waits and comes back at known_failure, where
the capability that took it up - the runtime holds it to that one, and to the very word (runtime.py) -
answers that word again, or DEFER, and core ends it unsent. Every send is the ordinary continuation,
with its marker, through core's one claim, which pays a unit of the capability's.

    StructuredRules   the rules a person wrote for Codex's error codes: a failure nothing classified
                      whose code a rule names is paced as the temporary kind the rule says (AS_*)
    UnknownFailureBudget  a failure nothing classified, on a budget of its own (ADMIT), each one it
                      takes up leaving a sample: Codex's code, a status, the error's form, the items
                      the turn left, its times - never a word
    CodexGaveUp       Codex giving up after its own retries (responseTooManyFailedAttempts) on a
                      server error or none, taken up twice a task at most (ADMIT); on a 429 the
                      standard edition retries it already, and core offers nothing else

A capability here never reads a word of an error, and core never hands it one.
"""
from __future__ import annotations

from codex_auto_resume import failures
from codex_auto_resume.domain.plug import DEFER, PACED_AS, Alternative

from ..codex import inuse
from ..vocabulary import OptionKey

KNOWN_FAILURE = "known_failure"
# The word that paces a failure as each temporary kind (domain/plug.PACED_AS, the other way round).
AS_FOR = {kind: word for word, kind in PACED_AS.items()}


def matching(rules, code, status):
    """The rule a failure with `code` and `status` matches: the lowest-numbered that names `code`
    exactly and, where it has a range, holds `status`. Never one whose code the product has come to
    classify since: it no longer applies."""
    if not isinstance(code, str) or code in failures.CODES:
        return None
    for rule in sorted(rules, key=lambda found: found["rule_id"]):
        if rule["tag"] != code or rule.get("known"):
            continue
        low, high = rule["status_from"], rule["status_to"]
        if low is None or (type(status) is int and low <= status <= high):
            return rule
    return None


class _Taking:
    """What the capabilities here share: their view of the state (state.Scoped), given by `bind`."""
    __slots__ = ("paths", "_scoped")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None

    def bind(self, scoped):
        self._scoped = scoped


class StructuredRules(_Taking):
    """Rules for Codex's error codes: P17 and P3, and what it keeps when core goes on (a hit)."""
    __slots__ = ()

    def _rules(self):
        """The rules as they stand; none where the state cannot be read, so nothing is taken up then
        and the failure is put to it again a minute on."""
        try:
            return self._scoped.rules() if self._scoped is not None else []
        except Exception:
            return []

    def admission(self, failure):
        """The word of the rule this failure matches - only for one nothing classified - or DEFER."""
        if failure.get("category") != failures.UNKNOWN:
            return DEFER
        rule = matching(self._rules(), failure.get("code"), failure.get("status"))
        return DEFER if rule is None else AS_FOR.get(rule["category"], DEFER)

    def rule_for(self, facts, answer):
        """The rule the answer rests on, which the runtime remembers with it."""
        rule = matching(self._rules(), facts.get("code"), facts.get("status"))
        return rule["rule_id"] if rule is not None and AS_FOR.get(rule["category"]) == answer else None

    def gate(self, name, record, facts):
        """At known_failure, the word of the rule that took the record up, while that rule is there
        and still applies - removing it ends what it took up. A state it cannot read holds the record:
        it never ends one for that."""
        if name != KNOWN_FAILURE or record.get("category") != failures.UNKNOWN or self._scoped is None:
            return DEFER
        try:
            row = self._scoped.admission(record.get("interruption_id"))
            rules = self._scoped.rules()
        except Exception:
            return Alternative.HOLD
        if row is None:
            return DEFER
        rule = next((found for found in rules if found["rule_id"] == row["rule_id"]), None)
        if rule is None or rule.get("known"):
            return DEFER
        return AS_FOR.get(rule["category"], DEFER)

    def taken(self, point, answer, *arguments):
        """The rule's hit, counted the first time core goes on with what it took up."""
        return {"code": "matched"}


def make_structured_rules(paths) -> StructuredRules:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return StructuredRules(paths)


# How many tries a task of failures nobody classified gets: the person's choice, one by default.
ATTEMPTS = (1, 2, 3)
DEFAULT_ATTEMPTS = 1


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class UnknownFailureBudget(_Taking):
    """Retry failures it cannot name: P17 and P3, and the sample it keeps the first time core goes on
    with what it took up. Core's own no-progress and chain budgets still bind; the tries a task gets
    are counted on the task it continues (`chain`), which is the record whose continuation failed."""
    __slots__ = ()

    def _attempts(self) -> int:
        try:
            return self._scoped.options().get(OptionKey.ATTEMPTS, DEFAULT_ATTEMPTS)
        except Exception:
            return DEFAULT_ATTEMPTS

    def admission(self, failure):
        """ADMIT for a failure nothing classified - core offers it only for a code of Codex's that
        names no decision - while its task has tries left; rules come first (the registry's order)."""
        if failure.get("category") != failures.UNKNOWN:
            return DEFER
        chain = failure.get("chain")
        if chain is not None:
            attempts = chain.get("recovery_attempts") if isinstance(chain, dict) else None
            if type(attempts) is not int or attempts >= self._attempts():
                return DEFER
        return Alternative.ADMIT

    def gate(self, name, record, facts):
        """At known_failure, ADMIT again for what it took up (the runtime holds it to its own)."""
        if name != KNOWN_FAILURE or record.get("category") != failures.UNKNOWN:
            return DEFER
        return Alternative.ADMIT

    def taken(self, point, answer, *arguments):
        """The sample, the first time core goes on: the shape its admission kept, the items the
        failed turn left - read from the Codex home the watcher told of, none where it told nothing -
        and how long the turn ran."""
        record = arguments[1] if len(arguments) > 1 and isinstance(arguments[1], dict) else {}
        row = self._scoped.admission(record.get("interruption_id")) if self._scoped is not None else None
        if row is None:
            return {"code": "sampled"}
        started, completed = record.get("started_at"), record.get("completed_at")
        duration = completed - started if _number(started) and _number(completed) and completed >= started else None
        return {"code": "sampled", "sample": {
            "code": row["tag"], "status": row["status"], "form": row["form"],
            "has_message": row["has_words"] == 1, "items": self._items(record), "duration": duration}}

    def _items(self, record):
        """How many items of each kind the failed turn left (codex/history.turn_item_counts), counts
        only - or None where the watcher told this process no Codex home, or it cannot be read."""
        told = inuse.told(self.paths)
        if told is None:
            return None
        try:
            from codex_auto_resume.codex import LocalSource
            return LocalSource(told[1]).turn_item_counts(record.get("thread_id"), record.get("turn_id"))
        except Exception:
            return None


def make_unknown_failure_budget(paths) -> UnknownFailureBudget:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return UnknownFailureBudget(paths)


GAVE_UP = "terminal_failure"
# How many continuations a task of Codex giving up gets at most.
GAVE_UP_TRIES = 2


class CodexGaveUp(_Taking):
    """Retry when Codex gave up: P17 and P3. Core offers ADMIT for `terminal_failure` only when Codex's
    code is responseTooManyFailedAttempts with a server error's status or none (failures.admits), so
    rollback, sandbox and not-steerable failures never reach it; and it waits ten minutes, then 15."""
    __slots__ = ()

    def admission(self, failure):
        """ADMIT while the task it continues has had fewer than two continuations."""
        if failure.get("category") != GAVE_UP:
            return DEFER
        chain = failure.get("chain")
        if chain is not None:
            attempts = chain.get("recovery_attempts") if isinstance(chain, dict) else None
            if type(attempts) is not int or attempts >= GAVE_UP_TRIES:
                return DEFER
        return Alternative.ADMIT

    def gate(self, name, record, facts):
        """At known_failure, ADMIT again for what it took up (the runtime holds it to its own)."""
        if name != KNOWN_FAILURE or record.get("category") != GAVE_UP:
            return DEFER
        return Alternative.ADMIT


def make_codex_gave_up(paths) -> CodexGaveUp:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return CodexGaveUp(paths)
