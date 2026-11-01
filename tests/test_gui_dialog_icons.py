"""No window the Dashboard opens inside itself has an icon in its title bar (the owner, 2026-11-01).

The v0.6.15 rule was "the product's icon, or none": the small dialogs hid theirs and the windows with a list wore the
Dashboard's. The live re-check of the v0.6.20 final (2026-11-01) found both kinds side by side and the owner chose one:
"앱 안에서 새로 창을 띄울 때 아이콘이 없는게 더 나은 거 같아" - a dialog, picker, statement or confirmation has no icon at all.
Only the Dashboard's main window keeps its icon (and the tray icon, the drawn menu and the popup are other things).

It is decided in one place, Soft.DialogBar (gui/SoftTheme.cs): every Form the window builds for a dialog calls it where it
used to call Soft.TitleBar, and it sets ShowIcon = false. This reads the window's sources, so a new dialog that forgets
it - or one that takes an Icon again - fails here before anyone opens it. A dialog is never in the taskbar either
(ShowInTaskbar = false), so none has a button whose icon would show. The setup window (InstallerWindow) is the setup
program's own and keeps its icon wherever it runs.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import guiscan  # noqa: E402

if str(ROOT / "build") not in sys.path:
    sys.path.insert(0, str(ROOT / "build"))

import motion_window  # noqa: E402

POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SOURCES = sorted(list((ROOT / "gui").glob("*.cs")) + list((ROOT / "advanced" / "gui").glob("*.cs")))
MADE = re.compile(r"\b(?:var|Form)\s+(\w+)\s*=\s*new Form\(\)")
# How far after `new Form()` a builder sets the window up: every builder here does it in its first dozen lines.
REACH = 40


def dialogs() -> list:
    """(source, line number, name, the lines that set the dialog up) of every `new Form()` the window's sources make."""
    found = []
    for path in SOURCES:
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            made = MADE.search(line)
            if made:
                found.append((path.relative_to(ROOT).as_posix(), number, made.group(1), lines[number:number + REACH]))
    return found


class DialogIconTests(unittest.TestCase):
    def test_the_sources_make_dialogs_at_all(self):
        # The scan is not vacuous: the Dashboard and the advanced page build fourteen between them.
        self.assertGreaterEqual(len(dialogs()), 14)

    def test_every_dialog_takes_its_title_bar_from_the_one_place_that_hides_the_icon(self):
        for source, line, name, after in dialogs():
            with self.subTest(source=source, line=line):
                self.assertTrue(any(re.search(r"\bSoft\.DialogBar\(%s\);" % re.escape(name), later) for later in after),
                                "%s:%d: call Soft.DialogBar(%s), not Soft.TitleBar: a dialog has no icon" % (source, line, name))
                self.assertFalse(any(re.search(r"\b%s\.TitleBar|Soft\.TitleBar\(%s\)" % (re.escape(name), re.escape(name)),
                                               later) for later in after))

    def test_no_dialog_is_given_an_icon_or_asks_to_show_one(self):
        for source, line, name, after in dialogs():
            with self.subTest(source=source, line=line):
                for later in after:
                    self.assertFalse(re.search(r"\b%s\.Icon\s*=" % re.escape(name), later), later)
                    self.assertFalse(re.search(r"\b%s\.ShowIcon\s*=\s*true" % re.escape(name), later), later)

    def test_no_dialog_shows_in_the_taskbar(self):
        for source, line, name, after in dialogs():
            with self.subTest(source=source, line=line):
                self.assertTrue(any(re.search(r"\b%s\.ShowInTaskbar\s*=\s*false;" % re.escape(name), later) for later in after))

    def test_the_one_place_hides_the_icon_and_still_makes_the_title_bar(self):
        body = guiscan.member_body("Soft", "DialogBar")
        self.assertIn("dialog.ShowIcon = false;", body)
        self.assertIn("TitleBar(dialog);", body)

    def test_the_main_window_and_the_setup_window_keep_theirs(self):
        window = guiscan.type_body("SettingsForm", "gui/SettingsApp.cs")
        self.assertIn("Icon = new Icon(icon);", window)
        self.assertNotIn("ShowIcon = false", window)
        self.assertIn("Icon = Icon.ExtractAssociatedIcon(", (ROOT / "gui" / "InstallerWindow.cs").read_text(encoding="utf-8"))

    def test_a_picture_of_a_dialog_draws_no_icon_either(self):
        render = guiscan.member_body("SettingsForm", "RenderDialog")
        self.assertIn("form.ShowIcon ? form.Icon : null", render)
        paint = guiscan.member_body("SettingsForm", "PaintDialog")
        self.assertIn("if (icon != null)", paint)
        self.assertIn("titleLeft", paint)


class RunTests(unittest.TestCase):
    @unittest.skipUnless(motion_window.CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
    def test_the_compiled_dialog_bar_hides_the_icon_and_the_plain_title_bar_does_not(self):
        """The built window's own Soft.DialogBar on a Form that is never shown: no icon; Soft.TitleBar alone leaves it."""
        with tempfile.TemporaryDirectory() as name:
            work = Path(name)
            exe = motion_window.compile_window(work / "window")
            probe = work / "probe.ps1"
            probe.write_text("\n".join((
                "$ErrorActionPreference = 'Stop'",
                "Add-Type -AssemblyName System.Windows.Forms",
                "[System.Windows.Forms.Application]::SetUnhandledExceptionMode('ThrowException')",
                "try {",
                "  $assembly = [Reflection.Assembly]::LoadFile('%s')" % exe,
                "  $soft = $assembly.GetType('CodexAutoResume.Soft')",
                "  $flags = [Reflection.BindingFlags]'Static,NonPublic,Public'",
                "  $plain = New-Object System.Windows.Forms.Form",
                "  $given = [object[]]::new(1); $given[0] = $plain.PSObject.BaseObject",
                "  $soft.GetMethod('TitleBar', $flags).Invoke($null, $given) | Out-Null",
                "  $dialog = New-Object System.Windows.Forms.Form",
                "  $given = [object[]]::new(1); $given[0] = $dialog.PSObject.BaseObject",
                "  $soft.GetMethod('DialogBar', $flags).Invoke($null, $given) | Out-Null",
                "  Write-Output ('plain=' + $plain.ShowIcon + ' dialog=' + $dialog.ShowIcon)",
                "  $plain.Dispose(); $dialog.Dispose()",
                "} catch { Write-Output ('error ' + $_.Exception.ToString()); exit 3 }", "")), encoding="utf-8")
            done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                   "-File", str(probe)], capture_output=True, timeout=120, creationflags=NO_WINDOW)
            said = done.stdout.decode("utf-8", "replace").strip()
            self.assertEqual(done.returncode, 0, said + done.stderr.decode("utf-8", "replace"))
            self.assertEqual(said.splitlines()[-1], "plain=True dialog=False")


if __name__ == "__main__":
    unittest.main()
