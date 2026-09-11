import ast
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid

from codex_auto_resume.source import LocalSource, SourceError, detect, normalize, _choose_reset

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codexsim  # noqa: E402  (a real Codex home; lives next to this file)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / "src" / "codex_auto_resume" / "source.py"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "usage-limit.json").read_text(encoding="utf-8"))
TID = FIXTURE["database_failure"]["thread_id"]
TURN = FIXTURE["database_failure"]["turn_id"]
SECOND = "33333333-3333-7333-8333-333333333333"
QID = "44444444-4444-7444-8444-444444444444"


def marker(digit="a"):
    return "[codex-auto-resume:" + digit * 64 + "]"


MARKER = marker("a")
# Text the tests put next to a marker. It must never come back out of the source.
SECRET = "harmless words that must not leave SQL"
LATER_STARTED = 1788628400
LATER_COMPLETED = 1788628500


class DetectionTests(unittest.TestCase):
    def test_real_usage_sample(self):
        found = detect(FIXTURE["database_failure"])
        self.assertEqual(found["category"], "usage_limit")
        self.assertEqual(found["thread_id"], TID)
        self.assertEqual(len(found["interruption_id"]), 64)
        self.assertNotIn("error_json", found)

    def test_nonusage_statuses(self):
        for status in ("completed", "interrupted", "inProgress"):
            with self.subTest(status=status):
                self.assertIsNone(detect(dict(FIXTURE["database_failure"], status=status)))

    def test_ordinary_failed(self):
        # Unknown and terminal categories are never registered, so they can never be
        # retried by any later stage.
        for error in ('{"codexErrorInfo":"other"}', '{"codexErrorInfo":"badRequest"}',
                      '{"codexErrorInfo":"unauthorized"}', '{"codexErrorInfo":"contextWindowExceeded"}',
                      '{"codexErrorInfo":{"httpStatusCode":404}}', None):
            with self.subTest(error=error):
                self.assertIsNone(detect(dict(FIXTURE["database_failure"], error_json=error)))

    def test_transient_failures_are_now_recoverable(self):
        for error, category in (
                ('{"codexErrorInfo":"httpConnectionFailed"}', "network_transient"),
                ('{"codexErrorInfo":"serverOverloaded"}', "server_5xx"),
                ('{"codexErrorInfo":"responseStreamDisconnected"}', "stream_interrupted"),
                ('{"codexErrorInfo":{"httpStatusCode":503}}', "server_5xx")):
            with self.subTest(error=error):
                found = detect(dict(FIXTURE["database_failure"], error_json=error))
                self.assertIsNotNone(found)
                self.assertEqual(found["category"], category)

    def test_malformed(self):
        for patch in ({"error_json": "broken"}, {"error_json": "[]"}, {"thread_id": "--last"},
                      {"turn_id": "bad"}, {"status": []}, {"started_at": None},
                      {"completed_at": None}, {"completed_at": 1788620000},
                      {"rollout_ordinal": True}, {"completed_at": float("nan")}):
            with self.subTest(patch=patch):
                self.assertIsNone(detect(dict(FIXTURE["database_failure"], **patch)))
        for row in (None, [], {}, "failed usageLimitExceeded"):
            self.assertIsNone(detect(row))

    def test_identity_stable_normalized_and_numeric(self):
        row = FIXTURE["database_failure"]
        key = detect(row)["interruption_id"]
        self.assertEqual(key, detect(normalize(row))["interruption_id"])
        self.assertEqual(key, detect(dict(row, completed_at=float(row["completed_at"])))["interruption_id"])
        self.assertNotEqual(key, detect(dict(row, turn_id=SECOND))["interruption_id"])

    def test_real_reset_and_timezone(self):
        limits = {r["limit_id"]: r for r in FIXTURE["rate_limits"]}
        hint = _choose_reset(limits, FIXTURE["database_failure"]["completed_at"])
        self.assertEqual(hint["reset_at"], FIXTURE["expected_reset_unix"])
        self.assertTrue(hint["uncertain"])
        stamp = datetime.fromtimestamp(hint["reset_at"], timezone(timedelta(hours=9))).isoformat()
        self.assertEqual(stamp, FIXTURE["expected_reset_kst"])

    def test_multiple_blocking_windows_wait_for_last(self):
        limits = {"codex": {"primary": {"used_percent": 100, "resets_at": 1788645827},
                             "secondary": {"used_percent": 100, "resets_at": 1789108889}}}
        hint = _choose_reset(limits, 1788628349)
        self.assertEqual(hint["reset_at"], 1789108889)
        self.assertEqual(hint["limit_type"], "codex:secondary")

    def test_unknown_reset_and_invalid_windows(self):
        self.assertIsNone(_choose_reset({}, 1788628349)["reset_at"])
        self.assertIsNone(_choose_reset({"premium": {"primary": {"used_percent": 100}}}, 1788628349)["reset_at"])

    def test_low_usage_hint_is_not_adopted_as_reset(self):
        # A fresh low-usage window's far-future reset must not delay the first check.
        low = {"codex": {"primary": {"used_percent": 12, "resets_at": 1788645827}}}
        self.assertIsNone(_choose_reset(low, 1788628349)["reset_at"])
        high = {"codex": {"primary": {"used_percent": 95, "resets_at": 1788645827}}}
        hint = _choose_reset(high, 1788628349)
        self.assertEqual(hint["reset_at"], 1788645827)
        self.assertEqual(hint["limit_type"], "codex:primary_hint")


