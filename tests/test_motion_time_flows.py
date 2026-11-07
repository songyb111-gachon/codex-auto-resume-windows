"""The README's first motion shows time passing (v0.6.22, the owner's request; plans/v0621-plan.md item 2).

docs/images/readme-motion.png and its Korean twin were drawn with the window's clock pinned at one moment
(make_screenshots.ENVELOPE_NOW), so every countdown and age it showed stood still for the whole picture. Its plans now
name the window's own clock (`clock_step_ms`, motion_plan.clock_at): each frame's render state says how far that clock
has gone on, at the last tick of its one-second timer at or before the frame's moment on the picture's one clock, and
the render mode reads every countdown and age at that moment (WindowRender.RenderClock, DashboardData.Now).

These build the frames' inputs - the render job, and the pinned installation's answers - and draw nothing.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
import make_motion  # noqa: E402
import motion_plan  # noqa: E402
import motion_window  # noqa: E402

README_PLANS = ("readme-en", "readme-ko")


def build(name: str, forms=None) -> dict:
    """The render job of a README plan, built from its file as make_motion builds it, without drawing."""
    plan = make_motion.load(name)
    frames, _held, _end = make_motion.schedule(plan, make_motion.icon_moments(plan, motion_plan.plan_end(plan)))
    return motion_window.job(plan, frames, Path("frames"), forms if forms is not None else {})


class TheClockMovesOn(unittest.TestCase):
    def test_every_frame_carries_the_window_s_clock_at_the_last_tick_before_it(self):
        for name in README_PLANS:
            plan = make_motion.load(name)
            frames, _held, end = make_motion.schedule(plan)
            states = build(name)["frames"]
            with self.subTest(name):
                self.assertEqual(plan.get("clock_step_ms"), motion_plan.WINDOW_CLOCK_MS)
                clocks = [state["clock"] for state in states]
                self.assertEqual(clocks, [motion_plan.clock_at(frame.t, 1000) for frame in frames])
                self.assertEqual(clocks[0], 0, "the first frame is the still's moment")
                self.assertEqual(clocks, sorted(clocks), "the clock never goes back")
                self.assertTrue(all(0 <= frame.t - clock < 1000 for frame, clock in zip(frames, clocks)),
                                "the clock is never ahead of the frame, nor a tick behind it")
                self.assertEqual(sorted(set(clocks)), list(range(0, end, 1000)),
                                 "every tick of the window's clock over the picture is shown")

    def test_a_plan_without_the_clock_stays_at_the_pinned_moment(self):
        plan = {"format": motion_plan.FORMAT, "name": "t", "locale": "en", "canvas": {"theme": "light"},
                "scenes": [{"id": "A", "steps": [{"hold": 1500}, {"set": {"page": "pending"}, "hold": 1500}]}]}
        motion_plan.check(plan)
        job = motion_window.job(plan, motion_plan.expand(plan), Path("out"), forms={"en": {"answers": []}})
        self.assertTrue(all("clock" not in state for state in job["frames"]))
        self.assertEqual(motion_window.shown_now(job["frames"][-1]), motion_window.shown_now({}))

    def test_the_clock_ticks_only_at_the_window_s_own_step(self):
        plan = {"format": motion_plan.FORMAT, "name": "t", "locale": "en", "clock_step_ms": 500,
                "scenes": [{"id": "A", "steps": [{"hold": 1500}]}]}
        with self.assertRaises(motion_plan.PlanError):
            motion_plan.check(plan)

    def test_two_builds_give_the_same_inputs(self):
        for name in README_PLANS:
            with self.subTest(name):
                self.assertEqual(json.dumps(build(name), sort_keys=True), json.dumps(build(name), sort_keys=True))


class TheTimesShownMoveOn(unittest.TestCase):
    """What the window works out from the pinned installation's answers at each frame's moment, as it works it out."""

    @classmethod
    def setUpClass(cls):
        cls.replies = {item["command"]: item["reply"] for item in motion_window.answers("en")}
        cls.states = build("readme-en")["frames"]

    def test_the_answers_are_the_same_on_a_second_build(self):
        again = {item["command"]: item["reply"] for item in motion_window.answers("en")}
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.replies, sort_keys=True))

    def at_each_tick(self, value):
        """value(now) at the first frame of each tick of the window's clock."""
        seen = {}
        for state in self.states:
            seen.setdefault(state["clock"], value(motion_window.shown_now(state)))
        return [seen[clock] for clock in sorted(seen)]

    def test_every_next_check_counts_down_a_second_a_tick_and_none_comes_due(self):
        pending = self.replies["dashboard"]["pending"]
        due = sorted(row["eligible_at"] for row in pending if row.get("eligible_at"))
        self.assertTrue(due, "the pinned installation has tasks waiting for a time")
        for eligible in due:
            counts = self.at_each_tick(lambda now: int(eligible - now))
            with self.subTest(eligible=eligible):
                self.assertEqual(counts, list(range(counts[0], counts[0] - len(counts), -1)))
                self.assertGreater(counts[-1], 0, "a task the picture shows waiting is never due in it")

    def test_every_age_grows_with_the_clock(self):
        watcher = self.replies["dashboard"]["status"]["watcher"]
        stamps = {"last check": watcher["last_tick_at"], "usage read": watcher["usage"]["read_at"]}
        stamps.update(("checks of " + row["interruption_id"], row["gates_at"])
                      for row in self.replies["dashboard"]["pending"] if row.get("gates_at"))
        for what, stamp in stamps.items():
            ages = self.at_each_tick(lambda now: int(now - stamp))
            with self.subTest(what):
                self.assertEqual(ages, list(range(ages[0], ages[0] + len(ages))))

    def test_a_reset_and_its_countdown_agree_in_every_frame(self):
        """The usage-limited task's Next check counts down to the reset Codex gave, and the reset's time of day the
        waiting line prints stays where it is: in every frame the two say the same moment."""
        import make_screenshots
        limited = [row for row in self.replies["dashboard"]["pending"] if row.get("reset_at")]
        self.assertTrue(limited, "the pinned installation has a task waiting for its usage reset")
        resets = {window["reset_at"] for window in self.replies["dashboard"]["status"]["watcher"]["usage"]["windows"]}
        for row in limited:
            self.assertIn(row["reset_at"], resets)
            for state in self.states[::97]:
                now = motion_window.shown_now(state)
                on_the_clock = make_screenshots.WINDOW_CLOCK + (now - make_screenshots.ENVELOPE_NOW)
                self.assertEqual(on_the_clock + (row["eligible_at"] - now),
                                 make_screenshots.WINDOW_CLOCK + (row["reset_at"] - make_screenshots.ENVELOPE_NOW))


class TheWindowReadsTheFramesClock(unittest.TestCase):
    def test_now_in_a_picture_is_the_pinned_moment_and_the_frame_s_clock(self):
        self.assertIn("if (Soft.StillNow > 0) return Soft.StillNow + renderClock;",
                      guiscan.member_body("SettingsForm", "Now"))

    def test_the_render_mode_sets_the_clock_first_and_says_every_time_again_at_it(self):
        clock = guiscan.member_body("SettingsForm", "RenderClock")
        self.assertIn('frame.TryGetValue("clock", out given)', clock)
        self.assertIn("/ 1000.0", clock)
        self.assertIn("if (snapshot != null) ApplySnapshot(snapshot);", clock)
        state = guiscan.member_body("SettingsForm", "RenderState")
        self.assertLess(state.index("RenderClock(frame);"), state.index("ShowPage(page);"))
        self.assertNotIn("renderClock =", guiscan.read("gui/DashboardData.cs"), "only the render mode sets it")


if __name__ == "__main__":
    unittest.main()
