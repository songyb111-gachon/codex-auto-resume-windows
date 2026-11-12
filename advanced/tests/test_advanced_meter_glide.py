"""The saved accounts' usage meters glide to a new reading (v0.6.23, the design audit's second round, F11).

The card is made again on every answer, so the window keeps what each meter showed (accountShares, by the account's id
and its window) and hands it to the new meter (AccountMeter.From): its first frame on screen starts one Transition from
there to the reading - paint only, as the Statistics bars glide (OutcomeChart.Changed). A meter with no reading, or the
same one, is simply drawn; with motion reduced it is at once.

The real compiled advanced window is loaded and a meter made in a window of the probe's own, far off the screen and
shown without taking activation (tests/test_gui_v0623_motion.py's head and tail). Nothing is captured.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_meter_glide.py
    (a GUI module: gui_lock.sh)
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pagecase  # noqa: E402
import guiscan  # noqa: E402
import test_gui_v0623_motion as first  # noqa: E402
from test_gui_v0611_access import CSC, POWERSHELL, run_probe  # noqa: E402

METER = pagecase.ROOT / "advanced" / "gui" / "AdvancedMeter.cs"

PROBE_METER = r"""
# ------------------------------------------------------------------ F11: a meter made again with a new reading
function Meter([double]$used, [double]$before) {
    $meter = Make 'AccountMeter'
    $meter.GetType().GetProperty('Used', $instance).SetValue($meter, $used, $null)
    if ($before -ge -1) { $null = Call $meter 'From' @([double]$before) }
    Place $meter 20 20 120 8
    return $meter
}
$m = Meter 80 20
$m.Refresh()
$out.meter = @{ starts = @([bool](P $m 'Growing'), [double](P $m 'Drawn')) }
Pump 400
$out.meter.arrives = @([bool](P $m 'Growing'), [double](P $m 'Drawn'))
$m.Dispose()
$same = Meter 50 50; $same.Refresh()
$out.meter.same = @([bool](P $same 'Growing'), [double](P $same 'Drawn')); $same.Dispose()
$none = Meter -1 40; $none.Refresh()
$out.meter.none = [bool](P $none 'Growing'); $none.Dispose()
$fresh = Meter 30 -5; $fresh.Refresh()
$out.meter.unreadBefore = @([bool](P $fresh 'Growing'), [double](P $fresh 'Drawn')); $fresh.Dispose()
$new = Meter 30 -9; $new.Refresh()
$out.meter.firstTime = [bool](P $new 'Growing'); $new.Dispose()
Reduce $true
$r = Meter 90 10; $r.Refresh()
$out.meter.reduced = @([bool](P $r 'Growing'), [double](P $r 'Drawn')); $r.Dispose()
Reduce $false
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class MeterGlideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = pagecase.compile_window(work)
        script = first.PROBE_HEAD + first.PROBE_HELPERS + PROBE_METER + first.PROBE_TAIL
        cls.answer = run_probe(script, work, 240, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_a_new_reading_glides_from_what_the_meter_showed(self):
        meter = self.answer["meter"]
        growing, drawn = meter["starts"]
        self.assertTrue(growing)
        self.assertGreaterEqual(drawn, 20.0)
        self.assertLess(drawn, 80.0, "part of the way, not simply there")
        self.assertEqual(meter["arrives"], [False, 80.0])

    def test_the_same_reading_and_no_reading_are_simply_drawn(self):
        meter = self.answer["meter"]
        self.assertEqual(meter["same"], [False, 50.0])
        self.assertFalse(meter["none"])

    def test_a_reading_after_none_grows_from_empty_and_a_first_meter_is_drawn(self):
        meter = self.answer["meter"]
        growing, drawn = meter["unreadBefore"]
        self.assertTrue(growing)
        self.assertLess(drawn, 30.0)
        self.assertFalse(meter["firstTime"], "a meter with nothing before it")

    def test_with_motion_reduced_it_is_at_once(self):
        self.assertEqual(self.answer["meter"]["reduced"], [False, 90.0])

    def test_the_card_hands_each_meter_what_its_last_one_showed(self):
        source = METER.read_text(encoding="utf-8")
        line = source[source.index("private void AccountsMeterLine("):]
        self.assertIn("if (key != null && accountShares.TryGetValue(key, out shown)) meter.From(shown);", line)
        self.assertIn("if (key != null) accountShares[key] = meter.Used;", line)
        paint = guiscan.type_body("AccountMeter", source)
        self.assertIn("int width = BarWidth(Drawn, groove.Width, groove.Height);", paint)
        self.assertIn("grow.To(1.0, Motion.Allowed(this));", paint)
        self.assertNotIn("PerformLayout", paint)


if __name__ == "__main__":
    unittest.main()
