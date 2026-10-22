"""Words for this time (v0.6.16-beta.3): a person's own words added, once, to one waiting interruption's next
continuation.

A person picks one waiting recovery on the Dashboard's Pending page and writes a few words for it. When that
recovery's limit lifts and its continuation is built (before the claim, A26), the words go after the usual
continuation text, one blank line between - and only that once. The continuation carrying them is the one handed
to Codex; once it is, the words are deleted, whatever delivery then proves, and they are deleted too when the
interruption ends without a send (recovered otherwise, cancelled, expired, superseded). Adding words never starts,
speeds or skips anything: every gate is the same with or without them.

Where they are kept: config/once-words.json, one small file beside the state, of this shape:

    {"<64-hex interruption id>": {"text": "...", "written_at": 1760000000.0}, ...}

Out of the store, whose schema is final for a beta (no schema moves, nothing for a downgrade to carry), and out of
settings.json, which is policy and which the Dashboard's Save writes whole. Older versions never read it. The text
is a Custom message in every way (A27): written only in the Dashboard, at most 2000 characters, sent exactly as
typed, the same placeholder whitelist, and checked again every time it is read - an entry that fails is treated as
not set, and a file that cannot be believed is read as holding nothing. The file is removed when it holds nothing.

Each write takes one named lock (the one this file's path names, as control/poweraction.py takes for its file),
rereads, decides and replaces the file whole (a temporary file of a name nobody can plant a link at, flushed to
disk, then moved over it). Without the lock nothing is written. Nothing here sends anything.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time

from . import config, continuation
from .domain import ids
from .windows import Mutex

FILE_NAME = "once-words.json"
# At most this many interruptions hold words at once: Pending rarely lists more, and a file of a few hundred KiB
# at the most is one every reader can take whole.
MAX_ENTRIES = 50
FILE_LIMIT = 512 * 1024
LOCK_SECONDS = 5.0
# As control/poweraction.py: a reader holding the file open refuses a replace for as long as its one read takes.
REPLACE_TRIES = 20
REPLACE_PAUSE = 0.025

READ_OK, READ_MISSING, READ_INVALID, READ_UNREADABLE = "ok", "missing", "invalid", "unreadable"


class OnceWordsError(ValueError):
    """Words that will not be stored, or a store that could not be written. `code` is a control refusal code."""

    def __init__(self, message, code="request_failed"):
        super().__init__(message)
        self.code = code


def validate(text) -> str:
    """The words unchanged, or continuation.CustomMessageError: the Custom message's own check (A27)."""
    return continuation.validate_custom(text)


def entries(document) -> dict:
    """The entries of a document that may be believed, each checked again (A27): an opaque interruption id, written
    as the store writes one, holding text a Custom message may hold and the time it was written. Anything else is
    left out, as a Custom message that fails its check is read as not set; more than MAX_ENTRIES is nothing."""
    if not isinstance(document, dict) or len(document) > MAX_ENTRIES:
        return {}
    kept = {}
    for key, entry in document.items():
        if not isinstance(key, str) or ids.read_interruption_id(key) != key or not isinstance(entry, dict):
            continue
        written = entry.get("written_at")
        if isinstance(written, bool) or not isinstance(written, (int, float)) or not math.isfinite(written) \
                or written < 0:
            continue
        try:
            text = validate(entry.get("text"))
        except continuation.CustomMessageError:
            continue
        kept[key] = {"text": text, "written_at": float(written)}
    return kept


def read_file(path):
    """(why, entries): READ_OK and what may be believed; or READ_MISSING and nothing (no file), READ_INVALID and
    nothing (a link, too large, or not JSON), READ_UNREADABLE and nothing (one that could not be read just now)."""
    try:
        if config.is_link(path):
            return READ_INVALID, {}
        size = path.stat().st_size
    except FileNotFoundError:
        return READ_MISSING, {}
    except OSError:
        return READ_UNREADABLE, {}
    if size > FILE_LIMIT:
        return READ_INVALID, {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return READ_MISSING, {}
    except UnicodeError:
        return READ_INVALID, {}
    except OSError:
        return READ_UNREADABLE, {}
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        return READ_INVALID, {}
    return (READ_OK, entries(document)) if isinstance(document, dict) else (READ_INVALID, {})


def _replace(temporary, path):
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_PAUSE)


