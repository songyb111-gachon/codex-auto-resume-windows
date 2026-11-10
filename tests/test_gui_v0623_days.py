r"""v0.6.23: the days with a look of their own, and the seven presses (both only by the owner's word).

The table is brand's and is generated into the window; nothing here reads today's date, so no test can fail because of the day
it runs on or the years that have passed. Part GUI (it compiles the window): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import datetime
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import guiscan
from codex_auto_resume import brand
from codex_auto_resume.ui import popup as tray_popup
from codex_auto_resume.ui.tray import animation
from codex_auto_resume.ui.tray.motion import IconFrames
from test_gui_v0611_access import compile_window, run_probe
from test_gui_v0623_motion import PROBE_HEAD, PROBE_HELPERS, PROBE_TAIL

ROOT = Path(__file__).resolve().parents[1]

# KASI's calendar converter (astro.kasi.re.kr), lunar 1/1 and 8/15, read once by hand into this list as well as the table.
KASI = {2026: ("0217", "0925"), 2027: ("0207", "0915"), 2028: ("0127", "1003"), 2029: ("0213", "0922"), 2030: ("0203", "0912"),
        2031: ("0123", "1001"), 2032: ("0211", "0919"), 2033: ("0131", "0908"), 2034: ("0219", "0927"), 2035: ("0208", "0916"),
        2036: ("0128", "1004"), 2037: ("0215", "0924"), 2038: ("0204", "0913"), 2039: ("0124", "1002"), 2040: ("0212", "0921")}


class TableTests(unittest.TestCase):
    def test_the_days_of_every_year(self):
        for year in (2026, 2031, 2041, 2099):
            self.assertEqual(brand.day_look(year, 9, 6), ("#C2553B", "confetti"))
            self.assertEqual(brand.day_look(year, 1, 1), ("#A67C1A", "sparkle"))
            self.assertEqual(brand.day_look(year, 12, 24), ("#1F6B4A", "snow"))
            self.assertEqual(brand.day_look(year, 12, 25), ("#1F6B4A", "snow"))

    def test_the_lunar_days_are_the_official_dates(self):
        for year, (seollal, chuseok) in KASI.items():
            self.assertEqual(brand.day_look(year, int(seollal[:2]), int(seollal[2:])), ("#A32D2D", "sparkle"), year)
            self.assertEqual(brand.day_look(year, int(chuseok[:2]), int(chuseok[2:])), ("#26215C", "moon"), year)

    def test_past_the_tables_last_year_nothing_lunar_is_shown(self):
        day = datetime.date(2041, 1, 2)
        while day.year == 2041:
            if (day.month, day.day) not in ((9, 6), (12, 24), (12, 25)):
                self.assertIsNone(brand.day_look(day.year, day.month, day.day), day)
            day += datetime.timedelta(days=1)

    def test_an_ordinary_day_has_none(self):
        self.assertIsNone(brand.day_look(2026, 11, 10))
        self.assertIsNone(brand.day_look(2030, 2, 4), "the day after is ordinary")

    def test_a_days_look_runs_midnight_to_midnight_by_the_local_date(self):
        for clock in ((2026, 9, 6, 0, 0, 1), (2026, 9, 6, 23, 59, 59)):
            self.assertEqual(brand.day_look_at(datetime.datetime(*clock).timestamp())[1], "confetti")
        self.assertIsNone(brand.day_look_at(datetime.datetime(2026, 9, 7, 0, 0, 1).timestamp()))

    def test_the_window_has_the_same_table(self):
        method = guiscan.member_body("Brand", "DayLook")
        for month, day, body, motif in brand.FIXED_DAYS:
            self.assertIn('if (yearly == %d) { body = "%s"; motif = "%s"; return true; }' % (month * 100 + day, body, motif), method)
        for body, motif, dates in brand.LUNAR_DAYS:
            for year, month, day in dates:
                self.assertIn("whole == %d" % (year * 10000 + month * 100 + day), method)
            self.assertIn('{ body = "%s"; motif = "%s"; return true; }' % (body, motif), method)


class IconTests(unittest.TestCase):
    def pixel(self, frames, frame, x, y):
        at = (y * frames.size + x) * 4
        return tuple(frame[at:at + 4])

    def test_an_ordinary_icon_is_the_icon_it_always_was(self):
        self.assertEqual(IconFrames(32, look=None).ground, IconFrames(32).ground)

    def test_the_body_takes_the_days_colour(self):
        frames = IconFrames(32, look=("#C2553B", "confetti"))
        blue, green, red, alpha = self.pixel(frames, frames.ground, 5, 26)
        self.assertEqual(alpha, 255)
        self.assertEqual((red, green, blue), brand.rgb("#C2553B"))

    def test_the_state_colour_stays_the_states(self):
        look = IconFrames(32, look=("#26215C", "moon"))
        plain = IconFrames(32)
        head = (10, 200, 90)
        one, other = look.compose(0, head), plain.compose(0, head)
        (left, top, right, bottom), rows = plain.heads[0]
        whole = 0
        for y, row in enumerate(rows):
            for x, sample in enumerate(row):
                if sample[1] == sample[0] and sample[0] > 0:
                    whole += 1
                    self.assertEqual(self.pixel(look, one, left + x, top + y), self.pixel(plain, other, left + x, top + y))
        self.assertGreater(whole, 0, "no pixel was all head")

    def test_the_mark_shows_where_the_icon_has_room_and_not_where_it_has_none(self):
        def top_right(size):
            with_mark = IconFrames(size, look=("#26215C", "moon")).ground
            cx = int((1.66) * size / 2)
            cy = int((1 - 0.66) * size / 2)
            at = (cy * size + cx) * 4
            return tuple(reversed(with_mark[at:at + 3]))
        self.assertEqual(top_right(32), brand.rgb("#F6EBC9"))
        self.assertEqual(top_right(16), brand.rgb("#26215C"))

    def test_every_mark_stays_clear_of_the_ring_and_the_head(self):
        place = brand.MOTIF_ON_ICON
        reach = place["half"] * 2 ** 0.5
        self.assertGreater(((place["x"] ** 2 + place["y"] ** 2) ** 0.5) - place["half"], brand.ICON_SHAPE["ring_outer"])
        self.assertLess(reach, 1.0)


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
        self.assertEqual(self.look(True), ("#C2553B", "confetti"))
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


class PopupTests(unittest.TestCase):
    def plan(self, motif):
        vm = tray_popup.view_model([], {"enabled": True}, {}, 1800000000.0)
        if motif:
            vm["motif"] = motif
        return tray_popup.layout(vm, 1.0, lambda role, text, width, wrap: (min(width, 100), 16))

    def test_the_header_carries_the_days_mark(self):
        items = [item for item in self.plan("sparkle")["items"] if item["kind"] == "motif"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["motif"], "sparkle")

    def test_an_ordinary_header_has_none(self):
        self.assertEqual([item for item in self.plan(None)["items"] if item["kind"] == "motif"], [])

    def test_the_popup_asks_only_when_it_was_told_to_and_the_colours_are_the_states(self):
        rebuild = (ROOT / "src/codex_auto_resume/ui/popup/window.py").read_text(encoding="utf-8")
        self.assertIn('if self.days and not self._contrast and self._design != "classic":', rebuild)
        self.assertEqual(tray_popup.Popup.days, False)


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

$dot = Make 'HaloDot'; Place $dot 20 20 60 60; Pump 30
$null = Call $dot 'Ripple' @()
$out.ripple = @{ running = [bool](P $dot 'Rippling'); length = [int](F (F $dot 'ripple') 'length') }
$bitmap = New-Object Drawing.Bitmap 60, 60
$dot.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, 60, 60))
$bitmap.Dispose()
Pump 1300
$out.ripple.after = [bool](P $dot 'Rippling')
Reduce $true
$null = Call $dot 'Ripple' @()
$out.ripple.reduced = [bool](P $dot 'Rippling')
Reduce $false

$line = Make 'AsideLabel'; $line.Text = 'What it said'; Place $line 20 100 300 24; Pump 20
$null = Call $line 'Aside' @('A sentence', [int]300)
$out.line = @{ during = [string]$line.Text; saying = [bool](P $line 'Saying') }
$line.Text = 'Told meanwhile'
$out.line.stillSaying = [string]$line.Text
Pump 600
$out.line.after = [string]$line.Text
$out.line.done = [bool](P $line 'Saying')
$body = ''; $motif = ''
$days = @(20260906, 20260907, 20270101, 20281003, 20281004, 20401225, 20410212, 20400212, 20330908)
$out.table = @()
$method = (T 'Brand').GetMethod('DayLook', $static)
foreach ($date in $days) {
    $call = [object[]]@([int][math]::Floor($date / 10000), [int][math]::Floor(($date % 10000) / 100), [int]($date % 100), $null, $null)
    $found = $method.Invoke($null, $call)
    $out.table += ,@($date, [bool]$found, $call[3], $call[4])
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
        self.assertEqual(self.answer["broken"], [False] * 3 + [False] * 5 + [False])

    def test_one_ring_of_about_a_second(self):
        ripple = self.answer["ripple"]
        self.assertTrue(ripple["running"])
        self.assertEqual(ripple["length"], 1000)
        self.assertFalse(ripple["after"], "once, and it ends")

    def test_with_motion_reduced_no_ring(self):
        self.assertFalse(self.answer["ripple"]["reduced"])

    def test_the_line_says_it_and_returns_to_what_it_was_told(self):
        line = self.answer["line"]
        self.assertEqual(line["during"], "A sentence")
        self.assertTrue(line["saying"])
        self.assertEqual(line["stillSaying"], "A sentence", "what it is told meanwhile waits")
        self.assertEqual(line["after"], "Told meanwhile")
        self.assertFalse(line["done"])

    def test_the_windows_table_answers_as_brands_does(self):
        for date, found, body, motif in self.answer["table"]:
            look = brand.day_look(date // 10000, date // 100 % 100, date % 100)
            self.assertEqual(found, look is not None, date)
            if look:
                self.assertEqual((body, motif), look, date)


class WiringTests(unittest.TestCase):
    def test_the_label_counts_presses_and_keeps_all_else(self):
        self.assertIn("versionText.MouseDown +=", guiscan.settings())

    def test_it_sends_nothing_writes_nothing_and_says_it_with_or_without_motion(self):
        body = guiscan.member_body("SettingsForm", "VersionPressed")
        self.assertIn("stateDot.Ripple();", body)
        self.assertIn('detail.Aside(S("status.aside",', body)
        for never in ("Send(", "CallAsync", "bridge", "Save", "File.", "Log", "Motion.Allowed"):
            self.assertNotIn(never, body)

    def test_the_sentence_is_in_every_catalog(self):
        import json
        for path in (ROOT / "src/codex_auto_resume/locales").glob("*.json"):
            self.assertIn("status.aside", json.loads(path.read_text(encoding="utf-8")), path.name)

    def test_no_document_names_it(self):
        for name in ("README.md", "README.ko.md", "docs/CHANGELOG.md", "docs/CHANGELOG.ko.md", "docs/GUIDE.md", "docs/GUIDE.ko.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for word in ("#C2553B", "#A32D2D", "status.aside", "pick it up", "이어 둘게요"):
                self.assertNotIn(word, text, name)


if __name__ == "__main__":
    unittest.main()
