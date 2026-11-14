r"""Save is in the accent only while something on Settings is unsaved (v0.6.23, the final's live acceptance).

On the owner's PC the Settings page's Save turned from grey to blue about a second after the page showed, with nothing
changed. Save was the accent - the page's primary action - whenever it could be pressed, and could not be while the page's
reads were on their way (SetBusy), which a window opened on Settings starts with: grey, then blue, which reads as "there are
changes to save". Save now rests as Close and Restore defaults do, and is the accent while the page holds an edit that is not
saved (Dirty) - as the panel's Save is quiet until there is something to save (panel.js renderFooter). Every editor tells it as
its value moves (WatchEdits), and the build, a status read of the sign-in entry and a save, which set what an edit is measured
from, tell it too (ShowSaveLook).

The real compiled window is built as LayoutAudit builds one - a bridge rooted where nothing is, nothing asked, nothing shown -
its editors built a step at a time from the settings' defaults, as a window opened on Settings builds them; then the busy
moment of a read, a status that says what Windows holds, and one edit of each kind made and taken back.

    PYTHONPATH="src;tests" python -m unittest test_gui_save_rests      (a GUI module: gui_lock.sh)
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import guiscan
from codex_auto_resume import l10n, settings

from test_gui_v0611_access import CSC, POWERSHELL, compile_window, run_probe

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Get-Field($target, [string]$name) { return $form.GetField($name, $instance).GetValue($target) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($target, $arguments)
}
$null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@('light'))
$accent = [int]$palette.GetField('Accent', $static).GetValue($null).ToArgb()
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
$bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
$window = $three.Invoke([object[]]@($bridge, (Read-Json 'strings-en.json'), [Drawing.SystemFonts]::MessageBoxFont))
$form.GetField('auditing', $instance).SetValue($window, $true)
$save = Get-Field $window 'saveButton'
$wanted = $save.GetType().GetMethod('Wanted', $instance)
function Look([string]$when) {
    $look = $wanted.Invoke($save, @())
    $fill = [int]$look.GetType().GetField('Fill', $instance).GetValue($look).ToArgb()
    return @{ when = $when; primary = [bool]$save.GetType().GetProperty('Primary', $instance).GetValue($save, $null)
              enabled = [bool]$save.Enabled; accent = ($fill -eq $accent); dirty = [bool](Invoke-Window $window 'Dirty' @()) }
}
$out = @{ looks = @() }
$out.looks += ,(Look 'built')
# Settings on screen, its editors built a step at a time from the read, as a window opened on Settings builds them.
$null = Invoke-Window $window 'ShowPage' @('settings')
# The schema read as it is, a List: a function's return of it would be unrolled into an array.
$schema = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)))
$form.GetField('pendingSchema', $instance).SetValue($window, $schema)
$form.GetField('pendingSettings', $instance).SetValue($window, (Read-Json 'settings.json'))
$steps = 0
while ([bool](Invoke-Window $window 'BuildEditorsStep' @())) {
    $steps++
    if ([bool]$save.GetType().GetProperty('Primary', $instance).GetValue($save, $null)) { $out.looks += ,(Look ('step ' + $steps)) }
}
$out.steps = $steps
$out.looks += ,(Look 'every step done')
# The page's reads on their way, and over: grey while busy, and then at rest - not the accent.
$null = Invoke-Window $window 'SetBusy' @($true)
$out.looks += ,(Look 'busy')
$null = Invoke-Window $window 'SetBusy' @($false)
$out.looks += ,(Look 'read')
# A status read saying what Windows holds for the sign-in switch: not an edit.
$null = Invoke-Window $window 'KnowStartup' @((Read-Json 'status.json'), $null)
$out.looks += ,(Look 'status read')
# What the clock does each second (none before v0.6.23: then the look is as the steps left it).
if ($form.GetMethod('ShowSaveLook', $instance)) { $null = Invoke-Window $window 'ShowSaveLook' @() }
$out.looks += ,(Look 'clock')

# One edit of each kind, made and taken back.
$editors = Get-Field $window 'editors'
$out.edits = @{}
function Edit([string]$name, [scriptblock]$change, [scriptblock]$back) {
    & $change
    $made = Look ($name + ' changed')
    & $back
    $taken = Look ($name + ' back')
    $out.edits[$name] = @($made, $taken)
}
$combo = $editors['theme']
$was = $combo.SelectedIndex
Edit 'combo' { $combo.SelectedIndex = $(if ($was -eq 0) { 1 } else { 0 }) } { $combo.SelectedIndex = $was }
$check = $editors['notifications']
Edit 'check' { $check.Checked = -not $check.Checked } { $check.Checked = -not $check.Checked }
$spin = $editors['max_recovery_attempts']
$value = $spin.Value
Edit 'number' { $spin.Value = $(if ($value -lt $spin.Maximum) { $value + 1 } else { $value - 1 }) } { $spin.Value = $value }
$startup = $editors['__startup']
Edit 'startup' { $startup.Checked = -not $startup.Checked } { $startup.Checked = -not $startup.Checked }
# The message for every interruption, a text area's box (jsonValues, not an editor of its own).
$area = Get-Field $window 'globalText'
$box = $area.GetType().GetField('Box', $instance).GetValue($area)
$before = $box.Text
Edit 'text' { $box.Text = $before + 'x' } { $box.Text = $before }
$window.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 6), $utf8)
"""


