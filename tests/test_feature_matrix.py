"""The feature matrix cites its evidence, and the citations have to still exist.

`docs/FEATURE_MATRIX.md` is the document a reader trusts about how much of this product
was actually verified: every row names a level and the test or artifact that earns it.
Nothing else in the repository reads it, so a renamed test or a moved file would leave the
matrix quietly wrong - the one failure mode a document about evidence cannot afford, and
one no reviewer catches twice.

So the citations are checked mechanically here. What is deliberately not checked is the
judgement: whether a test that exists really earns the level beside it is a question for a
person, and a test that pretended to answer it would be the same overclaim one layer down.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "FEATURE_MATRIX.md"
KOREAN = ROOT / "docs" / "FEATURE_MATRIX.ko.md"

# `tests/test_engine.py:CorrelationTests.test_T01_...`, and the bare `test_...`
# continuations that follow one in the same cell.
CITATION = re.compile(r"tests/(test_[A-Za-z0-9_]+)\.py:([A-Za-z_][A-Za-z0-9_]*)"
                      r"(?:\.(test_[A-Za-z0-9_]+))?")
# A path in backticks that points into this repository rather than at a command.
PATH = re.compile(r"`((?:src|tests|scripts|build|gui|docs|assets|install|skills)/[^`\s]+)`")
LEVELS = ("IMPLEMENTED", "UNIT TESTED", "INTEGRATION TESTED", "REAL WINDOWS TESTED",
          "REAL CODEX PROTOCOL TESTED", "REAL CODEX VISUALLY TESTED", "PUBLISHED",
          "UNVERIFIED")


def members(module: str) -> dict:
    """Every class in a test module, with the test methods it defines."""
    source = (ROOT / "tests" / (module + ".py")).read_text(encoding="utf-8")
    found = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef):
            found[node.name] = {item.name for item in node.body
                                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return found


class CitationTests(unittest.TestCase):
    def setUp(self):
        if not MATRIX.is_file():
            self.skipTest("docs/FEATURE_MATRIX.md is not in this checkout")
        self.text = MATRIX.read_text(encoding="utf-8")

    def test_every_test_it_cites_exists(self):
        cache = {}
        missing = []
        for module, klass, method in CITATION.findall(self.text):
            if not (ROOT / "tests" / (module + ".py")).is_file():
                missing.append("tests/%s.py does not exist" % module)
                continue
            classes = cache.setdefault(module, members(module))
            if klass not in classes:
                missing.append("tests/%s.py has no class %s" % (module, klass))
            elif method and method not in classes[klass]:
                missing.append("tests/%s.py:%s has no %s" % (module, klass, method))
        self.assertEqual(sorted(set(missing)), [],
                         "the matrix cites evidence that is no longer there; a citation "
                         "that does not resolve is a claim nobody can check")

    def test_every_file_it_points_at_is_in_the_repository(self):
        """Not merely on the machine that wrote the sentence.

        The first version of this asked whether the path existed, and passed for two
        build outputs that are generated and ignored - present for anyone who had built
        the executables, absent in a fresh clone and on CI. A reader who cannot open a
        cited file has no evidence, so the question is whether the repository carries it.
        """
        # A citation (`module.py:Class.test`) is the other test's business, and a pattern
        # (`gui/*.cs`) names a set rather than a file.
        cited = {path for path in PATH.findall(self.text)
                 if ":" not in path and "*" not in path and "?" not in path}
        missing = sorted(path for path in cited if not (ROOT / path).exists())
        self.assertEqual(missing, [], "the matrix points at files that are not here")
        tracked = self.tracked()
        if tracked is None:
            self.skipTest("git is not available to say what the repository carries")
        untracked = []
        for path in sorted(cited):
            if (ROOT / path).is_dir():
                # A directory is carried when anything in it is.
                prefix = path.rstrip("/") + "/"
                if not any(name.startswith(prefix) for name in tracked):
                    untracked.append(path)
            elif path not in tracked:
                untracked.append(path)
        self.assertEqual(untracked, [],
                         "the matrix points at files that are not in the repository; a "
                         "generated or ignored path is evidence only for whoever built it")

    @staticmethod
    def tracked():
        """Every path the repository carries, or None where git cannot be asked."""
        try:
            listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                                     capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        if listing.returncode != 0:
            return None
        return {name for name in listing.stdout.decode("utf-8").split("\0") if name}

    def test_no_row_invents_a_level(self):
        """Every cell written as a level is one of the eight.

        The hazard is not a missing level - a row can honestly answer "-" - but an
        invented one: "MOSTLY TESTED" or "PARTLY VERIFIED" reads like the vocabulary
        while meaning whatever the writer wanted it to mean.
        """
        invented = []
        for line in self.text.splitlines():
            if not line.startswith("|"):
                continue
            for cell in (part.strip().strip("*`") for part in line.split("|")):
                head = cell.split(",")[0].split("(")[0].strip()
                if not head or not re.fullmatch(r"[A-Z][A-Z ]{3,}", head):
                    continue
                if head not in LEVELS:
                    invented.append(head)
        self.assertEqual(sorted(set(invented)), [],
                         "a cell is written like a level but is not one of the eight this "
                         "document defines")

    def test_the_korean_matrix_levels_the_same_number_of_rows(self):
        """The two documents are siblings; a row that gains a level in one and not the
        other is how they start describing different products."""
        if not KOREAN.is_file():
            self.skipTest("docs/FEATURE_MATRIX.ko.md is not in this checkout")
        korean = KOREAN.read_text(encoding="utf-8")
        counts = {}
        for name, text in (("en", self.text), ("ko", korean)):
            counts[name] = sum(
                1 for line in text.splitlines()
                if line.startswith("|")
                and any(cell.strip().startswith(level)
                        for cell in line.split("|") for level in LEVELS))
        self.assertEqual(counts["en"], counts["ko"],
                         "the English matrix levels %d rows and the Korean one %d"
                         % (counts["en"], counts["ko"]))


if __name__ == "__main__":
    unittest.main()
