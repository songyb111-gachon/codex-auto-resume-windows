r"""v0.6.23, the second round of the design and motion audit (plans/v0624-audit/audit-design-motion.md, F6-F13).

The owner's standing rule for the design: one design everywhere, the panel's; every control's press and change of state
has a motion, smooth, through the shared pieces; lists stay flat hairline rows. What this round closed:

* F6  - choosing a page changes only the weight its tab's name is drawn in: no tab in the strip moves.
* F7  - Pending's Auto-resume switch comes up under the pointer, widens its knob while held and fades halfway into its row
        while its call is awaited past BusyHold's moment (ListSwitchFeel); its knob still moves only on the reply.
* F8  - a tooltip fades out on a window of its own, as a closed menu does (SoftTipWindow.Close, SoftLayerFade).

The real compiled window is loaded and its controls are made in a window of the probe's own, far off the screen and shown
without taking activation, as tests/test_gui_v0623_motion.py does (its head, tail and helpers are this module's). Nothing
is captured and nothing is drawn on the screen: the motion is counted in frames and states, the looks read from pixels
drawn into bitmaps.

GUI test module (it compiles the window and opens one of its own): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import json
import unittest

import guiscan
import test_gui_v0623_motion as first

TABS = ("Overview", "Pending", "History", "Statistics", "Diagnostics", "Settings", "Advanced")

PROBE_TABS = r"""
# ------------------------------------------------------------------ F6: the tab strip, each page chosen
$strip = Make 'SoftFlow'
$strip.FlowDirection = 'LeftToRight'; $strip.WrapContents = $false; $strip.AutoSize = $true
$strip.Location = New-Object Drawing.Point 0, 0
$form.Controls.Add($strip)
$tabs = @()
foreach ($name in (ConvertFrom-Json '@TABS@')) {
    $tab = Make 'NavButton'
    $tab.Text = [string]$name
    $tab.Font = S 'Soft' 'RoleFont' @('nav')
    $tab.AutoSize = $true; $tab.AutoSizeMode = 'GrowAndShrink'
    $tab.Padding = New-Object Windows.Forms.Padding 18, 8, 18, 8
    $tab.Margin = New-Object Windows.Forms.Padding 0, 0, 2, 0
    $strip.Controls.Add($tab)
    $tabs += ,$tab
}
Pump 30
$out.tabs = @{ chosen = @() }
for ($chosen = -1; $chosen -lt $tabs.Count; $chosen++) {
    # As ShowPage sets them: the chosen page's name in nav_current, every other in nav.
    for ($i = 0; $i -lt $tabs.Count; $i++) {
        $tabs[$i].Font = S 'Soft' 'RoleFont' @($(if ($i -eq $chosen) { 'nav_current' } else { 'nav' }))
        $tabs[$i].GetType().GetProperty('Current', $instance).SetValue($tabs[$i], ($i -eq $chosen), $null)
    }
    $strip.PerformLayout()
    $out.tabs.chosen += ,@(($tabs | ForEach-Object { $_.Left }))
}
$any = New-Object Drawing.Size ([int]::MaxValue), ([int]::MaxValue)
$out.tabs.heavier = @(($tabs | ForEach-Object {
    [int]([Windows.Forms.TextRenderer]::MeasureText($_.Text, (S 'Soft' 'RoleFont' @('nav_current')), $any).Width -
          [Windows.Forms.TextRenderer]::MeasureText($_.Text, (S 'Soft' 'RoleFont' @('nav')), $any).Width) }))
