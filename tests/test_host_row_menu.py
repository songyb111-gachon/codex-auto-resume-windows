"""The popup's row menus and their submenus, on the C# host (S6.4d, P6-DESIGN 3.4 "window").

Twins of tests/test_popup_row_menu_drawn.py ParityTests, PopupFocusTests, the scan of FallbackTests, WindowsTests (below),
SubmenuTests and RightToLeftSubmenuTests. The submenu twins run their own bodies, through `super()`,
with only the menu the test opens changed - tests/rustdiff/hosticon.py's HostMenu, a MenuWindow of the host's with its own
window, made and never shown (HostProbe.cs `menu_messages` with `create`), given the row's numbered entries, the language's
words, the chooser, the popup as its owner and the click-away callback the test gives. Its submenu is the host's own
(OpenChild, ShowBeside), read back through `_child`; the SetForegroundWindow and SetTimer calls it makes are handed to the
test's patched user32. The plan the test points into is the host's (its renderer's MenuLayout); whether it is the
reference's plan is the drawing's question (seat S6.4f).

Parity and the popup's focus: the original bodies, through `super()`, with `popup.Popup` replaced by
tests/rustdiff/hostpopup.py's HostPopup - the host's PopupWindow (HostProbe.cs `popup_steps`) handed the test's model as the
core's popup, its row menu the test's FakeDrawn asked back, what it posts handed to the test's `_run`. The numbering is the
host's MenuPlan.Numbered (`menu_numbered`). WindowsTests: the row menu made as the live host's icon makes it (MenuWindow),
created as the test's opening creates it and never shown (`row_menu_class`), and the submenu arrow drawn offscreen by the
host's own renderer (`menu_arrow`): the same assertions over the probe's answers.

Not here, and why: ParityTests' choice compared with Windows' menu and FallbackTests' three openings of Windows' own menu -
PopupWindow.ContextMenu shows that menu by calling user32 directly, not through SurfaceScreen, so the probe stops before it
(it never runs unrecorded); they wait for that half to be probe-safe (gui/, seat S6.3d). The plan's placement and the
mirrored arrow are the drawing's (seat S6.4f).

Nothing is shown: every call that would show a window is recorded instead, and the windows are destroyed after each run.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import hosticon  # noqa: E402
import hostpopup  # noqa: E402
import surfacehost  # noqa: E402
import test_popup_row_menu_drawn as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class PopupOnHost:
    """`popup.Popup` is the host's popup for the test's length: the original's shown_popup makes a HostPopup."""

    def setUp(self):
        super().setUp()
        patcher = unittest.mock.patch.object(original.popup, "Popup", hostpopup.HostPopup)
        patcher.start()
        self.addCleanup(patcher.stop)


def host_numbered(entries):
    """menu_numbered answered by the host's MenuPlan.Numbered: the numbered entries and {command: action}."""
    found = surfacehost.SERVE.ask("menu_numbered", entries=entries)
    actions = {int(number): (tuple(action) if isinstance(action, list) else action) for number, action in found["actions"]}
    return hostpopup._ids(found["numbered"]), actions


@ON_HOST
class ParityOnHostTests(PopupOnHost, original.ParityTests):
    def test_the_drawn_menu_is_handed_the_row_s_items_in_their_order_with_their_state(self):
        super().test_the_drawn_menu_is_handed_the_row_s_items_in_their_order_with_their_state()

    def test_every_leaf_is_numbered_depth_first_as_windows_menu_numbers_its_commands(self):
        with unittest.mock.patch.object(original.popup, "menu_numbered", host_numbered):
            super().test_every_leaf_is_numbered_depth_first_as_windows_menu_numbers_its_commands()

    def test_the_keyboard_opens_it_at_the_focused_row(self):
        super().test_the_keyboard_opens_it_at_the_focused_row()

    # compared with Windows' own menu, which the host's popup shows unrecorded (see the module's head)
    test_a_choice_in_the_drawn_menu_runs_the_action_windows_menu_runs = None


@ON_HOST
class FallbackOnHostTests(original.FallbackTests):
    def test_the_icon_gives_its_popup_the_drawn_menu(self):
        """The host's icon makes its popup with the drawn menu (gui/TrayIcon.cs), as ui/tray/clicks.py does."""
        source = (ROOT / "gui" / "TrayIcon.cs").read_text(encoding="utf-8")
        made = re.search(r"new PopupWindow\(.*?\};", source, re.S)
        self.assertIsNotNone(made, "the icon makes its popup")
        self.assertIn("MakeMenu = () => Accessible(new MenuWindow(Log))", made.group(0))

    # Windows' own menu, which the host's popup shows unrecorded (see the module's head)
    test_a_popup_with_nothing_to_draw_it_with_shows_windows_menu = None
    test_an_opening_refused_the_foreground_is_windows_menu_that_once = None
    test_a_drawn_menu_that_breaks_gives_way_to_windows_for_good_and_says_so_once = None


@ON_HOST
class PopupFocusOnHostTests(PopupOnHost, original.PopupFocusTests):
    def test_the_popup_stays_open_while_its_own_menu_has_the_focus_and_closes_it_as_it_hides(self):
        super().test_the_popup_stays_open_while_its_own_menu_has_the_focus_and_closes_it_as_it_hides()


@ON_HOST
class WindowsOnHostTests(original.WindowsTests):
    """The original's assertions over the host's answers: no window is shown, nothing is captured."""

    def test_the_row_menu_opens_in_the_drawn_menu_s_window(self):
        with unittest.mock.patch.object(original.popup, "Popup", hostpopup.HostPopup):
            shown = original.shown_popup()
        found = surfacehost.SERVE.ask("row_menu_class", strings=original.EN, core=shown._core(), key=original.KEY,
                                      lparam=(30 << 16) | 40)
        self.assertFalse(found["windows"], "the drawn menu opened, not Windows' own")
        self.assertEqual((found["made"], found["visible"]), (1, False), "made once, as an opening makes it, and not shown")
        self.assertTrue(found["class"].startswith("CodexAutoResumeMenu"), found["class"])

    def test_the_submenu_arrow_is_drawn_and_mirrored(self):
        for locale in ("en", "he"):
            with self.subTest(locale=locale):
                found = surfacehost.SERVE.ask("menu_arrow", entries=original.menu_entries(), locale=locale)
                left, top, right, bottom = (int(n) for n in found["arrow"])
                self.assertTrue(right > left and bottom > top, "the first item has an arrow")
                self.assertGreater(found["inks"], 1, "something is drawn in the arrow's place")
                self.assertEqual(found["rtl"], locale == "he")


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
