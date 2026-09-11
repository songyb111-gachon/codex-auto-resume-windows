"""Read-only adapter for the locally verified Codex 0.153.4 storage schema.

This is deliberately an internal-schema adapter, not a public API. Unknown
schemas and values fail closed. No prompt/error text escapes this module.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import uuid

from . import failures


MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_META_BYTES = 256 * 1024
MAX_ITEM_BYTES = 1024 * 1024
MARKER_RE = re.compile(r"\[codex-auto-resume:[0-9a-f]{64}\]\Z")
CLIENT_ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}\Z")
KNOWN_STATUSES = {"failed", "completed", "interrupted", "inProgress"}
# Item types that count as a turn having produced something. Anything Codex adds later
# does not count until it is added here on purpose.
PROGRESS_ITEM_TYPES = frozenset({"agentMessage", "commandExecution", "fileChange", "mcpToolCall"})


def _turn_status(value):
    if value is None:
        return None
    return value if value in KNOWN_STATUSES else "other"


class SourceError(RuntimeError):
    """Safe diagnostic: never include database contents or underlying errors."""


def valid_uuid(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def epoch(value) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and 946684800 <= value <= 4102444800)


def _json(value):
    if not isinstance(value, str) or len(value) > MAX_ITEM_BYTES:
        return None
    try:
        return json.loads(value)
    except (ValueError, RecursionError):
        return None


def normalize(row) -> dict | None:
    """Normalize just the required scalar fields, discarding raw error text."""
    if not isinstance(row, dict):
        return None
    tid, turn = row.get("thread_id"), row.get("turn_id")
    status = row.get("status")
    ordinal = row.get("ordinal", row.get("rollout_ordinal"))
    if (not valid_uuid(tid) or not valid_uuid(turn)
            or not isinstance(status, str) or status not in KNOWN_STATUSES
            or type(ordinal) is not int or ordinal < 0):
        return None
    started, completed = row.get("started_at"), row.get("completed_at")
    if not epoch(started) or (completed is not None and not epoch(completed)):
        return None
    if completed is not None and completed < started:
        return None
    if "category" in row:
        # Already normalized once: keep the decision rather than reclassifying from
        # fields that no longer exist, so normalize() stays idempotent.
        category = row["category"] if row["category"] in failures.CATEGORIES else None
    else:
        if "error_json" in row:
            err = _json(row["error_json"])
            info = err.get("codexErrorInfo") if isinstance(err, dict) else None
            text = err.get("message") if isinstance(err, dict) else None
        else:
            info = row.get("error_info", row.get("codexErrorInfo"))
            text = row.get("message")
        # The raw error is classified here and then dropped: only the category name
        # continues past this point, so no error text can reach state, logs or a toast.
        category = failures.classify(info, text) if status == "failed" else None
    return {"thread_id": tid, "turn_id": turn, "status": status,
            "started_at": started, "completed_at": completed,
            "ordinal": ordinal, "category": category}


def detect(row) -> dict | None:
    """A failed turn this tool is willing to recover, or None.

    `unknown` and every terminal category stop here: they are never registered, so
    they can never be retried by a later change somewhere else in the pipeline.
    """
    normalized = normalize(row)
    if (normalized is None or normalized["status"] != "failed"
            or not failures.is_recoverable(normalized["category"] or "")
            or normalized["completed_at"] is None):
        return None
    identity = [normalized[k] for k in ("thread_id", "turn_id", "completed_at", "ordinal")]
    # Integral epoch values have one canonical representation, int or float.
    identity[2] = float(identity[2]).hex()
    normalized["interruption_id"] = hashlib.sha256(
        json.dumps(identity, separators=(",", ":")).encode("ascii")).hexdigest()
    return normalized


MAX_LABEL_CHARS = 72


def _label(value):
    """A display label, or None. Never a paragraph, never multi-line.

    A defensive cap: if a future schema starts putting prompt-like text in the field
    this reads, a long or multi-line value is dropped rather than shown. Control
    characters are stripped so a label can never rearrange a notification.
    """
    if not isinstance(value, str):
        return None
    cleaned = "".join(character for character in value if character.isprintable()).strip()
    if not cleaned or any(ch in value for ch in ("\n", "\r", "\t")):
        return None
    if len(cleaned) > MAX_LABEL_CHARS:
        cleaned = cleaned[:MAX_LABEL_CHARS - 1].rstrip() + "…"
    return cleaned


def _safe_path(path: Path) -> Path:
    # SQLite stores Windows extended paths; normalize before confinement checks.
    raw = str(path)
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return Path(raw).resolve()


# Codex names its databases with a schema generation suffix (state_5, queue_1, ...).
# An app update can bump that number, so the file is discovered by pattern and then
# validated by the columns this tool actually reads. Extra columns are fine (Codex
# adds them over time); a MISSING required column means the schema moved and we refuse.
DB_KINDS = {
    "state": (re.compile(r"state_(\d+)\.sqlite\Z"), {
        "threads": {"id", "rollout_path", "source", "thread_source", "archived", "history_mode"},
    }),
    "history": (re.compile(r"thread_history_(\d+)\.sqlite\Z"), {
        "thread_turns": {"thread_id", "turn_id", "status", "error_json", "started_at",
                         "completed_at", "rollout_ordinal", "rollout_end_byte_offset",
                         "first_user_item_id"},
        "thread_items": {"thread_id", "turn_id", "item_id", "item_type", "item_json"},
    }),
    "queue": (re.compile(r"queue_(\d+)\.sqlite\Z"), {
        "queued_items": {"id", "thread_id", "payload_json"},
    }),
}


class LocalSource:
    def __init__(self, codex_home: Path):
        self.home = _safe_path(Path(codex_home))
        self._resolved: dict[str, str] = {}

    def _connect(self, path):
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _schema_ok(connection, tables) -> bool:
        for table, required in tables.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                return False
            found = {row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)}
            if not required <= found:
                return False
        return True

    def resolve(self, kind: str) -> str:
        """Newest generation of `kind` whose schema still has every column we read."""
        if kind in self._resolved:
            return self._resolved[kind]
        pattern, tables = DB_KINDS[kind]
        candidates = []
        try:
            for entry in self.home.iterdir():
                match = pattern.fullmatch(entry.name)
                if match and entry.is_file() and not entry.is_symlink():
                    candidates.append((int(match.group(1)), entry))
        except OSError:
            raise SourceError("Codex local state unavailable or unsupported") from None
        for _, path in sorted(candidates, key=lambda item: -item[0]):
            connection = None
            try:
                connection = self._connect(_safe_path(path))
                if self._schema_ok(connection, tables):
                    self._resolved[kind] = path.name
                    return path.name
            except (sqlite3.Error, OSError, ValueError):
                continue
            finally:
                if connection is not None:
                    connection.close()
        raise SourceError("No Codex %s database with the required schema" % kind)

    @contextmanager
    def _db(self, kind):
        connection = None
        try:
            path = _safe_path(self.home / self.resolve(kind))
            if path.parent != self.home:
                raise SourceError("Codex database path is outside configured home")
            connection = self._connect(path)
            yield connection
        except (sqlite3.Error, OSError, ValueError):
            raise SourceError("Codex local state unavailable or unsupported") from None
        finally:
            if connection is not None:
                connection.close()

    def _metadata(self, thread_id: str, strict: bool = False) -> Path | None:
        # strict=True (used by latest()) re-raises transient I/O as SourceError so the
        # engine defers instead of treating an unreadable rollout as "latest turn changed".
        if not valid_uuid(thread_id):
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
        if not valid_uuid(thread_id):
            return None
        with self._db("state") as connection:
            row = connection.execute("SELECT rollout_path FROM threads WHERE id=?", (thread_id,)).fetchone()
        if row is None or not isinstance(row["rollout_path"], str):
            return None
        path = _safe_path(Path(row["rollout_path"]))
        if (not path.is_relative_to(_safe_path(self.home / "sessions"))
                or path.suffix != ".jsonl" or thread_id not in path.name):
            return None
        return path

    def latest(self, thread_id: str) -> dict | None:
        if not valid_uuid(thread_id) or self._metadata(thread_id, strict=True) is None:
            return None
        with self._db("history") as connection:
            row = connection.execute(
                "SELECT thread_id,turn_id,status,started_at,completed_at,"
                "rollout_ordinal,error_json FROM thread_turns WHERE thread_id=? "
                "ORDER BY rollout_ordinal DESC LIMIT 1", (thread_id,)).fetchone()
        return normalize(dict(row)) if row else None

    def latest_failures(self, since: float) -> list[dict]:
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
            if eligible and self._metadata(eligible["thread_id"]) is not None:
                result.append(eligible)
        return result

    def identity(self, thread_id: str) -> dict:
        """Human-facing labels for one thread. Never used to *find* a thread.

        Only `threads.name` is read as a title. `threads.title`, `preview` and
        `first_user_message` all hold the raw first prompt on this schema (observed up
        to 67 KB, multi-line), so they are never touched. `name` is the short display
        name Codex itself shows, and it is length-capped and single-line-checked here
        anyway. Missing columns are not an error: display is optional, detection is not.
        """
        blank = {"name": None, "project": None, "cwd_basename": None}
        if not valid_uuid(thread_id):
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

    def progress(self, thread_id: str, after_ordinal: int) -> dict:
        """Content-free evidence that something happened after a given turn.

        Reads lifecycle columns only: whether a later turn exists, whether one of them
        completed, and whether a completed turn recorded a final agent item. No message
        text, tool input or tool output is read.
        """
        empty = {"later_turn": False, "later_completed": False, "assistant_reply": False}
        if not valid_uuid(thread_id) or type(after_ordinal) is not int:
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
        if not valid_uuid(thread_id) or not valid_uuid(turn_id):
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
    # ------------------------------------------------------------------------
    @staticmethod
    def _identity(thread_id, marker):
        if not valid_uuid(thread_id) or not isinstance(marker, str) or not MARKER_RE.fullmatch(marker):
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
            if not (isinstance(payload, dict) and payload.get("type") == "userMessage"
                    and _content_has_marker(payload.get("content"), marker)):
                continue
            client = payload.get("clientId")
            ordinal = row["rollout_ordinal"]
            found.append({
                "turn_id": row["turn_id"] if valid_uuid(row["turn_id"]) else None,
                "ordinal": ordinal if type(ordinal) is int else None,
                "status": _turn_status(row["status"]),
                # A row whose turn is not projected yet cannot say who started it.
                "first_unset": bool(row["first_unset"]) or type(ordinal) is not int,
                "starts_turn": bool(row["starts_turn"]),
                "client_id": client if isinstance(client, str) and CLIENT_ID_RE.fullmatch(client) else None,
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
                if valid_uuid(row["id"]) and _queue_has_marker(payload, marker):
                    client = payload["UserInput"].get("client_id")
                    found.append({"id": row["id"], "client_id": client if isinstance(client, str)
                                  and CLIENT_ID_RE.fullmatch(client) else None})
        return found

    def queue_row(self, thread_id: str, queue_id: str, marker: str) -> dict:
        """Whether the queued item with this exact id still exists, and still is ours.

        A row with our id but without our marker is one somebody edited in Codex; its
        content is not returned, only that fact.
        """
        self._identity(thread_id, marker)
        if not valid_uuid(queue_id):
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
            turns.append({"turn_id": row["turn_id"] if valid_uuid(row["turn_id"]) else None,
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
        if not valid_uuid(turn_id):
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
        if not valid_uuid(thread_id) or not valid_uuid(turn_id):
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

    def turn_markers(self, thread_id: str, turn_id: str, markers) -> list:
        """Which of these markers appear in a user message of one turn. Booleans only."""
        if not valid_uuid(thread_id) or not valid_uuid(turn_id):
            raise SourceError("Invalid turn identity")
        wanted = [marker for marker in markers if isinstance(marker, str) and MARKER_RE.fullmatch(marker)]
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
        if not valid_uuid(thread_id):
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


def _content_has_marker(content, marker):
    return isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "text"
        and isinstance(item.get("text"), str) and marker in item["text"]
        for item in content)


def _queue_has_marker(payload, marker):
    if not isinstance(payload, dict):
        return False
    # TurnInput's serde shape is version-pinned; unknown shapes fail closed.
    # protocol/src/turn_input.rs derives serde without tag/rename attributes:
    # {"UserInput": {"content": [...], "client_id": ...}}.
    content = payload.get("UserInput")
    return (set(payload) == {"UserInput"} and isinstance(content, dict)
            and _content_has_marker(content.get("content"), marker))


def _choose_reset(buckets, completed_at):
    blocked = []
    ambiguity = False
    for bucket, limits in buckets.items():
        has_window = False
        for name in ("primary", "secondary"):
            window = limits.get(name)
            if not isinstance(window, dict):
                continue
            used, reset = window.get("used_percent"), window.get("resets_at")
            if type(used) not in (int, float) or not math.isfinite(used) or used < 0:
                continue
            has_window = True
            if used >= 100:
                if epoch(reset) and reset >= completed_at:
                    blocked.append((reset, bucket + ":" + name))
                else:
                    ambiguity = True
        if not has_window:
            ambiguity = True
    if blocked:
        reset, limit = max(blocked)
        return {"reset_at": reset, "limit_type": limit, "uncertain": ambiguity or len(blocked) > 1}
    # Actual sample is codex primary=98%, immediately followed by premium=null.
    # Preserve its corroborating reset ONLY when its own usage is high enough to
    # plausibly be the block; a low-usage window's far-future reset must not delay
    # the first eligibility check. A fresh live availability check is still required.
    primary = buckets.get("codex", {}).get("primary")
    if isinstance(primary, dict):
        used = primary.get("used_percent")
        reset = primary.get("resets_at")
        if (type(used) in (int, float) and math.isfinite(used) and used >= 90
                and epoch(reset) and reset >= completed_at):
            return {"reset_at": reset, "limit_type": "codex:primary_hint", "uncertain": True}
    return {"reset_at": None, "limit_type": "unknown", "uncertain": True}
