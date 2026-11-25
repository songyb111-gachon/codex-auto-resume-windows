"""D15 inside the engine (review 6, S1): a panic where the reference catches an exception costs what the exception
costs there - one record's look, one send - and never the tick.

Each case runs one scenario twice in this process, on two worlds built alike (test_engine's Harness: a Store, a codexsim
home, the real LocalSource and SimBackend, one clock): once with the checkout's Python Engine, whose seam object RAISES
at one call, and once with car-engine through the scenario proxy (engineproxy.py), whose same seam object makes
car-harness PANIC at that call (`engineproxy.Panic`) - what a panic in S3.3's transport, car-codex or car-policy would
be there. After every step the two worlds must be equal: whether the step raised, every record's state, error,
counters and schedule, the engine's log, the notifications and the backend's sends. (The checkout's engine is the tag's
but for detect.py's HistoryNotYet, which no world here meets: each has a conversation.)

The cases: a send that panics (the reference's `except Exception: {"outcome": "unknown"}`), one record's look that
panics beside another that sends (`eligibility_check_failed_no_submission`), an observation that panics (observe's own
`except`: unknown, looked at again), a watch row that panics (`reconciliation_unavailable`), and a tick that ends in one: the
person's usage check is still said not checked (`_usage_checks_left` in tick's `finally`) and the tick still raises.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

RECORD: list[str] = []
# codexsim's ids are random in each world: a recovery turn is compared by whether there is one.
FIELDS = ("thread_id", "turn_id", "state", "last_error", "attempt_count", "retry_count", "next_retry_at",
          "withdraw_reason")


def proxy():
    from rustdiff import shim
    return shim.engine_proxy()


class Flaky:
    """A seam object - a store, source or backend - that answers as `real` but fails at `method` while `when` says so:
    raising `error` (the reference's world) or panicking (car-engine's)."""

    def __init__(self, real, method, error, when=lambda *args: True):
        self.real, self.method, self.error, self.when, self.armed = real, method, error, when, True

    def __getattr__(self, name):
        found = getattr(self.real, name)
        if name != self.method or not callable(found):
            return found

        def call(*args, **kwargs):
            if self.armed and self.when(*args):
                raise self.error("%s failed here" % name)
            return found(*args, **kwargs)
        return call


class World:
    """test_engine's Harness on one side: `rust` builds car-engine (the proxy) over the same objects."""

    def __init__(self, case, rust: bool, *, options=None):
        import test_engine
        from codex_auto_resume.codex import rollout
        # The reader's module state is cleared for each world, as enginerun.py clears it for each scenario: both worlds
        # name the same conversations, and what one read must not answer the other.
        for kept in ("_SPLITS", "_ASKED", "_RELISTED", "_META", "_TRIGGERS"):
            if hasattr(rollout, kept):
                getattr(rollout, kept).clear()
        temp = tempfile.TemporaryDirectory()
        case.addCleanup(temp.cleanup)
        self.h = test_engine.Harness(Path(temp.name) / "state", options=options)
        case.addCleanup(self.h.close)
        self.rust, self.error = rust, (proxy().Panic if rust else RuntimeError)
        self.h.enable()

    def build(self, *, store=None, source=None, backend=None):
        """The engine, over the seams given (a Flaky one in place of the Harness's own)."""
        h = self.h
        maker = proxy().Engine if self.rust else type(h.engine)
        h.engine = maker(store or h.store, source or h.source, backend or h.backend, clock=lambda: h.now,
                         log=lambda *args: h.logs.append(args), options=h.options,
                         notify=lambda *args: h.notifications.append(args))
        return h.engine

    def step(self, what):
        try:
            what(self.h)
            raised = None
        except Exception:
            raised = "raised"
        rows = [dict({name: row.get(name) for name in FIELDS}, turn_started=row.get("recovery_turn_id") is not None)
                for row in self.h.store.all_records()]
        logs = [(entry[0], entry[1]) for entry in self.h.logs]
        notes = [entry[0] for entry in self.h.notifications]
        return {"raised": raised, "rows": rows, "logs": logs, "notes": notes,
                "sends": len(self.h.backend.send_calls)}


