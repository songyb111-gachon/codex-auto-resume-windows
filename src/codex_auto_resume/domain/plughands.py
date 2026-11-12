"""What core holds of something a plug names: a channel, a route and (v0.6.14) an errand - and which
records of the plug's own core takes to carry out (P2), and what a surface takes of a plug's fields (P10).

A hook answers; it never sends, claims or starts anything (domain/plug.py). Where a point's answer is
something core carries out - a channel the one send is handed to (P5), a route that continues a
conversation the app does not hold (P16), an errand run once a tick (P8) - core holds it as one of
these and calls only its one method, at the moment core chooses and with what core decides. Each is
held to a guard of core's: the launch guard, read under the store's write lock, for a channel and a
route; for an errand, guards it asks core for and enters itself, once each, in which a Pause, Observe
only or quiet hours that committed first refuse the one irrevocable thing it was going to do.

Pure, as the rest of domain/: the standard library only, and nothing read or written here.
"""
from __future__ import annotations

from contextlib import nullcontext
from enum import StrEnum
import json

from . import ids
from .states import EPOCH_STORE, epoch

# How many records of the plug's own core takes in one tick (P2), at most: more is a plug's mistake.
RECORDS_LIMIT = 8
# P12 (v0.6.15-beta): at most this many sends wait for their receipts at once, whatever a plug answers - one in each
# conversation, the claim refusing a second (engine/launches.py).
MAX_WORKERS = 8


def workers(answer) -> int:
    """What core takes of P12's answer: a whole number 2 to MAX_WORKERS as it is - `type(x) is int`, so never True -
    and 1, one send after another as always, for anything else: DEFER, 0, 5, True, "2", a list."""
    return answer if type(answer) is int and 2 <= answer <= MAX_WORKERS else 1
# What one of them is, exactly: no more keys and no fewer.
BASE_RECORD_KEYS = frozenset({"record_id", "thread_id", "marker", "state", "words", "sent_at"})
# v0.6.15-beta: and what the words are (RecordPurpose), the turn a continuation follows, the queue item Codex said it
# took and whether a person asked for it back - each optional, a record without it being what one was before. v0.6.23:
# and whether a Pause leaves it in Codex's queue (`pause_keeps`, the in-app chat's: its statement departs from H4),
# taken back then only where the plug asks for it back or its conversation is off.
RECORD_KEYS = BASE_RECORD_KEYS | {"purpose", "ordinal", "queue_id", "withdraw", "pause_keeps"}
# How long the words of one may be, at most: what core's one send carries, less the blank line and the
# marker it ends with (continuation.validate_prompt checks them again, as text). 30,000: continuation.PROMPT_SEND_LIMIT,
# written again because this layer is below it (the owner, 2026-11-10; a test holds the two equal).
WORDS_LIMIT = 30000
# How many guards one errand may ask for in one tick: one for each capability whose errand the plug
# joins into it, and no more. A guard asked for past this is refused without a transaction.
ERRAND_GUARDS = 8


class Widening(StrEnum):
    """Which conversations of the Codex app besides a person's own core takes up (P19, v0.6.16-beta.3). EVERY_DESKTOP:
    every desktop conversation but the kinds Codex makes for itself (codex/values.INTERNAL_THREAD_SOURCES), whatever
    other label Codex sets on it, still the app's own, not archived, its rollout's first line of that very id."""
    EVERY_DESKTOP = "every_desktop"


WIDENINGS = tuple(Widening)


class SessionKind(StrEnum):
    """Which conversations besides the Codex app's a plug may ask core to watch (P18, v0.6.16-beta.4): those a
    terminal's Codex TUI runs, and those of the VS Code extension (codex/eligibility.py)."""
    CLI = "cli"
    IDE = "ide"


SESSION_KINDS = tuple(SessionKind)


def kinds_of(answer) -> frozenset:
    """What core takes of P18's answer: the SessionKind words in a set, a frozenset or a tuple of them - and the empty
    set, the app's conversations alone as always, for anything else: DEFER, a word, a list holding another word."""
    if type(answer) not in (set, frozenset, tuple):
        return frozenset()
    try:
        found = frozenset(answer)
        if not all(type(word) in (str, SessionKind) and word in tuple(SessionKind) for word in found):
            return frozenset()
        return frozenset(SessionKind(word) for word in found)
    except Exception:
        return frozenset()


def widening_of(answer) -> frozenset:
    """What core takes of P19's answer: the Widening words in a set, a frozenset or a tuple of them - and the empty set,
    a person's own conversations alone as always, for anything else: DEFER, a word, a list holding another word."""
    if type(answer) not in (set, frozenset, tuple):
        return frozenset()
    try:
        found = frozenset(answer)
        if not all(type(word) in (str, Widening) and word in tuple(Widening) for word in found):
            return frozenset()
        return frozenset(Widening(word) for word in found)
    except Exception:
        return frozenset()


