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

from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
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
from codexsim import RESET, transient_error
from test_control_v3 import SRC, legacy_store_module
from test_engine import T1, TURN_A, Harness

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
                                  "unfollowed_off": 1, "observe_only_paused": False})
        self.assertTrue(list(self.state.glob("state.v4-backup-*.sqlite")), "a forensic copy was taken")
        # Every record v0.6.10 could claim if nothing stopped it: none it could send twice.
        possibly_sent = sorted(key for key, state in keys.items() if state not in machine.WAITING
                               and state != "cancelled")
        waiting = next(key for key, state in keys.items() if state in machine.WAITING)
        read = released.read_state(self.state, claims=[waiting, released.key(52)])
        # THREAD has continuations out that v0.6.10 cannot follow to their turns, so it is off: what
        # waits there waits for a person (DowngradeChainTests says why).
        self.assertEqual(read["claims"][waiting], [False, "consent", "thread_disabled"])
        # One never sent where nothing is in flight is v0.6.10's to send, with the marker it looks for.
        self.assertEqual(read["claims"][released.key(52)], [True, None, None])
        # A person switches THREAD back on in v0.6.10, and still nothing that may have gone is claimed.
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            db.execute("UPDATE threads SET enabled=1 WHERE thread_id=?", (THREAD,))
            db.commit()
        on = released.read_state(self.state, claims=possibly_sent + [waiting])
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
                self.assertEqual(on["claims"][key], [False, "submission_safe", "possibly_sent"])
        self.assertEqual(on["claims"][waiting], [True, None, None])
        # Nothing looser: the held and the tiered conversation are off, the postponement stands.
        self.assertEqual(read["disabled"], sorted({OTHER, HELD, TIERED, THREAD}))
        self.assertEqual(records[released.key(52)]["next_retry_at"], 5000)
        self.assertTrue(read["settings"]["enabled"])
        # Every column schema 4 added is gone, the guards' two with the rest, and the file is schema 3's.
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(interruptions)")}
        self.assertFalse(columns & {"not_before", "hold", "task_print", "context_tokens", "objection_at",
                                    "objection_until"})

    def test_a_withdrawal_for_observe_only_reads_as_a_pause_does_in_v0_6_10(self):
        """v0.6.11 takes a queued continuation back for Observe only under words of its own, which
        v0.6.10's store would refuse to open: they go back to the Pause's, whose promise they make."""
        keys = self.v4_state()
        withdrawn = next(key for key, state in keys.items() if state == "withdrawn_unconfirmed")
        final = next(key for key, state in keys.items() if state == "failed")
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            db.execute("UPDATE interruptions SET withdraw_reason='observe_only', last_error='observe_only', "
                       "marker=? WHERE interruption_id=?", (ids.marker(withdrawn), withdrawn))
            db.execute("UPDATE interruptions SET withdraw_reason='observe_only_unknown', "
                       "last_error='observe_only_unknown' WHERE interruption_id=?", (final,))
            db.commit()
        downgrade_to_v3(self.state)
        rows = table(self.state / "state.sqlite", "interruptions")
        self.assertEqual((rows[withdrawn]["state"], rows[withdrawn]["withdraw_reason"], rows[withdrawn]["last_error"]),
                         ("withdrawn_unconfirmed", "paused", "paused"))
        self.assertEqual((rows[final]["withdraw_reason"], rows[final]["last_error"]),
                         ("paused_unknown", "paused_unknown"))
        read = released.read_state(self.state)
        self.assertNotIn("refused", read)
        self.assertIn(withdrawn, read["records"])

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


