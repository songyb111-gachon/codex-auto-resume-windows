"""v0.6.20 (the owner, 2026-10-29): four more scenes in the README's first motion picture.

On Pending the pointer presses Retry now - the header's light is the working one while the call is in flight - then
turns the wheel over Why it is waiting down to its last check, and presses Timeline: the dialog opens centred over the
window, holds, and its Close button closes it. Near the end the pointer presses Pause recovery - the light and the
words go to paused - and Resume recovery, and they go back.

The plan half (this module) holds the storyboard: the scenes, their order, the window states each one sets and the
frames those states land in, at the product's own cadence. The render half (tests/test_motion_window_scenes.py) runs
the window's render mode on them.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import make_motion  # noqa: E402
import motion_plan  # noqa: E402

PLANS = ("readme-en", "readme-ko")
# The tray's tick (Windows' 15.625 ms timer): the pointer is drawn no coarser, as in every motion picture.
POINTER_STEP = 16


def plan_of(name):
    return motion_plan.load(make_motion.plan_path(name))


def scene(plan, name):
    return next(item for item in plan["scenes"] if item["id"] == name)


def state(frame) -> dict:
    return motion_plan.thawed(frame.window)


def steps_of(plan, name, key):
    return [step for step in scene(plan, name)["steps"] if key in step]


class PlacementTests(unittest.TestCase):
    def test_the_new_scenes_are_where_they_read_naturally_in_both_pictures(self):
        for name in PLANS:
            with self.subTest(name):
                ids = [item["id"] for item in plan_of(name)["scenes"]]
                self.assertLess(ids.index("S1m"), ids.index("S2a"), "Retry now after the row menu, on Pending")
                self.assertEqual(ids[ids.index("S2a"):ids.index("S2a") + 3], ["S2a", "S2b", "S2c"])
                self.assertLess(ids.index("S2c"), ids.index("S5"), "all of them before History")
                self.assertEqual(ids[ids.index("S15") + 1:ids.index("S15") + 3], ["S15b", "S16"],
                                 "Pause and Resume on the Overview the picture ends on")

    def test_the_picture_is_longer_by_what_they_ask_and_its_range_says_so(self):
        for name in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                end = motion_plan.plan_end(plan)
                self.assertGreater(end, 40000)
                self.assertLessEqual(end, plan["length"][1])
                self.assertEqual(plan["length"], [25000, 48000])
                self.assertEqual(plan["budget"], {"cap": 9000000}, "the ceiling stays where it was")

    def test_the_first_frame_and_the_scenes_before_the_row_menu_are_as_they_were(self):
        for name in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                frames = motion_plan.expand(plan)
                self.assertEqual(frames[0].window, motion_plan._frozen({"page": "overview", "locale": "en" if
                                                                        name.endswith("en") else "ko"}))
                self.assertEqual(frames[0].t, 0)
                for key in ("busy", "variant", "dialog", "explain"):
                    self.assertNotIn(key, state(frames[0]))
                self.assertEqual([item["id"] for item in plan["scenes"]][:3], ["S0", "S1", "S1m"])


class RetryNowTests(unittest.TestCase):
    def test_the_pointer_presses_retry_now_and_the_call_is_in_flight_until_it_answers(self):
        for name in PLANS:
            with self.subTest(name):
                frames = motion_plan.expand(plan_of(name))
                pressed = [frame for frame in frames if state(frame).get("pressed") == "pending.retry"]
                self.assertTrue(pressed)
                self.assertTrue(all(frame.ripple and frame.ripple[0] == "pending.retry" for frame in pressed),
                                "a ripple where the pointer is")
                busy = [frame for frame in frames if state(frame).get("busy")]
                self.assertTrue(busy)
                self.assertGreaterEqual(busy[0].t, pressed[-1].t, "the call starts as the button is let go")
                self.assertEqual({state(frame)["page"] for frame in busy} - {"pending", "overview"}, set())
                self.assertEqual(busy[0].pointer, ("at", "pending.retry"), "the pointer stays on the button")

    def test_the_light_is_worked_for_exactly_the_frames_the_call_lasts_and_goes_back(self):
        for name in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                frames, delays, _end = make_motion.schedule(plan)
                first = [frame for frame in frames if state(frame).get("busy")
                         and state(frame).get("page") == "pending"]
                held = sum(delay for frame, delay in zip(frames, delays)
                           if frame in first)
                self.assertGreaterEqual(held, 1000, "long enough for the working light to be seen turning")
                after = frames[frames.index(first[-1]) + 1]
                self.assertNotIn("busy", state(after))
                self.assertEqual(state(after)["page"], "pending")
                self.assertNotIn("busy", state(frames[0]))


class ExplainTests(unittest.TestCase):
    def test_the_wheel_turns_over_why_it_is_waiting_with_the_pointer_on_it(self):
        from codex_auto_resume import brand  # noqa: F401 - the product's palette is the same import the plan uses
        for name in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                moves = steps_of(plan, "S2b", "move")
                self.assertEqual(moves[0]["move"], "pending.explain")
                wheels = steps_of(plan, "S2b", "wheel")
                self.assertEqual({step["on"] for step in wheels}, {"explain"})
                for step in wheels:
                    self.assertEqual(step["step"], 15, "SoftBar.GlideInterval, as Settings' own scroll in S9")
                    self.assertEqual(step["frames"], 12)
                frames = motion_plan.expand(plan)
                gliding = [state(frame)["explain"] for frame in frames if "explain" in state(frame)]
                self.assertEqual(gliding[0]["notches"], 1)
                self.assertEqual(gliding[-1], {"notches": len(wheels)}, "settled where the last turn ended")
                self.assertNotIn("scroll", state(frames[-1]), "the page itself never scrolls for it")
                turning = [frame for frame in frames if "glide_ms" in state(frame).get("explain", {})]
                self.assertTrue(turning)
                self.assertTrue(all(frame.pointer == ("at", "pending.explain") for frame in turning),
                                "the pointer is over it for every turn")

    def test_a_wheel_says_only_what_it_is_over_when_it_is_over_that(self):
        base = {"format": motion_plan.FORMAT, "name": "t", "locale": "en", "canvas": {"theme": "light"}}
        for step in ({"wheel": 1, "on": "page"}, {"hold": 100, "on": "explain"}, {"move": "save", "on": "explain"}):
            with self.subTest(step), self.assertRaises(motion_plan.PlanError):
                motion_plan.check(dict(base, scenes=[{"id": "A", "steps": [step]}]))

    def test_it_leaves_the_checks_where_they_stand_until_another_page(self):
        frames = motion_plan.expand(plan_of("readme-en"))
        shown = [index for index, frame in enumerate(frames) if "explain" in state(frame)]
        self.assertEqual({state(frames[index])["page"] for index in shown}, {"pending"})
        history = next(index for index, frame in enumerate(frames) if state(frame)["page"] == "history")
        self.assertGreater(history, shown[-1])
        self.assertNotIn("explain", state(frames[history]), "another page starts with its checks at the top")


class TimelineTests(unittest.TestCase):
    def test_the_pointer_presses_timeline_the_dialog_opens_holds_and_its_close_button_closes_it(self):
        for name in PLANS:
            with self.subTest(name):
                frames = motion_plan.expand(plan_of(name))
                opened = [index for index, frame in enumerate(frames) if "dialog" in state(frame)]
                self.assertTrue(opened)
                first, last = opened[0], opened[-1]
                self.assertEqual(opened, list(range(first, last + 1)), "one stretch, no other dialog")
                self.assertEqual(state(frames[first])["dialog"], {"kind": "timeline"})
                before = [state(frame) for frame in frames[:first] if state(frame).get("pressed") == "pending.timeline"]
                self.assertTrue(before, "opened by a press on Timeline")
                self.assertNotIn("dialog", state(frames[0]))
                closing = [frame for frame in frames[first:last + 1] if state(frame).get("pressed") == "dialog.close"]
                self.assertTrue(closing, "closed by a press on its Close button")
                self.assertEqual(closing[-1].pointer, ("at", "dialog.close"))
                self.assertNotIn("dialog", state(frames[last + 1]), "gone as the button is let go")
                held = [frame for frame in frames[first:last + 1] if frame.pointer[0] == "at"
                        and not state(frame).get("hover")]
                self.assertTrue(held, "it holds before the pointer goes to Close")
                hovered = [state(frame).get("hover") for frame in frames[first:last + 1]]
                self.assertIn("dialog.close", hovered)
                self.assertLess(frames[first].t, closing[0].t)

    def test_the_dialog_is_asked_for_over_pending_or_history_and_only_the_timeline(self):
        base = {"format": motion_plan.FORMAT, "name": "t", "locale": "en", "canvas": {"theme": "light"}}
        for dialog in ({"kind": "log"}, {"kind": "timeline", "list": "settings"}, "timeline"):
            with self.subTest(dialog), self.assertRaises(motion_plan.PlanError):
                motion_plan.check(dict(base, scenes=[{"id": "A", "steps": [{"set": {"dialog": dialog}, "hold": 100}]}]))
        motion_plan.check(dict(base, scenes=[{"id": "A", "steps": [
            {"set": {"dialog": {"kind": "timeline", "list": "history"}}, "hold": 100}]}]))


class PauseTests(unittest.TestCase):
    def test_pause_then_resume_from_the_overview_each_a_press_a_call_in_flight_and_an_answer(self):
        for name in PLANS:
            with self.subTest(name):
                frames = motion_plan.expand(plan_of(name))
                toggled = [(state(frame).get("variant"), state(frame).get("busy"), state(frame).get("pressed"))
                           for frame in frames if state(frame).get("page") == "overview"
                           and any(key in state(frame) for key in ("variant", "busy", "pressed"))
                           and frame.t > 30000]
                kinds = []
                for variant, busy, pressed in toggled:
                    kind = ("paused " if variant else "") + ("busy" if busy else "pressed" if pressed else "answered")
                    if not kinds or kinds[-1] != kind:
                        kinds.append(kind)
                self.assertEqual(kinds, ["pressed", "busy", "paused answered", "paused pressed", "paused busy"])
                last = frames[-1]
                self.assertNotIn("variant", state(last), "and back: the picture ends on a running watcher")
                self.assertNotIn("busy", state(last))
                self.assertEqual(state(last)["page"], "overview")

    def test_both_stay_in_the_language_the_picture_is_in_at_the_end(self):
        for name, second in (("readme-en", "ko"), ("readme-ko", "en")):
            with self.subTest(name):
                frames = motion_plan.expand(plan_of(name))
                paused = [frame for frame in frames if state(frame).get("variant") == "paused"]
                self.assertTrue(paused)
                self.assertEqual({state(frame)["locale"] for frame in paused}, {second})
                plan = plan_of(name)
                self.assertEqual(plan["variants"], ["paused"])

    def test_the_toggle_is_pressed_twice_with_the_cadence_of_every_other_click(self):
        for name in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                for step in scene(plan, "S15b")["steps"]:
                    for key in ("move", "hover", "press"):
                        if key in step:
                            self.assertEqual(step[key], "overview.toggle")
                            self.assertLessEqual(step["step"], POINTER_STEP)
                self.assertEqual(len(steps_of(plan, "S15b", "press")), 2)

    def test_a_state_of_the_installation_the_window_does_not_have_is_refused(self):
        base = {"format": motion_plan.FORMAT, "name": "t", "locale": "en", "canvas": {"theme": "light"}}
        for state_ in ({"variant": "offline"}, {"busy": False}, {"busy": 1}):
            with self.subTest(state_), self.assertRaises(motion_plan.PlanError):
                motion_plan.check(dict(base, scenes=[{"id": "A", "steps": [{"set": state_, "hold": 100}]}]))


class LightTickTests(unittest.TestCase):
    def test_a_frame_between_two_ticks_of_the_lights_timer_shows_the_light_as_the_last_tick_left_it(self):
        """The window's light moves on its own timer (HaloDot, 33 ms), not with a glide or the pointer: a frame the
        pointer draws between two ticks does not move it - nor the bytes of a picture round it and the pointer."""
        import motion_window
        for name in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                frames, _delays, _end = make_motion.schedule(plan)
                job = motion_window.job(plan, frames, Path("out"), forms={"en": {"answers": []}, "ko": {"answers": []}})
                step = plan["light_step_ms"]
                lights = [frame["light"] for frame in job["frames"]]
                self.assertEqual(lights[0], 0)
                for frame, light in zip(frames, lights):
                    self.assertEqual(light, (frame.t // step) * step)
                    self.assertLessEqual(light, frame.t)
                    self.assertLess(frame.t - light, step)
                self.assertTrue(any(frame.t != light for frame, light in zip(frames, lights)), "some frames are between ticks")
                self.assertEqual(lights, sorted(lights), "the light never goes back")


class CadenceTests(unittest.TestCase):
    def test_every_new_move_hover_and_press_is_at_the_pointer_s_cadence_and_the_light_at_the_windows(self):
        for name in PLANS:
            plan = plan_of(name)
            self.assertEqual(plan["light_step_ms"], 33)
            self.assertEqual(plan["ripple_step"], 16)
            for scene_id in ("S2a", "S2b", "S2c", "S15b"):
                for step in scene(plan, scene_id)["steps"]:
                    for key in ("move", "hover", "press"):
                        if key in step:
                            self.assertLessEqual(step["step"], POINTER_STEP, (scene_id, step))

    def test_no_frame_is_thinned_every_stretch_keeps_the_lights_own_frames(self):
        for name in PLANS:
            frames, delays, end = make_motion.schedule(plan_of(name))
            self.assertEqual(sum(delays), end)
            holding = [delay for frame, delay in zip(frames, delays)
                       if frame.pointer[0] == "at" and not frame.ripple]
            self.assertLessEqual(max(holding), 66, "a light frame every 33 ms wherever nothing else moves")


if __name__ == "__main__":
    unittest.main()
