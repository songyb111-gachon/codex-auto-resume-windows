"""Every identifier the product reads or writes, and the one parser for each kind.

Recovery is exact or it does not happen: a continuation goes to the one conversation that was
interrupted, named by its id, never to "the latest" or to one that looks like it. So an id is
read strictly everywhere, and it is read here - the store, the history reader, the Codex
adapter, the control layer, the command line, the MCP server, a notification's button, the log
and the diagnostics bundle all used to carry a pattern or a parser of their own.

The kinds:

* **Codex's UUIDs** - a conversation (`ThreadId`), a turn (`TurnId`), a queued message
  (`QueueId`), the turn a continuation started (`RecoveryTurnId`) - always as canonical text:
  lowercase hex in groups of 8-4-4-4-12, with nothing around it.
* **An interruption** (`InterruptionId`): 64 lowercase hex digits, which `interruption_id`
  makes from the failed turn. A chain of continuations is named by the id of the interruption
  that began it (`ChainOriginId`).
* **The marker** (`Marker`) a continuation carries, `[codex-auto-resume:<16 hex>]` - the first
  16 of the interruption id's 64 digits, from v0.6.11, and the whole id before it: how the engine
  finds its own message in Codex's history, and knows it for its own. Both are read.
* **A client id** (`ClientId`) Codex gives a queued message: 1 to 64 letters, digits and dashes.
* **A watcher session** (`SessionId`), and **a moment** (`Epoch`, seconds since 1970, which
  `machine.epoch` reads).

The readers of one kind do not all accept the same things, and each keeps what it had; where
they differ, the parser takes a parameter, and the difference is written down with it:

* The control layer reads any value as its text - a `uuid.UUID` passes as its canonical text -
  while the command line and everything else take only a `str` (`uuid_problem`, `as_text`).
  Each says why it refuses in its own words, and both tell a UUID merely written another way
  (capitals, braces, a urn, no dashes) from something that is no UUID at all.
* An interruption id handed over by a person or a link has its surrounding white space dropped
  and its capitals lowered first (`read_interruption_id`); everywhere else it is taken exactly.
* The store keeps as the key of a record, of its parent and of its chain anything it has ever
  kept - 1 to 128 letters, digits, `_` and `-` - which is wider than an id `interruption_id`
  makes (`is_interruption_id`, `as_stored`).

Pure: the standard library only, and none of it touches a file, a process or the clock.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import NewType
import uuid

ThreadId = NewType("ThreadId", str)
TurnId = NewType("TurnId", str)
QueueId = NewType("QueueId", str)
RecoveryTurnId = NewType("RecoveryTurnId", str)
ClientId = NewType("ClientId", str)
InterruptionId = NewType("InterruptionId", str)
ChainOriginId = NewType("ChainOriginId", str)
Marker = NewType("Marker", str)
SessionId = NewType("SessionId", str)
Epoch = NewType("Epoch", float)


# --------------------------------------------------------------------------- Codex's UUIDs
MALFORMED = "malformed"              # not a UUID at all
NOT_CANONICAL = "not_canonical"      # a UUID, written some other way than the canonical text

# The groups of a UUID's text, and so the pattern that finds one.
_GROUPS = (8, 4, 4, 4, 12)


def uuid_pattern(*, any_case: bool = False) -> str:
    """A regular expression for a UUID's canonical text, with no anchors: lowercase only, or
    either case for a reader that finds ids in text a person wrote (the diagnostics bundle)."""
    digit = "[0-9a-fA-F]" if any_case else "[0-9a-f]"
    return "-".join("%s{%d}" % (digit, size) for size in _GROUPS)


# What the MCP tools publish as a conversation id's JSON Schema pattern.
THREAD_ID_SCHEMA = "^%s$" % uuid_pattern()


def uuid_problem(value, *, as_text: bool = False):
    """None when `value` is a UUID in canonical text; otherwise why not: `NOT_CANONICAL` for a
    UUID written some other way, which a reader may refuse with a sentence that says so, and
    `MALFORMED` for anything else.

    Only a `str` is text - unless `as_text`, when any value is read as `str(value)`, which is
    what the control layer has always done. The canonical text is exactly what `uuid.UUID`
    writes back, so the question is asked of Python's own parser and answered by comparison."""
    try:
        text = str(value) if as_text else value
        if not isinstance(text, str):
            return MALFORMED
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError, TypeError):
        return MALFORMED
    return None if str(parsed) == text else NOT_CANONICAL


def is_uuid(value) -> bool:
    """Whether `value` is a thread, turn or queue id: a `str` holding a UUID's canonical text."""
    return uuid_problem(value) is None


