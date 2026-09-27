r"""v0.6.11: the Dashboard for a screen reader and at Windows' text size, and the Overview's line under Waiting.

* **A name for everything a person can act on.** The layout audit (gui/WindowAudit.cs, AuditSpoken) asks every
  button, tab, switch, check box, choice, drop-down, text box, number and list on every page, Settings section
  and dialog for the name a screen reader says, in every language at every scaling - LayoutAuditTests carries
  its findings with every other; here it is shown one control with no name, so a quiet report is the audit
  having asked.
* **Windows' text size.** "Make text bigger" (TextScale) draws the window that many times larger, its words and
  everything that holds them alike, as far as the screen it opens on holds the window at its narrowest and its
  tallest dialog - so nothing is cut at any text size: the audit runs at 150% and 225% here, in every language.
* **Keeping this PC awake shares the usage line.** It is said first on the Overview's one line under Waiting,
  the usage reading after it; a line longer than the card ends in an ellipsis, its whole text its tooltip and a
  fact on Diagnostics - and the card has no line more than it had.

Built and never shown, as every window test here is; nothing is asked of a bridge, a watcher or Windows' own
settings, which are read and never written.
"""
from __future__ import annotations

import copy
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

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def compile_window(work: Path) -> Path:
    exe = work / "CodexAutoResumeSettings.exe"
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                    "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                    *[str(path) for path in guiscan.sources()]],
                   check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
    return exe


def reply(locale: str) -> dict:
    return {"ok": True, "language": locale, "strings": l10n.catalog(locale), "endonyms": dict(l10n.ENDONYMS),
            "preference": locale, "system_language": locale}


def run_probe(script: str, work: Path, timeout: int, **env) -> dict:
    probe = work / "probe.ps1"
    probe.write_text(script, encoding="utf-8")
    done = subprocess.run([str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(probe)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=NO_WINDOW, env=dict(os.environ, CAR_WORK=str(work), **env))
    answer = work / "result.json"
    if done.returncode != 0 or not answer.is_file():
        raise AssertionError("the probe did not run: " + (done.stderr or done.stdout)[-3000:])
    return json.loads(answer.read_text(encoding="utf-8-sig"))


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$TS = $assembly.GetType('CodexAutoResume.TextScale', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$utf8 = New-Object Text.UTF8Encoding $false
function Parse($name) { return ,$J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8))) }
# Each argument as the object itself, never PowerShell's wrapper round it.
function Static($type, $name, $arguments) {
  $given = New-Object 'object[]' $arguments.Count
  for ($i = 0; $i -lt $arguments.Count; $i++) {
    $value = $arguments[$i]
    if ($null -ne $value -and $value -is [psobject]) { $value = $value.PSObject.BaseObject }
    $given[$i] = $value
  }
  return $type.GetMethod($name, $flags).Invoke($null, $given)
}
$out = @{}