class LocalSourceTests(unittest.TestCase):
    """A hand-built Codex home with the columns Codex 0.153.4 really has.

    The failed turn from the sanitized sample is ordinal 1 of thread TID. Tests add the
    turns, items and queued rows around it that each query has to tell apart.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.source = LocalSource(self.home)
        self.rollout = self.home / "sessions" / ("rollout-" + TID + ".jsonl")
        self.rollout.parent.mkdir()
        self.items = 0
        self.write_rollout()
        with self.db("state_5.sqlite") as db:
            db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT, "
                       "thread_source TEXT, archived INTEGER, history_mode TEXT, name TEXT, cwd TEXT, "
                       "project_id TEXT, title TEXT, first_user_message TEXT, preview TEXT)")
            db.execute("INSERT INTO threads (id, rollout_path, source, thread_source, archived, history_mode) "
                       "VALUES (?,?,'vscode','user',0,'paginated')", (TID, str(self.rollout)))
        with self.db("thread_history_1.sqlite") as db:
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
        with self.db("queue_1.sqlite") as db:
            db.execute("CREATE TABLE queued_items (id TEXT PRIMARY KEY, thread_id TEXT, payload_json TEXT, "
                       "queue_order INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER)")
        self.add_turn()
        self.catch_up()

    @contextmanager
    def db(self, name):
        connection = sqlite3.connect(self.home / name)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def tearDown(self):
        self.temp.cleanup()

    # ------------------------------------------------------------- fixtures
    def write_rollout(self, meta_patch=None):
        payload = {"id": TID, "originator": "Codex Desktop", "source": "vscode", "thread_source": "user"}
        payload.update(meta_patch or {})
        events = [{"type": "session_meta", "payload": payload}]
        events.extend({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": limit}}
                      for limit in FIXTURE["rate_limits"])
        events.append(FIXTURE["rollout_failure"])
        self.rollout.write_bytes(b"".join(json.dumps(e).encode() + b"\n" for e in events))

    def add_turn(self, **changes):
        """The sample failure (or a variant of it) as a real thread_turns row."""
        row = dict(FIXTURE["database_failure"], **changes)
        with self.db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_turns (thread_id, turn_id, status, started_at, completed_at, "
                       "rollout_ordinal, error_json, rollout_end_byte_offset) VALUES (?,?,?,?,?,?,?,?)",
                       tuple(row[k] for k in ("thread_id", "turn_id", "status", "started_at", "completed_at",
                                              "rollout_ordinal", "error_json"))
                       + (self.rollout.stat().st_size,))

    def later_turn(self, ordinal, status="completed", *, first=None, thread=TID, turn_id=None):
        """A turn after the failed one. `first` is its first_user_item_id (None: unset)."""
        turn_id = turn_id or str(uuid.uuid4())
        completed = None if status == "inProgress" else LATER_COMPLETED + ordinal
        with self.db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status, started_at, "
                       "completed_at, first_user_item_id) VALUES (?,?,?,?,?,?,?)",
                       (thread, turn_id, ordinal, status, LATER_STARTED + ordinal, completed, first))
        return turn_id

    def set_turn(self, turn_id, thread=TID, **columns):
        with self.db("thread_history_1.sqlite") as db:
            for column, value in columns.items():
                db.execute("UPDATE thread_turns SET %s=? WHERE thread_id=? AND turn_id=?" % column,
                           (value, thread, turn_id))

    def add_item(self, turn_id, item_type, payload=None, *, thread=TID, text=None, client_id=None,
                 item_id=None):
        """One thread_items row. Without a payload, the shape Codex writes for the type."""
        self.items += 1
        item_id = item_id or "item-%d" % self.items
        if payload is None:
            if item_type == "userMessage":
                payload = {"type": "userMessage", "id": item_id, "clientId": client_id,
                           "content": [{"type": "text", "text": text or "a message from the user"}]}
            else:
                payload = {"type": item_type, "id": item_id, "text": text or "work"}
        with self.db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_items (thread_id, turn_id, item_id, rollout_ordinal, item_json, "
                       "item_type) VALUES (?,?,?,?,?,?)",
                       (thread, turn_id, item_id, self.items,
                        payload if isinstance(payload, str) else json.dumps(payload), item_type))
        return item_id

    def our_turn(self, ordinal, the_marker=MARKER, status="completed", client_id=None):
        """A turn our continuation started: its first user item holds the marker."""
        turn_id = self.later_turn(ordinal, status)
        item = self.add_item(turn_id, "userMessage", text=SECRET + " " + the_marker, client_id=client_id)
        self.set_turn(turn_id, first_user_item_id=item)
        return turn_id

    def enqueue(self, payload, *, thread=TID, queue_id=None):
        """A queued_items row. A string payload is user text in the pinned serde shape."""
        queue_id = queue_id or str(uuid.uuid4())
        if isinstance(payload, str):
            payload = {"UserInput": {"content": [{"type": "text", "text": payload}], "client_id": None}}
        with self.db("queue_1.sqlite") as db:
            order = db.execute("SELECT coalesce(max(queue_order), 0) + 1 FROM queued_items").fetchone()[0]
            db.execute("INSERT INTO queued_items (id, thread_id, payload_json, queue_order) VALUES (?,?,?,?)",
                       (queue_id, thread, json.dumps(payload), order))
        return queue_id

    def enqueue_raw(self, raw, *, thread=TID, queue_id=None):
        queue_id = queue_id or str(uuid.uuid4())
        with self.db("queue_1.sqlite") as db:
            db.execute("INSERT INTO queued_items (id, thread_id, payload_json, queue_order) VALUES (?,?,?,0)",
                       (queue_id, thread, raw))
        return queue_id

    def catch_up(self, thread=TID):
        """The projection reaches the end of the rollout file, as it does in Codex."""
        size = self.rollout.stat().st_size
        with self.db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_history_projection_state VALUES (?,?,0) "
                       "ON CONFLICT(thread_id) DO UPDATE SET "
                       "next_rollout_byte_offset=excluded.next_rollout_byte_offset", (thread, size))

    def assertContentFree(self, value):
        self.assertNotIn(SECRET, repr(value))
        self.assertNotIn("harmless", repr(value))

    # ------------------------------------------------------------ detection
    def test_detect_actual_shape(self):
        self.assertEqual(len(self.source.latest_failures(1788620000)), 1)
        self.assertEqual(self.source.latest(TID)["turn_id"], TURN)
        self.assertEqual(self.source.reset_hint(TID, TURN)["reset_at"], FIXTURE["expected_reset_unix"])

    def test_latest_completion_cancellation_error_supersedes(self):
        for status in ("completed", "interrupted", "inProgress", "failed"):
            with self.subTest(status=status):
                self.add_turn(turn_id=SECOND, rollout_ordinal=2, status=status, error_json=None)
                self.assertEqual(self.source.latest_failures(1788620000), [])
                self.assertEqual(self.source.latest(TID)["turn_id"], SECOND)
                with self.db("thread_history_1.sqlite") as db:
                    db.execute("DELETE FROM thread_turns WHERE turn_id=?", (SECOND,))

    def test_ignore_historic_failure(self):
        self.assertEqual(self.source.latest_failures(1788628350), [])

    def test_exclude_subagents_and_archives(self):
        for column, value in (("archived", 1), ("thread_source", "subagent"), ("source", "cli"), ("history_mode", "legacy")):
            with self.subTest(column=column):
                with self.db("state_5.sqlite") as db:
                    before = db.execute("SELECT " + column + " FROM threads").fetchone()[0]
                    db.execute("UPDATE threads SET " + column + "=?", (value,))
                self.assertEqual(self.source.latest_failures(1788620000), [])
                self.assertIsNone(self.source.latest(TID))
                with self.db("state_5.sqlite") as db:
                    db.execute("UPDATE threads SET " + column + "=?", (before,))

    def test_originator_and_exact_meta_identity(self):
        for patch in ({"originator": "Codex CLI"}, {"id": SECOND}, {"thread_source": "subagent"}):
            self.write_rollout(patch)
            self.assertEqual(self.source.latest_failures(1788620000), [])

    def test_outside_rollout_path_is_not_read(self):
        with self.db("state_5.sqlite") as db:
            db.execute("UPDATE threads SET rollout_path=?", (str(self.home.parent / (TID + ".jsonl")),))
        self.assertIsNone(self.source.latest(TID))

    def test_reset_ignores_later_snapshots(self):
        with self.rollout.open("ab") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {"limit_id": "codex", "primary": {"used_percent": 100, "resets_at": 1789108889}}}}).encode() + b"\n")
        self.assertEqual(self.source.reset_hint(TID, TURN)["reset_at"], FIXTURE["expected_reset_unix"])

    def test_transient_rollout_read_error_defers_not_supersedes(self):
        # A rollout that cannot be read (here: replaced by a directory) is transient.
        # latest() (strict) raises so the engine defers; latest_failures skips the thread.
        self.rollout.unlink()
        self.rollout.mkdir()
        try:
            with self.assertRaises(SourceError):
                self.source.latest(TID)
            self.assertEqual(self.source.latest_failures(1788620000), [])
        finally:
            self.rollout.rmdir()
            self.write_rollout()

    def test_missing_failure_event_no_guessed_reset(self):
        self.rollout.write_bytes(self.rollout.read_bytes().splitlines(keepends=True)[0])
        self.assertIsNone(self.source.reset_hint(TID, TURN)["reset_at"])

    # ---------------------------------------------------------- marker_rows
    def test_marker_rows_only_user_message_text_holds_the_marker(self):
        """§4.1: only userMessage rows whose *text content* holds our marker are ours.

        The marker in an assistant message (it may quote us), in an id or other
        metadata field, in a non-text content item, or on another thread is not a
        delivery of this continuation.
        """
        turn = self.later_turn(2)
        self.add_item(turn, "agentMessage", text=SECRET + " " + MARKER)
        self.add_item(turn, "userMessage", {"type": "userMessage", "id": MARKER, "clientId": None,
                                            "content": []})
        self.add_item(turn, "userMessage", {"type": "userMessage", "id": "x1", "clientId": None,
                                            "content": [{"type": "text", "text": "hi", "note": MARKER}]})
        self.add_item(turn, "userMessage", {"type": "userMessage", "id": "x2", "clientId": None,
                                            "content": [{"type": "image", "url": "data:" + MARKER}]})
        self.add_item(turn, "userMessage", {"type": "userMessage", "id": "x3", "clientId": None,
                                            "metadata": {"text": MARKER}, "content": []})
        self.add_item(turn, "userMessage", text=SECRET + " " + MARKER, thread=SECOND)
        self.assertEqual(self.source.marker_rows(TID, MARKER), [])
        item = self.add_item(turn, "userMessage", text=SECRET + " " + MARKER)
        self.set_turn(turn, first_user_item_id=item)
        rows = self.source.marker_rows(TID, MARKER)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["turn_id"], turn)
        self.assertContentFree(rows)

    def test_marker_rows_report_their_own_turn_not_the_latest(self):
        """T01/§4.1: the turn is the marker row's own turn, even after a person has
        already started a newer one."""
        ours = self.our_turn(2)
        self.later_turn(3, "inProgress")
        user = self.later_turn(4)
        self.set_turn(user, first_user_item_id=self.add_item(user, "userMessage"))
        rows = self.source.marker_rows(TID, MARKER)
        self.assertEqual([row["turn_id"] for row in rows], [ours])
        self.assertEqual(rows[0]["ordinal"], 2)

    def test_marker_rows_turn_facts(self):
        """starts_turn, first_unset, ordinal and status of the marker row's turn (§4.1
        rules 5 and 6), with an unknown status closed to 'other' (§2.1, M8)."""
        a, b, c = marker("a"), marker("b"), marker("c")
        started = self.our_turn(2, a, status="completed")
        steered = self.later_turn(3, "somethingNewInCodex")
        self.set_turn(steered, first_user_item_id=self.add_item(steered, "userMessage"))
        self.add_item(steered, "userMessage", text=SECRET + " " + b)
        unset = self.later_turn(4, "inProgress")
        self.add_item(unset, "userMessage", text=SECRET + " " + c)
        cases = (
            (a, {"turn_id": started, "ordinal": 2, "status": "completed",
                 "starts_turn": True, "first_unset": False}),
            (b, {"turn_id": steered, "ordinal": 3, "status": "other",
                 "starts_turn": False, "first_unset": False}),
            (c, {"turn_id": unset, "ordinal": 4, "status": "inProgress",
                 "starts_turn": False, "first_unset": True}),
        )
        for the_marker, expected in cases:
            with self.subTest(expected=expected):
                rows = self.source.marker_rows(TID, the_marker)
                self.assertEqual(len(rows), 1)
                for key, value in expected.items():
                    self.assertEqual(rows[0][key], value, key)
                self.assertContentFree(rows)

    def test_marker_rows_never_claim_to_start_an_unprojected_turn(self):
        """A marker item whose turn row is not projected yet cannot say who started the
        turn: it is never reported as having started one."""
        self.add_item(str(uuid.uuid4()), "userMessage", text=SECRET + " " + MARKER)
        for row in self.source.marker_rows(TID, MARKER):
            self.assertFalse(row["starts_turn"])
            self.assertTrue(row["first_unset"])

    def test_marker_rows_return_every_copy(self):
        """§4.1 rule 2: two marker rows are reported as two; the source never picks one."""
        self.our_turn(2)
        self.our_turn(3)
        self.assertEqual(len(self.source.marker_rows(TID, MARKER)), 2)

    def test_marker_rows_client_id(self):
        """§2.1: a client id is kept only if it matches [A-Za-z0-9-]{1,64}; else None."""
        for index, (client, expected) in enumerate((
                ("abc-123", "abc-123"), (None, None), ("not valid!", None), ("a" * 65, None),
                ("a" * 64, "a" * 64), (123, None), ("", None))):
            the_marker = marker("0123456789"[index])
            with self.subTest(client=client):
                turn = self.later_turn(10 + index)
                item = self.add_item(turn, "userMessage",
                                     {"type": "userMessage", "id": "c%d" % index, "clientId": client,
                                      "content": [{"type": "text", "text": the_marker}]})
                self.set_turn(turn, first_user_item_id=item)
                rows = self.source.marker_rows(TID, the_marker)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["client_id"], expected)

    # ---------------------------------------------------------- queued_rows
    def test_queued_rows_pinned_serde(self):
        """Only the version-pinned TurnInput shape {"UserInput": {...}} with the marker in
        a text item is our queued item; ids and client ids only come back."""
        ours = self.enqueue({"UserInput": {"content": [{"type": "text", "text": SECRET + " " + MARKER}],
                                           "client_id": "client-1"}})
        self.enqueue(SECRET + " " + MARKER, thread=SECOND)
        for shape in (
                {"type": "UserInput", "content": [{"type": "text", "text": MARKER}]},
                {"UserInput": {"content": [{"type": "text", "text": MARKER}]}, "extra": 1},
                {"userInput": {"content": [{"type": "text", "text": MARKER}]}},
                {"UserInput": {"content": [{"type": "image", "url": MARKER}]}},
                {"UserInput": {"content": [], "client_id": MARKER}},
                {"UserInput": {"content": [{"type": "text", "text": "hi", "note": MARKER}]}},
                [{"UserInput": {"content": [{"type": "text", "text": MARKER}]}}]):
            self.enqueue(shape)
        self.enqueue_raw("not json " + MARKER)
        rows = self.source.queued_rows(TID, MARKER)
        self.assertEqual(rows, [{"id": ours, "client_id": "client-1"}])
        self.assertContentFree(rows)

    def test_queued_rows_invalid_client_id_is_none(self):
        self.enqueue({"UserInput": {"content": [{"type": "text", "text": MARKER}], "client_id": "bad id!"}})
        self.assertEqual([row["client_id"] for row in self.source.queued_rows(TID, MARKER)], [None])

    # ------------------------------------------------------------ queue_row
    def test_queue_row_exists_and_has_marker(self):
        """§5.3/C16: our exact queue id, and whether it still holds our marker. A row
        someone edited in Codex reports exists without the marker, and nothing of it."""
        ours = self.enqueue(SECRET + " " + MARKER)
        self.assertEqual(self.source.queue_row(TID, ours, MARKER), {"exists": True, "has_marker": True})
        with self.db("queue_1.sqlite") as db:
            db.execute("UPDATE queued_items SET payload_json=? WHERE id=?",
                       (json.dumps({"UserInput": {"content": [{"type": "text", "text": SECRET}],
                                                  "client_id": None}}), ours))
        edited = self.source.queue_row(TID, ours, MARKER)
        self.assertEqual(edited, {"exists": True, "has_marker": False})
        self.assertContentFree(edited)
        with self.db("queue_1.sqlite") as db:
            db.execute("DELETE FROM queued_items WHERE id=?", (ours,))
        self.assertEqual(self.source.queue_row(TID, ours, MARKER), {"exists": False, "has_marker": False})

    def test_queue_row_is_scoped_to_the_thread(self):
        elsewhere = self.enqueue(MARKER, thread=SECOND)
        self.assertFalse(self.source.queue_row(TID, elsewhere, MARKER)["exists"])

    def test_queue_row_refuses_a_bad_queue_id(self):
        with self.assertRaises(SourceError):
            self.source.queue_row(TID, "--all", MARKER)

    # ------------------------------------------------------- foreign_queued
    def test_foreign_queued_counts_only(self):
        """§5.3/D18: how many items on this thread's queue are not ours - a number."""
        self.assertEqual(self.source.foreign_queued(TID, MARKER), 0)
        self.enqueue(SECRET + " " + MARKER)
        self.assertEqual(self.source.foreign_queued(TID, MARKER), 0)
        self.enqueue(SECRET)
        self.enqueue(SECRET, thread=SECOND)
        self.enqueue({"UserInput": {"content": [{"type": "text", "text": SECRET}], "client_id": "x"}})
        count = self.source.foreign_queued(TID, MARKER)
        self.assertIs(type(count), int)
        self.assertEqual(count, 2)

    # ---------------------------------------------------------- later_turns
    def test_later_turns_three_way_classification(self):
        """§5.2: every turn after the failed ordinal is ours, undetermined, or foreign.

        Foreign includes a finished turn that never recorded a user item
        (turn_without_user_item: input a hook blocked, U3), a turn whose first item is
        an assistant message holding our marker, and a turn pointing at an item id
        that holds our marker only on another thread.
        """
        before = self.later_turn(0)           # older than the failure: never listed
        self.set_turn(before, first_user_item_id=self.add_item(before, "userMessage"))
        self.our_turn(2)
        self.later_turn(3, "inProgress")
        self.later_turn(4, "completed")
        self.later_turn(5, "failed")
        self.later_turn(6, "interrupted")
        user = self.later_turn(7)
        self.set_turn(user, first_user_item_id=self.add_item(user, "userMessage", text=SECRET))
        agent = self.later_turn(8)
        self.set_turn(agent, first_user_item_id=self.add_item(agent, "agentMessage", text=MARKER))
        borrowed = self.later_turn(9)
        self.add_item(borrowed, "userMessage", text=MARKER, thread=SECOND, item_id="shared-id")
        self.set_turn(borrowed, first_user_item_id="shared-id")
        turns = self.source.later_turns(TID, 1, MARKER)
        self.assertEqual([(turn["ordinal"], turn["kind"]) for turn in turns],
                         [(2, "ours"), (3, "undetermined"), (4, "foreign"), (5, "foreign"),
                          (6, "foreign"), (7, "foreign"), (8, "foreign"), (9, "foreign")])
        for turn in turns:
            if turn["ordinal"] in (4, 5, 6):
                self.assertEqual(turn["reason"], "turn_without_user_item")
        self.assertContentFree(turns)

    def test_later_turns_baseline_is_the_ordinal(self):
        """C6: the baseline is rollout_ordinal > the failed ordinal, nothing else."""
        self.later_turn(2)
        self.later_turn(3)
        self.assertEqual([turn["ordinal"] for turn in self.source.later_turns(TID, 2, MARKER)], [3])
        self.assertEqual(self.source.later_turns(TID, 3, MARKER), [])
        self.assertEqual(len(self.source.later_turns(TID, 1, MARKER)), 2)

    def test_later_turns_other_thread_is_invisible(self):
        self.later_turn(2, thread=SECOND)
        self.assertEqual(self.source.later_turns(TID, 1, MARKER), [])

    # ----------------------------------------------------- turn_observation
    def test_turn_observation_status_closed_enum(self):
        """§2.1/M8: any status Codex adds is reported as 'other'."""
        turn = self.our_turn(2)
        for status, expected in (("completed", "completed"), ("failed", "failed"),
                                 ("interrupted", "interrupted"), ("inProgress", "inProgress"),
                                 ("cancelledByHook", "other"), ("", "other")):
            with self.subTest(status=status):
                self.set_turn(turn, status=status)
                seen = self.source.turn_observation(TID, turn, MARKER)
                self.assertTrue(seen["found"])
                self.assertEqual(seen["status"], expected)

    def test_turn_observation_progress_only_known_types_in_that_turn(self):
        """§4.2: progress is an agentMessage, commandExecution, fileChange or mcpToolCall
        in *that* turn. Unknown item types and later turns never count."""
        for kind in ("agentMessage", "commandExecution", "fileChange", "mcpToolCall"):
            with self.subTest(kind=kind):
                turn = self.our_turn(self.items + 10, marker("b"))
                self.assertFalse(self.source.turn_observation(TID, turn, marker("b"))["progress"])
                self.add_item(turn, kind)
                self.assertTrue(self.source.turn_observation(TID, turn, marker("b"))["progress"])
                with self.db("thread_history_1.sqlite") as db:
                    db.execute("DELETE FROM thread_items WHERE turn_id=?", (turn,))
                    db.execute("DELETE FROM thread_turns WHERE turn_id=?", (turn,))
        turn = self.our_turn(2)
        for kind in ("reasoning", "webSearch", "plan", "contextCompaction", "somethingNew",
                     "AgentMessage", "userMessage"):
            self.add_item(turn, kind)
        later = self.later_turn(3)
        self.add_item(later, "agentMessage")
        self.add_item(later, "fileChange")
        self.add_item(turn, "agentMessage", thread=SECOND)
        self.assertFalse(self.source.turn_observation(TID, turn, MARKER)["progress"])

    def test_turn_observation_counts_foreign_user_messages(self):
        """§4.2/U10: every non-marker userMessage in the turn counts, whatever its
        clientId; our own message and other turns' messages do not."""
        turn = self.our_turn(2, client_id="ours-1")
        self.assertEqual(self.source.turn_observation(TID, turn, MARKER)["foreign_user_messages"], 0)
        self.add_item(turn, "userMessage", text=SECRET, client_id=None)
        self.add_item(turn, "userMessage", text=SECRET, client_id="a-string-id")
        later = self.later_turn(3)
        self.add_item(later, "userMessage", text=SECRET)
        self.add_item(turn, "agentMessage", text=SECRET)
        seen = self.source.turn_observation(TID, turn, MARKER)
        self.assertEqual(seen["foreign_user_messages"], 2)
        self.assertContentFree(seen)

    def test_turn_observation_later_terminal(self):
        """§4.3/U4: a later turn that is terminal shows an inProgress row is stale. The
        failed turn before ours, and a later turn still running, do not."""
        turn = self.our_turn(2, status="inProgress")
        self.assertFalse(self.source.turn_observation(TID, turn, MARKER)["later_terminal"])
        later = self.later_turn(3, "inProgress")
        self.assertFalse(self.source.turn_observation(TID, turn, MARKER)["later_terminal"])
        for status in ("completed", "failed", "interrupted"):
            with self.subTest(status=status):
                self.set_turn(later, status=status)
                self.assertTrue(self.source.turn_observation(TID, turn, MARKER)["later_terminal"])

    def test_turn_observation_missing_turn(self):
        self.assertFalse(self.source.turn_observation(TID, str(uuid.uuid4()), MARKER)["found"])

    def test_turn_observation_completed_at(self):
        turn = self.our_turn(2)
        self.assertEqual(self.source.turn_observation(TID, turn, MARKER)["completed_at"], LATER_COMPLETED + 2)

    # --------------------------------------------------------- turn_progress
    def test_turn_progress_true_false(self):
        """§4.4 failed_turn_progress: the failed turn's own items decide."""
        self.assertIs(self.source.turn_progress(TID, TURN), False)
        self.add_item(TURN, "reasoning")
        self.add_item(TURN, "userMessage")
        self.add_item(TURN, "agentMessage", thread=SECOND)
        self.assertIs(self.source.turn_progress(TID, TURN), False)
        self.add_item(TURN, "commandExecution")
        self.assertIs(self.source.turn_progress(TID, TURN), True)

    def test_turn_progress_none_when_unreadable(self):
        """§4.4: None when the history cannot be read - never a guessed False."""
        with self.db("thread_history_1.sqlite") as db:
            db.execute("DROP TABLE thread_items")
        self.assertIsNone(self.source.turn_progress(TID, TURN))
        self.assertIsNone(LocalSource(self.home).turn_progress(TID, TURN))
        (self.home / "thread_history_1.sqlite").write_bytes(b"not sqlite at all")
        self.assertIsNone(LocalSource(self.home).turn_progress(TID, TURN))

    # --------------------------------------------------------- turn_markers
    def test_turn_markers_user_messages_of_that_turn(self):
        """§4.4 owner lookup: which candidate markers are in a userMessage of the failed
        turn. A marker quoted by the assistant, or in another turn or thread, is not."""
        a, b, c, d = marker("a"), marker("b"), marker("c"), marker("d")
        self.add_item(TURN, "userMessage", text=SECRET + " " + a)
        self.add_item(TURN, "agentMessage", text=b)
        later = self.later_turn(2)
        self.add_item(later, "userMessage", text=c)
        self.add_item(TURN, "userMessage", text=d, thread=SECOND)
        found = self.source.turn_markers(TID, TURN, [a, b, c, d])
        self.assertEqual(sorted(found), [a])
        self.assertContentFree(found)
        self.assertEqual(self.source.turn_markers(TID, TURN, []), [])

    # ------------------------------------------------------ marker_presence
    def test_marker_presence_counts_any_row_on_the_thread(self):
        """§1 duplicate-owner check: any queued or history row on the thread that
        carries our marker. Counts only; other threads never count."""
        self.assertEqual(self.source.marker_presence(TID, MARKER), {"history": 0, "queue": 0})
        self.enqueue(SECRET + " " + MARKER)
        self.enqueue(MARKER, thread=SECOND)
        self.add_item(TURN, "userMessage", text=MARKER, thread=SECOND)
        self.assertEqual(self.source.marker_presence(TID, MARKER), {"history": 0, "queue": 1})
        self.add_item(TURN, "userMessage", text=SECRET + " " + MARKER)
        self.add_item(TURN, "agentMessage", text=MARKER)
        presence = self.source.marker_presence(TID, MARKER)
        self.assertEqual(presence, {"history": 2, "queue": 1})
        self.assertEqual(self.source.marker_presence(TID, marker("f")), {"history": 0, "queue": 0})

    # ----------------------------------------------------------- projection
    def test_projection_fresh_when_caught_up(self):
        """§6/U5: fresh when the rollout size equals next_rollout_byte_offset."""
        self.assertEqual(self.source.projection(TID), {"table": True, "fresh": True})

    def test_projection_not_fresh_when_the_rollout_grew(self):
        with self.rollout.open("ab") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {"type": "noise"}}).encode() + b"\n")
        self.assertEqual(self.source.projection(TID), {"table": True, "fresh": False})
        self.catch_up()
        self.assertEqual(self.source.projection(TID)["fresh"], True)

    def test_projection_table_missing(self):
        """§6 engine_compatible: a missing projection-state table is reported as such."""
        with self.db("thread_history_1.sqlite") as db:
            db.execute("DROP TABLE thread_history_projection_state")
        found = self.source.projection(TID)
        self.assertIs(found["table"], False)
        self.assertNotEqual(found["fresh"], True)

    def test_projection_row_missing_is_unknown(self):
        with self.db("thread_history_1.sqlite") as db:
            db.execute("DELETE FROM thread_history_projection_state WHERE thread_id=?", (TID,))
        self.assertEqual(self.source.projection(TID), {"table": True, "fresh": None})

    # --------------------------------------------------------- schema drift
    def test_survives_a_schema_generation_bump(self):
        # A Codex update that renames state_5 -> state_6 (and friends) must not break
        # detection: the newest generation whose schema still fits is discovered.
        renames = {"state_5.sqlite": "state_6.sqlite",
                   "thread_history_1.sqlite": "thread_history_2.sqlite",
                   "queue_1.sqlite": "queue_9.sqlite"}
        for old, new in renames.items():
            (self.home / old).rename(self.home / new)
        fresh = LocalSource(self.home)
        self.assertEqual(fresh.resolve("state"), "state_6.sqlite")
        self.assertEqual(fresh.resolve("history"), "thread_history_2.sqlite")
        self.assertEqual(fresh.resolve("queue"), "queue_9.sqlite")
        self.assertEqual(len(fresh.latest_failures(1788620000)), 1)
        self.assertEqual(fresh.latest(TID)["turn_id"], TURN)

    def test_prefers_the_newest_usable_generation(self):
        # An older generation left behind by a migration must not win over the new one.
        import shutil
        shutil.copy(self.home / "thread_history_1.sqlite", self.home / "thread_history_7.sqlite")
        self.assertEqual(LocalSource(self.home).resolve("history"), "thread_history_7.sqlite")

    def test_newer_generation_with_missing_column_falls_back_then_refuses(self):
        # A newer file whose schema lost a column we read is skipped in favour of an
        # older usable one; if none is usable at all, we refuse rather than guess.
        with self.db("thread_history_5.sqlite") as db:
            db.execute("CREATE TABLE thread_turns(thread_id TEXT, turn_id TEXT)")   # columns missing
            db.execute("CREATE TABLE thread_items(thread_id TEXT, item_type TEXT, item_json TEXT)")
        self.assertEqual(LocalSource(self.home).resolve("history"), "thread_history_1.sqlite")
        (self.home / "thread_history_1.sqlite").unlink()
        with self.assertRaises(SourceError):
            LocalSource(self.home).resolve("history")

    def test_corrupt_database_safe_error(self):
        (self.home / "thread_history_1.sqlite").write_bytes(b"not sqlite sensitive-data")
        # A corrupt file is simply not a usable generation; the message stays static
        # and must never quote file contents.
        with self.assertRaises(SourceError) as caught:
            self.source.latest_failures(1788620000)
        self.assertNotIn("sensitive-data", str(caught.exception))

    def test_missing_schema_safe_error(self):
        with self.db("thread_history_1.sqlite") as db:
            db.execute("DROP TABLE thread_turns")
        with self.assertRaises(SourceError):
            self.source.latest(TID)

    def test_read_only_connection(self):
        with self.source._db("state") as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM threads")

    def test_invalid_identity_and_timestamp(self):
        self.assertIsNone(self.source.latest("--last"))
        for bad_thread, bad_marker in ((TID, "anything"), (TID, MARKER + "x"), ("--last", MARKER),
                                       (TID, "[codex-auto-resume:" + "A" * 64 + "]")):
            with self.subTest(thread=bad_thread, marker=bad_marker):
                for call in (lambda: self.source.marker_rows(bad_thread, bad_marker),
                             lambda: self.source.queued_rows(bad_thread, bad_marker),
                             lambda: self.source.foreign_queued(bad_thread, bad_marker),
                             lambda: self.source.later_turns(bad_thread, 1, bad_marker),
                             lambda: self.source.turn_observation(bad_thread, TURN, bad_marker),
                             lambda: self.source.marker_presence(bad_thread, bad_marker)):
                    with self.assertRaises(SourceError):
                        call()
        with self.assertRaises(SourceError):
            self.source.latest_failures(float("nan"))


