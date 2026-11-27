"""What the icon does with the shell's words about hovering, on the C# host (S6.4d3, P6-DESIGN 3.4 "window").

Twins of tests/test_tray_tip_messages.py's IconCase classes: the originals' own bodies, through `super()`, with only the icon
changed - tests/rustdiff/hosttipicon.py's HostTipTray, the host's TrayIcon (`tip_icon`, everything it asks of Windows
recorded), handed every step the test makes; the shell's calls and timers it made are handed to the test's own stand-in
shell, its card's shows, hides and destroys to the test's own cards.

Not here, and why: ShowTests' `test_the_first_rest_makes_the_card_with_what_the_tooltip_says` reads what the card is made
with (content, held, days); the host's ShowTip makes `new TipCard(TipContent, PopupHeld, Log, Days)` itself and the probe's
MakeTip replaces that making whole, so nothing shows what the host hands it (a gui/ seam that makes the card from those three
would). LiveCardTests show the real card, far off every screen: the host's TipCard calls ShowWindow and the timers of user32
directly (the seam S6.4d2 named), and a window shown is not this seat's to make.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import hosttipicon  # noqa: E402
import surfacehost  # noqa: E402
import test_tray_tip_messages as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class OnHost:
    """The original's setUp with the reference Tray it makes the host's."""

    def setUp(self):
        with mock.patch.object(original.tray, "Tray", hosttipicon.HostTipTray):
            super().setUp()


@ON_HOST
class ShowOnHostTests(OnHost, original.ShowTests):
    def test_the_pointer_resting_shows_the_card_at_the_shells_anchor(self):
        super().test_the_pointer_resting_shows_the_card_at_the_shells_anchor()

    def test_not_over_the_popup_or_the_menu(self):
        super().test_not_over_the_popup_or_the_menu()

    def test_without_version_4_there_is_no_card(self):
        super().test_without_version_4_there_is_no_card()

    test_the_first_rest_makes_the_card_with_what_the_tooltip_says = None      # see the module's head


@ON_HOST
class HideOnHostTests(OnHost, original.HideTests):
    def test_each_way_away_hides_it(self):
        super().test_each_way_away_hides_it()

    def test_the_icons_end_destroys_it(self):
        super().test_the_icons_end_destroys_it()


@ON_HOST
class FlagOnHostTests(OnHost, original.FlagTests):
    def test_windows_tooltip_is_left_out_only_while_the_card_can_be_shown(self):
        super().test_windows_tooltip_is_left_out_only_while_the_card_can_be_shown()

    def test_version_4_drops_windows_tooltip_as_the_icon_is_added_and_after_explorer_restarts(self):
        super().test_version_4_drops_windows_tooltip_as_the_icon_is_added_and_after_explorer_restarts()

    def test_a_refused_version_keeps_windows_tooltip(self):
        super().test_a_refused_version_keeps_windows_tooltip()


@ON_HOST
class FallbackOnHostTests(OnHost, original.FallbackTests):
    def test_a_card_that_cannot_be_made_gives_windows_tooltip_back(self):
        super().test_a_card_that_cannot_be_made_gives_windows_tooltip_back()

    def test_a_card_that_cannot_be_shown_gives_windows_tooltip_back(self):
        super().test_a_card_that_cannot_be_shown_gives_windows_tooltip_back()


@ON_HOST
class SilentShellOnHostTests(OnHost, original.SilentShellTests):
    def test_a_resting_pointer_brings_windows_tooltip_back_after_two_silent_visits(self):
        super().test_a_resting_pointer_brings_windows_tooltip_back_after_two_silent_visits()

    def test_a_pointer_that_only_passed_by_is_not_a_silent_visit(self):
        super().test_a_pointer_that_only_passed_by_is_not_a_silent_visit()

    def test_a_slow_drift_before_the_word_switches_nothing_off_for_good(self):
        super().test_a_slow_drift_before_the_word_switches_nothing_off_for_good()

    def test_the_word_after_a_fallback_turns_the_card_back_on_at_once(self):
        super().test_the_word_after_a_fallback_turns_the_card_back_on_at_once()


if __name__ == "__main__":
    unittest.main()
