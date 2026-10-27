"""A conversation's rollout file, read no further than this product needs (v0.6.16-beta.3).

None of these readings is a statement to a database - codex/history.py keeps every one:

    confined       which file a `threads` row's path names, if it is that conversation's in the sessions folder
    session_meta   the file's first line: who the conversation says it is
    continued_id   the id Codex records the conversation's turns under, where it split them
    earlier        the ids it recorded them under before, by the names of its earlier files
    named_after    the conversations whose file names an id as theirs, by name
    reset_scan     the rate-limit snapshots just before a usage-limit failure, for the reset hint
    superseded_in  whether a person's message came after a failed turn's end, for Rescan and reconcile (issue #39)
    turn_trigger   how Codex says a turn was started - "composer" is the person's input box (issue #54)

The split is Codex's (openai/codex#43422, this project's issue #30): the `threads` row keeps the
conversation's id A, but its current file is named `..._A_B.jsonl` and its turns are projected under B,
which has no row of its own - and a later split names `..._A_C.jsonl` while B's turns stay under B. Its
turns are every id's, in that order (`SPAN`); whether an id is taken is history.py's (`_chain`), with every
guard. Only file names are looked at here, never a file's contents.
"""
from __future__ import annotations

from pathlib import Path
import re
import time

from ..domain import ids
from .paths import _safe_path
from .payload import _choose_reset
from .values import MAX_ITEM_BYTES, MAX_META_BYTES, MAX_SCAN_BYTES, _json

UNKNOWN_RESET = {"reset_at": None, "limit_type": "unknown", "uncertain": True}
# What `superseded_in` finds (v0.6.16, issue #39): a person's message after the failed turn's own end; that end and
# nothing of a person's after it; not that end at all; a file over RESCAN_BYTES; a file that cannot be read; and a
# rollback - or a line that cannot be read - after that end, past which nothing in the file is proof of anything.
LATER_MESSAGE, NOTHING_LATER, NO_ANCHOR, TOO_LARGE, UNREADABLE, ROLLED_BACK = (
    "later_message", "nothing_later", "no_anchor", "too_large", "unreadable", "rolled_back")
# What a rollback is written with (Codex's thread_rolled_back event): any line after the anchor that holds it.
_ROLLBACK = b"rolled_back"
# The largest file it reads, start to end, only when a person asks for it.
RESCAN_BYTES = 32 * 1024 * 1024
_OURS = ids.MARKER_PREFIX.encode("utf-8")
_TRIGGERS = {}                   # (file, turn id) -> the trigger found; a turn's is written once and never changes
# A turn's ordinal across a split conversation: the index of the id it is recorded under (A's own 0, then each
# split id in order) times SPAN, plus its own rollout ordinal - so a turn of a later id always comes after every
# turn of an earlier one, whatever Codex numbered it, and a conversation never split reads its ordinals as they are.
SPAN = 1 << 40
# The split files of each Codex home by name, looked at again at most every LIST_SECONDS: one listing for every
# conversation, names only.
LIST_SECONDS = 60.0
AGAIN = 5
_SPLITS, _ASKED, _RELISTED = {}, set(), {}


def _splits(home, fresh=False) -> dict:
    """{conversation id: ((split id, file), ...) oldest first} for every file under the home's sessions folder
    named `<id>_<id>.jsonl` - by name only, nothing opened, no link followed; none where it cannot be listed."""
    key, now = str(home), time.monotonic()
    held = _SPLITS.get(key)
    if held is None or fresh or now - held[0] > LIST_SECONDS:
        found = {}
        pattern = re.compile(r"(%s)_(%s)\.jsonl\Z" % (ids.uuid_pattern(any_case=True), ids.uuid_pattern(any_case=True)))
        try:
            names = sorted((path for path in (Path(home) / "sessions").rglob("*_*.jsonl") if path.is_file()),
                           key=lambda path: path.name)
        except OSError:
            names = []
        for path in names:
            match = pattern.search(path.name)
            if match and continued_id(match.group(1), path.name) == match.group(2):
                found.setdefault(match.group(1), []).append((match.group(2), path))
        held = _SPLITS[key] = (now, {owner: tuple(pairs) for owner, pairs in found.items()})
    return held[1]


def earlier(home, thread_id, current) -> tuple:
    """((id, file), ...): the ids before `current` that `thread_id`'s earlier files name as `<thread_id>_<id>`, oldest
    first by file name (Codex starts each name with its time)."""
    pairs = _splits(home).get(thread_id, ())
    if (str(home), thread_id, current) not in _ASKED and all(pair[0] != current for pair in pairs):
        if len(_ASKED) > 4096:
            _ASKED.clear()
        _ASKED.add((str(home), thread_id, current))              # a split newer than the listing: list again, once
        pairs = _splits(home, fresh=True).get(thread_id, ())
    return tuple(pair for pair in pairs if pair[0] != current)


