r"""v0.6.23: the days with a look of their own, and the seven presses (both only by the owner's word).

The table is brand's and is generated into the window; nothing here reads today's date, so no test can fail because of the day
it runs on or the years that have passed. Part GUI (it compiles the window): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import guiscan
from codex_auto_resume import brand
from codex_auto_resume.brand import days as brand_days
from codex_auto_resume.ui import popup as tray_popup
from codex_auto_resume.ui.popup import window as popup_window
from codex_auto_resume.ui.tray import animation
from codex_auto_resume.ui.tray.motion import IconFrames
from test_gui_v0611_access import compile_window, run_probe
from test_gui_v0623_motion import PROBE_HEAD, PROBE_HELPERS, PROBE_TAIL

ROOT = Path(__file__).resolve().parents[1]

# KASI's calendar converter (astro.kasi.re.kr), lunar 1/1 and 8/15, read once by hand into this list as well as the table.
KASI = {2026: ("0217", "0925"), 2027: ("0207", "0915"), 2028: ("0127", "1003"), 2029: ("0213", "0922"), 2030: ("0203", "0912"),
        2031: ("0123", "1001"), 2032: ("0211", "0919"), 2033: ("0131", "0908"), 2034: ("0219", "0927"), 2035: ("0208", "0916"),
        2036: ("0128", "1004"), 2037: ("0215", "0924"), 2038: ("0204", "0913"), 2039: ("0124", "1002"), 2040: ("0212", "0921")}
LOOKS = ("birthday", "new_year", "christmas", "seollal", "chuseok")


class TableTests(unittest.TestCase):
    def test_the_days_of_every_year(self):
        for year in (2026, 2031, 2041, 2099):
            self.assertEqual(brand.day_look(year, 9, 6), "birthday")
            self.assertEqual(brand.day_look(year, 1, 1), "new_year")
            self.assertEqual(brand.day_look(year, 12, 24), "christmas")
            self.assertEqual(brand.day_look(year, 12, 25), "christmas")

    def test_the_mocks_colours(self):
        self.assertEqual(brand.DAY_LOOKS, {
            "birthday": ("#EE8468", "#9E3A4B", "#FFEADF"), "new_year": ("#2F3D8F", "#C9942B", "#1B2559"),
            "christmas": ("#2E8B5E", "#0F4A36", "#12442F"), "seollal": ("#D2453E", "#7A1F2B", "#FFF4E2"),
            "chuseok": ("#2B2F77", "#12143F", "#1C1F55")})

    def test_the_lunar_days_are_the_official_dates(self):
        for year, (seollal, chuseok) in KASI.items():
            self.assertEqual(brand.day_look(year, int(seollal[:2]), int(seollal[2:])), "seollal", year)
            self.assertEqual(brand.day_look(year, int(chuseok[:2]), int(chuseok[2:])), "chuseok", year)

    def test_past_the_tables_last_year_nothing_lunar_is_shown(self):
        day = datetime.date(2041, 1, 2)
        while day.year == 2041:
            if (day.month, day.day) not in ((9, 6), (12, 24), (12, 25)):
                self.assertIsNone(brand.day_look(day.year, day.month, day.day), day)
            day += datetime.timedelta(days=1)

    def test_a_days_look_runs_midnight_to_midnight_by_the_local_date(self):
        for clock in ((2026, 9, 6, 0, 0, 1), (2026, 9, 6, 23, 59, 59)):
            self.assertEqual(brand.day_look_at(datetime.datetime(*clock).timestamp()), "birthday")
        self.assertIsNone(brand.day_look_at(datetime.datetime(2026, 9, 7, 0, 0, 1).timestamp()))

    def test_the_window_has_the_same_table(self):
        method = guiscan.member_body("Brand", "DayLook")
        for month, day, key in brand.FIXED_DAYS:
            first, last, _ = brand.DAY_LOOKS[key]
            self.assertIn('if (yearly == %d) { look = "%s"; top = "%s"; bottom = "%s"; return true; }' % (month * 100 + day, key, first, last), method)
        for key, dates in brand.LUNAR_DAYS:
            for year, month, day in dates:
                self.assertIn("whole == %d" % (year * 10000 + month * 100 + day), method)


class SceneTests(unittest.TestCase):
    def test_a_scene_is_the_same_every_time(self):
        for look in LOOKS:
            self.assertEqual(brand.scene_frame(look, 1500.0), brand.scene_frame(look, 1500.0), look)

    def test_every_scene_moves_on_its_own_clock(self):
        for look in LOOKS:
            self.assertNotEqual(brand.scene_frame(look, 0.0), brand.scene_frame(look, 1300.0), look)

    def test_the_seeds_are_fixed_numbers(self):
        self.assertNotIn("random", (ROOT / "src/codex_auto_resume/brand/days.py").read_text(encoding="utf-8"))
        for build in (brand_days._birthday, brand_days._new_year, brand_days._christmas, brand_days._chuseok):
            self.assertEqual(build()(0.0), build()(0.0), "made twice, it is one scene")
        self.assertAlmostEqual(brand_days._Seeded(906)(0.0, 1.0), ((906 * 1103515245 + 12345) & 0x7FFFFFFF) / 0x7FFFFFFF)

    def test_each_scene_holds_the_mocks_parts(self):
        def colours(look):
            return {shape[-2] for shape in brand.scene_frame(look, 0.0)}
        self.assertLessEqual({"#FFFFFF", "#F4A7B5", "#5BB8C4", "#F6B73C", "#F2A33A"}, colours("birthday"))
        self.assertLessEqual({"#F6B73C", "#FAC65A", "#141B45", "#FFE9A8"}, colours("new_year"))
        self.assertLessEqual({"#1F6B4A", "#2B8660", "#FFD76A", "#FFFFFF"}, colours("christmas"))
        self.assertLessEqual({"#D9463E", "#F2C230", "#3FA86B", "#3B6FC9", "#E88BB0", "#E2C9A0", "#C93B3B"}, colours("seollal"))
        self.assertLessEqual({"#F6E7B4", "#E6D39B", "#3A3F86", "#FFF4D0"}, colours("chuseok"))

    def test_the_counts_of_the_mock(self):
        count = lambda look, kind, colour: sum(1 for shape in brand.scene_frame(look, 0.0) if shape[0] == kind and shape[-2] == colour)  # noqa: E731
        self.assertEqual(count("new_year", "poly", "#FFE9A8"), 9)
        self.assertEqual(count("christmas", "circle", "#FFFFFF"), 22)
        self.assertEqual(count("chuseok", "poly", "#FFF4D0"), 7)
        self.assertEqual(sum(1 for shape in brand.scene_frame("birthday", 0.0) if shape[0] == "poly" and shape[-2] != "#F4A7B5"), 16)


class IconTests(unittest.TestCase):
    def pixel(self, frames, frame, x, y):
        at = (y * frames.size + x) * 4
        return tuple(frame[at:at + 4])

    def rgb(self, frames, x, y):
        blue, green, red, _ = self.pixel(frames, frames.ground, x, y)
        return (red, green, blue)

    def test_an_ordinary_icon_is_the_icon_it_always_was(self):
        self.assertEqual(IconFrames(32, look=None).ground, IconFrames(32).ground)

    def test_the_body_runs_from_one_colour_to_the_other_down_the_icon(self):
        for look in LOOKS:
            frames = IconFrames(16, look=look)
            top, bottom = brand.rgb(brand.DAY_LOOKS[look][0]), brand.rgb(brand.DAY_LOOKS[look][1])
            near_top, near_bottom = self.rgb(frames, 8, 0), self.rgb(frames, 8, 15)
            for channel in range(3):
                self.assertLess(abs(near_top[channel] - top[channel]), 30, look)
                self.assertLess(abs(near_bottom[channel] - bottom[channel]), 30, look)

    def test_the_state_colour_stays_the_states(self):
        for look in LOOKS:
            themed, plain = IconFrames(32, look=look), IconFrames(32)
            head = (10, 200, 90)
            one, other = themed.compose(0, head), plain.compose(0, head)
            (left, top, _, _), rows = plain.heads[0]
            whole = 0
            for y, row in enumerate(rows):
                for x, sample in enumerate(row):
                    if sample[1] == sample[0] and sample[0] > 0:
                        whole += 1
                        self.assertEqual(self.pixel(themed, one, left + x, top + y), self.pixel(plain, other, left + x, top + y), look)
            self.assertGreater(whole, 0, "no pixel was all head")

    def test_the_ring_is_the_ring_it_always_was(self):
        themed, plain = IconFrames(32, look="birthday"), IconFrames(32)
        self.assertEqual(self.pixel(themed, themed.ground, 16, 23), self.pixel(plain, plain.ground, 16, 23))

    def test_the_mark_shows_from_24_px_and_never_below(self):
        moon = brand.rgb("#F6E7B4")
        self.assertEqual(self.rgb(IconFrames(32, look="chuseok"), 26, 7), moon)
        self.assertEqual(self.rgb(IconFrames(24, look="chuseok"), 20, 5), moon)
        small = IconFrames(16, look="chuseok")
        self.assertNotEqual(self.rgb(small, 13, 3), moon)

    def test_the_stripes_lie_at_the_bottom_edge(self):
        frames = IconFrames(32, look="seollal")
        self.assertEqual(self.rgb(frames, 6, 24), brand.rgb("#F2C230"))
        self.assertEqual(self.rgb(frames, 6, 28), brand.rgb("#E88BB0"))

    def test_the_head_stands_on_the_mark_as_it_goes_round(self):
        frames, plain = IconFrames(32, look="seollal"), IconFrames(32, look=None)
        head = (10, 200, 90)
        position = len(frames.heads) // 2
        frame = frames.compose(position, head)
        (left, top, _, _), rows = frames.heads[position]
        checked = 0
        for y, row in enumerate(rows):
            for x, sample in enumerate(row):
                if sample[1] == sample[0] and sample[0] > 0:
                    checked += 1
                    self.assertEqual(self.pixel(frames, frame, left + x, top + y)[:3], (90, 200, 10))
        self.assertGreater(checked, 0)
        self.assertTrue(plain)


class TrayGateTests(unittest.TestCase):
    def tray(self, days):
        made = animation.AnimationMixin.__new__(animation.AnimationMixin)
        made.days = days
        return made

    def look(self, days, contrast=False):
        with mock.patch.object(tray_popup, "high_contrast", return_value=contrast), \
             mock.patch.object(animation.time, "time", return_value=datetime.datetime(2026, 9, 6, 12).timestamp()):
            return self.tray(days)._day_look()

    def test_only_the_watchers_own_icon_reads_the_date(self):
        self.assertEqual(self.look(True), "birthday")
        self.assertIsNone(self.look(False))

    def test_high_contrast_is_untouched(self):
        self.assertIsNone(self.look(True, contrast=True))

    def test_one_place_asks_for_it_and_no_picture_generator_is_it(self):
        callers = [path for path in (ROOT / "src").rglob("*.py") if "days=True" in path.read_text(encoding="utf-8")]
        self.assertEqual([path.name for path in callers], ["app.py"])
        for path in (ROOT / "build").rglob("*.py"):
            self.assertNotIn("days=True", path.read_text(encoding="utf-8"), path)

    def test_the_pictures_clock_is_no_such_day_in_any_time_zone(self):
        source = (ROOT / "build/make_screenshots.py").read_text(encoding="utf-8")
        moment = float(re.search(r"^POPUP_NOW = ([\d_.]+)", source, re.M).group(1).replace("_", ""))
        for hours in range(-12, 15):
            day = datetime.datetime.fromtimestamp(moment, datetime.timezone.utc) + datetime.timedelta(hours=hours)
            self.assertIsNone(brand.day_look(day.year, day.month, day.day), hours)


class FakeUser32:
    def __init__(self):
        self.set, self.killed = 0, 0

    def SetTimer(self, *unused):
        self.set += 1

    def KillTimer(self, *unused):
        self.killed += 1


class PopupClockTests(unittest.TestCase):
    def popup(self, *, visible=True, reduced=False, scene="seollal"):
        made = tray_popup.Popup.__new__(tray_popup.Popup)
        made.visible, made._reduced, made._glides, made.hwnd, made._frame_running = visible, reduced, {}, 1, False
        made._state_since = 0.0
        made._vm = {"light": "idle", "scene": scene}
        return made

    def synced(self, made):
        user32 = FakeUser32()
        with mock.patch.object(popup_window, "_dll", return_value=user32), mock.patch.object(popup_window, "animates", return_value=False):
            made._sync_frames()
        return user32

    def test_the_scene_keeps_the_frame_timer_running_while_it_is_shown(self):
        self.assertEqual(self.synced(self.popup()).set, 1)

    def test_hidden_there_is_no_wake_up(self):
        self.assertEqual(self.synced(self.popup(visible=False)).set, 0)

    def test_with_motion_reduced_it_stands_still(self):
        made = self.popup(reduced=True)
        self.assertEqual(self.synced(made).set, 0)
        self.assertEqual(popup_window.scene_ms(True, 0.0), 0.0)
        self.assertGreater(popup_window.scene_ms(False, 0.0), 0.0)

    def test_an_ordinary_day_does_not_run_it(self):
        self.assertEqual(self.synced(self.popup(scene=None)).set, 0)

    def test_the_popup_asks_only_when_it_was_told_to(self):
        rebuild = (ROOT / "src/codex_auto_resume/ui/popup/window.py").read_text(encoding="utf-8")
        self.assertIn('if self.days and not self._contrast and self._design != "classic" else None', rebuild)
        self.assertEqual(tray_popup.Popup.days, False)


class PopupSceneTests(unittest.TestCase):
    def setUp(self):
        self.renderer = tray_popup.Renderer()
        self.addCleanup(self.renderer.close)

    def vm(self, scene):
        made = tray_popup.view_model([], {"enabled": True}, {}, 1800000000.0)
        if scene:
            made["scene"] = scene
        return made

    def draw(self, scene, ms=0.0, theme="light"):
        self.renderer.theme = theme
        vm = self.vm(scene)
        plan = self.renderer.layout(vm, 1.0, "en")
        return plan, self.renderer.draw(vm, plan, frame=tray_popup.halo("monitoring", 0.0), scene_ms=ms).pixels()

    @staticmethod
    def at(plan, pixels, x, y):
        index = (y * plan["size"][0] + x) * 4
        return (pixels[index + 2], pixels[index + 1], pixels[index])

    @staticmethod
    def scene_item(plan):
        return [item for item in plan["items"] if item["kind"] == "scene"][0]

    def test_an_ordinary_header_has_none(self):
        plan = self.renderer.layout(self.vm(None), 1.0, "en")
        self.assertEqual([item for item in plan["items"] if item["kind"] == "scene"], [])

    def test_the_scene_is_two_thirds_of_the_card_at_its_top_right_and_touches_nothing_below(self):
        plan, _ = self.draw("seollal")
        left, top, right, bottom = self.scene_item(plan)["rect"]
        card = plan["card"]
        self.assertAlmostEqual((right - left) / (card[2] - card[0]), 0.66, delta=0.02)
        self.assertEqual(top, card[1] + 1)
        self.assertEqual(right, card[2] - 1)
        self.assertLessEqual(bottom - top, 66)
        for item in plan["items"]:
            if item["kind"] in ("well", "panel", "button", "note"):
                self.assertGreaterEqual(item["rect"][1], bottom, item["kind"])

    def test_the_scene_is_drawn_and_the_stripes_are_the_mocks(self):
        plan, pixels = self.draw("seollal")
        left, top, right, _ = self.scene_item(plan)["rect"]
        self.assertIn(self.at(plan, pixels, right - 30, top + 1), [brand.rgb(colour) for colour in ("#D9463E", "#F2C230", "#3FA86B", "#3B6FC9", "#E88BB0")])

    def test_its_inner_side_is_the_cards_own_colour(self):
        for theme in ("light", "dark"):
            plan, pixels = self.draw("chuseok", theme=theme)
            item = self.scene_item(plan)
            ground = brand.rgb(brand.card_ground(theme, "soft"))
            edge = self.at(plan, pixels, item["rect"][0], item["rect"][1] + 2)
            bg = brand.rgb(brand.DAY_LOOKS["chuseok"][2])
            for channel in range(3):
                self.assertLess(abs(edge[channel] - ground[channel]), abs(bg[channel] - ground[channel]) * 0.25 + 2, theme)

    def test_what_stands_left_of_it_is_what_stands_there_on_any_day(self):
        for theme in ("light", "dark"):
            plan, plain = self.draw(None, theme=theme)
            scene_plan, day = self.draw("birthday", theme=theme)
            limit = self.scene_item(scene_plan)["rect"][0]
            top, bottom = scene_plan["card"][1], scene_plan["card"][1] + 60
            for y in range(top, bottom):
                for x in range(0, limit):
                    self.assertEqual(self.at(plan, plain, x, y), self.at(scene_plan, day, x, y), (theme, x, y))

    def test_the_words_on_it_are_drawn_again_with_each_frame(self):
        vm = self.vm("birthday")
        vm["title"] = "A title long enough to run well into the scene behind it"
        plan = self.renderer.layout(vm, 1.0, "en")
        whole = self.renderer.draw(vm, plan, frame=tray_popup.halo("monitoring", 0.0), scene_ms=2000.0).pixels()
        self.renderer.draw(vm, plan, frame=tray_popup.halo("monitoring", 0.0), scene_ms=0.0)
        framed = self.renderer.draw_scene(plan, 2000.0).pixels()
        self.assertEqual(framed, whole)

    def test_a_frame_moves_the_scene_and_the_same_instant_draws_the_same(self):
        _, one = self.draw("christmas", 500.0)
        _, again = self.draw("christmas", 500.0)
        _, later = self.draw("christmas", 1500.0)
        self.assertEqual(one, again)
        self.assertNotEqual(one, later)

    def test_every_scene_draws(self):
        for look in LOOKS:
            self.draw(look, 800.0, "dark")

    def test_mirrored_the_scene_stands_at_the_other_side(self):
        vm = self.vm("new_year")
        plan = self.renderer.layout(vm, 1.0, "ar")
        item = self.scene_item(plan)
        self.assertLess(item["rect"][0], plan["size"][0] / 2)
        self.renderer.draw(vm, plan, frame=tray_popup.halo("monitoring", 0.0), scene_ms=0.0)


PROBE = r"""
$run = Make 'PressRun'
$at = 0.0
$said = @()
foreach ($gap in 0, 1800, 1800, 1800, 1800, 1800) { $at += $gap; $said += [bool](Call $run 'Press' @([double]$at)) }
$out.six = $said
$at += 1800
$out.seventh = [bool](Call $run 'Press' @([double]$at))
$at += 1800
$out.eighth = [bool](Call $run 'Press' @([double]$at))
$late = Make 'PressRun'
$at = 0.0
$said = @()
foreach ($gap in 0, 1000, 1000, 1801, 1000, 1000, 1000, 1000, 1000) { $at += $gap; $said += [bool](Call $late 'Press' @([double]$at)) }
$out.broken = $said

