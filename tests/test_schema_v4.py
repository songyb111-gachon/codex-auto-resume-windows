"""Schema 4 (v0.6.11): what it adds, that nothing it adds is set at the defaults, and the ways in.

It adds a record's postponement (`interruptions.not_before`) and hold (`interruptions.hold`), a
conversation's tier (`threads.tier`), the observe-only switch (`settings.observe_only`) and a table
of needs-you notices. None of them is a new gate: each is a reason of the consent gate or of the
schedule gate, so A8's thirteen gates stay the thirteen they were, in their order, and each is
asked where those two are asked - by the engine, again inside the claim, again at the last look
before the send, and (the consent ones) once more under the launch guard. At the defaults nothing
is postponed, held, tiered or only observed, and the watcher does what v0.6.10 did - apart from
the one thing the owner asked to change: the marker a continuation carries is the first 16 hex
digits of its interruption id, and a record made before keeps, and is still found by, its whole
id's marker.

The needs-you notices are for a person. Nothing that decides a send may read them, which is the
structural test at the end.

The way back, to v0.6.10's schema 3, is tests/test_downgrade.py's.
"""
from __future__ import annotations

import ast
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import released  # noqa: E402
import srcscan  # noqa: E402
from codex_auto_resume import machine  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.store import SCHEMA_VERSION, Store, StoreError, UpgradePending  # noqa: E402
from test_engine import T1, EngineCase  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
KEY = "ab" * 32


def detection(key=KEY, thread=THREAD, turn="0a1b2c3d-0002-7000-8000-000000000001"):
    return {"thread_id": thread, "turn_id": turn, "completed_at": 110.0, "started_at": 105.0,
            "ordinal": 1, "interruption_id": key, "reset_at": None, "limit_type": "x",
            "uncertain": False, "category": "server_5xx"}


def write(root, statement, parameters=()):
    """A plain second connection: how a test sets what no store call sets yet."""
    with closing(sqlite3.connect(Path(root) / "state.sqlite")) as db:
        db.execute(statement, parameters)
        db.commit()


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "state"


# ------------------------------------------------------------------------ what is added
class FreshStateTests(Case):
    def test_a_fresh_state_is_schema_4_and_nothing_in_it_is_set(self):
        with Store(self.root) as store:
            self.assertEqual(store.schema_version(), SCHEMA_VERSION)
            self.assertEqual(SCHEMA_VERSION, 4)
            self.assertIs(store.settings()["observe_only"], False)
            store.register(detection(), 100.0)
            record = store.get(KEY)
            self.assertEqual((record["not_before"], record["hold"]), (None, None))
            self.assertEqual(record["marker"], ids.short_marker(KEY))
            store.set_thread_enabled(THREAD, False)
        with closing(sqlite3.connect(self.root / "state.sqlite")) as db:
            self.assertEqual(db.execute("SELECT tier FROM threads").fetchall(), [(None,)])
            self.assertEqual(db.execute("SELECT count(*) FROM notices").fetchone()[0], 0)

    def test_every_new_value_is_checked_when_the_state_is_opened(self):
        bad = {
            "a hold that is no word": ("UPDATE interruptions SET hold='maybe'", ()),
            "a postponement that is no time": ("UPDATE interruptions SET not_before='soon'", ()),
            "a tier that is no word": ("UPDATE threads SET tier='sometimes'", ()),
            "a notice with no category": ("INSERT INTO notices VALUES (?,?,?,?,?)",
                                          (KEY, THREAD, "nonsense", 120.0, None)),
            "a notice with no conversation": ("INSERT INTO notices VALUES (?,?,?,?,?)",
                                              (KEY, "not-a-uuid", "terminal_policy", 120.0, None)),
            "a notice at no time": ("INSERT INTO notices VALUES (?,?,?,?,?)",
                                    (KEY, THREAD, "terminal_policy", "later", None)),
            "a marker of neither length": ("UPDATE interruptions SET marker=?",
                                           ("[codex-auto-resume:%s]" % KEY[:20],)),
        }
        for name, (statement, parameters) in bad.items():
            with self.subTest(name):
                root = self.root.parent / re.sub(r"\W", "-", name)
                with Store(root) as store:
                    store.register(detection(), 100.0)
                    store.set_thread_enabled(THREAD, True)
                write(root, statement, parameters)
                with self.assertRaises(StoreError):
                    Store(root)

    def test_the_good_values_are_kept(self):
        with Store(self.root) as store:
            store.register(detection(), 100.0)
            store.set_thread_enabled(THREAD, True)
        for hold in sorted(machine.HOLDS):
            write(self.root, "UPDATE interruptions SET hold=?, not_before=200.5", (hold,))
            write(self.root, "UPDATE threads SET tier=?", (machine.IMPORTANCE_TIERS[-1],))
            with Store(self.root) as store:
                self.assertEqual((store.get(KEY)["hold"], store.get(KEY)["not_before"]), (hold, 200.5))


