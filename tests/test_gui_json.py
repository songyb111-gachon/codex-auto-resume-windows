"""The settings window's JSON reader fails as a format error, never as a crash.

The window reads only its own bridge's output, so none of this is reachable by an
attacker today; the security review still demonstrated that a deeply nested document
ended the process with a StackOverflowException, which .NET cannot catch, and that
truncated input raised IndexOutOfRangeException. A reader that can crash its host on
malformed input is one change in data flow away from being a problem.

These tests compile the real window source with the in-box compiler and call its
internal parser through reflection, so what is tested is what ships.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"

PROBE = r"""
$ErrorActionPreference = 'Stop'
$asm = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$json = $asm.GetType('CodexAutoResume.Json', $true)
$parse = $json.GetMethod('Parse', [Reflection.BindingFlags]'Static,NonPublic,Public')
# Parsed on a thread with a 1 MB stack - the window's UI thread size. PowerShell's own
# pipeline thread is far larger, and an unbounded parser survived 20,000 levels there
# while the window would not have.
Add-Type -TypeDefinition @'
using System; using System.Reflection; using System.Threading;
public static class CarParseProbe {
    public static string Run(MethodInfo parse, string text) {
        string outcome = null;
        var thread = new Thread(() => {
            try { parse.Invoke(null, new object[] { text }); outcome = "ok"; }
            catch (TargetInvocationException e) { outcome = e.InnerException.GetType().Name; }
        }, 1024 * 1024);
        thread.Start(); thread.Join();
        return outcome;
    }
}
'@
function Try-Parse([string]$text) { return [CarParseProbe]::Run($parse, $text) }
'deep=' + (Try-Parse ('[' * 20000))
'deepobj=' + (Try-Parse ('{"a":' * 20000))
'truncated=' + (Try-Parse '{"a": [1, 2')
'unterminated=' + (Try-Parse '{"a": "abc')
'normal=' + (Try-Parse '{"ok": true, "strings": {"x": "\uc790\ub3d9"}, "n": [1, 2.5, -3]}')
'nested64=' + (Try-Parse (('[' * 64) + (']' * 64)))
'nested65=' + (Try-Parse (('[' * 65) + (']' * 65)))
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class ParserRobustnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        exe = Path(cls.folder.name) / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        # The settings window's sources, as build/make_gui.ps1 lists them.
                        *[str(ROOT / "gui" / name) for name in ("SettingsApp.cs", "Dashboard.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=180)
        env = dict(os.environ, CAR_EXE=str(exe))
        result = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", PROBE],
                                capture_output=True, text=True, timeout=180, env=env)
        cls.returncode = result.returncode
        cls.outcome = dict(line.split("=", 1) for line in result.stdout.split() if "=" in line)
        cls.stderr = result.stderr

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_probe_process_survived(self):
        """A StackOverflowException would have ended the PowerShell process itself."""
        self.assertEqual(self.returncode, 0, self.stderr[-500:])
        self.assertEqual(len(self.outcome), 7, self.outcome)

    def test_deep_nesting_is_a_format_error(self):
        self.assertEqual(self.outcome.get("deep"), "FormatException")
        self.assertEqual(self.outcome.get("deepobj"), "FormatException")

    def test_truncated_input_is_a_format_error(self):
        self.assertEqual(self.outcome.get("truncated"), "FormatException")
        self.assertEqual(self.outcome.get("unterminated"), "FormatException")

    def test_real_output_still_parses(self):
        self.assertEqual(self.outcome.get("normal"), "ok")

    def test_the_limit_is_where_it_says(self):
        self.assertEqual(self.outcome.get("nested64"), "ok")
        self.assertEqual(self.outcome.get("nested65"), "FormatException")


if __name__ == "__main__":
    unittest.main()
