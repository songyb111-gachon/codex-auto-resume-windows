# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""A part hidden or held back because its measurement failed says so (the owner, 2026-10-31; v0.6.20 final).

The Codex account card said its sign-out and sign-in button is missing "until it is measured on this Codex" - after MAL had
been measured on this Codex and had failed. Each card line that rests on a measurement now follows the verdict for the Codex
in force: no record or a pass on another Codex is "not measured yet" (the old words), a failed record is "its measurement
failed" (new words, in all eighteen catalogs). The bridge's answers carry which one - `measurement_failed` (MAL),
`count_failed` (MK), `after_turn_failed` (MT), `count_failed` and `credit_failed` (MU, MR) - from the same
`arming.verdict` the old booleans read, so a fail on any Codex counts, as a statement's warnings read it.

Every answer here is the real control module's over a runtime of the test's own; nothing reads Codex.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_failed_measurement_words.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.codex import account  # noqa: E402
from codex_auto_resume_advanced.control import account as card, keepgoing, prompts, resets  # noqa: E402
from codex_auto_resume_advanced.registry import ACCOUNT_SWITCH  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, Measurement, Verdict  # noqa: E402

CAP = "account_switch"
ONE = {"account": {"type": "chatgpt", "email": "someone@example.com", "planType": "plus"}}
OLDER = "codex-cli 0.150.0"
# (the line's words, its failed words) - and the English each says, so that the two never read the same.
PAIRS = (("page.account.guidance", "page.account.guidance_failed"), ("page.keep.capped", "page.keep.capped_failed"),
         ("page.queue.unproven", "page.queue.unproven_failed"), ("page.resets.unproven", "page.resets.unproven_failed"),
         ("page.resets.ask.note", "page.resets.ask.note_failed"))
LOCALES = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales"


class AnswerTests(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="usage_probe")
        self.rt = self.runtime(ACCOUNT_SWITCH)
        self.rt.arming.catalogs = statement.CATALOGS
        card._SWITCHES.clear()
        self.addCleanup(card._SWITCHES.clear)
        result = self.rt.arming.arm(CAP, state="shadow", revision=ACCOUNT_SWITCH.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(ACCOUNT_SWITCH)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)

    def read(self):
        return card.view(self.rt, reader=lambda paths: account.parse(ONE))

    def answers(self):
        return {"account": self.read()["measurement_failed"], "keep": keepgoing.view(self.rt)["count_failed"],
                "after_turn": prompts.view(self.rt)["after_turn_failed"],
                "count": resets.view(self.rt)["count_failed"], "credit": resets.view(self.rt)["credit_failed"]}

    def test_no_record_is_not_a_failure_and_the_old_booleans_stay(self):
        self.assertEqual(self.answers(), {"account": False, "keep": False, "after_turn": False, "count": False,
                                          "credit": False})
        self.assertTrue(keepgoing.view(self.rt)["count_capped"])
        self.assertTrue(prompts.view(self.rt)["after_turn_unproven"])
        self.assertTrue(resets.view(self.rt)["count_unproven"])

    def test_a_pass_here_is_not_a_failure(self):
        self.measured = {m: (Verdict.PASS, ac.ENGINE) for m in
                         (Measurement.MALR, Measurement.MK, Measurement.MT, Measurement.MU, Measurement.MR)}
        self.assertEqual(set(self.answers().values()), {False})
        self.assertFalse(keepgoing.view(self.rt)["count_capped"])

    def test_a_pass_on_another_codex_is_unmeasured_here_not_failed(self):
        self.measured = {m: (Verdict.PASS, OLDER) for m in
                         (Measurement.MALR, Measurement.MK, Measurement.MT, Measurement.MU, Measurement.MR)}
        self.assertEqual(set(self.answers().values()), {False})
        self.assertTrue(keepgoing.view(self.rt)["count_capped"])

    def test_a_failed_record_is_a_failure_for_the_part_it_rests_on_and_for_no_other(self):
        for measurement, name in ((Measurement.MALR, "account"), (Measurement.MK, "keep"), (Measurement.MT, "after_turn"),
                                  (Measurement.MU, "count"), (Measurement.MR, "credit")):
            with self.subTest(measurement):
                self.measured = {measurement: (Verdict.FAIL, ac.ENGINE)}
                self.assertEqual({key for key, found in self.answers().items() if found}, {name})

    def test_a_failure_on_another_codex_counts_as_a_warning_reads_it(self):
        self.measured = {Measurement.MALR: (Verdict.FAIL, OLDER)}
        self.assertTrue(self.read()["measurement_failed"])

    def test_the_account_button_stays_hidden_after_a_failure(self):
        self.measured = {Measurement.MALR: (Verdict.FAIL, ac.ENGINE)}
        self.assertEqual((self.read()["button"], self.read()["measurement_failed"]), (False, True))


class WordsTests(unittest.TestCase):
    @staticmethod
    def catalog(locale):
        return json.loads((LOCALES / (locale + ".json")).read_text(encoding="utf-8"))

    def test_each_failed_line_is_in_every_language_and_says_something_else(self):
        english = self.catalog("en")
        for locale in l10n.LOCALES:
            table = self.catalog(locale)
            for old, failed in PAIRS:
                with self.subTest(locale=locale, key=failed):
                    self.assertTrue(table[failed].strip())
                    self.assertNotEqual(table[failed], table[old])
                    self.assertEqual(l10n.placeholders(table[failed]), l10n.placeholders(english[failed]))

    def test_the_failed_lines_say_failed_and_the_old_ones_say_measured_in_english(self):
        english = self.catalog("en")
        for old, failed in PAIRS:
            self.assertIn("failed", english[failed])
            self.assertNotIn("until", english[failed].lower())
            self.assertIn("measured", english[old])

    def test_the_window_asks_for_every_failed_line(self):
        asked = set(statement.PAGE_KEYS)
        for _old, failed in PAIRS:
            self.assertIn(failed, asked)


if __name__ == "__main__":
    unittest.main()
