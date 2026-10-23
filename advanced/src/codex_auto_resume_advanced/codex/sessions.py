# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Where a conversation came from, and the kind of the newest event its rollout holds, read-only (v0.6.16-beta.4) -
for the measurements MO and MC2 alone, never what either says - and (v0.6.19) where its rollout is, for MTOK.

MO records which source, originator and holder a terminal's TUI and VS Code's conversations have, so the words the
edition takes them by (core's codex/eligibility.py) are measured rather than guessed: `origin` reads the
conversation's `threads` row - its source, thread source and history mode, and where its rollout is - and the
rollout's first line, `session_meta`, as core's own eligibility check reads it (B6: id and origin only). MC2 asks
which of the history database and the rollout says first that a turn started and ended: `newest_event` reads the
last complete line of the rollout and keeps only its type and its payload's type - never a payload - each a word of
letters and underscores or "other".

The file is found as core finds every Codex database (codex/turns.connect); the rollout only where its path is the
conversation's own .jsonl file inside the Codex home's sessions folder, a symbolic link never followed. Anything that
goes wrong is TurnsUnavailable.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from codex_auto_resume.codex.paths import _safe_path
from codex_auto_resume.domain import ids

from .turns import TurnsUnavailable, connect

THREAD_COLUMNS = frozenset({"id", "rollout_path", "source", "thread_source", "history_mode"})
ORIGIN = "SELECT rollout_path, source, thread_source, history_mode FROM threads WHERE id=?"
STATEMENTS = (ORIGIN,)
# The first line's bound, as core's (codex/values.MAX_META_BYTES), and how much of the rollout's end is read.
FIRST_LINE_BYTES = 64 * 1024
TAIL_BYTES = 64 * 1024
WORD_MAX = 64


def _word(value) -> str:
    return (value if isinstance(value, str) and 0 < len(value) <= WORD_MAX
            and value.replace("_", "").isalpha() else "other")


class Origins:
    """The conversations of the Codex home `home`, as MO and MC2 read them."""

    def __init__(self, home):
        self.home = Path(home)

    def _row(self, thread_id):
        if not ids.is_uuid(thread_id):
            raise TurnsUnavailable("not a conversation")
        connection = connect(self.home, "state", {"threads": THREAD_COLUMNS})
        try:
            found = connection.execute(ORIGIN, (thread_id,)).fetchone()
        except (sqlite3.Error, ValueError):
            raise TurnsUnavailable("the conversation cannot be read") from None
        finally:
            connection.close()
        if found is None:
            return None
        return dict(zip(("rollout_path", "source", "thread_source", "history_mode"), found))

    def _rollout(self, thread_id, raw):
        if not isinstance(raw, str):
            return None
        path = _safe_path(Path(raw))
        sessions = _safe_path(self.home / "sessions")
        if not path.is_relative_to(sessions) or path.suffix != ".jsonl" or thread_id not in path.name:
            return None
        return path

    def rollout(self, thread_id):
        """The conversation's rollout, where it is its own .jsonl file inside the sessions folder - else None (MTOK,
        v0.6.19). The path is the reader's to open, never to keep."""
        row = self._row(thread_id)
        return self._rollout(thread_id, row.get("rollout_path")) if row is not None else None

    def origin(self, thread_id):
        """(the `threads` row's source, thread source and history mode, the first line's originator, source and
        whether it names a CLI version) - each None where it is not there. Paths are used, never returned."""
        row = self._row(thread_id)
        if row is None:
            return None, None
        path = self._rollout(thread_id, row.pop("rollout_path"))
        first = None
        if path is not None:
            try:
                with path.open("rb") as stream:
                    line = stream.readline(FIRST_LINE_BYTES + 1)
                event = json.loads(line.decode("utf-8")) if line.endswith(b"\n") else None
            except (OSError, ValueError, UnicodeError):
                event = None
            payload = event.get("payload") if isinstance(event, dict) and event.get("type") == "session_meta" else None
            if isinstance(payload, dict) and payload.get("id") == thread_id:
                first = {"originator": payload.get("originator"), "source": payload.get("source"),
                         "cli_version": payload.get("cli_version")}
        return row, first

    def events_since(self, thread_id, offset):
        """([the payload type of each complete line the rollout gained after byte `offset`, in order], the offset to
        look from next) - the end of the file where `offset` is None (the first look); ([], offset) where there is no
        rollout. At most TAIL_BYTES are read; nothing of a payload but its type is looked at."""
        row = self._row(thread_id)
        path = self._rollout(thread_id, row.get("rollout_path")) if row is not None else None
        if path is None:
            return [], offset
        try:
            with path.open("rb") as stream:
                stream.seek(0, 2)
                size = stream.tell()
                if offset is None or offset > size:
                    return [], size
                start = max(offset, size - TAIL_BYTES)
                stream.seek(start)
                data = stream.read(size - start)
        except OSError:
            raise TurnsUnavailable("the rollout cannot be read") from None
        complete = data[:data.rfind(b"\n") + 1]
        kinds = []
        for line in complete.split(b"\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeError):
                kinds.append("other")
                continue
            payload = event.get("payload") if isinstance(event, dict) else None
            kinds.append(_word(payload.get("type") if isinstance(payload, dict) else None))
        return kinds, start + len(complete)

    def newest_event(self, thread_id):
        """(the newest complete line's type, its payload's type) of the conversation's rollout, each a word or
        "other" - or None where there is no rollout to read. Nothing of a payload but its type is looked at."""
        row = self._row(thread_id)
        path = self._rollout(thread_id, row.get("rollout_path")) if row is not None else None
        if path is None:
            return None
        try:
            with path.open("rb") as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - TAIL_BYTES))
                tail = stream.read()
        except OSError:
            raise TurnsUnavailable("the rollout cannot be read") from None
        lines = [line for line in tail.split(b"\n")[1 if size > TAIL_BYTES else 0:-1] if line.strip()]
        if not lines:
            return None
        try:
            event = json.loads(lines[-1].decode("utf-8"))
        except (ValueError, UnicodeError):
            return "other", "other"
        payload = event.get("payload") if isinstance(event, dict) else None
        return (_word(event.get("type") if isinstance(event, dict) else None),
                _word(payload.get("type") if isinstance(payload, dict) else None))
