"""The script that runs outside another app's view is the same text on every run; the values travel in its environment.

STANDARDS D8: values that reach PowerShell travel as environment variables to constant scripts. install.ps1 and the
bootstrap run themselves (or the installation's setup) again outside an MSIX app's private view through WMI
(Resolve-OutsideRun, Invoke-Outside). Until v0.6.23 the script given to -EncodedCommand was written afresh for each
run with every path and value spliced in as a quoted literal (the 2026-11-12 standards audit, S3); now
Get-OutsideSource is constant and Get-OutsideVariables puts what the run is to do into the environment block of the
Win32_ProcessStartup, as CODEX_AUTO_RESUME_RELAY_* variables the run outside reads and takes out of its environment.

The whole gate is lifted from each script and Resolve-OutsideRun runs twice with different values - quotes of every
kind PowerShell ends a string at, `$`, a backtick, a path with spaces and non-ASCII letters - its process table
stubbed to an app's and WMI's two calls standing in as functions: the startup object is written down, and Create
starts the very command line it is given with the environment block it is given, as a hidden child, against a
stand-in at a scratch path that writes down what it got. Nothing of the product runs.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {"install.ps1": ROOT / "build" / "install" / "install.ps1", "bootstrap.ps1": ROOT / "scripts" / "bootstrap.ps1"}
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RELAY = "CODEX_AUTO_RESUME_RELAY_"
INJECTED = "INJECTED-CODE-RAN"
QUOTES = "' \u2018 \u2019 \u201a \u201b \""

VOICE = ("[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n"
         "function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) }\n")

# Defined after the gate, so these are the ones its functions call.
STUBS = r"""
function Get-ProcessTable {
    param([int]$Self)
    $table = @{}
    $table[$Self] = @{ Parent = 41; Created = 50; Package = $null }
    $table[41] = @{ Parent = 4; Created = 40; Package = 'OpenAI.Codex_2p2nqsd0c76g0' }
    return $table
}
function New-CimInstance {
    [CmdletBinding()]
    param([string]$ClassName, [switch]$ClientOnly, [hashtable]$Property)
    $script:startupSeen = $Property
    return $Property
}
function Invoke-CimMethod {
    [CmdletBinding()]
    param([string]$ClassName, [string]$MethodName, [hashtable]$Arguments)
    $line = [string]$Arguments.CommandLine
    $script:lineSeen = $line
    $close = $line.IndexOf('"', 1)
    $info = New-Object System.Diagnostics.ProcessStartInfo($line.Substring(1, $close - 1), $line.Substring($close + 2))
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.EnvironmentVariables.Clear()
    foreach ($entry in @($script:startupSeen.EnvironmentVariables)) {
        $at = $entry.IndexOf('=')
        if ($at -gt 0) { $info.EnvironmentVariables[$entry.Substring(0, $at)] = $entry.Substring($at + 1) }
    }
    $process = [System.Diagnostics.Process]::Start($info)
    return [pscustomobject]@{ ReturnValue = 0; ProcessId = $process.Id }
}
"""

BODY = r"""
$v = Get-Content -LiteralPath $env:CAR_VALUES -Raw -Encoding UTF8 | ConvertFrom-Json
$answers = @()
foreach ($run in $v) {
    $script:lineSeen = $null
    $script:startupSeen = $null
    $code = Resolve-OutsideRun -Script $run.script -Switches @('Uninstall') -Values @{ PluginName = $run.plugin } `
                               -Arguments @($run.argument) -Environment @{ CAR_QUOTED = $run.variable }
    $answers += ,([ordered]@{ code = $code; line = $script:lineSeen
                             relay = @(@($script:startupSeen.EnvironmentVariables) | Where-Object { $_ -like 'CODEX_AUTO_RESUME_RELAY_*' }) })
}
'SOURCE ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-OutsideSource)))
'JSON ' + (ConvertTo-Json $answers -Compress -Depth 4)
"""

STAND_IN = """param([switch]$Uninstall, [string]$PluginName, [Parameter(ValueFromRemainingArguments = $true)]$Rest)
$seen = [ordered]@{ uninstall = [bool]$Uninstall; plugin = $PluginName; rest = @($Rest); variable = $env:CAR_QUOTED
                   relay = @(Get-ChildItem Env: | Where-Object { $_.Name -like 'CODEX_AUTO_RESUME_RELAY_*' }).Count }
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'seen.json'), (ConvertTo-Json $seen -Compress), [Text.Encoding]::UTF8)
Write-Host 'the stand-in ran'
exit 3
"""


def outside_gate(text: str) -> str:
    start = text.index("# Opens a process for limited query")
    return text[start:text.index("# <<< the outside gate", start)]


@unittest.skipUnless(sys.platform == "win32" and POWERSHELL.is_file(), "the gate is Windows PowerShell")
class ConstantOutsideScriptTests(unittest.TestCase):
    def runs(self, name: str):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        work = Path(temp.name)
        # Two runs, every value different: Windows keeps " out of a folder name, so the path has the rest.
        folders = [work / ("first run \u2018quoted\u2019 \u201aand\u201b it's $HOME `n \ud55c\uad6d\uc5b4 \u00dcn\u00efc\u00f8de"),
                   work / "second, other $null \u2019 x' \u00e9t\u00e9 \u4e2d\u6587 `t"]
        runs = []
        for number, folder in enumerate(folders):
            folder.mkdir()
            (folder / "stand-in.ps1").write_text(STAND_IN, encoding="utf-8-sig")
            runs.append({"script": str(folder / "stand-in.ps1"),
                         "plugin": ["it's %s $env:USERNAME `$(Write-Host %s)" % (QUOTES, INJECTED), "plain"][number],
                         "argument": ["$(Write-Host %s) %s `" % (INJECTED, QUOTES), "other"][number],
                         "variable": ["v%s; Write-Host %s # $x `0" % (QUOTES, INJECTED), "another"][number]})
        given = work / "values.json"
        given.write_text(json.dumps(runs), encoding="utf-8")
        temp_folder = work / "temp"
        temp_folder.mkdir()
        probe = work / "probe.ps1"
        probe.write_text(VOICE + outside_gate(SCRIPTS[name].read_text(encoding="utf-8")) + STUBS + BODY,
                         encoding="utf-8-sig")
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() != "CODEX_AUTO_RESUME_OUTSIDE" and not key.upper().startswith(RELAY)}
        environment.update(CAR_VALUES=str(given), TEMP=str(temp_folder), TMP=str(temp_folder))
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(probe)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=240, env=environment, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn(INJECTED, done.stdout + done.stderr)
        answers = json.loads(next(line[5:] for line in done.stdout.splitlines() if line.startswith("JSON ")))
        source = base64.b64decode(next(line[7:] for line in done.stdout.splitlines() if line.startswith("SOURCE ")))
        seen = [json.loads((folder / "seen.json").read_text(encoding="utf-8-sig")) for folder in folders]
        return runs, answers, source.decode("utf-8"), seen, done.stdout

    def check(self, name: str):
        runs, answers, source, seen, said = self.runs(name)
        self.assertEqual([answer["code"] for answer in answers], [3, 3], said)
        self.assertIn("the stand-in ran", said, "what the run outside printed is passed on")
        first, second = (answer["line"] for answer in answers)
        self.assertEqual(first, second, "the encoded script differs between two runs with different values")
        encoded = first.rsplit(" ", 1)[1]
        self.assertEqual(base64.b64decode(encoded).decode("utf-16-le"), source)
        for run in runs:
            for value in run.values():
                self.assertNotIn(value, source)
        for run, answer, got in zip(runs, answers, seen):
            with self.subTest(run["script"]):
                self.assertEqual(got, {"uninstall": True, "plugin": run["plugin"], "rest": [run["argument"]],
                                       "variable": run["variable"], "relay": 0})
                relay = {entry.split("=", 1)[0][len(RELAY):]: base64.b64decode(entry.split("=", 1)[1]).decode("utf-8")
                         for entry in answer["relay"]}
                self.assertEqual(relay["SCRIPT"], run["script"])
                self.assertEqual((relay["VALUE_NAME_0"], relay["VALUE_0"]), ("PluginName", run["plugin"]))

    def test_the_installers_outside_script_is_constant(self):
        self.check("install.ps1")

    def test_the_bootstraps_outside_script_is_constant(self):
        self.check("bootstrap.ps1")


if __name__ == "__main__":
    unittest.main()
