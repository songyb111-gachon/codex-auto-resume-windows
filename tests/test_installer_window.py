"""The installer window (v0.6.16): a setup program's wizard, the Dashboard's update and the uninstall Add or remove
programs runs, in one window of the product's own design.

gui/InstallerFlow.cs decides what it asks and what each answer becomes, gui/InstallerWindow.cs shows it,
build/setup/SetupWindow.cs gives it what a setup program has, gui/SettingsRemove.cs what the entry in Add or remove
programs has, and gui/DashboardMaintenance.cs runs the Dashboard's update in it. What is held here:

* FlowTests - compiled into a setup program around a TEST archive (never the real installer) and called through
  reflection, with no window shown: the pages of each way it is shown; the switches each answer becomes, which are
  install.ps1's own (-SkipStartup on a first installation only, -AllowEditionChange only once asked, -Purge, and
  -Silent always); the bar's place and step from install.ps1's, the bootstrap's and the uninstall's own lines, never
  going back; the edition rule against install.ps1's; the language rules and endonyms against l10n's.
* ScriptTests - every line the bar reads is one the scripts print, so a reworded step fails here, not on a
  person's screen.
* LayoutAuditTests - InstallerAudit, the window measuring itself: every page of every way it is shown, in every
  language at every scaling and text size, cut off nowhere - and a canary, so a quiet report means something.
* CatalogTests and SourceTests - every word it says is in the catalogs; no console window in the window's mode
  (CREATE_NO_WINDOW on every console child); no elevation; nothing under HKLM.

Nothing here runs the real installer, touches a real home or the registry, or shows a window: the audit lays the
window out without showing it, as the settings window's audit does (tests/test_gui_layout.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import guiscan  # noqa: E402
import languages  # noqa: E402
import make_setup  # noqa: E402

from codex_auto_resume import l10n  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FLOW = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
WINDOW = (ROOT / "gui" / "InstallerWindow.cs").read_text(encoding="utf-8")
SETUP_WINDOW = (ROOT / "build" / "setup" / "SetupWindow.cs").read_text(encoding="utf-8")
REMOVE = (ROOT / "gui" / "SettingsRemove.cs").read_text(encoding="utf-8")
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)
TEXT_SIZES = (1.0, 1.5, 2.25)
# Every scaling at Windows' usual text size, and every text size at 100%: the settings window's audit measures the
# scalings (tests/test_gui_layout.py), and a larger text size is the whole window that many times larger again
# (TextScale), so each is audited once rather than at every scaling - the audit builds every page of six ways the
# window is shown, five endings each, and all fifteen pairs took a quarter of an hour.
PAIRS = [(scale, 1.0) for scale in SCALES] + [(1.0, text) for text in TEXT_SIZES if text != 1.0]

TEST_ENTRIES = {"Install.cmd": b"@echo off\r\nexit /b 0\r\n",
                "install/install.ps1": b"# never run\r\n",
                "payload/app/src/codex_auto_resume/__init__.py": b"",
                "payload/app/.codex-plugin/plugin.json": b'{"name": "codex-auto-resume", "version": "9.9.9"}\n'}

# install.ps1's lines in the order a first installation prints them, the bootstrap's -Update before its own, and the
# uninstall's: what the bar is read from (FlowTests), each one checked against the scripts (ScriptTests).
INSTALLING = ["", "Codex Auto Resume", "edition: standard", "  [ok] Found Codex", "  Updating program files",
              "  Stopping the running watcher so the new version takes over", "  [ok] The previous watcher stopped",
              "  Closing the Dashboard so it opens again on the new version", "  [ok] The Dashboard closed",
              "  Copying the program files into place",
              "  [ok] Bundled Python 3.13 (no system Python needed)", "  Registering the Codex plugin",
              "  [ok] Codex plugin installed", "  Setting up the watcher", "    (the setup step's words, in any language)",
              "  Checking the installation", "Installed and running."]
UPDATING = ["Codex Auto Resume - setting up", "edition: standard",
            "  Asking github.com which release is newest. Nothing is uploaded, and no page is read.",
            "  Downloading v9.9.9 from github.com over HTTPS.", "  [ok] SHA-256 matches the digest pinned in this plugin",
            "  [ok] Archive contents verified as Codex Auto Resume v9.9.9", "  Installing", "edition: standard",
            "  [ok] Found Codex", "  Updating program files", "  Stopping the running watcher so the new version takes over",
            "  Closing the Dashboard so it opens again on the new version", "  Copying the program files into place",
            "  [ok] Bundled Python 3.13 (no system Python needed)", "  Registering the Codex plugin",
            "  Setting up the watcher", "  Checking the installation", "Updated. Your settings and pending recoveries were kept."]
REMOVING = ["Codex Auto Resume", "  Closing the Dashboard so its files can be removed", "  [ok] The Dashboard closed",
            "  Removing the watcher, autostart, notification identity and Start Menu entry",
            "  Removing the Codex plugin", "  Removing the marketplace this installation registered",
            "  Removing program files", "Removed. Settings and pending recoveries were kept."]

# A changelog section as the release's are written: a title, a link line, wrapped paragraphs with emphasis, links
# and code, headings and a list whose items wrap (the acceptance's notes page, 2026-10-18).
NOTES_SAMPLE = ("v9.9.9 — A title\n\n"
                "[The commits in this release](https://example.com/compare/v9.9.8...v9.9.9)\n\n"
                "**From v9.9.8, an ordinary update.** v9.9.8's *Check for updates*\n"
                "offers it, the final of a line that went out\n"
                "in four pre-releases ([beta](#v999-beta) and [beta.2](#v999-beta2)).\n\n"
                "### Both editions\n\n"
                "#### New\n\n"
                "- **Rescan** on the Pending page. It reads `reopen-after-update*.txt` and\n"
                "  `*.old-*` folders, once you confirm.\n"
                "- A *second* item.\n"
                "1. A numbered one\n")
NOTES_READABLE = ("v9.9.9 — A title\r\n\r\n"
                  "From v9.9.8, an ordinary update. v9.9.8's Check for updates offers it, the final of a line that "
                  "went out in four pre-releases (beta and beta.2).\r\n\r\n"
                  "Both editions\r\n\r\n"
                  "New\r\n\r\n"
                  "• Rescan on the Pending page. It reads reopen-after-update*.txt and *.old-* folders, once you "
                  "confirm.\r\n"
                  "• A second item.\r\n"
                  "• A numbered one")

# Every phase the installer window shows, as (name, mode, page, code, watcher unconfirmed, previous watcher running)
# for InstallerFlow.Light, and the light that is true there (the owner, 2026-10-20). A code of None is a page before
# the run, which is asked twice - with no code yet and with 0 - for the page decides there, whatever the code.
NO_CODE = -2147483648
PHASES = [
    ("welcome", "install", "welcome", None, False, False, "idle"),
    ("options", "install", "options", None, False, False, "idle"),
    ("edition_switch", "install", "options", None, False, False, "idle"),
    ("maintain", "install", "maintain", None, False, False, "idle"),
    ("uninstall_confirm", "uninstall", "confirm", None, False, False, "idle"),
    ("update_notes", "update", "notes", None, False, False, "idle"),
    ("installing", "install", "progress", None, False, False, "checking"),
    ("updating", "update", "progress", None, False, False, "checking"),
    ("uninstalling", "uninstall", "progress", None, False, False, "checking"),
    ("installed_running", "install", "finish", 0, False, False, "monitoring"),
    ("updated_running", "update", "finish", 0, False, False, "monitoring"),
    ("installed_unconfirmed", "install", "finish", 0, True, False, "idle"),
    ("updated_unconfirmed", "update", "finish", 0, True, False, "idle"),
    ("updated_previous_still_running", "update", "finish", 0, False, True, "attention"),
    ("install_failed", "install", "finish", 1, False, False, "idle"),
    ("edition_refused", "install", "finish", 14, False, False, "idle"),
    ("not_started", "install", "finish", -1, False, False, "idle"),
    ("still_working", "update", "finish", -2, False, False, "checking"),
    ("uninstalled", "uninstall", "finish", 0, False, False, "idle"),
    ("uninstall_failed", "uninstall", "finish", 1, False, False, "idle"),
]


def _phase_cases():
    cases = []
    for name, mode, page, code, unconfirmed, previous, _ in PHASES:
        if code is None:
            cases.append([name, mode, page, NO_CODE, unconfirmed, previous])
            cases.append([name + "@0", mode, page, 0, unconfirmed, previous])
        else:
            cases.append([name, mode, page, code, unconfirmed, previous])
    return cases


PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
function T($name) { $assembly.GetType('CodexAutoResume.' + $name, $true) }
function Call($type, $name, $arguments) { (T $type).GetMethod($name, $any).Invoke($null, [object[]]$arguments) }
$FlowType = T 'InstallerFlow'
function NewFlow($mode, $edition, $installed) {
    $FlowType.GetConstructors($any)[0].Invoke([object[]]@([string]$mode, 'C:\Users\ExampleUser\.codex-auto-resume',
                                                      [string]$edition, $installed, '9.9.9'))
}
function SetField($flow, $field, $value) { $FlowType.GetField($field, $any).SetValue($flow, $value) }
# Internal members, which PowerShell's own dot does not reach.
function Of($object, $name) { $object.GetType().GetProperty($name, $any).GetValue($object, $null) }
function CallOn($object, $name, $arguments) { $object.GetType().GetMethod($name, $any).Invoke($object, [object[]]$arguments) }
# Lists go in as string arrays, which reflection takes for IEnumerable<string> and IList<string>: a list PowerShell
# made is handed over wrapped, and refused.
function Switches($flow, $given) {
    @($FlowType.GetMethod('Switches', $any).Invoke($flow, [object[]]@(,[string[]]@($given))))
}
$out = @{}
$input_ = ConvertFrom-Json ([IO.File]::ReadAllText($env:CAR_INPUT, [Text.Encoding]::UTF8))

# Pages, start and switches.
$first = NewFlow 'install' 'standard' $null
$upgrade = NewFlow 'install' 'standard' 'standard'
$change = NewFlow 'install' 'standard' 'advanced'
$update = NewFlow 'update' 'standard' 'standard'
$remove = NewFlow 'uninstall' 'standard' 'standard'
$out.pages = @{ install = @(CallOn $first 'Pages' @()); update = @(CallOn $update 'Pages' @()); uninstall = @(CallOn $remove 'Pages' @()) }
$out.switches = @{}
$out.switches.first = Switches $first @()
SetField $first 'StartAtSignIn' $false
$out.switches.first_no_startup = Switches $first @()
$out.switches.given = Switches $first @('-SkipStartup', '-AllowEditionChange', '-Silent', '-Other')
SetField $upgrade 'StartAtSignIn' $false
$out.switches.upgrade_no_startup = Switches $upgrade @()
$out.can_start = @{ unasked = (CallOn $change 'CanStart' @()); upgrade = (CallOn $upgrade 'CanStart' @()) }
$out.switches.change_unasked = Switches $change @()
SetField $change 'ChangeEdition' $true
$out.can_start.asked = (CallOn $change 'CanStart' @())
$out.switches.change_asked = Switches $change @()
$out.switches.remove = Switches $remove @()
SetField $remove 'Purge' $true
$out.switches.remove_purge = Switches $remove @()
$out.switches.update = Switches $update @()

# The bar, line by line.
$advance = (T 'InstallerProgress').GetMethod('Advance', $any)
$out.bar = @{}
foreach ($mode in @('install', 'update', 'uninstall')) {
    $at = [double]0; $step = 'starting'; $seen = @()
    foreach ($line in $input_.lines.$mode) {
        $arguments = [object[]]@($mode, [string]$line, $at, $step)
        $moved = $advance.Invoke($null, $arguments)
        $at = [double]$arguments[2]; $step = [string]$arguments[3]
        $seen += ,@($moved, $at, $step)
    }
    $out.bar[$mode] = $seen
}
$out.unpacked = @((Call 'InstallerProgress' 'Unpacked' @(0, 10)), (Call 'InstallerProgress' 'Unpacked' @(5, 10)),
                  (Call 'InstallerProgress' 'Unpacked' @(10, 10)), (Call 'InstallerProgress' 'Unpacked' @(3, 0)))

# Languages.
$out.normalized = @{}
foreach ($tag in $input_.tags) { $out.normalized[[string]$tag] = Call 'InstallerLanguages' 'Normalize' @([string]$tag) }
$list = [string[]]@('de-AT', 'ko-KR')
$none = [string[]]@()
$out.from_system = @((Call 'InstallerLanguages' 'FromSystem' @(,$list)), (Call 'InstallerLanguages' 'FromSystem' @(,$none)))
$out.resolved = @((Call 'InstallerLanguages' 'Resolve' @('ja', $list)), (Call 'InstallerLanguages' 'Resolve' @('system', $list)),
                  (Call 'InstallerLanguages' 'Resolve' @('ar', $list)), (Call 'InstallerLanguages' 'Resolve' @($null, $list)))
$Languages = T 'InstallerLanguages'
$out.all = @($Languages.GetField('All', $any).GetValue($null))
$out.held = @($Languages.GetField('Held', $any).GetValue($null))
$out.offered = @(Call 'InstallerLanguages' 'Offered' @())
$names = @{}
$endonyms = $Languages.GetField('Endonyms', $any).GetValue($null)
foreach ($key in $endonyms.Keys) { $names[$key] = $endonyms[$key] }
$out.endonyms = $names

# Editions, homes and versions.
$out.edition_of = @{}
foreach ($case in $input_.trees.PSObject.Properties) { $out.edition_of[$case.Name] = Call 'InstallerFlow' 'EditionOfSource' @([string]$case.Value) }
$out.installed_at = @{}
foreach ($case in $input_.homes.PSObject.Properties) { $out.installed_at[$case.Name] = Call 'InstallerFlow' 'InstalledAt' @([string]$case.Value) }
$entries = [string[]]@('payload/app/src/codex_auto_resume_advanced/__init__.py')
$plain = [string[]]@('payload/app/src/Codex_Auto_Resume_Advanced/__init__.py')
$out.entries = @((Call 'InstallerFlow' 'EditionOfEntries' @(,$entries)), (Call 'InstallerFlow' 'EditionOfEntries' @(,$plain)))
$out.home = @((Call 'InstallerFlow' 'HomeFrom' @('', 'C:\Users\ExampleUser')), (Call 'InstallerFlow' 'HomeFrom' @('D:\Elsewhere', 'C:\Users\ExampleUser')))
$out.version = @((Call 'InstallerFlow' 'VersionOf' @('{"version": "1.2.3"}')), (Call 'InstallerFlow' 'VersionOf' @('not json')))

# Words: the outcome of each code, and the steps' keys.
$WordsType = T 'InstallerWords'
$english = $WordsType.GetConstructors($any)[0].Invoke([object[]]@($null, 'en'))
$out.outcome = @{}
foreach ($code in @(0, 1, 14, 43, -2, -1)) {
    $out.outcome[[string]$code] = @($WordsType.GetMethod('Outcome', $any).Invoke($english, [object[]]@('install', [int]$code)),
                                    $WordsType.GetMethod('Explain', $any).Invoke($english, [object[]]@([int]$code)))
}
$out.removed = $WordsType.GetMethod('Outcome', $any).Invoke($english, [object[]]@('uninstall', [int]0))
$out.step_keys = @(Call 'InstallerWords' 'StepKeys' @())

# The window, built and never shown: its pages in order, and what a finished run leaves it saying.
$WindowType = T 'InstallerWindow'
$font = [System.Drawing.SystemFonts]::MessageBoxFont
$walk = NewFlow 'install' 'standard' 'advanced'
$built = $WindowType.GetConstructors($any)[0].Invoke([object[]]@($walk, $english, $null, $null, $null, $font))
$pages = @(Of $built 'Page')
$null = CallOn $built 'Go' @(1)
$pages += (Of $built 'Page')
$forward = $WindowType.GetField('forward', $any).GetValue($built)
$enabled = [System.Windows.Forms.Control].GetProperty('Enabled').GetValue($forward, $null)
$out.window = @{ pages = $pages; start_enabled_unasked = $enabled }
$null = CallOn $built 'Finished' @(14, "  [x]  This archive is the standard edition")
$out.window.after = @((Of $built 'Page'), (Of $built 'Code'), (Of $built 'OpenDashboard'), (Of $built 'Log').Contains('[x]'))
$done = $WindowType.GetConstructors($any)[0].Invoke([object[]]@((NewFlow 'install' 'standard' $null), $english, $null, $null, $null, $font))
$null = CallOn $done 'Finished' @(0, "The watcher could not be confirmed running, so nothing is being watched yet.")
$out.window.done = @((Of $done 'Page'), (Of $done 'Code'), (Of $done 'OpenDashboard'))

# An update (v0.6.16): its Notes page, the Dashboard it opens by itself, and Later, which closes with nothing installed.
$update = NewFlow 'update' 'standard' 'standard'
$FlowType.GetField('From', $any).SetValue($update, '9.9.8')
$updating = $WindowType.GetConstructors($any)[0].Invoke([object[]]@($update, $english, $null, $null, $null, $font))
$null = CallOn $updating 'Finished' @(0, "  Checking the installation")
$out.updated = @((Of $updating 'Page'), (Of $updating 'Code'), (Of $updating 'OpenDashboard'))
$reopened = $WindowType.GetConstructors($any)[0].Invoke([object[]]@((NewFlow 'install' 'standard' 'standard'), $english, $null, $null, $null, $font))
$null = CallOn $reopened 'Finished' @(0, "  [ok] The Dashboard was opened again on the new version")
$out.reopened = @((Of $reopened 'OpenDashboard'), @(@(CallOn $reopened 'ShownRows' @()) | Where-Object { $_.GetType().Name -eq 'SoftCheck' }).Count)
$out.updated_switches = @(@(CallOn $updating 'ShownRows' @()) | Where-Object { $_.GetType().Name -eq 'SoftCheck' }).Count
$later = $WindowType.GetConstructors($any)[0].Invoke([object[]]@((NewFlow 'update' 'standard' 'standard'), $english, $null, $null, $null, $font))
$null = CallOn $later 'Finished' @(-3, "update: later 9.9.8 9.9.9")
$out.later = @((Of $later 'Code'), (Of $later 'OpenDashboard'), $later.IsDisposed)
# The exit code on the Finish page and at the end of the log - only where the installer ended with one.
$unstarted = $WindowType.GetConstructors($any)[0].Invoke([object[]]@((NewFlow 'install' 'standard' $null), $english, $null, $null, $null, $font))
$null = CallOn $unstarted 'Finished' @(-1, "could not start")
$out.exit_code = @((@(@(CallOn $done 'ShownRows' @()) | ForEach-Object { [string]$_.Text }) -contains 'Exit code: 0'),
                   (Of $done 'Log').TrimEnd().EndsWith('Exit code: 0'), (Of $built 'Log').TrimEnd().EndsWith('Exit code: 14'),
                   (Of $later 'Log').Contains('Exit code'), (Of $unstarted 'Log').Contains('Exit code'))

# What is new: a version's section of a changelog, its brief, and which file is read.
$notes = T 'InstallerNotes'
$changelog = [IO.File]::ReadAllText($env:CAR_CHANGELOG, [Text.Encoding]::UTF8)
$out.notes = @{}
foreach ($version in @('0.6.16-beta.3', '0.6.16-beta', '0.6.16', '9.9.9')) {
    $out.notes[$version] = $notes.GetMethod('Section', $any).Invoke($null, [object[]]@($changelog, $version))
}
$out.brief = $notes.GetMethod('Brief', $any).Invoke($null, [object[]]@([string]$out.notes['0.6.16-beta.3'], 3))
# The notes as the Notes page shows them: plain text, never the changelog's Markdown (v0.6.16 acceptance).
$readable = $notes.GetMethod('Readable', $any)
$out.readable = @{ sample = $readable.Invoke($null, [object[]]@([string]$input_.sample))
                   real = $readable.Invoke($null, [object[]]@([string]$out.notes['0.6.16'])) }
$shown = NewFlow 'update' 'standard' 'standard'
$FlowType.GetField('NotesText', $any).SetValue($shown, [string]$input_.sample)
$showing = $WindowType.GetConstructors($any)[0].Invoke([object[]]@($shown, $english, $null, $null, $null, $font))
$null = CallOn $showing 'ShowPage' @('notes')
function BoxOf($window, $name) {
    $area = $WindowType.GetField($name, $any).GetValue($window)
    $area.GetType().GetField('Box', $any).GetValue($area)
}
$out.readable.box = [string](BoxOf $showing 'notesArea').Text
$log = BoxOf $showing 'logArea'
$out.log_box = @([bool]$log.WordWrap, [string]$log.ScrollBars)
$docs = [string]$env:CAR_DOCS
$out.file = @(($notes.GetMethod('FileFor', $any).Invoke($null, [object[]]@($docs, 'ko'))),
              ($notes.GetMethod('FileFor', $any).Invoke($null, [object[]]@($docs, 'ja'))),
              ($notes.GetMethod('FileFor', $any).Invoke($null, [object[]]@($docs, 'en'))))

# An update's time limit, which the Notes page's wait does not count against.
$ClockType = T 'InstallerClock'
function NewClock($limit) { $ClockType.GetConstructors($any)[0].Invoke([object[]]@([long]$limit)) }
$clock = NewClock 1000
$out.clock = @((CallOn $clock 'Over' @([long]999)), (CallOn $clock 'Over' @([long]1000)))
$clock = NewClock 1000
$null = CallOn $clock 'Pause' @([long]100)
$out.clock += (CallOn $clock 'Over' @([long]1500000))
$null = CallOn $clock 'Resume' @([long]5000)
$out.clock += @((CallOn $clock 'Over' @([long]5500)), (CallOn $clock 'Over' @([long]5899)), (CallOn $clock 'Over' @([long]5900)))

# What a setup program's window shows for its command line.
$SetupType = $assembly.GetType('CodexAutoResumeSetup.SetupWindow', $true)
$out.setup = @{}
foreach ($case in @(@('plain'), @('uninstall', '-Uninstall'), @('purge', '-uninstall', '-Purge'), @('skip', '-SkipStartup'))) {
    $given = [string[]]@($case | Select-Object -Skip 1)
    $flow = $SetupType.GetMethod('FlowFor', $any).Invoke($null, [object[]]@($given, 'C:\Users\ExampleUser\.codex-auto-resume',
                                                                            'standard', 'standard', '9.9.9', '9.9.8'))
    $out.setup[$case[0]] = @([string]$FlowType.GetField('Mode', $any).GetValue($flow), (CallOn $flow 'Pages' @())[0],
                             ((Switches $flow $given) -join ' '))
}

# The look it opens in: the installation's stored theme, design and motion, else the Dashboard's defaults.
$out.look = @{}
foreach ($case in $input_.looks.PSObject.Properties) {
    $out.look[$case.Name] = @($SetupType.GetMethod('LookAt', $any).Invoke($null, [object[]]@([string]$case.Value)))
}

# Over its own version, installed already: Repair or Remove first (the owner, 2026-10-17); a newer one updates.
function SetupFlow($given, $installed, $from) {
    $SetupType.GetMethod('FlowFor', $any).Invoke($null, [object[]]@([string[]]@($given), 'C:\Users\ExampleUser\.codex-auto-resume',
                                                                      'standard', $installed, '9.9.9', $from))
}
function Told($flow, $given) {
    @([string]$FlowType.GetField('Mode', $any).GetValue($flow), ((CallOn $flow 'Pages' @()) -join ' '),
      ((Switches $flow $given) -join ' '), [bool](Of $flow 'Repair'))
}
$out.maintain = @{}
$same = SetupFlow @() 'standard' '9.9.9'
$out.maintain.repair = Told $same @()
$null = CallOn $same 'Choose' @($true)
$out.maintain.remove = Told $same @()
$null = CallOn $same 'Choose' @($false)
$out.maintain.repair_again = Told $same @()
$out.maintain.older = Told (SetupFlow @() 'standard' '9.9.8') @()
$out.maintain.other_edition = Told (SetupFlow @() 'advanced' '9.9.9') @()
$out.maintain.asked_uninstall = Told (SetupFlow @('-Uninstall') 'standard' '9.9.9') @('-Uninstall')
$out.maintain.unreadable = Told (SetupFlow @() 'standard' '') @()
# The window over it, built and never shown: its first page, the two ways on it and what the button says.
$maintaining = $WindowType.GetConstructors($any)[0].Invoke([object[]]@((SetupFlow @() 'standard' '9.9.9'), $english, $null, $null, $null, $font))
$ways = @(@(CallOn $maintaining 'ShownRows' @()) | Where-Object { $_.GetType().Name -eq 'ChoiceCard' })
$button = $WindowType.GetField('forward', $any).GetValue($maintaining)
$out.maintain.window = @((Of $maintaining 'Page'), $ways.Count, [string]$button.Text, @($ways | ForEach-Object { $_.Checked }))
$ways[1].Checked = $true
$out.maintain.window_remove = @([string]$FlowType.GetField('Mode', $any).GetValue((Of $maintaining 'Flow')), [string]$button.Text)
$ways[0].Checked = $true
$out.maintain.window_repair = @([string]$FlowType.GetField('Mode', $any).GetValue((Of $maintaining 'Flow')), [string]$button.Text)
$null = CallOn $maintaining 'Finished' @(0, "  Checking the installation")
$out.maintain.finished = [string](@(CallOn $maintaining 'ShownRows' @())[0].Text)

# The status light, phase by phase (InstallerFlow.Light, the one place it is decided), and the windows above showing it.
$out.light = @{}
foreach ($case in $input_.phases) {
    $out.light[[string]$case[0]] = [string](Call 'InstallerFlow' 'Light' @([string]$case[1], [string]$case[2], [int]$case[3],
                                                                          [bool]$case[4], [bool]$case[5]))
}
function LightOf($window) {
    $dot = $WindowType.GetField('light', $any).GetValue($window)
    [string]$dot.GetType().GetProperty('State', $any).GetValue($dot, $null)
}
$gone = $WindowType.GetConstructors($any)[0].Invoke([object[]]@((NewFlow 'uninstall' 'advanced' 'advanced'), $english, $null, $null, $null, $font))
$asking = LightOf $gone
$null = CallOn $gone 'Finished' @(0, "Removed. Settings and pending recoveries were kept.")
$out.window_light = @{ removed = (LightOf $gone); confirm = $asking; unconfirmed = (LightOf $done); updated = (LightOf $updating)
                       refused = (LightOf $built); unstarted = (LightOf $unstarted); repaired = (LightOf $maintaining) }
$out | ConvertTo-Json -Depth 6 -Compress
"""

