"""Sleep, hibernate or shut down after tasks a person picked (power_after_tasks, v0.6.20, Discussion #57).

The advanced half: the capability is offered with its statement (departing from H14 only) in every language and its
place on the page; a task's end followed through any usage limit and its recovery, ids and statuses only; the endings a
person chose to count; the answer at P21 only for the arming its list belongs to, and only while the capability is on;
the card's arming - refused unless it is on and each conversation runs now, then core's own power action armed once for
tasks and the list written with its nonce; and turning the capability off turning such an arming off.

Core's half (the countdown, the stop for one batch, every condition of core's own) is tests/test_power_action_tasks.py.
Codex's history, core's records and Windows are the tests' own: nothing here reads this PC's Codex or asks Windows.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_power_tasks.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import l10n, managed  # noqa: E402
from codex_auto_resume.control import Control, policy as control_policy, poweraction as control_power  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point, guard  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.control import powertasks as card  # noqa: E402
from codex_auto_resume_advanced.engine import powertasks  # noqa: E402
from codex_auto_resume_advanced.registry import POWER_AFTER_TASKS, problems  # noqa: E402

THREAD, OTHER = ac.THREAD, ac.OTHER_THREAD
TURN = "11111111-1111-7111-8111-111111111111"
RECOVERY = "22222222-2222-7222-8222-222222222222"
AGAIN = "33333333-3333-7333-8333-333333333333"
NONCE = "fedcba9876543210"


def record(n, state, turn=TURN, *, thread=THREAD, recovery=None, parent=None):
    return {"interruption_id": "%064x" % n, "thread_id": thread, "turn_id": turn, "state": state,
            "recovery_turn_id": recovery, "parent_interruption_id": parent, "detected_at": 1000 + n}


class Statuses:
    """codex/turns.Turns' two reads, from a table: {turn id: status}; `latest` {thread: (turn, status)}."""

    def __init__(self, statuses=None, latest=None, broken=False):
        self.statuses, self.latest_of, self.broken, self.asked = dict(statuses or {}), dict(latest or {}), broken, []

    def status(self, thread, turn):
        self.asked.append((thread, turn))
        if self.broken:
            raise RuntimeError("unreadable")
        return self.statuses.get(turn)

    def latest(self, thread):
        found = self.latest_of.get(thread)
        if found is None:
            return None
        return type("Turn", (), {"turn_id": found[0], "status": found[1]})()


class FakePort:
    def available(self, action):
        return True, None

    def act(self, action):
        raise AssertionError("nothing here acts")


# ------------------------------------------------------------------------------ the definition
class DefinitionTests(unittest.TestCase):
    def test_it_is_offered_and_departs_from_h14_alone(self):
        self.assertEqual(problems(POWER_AFTER_TASKS), [])
        self.assertIs(registry.REGISTRY.get("power_after_tasks"), POWER_AFTER_TASKS)
        self.assertEqual(POWER_AFTER_TASKS.departs_from, ("H14",))
        self.assertEqual(POWER_AFTER_TASKS.points, frozenset({Point.POWER}))
        self.assertEqual(registry.REGISTRY.at(Point.POWER), (POWER_AFTER_TASKS,), "the one answer at P21")

    def test_its_place_is_the_end_of_group_two(self):
        shown = [definition.id for definition in registry.shown(registry.REGISTRY)]
        self.assertEqual(shown[shown.index("usage_analytics") + 1], "power_after_tasks")
        self.assertLess(shown.index("power_after_tasks"), shown.index("empty_response"), "before group 3")

    def test_its_statement_and_card_words_are_in_every_language(self):
        self.assertEqual(statement.CATALOGS.missing(POWER_AFTER_TASKS), [])
        keys = [key for key in statement.PAGE_KEYS if "powertasks" in key or "power_after_tasks" in key
                or key.endswith("power_no_turn") or key.endswith("power_refused")]
        self.assertEqual(len(keys), 17)
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                own = statement.CATALOGS.own(locale)
                self.assertTrue(own[statement.name_key("power_after_tasks")].strip())
                self.assertIn("H14", own["statement.power_after_tasks.departs"])
                for key in keys:
                    self.assertTrue(own.get(key, "").strip(), key)
                for token in ("{n}", "{action}", "{grace}"):
                    self.assertIn(token, own["page.confirm.power_after_tasks"])


