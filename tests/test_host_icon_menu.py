"""The icon's right-click menu - the drawn one, Windows' own as the fallback, and a choice in either - on the C# host (S6.4d).

Twins of tests/test_tray_menu_drawn.py ParityTests and FallbackTests: their own bodies, through `super()`, with the module's
`tray.Tray` made tests/rustdiff/hosticon.py's HostTray (each member one step of gui/TrayIcon.cs / gui/TrayMenu.cs in the
host's probe, HostProbe.cs `icon_steps`) and the MENU_* numbers the host's. The test's drawn menu (FakeDrawn, or what its
patched `popup.Menu` makes) is asked each opening the host makes, its `on_choose` replays the host's own opening, and its
patched user32 is handed exactly the calls the host made of Windows' menu, so `appended`, `tracked`, `shown` and
`destroyed` are the host's. The plans the parity test compares with (popup.menu_layout) and the items it expects
(tray.menu_items) are the reference's - or, under CODEX_AR_CORE=rust, the shim's.

Nothing is shown: the icon has no window and no shell icon, the drawn menu is the test's own object, and Windows' menu is
recorded, never made.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import hosticon  # noqa: E402
import surfacehost  # noqa: E402
import test_tray_menu_drawn as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class TrayOnHost:
    """The reference tray package with its Tray and its MENU_* numbers the host's; everything else is the reference's."""

    def __init__(self, reference):
        self._reference = reference
        self.Tray = hosticon.HostTray
        for name, value in hosticon.menu_ids().items():
            setattr(self, name, value)

    def __getattr__(self, name):
        return getattr(self._reference, name)


def on_host(case):
    patcher = unittest.mock.patch.object(original, "tray", TrayOnHost(original.tray))
    patcher.start()
    case.addCleanup(patcher.stop)


@ON_HOST
class ParityOnHostTests(original.ParityTests):
    def setUp(self):
        on_host(self)

    def test_the_drawn_menu_has_every_item_of_windows_menu_in_its_order_with_its_state(self):
        super().test_the_drawn_menu_has_every_item_of_windows_menu_in_its_order_with_its_state()

    def test_the_icon_hands_the_drawn_menu_exactly_what_windows_menu_would_get(self):
        super().test_the_icon_hands_the_drawn_menu_exactly_what_windows_menu_would_get()

    def test_a_choice_in_the_drawn_menu_reaches_the_action_windows_menu_reaches(self):
        super().test_a_choice_in_the_drawn_menu_reaches_the_action_windows_menu_reaches()

    # routed by the shim (tray.menu_items is the host's TrayIcon.MenuItems under CODEX_AR_CORE=rust): a row's host_tests
    test_the_items_are_the_menu_windows_has_always_shown = None


@ON_HOST
class FallbackOnHostTests(original.FallbackTests):
    def setUp(self):
        on_host(self)

    def test_an_icon_without_its_own_window_shows_windows_menu(self):
        super().test_an_icon_without_its_own_window_shows_windows_menu()

    def test_the_drawn_menu_is_shown_and_windows_is_not(self):
        super().test_the_drawn_menu_is_shown_and_windows_is_not()

    def test_a_drawn_menu_that_breaks_gives_way_to_windows_for_good_and_says_so_once(self):
        super().test_a_drawn_menu_that_breaks_gives_way_to_windows_for_good_and_says_so_once()

    def test_an_opening_refused_the_foreground_is_windows_menu_that_once(self):
        super().test_an_opening_refused_the_foreground_is_windows_menu_that_once()

    def test_the_drawn_menu_is_made_on_the_first_right_click_and_goes_with_the_icon(self):
        super().test_the_drawn_menu_is_made_on_the_first_right_click_and_goes_with_the_icon()


class PopupOnHost:
    """The reference popup package with menu_step, menu_end and menu_letter the host's MenuPlan; the rest the reference's."""

    def __init__(self, reference):
        self._reference = reference
        self.menu_step = hosticon.HostMenuKeys.menu_step
        self.menu_end = hosticon.HostMenuKeys.menu_end
        self.menu_letter = hosticon.HostMenuKeys.menu_letter

    def __getattr__(self, name):
        return getattr(self._reference, name)


@ON_HOST
class KeyOnHostTests(original.KeyTests):
    def setUp(self):
        patcher = unittest.mock.patch.object(original, "popup", PopupOnHost(original.popup))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_arrows_go_round_the_usable_items_and_never_land_on_the_status_or_a_line(self):
        super().test_arrows_go_round_the_usable_items_and_never_land_on_the_status_or_a_line()

    def test_a_letter_chooses_the_one_item_it_starts_and_steps_through_several(self):
        super().test_a_letter_chooses_the_one_item_it_starts_and_steps_through_several()


@ON_HOST
class BehaviourOnHostTests(original.BehaviourTests):
    """The drawn menu's handlers: the test's setUp, then its menu made the host's (hosticon.HostMenu), given what the
    reference's was given - entries, words, chooser, open - with the same `_push` and `_tell` patched on it."""

    def setUp(self):
        super().setUp()
        reference = self.menu
        self.menu = hosticon.HostMenu(reference.entries, reference.strings, reference.on_choose)
        self.menu.visible = True
        self.menu._plan = reference._plan
        for name, value in (("_push", lambda: None), ("_tell", self.told.append)):
            patcher = unittest.mock.patch.object(self.menu, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_down_and_enter_choose_the_item_and_close_first(self):
        super().test_down_and_enter_choose_the_item_and_close_first()

    def test_home_end_and_up(self):
        super().test_home_end_and_up()

    def test_enter_with_nothing_in_hand_does_nothing(self):
        super().test_enter_with_nothing_in_hand_does_nothing()

    def test_esc_alt_and_f10_close_it_choosing_nothing(self):
        super().test_esc_alt_and_f10_close_it_choosing_nothing()

    def test_a_letter_chooses_or_moves(self):
        super().test_a_letter_chooses_or_moves()

    def test_the_pointer_puts_an_item_in_hand_and_either_button_s_release_chooses_it(self):
        super().test_the_pointer_puts_an_item_in_hand_and_either_button_s_release_chooses_it()

    def test_leaving_it_puts_nothing_in_hand(self):
        super().test_leaving_it_puts_nothing_in_hand()

    def test_a_click_elsewhere_and_losing_the_focus_close_it(self):
        super().test_a_click_elsewhere_and_losing_the_focus_close_it()

    def test_a_screen_reader_hears_the_item_in_hand_move(self):
        super().test_a_screen_reader_hears_the_item_in_hand_move()

    def test_what_a_screen_reader_is_told_is_each_item_by_name_role_and_state(self):
        super().test_what_a_screen_reader_is_told_is_each_item_by_name_role_and_state()


if __name__ == "__main__":
    unittest.main()
