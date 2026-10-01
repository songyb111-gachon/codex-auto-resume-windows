"""The one-file installers: build/make_setup.py and build/setup/Setup.cs.

Each release ships CodexAutoResume-Setup-v<version>.exe and CodexAutoResume-Advanced-Setup-v<version>.exe: the
edition's release ZIP, byte for byte, inside a small program that unpacks it into a new folder of its own and
runs that archive's Install.cmd there. What is held here:

* BuildTests - the program carries exactly the archive it was built around, with its SHA-256; two builds of
  one archive are one file; it is a console program for x64 that asks for no elevation, and says its edition.
* HandOffTests - built around a TEST archive whose Install.cmd only writes down what it was given, never the
  real installer: it runs that Install.cmd by its full path, in the folder it unpacked everything into, with
  the arguments it was given, passes its exit code back and removes the folder; it refuses an argument cmd
  would read as more than a word, damaged bytes, an entry that climbs out of its folder, and a folder - or a
  junction - that is already there.
* DllTests - copies of Windows' own DLLs beside it and in the current folder, as a DLL of one of their names
  could be waiting in Downloads: none is loaded from either (the --loaded-modules hook), and a .config beside
  it stops it.
* LongTempTests - a temporary folder long enough that the release's own entries run past 260 characters below
  it: everything is unpacked, run and removed all the same.
* CloseTests - the console window closed while Install.cmd runs, as a person closes it at its last "Press any
  key": the folder is removed all the same. The console is a pseudo-console with no window, and Install.cmd
  only writes a line and waits.
* SourceTests, ReleaseTests, DocsTests - what the source, the release build and workflow, and the install
  instructions have to say.

Every run points TEMP and TMP at a folder of the test's own, so nothing is unpacked anywhere else, and every
child is started with CREATE_NO_WINDOW and no input - or, in CloseTests, in a pseudo-console, which has no
window either.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import make_setup  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SOURCE = (ROOT / make_setup.SOURCE).read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

# What the test archive's Install.cmd writes down, one line each, and the code it ends with - both through the
# environment the setup program passes on, so one build serves every run.
RECORDER = (
    "@echo off\r\n"
    ">>\"%SETUP_TEST_RECORD%\" echo args=[%*]\r\n"
    ">>\"%SETUP_TEST_RECORD%\" echo cd=[%CD%]\r\n"
    ">>\"%SETUP_TEST_RECORD%\" echo script=[%~f0]\r\n"
    "dir /s /b /a-d \"%~dp0\" >>\"%SETUP_TEST_RECORD%\"\r\n"
    "exit /b %SETUP_TEST_EXIT%\r\n")
TEST_ENTRIES = {"Install.cmd": RECORDER.encode("ascii"),
                "install/install.ps1": b"# never run: the test's Install.cmd does not call it\r\n",
                "payload/app/src/codex_auto_resume/__init__.py": b"",
                "payload/app/.codex-plugin/plugin.json": b'{"name": "codex-auto-resume", "version": "9.9.9"}\n',
                "payload/runtime/python.exe": b"MZ not a program"}
VERSION = "9.9.9"
FOLDER = re.compile(r"\ACodexAutoResume-Setup-[0-9a-f]{16}\Z")

# Windows' own DLLs, copied beside the setup program as a DLL of one of their names could be waiting in
# Downloads: the four codex-compat-reporter 1.4.0 loaded from its own folder (bcrypt, profapi, CRYPTSP,
# CRYPTBASE), more that .NET and compression load or could, and the one this program's own code calls into.
PLANTED = ("bcrypt.dll", "profapi.dll", "CRYPTSP.dll", "CRYPTBASE.dll", "version.dll", "uxtheme.dll",
           "dwmapi.dll", "winmm.dll", "secur32.dll", "sspicli.dll", "psapi.dll", "mscoree.dll", "kernel32.dll",
           "user32.dll")


def write_zip(path: Path, entries: dict) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in entries.items():
            bundle.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data,
                            compress_type=zipfile.ZIP_DEFLATED)
    return path


def system32() -> Path:
    """System32 as a 64-bit program sees it, which a 32-bit Python sees only as Sysnative."""
    windows = Path(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "C:\\Windows")
    native = windows / "Sysnative"
    return native if native.is_dir() else windows / "System32"


def same(one, other) -> bool:
    return os.path.normcase(str(Path(one).resolve())) == os.path.normcase(str(Path(other).resolve()))


class Scratch:
    """A folder of the test's own, with a temporary folder in it for the program to unpack into."""

    def __init__(self, case: unittest.TestCase):
        self.base = Path(tempfile.mkdtemp(prefix="setup-"))
        case.addCleanup(shutil.rmtree, self.base, True)
        self.temp = self.base / "temp"
        self.temp.mkdir()
        self.record = self.base / "record.txt"

    def run(self, exe: Path, *arguments: str, exit_code: int = 7, cwd: Path | None = None):
        environment = dict(os.environ, TEMP=str(self.temp), TMP=str(self.temp),
                           SETUP_TEST_RECORD=str(self.record), SETUP_TEST_EXIT=str(exit_code))
        return subprocess.run([str(exe), *arguments], capture_output=True, stdin=subprocess.DEVNULL,
                              cwd=str(cwd or self.base), env=environment, timeout=180, creationflags=NO_WINDOW)

    def recorded(self) -> list:
        return self.record.read_text(encoding="mbcs", errors="replace").splitlines() if self.record.exists() else []

    def left(self) -> list:
        return sorted(path.name for path in self.temp.iterdir())


