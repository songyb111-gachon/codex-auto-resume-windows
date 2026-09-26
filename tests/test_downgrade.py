"""Going back to an older release without losing what the state protects (design T36).

An older store refuses a newer schema, which is correct - but the answer to that must never be
"delete the state": the rows are what stop a cancelled, exhausted or possibly sent recovery from
being detected and sent again. `downgrade-state --to 2` rewrites the file so the tagged v0.5.7
code opens it, and from v0.6.11 `--to 3` so the tagged v0.6.10 code does, with every row kept.

Schema 4 holds what v0.6.10 cannot keep. The v0.6.11 marker is 16 hex digits, and v0.6.10's
store refuses to open a state with one and its history reader never looks for one - so every
marker is written back as the whole id, and a continuation that may already have gone out with a
short one is made final, which v0.6.10 never sends again. And nothing is left looser than it was:
observe-only becomes a Pause, a hold or a tier switches its conversation off, a postponement
becomes the schedule.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from codex_auto_resume import machine
from codex_auto_resume.domain import ids
from codex_auto_resume.store import (SCHEMA_VERSION, Store, StoreError, downgrade_to_v2,
                                     downgrade_to_v3)

import released
import schemagolden
from test_control_v3 import SRC, legacy_store_module

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER = "0a1b2c3d-0001-7000-8000-000000000002"
HELD = "0a1b2c3d-0001-7000-8000-000000000003"
TIERED = "0a1b2c3d-0001-7000-8000-000000000004"
LATER = "0a1b2c3d-0001-7000-8000-000000000005"


def turn(index: int) -> str:
    return "0a1b2c3d-0002-7000-8000-%012d" % index


def detection(key, thread, index):
    return {"thread_id": thread, "turn_id": turn(index), "completed_at": 110.0, "started_at": 105.0,
            "ordinal": index, "interruption_id": key, "reset_at": None, "limit_type": "x",
            "uncertain": False, "category": "server_5xx"}


def table(path, name) -> dict:
    """Every row of one table, by its first column, exactly as stored."""
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        return {row[0]: dict(row) for row in db.execute("SELECT * FROM %s" % name)}


class DowngradeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / "state"

    def every_state(self):
        """One record in each of the 27 stored states, a hidden one and a disabled thread."""
        keys = {}
        with Store(self.state) as store:
            for index, state in enumerate(sorted(machine.STATES)):
                key = "%064x" % (index + 1)
                store.register(detection(key, THREAD, index), 100.0)
                keys[key] = state
            store.set_thread_enabled(OTHER, False)
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            for index, (key, state) in enumerate(sorted(keys.items())):
                db.execute(
                    "UPDATE interruptions SET state=?, submitted_at=?, recovery_turn_id=?, "
                    "withdraw_reason=?, withdrawn_at=?, cancel_requested=?, history_hidden_at=? "
                    "WHERE interruption_id=?",
                    (state, None if state in machine.WAITING else 101.0,
                     turn(100 + index), "cancel" if state == "withdrawn_unconfirmed" else None,
                     101.0 if state == "withdrawn_unconfirmed" else None,
                     1 if state in ("cancelled", "submitting") else 0,
                     150.0 if state == "cancelled" else None, key))
            db.commit()
        with Store(self.state) as store:        # still a valid state
            self.assertEqual(len(store.all_records()), len(machine.STATES))
        return keys

    def test_the_tagged_v0_5_7_store_opens_the_result_with_every_row(self):
        keys = self.every_state()
        result = downgrade_to_v2(self.state)
        self.assertEqual((result["changed"], result["rows"]), (True, len(machine.STATES)))
        old = legacy_store_module("v0.5.7")
        with old.Store(self.state) as store:
            rows = {row["interruption_id"]: row for row in store.all_records()}
            self.assertEqual(set(rows), set(keys))
            for key, state in keys.items():
                expected = {"turn_started": "resumed", "turn_completed": "resumed",
                            "recovered": "resumed", "completed_no_progress": "resumed",
                            "recovery_turn_failed": "resumed", "stopped_by_user": "resumed",
                            "outcome_unverified": "resumed", "handed_over": "superseded_by_user",
                            "withdrawn_unconfirmed": "submission_unknown"}.get(state, state)
                # A short marker's record that may have been sent is final on the way through v3.
                if rows[key]["state"] != expected:
                    self.assertEqual((state, rows[key]["state"]), (state, "submission_unknown"))
                    self.assertIn(state, machine.CLAIMED | machine.IN_FLIGHT)
            # What protects against a second send survives.
            self.assertTrue(rows["%064x" % (sorted(machine.STATES).index("cancelled") + 1)]["cancel_requested"])
            self.assertFalse(store.thread_enabled(OTHER))
        self.assertTrue(list(self.state.glob("state.v%d-backup-*.sqlite" % SCHEMA_VERSION)),
                        "a forensic copy was taken")

    def test_it_is_a_no_op_on_a_schema_2_state_and_refuses_anything_else(self):
        old = legacy_store_module("v0.5.7")
        with old.Store(self.state):
            pass
        self.assertEqual(downgrade_to_v2(self.state), {"changed": False, "rows": None})
        self.assertEqual(downgrade_to_v3(self.state), {"changed": False, "rows": None})
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=%d" % (SCHEMA_VERSION + 1))
            db.commit()
        for downgrade in (downgrade_to_v2, downgrade_to_v3):
            with self.subTest(downgrade.__name__), self.assertRaises(StoreError):
                downgrade(self.state)

    def test_upgrading_again_restores_a_working_state(self):
        self.every_state()
        downgrade_to_v2(self.state)
        with Store(self.state, migrate=True) as store:
            self.assertEqual(store.schema_version(), SCHEMA_VERSION)
            self.assertEqual(len(store.all_records()), len(machine.STATES))


class DowngradeToV3Tests(unittest.TestCase):
    """`downgrade-state --to 3`, proved against the tagged v0.6.10 store itself."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / "state"

    def v4_state(self, *, observe_only=False):
        """A schema-4 state this version wrote: one record in each stored state on THREAD, each
        with its own short marker; a waiting record held for a person on HELD; a conversation
        whose tier asks first, with a record waiting, on TIERED; a waiting record postponed to
        5000 on LATER; OTHER switched off; one needs-you notice; observe-only as asked."""
        keys = {}
        with Store(self.state) as store:
            store.set_enabled(True, 100.0)
            for index, state in enumerate(sorted(machine.STATES)):
                key = released.key(index)
                store.register(detection(key, THREAD, index), 100.0)
                keys[key] = state
            for index, thread in enumerate((HELD, TIERED, LATER), start=50):
                store.register(detection(released.key(index), thread, index), 100.0)
            store.set_thread_enabled(OTHER, False)
            store.set_thread_enabled(TIERED, True)
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            for index, (key, state) in enumerate(sorted(keys.items())):
                db.execute(
                    "UPDATE interruptions SET state=?, submitted_at=?, recovery_turn_id=?, "
                    "withdraw_reason=?, withdrawn_at=?, cancel_requested=?, queue_id=? "
                    "WHERE interruption_id=?",
                    (state, None if state in machine.WAITING else 101.0,
                     None if state in machine.WAITING else turn(100 + index),
                     "cancel" if state == "withdrawn_unconfirmed" else None,
                     101.0 if state == "withdrawn_unconfirmed" else None,
                     1 if state == "cancelled" else 0,
                     turn(200 + index) if state in ("queued", "submission_unknown") else None, key))
            db.execute("UPDATE interruptions SET hold='ask' WHERE interruption_id=?", (released.key(50),))
            # What the two guards keep of a record (v0.6.11, step D): a digest and a token count.
            db.execute("UPDATE interruptions SET task_print=?, context_tokens=? WHERE interruption_id=?",
                       ("c" * 64, 123456, released.key(51)))
            db.execute("UPDATE threads SET tier='ask_first' WHERE thread_id=?", (TIERED,))
            db.execute("UPDATE interruptions SET not_before=5000 WHERE interruption_id=?", (released.key(52),))
            db.execute("INSERT INTO notices VALUES (?,?,?,?,?)",
                       ("f" * 64, THREAD, "terminal_policy", 120.0, None))
            db.execute("UPDATE settings SET observe_only=?", (int(observe_only),))
            db.commit()
        with Store(self.state) as store:        # a state the validator accepts
            self.assertEqual(len(store.all_records()), len(machine.STATES) + 3)
            self.assertTrue(all(row["marker"] == ids.short_marker(row["interruption_id"])
                                for row in store.all_records()))
        return keys

    def test_the_tagged_v0_6_10_store_opens_the_result_and_never_sends_what_may_have_gone(self):
        keys = self.v4_state()
        result = downgrade_to_v3(self.state)
        sent = {key for key, state in keys.items() if state in machine.CLAIMED | machine.IN_FLIGHT
                | machine.OBSERVING}
        self.assertEqual(result, {"changed": True, "rows": len(keys) + 3, "short_markers": len(keys) + 3,
                                  "made_final": len(sent), "postponed": 1, "conversations_off": 2,
                                  "observe_only_paused": False})
        self.assertTrue(list(self.state.glob("state.v4-backup-*.sqlite")), "a forensic copy was taken")
        # Every record v0.6.10 could claim if nothing stopped it: none it could send twice.
        possibly_sent = sorted(key for key, state in keys.items() if state not in machine.WAITING
                               and state != "cancelled")
        waiting = next(key for key, state in keys.items() if state in machine.WAITING)
        read = released.read_state(self.state, claims=possibly_sent + [waiting])
        self.assertEqual(read["version"], 3)
        records = read["records"]
        self.assertEqual(set(records), set(keys) | {released.key(index) for index in (50, 51, 52)})
        for key, record in records.items():
            with self.subTest(key=key, state=keys.get(key)):
                self.assertEqual(record["marker"], ids.marker(key), "v0.6.10 reads the whole id's marker")
                if key in sent:
                    self.assertEqual(record["state"], "outcome_unverified" if keys[key] in machine.OBSERVING
                                     else "submission_unknown")
                    self.assertIsNone(record["queue_id"])
                elif key in keys:
                    self.assertEqual(record["state"], keys[key])
        for key in possibly_sent:
            with self.subTest(claim=key, state=keys[key]):
                self.assertEqual(read["claims"][key], [False, "submission_safe", "possibly_sent"])
        # A continuation never sent is v0.6.10's to send, now with the marker it looks for.
        self.assertEqual(read["claims"][waiting], [True, None, None])
        # Nothing looser: the held and the tiered conversation are off, the postponement stands.
        self.assertEqual(read["disabled"], sorted({OTHER, HELD, TIERED}))
        self.assertEqual(records[released.key(52)]["next_retry_at"], 5000)
        self.assertTrue(read["settings"]["enabled"])
        # Every column schema 4 added is gone, the guards' two with the rest, and the file is schema 3's.
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(interruptions)")}
        self.assertFalse(columns & {"not_before", "hold", "task_print", "context_tokens", "objection_at"})

    def test_observe_only_becomes_a_pause(self):
        self.v4_state(observe_only=True)
        self.assertTrue(downgrade_to_v3(self.state)["observe_only_paused"])
        read = released.read_state(self.state, claims=[released.key(52)])
        self.assertFalse(read["settings"]["enabled"])
        self.assertEqual(read["claims"][released.key(52)], [False, "consent", "paused"])

    def test_a_short_marker_is_what_v0_6_10_would_refuse(self):
        """Why every marker is written back: one short marker, and v0.6.10 opens nothing."""
        self.v4_state()
        downgrade_to_v3(self.state)
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            db.execute("UPDATE interruptions SET marker=? WHERE interruption_id=?",
                       (ids.short_marker(released.key(0)), released.key(0)))
            db.commit()
        self.assertEqual(released.read_state(self.state), {"refused": "StoreError"})

    def test_a_v0_6_10_state_goes_up_and_comes_back_as_it_was(self):
        """v3 -> v4 -> v3: the state v0.6.10 wrote, row for row and column for column."""
        written = released.write_v3_state(self.state)
        path = self.state / "state.sqlite"
        before = {name: table(path, name) for name in ("interruptions", "threads", "settings")}
        shape = schemagolden.shape(path)
        with Store(self.state, migrate=True) as store:
            self.assertEqual(store.schema_version(), SCHEMA_VERSION)
            upgraded = {row["interruption_id"]: row for row in store.all_records()}
            self.assertEqual({key: row["state"] for key, row in upgraded.items()}, written["states"])
            self.assertTrue(all(row["not_before"] is None and row["hold"] is None
                                for row in upgraded.values()))
            self.assertFalse(store.settings()["observe_only"])
        result = downgrade_to_v3(self.state)
        self.assertEqual((result["short_markers"], result["made_final"], result["conversations_off"]),
                         (0, 0, 0))
        self.assertEqual({name: table(path, name) for name in ("interruptions", "threads", "settings")},
                         before)
        self.assertEqual(schemagolden.shape(path), shape)
        read = released.read_state(self.state)
        self.assertEqual({key: row["state"] for key, row in read["records"].items()}, written["states"])


