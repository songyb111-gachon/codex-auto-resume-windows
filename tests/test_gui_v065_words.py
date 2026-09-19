r"""Korean is broken between its words in the window, as the popup and the panel break it (v0.6.5).

Windows' own wrapping (DrawText's word break) breaks Korean between any two syllables, so the window split words across
two lines - the notification card's new help line ended a line in '잠겨 있' and began the next with '거나', and Pending's
placeholder broke '표시됩니다' - while the popup breaks Korean only at its spaces (tray_popup.unbroken) and the panel keeps
its words whole (word-break: keep-all). The window was the only surface that split a Korean word. Soft.Wrap breaks a text
with Korean in it into the lines it is drawn in - at its spaces, and in a run of Chinese or Japanese between characters -
and everything that wraps a help line, a note or a value in the window measures and draws what it returns (WrapLabel,
the Why it is waiting placeholder, the choice cards, the message quote, the reopen note, the layout audit). Text without
Korean is left as it was, for Windows to break as it always has: Chinese and Japanese between characters, as the popup
does.

The real compiled window is built in the probe's own process, far off the screen and never activated, as the other GUI
probes build it; nothing is sent to any other window.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

from codex_auto_resume import l10n, settings

from test_gui_layout import fullest_snapshot

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
SCALES = (1.0, 1.5, 2.0)
WIDTHS = (160, 240, 360, 520)
HANGUL = re.compile("[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System.Windows.Forms;
public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$soft = $assembly.GetType('CodexAutoResume.Soft', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($target, $arguments)
}
function Pump([int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 2 } while ($sw.ElapsedMilliseconds -lt $ms) }
$soft.GetField('ReduceMotionSetting', $static).SetValue($null, $true)
$systemScale = [double]$form.GetField('SystemScale', $static).GetValue($null)
$wrap = $soft.GetMethod('Wrap', $static)
$cases = [IO.File]::ReadAllText((Join-Path $work 'cases.json'), $utf8) | ConvertFrom-Json
$words = [Windows.Forms.TextFormatFlags]'WordBreak, TextBoxControl'
$single = [Windows.Forms.TextFormatFlags]'SingleLine'
$max = New-Object Drawing.Size ([int]::MaxValue), ([int]::MaxValue)
$out = @{ wrap = ($null -ne $wrap); scales = @{} }
foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
    $form.GetField('dpiScale', $static).SetValue($null, [double]$scale)
    $factor = [single]($scale / $systemScale)
    $box = [Drawing.SystemFonts]::MessageBoxFont
    [Drawing.Font]$font = New-Object Drawing.Font $box.FontFamily, ($box.SizeInPoints * $factor), $box.Style, ([Drawing.GraphicsUnit]::Point)
    $key = ([double]$scale).ToString('0.0', [Globalization.CultureInfo]::InvariantCulture)
    $entry = @{ line = [Windows.Forms.TextRenderer]::MeasureText([string]$cases.probe, $font, $max, $single).Height; texts = @() }
    if ($null -ne $wrap) {
        foreach ($text in $cases.texts) {
            foreach ($width in $cases.widths) {
                $w = [int][Math]::Round([int]$width * $scale)
                $wrapped = [string]$wrap.Invoke($null, [object[]]@([string]$text, $font, $w, $words))
                $lines = $wrapped.Split([char]10)
                $widths = @()
                $longer = @()
                for ($i = 0; $i -lt $lines.Count; $i++) {
                    $widths += [Windows.Forms.TextRenderer]::MeasureText($lines[$i], $font, $max, $single).Width
                    if ($i -lt $lines.Count - 1) {
                        $first = ($lines[$i + 1] -split ' ', 2)[0]
                        $longer += [Windows.Forms.TextRenderer]::MeasureText($lines[$i] + ' ' + $first, $font, $max, $single).Width
                    }
                }
                $height = [Windows.Forms.TextRenderer]::MeasureText($wrapped, $font, (New-Object Drawing.Size $w, ([int]::MaxValue)), $words).Height
                $entry.texts += ,@{ text = [string]$text; width = $w; wrapped = $wrapped; height = $height; widths = $widths; longer = $longer }
            }
        }
        $entry.same = @()
        foreach ($text in $cases.others) {
            $entry.same += ,@([string]$text, [string]$wrap.Invoke($null, [object[]]@([string]$text, $font, [int][Math]::Round(200 * $scale), $words)))
        }
    }
    $out.scales[$key] = $entry
}
# The window as it is built: Settings > General in Korean at 200%, the notification card's help line under its switch.
$scale = 2.0
$form.GetField('dpiScale', $static).SetValue($null, $scale)
$box = [Drawing.SystemFonts]::MessageBoxFont
[Drawing.Font]$font = New-Object Drawing.Font $box.FontFamily, ($box.SizeInPoints * [single]($scale / $systemScale)), $box.Style, ([Drawing.GraphicsUnit]::Point)
$null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@('dark'))
$nowhere = [string](Join-Path $work 'nowhere')
$once = $assembly.GetType('CodexAutoResume.Bridge', $true).GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
$bridge = $assembly.GetType('CodexAutoResume.PersistentBridge', $true).GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$frame = New-Object QuietForm
$frame.FormBorderStyle = 'None'
$frame.ShowInTaskbar = $false
$frame.StartPosition = 'Manual'
$frame.Location = New-Object Drawing.Point -30000, -30000
# A top-level form is held to the screen's size, and a CI runner's screen is smaller than the window at
# 200%; the window inside is not, so it is given the opening size itself.
$opening = New-Object Drawing.Size ([int][Math]::Round(1000 * $scale)), ([int][Math]::Round(664 * $scale))
$frame.ClientSize = $opening
$window = $three.Invoke([object[]]@($bridge, (Read-Json 'strings-ko.json'), $font.PSObject.BaseObject))
$form.GetField('auditing', $instance).SetValue($window, $true)
$window.TopLevel = $false
$window.FormBorderStyle = 'None'
$window.MinimumSize = [Drawing.Size]::Empty
$window.Location = [Drawing.Point]::Empty
$window.ClientSize = $opening
$frame.Controls.Add($window)
Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
# Parsed here, not through Read-Json: a function's list comes back unrolled into an array.
$schema = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)))
Invoke-Window $window 'BuildEditors' @($schema, (Read-Json 'settings.json'))
$null = Invoke-Window $window 'ShowPage' @('settings')
$null = Invoke-Window $window 'ShowSection' @('general')
$window.Visible = $true
$frame.Show()
Pump 200
$found = @()
function Walk($control) {
    foreach ($child in $control.Controls) {
        if ($child -is [Windows.Forms.Label] -and [string]$child.Text -eq [string]$cases.help) {
            $inner = $child.ClientSize.Width - $child.Padding.Horizontal
            $lines = $null
            $method = $child.GetType().GetMethod('Lines', $instance)
            if ($null -ne $method) { $lines = [string]$method.Invoke($child, [object[]]@($inner)) }
            $script:found += ,@{ type = $child.GetType().Name; lines = $lines; height = $child.Height
                                 preferred = $child.GetPreferredSize((New-Object Drawing.Size $child.Width, 0)).Height; width = $inner }
        }
        Walk $child
    }
}
Walk $window
$out.help = $found
$frame.Close()
$frame.Dispose()
$form.GetField('dpiScale', $static).SetValue($null, $systemScale)
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 8 -Compress), $utf8)
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""


def breaks_anywhere(char) -> bool:
    """tray_popup._breaks_anywhere: Chinese and Japanese are set without spaces."""
    code = ord(char)
    return 0x2E80 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or 0xFF00 <= code <= 0xFFEF


def inserted_breaks(original: str, wrapped: str):
    """Each line break `wrapped` has where `original` has none, as (what came before it, what the original had there):
    a run of spaces it replaced, or '' where it was put between two characters. Raises if anything else changed."""
    found, i = [], 0
    for char in wrapped:
        if char != "\n":
            assert i < len(original) and original[i] == char, (original, wrapped)
            i += 1
            continue
        start = i
        while i < len(original) and original[i] in " \t\u3000":
            i += 1
        found.append((original[:start], original[start:i]))
    assert i == len(original), (original, wrapped)
    return found


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(GUI / name) for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=300)
        ko = l10n.catalog("ko")
        cls.texts = sorted({text for text in ko.values() if HANGUL.search(text) and len(text) >= 40 and "\n" not in text})
        others = []
        for locale in ("en", "de", "ja", "zh-CN"):
            catalog = l10n.catalog(locale)
            others += [catalog[key] for key in ("help.notification_card", "help.reduce_motion", "explain.none_selected")]
        cls.help = ko["help.notification_card"]
        cases = {"texts": cls.texts, "widths": list(WIDTHS), "others": others, "help": cls.help, "probe": "가Ag"}
        (work / "cases.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        reply = {"ok": True, "language": "ko", "strings": ko, "endonyms": dict(l10n.ENDONYMS),
                 "preference": "ko", "system_language": "ko"}
        (work / "strings-ko.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False), encoding="utf-8")
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        probe = work / "words.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_SCALES=json.dumps(SCALES)))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])
        self.assertEqual(sorted(self.answer["scales"]), ["%.1f" % scale for scale in SCALES])

    def cases(self):
        self.assertTrue(self.answer["wrap"], "the window has no Soft.Wrap: Windows breaks Korean wherever a line fills")
        for key, entry in sorted(self.answer["scales"].items()):
            for case in entry["texts"]:
                yield key, entry["line"], case

    def test_a_korean_line_ends_only_at_a_space(self):
        checked = 0
        for scale, _, case in self.cases():
            for before, gap in inserted_breaks(case["text"], case["wrapped"]):
                checked += 1
                after = case["text"][len(before) + len(gap):]
                with self.subTest(scale=scale, width=case["width"], at=before[-12:] + "|" + after[:12]):
                    self.assertTrue(gap or breaks_anywhere(before[-1]) or breaks_anywhere(after[0]),
                                    "a line may end at a space, or between two characters of Chinese or Japanese")
        self.assertGreater(checked, len(self.texts), "the texts were broken into lines at all")

    def test_windows_has_nothing_left_to_break(self):
        """Given the lines and the same width and format, Windows draws exactly those lines: each fits, and it breaks
        none of them again - between two syllables, as it would."""
        for scale, line, case in self.cases():
            lines = case["wrapped"].split("\n")
            with self.subTest(scale=scale, width=case["width"], text=case["text"][:20]):
                if any(width > case["width"] for width in case["widths"]):
                    # A word wider than the whole line has one of its own, for Windows to break where it must.
                    self.assertTrue(all(" " not in text.strip() for text, width in zip(lines, case["widths"])
                                        if width > case["width"]))
                    continue
                self.assertEqual(case["height"], len(lines) * line, "%d lines drawn as %d" % (len(lines), case["height"] // line))

    def test_each_line_is_as_long_as_fits(self):
        """No line ends early: the next word would not have fitted on it."""
        for scale, _, case in self.cases():
            lines = case["wrapped"].split("\n")
            for index, longer in enumerate(case["longer"]):
                if breaks_anywhere(lines[index + 1][:1] or " ") or breaks_anywhere(lines[index][-1:] or " "):
                    continue
                with self.subTest(scale=scale, width=case["width"], line=lines[index][-12:]):
                    self.assertGreater(longer, case["width"])

    def test_text_without_korean_is_left_to_windows(self):
        self.assertTrue(self.answer["wrap"], "the window has no Soft.Wrap")
        for entry in self.answer["scales"].values():
            for text, wrapped in entry["same"]:
                with self.subTest(text=text[:30]):
                    self.assertEqual(wrapped, text)

    def test_the_notification_cards_help_line_keeps_its_words_whole(self):
        """The line the review found split ('잠겨 있' / '거나'), in the window as it is built: Settings > General in
        Korean at 200%."""
        found = self.answer["help"]
        self.assertEqual(len(found), 1, "the notification card's help line, once")
        label = found[0]
        self.assertEqual(label["type"], "WrapLabel", "drawn in the lines it is measured in")
        self.assertIsNotNone(label["lines"])
        self.assertGreater(label["lines"].count("\n"), 0, "long enough to wrap at 200%")
        for before, gap in inserted_breaks(self.help, label["lines"]):
            self.assertTrue(gap, "a line of it ends inside a word: %s|" % before[-10:])
        self.assertEqual(label["height"], label["preferred"], "as tall as its lines")


class WordSourceTests(unittest.TestCase):
    """Everything in the window that wraps a help line, a note or a value measures and draws in the same lines."""

    @classmethod
    def setUpClass(cls):
        cls.dashboard = (GUI / "Dashboard.cs").read_text(encoding="utf-8")
        cls.controls = (GUI / "Controls.cs").read_text(encoding="utf-8")
        cls.window = (GUI / "SettingsApp.cs").read_text(encoding="utf-8")

    @staticmethod
    def method(source, signature):
        start = source.index(signature)
        return source[start:source.index("\n        }\n", start)]

    def test_help_notes_and_values_are_wrap_labels(self):
        self.assertIn("var label = new WrapLabel();", self.method(self.window, "private Label HelpText("))
        self.assertIn("var label = new WrapLabel();", self.method(self.dashboard, "private Label Value("))
        self.assertIn("internal sealed class NoteLabel : WrapLabel", self.dashboard)

    def test_what_draws_its_own_words_wraps_them_the_same_way(self):
        gates = self.dashboard[self.dashboard.index("internal sealed class GateList"):]
        gates = gates[:gates.index("\n    }\n")]
        choice = self.controls[self.controls.index("internal sealed class ChoiceCard"):]
        choice = choice[:choice.index("\n    }\n")]
        quote = self.controls[self.controls.index("internal sealed class SoftQuote"):]
        quote = quote[:quote.index("\n    }\n")]
        for name, body, count in (("GateList", gates, 2), ("ChoiceCard", choice, 4), ("SoftQuote", quote, 2)):
            with self.subTest(name):
                self.assertEqual(body.count("Soft.Wrap("), count, "every measure and every draw")
        note = self.method(self.window, "private int NoteHeight(")
        self.assertIn("reopenNote.Lines(width)", note, "the reopen note measured in the lines it is drawn in")
        audit = self.method(self.window, "private void AuditReopenNote(int width, bool beforeTheLayout")
        self.assertIn("reopenNote.Lines(inside)", audit)
        box = self.method(self.window, "private static Rectangle TextBox(")
        self.assertIn("wrap.Lines(room)", box, "the audit places a label's words as they are drawn")

    def test_windows_breaks_everything_that_is_not_korean(self):
        wrap = self.method(self.controls, "internal static string Wrap(")
        self.assertIn("if (!SplitsWords(text)", wrap)


if __name__ == "__main__":
    unittest.main()
