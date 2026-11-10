r"""Install another version... from the advanced edition to the standard one asks about the saved Codex accounts (v0.6.22).

The setup window's edition change (tests/test_edition_change_accounts.py) says the Codex accounts saved for switching
stay on this PC and offers a box, off, to delete them with the change; install.ps1 takes them with -DeleteSavedAccounts.
The Dashboard's Install another version... is the other way to the same change, and it said only "the advanced features
go, and their code with them" (the v0.6.22 reachability audit, R3): a person who switched there left sealed accounts
behind without a word. It now asks the same question in the same words with the same switch, and the bootstrap's -Pick
passes the switch on to the installer, only for the change it belongs to.

* BootstrapTests - scripts/bootstrap.ps1's Test-DeleteSavedAccounts lifted out and run: which picks pass the switch on.
* FlowTests - the setup program's flow, built as the window tests build it: the Update + Another flow of a pick offers
  the deletion exactly where the setup window's does, and an `accounts` folder with no saved account in it (M12) is not
  one that has anything to say.
* SourceTests - the Dashboard's confirmation shows the statement and the box, and the pick passes the switch once.

Nothing here touches a real installation, the registry or a running process; no window is shown.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import guiscan  # noqa: E402
from test_installer_window import _build, _powershell, CSC  # noqa: E402

WINDOWS = os.name == "nt"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BOOTSTRAP = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
FLOW = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
VERSIONS = (ROOT / "gui" / "DashboardVersions.cs").read_text(encoding="utf-8")
LINE = "installer.options.saved_accounts"
BOX = "installer.options.delete_saved_accounts"


def function_text(name: str) -> str:
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), BOOTSTRAP, re.M | re.S)
    if found is None:
        raise AssertionError("bootstrap.ps1 has no function %s" % name)
    return found.group(0)


def since() -> str:
    found = re.search(r"^\$DeleteAccountsSince = '([^']+)'", BOOTSTRAP, re.M)
    if found is None:
        raise AssertionError("bootstrap.ps1 does not define $DeleteAccountsSince")
    return found.group(1)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the bootstrap is Windows PowerShell")
class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = [  # pick, verdict, edition, target
            ("pick_change_to_standard", True, "change", "standard", "0.6.22"),
            ("the_first_version_that_has_it", True, "change", "standard", since()),
            ("a_later_beta", True, "change", "standard", "0.6.22-beta.2"),
            ("before_the_switch_existed", True, "change", "standard", "0.6.21"),
            ("an_older_alpha", True, "change", "standard", "0.6.22-alpha"),
            ("to_the_advanced_edition", True, "change", "advanced", "0.6.22"),
            ("no_change_of_edition", True, "same", "standard", "0.6.22"),
            ("not_a_pick", False, "change", "standard", "0.6.22"),
        ]
        lines = ["Set-StrictMode -Version 2.0", "$ErrorActionPreference = 'Stop'",
                 "$DeleteAccountsSince = '%s'" % since(),
                 function_text("Get-VersionParts"), function_text("Compare-ProductVersion"),
                 function_text("Test-DeleteSavedAccounts"), "$out = [ordered]@{}"]
        for name, pick, verdict, edition, target in cases:
            lines.append("$out['%s'] = [bool](Test-DeleteSavedAccounts -Pick $%s -Verdict '%s' -Edition '%s' -Target '%s')"
                         % (name, "true" if pick else "false", verdict, edition, target))
        lines.append("$out | ConvertTo-Json -Compress")
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        probe = Path(folder.name) / "probe.ps1"
        probe.write_text("\n".join(lines), encoding="utf-8-sig")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(probe)], capture_output=True, encoding="locale", errors="replace", timeout=180, creationflags=NO_WINDOW)
        if done.returncode != 0:
            raise AssertionError(done.stdout[-1500:] + done.stderr[-1500:])
        cls.answer = json.loads(done.stdout.strip().splitlines()[-1])

    def test_only_a_pick_that_changes_to_the_standard_edition_in_a_version_that_has_the_switch_passes_it_on(self):
        self.assertEqual({name for name, passed in self.answer.items() if passed},
                         {"pick_change_to_standard", "the_first_version_that_has_it", "a_later_beta"}, self.answer)

    def test_the_switch_is_a_parameter_forwarded_once_and_only_through_that_rule(self):
        params = BOOTSTRAP[BOOTSTRAP.index("[CmdletBinding()]"):]
        self.assertIn("[switch]$DeleteSavedAccounts", params[:params.index("\n)")])
        self.assertEqual(BOOTSTRAP.count("$arguments['DeleteSavedAccounts'] = $true"), 1)
        at = BOOTSTRAP.index("$arguments['DeleteSavedAccounts'] = $true")
        self.assertIn("if (Test-DeleteSavedAccounts -Pick ([bool]$Pick) -Verdict $plan.Verdict -Edition $targetEdition -Target $target)",
                      BOOTSTRAP[at - 300:at])
        # The one -Pick check that lists what it goes with names the switch, or the bootstrap would refuse its own flag.
        self.assertIn("goes with -Edition, -Force, -NoStartup and -DeleteSavedAccounts alone.", BOOTSTRAP)

    def test_the_first_version_is_the_one_whose_installer_has_the_switch_and_the_window_agrees(self):
        self.assertEqual(since(), "0.6.22-beta")
        self.assertIn('internal const string DeleteAccountsSince = "%s";' % since(), FLOW)
        installer = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$DeleteSavedAccounts", installer)


FLOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
$FlowType = $assembly.GetType('CodexAutoResume.InstallerFlow', $true)
function NewFlow($mode, $edition, $installed, $saved, $another) {
    $flow = $FlowType.GetConstructors($any)[0].Invoke([object[]]@([string]$mode, 'C:\Users\ExampleUser\.codex-auto-resume', $edition, $installed, '9.9.9'))
    $FlowType.GetField('SavedAccountsThere', $any).SetValue($flow, [bool]$saved)
    $FlowType.GetField('Another', $any).SetValue($flow, [bool]$another)
    $flow
}
function Offers($flow) { [bool]$FlowType.GetProperty('OffersAccountDeletion', $any).GetValue($flow, $null) }
$out = @{}
# mode, edition (picked), installed, saved accounts there, Another (the Dashboard's pick)
$out.pick_advanced_to_standard = Offers (NewFlow 'update' 'standard' 'advanced' $true $true)
$out.pick_with_no_saved_account = Offers (NewFlow 'update' 'standard' 'advanced' $false $true)
$out.pick_to_advanced = Offers (NewFlow 'update' 'advanced' 'standard' $true $true)
$out.pick_same_edition = Offers (NewFlow 'update' 'standard' 'standard' $true $true)
$out.update_that_is_no_pick = Offers (NewFlow 'update' 'standard' 'advanced' $true $false)
$out.setup_window_change = Offers (NewFlow 'install' 'standard' 'advanced' $true $false)
$at = $FlowType.GetMethod('SavedAccountsAt', $any)
foreach ($name in 'marker_only', 'one_account', 'other_files', 'nothing') {
    $out[$name] = [bool]$at.Invoke($null, [object[]]@([string](Join-Path $env:CAR_HOMES $name)))
}
$out | ConvertTo-Json -Compress
"""


