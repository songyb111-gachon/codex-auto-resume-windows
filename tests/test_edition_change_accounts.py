r"""A change to the standard edition says what becomes of the saved Codex sign-ins, and can delete them (v0.6.22).

The advanced edition keeps sealed copies of Codex's sign-in file in the installation's `accounts` folder. The standard
edition shows no card for them, so after a change to it only an uninstall that deletes the settings could have taken
them. The setup window's edition-change step therefore says they stay, sealed for this Windows user and unused, and
offers a box, off, to delete them with the change; install.ps1 takes them (-DeleteSavedAccounts) the way the purge does,
after the change succeeded.

* ScriptTests - install.ps1's own Remove-SavedAccounts, lifted out and run against a scratch home: the folder goes only
  when asked and only on a change to the standard edition, never through a link, a held file is kept and said.
  Nothing here touches a real installation, the registry or a running process.
* FlowTests / WindowTests - the box's switch and the page that shows it, with the setup program built as the window
  tests build it and the window never shown.
* WordsTests - the two sentences in all 18 catalogs, the switch in every list that names the installer's switches, the
  documents.
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

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import languages  # noqa: E402
from test_installer_window import _build, _powershell, CSC  # noqa: E402

WINDOWS = os.name == "nt"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
FLOW = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
SETUP = (ROOT / "build" / "setup" / "SetupWindow.cs").read_text(encoding="utf-8")
LOCALES = ROOT / "src" / "codex_auto_resume" / "locales"
ENGLISH = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
LINE = "installer.options.saved_accounts"
BOX = "installer.options.delete_saved_accounts"
CHANGE = "installer.options.edition_confirm"

# install.ps1's functions, as its own text defines them, run with the installation root a scratch folder.
HARNESS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_INSTALLER, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'install.ps1 does not parse' }
foreach ($node in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    Invoke-Expression $node.Extent.Text
}
$script:Failed = $false
$script:Said = New-Object System.Collections.ArrayList
function Warn { param([string]$m) $null = $script:Said.Add('warn: ' + $m) }
function Ok { param([string]$m) $null = $script:Said.Add('ok: ' + $m) }
function Step { param([string]$m) $null = $script:Said.Add('step: ' + $m) }
$InstallHome = $env:CAR_HOME
$OwnedHome = Resolve-Canonical $InstallHome
$asked = ($env:CAR_ASKED -eq '1'); $change = ($env:CAR_CHANGE -eq '1')
$answer = Remove-SavedAccounts -Asked $asked -EditionChange $change -Edition $env:CAR_EDITION
@{ answer = [bool]@($answer)[-1]; said = @($script:Said) } | ConvertTo-Json -Compress
"""


