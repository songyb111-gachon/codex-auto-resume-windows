"""The courier process (v0.6.19, advanced/src/codex_auto_resume_advanced/courier/__main__.py, launch.py): pythonw
running the product's own module with no console, suspended until it is in the starting process's job object made
KILL_ON_JOB_CLOSE; one per home (a named mutex, a second one exits busy); its arguments and exit codes; at most one start
a minute from the watcher; and a courier that never ends never holds the watcher up.

No courier is really started and nothing reaches the network: every start goes to a fake Popen and a fake kernel. The
one real Windows object made is a named mutex under a temporary home's name, released when the test ends.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.domain.errors import AdapterError  # noqa: E402
from codex_auto_resume.win.kernel import JOB_KILL_ON_CLOSE, NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced.courier import __main__ as courier, launch  # noqa: E402


class Process:
    """A started courier as Popen gives one: it never ends unless told to."""
    started = []

    def __init__(self, argv, **options):
        self.argv, self.options, self.pid = argv, options, 4242
        self.killed, self.code = False, None
        Process.started.append(self)

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.code

    def kill(self):
        self.killed, self.code = True, 1


class Lock:
    def __init__(self, error=None):
        self.error, self.entered, self.left = error, 0, 0

    def __enter__(self):
        if self.error is not None:
            raise self.error
        self.entered += 1
        return self

    def __exit__(self, *unused):
        self.left += 1


class Home(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = config.Paths(Path(folder.name) / "home")
        Process.started = []
        launch._STARTED.clear()
        self.addCleanup(launch._STARTED.clear)


class ArgumentTests(unittest.TestCase):
    def test_exactly_a_home_and_at_most_one_mode(self):
        self.assertEqual(courier.parse(["--home", "H"]), {"home": "H", "mode": "drain", "channel": None})
        self.assertEqual(courier.parse(["--home", "H", "--feed"])["mode"], "feed")
        self.assertEqual(courier.parse(["--pair", "--home", "H"])["mode"], "pair")
        self.assertEqual(courier.parse(["--home", "H", "--test", "telegram"]),
                         {"home": "H", "mode": "test", "channel": "telegram"})
        for argv in ([], ["--home"], ["--feed"], ["--home", "H", "--feed", "--pair"], ["--home", "H", "--test", "sms"],
                     ["--home", "H", "--home", "I"], ["--home", "H", "--verbose"], ["--home", "H", "--test"]):
            with self.subTest(argv=argv):
                self.assertIsNone(courier.parse(argv))


class MainTests(Home):
    def test_refused_arguments_exit_4_before_anything_is_taken(self):
        lock = Lock()
        self.assertEqual(courier.main(["--nothing"], mutex=lambda paths: lock), courier.EXIT_REFUSED)
        self.assertEqual(lock.entered, 0)

    def test_a_second_courier_for_the_same_home_exits_busy_and_does_nothing(self):
        worked = []
        with patch.object(courier, "work", lambda *a, **k: worked.append(a) or 0):
            self.assertEqual(courier.main(["--home", str(self.paths.home)],
                                          mutex=lambda paths: Lock(AdapterError("mutex_busy"))), courier.EXIT_BUSY)
            self.assertEqual(courier.main(["--home", str(self.paths.home)],
                                          mutex=lambda paths: Lock(AdapterError("mutex_creation_failed"))),
                             courier.EXIT_REFUSED)
        self.assertEqual(worked, [])

    def test_one_round_under_the_mutex_and_the_mutex_let_go_after_it_even_when_it_fails(self):
        lock = Lock()
        with patch.object(courier, "work", lambda paths, found, **seams: 0 if lock.entered and not lock.left else 99):
            self.assertEqual(courier.main(["--home", str(self.paths.home)], mutex=lambda paths: lock), 0)
        self.assertEqual((lock.entered, lock.left), (1, 1))
        lock = Lock()
        with patch.object(courier, "work", lambda *a, **k: 1 / 0):
            self.assertEqual(courier.main(["--home", str(self.paths.home)], mutex=lambda paths: lock),
                             courier.EXIT_REFUSED)
        self.assertEqual((lock.entered, lock.left), (1, 1))

    @unittest.skipUnless(os.name == "nt", "a Windows named mutex")
    def test_the_real_mutex_refuses_a_second_holder_of_the_same_home(self):
        held, release, done = threading.Event(), threading.Event(), []

        def hold():
            with courier.mutex(self.paths):
                held.set()
                release.wait(10)
        thread = threading.Thread(target=hold)
        thread.start()
        try:
            self.assertTrue(held.wait(10))
            with patch.object(courier, "work", lambda *a, **k: done.append(1) or 0):
                self.assertEqual(courier.main(["--home", str(self.paths.home)]), courier.EXIT_BUSY)
            self.assertEqual(done, [])
            other = config.Paths(Path(self.paths.home).parent / "other")
            with patch.object(courier, "work", lambda *a, **k: done.append(1) or 0):
                self.assertEqual(courier.main(["--home", str(other.home)]), 0, "another home has a mutex of its own")
        finally:
            release.set()
            thread.join(10)
        self.assertIn("codex-auto-resume-", courier.mutex(self.paths).name)


class LaunchTests(Home):
    def spawn(self, *extra, adopt=None):
        adopted = []
        with patch("codex_auto_resume.startup.python_launcher", lambda: Path(r"C:\Python\pythonw.exe")):
            found = launch.spawn(self.paths, *extra, popen=Process,
                                 adopt_it=adopt or (lambda process: adopted.append(process)))
        return found, adopted

    def test_pythonw_runs_the_courier_module_windowless_and_suspended_until_it_is_in_the_job(self):
        found, adopted = self.spawn("--feed")
        process, = Process.started
        self.assertIs(found, process)
        self.assertEqual(adopted, [process])
        self.assertEqual(process.argv, [r"C:\Python\pythonw.exe", "-m", "codex_auto_resume_advanced.courier",
                                        "--home", str(Path(self.paths.home)), "--feed"])
        self.assertEqual(process.options["creationflags"], NO_WINDOW | launch.CREATE_SUSPENDED)
        self.assertFalse(process.options["shell"])
        self.assertEqual(process.options["stdout"], subprocess.DEVNULL)
        roots = process.options["env"]["PYTHONPATH"].split(os.pathsep)
        self.assertTrue(any(root.endswith(os.path.join("advanced", "src")) for root in roots), roots)

    def test_one_the_job_will_not_take_is_ended_before_it_runs_and_counts_as_not_started(self):
        def refuse(process):
            process.kill()
            raise OSError("no job")
        found, _ = self.spawn(adopt=refuse)
        self.assertIsNone(found)
        self.assertTrue(Process.started[0].killed)

    def test_no_pythonw_starts_nothing(self):
        from codex_auto_resume.startup import StartupError

        def missing():
            raise StartupError("no pythonw")
        with patch("codex_auto_resume.startup.python_launcher", missing):
            self.assertIsNone(launch.spawn(self.paths, popen=Process, adopt_it=lambda process: None))
        self.assertEqual(Process.started, [])

    def test_from_the_watcher_at_most_one_start_a_minute_for_a_home(self):
        with patch("codex_auto_resume.startup.python_launcher", lambda: Path(r"C:\Python\pythonw.exe")):
            seams = dict(popen=Process, adopt_it=lambda process: None)
            self.assertTrue(launch.start_due(self.paths, 1000.0, **seams))
            self.assertFalse(launch.start_due(self.paths, 1059.0, "--feed", **seams))
            self.assertTrue(launch.start_due(self.paths, 1060.0, "--feed", **seams))
        self.assertEqual([process.argv[-1] for process in Process.started], [str(Path(self.paths.home)), "--feed"])

    def test_run_waits_at_most_its_time_and_leaves_one_running_to_finish(self):
        with patch("codex_auto_resume.startup.python_launcher", lambda: Path(r"C:\Python\pythonw.exe")):
            began = time.monotonic()
            self.assertIsNone(launch.run(self.paths, "--test", "ntfy", timeout=0.1, popen=Process,
                                         adopt_it=lambda process: None))
            self.assertLess(time.monotonic() - began, 5)
            self.assertFalse(Process.started[0].killed, "left to finish, in the job")

            class Ends(Process):
                def wait(self, timeout=None):
                    return 7
            self.assertEqual(launch.run(self.paths, "--test", "ntfy", popen=Ends, adopt_it=lambda process: None), 7)

    def test_a_start_never_waits_for_the_courier(self):
        """A courier that sleeps for ever: start returns at once."""
        with patch("codex_auto_resume.startup.python_launcher", lambda: Path(r"C:\Python\pythonw.exe")):
            began = time.monotonic()
            self.assertTrue(launch.start(self.paths, popen=Process, adopt_it=lambda process: None))
            self.assertLess(time.monotonic() - began, 1.0)


class JobTests(unittest.TestCase):
    """The job object, as report/github.py makes its own: KILL_ON_JOB_CLOSE, the courier assigned, then resumed."""

    class Kernel:
        def __init__(self, assign=True):
            self.assign, self.calls, self.flags = assign, [], None

        def CreateJobObjectW(self, *a):
            self.calls.append("create")
            return 77

        def SetInformationJobObject(self, handle, kind, info, size):
            self.flags = info._obj.basic.flags
            self.calls.append("limits")
            return True

        def OpenProcess(self, access, inherit, pid):
            self.calls.append(("open", pid))
            return 88

        def AssignProcessToJobObject(self, job, handle):
            self.calls.append(("assign", job, handle))
            return self.assign

        def CloseHandle(self, handle):
            self.calls.append(("close", handle))
            return True

    class NtDll:
        def __init__(self, calls):
            self.calls = calls

        def NtResumeProcess(self, handle):
            self.calls.append("resume")
            return 0

    def setUp(self):
        patcher = patch.object(launch, "_JOB", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def adopt(self, kernel):
        process = Process(["x"])
        real = ctypes.WinDLL if hasattr(ctypes, "WinDLL") else None
        with patch.object(launch, "_kernel", lambda: kernel), \
                patch.object(launch.ctypes, "WinDLL", lambda name: self.NtDll(kernel.calls) if name == "ntdll"
                             else real(name), create=True):
            launch.adopt(process)
        return process

    def test_the_courier_is_put_in_a_kill_on_close_job_then_resumed(self):
        kernel = self.Kernel()
        process = self.adopt(kernel)
        self.assertEqual(kernel.flags, JOB_KILL_ON_CLOSE)
        self.assertEqual(kernel.calls, ["create", "limits", ("open", 4242), ("assign", 77, 88), "resume",
                                        ("close", 88)])
        self.assertFalse(process.killed)

    def test_one_that_cannot_be_put_in_the_job_is_ended(self):
        kernel = self.Kernel(assign=False)
        with self.assertRaises(OSError):
            self.adopt(kernel)
        self.assertNotIn("resume", kernel.calls)


if __name__ == "__main__":
    unittest.main()
