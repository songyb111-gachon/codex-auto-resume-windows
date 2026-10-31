r"""A list's rows stand under its headings once its columns fit, whichever way the window reads (v0.6.20 final, A5).

The v0.6.20 final's live acceptance (2026-11-01) found History in Arabic showing one column, End, at the list's right, and
nothing else: the conversation, result, kind and detected columns, their headings and their rows, were blank, while
Pending's six columns stood mirrored as they should. The cause: a list scrolled sideways and then given another width kept
its headings and rows as far right as it had been scrolled. Its columns are fitted to its width as it takes it
(SettingsForm.FitColumns, on the list's ClientSizeChanged, inside Windows' own handling of the size), Windows took the
scroll back twice, and no bar was left to scroll them back. A mirrored list is scrolled to its first column whenever its
columns are wider than it is (SoftListHost.StartAtFirstColumn), and History, built while the window had not yet given it
its room - 133 px wide and no row tall - was scrolled 107 px to the right before it took its full width. Pending, empty,
had no row to scroll. Left to right the same followed a sideways scroll and a wider window.

The host now scrolls a list back to its left edge before it takes another size (SoftListHost.FromFirstPixel); mirrored, a
list still wider than its columns then starts at its first column again.

Two probes, never on the screen:
* a list on its host, scrolled sideways while narrow (mirrored by the host itself, left to right by hand), then made wide
  with its columns fitted as it takes its width: its first row starts at the list's left edge again;
* the real window, in Arabic and in Hebrew, in the standard and the advanced edition's build, shown far off the screen in a
  frame that is never activated, as the other GUI probes show it: History opened from Settings, the live path - its
  columns mirrored, the first at the right, and its rows under its headings.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

import guiscan

from codex_auto_resume import l10n, settings

from test_gui_layout import fullest_snapshot

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
RIGHT_TO_LEFT = sorted(l10n.RIGHT_TO_LEFT)


def overlay_sources() -> list:
    """The advanced edition's own window sources, compiled after the standard window's."""
    lines = (ROOT / "advanced" / "gui" / "window.sources").read_text(encoding="utf-8").splitlines()
    return [ROOT / line.strip() for line in lines if line.strip() and not line.startswith(("#", "["))]


def compile_window(exe: Path, advanced: bool) -> None:
    sources = [str(path) for path in guiscan.sources()]
    if advanced:
        sources += [str(path) for path in overlay_sources()]
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                    "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                    *sources], check=True, capture_output=True, timeout=300)


def run_probe(script: Path, env: dict, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=dict(os.environ, **env))


HOST = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::SetUnhandledExceptionMode('ThrowException')
Add-Type -Namespace RowsInPlace -Name Native -MemberDefinition '[DllImport("user32.dll")] public static extern System.IntPtr SendMessage(System.IntPtr w, int m, System.IntPtr p, System.IntPtr l);'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
$listType = $assembly.GetType('CodexAutoResume.SoftList', $true)
$hostType = $assembly.GetType('CodexAutoResume.SoftListHost', $true)
$out = @{}
foreach ($rtl in @('No', 'Yes')) {
    $script:form = New-Object Windows.Forms.Form
    $script:form.RightToLeft = $rtl
    $script:form.TopLevel = $false
    $script:form.ClientSize = New-Object Drawing.Size(150, 0)
    $script:list = $listType.GetConstructors($any)[0].Invoke(@())
    $script:list.View = 'Details'
    foreach ($name in @('c0', 'c1', 'c2', 'c3', 'c4')) { $null = $script:list.Columns.Add($name, 48) }
    foreach ($row in 1..40) { $null = $script:list.Items.Add((New-Object Windows.Forms.ListViewItem -ArgumentList (,[string[]]@('a', 'b', 'c', 'd', 'e')))) }
    # The columns fitted to the list's width as it takes it, as the window's FitColumns fits them.
    $script:list.add_ClientSizeChanged({
        param($sender, $e)
        try {
            $width = $sender.ClientSize.Width
            if ($width -lt 160 -or $sender.Columns.Count -lt 5) { return }
            $each = [int][Math]::Floor($width / 5)
            foreach ($i in 0..3) { ([Windows.Forms.ColumnHeader]$sender.Columns.Item($i)).Width = $each }
            ([Windows.Forms.ColumnHeader]$sender.Columns.Item(4)).Width = $width - 4 * $each
        } catch { [Console]::Error.WriteLine($_.ToString()); [Environment]::Exit(7) }
    })
    $script:soft = $hostType.GetConstructors($any)[0].Invoke(@($script:list))
    $script:soft.Dock = 'Fill'
    $script:form.Controls.Add($script:soft)
    $null = $script:form.Handle; $null = $script:soft.Handle; $null = $script:list.Handle
    $script:form.PerformLayout(); $script:soft.PerformLayout()
    # Mirrored, the host has scrolled the narrow list to its first column; left to right, a person scrolls it.
    if ($rtl -eq 'No') { $null = [RowsInPlace.Native]::SendMessage($script:list.Handle, 0x1014, [IntPtr]50, [IntPtr]::Zero) }
    $scrolled = $script:list.GetItemRect(0, 'Entire').Left
    $script:form.ClientSize = New-Object Drawing.Size(900, 400)
    $script:form.PerformLayout(); $script:soft.PerformLayout()
    [Windows.Forms.Application]::DoEvents()
    $script:soft.PerformLayout()
    $out[$rtl] = @{ scrolled = $scrolled; left = $script:list.GetItemRect(0, 'Entire').Left
                    across = [bool]$hostType.GetProperty('OverflowingAcross', $any).GetValue($script:soft, $null) }
    $script:form.Dispose()
}
$out | ConvertTo-Json -Depth 4 -Compress
"""