# ------------------------------------------------------------------------------ one task's end
class EndTests(unittest.TestCase):
    def end(self, records, statuses):
        return powertasks.end_of({"thread_id": THREAD, "turn_id": TURN}, records, Statuses(statuses).status)

    def test_a_turn_with_no_cut_off_ends_as_codex_says(self):
        for status, end in (("inProgress", "running"), ("completed", "completed"), ("failed", "failed"),
                            ("interrupted", "interrupted"), ("other", "unknown"), (None, "unknown")):
            with self.subTest(status):
                self.assertEqual(self.end([], {TURN: status} if status else {}), end)

    def test_a_usage_limit_waits_for_its_recovery_and_the_recovery_turn_decides(self):
        """Recovery first: a cut-off waiting or on its way is running, and the task's real end is its recovery's."""
        for state in ("waiting_reset", "waiting_for_usage", "claimed", "submitted"):
            with self.subTest(state):
                self.assertEqual(self.end([record(1, state)], {TURN: "failed"}), "running")
        recovered = record(1, "recovered", recovery=RECOVERY)
        self.assertEqual(self.end([recovered], {TURN: "failed", RECOVERY: "inProgress"}), "running")
        self.assertEqual(self.end([recovered], {TURN: "failed", RECOVERY: "completed"}), "completed")
        self.assertEqual(self.end([record(1, "recovered")], {TURN: "failed"}), "running", "no recovery turn yet")

    def test_a_recovery_cut_off_again_is_followed_to_its_end(self):
        chain = [record(1, "recovered", recovery=RECOVERY),
                 record(2, "recovered", RECOVERY, recovery=AGAIN, parent="%064x" % 1)]
        self.assertEqual(self.end(chain, {TURN: "failed", RECOVERY: "failed", AGAIN: "completed"}), "completed")
        given_up = [record(1, "recovered", recovery=RECOVERY), record(2, "retry_budget_exhausted", RECOVERY, parent="%064x" % 1)]
        self.assertEqual(self.end(given_up, {TURN: "failed", RECOVERY: "failed"}), "failed")
        stopped = [record(1, "stopped_by_user")]
        self.assertEqual(self.end(stopped, {TURN: "interrupted"}), "interrupted")

    def test_unreadable_is_unknown(self):
        task = {"thread_id": THREAD, "turn_id": TURN}
        self.assertEqual(powertasks.end_of(task, [], Statuses(broken=True).status), "unknown")


class JudgeTests(unittest.TestCase):
    def test_the_endings_a_person_chose_to_count(self):
        judge = powertasks.judge
        self.assertEqual(judge(["completed", "completed"]), "met")
        self.assertEqual(judge(["completed", "failed"]), "not_met", "completed only, by default")
        self.assertEqual(judge(["completed", "failed"], failed=True), "met")
        self.assertEqual(judge(["interrupted"], failed=True), "not_met")
        self.assertEqual(judge(["interrupted", "failed"], failed=True, interrupted=True), "met")

    def test_running_and_unknown(self):
        self.assertEqual(powertasks.judge(["completed", "running"]), "running")
        self.assertEqual(powertasks.judge(["running", "unknown"]), "unknown", "fail closed first")
        self.assertEqual(powertasks.judge([]), "unknown")


