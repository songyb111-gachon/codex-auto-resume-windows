"""Stage 4's advanced state version 7 (v0.6.16-beta.4, schema.STAGE4_VERSION): a turn run here and the Dashboard's
chat - two tables added to version 6 (the usage additions', test_advanced_state_v6) and none remade, every row of an
older file kept.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from test_advanced_state import StateCase  # noqa: E402
from codex_auto_resume_advanced.state import AdvancedState, StateError, session  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ChatReason, ChatState, RunEnd  # noqa: E402

KEY = "%064x" % 77
RECORD = "%064x" % 78


class UpgradeTests(StateCase):
    def version_before(self):
        """A file of the version before stage 4's (6), with a row in a table of it and a wording of version 6's own."""
        self.paths.advanced_dir.mkdir(parents=True)
        (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        path = self.paths.advanced_dir / schema_module.FILE_NAME
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for statement in schema_module.STATEMENTS_BEFORE_STAGE4:
                connection.execute(statement)
            connection.execute("INSERT INTO spend (at, capability, thread_id) VALUES (?, 'test_wake', ?)",
                               (self.now, ac.THREAD))
            connection.execute("INSERT INTO keep_going VALUES (?, 2, 0, ?, 'on', NULL, NULL)", (ac.THREAD, self.now))
            connection.execute("INSERT INTO wordings VALUES ('usage_wrap_up', 'wrap_custom_weekly', 'Stop soon.', ?)",
                               (self.now,))
            connection.commit()
        return path

    def test_the_file_before_is_brought_to_stage_4s_version_and_keeps_every_row(self):
        """Fails with the step reverted: the file would be refused, every capability off."""
        path = self.version_before()
        opened = self.state()
        opened.arming()
        self.assertEqual(opened.runs(live=False), [])
        opened.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            # And on to the version after stage 4's (v0.6.19's 8, test_advanced_schema_v8), in the same opening.
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], schema_module.SCHEMA_VERSION)
            self.assertEqual((schema_module.STAGE4_VERSION, schema_module.SCHEMA_VERSION), (7, 9))
            self.assertEqual(connection.execute("SELECT count(*) FROM spend").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM wordings").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM keep_going").fetchone()[0], 1)
            for name in schema_module.STAGE4_TABLES:
                self.assertEqual(connection.execute("SELECT count(*) FROM %s" % name).fetchone()[0], 0)

    def test_the_step_adds_and_remakes_nothing(self):
        self.assertTrue(all(statement.startswith(("CREATE TABLE", "CREATE INDEX", "PRAGMA"))
                            for statement in (s.strip() for s in schema_module.UPGRADE_TO_STAGE4)))
        self.assertEqual(set(schema_module.TABLES_V7) - set(schema_module.TABLES_BEFORE_STAGE4),
                         set(schema_module.STAGE4_TABLES))

    def test_a_newer_version_is_refused(self):
        made = self.state()
        made.run_started(KEY, "headless_run", ac.THREAD, started_at=self.now, ends_by=self.now)
        made.close()
        with contextlib.closing(sqlite3.connect(made.path)) as connection:
            # A newer version with no readable-from mark (v0.6.17): readable from itself alone.
            connection.execute("PRAGMA application_id=0")
            connection.execute("PRAGMA user_version=%d" % (schema_module.SCHEMA_VERSION + 1))
            connection.commit()
        with self.assertRaises(StateError):
            self.state().arming()

    def test_a_build_of_version_6_refuses_this_file_and_writes_nothing(self):
        """The usage additions alone (version 6) read a version-7 file as newer: every capability off, nothing
        written to it."""
        made = self.state()
        made.run_started(KEY, "headless_run", ac.THREAD, started_at=self.now, ends_by=self.now)
        made.close()
        before = made.path.read_bytes()
        with patch.object(session, "SCHEMA_VERSION", schema_module.STAGE4_VERSION - 1):
            older = AdvancedState(self.paths, registry=ac.Registry((ac.definition(),)), clock=lambda: self.now)
            self.addCleanup(older.close)
            with self.assertRaises(StateError):
                older.arming()
        self.assertEqual(made.path.read_bytes(), before)


class RunTests(StateCase):
    def test_a_run_is_written_stopped_and_ended(self):
        state = self.state()
        state.run_started(KEY, "headless_run", ac.THREAD, started_at=self.now, ends_by=self.now + 3600)
        self.assertEqual([row["interruption_id"] for row in state.runs()], [KEY])
        self.assertTrue(state.run_stop(KEY))
        self.assertIsNotNone(state.runs()[0]["stop_requested_at"])
        self.assertTrue(state.run_ended(KEY, RunEnd.INTERRUPTED))
        self.assertEqual(state.runs(), [])
        self.assertFalse(state.run_stop(KEY), "nothing to stop once it ended")

    def test_only_its_capabilities_and_ends_are_held(self):
        state = self.state()
        with self.assertRaises(StateError):
            state.run_started(KEY, "goal_continuation", ac.THREAD, started_at=self.now, ends_by=self.now)
        state.run_started(KEY, "headless_run", ac.THREAD, started_at=self.now, ends_by=self.now)
        with self.assertRaises(StateError):
            state.run_ended(KEY, "exploded")


    def test_only_ended_runs_older_than_asked_of_the_capability_asked_are_pruned(self):
        state = self.state()
        other = "%064x" % 79
        state.run_started(KEY, "headless_run", ac.THREAD, started_at=self.now, ends_by=self.now + 1)
        state.run_started(other, "model_fallback", ac.THREAD, started_at=self.now, ends_by=self.now + 1)
        state.run_ended(KEY, RunEnd.COMPLETED, at=self.now)
        state.run_ended(other, RunEnd.COMPLETED, at=self.now)
        state.run_started(RECORD, "headless_run", ac.THREAD, started_at=self.now, ends_by=self.now + 1)
        self.assertEqual(state.prune_runs(self.now + 1, capability="headless_run"), 1)
        self.assertEqual(sorted(row["interruption_id"] for row in state.runs(live=False)), sorted([other, RECORD]))
        self.assertEqual(state.prune_runs(self.now, capability="model_fallback"), 0, "not older than asked")


    def test_a_fallback_turns_model_is_kept_owed_until_put_back(self):
        state = self.state()
        state.run_owed(KEY, "model_fallback", ac.THREAD, "its-own-model", started_at=self.now, ends_by=self.now + 1)
        state.run_started(KEY, "model_fallback", ac.THREAD, started_at=self.now, ends_by=self.now + 1)
        state.run_ended(KEY, RunEnd.LOST, at=self.now)
        self.assertEqual([row["restore_model"] for row in state.runs_owed("model_fallback")], ["its-own-model"])
        self.assertEqual(state.prune_runs(self.now + 1), 0, "never pruned while owed")
        self.assertTrue(state.run_restored(KEY))
        self.assertEqual(state.runs_owed("model_fallback"), [])
        self.assertEqual(state.prune_runs(self.now + 1), 1)

    def test_only_a_fallback_turn_owes_a_model(self):
        state = self.state()
        for capability, model in (("headless_run", "m"), ("model_fallback", ""), ("model_fallback", "m" * 129)):
            with self.assertRaises((StateError, sqlite3.IntegrityError)):
                state.run_owed(KEY, capability, ac.THREAD, model, started_at=self.now, ends_by=self.now)


class ChatTests(StateCase):
    def test_words_are_kept_only_while_a_message_waits(self):
        state = self.state()
        state.add_chat(ac.THREAD, "my own words", RECORD)
        self.assertEqual(state.chats()[0]["words"], "my own words")
        self.assertTrue(state.chat_sent(RECORD))
        found = state.chats()[0]
        self.assertEqual((found["state"], found["words"]), (ChatState.IN_FLIGHT, None))
        self.assertTrue(state.chat_ended(RECORD, "delivered"))
        self.assertEqual(state.chats()[0]["reason"], ChatReason.DELIVERED)

    def test_the_file_refuses_words_on_a_message_not_waiting(self):
        state = self.state()
        state.add_chat(ac.THREAD, "mine", RECORD)
        state.chat_sent(RECORD)
        connection = sqlite3.connect(state.path)
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE chat_messages SET words='back again'")

    def test_a_cancel_takes_the_words_with_it(self):
        state = self.state()
        state.add_chat(ac.THREAD, "mine", RECORD)
        self.assertEqual(state.cancel_chat(ChatReason.CANCELLED, record_id=RECORD), 1)
        found = state.chats()[0]
        self.assertEqual((found["state"], found["words"]), (ChatState.CANCELLED, None))

    def test_over_two_thousand_characters_is_refused(self):
        with self.assertRaises(StateError):
            self.state().add_chat(ac.THREAD, "x" * 2001, RECORD)


if __name__ == "__main__":
    unittest.main()