$vertical = Make 'NavButton'; $vertical.Text = 'Notifications'; SetF $vertical 'Vertical' $true
$vertical.Font = S 'Soft' 'RoleFont' @('nav')
$out.tabs.vertical = @([int]$vertical.GetPreferredSize([Drawing.Size]::Empty).Width)
$vertical.Font = S 'Soft' 'RoleFont' @('nav_current')
$out.tabs.vertical += [int]$vertical.GetPreferredSize([Drawing.Size]::Empty).Width
""".replace("@TABS@", json.dumps(TABS))

PROBE_FEEL = r"""
# ------------------------------------------------------------------ F7: the Pending list's switch
$host7 = New-Object Windows.Forms.Panel; Place $host7 20 20 200 120; Pump 30
$cellOf = [Func[string, Drawing.Rectangle]]{ param($key) if ($key -eq 'b') { return New-Object Drawing.Rectangle 10, 60, 50, 24 }; return New-Object Drawing.Rectangle 10, 10, 50, 24 }
$script:waiting = $true
$feel = MakeWith 'ListSwitchFeel' @($host7, $cellOf, [Func[bool]]{ return [bool]$script:waiting })
function Feel([string]$key) { return @([double](Call $feel 'Hover' @($key)), [double](Call $feel 'Press' @($key)), [double](Call $feel 'Live' @($key))) }
$out.feel = @{ rest = (Feel 'a') }
$null = Call $feel 'Over' @('a')
$out.feel.overStarts = @([bool](P $feel 'Running'), [string](P $feel 'Hot'))
Pump 400
$out.feel.over = (Feel 'a'); $out.feel.otherOver = (Feel 'b')
$null = Call $feel 'Held' @('a')
$out.feel.heldLength = [int](F (F $feel 'down') 'length')
Pump 300
$out.feel.held = (Feel 'a')
$null = Call $feel 'Held' @($null)
Pump 300
$out.feel.letGo = (Feel 'a')
$null = Call $feel 'Over' @('b')
Pump 400
$out.feel.moved = @((Feel 'a'), (Feel 'b'))
$null = Call $feel 'Over' @($null)
Pump 400
$out.feel.left = (Feel 'b')
# A call still running when BusyHold's moment is over: the switch fades halfway into its row, and comes back on the answer.
$null = S 'BusyHold' 'Begin' @([Action]$null)
$null = Call $feel 'Awaiting' @('a', $true)
$out.feel.inTheMoment = (Feel 'a')
$null = S 'BusyHold' 'Lapse' @()
$out.feel.lapsed = [bool](P $feel 'Running')
Pump 400
$out.feel.awaited = (Feel 'a')
$null = Call $feel 'Awaiting' @('a', $false)
Pump 400
$out.feel.answered = (Feel 'a')
# A call answered within the moment shows nothing.
$null = S 'BusyHold' 'Begin' @([Action]$null)
$null = Call $feel 'Awaiting' @('b', $true)
$script:waiting = $false
$null = Call $feel 'Awaiting' @('b', $false)
$null = S 'BusyHold' 'End' @()
Pump 300
$out.feel.inTime = @((Feel 'b'), [bool](P $feel 'Running'))
$script:waiting = $true
# With motion reduced it is all at once.
Reduce $true
$null = Call $feel 'Awaiting' @('a', $true)
$null = Call $feel 'Over' @('a')
$out.feel.reduced = @((Feel 'a'), [bool](P $feel 'Running'))
$null = Call $feel 'Awaiting' @('a', $false)
$null = Call $feel 'Over' @($null)
Reduce $false
$null = Call $feel 'Forget' @('a')
$out.feel.forgotten = (Feel 'a')
$feel.Dispose()
# The switch drawn by those three, and at rest exactly as the switch has always been drawn.
$track = New-Object Drawing.Rectangle 4, 4, 40, 22
function SwitchPixels([double]$live, [double]$hover, [double]$press) {
    return Pixels { param($g) $null = S 'Soft' 'SwitchLive' @($g, $track, [double]0, $live, $hover, $press, [Drawing.Color]::White, $false) } 48 30
}
$atRest = Pixels { param($g) $null = S 'Soft' 'SwitchAt' @($g, $track, [double]0, $true, [Drawing.Color]::White) } 48 30
$out.feel.drawn = @{ rest = (Same $atRest (SwitchPixels 1 0 0)); hover = (Same $atRest (SwitchPixels 1 1 0)); press = (Same $atRest (SwitchPixels 1 0 1));
                     awaited = (Same $atRest (SwitchPixels 0 0 0)) }
