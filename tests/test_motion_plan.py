"""The frame plan of the README's motion pictures (build/motion_plan.py) and its runner (build/make_motion.py).

A plan says what a person does, scene by scene, and nothing else: these hold the steps to the frames they emit, the
checks to the plans they refuse, the clock to the frames the lights and ripples add and the delays browsers keep, and
the runner to writing a picture once however long it holds. Pure Python: nothing is drawn.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import make_motion  # noqa: E402
import motion_compose  # noqa: E402
import motion_plan  # noqa: E402
from motion_plan import PlanError  # noqa: E402


def plan_of(*steps, **extra) -> dict:
    """A one-scene plan of `steps`, checked as a plan file is."""
    plan = dict({"format": motion_plan.FORMAT, "name": "test", "locale": "en", "pointer": {"rest": [10, 20]},
                 "scenes": [{"id": "A", "steps": list(steps)}]}, **extra)
    motion_plan.check(plan)
    return plan


def state(frame) -> dict:
    return motion_plan.thawed(frame.window)


class ReadmePlanTests(unittest.TestCase):
    def test_both_readme_plans_load_and_last_as_the_storyboard_says(self):
        for name in make_motion.PLAN_NAMES:
            with self.subTest(name):
                plan = motion_plan.load(make_motion.plan_path(name))
                end = motion_plan.plan_end(plan)
                self.assertTrue(25000 <= end <= 35000, end)
                frames = motion_plan.expand(plan)
                self.assertEqual(frames[0].t, 0)
                self.assertEqual(state(frames[0]), {"page": "overview", "locale": plan["locale"]},
                                 "frame 1 is the Overview at rest: the still a browser without APNG shows")
                self.assertEqual(frames[0].card, ())

    def test_each_readme_ends_in_the_other_language_on_the_overview(self):
        for name, first, second in (("readme-en", "en", "ko"), ("readme-ko", "ko", "en")):
            with self.subTest(name):
                plan = motion_plan.load(make_motion.plan_path(name))
                frames = motion_plan.expand(plan)
                self.assertEqual(state(frames[-1]), {"page": "overview", "locale": second})
                self.assertIn(("combo", (("interface_language", second),)),
                              [item for frame in frames for item in frame.window],
                              "the language is chosen in the drop list before Save")
                self.assertEqual(plan["forms"][second], {"interface_language": second},
                                 "the window that opens after Save has the language stored")

    def test_the_readme_pictures_are_the_dashboard_alone_on_a_clear_canvas(self):
        """The owner, 2026-10-18: the first motion picture holds the Dashboard only - no notification card, no
        taskbar - and everything outside the window is transparent; it opens on the Overview and clicks Pending."""
        for name in make_motion.PLAN_NAMES:
            with self.subTest(name):
                plan = motion_plan.load(make_motion.plan_path(name))
                self.assertNotIn("card", plan)
                self.assertNotIn("taskbar", plan)
                self.assertIs(plan["canvas"].get("transparent"), True)
                frames = motion_plan.expand(plan)
                self.assertTrue(all(frame.card == () for frame in frames))
                self.assertFalse([target for target in motion_plan.pointer_targets(frames)
                                  if target.startswith("card.")])
                pages = [state(frame)["page"] for frame in frames]
                self.assertEqual(pages[0], "overview")
                self.assertEqual(next(page for page in pages if page != "overview"), "pending")

    def test_the_readme_pictures_are_exactly_the_bare_window(self):
        """The owner, 2026-10-19: the caption stood too far from the picture, first for an empty margin round the
        window, then for its drop shadow, which a dark page does not show. The canvas is the window itself, 1500x1041
        like the still window pictures, with no shadow, and the pointer rests on it."""
        import make_screenshots as shots
        still = shots.read_png(ROOT / "assets" / "screenshot-dashboard.png")
        for name in make_motion.PLAN_NAMES:
            with self.subTest(name):
                plan = motion_plan.load(make_motion.plan_path(name))
                width, height = plan["canvas"]["size"]
                self.assertEqual((width, height), (still[0], still[1]))
                self.assertEqual(plan["window"]["at"], [0, 0])
                self.assertIs(plan["canvas"].get("shadow"), False)
                chrome = motion_compose.WindowChrome(still, (still[0], still[1] - 1), size=(width, height),
                                                     at=tuple(plan["window"]["at"]), ground=None, scale=1.5,
                                                     shadow=False)
                self.assertEqual(chrome.empty_border(), (0, 0, 0, 0))
                x, y = plan["pointer"]["rest"]
                self.assertTrue(0 <= x < width and 0 <= y < height)

class CardPlanTests(unittest.TestCase):
    def test_the_card_on_its_own_is_planned_in_both_languages_and_drawn_only_when_named(self):
        self.assertEqual(make_motion.CARD_PLANS, ("card-en", "card-ko"))
        self.assertEqual(make_motion.ALL_PLANS,
                         make_motion.PLAN_NAMES + make_motion.CARD_PLANS + make_motion.POPUP_PLANS
                         + make_motion.LOGO_PLANS)
        for name, output in (("card-en", "docs/images/notification-card-motion.png"),
                             ("card-ko", "docs/images/notification-card-motion-ko.png")):
            with self.subTest(name):
                plan = motion_plan.load(make_motion.plan_path(name))
                self.assertEqual(plan["output"], output)
                self.assertNotIn("window", plan)
                self.assertNotIn("taskbar", plan)
                self.assertEqual((plan["canvas"]["size"], plan["card"]["scale"]),
                                 ([776, {"card-en": 540, "card-ko": 524}[name]], 2.0))
                self.assertLessEqual(plan["budget"]["cap"], 4000000)
                frames = motion_plan.expand(plan)
                from codex_auto_resume import notice_card
                self.assertEqual(dict(frames[0].card)["born"], -notice_card.ENTRANCE_MS,
                                 "frame 1 is the card at rest, as a viewer that does not animate shows it")
                self.assertIsNone(plan["pointer"], "nobody points: it is the popup appearing on its own")
                cards = [dict(frame.card) if frame.card else None for frame in frames]
                self.assertIn(None, cards, "it leaves, the product's own exit")
                gone = cards.index(None)
                self.assertTrue(any(card and card["born"] > 0 for card in cards[gone:]), "and comes again")
                self.assertIsNotNone(cards[-1], "it ends at rest, where it loops back to")
                self.assertEqual(make_motion.icon_moments(plan, motion_plan.plan_end(plan)), [])

    def test_what_the_card_picture_is_made_from_is_the_card_not_the_window(self):
        import make_screenshots as shots
        from unittest import mock
        plan = motion_plan.load(make_motion.plan_path("card-en"))
        before = make_motion.render_input(plan)
        with mock.patch.object(shots, "window_digest", return_value="moved"):
            self.assertEqual(make_motion.render_input(plan), before)
        with mock.patch.object(shots, "card_drawing", return_value="moved"):
            self.assertNotEqual(make_motion.render_input(plan), before)


class StepTests(unittest.TestCase):
    def test_a_cut_changes_the_window_at_once_and_leaves_the_section_with_its_page(self):
        frames = motion_plan.expand(plan_of({"set": {"page": "settings", "section": "general"}, "hold": 100},
                                            {"set": {"page": "pending"}, "hold": 100}))
        self.assertEqual([frame.t for frame in frames], [0, 100])
        self.assertEqual(state(frames[0])["section"], "general")
        self.assertNotIn("section", state(frames[1]))

    def test_a_move_is_eased_from_where_the_pointer_was_to_its_target(self):
        frames = motion_plan.expand(plan_of({"move": "save", "frames": 5, "step": 40}, {"hold": 100}))
        moving = frames[:5]
        self.assertEqual([frame.pointer[0] for frame in moving], ["move"] * 5)
        self.assertEqual(moving[0].pointer[1], (("at", (10, 20)),))
        self.assertEqual([frame.pointer[3] for frame in (moving[0], moving[-1])], [0.0, 1.0])
        fractions = [frame.pointer[3] for frame in moving]
        self.assertEqual(fractions, sorted(fractions))
        self.assertAlmostEqual(fractions[2], motion_plan.ease(0.5), places=6)
        self.assertEqual(frames[5].pointer, ("at", "save"))

    def test_a_move_by_is_measured_from_where_the_pointer_stood(self):
        frames = motion_plan.expand(plan_of({"move": "save", "frames": 1}, {"move": {"by": [-60, 0]}, "frames": 3},
                                            {"hold": 40}))
        self.assertEqual(frames[-1].pointer, ("at", (("by", (-60, 0)), ("from", "save"))))

    def test_a_press_shows_its_face_and_a_ripple_where_the_pointer_is_then_lets_go(self):
        frames = motion_plan.expand(plan_of({"move": "page.history", "frames": 2}, {"press": "page.history", "frames": 3},
                                            {"hold": 40}))
        pressed = [state(frame).get("pressed") for frame in frames]
        self.assertEqual(pressed, [None, None, "page.history", "page.history", "page.history", None])
        self.assertEqual(frames[2].ripple, ("page.history", 80))
        self.assertEqual(frames[-1].ripple, ("page.history", 80), "the ripple fades on after the press")
        self.assertIsNone(motion_plan.ripple_at(frames[-1]._replace(t=80 + motion_plan.RIPPLE_MS)))
        radius, opacity = motion_plan.ripple_at(frames[2])
        self.assertEqual((radius, opacity), (0.0, 1.0))

    def test_the_card_is_born_leaves_and_is_gone(self):
        frames = motion_plan.expand(plan_of({"card": "enter", "frames": 3, "step": 40}, {"hover": "card.open"},
                                            {"card": "leave", "frames": 2, "step": 40}, {"hold": 40}))
        cards = [dict(frame.card) if frame.card else None for frame in frames]
        self.assertEqual(cards[0], {"born": 0, "hover": None, "pressed": None, "leave": None})
        self.assertEqual(cards[3]["hover"], "open")
        self.assertEqual(cards[4]["leave"], 320)
        self.assertIsNone(cards[-1])

    def test_a_wheel_glides_and_settles(self):
        frames = motion_plan.expand(plan_of({"set": {"page": "settings"}}, {"wheel": 1, "frames": 3},
                                            {"wheel": 1, "frames": 2}, {"hold": 100}))
        scrolls = [state(frame).get("scroll") for frame in frames]
        self.assertEqual(scrolls, [None, {"notches": 1, "glide_ms": 0}, {"notches": 1, "glide_ms": 40},
                                   {"notches": 1, "glide_ms": 80}, {"notches": 2, "glide_ms": 0},
                                   {"notches": 2, "glide_ms": 40}, {"notches": 2}])

    def test_a_drop_list_opens_walks_its_rows_and_closes_on_a_choice(self):
        frames = motion_plan.expand(plan_of({"set": {"page": "settings"}}, {"open": "setting.interface_language"},
                                            {"rows": ["system", "en", "ko"], "step": 80}, {"choose": "ko"}))
        lists = [state(frame).get("droplist") for frame in frames]
        self.assertEqual(lists[1], {"field": "interface_language", "hover": None})
        self.assertEqual([item["hover"] for item in lists[2:5]], ["system", "en", "ko"])
        self.assertEqual([frame.pointer for frame in frames[2:5]], [("at", "row.system"), ("at", "row.en"),
                                                                   ("at", "row.ko")])
        self.assertIsNone(lists[5])
        self.assertEqual(state(frames[5])["combo"], {"interface_language": "ko"})

    def test_a_later_state_at_the_same_moment_is_the_one_shown(self):
        frames = motion_plan.expand(plan_of({"card": "enter", "frames": 1}, {"set": {"page": "pending"}, "hold": 0},
                                            {"card": "leave", "frames": 1}))
        self.assertEqual([frame.t for frame in frames], [0, 40])
        self.assertEqual(state(frames[1])["page"], "pending")
        self.assertEqual(dict(frames[1].card)["leave"], 40)


class CheckTests(unittest.TestCase):
    def refused(self, *steps, **extra):
        with self.assertRaises(PlanError) as caught:
            plan_of(*steps, **extra)
        return str(caught.exception)

    def test_it_refuses_what_the_window_cannot_draw(self):
        self.assertIn("no state", self.refused({"set": {"zoom": 2}}))
        self.assertIn("no page", self.refused({"set": {"page": "chat"}}))
        self.assertIn("no section", self.refused({"set": {"page": "settings", "section": "secret"}}))
        self.assertIn("nothing called", self.refused({"move": "the big button"}))
        self.assertIn("nothing called", self.refused({"hover": "page.chat"}))
        self.assertIn("one thing", self.refused({"move": "save", "hover": "save"}))
        self.assertIn("one thing", self.refused({"move": "save", "hold": 40}))
        self.assertIn("no step has", self.refused({"hold": 40, "fade": 1}))
        self.assertIn("at least one frame", self.refused({"move": "save", "frames": 0}))
        self.assertIn("shorter than a browser", self.refused({"move": "save", "step": 10}))

    def test_it_refuses_a_picture_outside_its_length(self):
        self.assertIn("long", self.refused({"hold": 1000}, length=[2000, 3000]))
        plan_of({"hold": 2500}, length=[2000, 3000])

    def test_it_refuses_a_value_the_plan_does_not_give(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "p.json"
            path.write_text(json.dumps({"format": motion_plan.FORMAT, "scenes": [{"id": "A", "steps": [
                {"set": {"locale": "${second}"}}]}]}), encoding="utf-8")
            with self.assertRaises(PlanError):
                motion_plan.load(path)

    def test_a_whole_value_keeps_its_kind_and_a_part_of_a_string_is_text(self):
        values = {"rows": ["system", "en"], "second": "ko"}
        self.assertEqual(motion_plan._substitute({"rows": "${rows}", "x": "to ${second}"}, values),
                         {"rows": ["system", "en"], "x": "to ko"})


class ClockTests(unittest.TestCase):
    def test_the_lights_add_a_frame_every_step_of_their_own_timer_after_frame_one_holds(self):
        frames = motion_plan.expand(plan_of({"hold": 1000}))
        filled = motion_plan.fill(frames, 1000, 100, first_hold=400)
        self.assertEqual([frame.t for frame in filled], [0, 400, 500, 600, 700, 800, 900])
        self.assertTrue(all(frame.window == frames[0].window for frame in filled))

    def test_a_ripple_gets_a_frame_every_step_while_it_fades_and_the_icon_its_own(self):
        frames = motion_plan.expand(plan_of({"press": "save", "frames": 1}, {"set": {"page": "pending"}, "hold": 500}))
        filled = motion_plan.fill(frames, 540, 0, also=(333,), ripple_step=40)
        self.assertEqual([frame.t for frame in filled], [0, 40, 80, 120, 160, 200, 333])
        self.assertEqual(state(filled[-1])["page"], "pending")

    def test_a_moment_too_close_to_another_adds_no_frame(self):
        frames = motion_plan.expand(plan_of({"hold": 300}, {"set": {"page": "pending"}, "hold": 300}))
        filled = motion_plan.fill(frames, 600, 100, also=(108, 150, 290, 595))
        self.assertEqual([frame.t for frame in filled], [0, 100, 150, 200, 300, 400, 500])
        self.assertTrue(all(b.t - a.t >= motion_plan.CLOSEST for a, b in zip(filled, filled[1:])))
        motion_plan.delays([frame.t for frame in filled], 600)
        readme = motion_plan.load(make_motion.plan_path("readme-en"))
        icon = [1092.0 + 1.37 * n for n in range(0, 20000, 7)]
        make_motion.schedule(readme, icon)

    def test_delays_are_whole_milliseconds_that_sum_to_the_picture(self):
        self.assertEqual(motion_plan.delays([0, 16, 32, 120], 1000), [16, 16, 88, 880])
        self.assertEqual(motion_plan.SHORTEST, 15, "the product's own quickest step")
        with self.assertRaises(PlanError):
            motion_plan.delays([0, 10], 100)


class RunnerTests(unittest.TestCase):
    def test_a_picture_that_holds_is_written_once_for_as_long_as_it_holds(self):
        plan = plan_of({"hold": 300}, {"set": {"page": "pending"}, "hold": 300}, {"set": {"page": "overview"},
                                                                                 "hold": 200},
                       light_step_ms=100)
        drawn = list(make_motion.run(plan, lambda frame: state(frame)["page"].encode()))
        self.assertEqual([(delay, picture) for delay, _scene, picture in drawn],
                         [(300, b"overview"), (300, b"pending"), (200, b"overview")])

    def test_the_dry_run_names_every_scene(self):
        text = make_motion.describe(motion_plan.load(make_motion.plan_path("readme-en")))
        for scene in ("S0", "S9", "S12b", "S16"):
            self.assertIn(scene, text)


if __name__ == "__main__":
    unittest.main()
