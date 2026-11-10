r"""A rule the window has to hold in C#, held equal to the one Python holds.

The window is compiled on its own and cannot import a Python constant, so where it states a rule Python states too the
two are compared as text here. (The behaviour of each copy has its own tests: tests/test_gui_versions.py and
tests/test_gui_update.py run the window's patterns over the version table of tests/test_version_rule.py.)
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from codex_auto_resume.domain.ids import PRODUCT_RELEASE, PRODUCT_STAGE
from codex_auto_resume.notify import UPDATE_VERSION

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"


def regex_of(source: str, field: str) -> str:
    """The verbatim pattern the `field` Regex of a C# source is made from."""
    found = re.search(r"Regex\s+%s\s*=\s*new\s+[\w.]*Regex\(\s*@\"([^\"]+)\"" % field, source)
    if found is None:
        raise AssertionError("no Regex field named %s" % field)
    return found.group(1)


class VersionRuleCopies(unittest.TestCase):
    def test_any_version_the_window_reads_is_the_one_the_notice_names(self):
        window = regex_of((GUI / "DashboardVersions.cs").read_text(encoding="utf-8"), "VersionRule")
        self.assertEqual(window, "^" + PRODUCT_RELEASE + "(" + PRODUCT_STAGE + r")?\z")

    def test_a_prerelease_the_window_offers_is_the_same_rule_with_the_stage_required(self):
        window = regex_of((GUI / "DashboardMaintenance.cs").read_text(encoding="utf-8"), "PrereleaseRule")
        self.assertEqual(window, "^" + PRODUCT_RELEASE + PRODUCT_STAGE + r"\z")

    def test_the_notice_is_built_from_the_one_source(self):
        self.assertEqual(UPDATE_VERSION.pattern, PRODUCT_RELEASE + "(" + PRODUCT_STAGE + r")?\Z")


if __name__ == "__main__":
    unittest.main()
