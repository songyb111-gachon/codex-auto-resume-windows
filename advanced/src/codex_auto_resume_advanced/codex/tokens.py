# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The tokens a conversation used, read from its rollout - four numbers and a count, never a word (v0.6.20,
usage_analytics; plans/v0619-design/D-analytics.md, "Sources, in order", source 2).

Codex writes a `token_count` event into a conversation's rollout after each model call: how many tokens that call
took in (`input_tokens`), how many of those came from its cache (`cached_input_tokens`), how many it wrote
(`output_tokens`) and how many of those it spent reasoning (`reasoning_output_tokens`), as `last_token_usage`, beside
the running `total_token_usage`. And a `task_started` event when a turn begins. Only those two kinds of line are ever
parsed, and only these numbers - and the event's time, as the local day it fell on - are kept of them; everything else
of the line, and every other line, is passed over by its bytes before any parse (B1, B7, B9: a line is looked at only
if it holds the bytes `"token_count"` or `"task_started"` and is at most LINE_BYTES).

Read-only like codex/turns.py, and with no database of its own: files are opened `rb`, never for writing (B2), and
each is read from where the last pass stopped (`token_files`, kept by state/analytics.py under a digest of its path,
never the path) to its end - at most FILE_BYTES of one file and PASS_BYTES in a pass, so a first pass over hundreds of
megabytes takes several. A file that shrank, or whose first line names another conversation, is read again from its
start, that file alone. The conversation is the one the file's first line says it is (core's codex/rollout
session_meta, 256 KiB at most), and its project the digest of the folder that line names, cut to 16 hex digits and the
folder dropped at once (B8) - the ingest prefers core's own project key for it (engine/analytics.py).

