# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's reset actions (v0.6.14): their rules read, one added, one cancelled, one held over a gap let
go on, and a reset credit used now.

Each is the long-lived bridge's, the Dashboard's alone (surfaces.py), against the generation the page read: a page
that had not seen something turned off is refused, as an arm is. No MCP tool reaches any of them, and core's own
update_settings has no field they could be written through.

A rule is added only while its capability stands on - watched, a rule could neither be adopted nor counted (its
errand is not run, runtime.py) - and every rule of a capability that stands anywhere else is cancelled at the next
sweep, its words with it (arming.py). A message is for one conversation, ten in all and one to a conversation, at
most 2,000 characters - A27's bound - unless Longer reset messages stands on, and then what one continuation can
carry (continuation.PROMPT_LIMIT); it is checked as core checks it before it is sent (validate_prompt). Use a reset
credit now is a person's click: a rule of its own, good for fifteen minutes, which the errand spends at its next
look - with every check of its own but Ask me first - and the watcher is woken for it, as Send now wakes it.
"""
from __future__ import annotations

import secrets

from codex_auto_resume import continuation
from codex_auto_resume.domain import ids

from ..engine import credits as reset_credit
from ..engine.resetmessage import CAPABILITY as MESSAGE, LONG, SHORT_LIMIT
from ..state.schema import BUCKETS
from ..vocabulary import ArmingState, Refusal, RuleState

CREDIT = reset_credit.CAPABILITY
KINDS = {"credit": CREDIT, "message": MESSAGE}
# A week, in minutes: a weekly window is offered once - its next reset - and every shorter one up to nine times.
WEEK = 10080
ORDINALS = range(1, 10)
# The families offered where nothing has been counted yet: Codex's 5-hour and weekly windows.
DEFAULT_FAMILIES = (("codex", 300), ("codex", WEEK))
# What the Dashboard is shown of a rule, and nothing else of its row.
SHOWN = ("rule_id", "capability", "bucket", "minutes", "ordinal", "repeat", "ask_first", "state", "reason", "gate",
         "gate_reason", "created_at", "adopted_at", "due_at", "sent_at", "finished_at", "thread_id")


def _refused(refusal, runtime=None) -> dict:
    found = {"done": False, "refusal": Refusal(refusal)}
    if runtime is not None:
        try:
            found["generation"] = runtime.state.meta()["generation"]
        except Exception:
            pass
    return found


def _stale(runtime, generation) -> bool:
    try:
        return type(generation) is not int or runtime.state.meta()["generation"] != generation
    except Exception:
        return True


def _on(runtime, capability) -> bool:
    return runtime.states(fresh=True).get(capability, ArmingState.OFF) == ArmingState.ARMED


def words_limit(runtime) -> int:
    """How long a message may be now: A27's 2,000, or what one continuation carries while Longer reset messages
    stands on."""
    return continuation.PROMPT_LIMIT if _on(runtime, LONG) else SHORT_LIMIT


def occasion_problem(bucket, minutes, ordinal) -> bool:
    """Whether (bucket, minutes, ordinal) is no occasion on offer: a bucket core keeps, a length in minutes, and the
    1st to 9th next reset - only the next for a weekly window."""
    if bucket not in BUCKETS or type(minutes) is not int or not 0 < minutes <= 10 * WEEK:
        return True
    if type(ordinal) is not int or ordinal not in ORDINALS:
        return True
    return minutes >= WEEK and ordinal != 1


def switched_off(runtime, thread) -> bool:
    """Whether core holds conversation `thread` switched off now, read from core's state as the Dashboard's
    own reads open it. One that cannot be read refuses nothing: P2 cancels a message whose conversation it
    finds off (engine/resetmessage.py)."""
    from codex_auto_resume.store import Store
    try:
        with Store(runtime.paths.state_dir) as store:
            return store.thread_enabled(thread) is False
    except Exception:
        return False


def view(runtime) -> dict:
    """advanced-resets: every rule still to act and those of the last thirty days, a message's words while it is
    still to act, the window families on offer with what was counted of each, the last reading - the count of
    credits and the soonest expiry only while reset_credit is on - the last spend, and the bounds."""
    state = runtime.state
    try:
        rules = state.reset_rules(pending=None)
        windows = state.windows()
        reading = state.reading()
        spends = state.credit_spends()
        generation = state.meta()["generation"]
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE)
    now = runtime.clock()
    shown = []
    for rule in rules:
        if rule["state"] not in (RuleState.COUNTING, RuleState.READY, RuleState.HELD) and (
                rule["finished_at"] or 0) < now - 30 * 86400:
            continue
        item = {name: rule.get(name) for name in SHOWN}
        row = windows.get((rule["bucket"], rule["minutes"]))
        item["counted"] = (None if rule["base"] is None or row is None
                           else (row["hits"] if rule["capability"] == CREDIT else row["resets"]) - rule["base"])
        item["next_reset"] = row["open_reset_at"] if row is not None else None
        item["words"] = rule["words"]
        item["being_sent"] = rule["launching_at"] is not None or rule["record_state"] == "in_flight"
        shown.append(item)
    families = [{"bucket": bucket, "minutes": minutes,
                 "open_reset_at": (windows.get((bucket, minutes)) or {}).get("open_reset_at"),
                 "open_full": bool((windows.get((bucket, minutes)) or {}).get("open_full"))}
                for bucket, minutes in sorted(set(DEFAULT_FAMILIES) | set(windows), key=lambda family: (family[1], family[0]))]
    credit_on = _on(runtime, CREDIT)
    last = next((spend for spend in spends if spend["outcome"] is not None), None)
    return {"done": True, "refusal": None, "generation": generation, "rules": shown, "families": families,
            "reading": {"read_at": reading.get("read_at"),
                        "credits": reading.get("credits") if credit_on else None,
                        "nearest_expiry": reading.get("nearest_expiry") if credit_on else None,
                        "expiry_known": bool(reading.get("expiry_known")) if credit_on else None},
            "last_spend": None if last is None else {"outcome": last["outcome"], "at": last["finished_at"]},
            "limits": {"messages": 10, "credit_rules": 4, "words": words_limit(runtime), "ordinals": 9,
                       "use_now_minutes": reset_credit.USE_NOW // 60}}


def add(runtime, argument) -> dict:
    """advanced-reset-add: one rule, `kind` credit or message, for the occasion (bucket, minutes, ordinal); a credit's
    `repeat` and `ask_first`, a message's `thread_id` and `words`. Refused while its capability does not stand on,
    for an occasion not on offer, for words the check refuses or longer than the bound, for a conversation switched
    off, and as the state refuses it (one waiting in that conversation, as many waiting as may)."""
    capability = KINDS.get(argument.get("kind"))
    if capability is None or runtime.registry.get(capability) is None:
        return _refused(Refusal.INVALID_REQUEST)
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    if not _on(runtime, capability):
        return _refused(Refusal.NOT_ON, runtime)
    bucket, minutes, ordinal = argument.get("bucket"), argument.get("minutes"), argument.get("ordinal")
    if occasion_problem(bucket, minutes, ordinal):
        return _refused(Refusal.OCCASION_INVALID, runtime)
    from ..state import Refused, StateError
    try:
        if capability == CREDIT:
            repeat, ask_first = argument.get("repeat", False), argument.get("ask_first", False)
            if type(repeat) is not bool or type(ask_first) is not bool or "words" in argument or "thread_id" in argument:
                return _refused(Refusal.INVALID_REQUEST, runtime)
            rule = runtime.state.add_reset_rule(CREDIT, bucket, minutes, ordinal, repeat=repeat, ask_first=ask_first)
        else:
            thread, words = argument.get("thread_id"), argument.get("words")
            if ids.uuid_problem(thread) is not None or set(argument) & {"repeat", "ask_first"}:
                return _refused(Refusal.INVALID_REQUEST, runtime)
            try:
                continuation.validate_prompt(words)
            except continuation.PromptError:
                return _refused(Refusal.MESSAGE_REFUSED, runtime)
            if len(words) > words_limit(runtime):
                return _refused(Refusal.MESSAGE_REFUSED, runtime)
            if switched_off(runtime, thread):
                return _refused(Refusal.CONVERSATION_OFF, runtime)
            rule = runtime.state.add_reset_rule(MESSAGE, bucket, minutes, ordinal, thread_id=thread, words=words,
                                                record_id=secrets.token_hex(32))
    except Refused as refused:
        return _refused(refused.refusal, runtime)
    except StateError:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    _wake(runtime)
    return {"done": True, "refusal": None, "rule": rule, "generation": runtime.state.meta()["generation"]}


def cancel(runtime, rule, generation) -> dict:
    """advanced-reset-cancel: a person's Cancel of one rule - refused once its message is being sent."""
    if type(rule) is not int:
        return _refused(Refusal.INVALID_REQUEST)
    if _stale(runtime, generation):
        return _refused(Refusal.STALE_GENERATION, runtime)
    from ..state import Refused, StateError
    try:
        runtime.state.cancel_reset_rule(rule, at=runtime.clock())
    except Refused as refused:
        return _refused(refused.refusal, runtime)
    except StateError:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return {"done": True, "refusal": None, "rule": rule}


