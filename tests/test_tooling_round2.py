"""The build, release and workflow findings of the v0.6.23 second-round tooling audit.

* SmokeStepExitCodeTests (R1) - test.yml's CLI smoke test fails when ANY of its commands exits
  non-zero, not only the last; and no other multi-command pwsh step of any workflow leaves a native
  program's exit code unread.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _steps(workflow: str):
    """(job runs-on, step text) for each step of a workflow, read as text: a job header is two
    spaces in, a step is a dash at six spaces."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    runs_on = ""
    found = []
    for chunk in re.split(r"(?m)^(?=  [A-Za-z0-9_-]+:\n)", text):
        on = re.search(r"(?m)^    runs-on: (\S+)", chunk)
        runs_on = on.group(1) if on else ""
        for step in re.split(r"(?m)^(?=      - )", chunk)[1:]:
            found.append((runs_on, step))
    return found


def _run_script(step: str) -> str:
    """The step's multi-line `run: |` script, dedented, or "" for a one-line run."""
    lines = step.split("\n")
    for number, line in enumerate(lines):
        match = re.match(r"(\s*)run: \|\s*$", line)
        if match:
            body = []
            for later in lines[number + 1:]:
                if later.strip() and len(later) - len(later.lstrip()) <= len(match.group(1)):
                    break
                body.append(later)
            indent = min(len(b) - len(b.lstrip()) for b in body if b.strip())
            return "\n".join(b[indent:] for b in body).rstrip() + "\n"
    return ""


def _shell(runs_on: str, step: str) -> str:
    found = re.search(r"(?m)^\s+shell: (\S+)", step)
    if found:
        return found.group(1)
    return "pwsh" if runs_on.startswith("windows") else "bash"


class SmokeStepExitCodeTests(unittest.TestCase):
    """Run the step's own script the way the runner does (pwsh, `$ErrorActionPreference = 'stop'`
    first, `exit $LASTEXITCODE` last) against a stand-in for the CLI that exits with a chosen
    code on each call: a native program's non-zero exit is not a PowerShell error, so what the
    script does with it is all that decides the step."""

    NATIVE = re.compile(r"^\s*(python|py|git|gh|pip|node|npm|cmd|csc)(\.exe)?\s")

    def _step_script(self) -> str:
        for runs_on, step in _steps("test.yml"):
            if "name: CLI smoke test in an isolated home" in step:
                return _run_script(step)
        raise AssertionError("test.yml has no CLI smoke test step")

    def _powershell(self):
        found = shutil.which("pwsh") or shutil.which("powershell")
        if not found:
            self.skipTest("no PowerShell on this machine")
        return found

    def _run(self, script: str, codes):
        shell = self._powershell()
        with tempfile.TemporaryDirectory() as scratch:
            work = Path(scratch)
            (work / "src").mkdir()
            (work / "src" / "auto_resume.py").write_text(
                "import pathlib, sys\n"
                "count = pathlib.Path('calls.txt')\n"
                "n = int(count.read_text()) if count.exists() else 0\n"
                "count.write_text(str(n + 1))\n"
                "sys.exit(%r[n])\n" % (list(codes),), encoding="utf-8")
            script = script.replace("${{ runner.temp }}", str(work / "temp"))
            (work / "step.ps1").write_text(
                "$ErrorActionPreference = 'stop'\n" + script
                + "\nif ((Test-Path -LiteralPath variable:\\LASTEXITCODE)) { exit $LASTEXITCODE }\n",
                encoding="utf-8")
            env = dict(os.environ, PYTHONPATH="src")
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            done = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "step.ps1"],
                                  cwd=work, env=env, capture_output=True, text=True,
                                  creationflags=NO_WINDOW, timeout=120)
            calls = int((work / "calls.txt").read_text()) if (work / "calls.txt").exists() else 0
            return done.returncode, calls

    def test_a_first_command_that_fails_fails_the_step(self):
        # The audit's repro: exits 3, 0, 0, 0, 0 - the step used to report the last one's 0.
        code, calls = self._run(self._step_script(), [3, 0, 0, 0, 0])
        self.assertEqual(code, 3)
        self.assertEqual(calls, 1, "the step went on after a command failed")

    def test_a_middle_command_that_fails_fails_the_step(self):
        code, calls = self._run(self._step_script(), [0, 0, 5, 0, 0])
        self.assertEqual(code, 5)
        self.assertEqual(calls, 3)

    def test_every_command_runs_when_all_succeed(self):
        code, calls = self._run(self._step_script(), [0, 0, 0, 0, 0])
        self.assertEqual((code, calls), (0, 5))

    def test_the_old_shape_is_what_the_stand_in_catches(self):
        """The stand-in is only worth believing if it reproduces the bug: the step's former five
        bare lines, run the same way, exit 0 over a first command that exited 3."""
        old = "".join('python src\\auto_resume.py --home "x" --quiet %s\n' % verb
                      for verb in ("install", "status", "install", "uninstall", "uninstall"))
        code, calls = self._run(old, [3, 0, 0, 0, 0])
        self.assertEqual((code, calls), (0, 5))

    def test_no_pwsh_step_of_any_workflow_leaves_a_native_exit_code_unread(self):
        for workflow in sorted(p.name for p in WORKFLOWS.glob("*.yml")):
            for runs_on, step in _steps(workflow):
                script = _run_script(step)
                if not script or _shell(runs_on, step) != "pwsh":
                    continue
                lines = [l for l in script.split("\n") if l.strip() and not l.strip().startswith("#")]
                for number, line in enumerate(lines):
                    if self.NATIVE.match(line) and len(lines) > 1:
                        with self.subTest(workflow=workflow, line=line.strip()):
                            following = lines[number + 1] if number + 1 < len(lines) else ""
                            self.assertIn("LASTEXITCODE", following,
                                          "%s: a native command in a multi-line pwsh step is not "
                                          "followed by a check of its exit code" % workflow)


if __name__ == "__main__":
    unittest.main()