function ArcAt([double]$ms) {
    $call = [object[]]@($ms, [double]0, [double]0)
    $null = (T 'HaloDot').GetMethod('ArcAt', $static).Invoke($null, $call)
    return @([double]$call[1], [double]$call[2])
}
function RingAt([double]$ms) {
    $call = [object[]]@($ms, [double]0, [double]0)
    $null = (T 'HaloDot').GetMethod('RingAt', $static).Invoke($null, $call)
    return @([double]$call[1], [double]$call[2])
}
$out.arc = @((ArcAt 0), (ArcAt 735), (ArcAt 900), (ArcAt 1050))
$out.ring = @((RingAt -1), (RingAt 0), (RingAt 450), (RingAt 900))
$dot = Make 'HaloDot'; Place $dot 20 20 28 44; Pump 30
function Centre {
    $bitmap = New-Object Drawing.Bitmap $dot.Width, $dot.Height
    $g = [Drawing.Graphics]::FromImage($bitmap)
    $e = New-Object Windows.Forms.PaintEventArgs $g, $dot.ClientRectangle
    $null = Call $dot 'OnPaint' @($e)
    $g.Dispose()
    $pixel = Argb $bitmap.GetPixel([int]($dot.Width / 2), [int]($dot.Height / 2))
    $bitmap.Dispose()
    return $pixel
}
$before = Centre
$null = Call $dot 'Sweep' @()
$out.sweep = @{ running = [bool](P $dot 'Sweeping'); length = [int](F (F $dot 'sweep') 'length'); scale = [double](P $dot 'SweepScale'); before = $before }
Pump 300
$out.sweep.during = Centre
$out.sweep.reach = [double](P $dot 'SweepScale') * 27.0
$out.sweep.room = [math]::Min($dot.Width, $dot.Height) / 2.0
Pump 2000
$out.sweep.after = [bool](P $dot 'Sweeping')
$out.sweep.stateAfter = (P $dot 'State')
Reduce $true
$null = Call $dot 'Sweep' @()
$out.sweep.reduced = [bool](P $dot 'Sweeping')
Reduce $false