def build_around(entries: dict, folder: Path, edition: str = "standard", name: str = "Test-v9.9.9-win-x64.zip"):
    folder.mkdir(parents=True, exist_ok=True)
    archive = write_zip(folder / name, entries)
    return archive, make_setup.build(archive, folder / ("out-" + edition), edition, VERSION)


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="setup-build-"))
        cls.archive, cls.exe = build_around(TEST_ENTRIES, cls.work)
        cls.image = cls.exe.read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_it_carries_the_archive_byte_for_byte_and_its_digest(self):
        self.assertEqual(make_setup.carried(self.image), self.archive.read_bytes())
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        start, end = make_setup.carried_span(self.image)
        self.assertIn(digest.encode("utf-16-le"), self.image[:start] + self.image[end:])

    def test_building_it_leaves_the_archive_as_it_was(self):
        self.assertEqual(self.archive.read_bytes(), write_zip(self.work / "again.zip", TEST_ENTRIES).read_bytes())

    def test_two_builds_of_one_archive_are_one_file_and_another_archive_another(self):
        time.sleep(1.1)   # the compiler's timestamp has one-second resolution; straddle one
        again = make_setup.build(self.archive, self.work / "again", "standard", VERSION)
        self.assertEqual(again.read_bytes(), self.image)
        other = write_zip(self.work / "Other-v9.9.9-win-x64.zip", dict(TEST_ENTRIES, **{"extra.txt": b"more"}))
        self.assertNotEqual(make_setup.build(other, self.work / "other", "standard", VERSION).read_bytes(),
                            self.image)

    def test_a_program_that_is_not_one_is_refused_by_the_reader(self):
        for image in (b"MZ" + bytes(200), self.image[:4096], b""):
            with self.subTest(len(image)), self.assertRaises(ValueError):
                make_setup.carried(image)

    def test_it_is_a_console_program_for_x64_that_asks_for_no_elevation(self):
        pe = struct.unpack_from("<I", self.image, 0x3C)[0]
        self.assertEqual(struct.unpack_from("<H", self.image, pe + 4)[0], 0x8664, "x64")
        self.assertEqual(struct.unpack_from("<H", self.image, pe + 24 + 68)[0], 3, "the console subsystem")
        self.assertIn(b'level="asInvoker"', self.image)
        for elevated in (b"requireAdministrator", b"highestAvailable"):
            self.assertNotIn(elevated, self.image)

    def test_its_name_and_version_resource_say_the_edition(self):
        self.assertEqual(make_setup.setup_name("standard", "0.6.11"), "CodexAutoResume-Setup-v0.6.11.exe")
        self.assertEqual(make_setup.setup_name("advanced", "0.6.11-beta.2"),
                         "CodexAutoResume-Advanced-Setup-v0.6.11-beta.2.exe")
        self.assertEqual(self.exe.name, "CodexAutoResume-Setup-v9.9.9.exe")
        self.assertIn("Codex Auto Resume setup (Standard edition)".encode("utf-16-le"), self.image)
        advanced = make_setup.build(self.archive, self.work / "advanced", "advanced", VERSION).read_bytes()
        self.assertIn("Codex Auto Resume setup (Advanced edition)".encode("utf-16-le"), advanced)
        self.assertNotIn("(Advanced edition)".encode("utf-16-le"), self.image)
        with self.assertRaises(ValueError):
            make_setup.version_source("standard", "0.6.11-beta.1")


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class HandOffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="setup-handoff-"))
        cls.archive, cls.exe = build_around(TEST_ENTRIES, cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.scratch = Scratch(self)

    def test_it_runs_the_archives_own_install_cmd_in_its_folder_with_the_arguments(self):
        done = self.scratch.run(self.exe, "-SkipStartup", "-AllowEditionChange")
        self.assertEqual(done.returncode, 7, done.stderr)
        lines = self.scratch.recorded()
        self.assertEqual(lines[0], "args=[-SkipStartup -AllowEditionChange]")
        folder = Path(lines[1][len("cd=["):-1])
        self.assertTrue(same(folder.parent, self.scratch.temp), folder)
        self.assertRegex(folder.name, FOLDER)
        self.assertEqual(lines[2], "script=[%s]" % (folder / "Install.cmd"))
        unpacked = sorted(Path(line).relative_to(folder).as_posix() for line in lines[3:])
        self.assertEqual(unpacked, sorted(TEST_ENTRIES))
        self.assertEqual(self.scratch.left(), [], "the folder is removed afterwards")
        self.assertIn(("unpacking %s into %s" % (self.archive.name, folder)).encode("mbcs"), done.stdout)

    def test_install_cmds_exit_code_is_its_own(self):
        for code in (0, 1, 14):
            with self.subTest(code):
                self.assertEqual(self.scratch.run(self.exe, exit_code=code).returncode, code)
        self.assertEqual(self.scratch.left(), [])
        self.assertEqual(sum(line.startswith("args=[]") for line in self.scratch.recorded()), 3)

    def test_an_argument_cmd_would_read_as_more_than_a_word_is_refused(self):
        for argument in ("-Skip&Startup", "a b", "-Name^x", "%PATH%", "\"x\"", "--anything", "-", "a|b", "-x>y"):
            with self.subTest(argument):
                done = self.scratch.run(self.exe, "-SkipStartup", argument)
                self.assertEqual(done.returncode, 42)
                self.assertIn(b"passes on to Install.cmd only switches and plain words", done.stderr)
        self.assertEqual((self.scratch.recorded(), self.scratch.left()), ([], []), "nothing ran or was unpacked")

    def test_damaged_bytes_stop_it_before_anything_is_unpacked(self):
        image = bytearray(self.exe.read_bytes())
        start, end = make_setup.carried_span(bytes(image))
        image[(start + end) // 2] ^= 0x01
        damaged = self.scratch.base / self.exe.name
        damaged.write_bytes(bytes(image))
        done = self.scratch.run(damaged)
        self.assertEqual(done.returncode, 43)
        self.assertIn(b"its SHA-256 differs", done.stderr)
        self.assertEqual((self.scratch.recorded(), self.scratch.left()), ([], []))

    def test_an_entry_that_would_land_outside_its_folder_is_refused(self):
        for name, entry in (("climbs", "../escape.txt"), ("drive", "C:/escape.txt"), ("dots", "payload/./x.txt")):
            with self.subTest(entry):
                _, exe = build_around(dict(TEST_ENTRIES, **{entry: b"out"}), self.scratch.base / name)
                done = self.scratch.run(exe)
                self.assertEqual(done.returncode, 45, done.stderr)
                self.assertIn(entry.encode("ascii"), done.stderr)
                self.assertEqual((self.scratch.recorded(), self.scratch.left()), ([], []))
                self.assertFalse((self.scratch.base / "escape.txt").exists())

    def test_a_folder_that_is_already_there_is_refused_a_junction_too(self):
        taken = self.scratch.temp / "taken"
        taken.mkdir()
        (taken / "someone's.txt").write_bytes(b"theirs")
        elsewhere = self.scratch.base / "elsewhere"
        elsewhere.mkdir()
        link = self.scratch.temp / "linked"
        made = subprocess.run([str(system32() / "cmd.exe"), "/d", "/c", "mklink", "/J", str(link), str(elsewhere)],
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=60, creationflags=NO_WINDOW)
        self.assertEqual(made.returncode, 0, made.stderr)
        for name in ("taken", "linked"):
            with self.subTest(name):
                done = self.scratch.run(self.exe, "--unpack-into", name)
                self.assertEqual(done.returncode, 44)
                self.assertIn(b"is already there", done.stderr)
        self.assertEqual(sorted(path.name for path in taken.iterdir()), ["someone's.txt"])
        self.assertEqual(list(elsewhere.iterdir()), [], "nothing is written through the junction")
        self.assertTrue(link.is_junction() if hasattr(link, "is_junction") else link.exists())

    def test_a_fresh_folder_is_unpacked_into_and_removed_and_a_hooks_name_is_a_plain_one(self):
        done = self.scratch.run(self.exe, "--unpack-into", "fresh")
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertEqual((self.scratch.left(), self.scratch.recorded()), ([], []), "nothing is run by a hook")
        for name in ("..", "a\\b", "", "x" * 65):
            with self.subTest(name):
                self.assertEqual(self.scratch.run(self.exe, "--unpack-into", name).returncode, 42)


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class DllTests(unittest.TestCase):
    """The setup program is downloaded and started from Downloads, where anything else downloaded lies too.
    Windows looks for a DLL that is not one of its KnownDLLs in the program's own folder first, so the first
    thing Main does is tell Windows to load DLLs from System32 alone, and stop when it cannot."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="setup-dlls-"))
        cls.archive, cls.built = build_around(TEST_ENTRIES, cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.scratch = Scratch(self)
        self.here = self.scratch.base / "Downloads"
        self.current = self.scratch.base / "current"
        for folder in (self.here, self.current):
            folder.mkdir()
        self.exe = self.here / self.built.name
        shutil.copy2(self.built, self.exe)
        self.copied = []
        for name in PLANTED:
            source = system32() / name
            if source.is_file():
                for folder in (self.here, self.current):
                    shutil.copy2(source, folder / name)
                self.copied.append(name)

    def test_no_dll_is_loaded_from_its_own_folder_nor_from_the_current_one(self):
        self.assertEqual([name for name in ("bcrypt.dll", "profapi.dll", "CRYPTSP.dll", "CRYPTBASE.dll", "mscoree.dll")
                          if name not in self.copied], [], "Windows' own, there to be copied")
        for current in (self.here, self.current):
            with self.subTest(current=current.name):
                done = self.scratch.run(self.exe, "--loaded-modules", cwd=current)
                self.assertEqual((done.returncode, done.stderr), (0, b""), done.stderr.decode("mbcs", "replace"))
                modules = [Path(module) for module in json.loads(done.stdout.decode("utf-8"))]
                beside = [str(module) for module in modules
                          if same(module.parent, self.here) or same(module.parent, current)]
                self.assertEqual(beside, [str(self.exe)], "the program itself, and no DLL beside it")
                taken = {}
                for module in modules:
                    taken.setdefault(module.name.lower(), []).append(module)
                # .NET's own and CNG's, for the SHA-256, are loaded on any Windows, and the unpacking's: the
                # start was exercised, not skipped.
                for name in ("mscoree.dll", "bcrypt.dll"):
                    self.assertIn(name, taken)
                self.assertTrue(any("compression" in name for name in taken), sorted(taken))
                for name in PLANTED:
                    for module in taken.get(name.lower(), []):
                        self.assertTrue(same(module.parent, system32()), module)
                    self.assertLessEqual(len(taken.get(name.lower(), [])), 1, name)
                self.assertEqual(self.scratch.left(), [], "the hook's folder is removed too")

    def test_a_config_file_beside_it_stops_it(self):
        """.NET reads <program>.config beside a program before Main; this one never comes with one, so one
        beside it is someone else's file, and the program stops, saying so, before it unpacks anything."""
        self.assertEqual(self.scratch.run(self.exe, "--unpack-into", "first").returncode, 0)
        config = Path(str(self.exe) + ".config")
        config.write_text('<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n</configuration>\n',
                          encoding="utf-8")
        for arguments in (("--unpack-into", "second"), ("-SkipStartup",)):
            with self.subTest(arguments):
                done = self.scratch.run(self.exe, *arguments)
                self.assertEqual(done.returncode, 41)
                self.assertIn(("a file named %s is beside it" % config.name).encode("mbcs"), done.stderr)
                self.assertEqual(done.stdout, b"")
        self.assertEqual((self.scratch.left(), self.scratch.recorded()), ([], []))


# An Install.cmd that writes down where it ran, and ends: for the long temporary folder, where cmd.exe's own `dir`
# cannot list what lies past 260 characters. And the two releases' longest entries, 62 and 61 characters.
LONG_ENTRIES = {"Install.cmd": (b"@echo off\r\n>>\"%SETUP_TEST_RECORD%\" echo cd=[%CD%]\r\n"
                                b"exit /b %SETUP_TEST_EXIT%\r\n"),
                "payload/app/src/codex_auto_resume_advanced/codex/wmi_escape.py": b"x = 1\n",
                "payload/app/src/codex_auto_resume/domain/compat_vocabulary.py": b"y = 2\n"}


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class LongTempTests(unittest.TestCase):
    """.NET Framework's file functions and CreateDirectory stop at 260 characters for a file (248 for a folder)
    unless a path is given by its \\\\?\\ name. A temporary folder of about 155 characters was enough to stop
    the setup program with 45 before anything ran; so was running this suite from a long TEMP."""

    def test_a_long_temporary_folder_is_unpacked_into_run_and_removed(self):
        work = Path(tempfile.mkdtemp(prefix="s-"))
        self.addCleanup(shutil.rmtree, work, True)
        _, exe = build_around(LONG_ENTRIES, work)
        scratch = Scratch(self)
        self.addCleanup(shutil.rmtree, "\\\\?\\" + str(scratch.base), True)
        longest = max(len(name) for name in LONG_ENTRIES)
        # The folder it makes is about 240 characters: under 248, where cmd.exe can still be started in it, while
        # its files run past 260. A TEMP that is long already needs no more.
        folder = len(str(scratch.temp)) + len("\\CodexAutoResume-Setup-0123456789abcdef")
        if folder > 246:
            self.skipTest("this test's own temporary folder leaves no room under 248 characters")
        if folder < 239:
            scratch.temp = scratch.temp / ("t" * (240 - folder - 1))
            scratch.temp.mkdir()
        self.assertGreater(len(str(scratch.temp)) + 39 + 1 + longest, 260, "the entries reach past 260 characters")
        done = scratch.run(exe, exit_code=7)
        self.assertEqual(done.returncode, 7, done.stderr)
        lines = scratch.recorded()
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(Path(lines[0][len("cd=["):-1]).name, FOLDER)
        self.assertEqual(scratch.left(), [], "the folder is removed afterwards")


class _Coord(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD),
                ("dwThreadId", wintypes.DWORD)]


def _kernel32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreatePseudoConsole.argtypes = [_Coord, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD,
                                        ctypes.POINTER(ctypes.c_void_p)]
    k32.CreatePseudoConsole.restype = ctypes.c_long
    k32.ClosePseudoConsole.argtypes = [ctypes.c_void_p]
    k32.ClosePseudoConsole.restype = None
    k32.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p,
                               wintypes.DWORD]
    k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                                      ctypes.POINTER(ctypes.c_size_t)]
    k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                              ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                   wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                   ctypes.c_void_p, ctypes.POINTER(_ProcessInformation)]
    k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                             ctypes.c_void_p]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return k32