# ------------------------------------------------------------------------------ the gates
class GateTests(unittest.TestCase):
    def test_the_thirteen_gates_are_the_ones_there_were_in_their_order(self):
        self.assertEqual(machine.GATES, (
            "consent", "engine_compatible", "single_owner", "submission_safe", "identity",
            "known_failure", "schedule", "chain_budget", "attempt_budget", "no_progress_budget",
            "thread_available", "no_newer_user_work", "usage"))

    def test_consent(self):
        consent = machine.gate_consent
        self.assertEqual(consent(True, True, False), ("PASS", "ok"))
        self.assertEqual(consent(True, True, False, observe_only=False, hold=None), ("PASS", "ok"))
        self.assertEqual(consent(True, True, False, observe_only=True), ("BLOCK", "observe_only"))
        for hold in sorted(machine.HOLDS) + ["a word from a later version"]:
            self.assertEqual(consent(True, True, False, hold=hold), ("WAIT", "held"))
        # The three there always were come first, in their order.
        self.assertEqual(consent(False, False, True, observe_only=True, hold="ask"), ("BLOCK", "paused"))
        self.assertEqual(consent(True, False, True, observe_only=True, hold="ask"), ("BLOCK", "thread_disabled"))
        self.assertEqual(consent(True, True, True, observe_only=True, hold="ask"), ("BLOCK", "cancel_requested"))
        self.assertEqual(consent(True, True, False, observe_only=True, hold="ask"), ("BLOCK", "observe_only"))

    def test_schedule(self):
        schedule = machine.gate_schedule
        due = {"next_retry_at": 100.0, "reset_at": None}
        self.assertEqual(schedule(due, 150.0), ("PASS", "ok"))
        self.assertEqual(schedule(dict(due, not_before=None), 150.0, quiet_until=None), ("PASS", "ok"))
        self.assertEqual(schedule(dict(due, not_before=200.0), 150.0), ("WAIT", "postponed"))
        self.assertEqual(schedule(dict(due, not_before=120.0), 150.0), ("PASS", "ok"))
        self.assertEqual(schedule(due, 150.0, quiet_until=160.0), ("WAIT", "quiet_hours"))
        self.assertEqual(schedule(due, 150.0, quiet_until=150.0), ("PASS", "ok"))
        # Not due, and a usage reset ahead, still come first.
        self.assertEqual(schedule(dict(due, next_retry_at=300.0, not_before=400.0), 150.0), ("WAIT", "not_due"))
        self.assertEqual(schedule(dict(due, reset_at=300.0, not_before=400.0), 150.0),
                         ("WAIT", "waiting_reset"))

    def test_a_postponement_is_when_the_record_is_next_looked_at(self):
        record = {"state": "waiting_backoff", "next_retry_at": 100.0, "reset_at": None}
        self.assertEqual(machine.eligible_at(record), 100.0)
        self.assertEqual(machine.eligible_at(dict(record, not_before=None)), 100.0)
        self.assertEqual(machine.eligible_at(dict(record, not_before=500.0)), 500.0)

    def test_the_new_reasons_are_stored_as_themselves(self):
        vector = {name: ("PASS", "ok") for name in machine.GATES}
        for gate, reason in (("consent", "observe_only"), ("consent", "held"),
                             ("schedule", "postponed"), ("schedule", "quiet_hours")):
            encoded = machine.encode_gates(dict(vector, **{gate: ("WAIT", reason)}))
            self.assertEqual(machine.decode_gates(encoded)[gate], ("WAIT", reason))


