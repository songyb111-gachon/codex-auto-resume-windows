"""The one-file installers: build/make_setup.py and build/setup/Setup.cs.

Each release ships CodexAutoResume-Setup-v<version>.exe and CodexAutoResume-Advanced-Setup-v<version>.exe: the
edition's release ZIP, byte for byte, inside a small program that unpacks it into a new folder of its own and
runs that archive's Install.cmd there. What is held here:

* BuildTests - the program carries exactly the archive it was built around, with its SHA-256; two builds of
  one archive are one file; it is a Windows program (v0.6.16: a window, never a console) for x64 that asks for
  no elevation, and says its edition.
* HandOffTests - built around a TEST archive whose Install.cmd only writes down what it was given, never the
  real installer, and run with -Silent, as winget runs it (without -Silent it is the installer window,
  tests/test_installer_window.py): it runs that Install.cmd by its full path, in the folder it unpacked
  everything into, with the arguments it was given, passes its exit code and its output back and removes the
  folder; it refuses an argument cmd would read as more than a word, damaged bytes, an entry that climbs out of
  its folder, and a folder - or a junction - that is already there.
* DllTests - copies of Windows' own DLLs beside it and in the current folder, as a DLL of one of their names
  could be waiting in Downloads: none is loaded from either (the --loaded-modules hook), and a .config beside
  it stops it.
* LongTempTests - a temporary folder long enough that the release's own entries run past 260 characters below
  it: everything is unpacked, run and removed all the same.
* SilentTests - with -Silent, a stop ends the program by itself with its own code.
* SourceTests, ReleaseTests, DocsTests - what the source, the release build and workflow, and the install
  instructions have to say.

Every run points TEMP and TMP at a folder of the test's own, so nothing is unpacked anywhere else, and every
child is started with CREATE_NO_WINDOW and no input. Until v0.6.16 the program was a console program, and
CloseTests closed a pseudo-console on it while Install.cmd ran: a Windows program has no console window for a
person to close, so they went with it; the window is not closed while Install.cmd runs (InstallerWindow).
"""
from __future__ import annotations

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
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)
_TESTS = str(Path(__file__).resolve().parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import languages  # noqa: E402
import make_setup  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SOURCE = (ROOT / make_setup.SOURCE).read_text(encoding="utf-8")
WINDOW = (ROOT / make_setup.WINDOW).read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

# What the test archive's Install.cmd writes down, one line each, and the code it ends with - both through the
# environment the setup program passes on, so one build serves every run.
RECORDER = (
    "@echo off\r\n"
    ">>\"%SETUP_TEST_RECORD%\" echo args=[%*]\r\n"
    ">>\"%SETUP_TEST_RECORD%\" echo cd=[%CD%]\r\n"
    ">>\"%SETUP_TEST_RECORD%\" echo script=[%~f0]\r\n"
    "dir /s /b /a-d \"%~dp0\" >>\"%SETUP_TEST_RECORD%\"\r\n"
    "echo said by Install.cmd\r\n"
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
        """Runs it with -Silent added, unless a hook or -Silent is there already: without it, the program is the
        installer window, which these tests never open."""
        if not (arguments and arguments[0].startswith("--")) and "-Silent" not in arguments:
            arguments = arguments + ("-Silent",)
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

    def test_it_is_a_windows_program_for_x64_that_asks_for_no_elevation(self):
        """v0.6.16: the Windows subsystem, so a double-click opens the installer window and no console window at
        all - a console program gets one from Windows before its first line runs."""
        pe = struct.unpack_from("<I", self.image, 0x3C)[0]
        self.assertEqual(struct.unpack_from("<H", self.image, pe + 4)[0], 0x8664, "x64")
        self.assertEqual(struct.unpack_from("<H", self.image, pe + 24 + 68)[0], 2, "the Windows subsystem")
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
        self.assertEqual(lines[0], "args=[-SkipStartup -AllowEditionChange -Silent]")
        folder = Path(lines[1][len("cd=["):-1])
        self.assertTrue(same(folder.parent, self.scratch.temp), folder)
        self.assertRegex(folder.name, FOLDER)
        self.assertEqual(lines[2], "script=[%s]" % (folder / "Install.cmd"))
        unpacked = sorted(Path(line).relative_to(folder).as_posix() for line in lines[3:])
        self.assertEqual(unpacked, sorted(TEST_ENTRIES))
        self.assertEqual(self.scratch.left(), [], "the folder is removed afterwards")
        self.assertIn(("unpacking %s into %s" % (self.archive.name, folder)).encode("mbcs"), done.stdout)
        self.assertIn(b"said by Install.cmd\r\n", done.stdout, "what Install.cmd prints is passed on")

    def test_install_cmds_exit_code_is_its_own(self):
        for code in (0, 1, 14):
            with self.subTest(code):
                self.assertEqual(self.scratch.run(self.exe, exit_code=code).returncode, code)
        self.assertEqual(self.scratch.left(), [])
        self.assertEqual(sum(line.startswith("args=[-Silent]") for line in self.scratch.recorded()), 3)

    def test_the_silent_switch_is_passed_on_like_any_other(self):
        done = self.scratch.run(self.exe, "-SkipStartup", "-Silent")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertEqual(self.scratch.recorded()[0], "args=[-SkipStartup -Silent]")

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


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class SilentTests(unittest.TestCase):
    """With -Silent, a stop waits for no one: a damaged copy says why on its error output and ends by itself with
    its own code, opening no window. Without it the stop is said in a message box (Say.Stopped), which is a
    window, and these tests open none (SourceTests holds it)."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="setup-silent-"))
        _, exe = build_around(TEST_ENTRIES, cls.work)
        cls.exe = exe
        image = bytearray(exe.read_bytes())
        start, end = make_setup.carried_span(bytes(image))
        image[(start + end) // 2] ^= 0x01
        cls.damaged = cls.work / "damaged.exe"
        cls.damaged.write_bytes(bytes(image))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_with_the_switch_it_ends_by_itself_with_its_own_code(self):
        done = Scratch(self).run(self.damaged, "-Silent")
        self.assertEqual(done.returncode, 43)
        self.assertIn(b"its SHA-256 differs", done.stderr)

    def test_the_guides_way_to_run_it_from_powershell_waits_and_gives_the_exit_code(self):
        """The setup program is a Windows program (/target:winexe), so `& Setup.exe -Silent` in PowerShell returns
        at once with no $LASTEXITCODE, while the guide promised it prints and ends with its code. The guide now
        gives the waiting form; it is run here as written, in PowerShell, around a test archive whose Install.cmd
        says a line and ends with 7 - and the bare form beside it, which does not wait."""
        exe = self.exe
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        # The generated ko branch keeps the Korean guide as docs/GUIDE.md, with the same command in it.
        documents = {"docs/GUIDE.md": True, "docs/GUIDE.ko.md": True}
        forms = {}
        for name, present in documents.items():
            if present and (ROOT / name).is_file():
                spans = re.findall(r"`(cmd /c \.\\CodexAutoResume-Setup-vX\.Y\.Z\.exe -Silent)`",
                                   (ROOT / name).read_text(encoding="utf-8"))
                self.assertEqual(len(spans), 1, "%s gives the form PowerShell waits with" % name)
                forms[name] = spans[0]
        self.assertTrue(forms)
        forms["the bare form"] = "& .\\CodexAutoResume-Setup-vX.Y.Z.exe -Silent"
        for name, form in forms.items():
            with self.subTest(name):
                scratch = Scratch(self)
                shutil.copyfile(exe, scratch.base / "CodexAutoResume-Setup-vX.Y.Z.exe")
                environment = dict(os.environ, TEMP=str(scratch.temp), TMP=str(scratch.temp),
                                   SETUP_TEST_RECORD=str(scratch.record), SETUP_TEST_EXIT="7")
                done = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command",
                                       form + "; 'code=' + $LASTEXITCODE"], capture_output=True, stdin=subprocess.DEVNULL,
                                      cwd=str(scratch.base), env=environment, timeout=180, creationflags=NO_WINDOW)
                out = done.stdout.decode("utf-8", "replace")
                if name == "the bare form":
                    self.assertNotIn("code=7", out, "PowerShell waited for a Windows program after all")
                else:
                    self.assertIn("said by Install.cmd", out)
                    self.assertIn("code=7", out)


def method(name: str) -> str:
    """The text of a method of Setup.cs, from its signature to its closing brace."""
    found = re.search(r"\n([ \t]+)(?:public |internal |private )?static \w+(?:<\w+>)? %s\(" % re.escape(name), SOURCE)
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
        """Setup.cs starts cmd.exe and nothing else, with no window of its own. The window it shows
        (build/setup/SetupWindow.cs) starts one more program, once it has finished and only where the person left
        "Open the Dashboard" on: the installation's Dashboard, by its full path in the home it has just installed.
        The window reads Windows' theme and text size from the registry, as the settings window does
        (gui/SoftTheme.cs), and writes nothing there; the guide is a link the person follows in their browser."""
        for forbidden in (r"System\.Net", r"WebClient", r"WebRequest", r"Socket", r"Microsoft\.Win32\.Registry",
                          r"RegistryKey", r"runas", r"(?<!Use)ShellExecute", r"CreateProcess", r"UseShellExecute = true"):
            for name, text in (("Setup.cs", SOURCE), ("SetupWindow.cs", WINDOW)):
                with self.subTest(forbidden, file=name):
                    self.assertIsNone(re.search(forbidden, text))
        self.assertIn("start.UseShellExecute = false;", SOURCE)
        self.assertIn("start.CreateNoWindow = true;", method("Install"))
        self.assertEqual(make_setup.REFERENCES, ("System.dll", "System.IO.Compression.dll", "System.Drawing.dll",
                                                 "System.Windows.Forms.dll"))
        self.assertEqual(SOURCE.count("Process.Start("), 1)
        self.assertEqual(SOURCE.count("new ProcessStartInfo("), 1)
        self.assertIn('new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "cmd.exe"))', SOURCE)
        install = method("Install")
        self.assertIn('start.Arguments = "/d /s /c \\"\\"" + script + "\\""', install)
        self.assertIn("start.WorkingDirectory = folder;", install)
        self.assertIn('string script = Path.Combine(folder, "Install.cmd");', install)
        # The Dashboard is started in front by HostApp.StartInFront (v0.6.17, gui/HostApp.cs), with no shell.
        self.assertEqual(WINDOW.count("Process.Start("), 0)
        self.assertIn("HostApp.StartInFront(exe, null, home);", WINDOW)
        self.assertIn("string exe = Path.Combine(home, Dashboard);", WINDOW)
        self.assertIn('internal const string Dashboard = "CodexAutoResumeSettings.exe";', WINDOW)

    def test_without_the_switch_or_a_hook_it_is_the_window_and_a_stop_is_a_message_box(self):
        started = method("Started")
        self.assertLess(started.index("if (wait)"), started.index("return Windowed(arguments);"))
        self.assertLess(started.index("return Windowed(arguments);"), started.index("Carried.Read()"))
        stopped = method("Stopped")
        self.assertIn("else if (wait && processes == 0)", stopped)
        self.assertIn("SetupWindow.Tell(text);", stopped)
        self.assertIn("[STAThread]\n        static int Main(", SOURCE.replace("\r\n", "\n"))

    def test_every_stop_asks_whether_it_may_wait_and_silent_says_no(self):
        # Each Say.Stopped is told, not left to wait: by a hook or -Silent, which nothing else is.
        stops = re.findall(r"Say\.Stopped\([^;]*?\);", SOURCE)
        self.assertGreaterEqual(len(stops), 7)
        for stop in stops:
            self.assertTrue(stop[:-2].endswith(("wait", "Waits(arguments)", "!Passed.Silent(arguments)")), stop)
        self.assertIn("return !Hook(arguments) && !Passed.Silent(arguments);", SOURCE)
        self.assertIn('string.Equals(argument, "-Silent", StringComparison.OrdinalIgnoreCase)', SOURCE)

    def test_its_manifest_asks_for_no_elevation(self):
        manifest = (ROOT / make_setup.MANIFEST).read_text(encoding="utf-8")
        self.assertIn('<requestedExecutionLevel level="asInvoker" uiAccess="false" />', manifest)
        self.assertEqual(make_setup.manifest_bytes().count(b"\r\n"), make_setup.manifest_bytes().count(b"\n"))

    def test_its_own_exit_codes_are_apart_from_install_cmds_and_from_each_other(self):
        codes = [int(value) for value in re.findall(r"internal const int \w+ = (\d+);", SOURCE)]
        self.assertEqual(len(codes), 8, "and since v0.6.16 Cancelled, the window closed before anything ran")
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

    def test_no_console_handler_is_added_or_taken_away_after_the_one_that_waits_for_the_folder(self):
        """Windows holds its list of console handlers while one of them runs, and Closing's runs until the folder
        is removed. Install added Console.CancelKeyPress's handler for Ctrl+C and took it away as Install.cmd
        ended: when the window closed at that moment, taking it away waited for Closing's handler, which waited
        for the folder, until Windows ended the program with the folder there (CloseTests, on GitHub and here).
        Ctrl+C is answered by Closing's handler instead, from Install.cmd's start on."""
        code = "\n".join(line for line in SOURCE.splitlines() if not line.lstrip().startswith("//"))
        self.assertNotIn("CancelKeyPress", code)
        self.assertEqual(len(re.findall(r"\bSetConsoleCtrlHandler\(", code)), 2, "its declaration and Watch's call")
        heard = method("Heard")
        self.assertLess(heard.index("return outliveCtrlC;"), heard.index("cleaned.WaitOne("))
        install = method("Install")
        self.assertLess(install.index("Closing.OutliveCtrlC();"), install.index("Process.Start("))

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
LATEST = RELEASES + "/latest"
# The first release published with the setup programs.
SETUP_SINCE = (0, 6, 11)


def _latest_release() -> tuple:
    """The release releases/latest answers with once this tree is published: the manifest's version when it is a
    release, and otherwise the newest release whose digest is pinned. A pre-release is published with
    --latest=false, so it never is the latest, and a release is pinned only once it is published."""
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    pinned = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))["sha256"]
    releases = [version for version, digest in pinned.items() if digest] + ([manifest] if "-" not in manifest else [])
    return max(tuple(int(part) for part in version.split(".")) for version in releases)


def _install_documents(english, korean, readme=None):
    """Each document with install instructions here, with what it is written in: dev has both languages, main
    English only, and the generated ko branch has the Korean text under the English names. The README is the
    short page (from the v0.6.16 final the setup program leads it), the guide keeps its own order of routes, so
    `readme` gives the README's (English, Korean) if they differ from the guide's."""
    on_ko = languages.generated_ko_branch()
    documents = {"README.md": on_ko, "README.ko.md": True, "docs/GUIDE.md": on_ko, "docs/GUIDE.ko.md": True}
    found = {}
    for name, is_korean in documents.items():
        if (ROOT / name).is_file():
            own = readme if readme is not None and name.startswith("README") else (english, korean)
            found[name] = ((own[1] if is_korean else own[0]), is_korean)
    return found


class DocsTests(unittest.TestCase):
    """Where the install instructions send a person for the setup program."""

    def test_the_setup_programs_route_points_at_the_latest_release_and_it_carries_one(self):
        """The setup programs start with v0.6.11. Until it was out they were only on its pre-releases, which are
        published with --latest=false, so releases/latest stayed on v0.6.10, which has none: a route that pointed
        there sent everyone to a file that was not there, and it named the releases page instead. From v0.6.11
        the latest release carries them, and the route points there again - only while that holds. So the release
        releases/latest answers with for this tree has to be one with setup programs, and the route may name no
        other release page: the list, or a tag, is a second place to look, and a tag can be one without."""
        latest = _latest_release()
        self.assertGreaterEqual(latest, SETUP_SINCE, "releases/latest answers with v%s, which has no setup program"
                                % ".".join(map(str, latest)))
        for name, (heading, korean) in _install_documents(
                "### With the setup program", "### 설치 마법사로 설치",
                readme=("### With the setup program", "### 설치 마법사로 설치")).items():
            with self.subTest(name):
                text = (ROOT / name).read_text(encoding="utf-8")
                section = text[text.index(heading):]
                section = section[:section.index("\n### ", len(heading))]
                links = re.findall(r"\]\((%s[^)\s]*)\)" % re.escape(RELEASES), section)
                if name.startswith("README"):
                    # The README's section holds the setup program's paragraph and, folded under it, the plugin
                    # and the archive routes, each of which may link the release page: every link is the latest
                    # release, and there is at least one.
                    self.assertTrue(links)
                    self.assertEqual(set(links), {LATEST},
                                     "the latest release, which carries the setup programs, and no other release page")
                else:
                    self.assertEqual(links, [LATEST],
                                     "the latest release, which carries the setup programs, and no other release page")
                if not korean:
                    # The guide names the release the setup programs start with; the README says instead where
                    # the setup program's link is, on every release page, which the check above keeps true.
                    self.assertIn("at the top of every" if name.startswith("README") else "from v0.6.11 on",
                                  section, "where the setup program is, and since which release")

    def test_the_recommended_route_comes_first(self):
        """The owner, 2026-10-02: the recommended route belongs at the top. From the v0.6.16 final (owner, 2026-10-16)
        it is the setup program's in the README, and the guide leads with it too (the docs review, 2026-10-22: the
        two listed different routes first); the plugin and the archive routes follow it."""
        for name, ((install, recommended), _) in _install_documents(
                ("## Install", "### With the setup program (recommended)"), ("## 설치", "### 설치 마법사로 설치 (권장)"),
                readme=(("## Install", "### With the setup program (recommended)"),
                        ("## 설치", "### 설치 마법사로 설치 (권장)"))).items():
            with self.subTest(name):
                text = (ROOT / name).read_text(encoding="utf-8")
                start = text.index("\n%s\n" % install)
                first = text.index("\n### ", start)
                self.assertEqual(text[first + 1:first + 1 + len(recommended)], recommended)


if __name__ == "__main__":
    unittest.main()