def _write(path, held) -> bool:
    """`held` to `path` whole, or the file removed when it holds nothing: False where Windows refused, with nothing
    left behind."""
    if not held:
        try:
            if path.exists() or config.is_link(path):
                path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False
    try:
        descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix="once-words.", suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(held, handle, allow_nan=False, sort_keys=True, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(temporary, path)
        return True
    except (OSError, ValueError, TypeError):
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False


class OnceWords:
    """The words for this time of one state folder: read by anyone, written under the file's one lock."""

    def __init__(self, path):
        self.path = path

    @classmethod
    def of(cls, paths):
        return cls(paths.once_words_file)

    # ------------------------------------------------------------------ reading
    def held(self) -> dict:
        """Every entry that may be believed now (interruption id -> {text, written_at})."""
        return read_file(self.path)[1]

    def words(self, key):
        """This interruption's words, checked again as they are read, or None."""
        entry = self.held().get(key) if isinstance(key, str) else None
        return entry["text"] if entry else None

    def count(self) -> int:
        return len(self.held())

    # ------------------------------------------------------------------ writing
    def _change(self, change):
        """Take the lock, reread, `change` the entries (which returns the answer), and write them back if they moved.
        (answer, written): written is False where the lock or Windows refused, and then nothing was changed. A file
        that could not be read just now is never written over."""
        if not self.path.parent.is_dir():
            return None, False
        try:
            lock = Mutex(str(self.path), timeout=LOCK_SECONDS)
            lock.__enter__()
        except Exception:
            return None, False
        try:
            why, held = read_file(self.path)
            if why == READ_UNREADABLE:
                return None, False
            before = dict(held)
            answer = change(held)
            if held == before and why != READ_INVALID:
                return answer, True
            return answer, _write(self.path, held)
        finally:
            lock.__exit__(None, None, None)

    def put(self, key, text, now=None, guard=None):
        """Words for interruption `key`, replacing any it had. Raises OnceWordsError: the text refused (in the Custom
        message's own words), one more interruption than MAX_ENTRIES, or a store that could not be written.

        `guard`, when given, is called under the file's lock before anything is written, and whatever it raises
        leaves the file as it was: the Dashboard's check that the recovery still waits, made where the engine's look
        after its claim (`unchanged`) cannot fall between the check and the write."""
        if ids.read_interruption_id(str(key or "")) != key:
            raise OnceWordsError("invalid interruption id", "invalid_id")
        try:
            text = validate(text)
        except continuation.CustomMessageError as exc:
            raise OnceWordsError(str(exc)) from None
        moment = time.time() if now is None else float(now)

        def change(held):
            if guard is not None:
                guard()
            if key not in held and len(held) >= MAX_ENTRIES:
                return "too_many"
            held[key] = {"text": text, "written_at": moment}
            return "set"

        answer, written = self._change(change)
        if answer == "too_many":
            raise OnceWordsError("at most %d waiting recoveries can have words for this time" % MAX_ENTRIES,
                                 "too_many_messages")
        if not written:
            raise OnceWordsError("the state is busy", "state_busy")
        return True

    def remove(self, key) -> bool:
        """This interruption's words taken away. True when it holds none afterwards (taken, or there were none);
        False where the lock or Windows refused - then they are still there."""
        _, written = self._change(lambda held: held.pop(key, None))
        return written

    def unchanged(self, key, seen):
        """Whether this interruption's words are still `seen` (None for none), read under the file's lock, so a
        write a person has begun is finished first: True or False, or None where the lock or the file could not be
        had just now. Nothing is changed (engine/delivery.py, after the claim)."""
        answer, written = self._change(lambda held: (held.get(key) or {}).get("text") == seen)
        return answer if written else None

    def restore(self, key, text, now=None) -> bool:
        """Words put back for `key` only if it holds none now (a send that never started, engine/dispatch.py)."""
        try:
            text = validate(text)
        except continuation.CustomMessageError:
            return False
        moment = time.time() if now is None else float(now)

        def change(held):
            if key in held or len(held) >= MAX_ENTRIES:
                return False
            held[key] = {"text": text, "written_at": moment}
            return True

        answer, written = self._change(change)
        return bool(answer) and written

    def prune(self, keep) -> int:
        """Every entry whose interruption `keep(key)` no longer keeps taken away - and a file that cannot be
        believed removed. How many were taken; nothing is written when nothing is held."""
        why, held = read_file(self.path)
        if why == READ_MISSING or (why == READ_OK and all(keep(key) for key in held)):
            return 0

        def change(held):
            gone = [key for key in held if not keep(key)]
            for key in gone:
                del held[key]
            return len(gone)

        answer, written = self._change(change)
        return answer or 0 if written else 0