def run_in_a_console_then_close_it(exe: Path, environment: dict, cwd: Path, closed_when) -> int:
    """Starts `exe` in a pseudo-console - a console with no window - and closes that console once `closed_when()`
    is true, which sends every program in it the CTRL_CLOSE_EVENT the X of a console window sends. Its exit code."""
    k32 = _kernel32()
    in_read, in_write, out_read, out_write = (wintypes.HANDLE(), wintypes.HANDLE(), wintypes.HANDLE(),
                                              wintypes.HANDLE())
    assert k32.CreatePipe(ctypes.byref(in_read), ctypes.byref(in_write), None, 0)
    assert k32.CreatePipe(ctypes.byref(out_read), ctypes.byref(out_write), None, 0)
    console = ctypes.c_void_p()
    made = k32.CreatePseudoConsole(_Coord(120, 30), in_read, out_write, 0, ctypes.byref(console))
    assert made == 0, hex(made & 0xFFFFFFFF)
    k32.CloseHandle(in_read)
    k32.CloseHandle(out_write)

    def drain():
        # The console's output has to be read, or it stops the programs writing to it.
        buffer = ctypes.create_string_buffer(4096)
        got = wintypes.DWORD()
        while k32.ReadFile(out_read, buffer, 4096, ctypes.byref(got), None) and got.value:
            pass

    threading.Thread(target=drain, daemon=True).start()
    size = ctypes.c_size_t()
    k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    assert k32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size))
    assert k32.UpdateProcThreadAttribute(attributes, 0, 0x00020016, console, ctypes.sizeof(ctypes.c_void_p),
                                         None, None)   # PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE
    startup = _StartupInfoEx()
    startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoEx)
    # STARTF_USESTDHANDLES with none given: the program's standard handles are the pseudo-console's, never the
    # ones this test's own process may have redirected.
    startup.StartupInfo.dwFlags = 0x00000100
    startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
    block = ctypes.create_unicode_buffer("".join("%s=%s\0" % pair for pair in sorted(environment.items())) + "\0")
    info = _ProcessInformation()
    line = ctypes.create_unicode_buffer('"%s"' % exe)
    # EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT: the pseudo-console, and this environment.
    assert k32.CreateProcessW(None, line, None, None, False, 0x00080000 | 0x00000400, block, str(cwd),
                              ctypes.byref(startup), ctypes.byref(info)), ctypes.get_last_error()
    try:
        deadline = time.monotonic() + 60
        while not closed_when() and time.monotonic() < deadline:
            time.sleep(0.2)
        closer = threading.Thread(target=k32.ClosePseudoConsole, args=(console,), daemon=True)
        closer.start()
        closer.join(30)
        if k32.WaitForSingleObject(info.hProcess, 30000) != 0:
            k32.TerminateProcess(info.hProcess, 1)
            k32.WaitForSingleObject(info.hProcess, 5000)
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        k32.CloseHandle(info.hProcess)
        k32.CloseHandle(info.hThread)
        k32.DeleteProcThreadAttributeList(attributes)
        k32.CloseHandle(in_write)