# v0.6.10's own watcher on a state `downgrade-state --to 3` wrote, in a process of its own: its engine,
# its store and its history reader, from the tag, on the Codex home a test built with tests/codexsim.py
# (which imports nothing of the product). `ticks` passes of 10 minutes; what it sent, and every record.
_OLDER_WATCHER = r"""
import json, sys
from pathlib import Path
root, tests, now, thread, options = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]), sys.argv[4], sys.argv[5]
sys.path.append(tests)
from codexsim import CodexHome, SimBackend
from codex_auto_resume.codex import LocalSource
from codex_auto_resume.engine import Engine
from codex_auto_resume.store import Store
clock = [now]
home = CodexHome.__new__(CodexHome)              # the home the test built; nothing is created again
home.root, home._items, home.clock = root / "codex-home", 100000, lambda: clock[0]
backend = SimBackend(home)
backend.loaded_map[thread] = "loaded"
backend.after_accept = "queue"
with Store(root) as store:
    engine = Engine(store, LocalSource(home.root), backend, clock=lambda: clock[0], log=lambda *a: None,
                    options=json.loads(options), notify=lambda *a: None)
    for _ in range(12):
        clock[0] += 600
        engine.tick()
    records = [{name: row[name] for name in ("interruption_id", "state", "last_error", "parent_interruption_id",
                                             "no_progress_count", "chain_continuations", "cancel_requested")}
               for row in store.all_records()]
    print(json.dumps({"sent": len(backend.send_calls), "records": records,
                      "disabled": sorted(store.disabled_threads())}))
"""


class DowngradeChainTests(unittest.TestCase):
    """A23 across `downgrade-state --to 3`, against v0.6.10's own watcher.

    A continuation that went out with a short marker, and was not yet followed to the turn it
    started, is one v0.6.10 cannot follow: it knows a continuation's turn by the record's turn id or
    by finding its marker in it, and has neither. When Codex delivers it and that turn fails, the
    failure is a new task to v0.6.10 - a cancel made before the downgrade forgotten and a
    continuation sent, or the budgets started again and a chain that had to stop sent once more.
    v0.6.10 alone and this version alone both stop there. So the downgrade switches such a
    conversation off, and v0.6.10 detects nothing there and sends nothing until a person says so."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.h = Harness(Path(temporary.name) / "state")
        self.addCleanup(self.h.close)
        self.h.enable()
        self.h.backend.after_accept = "queue"
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.home.add_thread(T1)
        self.h.home.fail_usage(T1, TURN_A)
        self.h.tick()
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1, "a continuation waits in Codex's queue")

    def deliver_and_fail(self):
        """Codex takes the head of the queue, and the turn it starts fails with a temporary error."""
        turn = self.h.home.dispatch(T1, status="failed", progress=False)
        self.assertIsNotNone(turn)
        self.h.home.set_turn(T1, turn, error_json=transient_error())

    def older_watcher(self):
        """Downgrade, let Codex deliver what is queued and its turn fail, then run v0.6.10 over it."""
        self.h.store.close()
        report = downgrade_to_v3(self.h.root)
        self.deliver_and_fail()
        return report, released.run(released.V0610, _OLDER_WATCHER, self.h.root, Path(__file__).resolve().parent,
                                    self.h.now, T1, json.dumps(self.h.options))

    def test_a_task_cancelled_before_the_downgrade_is_not_resumed(self):
        self.h.store.cancel_interruption(self.h.record()["interruption_id"], self.h.now)
        report, older = self.older_watcher()
        self.assertEqual(report["unfollowed_off"], 1)
        self.assertEqual(older["sent"], 0, "v0.6.10 sent a continuation to a task the person cancelled")
        self.assertIn(T1, older["disabled"])

    def test_a_chain_that_has_to_stop_is_not_started_again(self):
        """At the defaults the third continuation that makes no progress is the last: the failure of
        its turn stops the task (no_progress_budget). Here that third one is still queued."""
        for _ in range(2):
            self.deliver_and_fail()
            sent = len(self.h.backend.send_calls)
            for _ in range(40):
                self.h.tick(advance=300)
                if len(self.h.backend.send_calls) > sent:
                    break
            self.assertEqual(len(self.h.backend.send_calls), sent + 1)
        self.assertEqual(self.h.records()[-1]["no_progress_count"], 2)
        report, older = self.older_watcher()
        self.assertEqual(report["unfollowed_off"], 1)
        self.assertEqual(older["sent"], 0, "v0.6.10 started the task's budgets again")
        self.assertIn(T1, older["disabled"])


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


# A watcher as far as the mutex and the stop event go: it holds the watcher's mutex and its stop event,
# says so, and - unless it is told to ignore it - lets go when it is asked to stop.
_HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from codex_auto_resume.windows import Mutex, StopEvent
state, listens = sys.argv[2], sys.argv[3] == "listens"
with StopEvent(state) as stop, Mutex(state, timeout=0):
    print("held", flush=True)
    if listens:
        stopped = stop.wait(120)
    else:
        time.sleep(120)
        stopped = False
print("stopped" if stopped else "timeout", flush=True)
"""


