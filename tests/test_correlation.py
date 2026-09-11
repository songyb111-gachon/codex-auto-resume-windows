"""Correlation and the queue-row watch, end to end (engine design v2, section 10.1, T01-T10).

Every test drives the real Engine, the real Store and the real LocalSource over a real
Codex home (tests/codexsim.py): the three SQLite databases with the columns Codex
0.153.4 has, and the rollout files. Only the Codex *processes* are simulated. Nothing
here mocks the query layer, so a query that is wrong against the real schema fails
here too.

The expectations are the design's (sections 4.1, 5.2-5.5), not whatever the code
happens to do. After a send, the tests call `engine.watch()` directly: that is the
one-second loop section 5.1 describes, and it keeps outcome observation from moving a
record on before the test has looked at it.

Content-free: the only prompt text these tests touch is the text our own continuation
carried, and nothing asserts on it beyond the marker.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_auto_resume import machine
from codex_auto_resume.engine import Engine
from codex_auto_resume.source import LocalSource
from codex_auto_resume.store import Store

try:
    from tests.codexsim import BASE, CodexHome, SimBackend, new_id, transient_error
except ImportError:                                  # run from inside tests/
    from codexsim import BASE, CodexHome, SimBackend, new_id, transient_error

SRC = Path(__file__).resolve().parents[1] / "src"
DELIVERY_TIMEOUT = 180                               # delivery_timeout_seconds (policy default)
SUPERSEDE_REASONS = {"superseded", "superseded_by_user", "user_queued_input"}
# Any of these after a delete that Codex overtook would be a lie about what happened.
WRONG_ENDINGS = {"superseded_by_user", "superseded", "cancelled", "failed"}


class Scenario:
    """One Codex home, one state directory, one watcher, one failed turn on one thread.

    The failed turn is a transient 5xx, so the first attempt is due five seconds after
    detection. `home.clock` follows the test clock, so a turn Codex starts gets a
    realistic completion time.
    """

    def __init__(self, test, *, after_accept="dispatch", turn_status="completed"):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.test = test
        self.now = BASE + 10.0
        self.home = CodexHome(root / "codex")
        self.home.clock = lambda: self.now
        self.state_dir = root / "state"
        self.backend = SimBackend(self.home)
        self.backend.after_accept = after_accept
        self.backend.turn_status = turn_status
        self.thread = new_id()
        self.backend.loaded_map[self.thread] = "loaded"
        self.failed_turn = self.home.fail_transient(self.thread)
        self.failed_ordinal = self.home.turns(self.thread)[-1]["rollout_ordinal"]
        self.logs, self.notes = [], []
        self.store = None
        self.key = None
        self.open()
        self.store.set_enabled(True, BASE)

    # ------------------------------------------------------------ the watcher
    def open(self):
        """Start the watcher, or restart it: a new Store and Engine on the same dirs."""
        if self.store is not None:
            self.store.close()
        self.store = Store(self.state_dir)
        self.test.addCleanup(self.store.close)
        self.engine = Engine(self.store, LocalSource(self.home.root), self.backend,
                             clock=lambda: self.now,
                             log=lambda *entry: self.logs.append(entry),
                             notify=lambda event, detail: self.notes.append((event, detail)))

    def advance(self, seconds):
        self.now += seconds

    def watch(self, *, step=1):
        """One iteration of the section 5.1 watch loop, `step` seconds after the last."""
        self.advance(step)
        self.engine.watch()

    def register(self):
        self.engine.tick()
        rows = self.store.all_records()
        self.test.assertEqual(len(rows), 1, self.logs)
        self.key = rows[0]["interruption_id"]
        return rows[0]

    def make_due(self):
        self.now = max(self.now, self.record()["next_retry_at"]) + 1

    def send(self):
        """Detect the failure, then tick once it is due: the continuation is sent."""
        self.register()
        self.make_due()
        self.engine.tick()
        self.test.assertEqual(len(self.backend.send_calls), 1, self.logs)
        return self.record()

    def through_window(self):
        """Watch until the settle window after the withdrawal has fully elapsed."""
        start = self.record()["withdrawn_at"]
        self.test.assertIsNotNone(start)
        while self.now <= start + DELIVERY_TIMEOUT + 1:
            self.watch(step=10)
        self.watch()
        return self.record()

    # ------------------------------------------------------------ inspection
    def record(self):
        return self.store.get(self.key)

    @property
    def prompt(self):
        return self.backend.send_calls[0][1]

    @property
    def marker(self):
        return self.record()["marker"]

    def events(self):
        return self.store.events(self.key)

    def codes(self):
        return [event["code"] for event in self.events()]

    def states_entered(self):
        return {event["to_state"] for event in self.events() if event["to_state"]}

    # -------------------------------------------------------- Codex behaviour
    def dispatch_inside_delete(self):
        """Codex takes our item and starts its turn, and only then answers our delete
        with `deleted:true` (U2). Returns the list the started turn ids go into."""
        started = []

        def delete(thread_id, queue_id):
            self.backend.deleted.append((thread_id, queue_id))
            turn = self.home.dispatch(thread_id, status="inProgress")
            if turn:
                started.append(turn)
            return True
        self.backend.delete_queue = delete
        return started

    def set_queued_client(self, queue_id, client_id):
        """Rewrite only the `client_id` of a queued payload (the text is untouched)."""
        with closing(sqlite3.connect(self.home.root / "queue_1.sqlite")) as db:
            payload = json.loads(db.execute("SELECT payload_json FROM queued_items WHERE id=?",
                                            (queue_id,)).fetchone()[0])
            payload["UserInput"]["client_id"] = client_id
            db.execute("UPDATE queued_items SET payload_json=? WHERE id=?", (json.dumps(payload), queue_id))
            db.commit()

    def rewrite_failed_turn(self):
        """The failed turn's row changes identity, so it is no longer the failure we
        recorded - with no later turn on the thread."""
        self.home.set_turn(self.thread, self.failed_turn, completed_at=int(BASE) + 1)


def _foreign_turn(sim):
    sim.home.add_turn(sim.thread)


def _not_loaded(sim):
    sim.backend.loaded_map[sim.thread] = "notLoaded"
    sim.advance(6)                                    # past the 5 s loaded-inventory cadence


def _expired(sim):
    sim.advance(DELIVERY_TIMEOUT + 1)


def _cancel(sim):
    sim.store.cancel_interruption(sim.key, sim.now, actor="gui")


def _thread_disabled(sim):
    sim.store.set_thread_enabled(sim.thread, False, actor="gui")


def _invalid(sim):
    sim.rewrite_failed_turn()


# The withdraw triggers of section 5.3 that section 5.4 names (the old T20 paths:
# notLoaded, expiry, cancel, invalid), plus a foreign turn and a disabled thread.
TRIGGERS = (
    ("superseded_by_user", _foreign_turn),
    ("not_loaded", _not_loaded),
    ("expired", _expired),
    ("cancel", _cancel),
    ("superseded", _invalid),
    ("thread_disabled", _thread_disabled),
)


class CorrelationTest(unittest.TestCase):
    """Section 4.1: the turn our continuation started is the marker row's own turn."""

    def test_T01_recovery_turn_is_the_marker_rows_turn_even_after_a_later_user_turn(self):
        """The marker lands in T2; a person has already started T3 by the time the watch
        looks - including after the watcher restarts. The recovery turn is T2, never the
        thread's latest turn (D1, C5, M7)."""
        for restart in (False, True):
            with self.subTest(restart=restart):
                sim = Scenario(self)
                sim.send()                            # an idle loaded thread: T2 starts at once
                t2 = sim.home.turns(sim.thread)[-1]["turn_id"]
                self.assertNotEqual(t2, sim.failed_turn)
                t3 = sim.home.add_turn(sim.thread, progress=False)
                if restart:
                    sim.open()
                sim.watch()
                row = sim.record()
                self.assertEqual(row["state"], "turn_started")
                self.assertEqual(row["recovery_turn_id"], t2)
                self.assertNotEqual(row["recovery_turn_id"], t3)
                # T3 came after ours, so it is not user work our turn ran after.
                self.assertFalse(row["after_user_work"])
                self.assertIn("correlated", sim.codes())
                # The outcome is read from T2 (which made progress), not from T3 (which
                # made none).
                for _ in range(4):
                    sim.advance(6)
                    sim.engine.tick()
                row = sim.record()
                self.assertEqual(row["state"], "recovered")
                self.assertEqual(row["recovery_turn_id"], t2)
                self.assertEqual(len(sim.backend.send_calls), 1)

    def test_T01_latest_turn_id_is_gone_from_src(self):
        """`delivery()` used to compute the thread's top-ordinal turn and call it ours.
        The name must not survive anywhere in the product source (D1)."""
        offenders = [str(path.relative_to(SRC)) for path in SRC.rglob("*.py")
                     if "latest_turn_id" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])

    def test_T02a_two_marker_rows_are_never_correlated(self):
        """One send cannot explain our marker in two places, so no turn is picked, now
        or later: `submission_unknown(duplicate_marker)` (D2, C10)."""
        sim = Scenario(self)
        sim.send()
        sim.home.add_turn(sim.thread, user_text=sim.prompt)    # a second copy of our marker
        sim.watch()
        row = sim.record()
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "duplicate_marker"))
        self.assertIsNone(row["recovery_turn_id"])
        for _ in range(4):
            sim.watch(step=61)
        row = sim.record()
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "duplicate_marker"))
        self.assertIsNone(row["recovery_turn_id"])
        self.assertNotIn("correlated", sim.codes())
        self.assertEqual(len(sim.backend.send_calls), 1)

    def test_T02a_two_marker_rows_still_withdraw_our_queued_row(self):
        """Rule 2: 'The watch still withdraws our queue row if it exists.'"""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        sim.home.add_turn(sim.thread, user_text=sim.prompt)
        sim.home.add_turn(sim.thread, user_text=sim.prompt)
        sim.watch()
        row = sim.record()
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "duplicate_marker"))
        self.assertIsNone(row["recovery_turn_id"])
        self.assertIn((sim.thread, queue_id), sim.backend.deleted)
        self.assertEqual(sim.home.queued(sim.thread), [])

    def test_T02b_marker_steered_into_someone_elses_turn_is_handed_over(self):
        """Our text landed inside a turn a person started. That turn is theirs:
        `handed_over(marker_not_turn_initiator)` with `user_joined=1`, and its id is
        recorded so a failure of that turn is never auto-recovered (rule 6, D2)."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        theirs = sim.home.add_turn(sim.thread, status="inProgress", progress=False)
        sim.home.remove_queued(queue_id)                        # Codex steered our item in
        sim.home.add_item(sim.thread, theirs, "userMessage", sim.prompt, None)
        sim.watch()
        row = sim.record()
        self.assertEqual((row["state"], row["last_error"]), ("handed_over", "marker_not_turn_initiator"))
        self.assertTrue(row["user_joined"])
        self.assertEqual(row["recovery_turn_id"], theirs)
        self.assertEqual(sim.backend.deleted, [])
        # Their turn now fails: lineage creates the child already stopped, never claimed.
        sim.home.set_turn(sim.thread, theirs, status="failed", error_json=transient_error(),
                          completed_at=int(sim.now))
        sim.advance(1)
        sim.engine.tick()
        children = [r for r in sim.store.all_records() if r["interruption_id"] != sim.key]
        self.assertEqual(len(children), 1)
        self.assertEqual((children[0]["state"], children[0]["last_error"]),
                         ("superseded", "parent_handed_over"))
        for _ in range(3):
            sim.advance(120)
            sim.engine.tick()
        self.assertEqual(len(sim.backend.send_calls), 1)

    def test_T02c_different_client_id_is_an_ambiguous_receipt(self):
        """The queued payload's client id is known and the history row's differs: the
        receipt is ambiguous and nothing is correlated (rule 4)."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        sim.watch()                                             # the watch reads our queued row
        self.assertIsNotNone(sim.record()["recovery_client_id"])
        sim.home.remove_queued(queue_id)
        sim.home.add_turn(sim.thread, user_text=sim.prompt, client_id="another-client-0001")
        sim.watch()
        row = sim.record()
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "ambiguous_receipt"))
        self.assertIsNone(row["recovery_turn_id"])
        self.assertNotIn("correlated", sim.codes())

    def test_T02d_null_client_ids_leave_the_marker_rules_alone(self):
        """A null on either side skips the client-id check: correlation follows the
        marker rules only (rule 4; H-C1 is unverified)."""
        cases = ("both_null", "history_null", "queue_null")
        for case in cases:
            with self.subTest(case=case):
                sim = Scenario(self, after_accept="queue")
                sim.send()
                queue_id = sim.record()["queue_id"]
                if case in ("both_null", "queue_null"):
                    sim.set_queued_client(queue_id, None)
                sim.watch()
                if case == "history_null":
                    self.assertIsNotNone(sim.record()["recovery_client_id"])
                else:
                    self.assertIsNone(sim.record()["recovery_client_id"])
                if case == "both_null":
                    ours = sim.home.dispatch(sim.thread)       # payload client_id is null
                else:
                    sim.home.remove_queued(queue_id)
                    ours = sim.home.add_turn(sim.thread, user_text=sim.prompt,
                                             client_id=None if case == "history_null" else new_id())
                sim.watch()
                row = sim.record()
                self.assertEqual(row["state"], "turn_started")
                self.assertEqual(row["recovery_turn_id"], ours)

    def test_T02e_marker_at_or_below_the_failed_ordinal_is_ambiguous(self):
        """A marker row whose turn is not after the failed turn cannot be our
        continuation's turn: `ambiguous_receipt` (rule 3)."""
        for where in ("below", "at"):
            with self.subTest(where=where):
                sim = Scenario(self, after_accept="queue")
                sim.send()
                sim.home.remove_queued(sim.record()["queue_id"])
                if where == "below":
                    sim.home.add_turn(sim.thread, ordinal=sim.failed_ordinal - 2, user_text=sim.prompt)
                else:
                    sim.home.add_item(sim.thread, sim.failed_turn, "userMessage", sim.prompt, None)
                sim.watch()
                row = sim.record()
                self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "ambiguous_receipt"))
                self.assertIsNone(row["recovery_turn_id"])