class ListOnItsHostTests(unittest.TestCase):
    """A list on its host, scrolled sideways while narrow and then made wide, its columns fitted as it takes its width."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        compile_window(exe, advanced=False)
        script = work / "host.ps1"
        script.write_text(HOST, encoding="utf-8")
        cls.result = run_probe(script, {"CAR_EXE": str(exe)}, 300)
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_the_narrow_list_was_scrolled_sideways(self):
        """What the test stands on: both lists were scrolled away from their left edge while narrow."""
        for rtl in ("No", "Yes"):
            with self.subTest(rtl=rtl):
                self.assertLess(self.answer[rtl]["scrolled"], 0)

    def test_once_its_columns_fit_its_rows_start_at_its_left_edge(self):
        for rtl in ("No", "Yes"):
            with self.subTest(rtl=rtl):
                self.assertFalse(self.answer[rtl]["across"], "the columns fit the wide list")
                self.assertEqual(self.answer[rtl]["left"], 0, "the rows stayed where the narrow list had been scrolled")


WINDOW = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public class RowsQuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
public static class RowsNative {
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr w, int m, IntPtr p, int[] l);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr w, int m, IntPtr p, IntPtr l);
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $any)
$type = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
function Pump($times) { for ($k = 0; $k -lt $times; $k++) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 10 } }
$out = @{}
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    $catalog = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)))
    $schema = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)))
    $current = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'settings.json'), $utf8)))
    $snapshot = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'snapshot.json'), $utf8)))
    $nowhere = [string](Join-Path $work 'nowhere')
    $once = $assembly.GetType('CodexAutoResume.Bridge', $true).GetConstructors($any)[0].Invoke([object[]]@($nowhere))
    $two = @($assembly.GetType('CodexAutoResume.PersistentBridge', $true).GetConstructors($any) | Where-Object { $_.GetParameters().Count -eq 2 })[0]
    $bridge = $two.Invoke([object[]]@($nowhere, $once))
    $three = @($type.GetConstructors($any) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
    $frame = New-Object RowsQuietForm
    $frame.FormBorderStyle = 'None'
    $frame.ShowInTaskbar = $false
    $frame.StartPosition = 'Manual'
    $frame.Location = New-Object Drawing.Point -30000, -30000
    $frame.ClientSize = New-Object Drawing.Size 1000, 664
    $window = $three.Invoke([object[]]@($bridge, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
    $type.GetField('auditing', $any).SetValue($window, $true)
    $window.TopLevel = $false
    $window.FormBorderStyle = 'None'
    $window.MinimumSize = [Drawing.Size]::Empty
    $window.Location = [Drawing.Point]::Empty
    $window.ClientSize = $frame.ClientSize
    $frame.Controls.Add($window)
    $null = $type.GetMethod('BuildEditors', $any).Invoke($window, [object[]]@($schema, $current))
    $null = $type.GetMethod('ApplySnapshot', $any).Invoke($window, [object[]]@($snapshot))
    $null = $type.GetMethod('ShowPage', $any).Invoke($window, [object[]]@('settings'))
    $window.Visible = $true
    $frame.Show()
    Pump 30
    # The live path: History opened from another page of a window on the screen, built as it is shown.
    $null = $type.GetMethod('ShowPage', $any).Invoke($window, [object[]]@('history'))
    Pump 30
    $list = $type.GetField('historyList', $any).GetValue($window)
    $count = $list.Columns.Count
    $order = New-Object int[] $count
    $null = [RowsNative]::SendMessage($list.Handle, 0x103B, [IntPtr]$count, [int[]]$order)
    $header = [RowsNative]::SendMessage($list.Handle, 0x101F, [IntPtr]::Zero, [IntPtr]::Zero)
    $first = New-Object int[] 4
    $null = [RowsNative]::SendMessage($header, 0x1207, [IntPtr]0, [int[]]$first)
    $out[$locale] = @{ mirrored = [bool]($list.Parent.RightToLeft -eq 'Yes'); rows = $list.Items.Count; order = @($order)
                       left = $list.GetItemRect(0, 'Entire').Left; client = $list.ClientSize.Width; first_right = $first[2] }
    $frame.Close()
    $frame.Dispose()
}
$out | ConvertTo-Json -Depth 4 -Compress
"""