@unittest.skipUnless(sys.platform == "win32", "Windows named objects")
class DowngradeStopWatcherTests(unittest.TestCase):
    """downgrade-state --stop-watcher, which the bootstrap's -Pick runs before an older release is
    installed: it asks the watcher to stop, waits for it a minute at most, converts, and says what it did
    on one closed line - and a watcher that does not stop is waited for, never killed."""

    def setUp(self):
        from unittest import mock
        from codex_auto_resume import config
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "no-codex"),
                                                   "CODEX_HOME": str(self.root / "codex")})
        environment.start()
        self.addCleanup(environment.stop)
        self.paths = config.Paths(str(self.root / "home"))
        self.paths.ensure()
        self.state = self.paths.state_dir
        self.addCleanup(DowngradeCommandTests.close_log)

    def holder(self, listens: bool):
        holder = subprocess.Popen([sys.executable, "-c", _HOLDER, SRC, str(self.state),
                                   "listens" if listens else "deaf"], stdout=subprocess.PIPE, text=True,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.addCleanup(self.end, holder)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        return holder

    @staticmethod
    def end(holder):
        if holder.poll() is None:
            holder.kill()
        holder.wait(timeout=30)
        holder.stdout.close()

    def downgrade(self, *more):
        from test_cli import run_cli
        return run_cli("--home", str(self.paths.home), "--codex-home", str(self.root / "codex"), "--quiet",
                       "downgrade-state", "--to", "3", *more)

    def schema(self):
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            return db.execute("PRAGMA user_version").fetchone()[0]

    def test_a_watcher_that_stops_when_asked_is_waited_for_and_the_state_converted(self):
        keys = DowngradeToV3Tests.v4_state(self, observe_only=True)
        holder = self.holder(listens=True)
        status, out, _ = self.downgrade("--stop-watcher")
        self.assertEqual(status, 0, out)
        sent = sum(1 for state in keys.values() if state in machine.CLAIMED | machine.IN_FLIGHT | machine.OBSERVING)
        self.assertEqual(out.splitlines(), ["downgrade: converted %d %d 2 1 1" % (len(keys) + 3, sent)])
        self.assertEqual(self.schema(), 3)
        self.assertEqual(holder.stdout.readline().strip(), "stopped", "it was asked to stop, and stopped")
        self.assertEqual(holder.wait(timeout=30), 0)
        self.assertTrue(list(self.state.glob("state.v4-backup-*.sqlite")), "a forensic copy was taken")
        log = self.paths.log_file.read_text(encoding="utf-8")
        self.assertIn("downgrade-state asked the watcher to stop", log)

    def test_a_watcher_that_does_not_stop_is_waited_for_and_left_running(self):
        from codex_auto_resume.commands import install
        with Store(self.state):
            pass
        holder = self.holder(listens=False)
        from unittest import mock
        with mock.patch.object(install, "STOP_WAIT_SECONDS", 2.0):
            status, out, _ = self.downgrade("--stop-watcher")
        self.assertEqual((status, out.splitlines()), (install.EXIT_WATCHER_RUNNING, ["downgrade: watcher-running"]))
        self.assertEqual(install.EXIT_WATCHER_RUNNING, 3)
        self.assertEqual(self.schema(), SCHEMA_VERSION, "nothing was converted")
        self.assertIsNone(holder.poll(), "the watcher was killed")
        self.assertEqual(list(self.state.glob("state.v*-backup-*.sqlite")), [])

    def test_it_waits_a_minute_at_most(self):
        from codex_auto_resume.commands import install
        from codex_auto_resume.win import sync
        self.assertEqual(install.STOP_WAIT_SECONDS, 60.0)
        self.assertEqual(sync.Mutex("x", timeout=install.STOP_WAIT_SECONDS).timeout, 60.0)

    def test_a_state_already_old_enough_is_nothing_to_do(self):
        old = legacy_store_module("v0.5.7")
        with old.Store(self.state):
            pass
        status, out, _ = self.downgrade("--stop-watcher")
        self.assertEqual((status, out.splitlines()), (0, ["downgrade: nothing"]))

    def test_a_state_that_cannot_be_converted_is_said_and_left_as_it_was(self):
        with Store(self.state):
            pass
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=%d" % (SCHEMA_VERSION + 1))
            db.commit()
        status, out, _ = self.downgrade("--stop-watcher")
        self.assertEqual((status, out.splitlines()), (1, ["downgrade: failed"]))
        self.assertEqual(self.schema(), SCHEMA_VERSION + 1)

    def test_without_it_a_running_watcher_is_still_refused(self):
        with Store(self.state):
            pass
        holder = self.holder(listens=True)
        status, out, _ = self.downgrade()
        self.assertEqual(status, 1)
        self.assertIn("stop it first", out)
        self.assertIsNone(holder.poll(), "the watcher was asked to stop without --stop-watcher")
        self.assertEqual(self.schema(), SCHEMA_VERSION)

    def test_the_plugin_front_passes_it_through_for_schema_3_alone(self):
        from unittest import mock
        sys.path.insert(0, str(Path(SRC).parent / "scripts"))
        import plugin_setup
        parser = plugin_setup.build_parser()
        with mock.patch.object(plugin_setup, "_cli", return_value=0) as cli,                 mock.patch.object(plugin_setup, "runtime_home", return_value=self.paths.home):
            args = parser.parse_args(["downgrade-state", "--to", "3", "--stop-watcher"])
            self.assertEqual(plugin_setup.COMMANDS[args.command](args), 0)
            cli.assert_called_once_with(self.paths.home, ["--quiet", "downgrade-state", "--to", "3", "--stop-watcher"])
        for refused in (["downgrade-state", "--to", "2"], ["downgrade-state"]):
            with self.subTest(refused), self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                parser.parse_args(refused)


# What a tagged release's own store makes of a state: its schema, and - where it opens it - every record's
# state and the conversations switched off.
_TAGGED_STORE = r"""
import json, sys
from pathlib import Path
from codex_auto_resume import store as module
root = Path(sys.argv[1])
answer = {"schema": getattr(module, "SCHEMA_VERSION", None)}
if sys.argv[2] == "open":
    try:
        opened = module.Store(root)
    except Exception as exc:
        answer["refused"] = "%s: %s" % (type(exc).__name__, exc)
    else:
        with opened:
            answer["records"] = {row["interruption_id"]: row["state"] for row in opened.all_records()}
            answer["disabled"] = sorted(opened.disabled_threads())
print(json.dumps(answer))
"""


class PickerFloorTests(unittest.TestCase):
    """What the bootstrap's picker assumes of the published releases, from the tags themselves
    (scripts/bootstrap.ps1: $PickFloor, $EditionsSince, $StateSchemaSince). Skipped where the tags are not in
    the checkout, and a failure on CI, which fetches them (tests/released.py)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(released.ROOT / "build"))
        import legacy_bootstraps as legacy
        text = (released.ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        cls.floor = re.search(r"^\$PickFloor = '([^']+)'$", text, re.M).group(1)
        cls.editions = re.search(r"^\$EditionsSince = '([^']+)'$", text, re.M).group(1)
        rows = re.search(r"^\$StateSchemaSince = @\((.*)\)$", text, re.M).group(1)
        cls.schemas = [(version, int(schema)) for version, schema in re.findall(r"@\('([^']+)', ([0-9]+)\)", rows)]
        cls.order = staticmethod(legacy.order)
        listed = subprocess.run(["git", "-C", str(released.ROOT), "tag", "--list", "v*"], capture_output=True,
                                text=True, creationflags=released.NO_WINDOW).stdout.split()
        tags = []
        for tag in listed:
            try:
                tags.append((legacy.order(tag[1:]), tag))
            except ValueError:
                continue
        cls.tags = [tag for _, tag in sorted(tags)]

    def setUp(self):
        if "v" + self.floor not in self.tags or "v" + self.editions not in self.tags:
            if os.environ.get("CI"):
                self.fail("the tags are not in this checkout; CI must fetch them")
            self.skipTest("the tags are not in this checkout")

    def shown(self, tag, path):
        done = subprocess.run(["git", "-C", str(released.ROOT), "show", "%s:%s" % (tag, path)], capture_output=True,
                              creationflags=released.NO_WINDOW)
        return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None

    def installer(self, tag):
        for path in ("build/install/install.ps1", "install/install.ps1"):
            text = self.shown(tag, path)
            if text is not None:
                return text
        return ""

    def schema_for(self, version):
        for since, schema in self.schemas:
            if self.order(version) >= self.order(since):
                return schema
        return None

    def from_floor(self):
        return [tag for tag in self.tags if self.order(tag[1:]) >= self.order(self.floor)]

    def test_the_floor_is_the_first_release_the_dashboard_can_bring_a_person_back_from(self):
        """From v0.6.2 every bootstrap computes its digest with .NET (v0.6.0 and v0.6.1 call Get-FileHash, which
        did not resolve in the process the Dashboard starts) and every installer keeps the state on an upgrade
        (`--keep-state`; v0.5.x's has none) - and the tag below the floor lacks one of them."""
        def able(tag):
            bootstrap = self.shown(tag, "scripts/bootstrap.ps1") or ""
            return "Security.Cryptography.SHA256" in bootstrap and "--keep-state" in self.installer(tag)
        offered = self.from_floor()
        self.assertTrue(offered)
        for tag in offered:
            with self.subTest(tag):
                self.assertTrue(able(tag))
        below = [tag for tag in self.tags if self.order(tag[1:]) < self.order(self.floor)]
        self.assertTrue(below, "no tag below the floor to hold it against")
        self.assertFalse(able(below[-1]), "%s could be offered too" % below[-1])

    def test_an_edition_change_reaches_only_installers_that_know_editions(self):
        for tag in self.from_floor():
            with self.subTest(tag):
                knows = "AllowEditionChange" in self.installer(tag)
                self.assertEqual(knows, self.order(tag[1:]) >= self.order(self.editions))
        self.assertEqual(self.editions, json.loads((released.ROOT / "scripts" / "release.json").read_text(
            encoding="utf-8"))["advanced"]["since"] + "-alpha", "the advanced edition began with its first alpha")

    def test_every_offered_tags_schema_is_the_one_the_table_says(self):
        self.assertEqual(self.schemas[0][1], SCHEMA_VERSION, "the table's first row is this version's schema")
        with tempfile.TemporaryDirectory() as folder:
            for tag in self.from_floor():
                with self.subTest(tag):
                    self.assertEqual(released.run(tag, _TAGGED_STORE, folder, "schema")["schema"],
                                     self.schema_for(tag[1:]))

    def test_every_schema_3_tag_opens_what_to_3_wrote_with_every_row(self):
        """The picker converts with `--to 3` for every offered tag on schema 3, v0.6.2 to v0.6.11-alpha - so each
        of them, its own store, opens the result and reads every record as it was written."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name) / "state"
        DowngradeToV3Tests.v4_state(self)
        downgrade_to_v3(self.state)
        expected = {key: row["state"] for key, row in table(self.state / "state.sqlite", "interruptions").items()}
        switched_off = sorted(key for key, row in table(self.state / "state.sqlite", "threads").items()
                              if not row["enabled"])
        tags = [tag for tag in self.from_floor() if self.schema_for(tag[1:]) == 3]
        self.assertIn("v" + self.floor, tags)
        self.assertIn("v0.6.11-alpha", tags)
        for tag in tags:
            with self.subTest(tag):
                copy = Path(temporary.name) / tag
                shutil.copytree(self.state, copy)
                read = released.run(tag, _TAGGED_STORE, copy, "open")
                self.assertNotIn("refused", read)
                self.assertEqual(read["schema"], 3)
                self.assertEqual(read["records"], expected)
                self.assertEqual(read["disabled"], switched_off)



@unittest.skipUnless(os.name == "nt", "the install lock is a Windows named mutex")
class ConvertedStateUnderTheInstallLockTests(unittest.TestCase):
    """Between -Pick's conversion and the older version's installer, the watcher is stopped and the
    bootstrap holds the install lock. What reads the state then - through the control layer, the
    Dashboard's five-second refresh, the panel, Codex's tools, or through the command line, a
    notification's Cancel and the skill's status - reads it as it is and never upgrades it back,
    which the older watcher would refuse. The installer's own setup switches through the older store,
    and the watcher it starts upgrades. Once no installation holds the lock the current version
    upgrades - unless that version's installer has replaced the files it runs, as after a pick."""

    def setUp(self):
        from unittest import mock
        from codex_auto_resume import config, control, startup
        from test_cli import FakeWinreg, _reset_logging
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # The command line's App logs into the scratch home; its file is let go before that goes.
        self.addCleanup(_reset_logging)
        self.root = Path(temporary.name)
        guards = (mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local"),
                                               "CODEX_HOME": str(self.root / "codex")}),
                  mock.patch.object(control.Control, "watcher_running", return_value=False),
                  mock.patch.object(control.Control, "startup_enabled", return_value=False),
                  mock.patch.object(startup, "_winreg", return_value=FakeWinreg()),
                  # A name of the test's own, where install_in_progress reads it: the real
                  # installer lock is never touched.
                  mock.patch("codex_auto_resume.win.homelock.INSTALL_LOCK",
                             "Local\\CodexAutoResume.Install.test-%d" % os.getpid()))
        for guard in guards:
            guard.start()
            self.addCleanup(guard.stop)
        self.paths = config.Paths(str(self.root / "home"))
        self.paths.ensure()
        self.state = self.paths.state_dir
        self.control = control.Control(self.paths)
        DowngradeToV3Tests.v4_state(self)
        downgrade_to_v3(self.state)
        self.assertEqual(self.schema(), 3)
        self.rows = {key: row["state"] for key, row in table(self.state / "state.sqlite", "interruptions").items()}

    def schema(self):
        with closing(sqlite3.connect(self.state / "state.sqlite")) as db:
            return db.execute("PRAGMA user_version").fetchone()[0]

    def upgraded(self):
        """Whether anything upgraded the state: every upgrade leaves its own copy of the older one."""
        return [path.name for path in self.state.glob("state.v3-backup-*")]

    def install_lock(self):
        """The test's own install lock, held by a thread as an installer holds it, until the returned
        function is called."""
        import ctypes
        import threading
        from codex_auto_resume import windows
        from codex_auto_resume.win import homelock
        name, held, release = homelock.INSTALL_LOCK, threading.Event(), threading.Event()

        def hold():
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.restype = ctypes.c_void_p
            handle = kernel.CreateMutexW(None, True, name)
            held.set()
            release.wait(60)
            kernel.ReleaseMutex(ctypes.c_void_p(handle))
            kernel.CloseHandle(ctypes.c_void_p(handle))

        holder = threading.Thread(target=hold)
        holder.start()

        def let_go():
            release.set()
            holder.join(30)
        self.addCleanup(let_go)
        self.assertTrue(held.wait(30))
        self.assertIs(windows.install_in_progress(), True)
        return let_go

    def test_the_dashboards_refresh_under_the_lock_leaves_the_converted_state_as_it_is(self):
        from codex_auto_resume import control, controlcli
        let_go = self.install_lock()
        for _ in range(3):
            reply = controlcli.dispatch(self.control, "dashboard", {})
            self.assertTrue(reply.get("ok"), reply)
            self.assertTrue(reply["status"]["upgrade_pending"], "read as an older watcher's state")
        self.assertTrue(self.control.get_status()["upgrade_pending"])
        # What is not a reduction is refused, as under an older watcher, and upgrades nothing either.
        with self.assertRaises(control.ControlError) as caught:
            self.control.list_pending()
        self.assertEqual(caught.exception.code, "upgrade_pending")
        self.assertEqual((self.schema(), self.upgraded()), (3, []))
        self.assertEqual({key: row["state"] for key, row in
                          table(self.state / "state.sqlite", "interruptions").items()}, self.rows)
        # Once no installation holds it - an older installer that failed after the conversion
        # leaves this version installed - the next read is this version's, and upgrades it.
        let_go()
        reply = controlcli.dispatch(self.control, "dashboard", {})
        self.assertFalse(reply["status"]["upgrade_pending"])
        self.assertEqual(self.schema(), SCHEMA_VERSION)
        self.assertEqual(len(self.upgraded()), 1)

    def test_the_older_version_opens_what_the_held_reads_left_with_every_row(self):
        from codex_auto_resume import controlcli
        self.install_lock()
        controlcli.dispatch(self.control, "dashboard", {})
        read = released.run("v0.6.10", _TAGGED_STORE, self.state, "open")
        self.assertNotIn("refused", read)
        self.assertEqual((read["schema"], read["records"]), (3, self.rows))

    def test_no_start_of_the_watcher_meanwhile_brings_the_state_back(self):
        """Codex's start_watcher and the bridge's start-watcher, which the window's Start watcher
        sends, are refused while the lock is held (the picker's Q7): this version's watcher, started
        between the conversion and the older installer, would upgrade the converted state back."""
        from unittest import mock
        from codex_auto_resume import controlcli, mcpserver
        (self.paths.home / "watcher-launcher.py").write_text("# launcher\n", encoding="utf-8")
        self.install_lock()
        server = mcpserver.Server(self.control, io.StringIO(), io.StringIO())
        with mock.patch("subprocess.Popen", side_effect=AssertionError("a watcher was started")) as popen:
            tool = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "start_watcher", "arguments": {}}})
            bridge = controlcli.dispatch(self.control, "start-watcher", None)
        popen.assert_not_called()
        self.assertIs(tool["result"]["isError"], True)
        self.assertEqual(tool["result"]["structuredContent"], {"error_code": "start_failed"})
        self.assertEqual((bridge["ok"], bridge["error_code"]), (False, "start_failed"))
        self.assertEqual((self.schema(), self.upgraded()), (3, []))
        self.assertEqual({key: row["state"] for key, row in
                          table(self.state / "state.sqlite", "interruptions").items()}, self.rows)

    def test_a_lock_that_cannot_be_looked_at_holds_the_upgrade_too(self):
        from unittest import mock
        from codex_auto_resume import windows
        with mock.patch.object(windows, "install_in_progress", return_value=None):
            self.assertTrue(self.control.get_status()["upgrade_pending"])
        self.assertEqual((self.schema(), self.upgraded()), (3, []))

    def test_a_notifications_cancel_and_the_commands_under_the_lock_upgrade_nothing(self):
        """A notification's Cancel pressed during a pick makes Windows run the command line's
        `activate`, and the skill's command fallback and the Start Menu's run its `status`: under the
        lock they read the converted state as an older watcher's, as the control layer does. The
        cancel and a pause work through the older watcher's store; the status is refused, as it is
        under an older watcher; nothing is upgraded, and the older version opens what is left."""
        from unittest import mock
        from codex_auto_resume import cli, notify
        self.install_lock()
        home = ["--home", str(self.paths.home), "--quiet"]
        with mock.patch.object(notify, "show_content", return_value=True), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            cancelled = cli.main(home + ["activate", notify.cancel_uri(released.key(0))])
            status = cli.main(home + ["status"])
            paused = cli.main(home + ["disable"])
        self.assertEqual((cancelled, paused), (0, 0), "both work through the older watcher's store")
        self.assertNotEqual(status, 0, "a status is refused, as under an older watcher")
        self.assertEqual((self.schema(), self.upgraded()), (3, []))
        read = released.run("v0.6.10", _TAGGED_STORE, self.state, "open")
        self.assertNotIn("refused", read)
        self.assertEqual(read["schema"], 3)

    def test_the_installers_own_setup_switches_through_the_older_store_and_its_watcher_upgrades(self):
        """An installer of this version runs its setup's `install` and `enable` through the command
        line under its own lock: they read and switch through the older store and upgrade nothing,
        and the watcher setup then starts upgrades the state under its mutex, as a watcher always has.
        An opener that did not ask for the hold would upgrade under the lock - which is why every one
        in the product asks (test_every_opener_in_the_product_holds_while_installing)."""
        from codex_auto_resume import cli
        from codex_auto_resume.app import App
        from codex_auto_resume.openstate import open_state
        self.install_lock()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            enabled = cli.main(["--home", str(self.paths.home), "--quiet", "enable"])
        self.assertEqual(enabled, 0)
        self.assertEqual((self.schema(), self.upgraded()), (3, []))
        for legacy in ("always", "never"):
            with self.subTest(legacy=legacy):
                state = self.root / legacy
                shutil.copytree(self.state, state)
                with open_state(state, legacy=legacy) as store:
                    self.assertIsInstance(store, Store)
                with closing(sqlite3.connect(state / "state.sqlite")) as db:
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        with App(self.paths, console=False)._open_for_watcher(None) as store:
            self.assertIsInstance(store, Store)
            self.assertTrue(store.settings()["enabled"], "the switch made through the older store holds")
        self.assertEqual((self.schema(), len(self.upgraded())), (SCHEMA_VERSION, 1))

    def test_every_opener_in_the_product_holds_while_installing(self):
        """Every call of open_state passes hold_while_installing=True - the control layer's and the
        command line's two - so a new opener that forgot it is caught here, before it upgrades a
        converted state under the lock."""
        import ast
        callers = []
        for path in sorted((Path(SRC) / "codex_auto_resume").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "open_state":
                    held = any(keyword.arg == "hold_while_installing" and isinstance(keyword.value, ast.Constant)
                               and keyword.value.value is True for keyword in node.keywords)
                    callers.append((path.relative_to(Path(SRC)).as_posix(), held))
        self.assertEqual(sorted(callers), [("codex_auto_resume/commands/base.py", True),
                                           ("codex_auto_resume/control/state.py", True),
                                           ("codex_auto_resume/runtime/app.py", True)])

    def test_a_window_left_open_after_the_pick_never_upgrades_what_the_older_version_runs_on(self):
        """After a pick the window that made it stays open until it is closed, and Codex's MCP server
        may too: processes of this version whose files the older version's installer has replaced.
        With the lock let go and no watcher holding the state - stopped from that window, or never
        confirmed started - their reads leave the converted state as it is, which the older version
        then opens. Where this version's files are still there, as when an older installer failed,
        nothing is superseded and the next read upgrades the state, as before."""
        from unittest import mock
        from codex_auto_resume import config, controlcli, mcpserver, windows
        from codex_auto_resume.control import state as control_state
        replaced = self.root / "replaced"
        (replaced / ".codex-plugin").mkdir(parents=True)
        (replaced / ".codex-plugin" / "plugin.json").write_text(json.dumps({"version": "0.6.10"}),
                                                                 encoding="utf-8")
        self.assertIs(windows.install_in_progress(), False)
        server = mcpserver.Server(self.control, io.StringIO(), io.StringIO())
        with mock.patch.object(config, "PROJECT_ROOT", replaced):
            self.assertTrue(control_state.superseded())
            for _ in range(3):
                reply = controlcli.dispatch(self.control, "dashboard", {})
                self.assertTrue(reply.get("ok"), reply)
                self.assertTrue(reply["status"]["upgrade_pending"], "read as an older watcher's state")
            tool = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "get_status", "arguments": {}}})
            self.assertTrue(tool["result"]["structuredContent"]["upgrade_pending"])
        self.assertEqual((self.schema(), self.upgraded()), (3, []))
        self.assertEqual({key: row["state"] for key, row in
                          table(self.state / "state.sqlite", "interruptions").items()}, self.rows)
        kept = self.root / "kept"
        shutil.copytree(self.state, kept)
        self.assertFalse(control_state.superseded())
        reply = controlcli.dispatch(self.control, "dashboard", {})
        self.assertFalse(reply["status"]["upgrade_pending"])
        self.assertEqual((self.schema(), len(self.upgraded())), (SCHEMA_VERSION, 1))
        read = released.run("v0.6.10", _TAGGED_STORE, kept, "open")
        self.assertNotIn("refused", read)
        self.assertEqual((read["schema"], read["records"]), (3, self.rows))


if __name__ == "__main__":
    unittest.main()
