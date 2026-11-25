"""The installer finds the official Store engine when the old bin directory is absent.

Lift the actual PowerShell function; stand in for Appx registration and the existing offline
signature checker. The interpreter is real, and the candidate files are inert fixtures.
No Codex process, registry, or real installation is touched.
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
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STAND_IN = r"""
function Get-AppxPackage {
    [CmdletBinding()]
    param([string]$Name)
    if ($Name -cne 'OpenAI.Codex') { throw 'unexpected package lookup' }
    if ($env:CAR_APPX_FAIL -eq '1') { throw 'registration unavailable' }
    ConvertFrom-Json -InputObject $env:CAR_PACKAGES
}
"""

SIGNER = """import os
def official_engine(path):
    if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(os.environ['CAR_ENGINE'])):
        raise AssertionError('unexpected engine')
    mode = os.environ['CAR_SIGNATURE']
    if mode == 'error':
        raise RuntimeError('unreadable')
    return (mode != 'bad', mode)
"""


@unittest.skipUnless(sys.platform == "win32" and POWERSHELL.is_file(), "the installer is Windows PowerShell")
class StoreEngineDiscoveryTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name) / "profile [work]"
        self.root.mkdir()
        self.local = self.root / "Local"
        self.local.mkdir()
        self.store = self.root / "WindowsApps" / "OpenAI.Codex_26.1.0.0_x64__2p2nqsd0c76g0"
        self.engine = self.store / "app" / "resources" / "codex.exe"
        self.engine.parent.mkdir(parents=True)
        self.engine.write_bytes(b"MZ")
        self.source = self.root / "src"
        module = self.source / "codex_auto_resume" / "codex" / "pairing.py"
        module.parent.mkdir(parents=True)
        module.write_text(SIGNER, encoding="utf-8")
        self.package = dict(PackageFamilyName="OpenAI.Codex_2p2nqsd0c76g0", Status="Ok",
                            SignatureKind="Store", IsDevelopmentMode=False, InstallLocation=str(self.store))

    def discover(self, packages=None, signature="openai_signature", appx_fail=False, runtime=None, uninstall=False):
        found = re.search(r"^function Get-CodexCli \{.*?^\}\r?$", INSTALL_PS1, re.M | re.S)
        self.assertIsNotNone(found)
        script = self.root / "probe.ps1"
        script.write_text(
            "Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" +
            found.group(0) + "\n" + STAND_IN +
            ("\n$Uninstall = $true\n$interpreter = $env:CAR_PYTHON\n"
             "$verifier = Join-Path (Split-Path -Parent $env:CAR_SOURCE) 'scripts\\plugin_setup.py'\n"
             "@{ found = [string](Get-CodexCli) } | ConvertTo-Json -Compress\n" if uninstall else
             "\n@{ found = [string](Get-CodexCli -RuntimePython $env:CAR_PYTHON "
             "-RuntimeSource $env:CAR_SOURCE) } | ConvertTo-Json -Compress\n"),
            encoding="utf-8-sig")
        done = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, encoding="locale", errors="replace", timeout=60, creationflags=NO_WINDOW,
            env=dict(os.environ, LOCALAPPDATA=str(self.local), CAR_PACKAGES=json.dumps(
                [self.package] if packages is None else packages), CAR_APPX_FAIL=str(int(appx_fail)),
                CAR_ENGINE=str(self.engine), CAR_SIGNATURE=signature, CAR_SOURCE=str(self.source),
                CAR_PYTHON=str(sys.executable if runtime is None else runtime)))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        answer = json.loads(done.stdout.strip().splitlines()[-1])["found"]
        return Path(answer).resolve() if answer else None

    def test_store_only_engine_is_found(self):
        self.assertEqual(self.discover(), self.engine.resolve())

    def test_empty_legacy_bin_falls_back_to_store(self):
        (self.local / "OpenAI" / "Codex" / "bin" / "abc123").mkdir(parents=True)
        self.assertEqual(self.discover(), self.engine.resolve())

    def test_legacy_engine_still_wins_without_appx_or_signature_probe(self):
        legacy = self.local / "OpenAI" / "Codex" / "bin" / "abc123" / "codex.exe"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"MZ")
        self.assertEqual(self.discover(appx_fail=True, signature="error"), legacy.resolve())

    def test_no_registration_or_unavailable_appx_is_refused(self):
        self.assertIsNone(self.discover(packages=[]))
        self.assertIsNone(self.discover(appx_fail=True))

    def test_non_store_unhealthy_or_other_publisher_is_refused(self):
        for field, value in (("PackageFamilyName", "OpenAI.Codex_notopenai"), ("Status", "Error"),
                             ("SignatureKind", "Developer"), ("IsDevelopmentMode", True)):
            with self.subTest(field=field):
                self.assertIsNone(self.discover(packages=[dict(self.package, **{field: value})]))

    def test_ambiguous_registration_is_refused(self):
        self.assertIsNone(self.discover(packages=[self.package, self.package]))

    def test_missing_or_non_file_engine_is_refused(self):
        self.engine.unlink()
        self.assertIsNone(self.discover())
        self.engine.mkdir()
        self.assertIsNone(self.discover())

    def test_only_the_valid_openai_signature_is_accepted(self):
        for mode in ("bad", "official_location", "error"):
            with self.subTest(mode=mode):
                self.assertIsNone(self.discover(signature=mode))

    def test_uninstall_reuses_its_verified_interpreter_and_source(self):
        self.assertEqual(self.discover(uninstall=True), self.engine.resolve())

    def test_missing_bundled_runtime_is_refused(self):
        self.assertIsNone(self.discover(runtime=self.root / "missing.exe"))


if __name__ == "__main__":
    unittest.main()
