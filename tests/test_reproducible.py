"""The executables are reproducible: the same source always compiles to the same bytes.

The in-box C# compiler has no /deterministic switch. Two builds of the same source were
diffed byte for byte and differed in exactly two fields - the COFF header's TimeDateStamp
and the module's MVID in the #GUID metadata heap - and nothing else: not the IL, not the
resources, not the manifest. build/normalize_pe.py sets the first to a constant and the
second to a GUID derived from the module's own content, which is what Roslyn's
/deterministic does. These tests compile real executables with the real compiler, twice,
and hold the normaliser to that.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import struct
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # guiscan lives next to this file
sys.path.insert(0, str(ROOT / "build"))

import guiscan  # noqa: E402
import gui_stamp  # noqa: E402
import normalize_pe  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
READ_VERSION = r"""
$ErrorActionPreference = 'Stop'
$out = @{}
foreach ($name in @('CodexAutoResumeSettings.exe')) {
    $path = Join-Path $env:CAR_BUILD $name
    $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($path)
    $out[$name] = @{
        FileVersion      = $info.FileVersion
        ProductVersion   = $info.ProductVersion
        ProductName      = $info.ProductName
        CompanyName      = $info.CompanyName
        LegalCopyright   = $info.LegalCopyright
        FileDescription  = $info.FileDescription
    }
}
$out | ConvertTo-Json -Depth 4 -Compress
"""

SOURCE = """
using System;
static class Program {
    static int Main(string[] args) { Console.WriteLine("reproducible " + args.Length); return 0; }
}
"""


def compile_once(folder: Path) -> Path:
    """Same source, same output name - the assembly name comes from the file name, so two
    builds under different names are genuinely different programs."""
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "Program.cs"
    source.write_text(SOURCE, encoding="utf-8")
    exe = folder / "program.exe"
    subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
                    "/out:" + str(exe), str(source)], check=True, capture_output=True, timeout=120)
    return exe


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class RealCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp())
        cls.first = compile_once(cls.folder / "a").read_bytes()
        # The timestamp has one-second resolution; make sure the two builds straddle one.
        time.sleep(1.2)
        cls.second = compile_once(cls.folder / "b").read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_two_raw_builds_differ(self):
        """If this ever fails the compiler became deterministic and the normaliser is moot."""
        self.assertNotEqual(self.first, self.second)

    def test_they_differ_only_in_the_two_known_fields(self):
        offsets = normalize_pe.locate(self.first)
        self.assertEqual(offsets, normalize_pe.locate(self.second))
        allowed = set(range(offsets["timestamp"], offsets["timestamp"] + 4)) | \
            set(range(offsets["mvid"], offsets["mvid"] + 16))
        differing = {i for i, (a, b) in enumerate(zip(self.first, self.second)) if a != b}
        self.assertEqual(len(self.first), len(self.second))
        self.assertTrue(differing, "the builds should differ somewhere")
        self.assertLessEqual(differing, allowed, "a byte outside the known fields varies")

    def test_normalised_builds_are_identical(self):
        self.assertEqual(normalize_pe.normalise(self.first), normalize_pe.normalise(self.second))

    def test_normalising_is_idempotent(self):
        once = normalize_pe.normalise(self.first)
        self.assertEqual(normalize_pe.normalise(once), once)

    def test_the_normalised_program_still_runs(self):
        exe = self.folder / "normalised.exe"
        exe.write_bytes(normalize_pe.normalise(self.first))
        result = subprocess.run([str(exe), "a", "b"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "reproducible 2")

    def test_the_mvid_depends_on_the_content(self):
        """Different programs must not share an MVID just because both were normalised."""
        other = bytearray(normalize_pe.normalise(self.first))
        mvid = normalize_pe.locate(bytes(other))["mvid"]
        # Change one byte of IL-bearing content well away from both fields.
        target = len(other) // 2
        while mvid <= target < mvid + 16:
            target += 32
        other[target] ^= 0xFF
        renormalised = normalize_pe.normalise(bytes(other))
        self.assertNotEqual(renormalised[mvid:mvid + 16],
                            normalize_pe.normalise(self.first)[mvid:mvid + 16])

    def test_the_timestamp_is_the_fixed_value(self):
        data = normalize_pe.normalise(self.first)
        offset = normalize_pe.locate(data)["timestamp"]
        self.assertEqual(struct.unpack_from("<I", data, offset)[0], normalize_pe.FIXED_TIMESTAMP)


RANDOMLY_NAMED = """
using System;
static class Program {
    static int Code(string s) {
        switch (s) {
            case "a": return 1; case "b": return 2; case "c": return 3; case "d": return 4;
            case "e": return 5; case "f": return 6; case "g": return 7; case "h": return 8;
            case "i": return 9; case "j": return 10;
            default: return 0;
        }
    }
    static int Main(string[] args) { return Code(args.Length > 0 ? args[0] : ""); }
}
"""


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class RandomlyNamedClassTests(unittest.TestCase):
    """The third varying field, which stopped the first v0.6.3 release run.

    A long string switch makes the in-box compiler emit a class named with a fresh random
    GUID. The normaliser cannot make that name a function of the source, so it refuses the
    image, and `make_gui.ps1` fails on the machine that built it."""

    def test_an_image_with_a_randomly_named_class_is_refused(self):
        folder = Path(tempfile.mkdtemp())
        try:
            source = folder / "Program.cs"
            source.write_text(RANDOMLY_NAMED, encoding="utf-8")
            exe = folder / "program.exe"
            subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
                            "/out:" + str(exe), str(source)], check=True, capture_output=True, timeout=120)
            data = exe.read_bytes()
            self.assertIn(b"<PrivateImplementationDetails>{", data,
                          "the compiler no longer emits the class; this test proves nothing")
            with self.assertRaises(normalize_pe.NotNormalisable) as caught:
                normalize_pe.normalise(data)
            self.assertIn("PrivateImplementationDetails", str(caught.exception))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_the_shipped_window_source_has_no_long_string_switch(self):
        # The same rule, read from the source, so it fails without a compiler too.
        for name in guiscan.manifest():
            text = guiscan.read(name)
            for match in re.finditer(r"\bswitch\s*\(", text):
                start = text.find("{", match.end())
                depth, end = 0, start
                while end < len(text):
                    depth += {"{": 1, "}": -1}.get(text[end], 0)
                    if depth == 0:
                        break
                    end += 1
                cases = len(re.findall(r'\bcase\s+"', text[start:end]))
                with self.subTest(file=name, line=text.count("\n", 0, match.start()) + 1):
                    # Measured on this compiler: six string cases produced the class, four did not.
                    self.assertLess(cases, 5, "a string switch this long makes the build unreproducible")


# What makes the in-box compiler write a class named <PrivateImplementationDetails>{GUID}, measured on this compiler
# (v0.6.27, S6.3d): a string switch of six or more labels (five and fewer do not: it builds a Dictionary for six) and a
# constant array initializer of three or more primitive elements (one and two do not). The host's sources (gui/host.sources)
# are held to both here, from the text, so a failure shows without a compiler; HostBuildTests proves it with one.
STRING_SWITCH_LABELS = 6
CONSTANT_ARRAY_ELEMENTS = 3
PRIMITIVES = r"(?:int|uint|long|ulong|short|ushort|byte|sbyte|char|bool|float|double)"
ARRAY_START = re.compile(r"new\s+" + PRIMITIVES + r"\s*\[[^\]]*\]\s*\{|new\s*\[\s*\]\s*\{|\b" + PRIMITIVES + r"\s*\[,*\]\s+\w+\s*=\s*\{")


def code_of(text: str) -> str:
    """The C# text with its comments blanked (a quote in a comment is not a literal), strings and chars kept."""
    out, at = [], 0
    while at < len(text):
        two = text[at:at + 2]
        if two == "//":
            end = text.find("\n", at)
            end = len(text) if end < 0 else end
            out.append(" " * (end - at))
            at = end
        elif two == "/*":
            end = text.find("*/", at + 2)
            end = len(text) if end < 0 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[at:end]))
            at = end
        elif text[at] == "@" and text[at + 1:at + 2] == '"':
            end = at + 2
            while end < len(text) and not (text[end] == '"' and text[end + 1:end + 2] != '"'):
                end += 2 if text[end] == '"' else 1
            out.append(text[at:end + 1])
            at = end + 1
        elif text[at] in "\"'":
            end = at + 1
            while text[end] != text[at]:
                end += 2 if text[end] == "\\" else 1
            out.append(text[at:end + 1])
            at = end + 1
        else:
            out.append(text[at])
            at += 1
    return "".join(out)


