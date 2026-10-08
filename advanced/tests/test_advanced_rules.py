"""Rules for Codex's error codes (v0.6.14): a failure nothing classified, paced as the kind a rule names.

Held against the shipped definition and statement and against core's own engine, store and
simulated Codex home (takingcase.py): off, a failure nothing classified waits for the person, as in
the standard edition; armed, one whose code a rule names is taken up at P17 as that rule's kind, waits
as that kind waits, follows that kind's switch, goes as the short standard continuation with its
marker, and counts the rule's hit once; a status outside the rule's range, a code core does not offer,
or a rule removed takes nothing up, or ends what it took up unsent; watched, it only journals; the
unit is spent before the send; past its ceilings nothing is taken up; a send it cannot prove turns it
off; a policy refuses it; and MCP writes no rule.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from codex_auto_resume import failures, settings  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import policy, surfaces  # noqa: E402
from codex_auto_resume_advanced.engine import admitted  # noqa: E402
from codex_auto_resume_advanced.engine.admitted import StructuredRules  # noqa: E402
from codex_auto_resume_advanced.registry import STRUCTURED_RULES  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode, McpTool,  # noqa: E402
                                                   OffReason, Refusal)
from test_engine import T1  # noqa: E402

CAP = "structured_rules"
TAG = "brandNewVariant"
UNNAMED = json.dumps({"codexErrorInfo": TAG, "message": "the secret words"})
# A status no rule of the standard edition's places (failures._status_category): still unknown.
WITH_STATUS = json.dumps({"codexErrorInfo": {"type": TAG, "httpStatusCode": 302}})


class RulesCase(TakingCase):
    DEFINITION = STRUCTURED_RULES

    def rule(self, plug, tag=TAG, low=None, high=None, category="timeout"):
        runtime = plug.runtime
        result = runtime.arming.add_rule(tag, low, high, category, generation=runtime.state.meta()["generation"],
                                         actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        return result["rule"]

    def ruled(self, error=UNNAMED, state="armed", **rule):
        plug = self.armed(state=state)
        made = self.rule(plug, **rule)
        self.failing(error)
        self.h.tick()
        return plug, made


class OffTests(RulesCase):
    def test_off_a_failure_nothing_classified_waits_for_the_person(self):
        self.assertIsNone(self.standard(UNNAMED))
        plug = self.advanced()
        self.plugged(plug)
        self.failing(UNNAMED)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertFalse(plug.runtime.state.exists())


class ArmedTests(RulesCase):
    def test_a_rules_code_is_paced_as_its_kind_and_goes_as_the_short_continuation(self):
        plug, rule = self.ruled()
        row = self.h.record()
        key = row["interruption_id"]
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now),
                         ("unknown", "waiting_backoff", self.h.engine.first_delay("timeout")))
        admission = plug.runtime.state.admission(key)
        self.assertEqual((admission["answer"], admission["rule_id"]), (Alternative.AS_TIMEOUT, rule))
        self.assertEqual(plug.runtime.state.rule_hits(0), {})
        self.h.tick(advance=self.h.engine.first_delay("timeout"))
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))
        self.assertEqual(plug.runtime.state.rule_hits(0), {rule: 1})
        self.assertIn((JournalCode.ACTED, Point.GATES, Alternative.AS_TIMEOUT), self.journal(plug))
        self.assertIn(("rule.matched", None, None), self.journal(plug))
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])

    def test_a_status_outside_the_rules_range_takes_nothing_up(self):
        self.ruled(WITH_STATUS, low=300, high=301)
        self.assertEqual(self.h.records(), [])
        self.h = self.fresh()
        self.ruled(WITH_STATUS, low=300, high=302, category="server_5xx")
        self.assertEqual(self.h.record()["next_retry_at"] - self.h.now, self.h.engine.first_delay("server_5xx"))

    def test_the_kinds_switch_in_settings_is_the_rules_switch_too(self):
        plug = self.armed()
        self.rule(plug)
        self.h.engine.apply_policy(dict(settings.defaults(), recover_timeout=False))
        self.failing(UNNAMED)
        self.h.tick()
        self.assertEqual(self.h.records(), [], "core did not offer the word, so nothing was taken up")

    def test_removing_the_rule_ends_what_it_took_up_unsent(self):
        plug, rule = self.ruled()
        runtime = plug.runtime
        self.assertTrue(runtime.arming.remove_rule(rule, generation=runtime.state.meta()["generation"],
                                                   actor=Actor.DASHBOARD)["done"])
        self.h.tick(advance=self.h.engine.first_delay("timeout"))
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("terminal_failure", "not_recoverable"))
        self.assert_no_send()

    def test_a_code_the_product_knows_or_one_naming_a_decision_is_never_a_rule(self):
        plug = self.armed()
        runtime = plug.runtime
        for tag, refusal in (("internalServerError", Refusal.RULE_KNOWN), ("unauthorized", Refusal.RULE_KNOWN),
                             ("policyRefused", Refusal.RULE_DECISION), ("userCancelled", Refusal.RULE_DECISION)):
            with self.subTest(tag):
                result = runtime.arming.add_rule(tag, None, None, "timeout",
                                                 generation=runtime.state.meta()["generation"], actor=Actor.DASHBOARD)
                self.assertEqual(result["refusal"], refusal)
        self.assertEqual(runtime.state.rules(), [])


class ShadowNeverActsTests(RulesCase):
    def test_watched_it_journals_what_it_would_have_done_and_takes_nothing_up(self):
        plug, _rule = self.ruled(state="shadow")
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.WOULD_HAVE, Point.ADMISSION, Alternative.AS_TIMEOUT), self.journal(plug))
        self.assertEqual(self.spends(plug), [])


class SpendBeforeSendTests(RulesCase):
    def test_the_unit_is_spent_before_the_continuation_goes(self):
        plug, _rule = self.ruled()
        key = self.h.record()["interruption_id"]
        seen = []
        self.h.backend.on_send = lambda thread, prompt: seen.append(self.spends(plug))
        self.h.tick(advance=self.h.engine.first_delay("timeout"))
        self.assertEqual(seen, [[(CAP, T1, key)]])


class CeilingTests(RulesCase):
    def test_past_its_ceiling_nothing_is_taken_up(self):
        plug = self.armed()
        self.rule(plug)
        self.fill(plug, STRUCTURED_RULES.ceilings.per_conversation, at=self.h.now - 3600)
        self.failing(UNNAMED)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.CEILING, Point.ADMISSION, Alternative.AS_TIMEOUT), self.journal(plug))


class TripwireTests(RulesCase):
    def test_a_send_it_paid_for_gone_unknown_turns_it_off_and_is_never_sent_again(self):
        plug, _rule = self.ruled()
        self.h.backend.default_outcome = "unknown"
        self.h.tick(advance=self.h.engine.first_delay("timeout"))
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        for _ in range(8):
            self.h.tick(advance=900)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_hook_that_raises_trips_it_and_what_it_took_up_ends_unsent(self):
        plug, _rule = self.ruled()
        with patch.object(StructuredRules, "gate", side_effect=RuntimeError("boom")):
            self.h.tick(advance=self.h.engine.first_delay("timeout"))
        self.assertEqual(plug.runtime.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)
        self.assertEqual(self.h.record()["state"], "terminal_failure")
        self.assert_no_send()


class PolicyTests(RulesCase):
    def test_forbidden_it_reads_off_and_takes_nothing_up(self):
        plug = self.armed()
        self.rule(plug)
        self.policy = policy.Policy(forbid=True)
        plug.runtime.states(fresh=True)
        self.failing(UNNAMED)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        result = plug.runtime.arming.arm(CAP, state="armed", revision=1, generation=plug.runtime.state.meta()
                                         ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertEqual(result["refusal"], Refusal.FORBIDDEN_BY_POLICY)


class McpTests(RulesCase):
    def test_mcp_writes_no_rule_and_arms_nothing(self):
        plug = self.armed()
        runtime = plug.runtime
        refused = surfaces.mcp(runtime, {"request": "call", "tool": McpTool.DISARM_ADVANCED_CAPABILITY,
                                         "arguments": {"capability": CAP, "tag": TAG}})
        self.assertIn("refused", refused)
        self.assertEqual(runtime.arming.add_rule(TAG, None, None, "timeout", generation=runtime.state.meta()
                                                 ["generation"], actor=Actor.MCP)["refusal"],
                         Refusal.NOT_THE_DASHBOARD)
        self.assertEqual(runtime.state.rules(), [])
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.ARMED)


class CodeTests(unittest.TestCase):
    """The capability's code on its own."""

    RULES = [{"rule_id": 3, "tag": TAG, "status_from": 500, "status_to": 503, "category": "server_5xx",
              "known": False},
             {"rule_id": 5, "tag": TAG, "status_from": None, "status_to": None, "category": "timeout", "known": False},
             {"rule_id": 7, "tag": "serverOverloaded", "status_from": None, "status_to": None,
              "category": "timeout", "known": True}]

    class Scoped:
        def __init__(self, rules, row=None):
            self._rules, self.row = rules, row

        def rules(self):
            if isinstance(self._rules, Exception):
                raise self._rules
            return self._rules

        def admission(self, key):
            return self.row

    def code(self, rules=RULES, row=None):
        made = StructuredRules(None)
        made.bind(self.Scoped(rules, row))
        return made

    def test_the_lowest_numbered_rule_that_names_the_code_and_holds_the_status(self):
        self.assertEqual(admitted.matching(self.RULES, TAG, 503)["rule_id"], 3)
        self.assertEqual(admitted.matching(self.RULES, TAG, 504)["rule_id"], 5)
        self.assertEqual(admitted.matching(self.RULES, TAG, None)["rule_id"], 5)
        self.assertIsNone(admitted.matching(self.RULES, "serverOverloaded", None), "a code now known")
        self.assertIsNone(admitted.matching(self.RULES, "otherVariant", None))
        code = self.code()
        facts = {"category": "unknown", "code": TAG, "status": 501}
        self.assertIs(code.admission(facts), Alternative.AS_SERVER_5XX)
        self.assertEqual(code.rule_for(facts, Alternative.AS_SERVER_5XX), 3)
        self.assertIsNone(code.rule_for(facts, Alternative.AS_TIMEOUT))
        self.assertIs(code.admission(dict(facts, category="terminal_auth")), DEFER)
        self.assertIs(self.code(RuntimeError("locked")).admission(facts), DEFER)

    def test_at_known_failure_only_while_its_rule_is_there(self):
        record = {"category": "unknown", "interruption_id": ac.KEY}
        self.assertIs(self.code(row={"rule_id": 5}).gate("known_failure", record, {}), Alternative.AS_TIMEOUT)
        self.assertIs(self.code(row={"rule_id": 9}).gate("known_failure", record, {}), DEFER, "removed")
        self.assertIs(self.code(row={"rule_id": 7}).gate("known_failure", record, {}), DEFER, "now known")
        self.assertIs(self.code(row=None).gate("known_failure", record, {}), DEFER)
        self.assertIs(self.code(row={"rule_id": 5}).gate("usage", record, {}), DEFER)
        self.assertIs(self.code(RuntimeError("locked"), row={"rule_id": 5}).gate("known_failure", record, {}),
                      Alternative.HOLD)

    def test_every_word_it_answers_paces_a_temporary_kind(self):
        self.assertEqual(set(admitted.AS_FOR), set(failures.TRANSIENT))


if __name__ == "__main__":
    unittest.main()