# ------------------------------------------------------------------------------ the claim
class ClaimTests(Case):
    def record(self):
        store = Store(self.root)
        self.addCleanup(store.close)
        store.set_enabled(True, 100.0)
        store.register(detection(), 100.0)
        return store

    def test_at_the_defaults_a_claim_is_granted_as_before(self):
        self.assertEqual(self.record().reserve_detailed(KEY, 150.0), (True, None, None))

    def test_each_condition_refuses_the_claim_under_its_own_gate(self):
        for (statement, quiet), refusal in (
                (("UPDATE settings SET observe_only=1", None), ("consent", "observe_only")),
                (("UPDATE interruptions SET hold='account_changed'", None), ("consent", "held")),
                (("UPDATE interruptions SET not_before=200", None), ("schedule", "postponed")),
                ((None, 200.0), ("schedule", "quiet_hours"))):
            with self.subTest(refusal):
                self.root = self.root.parent / refusal[1]
                store = self.record()
                if statement:
                    write(self.root, statement)
                self.assertEqual(store.reserve_detailed(KEY, 150.0, quiet_until=quiet), (False, *refusal))
                record = store.get(KEY)
                self.assertEqual((record["state"], record["attempt_count"], record["submitted_at"]),
                                 ("waiting_reset", 0, None), "nothing was claimed")

    def test_the_launch_guard_stops_a_send_a_hold_or_observe_only_has_overtaken(self):
        for statement in ("UPDATE interruptions SET hold='ask'", "UPDATE settings SET observe_only=1"):
            with self.subTest(statement):
                self.root = self.root.parent / statement.split()[1]
                store = self.record()
                self.assertTrue(store.reserve(KEY, 150.0))
                with store.submission_guard(KEY) as permitted:
                    self.assertTrue(permitted)
                write(self.root, statement)
                with store.submission_guard(KEY) as permitted:
                    self.assertFalse(permitted)