$line = Make 'AsideLabel'; $line.Text = 'What it said'; Place $line 20 100 300 24; Pump 20
$null = Call $line 'Aside' @('A sentence', [int]250, [int]500)
$out.line = @{ waiting = [string]$line.Text; saying = [bool](P $line 'Saying') }
$line.Text = 'Told meanwhile'
$out.line.notYet = [string]$line.Text
Pump 350
$out.line.during = [string]$line.Text
$out.line.saying2 = [bool](P $line 'Saying')
$out.line.length = [int](F (F $line 'fade') 'length')
Pump 700
$out.line.after = [string]$line.Text
$out.line.done = [bool](P $line 'Saying')
$out.line.outLength = [int](F (F $line 'fade') 'length')
$null = Call $line 'Aside' @('At once', [int]250, [int]300)
Pump 350
Pump 500
Reduce $true
$null = Call $line 'Aside' @('Reduced', [int]0, [int]200)
$out.line.reducedAt = @([string]$line.Text, [bool](P $line 'Fading'))
Pump 400
$out.line.reducedBack = @([string]$line.Text, [bool](P $line 'Fading'))
Reduce $false

$out.table = @()
$method = (T 'Brand').GetMethod('DayLook', $static)
foreach ($date in @(20260906, 20260907, 20270101, 20281003, 20281004, 20401225, 20410212, 20400212, 20330908)) {
    $call = [object[]]@([int][math]::Floor($date / 10000), [int][math]::Floor(($date % 10000) / 100), [int]($date % 100), $null, $null, $null)
    $found = $method.Invoke($null, $call)
    $out.table += ,@($date, [bool]$found, $call[3], $call[4], $call[5])
}
"""


class PressAndLightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        cls.answer = run_probe(PROBE_HEAD + PROBE_HELPERS + PROBE + PROBE_TAIL, work, 200, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_seven_presses_each_within_the_gap_say_so_once(self):
        self.assertEqual(self.answer["six"], [False] * 6)
        self.assertTrue(self.answer["seventh"])
        self.assertFalse(self.answer["eighth"], "and it starts again")

    def test_a_press_too_late_starts_the_count_again(self):
        self.assertEqual(self.answer["broken"], [False] * 9)

    def test_the_arc_sweeps_once_in_the_mocks_time_and_fades(self):
        start, end, fading, gone = self.answer["arc"]
        self.assertEqual(start, [0.0, 1.0])
        self.assertEqual(end, [1.0, 1.0])
        self.assertGreater(fading[1], 0.0)
        self.assertLess(fading[1], 1.0)
        self.assertEqual(gone[1], 0.0)

    def test_a_ring_spreads_and_fades_in_nine_tenths_of_a_second(self):
        before, start, middle, end = self.answer["ring"]
        self.assertEqual(before[1], 0.0)
        self.assertAlmostEqual(start[1], 0.65)
        self.assertGreater(middle[0], 0.5)
        self.assertLess(middle[1], 0.65)
        self.assertEqual(end[1], 0.0)

    def test_the_run_is_the_arc_then_two_rings_and_ends(self):
        sweep = self.answer["sweep"]
        self.assertTrue(sweep["running"])
        self.assertEqual(sweep["length"], 1900, "the second ring starts at 1 s and takes 0.9 s")
        self.assertFalse(sweep["after"])

    def test_nothing_is_clipped(self):
        sweep = self.answer["sweep"]
        self.assertLess(sweep["reach"] + 1.0, sweep["room"] + 0.01, "the outermost ring within what the control paints")

    def test_the_light_keeps_its_colour(self):
        self.assertEqual(self.answer["sweep"]["during"], self.answer["sweep"]["before"])
        self.assertEqual(self.answer["sweep"]["stateAfter"], "idle")

    def test_with_motion_reduced_no_sweep(self):
        self.assertFalse(self.answer["sweep"]["reduced"])

    def test_the_sentence_comes_after_the_wait_and_fades_in(self):
        line = self.answer["line"]
        self.assertEqual(line["waiting"], "What it said")
        self.assertFalse(line["saying"])
        self.assertEqual(line["during"], "A sentence")
        self.assertTrue(line["saying2"])
        self.assertEqual(line["length"], 450)

    def test_what_it_is_told_meanwhile_waits_and_it_returns_the_same_way(self):
        line = self.answer["line"]
        self.assertEqual(line["after"], "Told meanwhile")
        self.assertFalse(line["done"])
        self.assertEqual(line["outLength"], 400)

    def test_reduced_the_sentence_shows_and_returns_without_the_fade(self):
        self.assertEqual(self.answer["line"]["reducedAt"], ["Reduced", False])
        self.assertFalse(self.answer["line"]["reducedBack"][1])
        self.assertNotEqual(self.answer["line"]["reducedBack"][0], "Reduced")

    def test_the_windows_table_answers_as_brands_does(self):
        for date, found, look, top, bottom in self.answer["table"]:
            key = brand.day_look(date // 10000, date // 100 % 100, date % 100)
            self.assertEqual(found, key is not None, date)
            if key:
                self.assertEqual((look, top, bottom), (key,) + brand.DAY_LOOKS[key][:2], date)


class WiringTests(unittest.TestCase):
    def test_the_label_counts_presses_and_keeps_all_else(self):
        self.assertIn("versionText.MouseDown +=", guiscan.settings())

    def test_it_sends_nothing_writes_nothing_and_says_it_with_or_without_motion(self):
        body = guiscan.member_body("SettingsForm", "VersionPressed")
        self.assertIn("stateDot.Sweep();", body)
        self.assertIn('detail.Aside(S("status.aside",', body)
        self.assertIn("stateDot.Sweeping ? AsideAfterMs : 0", body)
        for never in ("Send(", "CallAsync", "bridge", "Save", "File.", "Log", "Motion.Allowed"):
            self.assertNotIn(never, body)

    def test_the_sentence_is_in_every_catalog(self):
        for locale in ("en", "ko", "ar", "de", "es", "fr", "he", "id", "it", "ja", "pl", "pt-BR", "ru", "tr", "uk", "vi", "zh-CN", "zh-TW"):
            catalog = (ROOT / "src/codex_auto_resume/locales" / (locale + ".json")).read_text(encoding="utf-8")
            self.assertIn("status.aside", json.loads(catalog), locale)

    def test_no_document_names_it(self):
        for name in ("README.md", "README.ko.md", "docs/CHANGELOG.md", "docs/CHANGELOG.ko.md", "docs/GUIDE.md", "docs/GUIDE.ko.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for word in ("#EE8468", "#D2453E", "status.aside", "pick it up", "이어 둘게요"):
                self.assertNotIn(word, text, name)


if __name__ == "__main__":
    unittest.main()
