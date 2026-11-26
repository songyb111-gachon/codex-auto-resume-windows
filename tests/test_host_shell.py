"""The watcher host's shell (v0.6.27, seat S6.2b; P6-DESIGN 1.4, 1.6, 1.8, 1.9 and 4.1 row 2).

* the source rules: gui/host.sources' groups, no process started by the host's C# (1.8), the core's imports only in
  HostCore.cs, the render mode asked before any DLL loads;
* the GUI-subsystem check: CodexAutoResume.exe, compiled from gui/host.sources as make_gui.ps1 compiles it, is
  /target:winexe (PE subsystem 2) and its manifest declares no DPI awareness;
* the DLL-load test (1.6): a car_core.dll in the current directory, or on PATH, is never loaded - the host loads only
  its own folder's, by full path;
* the mutex handover (1.9): a v0.6.26 Python watcher (this tree's src, the reference) and the host exclude each other
  on a scratch home, both ways, and a host killed mid-run leaves an abandoned mutex the next watcher reconciles.

No window is shown: every run has show_tray off, so the host makes no surface (its pump's window is message-only).
Every run gets a scratch profile, local and roaming folder and Codex home; the named objects are named from the scratch
state folder. The Rust core is the workspace's built car_core.dll (rust/target/release, else debug).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guiscan  # noqa: E402


def groups() -> dict:
    found, group = {}, None
    for line in (GUI / "host.sources").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            group = line[1:-1]
            found[group] = []
        else:
            found[group].append(line)
    return found


def sources() -> list:
    return [name for names in groups().values() for name in names]


def core_dll() -> Path | None:
    for profile in ("release", "debug"):
        path = ROOT / "rust" / "target" / profile / "car_core.dll"
        if path.is_file():
            return path
    return None


def build_host(folder: Path) -> Path:
    """CodexAutoResume.exe compiled from gui/host.sources as make_gui.ps1 compiles it (no version resource)."""
    exe = folder / "CodexAutoResume.exe"
    done = subprocess.run([str(CSC), "-nologo", "-target:winexe", "-platform:x64", "-optimize+", "-warnaserror",
                           "-reference:System.dll", "-reference:System.Drawing.dll", "-out:" + str(exe),
                           "-win32manifest:" + str(GUI / "host.manifest")] + [str(ROOT / name) for name in sources()],
                          capture_output=True, encoding="locale", errors="replace", creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise AssertionError(done.stdout + done.stderr)
    return exe


def subsystem(image: bytes) -> int:
    offset = int.from_bytes(image[60:64], "little")
    return int.from_bytes(image[offset + 92:offset + 94], "little")


class SourceTests(unittest.TestCase):
    def test_the_host_list_has_its_groups_and_the_window_list_names_none_of_them(self):
        found = groups()
        self.assertEqual(found["host"], ["gui/HostCore.cs", "gui/HostMain.cs", "gui/HostPump.cs"])
        self.assertEqual(found["contract"], ["gui/ISurfaces.cs"])
        window = set(guiscan.manifest())
        for name in sources():
            with self.subTest(name):
                self.assertTrue((ROOT / name).is_file())
                self.assertNotIn(name, window)
                self.assertIn(name, guiscan.SEPARATE)

    def test_the_host_starts_no_process(self):
        # P6-DESIGN 1.8: opening the Dashboard, the toast, a relaunch and a supervised child are all the core's.
        for name in sources():
            text = (ROOT / name).read_text(encoding="utf-8")
            for word in ("ProcessStartInfo", "Process.Start", "ShellExecute", "CreateProcess", "WinExec"):
                with self.subTest(name=name, word=word):
                    self.assertNotIn(word, text)

    def test_only_hostcore_imports_the_core_and_main_loads_it_by_full_path(self):
        for name in sources():
            text = (ROOT / name).read_text(encoding="utf-8")
            imports = re.findall(r'\[DllImport\(([^,\)]+)', text)
            with self.subTest(name):
                if name == "gui/HostCore.cs":
                    self.assertEqual(set(imports), {"Dll"})
                else:
                    self.assertTrue(set(imports) <= {'"kernel32.dll"', '"user32.dll"'}, imports)
        main = (GUI / "HostMain.cs").read_text(encoding="utf-8")
        self.assertIn("SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)", main)
        self.assertIn("Path.Combine(folder ?? \".\", HostCore.Dll)", main)
        # The render and probe modes are asked first; the DLL loads after them (S6.3's seam).
        self.assertLess(main.index("SurfaceRender.Run()"), main.index("Load(folder)"))
        self.assertLess(main.index("SurfaceRender.Probe(args)"), main.index("Load(folder)"))
        self.assertNotIn("Application.Run", main + (GUI / "HostPump.cs").read_text(encoding="utf-8"))

    def test_make_gui_builds_the_host_from_its_list_with_its_own_manifest(self):
        script = (ROOT / "build" / "make_gui.ps1").read_text(encoding="utf-8")
        self.assertIn("Read-SourceList 'gui\\host.sources'", script)
        self.assertIn("-Name 'CodexAutoResume.exe' -Target 'winexe' -Kind 'host'", script)
        self.assertIn("-ManifestPath $hostManifest", script)
        manifest = (GUI / "host.manifest").read_text(encoding="utf-8")
        self.assertNotIn("<dpiAware", manifest)
        self.assertNotIn("<dpiAwareness", manifest)


@unittest.skipUnless(CSC.is_file(), "needs the in-box C# compiler")
class BuildTests(unittest.TestCase):
    def test_the_host_is_a_gui_program_with_no_dpi_awareness(self):
        with tempfile.TemporaryDirectory(prefix="car-host-build-") as folder:
            data = build_host(Path(folder)).read_bytes()
            self.assertEqual(subsystem(data), 2, "the host is /target:winexe")
            self.assertIn(b"CodexAutoResume.Host", data)
            self.assertNotIn(b"dpiAware", data)


class Scratch:
    """A scratch PC for one host or watcher: profile, local, roaming, a Codex home, and an installation whose
    app\\bin holds the host (and its car_core.dll where asked). show_tray is off: nothing is drawn."""

    def __init__(self, base: Path, host: Path, dll: Path | None):
        self.base = base
        self.home = base / "install home"
        self.started = []
        self.bin = self.home / "app" / "bin"
        self.bin.mkdir(parents=True)
        shutil.copyfile(host, self.bin / host.name)
        if dll is not None:
            shutil.copyfile(dll, self.bin / "car_core.dll")
        for folder in ("profile", "local", "codex"):
            (base / folder).mkdir()
        (self.home / "config").mkdir()
        (self.home / "config" / "settings.json").write_text(json.dumps({"show_tray": False}), encoding="utf-8")
        (self.home / "runtime.json").write_text(json.dumps({"home": str(self.home)}), encoding="utf-8")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.upper().startswith(("CODEX_AUTO_RESUME", "CAR_CORE"))}
        self.env.update(USERPROFILE=str(base / "profile"), HOME=str(base / "profile"), LOCALAPPDATA=str(base / "local"),
                        APPDATA=str(base / "local"), CODEX_HOME=str(base / "codex"), PYTHONPATH=str(ROOT / "src"),
                        # Both watchers discover codex.exe at their first tick: a named engine that is not there ends
                        # discovery before any candidate - this PC's, or one the ChatGPT app runs - is started.
                        CODEX_AUTO_RESUME_CODEX_EXE=str(base / "no-codex" / "codex.exe"))

    def host(self, cwd: Path | None = None, env: dict | None = None) -> subprocess.Popen:
        return self.keep(subprocess.Popen([str(self.bin / "CodexAutoResume.exe"), "--home", str(self.home), "run"],
                                cwd=str(cwd or self.base), env=env or self.env, creationflags=NO_WINDOW,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def keep(self, process: subprocess.Popen) -> subprocess.Popen:
        """Every process this scratch PC started, so the test ends each one it left running (its own, never another's)."""
        self.started.append(process)
        return process

    def end_all(self) -> None:
        for process in self.started:
            if process.poll() is None:
                process.kill()
                process.wait()

    def python(self) -> subprocess.Popen:
        return self.keep(subprocess.Popen([sys.executable, "-X", "utf8", "-m", "codex_auto_resume.cli", "--home", str(self.home),
                                 "--quiet", "run"], cwd=str(self.base), env=self.env, creationflags=NO_WINDOW,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def stop(self) -> None:
        code = ("from codex_auto_resume.win.sync import StopEvent; import sys; StopEvent(sys.argv[1]).signal()")
        # The state folder is the installation's config folder (config.Paths: state_dir).
        subprocess.run([sys.executable, "-c", code, str(self.home / "config")], env=self.env, check=True,
                       creationflags=NO_WINDOW, timeout=60)

    def hold_mutex(self) -> subprocess.Popen:
        """A process that opens the watcher's named mutex (win/sync.py's name for the scratch state) and holds the
        handle until its standard input closes."""
        code = ("import ctypes, sys; from codex_auto_resume.win.sync import Mutex; "
                "k = ctypes.windll.kernel32; k.OpenMutexW.restype = ctypes.c_void_p; "
                "h = k.OpenMutexW(0x00100000, False, Mutex(sys.argv[1]).name); "
                "print('held' if h else 'none', flush=True); sys.stdin.read()")
        holder = self.keep(subprocess.Popen([sys.executable, "-c", code, str(self.home / "config")], env=self.env,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                            creationflags=NO_WINDOW))
        if holder.stdout.readline().strip() != "held":
            raise AssertionError("the watcher's mutex could not be opened")
        return holder

    def log(self, name: str = "auto-resume.log") -> str:
        path = self.home / "logs" / name
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

    def wait_for(self, text: str, after: int = 0, seconds: float = 90) -> int:
        """The log's length once `text` is in it past `after`."""
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            log = self.log()
            if text in log[after:]:
                return len(log)
            time.sleep(0.2)
        raise AssertionError("%r never came:\n%s\n--- launcher.log\n%s\n--- errors.log\n%s"
                             % (text, self.log(), self.log("launcher.log"), self.log("errors.log")))


def ended(process: subprocess.Popen, seconds: float = 60) -> int:
    try:
        return process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise


STARTED = "watcher started (pid"
BUSY = "another watcher already holds the single-instance mutex; exiting"
ABANDONED = "previous watcher exited without releasing the mutex; reconciling before any send"


@unittest.skipUnless(CSC.is_file(), "needs the in-box C# compiler")
@unittest.skipUnless(core_dll() is not None, "needs a built car_core.dll (cargo build -p car-host in rust/)")
class ProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="car-host-shell-"))
        built = cls.work / "built"
        built.mkdir()
        cls.exe = build_host(built)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def scratch(self, name: str, dll: bool = True) -> Scratch:
        base = self.work / name
        base.mkdir()
        scratch = Scratch(base, self.exe, core_dll() if dll else None)
        self.addCleanup(scratch.end_all)
        return scratch

    def test_a_planted_dll_in_the_current_directory_or_on_path_is_never_loaded(self):
        scratch = self.scratch("planted", dll=False)
        planted = scratch.base / "cwd"
        planted.mkdir()
        shutil.copyfile(core_dll(), planted / "car_core.dll")
        env = dict(scratch.env, PATH=str(planted) + os.pathsep + scratch.env.get("PATH", ""))
        process = scratch.host(cwd=planted, env=env)
        self.assertEqual(ended(process), 1, "the host has no car_core.dll of its own and loads no other")
        errors = scratch.log("errors.log")
        self.assertIn("watcher launcher: car_core.dll could not be loaded from %s (no such file); not starting"
                      % scratch.bin, errors)
        self.assertIn("car_core.dll could not be loaded", scratch.log("launcher.log"))
        self.assertFalse((scratch.home / "state").exists(), "no watcher ran")

    def test_the_host_loads_its_own_dll_beside_a_planted_one(self):
        scratch = self.scratch("own")
        planted = scratch.base / "cwd"
        planted.mkdir()
        (planted / "car_core.dll").write_bytes(b"MZ not a dll at all")
        process = scratch.host(cwd=planted)
        try:
            scratch.wait_for(STARTED)
        finally:
            scratch.stop()
        self.assertEqual(ended(process), 0)
        self.assertIn("stop requested; watcher exiting", scratch.log())

    def test_the_mutex_is_handed_over_between_the_python_watcher_and_the_host(self):
        scratch = self.scratch("handover")
        # (a) a v0.6.26 Python watcher holds the mutex: the host looks twice and exits 3 with the reference's line.
        python = scratch.python()
        mark = scratch.wait_for(STARTED)
        host = scratch.host()
        self.assertEqual(ended(host), 3)
        mark = scratch.wait_for(BUSY, mark)
        # (b) the stop event: Python exits 0, and a host started next takes the mutex.
        scratch.stop()
        self.assertEqual(ended(python), 0)
        host = scratch.host()
        mark = scratch.wait_for(STARTED, mark)
        # (c) the other way round: the Python watcher exits 3 while the host holds it; the stop ends the host with 0.
        python = scratch.python()
        self.assertEqual(ended(python), 3)
        mark = scratch.wait_for(BUSY, mark)
        scratch.stop()
        self.assertEqual(ended(host), 0)
        # (d) a host killed mid-run: the next watcher, of either language, reconciles the abandoned mutex first.
        for first, then in (("host", "python"), ("python", "host")):
            with self.subTest(killed=first, next=then):
                started = getattr(scratch, first)()
                mark = scratch.wait_for(STARTED, mark)
                time.sleep(1.0)
                # A named mutex lives while any handle to it is open; a third holder keeps it across the kill, as a
                # process asking about the watcher does, so the next one finds it abandoned rather than new.
                holder = scratch.hold_mutex()
                try:
                    started.kill()
                    started.wait()
                    following = getattr(scratch, then)()
                    mark = scratch.wait_for(ABANDONED, mark)
                finally:
                    holder.stdin.close()
                    holder.wait(timeout=30)
                scratch.stop()
                self.assertEqual(ended(following), 0)


if __name__ == "__main__":
    unittest.main()