class WatchTest(unittest.TestCase):
    """Sections 5.2-5.5: the queued item is taken back only when it must be, and a
    successful delete is never taken as proof that nothing ran."""

    def test_T03_undetermined_turn_is_never_a_reason_to_delete(self):
        """A turn row `inProgress` with `first_user_item_id` NULL after the failed turn
        cannot have started our item while it runs, so the watch waits - across many
        iterations, past the delivery timeout too (C1-B, D3)."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        running = sim.home.add_turn(sim.thread, status="inProgress", user_text=None, progress=False)
        for _ in range(100):
            sim.watch(step=2)                                  # 200 s: past delivery_timeout
        self.assertEqual(sim.backend.deleted, [])
        self.assertEqual(sim.home.queued(sim.thread), [queue_id])
        self.assertEqual(sim.record()["state"], "queued")
        # Once the turn's first user message is projected and it is not ours, it is a
        # foreign turn: the next iteration takes our item back.
        item = sim.home.add_item(sim.thread, running, "userMessage", "a message from the user")
        sim.home.set_turn(sim.thread, running, first_user_item_id=item)
        sim.watch()
        row = sim.record()
        self.assertEqual(sim.backend.deleted, [(sim.thread, queue_id)])
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "superseded_by_user"))

    def test_T03_an_undetermined_turn_never_holds_back_a_cancel_or_a_pause(self):
        """A deliberate refinement of section 5.3. An undetermined turn holds back only
        the decisions that depend on who started it - superseding and expiry (above).
        Cancel, Pause, a disabled thread and notLoaded withdraw at once: Codex starts
        the head of the queue the moment the running turn ends (U1), so waiting for
        that turn would deliver the very message the person asked not to send. If the
        undetermined turn was in fact ours, the settle follows it (T04)."""
        for reason, trigger in (("cancel", _cancel), ("paused", lambda sim: sim.store.set_enabled(False, sim.now)),
                                ("thread_disabled", _thread_disabled), ("not_loaded", _not_loaded)):
            with self.subTest(trigger=reason):
                sim = Scenario(self, after_accept="queue")
                sim.send()
                queue_id = sim.record()["queue_id"]
                sim.home.add_turn(sim.thread, status="inProgress", user_text=None, progress=False)
                trigger(sim)
                sim.watch()
                self.assertEqual(sim.backend.deleted, [(sim.thread, queue_id)])
                self.assertEqual(sim.home.queued(sim.thread), [])
                row = sim.record()
                self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", reason))

    def test_T03_our_own_turn_before_its_user_item_is_projected(self):
        """Our item started a turn, Codex has not yet recorded who started it, and our
        queue row is still there (U2, U3). Nothing is deleted; once the first user item
        is projected, the turn is correlated as ours (rule 5)."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        ours = sim.home.add_turn(sim.thread, status="inProgress", user_text=sim.prompt,
                                 progress=False, first_user=False)
        for _ in range(10):
            sim.watch()
        self.assertEqual(sim.backend.deleted, [])
        self.assertIsNone(sim.record()["recovery_turn_id"])
        sim.home.remove_queued(queue_id)
        with closing(sqlite3.connect(sim.home.root / "thread_history_1.sqlite")) as db:
            item = db.execute("SELECT item_id FROM thread_items WHERE thread_id=? AND turn_id=? "
                              "AND item_type='userMessage'", (sim.thread, ours)).fetchone()[0]
        sim.home.set_turn(sim.thread, ours, first_user_item_id=item)
        sim.watch()
        row = sim.record()
        self.assertEqual(row["state"], "turn_started")
        self.assertEqual(row["recovery_turn_id"], ours)
        self.assertEqual(sim.backend.deleted, [])

    def test_T04_marker_after_a_successful_delete_is_followed_not_superseded(self):
        """Codex started our item, then answered our delete with `deleted:true` (U2).
        The marker appears in the settle window: `turn_started` with the
        `dispatched_despite_delete` event - never `superseded_by_user`, for every
        trigger. `after_user_work=1` for the supersede reasons (section 5.4) (C1-A, D3)."""
        for reason, trigger in TRIGGERS:
            with self.subTest(trigger=reason):
                sim = Scenario(self, after_accept="queue")
                sim.send()
                started = sim.dispatch_inside_delete()
                trigger(sim)
                sim.watch()
                row = sim.record()
                self.assertEqual((row["state"], row["withdraw_reason"], row["withdraw_deleted"]),
                                 ("withdrawn_unconfirmed", reason, True))
                self.assertEqual(len(started), 1)
                sim.watch()
                row = sim.record()
                self.assertEqual(row["state"], "turn_started")
                self.assertEqual(row["recovery_turn_id"], started[0])
                self.assertIn("dispatched_despite_delete", sim.codes())
                self.assertEqual(bool(row["after_user_work"]), reason in SUPERSEDE_REASONS)
                self.assertFalse(sim.states_entered() & WRONG_ENDINGS)
                for _ in range(3):
                    sim.watch(step=60)
                self.assertEqual(sim.record()["state"], "turn_started")
                self.assertEqual(len(sim.backend.send_calls), 1)

    def test_T04_marker_that_appears_late_in_the_settle_window(self):
        """The dispatched turn exists but its user item is projected only a minute after
        our delete returned true. The marker still wins over the withdrawal."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        started = []

        def delete(thread_id, qid):
            sim.backend.deleted.append((thread_id, qid))
            sim.home.remove_queued(qid)
            started.append(sim.home.add_turn(thread_id, status="inProgress", user_text=None, progress=False))
            return True
        sim.backend.delete_queue = delete
        sim.home.add_turn(sim.thread)                          # a person's turn
        sim.watch()
        self.assertEqual(sim.backend.deleted, [(sim.thread, queue_id)])
        self.assertEqual(sim.record()["state"], "withdrawn_unconfirmed")
        for _ in range(6):
            sim.watch(step=10)
        self.assertEqual(sim.record()["state"], "withdrawn_unconfirmed")
        item = sim.home.add_item(sim.thread, started[0], "userMessage", sim.prompt, None)
        sim.home.set_turn(sim.thread, started[0], first_user_item_id=item)
        sim.watch()
        row = sim.record()
        self.assertEqual(row["state"], "turn_started")
        self.assertEqual(row["recovery_turn_id"], started[0])
        self.assertTrue(row["after_user_work"])
        self.assertIn("dispatched_despite_delete", sim.codes())
        self.assertFalse(sim.states_entered() & WRONG_ENDINGS)

    def test_T05_nothing_ran_settles_per_reason_with_a_fresh_projection(self):
        """Delete true, no marker by the end of the settle window, and history is
        current: the record ends per its withdraw reason (C1, D9)."""
        expected = {"cancel": "cancelled", "thread_disabled": "cancelled",
                    "not_loaded": "failed", "expired": "failed",
                    "superseded_by_user": "superseded_by_user", "superseded": "superseded"}
        for reason, trigger in TRIGGERS:
            with self.subTest(trigger=reason):
                sim = Scenario(self, after_accept="queue")
                sim.send()
                queue_id = sim.record()["queue_id"]
                trigger(sim)
                sim.watch()
                row = sim.record()
                self.assertEqual(sim.backend.deleted, [(sim.thread, queue_id)])
                self.assertEqual((row["state"], row["withdraw_reason"], row["withdraw_deleted"]),
                                 ("withdrawn_unconfirmed", reason, True))
                sim.watch(step=DELIVERY_TIMEOUT // 2)          # inside the window: undecided
                self.assertEqual(sim.record()["state"], "withdrawn_unconfirmed")
                row = sim.through_window()
                self.assertEqual(row["state"], expected[reason])
                self.assertIsNone(row["recovery_turn_id"])
                if expected[reason] == "failed":
                    self.assertEqual(machine.public_code(row), "failed_terminal")
                self.assertEqual(len(sim.backend.send_calls), 1)

    def test_T05_stale_projection_at_the_end_of_the_window_is_unknown(self):
        """If Codex's history stopped following the rollout file after the withdrawal,
        a missing marker proves nothing: `submission_unknown(withdraw_unconfirmed)`,
        never resent (C1, D9)."""
        for reason, trigger in (("cancel", _cancel), ("superseded_by_user", _foreign_turn),
                                ("expired", _expired), ("not_loaded", _not_loaded)):
            with self.subTest(trigger=reason):
                sim = Scenario(self, after_accept="queue")
                sim.send()
                trigger(sim)
                sim.watch()
                self.assertEqual(sim.record()["state"], "withdrawn_unconfirmed")
                sim.home.make_stale(sim.thread)                # stale from here to the end
                row = sim.through_window()
                self.assertEqual((row["state"], row["last_error"]),
                                 ("submission_unknown", "withdraw_unconfirmed"))
                for _ in range(3):
                    sim.advance(1000)
                    sim.engine.tick()
                self.assertEqual(len(sim.backend.send_calls), 1)

    def test_T05_projection_stale_withdrawal_always_ends_unknown(self):
        """A withdrawal made *because* history is stale ends unknown even if history has
        caught up by the end of the window (section 5.4)."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        sim.home.make_stale(sim.thread)
        for _ in range(40):
            sim.watch(step=5)
            if sim.record()["state"] != "queued":
                break
        row = sim.record()
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "projection_stale"))
        self.assertEqual(sim.backend.deleted, [(sim.thread, queue_id)])
        sim.home.catch_up(sim.thread)
        row = sim.through_window()
        self.assertEqual((row["state"], row["last_error"]), ("submission_unknown", "withdraw_unconfirmed"))

    def _unknown_with_queued_row(self):
        """A `codex queue` whose result is unknown, although the item did reach the
        queue. The watch then finds our row and records its id."""
        sim = Scenario(self, after_accept="queue")
        sim.backend.default_outcome = "timeout"
        sim.backend.on_send = lambda thread, prompt: sim.home.enqueue(thread, prompt, client_id=new_id())
        sim.send()
        self.assertEqual(sim.record()["state"], "submission_unknown")
        sim.watch()
        queue_id = sim.home.queued(sim.thread)[0]
        row = sim.record()
        self.assertEqual((row["state"], row["queue_id"]), ("submission_unknown", queue_id))
        return sim, queue_id

    def test_T06_unknown_record_with_a_queued_row_is_withdrawn_within_two_seconds(self):
        """Its reconcile schedule is 15 minutes out, but its row sits in Codex's queue:
        the watch covers it every iteration, so a foreign turn gets it withdrawn within
        two 1 s iterations (section 5.1; C6-B, D17)."""
        sim, queue_id = self._unknown_with_queued_row()
        sim.store.update(sim.key, at=sim.now, next_retry_at=sim.now + 900)
        self.assertTrue(sim.engine.watch_needed())
        sim.home.add_turn(sim.thread)
        sim.watch()
        sim.watch()
        self.assertIn((sim.thread, queue_id), sim.backend.deleted)
        self.assertEqual(sim.home.queued(sim.thread), [])
        row = sim.record()
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "superseded_by_user"))

    def test_T06_cleanup_unconfirmed_record_stays_watched_while_its_row_exists(self):
        """After five refused deletes the record is `submission_unknown
        (queue_cleanup_unconfirmed)`, 'which stays watched while the row exists'
        (section 5.4): once deletes work again, the row is gone at the next paced
        attempt. Each delete starts a Codex process, so a failed one is retried every
        delete_retry_seconds rather than every pass."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        sim.backend.delete_result = False
        sim.home.add_turn(sim.thread)
        pace = sim.engine.options["delete_retry_seconds"]
        for _ in range(5):
            sim.watch(step=pace)
        row = sim.record()
        self.assertEqual((row["state"], row["last_error"], row["queue_id"]),
                         ("submission_unknown", "queue_cleanup_unconfirmed", queue_id))
        self.assertTrue(sim.engine.watch_needed())
        sim.backend.delete_result = None
        sim.watch(step=pace)
        sim.watch(step=pace)
        self.assertEqual(sim.home.queued(sim.thread), [])
        self.assertEqual(sim.record()["state"], "withdrawn_unconfirmed")

    def test_T06_unknown_record_older_than_a_day_with_its_row_is_still_watched(self):
        """The 24 h reconcile limit applies only to a record without a queue row
        (section 5.1)."""
        sim, queue_id = self._unknown_with_queued_row()
        sim.advance(25 * 3600)
        self.assertTrue(sim.engine.watch_needed())
        sim.home.add_turn(sim.thread)
        sim.watch()
        self.assertIn((sim.thread, queue_id), sim.backend.deleted)
        self.assertEqual(sim.home.queued(sim.thread), [])
        self.assertEqual(sim.record()["state"], "withdrawn_unconfirmed")

    def test_T07_foreign_turn_between_claim_and_popen_triggers_a_withdraw(self):
        """A person starts a turn after the pre-send re-check but before `codex queue`
        runs. The watch's baseline is the failed turn's ordinal, not 'turns seen since
        the watch started', so that turn gets our item withdrawn (C6-A)."""
        sim = Scenario(self, after_accept="queue")
        foreign = []

        def person_types_first(thread_id, prompt):
            if not foreign:
                foreign.append(sim.home.add_turn(thread_id))
        sim.backend.on_send = person_types_first
        sim.send()
        queue_id = sim.record()["queue_id"]
        self.assertEqual(len(foreign), 1)
        ordinal = {turn["turn_id"]: turn["rollout_ordinal"] for turn in sim.home.turns(sim.thread)}
        self.assertGreater(ordinal[foreign[0]], sim.failed_ordinal)
        sim.watch()
        row = sim.record()
        self.assertEqual(sim.backend.deleted, [(sim.thread, queue_id)])
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "superseded_by_user"))
        self.assertEqual(sim.through_window()["state"], "superseded_by_user")

    def test_T08_change_between_reserve_and_send_releases_the_claim(self):
        """A cancel, Pause, thread disable, invalidation or foreign queued input that
        lands after `reserve` and before `send`: nothing is sent, the claim is released
        (`release_claim`), `retry_count` is unchanged, `last_claim_at` is kept, and no
        notification is made (section 5.5; C6, C11-C, U9)."""
        injections = (
            ("cancel", _cancel, "cancelled"),
            ("pause", lambda sim: sim.store.set_enabled(False, sim.now), "waiting_backoff"),
            ("thread_disable", _thread_disabled, "waiting_backoff"),
            ("foreign_turn", _foreign_turn, "superseded_by_user"),
            ("failed_turn_rewritten", _invalid, "superseded"),
            ("foreign_queued", lambda sim: sim.home.enqueue(sim.thread, "something the user queued"),
             "waiting_retry"),
        )
        for name, inject, target in injections:
            with self.subTest(injection=name):
                sim = Scenario(self)
                sim.register()
                sim.make_due()
                seen = {}
                real = sim.store.reserve_detailed

                def reserve_then_inject(key, now, _real=real, _sim=sim, _seen=seen, _inject=inject, **options):
                    result = _real(key, now, **options)
                    if result[0]:
                        _seen["claim"] = _sim.store.get(key)
                        _seen["notes"] = len(_sim.notes)
                        _inject(_sim)
                    return result
                sim.store.reserve_detailed = reserve_then_inject
                sim.engine.tick()
                self.assertIn("claim", seen, sim.logs)
                self.assertEqual(sim.backend.send_calls, [])
                row = sim.record()
                self.assertEqual(row["state"], target)
                self.assertIsNone(row["submitted_at"])
                self.assertIsNone(row["queue_id"])
                self.assertEqual(row["retry_count"], seen["claim"]["retry_count"])
                self.assertIsNotNone(row["last_claim_at"])
                self.assertEqual(row["last_claim_at"], seen["claim"]["last_claim_at"])
                # A released claim still counts towards the daily cap and the cooldown.
                self.assertEqual(sim.store.recent_claims(sim.thread, 0), [row["last_claim_at"]])
                released = [event for event in sim.events() if event["code"] == "release_claim"]
                self.assertEqual(len(released), 1)
                self.assertEqual(released[0]["to_state"], target)
                self.assertEqual(len(sim.notes), seen["notes"])

    def test_T08_no_notification_between_claim_and_send(self):
        """The positive path: nothing is announced between the claim and the send
        (section 5.5 step 1, section 7.5)."""
        sim = Scenario(self)
        sim.register()
        sim.make_due()
        marks = {}
        real = sim.store.reserve_detailed

        def reserve(key, now, **options):
            result = real(key, now, **options)
            marks["claim"] = len(sim.notes)
            return result
        sim.store.reserve_detailed = reserve
        sim.backend.on_send = lambda thread_id, prompt: marks.setdefault("send", len(sim.notes))
        sim.engine.tick()
        self.assertEqual(len(sim.backend.send_calls), 1)
        self.assertEqual(marks["send"], marks["claim"])

    def test_T09_foreign_queued_input_makes_the_record_wait(self):
        """Somebody already queued something for this conversation. It goes first:
        pre-send WAIT(`user_input_queued`), recorded in the gate vector (D18)."""
        sim = Scenario(self)
        sim.register()
        sim.home.enqueue(sim.thread, "something the user queued")
        for _ in range(2):
            sim.make_due()
            sim.engine.tick()
            self.assertEqual(sim.backend.send_calls, [])
            row = sim.record()
            self.assertEqual((row["state"], row["last_error"]), ("waiting_retry", "user_input_queued"))
            gates = machine.decode_gates(row["gate_eval"])
            self.assertEqual(gates["no_newer_user_work"], (machine.WAIT, "user_input_queued"))
        # Their item runs: the failure is no longer the thread's latest state.
        sim.home.dispatch(sim.thread)
        sim.make_due()
        sim.engine.tick()
        self.assertEqual(sim.record()["state"], "superseded_by_user")
        self.assertEqual(sim.backend.send_calls, [])

    def test_T09_foreign_item_queued_while_ours_is_queued_withdraws_ours(self):
        """A person queues a message behind our continuation: ours is withdrawn
        (`user_queued_input`) and, with nothing having run, ends `superseded_by_user`.
        Their item stays in the queue (D18)."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        theirs = sim.home.enqueue(sim.thread, "something the user queued")
        sim.watch()
        row = sim.record()
        self.assertEqual(sim.backend.deleted, [(sim.thread, queue_id)])
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "user_queued_input"))
        self.assertEqual(sim.through_window()["state"], "superseded_by_user")
        self.assertEqual(sim.home.queued(sim.thread), [theirs])

    def test_T10_edited_queued_item_is_handed_over_without_a_delete(self):
        """A row with our `queue_id` but without our marker is one the user edited in
        Codex. It is theirs now: `handed_over(queued_item_edited)`, and it is never
        deleted (C16)."""
        sim = Scenario(self, after_accept="queue")
        sim.send()
        queue_id = sim.record()["queue_id"]
        sim.watch()
        self.assertEqual(sim.record()["state"], "queued")
        sim.home.edit_queued(queue_id, "the user rewrote this")
        sim.watch()
        row = sim.record()
        self.assertEqual((row["state"], row["last_error"]), ("handed_over", "queued_item_edited"))
        for _ in range(4):
            sim.watch(step=60)
        self.assertEqual(sim.record()["state"], "handed_over")
        self.assertEqual(sim.backend.deleted, [])
        self.assertEqual(sim.home.queued(sim.thread), [queue_id])
        self.assertEqual(len(sim.backend.send_calls), 1)


if __name__ == "__main__":
    unittest.main()
