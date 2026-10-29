"""A run kind turned off still finishes what it started (v0.6.18, the advanced audit's R1 and R3).

headless_run, compact_continue and model_fallback run turns of their own on Codex's app server. Turned off - by the
person, All off, a tripwire or an edition's entry - or watched, P8 used to stop asking them anything, so a turn already
running could no longer be stopped (the Dashboard's Stop wrote a row nothing read: "stopping" for up to six hours), a
row no thread followed was never ended, and a model a fallback turn still owed its conversation was never put back.
Their `tend` (runtime.Runtime.tick) keeps that clean-up going whatever they stand at, and never starts a turn.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume_advanced.codex import headless  # noqa: E402
from codex_auto_resume_advanced.registry import MODEL_FALLBACK  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, OffReason, RunEnd  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from test_advanced_headless_run import HeadlessCase  # noqa: E402
from test_engine import T1  # noqa: E402

KEY = "%064x" % 77


class StopAfterOffTests(HeadlessCase):
    def running(self):
        plug = self.armed(completes_after=None)
        self.closed()
        self.h.tick()
        key = self.h.record()["interruption_id"]
        self.h.tick(advance=1)                          # the P8 tick writes the live run's row
        self.assertEqual([row["interruption_id"] for row in plug.runtime.state.runs()], [key])
        return plug, key

    def stop(self, plug, key):
        from codex_auto_resume_advanced import surfaces
        answered = surfaces.bridge(plug.runtime, "advanced-headless-stop", {"interruption_id": key})
        self.assertTrue(answered["done"], answered)
        self.h.tick(advance=1)
        self.settle()
        self.h.tick(advance=1)

    def test_a_stop_still_interrupts_a_turn_after_its_capability_is_turned_off(self):
        """Fails with `tend` reverted: off, nothing handed the Stop on and the row said "stopping" until the cap."""
        for how in ("disarm", "all_off", "trip"):
            with self.subTest(how):
                self.h = self.fresh()
                self.servers.clear()
                self.follower = headless.Follower(poll=0.01)
                plug, key = self.running()
                arming = plug.runtime.arming
                if how == "disarm":
                    self.assertTrue(arming.disarm(self.cap, actor=Actor.DASHBOARD)["done"])
                elif how == "all_off":
                    self.assertTrue(arming.all_off(actor=Actor.DASHBOARD)["done"])
                else:
                    arming.trip(self.cap, OffReason.HOOK_EXCEPTION)
                self.h.tick(advance=1)
                self.assertIsNotNone(self.follower.live(), "a turn already running ends at its cap, not at off")
                self.stop(plug, key)
                self.assertIsNone(self.follower.live())
                self.assertEqual(plug.runtime.state.runs(live=False)[0]["end"], RunEnd.INTERRUPTED)
                self.assertIn("turn/interrupt", self.servers[-1].methods())

    def test_watched_a_stop_still_reaches_the_turn(self):
        plug, key = self.running()
        self.arm(plug, state="shadow")
        self.stop(plug, key)
        self.assertEqual(plug.runtime.state.runs(live=False)[0]["end"], RunEnd.INTERRUPTED)

    def test_off_a_row_no_thread_follows_is_ended_lost_and_no_turn_starts(self):
        plug = self.armed()
        state = plug.runtime.state
        state.run_started(KEY, self.cap, T1, started_at=self.h.now - 60, ends_by=self.h.now + 3600)
        self.assertTrue(plug.runtime.arming.disarm(self.cap, actor=Actor.DASHBOARD)["done"])
        self.closed()
        self.h.tick(advance=1)
        self.assertEqual(state.runs(live=False)[0]["end"], RunEnd.LOST)
        self.assertEqual(self.servers, [], "off, it never runs a turn")


class Server:
    def __init__(self, model_after):
        self.calls, self.model_after, self.closed = [], model_after, False

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.closed = True

    def call(self, method, params=None):
        self.calls.append((method, params))
        return {"model": self.model_after} if method == "thread/resume" else {}


class RestoreAfterOffTests(TakingCase):
    DEFINITION = MODEL_FALLBACK

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(word) for word in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def owing(self, h=None, state="armed"):
        h = h or self.h
        plug = self.armed(h, state=state)
        code = plug.runtime._code_of(self.DEFINITION)
        self.servers = []

        def opening(capability):
            self.servers.append(Server("its-own"))
            return self.servers[-1]
        code._open, code.follower, code._unheld = opening, headless.Follower(poll=0.01), (lambda thread_id: True)
        code._app = lambda: False
        plug.runtime.state.run_owed(KEY, self.cap, T1, "its-own", started_at=h.now - 60, ends_by=h.now + 3600)
        return plug

    def test_a_model_owed_back_is_put_back_after_the_capability_is_turned_off(self):
        """Fails with `tend` reverted: off - by the person, All off, a tripwire or an edition's entry - the
        conversation stayed on Codex's default model."""
        for how in ("disarm", "all_off", "trip", "edition_entered"):
            with self.subTest(how):
                h = self.fresh()
                plug = self.owing(h)
                arming = plug.runtime.arming
                if how == "disarm":
                    arming.disarm(self.cap, actor=Actor.DASHBOARD)
                elif how == "all_off":
                    arming.all_off(actor=Actor.DASHBOARD)
                elif how == "trip":
                    arming.trip(self.cap, OffReason.HOOK_EXCEPTION)
                else:
                    arming.edition_entered()
                h.tick(advance=1)
                self.assertEqual([method for method, _ in self.servers[0].calls],
                                 ["thread/resume", "thread/settings/update", "thread/resume"])
                self.assertEqual(self.servers[0].calls[1][1], {"threadId": T1, "model": "its-own"})
                self.assertEqual(plug.runtime.state.runs_owed(self.cap), [])

    def test_watched_a_model_owed_back_is_put_back_too(self):
        plug = self.owing(state="shadow")
        self.h.tick(advance=1)
        self.assertIn(("thread/settings/update", {"threadId": T1, "model": "its-own"}), self.servers[0].calls)
        self.assertEqual(plug.runtime.state.runs_owed(self.cap), [])


if __name__ == "__main__":
    unittest.main()
