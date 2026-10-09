"""Codex's usage read as the reset actions keep it (codex/credits.py): core's windows, the count of reset
credits and when the soonest expires - never a credit's id, title or description, the account or the plan.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401  (puts src and advanced/src on the path)
from codex_auto_resume.codex.usage import parse_usage  # noqa: E402
from codex_auto_resume.domain import usage as readings  # noqa: E402
from codex_auto_resume_advanced.codex import credits  # noqa: E402
from codex_auto_resume_advanced.vocabulary import SpendOutcome  # noqa: E402

RESET = 1_800_003_600


def credit(expires=1_801_000_000, status="available", **changes):
    made = {"id": "rc_9f8e7d6c5b4a-ExampleUser", "title": "Reset credit for ExampleUser",
            "description": "Thanks for waiting through the outage", "grantedAt": 1_799_000_000,
            "expiresAt": expires, "resetType": "codexRateLimits", "status": status}
    made.update(changes)
    return made


def reply(count=2, listed=None, *, used=100, allowed=False):
    return {"accountId": "acct_ExampleUser_1234", "planType": "pro",
            "rateLimitsByLimitId": {"codex": {"limitId": "codex", "limitName": "ExampleUser's plan",
                                              "planType": "pro", "credits": {"hasCredits": True, "unlimited": False,
                                                                             "balance": "17.5"},
                                              "primary": {"usedPercent": used, "windowDurationMins": 300,
                                                          "resetsAt": RESET}}},
            "ordinaryUsageAllowed": allowed,
            "rateLimitResetCredits": {"availableCount": count,
                                      "credits": [credit(), credit(1_800_500_000)] if listed is None else listed}}


class ParseTests(unittest.TestCase):
    def test_only_the_count_the_soonest_expiry_and_cores_windows_are_kept(self):
        found = credits.parse(reply())
        self.assertEqual(found, {"windows": readings.windows_of(parse_usage(reply())), "credits": 2,
                                 "expiry_known": True, "nearest_expiry": 1_800_500_000,
                                 "ordinary_usage_allowed": False})
        text = json.dumps(found)
        for secret in ("rc_9f8e", "ExampleUser", "outage", "pro", "acct", "17.5", "1799000000", "codexRateLimits"):
            self.assertNotIn(secret, text)

    def test_a_count_that_is_not_a_whole_number_is_no_count_and_no_expiry(self):
        for count in (None, "2", 2.0, True, -1, 10_000):
            with self.subTest(count=count):
                found = credits.parse(reply(count))
                self.assertIsNone(found["credits"])
                self.assertFalse(found["expiry_known"])

    def test_details_left_out_are_an_expiry_that_cannot_be_read(self):
        found = credits.parse(dict(reply(), rateLimitResetCredits={"availableCount": 2, "credits": None}))
        self.assertEqual((found["credits"], found["expiry_known"], found["nearest_expiry"]), (2, False, None))

    def test_a_capped_list_with_no_available_credit_is_an_expiry_that_cannot_be_read(self):
        for listed in ([], [credit(status="redeemed")]):
            with self.subTest(listed=listed):
                self.assertFalse(credits.parse(reply(2, listed))["expiry_known"])

    def test_a_credit_that_never_expires_is_a_known_expiry_of_none(self):
        found = credits.parse(reply(1, [credit(None)]))
        self.assertEqual((found["expiry_known"], found["nearest_expiry"]), (True, None))
        found = credits.parse(reply(2, [credit(None), credit(1_800_700_000)]))
        self.assertEqual((found["expiry_known"], found["nearest_expiry"]), (True, 1_800_700_000))

    def test_no_credit_is_a_known_expiry_whatever_the_list(self):
        self.assertEqual(credits.parse(reply(0, None))["expiry_known"], True)
        self.assertEqual(credits.parse(reply(0, []))["nearest_expiry"], None)

    def test_a_malformed_credit_or_expiry_is_an_expiry_that_cannot_be_read(self):
        for listed in ([credit("soon")], [credit(1.8e9)], [credit(True)], ["credit"], [credit(status=None)],
                       [credit(-5)], "credits"):
            with self.subTest(listed=listed):
                found = credits.parse(reply(2, listed))
                self.assertFalse(found["expiry_known"])
                self.assertIsNone(found["nearest_expiry"])

    def test_a_reply_of_another_shape_is_no_reading_at_all(self):
        for value in (None, [], "usage", {"rateLimitResetCredits": "x"}):
            with self.subTest(value=value):
                self.assertEqual(credits.parse(value), {"windows": None, "credits": None, "expiry_known": False,
                                                        "nearest_expiry": None, "ordinary_usage_allowed": None})

    def test_whether_details_were_listed(self):
        self.assertTrue(credits.details_listed(reply()))
        self.assertTrue(credits.details_listed(reply(0, [])))
        self.assertFalse(credits.details_listed(dict(reply(), rateLimitResetCredits={"availableCount": 1})))
        self.assertFalse(credits.details_listed(None))

    def test_full_windows_are_those_at_a_hundred_with_a_reset_time(self):
        self.assertEqual(len(credits.full(credits.parse(reply())["windows"])), 1)
        self.assertEqual(credits.full(credits.parse(reply(used=99))["windows"]), [])
        self.assertEqual(credits.full(None), [])


class OutcomeTests(unittest.TestCase):
    def test_codexs_four_outcomes_in_this_editions_words(self):
        self.assertEqual({word: credits.outcome({"outcome": word}) for word in credits.OUTCOMES},
                         {"reset": SpendOutcome.RESET, "nothingToReset": SpendOutcome.NOTHING_TO_RESET,
                          "noCredit": SpendOutcome.NO_CREDIT, "alreadyRedeemed": SpendOutcome.ALREADY_REDEEMED})

    def test_anything_else_is_unknown_never_one_of_the_four(self):
        for value in (None, {}, {"outcome": "Reset"}, {"outcome": "reset_done"}, {"outcome": 1}, "reset", []):
            with self.subTest(value=value):
                self.assertIs(credits.outcome(value), SpendOutcome.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
