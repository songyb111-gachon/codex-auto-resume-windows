# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""A delivered message followed to the end of the work it started (v0.6.20, issue #50 - promised there on 2026-10-26).

History says a scheduled message was delivered; this says what its work did after: the turn the message started, whether
a limit cut that turn off, where the recovery of THAT turn stands - and, where the recovery's own turn was cut off again,
the next one - to the end. The bridge's advanced-prompt-follow, the Dashboard's alone (surfaces.py), part of the prompt
queue: answered only while prompt_queue stands on, as everything of the queue is. No MCP tool reaches it.

The link, in the order it is tried (`follow`):

1. exact - the message's occurrence carries its own proof into Codex: its marker (ids.short_marker of the occurrence's
   record id, which the prompt row keeps) or, for a message sent with pictures and so with no marker, the client id core
   derives from that id (ids.continuation_client_id). Core's own reader (codex/history.py marker_rows) names the turn
   whose user message holds it - the look the watcher made to say "delivered". One turn, or no link (two: ambiguous).
2. by time - only where that found nothing (Codex's history unreadable, or the proof no longer in it): the one cut-off
   of core's records in the conversation whose turn started between the message's send and the watcher seeing it
   delivered, and that is no recovery's own turn. One, or no link. The answer says `time`, and the page says "linked by
   time": it never claims more than the times show.
3. from that turn on, ids only: the interruption whose turn it is; then the one whose turn is that one's recovery turn
   (or whose parent it is); and so on, at most STEPS. A turn a person started is never on the path: its id is neither
   the message's nor any recovery's.

Read-only: nothing is written anywhere - the edition's state and core's are read, Codex's history is read by core's
reader (opened read-only), and nothing a conversation says is read or answered: ids, statuses, times and words of a
closed list only. There is no send path here.
"""
from __future__ import annotations

from codex_auto_resume import machine
from codex_auto_resume.domain import ids
from codex_auto_resume.domain.public import public_code

from ..engine.promptqueue import CAPABILITY
from ..vocabulary import PromptReason, PromptState, Refusal
from .resets import _refused, _standing

# How many cut-offs one message is followed through at most: a recovery cut off again and again is a chain, and a chain
# this long has long stopped (core's own chain cap is far below it).
STEPS = 12
# How the message's turn was tied to it.
EXACT, TIME, NONE = "exact", "time", "none"
# Why it was not: the history unreadable and nothing by time, the proof in two turns or two cut-offs by time, or no
# occurrence kept.
NOT_FOUND, AMBIGUOUS, NO_RECORD = "not_found", "ambiguous", "no_record"
# Where one recovery stands, from core's state: waiting, on its way (claimed, in Codex's queue, its turn running),
# recovered, or ended any other way (failed, exhausted, cancelled, handed over...) - its public code says which.
WAITING, RECOVERING, RECOVERED, ENDED = "waiting", "recovering", "recovered", "ended"
# How the work it started stands at the end.
STILL_RUNNING, FINISHED, UNKNOWN = "still_running", "finished", "unknown"
# What one cut-off answers: ids, closed words and times - never a word anyone wrote.
STEP_FIELDS = ("interruption_id", "turn_id", "category", "limit_type", "detected_at", "reset_at", "outcome_at",
               "recovery_turn_id", "recovery_turn_status")


def proofs(record_id) -> tuple:
    """What proves an occurrence of `record_id` reached Codex: its marker, then the client id it went under with none."""
    return (ids.short_marker(record_id), ids.continuation_client_id(record_id))


def read_turns(home):
    """The reader of Codex's history the bridge uses: (thread, record_id) -> the marker rows of the occurrence's turn
    (core's LocalSource.marker_rows, for each proof until one is found), or None where the history cannot be read."""
    def read(thread_id, record_id):
        from pathlib import Path
        from codex_auto_resume.codex import LocalSource
        try:
            source = LocalSource(Path(home))
            for proof in proofs(record_id):
                found = source.marker_rows(thread_id, proof)
                if found:
                    return found
            return []
        except Exception:
            return None
    return read


def _stage(state) -> str:
    if state in machine.WAITING:
        return WAITING
    if state == "recovered":
        return RECOVERED
    if state in machine.TERMINAL:
        return ENDED
    return RECOVERING


def _turn_of(found):
    """(link, turn id, its status, why) from the marker rows `found`: one turn exact, two ambiguous, none not found."""
    turns = []
    for row in found or ():
        if isinstance(row, dict) and ids.is_uuid(row.get("turn_id")) and row["turn_id"] not in [t for t, _ in turns]:
            turns.append((row["turn_id"], row.get("status")))
    if len(turns) == 1:
        return EXACT, turns[0][0], turns[0][1], None
    if len(turns) > 1:
        return NONE, None, None, AMBIGUOUS
    return NONE, None, None, NOT_FOUND


def _by_time(prompt, records):
    """(link, turn id, why) by time: the one cut-off whose turn started between the send and the delivery seen, that is
    no recovery's own turn - else no link (none, or two)."""
    low = prompt.get("sent_at") or prompt.get("due_at")
    high = prompt.get("finished_at")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return NONE, None, NOT_FOUND
    recovery_turns = {record.get("recovery_turn_id") for record in records} - {None}
    # Codex keeps a turn's start in whole seconds, so one started the second the message went reads that second.
    found = [record for record in records
             if record.get("parent_interruption_id") is None and record.get("turn_id") not in recovery_turns
             and isinstance(record.get("started_at"), (int, float)) and int(low) <= record["started_at"] <= high]
    if len(found) == 1:
        return TIME, found[0]["turn_id"], None
    return NONE, None, AMBIGUOUS if found else NOT_FOUND


def _cut_off(records, turn_id, parent):
    """The interruption of `turn_id` - or, failing that, the one whose parent is `parent` - the earliest detected."""
    found = [record for record in records if record.get("turn_id") == turn_id]
    if not found and parent is not None:
        found = [record for record in records if record.get("parent_interruption_id") == parent]
    found.sort(key=lambda record: (record.get("detected_at") or 0, record.get("interruption_id") or ""))
    return found[0] if found else None


def follow(prompt, found, records) -> dict:
    """The follow-through of the delivered message `prompt` (a prompts row): `found` the marker rows of its occurrence's
    turn (None where Codex's history could not be read), `records` core's interruptions of its conversation. Pure: what
    it answers is made from these alone."""
    records = [record for record in records if record.get("thread_id") == prompt["thread_id"]]
    answer = {"link": NONE, "why": None, "turn_id": None, "turn_status": None, "steps": [], "end": UNKNOWN}
    if prompt.get("record_id") is None:
        answer["why"] = NO_RECORD
        return answer
    link, turn, status, why = _turn_of(found)
    if link == NONE and why == NOT_FOUND:
        link, turn, why = _by_time(prompt, records)
        status = None
    answer.update(link=link, why=why, turn_id=turn, turn_status=status if status in machine.TURN_STATUSES else None)
    if link == NONE:
        return answer
    steps, current, parent, seen = [], turn, None, set()
    while current is not None and len(steps) < STEPS:
        record = _cut_off(records, current, parent)
        if record is None or record["interruption_id"] in seen:
            break
        seen.add(record["interruption_id"])
        step = {name: record.get(name) for name in STEP_FIELDS}
        step["code"] = public_code(record)
        step["stage"] = _stage(record.get("state"))
        steps.append(step)
        current, parent = record.get("recovery_turn_id"), record["interruption_id"]
        if current is None:
            break
    answer["steps"] = steps
    if steps:
        answer["end"] = steps[-1]["stage"]
    elif link == EXACT and answer["turn_status"] == "inProgress":
        answer["end"] = STILL_RUNNING
    elif link == EXACT and answer["turn_status"] in ("completed", "failed", "interrupted"):
        answer["end"] = FINISHED
    return answer


def _records(runtime, thread_id) -> list:
    """Core's interruptions of `thread_id`, every one (hidden from History too: the chain is the record's, not the
    list's). None at all where core's state is not there yet: opening it would make one, and this writes nothing."""
    from pathlib import Path
    from codex_auto_resume.store import Store
    if not (Path(runtime.paths.state_dir) / "state.sqlite").is_file():
        return []
    with Store(runtime.paths.state_dir) as store:
        return [record for record in store.all_records() if record.get("thread_id") == thread_id]


def view(runtime, prompt, reader=None) -> dict:
    """advanced-prompt-follow: the follow-through of the delivered message `prompt` - refused for an id that is no
    prompt's (invalid_request), a prompt that is not a delivered one (invalid_request), the queue not standing (not_on),
    and anything unreadable of the state (state_unavailable)."""
    if type(prompt) is not int:
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    try:
        row = runtime.state.prompt(prompt)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if row is None or row["state"] != PromptState.DONE or row["reason"] != PromptReason.DELIVERED:
        return _refused(Refusal.INVALID_REQUEST, runtime)
    try:
        records = _records(runtime, row["thread_id"])
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if reader is None:
        from ..codex import inuse
        reader = read_turns(inuse.home(runtime.paths))
    found = None if row["record_id"] is None else reader(row["thread_id"], row["record_id"])
    answer = follow(row, found, records)
    answer.update(done=True, refusal=None, prompt=prompt, thread_id=row["thread_id"], sent_at=row.get("sent_at"),
                  delivered_at=row.get("finished_at"), due_at=row.get("due_at"), occurrence=row.get("sent_count"),
                  occurrences=row.get("occurrences"), trigger=row.get("trigger"))
    return answer