# An Install.cmd that says it started, and then waits as the real one's last "Press any key" does.
WAITING_ENTRIES = {"Install.cmd": (b"@echo off\r\n>>\"%SETUP_TEST_RECORD%\" echo started\r\n"
                                   b"\"%SystemRoot%\\System32\\PING.EXE\" -n 40 127.0.0.1 >nul\r\n"
                                   b">>\"%SETUP_TEST_RECORD%\" echo finished\r\nexit /b 0\r\n"),
                   "install/install.ps1": b"# never run\r\n",
                   "payload/app/src/codex_auto_resume/__init__.py": b"",
                   "payload/runtime/python.exe": b"MZ not a program"}


def _pseudo_consoles() -> bool:
    try:
        return hasattr(ctypes.WinDLL("kernel32"), "CreatePseudoConsole")
    except (AttributeError, OSError):
        return False


@unittest.skipUnless(CSC.is_file() and _pseudo_consoles(), "the in-box C# compiler and pseudo-consoles are not available")
class CloseTests(unittest.TestCase):
    """Closing the console window - most often at Install.cmd's last "Press any key" - used to end the setup
    program before its finally ran: the whole unpacked archive stayed in %TEMP%, about 27 MB under a new name
    each time, which nothing removes later."""

    def test_the_folder_is_removed_when_the_console_window_is_closed_while_install_cmd_runs(self):
        work = Path(tempfile.mkdtemp(prefix="s-"))
        self.addCleanup(shutil.rmtree, work, True)
        _, exe = build_around(WAITING_ENTRIES, work)
        scratch = Scratch(self)
        environment = dict(os.environ, TEMP=str(scratch.temp), TMP=str(scratch.temp),
                           SETUP_TEST_RECORD=str(scratch.record))
        seen = []

        def started():
            if scratch.recorded() == ["started"]:
                seen.extend(scratch.left())
                return True
            return False

        code = run_in_a_console_then_close_it(exe, environment, scratch.base, started)
        self.assertEqual(len(seen), 1, "Install.cmd ran in a folder of its own: %s" % seen)
        self.assertRegex(seen[0], FOLDER)
        self.assertEqual(scratch.recorded(), ["started"], "the close ended Install.cmd before it finished")
        self.assertNotEqual(code, 0, "the program was ended by the close")
        self.assertEqual(scratch.left(), [], "the unpacked archive outlived the console window")


