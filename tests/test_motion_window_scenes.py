"""v0.6.20: the window's render mode draws the four new scenes of the README's first motion picture (gui/WindowRender.cs).

An action in flight (`busy`: SetBusy, which makes the header's light the working one and makes every button wait), Why it
is waiting turned down by the wheel (`explain`), the Timeline dialog over the window (`dialog`: BuildTimeline, the method
the Timeline button builds it with, drawn offscreen with a title bar round it and centred as Windows centres it), and the
installation paused (`variant`: the window opened on a paused installation's replies). One small job of the real window,
offscreen - nothing shown, nothing captured.

GUI test module (it compiles the window): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
import motion_window  # noqa: E402

TYPE = "SettingsForm"


class SourceTests(unittest.TestCase):
    def test_the_dialog_is_built_by_the_method_the_click_builds_it_with(self):
        self.assertIn("BuildTimeline(", guiscan.member_body(TYPE, "OpenTimeline"))
        render = guiscan.member_body(TYPE, "RenderDialog")
        self.assertIn("BuildTimeline(row, Items(result, \"events\"), Items(result, \"receipts\"))", render)
        self.assertIn('RenderAnswer("timeline", IdArgument(row))', render, "from the reply the bridge gives for the row")
        self.assertNotIn("ShowDialog", render)
        self.assertNotIn("Process.Start", render)

    def test_a_dialog_is_centred_as_a_window_that_opens_it_centres_it(self):
        place = guiscan.member_body(TYPE, "RenderDialogPlace")
        self.assertIn("(owner.Width - size.Width) / 2", place)
        self.assertIn("(owner.Height - size.Height) / 2", place)
        self.assertIn("StartPosition = FormStartPosition.CenterParent", guiscan.member_body(TYPE, "BuildTimeline"))

    def test_an_action_in_flight_is_the_window_s_own_count(self):
        body = guiscan.member_body(TYPE, "RenderBusy")
        self.assertIn("SetBusy(on);", body)
        self.assertIn("BusyLight", guiscan.member_body(TYPE, "Hero"), "the light rule the render takes the state to")

    def test_the_wheel_over_why_it_is_waiting_moves_its_soft_page_as_every_page_moves(self):
        body = guiscan.member_body(TYPE, "RenderExplain")
        self.assertIn("RenderOffset(", body)
        self.assertIn("explainPage", body)
        self.assertIn("explainPage = gates;", guiscan.member_body(TYPE, "BuildPending"))


@unittest.skipUnless(os.name == "nt" and motion_window.CSC.is_file(), "the window is built with Windows' C# compiler")
class RenderTests(unittest.TestCase):
    """One job: Pending at rest, an action in flight, the checks turned down, the dialog open, the paused Overview."""

    FRAMES = [
        {"locale": "en", "page": "pending", "light": 0},                                           # 0 at rest
        {"locale": "en", "page": "pending", "light": 0, "busy": True},                             # 1 in flight
        {"locale": "en", "page": "pending", "light": 0},                                           # 2 answered
        {"locale": "en", "page": "pending", "light": 0, "explain": {"notches": 1}},                # 3
        {"locale": "en", "page": "pending", "light": 0, "explain": {"notches": 4}},                # 4 at the bottom
        {"locale": "en", "page": "pending", "light": 0, "explain": {"notches": 9}},                # 5 and no further
        {"locale": "en", "page": "pending", "light": 0, "dialog": {"kind": "timeline"}},           # 6 dialog open
        {"locale": "en", "page": "pending", "light": 0, "dialog": {"kind": "timeline"}, "hover": "dialog.close"},  # 7
        {"locale": "en", "page": "history", "light": 0, "dialog": {"kind": "timeline", "list": "history"}},       # 8
        {"locale": "en", "page": "overview", "light": 0},                                          # 9 running
        {"locale": "en", "page": "overview", "light": 0, "variant": "paused"},                     # 10 paused
        {"locale": "en", "page": "overview", "light": 0, "variant": "paused", "busy": True},       # 11 resuming
        {"locale": "en", "page": "overview", "light": 0},                                          # 12 running again
    ]

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = motion_window.compile_window(work)
        still = {"window": {"still": "assets/screenshot-dashboard.png"}}
        import make_screenshots
        width, height, _rgb, _alpha = make_screenshots.read_png(ROOT / still["window"]["still"])
        job = {"out": str(work / "out"), "theme": "light", "design": "soft",
               "forms": {"en": {"answers": motion_window.answers("en")},
                         "en-paused": {"answers": motion_window.answers("en", None, paused=True)}},
               "targets": ["pending.retry", "pending.timeline", "pending.explain", "overview.toggle", "dialog.close",
                           "dialog.window"],
               "outer": [width, height], "chrome": motion_window.chrome(still),
               "frames": [dict(frame, index=index) for index, frame in enumerate(cls.FRAMES)]}
        cls.result = motion_window.render(exe, job, work)
        cls.pictures = list(motion_window.pictures(cls.result, work / "out"))
        cls.outer = (width, height)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def box(self, one, other):
        """(left, top, right, bottom) of the pixels two frames differ in, or None."""
        width, height = self.result["client"]
        xs, ys = [], []
        for y in range(height):
            a, b = one[y * width * 3:(y + 1) * width * 3], other[y * width * 3:(y + 1) * width * 3]
            if a == b:
                continue
            ys.append(y)
            xs.extend(x for x in range(width) if a[x * 3:x * 3 + 3] != b[x * 3:x * 3 + 3])
        return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None

    def picture(self, index):
        return self.pictures[index][1]

    def bounds(self, index):
        return self.pictures[index][2]

    def inside(self, box, rect):
        x, y, wide, tall = rect
        return x <= box[0] and y <= box[1] and box[2] <= x + wide and box[3] <= y + tall

    def test_every_frame_was_drawn_and_every_read_answered(self):
        self.assertEqual(self.result["notes"], [])
        self.assertEqual(self.result["misses"], [])
        self.assertEqual(len(self.pictures), len(self.FRAMES))

    def test_an_action_in_flight_changes_the_header_and_the_buttons_and_let_go_changes_them_back(self):
        box = self.box(self.picture(0), self.picture(1))
        self.assertIsNotNone(box)
        retry = self.bounds(0)["pending.retry"]
        self.assertTrue(box[1] < 130 and box[3] >= retry[1], "the light above and the buttons below: %r" % (box,))
        self.assertEqual(self.picture(2), self.picture(0), "the same window once the call has been answered")

    def test_the_header_s_light_alone_changes_while_the_call_is_in_flight(self):
        before, during = self.picture(0), self.picture(1)
        width, _height = self.result["client"]
        dot = (int(width * 0.03), 30, int(width * 0.06), 110)
        changed = [(x, y) for y in range(dot[1], dot[3]) for x in range(dot[0], dot[2])
                   if before[(y * width + x) * 3:(y * width + x) * 3 + 3] != during[(y * width + x) * 3:(y * width + x) * 3 + 3]]
        self.assertTrue(changed, "the working light is not the resting one")

    def test_the_checks_are_turned_down_inside_their_card_to_the_last_and_no_further(self):
        card = self.bounds(0)["pending.explain"]
        box = self.box(self.picture(0), self.picture(3))
        self.assertIsNotNone(box)
        self.assertTrue(self.inside(box, card), "%r is outside the card %r" % (box, card))
        self.assertIsNotNone(self.box(self.picture(3), self.picture(4)))
        self.assertEqual(self.picture(4), self.picture(5), "more turns than the checks have change nothing")

    def test_the_dialog_is_centred_on_the_window_with_its_close_button_inside_it(self):
        window = self.bounds(6)["dialog.window"]
        close = self.bounds(6)["dialog.close"]
        outer_w, outer_h = self.outer
        caption = outer_h - self.result["client"][1]
        self.assertAlmostEqual(window[0] + window[2] / 2.0, outer_w / 2.0, delta=1.0)
        # Client coordinates have the window's own title bar above them: centred on the whole window, title bar included.
        self.assertAlmostEqual(window[1] + caption + window[3] / 2.0, outer_h / 2.0, delta=1.0)
        self.assertTrue(window[0] < close[0] and close[0] + close[2] < window[0] + window[2])
        self.assertTrue(window[1] < close[1] and close[1] + close[3] < window[1] + window[3])
        self.assertGreater(close[0] + close[2] / 2.0, window[0] + window[2] / 2.0, "Close is on the right, as the dialog puts it")

    def test_the_dialog_changes_the_picture_only_inside_its_window_and_shadow(self):
        window = self.bounds(6)["dialog.window"]
        reach = 40
        outside = (window[0] - reach, window[1] - reach, window[2] + 2 * reach, window[3] + 2 * reach)
        box = self.box(self.picture(2), self.picture(6))
        self.assertTrue(self.inside(box, outside), "%r is beyond the dialog %r" % (box, outside))

    def test_hovering_its_close_button_changes_only_that_button(self):
        close = self.bounds(7)["dialog.close"]
        box = self.box(self.picture(6), self.picture(7))
        self.assertIsNotNone(box)
        self.assertTrue(self.inside(box, close), "%r is outside Close %r" % (box, close))

    def test_the_history_page_opens_the_same_dialog_for_its_own_chosen_task_or_says_it_has_none(self):
        notes = self.result["notes"]
        self.assertEqual(notes, [])
        self.assertIn("dialog.close", self.bounds(8))

    def test_the_paused_installation_is_what_the_window_says_and_resuming_puts_it_back(self):
        box = self.box(self.picture(9), self.picture(10))
        self.assertIsNotNone(box)
        self.assertLess(box[1], 140, "the headline and the light change at the top of the window")
        self.assertIn("overview.toggle", self.bounds(10))
        resting_width = self.bounds(9)["overview.toggle"][2]
        resuming_width = self.bounds(10)["overview.toggle"][2]
        self.assertNotEqual(resting_width, resuming_width, "the button says Resume recovery now")
        self.assertEqual(self.picture(12), self.picture(9), "and the window is the running one again")
        self.assertIsNotNone(self.box(self.picture(10), self.picture(11)), "the call in flight is drawn on the paused window")


if __name__ == "__main__":
    unittest.main()
