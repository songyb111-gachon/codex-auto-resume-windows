"""The advanced window is the standard one with the overlay compiled after it, and the standard
window holds nothing of the points the overlay plugs into.

Core C# declares `partial void` methods on SettingsForm (gui/Dashboard.cs) where the advanced
window joins, and calls them. C# removes a partial method that has no body, calls included, so
the standard executable is meant to be the very file it would be without the declarations and the
calls. That is measured here with the in-box compiler rather than taken from the language's
specification: once on a program small enough to read, and once on the window itself, built by
build/make_gui.ps1 from a copy of its sources and from the same copy with every point cut out.

The advanced window is built from that copy too, with a probe listed on its overlay in place of
the empty real one: the probe's names and strings are in the advanced executable, none of them are
in the standard one, and build/edition_audit.py's check (d) reads the two the same way.

GUI test module: compiles real executables, so it runs on its own.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # guiscan lives next to this file
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import edition_audit  # noqa: E402
import guiscan  # noqa: E402
import normalize_pe  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
WINDOW = "CodexAutoResumeSettings.exe"
LAUNCHER = "codex-auto-resume-mcp.exe"
# The points core declares, one per line and with no body, and each call a statement of its own.
DECLARATION = re.compile(r"^\s*partial void (\w+)\(([^)]*)\)\s*;\s*$")

PROGRAM = """
using System;
partial class Form {
    %s
    public int Run() { %s return 1; }
    static int Main() { return new Form().Run(); }
}
"""
BODY = """
using System;
partial class Form {
    partial void Hook(string text) { Console.WriteLine("given a body " + text); }
}
"""
PROBE = """// ADVANCED-EDITION-CODE: a probe this test compiles into an advanced window, never a real source.
namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        partial void DashboardBuilt() { EditionProbe.Seen = "the advanced window was built"; }
        partial void SnapshotApplied(System.Collections.Generic.Dictionary<string, object> reply)
        {
            EditionProbe.Seen = "a snapshot reached the advanced window";
        }
    }

    internal static class EditionProbe { internal static string Seen; }
}
"""


def points() -> dict:
    """Every `partial void` the standard window declares, by name, with where it is declared."""
    found = {}
    for name in guiscan.manifest():
        for line in guiscan.read(name).splitlines():
            match = DECLARATION.match(line)
            if match:
                found[match.group(1)] = name
    return found


def compile_program(folder: Path, *sources: str) -> bytes:
    folder.mkdir(parents=True)
    paths = []
    for index, text in enumerate(sources):
        path = folder / ("part%d.cs" % index)
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    exe = folder / "program.exe"
    subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/optimize+", "/out:" + str(exe),
                    *paths], check=True, capture_output=True, timeout=120)
    return normalize_pe.normalise(exe.read_bytes())


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class PartialMethodTests(unittest.TestCase):
    """What the compiler does with a partial method, on a program small enough to read."""

    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix="edition-partial-"))
        declared = PROGRAM % ('partial void Hook(string text);', 'Hook("from the call");')
        cls.declared = compile_program(cls.folder / "declared", declared)
        cls.neither = compile_program(cls.folder / "neither", PROGRAM % ("", ""))
        cls.bodied = compile_program(cls.folder / "bodied", declared, BODY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_a_partial_method_with_no_body_leaves_no_trace(self):
        """Not a no-op left in: the same bytes as a program that never had it."""
        self.assertEqual(self.declared, self.neither)
        self.assertNotIn(b"Hook", self.declared)
        self.assertNotIn("from the call".encode("utf-16-le"), self.declared)

    def test_a_body_compiled_beside_it_brings_the_method_and_the_call_in(self):
        self.assertNotEqual(self.bodied, self.declared)
        self.assertIn(b"Hook", self.bodied)
        self.assertIn("given a body ".encode("utf-16-le"), self.bodied)
        self.assertIn("from the call".encode("utf-16-le"), self.bodied)


class PointTests(unittest.TestCase):
    """The points as the standard sources declare them: bodiless, where the window is one class."""

    def test_the_standard_window_declares_the_points_and_gives_none_a_body(self):
        found = points()
        self.assertEqual(found, {"DashboardBuilt": "gui/Dashboard.cs", "SnapshotApplied": "gui/Dashboard.cs"})
        # No other shape of partial method: one with a body in a standard source would be
        # compiled into the standard window, which is the whole thing this rules out.
        whole = guiscan.whole()
        self.assertEqual(len(re.findall(r"^[ \t]*partial[ \t]+void\b", whole, re.M)), len(found))

    def test_each_call_is_a_statement_of_its_own(self):
        """So cutting a point out, below, is cutting whole lines, and nothing else changes."""
        calls, declared = {}, points()
        for name in guiscan.manifest():
            for line in guiscan.read(name).splitlines():
                for point in declared:
                    if re.search(r"\b%s\(" % point, line) and not DECLARATION.match(line):
                        self.assertRegex(line, r"^\s*%s\([^;]*\);\s*$" % point)
                        calls[point] = calls.get(point, 0) + 1
        self.assertEqual(calls, {"DashboardBuilt": 1, "SnapshotApplied": 2})


def copy_window(target: Path) -> Path:
    """What build/make_gui.ps1 reads to build the window, copied as it is."""
    shutil.copytree(ROOT / "gui", target / "gui")
    for name in (".codex-plugin/plugin.json", "assets/codex-auto-resume.ico", "build/make_gui.ps1",
                 "build/normalize_pe.py", "advanced/gui/window.sources"):
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target / name)
    return target


def cut_points(root: Path) -> int:
    """Every point's declaration and call taken out of the copy; how many lines went."""
    names = set(points())
    cut = 0
    for source in sorted((root / "gui").glob("*.cs")):
        data = source.read_bytes().decode("utf-8")
        kept = []
        for line in data.splitlines(keepends=True):
            if DECLARATION.match(line.rstrip("\r\n")) or any(
                    re.fullmatch(r"\s*%s\([^;]*\);\s*" % name, line) for name in names):
                cut += 1
                continue
            kept.append(line)
        source.write_bytes("".join(kept).encode("utf-8"))
    return cut