# ------------------------------------------------------------------------- interruption ids
INTERRUPTION_ID_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")
# What the MCP tools publish as an interruption id's JSON Schema pattern: either case, because
# the control layer lowers what it is handed (`read_interruption_id`).
INTERRUPTION_ID_SCHEMA = "^[0-9a-fA-F]{%d}$" % INTERRUPTION_ID_LENGTH
# Every key the store has ever kept for a record, its parent or its chain.
_STORED_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def interruption_id(thread_id, turn_id, completed_at, ordinal) -> InterruptionId:
    """The id of a failed turn: SHA-256, as lowercase hex, of the compact JSON array
    `[thread_id, turn_id, float(completed_at).hex(), ordinal]`, ASCII-encoded.

    Written once and recomputed at every look for as long as the record lives, so it never
    changes: a failure computed to another id is a new interruption, and a second recovery of
    one already recovered. `float.hex()` gives a whole second one spelling whether Codex wrote
    it as an int or a float (tests/test_domain_vectors.py holds the vectors)."""
    identity = [thread_id, turn_id, float(completed_at).hex(), ordinal]
    text = json.dumps(identity, separators=(",", ":"), allow_nan=False)
    return InterruptionId(hashlib.sha256(text.encode("ascii")).hexdigest())


def stalled_id(thread_id, turn_id) -> InterruptionId:
    """The key a needs-you notice about a turn that stopped moving is kept under (v0.6.11): SHA-256,
    as lowercase hex, of the compact JSON array `["stalled", thread_id, turn_id]`. Three members where
    an interruption's id has four, so it is never one; and one turn is told once, however long it
    stays still."""
    text = json.dumps(["stalled", thread_id, turn_id], separators=(",", ":"), allow_nan=False)
    return InterruptionId(hashlib.sha256(text.encode("ascii")).hexdigest())


def is_digest(value) -> bool:
    """Whether `value` is a SHA-256 as the product writes one: 64 lowercase hex digits, with nothing
    around them. What an interruption id is, and - from v0.6.11 - a project's key (projects.py) and
    what the task-changed guard keeps of a task (guards.py): one rule for all three."""
    return (isinstance(value, str) and len(value) == INTERRUPTION_ID_LENGTH
            and all(character in _HEX_DIGITS for character in value))


def is_interruption_id(value, *, as_stored: bool = False) -> bool:
    """Whether `value` is exactly an id `interruption_id` makes: 64 lowercase hex digits.

    `as_stored` asks instead whether the store would keep it as a record's key, or its
    parent's, or its chain's: 1 to 128 letters, digits, `_` and `-`, as it always has."""
    if as_stored:
        return isinstance(value, str) and _STORED_KEY.fullmatch(value) is not None
    return is_digest(value)


def read_interruption_id(text: str):
    """The interruption id in `text` as a person or a link hands one over - surrounding white
    space dropped, capitals lowered - or None when what is left is not exactly an id."""
    candidate = text.strip().lower()
    return candidate if is_interruption_id(candidate) else None


# ------------------------------------------------------------------------------- markers
MARKER_PREFIX = "[codex-auto-resume:"
# How many of an interruption id's 64 hex digits the marker carries, from v0.6.11 (the owner:
# the whole id was more than a person needs to see at the end of every continuation). A marker is
# only ever looked for inside the one conversation its record belongs to, and a record is never
# given one another record of that conversation already has (store/records.py), so 16 digits
# tell every continuation of a conversation apart as surely as 64 did. The closing `]` keeps the
# two lengths apart: neither is ever found inside the other.
SHORT_MARKER_DIGITS = 16


def marker(key) -> Marker:
    """The marker of the whole key: the prefix, the key, `]`. What every continuation carried
    before v0.6.11, and still carries where its short one is taken (store/records.py)."""
    return Marker(f"{MARKER_PREFIX}{key}]")


def short_marker(key) -> Marker:
    """The marker a new record's continuation carries from v0.6.11: the prefix, the first 16 hex
    digits of its interruption id, `]`. A stored key that is not an id `interruption_id` makes -
    which only a test writes - keeps the marker of the whole key."""
    return marker(key[:SHORT_MARKER_DIGITS] if is_interruption_id(key) else key)


def record_markers(key) -> tuple:
    """Every marker a record of `key` may carry: its short one, and the one of the whole key
    that a record made before v0.6.11 carries (one, when the two are the same)."""
    return tuple(dict.fromkeys((short_marker(key), marker(key))))


def is_marker(value) -> bool:
    """Whether `value` is exactly the marker of an interruption id - of all 64 digits, or of the
    first 16 - with nothing around it. The history reader looks for no other: this is the text its
    queries search Codex for."""
    if not (isinstance(value, str) and value.startswith(MARKER_PREFIX) and value.endswith("]")):
        return False
    body = value[len(MARKER_PREFIX):-1]
    return is_interruption_id(body) or (
        len(body) == SHORT_MARKER_DIGITS and all(character in _HEX_DIGITS for character in body))


# ----------------------------------------------------------------------------- client ids
_CLIENT_ID = re.compile(r"[A-Za-z0-9-]{1,64}\Z")


def is_client_id(value) -> bool:
    """Whether `value` is a client id Codex may give a queued message: 1 to 64 letters, digits
    and dashes. Anything else is not kept: the store and the history reader record None."""
    return isinstance(value, str) and _CLIENT_ID.fullmatch(value) is not None
