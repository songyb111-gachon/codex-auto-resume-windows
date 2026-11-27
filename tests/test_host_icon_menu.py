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


if __name__ == "__main__":
    unittest.main()