class MirroredHistoryTests(unittest.TestCase):
    """The real window's History in each language written right to left, in both editions' builds."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        for locale in RIGHT_TO_LEFT:
            reply = {"ok": True, "language": locale, "strings": l10n.catalog(locale), "endonyms": dict(l10n.ENDONYMS),
                     "preference": locale, "system_language": locale}
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        snapshot = fullest_snapshot(time.time())
        # More rows than show: the list has its own bar beside them, as a history of any length does.
        finished = snapshot["history"]
        snapshot["history"] = [dict(finished[i % len(finished)], interruption_id="%064x" % (i + 1)) for i in range(40)]
        (work / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        script = work / "window.ps1"
        script.write_text(WINDOW, encoding="utf-8")
        cls.answers, cls.failures = {}, {}
        for edition in ("standard", "advanced"):
            exe = work / ("CodexAutoResume-%s.exe" % edition)
            compile_window(exe, advanced=edition == "advanced")
            result = run_probe(script, {"CAR_EXE": str(exe), "CAR_WORK": str(work), "CAR_LOCALES": json.dumps(RIGHT_TO_LEFT)},
                               600)
            if result.returncode == 0 and result.stdout.strip():
                cls.answers[edition] = json.loads(result.stdout)
            else:
                cls.failures[edition] = (result.stderr or result.stdout)[-3000:]

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if self.failures:
            self.fail("the probe did not run: %r" % self.failures)

    def test_history_shows_every_column_mirrored_with_its_rows_under_its_headings(self):
        for edition, answer in self.answers.items():
            for locale in RIGHT_TO_LEFT:
                with self.subTest(edition=edition, locale=locale):
                    seen = answer[locale]
                    self.assertTrue(seen["mirrored"])
                    self.assertEqual(seen["rows"], 40)
                    self.assertEqual(seen["order"], [4, 3, 2, 1, 0], "the first column at the right, End at the left")
                    self.assertEqual(seen["first_right"], seen["client"], "the conversation's heading ends at the list's right")
                    self.assertEqual(seen["left"], 0, "the rows stand right of the headings, past the list's edge")

    def test_both_editions_were_looked_at(self):
        self.assertEqual(sorted(self.answers), ["advanced", "standard"])


class SourceTests(unittest.TestCase):
    def test_the_host_scrolls_back_before_the_list_takes_another_size(self):
        layout = guiscan.member_body("SoftListHost", "OnLayout")
        back = layout.index("FromFirstPixel();")
        self.assertLess(back, layout.index("List.SetBounds(0, 0, rows + beside, tall + below);"))
        self.assertLess(back, layout.index("StartAtFirstColumn();"), "mirrored, it starts at its first column after")
        body = guiscan.member_body("SoftListHost", "FromFirstPixel")
        self.assertIn("LVM_SCROLL, new IntPtr(-at)", body)
        self.assertIn("startedRight = false;", body)


if __name__ == "__main__":
    unittest.main()
