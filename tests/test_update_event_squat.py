r"""The Dashboard does not listen to a close-for-update event someone else made first (v0.6.18, security M6).

An update asks this installation's Dashboard windows to close themselves through a named event,
`Local\CodexAutoResume.CloseForUpdate.<16 hex of the installation's path>` (gui/WindowReopen.cs WatchForUpdate,
install.ps1 Get-UpdateEventName). Anyone who reads the code can work the name out. A Low-integrity process - a
browser's sandbox, say - or another account that made it first and set it closed every Dashboard as it opened. The
window now refuses an event that existed before it under the rule the watcher's own named objects follow
(win/kernel.py): a label below Medium, or an owner that is neither this account, the administrators nor Windows.

The real compiled window is loaded and its methods are called through reflection; the squatter's Low-labelled event
is planted by this process, which holds it while the window's code opens it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

import guiscan
from test_named_objects import LOW_LABEL, close, plant

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
OTHER_ACCOUNT = "S-1-5-21-1111111111-2222222222-3333333333-1002"
ME = "S-1-5-21-1-2-3-1001"

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
$owner = $form.GetMethod('TrustedOwner', $flags)
$squatted = $form.GetMethod('SquattedEvent', $flags)
$out = @{ owners = @(); events = @{} }
# A null from the JSON arrives as '' - read as nothing, as a null is.
foreach ($pair in ($env:CAR_OWNERS | ConvertFrom-Json)) {
    $arguments = New-Object 'object[]' 2
    $arguments[0] = [string]$pair[0]
    $arguments[1] = [string]$pair[1]
    $out.owners += [bool]$owner.Invoke($null, $arguments)
}
foreach ($name in @('ordinary', 'low')) {
    # Opened as the window opens it (WatchForUpdate): created, or found already there.
    $created = $false
    $event = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::ManualReset,
                                                          (Get-Item "env:CAR_$name").Value, [ref]$created)
    try {
        if ($created) { throw "the planted event $name was not there" }
        $arguments = New-Object 'object[]' 1
        $arguments[0] = $event.psobject.BaseObject
        $out.events[$name] = [bool]$squatted.Invoke($null, $arguments)
    } finally { $event.Dispose() }
}
$out | ConvertTo-Json -Depth 4 -Compress
"""

OWNERS = [([ME, ME], True), (["S-1-5-32-544", ME], True), (["S-1-5-18", ME], True),
          ([OTHER_ACCOUNT, ME], False), (["S-1-1-0", ME], False), ([None, ME], False), ([ME, None], False)]


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(),
                     "needs Windows, the in-box compiler and PowerShell")
class UpdateEventSquatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        names = {kind: "Local\\car-bughunt-update-%s-%s" % (kind, uuid.uuid4().hex) for kind in ("ordinary", "low")}
        handles = [plant("event", names["ordinary"], None), plant("event", names["low"], LOW_LABEL)]
        try:
            probe = work / "probe.ps1"
            probe.write_text(PROBE, encoding="utf-8")
            cls.result = subprocess.run(
                [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env=dict(os.environ, CAR_EXE=str(exe), CAR_ordinary=names["ordinary"], CAR_low=names["low"],
                         CAR_OWNERS=json.dumps([pair for pair, _ in OWNERS])))
        finally:
            for handle in handles:
                close(handle)
        cls.answer = (json.loads(cls.result.stdout)
                      if cls.result.returncode == 0 and cls.result.stdout.strip() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_who_may_own_the_event(self):
        self.assertEqual(self.answer["owners"], [trusted for _, trusted in OWNERS])

    def test_a_low_labelled_event_is_refused(self):
        self.assertIs(self.answer["events"]["low"], True)

    def test_this_accounts_own_event_is_listened_to(self):
        """Another Dashboard of this installation, or the installer, made it: still heard."""
        self.assertIs(self.answer["events"]["ordinary"], False)


class WatchForUpdateTests(unittest.TestCase):
    def test_an_event_that_existed_before_is_checked_before_it_is_listened_to(self):
        body = guiscan.member_body("SettingsForm", "WatchForUpdate")
        self.assertIn("UpdateEventName(installRoot), out created)", body)
        check = body.index("if (!created && SquattedEvent(updateClose))")
        self.assertLess(check, body.index("RegisterWaitForSingleObject"), "refused before the wait is registered")
        refused = body[check:body.index("RegisterWaitForSingleObject")]
        self.assertIn("updateClose = null;", refused)
        self.assertIn("return;", refused)


if __name__ == "__main__":
    unittest.main()