def method(name: str) -> str:
    """The text of a method of Setup.cs, from its signature to its closing brace."""
    found = re.search(r"\n(\s+)(?:public |internal |private )?static \w+(?:<\w+>)? %s\(" % re.escape(name), SOURCE)
    if not found:
        raise AssertionError("Setup.cs has no method %s" % name)
    end = SOURCE.index("\n" + found.group(1) + "}\n", found.end())
    return SOURCE[found.start():end]


class SourceTests(unittest.TestCase):
    def test_the_first_thing_main_does_is_take_dlls_from_system32_alone_or_stop(self):
        main = method("Main")
        body = main[main.index("{") + 1:].strip()
        self.assertTrue(body.startswith("if (!Dlls.FromSystem32Only())"), body[:80])
        self.assertLess(main.index("Dlls.FromSystem32Only()"), main.index("Dlls.ConfigBeside()"))
        self.assertLess(main.index("Dlls.ConfigBeside()"), main.index("Started("))
        self.assertIn("\n[assembly: DefaultDllImportSearchPaths(DllImportSearchPath.System32)]\n",
                      SOURCE.replace("\r\n", "\n"))
        self.assertEqual(SOURCE.count("DefaultDllImportSearchPaths"), 1)
        self.assertIn("const uint LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x800;", SOURCE)
        self.assertIn("return SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32) && SetDllDirectory(\"\");",
                      SOURCE)
        self.assertIn("catch (EntryPointNotFoundException)", SOURCE)

    def test_it_calls_into_kernel32_alone_by_exact_names(self):
        imports = re.findall(r"\[DllImport\(([^\]]*)\)\]", SOURCE)
        self.assertEqual(len(imports), 7)
        for declaration in imports:
            with self.subTest(declaration):
                self.assertTrue(declaration.startswith('"kernel32.dll"'))
                self.assertIn("ExactSpelling = true", declaration)
                self.assertEqual("CharSet" in declaration, "EntryPoint" in declaration)

    def test_it_reaches_no_network_no_registry_and_starts_only_cmd_from_system32(self):
        for forbidden in (r"System\.Net", r"WebClient", r"WebRequest", r"Socket", r"Microsoft\.Win32\.Registry",
                          r"RegistryKey", r"runas", r"(?<!Use)ShellExecute", r"CreateProcess", r"UseShellExecute = true"):
            with self.subTest(forbidden):
                self.assertIsNone(re.search(forbidden, SOURCE))
        self.assertIn("start.UseShellExecute = false;", SOURCE)
        self.assertEqual(make_setup.REFERENCES, ("System.dll", "System.IO.Compression.dll"))
        self.assertEqual(SOURCE.count("Process.Start("), 1)
        self.assertEqual(SOURCE.count("new ProcessStartInfo("), 1)
        self.assertIn('new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "cmd.exe"))', SOURCE)
        install = method("Install")
        self.assertIn('start.Arguments = "/d /s /c \\"\\"" + script + "\\""', install)
        self.assertIn("start.WorkingDirectory = folder;", install)
        self.assertIn('string script = Path.Combine(folder, "Install.cmd");', install)

    def test_its_manifest_asks_for_no_elevation(self):
        manifest = (ROOT / make_setup.MANIFEST).read_text(encoding="utf-8")
        self.assertIn('<requestedExecutionLevel level="asInvoker" uiAccess="false" />', manifest)
        self.assertEqual(make_setup.manifest_bytes().count(b"\r\n"), make_setup.manifest_bytes().count(b"\n"))

    def test_its_own_exit_codes_are_apart_from_install_cmds_and_from_each_other(self):
        codes = [int(value) for value in re.findall(r"internal const int \w+ = (\d+);", SOURCE)]
        self.assertEqual(len(codes), 7)
        self.assertEqual(len(set(codes)), len(codes))
        self.assertFalse(set(codes) & {0, 1, 14}, "Install.cmd passes back 0, 1 and 14")
        installer = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r"(?m)exit (\d+)", installer)), {"0", "1"})
        self.assertIn("$EDITION_CHANGE_REFUSED = 14", installer)

    def test_every_file_it_writes_or_removes_goes_by_its_long_name(self):
        into = method("Into")
        self.assertIn("string written = LongName.Of(target);", into)
        self.assertIn("new FileStream(written,", into)
        self.assertNotIn("new FileStream(target,", into)
        self.assertIn("CreateDirectory(LongName.Of(path), IntPtr.Zero)", SOURCE)
        self.assertIn("CreateFile(LongName.Of(path),", SOURCE)
        self.assertIn("new DirectoryInfo(LongName.Of(Path))", SOURCE)
        self.assertIn('[assembly: TargetFramework(".NETFramework,Version=v4.8"', make_setup.version_source(
            "standard", "9.9.9"), "a \\\\?\\ name needs .NET Framework 4.6.2's path handling, not 4.0's")

    def test_a_closed_console_window_is_heard_and_the_folder_removed_first(self):
        self.assertIn("SetConsoleCtrlHandler(heard, true);", SOURCE)
        self.assertIn("static readonly Handler heard = Heard;", SOURCE, "the handler outlives the collector")
        started = method("Started")
        self.assertLess(started.index("Closing.Watch();"), started.index("Folder.Fresh("))
        cleanup = started[started.index("finally"):]
        self.assertLess(cleanup.index("folder.Remove()"), cleanup.index("Closing.Done();"))

    def test_it_unpacks_the_bytes_it_checked(self):
        started = method("Started")
        self.assertLess(started.index("Carried.Read()"), started.index("Folder.Fresh("))
        self.assertLess(started.index("Folder.Fresh("), started.index("Unpacking.Into(archive, folder.Path)"))
        self.assertIn("finally", started)
        self.assertIn("folder.Remove()", started[started.index("finally"):])


