r"""A window probe never waits on a process it started (dev CI, 2026-10-22).

Dev CI run 39782463093 hung for two hours on every lane, each at the module after test_gui_v0617_diagnostics,
test_gui_v0611_waits or test_gui_v0614_hang: test_gui_v0620_audit, whose stand-in watcher (a pythonw.exe nothing may
end, ChildTree.Spared) outlived the probe. The runner's TEMP is an 8.3 short name, so the cleanup - by path inside
the test's folder - did not know the stand-in's long path, and the stand-in slept for ever. It held the probe's
inherited stdout, and run_probe read that pipe to its end: past the probe, and past the timeout too, since
subprocess.run reads the pipes again after it kills a timed-out child. Reproduced here with TEMP set to a short name.

run_probe now writes the probe's output to files, the stand-ins end themselves after two minutes, and the audit's
folder is resolved. This holds the first: a probe that leaves a process holding its output behind is answered at once.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from test_gui_v0611_access import NO_WINDOW, POWERSHELL, run_probe

HOLD_SECONDS = 60

PROBE = r"""
$ErrorActionPreference = 'Stop'
# A child that keeps this probe's stdout - redirecting only its stdin hands it this process's own output - and lives on.
$info = New-Object Diagnostics.ProcessStartInfo
$info.FileName = (Get-Process -Id $PID).Path
$info.Arguments = '-NoProfile -NonInteractive -Command Start-Sleep -Seconds ' + $env:CAR_HOLD
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardInput = $true
$child = [Diagnostics.Process]::Start($info)
Write-Output 'the probe has written to its output'
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), (ConvertTo-Json @{ child = $child.Id } -Compress))
"""


@unittest.skipUnless(os.name == "nt" and POWERSHELL.is_file(), "needs Windows PowerShell")
class ProbeTests(unittest.TestCase):
    def test_a_probe_is_answered_although_a_process_it_left_holds_its_output(self):
        with tempfile.TemporaryDirectory() as name:
            work = Path(name)
            started = time.monotonic()
            answer = run_probe(PROBE, work, 120, CAR_HOLD=str(HOLD_SECONDS))
            took = time.monotonic() - started
            # The child is this test's own: ended by its id, whatever the result.
            subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command",
                            "Stop-Process -Id %d -Force -ErrorAction SilentlyContinue" % int(answer["child"])],
                           capture_output=True, timeout=60, creationflags=NO_WINDOW)
        self.assertLess(took, HOLD_SECONDS / 2, "run_probe waited %.0f s for a process the probe left behind" % took)


if __name__ == "__main__":
    unittest.main()