def block_end(code: str, start: int, opener: str = "{", closer: str = "}") -> int:
    """The index of the bracket that closes the one at `start`, literals skipped."""
    depth, at = 0, start
    while at < len(code):
        char = code[at]
        if char in "\"'":
            at += 1
            while code[at] != char:
                at += 2 if code[at] == "\\" else 1
        else:
            depth += (char == opener) - (char == closer)
            if depth == 0:
                return at
        at += 1
    raise ValueError("unbalanced")


def top_level(code: str, start: int, end: int) -> list:
    """The pieces of code[start:end] split at the commas outside any bracket or literal."""
    pieces, depth, at, begin = [], 0, start, start
    while at < end:
        char = code[at]
        if char in "\"'":
            at += 1
            while code[at] != char:
                at += 2 if code[at] == "\\" else 1
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            pieces.append(code[begin:at])
            begin = at + 1
        at += 1
    pieces.append(code[begin:end])
    return [piece for piece in pieces if piece.strip()]


def string_switch_labels(text: str) -> list:
    """(line, number of case labels) of every switch that has a string label, from the text."""
    code = code_of(text)
    found = []
    for match in re.finditer(r"\bswitch\s*\(", code):
        opening = code.index("(", match.start())
        body = code.index("{", block_end(code, opening, "(", ")"))
        end = block_end(code, body)
        labels, depth, at = 0, 0, body + 1
        string_label = False
        while at < end:
            char = code[at]
            if char in "\"'":
                at += 1
                while code[at] != char:
                    at += 2 if code[at] == "\\" else 1
            elif char in "{([":
                depth += 1
            elif char in "})]":
                depth -= 1
            elif depth == 0 and re.match(r"case\b", code[at:at + 5]) and not (code[at - 1].isalnum() or code[at - 1] == "_"):
                labels += 1
                string_label = string_label or code[at + 4:].lstrip().startswith('"')
            at += 1
        if string_label:
            found.append((code.count("\n", 0, match.start()) + 1, labels))
    return found


