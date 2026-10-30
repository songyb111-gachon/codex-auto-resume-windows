r"""v0.6.20 (the owner, 2026-10-30): in the README's first motion the Timeline dialog wore Windows' default form icon.

The real window loads the product's icon from the file beside its exe (SettingsForm reads BaseDirectory\
codex-auto-resume.ico), and every dialog that shows an icon takes the window's (`dialog.Icon = Icon`, BuildTimeline). The
motion's own build of the window (build/motion_window.compile_window) wrote the exe into a scratch folder with no icon
beside it, so the window had none and WindowRender painted the dialog's title bar with the default one.

* The build: compile_window embeds the icon (`/win32icon`, as build/make_gui.ps1 does) and puts the same file beside the exe.
* The source: the window still takes its icon from that file, and the Timeline dialog still takes the window's.

Compiles the window once (csc): run on its own.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import guiscan

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "build") not in sys.path:
    sys.path.insert(0, str(ROOT / "build"))

import motion_window  # noqa: E402

ICON = ROOT / "assets" / "codex-auto-resume.ico"


class BuildTests(unittest.TestCase):
    @unittest.skipUnless(motion_window.CSC.is_file(), "the in-box C# compiler is not on this machine")
    def test_the_motions_window_has_the_products_icon_beside_it(self):
        with tempfile.TemporaryDirectory() as name:
            exe = motion_window.compile_window(Path(name))
            beside = exe.parent / "codex-auto-resume.ico"
            self.assertTrue(beside.is_file(), "the window the motion draws has no icon beside it")
            self.assertEqual(beside.read_bytes(), ICON.read_bytes(), "the icon beside it is the product's own")


class SourceTests(unittest.TestCase):
    def test_the_window_loads_its_icon_from_the_file_beside_it(self):
        body = guiscan.type_body("SettingsForm", "gui/SettingsApp.cs")
        self.assertIn('Path.Combine(root, "codex-auto-resume.ico")', body)
        self.assertIn("Icon = new Icon(icon);", body)

    def test_the_timeline_dialog_wears_the_windows_icon(self):
        body = guiscan.member_body("SettingsForm", "BuildTimeline")
        self.assertIn("dialog.Icon = Icon;", body)


if __name__ == "__main__":
    unittest.main()