class RecordPurpose(StrEnum):
    """What a record of the plug's says (v0.6.15-beta): a person's own MESSAGE (continuation.validate_prompt, product
    text refused), or a CONTINUATION in the edition's own catalog words (continuation.validate_continuation), sent only
    while the turn it follows is still its conversation's latest. From v0.6.16-beta.3 a WRAP_UP, in the edition's own
    catalog words too, sent only while the turn it was made for is still the latest and still running - Codex's queue
    delivers it when that turn ends."""
    MESSAGE = "message"
    CONTINUATION = "continuation"
    WRAP_UP = "wrap_up"


class RecordMove(StrEnum):
    """What core did with a record of the plug's own (P2, v0.6.14), as P14 tells it (RECORD_MOVES): it
    waits, at a gate and for a reason core names; it was handed back before its send, or its process
    never started, and waits again with its words; it was sent - its words gone from the plug's state -
    and is watched; its marker was found in Codex's history; or none was a day after it was sent, and
    it is never sent again. From v0.6.15-beta: a continuation whose turn is no longer the latest is
    SUPERSEDED and never sent; one a person edited in Codex's queue is HANDED_OVER, theirs; one taken back
    out of Codex's queue on a Cancel or a Pause is WITHDRAWN; and one Codex would not give back is
    WITHDRAW_REFUSED - left there, watched, and never sent twice."""
    WAITING = "waiting"
    RELEASED = "released"
    NOT_STARTED = "not_started"
    SENT = "sent"
    DELIVERED = "delivered"
    UNPROVEN = "unproven"
    SUPERSEDED = "superseded"
    HANDED_OVER = "handed_over"
    WITHDRAWN = "withdrawn"
    WITHDRAW_REFUSED = "withdraw_refused"


class Channel:
    """A channel a plug named at P5, held to the launch guard rather than asked to enter it.

    Core's backend enters the guard it is handed around the one moment it launches the queue
    process, so a Pause, a cancel or a conversation switched off that committed after the claim
    stops the send there. A channel is the plug's code, and nothing made it enter the guard it
    was handed, so this enters the guard for it: consent is read under the store's write lock,
    and the channel is called only if it held, with a guard already decided.

    The lock is let go before the channel is called, as core's backend lets it go once the
    queue process is launched: calling the channel is this send's launch. Held across a
    transport core cannot see into - the lock being the advanced state's too once the claim
    attached it - a Pause, a disarm on another thread and the channel's own write all waited for
    it, and failed past SQLite's ten seconds. A Pause that commits once consent was read finds a
    send started, as it finds one of the backend's after its launch.

    `client_id` is handed on only when core gives one - a continuation it sends with no marker
    (P15) - so a channel that was never asked for that is called exactly as before.

    `concurrent` (v0.6.17): whether this send may wait for its receipt on a worker beside others (P12,
    engine/delivery.py) - what the plug's object said when it was named (its `pools()`), held to True itself;
    a channel that says nothing is sent inline, one at a time, as every channel was before."""
    __slots__ = ("_send", "concurrent")

    def __init__(self, send, concurrent=False):
        self._send, self.concurrent = send, concurrent is True

    def send(self, thread_id, prompt, *, launch_guard=None, client_id=None):
        with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
            pass
        if permitted is not True:
            return {"outcome": "not_started", "error_code": "queue_consent_refused"}
        if client_id is None:
            return self._send(thread_id, prompt, launch_guard=nullcontext(True))
        return self._send(thread_id, prompt, launch_guard=nullcontext(True), client_id=client_id)


class Route:
    """A route a plug named at P16, held to the launch guard as a channel is (`Channel`).

    Consent is read under the store's write lock, and the route is called only if it held, with
    a guard already decided and the lock let go - the route is the plug's code, and a transport
    core cannot see into, and a Pause or a disarm must never wait behind it. `resume` is the
    route's one method, and the only thing of it core ever calls.

    `still_unloaded` is core's own look at whether the app still does not hold the conversation
    (engine/delivery.py), handed on, when core gives one, for the route to ask at the last moment
    before it changes anything in Codex: the app may open the conversation while a session starts.

    `words` (v0.6.16-beta.4): a route that takes them - one whose plug object says `takes_words` - is
    handed the continuation core decided before the claim, as for a send, and the client id core
    derived; one that does not is called exactly as before."""
    __slots__ = ("_resume", "words")

    def __init__(self, resume, words=False):
        self._resume, self.words = resume, words is True

    @property
    def takes_words(self) -> bool:
        """Whether this route is handed core's words (`words`): what the plug's object said, held to True itself."""
        return self.words

    def resume(self, thread_id, *, launch_guard=None, still_unloaded=None, words=None, client_id=None):
        with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
            pass
        if permitted is not True:
            return {"outcome": "not_started", "error_code": "queue_consent_refused"}
        handed = {} if still_unloaded is None else {"still_unloaded": still_unloaded}
        if self.words:
            handed.update(words=words, client_id=client_id)
        return self._resume(thread_id, launch_guard=nullcontext(True), **handed)