# ---------------------------------------------------------------- static checks
def _matching_paren(text, open_index):
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(text) - 1


def _strip_calls(text, name):
    """`text` with every `name(...)` call removed, nested parentheses included."""
    pattern = re.compile(r"\b%s\s*\(" % name, re.IGNORECASE)
    while True:
        match = pattern.search(text)
        if not match:
            return text
        end = _matching_paren(text, match.end() - 1)
        text = text[:match.start()] + " __%s__ " % name + text[end + 1:]


def _blank_subqueries(text):
    """`text` with every parenthesised group that holds a SELECT removed."""
    index = 0
    while index < len(text):
        if text[index] == "(":
            end = _matching_paren(text, index)
            if re.search(r"\bSELECT\b", text[index:end + 1], re.IGNORECASE):
                text = text[:index] + "(__subquery__)" + text[end + 1:]
        index += 1
    return text


def _selects(sql):
    """Every SELECT in a statement, nested ones included: (column list, rest of it).

    `rest` runs from that SELECT's own FROM to the end of its own scope.
    """
    upper = sql.upper()
    for match in re.finditer(r"\bSELECT\b", upper):
        depth, index, start = 0, match.end(), match.end()
        columns_end = None
        while index < len(sql):
            char = sql[index]
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            elif (columns_end is None and depth == 0 and upper.startswith("FROM", index)
                  and not (upper[index - 1].isalnum() or upper[index - 1] == "_")
                  and not (index + 4 < len(upper) and (upper[index + 4].isalnum() or upper[index + 4] == "_"))):
                columns_end = index
            index += 1
        if columns_end is None:
            columns_end = index
        yield sql[start:columns_end], sql[columns_end:index]


