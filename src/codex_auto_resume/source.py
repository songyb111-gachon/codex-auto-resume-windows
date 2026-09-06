"""Read-only adapter for the locally verified Codex 0.153.4 storage schema.

This is deliberately an internal-schema adapter, not a public API. Unknown
schemas and values fail closed. No prompt/error text escapes this module.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid


MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_META_BYTES = 256 * 1024
MAX_ITEM_BYTES = 1024 * 1024
MARKER_RE = re.compile(r"\[codex-auto-resume:[0-9a-f]{64}\]\Z")
KNOWN_STATUSES = {"failed", "completed", "interrupted", "inProgress"}


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
    if "error_json" in row:
        err = _json(row["error_json"])
        info = err.get("codexErrorInfo") if isinstance(err, dict) else None
    else:
        info = row.get("error_info", row.get("codexErrorInfo"))
    # All other error variants are deliberately opaque, even object variants.
    info = "usageLimitExceeded" if info == "usageLimitExceeded" else None
    return {"thread_id": tid, "turn_id": turn, "status": status,
            "started_at": started, "completed_at": completed,
            "ordinal": ordinal, "error_info": info}


def detect(row) -> dict | None:
    normalized = normalize(row)
    if (normalized is None or normalized["status"] != "failed"
            or normalized["error_info"] != "usageLimitExceeded"
            or normalized["completed_at"] is None):
        return None
    identity = [normalized[k] for k in ("thread_id", "turn_id", "completed_at", "ordinal")]
    # Integral epoch values have one canonical representation, int or float.
    identity[2] = float(identity[2]).hex()
    normalized["interruption_id"] = hashlib.sha256(
        json.dumps(identity, separators=(",", ":")).encode("ascii")).hexdigest()
    return normalized


def _safe_path(path: Path) -> Path:
    # SQLite stores Windows extended paths; normalize before confinement checks.
    raw = str(path)
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return Path(raw).resolve()


class LocalSource:
    def __init__(self, codex_home: Path):
        self.home = _safe_path(Path(codex_home))

    @contextmanager
    def _db(self, name):
        connection = None
        try:
            path = _safe_path(self.home / name)
            if path.parent != self.home:
                raise SourceError("Codex database path is outside configured home")
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.row_factory = sqlite3.Row
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
        with self._db("state_5.sqlite") as connection:
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

    def latest(self, thread_id: str) -> dict | None:
        if not valid_uuid(thread_id) or self._metadata(thread_id, strict=True) is None:
            return None
        with self._db("thread_history_1.sqlite") as connection:
            row = connection.execute(
                "SELECT thread_id,turn_id,status,started_at,completed_at,"
                "rollout_ordinal,error_json FROM thread_turns WHERE thread_id=? "
                "ORDER BY rollout_ordinal DESC LIMIT 1", (thread_id,)).fetchone()
        return normalize(dict(row)) if row else None

    def latest_failures(self, since: float) -> list[dict]:
        if not epoch(since):
            raise SourceError("Invalid detection start timestamp")
        # Read only failure metadata; no transcript scanning or folder traversal.
        with self._db("thread_history_1.sqlite") as connection:
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

    def reset_hint(self, thread_id: str, turn_id: str) -> dict:
        unknown = {"reset_at": None, "limit_type": "unknown", "uncertain": True}
        if not valid_uuid(thread_id) or not valid_uuid(turn_id):
            return unknown
        path = self._metadata(thread_id)
        if path is None:
            return unknown
        with self._db("thread_history_1.sqlite") as connection:
            row = connection.execute(
                "SELECT thread_id,turn_id,status,started_at,completed_at,"
                "rollout_ordinal,error_json,rollout_end_byte_offset "
                "FROM thread_turns WHERE thread_id=? AND turn_id=?",
                (thread_id, turn_id)).fetchone()
        if row is None or detect(dict(row)) is None:
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

    def delivery(self, thread_id: str, marker: str) -> dict:
        if not valid_uuid(thread_id) or not isinstance(marker, str) or not MARKER_RE.fullmatch(marker):
            raise SourceError("Invalid delivery identity")
        delivered = False
        with self._db("thread_history_1.sqlite") as connection:
            # instr bounds the returned content to this unique owned marker.
            rows = connection.execute(
                "SELECT item_json FROM thread_items WHERE thread_id=? "
                "AND item_type='userMessage' AND instr(item_json,?)>0",
                (thread_id, marker))
            for row in rows:
                payload = _json(row["item_json"])
                if isinstance(payload, dict) and payload.get("type") == "userMessage":
                    delivered |= _content_has_marker(payload.get("content"), marker)
            row = connection.execute(
                "SELECT turn_id FROM thread_turns WHERE thread_id=? "
                "ORDER BY rollout_ordinal DESC LIMIT 1", (thread_id,)).fetchone()
            latest_turn_id = row["turn_id"] if row and valid_uuid(row["turn_id"]) else None
        queued = []
        with self._db("queue_1.sqlite") as connection:
            rows = connection.execute(
                "SELECT id,payload_json FROM queued_items WHERE thread_id=? "
                "AND instr(payload_json,?)>0", (thread_id, marker))
            for row in rows:
                payload = _json(row["payload_json"])
                if valid_uuid(row["id"]) and _queue_has_marker(payload, marker):
                    queued.append(row["id"])
        return {"delivered": delivered, "queued_ids": queued, "latest_turn_id": latest_turn_id}


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
