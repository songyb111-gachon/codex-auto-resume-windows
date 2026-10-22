"""Everything this product asks of Codex, in one file.

Every statement sent to Codex's own state, history and queue is here, and
`tests/test_codex_schema.py` fails if one appears anywhere else in the package. The reason is
a reader's: somebody wondering what this thing reads of theirs should be able to answer it by
opening one file, and `PRIVACY.md` makes that promise on this file's behalf.

Everything is read-only - the connections are opened `mode=ro`, with `query_only` set - and
nothing here writes to Codex, ever."""
from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
import sqlite3
import time
from .. import failures, guards, machine, projects
from ..domain import ids, skips
from .errors import SourceError
from .labels import _label
from .values import KNOWN_STATUSES, PROGRESS_ITEM_TYPES, PROGRESS_KINDS, _json, _turn_status, epoch, normalize
from . import eligibility, rollout, workspace
from .payload import (_choose_reset, _item_is_ours, _needing, _queue_has_marker, detect,  # noqa: F401
                      judge, later_turn, marker_row)


class HistoryMixin:
    def _eligibility(self, thread_id: str, strict: bool = False, kinds=None):
        """(its file, None) for a conversation taken up - a person's own desktop one (A15), or of a kind the plug names
        (P18; `kinds`, else this tick's) - or (None, why not), a domain/skips.py reason and its kind word. strict=True
        (latest) re-raises transient I/O as SourceError, so the engine defers rather than calling it changed."""
        kinds = self.session_kinds if kinds is None else kinds
        if not ids.is_uuid(thread_id):
            return None, (skips.UNKNOWN_CONVERSATION, None)
        with self._db("state") as connection:
            row = connection.execute(
                "SELECT rollout_path,source,thread_source,archived,history_mode "
                "FROM threads WHERE id=?", (thread_id,)).fetchone()
        if row is None:
            return None, (skips.UNKNOWN_CONVERSATION, None)
        word = eligibility.row_problem(dict(row), kinds, self.widened)
        if word is not None:
            return None, (skips.OTHER_KIND, word)
        try:
            path = rollout.confined(self.home, thread_id, row["rollout_path"])
            payload = None if path is None else rollout.session_meta(path)
            if payload is None or payload.get("id") != thread_id:
                return None, (skips.OTHER_KIND, "file")
            if not eligibility.originator_taken(row["source"], payload.get("originator"), kinds):
                return None, (skips.OTHER_KIND, "originator " + skips.kind(payload.get("originator")))
            if (eligibility.kind_of(row["source"], payload, kinds) is None
                    or payload.get("thread_source") != row["thread_source"]):
                return None, (skips.OTHER_KIND, "file " + skips.kind(payload.get("thread_source")))
            return path, None
        except OSError:
            # Transient (AV scanner, sharing violation) vs a genuinely ineligible thread.
            if strict:
                raise SourceError("Codex local state unavailable or unsupported") from None
            return None, (skips.OTHER_KIND, "file")
        except (ValueError, UnicodeError):
            return None, (skips.OTHER_KIND, "file")

    def taken(self, thread_id: str, kinds) -> bool:
        """Whether `thread_id` is a conversation taken up with `kinds` watched (P18, engine/kinds.py)."""
        return self._eligibility(thread_id, kinds=frozenset(kinds))[0] is not None

    def _chain(self, thread_id: str, strict: bool = False):
        """(its file, every id its turns are recorded under - its own first, each split id oldest first, the current
        last - , why not); the file None for a conversation this does not recover (`_eligibility`). Split ids
        (codex/rollout.py, issue #30) count only when every guard holds: its current file is named exactly
        A_B.jsonl, its session_meta says A, no split id has a `threads` row and no other conversation's file names
        the current one. Any doubt is A alone, today's read. The queue and the app's hold stay under A always."""
        path, why = self._eligibility(thread_id, strict=strict)
        current = None if path is None else rollout.continued_id(thread_id, path.name)
        if current is None:
            return path, (thread_id,), why
        # What was seen before is kept (codex/chains.py); an earlier file's id joins only if it says it is A's.
        held = self.chains.get(self.home, thread_id)
        found = tuple(other for other, file in rollout.earlier(self.home, thread_id, current)
                      if other not in held and rollout.meta_id(file) == thread_id)
        chain = tuple(dict.fromkeys(held + found + (current,)))
        with self._db("state") as connection:
            taken = rollout.taken(chain, connection.execute(
                "SELECT id,rollout_path FROM threads WHERE %s OR (id<>? AND (%s))" % (self._of(chain, "id"), " OR ".join(
                    ["instr(rollout_path,?)>0"] * len(chain))), (*chain, thread_id, *chain)).fetchall())
        if taken & set(held + (current,)):
            return path, (thread_id,), why
        chain = self.chains.extend(self.home, thread_id, [other for other in chain if other not in taken])
        return path, (thread_id,) + chain + (() if current in chain else (current,)), why

    def _ids(self, thread_id: str) -> tuple:
        """Every id a conversation's turns are recorded under (`_chain`): every read of its turns asks this."""
        return self._chain(thread_id)[1] if ids.is_uuid(thread_id) else (thread_id,)

    def turn_chain(self, thread_id: str) -> tuple:
        """`_ids`, for the advanced edition's turn reader, which reads a split conversation as core does."""
        return self._ids(thread_id)

    @staticmethod
    def _of(chain, column="thread_id") -> str:
        return "%s IN (%s)" % (column, ",".join("?" * len(chain)))

    def _after(self, chain, ordinal, prefix=""):
        """(condition, parameters) for the turns after the one at `ordinal` (rollout.SPAN): later in its own id,
        and every turn of each later id."""
        index, own = divmod(ordinal, rollout.SPAN)
        later = chain[min(index, len(chain) - 1) + 1:]
        return ("(%sthread_id=? AND %srollout_ordinal>?%s)" % (prefix, prefix, " OR " + self._of(
            later, prefix + "thread_id") if later else ""), (chain[min(index, len(chain) - 1)], own, *later))

    def _latest_row(self, connection, chain, columns):
        """(its index in `chain`, its row) for a conversation's latest turn: the latest of the newest id with one."""
        for index in range(len(chain) - 1, -1, -1):
            row = connection.execute("SELECT %s FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal DESC "
                                     "LIMIT 1" % columns, (chain[index],)).fetchone()
            if row is not None:
                return index, row
        return 0, None

    def _owner(self, turns_id: str, turn_id=None):
        """(conversation, None, index) for the conversation this recovers whose turns are recorded under `turns_id`,
        at that index of its `_chain` - itself, or the one conversation whose file names it - or (its id or None,
        why not, 0). With `turn_id`, that turn must be the conversation's latest: a turn of an id split away from
        is not (A17), and an id no file names any more is nobody's."""
        if not ids.is_uuid(turns_id):
            return None, (skips.UNKNOWN_CONVERSATION, None), 0
        with self._db("state") as connection:
            found = {row[0] for row in connection.execute(
                "SELECT id FROM threads WHERE id=? OR instr(rollout_path,?)>0", (turns_id, turns_id))}
        named = () if found else rollout.named_after(self.home, turns_id)
        owner = (turns_id if turns_id in found else next(iter(found)) if len(found) == 1
                 else named[0] if len(named) == 1 else None)
        if owner is None or not ids.is_uuid(owner):
            return None, (skips.UNKNOWN_CONVERSATION, None), 0
        path, chain, why = self._chain(owner)
        if path is None:
            return owner, why, 0
        if turns_id not in chain:
            return owner, (skips.CONTINUED_ELSEWHERE, None), 0
        if turn_id is not None and len(chain) > 1:
            with self._db("history") as connection:
                row = self._latest_row(connection, chain, "turn_id")[1]
            if row is None or row["turn_id"] != turn_id:
                return owner, (skips.NEWER_TURN, None), chain.index(turns_id)
        return owner, None, chain.index(turns_id)

    def owner_of(self, turns_id: str):
        """The conversation whose turns are recorded under `turns_id` (`_owner`), or None - for the advanced
        edition's list of conversations that finished a turn lately."""
        owner, why, _ = self._owner(turns_id)
        return owner if why is None else None

    def _rollout_path(self, thread_id: str) -> Path | None:
        """Where a conversation's file is, confined to the Codex sessions folder (rollout.confined). Only for the size
        comparison behind projection freshness: the file is not opened, and whether the thread is still eligible does
        not matter - a settle must tell, for an archived thread too, whether Codex's history has caught up."""
        if not ids.is_uuid(thread_id):
            return None
        with self._db("state") as connection:
            row = connection.execute("SELECT rollout_path FROM threads WHERE id=?", (thread_id,)).fetchone()
        return None if row is None else rollout.confined(self.home, thread_id, row["rollout_path"])

    def latest(self, thread_id: str) -> dict | None:
        if not ids.is_uuid(thread_id):
            return None
        path, chain, _ = self._chain(thread_id, strict=True)
        if path is None:
            return None
        with self._db("history") as connection:
            index, row = self._latest_row(connection, chain, "thread_id,turn_id,status,started_at,completed_at,"
                                          "rollout_ordinal,error_json")
        return normalize(rollout.placed(row, thread_id, index)) if row else None

    def latest_failures(self, since: float, *, needs_you=frozenset(), admissible=False,
                        shapes=False) -> list[dict]:
        """Every conversation's latest turn that failed since `since` and that this product would recover
        (payload.detect). `needs_you` (v0.6.11) adds those of these categories (needsyou.KINDS), normalized the
        same way with the id `detect` would give, but never through it: none can become a record (A14).

        v0.6.14, only while the plug wants P17 (domain/plug.py): `admissible` adds, marked so, those it may take up
        (failures.ADMISSIBLE), and `shapes` gives each entry its error's shape - never a word of a message
        (failures.shape); each through the same check of its conversation (A15)."""
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
            # A turn recorded under another id is read as its conversation's (`_owner`); no owner, no failure.
            owner, why, index = (self._owner(row["thread_id"], row["turn_id"])
                                 if judge(row, needs_you, admissible, shapes) else (None, 0, 0))
            if owner is not None and why is None:
                result.append(judge(rollout.placed(row, owner, index), needs_you, admissible, shapes))
        return result

    def passed_over(self, since: float, before: float, *, every_status=False, known=frozenset(), newest=None,
                    deadline=None) -> dict:
        """What latest_failures does not bring, and why (v0.6.16-beta.3, issue #27). "passed": each failed turn
        completed at `before` or later - or, with `every_status` (the Diagnostics check), every conversation's
        latest turn - whose turn id is not in `known`, with the reason (domain/skips.py) it stops at, in the
        order latest_failures decides: a later turn (A17), before `since` (A16), its conversation (A15,
        `_owner`), its kind (A13); None where it would be brought, or is no failure. "seen": how many failed
        latest turns from `since` on the read held. Lifecycle columns, ids and kind words only. With `newest`
        (every_status only) the most recent that many conversations, "more" saying how many are left out; past
        `deadline` (time.monotonic) nothing more is explained, "unchecked" saying how many were not."""
        if not epoch(since) or not epoch(before):
            raise SourceError("Invalid detection start timestamp")
        with self._db("history") as connection:
            rows = connection.execute(
                "SELECT t.thread_id,t.turn_id,t.status,t.started_at,t.completed_at,t.rollout_ordinal,t.error_json,"
                "EXISTS (SELECT 1 FROM thread_turns n WHERE n.thread_id=t.thread_id "
                "AND n.rollout_ordinal>t.rollout_ordinal) AS later FROM thread_turns t "
                "WHERE (t.status='failed' OR ?) AND coalesce(t.completed_at,t.started_at)>=?" + (
                    " AND NOT EXISTS (SELECT 1 FROM thread_turns n WHERE n.thread_id=t.thread_id AND n.rollout_ordinal"
                    ">t.rollout_ordinal) ORDER BY coalesce(t.completed_at,t.started_at) DESC" if newest else ""),
                (1 if every_status else 0, before)).fetchall()
        more, rows = max(0, len(rows) - (newest or len(rows))), rows[:newest] if newest else rows
        seen, found, unchecked = 0, [], 0
        for row in rows:
            if deadline is not None and time.monotonic() > deadline:
                unchecked += 1
                continue
            failed, when, later = row["status"] == "failed", row["completed_at"], bool(row["later"])
            inside = epoch(when) and when >= since
            seen += int(failed and inside and not later)
            if (every_status and later) or row["turn_id"] in known:
                continue
            category = (normalize(dict(row)) or {}).get("category") if failed else None
            owner, why, index = (row["thread_id"], (skips.NEWER_TURN, None), 0) if later else (
                (row["thread_id"], (skips.BEFORE_WINDOW, None), 0) if failed and not inside
                else self._owner(row["thread_id"], row["turn_id"]))
            if why is None and failed and judge(rollout.placed(row, owner, index)) is None:
                why = (skips.NOT_RECOVERED, skips.kind(category))
            found.append({"thread_id": owner or row["thread_id"], "turn_id": row["turn_id"],
                          "turns_id": row["thread_id"] if owner not in (None, row["thread_id"]) else None,
                          "status": _turn_status(row["status"]), "category": category,
                          "completed_at": when if epoch(when) else None,
                          "reason": why[0] if why else None, "kind": why[1] if why else None})
        return {"seen": seen, "passed": found, "more": more, "unchecked": unchecked}

    def stalled_turns(self, since: float, quiet_seconds: float, now: float) -> list[dict]:
        """Conversations whose latest turn is still in progress and recorded nothing new for `quiet_seconds`
        (v0.6.11, a needs-you notice): lifecycle columns and its newest item's time, never content (B7, B9);
        only a person's own desktop conversation (A15), none where items carry no time (B5)."""
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
            owner, why, _ = self._owner(thread, turn) if now - moved >= quiet_seconds else (None, 0, 0)
            if owner is not None and why is None:
                found.append({"thread_id": owner, "turn_id": turn, "moved_at": moved})
        return found

    def identity(self, thread_id: str) -> dict:
        """Human-facing labels for one thread, never used to *find* one. Only `threads.name` is read as a
        title: `title`, `preview` and `first_user_message` hold the raw first prompt (up to 67 KB seen), so
        they are never touched; `name` is capped and single-line-checked anyway. A missing column is no error."""
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
        """The key of the project a conversation is filed under (projects.key_for), or None: its project id or
        else its folder, digested here - the key is all that leaves, and nothing is found by it (B8). Asked
        only when Settings let some projects resume and not others; the two columns the labels read."""
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
        """What the two guards of v0.6.11 read of a conversation (guards.py), and only what they ask: "print",
        the digest of its model, approval mode and folder's git HEAD (codex/workspace.py), and "tokens", Codex's
        own count where `tokens_used` is a numeric column - each None where it cannot be read. Each column only
        if it is there (B5); only the digest and the count leave, and neither guard is on at the defaults."""
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
        """Content-free evidence that something happened after a given turn: whether a later turn exists, one
        completed, and a completed one recorded a final agent item - lifecycle columns only."""
        empty = {"later_turn": False, "later_completed": False, "assistant_reply": False}
        if not ids.is_uuid(thread_id) or type(after_ordinal) is not int:
            return empty
        try:
            where, parameters = self._after(self._ids(thread_id), after_ordinal)
            with self._db("history") as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(thread_turns)")}
                final = "final_agent_item_id" in columns
                rows = connection.execute(
                    "SELECT status, completed_at%s FROM thread_turns WHERE %s"
                    % (", final_agent_item_id" if final else "", where), parameters).fetchall()
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
        unknown = dict(rollout.UNKNOWN_RESET)
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            return unknown
        path, chain, _ = self._chain(thread_id)
        if path is None:
            return unknown
        with self._db("history") as connection:
            row = connection.execute(
                "SELECT thread_id,turn_id,status,started_at,completed_at,"
                "rollout_ordinal,error_json,rollout_end_byte_offset "
                "FROM thread_turns WHERE %s AND turn_id=?" % self._of(chain), (*chain, turn_id)).fetchone()
        eligible = detect(dict(row, thread_id=thread_id)) if row is not None else None
        # A reset timestamp only means anything for a usage limit - read from the file its turn was written to.
        files = dict(rollout.earlier(self.home, thread_id, chain[-1])) if len(chain) > 1 else {}
        held = path if row is not None and row["thread_id"] == chain[-1] else files.get(row and row["thread_id"])
        if eligible is None or eligible["category"] != failures.USAGE_LIMIT or held is None:
            return unknown
        return rollout.reset_scan(held, row["rollout_end_byte_offset"], turn_id, row["completed_at"])

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

    def _following(self, thread_id, marker) -> tuple:
        """`_identity`, then every id the conversation's turns are recorded under (`_ids`), none the marker."""
        self._identity(thread_id, marker)
        chain = self._ids(thread_id)
        if marker in chain:
            raise SourceError("Invalid delivery identity")
        return chain

    def marker_rows(self, thread_id: str, marker: str) -> list:
        """Every history row that holds our marker, with the facts about its own turn: the turn a continuation
        started is that row's, never "the latest turn" - a person may already have started another."""
        chain = self._following(thread_id, marker)
        with self._db("history") as connection:
            rows = connection.execute(
                "SELECT i.thread_id, i.turn_id, i.item_id, i.item_json, t.rollout_ordinal, t.status, "
                "t.first_user_item_id IS NULL AS first_unset, "
                "coalesce(t.first_user_item_id = i.item_id, 0) AS starts_turn "
                "FROM thread_items i LEFT JOIN thread_turns t "
                "ON t.thread_id=i.thread_id AND t.turn_id=i.turn_id "
                "WHERE %s AND i.item_type='userMessage' AND instr(i.item_json,?)>0" % self._of(chain, "i.thread_id"),
                (*chain, marker)).fetchall()
        placed = (rollout.placed(row, thread_id, chain.index(row["thread_id"])) for row in rows)
        return [found for found in (marker_row(row, marker) for row in placed) if found is not None]

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
        """Whether the queued item with this exact id still exists, and still is ours: one with our id but not
        our marker is one somebody edited in Codex, and only that fact is returned."""
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
        """Turns after the failed one, each ours, someone else's, or not yet knowable - booleans and ids only. One
        whose first user message is not projected yet is "undetermined" while it runs (it cannot have started
        our item); finished without any user message (a hook blocked it, or Codex started it), someone else's."""
        chain = self._following(thread_id, marker)
        if type(after_ordinal) is not int:
            raise SourceError("Invalid ordinal")
        where, parameters = self._after(chain, after_ordinal, "t.")
        with self._db("history") as connection:
            rows = connection.execute(
                "SELECT t.thread_id, t.turn_id, t.status, t.rollout_ordinal, "
                "t.first_user_item_id IS NOT NULL AS has_first, "
                "EXISTS(SELECT 1 FROM thread_items i WHERE i.thread_id=t.thread_id "
                "AND i.item_id=t.first_user_item_id AND i.item_type='userMessage' "
                "AND instr(i.item_json,?)>0) AS first_is_ours "
                "FROM thread_turns t WHERE %s" % where, (marker, *parameters)).fetchall()
        placed = [rollout.placed(row, thread_id, chain.index(row["thread_id"])) for row in rows]
        return [later_turn(row) for row in sorted(placed, key=lambda row: row["rollout_ordinal"])]

    def turn_observation(self, thread_id: str, turn_id: str, marker: str) -> dict:
        """What happened in one exact turn, content-free: progress is an assistant message, command, file change
        or tool call in *that* turn, never a later one; a user message in it that is not ours is a person."""
        chain = self._following(thread_id, marker)
        if not ids.is_uuid(turn_id):
            raise SourceError("Invalid turn identity")
        with self._db("history") as connection:
            turn = connection.execute(
                "SELECT thread_id, status, completed_at, rollout_ordinal FROM thread_turns "
                "WHERE %s AND turn_id=?" % self._of(chain), (*chain, turn_id)).fetchone()
            if turn is None:
                return {"found": False}
            turns = turn["thread_id"]
            turn = rollout.placed(turn, thread_id, chain.index(turns))
            counts = {row[0]: row[1] for row in connection.execute(
                "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? "
                "GROUP BY item_type", (turns, turn_id)) if isinstance(row[0], str)}
            foreign, branded, worked = connection.execute(  # branded: our marker (#39); worked: progress first
                "SELECT count(*), EXISTS(SELECT 1 FROM thread_items WHERE thread_id=? AND turn_id=? AND item_type='userMessage' "
                "AND instr(item_json,?)>0), EXISTS(SELECT 1 FROM thread_items p WHERE thread_id=? AND turn_id=? AND item_type "
                "IN (%s) AND NOT EXISTS(SELECT 1 FROM thread_items WHERE thread_id=? AND turn_id=? AND item_type='userMessage' "
                "AND instr(item_json,?)=0 AND coalesce(rollout_ordinal<=p.rollout_ordinal,1))) FROM thread_items WHERE "
                "thread_id=? AND turn_id=? AND item_type='userMessage' AND instr(item_json,?)=0"
                % ",".join("?" * len(PROGRESS_KINDS)), (turns, turn_id, ids.MARKER_PREFIX, turns, turn_id, *PROGRESS_KINDS,
                                                         turns, turn_id, marker, turns, turn_id, marker)).fetchone()
            after, values = self._after(chain, turn["rollout_ordinal"]) if type(turn["rollout_ordinal"]) is int else ("0", ())
            later_terminal, later_started = map(bool, connection.execute(     # later_started: any status, running too
                "SELECT EXISTS(SELECT 1 FROM thread_turns WHERE %s AND status IN ('completed','failed','interrupted')), "
                "EXISTS(SELECT 1 FROM thread_turns WHERE %s)" % (after, after), (*values, *values)).fetchone())
        return {
            "found": True, "ordinal": turn["rollout_ordinal"],     # across a split (rollout.SPAN): Rescan's anchor
            "status": _turn_status(turn["status"]), "completed_at": turn["completed_at"] if epoch(turn["completed_at"]) else None,
            "progress": any(counts.get(kind, 0) > 0 for kind in PROGRESS_ITEM_TYPES),
            "foreign_user_messages": foreign, "branded_user_messages": int(bool(branded)),
            "progress_before_foreign": bool(foreign and worked),   # 2026-10-22: it worked, then a person joined it
            "later_terminal": later_terminal, "later_started": later_started,   # one turn at a time: so not running
            "compaction_only": "contextCompaction" in counts and set(counts) <= {"contextCompaction", "reasoning"},
        }

    def turn_progress(self, thread_id: str, turn_id: str):
        """Whether one turn produced anything: True, False, or None when unreadable."""
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            return None
        try:
            chain = self._ids(thread_id)
            with self._db("history") as connection:
                return bool(connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM thread_items WHERE %s AND turn_id=? "
                    "AND item_type IN (%s))" % (self._of(chain), ",".join("?" for _ in PROGRESS_KINDS)),
                    (*chain, turn_id, *PROGRESS_KINDS)).fetchone()[0])
        except (SourceError, sqlite3.Error, OSError, ValueError):
            return None

    def turn_item_counts(self, thread_id: str, turn_id: str):
        """How many items of each kind one turn left, counts only (B7), or None: v0.6.14, for the
        edition's plug's samples of failures it took up. Core itself never asks it."""
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            return None
        counts = {kind: 0 for kind in sorted(PROGRESS_ITEM_TYPES) + ["userMessage", "other"]}
        try:
            chain = self._ids(thread_id)
            with self._db("history") as connection:
                rows = connection.execute(
                    "SELECT item_type, count(*) FROM thread_items WHERE %s AND turn_id=? "
                    "GROUP BY item_type" % self._of(chain), (*chain, turn_id)).fetchall()
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
        chain = self._ids(thread_id)
        wanted = [marker for marker in markers
                  if ids.is_delivery_proof(marker) and marker not in (*chain, turn_id)]
        found = []
        with self._db("history") as connection:
            for marker in wanted:
                if connection.execute(
                        "SELECT EXISTS(SELECT 1 FROM thread_items WHERE %s AND turn_id=? "
                        "AND item_type='userMessage' AND instr(item_json,?)>0)" % self._of(chain),
                        (*chain, turn_id, marker)).fetchone()[0]:
                    found.append(marker)
        return found

    def marker_presence(self, thread_id: str, marker: str) -> dict:
        """How many copies of our marker exist anywhere on this thread, counts only: checked just before a send,
        a copy already there means another installation derived the same marker and got there first."""
        chain = self._following(thread_id, marker)
        with self._db("history") as connection:
            history = connection.execute(
                "SELECT count(*) FROM thread_items WHERE %s AND instr(item_json,?)>0" % self._of(chain),
                (*chain, marker)).fetchone()[0]
        with self._db("queue") as connection:
            queue = connection.execute(
                "SELECT count(*) FROM queued_items WHERE thread_id=? AND instr(payload_json,?)>0",
                (thread_id, marker)).fetchone()[0]
        return {"history": history, "queue": queue}

    def projection(self, thread_id: str) -> dict:
        """Whether Codex's history tables have caught up with the conversation's file: the file's size from one
        stat call against the byte offset the projection reached - content-free. Behind, nothing may be
        decided from the tables; `fresh` is None when it cannot be told."""
        if not ids.is_uuid(thread_id):
            return {"table": None, "fresh": None}
        try:
            turns = self._ids(thread_id)[-1]           # the current file's projection: a split's newest id
            with self._db("history") as connection:
                if not connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='thread_history_projection_state'").fetchone():
                    return {"table": False, "fresh": None}
                row = connection.execute(
                    "SELECT next_rollout_byte_offset FROM thread_history_projection_state "
                    "WHERE thread_id=?", (turns,)).fetchone()
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
        """Whether anything may still run in this Codex home, for the power action (v0.6.12): sizes, times and
        counts, never content (B7). First Codex's history has caught up (A18): every conversation whose file was
        written in the last `recent` seconds, and each of `threads` (the batch's own) at any age, projected
        exactly - its file's size, one stat call, nothing opened, is the projection's offset, with no grace, so
        a turn just started or a failure not projected yet holds the action; a missing row is behind too.
        `history` is True when all are current, False when one is behind, None when it cannot be told. Then,
        only once current, the latest turns still in progress in every conversation and the items queued in
        Codex - each None when unreadable; a turn left in progress by a crash holds the action (Q9)."""
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
                path = rollout.confined(self.home, row["id"], row["rollout_path"])
                if path is None:
                    continue
                info = path.stat()
            except FileNotFoundError:
                continue                    # no file: nothing Codex could still be projecting
            except (OSError, ValueError):
                return unknown
            if row["id"] not in wanted and info.st_mtime < now - recent:
                continue
            split = rollout.continued_id(row["id"], path.name)      # its file projected under B (issue #30)
            offset = offsets.get(split if split in offsets else row["id"])
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
