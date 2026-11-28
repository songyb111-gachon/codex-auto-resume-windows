"""The icon's menu commands and the failure it shows, on the C# host (S6.4d, P6-DESIGN 3.4 "window").

Twins of tests/test_surface_properties.py TrayMenuTests (each menu item reaches the thing it names) and
tests/test_failure_seen.py IconTests (red while unseen, asked every second, seen when the popup is opened). The tests are
the originals' own bodies, through `super()`; only the object they make is changed: `tray.Tray` is tests/rustdiff/hosticon.py's
HostTray, whose every member the tests call is one step of gui/TrayIcon.cs / gui/TrayMenu.cs in the host's probe
(HostProbe.cs `icon_steps`), and the MENU_* numbers are the host's own. What the icon posts through IHostActions is handed to
the callback the reference would have called (the core's half of the boundary); whether a failure is unseen is asked of the
test's control layer only when the host's icon asks it.

Nothing is shown: the icon has no window and no shell icon, and every call it would make of Windows is recorded instead.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import hosticon  # noqa: E402
import surfacehost  # noqa: E402
import test_failure_seen as failure_seen  # noqa: E402  (module names: their classes are not collected here)
import test_surface_properties as properties  # noqa: E402

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


@ON_HOST
class TrayMenuOnHostTests(properties.TrayMenuTests):
    def setUp(self):
        super().setUp()
        self.reference = self.tray
        self.tray = types.SimpleNamespace(Tray=hosticon.HostTray, **hosticon.menu_ids())
        self.icon = hosticon.HostTray(
            strings={},
            on_open=lambda: self.calls.append("open"),
            on_toggle=lambda paused: self.calls.append("resume" if paused else "pause"),
            on_stop=lambda: self.calls.append("stop"),
            log=lambda *unused: self.calls.append("logged"))

    # the opener's own refusal (ui/tray/dashboard.py open_dashboard) is the Dashboard opener's (seat S6.4e), not the icon's
    test_the_window_is_only_ever_opened_on_a_page_it_has = None

    def test_open_opens(self):
        super().test_open_opens()

    def test_stop_stops(self):
        super().test_stop_stops()

    def test_the_one_item_that_changes_its_mind_is_told_which_way(self):
        super().test_the_one_item_that_changes_its_mind_is_told_which_way()

    def test_closing_the_menu_without_choosing_does_nothing(self):
        super().test_closing_the_menu_without_choosing_does_nothing()

    def test_an_id_that_is_not_a_menu_item_does_nothing(self):
        super().test_an_id_that_is_not_a_menu_item_does_nothing()

    def test_an_action_that_throws_is_logged_and_never_ends_the_watcher(self):
        super().test_an_action_that_throws_is_logged_and_never_ends_the_watcher()

    def test_a_menu_with_nothing_wired_to_it_is_harmless(self):
        super().test_a_menu_with_nothing_wired_to_it_is_harmless()

    def test_pending_opens_the_page_where_those_actions_live(self):
        super().test_pending_opens_the_page_where_those_actions_live()

    def test_the_menu_numbers_are_the_references(self):
        """The ids the tests pass are the host's; they are the reference's numbers too (Windows' menu returns them)."""
        for name, value in hosticon.menu_ids().items():
            self.assertEqual(value, getattr(self.reference, name), name)


@ON_HOST
class IconOnHostTests(failure_seen.IconTests):
    def icon(self, control_layer):
        icon = hosticon.HostTray(strings={}, control=control_layer)
        icon._refresh_calls = 0
        self.made = getattr(self, "made", []) + [icon]
        return icon

    def test_every_second_the_icon_asks_and_the_shell_is_told_what_it_found(self):
        super().test_every_second_the_icon_asks_and_the_shell_is_told_what_it_found()
        # and the words the shell was told are the host's own tooltip, the red one and then the plain one
        self.assertEqual(self.made[0].tips, ["Codex Auto Resume\nA recovery failed", "Codex Auto Resume\nNothing waiting"])

    def test_a_click_that_opens_the_popup_sees_the_failure(self):
        super().test_a_click_that_opens_the_popup_sees_the_failure()

    def test_the_icon_asks_the_control_layer_and_nothing_else_decides(self):
        super().test_the_icon_asks_the_control_layer_and_nothing_else_decides()

    def test_opening_the_popup_sees_it_and_only_when_it_is_shown(self):
        super().test_opening_the_popup_sees_it_and_only_when_it_is_shown()

    # routed by the shim (tray.icon_state and tray.tooltip are the host's under CODEX_AR_CORE=rust): a row's host_tests
    test_a_failure_turns_the_icon_red_and_says_so_when_hovered = None
    # the language catalogs only: nothing of the icon is asked
    test_every_language_says_it = None


if __name__ == "__main__":
    unittest.main()
