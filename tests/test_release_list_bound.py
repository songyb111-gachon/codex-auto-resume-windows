"""The bound on the list of releases the update check and the version picker read (v0.6.23, the owner's decision of
2026-11-10): 8 MiB, written once, and said the same wherever a person reads it.

Nothing here reaches the network: how near the real list stands to the bound is the release's own check. What a list
over the bound does is held by test_prerelease_offer and test_version_picker, which take the value from the script.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

import languages

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
MIB = 1024 * 1024


class BoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = BOOTSTRAP.read_text(encoding="utf-8")

    def test_the_bound_is_eight_mib(self):
        found = re.findall(r"(?m)^\$ReleasesMaxChars = (\d+)\s*$", self.script)
        self.assertEqual(found, [str(8 * MIB)], "one assignment, of 8 MiB")

    def test_the_comment_says_what_an_installed_copy_keeps(self):
        before = self.script[:self.script.index("$ReleasesMaxChars = ")].splitlines()[-3:]
        self.assertIn("An installed copy keeps the bound", " ".join(before))

    def test_every_reader_of_the_list_goes_through_the_one_bound(self):
        """The window and the Python side ask the script for the list; none reads it, or writes a bound of its own."""
        self.assertEqual(self.script.count("$body.Length -gt $ReleasesMaxChars"), 1)
        readers = [*sorted((ROOT / "gui").glob("*.cs")), *sorted((ROOT / "advanced" / "gui").glob("*.cs")),
                   *sorted((ROOT / "src").rglob("*.py")), *sorted((ROOT / "advanced" / "src").rglob("*.py"))]
        self.assertTrue(readers)
        for path in readers:
            words = path.read_text(encoding="utf-8")
            self.assertNotIn("ReleasesMaxChars", words, path.name)
            self.assertIsNone(re.search(r"api\.github\.com/repos", words), path.name)

    @unittest.skipIf(languages.generated_ko_branch(), "the generated ko branch's SECURITY.md is the Korean one")
    def test_a_person_reads_the_same_number(self):
        security = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("is over 8 MiB, is not a list", security)


if __name__ == "__main__":
    unittest.main()
