"""The scanner every test of the window reads its C# through (`tests/guiscan.py`).

The Python package has `tests/test_srcscan.py` for exactly this reason, and the reason is
that a structural test is only as good as the list of files it was looked for in. The
window's list was written out by hand in seventeen places until v0.6.10-alpha; these hold it
to being one list, to naming files that are there, and to nobody quietly adding a source that
the window compiles and no test reads.

The second half holds the finding, which matters more than it sounds. Twenty test classes take
a slice of a control source or `SettingsApp.cs` by searching for text, and a slice that ends at
"the next `private void `" is a slice that widens to the end of the file the day that string
stops appearing between the two anchors - with every assertion inside it still passing, over
the wrong code. `type_body` and `member_body` find a block by its braces and raise where they
cannot, so the failure is loud.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # guiscan lives next to this file

import guiscan  # noqa: E402


class ManifestTests(unittest.TestCase):
    def test_every_tracked_source_is_compiled_or_known_to_be_separate(self):
        """A `gui/*.cs` that is on neither list is a file somebody added to the window and
        nobody told the build about, or one the build compiles and no test reads."""
        listed = set(guiscan.manifest()) | set(guiscan.SEPARATE)
        tracked = {name for name in guiscan.tracked() if name.endswith(".cs")}
        self.assertEqual(tracked - listed, set(), "not on gui/window.sources")
        self.assertEqual(listed - tracked, set(), "listed but not tracked")

    def test_the_list_names_files_that_are_there_and_says_each_once(self):
        self.assertEqual(len(set(guiscan.manifest())), len(guiscan.manifest()))
        for path in guiscan.sources():
            with self.subTest(guiscan.relative(path)):
                self.assertTrue(path.is_file())

    def test_the_build_reads_the_list_rather_than_repeating_it(self):
        """The build that ships names no source of the window. It reads this file, which is
        the whole point of there being one: csc takes its sources in the order given and the
        release is reproducible byte for byte, so the order is part of what is shipped - and
        an order written down twice is an order that can differ."""
        script = (guiscan.ROOT / "build" / "make_gui.ps1").read_text(encoding="utf-8")
        self.assertIn("window.sources", script)
        for name in guiscan.manifest():
            with self.subTest(name):
                self.assertNotIn(name.replace("gui/", "gui\\"), script)
        # The launcher is the exception, and is named because it is its own executable.
        self.assertIn("gui\\McpLauncher.cs", script)

    def test_nothing_else_repeats_the_list_either(self):
        """Sixteen Python sites spelled these four names to hand them to csc. One call now."""
        spelled = []
        for folder in ("tests", "build"):
            for path in sorted((guiscan.ROOT / folder).glob("*.py")):
                if path.name in ("guiscan.py", "test_guiscan.py", "measure_window.py"):
                    continue                     # the scanner, its test, and the one that
                text = path.read_text(encoding="utf-8")   # measures another checkout's tree
                if all(name.rsplit("/", 1)[-1] in text for name in guiscan.manifest()):
                    spelled.append(path.name)
        self.assertEqual(spelled, [], "the compile list is written out again here")

    def test_nothing_on_disk_is_missed(self):
        listed = set(guiscan.manifest()) | set(guiscan.SEPARATE)
        self.assertEqual({guiscan.relative(path) for path in guiscan.on_disk()} - listed, set())

    def test_the_scan_refuses_to_answer_about_nothing(self):
        """A scan that quietly returns an empty listing proves whatever it is asked."""
        with self.assertRaises(guiscan.ScanError):
            guiscan.read("gui/NotASource.cs")
        with self.assertRaises(guiscan.ScanError):
            guiscan.type_body("NoSuchTypeExistsHere")


class SliceTests(unittest.TestCase):
    """Finding a block by its braces, and failing where it is not there."""

    def test_a_type_comes_back_whole_and_with_its_declaration(self):
        body = guiscan.type_body("Ground")
        self.assertTrue(body.lstrip().startswith(("internal", "public", "static", "sealed",
                                                  "partial", "class")))
        self.assertIn("class Ground", body.splitlines()[0])
        self.assertEqual(body.count("{"), body.count("}"), "the block is balanced")
        self.assertTrue(body.rstrip().endswith("}"))

    def test_a_member_is_found_inside_its_own_type(self):
        body = guiscan.member_body("SettingsForm", "BuildFooter")
        self.assertIn("BuildFooter", body.splitlines()[0])
        self.assertEqual(body.count("{"), body.count("}"))
        self.assertLess(len(body.splitlines()), 200, "a member, not half the file")

    def test_the_window_is_one_partial_class_in_as_many_parts_as_it_has_files(self):
        """`SettingsForm` is written across both halves of the window, so a rule that read one
        declaration of it reads a fraction of the window - a quarter when there were four
        parts in two files, an eleventh now. That is what `parts_of` is for, and it is why
        the split could happen at all: a partial class is written wherever it is convenient
        to read, and the compiler sees one type."""
        parts = guiscan.parts_of("SettingsForm")
        holders = [name for name in guiscan.window_sources()
                   if "partial class SettingsForm" in guiscan.read(name)]
        self.assertEqual(len(parts), len(holders))
        self.assertGreater(len(parts), 4, "it was four, in two files, before v0.6.10-alpha")
        self.assertEqual(sorted(set(guiscan.window_sources()) - set(holders)),
                         ["gui/WindowJson.cs"], "the one window source that is not the form")
        for part in parts:
            with self.subTest(part.splitlines()[0].strip()[:40]):
                self.assertIn("partial", part.splitlines()[0])
        with self.assertRaises(guiscan.ScanError):
            guiscan.type_body("SettingsForm")          # ambiguous without a source
        self.assertTrue(guiscan.type_body("SettingsForm", "gui/Dashboard.cs"))

    def test_a_missing_type_or_member_raises_rather_than_widening(self):
        """The whole point. The slices this replaces ended at the next occurrence of some
        other text, so a type that stopped being followed by it silently grew to the end of
        the file, and every assertion about it went on passing over the wrong code."""
        with self.assertRaises(guiscan.ScanError):
            guiscan.type_body("ThisTypeWasRenamedLastWeek")
        with self.assertRaises(guiscan.ScanError):
            guiscan.member_body("SettingsForm", "ThisMethodWasRenamedLastWeek")

    def test_every_type_the_window_declares_is_findable(self):
        """Not vacuous: if the pattern only matched a few shapes, the rules built on it would
        be checking a handful of types and reporting success for all of them.

        Three names are declared twice and one four times, and all four are legitimate: the
        window's own partial class, and three private `struct`s that each belong to a
        different class. `parts_of` is what answers for those.
        """
        names = guiscan.types()
        self.assertGreater(len(names), 50)
        for name in set(names):
            with self.subTest(name):
                self.assertTrue(guiscan.parts_of(name))

    def test_each_source_says_how_much_of_the_window_it_is(self):
        """What a split works from: the types a file declares directly, which is what moves."""
        counts = {source: len(guiscan.top_level(source)) for source in guiscan.manifest()}
        declared = [name for source in guiscan.manifest() for name in guiscan.top_level(source)]
        self.assertEqual(len(set(declared)), 54, "the window's types")
        self.assertEqual(len(declared) - len(set(declared)), 9,
                         "`partial class SettingsForm` written once per file that holds part "
                         "of it, which is ten of the window's eleven sources")
        for source, count in counts.items():
            with self.subTest(source):
                self.assertGreater(count, 0)
                # Controls.cs held 37 of the 57 before v0.6.10-alpha split it in seven. A
                # ceiling rather than an exact count, so adding a type is an ordinary edit
                # and gathering a third of the window into one file again is not.
                self.assertLessEqual(count, 12, "%s holds too much of the window" % source)


if __name__ == "__main__":
    unittest.main()
