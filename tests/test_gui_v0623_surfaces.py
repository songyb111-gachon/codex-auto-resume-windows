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


PROBE_WINDOW = r"""
$out.parity = @{}
$times = @(0.0, 1.3, 9.7)
foreach ($look in 'birthday', 'new_year', 'christmas', 'seollal', 'chuseok') {
    $elements = S 'DayArt' 'Parse' @((S 'Brand' 'DayScene' @($look)))
    $all = @()
    foreach ($seconds in $times) {
        foreach ($element in $elements) {
            $call = [object[]]@($element, [double]$seconds, $null, [double]0)
            $null = (T 'DayArt').GetMethod('At', $static).Invoke($null, $call)
            $all += ,@(@($call[2] | ForEach-Object { [double]$_ }), [double]$call[3])
        }
    }
    $out.parity[$look] = $all
}
$out.todayOff = (S 'DayArt' 'Today' @()) -eq $null
function Fit([int]$end, [int]$width) {
    $call = [object[]]@('birthday', [int]$end, [int]0, [int]$width, [int]($width - 1), [int]1, [int]65, [int]0, [double]0, [int]0)
    $ok = (T 'DayArt').GetMethod('Fit', $static).Invoke($null, $call)
    return @([bool]$ok, [int]$call[7], [double]$call[8], [int]$call[9])
}
$out.fitRoom = Fit 120 400
$out.fitNone = Fit 380 400
$card = (SProp 'Palette' 'Card')
$scene = Make 'SoftDayScene'
$form.Controls.Add($scene)
$scene.GetType().GetMethod('Place', $instance).Invoke($scene, [object[]]@($true, 'chuseok', [int]100, [int]10, [int]300, [int]60, [double](60.0 / 66.0), [int]60)) | Out-Null
Pump 30
$out.scene = @{ visible = [bool]$scene.Visible; moving = [bool](P $scene 'Moving') }
function Paint {
    $bitmap = New-Object Drawing.Bitmap $scene.Width, $scene.Height
    $g = [Drawing.Graphics]::FromImage($bitmap)
    $e = New-Object Windows.Forms.PaintEventArgs $g, $scene.ClientRectangle
    $null = Call $scene 'OnPaint' @($e)
    $g.Dispose()
    return $bitmap
}
$bitmap = Paint
$first = @(); foreach ($y in 0, 20, 40, 59) { $first += (Argb $bitmap.GetPixel(0, $y)) }
$out.scene.first = $first
$out.scene.card = (Argb $card)
$out.scene.far = (Argb $bitmap.GetPixel($scene.Width - 40, 30))
$bitmap.Dispose()
$scene.Visible = $false
Pump 30
$out.scene.hiddenMoving = [bool](P $scene 'Moving')
$scene.Visible = $true
Pump 30
Reduce $true
$null = Call $scene 'Sync' @()
$out.scene.reducedMoving = [bool](P $scene 'Moving')
Reduce $false
$null = Call $scene 'Sync' @()
$out.scene.allowedAgain = [bool](P $scene 'Moving')
$scene.GetType().GetMethod('Place', $instance).Invoke($scene, [object[]]@($false, 'chuseok', [int]0, [int]0, [int]0, [int]0, [double]0, [int]0)) | Out-Null
$out.scene.off = @([bool]$scene.Visible, [bool](P $scene 'Moving'))
"""


class DashboardSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        cls.answer = run_probe(PROBE_HEAD + PROBE_HELPERS + PROBE_WINDOW + PROBE_TAIL, work, 200, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_window_draws_brands_own_list(self):
        for look in LOOKS:
            expected = [brand.element_at(element, seconds) for seconds in (0.0, 1.3, 9.7) for element in brand.scene_elements(look)]
            got = self.answer["parity"][look]
            self.assertEqual(len(got), len(expected), look)
            for (numbers, opacity), (_, python, _, alpha) in zip(got, expected):
                self.assertAlmostEqual(opacity, alpha, places=2, msg=look)
                for one, other in zip(numbers, python):
                    self.assertAlmostEqual(one, other, delta=0.01, msg=look)

    def test_no_window_looks_at_the_date_unless_a_person_opened_it(self):
        self.assertTrue(self.answer["todayOff"])
        self.assertIn("DayArt.On = Soft.StillClock < 0;", guiscan.settings())

    def test_the_words_leave_room_or_there_is_no_scene(self):
        ok, left, unit, fade = self.answer["fitRoom"]
        self.assertTrue(ok)
        self.assertGreaterEqual(left, 128)
        self.assertGreater(fade, 0)
        self.assertFalse(self.answer["fitNone"][0])

    def test_there_is_no_seam(self):
        scene = self.answer["scene"]
        self.assertEqual(scene["first"], [scene["card"]] * 4)
        self.assertNotEqual(scene["far"], scene["card"])

    def test_it_moves_only_while_it_can_be_seen_and_motion_is_allowed(self):
        scene = self.answer["scene"]
        self.assertTrue(scene["moving"])
        self.assertFalse(scene["hiddenMoving"])
        self.assertFalse(scene["reducedMoving"])
        self.assertTrue(scene["allowedAgain"])
        self.assertEqual(scene["off"], [False, False])

    def test_classic_has_none_and_a_frame_lays_nothing_out(self):
        self.assertIn("dayLook = Palette.AccentBar ? null : DayArt.Today();", guiscan.settings())
        self.assertNotIn("PerformLayout", guiscan.type_body("SoftDayScene"))
        self.assertIn("dayScene.Sync();", guiscan.member_body("SettingsForm", "UpdateCountdowns"))

    def test_the_scene_stands_clear_of_the_words(self):
        body = guiscan.member_body("SettingsForm", "PlaceDayScene")
        self.assertIn("WordsEnd(headline, mirrored, width), WordsEnd(detail, mirrored, width)", body)
        self.assertIn("DayArt.Fit(", body)
