r"""v0.6.11: what the window and the panel say of the retry waits, a high limit and the attempts a task used.

The Dashboard looks the waits up in the schema the watcher hands it - a preset's in the table on
Retry timing, Custom's in each wait's seconds - and never works them out itself, so the one place
they are worked out stays `ladder.preview`. This loads the real compiled window and calls its own
methods through reflection, with the real schema, and holds each answer to Python's: the preview
for every preset and for a Custom pick, the notice under the limits, and the Attempts cell - `19/6`
after the limit was lowered, never cut down to it. The panel in Codex is held to the same, running its
own script in Node (PanelTests).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import guiscan

from codex_auto_resume import ladder, settings
from test_mcpui_v064 import ENGLISH, NODE, THREAD, run_page, say, snapshot

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

CUSTOM = ["m2", "m30", "h1", "h3", "h6"]

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
$preview = $form.GetMethod('PreviewWaits', $flags)
$high = $form.GetMethod('AnyHigh', $flags)
$attempts = $form.GetMethod('Attempts', $flags)
foreach ($pair in @(@('PreviewWaits', $preview), @('AnyHigh', $high), @('Attempts', $attempts))) {
    if (-not $pair[1]) { throw ('SettingsForm has no ' + $pair[0]) }
}

# JSON as the window's bridge hands it over: objects as Dictionary<string, object>, arrays as
# List<object>, every number a double.
function To-Value {
    param($value)
    if ($null -eq $value) { return $null }
    if ($value -is [System.Management.Automation.PSCustomObject]) {
        $map = New-Object 'System.Collections.Generic.Dictionary[string,object]'
        foreach ($field in $value.PSObject.Properties) { $map.Add([string]$field.Name, (To-Value $field.Value)) }
        return ,$map
    }
    if ($value -is [Array]) {
        $list = New-Object 'System.Collections.Generic.List[object]'
        foreach ($item in $value) { $list.Add((To-Value $item)) }
        return ,$list
    }
    if ($value -is [bool] -or $value -is [string]) { return $value }
    return [double]$value
}

[Collections.Generic.Dictionary[string,Collections.Generic.Dictionary[string,object]]]$schema =
    New-Object 'System.Collections.Generic.Dictionary[string,System.Collections.Generic.Dictionary[string,object]]'
foreach ($entry in (ConvertFrom-Json $env:CAR_SCHEMA)) {
    if ($entry.group -eq 'limits') { $schema.Add([string]$entry.name, [Collections.Generic.Dictionary[string,object]](To-Value $entry)) }
}
$out = @{ preview = @{}; high = @{}; attempts = @{} }
[Collections.Generic.List[string]]$steps = New-Object 'System.Collections.Generic.List[string]'
foreach ($step in (ConvertFrom-Json $env:CAR_CUSTOM)) { $steps.Add([string]$step) }
foreach ($timing in @('conservative', 'normal', 'aggressive', 'custom', 'nothing')) {
    $found = $preview.Invoke($null, [object[]]@($schema, $timing, $steps))
    $out.preview[$timing] = @($found | ForEach-Object { [double]$_ })
}
$out.preview['custom_short'] = @($preview.Invoke($null, [object[]]@($schema, 'custom', $null)) | ForEach-Object { [double]$_ })

foreach ($case in (ConvertFrom-Json $env:CAR_LIMITS).PSObject.Properties) {
    [Collections.Generic.Dictionary[string,double]]$values = New-Object 'System.Collections.Generic.Dictionary[string,double]'
    foreach ($field in $case.Value.PSObject.Properties) { $values.Add([string]$field.Name, [double]$field.Value) }
    $out.high[$case.Name] = [bool]$high.Invoke($null, [object[]]@($schema, $values))
}

foreach ($case in (ConvertFrom-Json $env:CAR_ROWS).PSObject.Properties) {
    $row = [Collections.Generic.Dictionary[string,object]](To-Value $case.Value)
    $out.attempts[$case.Name] = [string]$attempts.Invoke($null, [object[]]@($row))
}
$out | ConvertTo-Json -Depth 5 -Compress
"""

LIMITS = {"defaults": {"max_recovery_attempts": 4, "max_no_progress": 3, "max_chain_continuations": 6},
          "at_high": {"max_recovery_attempts": 8, "max_no_progress": 5, "max_chain_continuations": 8},
          "attempts_high": {"max_recovery_attempts": 9, "max_no_progress": 3, "max_chain_continuations": 6},
          "chain_high": {"max_recovery_attempts": 4, "max_no_progress": 3, "max_chain_continuations": 9}}
ROWS = {"lowered": {"recovery_attempts": 19, "attempt_limit": 6},
        "within": {"recovery_attempts": 3, "attempt_limit": 4},
        "usage": {"recovery_attempts": 0, "attempt_limit": None},
        "older_watcher": {"recovery_attempts": 2}}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box compiler and PowerShell")
class WaitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64",
                        "/out:" + str(exe), "/reference:System.dll",
                        "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_SCHEMA=json.dumps(settings.describe()),
                     CAR_CUSTOM=json.dumps(CUSTOM), CAR_LIMITS=json.dumps(LIMITS), CAR_ROWS=json.dumps(ROWS)))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_the_preview_is_ladders_for_every_preset_and_for_a_custom_pick(self):
        for timing in settings.RETRY_TIMING:
            with self.subTest(timing):
                self.assertEqual(self.answer["preview"][timing], ladder.preview({"retry_timing": timing}))
        custom = dict(settings.defaults(), retry_timing="custom",
                      **{field: wait for field, wait in zip(ladder.STEP_FIELDS, CUSTOM)})
        self.assertEqual(self.answer["preview"]["custom"], ladder.preview(custom))

    def test_nothing_is_said_for_what_the_schema_does_not_have(self):
        self.assertEqual(self.answer["preview"]["nothing"], [])
        self.assertEqual(self.answer["preview"]["custom_short"], [])

    def test_the_notice_shows_only_above_a_high(self):
        self.assertEqual(self.answer["high"], {"defaults": False, "at_high": False,
                                               "attempts_high": True, "chain_high": True})
        for name, values in LIMITS.items():
            self.assertEqual(self.answer["high"][name], bool(settings.high_limits(values)), name)

    def test_the_attempts_cell_keeps_the_count_beside_the_limit(self):
        self.assertEqual(self.answer["attempts"], {"lowered": "19/6", "within": "3/4", "usage": "0",
                                                   "older_watcher": "2"})


def spoken(seconds) -> str:
    """A wait as the page writes it in English, from the catalog's own words."""
    total = int(round(seconds))
    if total < 60:
        return ENGLISH["time.seconds"].replace("{n}", str(total))
    if total < 3600:
        rest = (" " + ENGLISH["time.seconds"].replace("{n}", str(total % 60))) if total % 60 else ""
        return ENGLISH["time.minutes"].replace("{n}", str(total // 60)) + rest
    rest = (" " + ENGLISH["time.minutes"].replace("{n}", str(total % 3600 // 60))) if total % 3600 >= 60 else ""
    return ENGLISH["time.hours"].replace("{n}", str(total // 3600)) + rest


SHOWN = """(function () {
  var waits = ROOT_NODE.all(function (n) { return n.tagName === 'p' && n.textContent.indexOf(%s) === 0; });
  var high = ROOT_NODE.all(function (n) { return n.className === 'callout' && n.textContent === %s; });
  var meta = ROOT_NODE.all(function (n) { return n.className === 'prow-meta'; });
  return {waits: waits.map(function (n) { return n.textContent; }),
          high: high.map(function (n) { return !n.hidden; }),
          meta: meta.map(function (n) { return n.textContent; })};
})()""" % (json.dumps(ENGLISH["retry.preview"].split("{waits}")[0]), json.dumps(ENGLISH["warn.high_limits"]))


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PanelTests(unittest.TestCase):
    def shown(self, data):
        return run_page(say(SHOWN), data=data)

    def line(self, values, jitter=False):
        line = ENGLISH["retry.preview"].replace("{waits}", " · ".join(map(spoken, ladder.preview(values))))
        return line + (" " + ENGLISH["retry.preview_jitter"] if jitter else "")

    def test_the_waits_line_says_what_ladder_says(self):
        for timing in settings.RETRY_TIMING:
            with self.subTest(timing):
                self.assertEqual(self.shown(snapshot(retry_timing=timing))["waits"],
                                 [self.line({"retry_timing": timing})])
        custom = dict(retry_timing="custom", retry_jitter=True,
                      **{field: wait for field, wait in zip(ladder.STEP_FIELDS, CUSTOM)})
        self.assertEqual(self.shown(snapshot(**custom))["waits"], [self.line(custom, jitter=True)])

    def test_the_high_notice_shows_only_above_a_high(self):
        self.assertEqual(self.shown(snapshot())["high"], [False])
        self.assertEqual(self.shown(snapshot(max_recovery_attempts=9))["high"], [True])
        self.assertEqual(self.shown(snapshot(max_chain_continuations=8))["high"], [False])

    def test_a_pending_row_keeps_the_count_beside_the_limit_and_the_tokens(self):
        data = snapshot()
        data["pending"] = [{"thread_id": THREAD, "interruption_id": "a" * 64, "code": "scheduled",
                            "category": "server_5xx", "thread_enabled": True, "overlays": [],
                            "name": "example-project", "eligible_at": None, "recovery_attempts": 19,
                            "attempt_limit": 6, "context_tokens": 182000}]
        meta = self.shown(data)["meta"]
        self.assertEqual(len(meta), 1)
        self.assertIn(ENGLISH["panel.col_attempts"] + " 19/6", meta[0])
        self.assertIn(ENGLISH["pending.tokens"].replace("{n}", "182,000"), meta[0])


if __name__ == "__main__":
    unittest.main()
