r"""v0.6.23: the special days on the other surfaces (by the owner's word). Nothing here reads today's date.

Part GUI (it compiles the window and draws): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import guiscan
from codex_auto_resume import brand
from codex_auto_resume.ui import popup as tray_popup
from codex_auto_resume.ui.popup import hidden as popup_hidden
from codex_auto_resume.ui.tray.motion import IconFrames
from test_gui_v0611_access import compile_window, run_probe
from test_gui_v0623_motion import PROBE_HEAD, PROBE_HELPERS, PROBE_TAIL

ROOT = Path(__file__).resolve().parents[1]
LOOKS = tuple(brand.DAY_LOOKS)


class TheNumbersTests(unittest.TestCase):
    def test_seven_presses_each_within_the_gap(self):
        run = brand.PressRun()
        self.assertEqual([run.press(1800.0 * index) for index in range(7)], [False] * 6 + [True])
        self.assertFalse(run.press(1800.0 * 7), "and it starts again")

    def test_a_press_too_late_starts_again(self):
        run = brand.PressRun()
        moments = [0, 1000, 2000, 3801, 4000, 5000, 6000, 7000, 8000]
        self.assertEqual([run.press(float(at)) for at in moments], [False] * 9)

    def test_the_sweep_is_the_mocks(self):
        start = brand.sweep_at(0.0, brand.ease)
        self.assertEqual((start[0], start[1]), (0.0, 1.0))
        self.assertEqual(start[2], [(0.0, 0.0), (0.0, 0.0)])
        self.assertEqual(brand.sweep_at(735.0, brand.ease)[:2], (1.0, 1.0))
        self.assertEqual(brand.sweep_at(1050.0, brand.ease)[1], 0.0)
        self.assertGreater(brand.sweep_at(1000.0, brand.ease)[2][0][1], 0.0)
        self.assertEqual(brand.sweep_at(1900.0, brand.ease)[2], [(1.0, 0.0), (1.0, 0.0)])


class Fake:
    def __init__(self):
        self.calls = 0

    def __call__(self, *unused, **unused2):
        self.calls += 1


class PopupPressTests(unittest.TestCase):
    PLAN = {"items": [{"kind": "title_press", "rect": (40, 20, 160, 40)}]}

    def popup(self, reduced=False):
        made = tray_popup.Popup.__new__(tray_popup.Popup)
        made._reduced, made._contrast, made.visible, made._painted_plan = reduced, False, True, self.PLAN
        made._sync_frames, made._update = Fake(), Fake()
        made.model = mock.Mock(strings={"status.aside": "The sentence"})
        return made

    @staticmethod
    def at(x, y):
        return (y << 16) | x

    def press_seven(self, made, start=0.0):
        for index in range(7):
            made.title_pressed(self.at(60, 30), start + 1000.0 * index)

    def test_seven_presses_of_the_title_start_it_once(self):
        made = self.popup()
        for index in range(6):
            made.title_pressed(self.at(60, 30), 1000.0 * index)
        self.assertIsNone(made._sweep_since)
        made.title_pressed(self.at(60, 30), 6000.0)
        self.assertEqual(made._sweep_since, 6000.0)
        self.assertEqual(made._aside_from, 6000.0 + brand.SWEEP["aside_after_ms"])

    def test_a_press_anywhere_else_is_not_counted(self):
        made = self.popup()
        for index in range(7):
            made.title_pressed(self.at(300, 30), 1000.0 * index)
        self.assertIsNone(made._sweep_since)
        self.assertIsNone(made._aside_from)

    def test_with_motion_reduced_no_sweep_and_the_sentence_at_once(self):
        made = self.popup(reduced=True)
        self.press_seven(made)
        self.assertIsNone(made._sweep_since)
        self.assertEqual(made._aside_from, 6000.0)

    def test_the_sentence_stands_for_its_moment_and_the_state_line_returns(self):
        made = self.popup()
        with mock.patch.object(popup_hidden.time, "monotonic", return_value=100.0):
            made._aside_from = 100000.0 + 500.0
            self.assertEqual(made.aside_words("The state"), "The state", "not yet")
            made._aside_from = 100000.0 - 500.0
            self.assertEqual(made.aside_words("The state"), "The sentence")
            made._aside_from = 100000.0 - brand.SWEEP["aside_ms"] - 1.0
            self.assertEqual(made.aside_words("The state"), "The state")
            self.assertIsNone(made._aside_from)

    def test_it_reaches_nothing_but_the_window(self):
        source = (ROOT / "src/codex_auto_resume/ui/popup/hidden.py").read_text(encoding="utf-8")
        for never in ("control", "perform", "_request_read", "open(", "journal", "log("):
            self.assertNotIn(never, source.replace("A mixin", ""))

    def test_the_title_is_no_target_so_a_press_on_it_does_what_it_always_did(self):
        renderer = tray_popup.Renderer()
        self.addCleanup(renderer.close)
        vm = tray_popup.view_model([], {"enabled": True}, {}, 1800000000.0)
        plan = renderer.layout(vm, 1.0, "en")
        title = [item for item in plan["items"] if item["kind"] == "title_press"][0]["rect"]
        self.assertIsNone(tray_popup.hit_test(plan["targets"], (title[0] + title[2]) // 2, (title[1] + title[3]) // 2))


class PopupSweepDrawnTests(unittest.TestCase):
    def setUp(self):
        self.renderer = tray_popup.Renderer()
        self.addCleanup(self.renderer.close)
        self.vm = tray_popup.view_model([], {"enabled": True}, {}, 1800000000.0)
        self.plan = self.renderer.layout(self.vm, 2.0, "en")
        self.halo = [item for item in self.plan["items"] if item["kind"] == "halo"][0]

    def frame(self, ms):
        self.renderer.sweep_ms = None
        self.renderer.draw(self.vm, self.plan, frame=tray_popup.halo("idle", 0.0))
        self.renderer.sweep_ms = ms
        return self.renderer.draw_halo(self.plan, tray_popup.halo("idle", 0.0)).pixels()

    def test_it_draws_round_the_light(self):
        self.assertNotEqual(self.frame(400.0), self.frame(None))

    def test_the_light_keeps_its_colour(self):
        width = self.plan["size"][0]
        centre = (int(self.halo["cy"]) * width + int(self.halo["cx"])) * 4
        self.assertEqual(self.frame(400.0)[centre:centre + 3], self.frame(None)[centre:centre + 3])

    def test_it_stays_in_its_room_clear_of_the_words(self):
        width = self.plan["size"][0]
        one, other = self.frame(1200.0), self.frame(None)
        right_of_room = int(self.halo["cx"] + self.halo["sweep_reach"] + 3)
        for y in range(self.plan["size"][1]):
            start = (y * width + right_of_room) * 4
            self.assertEqual(one[start:(y + 1) * width * 4], other[start:(y + 1) * width * 4], y)

    def test_the_seam_of_a_frame_is_the_band_kept_for_it(self):
        self.assertGreaterEqual(self.halo["sweep_reach"], self.halo["radius"] * 0.5)
