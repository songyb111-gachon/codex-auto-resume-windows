"""Every moving stretch of the motion pictures is drawn at the product's own cadence (the owner, 2026-10-18:
"apng는 가벼운거보다 퀄리티가 중요해" - quality before size).

The steps are read from the product, never written here: the window's light ticks at HaloDot's timer, a turn of the
wheel glides at SoftBar.GlideInterval to arrival, the drop list fades in at Motion.Interval over Brand.TransitionMs,
the card moves at notice_card.FRAME_MS through ENTRANCE_MS and EXIT_MS and breathes at BREATH_FRAME_MS. A plan that
went back to 40 ms steps, ten light frames a second, four wheel frames or nine entrance frames fails here; so does a
budget with a size target, or a lever kept only for size.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
import make_motion  # noqa: E402
import motion_plan  # noqa: E402

# The tray's tick (Windows' 15.625 ms timer) and the card's FRAME_MS: the pointer is drawn no coarser.
POINTER_STEP = 16


def constant(source: str, pattern: str) -> int:
    found = re.search(pattern, source)
    if found is None:
        raise AssertionError("the window's source no longer says %s" % pattern)
    return int(found.group(1))


def window_light_ms() -> int:
    return constant(guiscan.type_body("HaloDot"), r"timer\.Interval = (\d+);")


def glide_ms() -> int:
    return constant(guiscan.type_body("SoftBar"), r"const int GlideInterval = (\d+);")


def motion_ms() -> int:
    return constant(guiscan.type_body("Motion"), r"const int Interval = (\d+);")


def transition_ms() -> int:
    return constant(guiscan.read("gui/Brand.cs"), r"const int TransitionMs = (\d+);")


def steps(plan, key):
    return [step for scene in plan["scenes"] for step in scene["steps"] if key in step]


class ReadmeCadenceTests(unittest.TestCase):
    def plans(self):
        return [motion_plan.load(make_motion.plan_path(name)) for name in make_motion.PLAN_NAMES]

    def test_the_window_s_light_is_drawn_at_its_own_timer_s_step(self):
        for plan in self.plans():
            with self.subTest(plan["name"]):
                self.assertEqual(plan["light_step_ms"], window_light_ms())
                self.assertNotIn("lights_per_second", plan)
                self.assertFalse(plan.get("first_hold"), "the light breathes from frame 1 on")

    def test_a_turn_of_the_wheel_is_every_tick_of_the_glide_to_its_arrival(self):
        ticks = transition_ms() // glide_ms() + 1              # v0.6.23: a glide is a time, not a number of frames
        for plan in self.plans():
            for step in steps(plan, "wheel"):
                with self.subTest(plan["name"]):
                    self.assertEqual(step["step"], glide_ms())
                    self.assertGreaterEqual(step["frames"], ticks + 1, "the glide is cut short")

    def test_the_drop_list_fades_in_at_its_own_step_through_its_transition(self):
        for plan in self.plans():
            for step in steps(plan, "open"):
                with self.subTest(plan["name"]):
                    self.assertEqual(step["step"], motion_ms())
                    self.assertGreaterEqual(step["frames"] * step["step"], transition_ms())
            frames = motion_plan.expand(plan)
            appearing = [dict(dict(frame.window)["droplist"]).get("appear_ms") for frame in frames
                         if "droplist" in dict(frame.window)]
            self.assertIn(0, appearing)

    def test_the_pointer_and_its_click_move_at_the_tray_s_tick(self):
        for plan in self.plans():
            with self.subTest(plan["name"]):
                for key in ("move", "hover", "press"):
                    for step in steps(plan, key):
                        self.assertLessEqual(step["step"], POINTER_STEP, step)
                self.assertLessEqual(plan["ripple_step"], POINTER_STEP)

    def test_the_budget_is_a_generous_ceiling_and_no_target(self):
        for plan in self.plans():
            with self.subTest(plan["name"]):
                self.assertEqual(plan["budget"], {"cap": 9000000})


class CardCadenceTests(unittest.TestCase):
    def test_the_card_enters_and_leaves_at_its_own_frame_step_and_breathes_at_its_own(self):
        from codex_auto_resume import notice_card
        for name in make_motion.CARD_PLANS:
            plan = motion_plan.load(make_motion.plan_path(name))
            with self.subTest(name):
                self.assertEqual(plan["light_step_ms"], notice_card.BREATH_FRAME_MS)
                self.assertEqual(plan["budget"], {"cap": 4000000})
                for step in steps(plan, "card"):
                    if step["card"] == "shown":
                        continue
                    self.assertEqual(step["step"], notice_card.FRAME_MS)
                    length = notice_card.ENTRANCE_MS if step["card"] == "enter" else notice_card.EXIT_MS
                    self.assertGreaterEqual(step["frames"] * step["step"], length, "its motion is cut short")
                frames, delays, _end = make_motion.schedule(plan)
                entering = [delay for frame, delay in zip(frames, delays) if frame.card
                            and 0 <= frame.t - dict(frame.card)["born"] < notice_card.ENTRANCE_MS]
                self.assertTrue(entering and max(entering) <= notice_card.FRAME_MS)
                leaves = [dict(frame.card)["leave"] for frame in frames if frame.card and dict(frame.card)["leave"]]
                self.assertEqual(leaves[0], notice_card.HOLD_MS, "it stands as long as the product holds a card")


if __name__ == "__main__":
    unittest.main()