def sealed_accounts(home: Path) -> Path:
    accounts = home / "accounts"
    accounts.mkdir(parents=True)
    (accounts / ".owned-by-codex-auto-resume").write_text("x", encoding="utf-8")
    (accounts / "one.dat").write_bytes(b"sealed one")
    (accounts / "scratch-0123456789ab").mkdir()
    (accounts / "scratch-0123456789ab" / "auth.json").write_bytes(b"{}")
    return accounts


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class ScriptTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / "home"
        (self.home / "config").mkdir(parents=True)
        (self.home / "config" / "settings.json").write_text('{"enabled": false}', encoding="utf-8")
        (self.home / "logs").mkdir()
        (self.home / "logs" / "watcher.log").write_text("a line", encoding="utf-8")

    def run_it(self, asked, change, edition):
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", HARNESS], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", timeout=300,
                              env=dict(os.environ, CAR_INSTALLER=str(ROOT / "build" / "install" / "install.ps1"),
                                       CAR_HOME=str(self.home), CAR_ASKED="1" if asked else "0",
                                       CAR_CHANGE="1" if change else "0", CAR_EDITION=edition))
        self.assertEqual(done.returncode, 0, done.stdout[-1500:])
        return json.loads(done.stdout.strip().splitlines()[-1])

    def assert_others_kept(self):
        self.assertEqual((self.home / "config" / "settings.json").read_text(encoding="utf-8"), '{"enabled": false}')
        self.assertEqual((self.home / "logs" / "watcher.log").read_text(encoding="utf-8"), "a line")

    def test_asked_on_a_change_to_the_standard_edition_the_folder_goes_and_nothing_else(self):
        accounts = sealed_accounts(self.home)
        answer = self.run_it(True, True, "standard")
        self.assertIs(answer["answer"], True)
        self.assertFalse(accounts.exists(), "the saved accounts are still there")
        self.assert_others_kept()
        self.assertTrue(any(line.startswith("ok: Deleted the Codex accounts") for line in answer["said"]), answer)

    def test_not_asked_they_stay_whatever_the_change(self):
        accounts = sealed_accounts(self.home)
        for change, edition in ((True, "standard"), (True, "advanced"), (False, "standard"), (False, "advanced")):
            with self.subTest(change=change, edition=edition):
                answer = self.run_it(False, change, edition)
                self.assertEqual(answer["said"], [])
                self.assertTrue((accounts / "one.dat").is_file())
                self.assertTrue((accounts / "scratch-0123456789ab" / "auth.json").is_file())

    def test_asked_where_it_is_no_change_to_the_standard_edition_nothing_is_deleted_and_it_says_so(self):
        """A standard-only installation, an update, a repair and a change to the advanced edition: the switch means
        nothing there."""
        accounts = sealed_accounts(self.home)
        for change, edition in ((False, "standard"), (False, "advanced"), (True, "advanced")):
            with self.subTest(change=change, edition=edition):
                answer = self.run_it(True, change, edition)
                self.assertIs(answer["answer"], True)
                self.assertTrue((accounts / "one.dat").is_file())
                self.assertTrue(any("only goes with a change to the standard edition" in line for line in answer["said"]))
        self.assert_others_kept()

    def test_a_standard_installation_with_no_folder_is_untouched(self):
        before = sorted(path.relative_to(self.home).as_posix() for path in self.home.rglob("*"))
        for asked in (True, False):
            answer = self.run_it(asked, True, "standard")
            self.assertIs(answer["answer"], True)
            self.assertEqual(sorted(path.relative_to(self.home).as_posix() for path in self.home.rglob("*")), before)

    def test_a_junction_at_the_folder_is_never_followed(self):
        import _winapi
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "precious.txt").write_text("not ours", encoding="utf-8")
        _winapi.CreateJunction(str(outside), str(self.home / "accounts"))
        answer = self.run_it(True, True, "standard")
        self.assertIs(answer["answer"], True)
        self.assertEqual((outside / "precious.txt").read_text(encoding="utf-8"), "not ours")
        self.assertTrue((self.home / "accounts").exists(), "a link is left to the person, as the purge leaves it")

    def test_a_held_file_is_kept_and_said(self):
        accounts = sealed_accounts(self.home)
        with open(accounts / "one.dat", "rb"):                    # an open handle without delete sharing
            answer = self.run_it(True, True, "standard")
        self.assertIs(answer["answer"], False)
        self.assertTrue((accounts / "one.dat").is_file())
        self.assertTrue(any(line.startswith("warn: Some of the saved Codex accounts could not be deleted")
                            for line in answer["said"]), answer)

    def test_it_never_deletes_outside_the_verified_installation(self):
        """Remove-OwnedItem is the one door: the folder is joined to the verified root, not read from anywhere."""
        block = INSTALL_PS1[INSTALL_PS1.index("function Remove-SavedAccounts"):]
        block = block[:block.index("\n}\n")]
        self.assertIn("Join-Path $OwnedHome 'accounts'", block)
        self.assertIn("Remove-OwnedItem $dir", block)
        self.assertNotIn("Remove-Item", block)
        self.assertIn("$item.LinkType", block)

    def test_the_switch_is_install_ps1s_and_reaches_a_run_outside_another_app(self):
        self.assertRegex(INSTALL_PS1, r"param\(\s[\s\S]*\[switch\]\$DeleteSavedAccounts\b")
        gate = INSTALL_PS1.index("$outsideCode = Resolve-OutsideRun")
        self.assertIn("'DeleteSavedAccounts'", INSTALL_PS1[INSTALL_PS1.index("$outsideSwitches = @("):gate])

    def test_it_runs_once_after_setup_succeeded_never_in_the_uninstall_or_before_the_change(self):
        call = "Remove-SavedAccounts -Asked ([bool]$DeleteSavedAccounts) -EditionChange $editionChange -Edition $edition"
        self.assertEqual(INSTALL_PS1.count(call), 1)
        at = INSTALL_PS1.index(call)
        self.assertGreater(at, INSTALL_PS1.index("Fail 'Setup did not complete."), "after setup succeeded")
        self.assertGreater(at, INSTALL_PS1.index("Ok ('Replacing the ' + $previousEdition"), "after the change")
        self.assertGreater(at, INSTALL_PS1.index("$code = Invoke-Setup"))
        self.assertLess(at, INSTALL_PS1.index("Step 'Checking the installation'"))
        uninstall = INSTALL_PS1[INSTALL_PS1.index("if ($Uninstall) {"):INSTALL_PS1.index("$upgrade = Test-Path -LiteralPath $AppDir")]
        self.assertNotIn("Remove-SavedAccounts", uninstall)

    def test_silent_with_the_change_and_no_new_switch_keeps_them(self):
        """The call is made with the switch's own value, so a run that was not given it asks for nothing."""
        self.assertIn("-Asked ([bool]$DeleteSavedAccounts)", INSTALL_PS1)
        self.assertEqual(INSTALL_PS1.count("$DeleteSavedAccounts"), 2, "named only in its parameter and at the one call")


FLOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
$FlowType = $assembly.GetType('CodexAutoResume.InstallerFlow', $true)
$SetupType = $assembly.GetType('CodexAutoResumeSetup.SetupWindow', $true)
function NewFlow($mode, $edition, $installed, $saved, $change, $delete) {
    $flow = $FlowType.GetConstructors($any)[0].Invoke([object[]]@([string]$mode, 'C:\Users\ExampleUser\.codex-auto-resume', $edition, $installed, '9.9.9'))
    $FlowType.GetField('SavedAccountsThere', $any).SetValue($flow, [bool]$saved)
    $FlowType.GetField('ChangeEdition', $any).SetValue($flow, [bool]$change)
    $FlowType.GetField('DeleteSavedAccounts', $any).SetValue($flow, [bool]$delete)
    $flow
}
function Switches($flow, $given) { (@($FlowType.GetMethod('Switches', $any).Invoke($flow, [object[]]@(,[string[]]@($given)))) -join ' ') }
function Offers($flow) { [bool]$FlowType.GetProperty('OffersAccountDeletion', $any).GetValue($flow, $null) }
$out = @{}
# mode, edition (this archive), installed, folder there, change ticked, box ticked
$cases = [ordered]@{
    advanced_to_standard_unticked = @('install', 'standard', 'advanced', $true, $true, $false)
    advanced_to_standard_ticked   = @('install', 'standard', 'advanced', $true, $true, $true)
    ticked_but_change_not_asked   = @('install', 'standard', 'advanced', $true, $false, $true)
    ticked_but_no_folder          = @('install', 'standard', 'advanced', $false, $true, $true)
    standard_to_advanced          = @('install', 'advanced', 'standard', $true, $true, $true)
    same_standard                 = @('install', 'standard', 'standard', $true, $true, $true)
    same_advanced                 = @('install', 'advanced', 'advanced', $true, $true, $true)
    first_installation            = @('install', 'standard', $null, $true, $true, $true)
    update                        = @('update', 'standard', 'advanced', $true, $true, $true)
    uninstall                     = @('uninstall', 'standard', 'advanced', $true, $true, $true)
}
foreach ($name in $cases.Keys) {
    $c = $cases[$name]
    $flow = NewFlow $c[0] $c[1] $c[2] $c[3] $c[4] $c[5]
    $out[$name] = @((Switches $flow @()), (Offers $flow))
}
# A switch the setup program was started with is the box's first answer, and is passed once, only where it applies.
$flow = $SetupType.GetMethod('FlowFor', $any).Invoke($null, [object[]]@([string[]]@('-AllowEditionChange', '-DeleteSavedAccounts'),
    'C:\Users\ExampleUser\.codex-auto-resume', 'standard', 'advanced', '9.9.9', '9.9.8'))
$out.preset_box = [bool]$FlowType.GetField('DeleteSavedAccounts', $any).GetValue($flow)
$out.preset_there = Switches $flow @('-AllowEditionChange', '-DeleteSavedAccounts')
$FlowType.GetField('SavedAccountsThere', $any).SetValue($flow, $true)
$out.preset_offered = Switches $flow @('-AllowEditionChange', '-DeleteSavedAccounts')
$flow = $SetupType.GetMethod('FlowFor', $any).Invoke($null, [object[]]@([string[]]@('-AllowEditionChange'),
    'C:\Users\ExampleUser\.codex-auto-resume', 'standard', 'advanced', '9.9.9', '9.9.8'))
$FlowType.GetField('SavedAccountsThere', $any).SetValue($flow, $true)
$out.silent_keeps = Switches $flow @('-AllowEditionChange')
$flow = $SetupType.GetMethod('FlowFor', $any).Invoke($null, [object[]]@([string[]]@('-DeleteSavedAccounts'),
    'C:\Users\ExampleUser\.codex-auto-resume', 'standard', 'standard', '9.9.9', '9.9.8'))