def _split_top_level(text):
    parts, depth, current = [], 0, ""
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return [part for part in parts if part]


def _sql_strings():
    tree = ast.parse(SOURCE_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and re.match(r"\s*(SELECT|WITH)\b", node.value, re.IGNORECASE)):
            yield node.lineno, node.value


CONTENT_COLUMNS = ("item_json", "payload_json")
# What a query over somebody else's rows may return: counts, booleans and ids.
SAFE_COLUMN = re.compile(
    r"(?:count\s*\(\s*(?:\*|[\w.]+)\s*\)"
    r"|EXISTS\s*\(.*\)"
    r"|__instr__\s*(?:[<>=!]=?|<>)\s*\d+"
    r"|[\w.]+\s+IS\s+(?:NOT\s+)?NULL"
    r"|1"
    r"|(?:\w+\.)?(?:id|\w+_id))"
    r"(?:\s+AS\s+\w+)?", re.IGNORECASE | re.DOTALL)


class StaticQueryTests(unittest.TestCase):
    def test_T11_content_is_marker_bounded_and_foreign_rows_are_counts(self):
        """T11/D21: every history or queue query that returns item_json or payload_json
        is bounded by instr(<column>,<marker>)>0 in its own WHERE, so the only message
        text that can leave SQL is our own continuation. Every query over non-marker
        rows (instr(...)=0) returns only counts, booleans or ids."""
        content_queries, foreign_queries = set(), 0
        for line, sql in _sql_strings():
            for columns, rest in _selects(sql):
                visible = _strip_calls(_strip_calls(columns, "instr"), "EXISTS")
                visible_no_count = re.sub(r"count\s*\(\s*\*\s*\)", "", visible, flags=re.IGNORECASE)
                reads_items = re.search(r"\b(thread_items|queued_items)\b", rest)
                for column in CONTENT_COLUMNS:
                    selects_it = re.search(r"\b%s\b" % column, visible) or (
                        reads_items and "*" in visible_no_count)
                    if not selects_it:
                        continue
                    content_queries.add((line, column))
                    own_where = _blank_subqueries(rest)
                    with self.subTest(line=line, column=column):
                        self.assertRegex(
                            own_where, r"instr\(\s*(?:\w+\.)?%s\s*,\s*\?\s*\)\s*>\s*0" % column,
                            "line %d returns %s without the marker bound" % (line, column))
            if re.search(r"instr\s*\([^()]*\)\s*=\s*0", sql, re.IGNORECASE):
                foreign_queries += 1
                for columns, _ in _selects(sql):
                    visible = _strip_calls(columns, "instr")
                    # Nested SELECTs (inside EXISTS) are yielded and checked on their own.
                    for part in _split_top_level(visible):
                        with self.subTest(line=line, column=part):
                            self.assertTrue(SAFE_COLUMN.fullmatch(part),
                                            "line %d returns %r over rows that are not ours; only "
                                            "counts, booleans or ids may leave SQL" % (line, part))
        # Not vacuous: the marker query and the queue query both exist and were checked.
        self.assertEqual({column for _, column in content_queries}, set(CONTENT_COLUMNS))
        self.assertGreaterEqual(foreign_queries, 2)

    def test_T11_checker_catches_an_unbounded_query(self):
        """The static checker itself: a bound that sits only in a sub-query does not
        count, and a foreign-row query may not return text or non-id columns."""
        bad = ("SELECT i.item_json FROM thread_items i WHERE i.thread_id=? AND EXISTS("
               "SELECT 1 FROM thread_items j WHERE instr(j.item_json,?)>0)")
        columns, rest = next(_selects(bad))
        self.assertIn("item_json", _strip_calls(columns, "instr"))
        self.assertNotRegex(_blank_subqueries(rest), r"instr\(\s*(?:\w+\.)?item_json\s*,\s*\?\s*\)\s*>\s*0")
        good = "SELECT i.item_json FROM thread_items i WHERE i.thread_id=? AND instr(i.item_json,?)>0"
        columns, rest = next(_selects(good))
        self.assertRegex(_blank_subqueries(rest), r"instr\(\s*(?:\w+\.)?item_json\s*,\s*\?\s*\)\s*>\s*0")
        for unsafe in ("item_json", "i.payload_json", "t.status", "i.item_json AS first_id",
                       "json_extract(item_json,'$.clientId')", "substr(payload_json,1,10)"):
            self.assertIsNone(SAFE_COLUMN.fullmatch(unsafe), unsafe)
        for safe in ("count(*)", "t.turn_id", "id", "1", "__instr__>0 AS has_marker",
                     "t.first_user_item_id IS NOT NULL AS has_first",
                     "EXISTS(SELECT 1 FROM thread_items i WHERE i.item_id=t.first_user_item_id)"):
            self.assertIsNotNone(SAFE_COLUMN.fullmatch(safe), safe)

    def test_T01_latest_turn_id_is_gone(self):
        """T01/D1: the name of the old "latest turn" id is gone from every source file."""
        found = []
        for path in (ROOT / "src").rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            if b"latest_turn_id" in path.read_bytes():
                found.append(str(path.relative_to(ROOT)))
        self.assertEqual(found, [])


