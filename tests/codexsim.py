"""A small, real Codex home for tests.

The engine is tested against the same SQLite tables it reads in production - the
columns Codex 0.153.4 has, checked against a live installation - through the real
`LocalSource`. Only the Codex *processes* are simulated: `SimBackend` stands in for
`codex queue`, the App Server's queue delete, the loaded-thread inventory and the
usage probe, and `CodexHome.dispatch` does what the desktop app does when it takes the
head of a thread's queue and starts a turn with it.

Nothing here is a mock of the query layer, so a query that is wrong against the real
schema fails here too.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import uuid

BASE = 1788628000.0          # realistic unix seconds (source.epoch bounds)
RESET = BASE + 3600.0
USAGE_ERROR = json.dumps({"codexErrorInfo": "usageLimitExceeded"})
APP = {"pid": 10, "created": 100, "path": "app", "server": {"pid": 20, "created": 200, "path": "codex"}}


def transient_error(code="serverOverloaded"):
    return json.dumps({"codexErrorInfo": code})


def new_id() -> str:
    return str(uuid.uuid4())


class CodexHome:
    """The three databases and the rollout files, owned by the test."""

    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "sessions").mkdir(parents=True, exist_ok=True)
        self._items = 0
        # Completion time for turns created without one; tests point it at their clock.
        self.clock = lambda: BASE
        with self._db("state_5.sqlite") as db:
            db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT, "
                       "thread_source TEXT, archived INTEGER, history_mode TEXT, name TEXT, cwd TEXT, "
                       "project_id TEXT, title TEXT, first_user_message TEXT, preview TEXT)")
        with self._db("thread_history_1.sqlite") as db:
            db.execute("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, "
                       "status TEXT, error_json TEXT, started_at INTEGER, completed_at INTEGER, "
                       "duration_ms INTEGER, first_user_item_id TEXT, final_agent_item_id TEXT, "
                       "rollout_byte_offset INTEGER, rollout_end_ordinal INTEGER, "
                       "rollout_end_byte_offset INTEGER, PRIMARY KEY (thread_id, turn_id))")
            db.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, item_id TEXT, "
                       "rollout_ordinal INTEGER, created_at_ms INTEGER, item_json TEXT, item_type TEXT, "
                       "updated_at_ordinal INTEGER, PRIMARY KEY (thread_id, item_id))")
            db.execute("CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY KEY, "
                       "next_rollout_byte_offset INTEGER, next_rollout_ordinal INTEGER)")
        with self._db("queue_1.sqlite") as db:
            db.execute("CREATE TABLE queued_items (id TEXT PRIMARY KEY, thread_id TEXT, payload_json TEXT, "
                       "queue_order INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER)")

    # ------------------------------------------------------------ plumbing
    def _db(self, name):
        connection = sqlite3.connect(self.root / name)

        class _Scope:
            def __enter__(self_inner):
                return connection

            def __exit__(self_inner, kind, *_):
                if kind is None:
                    connection.commit()
                connection.close()
        return _Scope()

    def rollout(self, thread_id) -> Path:
        return self.root / "sessions" / ("rollout-" + thread_id + ".jsonl")

    def _append(self, thread_id, events) -> int:
        with self.rollout(thread_id).open("ab") as stream:
            for event in events:
                stream.write(json.dumps(event).encode("utf-8") + b"\n")
        return self.rollout(thread_id).stat().st_size

    def catch_up(self, thread_id):
        """The projection reaches the end of the rollout file, as it does in Codex."""
        size = self.rollout(thread_id).stat().st_size
        with self._db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_history_projection_state VALUES (?,?,0) "
                       "ON CONFLICT(thread_id) DO UPDATE SET next_rollout_byte_offset=excluded.next_rollout_byte_offset",
                       (thread_id, size))

    def make_stale(self, thread_id):
        """The rollout grows but the projection does not follow (the #43142 shape)."""
        self._append(thread_id, [{"type": "event_msg", "payload": {"type": "noise"}}])

    # ------------------------------------------------------------- threads
    def add_thread(self, thread_id, *, name=None, thread_source="user", originator="Codex Desktop"):
        path = self.rollout(thread_id)
        if not path.exists():
            meta = {"type": "session_meta", "payload": {"id": thread_id, "originator": originator,
                                                        "source": "vscode", "thread_source": thread_source}}
            path.write_bytes(json.dumps(meta).encode("utf-8") + b"\n")
            with self._db("state_5.sqlite") as db:
                db.execute("INSERT INTO threads (id, rollout_path, source, thread_source, archived, history_mode, name) "
                           "VALUES (?,?,'vscode',?,0,'paginated',?)", (thread_id, str(path), thread_source, name))
        self.catch_up(thread_id)

    def next_ordinal(self, thread_id) -> int:
        with self._db("thread_history_1.sqlite") as db:
            value = db.execute("SELECT max(rollout_ordinal) FROM thread_turns WHERE thread_id=?",
                               (thread_id,)).fetchone()[0]
        return 5 if value is None else value + 1

    def add_item(self, thread_id, turn_id, item_type, text=None, client_id=None) -> str:
        self._items += 1
        item_id = "item-%d" % self._items
        if item_type == "userMessage":
            payload = {"type": "userMessage", "id": item_id, "clientId": client_id,
                       "content": [{"type": "text", "text": text or "a message from the user"}]}
        else:
            payload = {"type": item_type, "id": item_id, "text": text or "work"}
        with self._db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_items (thread_id, turn_id, item_id, rollout_ordinal, item_json, "
                       "item_type) VALUES (?,?,?,?,?,?)",
                       (thread_id, turn_id, item_id, self._items, json.dumps(payload), item_type))
        return item_id

    def add_turn(self, thread_id, turn_id=None, status="completed", ordinal=None, *, completed=None,
                 started=None, error_json=None, user_text="a message from the user", client_id=None,
                 progress=True, first_user=True):
        """A turn with its items. `user_text=None` or `first_user=False` leaves the
        first user item unset, as Codex does until the user message is projected."""
        self.add_thread(thread_id)
        turn_id = turn_id or new_id()
        ordinal = self.next_ordinal(thread_id) if ordinal is None else ordinal
        if completed is None and status != "inProgress":
            completed = int(self.clock())
        first = None
        if user_text is not None:
            item = self.add_item(thread_id, turn_id, "userMessage", user_text, client_id)
            first = item if first_user else None
        final = None
        if progress:
            item = self.add_item(thread_id, turn_id, "agentMessage")
            final = item if status == "completed" else None
        end = self._append(thread_id, [{"type": "event_msg", "payload": {"type": "turn", "turn_id": turn_id}}])
        with self._db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status, error_json, "
                       "started_at, completed_at, first_user_item_id, final_agent_item_id, "
                       "rollout_end_byte_offset) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (thread_id, turn_id, ordinal, status, error_json,
                        (BASE - 100) if started is None else started, completed, first, final, end))
        self.catch_up(thread_id)
        return turn_id

    def fail_usage(self, thread_id, turn_id=None, ordinal=None, *, completed=BASE, reset=RESET):
        """A failed turn with a usage limit, and the rollout events the reset hint reads."""
        self.add_thread(thread_id)
        turn_id = turn_id or new_id()
        events = []
        if reset is not None:
            events.append({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
                "limit_id": "codex", "primary": {"used_percent": 100, "resets_at": reset}}}})
        events.append({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn_id,
                                                        "error": {"codex_error_info": "usage_limit_exceeded"}}})
        self._append(thread_id, events)
        turn = self.add_turn(thread_id, turn_id, "failed", ordinal, completed=completed,
                             error_json=USAGE_ERROR, progress=False)
        # The failure event must be the last thing before the turn's end offset.
        with self._db("thread_history_1.sqlite") as db:
            db.execute("UPDATE thread_turns SET rollout_end_byte_offset=? WHERE thread_id=? AND turn_id=?",
                       (self._size_before_last(thread_id), thread_id, turn))
        return turn

    def _size_before_last(self, thread_id) -> int:
        data = self.rollout(thread_id).read_bytes()
        return len(data) - len(data.splitlines(keepends=True)[-1])

    def fail_transient(self, thread_id, turn_id=None, ordinal=None, *, completed=BASE, code="serverOverloaded",
                       error_json=None):
        return self.add_turn(thread_id, turn_id, "failed", ordinal, completed=completed,
                             error_json=error_json or transient_error(code), progress=False)

    def set_turn(self, thread_id, turn_id, **columns):
        with self._db("thread_history_1.sqlite") as db:
            for column, value in columns.items():
                db.execute("UPDATE thread_turns SET %s=? WHERE thread_id=? AND turn_id=?" % column,
                           (value, thread_id, turn_id))

    def turns(self, thread_id) -> list:
        with self._db("thread_history_1.sqlite") as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT * FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal", (thread_id,))]

    # --------------------------------------------------------------- queue
    def enqueue(self, thread_id, text, client_id=None) -> str:
        queue_id = new_id()
        payload = {"UserInput": {"content": [{"type": "text", "text": text}], "client_id": client_id}}
        with self._db("queue_1.sqlite") as db:
            order = db.execute("SELECT coalesce(max(queue_order), 0) + 1 FROM queued_items").fetchone()[0]
            db.execute("INSERT INTO queued_items (id, thread_id, payload_json, queue_order) VALUES (?,?,?,?)",
                       (queue_id, thread_id, json.dumps(payload), order))
        return queue_id

    def queued(self, thread_id) -> list:
        with self._db("queue_1.sqlite") as db:
            return [row[0] for row in db.execute(
                "SELECT id FROM queued_items WHERE thread_id=? ORDER BY queue_order", (thread_id,))]

    def remove_queued(self, queue_id) -> bool:
        with self._db("queue_1.sqlite") as db:
            return db.execute("DELETE FROM queued_items WHERE id=?", (queue_id,)).rowcount == 1

    def edit_queued(self, queue_id, text):
        with self._db("queue_1.sqlite") as db:
            db.execute("UPDATE queued_items SET payload_json=? WHERE id=?",
                       (json.dumps({"UserInput": {"content": [{"type": "text", "text": text}],
                                                  "client_id": None}}), queue_id))

    def dispatch(self, thread_id, *, status="completed", progress=True, completed=None,
                 steer_user=False, first_user=True):
        """What the desktop app does: take the head of the queue and start a turn with it.

        Returns the new turn id, or None when the queue is empty. `status="inProgress"`
        leaves the turn running; `set_turn` finishes it later.
        """
        with self._db("queue_1.sqlite") as db:
            row = db.execute("SELECT id, payload_json FROM queued_items WHERE thread_id=? "
                             "ORDER BY queue_order LIMIT 1", (thread_id,)).fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM queued_items WHERE id=?", (row[0],))
        payload = json.loads(row[1])["UserInput"]
        text = payload["content"][0]["text"]
        turn = self.add_turn(thread_id, None, status, completed=completed, user_text=text,
                             client_id=payload.get("client_id"), progress=progress,
                             first_user=first_user)
        if steer_user:
            self.add_item(thread_id, turn, "userMessage", "and also this", None)
        return turn