@unittest.skipUnless(WINDOWS and CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="pick-accounts-flow-"))
        cls.addClassCleanup(lambda: __import__("shutil").rmtree(cls.work, ignore_errors=True))
        exe = _build(cls.work)
        homes = cls.work / "homes"
        marker = ".owned-by-codex-auto-resume"
        (homes / "marker_only" / "accounts").mkdir(parents=True)
        (homes / "marker_only" / "accounts" / marker).write_text("x", encoding="utf-8")
        (homes / "one_account" / "accounts").mkdir(parents=True)
        (homes / "one_account" / "accounts" / marker).write_text("x", encoding="utf-8")
        (homes / "one_account" / "accounts" / "0123456789abcdef.dat").write_bytes(b"sealed")
        (homes / "other_files" / "accounts" / "scratch-0123456789ab").mkdir(parents=True)
        (homes / "other_files" / "accounts" / marker).write_text("x", encoding="utf-8")
        (homes / "other_files" / "accounts" / "switch.intent").write_bytes(b"x")
        (homes / "nothing").mkdir(parents=True)
        done = _powershell(FLOW_PROBE, cls.work, 300, CAR_EXE=str(exe), CAR_HOMES=str(homes))
        if done.returncode != 0:
            raise AssertionError(done.stdout[-1500:] + done.stderr[-1500:])
        cls.answer = json.loads(done.stdout.strip().splitlines()[-1])

    def test_a_pick_from_the_advanced_edition_to_the_standard_one_offers_the_deletion_as_the_setup_window_does(self):
        self.assertTrue(self.answer["pick_advanced_to_standard"], self.answer)
        self.assertTrue(self.answer["setup_window_change"], self.answer)

    def test_nothing_else_offers_it(self):
        for name in ("pick_with_no_saved_account", "pick_to_advanced", "pick_same_edition", "update_that_is_no_pick"):
            with self.subTest(name):
                self.assertFalse(self.answer[name], self.answer)

    def test_an_accounts_folder_with_no_saved_account_in_it_has_nothing_to_say_or_delete(self):
        """M12: SavedAccountsAt tested only that the folder existed, so the statement and box showed for the folder an Add
        that added nothing, or Delete all, leaves behind (its marker file alone)."""
        self.assertTrue(self.answer["one_account"], self.answer)
        self.assertFalse(self.answer["marker_only"], self.answer)
        self.assertFalse(self.answer["other_files"], "a scratch home and an intent file are no saved account")
        self.assertFalse(self.answer["nothing"], self.answer)


