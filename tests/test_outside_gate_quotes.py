"""The outside gate quotes every single-quote character PowerShell knows, so a path is only ever a path.

install.ps1 and the bootstrap build the script that runs outside another app's package view (Get-OutsideSource) with
each path and value as a single-quoted literal. Only the ASCII quote was doubled, but PowerShell also ends such a
string at U+2018, U+2019, U+201A and U+201B: a profile or unpack folder holding one (O'Brien typed on a phone) broke
the script, and a folder named for it (`x'; <command> #` with a curly quote) ran its command in the outside run (the
v0.6.18 security review, M3).

Get-OutsideSource is lifted from each script and the script it writes is run as the run outside runs it, against a
stand-in at a scratch path with such a name that writes down what it was given. Nothing of the product runs.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {"install.ps1": ROOT / "build" / "install" / "install.ps1", "bootstrap.ps1": ROOT / "scripts" / "bootstrap.ps1"}
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CURLY = "\u2019"
CRAFTED = "x" + CURLY + "; Write-Host INJECTED-CODE-RAN #"

STAND_IN = """param([switch]$Uninstall, [string]$PluginName, [Parameter(ValueFromRemainingArguments = $true)]$Rest)
$seen = [ordered]@{ uninstall = [bool]$Uninstall; plugin = $PluginName; rest = @($Rest); variable = $env:CAR_QUOTED }
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'seen.json'), (ConvertTo-Json $seen -Compress), [Text.Encoding]::UTF8)
exit 0
"""


def function_text(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), text, re.M | re.S)
    if found is None:
        raise AssertionError("%s has no function %s" % (path.name, name))
    return found.group(0)


def ps_literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == "win32", "the gate is Windows PowerShell")
class OutsideGateQuoteTests(unittest.TestCase):
    def run_gate(self, script: Path) -> tuple[subprocess.CompletedProcess, Path, str]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name) / CRAFTED
        folder.mkdir()
        stand_in = folder / "stand-in.ps1"
        stand_in.write_text(STAND_IN, encoding="utf-8-sig")
        log = folder / "output.txt"
        code_file = folder / "code.txt"
        # The values go to the maker through a file, so no quoting of this test's own stands in their way.
        values = {"script": str(stand_in), "log": str(log), "code": str(code_file),
                  "plugin": "O" + CURLY + "Brien\u2018s \u201aplugin\u201b'", "argument": CRAFTED,
                  "variable": "v" + CURLY + "; Write-Host INJECTED-CODE-RAN #"}
        given = Path(temp.name) / "values.json"
        given.write_text(json.dumps(values), encoding="utf-8")
        maker = (function_text(script, "Get-OutsideSource") + "\n"
                 "$v = Get-Content -LiteralPath %s -Raw -Encoding UTF8 | ConvertFrom-Json\n"
                 "$source = Get-OutsideSource -Script $v.script -Switches @('Uninstall') "
                 "-Values @{ PluginName = $v.plugin } -Arguments @($v.argument) -Log $v.log -CodeFile $v.code "
                 "-Environment @{ CAR_QUOTED = $v.variable }\n"
                 "[IO.File]::WriteAllText(%s, $source, (New-Object Text.UTF8Encoding $true))\n"
                 % (ps_literal(given), ps_literal(Path(temp.name) / "outer.ps1")))
        made = Path(temp.name) / "maker.ps1"
        made.write_text(maker, encoding="utf-8-sig")
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(made)],
                              capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(Path(temp.name) / "outer.ps1")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                              creationflags=NO_WINDOW)
        said = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        return done, folder, said + done.stdout + done.stderr

    def check(self, name: str):
        done, folder, said = self.run_gate(SCRIPTS[name])
        self.assertNotIn("INJECTED-CODE-RAN", said)
        self.assertEqual((folder / "code.txt").read_text(encoding="utf-8").strip(), "0", said)
        seen = json.loads((folder / "seen.json").read_text(encoding="utf-8-sig"))
        self.assertTrue(seen["uninstall"])
        self.assertEqual(seen["plugin"], "O" + CURLY + "Brien\u2018s \u201aplugin\u201b'")
        self.assertEqual(seen["rest"], [CRAFTED])
        self.assertEqual(seen["variable"], "v" + CURLY + "; Write-Host INJECTED-CODE-RAN #")

    def test_the_installers_gate_keeps_a_curly_quote_a_character(self):
        self.check("install.ps1")

    def test_the_bootstraps_gate_keeps_a_curly_quote_a_character(self):
        self.check("bootstrap.ps1")


if __name__ == "__main__":
    unittest.main()
