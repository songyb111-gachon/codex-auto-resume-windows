"""v0.6.18: the README's first motion picture opens a Pending row's own menu (the owner: "첫 apng에 우클릭 장면도
추가해줘" - add a right-click scene to the first APNG).

After the Pending page opens, the pointer goes to the first waiting task, right-clicks it - the row is chosen, a ripple
where the pointer is - and the row's menu opens there, drawn by its own card as the product draws it (SoftMenu,
gui/SoftMenu.cs). The pointer goes down over two items, each in hand in turn, holds on the second, and the menu closes
with nothing chosen; the picture goes on to History as before.

The plan half holds the new steps (`right`, `dismiss`, a hover on `menu.<n>`) and the storyboard; the render half runs
the window's render mode on a small job of the real window - offscreen, nothing shown, nothing captured - and holds
the menu to where it opens, what it names and what it draws.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
import make_motion  # noqa: E402
import motion_plan  # noqa: E402
import motion_window  # noqa: E402


def state(frame) -> dict:
    return motion_plan.thawed(frame.window)


def plan_of(steps) -> dict:
    plan = {"format": motion_plan.FORMAT, "name": "t", "locale": "en", "canvas": {"theme": "light"},
            "scenes": [{"id": "A", "steps": steps}]}
    motion_plan.check(plan)
    return plan


class StepTests(unittest.TestCase):
    STEPS = [{"set": {"page": "pending"}, "hold": 100}, {"move": "task.0", "frames": 2, "step": 16},
             {"right": "task.0", "frames": 3, "step": 16, "hold": 200}, {"move": "menu.4", "frames": 2, "step": 16},
             {"hover": "menu.4", "frames": 2, "step": 16}, {"move": "menu.5", "frames": 2, "step": 16},
             {"hover": "menu.5", "frames": 2, "step": 16}, {"hold": 300}, {"dismiss": "menu", "hold": 100}]

    def setUp(self):
        self.frames = motion_plan.expand(plan_of(self.STEPS))

    def test_a_right_click_chooses_the_row_with_a_ripple_then_opens_its_menu_there(self):
        pressed = [frame for frame in self.frames if frame.ripple]
        self.assertTrue(pressed, "a right click shows a ripple")
        first = pressed[0]
        self.assertEqual(first.ripple[0], "task.0", "the ripple is where the pointer stands, on the row")
        self.assertEqual(state(first)["selected"], {"pending": 0}, "the row under the pointer is chosen")
        self.assertNotIn("menu", state(first), "the menu opens as the button is let go, not as it is pressed")
        opened = [frame for frame in self.frames if "menu" in state(frame)]
        self.assertEqual(state(opened[0])["menu"], {"at": "task.0"})
        self.assertEqual(opened[0].t, first.t + 3 * 16)
        self.assertEqual(opened[0].pointer, ("at", "task.0"))

    def test_a_hover_in_the_menu_names_the_item_in_hand(self):
        hovered = [state(frame).get("hover") for frame in self.frames if "menu" in state(frame)]
        self.assertIn("menu.4", hovered)
        self.assertIn("menu.5", hovered)
        self.assertLess(hovered.index("menu.4"), hovered.index("menu.5"), "down the menu, one item after the other")

    def test_dismissing_closes_the_menu_with_nothing_chosen_and_the_row_stays_chosen(self):
        last = state(self.frames[-1])
        self.assertNotIn("menu", last)
        self.assertNotIn("hover", last, "no item stays in hand once the menu is gone")
        self.assertEqual(last["selected"], {"pending": 0}, "a closed menu leaves its row chosen, as the list does")
        self.assertEqual(last["page"], "pending")
        self.assertNotIn("combo", last)

    def test_it_refuses_a_menu_it_cannot_draw(self):
        for steps in ([{"right": "page.pending"}], [{"dismiss": "menu"}], [{"hover": "menu.2"}],
                      [{"right": "task.0"}, {"press": "menu.2"}], [{"dismiss": "list"}], [{"right": "task.x"}]):
            with self.subTest(steps):
                with self.assertRaises(motion_plan.PlanError):
                    plan_of(steps)

    def test_the_targets_are_named_for_the_window(self):
        self.assertIn("menu.4", motion_plan.pointer_targets(self.frames))
        self.assertIn("task.0", motion_plan.pointer_targets(self.frames))
        self.assertIn("menu", motion_plan.STATE_KEYS)
        self.assertIn("selected", motion_plan.STATE_KEYS)


class StoryboardTests(unittest.TestCase):
    def test_the_first_picture_opens_the_row_menu_after_pending_and_before_history(self):
        for name in make_motion.PLAN_NAMES:
            with self.subTest(name):
                plan = motion_plan.load(make_motion.plan_path(name))
                ids = [scene["id"] for scene in plan["scenes"]]
                self.assertEqual(ids[ids.index("S1") + 1:ids.index("S1") + 3], ["S1m", "S5"])
                steps = plan["scenes"][ids.index("S1m")]["steps"]
                self.assertEqual([next(key for key in step if key in motion_plan.STEPS) for step in steps],
                                 ["move", "right", "move", "hover", "hold", "move", "hover", "hold", "dismiss"])
                self.assertEqual(steps[1]["right"], "task.0", "the first waiting task")
                hovers = [step["hover"] for step in steps if "hover" in step]
                self.assertEqual(hovers, ["menu.4", "menu.5"], "two items, one under the other")
                # The second item held about 1.2 s: its hover's frames and the hold after it.
                held = steps[6]["frames"] * steps[6]["step"] + steps[7]["hold"]
                self.assertGreaterEqual(held, 1150)
                self.assertLessEqual(held, 1300)
                frames = motion_plan.expand(plan)
                menu = [frame for frame in frames if frame.scene == "S1m" and "menu" in state(frame)]
                self.assertTrue(menu)
                self.assertTrue(all(state(frame)["page"] == "pending" for frame in menu))
                after = [frame for frame in frames if frame.scene == "S5" and state(frame)["page"] == "history"]
                self.assertNotIn("menu", state(after[0]), "History opens with the menu closed")
                self.assertNotIn("selected", state(after[0]), "the chosen row stays on Pending")

    def test_the_moves_keep_the_storyboard_s_frame_rate(self):
        plan = motion_plan.load(make_motion.plan_path("readme-en"))
        steps = plan["scenes"][[scene["id"] for scene in plan["scenes"]].index("S1m")]["steps"]
        for step in steps:
            if "move" in step or "hover" in step or "right" in step:
                with self.subTest(step):
                    self.assertEqual(step["step"], 16, "every pointer step at the picture's 16 ms, as the others")


class SourceTests(unittest.TestCase):
    def test_the_render_mode_draws_the_menu_by_its_own_card(self):
        render = guiscan.member_body("SettingsForm", "RenderMenu")
        self.assertIn("FillRowMenu(", render, "filled as the menu's Opening fills it")
        self.assertIn("SoftMenuLayer layer = pendingMenu.Layer;", render)
        self.assertIn("layer.Render();", render)
        self.assertIn('RenderMenu(picture, Str(menu, "at"), Str(frame, "hover"), writer);',
                      guiscan.member_body("SettingsForm", "RenderPicture"))
        self.assertIn('RenderSelected(Map(frame, "selected"))', guiscan.member_body("SettingsForm", "RenderState"))


class RenderTests(unittest.TestCase):
    """One small job of the real window, offscreen: the Pending page, its first row's menu open, and closed again."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = motion_window.compile_window(work)
        frames = [{"index": 0, "locale": "en", "page": "pending", "light": 0},
                  {"index": 1, "locale": "en", "page": "pending", "light": 0, "selected": {"pending": 0},
                   "menu": {"at": "task.0"}},
                  {"index": 2, "locale": "en", "page": "pending", "light": 0, "selected": {"pending": 0},
                   "menu": {"at": "task.0"}, "hover": "menu.4"},
                  {"index": 3, "locale": "en", "page": "pending", "light": 0, "selected": {"pending": 1}}]
        job = {"out": str(work / "out"), "theme": "light", "design": "soft",
               "forms": {"en": {"answers": motion_window.answers("en")}},
               "targets": ["task.0", "task.1", "menu.0", "menu.4", "menu.5"], "frames": frames}
        cls.result = motion_window.render(exe, job, work)
        cls.pictures = list(motion_window.pictures(cls.result, work / "out"))
        cls.place = cls.run_place(work, exe)

    @classmethod
    def run_place(cls, work, exe):
        from test_gui_v0611_access import run_probe
        script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
