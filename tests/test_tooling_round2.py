"""The build, release and workflow findings of the v0.6.23 second-round tooling audit.

* SmokeStepExitCodeTests (R1) - test.yml's CLI smoke test fails when ANY of its commands exits
  non-zero, not only the last; and no other multi-command pwsh step of any workflow leaves a native
  program's exit code unread.
* StampedBuildTests (R2) - make_release packs a settings window or launcher only when the stamp
  make_gui.ps1 left beside it is this tree's (version and sources); a stale or missing one stops the
  build and names the executable and the command that rebuilds it.
* KoWatchLogicTests (M1) - ko-watch.yml counts ko as caught up only on a sync that was for main's
  current commit or a later one containing it, and dates main by its push, not its commit.
* MaintainerToolConsoleTests (M2) - every console child the build tools and scripts start gets
  CREATE_NO_WINDOW (edition_audit, legacy_bootstraps, measure_window, the community_* scripts).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import gui_stamp  # noqa: E402
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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_make_release():
    spec = importlib.util.spec_from_file_location("make_release_round2", ROOT / "build" / "make_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StampedBuildTests(unittest.TestCase):
    """A small tree of its own (the real sources are not needed to know what the stamp is made of),
    stand-in executables, and the real collect_gui."""

    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self._scratch.cleanup)
        self.tree = Path(self._scratch.name) / "tree"
        files = {
            ".codex-plugin/plugin.json": json.dumps({"version": "9.9.9", "author": {"name": "Someone"},
                                                     "interface": {"displayName": "Example"}}),
            "gui/window.sources": "# the window\n[window]\ngui/A.cs  # first\n\ngui/B.cs\n",
            "advanced/gui/window.sources": "advanced/gui/Overlay.cs\n",
            "gui/A.cs": "class A {}", "gui/B.cs": "class B {}", "advanced/gui/Overlay.cs": "class O {}",
            "gui/app.manifest": "<manifest/>", "gui/McpLauncher.cs": "class L {}",
            "gui/RuntimeChoice.cs": "class R {}", "assets/codex-auto-resume.ico": "icon",
            "build/make_gui.ps1": "script", "build/normalize_pe.py": "normalize",
        }
        for name, text in files.items():
            (self.tree / name).parent.mkdir(parents=True, exist_ok=True)
            (self.tree / name).write_text(text, encoding="utf-8")
        self.built = Path(self._scratch.name) / "built"
        (self.built / "advanced").mkdir(parents=True)
        self.release = _load_make_release()
        self.release.ROOT = self.tree
        self.release.BUILT = self.built
        self.window = self.built / self.release.GUI_EXE
        self.advanced_window = self.built / "advanced" / self.release.GUI_EXE
        self.launcher = self.built / self.release.MCP_EXE
        for exe in (self.window, self.advanced_window, self.launcher):
            exe.write_bytes(b"MZ " + exe.name.encode("ascii"))

    def _stamp_all(self):
        gui_stamp.write(self.window, self.tree, "standard", "window")
        gui_stamp.write(self.advanced_window, self.tree, "advanced", "window")
        gui_stamp.write(self.launcher, self.tree, "standard", "launcher")

    def _collect(self, edition: str):
        stage = Path(self._scratch.name) / ("stage-" + edition)
        (stage / "payload").mkdir(parents=True)
        return self.release.collect_gui(stage, edition), stage

    def test_a_stamped_build_of_this_tree_is_packed(self):
        self._stamp_all()
        for edition, exe in (("standard", self.window), ("advanced", self.advanced_window)):
            with self.subTest(edition):
                count, stage = self._collect(edition)
                self.assertEqual(count, 3)
                self.assertEqual((stage / "payload" / self.release.GUI_EXE).read_bytes(), exe.read_bytes())
                self.assertEqual((stage / "payload" / "app" / "mcp" / self.release.MCP_EXE).read_bytes(),
                                 self.launcher.read_bytes())

    def test_an_executable_with_no_stamp_is_refused_by_name(self):
        self._stamp_all()
        gui_stamp.stamp_path(self.advanced_window).unlink()
        with self.assertRaises(SystemExit) as refused:
            self._collect("advanced")
        message = str(refused.exception)
        self.assertIn(str(self.advanced_window), message)
        self.assertIn("make_gui.ps1 -Edition advanced", message)

    def test_a_window_built_for_another_version_is_refused(self):
        """The audit's case: build/advanced/ held the previous release's window."""
        self._stamp_all()
        manifest = self.tree / ".codex-plugin" / "plugin.json"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace("9.9.9", "9.9.10"), encoding="utf-8")
        with self.assertRaises(SystemExit) as refused:
            self._collect("standard")
        message = str(refused.exception)
        self.assertIn(str(self.window), message)
        self.assertIn("built for 9.9.9", message)
        self.assertIn("9.9.10", message)
        self.assertIn("make_gui.ps1", message)

    def test_a_window_built_from_other_sources_of_the_same_version_is_refused(self):
        self._stamp_all()
        (self.tree / "gui" / "B.cs").write_text("class B { int changed; }", encoding="utf-8")
        with self.assertRaises(SystemExit) as refused:
            self._collect("standard")
        self.assertIn("changed after it was built", str(refused.exception))
        self.assertIn(str(self.window), str(refused.exception))

    def test_the_advanced_window_is_stale_when_only_the_overlay_changed(self):
        self._stamp_all()
        (self.tree / "advanced" / "gui" / "Overlay.cs").write_text("class O { int changed; }", encoding="utf-8")
        self._collect("standard")      # the standard window does not read the overlay
        with self.assertRaises(SystemExit):
            self._collect("advanced")

    def test_a_launcher_built_before_its_source_changed_is_refused(self):
        self._stamp_all()
        (self.tree / "gui" / "RuntimeChoice.cs").write_text("class R { int changed; }", encoding="utf-8")
        with self.assertRaises(SystemExit) as refused:
            self._collect("standard")
        # The window reads neither launcher source, so it is the launcher that is named.
        self.assertIn(str(self.launcher), str(refused.exception))

    def test_a_stamp_that_is_not_readable_is_refused_not_trusted(self):
        self._stamp_all()
        gui_stamp.stamp_path(self.window).write_text("not json", encoding="utf-8")
        with self.assertRaises(SystemExit) as refused:
            self._collect("standard")
        self.assertIn("cannot be read", str(refused.exception))

    def test_make_gui_stamps_each_executable_it_builds_after_normalising_it(self):
        script = (ROOT / "build" / "make_gui.ps1").read_text(encoding="utf-8")
        self.assertIn("gui_stamp.py", script)
        self.assertEqual(script.count(" -Kind '"), 2)
        self.assertIn("-Kind 'window'", script)
        self.assertIn("-Kind 'launcher'", script)
        build = script[script.index("function Build {"):script.index("$WindowSources = ")]
        self.assertLess(build.index("normalizer $exe"), build.index("$stamper"))
        self.assertLess(build.index("Remove-Item -LiteralPath ($exe + '.stamp')"), build.index("& $csc"))

    def test_the_release_workflow_builds_both_editions_before_packing(self):
        """CI makes the stamps itself: make_gui.ps1 for both editions in the build job, ahead of the
        steps that run make_release, and a stamp is not an executable for the reproducibility step."""
        release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        built = release.index("./build/make_gui.ps1 -Edition advanced")
        for packing in ("make_release.py --edition standard", "make_release.py --edition advanced"):
            self.assertLess(built, release.index(packing))
        self.assertIn("Get-ChildItem build -Filter *.exe", release)

    def test_the_stamps_are_not_committed(self):
        self.assertIn("build/*.stamp", (ROOT / ".gitignore").read_text(encoding="utf-8"))


FAKE_GH = r'''
import json, os, sys
sys.stdout.reconfigure(newline="\n")        # gh prints LF, on Windows too
scenario = json.load(open(os.environ["FAKE_GH_SCENARIO"], encoding="utf-8"))
argv = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(" ".join(argv) + "\n")
if not argv or argv[0] != "api" or any(a in ("-X", "--method", "-f", "-F", "--input") for a in argv):
    sys.stderr.write("fake gh: only reads\n")
    sys.exit(2)
endpoint = argv[1]
jq = argv[argv.index("--jq") + 1] if "--jq" in argv else ""
base = scenario["main_sha"]
if endpoint.endswith("commits/main"):
    print(base if jq == ".sha" else scenario["committer_date"])
elif endpoint.endswith("commits/ko"):
    print(scenario["ko_message"])
elif "workflows/sync-ko.yml/runs" in endpoint:
    assert "status=success" in endpoint, endpoint
    print("\n".join(scenario["sync_runs"]))
elif "workflows/test.yml/runs" in endpoint:
    for wanted in ("head_sha=" + base, "branch=main", "event=push"):
        assert wanted in endpoint, endpoint
    print("\n".join(scenario["test_runs"]))
elif "/compare/" in endpoint:
    pair = endpoint.rsplit("/compare/", 1)[1]
    first, second = pair.split("...")
    assert first == base, pair
    if second not in scenario["compare"]:
        sys.stderr.write("fake gh: 404\n")
        sys.exit(1)
    print(scenario["compare"][second])
else:
    sys.stderr.write("fake gh: unexpected " + endpoint + "\n")
    sys.exit(2)
'''


def _git_bash():
    candidates = [Path(os.environ.get(name, "")) / "Git" / "bin" / "bash.exe"
                  for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)") if os.environ.get(name)]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("bash")


def _hours_ago(hours: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))


class KoWatchLogicTests(unittest.TestCase):
    """ko-watch.yml's script run as the runner runs it - bash -e, GNU date - against a stand-in `gh` that
    answers each read from a recorded scenario and refuses anything that is not a read. The jq filters
    are gh's own and run on the real API; the stand-in answers after them, so what is held here is the
    decision the script makes on what they print."""

    MAIN = "b" * 40
    OLDER = "a" * 40
    LATER = "c" * 40

    @classmethod
    def setUpClass(cls):
        cls.bash = _git_bash()
        cls.gnu_date = bool(cls.bash) and subprocess.run(
            [cls.bash, "-c", 'test "$(date -u -d 2026-01-01T00:00:00Z +%s)" = 1767225600'],
            capture_output=True, creationflags=NO_WINDOW, timeout=60).returncode == 0
        cls.script = ""
        for runs_on, step in _steps("ko-watch.yml"):
            if "Fail when ko has fallen behind main" in step:
                cls.script = _run_script(step)
        assert cls.script, "ko-watch.yml has no step that fails when ko has fallen behind"

    def setUp(self):
        if not self.gnu_date:
            self.skipTest("no bash with GNU date on this machine")
        self._scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self._scratch.cleanup)
        self.work = Path(self._scratch.name)
        (self.work / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
        (self.work / "gh").write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                                      % (Path(sys.executable).as_posix(), (self.work / "fake_gh.py").as_posix()),
                                      encoding="utf-8", newline="\n")

    def _run(self, **scenario):
        record = {"main_sha": self.MAIN, "committer_date": _hours_ago(10),
                  "ko_message": "Generate ko from main@" + self.OLDER + "\n\nbody",
                  "sync_runs": [], "test_runs": [_hours_ago(10)], "compare": {}}
        record.update(scenario)
        (self.work / "scenario.json").write_text(json.dumps(record), encoding="utf-8")
        (self.work / "gh.log").write_text("", encoding="utf-8")
        env = dict(os.environ, REPO="owner/repo", GH_TOKEN="none",
                   FAKE_GH_SCENARIO=str(self.work / "scenario.json"), FAKE_GH_LOG=str(self.work / "gh.log"))
        env["PATH"] = str(self.work) + os.pathsep + env.get("PATH", "")
        return subprocess.run([self.bash, "-c", "set -eo pipefail\n" + self.script], env=env, capture_output=True,
                              text=True, creationflags=NO_WINDOW, timeout=120)

    def test_ko_built_from_mains_head_is_caught_up(self):
        done = self._run(ko_message="Generate ko from main@" + self.MAIN + "\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("built from main's head", done.stdout)

    def test_a_sync_for_mains_head_that_changed_nothing_is_caught_up(self):
        done = self._run(sync_runs=[self.MAIN, self.OLDER])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("for main's head", done.stdout)

    def test_a_sync_for_a_later_commit_that_contains_mains_head_is_caught_up(self):
        done = self._run(sync_runs=[self.LATER], compare={self.LATER: "ahead"})
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_an_older_commits_sync_that_started_after_mains_head_was_committed_is_not_caught_up(self):
        """The audit's (a): main got A then B, B was committed 10 hours ago and pushed 9, A's sync
        started after B's commit time and succeeded, B's own sync failed. The sync that succeeded is
        for A, which does not contain B: ko is behind, and the watch must say so."""
        done = self._run(sync_runs=[self.OLDER], compare={self.OLDER: "behind"}, test_runs=[_hours_ago(9)])
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("::error::", done.stdout)

    def test_a_sync_of_a_commit_that_does_not_contain_mains_head_is_not_caught_up(self):
        done = self._run(sync_runs=[self.LATER], compare={self.LATER: "diverged"}, test_runs=[_hours_ago(9)])
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)

    def test_a_run_the_comparison_cannot_place_is_not_caught_up(self):
        done = self._run(sync_runs=[self.LATER], compare={}, test_runs=[_hours_ago(9)])
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)

    def test_a_head_pushed_an_hour_ago_has_its_six_hours_however_old_its_commit(self):
        """The audit's (b): a promotion committed 10 hours before it was pushed is one hour old."""
        done = self._run(committer_date=_hours_ago(10), test_runs=[_hours_ago(1)])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("minutes ago", done.stdout)

    def test_the_push_is_the_main_branch_runs_oldest_not_a_later_rerun_or_another_branchs(self):
        # Two runs for main's head; the older one, 9 hours ago, is the push.
        done = self._run(test_runs=[_hours_ago(1), _hours_ago(9)])
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)

    def test_with_no_test_run_found_main_is_dated_by_its_commit(self):
        done = self._run(committer_date=_hours_ago(10), test_runs=[])
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        done = self._run(committer_date=_hours_ago(2), test_runs=[])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_script_only_reads(self):
        self._run(sync_runs=[self.OLDER], compare={self.OLDER: "behind"})
        calls = (self.work / "gh.log").read_text(encoding="utf-8").splitlines()
        self.assertTrue(calls)
        for call in calls:
            self.assertTrue(call.startswith("api "), call)
            for write in (" -X ", " --method", " -f ", " -F ", " --input"):
                self.assertNotIn(write, call + " ")