# ------------------------------------------------------------------------------ the answer at P21
class AnswerTests(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.catalogs = statement.CATALOGS
        self.compat = ac.view(capability="recovery_turn_tracking")
        self.statuses = Statuses({TURN: "completed"})
        self.records = []

    def listed(self, nonce=NONCE, **changes):
        document = {"format": powertasks.FORMAT, "nonce": nonce, "armed_at": ac.NOW, "failed": False,
                    "interrupted": False, "tasks": [{"thread_id": THREAD, "turn_id": TURN}]}
        document.update(changes)
        self.assertTrue(powertasks.write(self.paths, document))

    def code(self):
        return powertasks.PowerAfterTasks(self.paths, records=lambda: self.records, turns=self.statuses)

    def test_no_list_or_another_armings_list_answers_unknown(self):
        self.assertEqual(self.code().power({"nonce": NONCE}), {"tasks": "unknown", "threads": []})
        self.listed(nonce="0123456789abcdef")
        self.assertEqual(self.code().power({"nonce": NONCE})["tasks"], "unknown")

    def test_met_not_met_and_running_with_the_conversations(self):
        self.listed()
        self.assertEqual(self.code().power({"nonce": NONCE}), {"tasks": "met", "threads": [THREAD]})
        self.statuses.statuses[TURN] = "failed"
        self.assertEqual(self.code().power({"nonce": NONCE})["tasks"], "not_met")
        self.listed(failed=True)
        self.assertEqual(self.code().power({"nonce": NONCE})["tasks"], "met")
        self.records = [record(1, "waiting_reset")]
        self.assertEqual(self.code().power({"nonce": NONCE})["tasks"], "running")

    def test_core_records_that_cannot_be_read_are_unknown(self):
        self.listed()
        broken = powertasks.PowerAfterTasks(self.paths, records=mock.Mock(side_effect=OSError("no")),
                                            turns=self.statuses)
        self.assertEqual(broken.power({"nonce": NONCE})["tasks"], "unknown")

    def test_a_list_not_as_written_is_refused(self):
        for changes in ({"tasks": []}, {"failed": "yes"}, {"tasks": [{"thread_id": "x", "turn_id": TURN}]},
                        {"tasks": [{"thread_id": THREAD, "turn_id": TURN}] * 2}):
            with self.subTest(changes):
                document = {"format": powertasks.FORMAT, "nonce": NONCE, "armed_at": ac.NOW, "failed": False,
                            "interrupted": False, "tasks": [{"thread_id": THREAD, "turn_id": TURN}]}
                document.update(changes)
                self.assertFalse(powertasks.write(self.paths, document))

    def test_only_an_armed_capability_is_asked_and_taken(self):
        self.listed()
        plug = self.plug(POWER_AFTER_TASKS)
        runtime = plug.runtime
        self.assertIs(guard(plug).power({"nonce": NONCE}), None, "off: nothing wanted, nothing asked")
        with mock.patch.object(powertasks, "core_records", return_value=[]), \
                mock.patch.object(powertasks.PowerAfterTasks, "turns", return_value=self.statuses):
            self.arm(runtime, "power_after_tasks", state="shadow")
            runtime.states(fresh=True)
            self.assertIs(guard(plug).power({"nonce": NONCE}), None, "watched: a would-have, never taken")
            self.assertTrue(self.arm(runtime, "power_after_tasks").get("done"))
            runtime.states(fresh=True)          # as the watcher's next tick reads them
            self.listed()                       # watching it took the list away: a watched one waits for nothing
            self.assertEqual(guard(plug).power({"nonce": NONCE}), {"tasks": "met", "threads": (THREAD,)})


# ------------------------------------------------------------------------------ the card's arming
class ArmTests(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.catalogs = statement.CATALOGS
        self.compat = ac.view(capability="recovery_turn_tracking")
        self.paths.ensure()
        port = mock.patch.object(control_power.PowerActionMixin, "power_port", FakePort())
        port.start()
        self.addCleanup(port.stop)
        # An administrator's keys of the test's own: nothing reads this PC's policies.
        self.policies = mock.patch.object(control_policy, "managed_policy", return_value=managed.NONE)
        self.policies.start()
        self.addCleanup(self.policies.stop)
        offered = mock.patch.object(card, "_offered", return_value=[(THREAD, "example-project"),
                                                                     (OTHER, "example-service")])
        offered.start()
        self.addCleanup(offered.stop)
        self.statuses = Statuses({TURN: "inProgress"}, latest={THREAD: (TURN, "inProgress"),
                                                                OTHER: ("44444444-4444-7444-8444-444444444444",
                                                                        "completed")})
        self.run_ = self.runtime(POWER_AFTER_TASKS)

    def arm_tasks(self, threads=(THREAD,), **changes):
        request = dict(threads=list(threads), action="sleep", grace_minutes=5, failed=False, interrupted=False,
                       generation=self.run_.state.meta()["generation"], turns=self.statuses)
        request.update(changes)
        return card.arm(self.run_, **request)

    def stored(self):
        return json.loads(self.paths.power_action_file.read_text(encoding="utf-8"))

    def test_refused_unless_it_is_on(self):
        self.assertEqual(self.arm_tasks()["refusal"], "not_on")
        self.assertFalse(self.paths.power_action_file.exists())

    def test_refused_for_a_conversation_whose_turn_does_not_run(self):
        self.arm(self.run_, "power_after_tasks")
        self.assertEqual(self.arm_tasks((THREAD, OTHER))["refusal"], "no_turn_running")
        unlisted = "55555555-5555-7555-8555-555555555555"
        self.assertEqual(self.arm_tasks((unlisted,))["refusal"], "no_turn_running")
        for bad in ({"threads": []}, {"action": "restart"}, {"grace_minutes": 7}, {"failed": 1}):
            with self.subTest(bad):
                self.assertEqual(self.arm_tasks(**bad)["refusal"], "invalid_request")
        self.assertFalse(self.paths.power_action_file.exists())

    def test_armed_once_for_tasks_with_its_list_under_cores_nonce(self):
        self.arm(self.run_, "power_after_tasks")
        answer = self.arm_tasks(failed=True)
        self.assertTrue(answer["done"], answer)
        armed = self.stored()["armed"]
        self.assertIs(armed["tasks"], True)
        self.assertEqual((armed["repeat"], armed["carried"]), ("once", []))
        listed = powertasks.read(self.paths)
        self.assertEqual(listed["nonce"], armed["nonce"])
        self.assertEqual(listed["tasks"], [{"thread_id": THREAD, "turn_id": TURN}])
        self.assertIs(listed["failed"], True)
        self.assertEqual(answer["armed"]["tasks"][0]["thread_id"], THREAD)

    def test_core_refusing_is_said_and_writes_no_list(self):
        self.arm(self.run_, "power_after_tasks")
        self.policies.stop()
        with mock.patch.object(control_policy, "managed_policy",
                               return_value=managed.Managed(disable_power_action=True)):
            answer = self.arm_tasks()
        self.policies.start()
        self.assertEqual((answer["refusal"], answer["reason"]), ("power_refused", "managed_by_policy"))
        self.assertIsNone(powertasks.read(self.paths))

    def test_turning_the_capability_off_turns_a_tasks_arming_off(self):
        self.arm(self.run_, "power_after_tasks")
        self.assertTrue(self.arm_tasks()["done"])
        self.run_.arming.disarm("power_after_tasks", actor="dashboard")
        self.assertIsNone(self.stored()["armed"])
        self.assertIsNone(powertasks.read(self.paths))

    def test_turned_off_while_it_armed_the_arming_is_turned_off_too(self):
        """seatA:B-M8 (v0.6.23 audit). Fails without the second look: the tray's every-feature-off ran between the
        card's first look and the arming, found nothing armed, and the arming stood with the capability off."""
        self.arm(self.run_, "power_after_tasks")
        real = card._on
        looks = []

        def on(runtime, capability):
            looks.append(capability)
            if len(looks) == 1:
                answer = real(runtime, capability)
                self.run_.arming.disarm("power_after_tasks", actor="dashboard")
                return answer
            return real(runtime, capability)
        with mock.patch.object(card, "_on", on):
            self.assertEqual(self.arm_tasks()["refusal"], "not_on")
        self.assertIsNone(self.stored()["armed"])
        self.assertIsNone(powertasks.read(self.paths))

    def test_a_standard_arming_is_left_alone_when_it_goes_off(self):
        Control(self.paths).arm_power_action({"action": "sleep", "after": "all_recovered", "repeat": "once",
                                             "grace_minutes": 5})
        self.arm(self.run_, "power_after_tasks")
        self.run_.arming.disarm("power_after_tasks", actor="dashboard")
        self.assertIsNotNone(self.stored()["armed"], "only an arming for tasks follows the capability")


class NothingSentTests(unittest.TestCase):
    def test_no_send_path(self):
        for module in (powertasks, card):
            source = Path(module.__file__).read_text(encoding="utf-8")
            with self.subTest(module.__name__):
                for word in ("subprocess", "send(", "queue --thread", "dispatch"):
                    self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
