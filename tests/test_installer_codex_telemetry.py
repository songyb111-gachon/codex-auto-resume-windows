"""The installer's calls to codex run with telemetry off, as the watcher's own calls do (standard C10).

docs/STANDARDS.md C10 says every codex process this product starts runs with its telemetry off. The watcher's
app-server and queue calls carry OTEL_SDK_DISABLED=true and the `-c` overrides (codex/transport.py, Backend._environment
and Backend._argv); install.ps1's `codex plugin ...` calls (Invoke-Codex: the plugin probe, marketplace add, upgrade
and remove, plugin add and remove, the two lists) carried neither (the v0.6.18 docs audit, REAL #1). Measured before
the change against a scratch CODEX_HOME on codex-cli 0.163.0-alpha.11: `codex -c analytics.enabled=false ... plugin
list --json` exits 0 and prints the list; a wrong value for the same key fails to load the configuration, so the
override is really read.

Invoke-Codex is lifted out of install.ps1 with Start-Process stood in for, so no codex runs here: the stand-in writes
down the command line and the variable Invoke-Codex hands it, and the test reads the line back the way Windows does.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import unittest

from codex_auto_resume.codex.transport import Backend

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STAND_IN = """
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$NoNewWindow, [switch]$Wait, [switch]$PassThru,
          $RedirectStandardOutput, $RedirectStandardError)
    [IO.File]::WriteAllText($seen, ([string]$ArgumentList + "`n" + 'otel=' + [string]$env:OTEL_SDK_DISABLED))
    return [pscustomobject]@{ ExitCode = 0 }
}
"""


def function_text(name: str) -> str:
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), INSTALL_PS1, re.M | re.S)
    if found is None:
        raise AssertionError("install.ps1 has no function %s" % name)
    return found.group(0)


def split_command_line(line: str) -> list[str]:
    """The arguments a program gets from `line`, as Windows' CommandLineToArgvW reads them."""
    count = ctypes.c_int()
    parse = ctypes.windll.shell32.CommandLineToArgvW
    parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
    parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    found = parse("program.exe " + line, ctypes.byref(count))
    try:
        return [found[i] for i in range(1, count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(found)


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class InstallerCodexTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.seen = self.folder / "seen.txt"

    def invoke(self, before: str) -> tuple[list[str], str, str]:
        source = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" +
                  function_text("Quote-Argument") + "\n" + function_text("Invoke-Codex") + "\n" + STAND_IN +
                  "$seen = '%s'\n%s\n" % (str(self.seen).replace("'", "''"), before) +
                  "$done = Invoke-Codex 'codex.exe' @('plugin', 'list', '--json')\n"
                  "Write-Host ('code=' + $done.Code)\nWrite-Host ('after=[' + [string]$env:OTEL_SDK_DISABLED + ']')\n")
        path = self.folder / "probe.ps1"
        path.write_text(source, encoding="utf-8-sig")
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(path)],
                              capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("code=0", done.stdout)
        line, otel = self.seen.read_text(encoding="utf-8").split("\n")
        return split_command_line(line), otel, done.stdout

    def test_each_call_carries_the_watchers_flags_before_its_own_arguments(self):
        arguments, _, _ = self.invoke("$env:OTEL_SDK_DISABLED = $null")
        watcher = Backend._argv(types.SimpleNamespace(codex_exe="codex.exe"))[1:]
        self.assertEqual(arguments, watcher + ["plugin", "list", "--json"])

    def test_each_call_runs_with_the_watchers_variable(self):
        _, otel, _ = self.invoke("$env:OTEL_SDK_DISABLED = $null")
        expected = Backend._environment(types.SimpleNamespace(codex_home="home"))["OTEL_SDK_DISABLED"]
        self.assertEqual(otel, "otel=" + expected)

    def test_the_variable_is_set_for_the_call_alone(self):
        _, _, said = self.invoke("$env:OTEL_SDK_DISABLED = $null")
        self.assertIn("after=[]", said)
        _, _, said = self.invoke("$env:OTEL_SDK_DISABLED = 'kept'")
        self.assertIn("after=[kept]", said)


if __name__ == "__main__":
    unittest.main()
