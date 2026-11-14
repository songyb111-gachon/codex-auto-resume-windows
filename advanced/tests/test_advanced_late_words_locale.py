"""A window in English because its words came late asks this edition's words in English too (v0.6.23, the final's live acceptance).

After an update the setup program reopened the Dashboard, whose words came after it had opened (StringsWaitMilliseconds):
its header, tabs, lists and buttons were English and this page's tab, the Chat tab and the Pending buttons of this edition
Korean - the page asked advanced-words in the stored language (LocaleArgument: no locale while the window had read none,
which the bridge answers in the stored one). A window that opened late now asks in English (openedLate) until it reopens in
its language (TakeLateWords), so it is in one language all along.

The real compiled advanced window's LocaleArgument is asked of a window object no constructor made (nothing is built,
nothing shown, no bridge), with the fields it reads set.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_late_words_locale.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pagecase  # noqa: E402
from test_gui_v0611_access import CSC, POWERSHELL, run_probe  # noqa: E402

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$utf8 = New-Object Text.UTF8Encoding $false
$out = @{}
$locale = $F.GetMethod('LocaleArgument', $flags)
foreach ($case in @(@('late', $true, 'system'), @('lateNothingRead', $true, $null), @('onTime', $false, 'system'),
                    @('onTimeKorean', $false, 'ko'), @('nothingRead', $false, $null))) {
    $window = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($F)
    [GC]::SuppressFinalize($window)
    $F.GetField('openedLate', $flags).SetValue($window, [bool]$case[1])
    $F.GetField('openedLanguage', $flags).SetValue($window, $case[2])
    $out[$case[0]] = @([string]$locale.Invoke($window, [object[]]@($null)), [string]$locale.Invoke($window, [object[]]@('queue_for_open')))
}
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), (ConvertTo-Json $out -Compress -Depth 4), $utf8)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class LateWordsLocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = pagecase.compile_window(work)
        cls.answer = run_probe(PROBE, work, 240, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_a_window_that_opened_late_asks_in_english(self):
        for case in ("late", "lateNothingRead"):
            with self.subTest(case):
                self.assertEqual(self.answer[case], ['{"locale":"en"}', '{"capability":"queue_for_open","locale":"en"}'])

    def test_a_window_that_had_its_words_asks_as_before(self):
        self.assertEqual(self.answer["onTime"],
                         ['{"locale":"system"}', '{"capability":"queue_for_open","locale":"system"}'])
        self.assertEqual(self.answer["onTimeKorean"], ['{"locale":"ko"}', '{"capability":"queue_for_open","locale":"ko"}'])
        self.assertEqual(self.answer["nothingRead"], ['{}', '{"capability":"queue_for_open"}'])


if __name__ == "__main__":
    unittest.main()
