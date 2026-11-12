r"""v0.6.23, the second round of the design and motion audit (plans/v0624-audit/audit-design-motion.md, F6-F13).

The owner's standing rule for the design: one design everywhere, the panel's; every control's press and change of state
has a motion, smooth, through the shared pieces; lists stay flat hairline rows. What this round closed:

* F6  - choosing a page changes only the weight its tab's name is drawn in: no tab in the strip moves.

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


if __name__ == "__main__":
    unittest.main()