def taken(chain, rows) -> set:
    """The ids of `chain` that are no split id of the conversation's: one with a `threads` row of its own, or one
    another conversation's file names (`rows`: (id, rollout_path) of those rows)."""
    return {other for other in chain for row_id, path in rows
            if row_id == other or (isinstance(path, str) and other in path)}


_META = {}


def meta_id(path):
    """The id an earlier file's first line says it is (session_meta), read once and remembered - None for none."""
    key = str(path)
    if key not in _META:
        try:
            payload = session_meta(Path(path))
        except OSError:
            return None
        if len(_META) >= 4096:
            _META.pop(next(iter(_META)))
        _META[key] = payload.get("id") if payload else None
    return _META[key]


def named_after(home, turns_id) -> tuple:
    """The conversation ids whose files, by name and first line, hold `turns_id`'s turns (`<id>_<turns_id>.jsonl`) -
    listed again, once for each id and at most AGAIN times a minute, where the listing names none: a split newer than the listing
    is found at once, and many ids no file names cost a few listings."""
    def named(listing):                     # a file whose first line is another conversation's names no one
        return tuple(owner for owner, pairs in listing.items()
                     if any(other == turns_id and meta_id(file) == owner for other, file in pairs))
    found = named(_splits(home))
    now = time.monotonic()
    recent = _RELISTED.setdefault(str(home), [])
    recent[:] = [at for at in recent if now - at < LIST_SECONDS]
    if not found and (str(home), turns_id) not in _ASKED and len(recent) < AGAIN:
        if len(_ASKED) > 4096:
            _ASKED.clear()
        _ASKED.add((str(home), turns_id))
        recent.append(now)
        found = named(_splits(home, fresh=True))
    return found


def placed(row, owner, index) -> dict:
    """A turn's row as its conversation's: `owner`'s id, and its ordinal across the split (SPAN) - itself for a
    conversation never split, where `index` is 0."""
    ordinal = row["rollout_ordinal"]
    return dict(row, thread_id=owner, rollout_ordinal=index * SPAN + ordinal if type(ordinal) is int else ordinal)


def confined(home, thread_id, raw):
    """`raw`, the rollout path Codex's `threads` row names, as a Path if it is this conversation's file in the
    Codex home `home`'s sessions folder: a .jsonl file whose name holds the id. None for anything else, which
    is then neither opened nor asked about."""
    if not ids.is_uuid(thread_id) or not isinstance(raw, str):
        return None
    path = _safe_path(Path(raw))
    if (not path.is_relative_to(_safe_path(Path(home) / "sessions"))
            or path.suffix != ".jsonl" or thread_id not in path.name):
        return None
    return path


def session_meta(path) -> dict | None:
    """The payload of the file's first line where it is a session_meta event, or None. An OSError is the
    caller's: a file that cannot be opened now is not a file that says nothing."""
    with path.open("rb") as stream:
        first = stream.readline(MAX_META_BYTES + 1)
    if len(first) > MAX_META_BYTES or not first.endswith(b"\n"):
        return None
    try:
        event = _json(first.decode("utf-8"))
    except UnicodeError:
        return None
    if not isinstance(event, dict) or event.get("type") != "session_meta":
        return None
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else None


def continued_id(thread_id, name) -> str | None:
    """B, where the file name `name` ends exactly in `<thread_id>_<B>.jsonl` and B is another id; else None."""
    if not ids.is_uuid(thread_id) or not isinstance(name, str):
        return None
    found = re.search(r"(?:^|[-_])%s_(%s)\.jsonl\Z" % (re.escape(thread_id), ids.uuid_pattern(any_case=True)), name)
    other = found.group(1) if found else None
    return other if other is not None and ids.is_uuid(other) and other != thread_id else None


