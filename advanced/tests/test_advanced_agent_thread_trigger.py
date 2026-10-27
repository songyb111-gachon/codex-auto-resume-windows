"""Issue #54, the advanced edition: with "Recover every conversation but Codex's own" on, an agent-made conversation
(thread_source agent_created_thread) is taken up exactly where the standard edition takes it up - the failed turn was
started from the input box (rollout task_started, turn_attribution.turn_trigger "composer") - by core's one rule,
codex/values.taken_thread_source; any other trigger, none or no rollout leaves it out, and Codex's other own kinds
stay out whatever started the turn.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from takingcase import TakingCase  # noqa: E402
import codexsim  # noqa: E402
from codex_auto_resume_advanced.registry import EVERY_CONVERSATION  # noqa: E402

AGENT = "agent_created_thread"


class AgentThreadTriggerTests(TakingCase):
    DEFINITION = EVERY_CONVERSATION

    def fail(self, h, trigger, label=AGENT):
        thread, turn = codexsim.new_id(), codexsim.new_id()
        h.home.add_thread(thread, thread_source=label)
        h.backend.loaded_map[thread] = "loaded"
        if trigger is not False:
            payload = {"type": "task_started", "turn_id": turn}
            if trigger is not None:
                payload["turn_attribution"] = {"turn_id": turn, "turn_trigger": trigger}
            h.home._append(thread, [{"type": "event_msg", "payload": payload}])
        h.now += 1
        h.home.fail_usage(thread, turn_id=turn)
        h.tick()
        return thread, h.records(thread)

    def test_on_a_turn_started_from_the_input_box_is_taken_up(self):
        self.armed()
        thread, records = self.fail(self.h, "composer")
        self.assertEqual(len(records), 1)

    def test_on_any_other_trigger_none_or_no_rollout_event_is_left_out(self):
        self.armed()
        for trigger in ("queue", "goal", "guardian_review", "app_tool_send_message", None, False):
            with self.subTest(trigger):
                self.assertEqual(self.fail(self.h, trigger)[1], [])

    def test_on_codexs_other_own_kinds_stay_out_from_the_input_box_too(self):
        self.armed()
        for label in ("subagent", "guardian_review", "memory_consolidation"):
            with self.subTest(label):
                self.assertEqual(self.fail(self.h, "composer", label)[1], [])

    def test_off_the_standard_rule_is_the_same(self):
        self.plugged(self.advanced())
        self.assertEqual(len(self.fail(self.h, "composer")[1]), 1)
        self.assertEqual(self.fail(self.h, "queue")[1], [])


if __name__ == "__main__":
    unittest.main()