class SourceTests(unittest.TestCase):
    def test_save_is_made_at_rest_and_follows_the_unsaved_edits(self):
        footer = guiscan.member_body("SettingsForm", "BuildFooter")
        self.assertTrue('saveButton = MakeButton(S("action.save", "Save"), false, delegate { Save(); });' in footer,
                        "Save is made at rest, not as the page's primary action")
        look = guiscan.member_body("SettingsForm", "ShowSaveLook")
        self.assertIn("bool dirty = editorSteps == null && Dirty();", look)
        self.assertIn("if (save.Primary != dirty) save.Primary = dirty;", look)

    def test_whatever_sets_what_an_edit_is_measured_from_tells_save(self):
        steps = guiscan.member_body("SettingsForm", "EditorSteps")
        self.assertLess(steps.rindex("baseline = EditorValues();"), steps.rindex("WatchEdits(columns);"))
        self.assertIn("ShowSaveLook();", guiscan.member_body("SettingsForm", "KnowStartup"))
        save = guiscan.member_body("SettingsForm", "Save")
        self.assertIn("baseline = values;\n                ShowSaveLook();", save.replace("\r\n", "\n"))


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class SaveRestsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        (work / "status.json").write_text(json.dumps({"startup_enabled": True}), encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 300, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_with_nothing_changed_save_never_takes_the_accent(self):
        looks = self.answer["looks"]
        self.assertGreater(self.answer["steps"], 3, "the editors were meant to be built in steps")
        self.assertEqual([look["when"] for look in looks],
                         ["built", "every step done", "busy", "read", "status read", "clock"],
                         "Save took the accent during a step of the build: %s" % looks)
        for look in looks:
            with self.subTest(look["when"]):
                self.assertFalse(look["dirty"])
                self.assertFalse(look["primary"])
                self.assertFalse(look["accent"], "nothing was changed: Save is not the accent")
        self.assertFalse(looks[2]["enabled"], "while a read is on its way it cannot be pressed")
        self.assertTrue(looks[3]["enabled"])

    def test_an_edit_gives_save_the_accent_and_taking_it_back_takes_it_away(self):
        edits = self.answer["edits"]
        self.assertEqual(sorted(edits), ["check", "combo", "number", "startup", "text"])
        for name, (made, taken) in edits.items():
            with self.subTest(name):
                self.assertEqual((made["dirty"], made["primary"], made["accent"]), (True, True, True), made)
                self.assertEqual((taken["dirty"], taken["primary"], taken["accent"]), (False, False, False), taken)


if __name__ == "__main__":
    unittest.main()
