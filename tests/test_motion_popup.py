"""The notification-area popup in the README's motion picture (build/motion_popup.py): opened, used and closed.

What the picture shows is only what the product does (ui/popup): the popup is there at once and gone at once (it has no
entrance); its light breathes on the clock of the state it shows, at the popup's own frame timer; its countdowns are
drawn again each second it is open; a press on a row's switch fades the switch while the answer is awaited, and the
answer makes it glide in brand's transition time on brand's curve. Drawn with Windows' GDI+, offscreen, in memory:
nothing is written and nothing is put on the screen.

The pictures themselves are the main session's (build/make_motion.py popup-en popup-ko); nothing here reads them
except for their sizes, which are the stills' - a picture drawn on one machine is not compared with another's fonts.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import make_motion  # noqa: E402
import motion_plan  # noqa: E402

PLANS = (("popup-en", "en", "docs/images/tray-popup-motion.png", "docs/images/tray-popup.png"),
         ("popup-ko", "ko", "docs/images/tray-popup-motion-ko.png", "docs/images/tray-popup-ko.png"))


def plan_of(name):
    return motion_plan.load(make_motion.plan_path(name))


def canvas_colour():
    from codex_auto_resume import brand
    return bytes(brand.rgb(brand.palette("light", brand.DEFAULT_DESIGN)["canvas"]))


class PopupPlanTests(unittest.TestCase):
    def test_the_popup_is_planned_in_both_languages_and_drawn_only_when_named_or_with_all(self):
        self.assertEqual(make_motion.POPUP_PLANS, ("popup-en", "popup-ko"))
        self.assertEqual(make_motion.ALL_PLANS, make_motion.PLAN_NAMES + make_motion.CARD_PLANS
                         + make_motion.POPUP_PLANS + make_motion.LOGO_PLANS)
        self.assertNotIn("popup-en", make_motion.PLAN_NAMES, "the README's two are drawn without them")

    def test_each_plan_writes_beside_the_card_s_and_leaves_the_still_to_the_screenshot_generator(self):
        import make_screenshots as shots
        for name, locale, output, still in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                self.assertEqual(plan["output"], output)
                self.assertNotEqual(plan["output"], still, "the still is make_screenshots', checked against its manifest")
                self.assertEqual(plan["popup"], {"scale": shots.POPUP_SCALE, "locale": locale, "still": still})
                for absent in ("window", "taskbar", "card"):
                    self.assertNotIn(absent, plan)
                self.assertIsNone(plan["pointer"], "nobody points: the switch is the popup's own")
                self.assertNotIn("transparent", plan["canvas"])
                self.assertEqual(plan["canvas"].get("theme"), shots.THEME)
                self.assertEqual(make_motion.icon_moments(plan, motion_plan.plan_end(plan)), [])

    def test_the_canvas_is_the_size_of_the_committed_still_and_the_budget_is_the_cards_ceiling(self):
        import make_screenshots as shots
        for name, _locale, _output, still in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                width, height = (int(part) for part in shots.dimensions(ROOT / still).split("x"))
                self.assertEqual(plan["canvas"]["size"], [width, height])
                self.assertEqual(plan["budget"], {"cap": 4000000}, "quality over size: a ceiling, no target")

    def test_the_picture_is_whole_breaths_long_so_it_loops_without_a_jump_in_the_light(self):
        from codex_auto_resume import brand
        for name, *_rest in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                end = motion_plan.plan_end(plan)
                self.assertEqual(end % brand.GLOW["waiting_ms"], 0)
                self.assertEqual(plan["length"], [end, end])

    def test_the_sequence_is_open_then_the_switch_off_then_on_then_closed(self):
        for name, *_rest in PLANS:
            with self.subTest(name):
                frames = motion_plan.expand(plan_of(name))
                first = dict(frames[0].popup)
                self.assertEqual((frames[0].t, first["opened"], first["off"], first["busy"]), (0, 0, (), ()),
                                 "frame 1 is the popup open and untouched, as a viewer that does not animate shows it")
                states = [(dict(frame.popup)["busy"], dict(frame.popup)["off"]) if frame.popup else None
                          for frame in frames]
                order = []
                for state in states:
                    if not order or order[-1] != state:
                        order.append(state)
                self.assertEqual(order, [((), ()), ((1,), ()), ((), (1,)), ((1,), (1,)), ((), ()), None])
                self.assertEqual(states[-1], None, "it ends closed, where it loops back to the open popup")

    def test_a_press_waits_then_the_answer_glides_the_switch_for_brand_s_transition_time(self):
        from codex_auto_resume import brand
        from codex_auto_resume.ui.popup import window
        for name, *_rest in PLANS:
            with self.subTest(name):
                plan = plan_of(name)
                steps = [step for scene in plan["scenes"] for step in scene["steps"]]
                for step in steps:
                    if "switch" in step:
                        self.assertEqual(step["step"], window.FRAME_MS, "the popup's frame timer")
                        self.assertGreaterEqual(step["frames"] * step["step"], brand.MOTION["transition_ms"],
                                                "the glide is cut short")
                        self.assertLess((step["frames"] - 1) * step["step"], brand.MOTION["transition_ms"],
                                        "and not held past its end")
                    if "ask" in step:
                        self.assertEqual(step["step"], window.FRAME_MS)
                self.assertEqual(plan["light_step_ms"], window.FRAME_MS)
                glides = [dict(frame.popup)["glides"] for frame in motion_plan.expand(plan) if frame.popup]
                self.assertTrue(any(glides))
                starts = {(row, glide) for case in glides for row, glide in case}
                self.assertEqual(sorted((glide[1], glide[2]) for _row, glide in starts), [(0.0, 1.0), (1.0, 0.0)])

    def test_every_frame_while_it_is_open_is_held_for_the_popup_s_own_frame_timer(self):
        from codex_auto_resume.ui.popup import window
        for name, *_rest in PLANS:
            with self.subTest(name):
                frames, delays, end = make_motion.schedule(plan_of(name))
                self.assertEqual({delay for frame, delay in zip(frames, delays) if frame.popup}, {window.FRAME_MS})
                self.assertEqual(sum(delays), end)

    def test_the_dry_run_counts_the_frames_and_writes_nothing(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(make_motion, "write_manifest") as written:
            self.assertEqual(make_motion.main(["popup-en", "--dry-run"]), 0)
        written.assert_not_called()
        self.assertIn("popup-en -> docs/images/tray-popup-motion.png", out.getvalue())
        self.assertIn("266 frames, 8.80 s", out.getvalue())


class PopupStepTests(unittest.TestCase):
    def plan(self, *steps):
        return {"format": "car-motion/1", "name": "t", "scenes": [{"id": "S", "steps": list(steps)}]}

    def test_a_press_or_an_answer_needs_an_open_popup_and_a_row_counted_from_one(self):
        for step in ({"ask": 1}, {"switch": 1, "to": "off"}):
            with self.subTest(step), self.assertRaises(motion_plan.PlanError):
                motion_plan.check(self.plan(step, {"hold": 100}))
        for row in (0, "1", True):
            with self.subTest(row), self.assertRaises(motion_plan.PlanError):
                motion_plan.check(self.plan({"popup": "open"}, {"ask": row}))

    def test_a_switch_goes_to_a_new_place_and_never_to_the_one_it_is_in(self):
        for steps in ([{"switch": 1, "to": "on"}], [{"switch": 1, "to": "off"}, {"switch": 1, "to": "off"}],
                      [{"switch": 1, "to": "maybe"}]):
            with self.subTest(steps), self.assertRaises(motion_plan.PlanError):
                motion_plan.check(self.plan({"popup": "open"}, *steps))

    def test_it_opens_and_closes_once_each_and_a_step_does_one_thing(self):
        for steps in ([{"popup": "open"}, {"popup": "open"}], [{"popup": "close"}], [{"popup": "slide"}],
                      [{"popup": "open", "ask": 1}]):
            with self.subTest(steps), self.assertRaises(motion_plan.PlanError):
                motion_plan.check(self.plan(*steps))

    def test_a_glide_that_is_over_is_let_go_and_the_row_stays_where_it_went(self):
        frames = motion_plan.expand(self.plan({"popup": "open", "hold": 100}, {"switch": 2, "to": "off", "frames": 5,
                                                                              "step": 33}, {"hold": 400}))
        late = dict(frames[-1].popup)
        self.assertEqual((late["off"], late["glides"]), ((2,), ()))
        self.assertTrue(dict(frames[1].popup)["glides"])


class PopupInputTests(unittest.TestCase):
    def test_what_the_picture_is_made_from_is_the_popup_and_the_sequence_and_not_the_window_or_the_card(self):
        import make_screenshots as shots
        plan = plan_of("popup-en")
        before = make_motion.render_input(plan)
        self.assertNotEqual(before, make_motion.render_input(plan_of("popup-ko")))
        with mock.patch.object(shots, "window_digest", return_value="moved"):
            self.assertEqual(make_motion.render_input(plan), before)
        with mock.patch.object(shots, "popup_drawing", return_value="moved"):
            self.assertNotEqual(make_motion.render_input(plan), before)
        real = shots.input_digest
        moved = ROOT / "build" / "motion_popup.py"
        with mock.patch.object(shots, "input_digest", side_effect=lambda p: "moved" if Path(p) == moved else real(p)):
            self.assertNotEqual(make_motion.render_input(plan), before)

    def test_the_other_pictures_are_not_made_from_the_popup(self):
        import make_screenshots as shots
        plan = plan_of("card-en")
        before = make_motion.render_input(plan)
        with mock.patch.object(shots, "popup_drawing", return_value="moved"):
            self.assertEqual(make_motion.render_input(plan), before)


@unittest.skipUnless(os.name == "nt", "the popup is drawn with Windows' GDI+")
class PopupDrawnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import motion_popup
        cls.motion_popup = motion_popup
        cls.plan = plan_of("popup-en")
        cls.frames, _delays, _end = make_motion.schedule(cls.plan)
        cls.width, cls.height = cls.plan["canvas"]["size"]
        cls.closed = canvas_colour() * (cls.width * cls.height)
        cls.popup = motion_popup.PopupFrames("en", scale=2.0)

    @classmethod
    def tearDownClass(cls):
        cls.popup.close()

    def at(self, t):
        return next(frame for frame in self.frames if frame.t == t)

    def draw(self, t):
        return self.popup.drawn(self.at(t), self.closed)

    def changed(self, one, other):
        """(left, top, right, bottom) of the pixels two pictures differ in, or None."""
        width = self.width
        rows = [y for y in range(self.height) if one[y * width * 3:(y + 1) * width * 3]
                != other[y * width * 3:(y + 1) * width * 3]]
        if not rows:
            return None
        columns = [x for y in rows for x in range(width) if one[(y * width + x) * 3:(y * width + x) * 3 + 3]
                   != other[(y * width + x) * 3:(y * width + x) * 3 + 3]]
        return min(columns), rows[0], max(columns) + 1, rows[-1] + 1

    def test_frame_one_is_the_popup_the_still_generator_draws(self):
        """Drawn here by both, on this machine: whatever its fonts, the motion starts from the still's own pixels."""
        import make_screenshots as shots
        with tempfile.TemporaryDirectory() as name:
            still = Path(name) / "still.png"
            shots.render_popup(still, "en")
            self.assertTrue(self.popup.is_the_still(self.frames[0], self.closed, still))
            other = Path(name) / "other.png"
            shots.render_popup(other, "ko")
            self.assertFalse(self.popup.is_the_still(self.frames[0], self.closed, other),
                             "a popup of another language is not the still")

    def test_it_is_there_at_once_and_gone_at_once_the_canvas_empty_before_and_after(self):
        shown, gone = self.draw(0), self.draw(8217)
        self.assertNotEqual(shown, self.closed)
        self.assertEqual(gone, self.closed)
        self.assertEqual(self.draw(8250), self.closed)

    def test_while_nothing_is_asked_only_the_light_moves_until_a_countdown_is_drawn_again(self):
        light = self.changed(self.draw(0), self.draw(990))
        self.assertIsNotNone(light)
        left, top, right, bottom = light
        self.assertLess(right - left, 120)
        self.assertLess(bottom - top, 120)
        later = self.changed(self.draw(990), self.draw(1023))
        self.assertIsNotNone(later)
        self.assertGreater(later[3] - later[1], bottom - top, "the second that passed redraws the counts and rows' words")

    def test_a_press_fades_the_first_switch_and_after_that_only_the_light_moves(self):
        plan = self.popup.view((), (1,), 2)[1]
        switch = next(item["rect"] for item in plan["items"] if item["kind"] == "switch")
        fade = self.changed(self.draw(2277), self.draw(2310))
        self.assertIsNotNone(fade)
        self.assertTrue(fade[0] <= switch[0] and switch[2] <= fade[2] and fade[1] <= switch[1]
                        and switch[3] <= fade[3], "the whole first switch is drawn faded")
        waiting = self.changed(self.draw(2310), self.draw(2343))
        self.assertTrue(waiting is None or waiting[2] - waiting[0] < 120, "while the answer is awaited, the light")

    def test_the_glide_is_the_product_s_amount_at_each_frame_and_ends_where_the_answer_put_the_switch(self):
        from codex_auto_resume import brand
        from codex_auto_resume.ui.popup.motion import glide_amount
        started = next(dict(frame.popup)["glides"][0][1][0] for frame in self.frames
                       if frame.popup and dict(frame.popup)["glides"])
        amounts = [glide_amount((started, 1.0, 0.0), started + index * 33)[0] for index in range(6)]
        self.assertEqual(amounts[0], 1.0)
        self.assertEqual(amounts[-1], 0.0)
        self.assertEqual(amounts, sorted(amounts, reverse=True))
        self.assertAlmostEqual(amounts[1], 1.0 - brand.ease(33 / float(brand.MOTION["transition_ms"])))
        rest = self.draw(started + 5 * 33)
        shifted = self.draw(started + 6 * 33)
        self.assertIsNotNone(self.changed(self.draw(started + 33), self.draw(started + 66)), "the knob is moving")
        box = self.changed(rest, shifted)
        self.assertTrue(box is None or box[2] - box[0] < 120, "after it, only the light and the clock move")

    def test_the_row_that_is_off_is_drawn_as_the_model_draws_it_and_the_light_stays_waiting(self):
        vm_on, _plan = self.popup.view((), (), 2)
        vm_off, _plan = self.popup.view((1,), (), 2)
        self.assertEqual(vm_on["light"], vm_off["light"], "turning one task off does not change the watcher's light")
        self.assertEqual((vm_on["tasks"][0]["checked"], vm_off["tasks"][0]["checked"]), (True, False))
        self.assertEqual(vm_on["tasks"][0]["tone"], "waiting")
        self.assertEqual(vm_off["tasks"][0]["tone"], "paused")
        self.assertEqual(vm_on["counts"], vm_off["counts"])
        self.assertEqual(vm_on["tasks"][1:], vm_off["tasks"][1:])


if __name__ == "__main__":
    unittest.main()