$FlowType.GetField('SavedAccountsThere', $any).SetValue($flow, $true)
$out.preset_no_change = Switches $flow @('-DeleteSavedAccounts')
# A real folder on disk, as the window reads it as it opens.
$at = $FlowType.GetMethod('SavedAccountsAt', $any)
$out.folder = @($at.Invoke($null, [object[]]@($env:CAR_WITH)), $at.Invoke($null, [object[]]@($env:CAR_WITHOUT)))
$out | ConvertTo-Json -Depth 4 -Compress
"""

WINDOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
function T($name) { $assembly.GetType('CodexAutoResume.' + $name, $true) }
$FlowType = T 'InstallerFlow'
$catalog = (T 'Json').GetMethod('Parse', $any).Invoke($null, [object[]]@([IO.File]::ReadAllText($env:CAR_CATALOG, [Text.Encoding]::UTF8)))
$words = (T 'InstallerWords').GetConstructors($any)[0].Invoke([object[]]@($catalog, 'en'))
function NewFlow($edition, $installed, $saved) {
    $flow = $FlowType.GetConstructors($any)[0].Invoke([object[]]@('install', 'C:\Users\ExampleUser\.codex-auto-resume', $edition, $installed, '9.9.9'))
    $FlowType.GetField('SavedAccountsThere', $any).SetValue($flow, [bool]$saved)
    $flow
}
function NewWindow($flow) { (T 'InstallerWindow').GetConstructors($any)[0].Invoke([object[]]@($flow, $words, $null, $null, $null, $null)) }
function CallOn($object, $name, $arguments) { $object.GetType().GetMethod($name, $any).Invoke($object, [object[]]$arguments) }
# What the options page shows, in order: its sentences, and its boxes as @(text, ticked, a box and not a switch).
function Page($flow) {
    $window = NewWindow $flow
    $null = CallOn $window 'ShowPage' @('options')
    $found = @()
    foreach ($row in @(CallOn $window 'ShownRows' @())) {
        $kind = $row.GetType().Name
        if ($kind -ceq 'WrapLabel') { $found += ,@('say', [string]$row.Text) }
        elseif ($kind -ceq 'SoftCheck') {
            $found += ,@('box', [string]$row.Text, [bool]$row.Checked, [bool]$row.GetType().GetProperty('Box', $any).GetValue($row, $null))
        }
    }
    ,$found
}
$out = @{}
$out.advanced_to_standard = Page (NewFlow 'standard' 'advanced' $true)
$out.advanced_to_standard_no_folder = Page (NewFlow 'standard' 'advanced' $false)
$out.standard_to_advanced = Page (NewFlow 'advanced' 'standard' $true)
$out.same_standard = Page (NewFlow 'standard' 'standard' $true)
$out.first = Page (NewFlow 'standard' $null $true)
$out | ConvertTo-Json -Depth 5 -Compress
"""


@unittest.skipUnless(WINDOWS and CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="edition-accounts-flow-"))
        exe = _build(cls.work)
        with_folder = cls.work / "with"
        sealed_accounts(with_folder)
        (cls.work / "without").mkdir()
        cls.result = _powershell(FLOW_PROBE, cls.work, 300, CAR_EXE=str(exe), CAR_WITH=str(with_folder),
                                 CAR_WITHOUT=str(cls.work / "without"))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_the_switch_is_passed_only_when_ticked_on_the_change_it_belongs_to(self):
        self.assertEqual(self.answer["advanced_to_standard_unticked"], ["-AllowEditionChange -Silent", True])
        self.assertEqual(self.answer["advanced_to_standard_ticked"],
                         ["-AllowEditionChange -DeleteSavedAccounts -Silent", True])

    def test_it_is_never_passed_where_it_means_nothing(self):
        for name in ("ticked_but_change_not_asked", "ticked_but_no_folder", "standard_to_advanced", "same_standard",
                     "same_advanced", "first_installation", "update", "uninstall"):
            with self.subTest(name):
                self.assertNotIn("DeleteSavedAccounts", self.answer[name][0])
        for name in ("standard_to_advanced", "same_standard", "same_advanced", "first_installation", "update"):
            self.assertIs(self.answer[name][1], False, name + ": nothing to offer there")
        self.assertEqual(self.answer["ticked_but_no_folder"][0], "-AllowEditionChange -Silent")

    def test_a_switch_the_setup_program_was_given_is_the_boxs_first_answer_and_kept_to_its_case(self):
        self.assertIs(self.answer["preset_box"], True)
        self.assertEqual(self.answer["preset_there"], "-AllowEditionChange -Silent", "no folder: not passed on")
        self.assertEqual(self.answer["preset_offered"], "-AllowEditionChange -DeleteSavedAccounts -Silent",
                         "passed once, not twice")
        self.assertEqual(self.answer["silent_keeps"], "-AllowEditionChange -Silent")
        self.assertEqual(self.answer["preset_no_change"], "-Silent", "an update or repair asks for nothing")

    def test_the_window_reads_the_folder_as_the_purge_does(self):
        self.assertEqual(self.answer["folder"], [True, False])


