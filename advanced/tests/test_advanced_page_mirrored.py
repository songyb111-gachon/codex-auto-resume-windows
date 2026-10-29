"""The Dashboard's Advanced features page mirrored in a language written right to left (v0.6.20, W8a phase A).

The standard window's pages, Settings sections and dialogs are held to their left-to-right selves mirrored by
tests/test_gui_mirrored_window.py (SettingsForm.MirrorAudit). This holds the advanced edition's page to the same: every
view the page's own layout audit lays out (AdvancedLayoutAudit - each capability open with every warning there is, then
unread, the narrowest window on two screens, the compatibility report's card in each of its states, Pending's scheduled
group) laid out in Arabic and in Hebrew as if they were written left to right, and as they are, and compared
(AdvancedMirrorAudit, through SettingsForm.MirrorCompare): each control the screen-reader walk reaches stands where the
first layout had it mirrored, within a pixel; each list's first column at its right; each row of buttons that flows
from the right with its first button at its left; and the page's own audit, right to left, reports nothing.

The window is compiled once for the module and its replies are made by this edition's real bridge in a temporary home
(pagecase), so nothing here reads the real installation. GUI test module: compiles real executables, runs on its own.

    PYTHONPATH=src;advanced/src;tests python -m unittest discover -s advanced/tests -p test_advanced_page_mirrored.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pagecase  # noqa: E402
from pagecase import CSC, POWERSHELL  # noqa: E402

from codex_auto_resume import l10n  # noqa: E402

RIGHT_TO_LEFT = sorted(l10n.RIGHT_TO_LEFT)
# The narrowest and the widest scaling: what the comparison checks - where a thing stands, not whether it fits, which
# the five layout modules check at every scaling for these languages too.
SCALES = (1.0, 2.0)

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$audit = $form.GetMethod('AdvancedMirrorAudit', $static)
$compared = $form.GetField('AuditedMirror', $static)
if (-not $audit) { throw 'SettingsForm has no AdvancedMirrorAudit' }
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
function Text([string]$name) { [IO.File]::ReadAllText((Join-Path $work $name), $utf8) }
$out = @{}
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
        $key = $locale + ' ' + ([double]$scale).ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
        $report = [string]$audit.Invoke($null, [object[]]@((Text ('strings-' + $locale + '.json')), (Text ('words-' + $locale + '.json')),
                                                          (Text ('listing-' + $locale + '.json')), (Text ('statements-' + $locale + '.json')),
                                                          (Text ('kept-' + $locale + '.json')), (Text ('reports-' + $locale + '.json')),
                                                          [double]$scale))
        $out[$key] = @{ report = $report; compared = [int]$compared.GetValue($null) }
    }
}
[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Depth 6 -Compress), $utf8)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class AdvancedMirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = pagecase.compile_window(work)
        bridge = pagecase.Bridge(work / "home")
        try:
            for locale in RIGHT_TO_LEFT:
                # In the page's own words, as a person will see it once Arabic and Hebrew are offered: while they are
                # held (l10n.HELD) the bridge answers them in English, and English read right to left wraps otherwise
                # than read left to right - a comparison of the reading direction, not of the layout (measured: the
                # other_sessions card a line taller at 200%).
                with patch.object(l10n, "HELD", frozenset()), patch.object(l10n, "OFFERED", tuple(l10n.LOCALES)):
                    data = pagecase.audit_data(locale, bridge)
                for part in ("words", "listing", "statements", "kept", "reports"):
                    (work / ("%s-%s.json" % (part, locale))).write_text(json.dumps(data[part], ensure_ascii=False),
                                                                         encoding="utf-8")
                (work / ("strings-%s.json" % locale)).write_text(json.dumps(pagecase.strings(locale), ensure_ascii=False),
                                                                  encoding="utf-8")
        finally:
            bridge.close()
        script = work / "probe.ps1"
        script.write_text(PROBE, encoding="utf-8")
        cls.run_ = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_LOCALES=json.dumps(RIGHT_TO_LEFT),
                     CAR_SCALES=json.dumps(list(SCALES))))
        result = work / "result.json"
        cls.answer = (json.loads(result.read_text(encoding="utf-8-sig"))
                      if cls.run_.returncode == 0 and result.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.run_.stderr or self.run_.stdout)[-3000:])

    def test_every_view_of_the_page_is_its_left_to_right_self_mirrored(self):
        for locale in RIGHT_TO_LEFT:
            for scale in SCALES:
                found = self.answer["%s %.2f" % (locale, scale)]
                with self.subTest(locale=locale, scale=scale):
                    self.assertEqual(found["report"], "", "\n" + "\n".join(found["report"].splitlines()[:60]))

    def test_the_comparison_looked_at_the_whole_page(self):
        for locale in RIGHT_TO_LEFT:
            for scale in SCALES:
                with self.subTest(locale=locale, scale=scale):
                    self.assertGreater(self.answer["%s %.2f" % (locale, scale)]["compared"], 1000)


if __name__ == "__main__":
    unittest.main()