class EnginePanicDiff(unittest.TestCase):
    maxDiff = None

    def run_both(self, name, scenario):
        """`scenario(world)` returns the steps (callables of the Harness) after building the world's engine."""
        traces = []
        for rust in (False, True):
            world = World(self, rust)
            steps = scenario(world)
            traces.append([world.step(each) for each in steps])
        reference, rust = traces
        for index, (want, got) in enumerate(zip(reference, rust)):
            self.assertEqual(want, got, "%s, step %d: the reference raised, car-engine panicked, and they differ"
                             % (name, index))
        RECORD.append("engine panics: %s, %d steps equal (reference raises where car-engine panics)"
                      % (name, len(reference)))
        return reference

    def test_a_send_that_panics_is_unknown_never_sent_again(self):
        import test_engine

        def scenario(world):
            h = world.h
            backend = Flaky(h.backend, "send", world.error)
            world.build(backend=backend)
            h.home.fail_usage(test_engine.T1, test_engine.TURN_A)
            h.backend.loaded_map[test_engine.T1] = "loaded"
            return [lambda h: h.tick(), lambda h: setattr(h, "now", test_engine.RESET + 61), lambda h: h.tick(),
                    lambda h: h.tick(advance=900), lambda h: h.tick(advance=3600)]
        found = self.run_both("a send that panics", scenario)
        self.assertEqual(found[2]["rows"][0]["last_error"], "queue_result_unknown_do_not_resend")

    def test_one_record_whose_look_panics_costs_that_record_alone(self):
        import test_engine

        def scenario(world):
            h = world.h
            source = Flaky(h.source, "latest", world.error, when=lambda thread, *rest: thread == test_engine.T1)
            world.build(source=source)
            for thread, turn in ((test_engine.T1, test_engine.TURN_A), (test_engine.T2, test_engine.TURN_B)):
                h.home.fail_usage(thread, turn)
                h.backend.loaded_map[thread] = "loaded"
            return [lambda h: h.tick(), lambda h: setattr(h, "now", test_engine.RESET + 61), lambda h: h.tick(),
                    lambda h: h.tick(advance=60)]
        found = self.run_both("one record's look panics, the other sends", scenario)
        self.assertIn((test_engine.T1, "eligibility_check_failed_no_submission"), found[2]["logs"])
        self.assertEqual(found[2]["sends"], 1)

    def test_an_observation_that_panics_is_unknown_and_looked_at_again(self):
        import test_engine

        def scenario(world):
            h = world.h
            source = Flaky(h.source, "turn_observation", world.error)
            source.armed = False
            world.build(source=source)
            h.home.fail_usage(test_engine.T1, test_engine.TURN_A)
            h.backend.loaded_map[test_engine.T1] = "loaded"

            def arm(h):
                source.armed = True
            return [lambda h: h.tick(), lambda h: setattr(h, "now", test_engine.RESET + 61), lambda h: h.tick(),
                    lambda h: h.tick(advance=2), arm, lambda h: h.tick(advance=30), lambda h: h.tick(advance=30)]
        found = self.run_both("an observation that panics", scenario)
        # observe's own `except Exception: seen = None`: unreadable is unknown, the record waits, the tick goes on.
        self.assertEqual((found[-1]["raised"], found[-1]["rows"][0]["state"]), (None, "turn_completed"))

    def test_a_watch_row_that_panics_is_reconciliation_unavailable(self):
        import test_engine

        def scenario(world):
            h = world.h
            source = Flaky(h.source, "marker_rows", world.error)
            source.armed = False
            world.build(source=source)
            h.backend.after_accept = "queue"
            h.home.fail_usage(test_engine.T1, test_engine.TURN_A)
            h.backend.loaded_map[test_engine.T1] = "loaded"

            def arm(h):
                source.armed = True
            return [lambda h: h.tick(), lambda h: setattr(h, "now", test_engine.RESET + 61), lambda h: h.tick(),
                    arm, lambda h: h.watch(advance=1), lambda h: h.tick(advance=5)]
        found = self.run_both("a watch row that panics", scenario)
        self.assertIn((test_engine.T1, "reconciliation_unavailable"), found[-2]["logs"])

    def test_a_tick_that_ends_in_a_panic_still_says_the_usage_check_was_not_made(self):
        import test_engine

        def scenario(world):
            h = world.h
            store = Flaky(h.store, "settings", world.error)
            store.armed = False
            world.build(store=store)
            h.home.fail_usage(test_engine.T1, test_engine.TURN_A)
            h.backend.loaded_map[test_engine.T1] = "loaded"

            def ask(h):
                key = h.store.all_records()[0]["interruption_id"]
                h.store.ask_usage_check(key, h.now)
                store.armed = True

            def checks(h):
                key = h.store.all_records()[0]["interruption_id"]
                h.logs.append((None, "events:" + ",".join(event["code"] for event in h.store.events(key))))
            return [lambda h: h.tick(), ask, lambda h: h.tick(advance=5), checks]
        found = self.run_both("a tick that ends in a panic", scenario)
        self.assertEqual(found[2]["raised"], "raised")

    def test_an_unbounded_watch_budget_is_no_deadline(self):
        import test_engine

        def scenario(world):
            h = world.h
            h.options["watch_budget_seconds"] = 1e300
            world.build()
            h.backend.after_accept = "queue"
            h.home.fail_usage(test_engine.T1, test_engine.TURN_A)
            h.backend.loaded_map[test_engine.T1] = "loaded"
            return [lambda h: h.tick(), lambda h: setattr(h, "now", test_engine.RESET + 61), lambda h: h.tick(),
                    lambda h: h.watch(advance=1), lambda h: h.tick(advance=5)]
        self.run_both("a watch budget of 1e300 s", scenario)


if __name__ == "__main__":
    unittest.main()