class ReleaseTests(unittest.TestCase):
    def test_make_release_builds_it_from_the_archive_it_has_just_written(self):
        source = (ROOT / "build" / "make_release.py").read_text(encoding="utf-8")
        body = source[source.index("def main("):]
        order = [body.index(marker) for marker in ("target = write_archive(", "digest = write_sidecar(target)",
                                                   "setup = build_setup(target, edition, release)",
                                                   "setup_digest = write_sidecar(setup)")]
        self.assertEqual(order, sorted(order))
        self.assertIn("return make_setup.build(archive, archive.parent, edition, release)", source)

    def test_the_workflow_checks_each_one_before_the_audit_and_keeps_and_publishes_it(self):
        order = [WORKFLOW.index(marker) for marker in (
            "run: python build/make_release.py --edition advanced",
            "run: python build/make_setup.py --check --edition standard",
            "run: python build/make_setup.py --check --edition advanced",
            "run: python build/edition_audit.py",
            "- name: Keep the archives even when nothing is published")]
        self.assertEqual(order, sorted(order))
        self.assertIn("            build/dist/*.exe\n", WORKFLOW)
        for edition, variable in (("standard", "STANDARD_SETUP"), ("advanced", "ADVANCED_SETUP")):
            with self.subTest(edition):
                name = make_setup.setup_name(edition, "${{ needs.build.outputs.version }}")
                self.assertIn("      %s: dist/%s\n" % (variable, name), WORKFLOW)

    def test_the_names_are_apart_from_every_archive_name(self):
        templates = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
        for template in (templates["archive"], templates["advanced"]["archive"]):
            for edition in make_setup.EDITIONS:
                self.assertNotEqual(template, make_setup.NAMES[edition])
                self.assertTrue(make_setup.NAMES[edition].endswith("-v{version}.exe"))


