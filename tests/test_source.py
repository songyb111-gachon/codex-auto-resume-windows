from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_auto_resume.source import LocalSource, SourceError, detect, normalize, _choose_reset


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "usage-limit.json").read_text(encoding="utf-8"))
TID = FIXTURE["database_failure"]["thread_id"]
TURN = FIXTURE["database_failure"]["turn_id"]
SECOND = "33333333-3333-7333-8333-333333333333"
QID = "44444444-4444-7444-8444-444444444444"
MARKER = "[codex-auto-resume:" + "a" * 64 + "]"


class DetectionTests(unittest.TestCase):
    def test_real_usage_sample(self):
        found = detect(FIXTURE["database_failure"])
        self.assertEqual(found["error_info"], "usageLimitExceeded")
        self.assertEqual(found["thread_id"], TID)
        self.assertEqual(len(found["interruption_id"]), 64)
        self.assertNotIn("error_json", found)

    def test_nonusage_statuses(self):
        for status in ("completed", "interrupted", "inProgress"):
            with self.subTest(status=status):
                self.assertIsNone(detect(dict(FIXTURE["database_failure"], status=status)))

    def test_ordinary_failed(self):
        for error in ('{"codexErrorInfo":"other"}', '{"codexErrorInfo":{"httpConnectionFailed":{"status":429}}}', None):
            with self.subTest(error=error):
                self.assertIsNone(detect(dict(FIXTURE["database_failure"], error_json=error)))

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
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.source = LocalSource(self.home)
        self.rollout = self.home / "sessions" / ("rollout-" + TID + ".jsonl")
        self.rollout.parent.mkdir()
        self.write_rollout()
        with self.db("state_5.sqlite") as db:
            db.execute("CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,source TEXT,thread_source TEXT,archived INTEGER,history_mode TEXT)")
            db.execute("INSERT INTO threads VALUES(?,?,'vscode','user',0,'paginated')", (TID, str(self.rollout)))
        with self.db("thread_history_1.sqlite") as db:
            db.execute("CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,rollout_ordinal INTEGER,error_json TEXT,rollout_end_byte_offset INTEGER)")
            db.execute("CREATE TABLE thread_items(thread_id TEXT,turn_id TEXT,item_type TEXT,item_json TEXT)")
        with self.db("queue_1.sqlite") as db:
            db.execute("CREATE TABLE queued_items(id TEXT,thread_id TEXT,payload_json TEXT)")
        self.add_turn()

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

    def write_rollout(self, meta_patch=None):
        payload = {"id": TID, "originator": "Codex Desktop", "source": "vscode", "thread_source": "user"}
        payload.update(meta_patch or {})
        events = [{"type": "session_meta", "payload": payload}]
        events.extend({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": limit}}
                      for limit in FIXTURE["rate_limits"])
        events.append(FIXTURE["rollout_failure"])
        self.rollout.write_bytes(b"".join(json.dumps(e).encode() + b"\n" for e in events))

    def add_turn(self, **changes):
        row = dict(FIXTURE["database_failure"], **changes)
        with self.db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_turns VALUES(?,?,?,?,?,?,?,?)",
                       tuple(row[k] for k in ("thread_id", "turn_id", "status", "started_at", "completed_at", "rollout_ordinal", "error_json"))
                       + (self.rollout.stat().st_size,))

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

    def test_delivery_requires_exact_thread_user_message(self):
        payload = json.dumps({"type": "userMessage", "content": [{"type": "text", "text": "harmless " + MARKER}]})
        with self.db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_items VALUES(?,?,?,?)", (SECOND, TURN, "userMessage", payload))
            db.execute("INSERT INTO thread_items VALUES(?,?,?,?)", (TID, TURN, "agentMessage", payload))
        self.assertFalse(self.source.delivery(TID, MARKER)["delivered"])
        with self.db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_items VALUES(?,?,?,?)", (TID, TURN, "userMessage", payload))
        self.assertTrue(self.source.delivery(TID, MARKER)["delivered"])

    def test_queue_reconciliation_pinned_serde(self):
        payload = json.dumps({"UserInput": {"content": [{"type": "text", "text": MARKER}], "client_id": None}})
        with self.db("queue_1.sqlite") as db:
            db.execute("INSERT INTO queued_items VALUES(?,?,?)", (QID, TID, payload))
            db.execute("INSERT INTO queued_items VALUES(?,?,?)", (SECOND, SECOND, payload))
        state = self.source.delivery(TID, MARKER)
        self.assertFalse(state["delivered"])
        self.assertEqual(state["queued_ids"], [QID])

    def test_marker_in_metadata_not_delivery(self):
        payload = json.dumps({"type": "userMessage", "id": MARKER, "content": []})
        with self.db("thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_items VALUES(?,?,?,?)", (TID, TURN, "userMessage", payload))
        self.assertFalse(self.source.delivery(TID, MARKER)["delivered"])

    def test_corrupt_database_safe_error(self):
        (self.home / "thread_history_1.sqlite").write_bytes(b"not sqlite sensitive-data")
        with self.assertRaisesRegex(SourceError, "unavailable or unsupported"):
            self.source.latest_failures(1788620000)

    def test_missing_schema_safe_error(self):
        with self.db("thread_history_1.sqlite") as db:
            db.execute("DROP TABLE thread_turns")
        with self.assertRaises(SourceError):
            self.source.latest(TID)

    def test_read_only_connection(self):
        with self.source._db("state_5.sqlite") as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM threads")

    def test_invalid_identity_and_timestamp(self):
        self.assertIsNone(self.source.latest("--last"))
        with self.assertRaises(SourceError):
            self.source.delivery(TID, "anything")
        with self.assertRaises(SourceError):
            self.source.latest_failures(float("nan"))


if __name__ == "__main__":
    unittest.main()