class _Once:
    """One guard an errand asked for: entered once, and refused - False, no transaction - if it is
    entered again, so a guard is one irrevocable thing at most."""
    __slots__ = ("_make", "_used", "_held")

    def __init__(self, make):
        self._make, self._used, self._held = make, False, None

    def __enter__(self):
        if self._used:
            return False
        self._used = True
        self._held = self._make()
        return self._held.__enter__() is True

    def __exit__(self, *raised):
        held, self._held = self._held, None
        return bool(held.__exit__(*raised)) if held is not None else False


class Errand:
    """What a plug answered at P8 (v0.6.14): something with a callable `run`, held so that core
    calls it once, last in the tick, with a way to ask for guards and nothing else.

    `guard` is core's: each call makes one of the store's errand guards (store/claims.py), which an
    errand enters around the one write that cannot be taken back - a request made to Codex - and
    whose `permitted` says whether recovery is on, not only observed, not stopped by an administrator
    and outside quiet hours, read under the store's write lock: a Pause that committed first refuses
    it. Each guard enters once (`_Once`), and one errand asks for at most ERRAND_GUARDS of them a
    tick. What it reads, and what it waits for, it does outside them, as the queue launch lets the
    lock go before its receipt."""
    __slots__ = ("_run",)

    def __init__(self, run):
        self._run = run

    def run(self, guard):
        asked = []

        def one():
            asked.append(None)
            return _Once(guard if len(asked) <= ERRAND_GUARDS else (lambda: nullcontext(False)))
        return self._run(one)


def _record(found):
    """One record the plug handed over, as core takes it - a copy - or None for anything else."""
    if type(found) is not dict or not BASE_RECORD_KEYS <= set(found) <= RECORD_KEYS:
        return None
    key, thread, state, words, sent = (found["record_id"], found["thread_id"], found["state"], found["words"],
                                       found["sent_at"])
    # v0.6.15-beta's keys, each with what a record that names none of them is: a person's message, queued nowhere
    # Codex said, and no one asking for it back.
    purpose, ordinal = found.get("purpose", RecordPurpose.MESSAGE), found.get("ordinal")
    queue_id, withdraw = found.get("queue_id"), found.get("withdraw", False)
    keeps = found.get("pause_keeps", False)
    if type(keeps) is not bool:
        return None
    if (type(key) is not str or not ids.is_interruption_id(key) or ids.uuid_problem(thread) is not None
            or found["marker"] != ids.short_marker(key) or purpose not in tuple(RecordPurpose)):
        return None
    if purpose in (RecordPurpose.CONTINUATION, RecordPurpose.WRAP_UP):
        if type(ordinal) is not int or ordinal < 0:
            return None
    elif ordinal is not None:
        return None
    if state == "waiting":
        if (type(words) is not str or not 0 < len(words) <= WORDS_LIMIT or sent is not None or queue_id is not None
                or withdraw is not False):
            return None
    elif state == "in_flight":
        if (words is not None or not (sent is None or epoch(sent, *EPOCH_STORE, exact=True))
                or not (queue_id is None or ids.uuid_problem(queue_id) is None) or type(withdraw) is not bool):
            return None
    else:
        return None
    return {"record_id": key, "thread_id": thread, "marker": str(found["marker"]), "state": state,
            "words": words, "sent_at": None if sent is None else float(sent), "purpose": str(purpose),
            "ordinal": ordinal, "queue_id": queue_id, "withdraw": withdraw, "pause_keeps": keeps}


def records_of(answer) -> tuple:
    """The records of the plug's own core takes from P2's answer (v0.6.14): a list or a tuple of dicts,
    each with exactly RECORD_KEYS - a record id of 64 lowercase hex, a canonical conversation id, the
    marker core gives that id (ids.short_marker), and either `waiting` with words and no `sent_at`, or
    `in_flight` with no words and when it was sent, or None. Anything else is dropped, a record at a
    time, and past RECORDS_LIMIT the rest are; a second record of one id is the first's. DEFER, or
    anything that is not a list or a tuple, is none."""
    if type(answer) not in (list, tuple):
        return ()
    taken, seen = [], set()
    for found in answer[:RECORDS_LIMIT]:
        made = _record(found)
        if made is not None and made["record_id"] not in seen:
            seen.add(made["record_id"])
            taken.append(made)
    return tuple(taken)


def fields(answer, refused=None):
    """What a surface takes from a plug (P10, plug.Guarded.surface): a JSON object, copied, or `refused` - DEFER there.

    Words for keys, and nothing JSON cannot write strictly - no NaN, no infinity, no object of
    some other kind - so what a plug adds reaches a front end through the same writer as every
    reply (controlcli.encode) and cannot break it. It is copied through that writer's own form,
    so nothing the plug keeps a reference to changes a reply after it was made.

    A dict with str keys exactly, not a subclass of either: a subclass brings its own iteration,
    items and hashing, which are the plug's code running here, outside `consult`. Anything at all
    that goes wrong while it is copied is refused - a surface is the status, get_status and the
    Dashboard, which a strange answer must never break."""
    try:
        if type(answer) is not dict or not all(type(key) is str for key in answer):
            return refused
        return json.loads(json.dumps(answer, allow_nan=False))
    except Exception:
        return refused
