"""v0.6.19: the Dashboard's own report (core's ownreport/) and the advanced edition's compatibility report write a
version's body with one code - so, of the same records, the same body.

For each fixture home without a spend ledger (reportfixtures.SCENARIOS, the homes the reporter's goldens were made
from), every version the own report lists carries exactly the body the advanced reader (report/records.py `read`)
writes for that version, but for the progress counts, which only the advanced reader takes from Codex's history and
the own report leaves null; and what both leave out as hidden, carried another way or never placed is the same. A
home with a ledger is where they part on purpose: the own report reads no ledger, and in a home that holds the
advanced edition's state it counts no claimed record a mark of the state does not tell apart.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import reportfixtures as fixtures  # noqa: E402
from codex_auto_resume import ownreport  # noqa: E402
from codex_auto_resume.ownreport import reading  # noqa: E402
from codex_auto_resume_advanced.report import records  # noqa: E402

NO_LEDGER = ("state3_no_ledger", "state4_watcher_newer", "state4_empty")


def without_progress(body):
    body = json.loads(json.dumps(body))
    for row in body["records"]:
        row["progress_items"] = None
    return body


class OneCodeTests(unittest.TestCase):
    def home(self, name):
        home, _asked = fixtures.scenario(name)
        self.addCleanup(home.close)
        return home

    def test_each_version_the_own_report_lists_has_the_advanced_readers_body(self):
        for name in NO_LEDGER:
            home = self.home(name)
            with self.subTest(name), fixtures.isolated(home):
                found = reading.read_all(home.paths, view=home.raw_view)
                self.assertTrue(found["versions"])
                for entry in found["versions"]:
                    advanced = records.read(home.paths, home.codex, entry["codex_version"], now=fixtures.NOW,
                                            view=home.raw_view)
                    self.assertEqual(entry["body"], without_progress(advanced["body"]), entry["codex_version"])
                    for key in ("hidden", "another_route", "beyond_reach", "unplaced"):
                        self.assertEqual(found["left_out"][key], advanced["left_out"][key], key)

    def test_the_own_report_of_a_fixture_passes_its_own_check(self):
        home = self.home("state3_no_ledger")
        with fixtures.isolated(home):
            written = ownreport.write(home.paths, now=fixtures.NOW, view=home.raw_view)
        self.assertNotIn("refusal", written)
        self.assertEqual([entry["codex_version"] for entry in written["versions"]],
                         [fixtures.ENGINE, fixtures.OLDER])

    def test_a_home_with_the_advanced_editions_state_counts_no_claimed_record_it_cannot_tell(self):
        home = self.home("state4_ledger2")
        # The ledger's own folder, with the marker the advanced edition writes when it makes it.
        from codex_auto_resume import config
        (home.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        with fixtures.isolated(home):
            found = reading.read_all(home.paths, view=home.raw_view)
        claimed = sum(1 for row in fixtures.SCENARIOS["state4_ledger2"][0]["rows"]
                      if row["last_claim_at"] and not row["history_hidden_at"])
        self.assertGreater(found["left_out"]["beyond_reach"], 0)
        self.assertLessEqual(found["left_out"]["beyond_reach"] + found["left_out"]["another_route"], claimed)
        for entry in found["versions"]:
            for row in entry["body"]["records"]:
                self.assertIsNone(row["delivered_at"], "a delivered record was claimed, so it is left out")


if __name__ == "__main__":
    unittest.main()
