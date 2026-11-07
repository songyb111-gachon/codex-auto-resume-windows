"""Up to four sends wait for their receipts at once, one in each conversation, while every claim and look stays on the
tick (v0.6.15-beta, P12, engine/launches.py).

The scenarios run the real engine and store over a codexsim home, with a simulated backend whose send - entered
through the worker's own launch guard, as Backend.send enters it - waits on an event before it answers, so two
receipts can be seen waiting at the same moment. The plug answers P12 and nothing else. Scratch folders only.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codexsim import BASE, RESET, CodexHome, SimBackend  # noqa: E402
from codex_auto_resume.codex import LocalSource  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Plug, Point  # noqa: E402
from codex_auto_resume.domain.plughands import MAX_WORKERS, workers  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.engine import launches  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402

THREADS = ["%d%d%d%d%d%d%d%d-1111-7111-8111-111111111111" % ((n,) * 8) for n in range(1, 5)]
TURN = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
OPTIONS = {"reset_grace_seconds": 60, "state_poll_seconds": 60, "conservative_poll_seconds": 900,
           "delivery_timeout_seconds": 180}


class Workers(Plug):
    """A plug that answers P12 with `answer`, and writes down which points it was asked about."""

    def __init__(self, answer):
        self.answer, self.claims = answer, []

    def partition(self, records):
        return self.answer

    def claim_ledger(self, connection, record, now, carried):
        self.claims.append((record["thread_id"], frozenset(carried), threading.current_thread().name))
        return DEFER


class Waiting(SimBackend):
    """Each send, entered through its launch guard, waits until `go` is set (or `patience`, three seconds) before it
    answers - and counts how many are waiting at once. With `release_at`, the send that makes that many wait at once
    sets `go` itself: the overlap is seen the moment it happens, however slowly a busy machine starts the second."""

    def __init__(self, home):
        super().__init__(home)
        self.go = threading.Event()
        self.lock = threading.Lock()
        self.waiting = self.most = 0
        self.patience = 3.0
        self.release_at = None
        self.before_guard = None
        self.raising = set()

    def send(self, thread_id, prompt, *, launch_guard=None):
        if self.before_guard is not None:
            self.before_guard(thread_id)
        with launch_guard as permitted:
            if permitted is not True:
                return {"outcome": "not_started", "error_code": "queue_consent_refused"}
            with self.lock:
                self.send_calls.append((thread_id, prompt))
        if thread_id in self.raising:
            raise OSError("the queue process exploded")
        with self.lock:
            self.waiting += 1
            self.most = max(self.most, self.waiting)
            if self.release_at is not None and self.waiting >= self.release_at:
                self.go.set()
        self.go.wait(timeout=self.patience)
        with self.lock:
            self.waiting -= 1
        queue_id = self.home.enqueue(thread_id, prompt, client_id="0a1b2c3d-0009-7000-8000-%012d" % len(self.send_calls))
        return {"outcome": "accepted", "queue_id": queue_id}


class Case(unittest.TestCase):
    answer = 2

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.now = BASE + 10.0
        self.store = Store(self.root / "state")
        self.addCleanup(self.store.close)
        self.store.set_enabled(True, self.now)
        self.home = CodexHome(self.root / "home")
        self.home.clock = lambda: self.now
        self.backend = Waiting(self.home)
        self.plug = Workers(self.answer)
        self.opened = []

        def open_store():
            store = Store(self.root / "state", check=False)
            self.opened.append(store)
            return store
        self.engine = Engine(self.store, LocalSource(self.home.root), self.backend, clock=lambda: self.now,
                             options=dict(OPTIONS), plug=self.plug, open_store=open_store,
                             dispatch_lock=lambda: threading.RLock())
        self.lock = threading.RLock()
        self.engine.dispatch_lock = lambda: self.lock

    def due(self, threads):
        for thread in threads:
            self.backend.loaded_map[thread] = "loaded"
            self.home.fail_usage(thread, TURN)
        self.engine.tick()
        self.now = RESET + 61

    def states(self):
        return {row["thread_id"]: (row["state"], row["last_error"]) for row in self.store.all_records()}


class PoolTests(Case):
    def test_two_conversations_receipts_are_waited_for_at_once(self):
        """The first send waits - up to 30 s, not the three a busy CI runner once spent starting the second worker
        (dev CI 2026-10-16: "1 != 2") - until the second is waiting beside it, and both then answer. Sends that took
        turns would leave the first alone for all of that, and fail."""
        self.backend.patience, self.backend.release_at = 30.0, 2
        self.due(THREADS[:2])
        self.engine.tick()
        self.assertEqual(self.backend.most, 2, "the second send waited for the first's receipt")
        self.assertEqual({state for state, _ in self.states().values()}, {"queued"})

    def test_every_claim_is_the_tick_threads_and_none_waits_for_a_free_worker_inside_it(self):
        self.backend.go.set()
        self.due(THREADS[:3])
        order = [row["thread_id"] for row in self.store.records_in({"waiting_reset", "waiting_poll"})]
        self.engine.tick()
        names = [name for _thread, _carried, name in self.plug.claims]
        self.assertEqual(len(names), 3)
        self.assertEqual(set(names), {threading.current_thread().name})
        self.assertTrue(all(Point.CONCURRENCY in carried for _thread, carried, _name in self.plug.claims),
                        "the ledger is told each pooled send, and pays for it")
        self.assertEqual([thread for thread, _carried, _name in self.plug.claims], order, "in their order")

    def test_the_tick_returns_only_after_every_receipt_is_settled(self):
        self.due(THREADS[:2])
        before = threading.active_count()
        self.engine.tick()
        self.assertEqual(threading.active_count(), before, "no worker outlives the tick")
        self.assertEqual({state for state, _ in self.states().values()}, {"queued"})
        self.assertTrue(self.opened and all(store._connection is None for store in self.opened),
                        "every worker's store was closed")

    def test_one_conversation_never_has_two_in_flight(self):
        self.backend.go.set()
        self.due(THREADS[:1])
        # A second failure of the same conversation, already due beside the first.
        first = self.store.all_records()[0]
        self.store.register({"thread_id": THREADS[0], "turn_id": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
                             "completed_at": BASE + 1, "started_at": BASE, "ordinal": 9,
                             "interruption_id": "e" * 64, "reset_at": None, "limit_type": "x", "uncertain": False,
                             "category": "server_5xx"}, self.now - 1, next_retry_at=BASE)
        self.engine.tick()
        self.assertEqual(len(self.backend.send_calls), 1)
        self.assertEqual(self.store.get(first["interruption_id"])["state"], "queued")
        self.assertEqual(self.store.get("e" * 64)["last_error"], "other_recovery_in_flight")

    def test_a_pause_committed_after_the_claim_stops_the_launch_and_the_claim_is_given_back(self):
        self.backend.go.set()
        self.due(THREADS[:2])
        def pause_first(thread_id):
            # A person's Pause, from another process's connection, after this send was claimed and before its launch.
            if thread_id == THREADS[1]:
                with Store(self.root / "state", check=False) as other:
                    other.set_enabled(False, time.time())
        self.backend.before_guard = pause_first
        self.engine.tick()
        states = self.states()
        self.assertEqual(states[THREADS[0]][0], "queued")
        self.assertIn(states[THREADS[1]][0], ("waiting_reset", "waiting_poll", "waiting_retry"))
        self.assertEqual(states[THREADS[1]][1], "released_before_send")
        self.assertEqual([call[0] for call in self.backend.send_calls], [THREADS[0]], "the second never launched")

    def test_a_worker_whose_send_raised_leaves_an_uncertain_submission(self):
        self.backend.go.set()
        self.backend.raising.add(THREADS[1])
        self.due(THREADS[:2])
        self.engine.tick()
        self.assertEqual(self.states()[THREADS[1]], ("submission_unknown", "queue_result_unknown_do_not_resend"))

    def test_a_worker_that_cannot_open_its_store_launched_nothing(self):
        self.backend.go.set()
        self.due(THREADS[:1])

        def broken():
            raise OSError("no state")
        self.engine.open_store = broken
        self.engine.tick()
        self.assertEqual(self.backend.send_calls, [])
        self.assertEqual(self.states()[THREADS[0]], ("waiting_retry", "queue_process_not_started"))


class AnswerTests(unittest.TestCase):
    def test_only_two_to_eight_is_taken(self):
        self.assertEqual(MAX_WORKERS, 8)
        self.assertEqual([workers(answer) for answer in (2, 3, 4, 5, 6, 7, 8)], [2, 3, 4, 5, 6, 7, 8])
        for answer in (DEFER, None, 0, 1, 9, True, "2", 2.0, [2]):
            with self.subTest(answer=answer):
                self.assertEqual(workers(answer), 1)


class NoPoolTests(Case):
    def test_an_answer_core_does_not_take_starts_no_thread(self):
        for answer in (1, 9, True, "2", DEFER):
            with self.subTest(answer=answer):
                self.setUp()
                self.plug.answer = answer
                self.backend.go.set()
                self.due(THREADS[:2])
                started = []
                real = launches.LaunchPool._launch
                launches.LaunchPool._launch = lambda pool, *a: started.append(a) or real(pool, *a)
                try:
                    self.engine.tick()
                finally:
                    launches.LaunchPool._launch = real
                self.assertEqual(started, [])
                self.assertEqual(self.backend.most, 1)
                self.assertEqual(self.opened, [], "no worker store was opened")


if __name__ == "__main__":
    unittest.main()
