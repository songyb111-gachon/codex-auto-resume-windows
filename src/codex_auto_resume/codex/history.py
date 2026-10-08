"""Everything this product asks of Codex, in one file.

Every statement sent to Codex's own state, history and queue is here, and
`tests/test_codex_schema.py` fails if one appears anywhere else in the package. The reason is
a reader's: somebody wondering what this thing reads of theirs should be able to answer it by
opening one file, and `PRIVACY.md` makes that promise on this file's behalf.

Everything is read-only - the connections are opened `mode=ro`, with `query_only` set - and
nothing here writes to Codex, ever.
"""
from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
import re
import sqlite3
from .. import failures, guards, machine, projects
from ..domain import ids
from .errors import SourceError
from .labels import _label
from .values import (KNOWN_STATUSES, MAX_ITEM_BYTES, MAX_META_BYTES,
                     MAX_SCAN_BYTES, PROGRESS_ITEM_TYPES, _json,
                     _turn_status, epoch, error_shape, normalize)
from .paths import _safe_path
from . import workspace
from .payload import _choose_reset, _item_is_ours, _needing, _queue_has_marker, detect  # noqa: F401


class HistoryMixin:
    def _metadata(self, thread_id: str, strict: bool = False) -> Path | None:
        # strict=True (used by latest()) re-raises transient I/O as SourceError so the
        # engine defers instead of treating an unreadable rollout as "latest turn changed".
        if not ids.is_uuid(thread_id):
            return None
        with self._db("state") as connection:
            row = connection.execute(
                "SELECT rollout_path,source,thread_source,archived,history_mode "
                "FROM threads WHERE id=?", (thread_id,)).fetchone()
        if (row is None or row["source"] != "vscode" or row["archived"] != 0
                or row["thread_source"] != "user" or row["history_mode"] != "paginated"
                or not isinstance(row["rollout_path"], str)):
            return None
        try:
            path = _safe_path(Path(row["rollout_path"]))
            if not path.is_relative_to(_safe_path(self.home / "sessions")):
                return None
            if path.suffix != ".jsonl" or thread_id not in path.name:
                return None
            with path.open("rb") as stream:
                first = stream.readline(MAX_META_BYTES + 1)
            if len(first) > MAX_META_BYTES or not first.endswith(b"\n"):
                return None
            event = _json(first.decode("utf-8"))
            if not isinstance(event, dict) or event.get("type") != "session_meta":
                return None
            payload = event.get("payload")
            if (not isinstance(payload, dict) or payload.get("id") != thread_id
                    or payload.get("originator") != "Codex Desktop"
                    or payload.get("source") != "vscode"
                    or payload.get("thread_source") != "user"):
                return None
            return path
        except OSError:
            # Transient (AV scanner, sharing violation) vs a genuinely ineligible thread.
            if strict:
                raise SourceError("Codex local state unavailable or unsupported") from None
            return None
        except (ValueError, UnicodeError):
            return None

    def _rollout_path(self, thread_id: str) -> Path | None:
        """Where a conversation's file is, confined to the Codex sessions folder.

        Only for the size comparison behind projection freshness, which needs nothing
        else: the file is not opened, and whether the thread is still eligible for
        recovery does not matter - a settle must be able to tell, for an archived
        thread too, whether Codex's history has caught up.
        """
        if not ids.is_uuid(thread_id):
            return None
        with self._db("state") as connection:
            row = connection.execute("SELECT rollout_path FROM threads WHERE id=?", (thread_id,)).fetchone()
        return None if row is None else self._confined_rollout(thread_id, row["rollout_path"])

    def _confined_rollout(self, thread_id, raw) -> Path | None:
        """`raw`, the rollout path Codex's `threads` row names, if it is this conversation's file in the
        Codex sessions folder: a .jsonl file whose name holds the id. None for anything else, which is
        then neither opened nor asked about."""
        if not ids.is_uuid(thread_id) or not isinstance(raw, str):
            return None
        path = _safe_path(Path(raw))
        if (not path.is_relative_to(_safe_path(self.home / "sessions"))
                or path.suffix != ".jsonl" or thread_id not in path.name):
            return None
        return path

    def latest(self, thread_id: str) -> dict | None:
        if not ids.is_uuid(thread_id) or self._metadata(thread_id, strict=True) is None:
            return None
        with self._db("history") as connection:
            row = connection.execute(
                "SELECT thread_id,turn_id,status,started_at,completed_at,"
                "rollout_ordinal,error_json FROM thread_turns WHERE thread_id=? "
                "ORDER BY rollout_ordinal DESC LIMIT 1", (thread_id,)).fetchone()
        return normalize(dict(row)) if row else None

    def latest_failures(self, since: float, *, needs_you=frozenset(), admissible=False,
                        shapes=False) -> list[dict]:
        """Every conversation's latest turn that failed since `since` and that this product would
        recover (payload.detect). `needs_you` (v0.6.11) adds, from the same read, those whose category
        is one of these - failures that need a person (needsyou.KINDS) - normalized the same way and
        with the id `detect` would have given them, but never through `detect`, so none of them can
        ever become a record to recover (A14). Empty, the default, and this is v0.6.10's read.

        v0.6.13, only while the plug wants P17 (domain/plug.py): `admissible` adds, marked so, those
        it may take up (failures.ADMISSIBLE), and `shapes` gives each entry its error's shape - never a
        word of a message (failures.shape); each through the same check of its conversation (A15)."""
        if not epoch(since):
            raise SourceError("Invalid detection start timestamp")
        # Read only failure metadata; no transcript scanning or folder traversal.
        with self._db("history") as connection:
            rows = connection.execute(
                "SELECT t.thread_id,t.turn_id,t.status,t.started_at,t.completed_at,"
                "t.rollout_ordinal,t.error_json FROM thread_turns t "
                "WHERE t.status='failed' AND t.completed_at>=? "
                "AND NOT EXISTS (SELECT 1 FROM thread_turns n "
                "WHERE n.thread_id=t.thread_id AND n.rollout_ordinal>t.rollout_ordinal)",
                (since,)).fetchall()
        result = []
        for row in rows:
            eligible = detect(dict(row))
            if eligible is None and needs_you:
                eligible = _needing(dict(row), needs_you)
            if eligible is None and admissible:
                eligible = _needing(dict(row), failures.ADMISSIBLE)
            if eligible is not None and admissible and eligible["category"] in failures.ADMISSIBLE:
                eligible["admissible"] = True
            if eligible is not None and shapes:
                eligible["shape"] = error_shape(dict(row))
            if eligible and self._metadata(eligible["thread_id"]) is not None:
                result.append(eligible)
        return result

    def stalled_turns(self, since: float, quiet_seconds: float, now: float) -> list[dict]:
        """Conversations whose latest turn is still in progress and has recorded nothing new for
        `quiet_seconds` (v0.6.11, a needs-you notice): the turn's lifecycle columns and the time of its
        newest item, and nothing of any item's content, which is never selected (B7, B9). It says that
        nothing moved, never why. Only a desktop-app conversation of a person's own, as detection
        (A15); none at all where Codex's items carry no time (B5). Each: thread_id, turn_id, and when
        it last moved."""
        if not epoch(since) or type(quiet_seconds) is not int or quiet_seconds <= 0:
            raise SourceError("Invalid stall window")
        with self._db("history") as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(thread_items)")}
            if "created_at_ms" not in columns:
                return []
            rows = connection.execute(
                "SELECT t.thread_id,t.turn_id,t.started_at,"
                "(SELECT max(i.created_at_ms) FROM thread_items i WHERE i.thread_id=t.thread_id "
                "AND i.turn_id=t.turn_id) AS last_item_ms FROM thread_turns t "
                "WHERE t.status='inProgress' AND t.started_at>=? AND t.started_at<=? "
                "AND NOT EXISTS (SELECT 1 FROM thread_turns n "
                "WHERE n.thread_id=t.thread_id AND n.rollout_ordinal>t.rollout_ordinal)",
                (since, now - quiet_seconds)).fetchall()
        found = []
        for row in rows:
            thread, turn, started = row["thread_id"], row["turn_id"], row["started_at"]
            if not (ids.is_uuid(thread) and ids.is_uuid(turn) and epoch(started)):
                continue
            last = row["last_item_ms"]
            item = last / 1000.0 if type(last) is int and epoch(last // 1000) else None
            moved = max(started, item) if item is not None else started
            if now - moved >= quiet_seconds and self._metadata(thread) is not None:
                found.append({"thread_id": thread, "turn_id": turn, "moved_at": moved})
        return found

    def identity(self, thread_id: str) -> dict:
        """Human-facing labels for one thread. Never used to *find* a thread.

        Only `threads.name` is read as a title. `threads.title`, `preview` and
        `first_user_message` all hold the raw first prompt on this schema (observed up
        to 67 KB, multi-line), so they are never touched. `name` is the short display
        name Codex itself shows, and it is length-capped and single-line-checked here
        anyway. Missing columns are not an error: display is optional, detection is not.
        """
        blank = {"name": None, "project": None, "cwd_basename": None}
        if not ids.is_uuid(thread_id):
            return blank
        try:
            with self._db("state") as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
                wanted = [name for name in ("name", "cwd", "project_id") if name in columns]
                if not wanted:
                    return blank
                row = connection.execute(
                    "SELECT %s FROM threads WHERE id=?" % ",".join(wanted), (thread_id,)).fetchone()
                if row is None:
                    return blank
                keys = row.keys()
                project = None
                project_id = row["project_id"] if "project_id" in keys else None
                if project_id is not None:
                    has_projects = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'").fetchone()
                    if has_projects:
                        found = connection.execute(
                            "SELECT name FROM projects WHERE id=?", (project_id,)).fetchone()
                        if found is not None:
                            project = _label(found["name"])
                cwd = row["cwd"] if "cwd" in keys else None
                base = None
                if isinstance(cwd, str) and cwd.strip():
                    # SQLite stores Windows extended paths; the prefix is not part of a name.
                    plain = cwd[4:] if cwd.startswith("\\\\?\\") else cwd
                    base = _label(PureWindowsPath(plain).name)
                return {"name": _label(row["name"] if "name" in keys else None),
                        "project": project, "cwd_basename": base}
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return blank

    def project_key(self, thread_id: str):
        """The key of the project a conversation is filed under (projects.key_for), or None when it
        cannot be read. Codex's project id, or else its folder, is read here and digested here: the
        key is all that leaves this method, and nothing is ever found by it (B8).

        Asked only when Settings let some projects resume and not others (projects.asks); at the
        defaults it is never asked. The same two columns the labels are read from, and no other."""
        if not ids.is_uuid(thread_id):
            return None
        try:
            with self._db("state") as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
                wanted = [name for name in ("project_id", "cwd") if name in columns]
                if not wanted:
                    return None
                row = connection.execute(
                    "SELECT %s FROM threads WHERE id=?" % ",".join(wanted), (thread_id,)).fetchone()
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return None
        if row is None:
            return None
        keys = row.keys()
        return projects.key_for(row["project_id"] if "project_id" in keys else None,
                                row["cwd"] if "cwd" in keys else None)

    def task_facts(self, thread_id: str, *, fingerprint: bool = False, tokens: bool = False) -> dict:
        """What the two guards of v0.6.11 read of a conversation (guards.py), and only what they ask:

        * "print": the digest of its model, its approval mode and its folder's git HEAD
          (codex/workspace.py) - None when the conversation cannot be read;
        * "tokens": Codex's own count of the tokens it has used, only where the threads table has
          a numeric `tokens_used` column - None where it has none, or holds no whole number.

        Each column is read only if it is there (B5); a missing model or approval column is a
        part of the digest that is always the same, never a change. Nothing but the digest and
        the count leaves this method, and neither guard is on at the defaults, where it is never
        asked."""
        found = {"print": None, "tokens": None}
        if not ids.is_uuid(thread_id) or not (fingerprint or tokens):
            return found
        try:
            with self._db("state") as connection:
                columns = {row[1]: str(row[2] or "").upper()
                           for row in connection.execute("PRAGMA table_info(threads)")}
                wanted = [name for name in ("cwd", "model", "approval_mode")
                          if fingerprint and name in columns]
                counted = tokens and "INT" in columns.get("tokens_used", "")
                if counted:
                    wanted.append("tokens_used")
                if not wanted:
                    return found
                row = connection.execute(
                    "SELECT %s FROM threads WHERE id=?" % ",".join(wanted), (thread_id,)).fetchone()
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return found
        if row is None:
            return found
        keys = row.keys()
        if counted:
            found["tokens"] = guards.tokens(row["tokens_used"])
        if fingerprint:
            text = {name: row[name] if name in keys and isinstance(row[name], str) else None
                    for name in ("cwd", "model", "approval_mode")}
            head = workspace.head_digest(text["cwd"]) if text["cwd"] else workspace.UNREADABLE
            found["print"] = guards.fingerprint(text["model"], text["approval_mode"], head)
        return found

    def progress(self, thread_id: str, after_ordinal: int) -> dict:
        """Content-free evidence that something happened after a given turn.

        Reads lifecycle columns only: whether a later turn exists, whether one of them
        completed, and whether a completed turn recorded a final agent item. No message
        text, tool input or tool output is read.
        """
        empty = {"later_turn": False, "later_completed": False, "assistant_reply": False}
        if not ids.is_uuid(thread_id) or type(after_ordinal) is not int:
            return empty
        try:
            with self._db("history") as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(thread_turns)")}
                final = "final_agent_item_id" in columns
                rows = connection.execute(
                    "SELECT status, completed_at%s FROM thread_turns "
                    "WHERE thread_id=? AND rollout_ordinal>?"
                    % (", final_agent_item_id" if final else ""),
                    (thread_id, after_ordinal)).fetchall()
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return empty
        result = dict(empty, later_turn=bool(rows))
        for row in rows:
            if row["status"] == "completed" and row["completed_at"] is not None:
                result["later_completed"] = True
                if final and row["final_agent_item_id"]:
                    result["assistant_reply"] = True
        return result

    def reset_hint(self, thread_id: str, turn_id: str) -> dict:
        unknown = {"reset_at": None, "limit_type": "unknown", "uncertain": True}
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            return unknown
        path = self._metadata(thread_id)
        if path is None:
            return unknown
        with self._db("history") as connection:
            row = connection.execute(
                "SELECT thread_id,turn_id,status,started_at,completed_at,"
                "rollout_ordinal,error_json,rollout_end_byte_offset "
                "FROM thread_turns WHERE thread_id=? AND turn_id=?",
                (thread_id, turn_id)).fetchone()
        eligible = detect(dict(row)) if row is not None else None
        # A reset timestamp only means anything for a usage limit.
        if eligible is None or eligible["category"] != failures.USAGE_LIMIT:
            return unknown
        end = row["rollout_end_byte_offset"]
        if type(end) is not int or end <= 0:
            return unknown
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
                    return unknown
                data = stream.read(min(MAX_SCAN_BYTES, remaining))
        except (OSError, ValueError):
            return unknown
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
        return _choose_reset(buckets, row["completed_at"]) if found else unknown

    # ------------------------------------------------------------------------
    # Following our own continuation.
    #
    # Every query below that returns stored content is bounded by `instr(...,marker)>0`,
    # so the only message text that can ever leave SQL is our own continuation. Every
    # query over anyone else's rows returns counts, booleans and ids - never content.
    #
    # `marker` is what proves a continuation is ours (ids.is_delivery_proof): the marker at
    # the end of its words, or - for one the advanced edition sent with none (domain/plug.py,
    # P15) - the client id it was queued under, which Codex keeps on the message. Either is
    # looked for the same way, so the bound is the same: a row that holds our proof.
    # ------------------------------------------------------------------------
    @staticmethod
    def _identity(thread_id, marker):
        if not ids.is_uuid(thread_id) or not ids.is_delivery_proof(marker) or marker == thread_id:
            raise SourceError("Invalid delivery identity")

    def marker_rows(self, thread_id: str, marker: str) -> list:
        """Every history row that holds our marker, with the facts about its own turn.

        The turn a continuation started is the turn of the row that holds its marker.
        It is never "the latest turn": by the time anyone looks, a person may already
        have started another one.
        """
        self._identity(thread_id, marker)
        with self._db("history") as connection:
            rows = connection.execute(
                "SELECT i.turn_id, i.item_id, i.item_json, t.rollout_ordinal, t.status, "
                "t.first_user_item_id IS NULL AS first_unset, "
                "coalesce(t.first_user_item_id = i.item_id, 0) AS starts_turn "
                "FROM thread_items i LEFT JOIN thread_turns t "
                "ON t.thread_id=i.thread_id AND t.turn_id=i.turn_id "
                "WHERE i.thread_id=? AND i.item_type='userMessage' AND instr(i.item_json,?)>0",
                (thread_id, marker)).fetchall()
        found = []
        for row in rows:
            payload = _json(row["item_json"])
            if not _item_is_ours(payload, marker):
                continue
            client = payload.get("clientId")
            ordinal = row["rollout_ordinal"]
            found.append({
                "turn_id": row["turn_id"] if ids.is_uuid(row["turn_id"]) else None,
                "ordinal": ordinal if type(ordinal) is int else None,
                "status": _turn_status(row["status"]),
                # A row whose turn is not projected yet cannot say who started it.
                "first_unset": bool(row["first_unset"]) or type(ordinal) is not int,
                "starts_turn": bool(row["starts_turn"]),
                "client_id": client if ids.is_client_id(client) else None,
            })
        return found

    def queued_rows(self, thread_id: str, marker: str) -> list:
        """Our own queued items: ids and client ids only."""
        self._identity(thread_id, marker)
        found = []
        with self._db("queue") as connection:
            rows = connection.execute(
                "SELECT id,payload_json FROM queued_items WHERE thread_id=? "
                "AND instr(payload_json,?)>0", (thread_id, marker))
            for row in rows:
                payload = _json(row["payload_json"])
                if ids.is_uuid(row["id"]) and _queue_has_marker(payload, marker):
                    client = payload["UserInput"].get("client_id")
                    found.append({"id": row["id"], "client_id": client if ids.is_client_id(client) else None})
        return found

    def queue_row(self, thread_id: str, queue_id: str, marker: str) -> dict:
        """Whether the queued item with this exact id still exists, and still is ours.

        A row with our id but without our marker is one somebody edited in Codex; its
        content is not returned, only that fact.
        """
        self._identity(thread_id, marker)
        if not ids.is_uuid(queue_id):
            raise SourceError("Invalid queue identity")
        with self._db("queue") as connection:
            row = connection.execute(
                "SELECT instr(payload_json,?)>0 AS has_marker FROM queued_items "
                "WHERE thread_id=? AND id=?", (marker, thread_id, queue_id)).fetchone()
        return {"exists": row is not None, "has_marker": bool(row["has_marker"]) if row else False}

    def foreign_queued(self, thread_id: str, marker: str) -> int:
        """How many items on this thread's queue are not ours. A number only."""
        self._identity(thread_id, marker)
        with self._db("queue") as connection:
            return connection.execute(
                "SELECT count(*) FROM queued_items WHERE thread_id=? AND instr(payload_json,?)=0",
                (thread_id, marker)).fetchone()[0]

    def later_turns(self, thread_id: str, after_ordinal: int, marker: str) -> list:
        """Turns after the failed one, each classified as ours, someone else's, or not
        yet knowable. Booleans and ids only.

        A turn whose first user message is not projected yet is "undetermined": while it
        runs it cannot have started our queued item, so waiting is always safe. Once it
        has finished without any user message - input a hook blocked, or a turn Codex
        started itself - it is treated as someone else's.
        """
        self._identity(thread_id, marker)
        if type(after_ordinal) is not int:
            raise SourceError("Invalid ordinal")
        with self._db("history") as connection:
            rows = connection.execute(
                "SELECT t.turn_id, t.status, t.rollout_ordinal, "
                "t.first_user_item_id IS NOT NULL AS has_first, "
                "EXISTS(SELECT 1 FROM thread_items i WHERE i.thread_id=t.thread_id "
                "AND i.item_id=t.first_user_item_id AND i.item_type='userMessage' "
                "AND instr(i.item_json,?)>0) AS first_is_ours "
                "FROM thread_turns t WHERE t.thread_id=? AND t.rollout_ordinal>? "
                "ORDER BY t.rollout_ordinal", (marker, thread_id, after_ordinal)).fetchall()
        turns = []
        for row in rows:
            status = _turn_status(row["status"])
            if row["first_is_ours"]:
                kind, reason = "ours", None
            elif not row["has_first"] and status == "inProgress":
                kind, reason = "undetermined", None
            elif not row["has_first"]:
                kind, reason = "foreign", "turn_without_user_item"
            else:
                kind, reason = "foreign", "later_turn_exists"
            turns.append({"turn_id": row["turn_id"] if ids.is_uuid(row["turn_id"]) else None,
                          "ordinal": row["rollout_ordinal"], "status": status,
                          "kind": kind, "reason": reason})
        return turns

    def turn_observation(self, thread_id: str, turn_id: str, marker: str) -> dict:
        """What happened in one exact turn, content-free.

        Progress is at least one assistant message, command, file change or tool call
        in *that* turn - not in any later turn, which may be somebody else's. A user
        message in the turn that is not ours means a person joined it.
        """
        self._identity(thread_id, marker)
        if not ids.is_uuid(turn_id):
            raise SourceError("Invalid turn identity")
        with self._db("history") as connection:
            turn = connection.execute(
                "SELECT status, completed_at, rollout_ordinal FROM thread_turns "
                "WHERE thread_id=? AND turn_id=?", (thread_id, turn_id)).fetchone()
            if turn is None:
                return {"found": False}
            counts = {row[0]: row[1] for row in connection.execute(
                "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? "
                "GROUP BY item_type", (thread_id, turn_id)) if isinstance(row[0], str)}
            foreign = connection.execute(
                "SELECT count(*) FROM thread_items WHERE thread_id=? AND turn_id=? "
                "AND item_type='userMessage' AND instr(item_json,?)=0",
                (thread_id, turn_id, marker)).fetchone()[0]
            later_terminal = bool(type(turn["rollout_ordinal"]) is int and connection.execute(
                "SELECT EXISTS(SELECT 1 FROM thread_turns WHERE thread_id=? AND rollout_ordinal>? "
                "AND status IN ('completed','failed','interrupted'))",
                (thread_id, turn["rollout_ordinal"])).fetchone()[0])
        completed = turn["completed_at"]
        return {
            "found": True,
            "status": _turn_status(turn["status"]),
            "completed_at": completed if epoch(completed) else None,
            "progress": any(counts.get(kind, 0) > 0 for kind in PROGRESS_ITEM_TYPES),
            "foreign_user_messages": foreign,
            "later_terminal": later_terminal,
        }

    def turn_progress(self, thread_id: str, turn_id: str):
        """Whether one turn produced anything: True, False, or None when unreadable."""
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            return None
        kinds = tuple(sorted(PROGRESS_ITEM_TYPES))
        try:
            with self._db("history") as connection:
                return bool(connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM thread_items WHERE thread_id=? AND turn_id=? "
                    "AND item_type IN (%s))" % ",".join("?" for _ in kinds),
                    (thread_id, turn_id, *kinds)).fetchone()[0])
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return None

    def turn_item_counts(self, thread_id: str, turn_id: str):
        """How many items of each kind one turn left, counts only (B7), or None: v0.6.13, for the
        edition's plug's samples of failures it took up. Core itself never asks it."""
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            return None
        counts = {kind: 0 for kind in sorted(PROGRESS_ITEM_TYPES) + ["userMessage", "other"]}
        try:
            with self._db("history") as connection:
                rows = connection.execute(
                    "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? "
                    "GROUP BY item_type", (thread_id, turn_id)).fetchall()
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return None
        for kind, count in rows:
            counts[kind if kind in counts else "other"] += int(count)
        return counts

    def turn_markers(self, thread_id: str, turn_id: str, markers) -> list:
        """Which of these markers - or client ids a marker-free continuation was queued under -
        appear in a user message of one turn. Booleans only."""
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            raise SourceError("Invalid turn identity")
        wanted = [marker for marker in markers
                  if ids.is_delivery_proof(marker) and marker not in (thread_id, turn_id)]
        found = []
        with self._db("history") as connection:
            for marker in wanted:
                if connection.execute(
                        "SELECT EXISTS(SELECT 1 FROM thread_items WHERE thread_id=? AND turn_id=? "
                        "AND item_type='userMessage' AND instr(item_json,?)>0)",
                        (thread_id, turn_id, marker)).fetchone()[0]:
                    found.append(marker)
        return found

    def marker_presence(self, thread_id: str, marker: str) -> dict:
        """How many copies of our marker exist anywhere on this thread. Counts only.

        Checked immediately before a send: a copy that already exists means another
        installation derived the same marker and got there first.
        """
        self._identity(thread_id, marker)
        with self._db("history") as connection:
            history = connection.execute(
                "SELECT count(*) FROM thread_items WHERE thread_id=? AND instr(item_json,?)>0",
                (thread_id, marker)).fetchone()[0]
        with self._db("queue") as connection:
            queue = connection.execute(
                "SELECT count(*) FROM queued_items WHERE thread_id=? AND instr(payload_json,?)>0",
                (thread_id, marker)).fetchone()[0]
        return {"history": history, "queue": queue}

    def projection(self, thread_id: str) -> dict:
        """Whether Codex's history tables have caught up with the conversation's file.

        Content-free: the size of the rollout file from one stat call, compared with
        the byte offset the projection has reached. A projection that stays behind means
        the tables this tool reads are not the whole story, so nothing may be decided
        from them. `fresh` is None when it cannot be told.
        """
        if not ids.is_uuid(thread_id):
            return {"table": None, "fresh": None}
        try:
            with self._db("history") as connection:
                if not connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='thread_history_projection_state'").fetchone():
                    return {"table": False, "fresh": None}
                row = connection.execute(
                    "SELECT next_rollout_byte_offset FROM thread_history_projection_state "
                    "WHERE thread_id=?", (thread_id,)).fetchone()
            path = self._rollout_path(thread_id)
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return {"table": None, "fresh": None}
        if row is None or path is None or type(row[0]) is not int:
            return {"table": True, "fresh": None}
        try:
            size = path.stat().st_size
        except OSError:
            return {"table": True, "fresh": None}
        return {"table": True, "fresh": size == row[0]}

    def activity(self, threads=(), now=None, recent: float = 3600.0) -> dict:
        """Whether anything may still run in this Codex home, for the power action (v0.6.12): sizes, times
        and counts, and nothing of any conversation's content (B7). Two parts, in this order.

        Codex's history has caught up first (A18). Every conversation whose file was written in the last
        `recent` seconds, and every one of `threads` - the batch's own - whatever its age, must have been
        projected exactly: its file's size, from one stat call (the file is never opened), is the byte
        offset the projection has reached. There is no grace, as the engine allows before a send: nothing
        is checked again after the PC sleeps or shuts down, so a turn just started without local input, or
        a failure not projected yet, holds the action instead of reading as nothing running. A missing
        projection row for such a file is behind too. `history` is True when all are current, False when
        one is behind, and None when that cannot be told - the projection table itself missing, a
        database that cannot be read, a file that cannot be stat'ed.

        Then the counts, only once the history is current: the latest turns still in progress, in every
        conversation of this home, and the items queued in Codex. Each is None when it cannot be read; a
        turn left in progress by a crash is counted, and holds the action (Q9)."""
        unknown = {"history": None, "running": None, "queued": None}
        if not epoch(now) or type(recent) not in (int, float) or not recent >= 0:
            return unknown
        wanted = {thread for thread in threads if ids.is_uuid(thread)}
        try:
            with self._db("history") as connection:
                if not connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='thread_history_projection_state'").fetchone():
                    return unknown
                offsets = {row[0]: row[1] for row in connection.execute(
                    "SELECT thread_id,next_rollout_byte_offset FROM thread_history_projection_state")}
            with self._db("state") as connection:
                conversations = connection.execute("SELECT id,rollout_path FROM threads").fetchall()
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return unknown
        for row in conversations:
            try:
                path = self._confined_rollout(row["id"], row["rollout_path"])
                if path is None:
                    continue
                info = path.stat()
            except FileNotFoundError:
                continue                    # no file: nothing Codex could still be projecting
            except (OSError, ValueError):
                return unknown
            if row["id"] not in wanted and info.st_mtime < now - recent:
                continue
            offset = offsets.get(row["id"])
            if type(offset) is not int or offset != info.st_size:
                return {"history": False, "running": None, "queued": None}
        found = {"history": True, "running": None, "queued": None}
        try:
            with self._db("history") as connection:
                running = connection.execute(
                    "SELECT count(*) FROM thread_turns t WHERE t.status='inProgress' "
                    "AND NOT EXISTS (SELECT 1 FROM thread_turns n "
                    "WHERE n.thread_id=t.thread_id AND n.rollout_ordinal>t.rollout_ordinal)").fetchone()[0]
            found["running"] = running if type(running) is int else None
        except (SourceError, sqlite3.Error, OSError, ValueError):
            pass
        try:
            with self._db("queue") as connection:
                queued = connection.execute("SELECT count(*) FROM queued_items").fetchone()[0]
            found["queued"] = queued if type(queued) is int else None
        except (SourceError, sqlite3.Error, OSError, ValueError):
            pass
        return found
