"""An installation root outside the person's profile is made private to them before the program goes into it.

A home moved with CODEX_AUTO_RESUME_PLUGIN_HOME to a folder under a drive root inherits the root's
`Authenticated Users:(OI)(CI)(IO)(M)`, so every other account on the PC could replace the launcher, the program or
the runtime that run as the person at each sign-in (the v0.6.18 security review, R2). install.ps1 now gives such a
root a protected access list - the person, SYSTEM and Administrators, inherited below - and leaves a root inside the
profile as it is.

Protect-RelocatedHome is lifted from install.ps1 and run on a scratch folder whose access list this test sets itself to
the drive root's shape (icacls, on that folder only); the profile it is told is a second scratch folder, so the first
reads as outside it. No real folder's access list is touched.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
ICACLS = r"C:\Windows\System32\icacls.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AUTHENTICATED_USERS = "S-1-5-11"


def block(start: str, end: str) -> str:
    first = INSTALL_PS1.index(start)
    return INSTALL_PS1[first:INSTALL_PS1.index(end, first)]


def ps_literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "access lists are Windows'")
class RelocatedHomeAclTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home = self.folder / "relocated"
        self.home.mkdir()
        # The drive root's shape, on this scratch folder alone: every signed-in account may modify what is made below.
        done = subprocess.run([ICACLS, str(self.home), "/grant", "*%s:(OI)(CI)(M)" % AUTHENTICATED_USERS],
                              capture_output=True, text=True, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (self.home / "watcher-launcher.py").write_text("synthetic launcher fixture", encoding="utf-8")
        self.addCleanup(subprocess.run, [ICACLS, str(self.home), "/reset", "/T", "/C", "/Q"],
                        capture_output=True, creationflags=NO_WINDOW)

    def protect(self, profile: Path) -> dict:
        source = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n"
                  "function Ok { param([string]$m) Write-Host $m }\nfunction Warn { param([string]$m) Write-Host $m }\n" +
                  block("function Resolve-Canonical", "function Get-Edition") +
                  block("function Protect-RelocatedHome", "function Read-UninstallEntry") +
                  "$answer = Protect-RelocatedHome -Root %s -Profile %s\n" % (ps_literal(self.home), ps_literal(profile)) +
                  # Read through .NET as the installer writes: Get-Acl lives in a module a CI runner's PSModulePath
                  # cannot load into Windows PowerShell.
                  "function Rules { param($Path)\n"
                  "  if ([IO.Directory]::Exists($Path)) { $acl = (New-Object IO.DirectoryInfo $Path).GetAccessControl() }\n"
                  "  else { $acl = (New-Object IO.FileInfo $Path).GetAccessControl() }\n"
                  "  @{ protected = $acl.AreAccessRulesProtected; sids = @($acl.GetAccessRules($true, $true,\n"
                  "     [Security.Principal.SecurityIdentifier]) | ForEach-Object { $_.IdentityReference.Value }) } }\n"
                  "$me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n"
                  "ConvertTo-Json -Compress -Depth 4 @{ answer = $answer; me = $me; root = (Rules %s); child = (Rules %s) }\n"
                  % (ps_literal(self.home), ps_literal(self.home / "watcher-launcher.py")))
        path = self.folder / "probe.ps1"
        path.write_text(source, encoding="utf-8-sig")
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)],
                              capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_a_root_outside_the_profile_is_private_to_the_person(self):
        other_profile = self.folder / "profile"
        other_profile.mkdir()
        seen = self.protect(other_profile)
        self.assertEqual(seen["answer"], "protected")
        self.assertTrue(seen["root"]["protected"], "the root must not inherit from the drive")
        for where in ("root", "child"):
            self.assertNotIn(AUTHENTICATED_USERS, seen[where]["sids"], where)
            self.assertIn(seen["me"], seen[where]["sids"], where)
            self.assertLessEqual(set(seen[where]["sids"]), {seen["me"], "S-1-5-18", "S-1-5-32-544"}, where)

    def test_a_root_inside_the_profile_is_left_as_it_is(self):
        seen = self.protect(self.folder)
        self.assertEqual(seen["answer"], "profile")
        self.assertIn(AUTHENTICATED_USERS, seen["root"]["sids"])

    def test_it_runs_before_the_program_is_copied(self):
        protect = INSTALL_PS1.index("Protect-RelocatedHome -Root $OwnedHome")
        self.assertLess(INSTALL_PS1.index("$OwnedHome = Resolve-Canonical (@($claim)[1])"), protect)
        self.assertLess(protect, INSTALL_PS1.index("$claimedAside = Restore-InterruptedCopy"))


if __name__ == "__main__":
    unittest.main()
