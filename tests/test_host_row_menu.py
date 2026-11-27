"""The popup's row menus' submenus, on the C# host (S6.4d, P6-DESIGN 3.4 "window").

Twins of tests/test_popup_row_menu_drawn.py SubmenuTests and RightToLeftSubmenuTests: their own bodies, through `super()`,
with only the menu the test opens changed - tests/rustdiff/hosticon.py's HostMenu, a MenuWindow of the host's with its own
window, made and never shown (HostProbe.cs `menu_messages` with `create`), given the row's numbered entries, the language's
words, the chooser, the popup as its owner and the click-away callback the test gives. Its submenu is the host's own
(OpenChild, ShowBeside), read back through `_child`; the SetForegroundWindow and SetTimer calls it makes are handed to the
test's patched user32. The plan the test points into is the host's (its renderer's MenuLayout); whether it is the
reference's plan is the drawing's question (seat S6.4f).

Nothing is shown: every call that would show a window is recorded instead, and the windows are destroyed after each run.
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
import test_popup_row_menu_drawn as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class OpenOnHost:
    def open(self, locale="en", **extra):
        menu = hosticon.HostMenu(original.menu_entries(**extra), original.l10n.catalog(locale), self.chosen.append,
                                 create=True, owner=7, on_leave=lambda: self.left.append(True), locale=locale,
                                 origin=(300, 200))
        menu.visible = True
        return menu


@ON_HOST
class SubmenuOnHostTests(OpenOnHost, original.SubmenuTests):
    def test_the_arrow_towards_it_opens_the_submenu_its_first_item_in_hand_and_enter_chooses_in_it(self):
        super().test_the_arrow_towards_it_opens_the_submenu_its_first_item_in_hand_and_enter_chooses_in_it()

    def test_enter_opens_it_and_the_arrow_back_and_esc_close_it_one_level_at_a_time(self):
        super().test_enter_opens_it_and_the_arrow_back_and_esc_close_it_one_level_at_a_time()

    def test_home_end_and_letters_reach_into_the_open_submenu(self):
        super().test_home_end_and_letters_reach_into_the_open_submenu()

    def test_the_pointer_resting_on_it_opens_it_after_windows_delay_and_on_another_item_closes_it(self):
        super().test_the_pointer_resting_on_it_opens_it_after_windows_delay_and_on_another_item_closes_it()

    def test_one_submenu_at_a_time_and_a_click_on_its_item_opens_it_at_once(self):
        super().test_one_submenu_at_a_time_and_a_click_on_its_item_opens_it_at_once()

    def test_a_click_in_the_submenu_chooses_and_the_pointer_there_keeps_its_item_in_hand(self):
        super().test_a_click_in_the_submenu_chooses_and_the_pointer_there_keeps_its_item_in_hand()

    def test_closing_the_menu_closes_its_submenu_and_a_click_away_tells_the_popup(self):
        super().test_closing_the_menu_closes_its_submenu_and_a_click_away_tells_the_popup()

    def test_a_submenu_of_an_item_that_cannot_be_used_does_not_open(self):
        super().test_a_submenu_of_an_item_that_cannot_be_used_does_not_open()

    def test_a_screen_reader_hears_an_item_that_opens_a_submenu(self):
        super().test_a_screen_reader_hears_an_item_that_opens_a_submenu()


@ON_HOST
class RightToLeftSubmenuOnHostTests(OpenOnHost, original.RightToLeftSubmenuTests):
    """Right to left (Arabic), every submenu test above with the arrows swapped, as the original runs them."""

    def setUp(self):
        super().setUp()
        # the reference's own key handler called on the menu (Menu._key(menu, key)): the host's is its WM_KEYDOWN
        patcher = unittest.mock.patch.object(original.menuwindow.Menu, "_key",
                                             lambda menu, key: menu._handle(original.menuwindow.WM_KEYDOWN, key, 0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_left_to_right_arrow_does_not_open_it(self):
        super().test_the_left_to_right_arrow_does_not_open_it()

    # the mirrored plan's arrow and text rectangles: the drawing's (seat S6.4f's plan route)
    test_the_layout_is_mirrored_with_the_arrow_at_the_left = None


if __name__ == "__main__":
    unittest.main()