"""

PROBE_TIP = r"""
# ------------------------------------------------------------------ F8: the tooltip leaving
$label8 = New-Object Windows.Forms.Label; $label8.Text = 'Words'; Place $label8 20 200 200 24; Pump 20
$tip8 = Make 'SoftTip'
$null = Call $tip8 'Open' @($label8, 'A line too long for its place', (New-Object Drawing.Size 180, 20))
Pump 400
$live = [int](SF 'SoftLayerFade' 'Live')
$null = Call $label8 'OnMouseLeave' @($None)
$out.tipOut = @{ ghost = ([int](SF 'SoftLayerFade' 'Live') - $live); gone = ((P $tip8 'Card') -eq $null) }
Pump 400
$out.tipOut.ghostGone = ([int](SF 'SoftLayerFade' 'Live') - $live)
Reduce $true
$null = Call $tip8 'Open' @($label8, 'Words', (New-Object Drawing.Size 80, 20))
$live = [int](SF 'SoftLayerFade' 'Live')
$null = Call $label8 'OnMouseLeave' @($None)
$out.tipOut.reduced = @(([int](SF 'SoftLayerFade' 'Live') - $live), ((P $tip8 'Card') -eq $null))
Reduce $false
$tip8.Dispose()
"""


class TabStripTests(first.Probed):
    """F6: the strip laid out with no page chosen and then with each page chosen in turn."""

    sections = (first.PROBE_HELPERS, PROBE_TABS)

    def test_the_heavier_weight_is_wider_so_the_strip_had_something_to_hold(self):
        self.assertGreater(max(self.answer["tabs"]["heavier"]), 0, "nav_current draws these names no wider than nav")

    def test_no_tab_moves_whichever_page_is_chosen(self):
        laid = self.answer["tabs"]["chosen"]
        self.assertEqual(len(laid), len(TABS) + 1)
        for chosen, lefts in enumerate(laid[1:]):
            with self.subTest(chosen=TABS[chosen]):
                self.assertEqual(lefts, laid[0], "a tab moved when %s was chosen" % TABS[chosen])

    def test_a_section_in_settings_column_is_sized_by_its_words_alone(self):
        light, heavy = self.answer["tabs"]["vertical"]
        self.assertLess(light, heavy, "a section in its column is measured in the weight it has, as Button measures")

    def test_show_page_still_sets_the_chosen_name_in_the_heavier_weight(self):
        show = guiscan.member_body("SettingsForm", "ShowPage")
        self.assertIn('pair.Value.Font = Soft.RoleFont(pair.Key == name ? "nav_current" : "nav");', show)
        size = guiscan.member_body("NavButton", "GetPreferredSize")
        self.assertIn('Soft.RoleFont("nav")', size)
        self.assertIn('Soft.RoleFont("nav_current")', size)


class PendingSwitchTests(first.Probed):
    """F7: ListSwitchFeel, made in the probe's window, and the switch the list draws with it."""

    sections = (first.PROBE_HELPERS, PROBE_FEEL)

    def test_at_rest_the_switch_is_the_switch_it_always_was(self):
        feel = self.answer["feel"]
        self.assertEqual(feel["rest"], [0.0, 0.0, 1.0])
        self.assertTrue(feel["drawn"]["rest"])

    def test_it_comes_up_under_the_pointer_and_goes_back_when_the_pointer_moves_on(self):
        feel = self.answer["feel"]
        self.assertEqual(feel["overStarts"], [True, "a"])
        self.assertEqual(feel["over"][0], 1.0)
        self.assertEqual(feel["otherOver"][0], 0.0, "only the switch under the pointer")
        self.assertEqual(feel["moved"], [[0.0, 0.0, 1.0], [1.0, 0.0, 1.0]])
        self.assertEqual(feel["left"][0], 0.0)
        self.assertFalse(feel["drawn"]["hover"], "and it is drawn up")

    def test_held_down_its_knob_widens_in_the_press_time(self):
        feel = self.answer["feel"]
        self.assertEqual(feel["heldLength"], first.brand.MOTION["press_ms"])
        self.assertEqual(feel["held"][1], 1.0)
        self.assertEqual(feel["letGo"][1], 0.0)
        self.assertFalse(feel["drawn"]["press"], "and the knob is drawn wider")

    def test_an_answer_awaited_past_the_moment_fades_it_and_the_answer_brings_it_back(self):
        feel = self.answer["feel"]
        self.assertEqual(feel["inTheMoment"][2], 1.0, "BusyHold's moment first")
        self.assertTrue(feel["lapsed"])
        self.assertEqual(feel["awaited"][2], 0.0)
        self.assertEqual(feel["answered"][2], 1.0)
        self.assertFalse(feel["drawn"]["awaited"], "and it is drawn halfway into its row")

    def test_an_answer_in_time_shows_nothing(self):
        self.assertEqual(self.answer["feel"]["inTime"], [[0.0, 0.0, 1.0], False])

    def test_with_motion_reduced_it_is_all_at_once(self):
        self.assertEqual(self.answer["feel"]["reduced"], [[1.0, 0.0, 0.0], False])

    def test_a_row_gone_is_forgotten(self):
        self.assertEqual(self.answer["feel"]["forgotten"], [0.0, 0.0, 1.0])

    def test_the_list_draws_its_switch_through_it_and_the_knob_moves_only_on_the_reply(self):
        draw = guiscan.member_body("SettingsForm", "DrawResumeBox")
        for needle in ("resumeFeel.Hover(id)", "resumeFeel.Press(id)", "resumeFeel.Live(id)",
                       "Soft.SwitchLive(g, track, on, live, hover, press, ground, mirrored)"):
            self.assertIn(needle, draw)
        self.assertIn("glide.Running) on = glide.Value;", draw, "where the knob is is still the reply's glide alone")
        toggle = guiscan.member_body("SettingsForm", "ToggleAutoResume")
        self.assertLess(toggle.index("resumeFeel.Awaiting(id, false);"), toggle.index("RefreshAfterChange();"))
        self.assertIn("resumeFeel.Awaiting(id, true);", toggle)
        self.assertNotIn("resumeGlides", toggle, "the press moves no knob")
        feel = guiscan.type_body("ListSwitchFeel")
        self.assertIn("BusyHold.Join(this)", feel)
        self.assertNotIn("new Bitmap", feel)
        self.assertNotIn("PerformLayout", feel)


class TooltipLeavingTests(first.Probed):
    """F8: the tooltip closed by the pointer leaving."""

    sections = (first.PROBE_HELPERS, PROBE_TIP)

    def test_a_tooltip_closed_fades_out_on_a_window_of_its_own_and_leaves_nothing(self):
        tip = self.answer["tipOut"]
        self.assertEqual(tip["ghost"], 1, "the closing picture fades out on a window of its own")
        self.assertTrue(tip["gone"], "the tip itself is closed at once")
        self.assertEqual(tip["ghostGone"], 0)

    def test_with_motion_reduced_a_tooltip_is_simply_gone(self):
        self.assertEqual(self.answer["tipOut"]["reduced"], [0, True])

    def test_it_is_the_menus_fade_and_no_other(self):
        close = guiscan.member_body("SoftTipWindow", "Close")
        self.assertIn("new SoftLayerFade(memory, dib, previous,", close)
        self.assertIn("card.Close(fade);", guiscan.member_body("SoftTip", "Close"))


if __name__ == "__main__":
    unittest.main()