$place = $assembly.GetType('CodexAutoResume.SettingsForm', $true).GetMethod('RenderMenuPlace', $flags)
$reach = [Windows.Forms.Padding]::new(18, 18, 18, 18)
$out = @()
foreach ($case in @(@(100, 100), @(950, 100), @(100, 600), @(950, 600))) {
    $p = $place.Invoke($null, [object[]]@([Drawing.Point]::new($case[0], $case[1]), [Drawing.Size]::new(336, 236), $reach, [Drawing.Size]::new(1000, 664)))
    $out += ,@($p.X, $p.Y)
}
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), (ConvertTo-Json @{ place = $out } -Compress -Depth 4))
"""
        return run_probe(script, work, 300, CAR_EXE=str(exe))["place"]

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_every_frame_was_drawn_still_and_every_read_answered(self):
        self.assertEqual(self.result["notes"], [])
        self.assertEqual(self.result["misses"], [])
        self.assertEqual(len(self.pictures), 4)

    def test_the_menu_opens_with_its_card_where_the_pointer_stands_on_the_row(self):
        bounds = self.pictures[1][2]
        x, y, wide, tall = bounds["task.0"]
        anchor = (x + wide // 2, y + tall // 2)
        first = bounds["menu.0"]
        self.assertGreater(first[0], anchor[0] - 1, "the menu opens right of the pointer")
        self.assertGreater(first[1], anchor[1] - 1, "and below it")
        self.assertLess(first[1] - anchor[1], 40 * self.result["dpi_scale"], "its first item just under the pointer")
        self.assertIn("menu.4", bounds)
        self.assertIn("menu.5", bounds)
        self.assertGreater(bounds["menu.5"][1], bounds["menu.4"][1], "item 5 is under item 4")

    def test_the_menu_is_drawn_and_its_item_in_hand_rises(self):
        before, opened, held, closed = (picture[1] for picture in self.pictures)
        self.assertNotEqual(before, opened, "the open menu drew nothing")
        width = self.result["client"][0]
        x, y, wide, tall = self.pictures[2][2]["menu.4"]
        def area(picture):
            return [picture[(row * width + x) * 3:(row * width + x + wide) * 3] for row in range(y, y + tall)]
        self.assertNotEqual(area(opened), area(held), "the item in hand looks no different")

    def test_a_closed_menu_names_no_items_and_a_chosen_row_is_drawn_chosen(self):
        """The list chooses its first row as it fills (frame 0), so the row a frame chooses is shown on the second."""
        self.assertNotIn("menu.4", self.pictures[3][2])
        width = self.result["client"][0]
        x, y, wide, tall = self.pictures[3][2]["task.1"]
        def row(picture):
            return [picture[(line * width + x) * 3:(line * width + x + wide) * 3] for line in range(y, y + tall)]
        self.assertNotEqual(row(self.pictures[0][1]), row(self.pictures[3][1]), "the second row, chosen, looks unchosen")

    def test_a_menu_with_no_room_turns_round_as_windows_turns_it(self):
        # A window 336 by 236 with 18 px of shadow round its card of 300 by 200, in a client area of 1000 by 664.
        self.assertEqual(self.place, [[82, 82], [632, 82], [82, 382], [632, 382]])


if __name__ == "__main__":
    unittest.main()
