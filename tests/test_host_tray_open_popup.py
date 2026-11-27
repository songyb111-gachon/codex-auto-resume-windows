"""The icon's menu offers Open the popup, on the C# host (S6.4d4, P6-DESIGN 3.4 "window").

Twins of tests/test_tray_open_popup.py:

* ItemTests' three left: the originals' bodies through `super()`, the MENU_* numbers the host's (gui/TrayIcon.cs), the icon
  tests/rustdiff/hosticon.py's HostTray (its Windows menu the host's TrayMenu.NativeMenu, handed to the test's patched
  user32), and the letter that chooses an item the host's MenuPlan.Letter (hosticon.HostMenuKeys). The items they start
  from (tray.menu_items) and the drawn plan the parity compares with (popup.menu_layout) stay the reference's - or, under
  CODEX_AR_CORE=rust, the shim's - as test_host_icon_menu's parity twins have them; the language catalogs are the product's.
* OfferedTests: the icon's drawn menu opened by the host (`icon_steps` `menu`), the test's FakeDrawn asked; a popup that
  broke is the host icon's PopupFailed. On the host the icon's control layer is its IHostActions - every callback the
  reference called is an action posted through it - so the reference's icon with no control layer is the host's with no
  IHostActions (OfferedHostTray), and that one offers no popup (TrayIcon.PopupCanOpen: Actions != null && !PopupFailed).

Not here: OpensTests (6) open the popup the left click opens and hand it the Dashboard opener - the opener is seat S6.4e's.

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
import test_tray_open_popup as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class OfferedHostTray(hosticon.HostTray):
    """The host's icon with IHostActions exactly where the reference's had a control layer."""

    def _actions(self):
        return self.control is not None


class TrayOnHost:
    """The reference tray package with its Tray and its MENU_* numbers the host's; everything else is the reference's."""

    def __init__(self, reference, tray_class=hosticon.HostTray):
        self._reference = reference
        self.Tray = tray_class
        for name, value in hosticon.menu_ids().items():
            setattr(self, name, value)

    def __getattr__(self, name):
        return getattr(self._reference, name)


class PopupOnHost:
    """The reference popup package with the menu's letter the host's MenuPlan.Letter."""

    def __init__(self, reference):
        self._reference = reference
        self.menu_letter = hosticon.HostMenuKeys.menu_letter

    def __getattr__(self, name):
        return getattr(self._reference, name)


def on_host(case, tray_class=hosticon.HostTray):
    for name, value in (("tray", TrayOnHost(original.tray, tray_class)), ("popup", PopupOnHost(original.popup))):
        patcher = unittest.mock.patch.object(original, name, value)
        patcher.start()
        case.addCleanup(patcher.stop)


@ON_HOST
class ItemOnHostTests(original.ItemTests):
    def setUp(self):
        on_host(self)

    def test_its_own_command_and_every_language_has_its_words(self):
        super().test_its_own_command_and_every_language_has_its_words()

    def test_the_drawn_menu_and_windows_menu_have_it_alike(self):
        super().test_the_drawn_menu_and_windows_menu_have_it_alike()

    def test_its_letter_reaches_it_in_every_language(self):
        super().test_its_letter_reaches_it_in_every_language()

    # the other two are routed by the shim (menu_items): not run again here
    test_it_is_right_after_open_dashboard = None
    test_without_a_popup_the_menu_is_what_it_was = None


@ON_HOST
class OfferedOnHostTests(original.OfferedTests):
    def setUp(self):
        on_host(self, OfferedHostTray)

    def test_it_is_offered_where_a_left_click_opens_a_popup(self):
        super().test_it_is_offered_where_a_left_click_opens_a_popup()

    def test_not_without_a_control_layer_or_after_the_popup_broke(self):
        super().test_not_without_a_control_layer_or_after_the_popup_broke()


if __name__ == "__main__":
    unittest.main()