def constants_of(code: str) -> set:
    """The names a `const` of a primitive type gives, in any of the sources (a string constant makes an array of strings,
    which is no primitive array)."""
    names = set()
    for match in re.finditer(r"\bconst\s+" + PRIMITIVES + r"\s+", code):
        end = code.index(";", match.end())
        for piece in top_level(code, match.start(), end):
            named = re.search(r"(\w+)\s*=", piece)
            if named:
                names.add(named.group(1))
    return names


def constant_arrays(text: str, constants: set) -> list:
    """(line, number of elements) of every array initializer of primitives that are all constants: the numbers, chars
    and booleans written out, and the names of `const` declarations (`constants`), in any arithmetic."""
    code = code_of(text)
    found = []
    for match in ARRAY_START.finditer(code):
        opening = match.end() - 1
        end = block_end(code, opening)
        elements = top_level(code, opening + 1, end)
        wholly = True
        for element in elements:
            if '"' in element:
                wholly = False
                break
            bare = re.sub(r"'(?:\\.|[^'\\])'", "0", element)
            bare = re.sub(r"\b0[xX][0-9A-Fa-f]+[uUlL]*\b|\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?[fFdDuUlLmM]?\b", "0", bare)
            names = re.findall(r"[A-Za-z_]\w*", bare)
            if any(name not in constants and name not in ("true", "false", "int", "uint", "long", "double", "byte", "char") for name in names):
                wholly = False
                break
        if wholly and len(elements) >= CONSTANT_ARRAY_ELEMENTS:
            found.append((code.count("\n", 0, match.start()) + 1, len(elements)))
    return found


