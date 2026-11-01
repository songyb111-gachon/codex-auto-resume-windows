"""MAL only narrows account_switch: its fail hides the card's button and never turns the capability off.

The v0.6.20 final's live acceptance (A8, 2026-11-01): the update from v0.6.20-beta.4 brought MAL's fail, and with MAL
among account_switch's `measurements` the fail was a MEASUREMENT_FAILED warning the owner had not confirmed - a tripwire
(arming.standing) - so the watched account_switch went off (actor tripwire, reason measurement_failed) and the account
card vanished. Only the card's button rests on MAL (control/account.offered reads its verdict); the card's read rests on
MA. A measurement that only narrows is kept out of `measurements` and read where it is used, as M2b, MQO and MQP are.

v0.6.20 final: the button now ends with a restart of Codex the person agrees to, and rests on MALR - that route,
measured - in place of MAL, which stays the record of the plain route. The narrowing is the same, read from MALR.

Every read is a fake and every home a temporary folder: no Codex runs and no account is read.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import measured, registry, statement  # noqa: E402
from codex_auto_resume_advanced.codex import account  # noqa: E402
from codex_auto_resume_advanced.control import account as card  # noqa: E402
from codex_auto_resume_advanced.registry import ACCOUNT_SWITCH  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning, Measurement,  # noqa: E402
                                                   Verdict)

CAP = "account_switch"
# The measurement the button rests on (v0.6.20 final: MALR, the sign-in and then the product's restart of Codex).
NARROWS = Measurement.MALR
ONE = {"account": {"type": "chatgpt", "email": "someone@example.com", "planType": "plus"}}


class MalFailTests(ac.AdvancedCase):
    """An installation with account_switch on, or watched, before MAL had a verdict meets MAL's fail."""

    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="usage_probe")
        # As the owner's beta.4 had it: MA passed on the Codex in force, MAL not measured yet.
        self.measured = {Measurement.MA: (Verdict.PASS, ac.ENGINE)}
        self.rt = self.runtime(ACCOUNT_SWITCH)
        self.rt.arming.catalogs = statement.CATALOGS
        card._SWITCHES.clear()
        self.addCleanup(card._SWITCHES.clear)

    def on(self, state):
        result = self.rt.arming.arm(CAP, state=state, revision=ACCOUNT_SWITCH.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(ACCOUNT_SWITCH)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)

    def mal_fails(self):
        self.measured = dict(self.measured, **{NARROWS: (Verdict.FAIL, ac.ENGINE)})

    def codes(self):
        with self.rt.state._read() as connection:
            return [found[0] for found in connection.execute("SELECT code FROM journal")]

    def stays(self, state):
        self.on(state)
        self.mal_fails()
        self.assertEqual(self.rt.states(fresh=True).get(CAP), state, "MAL's fail turned it off")
        row = self.rt.state.arming()[CAP]
        self.assertEqual((row["state"], row["actor"], row["reason"]), (state, Actor.DASHBOARD, None))
        self.assertNotIn("account.tripped", " ".join(self.codes()))
        # The statement says MAL failed (it narrows the capability, as MK, MQ, MS and MTOK do); nothing trips on it.
        self.assertIn(ArmingWarning.MEASUREMENT_FAILED, self.rt.arming.warnings(ACCOUNT_SWITCH))
        listed = next(item for item in self.rt.arming.listing()["capabilities"] if item["id"] == CAP)
        self.assertEqual((listed["state"], listed["reason"], listed["notice"]), (state, None, None))
        self.assertIn(str(ArmingWarning.MEASUREMENT_FAILED), listed["warnings"])
        return card.view(self.rt, reader=lambda paths: account.parse(ONE))

    def test_on_it_stays_on_with_the_card_and_without_the_button(self):
        """Fails with the fix reverted: the tripwire turns it off (measurement_failed) and the card is refused."""
        answer = self.stays(ArmingState.ARMED)
        self.assertEqual((answer["done"], answer["present"], answer["plan"], answer["button"]),
                         (True, True, "plus", False))
        self.assertIs(card.offered(self.rt), False)

    def test_watched_it_stays_watched_and_the_card_still_reads(self):
        """Fails with the fix reverted: the owner's case at A8 - watched, then off by the tripwire."""
        answer = self.stays(ArmingState.SHADOW)
        self.assertEqual((answer["done"], answer["present"], answer["button"]), (True, True, False))

    def test_the_button_follows_malr(self):
        """The narrowing itself is unchanged: on, the button is offered once MALR passed on the Codex in force."""
        self.on(ArmingState.ARMED)
        self.mal_fails()
        self.assertFalse(card.offered(self.rt))
        self.measured[NARROWS] = (Verdict.PASS, ac.ENGINE)
        self.assertTrue(card.offered(self.rt))
        self.measured[NARROWS] = (Verdict.PASS, "0.1.0")
        self.assertFalse(card.offered(self.rt), "a pass on another Codex is no pass here")


class NarrowingAuditTests(unittest.TestCase):
    """Which capability the shipped table's fails warn of (2026-11-01 audit): each fail left among a capability's
    `measurements` is one its route rests on - confirmed by every person who turned it on, since each failed before
    its capability shipped - and none is a fail that only narrows."""

    def test_every_failed_measurement_in_a_capability_is_one_its_route_rests_on(self):
        failed = {m for m, (verdict, _on) in measured.MEASURED.items() if verdict == Verdict.FAIL}
        found = {definition.id: sorted(str(m) for m in definition.measurements if m in failed)
                 for definition in registry.DEFINITIONS}
        found = {key: value for key, value in found.items() if value}
        self.assertEqual(found, {"goal_continuation": ["m2"], "codex_chat": ["mc2"], "steer_send": ["msteer2"]})
        self.assertNotIn(Measurement.MAL, ACCOUNT_SWITCH.measurements)
        self.assertNotIn(Measurement.MALR, ACCOUNT_SWITCH.measurements)
        self.assertEqual(ACCOUNT_SWITCH.measurements, (Measurement.MA,))
        self.assertEqual(ACCOUNT_SWITCH.narrowed_by, (Measurement.MALR,))

    def test_mal_is_kept_as_the_record_of_the_plain_route(self):
        """MAL's fail stays in the shipped table, and no longer narrows account_switch: the button rests on MALR."""
        self.assertEqual(measured.MEASURED[Measurement.MAL][0], Verdict.FAIL)
        self.assertNotIn(Measurement.MAL, ACCOUNT_SWITCH.narrowed_by)


if __name__ == "__main__":
    unittest.main()
