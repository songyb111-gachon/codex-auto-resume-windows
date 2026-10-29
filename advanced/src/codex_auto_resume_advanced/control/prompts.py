# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's prompt queue (v0.6.15-beta): the queued prompts read, one added, one cancelled, one held let go on -
and (v0.6.19, #50) one still waiting edited, and the completed ones a person was shown deleted from the list (Delete
completed).

Each is the long-lived bridge's, the Dashboard's alone (surfaces.py), against the generation the page read. No MCP
tool reaches any of them. A prompt is added only while prompt_queue stands on and its conversation is switched on,
checked as core checks a message of a person's (continuation.validate_prompt: no empty text, no marker, no shipped
template), at most 2,000 characters unless Longer messages stands on; twenty waiting in all and five to a
conversation (state/prompts.py). Cancel takes the words at once - or, for one Codex already holds in its queue, asks
core to take it back out (the owner's answer of 2026-10-09), which says on its row when Codex will not; one being
sent, Cancel no longer reaches. Delete completed takes off the list only the finished prompts it is named that are still
completed work (state/prompts.COMPLETED), and says how many it deleted and how many it kept because they changed;
nothing of Codex's and no row the caps count is ever touched.
"""
from __future__ import annotations

from codex_auto_resume import continuation
from codex_auto_resume.domain import ids

from ..engine.promptqueue import CAPABILITY, LONG, SHORT_LIMIT
from ..state.choices import Refused
from ..state.prompts import COMPLETED, PER_CONVERSATION, PROMPTS_LIMIT
from ..vocabulary import Measurement, PromptState, Refusal
from .resets import _on, _refused, _stale, _standing, switched_off

SHOWN = ("prompt_id", "thread_id", "trigger", "at", "every", "occurrences", "sent_count", "until", "depends",
         "position", "state", "reason", "gate", "gate_reason", "created_at", "due_at", "sent_at", "finished_at",
         # v0.6.19 (#50): what it does while a turn of its conversation runs.
         "while_running")


def counts(runtime) -> dict:
    """What P10's status shows of the prompt queue: how many prompts are still to go - a count, and nothing else (no
    words, no conversation). Empty where none is."""
    try:
        rows = runtime.state.prompts()
    except Exception:
        return {}
    return {"prompts": len(rows)} if rows else {}


def words_limit(runtime) -> int:
    return continuation.PROMPT_LIMIT if _on(runtime, LONG) else SHORT_LIMIT


def view(runtime) -> dict:
    """advanced-prompts: every prompt still to go and those of the last thirty days, its words while one is still to
    go, whether one is being sent or held in Codex's queue, the bounds, and whether after_turn is unproven here."""
    try:
        rows = runtime.state.prompts(pending=None)
        generation = runtime.state.meta()["generation"]
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE)
    now = runtime.clock()
    shown = []
    for row in rows:
        if row["state"] not in (PromptState.WAITING, PromptState.READY, PromptState.HELD) and (
                row["finished_at"] or 0) < now - 30 * 86400:
            continue
        item = {name: row.get(name) for name in SHOWN}
        item["words"] = row["words"]
        item["in_codex"] = row["record_state"] == "in_flight" and row["sent_at"] is not None
        item["being_sent"] = row["record_state"] == "in_flight" and row["sent_at"] is None
        # v0.6.19 (#50): finished as completed work, so Delete completed may take it off the list.
        item["completed"] = row["state"] == PromptState.DONE and row["reason"] in COMPLETED
        shown.append(item)
    try:
        unproven = runtime.arming.verdict(Measurement.MT) != "pass"
    except Exception:
        unproven = True
    return {"done": True, "refusal": None, "generation": generation, "prompts": shown, "after_turn_unproven": unproven,
            "limits": {"prompts": PROMPTS_LIMIT, "per_conversation": PER_CONVERSATION, "words": words_limit(runtime),
                       "occurrences": 30, "days": 30}}


