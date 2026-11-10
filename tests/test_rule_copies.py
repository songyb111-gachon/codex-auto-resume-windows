r"""A rule the window has to hold in C#, held equal to the one Python holds.

The window is compiled on its own and cannot import a Python constant, so where it states a rule Python states too the
two are compared as text here. (The behaviour of each copy has its own tests: tests/test_gui_versions.py and
tests/test_gui_update.py run the window's patterns over the version table of tests/test_version_rule.py.)
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from codex_auto_resume import config
from codex_auto_resume.compat.files import RELEASE_VERSION
from codex_auto_resume.domain.ids import PRODUCT_RELEASE, PRODUCT_STAGE
from codex_auto_resume.notify import UPDATE_VERSION
from codex_auto_resume.ownreport.document import PRODUCT_VERSION

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


class VersionBoundsDifferOnPurpose(unittest.TestCase):
    """An offered version (no leading zero, six digits), this installation's own (cut out of plugin.json, wider) and a
    community report's (the receiver's four digits) are three questions; every version we publish answers all of them."""

    def test_each_refuses_what_it_should_and_the_others_do_not(self):
        self.assertIsNotNone(RELEASE_VERSION.fullmatch("00.6.1"))
        self.assertIsNone(UPDATE_VERSION.match("00.6.1"))
        self.assertIsNotNone(UPDATE_VERSION.match("12345.0.0"))
        self.assertIsNone(PRODUCT_VERSION.match("12345.0.0"))

    def test_the_report_takes_the_receivers_four_digits(self):
        receiver = (ROOT / "build" / "community_report.py").read_text(encoding="utf-8")
        self.assertIn(r'PRODUCT = re.compile(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})', receiver)

    def test_a_version_we_publish_is_every_one_of_them(self):
        for version in ("0.6.22", "0.6.23-alpha", "0.6.23-beta.2", config.version()):
            with self.subTest(version):
                self.assertIsNotNone(UPDATE_VERSION.match(version))
                self.assertIsNotNone(RELEASE_VERSION.fullmatch(version))
                self.assertIsNotNone(PRODUCT_VERSION.match(version))


if __name__ == "__main__":
    unittest.main()