# TextScale, pure: the percentage, the fitting and the font.
$out.factor = @{}
foreach ($percent in @(100, 125, 225, 99, 226, 0)) { $out.factor[[string]$percent] = [double](Static $TS 'Factor' @([int]$percent)) }
$out.fitting = @()
foreach ($case in @(@(2.25, 3840, 2100, 1.0), @(2.25, 1920, 1040, 1.0), @(2.25, 1920, 1040, 1.5), @(1.0, 1920, 1040, 1.0),
                    @(2.25, 800, 600, 1.0), @(0.5, 1920, 1040, 1.0))) {
  $out.fitting += ,[double](Static $TS 'Fitting' @([double]$case[0], (New-Object Drawing.Size ([int]$case[1]), ([int]$case[2])), [double]$case[3]))
}
$nine = New-Object Drawing.Font('Segoe UI', [float]9, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
$scaled = New-Object Drawing.Font('Segoe UI', [float]20.25, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
$eleven = New-Object Drawing.Font('Segoe UI', [float]11, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
$out.apply = @{
  usual = [double](Static $TS 'Apply' @($nine, [double]1.0, [double]1.0)).SizeInPoints
  same = [bool][object]::ReferenceEquals((Static $TS 'Apply' @($nine, [double]1.0, [double]1.0)), $nine)
  larger = [double](Static $TS 'Apply' @($nine, [double]1.0, [double]2.25)).SizeInPoints
  windowsScaled = [double](Static $TS 'Apply' @($scaled, [double]2.25, [double]2.25)).SizeInPoints
  fitted = [double](Static $TS 'Apply' @($scaled, [double]2.25, [double]1.5)).SizeInPoints
  own = [double](Static $TS 'Apply' @($eleven, [double]1.0, [double]1.5)).SizeInPoints
}
$out.read = [double](Static $TS 'Read' @())
$out.key = [string]$TS.GetField('Key', $flags).GetValue($null) + '|' + [string]$TS.GetField('Value', $flags).GetValue($null)

# AdoptTextSize: the whole window that many times the display's scale, and back.
$system = [double]$F.GetField('SystemScale', $flags).GetValue($null)
Static $F 'AdoptTextSize' @([double]2.25, [double]1.5) | Out-Null
$out.adopted = @(([double]$F.GetProperty('DpiScale', $flags).GetValue($null) / $system), [double]$F.GetField('TextSize', $flags).GetValue($null))
Static $F 'AdoptTextSize' @([double]1.0, [double]1.0) | Out-Null
$out.restored = ([double]$F.GetProperty('DpiScale', $flags).GetValue($null) / $system)

# The spoken-name audit shown a button with no name, one named by its text and one by its AccessibleName.
$panel = New-Object Windows.Forms.Panel
$nameless = New-Object Windows.Forms.Button
$texted = New-Object Windows.Forms.Button
$texted.Text = 'Pause'
$named = New-Object Windows.Forms.Button
$named.AccessibleName = 'Close'
$label = New-Object Windows.Forms.Label
$panel.Controls.AddRange(@($nameless, $texted, $named, $label))
$null = $panel.Handle
foreach ($c in @($nameless, $texted, $named, $label)) { $null = $c.Handle }
$findings = New-Object 'System.Collections.Generic.List[string]'
$F.GetField('AuditedSpoken', $flags).SetValue($null, 0)
Static $F 'AuditSpoken' @('canary', $panel, $findings) | Out-Null
$out.spokenCanary = @($findings)
$out.spokenCounted = [int]$F.GetField('AuditedSpoken', $flags).GetValue($null)

# The window, built and never shown, with a watcher that keeps this PC awake and a usage reading.
[string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
$bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
$persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
$form = $make.Invoke([object[]]@($persistent.PSObject.BaseObject, (Parse 'strings-en.json'), [Drawing.SystemFonts]::MessageBoxFont))
$F.GetField('auditing', $flags).SetValue($form, $true)
$form.TopLevel = $false
$form.ClientSize = New-Object Drawing.Size 1000, 664
function Waiting($name) {
  $F.GetMethod('ApplySnapshot', $flags).Invoke($form, @((Parse $name))) | Out-Null
  $F.GetMethod('ShowPage', $flags).Invoke($form, @('overview')) | Out-Null
  $form.PerformLayout()
  $line = $F.GetField('usageLine', $flags).GetValue($form)
  $card = $line.Parent
  $shown = @($card.Controls | Where-Object { $_.Visible -and $_ -is [Windows.Forms.Label] }).Count
  $tip = $F.GetField('lineTip', $flags).GetValue($form)
  $F.GetMethod('ShowPage', $flags).Invoke($form, @('diagnostics')) | Out-Null
  $diag = $F.GetField('diagWaiting', $flags).GetValue($form)
  return @{ text = $line.Text; tip = $tip.GetToolTip($line); diagnostics = $diag.Text; labels = $shown; height = $line.Height
            one = [Windows.Forms.TextRenderer]::MeasureText('Ag', $line.Font).Height + $line.Padding.Vertical; card = $card.Height
            spoken = $line.AccessibilityObject.Name }
}
$out.awake = Waiting 'snapshot-awake.json'
$out.plain = Waiting 'snapshot-plain.json'
$out.stopped = Waiting 'snapshot-stopped.json'
$F.GetMethod('MarkUnavailable', $flags).Invoke($form, @()) | Out-Null
$out.unreadable = @{ text = $F.GetField('usageLine', $flags).GetValue($form).Text; diagnostics = $F.GetField('diagWaiting', $flags).GetValue($form).Text }
$form.Dispose()
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    """The compiled window's own answers."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        cls.now = time.time()
        awake = fullest_snapshot(cls.now)
        plain = copy.deepcopy(awake)
        del plain["status"]["watcher"]["awake_since"]
        stopped = copy.deepcopy(awake)
        stopped["status"]["watcher_running"] = False
        stopped["status"]["watcher"]["running"] = False
        for name, value in (("awake", awake), ("plain", plain), ("stopped", stopped)):
            (work / ("snapshot-%s.json" % name)).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        (work / "strings-en.json").write_text(json.dumps(reply("en"), ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 600, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_text_size_is_windows_percentage_as_a_factor(self):
        self.assertEqual(self.answer["factor"], {"100": 1.0, "125": 1.25, "225": 2.25, "99": 1.0, "226": 1.0, "0": 1.0})
        self.assertEqual(self.answer["key"], "Software\\Microsoft\\Accessibility|TextScaleFactor")

    def test_the_text_size_is_read_where_windows_keeps_it(self):
        from codex_auto_resume.win import textsize
        self.assertEqual(self.answer["read"], textsize.read(), "the window and the popup read the one value alike")

    def test_the_window_opens_at_the_text_size_its_screen_holds(self):
        """At its narrowest the window is 816 by 468 logical pixels with its frame, and its tallest dialog 520 high
        with one: a 1920 by 1040 work area holds the window whole at 1.8 times, and at 150% at 1.2 times."""
        fitting = self.answer["fitting"]
        self.assertEqual(fitting[0], 2.25)
        self.assertAlmostEqual(fitting[1], 1040 / 568, places=6)
        self.assertAlmostEqual(fitting[2], 1040 / (1.5 * 568), places=6)
        self.assertEqual(fitting[3:], [1.0, 1.0, 1.0])

    def test_the_font_is_the_text_size_and_never_made_larger_twice(self):
        apply = self.answer["apply"]
        self.assertEqual((apply["usual"], apply["same"]), (9.0, True), "at 1 the message font itself")
        self.assertEqual(apply["larger"], 20.25)
        self.assertEqual(apply["windowsScaled"], 20.25, "a message font Windows made larger is not made larger again")
        self.assertEqual(apply["fitted"], 13.5, "and is taken back to the size the screen holds")
        self.assertEqual(apply["own"], 16.5, "a message font a person chose is made larger from its own size")

    def test_the_text_size_scales_the_whole_window_and_is_given_back(self):
        self.assertEqual(self.answer["adopted"], [1.5, 1.5])
        self.assertEqual(self.answer["restored"], 1.0)

    def test_the_audit_finds_a_control_with_no_name(self):
        self.assertEqual(len(self.answer["spokenCanary"]), 1, self.answer["spokenCanary"])
        self.assertIn("canary/Button :: has no name a screen reader can say", self.answer["spokenCanary"][0])
        self.assertEqual(self.answer["spokenCounted"], 3, "three buttons asked, the label not")

    def test_keeping_awake_shares_the_usage_line_and_adds_none(self):
        english = l10n.catalog("en")
        awake, plain = self.answer["awake"], self.answer["plain"]
        said = english["overview.awake"].split("{time}")[0]
        self.assertTrue(awake["text"].startswith(said), awake["text"])
        self.assertIn(" · " + plain["text"], awake["text"], "the usage reading after it, on the same line")
        self.assertTrue(plain["text"].startswith(english["usage.line"].split("{age}")[0]))
        self.assertEqual(awake["labels"], plain["labels"], "no line more on the Waiting card")
        self.assertEqual(awake["card"], plain["card"])
        self.assertEqual(awake["height"], awake["one"], "one line, ending in an ellipsis where it does not fit")

    def test_the_whole_line_is_its_tooltip_what_a_screen_reader_says_and_a_diagnostics_fact(self):
        for name in ("awake", "plain"):
            case = self.answer[name]
            with self.subTest(name):
                self.assertEqual(case["tip"], case["text"])
                self.assertEqual(case["diagnostics"], case["text"])
                self.assertEqual(case["spoken"], case["text"])

    def test_a_watcher_not_running_keeps_nothing_awake_and_an_unreadable_status_says_nothing(self):
        self.assertEqual(self.answer["stopped"]["text"], self.answer["plain"]["text"])
        self.assertEqual(self.answer["unreadable"], {"text": "", "diagnostics": "-"})


AUDIT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$audit = $form.GetMethod('LayoutAuditAt', $static)
$spoken = $form.GetField('AuditedSpoken', $static)
$utf8 = New-Object Text.UTF8Encoding $false
$work = [string]$env:CAR_WORK
$schema = [IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)
$current = [IO.File]::ReadAllText((Join-Path $work 'settings.json'), $utf8)
$snapshot = [IO.File]::ReadAllText((Join-Path $work 'snapshot.json'), $utf8)
$out = @{ audit = @{}; spoken = @{} }
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
  $catalog = [IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)
  $out.audit[$locale] = @{}
  $out.spoken[$locale] = @{}
  foreach ($case in (ConvertFrom-Json $env:CAR_CASES)) {
    $key = ([double]$case[0]).ToString('0.00', [Globalization.CultureInfo]::InvariantCulture) + 'x' +
           ([double]$case[1]).ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
    $out.audit[$locale][$key] = [string]$audit.Invoke($null, [object[]]@($schema, $current, $catalog, $snapshot, [double]$case[0], [double]$case[1]))
    $out.spoken[$locale][$key] = [int]$spoken.GetValue($null)
  }
}
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 5 -Compress), $utf8)
"""

# (display scaling, text size): the largest text size at the smallest and the largest scaling, and one between.
TEXT_CASES = ((1.0, 2.25), (1.25, 1.5), (2.0, 2.25))


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class TextSizeAuditTests(unittest.TestCase):
    """Every page, Settings section and dialog of the real window at Windows' text size, in every language, with
    the most the pages ever show - held to everything LayoutAuditTests holds it to at the usual size."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        current = dict(settings.defaults(), continuation_style="custom", custom_message_mode="per_reason")
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False),
                                            encoding="utf-8")
        for locale in l10n.LOCALES:
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply(locale), ensure_ascii=False),
                                                             encoding="utf-8")
        cls.answer = run_probe(AUDIT, work, 3000, CAR_EXE=str(exe), CAR_LOCALES=json.dumps(list(l10n.LOCALES)),
                               CAR_CASES=json.dumps(TEXT_CASES))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_nothing_is_cut_off_at_any_text_size_in_any_language(self):
        self.assertEqual(sorted(self.answer["audit"]), sorted(l10n.LOCALES))
        for locale in l10n.LOCALES:
            for scale, text in TEXT_CASES:
                report = self.answer["audit"][locale]["%.2fx%.2f" % (scale, text)]
                with self.subTest(locale=locale, scale=scale, text=text):
                    self.assertEqual(report, "", "\n" + "\n".join(report.splitlines()[:40]))

    def test_every_control_a_person_can_act_on_was_asked_its_name(self):
        for locale in l10n.LOCALES:
            for scale, text in TEXT_CASES:
                with self.subTest(locale=locale, scale=scale, text=text):
                    self.assertGreater(self.answer["spoken"][locale]["%.2fx%.2f" % (scale, text)], 150)


if __name__ == "__main__":
    unittest.main()