class SourceTests(unittest.TestCase):
    def body(self, member):
        return guiscan.member_body("SettingsForm", member)

    def test_the_confirmation_says_what_becomes_of_the_accounts_and_offers_the_box_in_the_setup_windows_words(self):
        confirm = self.body("ConfirmPick")
        self.assertIn("ask.Another = true;", confirm)
        self.assertIn("ask.SavedAccountsThere = InstallerFlow.SavedAccountsAt(home);", confirm)
        offered = confirm[confirm.index("if (ask.OffersAccountDeletion)"):]
        self.assertIn('"%s"' % LINE, offered)
        self.assertIn('"%s"' % BOX, offered)
        self.assertIn("new InstallerWords(strings, openedLanguage)", offered)
        # The box has a version to be offered for: an installer older than the switch could not take it.
        self.assertIn("CompareVersions(row[0], InstallerFlow.DeleteAccountsSince) >= 0", offered)
        self.assertIn('S("action.install", "Install"), S("action.not_now", "Not now"), deleteAccounts);', confirm)
        self.assertIn("pickDeletesAccounts = yes && deleteAccounts != null && deleteAccounts.Checked;", confirm)
        # One question, in the catalog's own words: the Dashboard has no second sentence for it.
        self.assertNotIn("pick.confirm.saved_accounts", VERSIONS)

    def test_the_pick_passes_the_switch_the_setup_window_passes_once_and_only_for_the_change(self):
        pick = self.body("InstallPick")
        self.assertEqual(VERSIONS.count('"-DeleteSavedAccounts"') + VERSIONS.count('" -DeleteSavedAccounts"'), 1)
        self.assertIn('if (pickDeletesAccounts && row[1] == InstallerFlow.Standard && words.Contains("edition")) '
                      'flag += " -DeleteSavedAccounts";', pick)
        self.assertLess(pick.index('"-Pick "'), pick.index('flag += " -DeleteSavedAccounts";'))
        self.assertLess(pick.index('flag += " -DeleteSavedAccounts";'), pick.index("StartBootstrap(root, script, flag,"))
        self.assertIn("pickDeletesAccounts = false;", pick, "an answer is read once, by the pick it was given for")
        # The same switch the setup program passes (InstallerFlow.Switches), under the same rule.
        self.assertIn('switches.Add("-DeleteSavedAccounts")', FLOW)

    def test_the_flow_offers_it_to_a_pick_as_to_the_setup_windows_change(self):
        self.assertIn("get { return (Mode == Install || Another) && EditionChange && Edition == Standard && "
                      "Installed == Advanced && SavedAccountsThere; }", FLOW)

    def test_the_words_are_the_catalogs_own(self):
        from codex_auto_resume import l10n
        english = l10n.catalog("en")
        self.assertIn(LINE, english)
        self.assertIn(BOX, english)


if __name__ == "__main__":
    unittest.main()
