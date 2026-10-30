"""The setup window mirrored for a language written right to left (v0.6.20, W8a phase B).

The settings window is held to its left-to-right self mirrored by tests/test_gui_mirrored_window.py; this holds the setup
window - the installer's window, the Dashboard's update and the uninstall - to the same (InstallerAudit.MirrorAudit in
build/setup/SetupWindow.cs): every page and finish its layout audit lays out, in Arabic and in Hebrew, laid out once as
if they read left to right and once as they are, each control where the first layout had it mirrored within a pixel, and
the audit right to left reporting nothing. Built by build/make_setup.py into a temporary folder and never shown.

GUI test module: compiles the setup program, runs on its own.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import test_installer_window as setup

from codex_auto_resume import l10n

RIGHT_TO_LEFT = sorted(l10n.RIGHT_TO_LEFT)
# The narrowest and widest scaling, and the largest text size: where a thing stands, which the installer's own audit
# checks for fit at every scaling and text size.
PAIRS = ((1.0, 1.0), (2.0, 1.0), (1.0, 2.25))

MIRROR = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$type = $assembly.GetType('CodexAutoResume.InstallerAudit', $true)
$audit = $type.GetMethod('MirrorAudit', [Reflection.BindingFlags]'Static,NonPublic')
$compared = $type.GetField('AuditedMirror', [Reflection.BindingFlags]'Static,NonPublic')
$out = @{}
foreach ($case in (ConvertFrom-Json $env:CAR_CASES)) {
    $catalog = [IO.File]::ReadAllText([string]$case.catalog, [Text.Encoding]::UTF8)
    $key = [string]$case.name
    $out[$key] = @{}
    foreach ($pair in (ConvertFrom-Json $env:CAR_PAIRS)) {
        $scale = [double]$pair[0]; $text = [double]$pair[1]
        $report = [string]$audit.Invoke($null, [object[]]@([string]$catalog, [string]$case.language, $scale, $text))
        $out[$key][('{0:F2}/{1:F2}' -f $scale, $text)] = @{ report = $report; compared = [int]$compared.GetValue($null) }
    }
}
[IO.File]::WriteAllText($env:CAR_RESULT, ($out | ConvertTo-Json -Depth 5 -Compress), (New-Object Text.UTF8Encoding $false))
"""


class SetupMirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="setup-mirror-"))
        exe = setup._build(cls.work)
        cases = [{"name": locale, "language": locale, "catalog": str(l10n.DIRECTORY / ("%s.json" % locale))}
                 for locale in RIGHT_TO_LEFT]
        result = cls.work / "result.json"
        cls.result = setup._powershell(MIRROR, cls.work, 600 * len(cases), CAR_EXE=str(exe), CAR_CASES=json.dumps(cases),
                                       CAR_PAIRS=json.dumps(PAIRS), CAR_RESULT=str(result))
        cls.answer = (json.loads(result.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and result.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the audit did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_every_page_and_finish_is_its_left_to_right_self_mirrored(self):
        for locale in RIGHT_TO_LEFT:
            for scale, text in PAIRS:
                found = self.answer[locale]["%.2f/%.2f" % (scale, text)]
                with self.subTest(locale=locale, scale=scale, text=text):
                    self.assertEqual(found["report"], "", "\n" + "\n".join(found["report"].splitlines()[:40]))

    def test_the_comparison_looked_at_every_page(self):
        for locale in RIGHT_TO_LEFT:
            for scale, text in PAIRS:
                with self.subTest(locale=locale, scale=scale, text=text):
                    self.assertGreater(self.answer[locale]["%.2f/%.2f" % (scale, text)]["compared"], 300)


if __name__ == "__main__":
    unittest.main()