class MaintainerToolConsoleTests(unittest.TestCase):
    """Every console child the build and release tools and the repository's scripts start gets
    CREATE_NO_WINDOW, as the product's own do (tests/test_no_console_windows.py reads what the
    release ships; these run on the owner's PC whenever a candidate is audited or measured, often
    detached under a parent with no console, and each plain start would flash a window)."""

    SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}
    # Programs that are windows themselves, not console programs: Edge makes the README's pictures.
    GUI_CHILDREN = {"build/make_screenshots.py": "starts Microsoft Edge, a GUI program"}
    # The community scripts are found by their prefix: naming them here would make test_community_file's
    # list of modules that read the filer's files ask for this one.
    NAMED = ("build/edition_audit.py", "build/legacy_bootstraps.py", "build/measure_window.py",
             "build/profile_tachyon.py", "build/make_release.py") + tuple(
        "build/" + path.name for path in sorted((ROOT / "build").glob("community_*.py")))

    def _starts_without_the_flag(self, relative: str) -> list:
        import ast
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                found.append((node.lineno, "from subprocess import: starts cannot be read by name"))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in self.SPAWNERS and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                    and not any(keyword.arg in ("creationflags", None) for keyword in node.keywords)):
                found.append((node.lineno, "subprocess.%s without creationflags" % node.func.attr))
        return found

    def test_the_named_tools_start_every_child_without_a_window(self):
        for relative in self.NAMED:
            with self.subTest(relative):
                self.assertEqual(self._starts_without_the_flag(relative), [])

    def test_no_build_tool_or_script_starts_a_console_child_plainly(self):
        files = sorted(str(path.relative_to(ROOT)).replace("\\", "/")
                       for folder in ("build", "scripts") for path in (ROOT / folder).glob("*.py"))
        self.assertTrue(set(self.NAMED) <= set(files))
        for relative in files:
            if relative in self.GUI_CHILDREN:
                continue
            with self.subTest(relative):
                self.assertEqual(self._starts_without_the_flag(relative), [])

    def test_the_scanner_finds_a_plain_start(self):
        """A scanner that finds nothing proves nothing: the files it was added for, as they were."""
        import ast
        sample = ast.parse("import subprocess\nsubprocess.run(['git'], capture_output=True)\n"
                           "subprocess.run(['git'], creationflags=0)\nsubprocess.Popen(['x'], **options)\n")
        plain = [node.lineno for node in ast.walk(sample)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in self.SPAWNERS
                 and not any(keyword.arg in ("creationflags", None) for keyword in node.keywords)]
        self.assertEqual(plain, [2])


if __name__ == "__main__":
    unittest.main()