class SimBackend:
    """The Codex processes: queue, delete, loaded inventory and usage probe."""

    def __init__(self, home: CodexHome):
        self.home = home
        self.app = dict(APP)
        self.loaded_map: dict[str, str] = {}
        self.usage_result = {"available": True, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"}
        self.send_calls: list[tuple[str, str]] = []
        self.outcomes: dict[str, object] = {}
        self.default_outcome = "accepted"
        # After an accepted send: "dispatch" starts the turn at once (an idle, loaded
        # thread), "queue" leaves the item waiting in the queue.
        self.after_accept = "dispatch"
        self.turn_status = "completed"
        self.turn_progress = True
        self.deleted: list[tuple[str, str]] = []
        self.delete_result = None      # None: really delete; True/False: report that without deleting
        self.identity_calls = 0
        self.on_send = None

    def app_identity(self):
        self.identity_calls += 1
        return dict(self.app) if self.app else None

    def loaded(self, thread_id, app_identity):
        if not app_identity or app_identity != self.app:
            return "unknown"
        return self.loaded_map.get(thread_id, "notLoaded")

    def usage(self):
        return dict(self.usage_result)

    def send(self, thread_id, prompt):
        self.send_calls.append((thread_id, prompt))
        if self.on_send:
            self.on_send(thread_id, prompt)
        outcome = self.outcomes.get(thread_id, self.default_outcome)
        if callable(outcome):
            outcome = outcome()
        if outcome == "accepted":
            queue_id = self.home.enqueue(thread_id, prompt, client_id=new_id())
            if self.after_accept == "dispatch":
                self.home.dispatch(thread_id, status=self.turn_status, progress=self.turn_progress)
            return {"outcome": "accepted", "queue_id": queue_id}
        if outcome == "accepted_lost":
            return {"outcome": "accepted", "queue_id": new_id()}
        if outcome == "not_started":
            return {"outcome": "not_started", "error_code": "queue_spawn_failed"}
        if outcome == "raise":
            raise OSError("transport exploded")
        return {"outcome": "unknown", "error_code": "queue_timeout"}

    def delete_queue(self, thread_id, queue_id):
        self.deleted.append((thread_id, queue_id))
        if self.delete_result is None:
            return self.home.remove_queued(queue_id)
        return self.delete_result