def go_on(runtime, rule, generation) -> dict:
    """advanced-reset-go-on: a rule held over a gap or a window gone counts again, from its next adoption, for what
    it had left to count (engine/resetwatch.py)."""
    if type(rule) is not int:
        return _refused(Refusal.INVALID_REQUEST)
    if _stale(runtime, generation):
        return _refused(Refusal.STALE_GENERATION, runtime)
    found = runtime.state.reset_rule(rule)
    if found is None or found["state"] != RuleState.HELD:
        return _refused(Refusal.UNKNOWN_RULE, runtime)
    if not _on(runtime, found["capability"]):
        return _refused(Refusal.NOT_ON, runtime)
    from ..state import StateError
    try:
        moved = runtime.state.change_rule(rule, expect=RuleState.HELD, state=RuleState.COUNTING, reason=None, base=None,
                                          adopted_at=None)
    except StateError:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if not moved:
        return _refused(Refusal.UNKNOWN_RULE, runtime)
    _wake(runtime)
    return {"done": True, "refusal": None, "rule": rule}


def credit_now(runtime, argument) -> dict:
    """advanced-credit-now: a person's Use a reset credit now - for the window of a rule of reset_credit that is due
    (`rule`), of the family named (`bucket`, `minutes`), or else the one window counted that is full now: a rule of
    its own, due at once and good for fifteen minutes. Only while reset_credit stands on. The watcher is woken."""
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    if not _on(runtime, CREDIT):
        return _refused(Refusal.NOT_ON, runtime)
    state = runtime.state
    family = None
    if "rule" in argument:
        found = state.reset_rule(argument["rule"]) if type(argument["rule"]) is int else None
        if found is None or found["capability"] != CREDIT or found["state"] != RuleState.READY:
            return _refused(Refusal.UNKNOWN_RULE, runtime)
        family = (found["bucket"], found["minutes"])
    elif "bucket" in argument or "minutes" in argument:
        family = (argument.get("bucket"), argument.get("minutes"))
        if occasion_problem(family[0], family[1], 1):
            return _refused(Refusal.OCCASION_INVALID, runtime)
    else:
        full = [key for key, row in state.windows().items() if row["open_reset_at"] and row["open_full"]]
        if len(full) != 1:
            return _refused(Refusal.OCCASION_INVALID, runtime)
        family = full[0]
    from ..state import Refused, StateError
    try:
        rule = state.add_reset_rule(CREDIT, family[0], family[1], 0)
        now = runtime.clock()
        state.change_rule(rule, state=RuleState.READY, due_at=now, reason=None)
    except Refused as refused:
        return _refused(refused.refusal, runtime)
    except StateError:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    _wake(runtime)
    return {"done": True, "refusal": None, "rule": rule, "expires_at": now + reset_credit.USE_NOW}


def counts(runtime) -> dict:
    """What P10's status shows of the reset actions: how many messages and credit rules wait, and how many of them
    are due - counts, and nothing else (no words, no conversation). Empty where none waits."""
    try:
        rules = runtime.state.reset_rules()
    except Exception:
        return {}
    if not rules:
        return {}
    return {"messages": sum(rule["capability"] == MESSAGE for rule in rules),
            "credit_rules": sum(rule["capability"] == CREDIT for rule in rules),
            "ready": sum(rule["state"] == RuleState.READY for rule in rules)}


def _wake(runtime) -> None:
    from .sendnow import wake
    try:
        wake(runtime.paths)
    except Exception:
        pass                                         # the next look finds it

