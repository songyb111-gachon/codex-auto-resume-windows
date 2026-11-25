"""Review 9 of the Rust installer (seat S8.2): reproducing tests, each FAILS today (outputs/plans/v0627-rust/REVIEW-install.md).

Every test runs the installers whole on a scratch home, exactly as tests/test_rust_install.py does - its Scratch, its
stages, its stand-ins (the JSON registry, test-only mutex and lock names, the outside gate and Codex stood in) - with one
addition: where a finding needs the core to answer as v0.6.26's plugin_setup.py does on a path the double does not walk,
the stub core is handed a small wrapper around tests/install_double.py (CODEX_AUTO_RESUME_TEST_CORE_SCRIPT), written into
the scratch folder:

* `setup-fails-after`: `setup` does everything the double's setup does - registers the start at sign-in and the link
  handler, starts the watcher where it would start - and then ends with 1. That is v0.6.26's cmd_setup when its
  `install` step fails (`incomplete`): it still registers, still starts the watcher, and returns EXIT_ERROR
  (scripts/plugin_setup.py:337-438 at the tag). The double's own CAR_DOUBLE_FAIL ends before any of that.
* `stop-returns-early`: `stop` comes back with 0 before the watcher has ended - plugin_setup.py's own `stop` waits a
  bounded time, and a watcher in the middle of a recovery turn outlives it.

Nothing here shows a window, touches the real install, its registry values or its watcher, or reaches the network: the
same guarantees as test_rust_install, whose helpers these are.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
_TESTS = str(ROOT / "tests")
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import test_rust_install as proofs  # noqa: E402

WRAPPER = r'''import os, sys, time
sys.path.insert(0, %(tests)r)
import install_double
words = sys.argv[1:]
mode = os.environ.get("CAR_REVIEW9_MODE", "").split(",")
if words[:1] == ["stop"] and "stop-returns-early" in mode:
    print("watcher: asked to stop")
    sys.exit(0)
if words[:1] == ["setup"] and "kill-at-setup" in mode:
    open(os.environ["CAR_REVIEW9_MARK"], "w").close()
    time.sleep(20)
    sys.exit(1)
code = install_double.main(words)
if words[:1] == ["setup"] and "setup-fails-after" in mode:
    print("error: the state could not be prepared (v0.6.26's `incomplete`, after registering and starting)")
    sys.exit(1)
sys.exit(code)
'''


def program_of(value: str) -> Path:
    """The program a Run value or a link handler starts: its first word."""
    return Path(shlex.split(value, posix=False)[0].strip('"'))


@unittest.skipIf(proofs.SKIP, proofs.SKIP or "")
class Review9Proofs(unittest.TestCase):
    v0626_installed = proofs.InstallerProofs.v0626_installed
    said = proofs.InstallerProofs.said

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="car-review9-install-")
        self.scratch = proofs.Scratch(Path(self.work.name))
        self.addCleanup(self.work.cleanup)
        self.addCleanup(self.scratch.stop)
        self.wrapper = self.scratch.folder / "review9_core.py"
        self.wrapper.write_text(WRAPPER % {"tests": _TESTS}, encoding="utf-8")

    def core(self, mode: str) -> dict:
        return {"CODEX_AUTO_RESUME_TEST_CORE_SCRIPT": str(self.wrapper), "CAR_REVIEW9_MODE": mode}

    def assert_a_working_version(self) -> None:
        """v0.6.26 back whole, or the Rust version whole: never neither."""
        home = self.scratch.home
        python = ((home / "app" / "src" / "codex_auto_resume" / "__init__.py").is_file()
                  and (home / "runtime" / "python.exe").is_file()
                  and (home / "runtime" / "python.exe").read_bytes() == (proofs.BASE / "python.exe").read_bytes())
        rust = (home / "app" / "bin" / "codex-auto-resume.exe").is_file()
        self.assertTrue(python or rust, "neither v0.6.26 nor the Rust version is installed: %s"
                        % sorted(path.name for path in home.iterdir()))

    # ---------------------------------------------------------------- B1: registrations left on the removed programs
    def test_b1_a_failed_migration_with_the_watcher_stopped_leaves_no_registration_on_a_removed_program(self):
        """The watcher was not running before the update (stopped by the person, or ended); the start at sign-in is
        on. The Rust setup registers the start at sign-in and the link handler on app\\bin and fails; Undo-Migration
        puts v0.6.26 back but runs no setup of its own where no watcher ran (install.ps1:1598-1606), so both stay on the
        Rust programs it just removed: nothing starts at the next sign-in, and a notification's button opens nothing."""
        self.v0626_installed("standard")
        self.scratch.stop()
        rust = proofs.rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent", **self.core("setup-fails-after"))
        self.assertEqual(done.returncode, 1, self.said(done))
        self.assertIn("Nothing was changed: the version that was installed is installed again.", done.stdout)
        registry = self.scratch.registered()
        for name in ("run", "protocol"):
            self.assertTrue(registry.get(name), name)
            self.assertTrue(program_of(registry[name]).is_file(),
                            "%s names %s, which the put-back removed: %s" % (name, program_of(registry[name]),
                                                                              registry[name]))

    def test_b1_a_failed_migration_with_no_start_at_sign_in_leaves_the_link_handler_on_a_removed_program(self):
        """The same with the start at sign-in off: no watcher is started anywhere, and the link handler alone is left
        on app\\bin\\codex-auto-resume.exe, which the put-back removed."""
        self.v0626_installed("standard")
        self.scratch.stop()
        registry = self.scratch.registered()
        registry["run"] = None
        self.scratch.registry.write_text(json.dumps(registry), encoding="utf-8")
        rust = proofs.rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent", **self.core("setup-fails-after"))
        self.assertEqual(done.returncode, 1, self.said(done))
        self.assertIn("put back as it was", done.stdout)
        protocol = self.scratch.registered()["protocol"]
        self.assertTrue(program_of(protocol).is_file(), "the link handler names a removed program: %s" % protocol)

    # ---------------------------------------------------------------- B2: the put-back path itself failing
    def test_b2_a_put_back_under_a_watcher_that_has_not_ended_leaves_no_working_version(self):
        """The Rust setup started the host and failed; Undo-Migration asks the core to stop and removes app\\ at once
        (install.ps1:1577-1590), without waiting for the host to end as the update's own hand-over does
        (install.ps1:2173-2177). Remove-OwnedItem deletes all it can (Remove-Item -Recurse -Force, SilentlyContinue):
        the core, the scripts and the data go, the running host's own files stay, the Python tree cannot be moved back,
        and Undo returns before it puts the window back or starts anything. Neither version is left."""
        self.v0626_installed("standard")
        rust = proofs.rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent", **self.core("setup-fails-after,stop-returns-early"))
        self.assertEqual(done.returncode, 1, self.said(done))
        self.assert_a_working_version()

    # ---------------------------------------------------------------- B4: the way back leaves a running watcher stopped
    def test_b4_going_back_to_v0626_keeps_a_watcher_that_ran_without_a_start_at_sign_in(self):
        """A Rust installation whose watcher runs and whose start at sign-in is off. The bootstrap's 6.10 step stops
        the watcher before v0.6.26's installer runs (bootstrap.ps1:2942), so that installer sees none running and
        passes --watcher-was-stopped (v0.6.26 install.ps1, `$upgrade -and -not $watcherWasRunning`): with no start at
        sign-in its setup leaves the watcher stopped and says it "was not running before". A pick from v0.6.26 to
        v0.6.26's own versions keeps that watcher running (its installer stops and starts it itself)."""
        rust = proofs.rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent", "-SkipStartup")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertEqual(self.scratch.running_as(), "rust")
        self.assertFalse(self.scratch.registered().get("run"))
        python = proofs.python_stage(self.scratch.folder, "standard", self.scratch.lock)
        bootstrap = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        step = self.scratch.powershell(
            "$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version 2.0\n"
            + proofs.function_text(bootstrap, "Stop-WatcherBeforeOlder") + "\n"
            + "Stop-WatcherBeforeOlder -Home_ '%s' -Unpacked '%s'\n" % (self.scratch.home, python))
        self.assertEqual(step.stdout.strip().splitlines()[-1:], ["stopped"], self.said(step))
        done = self.scratch.install(python, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertEqual(self.scratch.running_as(), "python",
                         "the watcher that ran before going back is not running after it:\n" + self.said(done))

    # ---------------------------------------------------------------- B5: v0.6.26's installer run by hand (6.10)
    def test_b5_v0626s_installer_run_by_hand_over_a_running_rust_watcher_hands_over(self):
        """v0.6.26's Setup exe, its Install.cmd, or our own bootstrap's `-ArchivePath <v0.6.26 zip> -Force` (no -Pick, so
        no 6.10 step: bootstrap.ps1:2942) run v0.6.26's installer straight over a Rust installation. It looks for a
        watcher only as runtime\\pythonw.exe (its install.ps1:681-690), moves app\\ aside under the running host, and
        its setup finds the mutex held and reports the watcher running: the Rust host goes on from app.old-<stamp>,
        whose files that installer then deletes around it, and v0.6.26's watcher never starts."""
        rust = proofs.rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertEqual(self.scratch.running_as(), "rust")
        python = proofs.python_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(python, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertEqual(self.scratch.running_as(), "python",
                         "the Rust host runs on from the folder v0.6.26 moved aside:\n" + self.said(done))

    # ---------------------------------------------------------------- B7: a Rust installation that lost its core
    def test_b7_a_repair_of_an_installation_whose_core_is_gone_stops_the_running_host(self):
        """app\\bin\\codex-auto-resume.exe is gone (an antivirus quarantine of the unsigned binary - PLAN risk 8 - or a
        cut-off removal) while the host runs. Invoke-InstalledEngine (install.ps1:1195-1203) then asks
        runtime\\python.exe - car-legacy - `-X disable-remote-debug plugin_setup.py stop`, a line car-legacy refuses
        (GROUNDWORK S8.2), though the archive's own core (`$PayloadCore`) is at hand. The repair waits its minute, moves
        app\\ aside under the running host, and its setup finds the mutex held: the old host runs on from
        app.old-<stamp>, and the last word asks the person to wait for a watcher that will not stop by itself."""
        rust = proofs.rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertEqual(self.scratch.running_as(), "rust")
        (self.scratch.home / "app" / "bin" / "codex-auto-resume.exe").unlink()
        done = self.scratch.install(rust, "-Silent")
        self.assertNotIn("The previous watcher is still finishing and was left running.", done.stdout, self.said(done))
        self.assertIn("[ok] The previous watcher stopped", done.stdout, self.said(done))

    # ---------------------------------------------------------------- B3: an interrupted migration's leftovers
    def test_b3_a_migration_cut_off_at_its_setup_and_run_again_leaves_nothing_behind(self):
        """The installer ends at the Rust setup (a reboot, a kill). The next run finds a Rust installation
        ($fromPython false), so Complete-Migration never runs: the `.migrating` copies of the window, the icon and the
        kept uninstaller stay for good (nothing sweeps that name), and the Python trees the journal still claims stay
        through that run as well."""
        self.v0626_installed("standard")
        rust = proofs.rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        mark = self.scratch.folder / "review9-at-setup"
        script = str(rust / "install" / "install.ps1").replace("'", "''")
        installer = subprocess.Popen(
            [str(proofs.POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
             "Set-StrictMode -Version 2.0; & '%s' -Silent; exit $LASTEXITCODE" % script],
            cwd=str(self.scratch.folder), env=self.scratch.env(CAR_REVIEW9_MARK=str(mark), **self.core("kill-at-setup")),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            creationflags=proofs.NO_WINDOW)
        try:
            deadline = time.monotonic() + 300
            while not mark.exists() and installer.poll() is None and time.monotonic() < deadline:
                time.sleep(0.2)
            self.assertTrue(mark.exists(), "the installer never reached its setup")
        finally:
            if installer.poll() is None:
                installer.kill()  # the PowerShell this test started, and nothing else
            installer.wait(30)
        time.sleep(21)  # the wrapper (the stub core's child) ends by itself
        done = self.scratch.install(rust, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        leftovers = sorted(path.name for path in self.scratch.home.rglob("*")
                           if path.name.endswith(".migrating") or ".old-" in path.name)
        self.assertEqual(leftovers, [], self.said(done))


if __name__ == "__main__":
    unittest.main()
