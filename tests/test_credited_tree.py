"""Every credit in this tree's contributors list stands on a report whose sender chose it (build/community_file.py CREDIT).

The filer runs this on the tree that would become main before it writes (community_file.FIXED_MODULES): a line in the
filer's credit sentence names a login that has a report filed under it for that Codex version saying `"credit": true` -
or one the maintainer withdrew since, whose credit stays (a withdrawal leaves a credit as it is) - and never the owner.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

import community_file as filer  # noqa: E402
import community_report as reader  # noqa: E402

LINE = re.compile(r"- \[@([A-Za-z0-9-]{1,39})\]\(https://github\.com/\1\) reported compatibility on Codex "
                  r"(codex-cli \S{1,40})\.")


def withdrawn() -> set:
    path = ROOT / filer.WITHDRAWN
    if not path.is_file():
        return set()
    document = json.loads(path.read_text(encoding="utf-8"))
    return {(entry.get("login"), "codex-cli " + str(entry.get("version")))
            for entry in document.get("withdrawn", []) if isinstance(entry, dict)}


class CreditedTreeTests(unittest.TestCase):
    def test_every_credit_line_stands_on_a_report_that_chose_it(self):
        text = (ROOT / filer.CONTRIBUTORS).read_text(encoding="utf-8")
        gone = withdrawn()
        for found in LINE.finditer(text):
            login, version = found.groups()
            with self.subTest(login=login, version=version):
                self.assertTrue(filer.credit_login(login), "a credit names the owner or no person")
                path = ROOT / reader.canonical_path(login, version)
                if path.is_file():
                    self.assertTrue(reader.credited(json.loads(path.read_text(encoding="utf-8"))),
                                    "%s did not choose credit" % path.name)
                else:
                    self.assertIn((login, version), gone, "a credit with no report behind it")
                self.assertEqual(text.count("](https://github.com/%s)" % login) >= 1, True)

    def test_a_person_is_listed_once_in_the_credit_sentence(self):
        text = (ROOT / filer.CONTRIBUTORS).read_text(encoding="utf-8")
        logins = [found.group(1).lower() for found in LINE.finditer(text)]
        self.assertEqual(len(logins), len(set(logins)))


if __name__ == "__main__":
    unittest.main()
