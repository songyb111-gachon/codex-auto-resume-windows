r"""v0.6.23 (second round, F1/G1 and G5): the Dashboard's day scene holds still under battery saver and a locked session,
and follows the date and the motion setting while the window stays open.

Standard H13: what moves by itself stops under battery saver and while the session is locked. The status light has asked
Motion.Ambient once a second since v0.6.23 (HaloDot.Beat); the scene, added in the same version, did not, and repainted
thirty times a second on battery saver or behind the lock screen. Here the compiled window's SoftDayScene is given the
probe's own battery and lock answers (TaskbarMark.BatterySaverOn, SessionLockedOn) and the probe's own date (DayArt.Clock).
Nothing reads this machine's power state, session or date.

GUI test module (it compiles the window and opens one of its own far off the screen): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import guiscan
from test_gui_v0611_access import compile_window, run_probe
from test_gui_v0623_motion import PROBE_HEAD, PROBE_HELPERS, PROBE_TAIL

PROBE_SCENE = r"""
function Special([datetime]$day) {
    $call = [object[]]@([int]$day.Year, [int]$day.Month, [int]$day.Day, $null, $null, $null)
    return [bool]((T 'Brand').GetMethod('DayLook', $static).Invoke($null, $call))
}
$script:special = $null; $script:plain = $null
$day = [datetime]'2027-01-01'
while ($day.Year -eq 2027 -and ($null -eq $script:special -or $null -eq $script:plain)) {
    if (Special $day) { if ($null -eq $script:special) { $script:special = $day } }
    elseif ($null -eq $script:plain) { $script:plain = $day }
    $day = $day.AddDays(1)
}
$scene = Make 'SoftDayScene'
$form.Controls.Add($scene)
$scene.GetType().GetMethod('Place', $instance).Invoke($scene, [object[]]@($true, 'chuseok', [int]100, [int]10, [int]300, [int]60, [double](60.0 / 66.0), [int]60)) | Out-Null
Pump 60
function Picture {
    $bitmap = New-Object Drawing.Bitmap $scene.Width, $scene.Height
    $g = [Drawing.Graphics]::FromImage($bitmap)
    $e = New-Object Windows.Forms.PaintEventArgs $g, $scene.ClientRectangle
    $null = Call $scene 'OnPaint' @($e)
    $g.Dispose()
    $ms = New-Object IO.MemoryStream
    $bitmap.Save($ms, [Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    return [Convert]::ToBase64String($ms.ToArray())
}
function State {
    $timer = F $scene 'timer'
    return @([bool](P $scene 'Moving'), [bool](P $scene 'Stilled'), [int]$timer.Interval, [bool](F $scene 'clock').IsRunning)
}
function Still([string]$which, [bool]$on) {
    SetSF 'TaskbarMark' $which ([Said]::Answer($on))
    $null = S 'Motion' 'AskAmbientAgain' @()
}
$saver = SF 'TaskbarMark' 'BatterySaverOn'; $lock = SF 'TaskbarMark' 'SessionLockedOn'
Still 'BatterySaverOn' $false; Still 'SessionLockedOn' $false
Pump 1100
$out.free = State
$one = Picture; Pump 300; $out.freeMoves = ($one -ne (Picture))
Still 'BatterySaverOn' $true
Pump 200
$out.saver = State
$one = Picture; Pump 300; $out.saverSame = ($one -eq (Picture))
Still 'BatterySaverOn' $false
Pump 1300
$out.saverOver = State
Still 'SessionLockedOn' $true
Pump 200
$out.locked = State
Still 'SessionLockedOn' $false
Pump 1300
$out.lockOver = State
# Made visible while battery saver is already on: it starts held.
$scene.Visible = $false; Pump 30
Still 'BatterySaverOn' $true
$scene.Visible = $true; Pump 60
$out.startsHeld = State
Still 'BatterySaverOn' $false
Pump 1300
# Reduce motion stops it; turned off, the window's clock (Sync, every second) starts it again.
Reduce $true; Pump 100
$out.reduced = State
Reduce $false
$null = Call $scene 'Sync' @()
$out.reducedOver = State
SetSF 'TaskbarMark' 'BatterySaverOn' $saver; SetSF 'TaskbarMark' 'SessionLockedOn' $lock
$null = S 'Motion' 'AskAmbientAgain' @()

# The date: a plain day, then midnight into a special one, the same day again, then a plain one.
(T 'DayArt').GetField('On', $static).SetValue($null, $true)
$script:today = $script:plain
$oldClock = (T 'DayArt').GetField('Clock', $static).GetValue($null)
(T 'DayArt').GetField('Clock', $static).SetValue($null, [Func[datetime]]{ return $script:today })
$follow = $scene.GetType().GetMethod('Follow', $instance)
function Follow($current) {
    $call = [object[]]@($current)
    $changed = [bool]$follow.Invoke($scene, $call)
    return @($changed, $call[0])
}
$out.follow = @{}
$out.follow.plain = Follow $null
$script:today = $script:special
$out.follow.special = Follow $null
$out.follow.again = Follow ([string]$out.follow.special[1])
$script:today = $script:special.AddHours(13)
$out.follow.sameDay = Follow ([string]$out.follow.special[1])
$script:today = $script:plain.AddDays(1)
if (Special $script:today) { $script:today = $script:plain.AddDays(2) }
$out.follow.after = Follow ([string]$out.follow.special[1])
(T 'DayArt').GetField('Clock', $static).SetValue($null, $oldClock)
(T 'DayArt').GetField('On', $static).SetValue($null, $false)
"""


class SceneHeldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        cls.answer = run_probe(PROBE_HEAD + PROBE_HELPERS + PROBE_SCENE + PROBE_TAIL, work, 240, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    # [moving, stilled, interval, clock running]
    def test_free_it_moves_at_its_frame_rate(self):
        self.assertEqual(self.answer["free"], [True, False, 33, True])
        self.assertTrue(self.answer["freeMoves"])

    def test_battery_saver_holds_it_still_and_it_asks_once_a_second(self):
        self.assertEqual(self.answer["saver"], [True, True, 1000, False], "no frame timer, the clock stopped")
        self.assertTrue(self.answer["saverSame"], "nothing moves while it is held")
        self.assertEqual(self.answer["saverOver"], [True, False, 33, True], "and it moves again by itself")

    def test_a_locked_session_holds_it_still(self):
        self.assertEqual(self.answer["locked"], [True, True, 1000, False])
        self.assertEqual(self.answer["lockOver"], [True, False, 33, True])

    def test_shown_while_held_it_starts_held(self):
        self.assertEqual(self.answer["startsHeld"], [True, True, 1000, False])

    def test_reduce_motion_stops_it_and_turned_off_it_starts_again(self):
        self.assertEqual(self.answer["reduced"][0], False)
        self.assertEqual(self.answer["reducedOver"][:2], [True, False])

    def test_the_scene_follows_the_date(self):
        follow = self.answer["follow"]
        self.assertEqual(follow["plain"], [False, None], "an ordinary day: nothing to change")
        changed, look = follow["special"]
        self.assertTrue(changed, "past midnight into a special day")
        self.assertTrue(look)
        self.assertEqual(follow["again"], [False, look], "asked again the same second")
        self.assertEqual(follow["sameDay"], [False, look], "later the same day")
        self.assertEqual(follow["after"], [True, None], "the next ordinary day takes it away")


class SceneWiringTests(unittest.TestCase):
    def test_the_window_s_clock_follows_the_date_and_the_motion_setting(self):
        body = guiscan.member_body("SettingsForm", "UpdateCountdowns")
        self.assertIn("FollowDayScene();", body)
        self.assertIn("dayScene.Sync();", body)
        follow = guiscan.member_body("SettingsForm", "FollowDayScene")
        self.assertIn("dayScene.Follow(ref dayLook)", follow)
        self.assertIn("JoinDayScene();", follow)
        self.assertIn("PlaceDayScene();", follow)
        self.assertIn("dayScene.Place(false,", follow)

    def test_a_beat_asks_the_ambient_question(self):
        for member in ("Beat", "Sync"):
            self.assertIn("Motion.Ambient", guiscan.member_body("SoftDayScene", member))


if __name__ == "__main__":
    unittest.main()