AUDIT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$audit = $assembly.GetType('CodexAutoResume.InstallerAudit', $true).GetMethod('LayoutAudit', [Reflection.BindingFlags]'Static,NonPublic')
$out = @{}
foreach ($case in (ConvertFrom-Json $env:CAR_CASES)) {
    $catalog = [IO.File]::ReadAllText([string]$case.catalog, [Text.Encoding]::UTF8)
    $key = [string]$case.name
    $out[$key] = @{}
    foreach ($pair in (ConvertFrom-Json $env:CAR_PAIRS)) {
        $scale = [double]$pair[0]; $text = [double]$pair[1]
        $out[$key][('{0:F2}/{1:F2}' -f $scale, $text)] = [string]$audit.Invoke($null, [object[]]@([string]$catalog, [string]$case.language, $scale, $text))
    }
}
[IO.File]::WriteAllText($env:CAR_RESULT, ($out | ConvertTo-Json -Depth 4 -Compress), (New-Object Text.UTF8Encoding $false))
"""


def _build(work: Path) -> Path:
    archive = work / "Test-v9.9.9-win-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in TEST_ENTRIES.items():
            bundle.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data, compress_type=zipfile.ZIP_DEFLATED)
    return make_setup.build(archive, work / "out", "standard", "9.9.9")


def _powershell(script: str, work: Path, timeout: int, **environment) -> subprocess.CompletedProcess:
    probe = work / ("probe-%d.ps1" % len(list(work.glob("probe-*.ps1"))))
    probe.write_text(script, encoding="utf-8-sig")
    return subprocess.run([str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(probe)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=NO_WINDOW, env=dict(os.environ, **environment))


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class FlowTests(unittest.TestCase):
    TAGS = ["ko", "ko-KR", "en-US", "zh", "zh-Hant-TW", "zh-HK", "zh-Hans", "pt-PT", "pt", "es-419", "in", "iw", "he",
            "ar-EG", "xx", "", "de_AT", "uk-UA", "nb-NO"]

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="installer-flow-"))
        exe = _build(cls.work)
        trees = {}
        for name, package in (("advanced", "codex_auto_resume_advanced"), ("other_case", "Codex_Auto_Resume_Advanced"),
                              ("no_init", None), ("standard", None)):
            src = cls.work / "trees" / name / "src"
            src.mkdir(parents=True)
            if package:
                (src / package).mkdir()
                (src / package / "__init__.py").write_text("", encoding="utf-8")
            if name == "no_init":
                (src / "codex_auto_resume_advanced").mkdir()
            trees[name] = str(src)
        homes = {"none": str(cls.work / "homes" / "none"), "standard": str(cls.work / "trees" / "standard")}
        (cls.work / "homes" / "none").mkdir(parents=True)
        # An installation's app\src: the advanced tree, moved under an app folder.
        advanced_home = cls.work / "homes" / "advanced"
        shutil.copytree(cls.work / "trees" / "advanced", advanced_home / "app")
        homes["advanced"] = str(advanced_home)
        standard_home = cls.work / "homes" / "standard"
        shutil.copytree(cls.work / "trees" / "standard", standard_home / "app")
        homes["standard"] = str(standard_home)
        docs = cls.work / "docs"
        docs.mkdir()
        for name in ("CHANGELOG.md", "CHANGELOG.ko.md"):
            (docs / name).write_text("# Changelog\n", encoding="utf-8")
        # Scratch homes whose settings say how the Dashboard looks (never the real one).
        looks = {}
        for name, settings in (("light", {"theme": "light", "design": "classic"}), ("dark", {"theme": "dark"}),
                               ("still", {"design": "still"}), ("none", None)):
            look_home = cls.work / "looks" / name
            (look_home / "config").mkdir(parents=True)
            if settings is not None:
                (look_home / "config" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
            looks[name] = str(look_home)
        source = cls.work / "input.json"
        source.write_text(json.dumps({"lines": {"install": INSTALLING, "update": UPDATING, "uninstall": REMOVING},
                                      "tags": cls.TAGS, "trees": trees, "homes": homes, "sample": NOTES_SAMPLE,
                                      "looks": looks, "phases": _phase_cases()}),
                          encoding="utf-8")
        cls.result = _powershell(PROBE, cls.work, 600, CAR_EXE=str(exe), CAR_INPUT=str(source),
                                 CAR_CHANGELOG=str(ROOT / "docs" / "CHANGELOG.md"), CAR_DOCS=str(docs))
        cls.docs = docs
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_each_way_it_is_shown_has_its_pages(self):
        self.assertEqual(self.answer["pages"], {"install": ["welcome", "options", "progress", "finish"],
                                                "update": ["progress", "notes", "finish"],
                                                "uninstall": ["confirm", "progress", "finish"]})

    def test_each_answer_is_one_of_install_ps1s_own_switches_and_silent_is_always_passed(self):
        # ConvertTo-Json writes an array of one as its one value.
        switches = {name: value if isinstance(value, list) else [value] for name, value in self.answer["switches"].items()}
        self.assertEqual(switches["first"], ["-Silent"])
        self.assertEqual(switches["first_no_startup"], ["-SkipStartup", "-Silent"])
        self.assertEqual(switches["upgrade_no_startup"], ["-Silent"],
                         "an update keeps the sign-in choice (--keep-state): there is nothing to ask")
        self.assertEqual(switches["change_unasked"], ["-Silent"])
        self.assertEqual(switches["change_asked"], ["-AllowEditionChange", "-Silent"])
        self.assertEqual(switches["remove"], ["-Uninstall", "-Silent"])
        self.assertEqual(switches["remove_purge"], ["-Uninstall", "-Purge", "-Silent"])
        self.assertEqual(switches["update"], ["-Silent"])
        self.assertEqual(switches["given"], ["-SkipStartup", "-Other", "-Silent"],
                         "the window's answers stand for its own switches; any other word is passed on")
        for word in ("-SkipStartup", "-AllowEditionChange", "-Uninstall", "-Purge"):
            self.assertIn("[switch]$" + word[1:], INSTALL_PS1)

    def test_an_edition_change_starts_only_once_it_is_asked_for(self):
        self.assertEqual(self.answer["can_start"], {"unasked": False, "asked": True, "upgrade": True})
        window = self.answer["window"]
        self.assertEqual(window["pages"], ["welcome", "options"])
        self.assertFalse(window["start_enabled_unasked"], "Install is not pressed for an edition change nobody asked for")

    def test_a_finished_run_says_its_code_and_offers_the_dashboard_only_after_a_success(self):
        self.assertEqual(self.answer["window"]["after"], ["finish", 14, False, True])
        self.assertEqual(self.answer["window"]["done"], ["finish", 0, True])

    def assert_phase_light(self, name, expected):
        """One phase's light (PHASES), as InstallerFlow.Light decides it: a page before the run asked with no code
        yet and with 0."""
        asked = [key for key in self.answer["light"] if key == name or key == name + "@0"]
        self.assertTrue(asked, "the phase %s was asked" % name)
        for key in asked:
            self.assertEqual(self.answer["light"][key], expected, key)

    def test_the_window_shows_the_phase_light_it_is_in(self):
        """The window's own light is the one InstallerFlow.Light gives: the acceptance's uninstall finished with it
        lit (cyan) on "Codex Auto Resume is removed." (the owner, 2026-10-20) - off now, as after a failure, a
        watcher not confirmed running and an installer that could not start; lit only where the watcher was."""
        self.assertEqual(self.answer["window_light"], {
            "confirm": "idle", "removed": "idle", "unconfirmed": "idle", "refused": "idle", "unstarted": "idle",
            "updated": "monitoring", "repaired": "monitoring"})
        shown = guiscan.member_body("InstallerWindow", "ShowPage")
        self.assertIn("light.State = InstallerFlow.Light(flow.Mode, name, code, unconfirmed, previousRunning);", shown)
        self.assertEqual(len(re.findall(r"\blight\.State\s*=", WINDOW)), 1, "the light is set in one place")

    def test_the_bar_follows_the_scripts_lines_forward_only(self):
        for mode, lines in (("install", INSTALLING), ("update", UPDATING), ("uninstall", REMOVING)):
            with self.subTest(mode):
                seen = self.answer["bar"][mode]
                self.assertEqual(len(seen), len(lines))
                places = [place for _, place, _ in seen]
                self.assertEqual(places, sorted(places), "never back")
                self.assertGreater(places[-1], 0.9)
                self.assertLess(places[-1], 1.0, "only the exit code says it is done")
        install = {line.strip(): (moved, step) for line, (moved, _, step) in zip(INSTALLING, self.answer["bar"]["install"])}
        self.assertEqual(install["Registering the Codex plugin"], (True, "plugin"))
        self.assertEqual(install["Setting up the watcher"], (True, "setup"))
        self.assertFalse(install["(the setup step's words, in any language)"][0], "the localized lines move nothing")
        # The acceptance's step stayed on the watcher while the Dashboard closed and the files were copied: each
        # has its own step now.
        self.assertEqual(install["Stopping the running watcher so the new version takes over"], (True, "watcher"))
        self.assertEqual(install["Closing the Dashboard so it opens again on the new version"], (True, "dashboard"))
        self.assertEqual(install["Copying the program files into place"], (True, "files"))
        update = self.answer["bar"]["update"]
        self.assertFalse(update[1][0], "the bootstrap's own edition line, before it downloads, is no step")
        self.assertEqual(update[3][2], "download")
        steps = {line.strip(): step for line, (_, _, step) in zip(UPDATING, update)}
        self.assertEqual(steps["Closing the Dashboard so it opens again on the new version"], "dashboard")
        self.assertEqual(steps["Copying the program files into place"], "files")
        self.assertEqual(self.answer["bar"]["uninstall"][-1][2], "finishing")
        self.assertEqual(self.answer["bar"]["uninstall"][1][2], "dashboard", "the uninstall closes the Dashboard first")
        self.assertEqual(self.answer["unpacked"], [0.0, 0.125, 0.25, 0.0])

    def test_the_languages_are_l10ns(self):
        self.assertEqual(self.answer["all"], list(l10n.LOCALES))
        self.assertEqual(sorted(self.answer["held"]), sorted(l10n.HELD))
        self.assertEqual(self.answer["offered"], list(l10n.OFFERED))
        self.assertEqual(self.answer["endonyms"], dict(l10n.ENDONYMS), "the picker names each language in itself")
        for tag in self.TAGS:
            with self.subTest(tag):
                self.assertEqual(self.answer["normalized"][tag], l10n.normalize(tag))
        self.assertEqual(self.answer["from_system"], ["de", "en"], "only the most preferred language counts")
        # Arabic, held until v0.6.20 (English then), is offered once the window is mirrored for it.
        self.assertEqual(self.answer["resolved"], ["ja", "de", "ar", "de"])

    def test_the_edition_is_install_ps1s_rule(self):
        self.assertEqual(self.answer["edition_of"], {"advanced": "advanced", "other_case": "standard",
                                                     "no_init": "standard", "standard": "standard"})
        self.assertEqual(self.answer["installed_at"], {"none": None, "advanced": "advanced", "standard": "standard"})
        self.assertEqual(self.answer["entries"], ["advanced", "standard"])
        self.assertIn("$_.Name -ceq 'codex_auto_resume_advanced'", INSTALL_PS1)
        self.assertIn("$upgrade = Test-Path -LiteralPath $AppDir", INSTALL_PS1)

    def test_the_home_and_the_version_are_install_ps1s(self):
        self.assertEqual(self.answer["home"], [r"C:\Users\ExampleUser\.codex-auto-resume", r"D:\Elsewhere"])
        self.assertIn("$InstallHome = Join-Path $env:USERPROFILE '.codex-auto-resume'", INSTALL_PS1)
        self.assertEqual(self.answer["version"], ["1.2.3", ""])

    def test_an_update_shows_what_is_new_and_opens_the_dashboard_by_itself(self):
        """v0.6.16, the owner: an update shows itself - from what to what and what is new, before it installs, and
        "Updated to" after - and the Dashboard it was started from comes back on the new version by itself. Later
        closes the window with nothing installed and nothing opened."""
        self.assertEqual(self.answer["updated"], ["finish", 0, True])
        self.assertEqual(self.answer["updated_switches"], 0, "nothing to tick: the Dashboard comes back by itself")
        self.assertEqual(self.answer["reopened"], [False, 0],
                         "the installer opened again the Dashboard that was open: none is offered beside it")
        self.assertEqual(self.answer["later"], [-3, False, True])

    def test_what_is_new_is_the_versions_own_section_of_the_changelog(self):
        notes = self.answer["notes"]
        # The section's own heading, as the changelog read here spells it: English on dev and main, Korean on the
        # generated ko branch, whose docs/CHANGELOG.md is the Korean one.
        heading = next(line[3:] for line in (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
                       if line.startswith("## v0.6.16-beta.3 "))
        self.assertTrue(notes["0.6.16-beta.3"].startswith(heading), notes["0.6.16-beta.3"][:80])
        self.assertNotIn("## v0.6.16-beta.2", notes["0.6.16-beta.3"], "it ends where the next version begins")
        self.assertTrue(notes["0.6.16-beta"].startswith("v0.6.16-beta \u2014 "), "not v0.6.16-beta.3's, whose name begins alike")
        self.assertIsNone(notes["9.9.9"])
        brief = self.answer["brief"].splitlines()
        self.assertEqual(len(brief), 3)
        self.assertFalse(any("](" in line or "**" in line for line in brief), brief)
        self.assertEqual(self.answer["file"], [str(self.docs / "CHANGELOG.ko.md"), str(self.docs / "CHANGELOG.md"),
                                               str(self.docs / "CHANGELOG.md")])

    def test_the_notes_page_shows_plain_text_not_markdown(self):
        """The acceptance's notes page showed the changelog's Markdown as written - [text](link), **, * - and ran the
        words of wrapped lines together ("*Check for updates*offers", "outin four"): a text box breaks a line only
        at CR LF. It is plain text now: a link as its text, no marks, headings as lines, a paragraph's or an item's
        wrapped lines joined with a space, each item a line of its own; code kept as written."""
        readable = self.answer["readable"]
        self.assertEqual(readable["sample"], NOTES_READABLE)
        self.assertEqual(readable["box"], NOTES_READABLE, "the Notes page shows it so")
        real = readable["real"]
        for mark in ("](", "**", "`", "## ", "\n- "):
            self.assertNotIn(mark, real)
        self.assertNotIn("*Check", real)
        self.assertEqual(real.count("\n"), real.count("\r\n"), "every line ends in CR LF")
        # The words of one English sentence the old reading ran together; the generated ko branch's changelog is the
        # Korean one, which says it in its own words.
        if not languages.generated_ko_branch():
            self.assertIn("Check for updates offers it", real.replace("\r\n", "\n"))

    def test_the_setup_window_opens_in_the_installations_own_look(self):
        """The acceptance's setup window was dark - Windows' app mode - while the Dashboard and the uninstall window
        of the installation it updated were light, as that installation's settings say. It opens in the theme,
        design and motion the installation stores, as those two do, and in the Dashboard's defaults where nothing is
        stored; the stored preference still goes through Theme.Current, so High Contrast wins as it does there."""
        self.assertEqual(self.answer["look"], {"light": ["light", "classic", ""], "dark": ["dark", "soft", ""],
                                               "still": ["system", "soft", "reduce"], "none": ["system", "soft", ""]})
        run = SETUP_WINDOW[SETUP_WINDOW.index("internal static int Run("):SETUP_WINDOW.index("internal static InstallerFlow FlowFor(")]
        self.assertIn("string[] look = LookAt(home);", run)
        self.assertIn("Palette.Adopt(Theme.Current(look[0]));", run)
        self.assertNotIn("Theme.Current(Theme.System)", run)
        self.assertLess(run.index("Palette.Adopt("), run.index("new InstallerWindow("))

    def test_the_finish_page_and_the_log_say_the_exit_code(self):
        """The changelog promises "whether it finished, with the exit code and the log", and the acceptance's
        Finish page said "installed" with no code, nor did the log. A success says its code on a line of its own (a
        failure's headline already says it), and the log ends with the code - but never one of the window's own,
        such as an installer that could not be started or an update put off."""
        self.assertEqual(self.answer["exit_code"], [True, True, True, False, False])

    def test_the_log_wraps_and_has_only_the_wells_own_scroll_bar(self):
        """The log box had Windows' own horizontal scroll bar, white on the dark setup window (the owner: "not our
        design"). It wraps its lines, and the one bar it has is the well's own (SoftTextArea draws it; Windows'
        vertical bar is kept outside the well's clip, where it is never seen)."""
        self.assertEqual(self.answer["log_box"], [True, "Vertical"])
        self.assertNotIn("ScrollBars.Both", WINDOW)
        self.assertNotIn("ScrollBars.Horizontal", WINDOW)

    def test_the_notes_pages_wait_is_not_the_installers_time(self):
        """Staying on the Notes page past the update's limit (20 minutes) reported "still running" with nothing
        installed, and left the bootstrap parked on its input until the window closed. The limit counts only the
        installer's time: none passes while the question is shown, and the wait is taken off once it is answered."""
        self.assertEqual(self.answer["clock"], [False, True, False, False, False, True])
        start = guiscan.member_body("SettingsForm", "StartBootstrap")
        self.assertNotIn("process.WaitForExit(milliseconds)", start)
        self.assertIn("var clock = new InstallerClock(milliseconds);", start)
        self.assertIn("if (clock.Over(time.ElapsedMilliseconds)) return \"running\";", start)
        asking = start[start.index("clock.Pause(time.ElapsedMilliseconds);"):]
        self.assertLess(asking.index("asked(notes)"), asking.index("clock.Resume(time.ElapsedMilliseconds);"),
                        "the clock waits as long as the question does")

    def test_a_setup_program_given_uninstall_shows_the_uninstall(self):
        """`Setup.exe -Uninstall` without -Silent dropped the switch (it is one the window answers) and showed the
        installation. It shows the uninstall, which passes -Uninstall on, with -Purge as its first answer."""
        self.assertEqual(self.answer["setup"], {"plain": ["install", "welcome", "-Silent"],
                                                "uninstall": ["uninstall", "confirm", "-Uninstall -Silent"],
                                                "purge": ["uninstall", "confirm", "-Uninstall -Purge -Silent"],
                                                "skip": ["install", "welcome", "-Silent"]})

    def test_over_its_own_version_it_offers_repair_and_remove(self):
        """The owner, 2026-10-17: a setup program run where its own version is installed already offers Repair and
        Remove on its first page, as an ordinary program's installer does. Repair installs it again in place, as
        install.ps1 runs over the same version; Remove goes on to the uninstall with its question about the settings.
        A newer version updates as before, the other edition is asked about as before, an explicit -Uninstall is the
        uninstall, and a version that cannot be read is no reason to offer either."""
        maintain = self.answer["maintain"]
        pages = "maintain confirm progress finish"
        self.assertEqual(maintain["repair"], ["install", pages, "-Silent", True])
        self.assertEqual(maintain["remove"], ["uninstall", pages, "-Uninstall -Silent", False])
        self.assertEqual(maintain["repair_again"], ["install", pages, "-Silent", True])
        ordinary = ["install", "welcome options progress finish", "-Silent", False]
        self.assertEqual(maintain["older"], ordinary)
        self.assertEqual(maintain["other_edition"], ordinary)
        self.assertEqual(maintain["unreadable"], ordinary)
        self.assertEqual(maintain["asked_uninstall"], ["uninstall", "confirm progress finish", "-Uninstall -Silent", False])
        self.assertEqual(maintain["window"], ["maintain", 2, "Repair", [True, False]], "Repair is the default")
        self.assertEqual(maintain["window_remove"], ["uninstall", "Next"])
        self.assertEqual(maintain["window_repair"], ["install", "Repair"])
        self.assertEqual(maintain["finished"], "Codex Auto Resume is repaired.")

    def test_each_code_says_what_it_means(self):
        outcome = self.answer["outcome"]
        self.assertEqual(outcome["0"], ["Codex Auto Resume is installed.", None])
        self.assertEqual(outcome["1"][0], "It did not finish (exit code 1).")
        self.assertIn("other edition", outcome["14"][1])
        self.assertIn("setup program stopped", outcome["43"][1])
        self.assertIn("still working", outcome["-2"][0])
        self.assertEqual(self.answer["removed"], "Codex Auto Resume is removed.")


def _phase_light_test(name, expected):
    def test(self):
        self.assert_phase_light(name, expected)
    test.__doc__ = "The status light of the phase %s is %s (InstallerFlow.Light)." % (name, expected)
    return test


for _phase in PHASES:
    setattr(FlowTests, "test_the_light_of_phase_" + _phase[0], _phase_light_test(_phase[0], _phase[6]))


class ScriptTests(unittest.TestCase):
    def milestones(self, table: str) -> list:
        body = FLOW[FLOW.index("Milestone[] %s =" % table):]
        body = body[:body.index("};")]
        return re.findall(r'new Milestone\("([^"]+)", ([0-9.]+), "([a-z_]+)"\)', body)

    def test_every_line_the_bar_reads_is_one_the_scripts_print(self):
        for table, scripts in (("Installing", (INSTALL_PS1,)), ("Updating", (BOOTSTRAP, INSTALL_PS1)),
                               ("Removing", (INSTALL_PS1,))):
            for starts, _, _ in self.milestones(table):
                with self.subTest(table=table, line=starts):
                    said = starts[len("[ok] "):] if starts.startswith("[ok] ") else starts
                    # PowerShell doubles an apostrophe inside a single-quoted string.
                    self.assertTrue(any(said.rstrip() in script.replace("''", "'") for script in scripts), said)

    def test_each_table_moves_forward(self):
        for table in ("Installing", "Updating", "Removing"):
            with self.subTest(table):
                places = [float(at) for _, at, _ in self.milestones(table)]
                self.assertEqual(places, sorted(places))
                self.assertLess(places[-1], 1.0)


class CatalogTests(unittest.TestCase):
    def said(self) -> dict:
        text = FLOW + WINDOW
        keys = dict(re.findall(r'Say\("([a-z_.]+)",\s*"((?:[^"\\]|\\.)*)"', text))
        # C#'s \uXXXX escapes, as the compiled words have them.
        keys = {key: re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), value) for key, value in keys.items()}
        steps = re.findall(r'"([^"]+)"', re.search(r"Steps =\s*\{(.*?)\};", FLOW, re.S).group(1))
        keys.update({"installer.step." + steps[i]: steps[i + 1] for i in range(0, len(steps), 2)})
        return keys

    def test_every_word_it_says_is_in_every_catalog_with_its_english_beside_it(self):
        english = l10n.catalog("en")
        said = self.said()
        self.assertGreater(len(said), 50)
        for key, fallback in said.items():
            with self.subTest(key):
                self.assertEqual(english.get(key), fallback.replace('\\"', '"'))
        for locale in l10n.LOCALES:
            # The file itself: l10n.catalog fills a missing key in with English.
            own = json.loads((l10n.DIRECTORY / ("%s.json" % locale)).read_text(encoding="utf-8"))
            with self.subTest(locale=locale):
                self.assertEqual(sorted(key for key in said if key not in own), [])

    def test_no_sentence_gives_a_word_both_of_its_endings(self):
        """The Repair page read "버전 0.6.16이(가) 이미 설치되어 있습니다" on the owner's PC: a Korean particle written
        both ways, because what comes before it is a value. A sentence is worded so its particle follows a word of
        its own ("0.6.16 버전이"), in every catalog - the advanced edition's too - and in the form a message takes."""
        both = re.compile(r"이\(가\)|가\(이\)|을\(를\)|를\(을\)|은\(는\)|는\(은\)|\(으\)로|와\(과\)|과\(와\)|\(이\)라|\(이\)나")
        folders = [l10n.DIRECTORY]
        advanced = ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales"
        if advanced.is_dir():
            folders.append(advanced)
        found = []
        for folder in folders:
            for catalog in sorted(folder.glob("*.json")):
                for key, text in json.loads(catalog.read_text(encoding="utf-8")).items():
                    if isinstance(text, str) and both.search(text):
                        found.append("%s/%s %s: %s" % (folder.parent.name, catalog.name, key, text[:80]))
        self.assertEqual(found, [])


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class LayoutAuditTests(unittest.TestCase):
    """InstallerAudit: every page of every way the window is shown - a first installation, an update, an edition
    change each way, the Dashboard's update and the uninstall, and a finish for each kind of ending - in every
    language at five scalings and three text sizes, built and never shown."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="installer-audit-"))
        exe = _build(cls.work)
        cases = [{"name": locale, "language": locale,
                  "catalog": str(l10n.DIRECTORY / ("%s.json" % locale))} for locale in l10n.LOCALES]
        # A word no switch's line can hold, and a button wider than the window. (A long word in a paragraph is
        # broken where the window's text is broken, and the window grows for it: that is not cut off.)
        canary = dict(l10n.catalog("en"), **{"field.startup": "S" * 300, "installer.next": "N" * 120})
        (cls.work / "canary.json").write_text(json.dumps(canary), encoding="utf-8")
        cases.append({"name": "canary", "language": "en", "catalog": str(cls.work / "canary.json")})
        result = cls.work / "result.json"
        cls.result = _powershell(AUDIT, cls.work, 300 * len(cases), CAR_EXE=str(exe), CAR_CASES=json.dumps(cases),
                                 CAR_PAIRS=json.dumps(PAIRS),
                                 CAR_RESULT=str(result))
        cls.answer = (json.loads(result.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and result.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the audit did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_nothing_is_cut_off_in_any_language_at_any_scaling_or_text_size(self):
        for locale in l10n.LOCALES:
            for scale, text in PAIRS:
                report = self.answer[locale]["%.2f/%.2f" % (scale, text)]
                with self.subTest(locale=locale, scale=scale, text=text):
                    self.assertEqual(report, "", "\n" + "\n".join(report.splitlines()[:30]))

    def test_the_audit_finds_what_does_not_fit(self):
        report = self.answer["canary"]["1.00/1.00"]
        self.assertIn("SoftCheck'SSSS", report, "a 300-letter word went unreported, so a quiet report proves nothing")
        self.assertIn("button 'NNNN", report, "a button wider than the window went unreported")
        self.assertIn("/pages/options :: SoftCheck", report, "the options page was laid out and looked at")


PRESENT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$present = $assembly.GetType('CodexAutoResume.SettingsRemove', $true).GetMethod('Present', [Reflection.BindingFlags]'Static,NonPublic')
$form = New-Object System.Windows.Forms.Form
$form.Text = 'installer-window-present-probe'
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point(-2000, -2000)
$form.Size = New-Object System.Drawing.Size(200, 120)
# As Windows handed the uninstall window out on the acceptance's PC: iconic from the start.
$form.WindowState = 'Minimized'
$null = $present.Invoke($null, [object[]]@($form.PSObject.BaseObject))
$script:shown = $false
$form.add_Shown({ $script:shown = $true })
$form.Show()
$deadline = (Get-Date).AddSeconds(10)
while (-not $script:shown -and (Get-Date) -lt $deadline) { [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 20 }
[System.Windows.Forms.Application]::DoEvents()
$state = [string]$form.WindowState
$form.Close(); $form.Dispose()
@{ shown = $script:shown; state = $state } | ConvertTo-Json -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class UninstallWindowTests(unittest.TestCase):
    """The uninstall window came up iconic - only on the taskbar - whether it was started from Settings > Apps or
    run directly (v0.6.16 acceptance): the copy that shows it is started by the program in the installation, which
    ends first. SettingsRemove.Present opens it normal and in front; here a window handed out minimized, as that one
    was, is shown through it, off screen, and comes up normal."""

    def test_the_uninstall_window_opens_normal_and_in_front(self):
        removing = guiscan.member_body("SettingsRemove", "Removing")
        self.assertLess(removing.index("Present(window);"), removing.index("Application.Run(window);"))
        refuse = guiscan.member_body("SettingsRemove", "Refuse")
        self.assertLess(refuse.index("Present(window);"), refuse.index("Application.Run(window);"))
        self.assertIn("AllowSetForegroundWindow(copied.Id);", guiscan.member_body("SettingsRemove", "CopyAndStart"))
        work = Path(tempfile.mkdtemp(prefix="installer-present-"))
        try:
            exe = work / "CodexAutoResumeSettings.exe"
            subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                            "/reference:System.dll", "/reference:System.Drawing.dll",
                            "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                           check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
            done = _powershell(PRESENT, work, 120, CAR_EXE=str(exe))
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1]), {"shown": True, "state": "Normal"})
        finally:
            shutil.rmtree(work, ignore_errors=True)


class SourceTests(unittest.TestCase):
    def test_it_is_built_into_the_window_and_the_setup_programs_from_one_list(self):
        # v0.6.17: gui/HostApp.cs, whether either program runs inside another app's private view of Windows.
        installer = ["gui/InstallerFlow.cs", "gui/InstallerWindow.cs", "gui/HostApp.cs"]
        self.assertEqual(list(guiscan.group("installer")), installer)
        self.assertEqual(make_setup.window_sources()[:3], installer)
        self.assertEqual(make_setup.window_sources()[3:], list(guiscan.group("controls")) +
                         list(guiscan.group("generated")) + ["gui/WindowJson.cs"])
        self.assertIn("gui/SettingsRemove.cs", guiscan.group("settings"))

    def test_no_console_window_appears_in_the_windows_mode(self):
        """Every console program the window starts is started with no window: the setup program's cmd.exe
        (Setup.cs, Install), the uninstall's and the tidying PowerShell (SettingsRemove), and the Dashboard's
        bootstrap, as before. The one program it starts with a window is the Dashboard, which has no console."""
        setup = (ROOT / "build" / "setup" / "Setup.cs").read_text(encoding="utf-8")
        install = setup[setup.index("static int Install("):setup.index("static Thread Pass(")]
        self.assertIn("start.CreateNoWindow = true;", install)
        self.assertEqual(REMOVE.count("new ProcessStartInfo("), 3)
        self.assertEqual(REMOVE.count("start.CreateNoWindow = true;"), 2, "the uninstall and the tidying")
        self.assertEqual(REMOVE.count("UseShellExecute = false;"), 3)
        self.assertNotIn("UseShellExecute = true", SETUP_WINDOW + REMOVE)
        self.assertIn('"/target:winexe"', (ROOT / "build" / "make_setup.py").read_text(encoding="utf-8"))

    def test_the_window_is_never_closed_while_the_installer_runs(self):
        closing = WINDOW[WINDOW.index("protected override void OnFormClosing("):]
        closing = closing[:closing.index("\n        }\n")]
        # v0.6.18 acceptance (B2): any close but Windows ending the session - a raw WM_CLOSE arrives as
        # TaskManagerClosing (tests/test_gui_pick_close.py).
        self.assertIn("if (running && e.CloseReason != CloseReason.WindowsShutDown)", closing)
        self.assertIn("e.Cancel = true;", closing)

    def test_it_asks_for_no_elevation_and_writes_nothing_under_hklm(self):
        manifest = (ROOT / "build" / "setup" / "setup.manifest").read_text(encoding="utf-8")
        self.assertIn('level="asInvoker"', manifest)
        for text in (FLOW, WINDOW, SETUP_WINDOW, REMOVE):
            self.assertNotIn("LocalMachine", text)
            self.assertNotIn("HKLM", text)
            self.assertNotIn("Registry.", text)

    def test_the_uninstall_runs_only_this_installations_kept_script_and_tidies_only_its_own_folder(self):
        self.assertIn('Path.Combine(Path.Combine(home, "uninstall"), "install.ps1")', REMOVE)
        self.assertIn("if (KeptScript(home, named) == null) return Refuse(named, home);", REMOVE)
        self.assertIn("'CodexAutoResume-Uninstall-*'", REMOVE)
        self.assertIn('internal const string FolderPrefix = "CodexAutoResume-Uninstall-";', REMOVE)
        tidy = REMOVE[REMOVE.index("internal const string TidyScript ="):REMOVE.index("private static void Tidy(")]
        self.assertNotIn("+ folder", tidy, "the folder is given in the environment, never in the script")
        main = guiscan.member_body("Program", "Main")
        self.assertLess(main.index("SettingsRemove.IsAsked(argv)"), main.index("new Bridge(root)"))

    def test_the_dashboards_update_asks_after_the_verified_download_and_before_the_install(self):
        """The bootstrap's -AskFirst stops between its checks of the download and the installer: the changelog's
        folder, the question, and only `install` on its input goes on (`update: later` and 16 otherwise). The
        Dashboard writes the person's answer there, and reads `later` as an update put off, not one that failed."""
        verified = BOOTSTRAP.index("Ok ('Archive contents verified as Codex Auto Resume v' + $target)")
        asked = BOOTSTRAP.index("Write-Host ('ask: install v' + $target)")
        self.assertLess(verified, asked)
        self.assertLess(asked, BOOTSTRAP.index("$installer = Join-Path $unpacked 'install\\install.ps1'"))
        self.assertIn("if ($answer -cne 'install') {", BOOTSTRAP)
        self.assertIn("$ExitLater = 16", BOOTSTRAP)
        update = guiscan.member_body("SettingsForm", "InstallUpdate")
        self.assertIn('flag + " -AskFirst"', update)
        self.assertIn("window.Ask(InstallerNotes.Section(", update)
        start = guiscan.member_body("SettingsForm", "StartBootstrap")
        self.assertIn('process.StandardInput.WriteLine(go ? "install" : "later");', start)
        self.assertIn("if (Asked != null) info.RedirectStandardInput = true;", start)
        self.assertIn('else if (code == UpdateLater && said == "later") answer = "later";',
                      guiscan.member_body("SettingsForm", "RunBootstrap"))

    def test_the_dashboards_update_runs_in_the_window_through_the_one_start_of_the_bootstrap(self):
        update = guiscan.member_body("SettingsForm", "InstallUpdate")
        self.assertIn("new InstallerWindow(flow,", update)
        self.assertIn('RunBootstrap(root, script, flag + " -AskFirst", UpdateMilliseconds,', update)
        self.assertIn("window.ShowDialog(this);", update)
        start = guiscan.member_body("SettingsForm", "StartBootstrap")
        self.assertIn("Action<string> heard = Heard;", start)


if __name__ == "__main__":
    unittest.main()