class HostSourceRuleTests(unittest.TestCase):
    """The host (gui/host.sources) compiles to an image build/normalize_pe.py accepts: no string switch of six or more
    labels, no constant primitive array of three or more elements. What replaces them is written in the repository's
    way - an if chain, an array filled one element at a time (SurfaceMath.Three, Four, Six, or `new int[4]` where the
    elements are zero), a large table built at its first use from a compact string (gui/SurfaceBidi.cs)."""

    @classmethod
    def setUpClass(cls):
        cls.names = guiscan.SEPARATE + guiscan.host_group("generated")
        cls.texts = {name: (ROOT / name).read_text(encoding="utf-8") for name in cls.names}
        cls.constants = set()
        for text in cls.texts.values():
            cls.constants |= constants_of(code_of(text))

    def test_the_host_list_is_there(self):
        self.assertTrue(self.names, "gui/host.sources lists nothing")
        self.assertIn("gui/SurfaceBidi.cs", self.names)

    def test_no_string_switch_of_six_or_more_labels_is_in_the_host(self):
        for name, text in self.texts.items():
            for line, labels in string_switch_labels(text):
                with self.subTest(file=name, line=line):
                    self.assertLess(labels, STRING_SWITCH_LABELS,
                                    "a string switch of %d labels makes the compiler name a class at random: write an if chain" % labels)

    def test_no_constant_array_of_three_or_more_elements_is_in_the_host(self):
        for name, text in self.texts.items():
            for line, count in constant_arrays(text, self.constants):
                with self.subTest(file=name, line=line):
                    self.fail("a constant array of %d elements makes the compiler name a class at random: fill it one element "
                              "at a time (SurfaceMath.Three, Four, Six) or build it at its first use" % count)

    def test_the_window_has_no_constant_array_either(self):
        constants = set(self.constants)
        window = {name: guiscan.read(name) for name in guiscan.manifest()}
        for text in window.values():
            constants |= constants_of(code_of(text))
        for name, text in window.items():
            for line, count in constant_arrays(text, constants):
                with self.subTest(file=name, line=line):
                    self.fail("a constant array of %d elements" % count)

    def test_the_scanner_finds_what_it_is_written_to_find(self):
        """The rules above are only as good as these two readers: each is shown a switch and an array it must refuse and
        ones it must let through, so a scanner that goes blind fails here and not silently."""
        six = 'class A { static int F(string s) { switch (s) { case "a": return 1; case "b": return 2; case "c": return 3; ' \
              'case "d": return 4; case "e": return 5; case "f": return 6; } return 0; } }'
        five = six.replace('case "f": return 6; ', "")
        stacked = 'class A { static int F(string s) { switch (s) { case "a": case "b": case "c": case "d": case "e": case "f": return 1; } return 0; } }'
        numbers = 'class A { static int F(int n) { switch (n) { case 1: case 2: case 3: case 4: case 5: case 6: case 7: return 1; } return 0; } }'
        commented = 'class A { // a switch (s) { case "a": ... } and an apostrophe\n static int F(string s) { return 0; } }'
        self.assertEqual(string_switch_labels(six), [(1, 6)])
        self.assertEqual(string_switch_labels(five), [(1, 5)])
        self.assertEqual(string_switch_labels(stacked), [(1, 6)])
        self.assertEqual(string_switch_labels(numbers), [], "an int switch builds no dictionary")
        self.assertEqual(string_switch_labels(commented), [])
        const = {"Tick", "Frame"}
        self.assertEqual(constant_arrays("int[] a = { 1, 2, 3 };", const), [(1, 3)])
        self.assertEqual(constant_arrays("var a = new[] { 0x10, 0x20, -3 };", const), [(1, 3)])
        self.assertEqual(constant_arrays("var a = new int[] { Tick, Frame, 2 * Tick };", const), [(1, 3)])
        self.assertEqual(constant_arrays("var a = new[] { 0, 0, 0, 0 };", const), [(1, 4)])
        self.assertEqual(constant_arrays("var a = new[] { 1, 2 };", const), [], "two elements are written one by one")
        self.assertEqual(constant_arrays("var a = new[] { x, 0, 1 };", const), [], "a variable is not a constant")
        self.assertEqual(constant_arrays('var a = new[] { "a", "b", "c" };', const), [], "strings are not primitives")
        self.assertEqual(constant_arrays("var a = new int[4];", const), [])
        self.assertEqual(constant_arrays("var a = new[] { Other, 0, 1 };", const), [], "an unknown name is not a constant")


HOST_COMPILE = ("/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/reference:System.dll", "/reference:System.Drawing.dll")


def compile_host(folder: Path) -> Path:
    """The host's sources, in gui/host.sources' order, with the in-box compiler - build/make_gui.ps1's arguments less the
    icon, manifest and version resource, which change no IL."""
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "CodexAutoResume.exe"
    sources = [str(ROOT / name) for name in guiscan.SEPARATE + guiscan.host_group("generated")]
    done = subprocess.run([str(CSC), *HOST_COMPILE, "/out:" + str(exe), *sources],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if done.returncode != 0:
        raise AssertionError("the host did not compile:\n" + (done.stdout + done.stderr)[-2000:])
    return exe


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class HostBuildTests(unittest.TestCase):
    """The host, built with the real compiler twice, is one program: the normaliser accepts it and the two are equal."""

    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp())
        cls.first = compile_host(cls.folder / "a").read_bytes()
        time.sleep(1.2)                     # the PE timestamp has one-second resolution
        cls.second = compile_host(cls.folder / "b").read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_the_host_has_no_randomly_named_class(self):
        self.assertNotIn(b"<PrivateImplementationDetails>{", self.first)

    def test_the_normaliser_accepts_the_host(self):
        self.assertEqual(normalize_pe.normalise(normalize_pe.normalise(self.first)), normalize_pe.normalise(self.first))

    def test_two_builds_of_the_host_are_the_same_bytes_once_normalised(self):
        self.assertNotEqual(self.first, self.second, "the raw builds differ in the timestamp and the MVID")
        self.assertEqual(normalize_pe.normalise(self.first), normalize_pe.normalise(self.second))


