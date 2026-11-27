"""The drawn menu's real window read as a screen reader reads it, on the C# host (S6.4d6, P6-DESIGN 3.4 "window").

Twins of tests/test_tray_menu_drawn.py LiveWindowTests: the originals' bodies through `super()`, with `popup.Menu`
tests/rustdiff/hostlive.py's HostLiveMenu - ONE host MenuWindow made by its own Create and kept on a thread of the probe's
own (HostProbe.cs `menu_live`), its screen reader's hooks filled as the icon's menu has them (SurfaceAccess.Attach). The
setUp's own UpdateLayeredWindow (`_push`) and ShowWindow(SW_SHOWNOACTIVATE) put it at (-32000, -32000) exactly as the
original puts the reference's (the main session's word of 2026-11-28; inside gui_lock.sh, never activated, never a dialog,
destroyed in the test's own cleanup). The test's own AccessibleObjectFromWindow and every call on the object it gets reach
the host's window across processes: the host's thread runs Windows' messages between questions (`running`), as COM's calls
into a single-threaded apartment need. What changed, and only that:

* `self.menu` is the host's menu (entries, strings, plan, origin, theme, contrast, visible and `_push` its steps; the plan
  the host renderer's of the same entries at the same scale and locale);
* the test's `call` (a method of the client object's table) asks the host's menu how it is after each call, so a choice
  the host's menu made in the call is handed to the test's `on_choose` before the test looks.
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

import surfacehost  # noqa: E402

if os.name == "nt":
    import hostlive  # noqa: E402
    import test_tray_menu_drawn as original  # noqa: E402  (a module name: its classes are not collected here)
    LIVE = original.LiveWindowTests
else:
    LIVE = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class PopupOnHost:
    """The reference popup package with its Menu the host's live one; everything else is the reference's."""

    def __init__(self, reference):
        self._reference = reference

    def Menu(self, **keywords):  # noqa: N802  (the reference's name)
        return hostlive.HostLiveMenu(running=True, **keywords)

    def __getattr__(self, name):
        return getattr(self._reference, name)


@ON_HOST
class LiveWindowOnHostTests(LIVE):  # noqa: F821
    def setUp(self):
        patcher = unittest.mock.patch.object(original, "popup", PopupOnHost(original.popup))
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def call(self, pointer, slot, *types):
        """The original's call through the client object's table, then the host's menu as it is after it."""
        real = original.LiveWindowTests.call(pointer, slot, *types)

        def calling(*arguments):
            answer = real(*arguments)
            self.menu.refresh()
            return answer
        return calling

    def test_it_is_a_menu_whose_children_are_its_items_by_name_role_and_state(self):
        super().test_it_is_a_menu_whose_children_are_its_items_by_name_role_and_state()

    def test_its_default_action_is_the_choice(self):
        super().test_its_default_action_is_the_choice()

    def test_the_layered_picture_is_taken_at_every_scale_and_theme(self):
        super().test_the_layered_picture_is_taken_at_every_scale_and_theme()


del LIVE


if __name__ == "__main__":
    unittest.main()