RELEASES = "https://github.com/songyb111-gachon/codex-auto-resume-windows/releases"


class DocsTests(unittest.TestCase):
    """Where the install instructions send a person for the setup program."""

    def test_the_setup_programs_route_names_where_one_is_found_while_no_release_has_one(self):
        """A pre-release is published with --latest=false, so releases/latest stays on the newest release - one
        from before the setup programs, until a release that carries one ships. A route that pointed there alone
        sent everyone to a file that was not there; it names the releases page, where the pre-releases are, too."""
        headings = {"README.md": "### With the setup program", "README.ko.md": "### 설치 파일로 설치",
                    "docs/GUIDE.md": "### With the setup program", "docs/GUIDE.ko.md": "### 설치 파일로 설치"}
        for name, heading in headings.items():
            if not (ROOT / name).is_file():
                continue
            with self.subTest(name):
                text = (ROOT / name).read_text(encoding="utf-8")
                section = text[text.index(heading):]
                section = section[:section.index("\n### ", len(heading))]
                self.assertIn("](%s)" % RELEASES, section, "the releases page, where a pre-release is listed")
                if not name.endswith(".ko.md"):
                    self.assertIn("v0.6.11", section, "the release the setup programs start with")

    def test_the_recommended_route_comes_first(self):
        """The owner, 2026-10-02: the recommended route belongs at the top. The setup program's route, new in
        v0.6.11, had been put above it."""
        installs = {"README.md": ("## Install", "### From Codex (recommended)"),
                    "README.ko.md": ("## 설치", "### Codex에서 설치 (권장)"),
                    "docs/GUIDE.md": ("## Install", "### From Codex (recommended)"),
                    "docs/GUIDE.ko.md": ("## 설치", "### Codex에서 설치 (권장)")}
        for name, (install, recommended) in installs.items():
            if not (ROOT / name).is_file():
                continue
            with self.subTest(name):
                text = (ROOT / name).read_text(encoding="utf-8")
                start = text.index("\n%s\n" % install)
                first = text.index("\n### ", start)
                self.assertEqual(text[first + 1:first + 1 + len(recommended)], recommended)


if __name__ == "__main__":
    unittest.main()
