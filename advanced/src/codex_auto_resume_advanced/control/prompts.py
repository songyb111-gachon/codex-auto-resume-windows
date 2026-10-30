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

From v0.6.20 (#50, steer_send) the list carries the steers of the last 30 days too (control/steer.rows), which History
shows, and the status counts the steers still waiting for the watcher, so the page reads the list again when one settles.

v0.6.20 (#50 item 1): an add or an edit may carry `images` - at most four, each {"path": a file the person chose,
dropped or the window wrote for a paste} or, on an edit, {"id": one of this prompt's copies} to keep it - copied as the
product's own (images.py), checked by their bytes and size, and never the person's path kept or answered. Where
MIMG failed on the Codex in force, pictures are refused (images_unavailable). An edit with no `images` keeps them. The
list shows each prompt still to go with its copies (their opaque ids and the copies' own paths, for the editor's
thumbnails); a finished one says nothing of pictures, and the status counts none.
"""
from __future__ import annotations

from codex_auto_resume import continuation
from codex_auto_resume.domain import ids

from ..engine.promptqueue import CAPABILITY, LONG, SHORT_LIMIT
from .. import images as copies
from ..state.choices import Refused
from ..state.prompts import COMPLETED, PENDING, PER_CONVERSATION, PROMPTS_LIMIT
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
    found = {"prompts": len(rows)} if rows else {}
    # v0.6.20: the steers waiting for the watcher (control/steer.py), a count.
    from .steer import waiting
    steers = waiting(runtime)
    if steers:
        found["steers_waiting"] = steers
    return found


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
        # v0.6.20 (#50): the product's own copies of its pictures, while it is still to go.
        if row["state"] in PENDING:
            item["images"] = copies.of(runtime.paths, row["prompt_id"])
        shown.append(item)
    try:
        unproven = runtime.arming.verdict(Measurement.MT) != "pass"
    except Exception:
        unproven = True
    from .steer import rows as steers
    return {"done": True, "refusal": None, "generation": generation, "prompts": shown, "after_turn_unproven": unproven,
            # v0.6.20 (#50): the steers History lists, with their words and outcomes (control/steer.py).
            "steers": steers(runtime),
            "limits": {"prompts": PROMPTS_LIMIT, "per_conversation": PER_CONVERSATION, "words": words_limit(runtime),
                       "occurrences": 30, "days": 30, "images": copies.MOST_IMAGES, "image_bytes": copies.MOST_BYTES},
            "images_unavailable": _images_failed(runtime)}


def _images_failed(runtime) -> bool:
    """Whether MIMG failed on the Codex in force (v0.6.20): pictures are then refused."""
    try:
        return runtime.arming.verdict(Measurement.MIMG) == "fail"
    except Exception:
        return False


def sweep(runtime) -> None:
    """Every copy whose prompt is no longer still to go removed (images.sweep)."""
    try:
        pending = [row["prompt_id"] for row in runtime.state.prompts(pending=True)]
    except Exception:
        return
    copies.sweep(runtime.paths, pending)


def _staged(runtime, images, prompt=None):
    """The pictures `images` names, as the opaque ids of copies: each new file read and copied as a save's copy, each
    kept one checked to be `prompt`'s. ((ids, made), None), or (None, refusal) with every copy this made removed."""
    if not isinstance(images, list):
        return None, Refusal.INVALID_REQUEST
    if len(images) > copies.MOST_IMAGES:
        return None, Refusal.IMAGES_FULL
    if images and _images_failed(runtime):
        return None, Refusal.IMAGES_UNAVAILABLE
    own = {image["id"] for image in copies.of(runtime.paths, prompt)} if prompt is not None else set()
    made, chosen = [], []
    for image in images:
        if not isinstance(image, dict) or len(image) != 1 or not ({"id", "path"} & set(image)):
            copies.drop(runtime.paths, made)
            return None, Refusal.INVALID_REQUEST
        if "id" in image:
            if image["id"] not in own or image["id"] in chosen:
                copies.drop(runtime.paths, made)
                return None, Refusal.INVALID_REQUEST
            chosen.append(image["id"])
            continue
        try:
            data, ext = copies.read(image["path"])
            made.append(copies.stage(runtime.paths, data, ext))
        except copies.ImageRefused as refused:
            copies.drop(runtime.paths, made)
            return None, Refusal(refused.refusal)
        except OSError:
            copies.drop(runtime.paths, made)
            return None, Refusal.STATE_UNAVAILABLE
        chosen.append(made[-1])
    return (chosen, made), None


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
    staged, refusal = _staged(runtime, argument.get("images", []))
    if refusal is not None:
        return _refused(refusal, runtime)
    images, made = staged
    try:
        prompt = runtime.state.add_prompt(thread, words, argument.get("trigger"), at=argument.get("at"),
                                          every=argument.get("every"), occurrences=argument.get("occurrences", 1),
                                          depends=argument.get("depends") is True,
                                          while_running=argument.get("while_running") or "queue")
    except Refused as refused:
        copies.drop(runtime.paths, made)
        return _refused(refused.refusal, runtime)
    except Exception:
        copies.drop(runtime.paths, made)
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if images:
        try:
            copies.place(runtime.paths, prompt, images)
        except (OSError, copies.ImageRefused):
            # Its pictures could not be made its own: the message is not left to go without them.
            try:
                runtime.state.cancel_prompt(prompt, at=runtime.clock())
            except Exception:
                pass
            copies.drop(runtime.paths, made)
            sweep(runtime)
            return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    sweep(runtime)
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
    sweep(runtime)
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
    images, made = None, []
    if "images" in argument:
        staged, refusal = _staged(runtime, argument.get("images"), prompt)
        if refusal is not None:
            return _refused(refusal, runtime)
        images, made = staged
    try:
        runtime.state.edit_prompt(prompt, argument.get("generation"), words, argument.get("trigger"),
                                  at=argument.get("at"), every=argument.get("every"),
                                  occurrences=argument.get("occurrences", 1), depends=argument.get("depends") is True,
                                  while_running=argument.get("while_running") or "queue", now=runtime.clock())
    except Refused as refused:
        copies.drop(runtime.paths, made)
        return _refused(refused.refusal, runtime)
    except Exception:
        copies.drop(runtime.paths, made)
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if images is not None:
        try:
            copies.place(runtime.paths, prompt, images)
        except (OSError, copies.ImageRefused):
            copies.drop(runtime.paths, made)
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
    sweep(runtime)
    return dict(view(runtime), done=True, deleted=cleared["deleted"], skipped=cleared["skipped"])