def reset_scan(path, end, turn_id, completed_at) -> dict:
    """The reset hint of the usage-limit failure of `turn_id`, whose event ends at byte `end` of `path`: the
    rate-limit snapshots before it, chosen as payload._choose_reset chooses - or UNKNOWN_RESET."""
    if type(end) is not int or end <= 0:
        return dict(UNKNOWN_RESET)
    try:
        # The verified end offset is immediately after the failure event.
        # Never include a subsequent turn's unrelated rate-limit snapshot.
        with path.open("rb") as stream:
            start = max(0, end - MAX_SCAN_BYTES)
            stream.seek(start)
            if start:
                stream.readline(MAX_ITEM_BYTES + 1)
            remaining = end - stream.tell()
            if remaining <= 0:
                return dict(UNKNOWN_RESET)
            data = stream.read(min(MAX_SCAN_BYTES, remaining))
    except (OSError, ValueError):
        return dict(UNKNOWN_RESET)
    buckets = {}
    found = False
    for line in data.splitlines():
        if len(line) > MAX_ITEM_BYTES:
            continue
        try:
            event = _json(line.decode("utf-8"))
        except UnicodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "event_msg":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "task_complete" and payload.get("turn_id") == turn_id:
            error = payload.get("error")
            found = isinstance(error, dict) and error.get("codex_error_info") == "usage_limit_exceeded"
            break
        if payload.get("type") == "token_count":
            limits = payload.get("rate_limits")
            if isinstance(limits, dict):
                bucket = limits.get("limit_id")
                if isinstance(bucket, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", bucket):
                    buckets[bucket] = limits
    return _choose_reset(buckets, completed_at) if found else dict(UNKNOWN_RESET)


def superseded_in(path, turn_id, limit=None) -> str:
    """Whether the file holds the exact end of the failed turn `turn_id` - its own task_complete event - and, after it, a
    person's message: a user_message event that carries no marker of this product's (ids.MARKER_PREFIX, which every
    continuation and every message the product writes carries). Read only on a person's Rescan and reconcile, and only
    while Codex's history has not caught up with the file (rescan.py): the file whole, up to `limit` bytes, one line at
    a time, each line parsed and dropped. Nothing of what a line says is kept; the answer is one of six words.

    A line over MAX_ITEM_BYTES, a line that is not JSON and any event but those two are passed over, which can only
    lose an answer, never make one: no anchor, nothing later. Where a person's message comes before that end, it is
    not after it, so a conversation's earlier work - or a file that replays it (a split's, issue #30) - proves nothing.

    A rollback undoes turns, and only Codex's history - which the engine reads, and which a rollback rewrites - says
    which. So the whole file is read, and a rollback anywhere after the anchor (`_ROLLBACK`, whatever its event), or a
    line after it that cannot be read and so could be one, means nothing after the anchor proves anything: ROLLED_BACK,
    never LATER_MESSAGE, though a person's message came before it."""
    try:
        size = path.stat().st_size
        if size > (RESCAN_BYTES if limit is None else limit):
            return TOO_LARGE
        anchored, later, doubt, read = False, False, False, 0
        with path.open("rb") as stream:
            while read < size:
                line = stream.readline(MAX_ITEM_BYTES + 1)
                if not line:
                    break
                read += len(line)
                if len(line) > MAX_ITEM_BYTES:
                    while line and not line.endswith(b"\n"):             # the rest of a line too long to read
                        line = stream.readline(MAX_ITEM_BYTES + 1)
                        read += len(line)
                    doubt = doubt or anchored
                    continue
                if anchored and _ROLLBACK in line:
                    doubt = True
                    continue
                if b'"event_msg"' not in line:
                    continue
                try:
                    event = _json(line.decode("utf-8"))
                except UnicodeError:
                    event = None
                if not isinstance(event, dict):
                    doubt = doubt or anchored
                    continue
                payload = event.get("payload") if event.get("type") == "event_msg" else None
                if not isinstance(payload, dict):
                    continue
                if not anchored:
                    anchored = payload.get("type") == "task_complete" and payload.get("turn_id") == turn_id
                elif payload.get("type") == "user_message" and _OURS not in line:
                    later = True
    except (OSError, ValueError):
        return UNREADABLE
    if not anchored:
        return NO_ANCHOR
    return ROLLED_BACK if doubt else LATER_MESSAGE if later else NOTHING_LATER


def turn_trigger(path, turn_id=None) -> str | None:
    """The turn_attribution.turn_trigger Codex wrote for the turn `turn_id` in its task_started event (issue #54,
    measured on codex-cli 0.164) - else for the last turn the file starts: the file read once, up to RESCAN_BYTES, a line
    at a time, each dropped after it is looked at. None is unknown - an older Codex wrote no attribution, the turn is not
    in this file, the file is too large or cannot be read - and is never a value; an OSError is the caller's, as
    session_meta's is."""
    key = (str(path), turn_id)
    if key in _TRIGGERS:
        return _TRIGGERS[key]
    if turn_id is not None and not ids.is_uuid(turn_id) or path.stat().st_size > RESCAN_BYTES:
        return None
    wanted, found = None if turn_id is None else turn_id.encode("utf-8"), None
    with path.open("rb") as stream:
        while True:
            line = stream.readline(MAX_ITEM_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_ITEM_BYTES:
                while line and not line.endswith(b"\n"):
                    line = stream.readline(MAX_ITEM_BYTES + 1)
                continue
            if b'"task_started"' not in line or (wanted is not None and wanted not in line):
                continue
            try:
                event = _json(line.decode("utf-8"))
            except UnicodeError:
                continue
            payload = event.get("payload") if isinstance(event, dict) and event.get("type") == "event_msg" else None
            if not isinstance(payload, dict) or payload.get("type") != "task_started":
                continue
            if turn_id is not None and payload.get("turn_id") != turn_id:
                continue
            attribution = payload.get("turn_attribution")
            value = attribution.get("turn_trigger") if isinstance(attribution, dict) else None
            found = value if isinstance(value, str) else None
            if turn_id is not None:
                break
    if found is not None and turn_id is not None:                 # a turn's trigger is written once and never changes
        if len(_TRIGGERS) >= 4096:
            _TRIGGERS.pop(next(iter(_TRIGGERS)))
        _TRIGGERS[key] = found
    return found