# ------------------------------------------------------------------------------ the engine
class EngineTests(EngineCase):
    def set(self, statement, parameters=()):
        write(self.root, statement, parameters)

    def test_at_the_defaults_the_send_carries_the_short_marker_and_is_found_by_it(self):
        self.ready_after_reset()
        self.h.tick()
        record = self.h.record()
        self.assertEqual(record["marker"], ids.short_marker(record["interruption_id"]))
        self.assertTrue(self.prompt().endswith("\n\n" + ids.short_marker(record["interruption_id"])))
        self.assertEqual(self.prompt().count("[codex-auto-resume:"), 1)
        self.follow()
        self.assertIsNotNone(self.h.record()["recovery_turn_id"], "our turn is found by its marker")

    def test_a_record_made_before_keeps_its_whole_marker_and_is_found_by_it(self):
        self.h.home.fail_usage(T1)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        key = self.h.record()["interruption_id"]
        self.set("UPDATE interruptions SET marker=?", (ids.marker(key),))   # as v0.6.10 wrote it
        self.h.now = self.h.record()["reset_at"] + 61
        self.h.tick()
        self.assertTrue(self.prompt().endswith("\n\n" + ids.marker(key)))
        self.follow()
        self.assertIsNotNone(self.h.record()["recovery_turn_id"])

    def test_a_held_record_is_not_sent_says_why_and_goes_once_released(self):
        self.ready_after_reset()
        self.set("UPDATE interruptions SET hold='ask'")
        for _ in range(3):
            self.h.tick(advance=60)
        self.assert_no_send()
        self.assertEqual(machine.decode_gates(self.h.record()["gate_eval"])["consent"], ("WAIT", "held"))
        self.set("UPDATE interruptions SET hold=NULL")
        self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_observe_only_sends_nothing(self):
        self.ready_after_reset()
        self.set("UPDATE settings SET observe_only=1")
        for _ in range(3):
            self.h.tick(advance=60)
        self.assert_no_send()
        self.assertEqual(machine.decode_gates(self.h.record()["gate_eval"])["consent"],
                         ("BLOCK", "observe_only"))

    def test_a_postponed_record_waits_until_then(self):
        self.ready_after_reset()
        later = self.h.now + 3600
        self.set("UPDATE interruptions SET not_before=?", (later,))
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(machine.decode_gates(self.h.record()["gate_eval"])["schedule"], ("WAIT", "postponed"))
        self.assertEqual(machine.eligible_at(self.h.record()), later)
        self.h.now = later + 1
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_hold_that_arrives_after_the_claim_gives_the_claim_back(self):
        """The last look before the send: a hold, observe-only or a postponement written between
        the claim and the queue process gives the claim back, and nothing is sent."""
        for statement in ("UPDATE interruptions SET hold='workspace_changed'",
                          "UPDATE settings SET observe_only=1",
                          "UPDATE interruptions SET not_before=%d" % (self.h.now + 10 ** 6)):
            with self.subTest(statement):
                h = self.fresh()
                self.ready_after_reset(h)
                reserve = h.store.reserve_detailed

                def overtaken(*args, **kwargs):
                    granted = reserve(*args, **kwargs)
                    write(h.root, statement)
                    return granted
                h.store.reserve_detailed = overtaken
                h.tick()
                self.assert_no_send(h)
                # Caught at the last look itself, before the queue process was ever started -
                # not only by the launch guard behind it (ClaimTests).
                self.assertNotIn("queue_submission_started", h.codes())
                record = h.record()
                self.assertIn(record["state"], machine.WAITING)
                self.assertEqual((record["last_error"], record["attempt_count"], record["submitted_at"]),
                                 ("released_before_send", 1, None))


# ------------------------------------------------------------------------------ the notices
NOTICES = re.compile(r"\bnotices\b", re.IGNORECASE)
READS_NOTICES = re.compile(r"\b(FROM|JOIN)\s+notices\b", re.IGNORECASE)
# What decides a send: the engine's dispatch, the claim and its ledger.
DISPATCH_MODULES = ("codex_auto_resume/engine/dispatch.py", "codex_auto_resume/store/claims.py",
                    "codex_auto_resume/store/ledger.py")


def docstrings(tree):
    return {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)}