@unittest.skipUnless(WINDOWS and CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    """The window built and never shown, as its layout audit is."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="edition-accounts-window-"))
        exe = _build(cls.work)
        cls.result = _powershell(WINDOW_PROBE, cls.work, 300, CAR_EXE=str(exe), CAR_CATALOG=str(LOCALES / "en.json"))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_leaving_the_advanced_edition_says_what_becomes_of_them_and_offers_the_box_off(self):
        page = self.answer["advanced_to_standard"]
        says = [row[1] for row in page if row[0] == "say"]
        boxes = [row[1:] for row in page if row[0] == "box"]
        self.assertIn(ENGLISH[LINE], says)
        change, delete = [ENGLISH[CHANGE], False, True], [ENGLISH[BOX], False, True]
        self.assertIn(change, boxes, "the change itself, a box, off")
        self.assertIn(delete, boxes, "the new box: off, and a box and not a switch")
        self.assertLess(boxes.index(change), boxes.index(delete))

    def test_nothing_else_has_the_sentence_or_the_box(self):
        for name in ("advanced_to_standard_no_folder", "standard_to_advanced", "same_standard", "first"):
            with self.subTest(name):
                texts = [row[1] for row in self.answer[name]]
                self.assertNotIn(ENGLISH[LINE], texts)
                self.assertNotIn(ENGLISH[BOX], texts)

    def test_the_other_change_keeps_its_own_box(self):
        for name in ("advanced_to_standard_no_folder", "standard_to_advanced"):
            self.assertIn([ENGLISH[CHANGE], False, True], [row[1:] for row in self.answer[name] if row[0] == "box"])

    def test_the_page_is_the_one_that_asks_before_replacing_the_other_edition(self):
        window = (ROOT / "gui" / "InstallerWindow.cs").read_text(encoding="utf-8")
        at = window.index('"installer.options.saved_accounts"')
        self.assertIn("if (flow.OffersAccountDeletion)", window[at - 120:at])
        at = window.index('"installer.options.delete_saved_accounts"')
        self.assertIn("if (flow.OffersAccountDeletion)", window[at - 120:at])
        self.assertIn("flow.DeleteSavedAccounts = on;", window[at:at + 400])


class WordsTests(unittest.TestCase):
    def test_both_sentences_are_in_all_22_catalogs_with_the_right_placeholders(self):
        catalogs = sorted(LOCALES.glob("*.json"))
        self.assertEqual(len(catalogs), 22)
        for catalog in catalogs:
            words = json.loads(catalog.read_text(encoding="utf-8"))
            for key in (LINE, BOX):
                with self.subTest(catalog.name, key=key):
                    self.assertTrue(words[key].strip())
                    self.assertEqual(sorted(re.findall(r"\{[a-z_]+\}", words[key])), [])
                    if catalog.stem != "en":
                        self.assertNotEqual(words[key], ENGLISH[key], "translated")
            self.assertIn("Codex", words[LINE])
            self.assertIn("Codex", words[BOX])

    def test_english_says_what_it_must(self):
        self.assertEqual(ENGLISH[LINE], "The Codex accounts you saved for switching stay on this PC, sealed for this Windows "
                                        "user, and the standard edition does not use them.")
        self.assertEqual(ENGLISH[BOX], "Also delete the Codex accounts you saved for switching")

    def test_the_setup_program_presets_the_box_from_its_command_line(self):
        self.assertIn('flow.DeleteSavedAccounts = InstallerFlow.Has(arguments, "-DeleteSavedAccounts");', SETUP)
        self.assertIn('"-DeleteSavedAccounts"', FLOW[FLOW.index("private static bool IsAnswered"):])

    @unittest.skipIf(languages.generated_ko_branch(), "the generated ko branch's English pages are the Korean ones")
    def test_the_documents_name_the_change_and_no_advanced_identifier(self):
        for name in ("SECURITY", "PRIVACY"):
            english = (ROOT / "docs" / (name + ".md")).read_text(encoding="utf-8")
            self.assertIn("change to the standard edition", english, name)
            if not languages.both_languages():
                continue  # main and the release carry no Korean documents
            korean = (ROOT / "docs" / (name + ".ko.md")).read_text(encoding="utf-8")
            self.assertIn("표준판", korean[korean.index("accounts"):], name)


if __name__ == "__main__":
    unittest.main()