# ------------------------------------------------------------ child threads
class ChildThreadTests(unittest.TestCase):
    """T47 on the real schema: a subagent or non-Desktop thread is never detected."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = codexsim.CodexHome(Path(self.temp.name))
        self.source = LocalSource(self.home.root)
        self.since = codexsim.BASE - 1000

    def tearDown(self):
        self.temp.cleanup()

    def _set_state(self, thread_id, **columns):
        with closing_db(self.home.root / "state_5.sqlite") as db:
            for column, value in columns.items():
                db.execute("UPDATE threads SET %s=? WHERE id=?" % column, (value, thread_id))

    def test_T47_desktop_user_thread_is_detected(self):
        """The control case: the same fixture on a Desktop user thread is detected."""
        thread = codexsim.new_id()
        self.home.add_thread(thread)
        self.home.fail_usage(thread)
        transient = codexsim.new_id()
        self.home.add_thread(transient)
        self.home.fail_transient(transient)
        self.assertEqual(sorted(row["thread_id"] for row in self.source.latest_failures(self.since)),
                         sorted([thread, transient]))

    def test_T47_subagent_or_foreign_originator_never_detected(self):
        cases = {
            "subagent": dict(thread_source="subagent"),
            "codex cli": dict(originator="Codex CLI"),
            "codex exec": dict(originator="codex_exec"),
            "vscode extension": dict(originator="codex_vscode"),
            "no originator": dict(originator=None),
        }
        for name, meta in cases.items():
            for fail in ("usage", "transient"):
                with self.subTest(case=name, failure=fail):
                    thread = codexsim.new_id()
                    self.home.add_thread(thread, **meta)
                    if fail == "usage":
                        self.home.fail_usage(thread)
                    else:
                        self.home.fail_transient(thread)
                    detected = [row["thread_id"] for row in self.source.latest_failures(self.since)]
                    self.assertNotIn(thread, detected)

    def test_T47_state_row_and_rollout_must_both_say_user(self):
        """Either side saying subagent is enough to exclude the thread."""
        state_says = codexsim.new_id()
        self.home.add_thread(state_says)
        self._set_state(state_says, thread_source="subagent")
        self.home.fail_usage(state_says)
        meta_says = codexsim.new_id()
        self.home.add_thread(meta_says, thread_source="subagent")
        self._set_state(meta_says, thread_source="user")
        self.home.fail_usage(meta_says)
        self.assertEqual(self.source.latest_failures(self.since), [])


@contextmanager
def closing_db(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
