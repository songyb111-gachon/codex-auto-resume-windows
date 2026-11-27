"""The icon's menu offers to turn the armed power action off, on the C# host (S6.4d4, P6-DESIGN 3.4 "window").

Twins of tests/test_tray.py PowerMenuTests: the originals' bodies through `super()`, with `tray.Tray` tests/rustdiff/hosticon.py's
HostTray (each member a step of gui/TrayIcon.cs / gui/TrayMenu.cs in the host's probe, HostProbe.cs `icon_steps`) and the
MENU_* numbers the host's. Windows' own menu is the host's TrayMenu.NativeMenu, its calls handed to the test's patched
user32 (`_Menu`, which answers the choice); the choice is posted (`disarm_power`) and handed to the control layer the
reference called (`disarm_power_action(actor="tray")`); `_power_armed` is the host's TrayMenu.Armed.

What the core sends the icon is stood in for from the test's own store, as the core reads it: the armed action rides the
snapshot (`power_armed`, from the control layer's power_view - HostTray's `_core_snapshot`), and the strings are the catalog
of the stored Interface language (the host takes them from the core's "surfaces" and "strings" events, gui/HostSurfaces.cs,
where the reference's icon read the settings itself: ui/tray/stored.py `_adopt_settings`) - PowerHostTray.

Not here: LiveIconTests starts the reference's real notification-area icon and its thread (a shell icon on the owner's
taskbar); the host's live icon is the window seat's last row (test_tray_menu_drawn.LiveWindowTests' route).

Nothing is shown: the icon has no window and no shell icon, and Windows' menu is recorded, never made.
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
import test_tray as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class PowerHostTray(hosticon.HostTray):
    """HostTray with the strings the core would send: the catalog of the language stored in the test's settings."""

    def _state(self):
        state = super()._state()
        paths = getattr(self.control, "paths", None)
        if paths is not None:
            from codex_auto_resume import settings
            from codex_auto_resume.ui import popup
            try:
                language = settings.load(paths.settings_file).get("interface_language")
            except Exception:
                language = None
            if language:
                state["strings"] = dict(popup.vocabulary(language))
        return state


class TrayOnHost:
    """The reference tray package with its Tray and its MENU_* numbers the host's; everything else is the reference's."""

    def __init__(self, reference):
        self._reference = reference
        self.Tray = PowerHostTray
        for name, value in hosticon.menu_ids().items():
            setattr(self, name, value)

    def __getattr__(self, name):
        return getattr(self._reference, name)


@ON_HOST
class PowerMenuOnHostTests(original.PowerMenuTests):
    def setUp(self):
        patcher = unittest.mock.patch.object(original, "tray", TrayOnHost(original.tray))
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_the_item_is_there_only_while_armed(self):
        super().test_the_item_is_there_only_while_armed()

    def test_the_item_speaks_the_language_stored(self):
        super().test_the_item_speaks_the_language_stored()

    def test_choosing_it_turns_it_off_as_the_icon(self):
        super().test_choosing_it_turns_it_off_as_the_icon()

    def test_an_icon_without_a_control_layer_offers_nothing(self):
        super().test_an_icon_without_a_control_layer_offers_nothing()


if __name__ == "__main__":
    unittest.main()