def make_gui(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(root / "build" / "make_gui.ps1"), "-Root", str(root), *arguments],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)


READ_VERSION = r"""
$ErrorActionPreference = 'Stop'
foreach ($path in @($env:CAR_STANDARD, $env:CAR_ADVANCED)) {
    $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($path)
    Write-Output ($info.FileDescription + '|' + $info.ProductVersion + '|' + $info.ProductName)
}
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    """The window itself, built three ways by build/make_gui.ps1: standard, standard with every
    point cut out, and advanced with a probe on the overlay."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="edition-window-"))
        root = copy_window(cls.work / "root")
        (root / "advanced" / "gui" / "Probe.cs").write_text(PROBE, encoding="utf-8")
        with open(root / "advanced" / "gui" / "window.sources", "a", encoding="utf-8") as overlay:
            overlay.write("advanced/gui/Probe.cs\n")
        cut = copy_window(cls.work / "cut")
        cls.cut_lines = cut_points(cut)
        cls.runs = [make_gui(root, "-Out", str(cls.work / "standard")),
                    make_gui(root, "-Edition", "advanced"),
                    make_gui(cut, "-Out", str(cls.work / "without"))]
        cls.advanced_folder = root / "build" / "advanced"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        for run in self.runs:
            if run.returncode != 0:
                self.fail("build/make_gui.ps1 failed:\n" + (run.stderr or run.stdout)[-2000:])
        self.standard = (self.work / "standard" / WINDOW).read_bytes()
        self.advanced = (self.advanced_folder / WINDOW).read_bytes()

    def test_the_standard_window_is_the_file_it_would_be_without_the_points(self):
        """The measurement the plan asked for: declaring the points and calling them changes
        not one byte of the standard executable."""
        self.assertEqual(self.cut_lines, 2 + 3, "two declarations and three calls")
        self.assertEqual(self.standard, (self.work / "without" / WINDOW).read_bytes())
        self.assertEqual((self.work / "standard" / LAUNCHER).read_bytes(),
                         (self.work / "without" / LAUNCHER).read_bytes())

    def test_the_advanced_window_carries_the_overlay_and_the_standard_one_does_not(self):
        for name in ("EditionProbe", "DashboardBuilt", "SnapshotApplied"):
            with self.subTest(name):
                self.assertIn(name.encode("utf-8"), self.advanced)
                self.assertNotIn(name.encode("utf-8"), self.standard)
        literal = "the advanced window was built".encode("utf-16-le")
        self.assertIn(literal, self.advanced)
        self.assertNotIn(literal, self.standard)

    def test_the_audit_reads_the_two_windows_the_same_way(self):
        tree = edition_audit.Inventory.build(
            {"advanced/gui/Probe.cs": PROBE.encode("utf-8")}, (),
            [(ROOT / name).read_text(encoding="utf-8") for name in guiscan.tracked() if name.endswith(".cs")])
        self.assertIn("EditionProbe", tree.window)
        self.assertIn("the advanced window was built", tree.literals)
        launcher = (self.work / "standard" / LAUNCHER).read_bytes()
        executables = dict(zip(edition_audit.EXECUTABLES, (self.standard, launcher)))
        self.assertEqual(edition_audit.check_executables(executables, tree), [])
        found = edition_audit.check_executables(dict(executables, **{edition_audit.WINDOW: self.advanced}), tree)
        self.assertIn("(d) %s holds EditionProbe" % edition_audit.WINDOW, found)
        self.assertIn("(d) %s holds the literal 'the advanced window was built'" % edition_audit.WINDOW, found)

    def test_the_advanced_run_builds_its_window_alone_in_its_own_folder(self):
        """The launcher is one file in both editions, built once, by the standard run."""
        self.assertEqual(sorted(path.name for path in self.advanced_folder.iterdir()),
                         [WINDOW, WINDOW + ".VersionInfo.cs"])

    def test_both_windows_come_out_normalised(self):
        for data in (self.standard, self.advanced):
            self.assertEqual(normalize_pe.normalise(data), data)

    def test_each_window_names_its_edition_in_its_version_resource(self):
        read = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", READ_VERSION],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                              env=dict(os.environ, CAR_STANDARD=str(self.work / "standard" / WINDOW),
                                       CAR_ADVANCED=str(self.advanced_folder / WINDOW)))
        self.assertEqual(read.returncode, 0, read.stderr[-2000:])
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        tail = "|%s|%s" % (manifest["version"], manifest["interface"]["displayName"])
        self.assertEqual([line.strip() for line in read.stdout.splitlines() if line.strip()],
                         ["Codex Auto Resume settings (Standard edition)" + tail,
                          "Codex Auto Resume settings (Advanced edition)" + tail])


if __name__ == "__main__":
    unittest.main()