@unittest.skipUnless(sys.platform == "win32", "Windows named objects")
class DowngradeCommandTests(unittest.TestCase):
    def test_it_refuses_while_the_watcher_runs(self):
        from codex_auto_resume import cli, config
        from test_cli import run_cli
        with tempfile.TemporaryDirectory() as temporary:
            paths = config.Paths(temporary)
            paths.ensure()
            with Store(paths.state_dir):
                pass
            code = ("import sys, time\nsys.path.insert(0, %r)\n"
                    "from codex_auto_resume.windows import Mutex\n"
                    "with Mutex(%r, timeout=0):\n    print('held', flush=True)\n    time.sleep(60)\n"
                    % (SRC, str(paths.state_dir)))
            holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                self.assertEqual(holder.stdout.readline().strip(), "held")
                status, out, _ = run_cli("--home", temporary, "--quiet", "downgrade-state", "--to", "3")
            finally:
                holder.kill()
                holder.wait(timeout=10)
                holder.stdout.close()
            self.assertEqual(status, cli.EXIT_ERROR)
            self.assertIn("stop it first", out)
            with closing(sqlite3.connect(paths.state_dir / "state.sqlite")) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.close_log()

    def test_to_3_writes_what_v0_6_10_reads(self):
        from codex_auto_resume import cli, config
        from test_cli import run_cli
        with tempfile.TemporaryDirectory() as temporary:
            paths = config.Paths(temporary)
            paths.ensure()
            with Store(paths.state_dir):
                pass
            status, out, _ = run_cli("--home", temporary, "downgrade-state", "--to", "3")
            self.assertEqual(status, cli.EXIT_OK, out)
            self.assertIn("state rewritten as schema 3", out)
            with closing(sqlite3.connect(paths.state_dir / "state.sqlite")) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            status, out, _ = run_cli("--home", temporary, "downgrade-state", "--to", "3")
            self.assertEqual(status, cli.EXIT_OK, out)
            self.assertIn("already schema 3", out)
            self.close_log()

    @staticmethod
    def close_log():
        import logging
        from codex_auto_resume import logbook
        for handler in list(logging.getLogger(logbook.LOGGER_NAME).handlers):
            logging.getLogger(logbook.LOGGER_NAME).removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    unittest.main()
