"""A path or value the outside gate is given is only ever a path or a value, whatever quote character it holds.

install.ps1 and the bootstrap built the script that runs outside another app's package view (Get-OutsideSource) with
each path and value as a single-quoted literal. Only the ASCII quote was doubled, but PowerShell also ends such a
string at U+2018, U+2019, U+201A and U+201B: a profile or unpack folder holding one (O'Brien typed on a phone) broke
the script, and a folder named for it (`x'; <command> #` with a curly quote) ran its command in the outside run (the
v0.6.18 security review, M3). Since v0.6.23 that script is constant and the values travel in its environment
(Get-OutsideVariables, STANDARDS D8), so no character of a value is read as code at all.

Get-OutsideSource and Get-OutsideVariables are lifted from each script, and the script is run as the run outside runs
it - with the variables in its environment - against a stand-in at a scratch path with such a name that writes down
what it was given. Nothing of the product runs.
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
SCRIPTS = {"install.ps1": ROOT / "build" / "install" / "install.ps1", "bootstrap.ps1": ROOT / "scripts" / "bootstrap.ps1"}
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CURLY = "\u2019"
CRAFTED = "x" + CURLY + "; Write-Host INJECTED-CODE-RAN #"
RELAY = "CODEX_AUTO_RESUME_RELAY_"

STAND_IN = """param([switch]$Uninstall, [string]$PluginName, [Parameter(ValueFromRemainingArguments = $true)]$Rest)
$seen = [ordered]@{ uninstall = [bool]$Uninstall; plugin = $PluginName; rest = @($Rest); variable = $env:CAR_QUOTED
                   relay = @(Get-ChildItem Env: | Where-Object { $_.Name -like 'CODEX_AUTO_RESUME_RELAY_*' }).Count }
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


def outside_environment(variables: Path) -> dict:
    """The run outside's environment as Invoke-Outside makes it: this one's, less any relay variables of its own, and
    the lines Get-OutsideVariables wrote."""
    environment = {name: value for name, value in os.environ.items() if not name.upper().startswith(RELAY)}
    for entry in variables.read_text(encoding="utf-8-sig").splitlines():
        name, _, value = entry.partition("=")
        environment[name] = value
    return environment


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
        outer = Path(temp.name) / "outer.ps1"
        variables = Path(temp.name) / "variables.txt"
        maker = (function_text(script, "Get-OutsideSource") + "\n" + function_text(script, "Get-OutsideVariables") + "\n"
                 "$v = Get-Content -LiteralPath %s -Raw -Encoding UTF8 | ConvertFrom-Json\n"
                 "$variables = Get-OutsideVariables -Script $v.script -Switches @('Uninstall') "
                 "-Values @{ PluginName = $v.plugin } -Arguments @($v.argument) -Log $v.log -CodeFile $v.code "
                 "-Environment @{ CAR_QUOTED = $v.variable }\n"
                 "[IO.File]::WriteAllText(%s, (Get-OutsideSource), (New-Object Text.UTF8Encoding $true))\n"
                 "[IO.File]::WriteAllLines(%s, $variables)\n"
                 % (ps_literal(given), ps_literal(outer), ps_literal(variables)))
        made = Path(temp.name) / "maker.ps1"
        made.write_text(maker, encoding="utf-8-sig")
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(made)],
                              capture_output=True, encoding="locale", errors="replace", timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(outer)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                              env=outside_environment(variables), creationflags=NO_WINDOW)
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
        self.assertEqual(seen["relay"], 0, "the run outside takes what it was given out of its environment")

    def test_the_installers_gate_keeps_a_curly_quote_a_character(self):
        self.check("install.ps1")

    def test_the_bootstraps_gate_keeps_a_curly_quote_a_character(self):
        self.check("bootstrap.ps1")


if __name__ == "__main__":
    unittest.main()
