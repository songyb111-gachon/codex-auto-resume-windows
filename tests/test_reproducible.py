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

import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

import normalize_pe  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
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
        result = subprocess.run([str(exe), "a", "b"], capture_output=True, text=True, timeout=60)
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
        self.assertEqual(script.count("-Description '"), 2, "both executables are described")

    def test_the_release_build_proves_it_twice(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("Check the executables are reproducible", workflow)
        build = workflow.index("Build the settings window and the MCP launcher")
        check = workflow.index("Check the executables are reproducible")
        archive = workflow.index("Build the release archive")
        self.assertLess(build, check)
        self.assertLess(check, archive)


if __name__ == "__main__":
    unittest.main()