def add(runtime, argument) -> dict:
    """advanced-prompt-add: one prompt for `thread_id`, its trigger, time, every and occurrences, whether it waits
    for the one before it to be delivered, and (v0.6.19, #50) what it does while a turn runs - `while_running`, "wait"
    or "queue"; where it is not named, "queue", what every prompt did before the choice existed (the Dashboard's
    editor names it, "wait" unless the person chose the other)."""
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    thread, words = argument.get("thread_id"), argument.get("words")
    if not ids.is_uuid(thread):
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    if switched_off(runtime, thread):
        return _refused(Refusal.CONVERSATION_OFF, runtime)
    try:
        continuation.validate_prompt(words)
    except Exception:
        return _refused(Refusal.PROMPT_REFUSED, runtime)
    if len(words) > words_limit(runtime):
        return _refused(Refusal.PROMPT_REFUSED, runtime)
    try:
        prompt = runtime.state.add_prompt(thread, words, argument.get("trigger"), at=argument.get("at"),
                                          every=argument.get("every"), occurrences=argument.get("occurrences", 1),
                                          depends=argument.get("depends") is True,
                                          while_running=argument.get("while_running") or "queue")
    except Refused as refused:
        return _refused(refused.refusal, runtime)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return dict(view(runtime), done=True, prompt=prompt)


def cancel(runtime, prompt, generation) -> dict:
    """advanced-prompt-cancel: one prompt cancelled, its words gone - or, held in Codex's queue, asked back."""
    if _stale(runtime, generation):
        return _refused(Refusal.STALE_GENERATION, runtime)
    if type(prompt) is not int:
        return _refused(Refusal.INVALID_REQUEST, runtime)
    try:
        how = runtime.state.cancel_prompt(prompt, at=runtime.clock())
    except Refused as refused:
        return _refused(refused.refusal, runtime)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return dict(view(runtime), done=True, cancelled=how)


def go_on(runtime, prompt, generation) -> dict:
    """advanced-prompt-go-on: a prompt held (the one before it did not arrive, or Codex's queue took it back at a
    Pause) waits again, the person's word."""
    if _stale(runtime, generation):
        return _refused(Refusal.STALE_GENERATION, runtime)
    if type(prompt) is not int:
        return _refused(Refusal.INVALID_REQUEST, runtime)
    try:
        if not runtime.state.go_on_prompt(prompt):
            return _refused(Refusal.INVALID_REQUEST, runtime)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return dict(view(runtime), done=True)


def edit(runtime, argument) -> dict:
    """advanced-prompt-edit (v0.6.19, #50): one prompt still waiting given new words, a new time or schedule, whether it
    waits for the one before it and what it does while a turn runs, against the generation the list was read at - checked
    as a new one is (add), and refused where it moved past waiting since."""
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    prompt, words = argument.get("prompt"), argument.get("words")
    if type(prompt) is not int:
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    try:
        row = runtime.state.prompt(prompt)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if row is None:
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if switched_off(runtime, row["thread_id"]):
        return _refused(Refusal.CONVERSATION_OFF, runtime)
    try:
        continuation.validate_prompt(words)
    except Exception:
        return _refused(Refusal.PROMPT_REFUSED, runtime)
    if len(words) > words_limit(runtime):
        return _refused(Refusal.PROMPT_REFUSED, runtime)
    try:
        runtime.state.edit_prompt(prompt, argument.get("generation"), words, argument.get("trigger"),
                                  at=argument.get("at"), every=argument.get("every"),
                                  occurrences=argument.get("occurrences", 1), depends=argument.get("depends") is True,
                                  while_running=argument.get("while_running") or "queue", now=runtime.clock())
    except Refused as refused:
        return _refused(refused.refusal, runtime)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return dict(view(runtime), done=True, prompt=prompt)


def clear_done(runtime, argument) -> dict:
    """advanced-prompts-clear-done (v0.6.19, #50): of `prompts`, the ids of the completed prompts the Dashboard showed,
    those still completed deleted from the list, against the generation it read them at; how many were deleted and how
    many kept because they changed (`deleted`, `skipped`)."""
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    try:
        cleared = runtime.state.clear_done(argument.get("prompts"), argument.get("generation"))
    except Refused as refused:
        return _refused(refused.refusal, runtime)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    return dict(view(runtime), done=True, deleted=cleared["deleted"], skipped=cleared["skipped"])