Which files: under each watched Codex home's `sessions` folder (the default home and those Settings add, core's
homes.py), `.jsonl` files changed in the last KEEP_DAYS - never a link, never one that resolves outside that home's
`sessions` folder (B5's confinement).
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
from pathlib import Path
import time
from typing import NamedTuple

from codex_auto_resume import homes as configured
from codex_auto_resume import projects
from codex_auto_resume.codex.paths import _safe_path
from codex_auto_resume.codex.rollout import session_meta
from codex_auto_resume.domain import ids

FILE_BYTES = 2 * 1024 * 1024          # read of one file in one pass, at most
PASS_BYTES = 8 * 1024 * 1024          # read of every file together in one pass, at most
LINE_BYTES = 64 * 1024                # a longer line is passed over unparsed
LOOK_BACK = 256 * 1024                # how far before where a pass begins it looks for the totals seen last
KEEP_DAYS = 90                        # a file not changed in this long is not read (state/journal's TOKENS_MAX_AGE)
TOKEN_BYTES = b'"token_count"'
TURN_BYTES = b'"task_started"'
# The four kinds kept, in the order token_days holds them.
KINDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
# A count larger than this is no count Codex wrote: the event is passed over.
MOST = 10 ** 13
# What became of one file in a pass.
READ, CAPPED, UNREADABLE, UNCHANGED = "read", "capped", "unreadable", "unchanged"
# How many files under one home's sessions folder are looked at, at most.
FILES_LIMIT = 20000


class Rollout(NamedTuple):
    """A rollout to read: its home, its path, its key (`file_key`) and what its stat said."""
    home: Path
    path: Path
    key: str
    size: int
    changed_ns: int


class Read(NamedTuple):
    """What one pass read of one file: its key, the conversation, where it now stands, and the numbers by local day -
    {day: [input, cached, output, reasoning, turns]} - with the project its first line names, as a 16-hex digest or
    None. Nothing else of the file."""
    key: str
    thread_id: str | None
    size: int
    offset: int
    changed_ns: int
    days: dict
    project_key: str | None
    outcome: str
    consumed: int


def file_key(path) -> str:
    """The key a rollout is known by: the first 16 hex digits of the SHA-256 of its resolved, case-folded path - the
    full path, so two homes' files never share one, and never the path itself."""
    resolved = os.path.normcase(str(_safe_path(Path(path))))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def watched_homes(paths) -> list:
    """Every Codex home the watcher watches: the default one (the watcher's, as told - codex/inuse.py), then those
    Settings add (core's homes.py), each once. A home that cannot be named is left out."""
    from . import inuse
    found = []
    try:
        found.append(Path(inuse.home(paths)))
    except Exception:
        pass
    try:
        from codex_auto_resume import config
        extra = configured.coerce(config.load_settings(paths).get(configured.FIELD) or [], [])
    except Exception:
        extra = []
    for entry in extra:
        try:
            found.append(Path(entry["path"]))
        except (KeyError, TypeError, ValueError):
            continue
    unique, seen = [], set()
    for home in found:
        try:
            marker = os.path.normcase(str(_safe_path(home)))
        except (OSError, RuntimeError, ValueError):
            continue
        if marker not in seen:
            seen.add(marker)
            unique.append(home)
    return unique


# The reparse tags that make an entry a link: a junction (a mount point) and a symbolic link.
_LINK_TAGS = (0xA0000003, 0xA000000C)


def _is_link(entry) -> bool:
    try:
        if entry.is_symlink():
            return True
        # A junction is a link Windows does not call a symbolic one.
        return getattr(os.stat(entry.path, follow_symlinks=False), "st_reparse_tag", 0) in _LINK_TAGS
    except OSError:
        return True


def rollouts(homes, now, *, keep_days=KEEP_DAYS) -> list:
    """The rollouts to read, newest first: every `.jsonl` file under each home's `sessions` folder changed in the last
    `keep_days`, found without following a link, and kept only where it resolves inside that folder."""
    found = []
    since_ns = int((now - keep_days * 86400) * 1e9)
    for home in homes:
        try:
            root = _safe_path(Path(home) / "sessions")
        except (OSError, RuntimeError, ValueError):
            continue
        if not root.is_dir():
            continue
        stack, seen = [root], 0
        while stack and seen < FILES_LIMIT:
            folder = stack.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                if _is_link(entry):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if not entry.name.endswith(".jsonl") or not entry.is_file(follow_symlinks=False):
                        continue
                    seen += 1
                    stat = entry.stat(follow_symlinks=False)
                    path = _safe_path(Path(entry.path))
                except (OSError, RuntimeError, ValueError):
                    continue
                if not path.is_relative_to(root) or stat.st_mtime_ns < since_ns:
                    continue
                found.append(Rollout(Path(home), path, file_key(path), stat.st_size, stat.st_mtime_ns))
    found.sort(key=lambda rollout: rollout.changed_ns, reverse=True)
    return found


def unchanged(rollout, known) -> bool:
    """Whether `rollout` has nothing new since `known` (its token_files row): the same size and time, read to its end."""
    return (known is not None and known.get("mtime_ns") == rollout.changed_ns and known.get("size") == rollout.size
            and known.get("offset", 0) >= rollout.size)


def _first(path):
    """(the conversation id, the 16-hex digest of the folder) its first line names - each None where it does not."""
    payload = session_meta(path)
    if not isinstance(payload, dict):
        return None, None
    thread = payload.get("id")
    thread = thread.lower() if isinstance(thread, str) else None
    digest = projects.key_for(cwd=payload.get("cwd"))
    return (thread if ids.is_uuid(thread) else None), (digest[:16] if digest else None)


def _epoch(stamp):
    """An event's `timestamp` (Codex writes UTC, `2026-10-22T03:04:05.123Z`) in seconds, or None."""
    if not isinstance(stamp, str) or len(stamp) < 19:
        return None
    try:
        return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def _counts(value):
    """The four kinds of a usage object as whole numbers, or None where any is missing or not one."""
    if not isinstance(value, dict):
        return None
    numbers = [value.get(kind) for kind in KINDS]
    if not all(type(number) is int and 0 <= number <= MOST for number in numbers):
        return None
    return numbers


def _event(line):
    """A line's (type, payload, seconds), parsed - None for one that is not an event of the two kinds read."""
    try:
        event = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return None
    if not isinstance(event, dict) or event.get("type") != "event_msg":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") not in ("token_count", "task_started"):
        return None
    at = _epoch(event.get("timestamp"))
    if at is None:
        return None
    return payload["type"], payload, at


def _totals_before(stream, offset):
    """The running totals of the last token_count event before `offset`, from at most LOOK_BACK bytes before it - so
    a pass that begins where the last one stopped knows what the last one saw, and neither counts a repeat of them nor
    loses a difference across the boundary. None where there is none."""
    back = min(offset, LOOK_BACK)
    if back <= 0:
        return None
    stream.seek(offset - back)
    data = stream.read(back)
    if offset - back > 0:
        data = data[data.find(b"\n") + 1:] if b"\n" in data else b""
    for line in reversed(data.split(b"\n")):
        if len(line) > LINE_BYTES or TOKEN_BYTES not in line:
            continue
        found = _event(line)
        if found is not None and found[0] == "token_count" and isinstance(found[1].get("info"), dict):
            totals = _counts(found[1]["info"].get("total_token_usage"))
            if totals is not None:
                return totals
    return None


def read(rollout, known, budget, *, local=time.localtime) -> Read:
    """One pass over `rollout` from where `known` (its token_files row, or None) says it stopped, reading at most
    min(FILE_BYTES, `budget`) bytes: the numbers of every whole line read, by the local day of its event (`local`, a
    seam a test fills), and where the next pass begins. A file that cannot be opened is UNREADABLE and left where it
    was."""
    def nothing(outcome, thread=None, offset=0, project=None, consumed=0):
        return Read(rollout.key, thread, rollout.size, offset, rollout.changed_ns, {}, project, outcome, consumed)

    try:
        thread, project = _first(rollout.path)
    except OSError:
        return nothing(UNREADABLE, offset=(known or {}).get("offset", 0))
    if thread is None:
        # No conversation named: the file is passed over whole, so it is not looked at again until it changes.
        return nothing(UNREADABLE, offset=rollout.size)
    offset = (known or {}).get("offset", 0)
    if known is None or known.get("thread_id") != thread or rollout.size < offset:
        offset = 0                                     # new, another conversation's now, or shrunk: from its start
    allowed = max(0, min(FILE_BYTES, budget))
    if allowed == 0 or offset >= rollout.size:
        return nothing(UNCHANGED if offset >= rollout.size else CAPPED, thread, offset, project)
    try:
        with rollout.path.open("rb") as stream:
            previous = _totals_before(stream, offset)
            stream.seek(offset)
            chunk = stream.read(allowed)
    except OSError:
        return nothing(UNREADABLE, thread, offset, project)
    end = chunk.rfind(b"\n")
    if end < 0:
        # No whole line: one longer than the read is skipped past; one still being written waits for the next pass.
        moved = len(chunk) if len(chunk) >= allowed else 0
        return nothing(CAPPED if moved else UNCHANGED, thread, offset + moved, project, len(chunk))
    started_at_zero = offset == 0
    days = {}
    for line in chunk[:end].split(b"\n"):
        if len(line) > LINE_BYTES or (TOKEN_BYTES not in line and TURN_BYTES not in line):
            continue
        found = _event(line)
        if found is None:
            continue
        kind, payload, at = found
        day = time.strftime("%Y-%m-%d", local(at))
        if kind == "task_started":
            days.setdefault(day, [0, 0, 0, 0, 0])[4] += 1
            continue
        info = payload.get("info")
        if not isinstance(info, dict):
            continue
        total, last = _counts(info.get("total_token_usage")), _counts(info.get("last_token_usage"))
        if total is not None and total == previous:
            continue                                   # the same totals again (a rate-limit update): nothing new
        if last is not None:
            numbers = last
        elif total is not None and previous is not None:
            numbers = [max(0, now - before) for now, before in zip(total, previous)]
        elif total is not None and started_at_zero:
            numbers = total
        else:
            numbers = None
        if total is not None:
            previous = total
        if numbers is None:
            continue
        kept = days.setdefault(day, [0, 0, 0, 0, 0])
        for index in range(4):
            kept[index] += numbers[index]
    consumed = end + 1
    outcome = CAPPED if offset + consumed < rollout.size and len(chunk) >= allowed else READ
    return Read(rollout.key, thread, rollout.size, offset + consumed, rollout.changed_ns, days, project, outcome,
                consumed)