class RefusalTests(unittest.TestCase):
    """A file it does not fully understand is refused, never edited."""

    def test_non_pe_input_is_refused(self):
        for junk in (b"", b"not an executable", b"MZ" + b"\0" * 100):
            with self.subTest(junk[:10]), self.assertRaises((normalize_pe.NotNormalisable, struct.error)):
                normalize_pe.normalise(junk)


class BuildScriptTests(unittest.TestCase):
    def test_make_gui_normalises_every_executable(self):
        script = (ROOT / "build" / "make_gui.ps1").read_text(encoding="utf-8")
        body = script[script.index("function Build"):]
        self.assertIn("$normalizer $exe", body[:body.index("\n}")])

    def test_the_executables_carry_a_version_resource_from_the_manifest(self):
        """Without one they said 0.0.0.0 with no product or publisher - in Explorer, and
        in the SmartScreen and Smart App Control prompts where people decide to trust a file."""
        script = (ROOT / "build" / "make_gui.ps1").read_text(encoding="utf-8")
        for attribute in ("AssemblyProduct", "AssemblyCompany", "AssemblyFileVersion",
                          "AssemblyInformationalVersion", "AssemblyCopyright"):
            self.assertIn(attribute, script)
        self.assertIn(r".codex-plugin\plugin.json", script)
        # The window is described, by edition, since each edition has its own; the host (one file for both editions,
        # built by the standard run: gui/host.sources) says what it is (v0.6.27: the MCP launcher that was the other is
        # car-bin's, built by cargo).
        self.assertEqual(script.count("-Description "), 2, "the window and the host are described")
        self.assertIn("-Description ('Codex Auto Resume settings (' + $EditionWord + ' edition)')", script)
        self.assertIn("-Description 'Codex Auto Resume watcher host'", script)

    def test_the_release_build_proves_it_twice(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("Check the executables are reproducible", workflow)
        build = workflow.index("Build each edition's settings window")
        check = workflow.index("Check the executables are reproducible")
        archive = workflow.index("Build the release archive")
        self.assertLess(build, check)
        self.assertLess(check, archive)

    def test_the_release_build_proves_both_editions_executables_twice(self):
        """Each edition builds its own window, so each is built twice and compared: two
        executables, known by folder as well as name, since the two windows share one."""
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        start = workflow.index("- name: Build each edition's settings window")
        steps = workflow[start:workflow.index("- name: Build the release archive")]
        self.assertEqual(steps.count("./build/make_gui.ps1 -Edition advanced"), 2, "built once, then again")
        self.assertEqual(len(re.findall(r"\./build/make_gui\.ps1(?! -Edition)", steps)), 2)
        self.assertIn("Get-ChildItem build/advanced -Filter *.exe", steps)
        self.assertIn("if ($first.Count -ne 2)", steps)
        self.assertIn('"$($exe.Directory.Name)/$($exe.Name)"', steps)


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box compiler and PowerShell")
class VersionResourceTests(unittest.TestCase):
    """Build both executables the way the release does, then read the resource back.

    Asserting that `build/make_gui.ps1` contains the word `AssemblyFileVersion` proves the
    script mentions it, not that a built file carries it: the attribute could be written
    into a source the compiler never sees, or the resource could be dropped by a later
    argument, and the source assertion would still pass. So this runs the real script and
    then asks Windows - the same `GetFileVersionInfo` that fills in Explorer's Properties,
    Details tab, which is where a person actually looks before trusting an unsigned file.
    """

    @classmethod
    def setUpClass(cls):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        cls.version = manifest["version"]
        cls.publisher = manifest["author"]["name"]
        cls.product = manifest["interface"]["displayName"]
        cls.folder = Path(tempfile.mkdtemp())
        build = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(ROOT / "build" / "make_gui.ps1"),
             "-Root", str(ROOT), "-Out", str(cls.folder)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        cls.build = build
        if build.returncode != 0:
            cls.fields = {}
            return
        # One PowerShell call reads both files: starting the host twice costs more than the
        # compile did. FileVersionInfo is the managed face of the Win32 version resource.
        read = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", READ_VERSION],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            env=dict(os.environ, CAR_BUILD=str(cls.folder)))
        cls.read = read
        cls.fields = json.loads(read.stdout) if read.returncode == 0 and read.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def setUp(self):
        if self.build.returncode != 0:
            self.fail("build/make_gui.ps1 failed:\n" + (self.build.stderr or self.build.stdout)[-2000:])
        if not self.fields:
            self.fail("the version resource could not be read: " + getattr(self, "read", self.build).stderr[-2000:])

    def test_the_window_was_built_and_nothing_else(self):
        """v0.6.27: the MCP launcher is car-bin's (D18); make_gui.ps1 builds the window, and the standard run the host beside it."""
        self.assertEqual(sorted(self.fields), ["CodexAutoResumeSettings.exe"])
        self.assertFalse((self.folder / "codex-auto-resume-mcp.exe").exists())

    def test_every_field_a_person_reads_comes_from_the_manifest(self):
        for name, found in sorted(self.fields.items()):
            with self.subTest(name):
                # Explorer shows the file version; the informational version is what the
                # product calls itself, and it is the manifest's version with nothing added. A
                # version resource holds numbers only, so a pre-release's file version is its
                # release's (0.6.9-alpha -> 0.6.9.0, 0.6.11-beta.2 -> 0.6.11.0).
                self.assertEqual(found["FileVersion"], self.version.split("-")[0] + ".0")
                self.assertEqual(found["ProductVersion"], self.version)
                self.assertEqual(found["ProductName"], self.product)
                self.assertEqual(found["CompanyName"], self.publisher)
                self.assertIn(self.publisher, found["LegalCopyright"])
                self.assertIn("MIT", found["LegalCopyright"])

    def test_each_executable_describes_itself(self):
        """The window names its edition, as the Dashboard does beside the version (v0.6.11).
        tests/test_edition_window.py reads the advanced window's."""
        descriptions = {name: found["FileDescription"] for name, found in self.fields.items()}
        self.assertEqual(descriptions, {
            "CodexAutoResumeSettings.exe": "Codex Auto Resume settings (Standard edition)",
        })

    def test_each_executable_is_stamped_for_this_tree(self):
        """What make_release.collect_gui asks of every executable it packs: a stamp beside it that
        build/gui_stamp.py gives this tree. Read from the real script's own output."""
        for name, kind in (("CodexAutoResumeSettings.exe", "window"),):
            with self.subTest(name):
                self.assertTrue(gui_stamp.stamp_path(self.folder / name).is_file(), name + " has no stamp")
                gui_stamp.check(self.folder / name, ROOT, "standard", kind)
                self.assertEqual(json.loads(gui_stamp.stamp_path(self.folder / name).read_text(encoding="utf-8")),
                                 gui_stamp.describe(ROOT, "standard", kind))

    def test_the_standard_run_builds_the_host_beside_the_window_normalised_and_stamped(self):
        """v0.6.27 (S6.3d): CodexAutoResume.exe, the C# host, is built by the same script and held to the same rules: its
        image is what build/normalize_pe.py leaves (it refused the host while its sources made random class names), and
        its stamp is this tree's."""
        host = self.folder / "CodexAutoResume.exe"
        self.assertTrue(host.is_file(), "the standard run builds the host")
        image = host.read_bytes()
        self.assertEqual(normalize_pe.normalise(image), image, "the build left it normalised")
        self.assertNotIn(b"<PrivateImplementationDetails>{", image)
        self.assertTrue(gui_stamp.stamp_path(host).is_file(), "the host has no stamp")
        gui_stamp.check(host, ROOT, "standard", "host")

    def test_nothing_reports_the_zero_version_that_made_this_worth_doing(self):
        for name, found in sorted(self.fields.items()):
            with self.subTest(name):
                self.assertNotEqual(found["FileVersion"], "0.0.0.0")
                self.assertTrue(found["CompanyName"].strip(), "no publisher is what SmartScreen shows")


if __name__ == "__main__":
    unittest.main()
