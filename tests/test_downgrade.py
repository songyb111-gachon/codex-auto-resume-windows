"""Going back to a v0.5 release without losing what the state protects (design T36).

The v0.5 store refuses a schema-3 file, which is correct - but the answer to that must
never be "delete the state": the rows are what stop a cancelled, exhausted or possibly
sent recovery from being detected and sent again. `downgrade-state --to 2` rewrites the
file so the tagged v0.5.7 code opens it, with every row kept.
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
from codex_auto_resume.store import Store, StoreError, downgrade_to_v2

from test_control_v3 import SRC, legacy_store_module

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER = "0a1b2c3d-0001-7000-8000-000000000002"


def turn(index: int) -> str:
    return "0a1b2c3d-0002-7000-8000-%012d" % index


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
                store.register({"thread_id": THREAD, "turn_id": turn(index), "completed_at": 110.0,
                                "started_at": 105.0, "ordinal": index, "interruption_id": key,
                                "reset_at": None, "limit_type": "x", "uncertain": False,
                                "category": "server_5xx"}, 100.0)
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
        with Store(self.state) as store:        # still a valid v3 state
            self.assertEqual(len(store.all_records()), len(machine.STATES))
        return keys

    def test_the_tagged_v0_5_7_store_opens_the_result_with_every_row(self):
        keys = self.every_state()
        result = downgrade_to_v2(self.state)
        self.assertEqual(result, {"changed": True, "rows": len(machine.STATES)})
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
                self.assertEqual(rows[key]["state"], expected, state)
            # What protects against a second send survives.
            self.assertTrue(rows["%064x" % (sorted(machine.STATES).index("cancelled") + 1)]["cancel_requested"])
            self.assertFalse(store.thread_enabled(OTHER))
        self.assertTrue(list(self.state.glob("state.v3-backup-*.sqlite")), "a forensic copy was taken")

    def test_it_is_a_no_op_on_a_schema_2_state_and_refuses_anything_else(self):
        old = legacy_store_module("v0.5.7")
        with old.Store(self.state):
            pass
        self.assertEqual(downgrade_to_v2(self.state), {"changed": False, "rows": None})
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=4")
            db.commit()
        with self.assertRaises(StoreError):
            downgrade_to_v2(self.state)

    def test_upgrading_again_restores_a_working_v3_state(self):
        self.every_state()
        downgrade_to_v2(self.state)
        with Store(self.state, migrate=True) as store:
            self.assertEqual(len(store.all_records()), len(machine.STATES))


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
            holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "held")
                status, out, _ = run_cli("--home", temporary, "--quiet", "downgrade-state", "--to", "2")
            finally:
                holder.kill()
                holder.wait(timeout=10)
                holder.stdout.close()
            self.assertEqual(status, cli.EXIT_ERROR)
            self.assertIn("stop it first", out)
            with closing(sqlite3.connect(paths.state_dir / "state.sqlite")) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            import logging
            from codex_auto_resume import logbook
            for handler in list(logging.getLogger(logbook.LOGGER_NAME).handlers):
                logging.getLogger(logbook.LOGGER_NAME).removeHandler(handler)
                handler.close()


if __name__ == "__main__":
    unittest.main()