class DispatchNeverSelectsFromNoticesTests(EngineCase):
    """A needs-you notice tells a person something; it never decides whether anything is sent.
    Two proofs: the source of what decides a send names no notice and calls nothing that reads
    one, and a whole send, run against a state that holds a notice, reads no row of the table."""

    def test_nothing_that_decides_a_send_names_or_reads_the_notices(self):
        trees = {srcscan.relative(path): tree for path, tree in srcscan.package_asts().items()}
        readers = set()
        for where, tree in trees.items():
            names = srcscan.qualnames(tree)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                        isinstance(value, ast.Constant) and isinstance(value.value, str)
                        and READS_NOTICES.search(value.value) for value in ast.walk(node)):
                    readers.add(names[node].rsplit(".", 1)[-1])
        self.assertTrue(readers, "the store reads the notices somewhere - at open, if nowhere else")
        for where in DISPATCH_MODULES:
            with self.subTest(where):
                tree = trees[where]
                skip = docstrings(tree)
                named = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                         and isinstance(node.value, str) and id(node) not in skip and NOTICES.search(node.value)]
                self.assertEqual(named, [])
                called = {node.func.attr for node in ast.walk(tree)
                          if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
                self.assertEqual(sorted(called & (readers - {"__init__"})), [])

    def test_the_claims_ledger_is_refused_them_too(self):
        """The edition's plug is asked inside the claim (P11), on the claim's connection; it may
        read core's rows there, and never a notice. Its own database's tables are its own."""
        from codex_auto_resume.store.ledger import _ledger_authorizer
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute("CREATE TABLE notices (interruption_id TEXT)")
            connection.execute("CREATE TABLE interruptions (interruption_id TEXT)")
            connection.execute("ATTACH ':memory:' AS ledger")
            connection.execute("CREATE TABLE ledger.notices (interruption_id TEXT)")
            connection.set_authorizer(_ledger_authorizer([]))
            for statement in ("SELECT count(*) FROM notices", "SELECT count(*) FROM main.notices",
                              "SELECT count(*) FROM interruptions WHERE interruption_id IN "
                              "(SELECT interruption_id FROM notices)"):
                with self.subTest(statement), self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(statement)
            self.assertEqual(connection.execute("SELECT count(*) FROM interruptions").fetchone(), (0,))
            self.assertEqual(connection.execute("SELECT count(*) FROM ledger.notices").fetchone(), (0,))

    def test_a_whole_send_reads_nothing_from_the_notices(self):
        write(self.root, "INSERT INTO notices VALUES (?,?,?,?,?)",
              ("e" * 64, T1, "terminal_policy", 120.0, None))
        self.ready_after_reset()
        tables = []

        def authorize(action, first, _second, _schema, _trigger):
            if action == sqlite3.SQLITE_READ:
                tables.append(first)
            return sqlite3.SQLITE_OK
        attempt = self.h.engine.attempt

        def watched(row):
            self.h.store._connection.set_authorizer(authorize)
            try:
                return attempt(row)
            finally:
                self.h.store._connection.set_authorizer(None)
        self.h.engine.attempt = watched
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1, "the send this test watches happened")
        self.assertIn("interruptions", tables)
        self.assertNotIn("notices", tables)


# ------------------------------------------------------------------------------ the way in
class MigrationTests(Case):
    def test_a_v0_6_10_state_upgrades_with_every_row_and_nothing_set(self):
        written = released.write_v3_state(self.root)
        path = self.root / "state.sqlite"
        before = path.read_bytes()
        with self.assertRaises(UpgradePending):
            Store(self.root)
        self.assertEqual(path.read_bytes(), before, "nothing migrates without the watcher's mutex")
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            old = {row["interruption_id"]: dict(row) for row in db.execute("SELECT * FROM interruptions")}
        with Store(self.root, migrate=True) as store:
            self.assertEqual(store.migrated_from, 3)
            self.assertEqual(store.schema_version(), SCHEMA_VERSION)
            records = {row["interruption_id"]: row for row in store.all_records()}
            self.assertEqual({key: row["state"] for key, row in records.items()}, written["states"])
            self.assertIs(store.settings()["observe_only"], False)
            self.assertEqual([event["code"] for event in store.events()].count("migrated"), 1)
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            new = {row["interruption_id"]: dict(row) for row in db.execute("SELECT * FROM interruptions")}
            self.assertEqual(db.execute("SELECT count(*) FROM threads WHERE tier IS NOT NULL").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM notices").fetchone()[0], 0)
        for key, row in old.items():
            self.assertEqual({name: new[key][name] for name in row}, row, "no column of %s moved" % key)
            self.assertEqual((new[key]["not_before"], new[key]["hold"]), (None, None))
        self.assertEqual(len(list(self.root.glob("state.v3-backup-*.sqlite"))), 1, "a forensic copy first")


if __name__ == "__main__":
    unittest.main()
