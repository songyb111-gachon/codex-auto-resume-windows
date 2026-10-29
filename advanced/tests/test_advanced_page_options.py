"""The Dashboard's Advanced features page in the window itself: a capability's own choices, the rules, the samples,
the watch log, Keep it on and Send now.

The window is compiled once for this module and every scenario_* below runs in one window process
(pagecase.PageCase); each makes its replies with this edition's real bridge in a home of its own, so nothing
here reads the real installation, the real Software\\Policies keys or a real Codex.

Held here: a capability's own choices are drop-downs whose choice is sent at once, the rules for Codex's
error codes are listed, added and removed, and the samples are listed, codes and numbers only - each
request one the real bridge takes, and each refusal told; what a watched capability would have done is a
card last in its column, answer words, counts and minutes only, read for every capability but an action; a
capability on or watched can be kept on, with Send again or without, after each warning, and let go - what
a kept-on one noted shown in the accent - and an action is never offered Send again; Send now, while it is
on, offers each waiting recovery, asking first.

GUI test module: compiles real executables, so it runs on its own.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_page_options.py
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.domain.plug import Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import watchlog  # noqa: E402
from codex_auto_resume_advanced.vocabulary import JournalCode  # noqa: E402
from pagecase import CSC, POWERSHELL, REPORT, Bridge, PageCase, sent, snapshot  # noqa: E402


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    """The page driven as a person would, every scenario of this module in one window process."""

    @classmethod
    def scenario_choices(cls, bridge):
        """Short retries when Codex is at capacity open: its one choice, the hours it keeps trying, a drop-down at the
        default; four hours chosen is sent at once, with the generation the list was read at."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "capacity_retry"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-option", "with": [{"ok": True, "result": {"done": True, "generation": 1}}]},
                 {"do": "set_option", "key": "ceiling_hours", "value": 4},
                 {"do": "reply", "key": "advanced-option",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "stale_generation"}}]},
                 {"do": "set_option", "key": "ceiling_hours", "value": 6}]
        return "en", {"script": script, "steps": steps}, {
            "listing": script["advanced-list"][0]["result"], "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def rules_home(cls, bridge):
        """A rule of the person's, written through the real bridge as the Dashboard writes one."""
        added = bridge("advanced-rule-add", {"tag": "brandNewVariant", "status_from": 500, "status_to": 599,
                                             "category": "server_5xx", "generation": 0})["result"]
        assert added["done"], added
        return added

    @classmethod
    def scenario_rules(cls, bridge):
        """The rules for Codex's error codes open: the person's one rule, with its Remove; a new one taken from the
        samples' codes, with status numbers and a kind, added; the first removed; a code that may name a decision
        refused by the bridge, and one that is not a code at all refused before anything is sent - each told."""
        cls.rules_home(bridge)
        script = cls.opening(bridge, "en")
        rules = bridge("advanced-rules", {})
        rules["result"]["tags"] = ["seenOnlyHere"]
        script["advanced-rules"] = [rules]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "structured_rules"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-rule-add", "with": [{"ok": True, "result": {"done": True, "rule": 2}}]},
                 {"do": "rule", "sampled": "seenOnlyHere", "from": "502", "to": "504", "kind": "timeout"},
                 {"do": "reply", "key": "advanced-rule-remove", "with": [{"ok": True, "result": {"done": True}}]},
                 {"do": "remove", "rule": 1}, {"do": "look"},
                 {"do": "reply", "key": "advanced-rule-add",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "rule_decision"}}]},
                 {"do": "rule", "tag": "policyRefused", "kind": "server_5xx"},
                 {"do": "rule", "tag": "not a code"}]
        return "en", {"script": script, "steps": steps}, {
            "rules": rules["result"], "listing": script["advanced-list"][0]["result"],
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_samples(cls, bridge):
        """Retry failures it cannot name open: its choice of tries, and its samples - a code with a status, and a
        failure with no code - then, read again, none."""
        script = cls.opening(bridge, "en")
        script["advanced-samples"] = [{"ok": True, "result": {"done": True, "samples": [
            {"tag": "brandNewVariant", "status": 503, "form": "tagged", "count": 2, "last": "2027-01-15"},
            {"tag": None, "status": None, "form": "absent", "count": 1, "last": "2027-01-14"}]}}]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "unknown_failure_budget"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-samples", "with": [{"ok": True, "result": {"done": True, "samples": []}}]},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_watch_log(cls, bridge):
        """Notice a usage limit that lifts early, watched: its watch log read through the real bridge - off with nothing,
        watched with nothing, then two looks early and one hold counted - and, scripted, one the bound has cut; then the
        compatibility report, an action, opened."""
        def log():
            return bridge("advanced-watch-log", {"capability": "early_reset"})
        off = log()
        cls.watched(bridge, "early_reset")
        none = log()
        state = bridge.plug.runtime.state
        for at in (ac.NOW - 3600, ac.NOW - 60):
            state.note(JournalCode.WOULD_HAVE, capability="early_reset", point=Point.SCHEDULE, answer=Alternative.EARLY,
                       at=at)
        state.note(JournalCode.WOULD_HAVE, capability="early_reset", point=Point.GATES, answer=Alternative.HOLD,
                   at=ac.NOW - 60)
        lines = log()
        full = copy.deepcopy(lines)
        full["result"].update({"full": True, "from": watchlog.minute(ac.NOW - 3600)})
        key = "advanced-watch-log early_reset"
        script = cls.opening(bridge, "en")
        script[key] = [lines]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "early_reset"},
                 {"do": "look"},
                 {"do": "reply", "key": key, "with": [none]}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "reply", "key": key, "with": [off]}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "reply", "key": key, "with": [full]}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "choose", "id": REPORT}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"],
            "replies": {"off": off["result"], "none": none["result"], "lines": lines["result"]}}

    @classmethod
    def scenario_keep_on(cls, bridge):
        """Short retries when Codex is at capacity watched: Keep it on... turns it on and keeps it on in one question -
        Keep it on's warning, then its statement - sent as one advanced-arm with keep_on (v0.6.16-beta.4); then Also
        send again when unsure... with its own; then Let it turn itself off, asking nothing - and it stays on. Each list
        read after is the real bridge's after that request."""
        cls.watched(bridge, "capacity_retry")
        script = cls.opening(bridge, "en")
        generation = script["advanced-list"][0]["result"]["generation"]
        shown = bridge("advanced-statement", {"capability": "capacity_retry", "locale": "en"})["result"]
        kept = bridge("advanced-arm", {"capability": "capacity_retry", "state": "armed", "revision": shown["revision"],
                                       "generation": generation, "engine_version": shown["engine_version"],
                                       "warnings": [item["warning"] for item in shown["warnings"]["items"]],
                                       "keep_on": True})
        assert kept["result"]["done"], kept
        once = bridge("advanced-list", {})
        again = bridge("advanced-keep-on", {"capability": "capacity_retry", "keep_on": True, "send_again": True,
                                            "generation": once["result"]["generation"],
                                            "confirmed": ["keep_on", "send_again"]})
        twice = bridge("advanced-list", {})
        let_go = bridge("advanced-keep-on", {"capability": "capacity_retry", "keep_on": False, "send_again": False})
        after = bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "capacity_retry"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-arm", "with": [kept]},
                 {"do": "reply", "key": "advanced-list", "with": [once]},
                 {"do": "press", "button": "keep_on"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-keep-on", "with": [again]},
                 {"do": "reply", "key": "advanced-list", "with": [twice]},
                 {"do": "press", "button": "send_again"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-keep-on", "with": [let_go]},
                 {"do": "reply", "key": "advanced-list", "with": [after]},
                 {"do": "press", "button": "let_go"}, {"do": "look"},
                 {"do": "choose", "id": "send_now"}, {"do": "look"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "generations": [generation, once["result"]["generation"]], "statement": shown,
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_keep_on_unread(cls, bridge):
        """Short retries when Codex is at capacity watched, its statement unreadable when it is opened: Keep it on... is
        not offered as pressable - it would confirm a statement nobody read - and once the statement is read again it is
        (v0.6.19-beta.3, the controls audit's finding 8: it was live and its click did nothing, said nothing)."""
        cls.watched(bridge, "capacity_retry")
        script = cls.opening(bridge, "en")
        shown = script["advanced-statement capacity_retry"][0]
        script["advanced-statement capacity_retry"] = [{"ok": False, "error": "timed out"}]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "capacity_retry"},
                 {"do": "look"}, {"do": "press", "button": "keep_on"},
                 {"do": "reply", "key": "advanced-statement capacity_retry", "with": [shown]},
                 {"do": "choose", "id": "send_now"}, {"do": "choose", "id": "capacity_retry"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_kept_notice(cls, bridge):
        """Kept on, Short retries when Codex is at capacity noted a new Codex version instead of turning itself off: said
        in the accent under its state; and a once-more capability that a resend found twice turned off: said why."""
        from codex_auto_resume_advanced.vocabulary import Actor, ArmingState, OffReason
        cls.watched(bridge, "capacity_retry", "armed")
        generation = bridge("advanced-list", {})["result"]["generation"]
        assert bridge("advanced-keep-on", {"capability": "capacity_retry", "keep_on": True, "generation": generation,
                                           "confirmed": ["keep_on"]})["result"]["done"]
        state = bridge.plug.runtime.state
        assert state.note_kept("capacity_retry", OffReason.ENGINE_CHANGED, at=ac.NOW)
        cls.watched(bridge, "once_more_when_unsure")
        state.move("once_more_when_unsure", ArmingState.OFF, actor=Actor.TRIPWIRE, reason=OffReason.DUPLICATE_SEEN,
                   at=ac.NOW)
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "capacity_retry"},
                 {"do": "look"}, {"do": "choose", "id": "once_more_when_unsure"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_action_kept(cls, bridge):
        """The compatibility report on and kept on: Let it turn itself off, and no Also send again when unsure... - an
        action sends no continuation to send again, and the bridge refuses Send again for one."""
        cls.watched(bridge, REPORT, "armed")
        generation = bridge("advanced-list", {})["result"]["generation"]
        assert bridge("advanced-keep-on", {"capability": REPORT, "keep_on": True, "generation": generation,
                                           "confirmed": ["keep_on"]})["result"]["done"]
        refused = bridge("advanced-keep-on", {"capability": REPORT, "keep_on": True, "send_again": True,
                                              "generation": bridge("advanced-list", {})["result"]["generation"],
                                              "confirmed": ["keep_on", "send_again"]})["result"]
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": REPORT},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"],
                                                          "refused": refused}

    @classmethod
    def scenario_send_now(cls, bridge):
        """Send now on: its card lists the recoveries the snapshot holds waiting - not the one whose turn is running -
        each with its Send now..., which asks first and sends that record's id; declined, nothing is sent."""
        cls.watched(bridge, "send_now", state="armed")
        script = cls.opening(bridge, "en")
        reply = snapshot()
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": "send_now"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-send-now",
                  "with": [{"ok": True, "result": {"done": True, "refusal": None, "expires_at": ac.NOW + 900}}]},
                 {"do": "send_now", "id": reply["pending"][0]["interruption_id"]}, {"do": "look"},
                 {"do": "send_now", "id": reply["pending"][1]["interruption_id"]},
                 {"do": "reply", "key": "advanced-send-now",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "not_on"}}]},
                 {"do": "send_now", "id": reply["pending"][1]["interruption_id"]},
                 {"do": "send_now", "id": reply["pending"][2]["interruption_id"]}]
        return "en", {"answers": [True, False, True], "script": script, "steps": steps}, {
            "pending": reply["pending"], "words": script["advanced-words"][0]["result"]["words"]}

    def test_a_choice_is_a_drop_down_whose_choice_is_sent_at_once(self):
        result, expected = self.of("scenario_choices")
        words = expected["words"]
        (shown,) = result["looks"]
        self.assertEqual(shown["choices"], [{"key": "ceiling_hours", "enabled": True, "value": "2 h",
                                             "items": ["%d h" % hours for hours in (1, 2, 3, 4, 6, 8, 12)]}])
        titles = [card[0] for card in shown["cards"]]
        self.assertEqual(titles[-1], words["page.options"])
        self.assertIn(words["page.option.ceiling_hours"], shown["cards"][-1])
        generation = expected["listing"]["generation"]
        self.assertEqual(sent(result, "advanced-option"),
                         [{"capability": "capacity_retry", "key": "ceiling_hours", "value": 4, "generation": generation},
                          {"capability": "capacity_retry", "key": "ceiling_hours", "value": 6, "generation": generation}])
        self.assertEqual(result["told"], [words["page.refused.choice"]])
        self.assertEqual(result["looks"][0]["note"], "")

    @staticmethod
    def keep_part(look, words):
        """The texts of Keep it on in the open capability's head card, from its caption on (v0.6.16-beta.3)."""
        head = look["cards"][0]
        return head[head.index(words["page.keep_on"]):]

    def test_keep_it_on_is_in_the_head_card_right_under_where_it_stands(self):
        """The owner found Keep it on too far down, a card of its own under the statement and the limits (2026-10-11):
        it is in the head card now, its caption right after the State fact - and no card of its own is left. Kept on,
        the State fact itself says Keep it on, never "On · kept on" (v0.6.16-beta.4)."""
        result, expected = self.of("scenario_keep_on")
        words = expected["words"]
        states = (words["state.shadow"], words["page.keep_on"], words["page.keep_on"], words["state.armed"])
        for look, state in zip(result["looks"][:4], states):
            head = look["cards"][0]
            at = head.index(words["page.col_state"])
            self.assertEqual(head[at + 1], state)
            self.assertEqual(head[at + 2], words["page.keep_on"], "Keep it on's caption right after the State fact")
            self.assertNotIn(words["page.keep_on"], [card[0] for card in look["cards"]])

    def test_the_list_says_keep_it_on_alone_for_a_kept_on_capability(self):
        """v0.6.16-beta.4 (the owner): a kept-on capability's row says Keep it on, and nothing else - not "On · kept on";
        watched before, it is on after Keep it on; let go, it is plainly on."""
        result, expected = self.of("scenario_keep_on")
        words = expected["words"]
        first, once, twice, after, _ = result["looks"]
        name = words["name.capacity_retry"]
        kept = words["page.keep_on"]

        def states(look):
            return {row[0]: row[1] for row in look["rows"]}
        for look, expected_state in ((first, words["state.shadow"]), (once, kept), (twice, kept),
                                     (after, words["state.armed"])):
            shown = states(look)
            self.assertEqual(shown[name], expected_state)
            self.assertEqual([text for text in shown.values() if text == kept],
                             [kept] if expected_state == kept else [], "no other row says Keep it on")
            self.assertFalse([text for text in shown.values() if " \u00b7 " in text], "no state with a second word")

    def test_keep_it_on_waits_for_the_statement_it_confirms(self):
        """Fails with Keep it on enabled on the policy alone again: unread, it was pressable and did nothing."""
        result, expected = self.of("scenario_keep_on_unread")
        unread, read = result["looks"]
        self.assertEqual(unread["kept"]["keep_on"], False)
        self.assertEqual(result["disabled"], ["keep_on"])
        self.assertEqual(read["kept"]["keep_on"], True)
        self.assertEqual([line for line in result["sent"] if line.startswith("advanced-arm ")], [])

    def test_keep_it_on_asks_with_each_warning_sends_what_was_confirmed_and_lets_go_asking_nothing(self):
        result, expected = self.of("scenario_keep_on")
        words = expected["words"]
        name = words["name.capacity_retry"]
        first, once, twice, after, send_now = result["looks"]
        self.assertEqual(self.keep_part(first, words)[1], words["page.keep_on.off"])
        self.assertEqual(first["kept"], {"keep_on": True, "send_again": None, "let_go": None})
        self.assertEqual(once["kept"], {"keep_on": None, "send_again": True, "let_go": True})
        self.assertIn(words["page.keep_on.on"], self.keep_part(once, words))
        self.assertEqual(twice["kept"], {"keep_on": None, "send_again": None, "let_go": True})
        self.assertIn(words["page.keep_on.again"], self.keep_part(twice, words))
        self.assertEqual(after["kept"], first["kept"])
        self.assertEqual(once["note"], words["page.done.keep_on"].replace("{name}", name))
        self.assertEqual(after["note"], words["page.done.keep_on_off"].replace("{name}", name))
        # One question turns it on and keeps it on: Keep it on's warning, then the statement it turns on.
        keep_question, again_question = result["asked"]
        self.assertTrue(keep_question.startswith(words["page.confirm.keep_on"].replace("{name}", name)))
        self.assertIn(words["page.confirm.on"].replace("{name}", name), keep_question)
        self.assertEqual(again_question, words["page.confirm.send_again"].replace("{name}", name))
        first_generation, second_generation = expected["generations"]
        statement = expected["statement"]
        self.assertEqual(sent(result, "advanced-arm"), [
            {"capability": "capacity_retry", "state": "armed", "revision": statement["revision"],
             "generation": first_generation, "engine_version": statement["engine_version"],
             "warnings": [item["warning"] for item in statement["warnings"]["items"]], "keep_on": True}])
        self.assertEqual(sent(result, "advanced-keep-on"), [
            {"capability": "capacity_retry", "keep_on": True, "send_again": True, "generation": second_generation,
             "confirmed": ["keep_on", "send_again"]},
            {"capability": "capacity_retry", "keep_on": False, "send_again": False}])
        self.assertEqual(result["told"], [])
        # Send now off: no card of waiting recoveries - and Keep it on... offered, which turns it on (v0.6.16-beta.4).
        self.assertEqual(send_now["send_now"], [])
        self.assertEqual(send_now["kept"], {"keep_on": True, "send_again": None, "let_go": None})
        self.assertNotIn(words["page.send_now.title"], [card[0] for card in send_now["cards"]])

    def test_what_keep_it_on_sends_is_what_the_real_bridge_takes(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                self.watched(bridge, "capacity_retry")
                line = next(line for line in self.of("scenario_keep_on")[0]["sent"] if line.startswith("advanced-arm "))
                self.assertTrue(bridge.request(line)["result"]["done"])
                item = next(entry for entry in bridge("advanced-list", {})["result"]["capabilities"]
                            if entry["id"] == "capacity_retry")
                self.assertEqual((item["state"], item["keep_on"], item["send_again"]), ("armed", True, False))
            finally:
                bridge.close()

    def test_a_kept_on_notice_and_a_duplicate_trip_are_said_in_the_accent(self):
        result, expected = self.of("scenario_kept_notice")
        words = expected["words"]
        kept, tripped = result["looks"]
        self.assertIn(words["page.kept.engine_changed"], kept["cards"][0])
        self.assertIn(words["page.tripped.duplicate_seen"], tripped["cards"][0])
        self.assertNotIn(words["page.keep_on"], [card[0] for card in tripped["cards"]], "off: nothing to keep on")

    def test_an_action_kept_on_is_never_offered_send_again(self):
        result, expected = self.of("scenario_action_kept")
        words = expected["words"]
        look, = result["looks"]
        self.assertEqual(look["kept"], {"keep_on": None, "send_again": None, "let_go": True})
        self.assertIn(words["page.keep_on.on"], self.keep_part(look, words))
        self.assertEqual((expected["refused"]["done"], expected["refused"]["refusal"]), (False, "invalid_request"))

    def test_send_now_offers_each_waiting_recovery_asks_first_and_sends_its_id(self):
        result, expected = self.of("scenario_send_now")
        words = expected["words"]
        pending = expected["pending"]
        shown, after = result["looks"]
        waiting = [row["interruption_id"] for row in pending if row["code"] in ("waiting_reset", "scheduled")]
        self.assertEqual(shown["send_now"], waiting)
        card = next(card for card in shown["cards"] if card[0] == words["page.send_now.title"])
        self.assertIn(pending[0]["name"], card[1])
        self.assertEqual(sent(result, "advanced-send-now"),
                         [{"interruption_id": pending[0]["interruption_id"]},
                          {"interruption_id": pending[1]["interruption_id"]}], "declined, nothing is sent")
        self.assertEqual(result["asked"], [words["page.confirm.send_now"]] * 3)
        self.assertEqual(after["note"], words["page.done.send_now"])
        self.assertEqual(result["told"], [words["page.refused.not_on"]])
        self.assertEqual(result["disabled"], ["send_now"], "a recovery whose turn is running is not offered")

    def test_what_send_now_sends_is_what_the_real_bridge_takes(self):
        from codex_auto_resume_advanced.control import sendnow
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                self.watched(bridge, "send_now", state="armed")
                line = next(line for line in self.of("scenario_send_now")[0]["sent"] if line.startswith("advanced-send-now "))
                with patch.object(sendnow, "wake", return_value=True) as woken:
                    self.assertTrue(bridge.request(line)["result"]["done"])
                self.assertEqual(woken.call_count, 1)
            finally:
                bridge.close()

    def test_the_choice_sent_is_one_the_real_bridge_takes(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                line = next(line for line in self.of("scenario_choices")[0]["sent"] if line.startswith("advanced-option "))
                self.assertTrue(bridge.request(line)["result"]["done"])
                item = next(entry for entry in bridge("advanced-list", {})["result"]["capabilities"]
                            if entry["id"] == "capacity_retry")
                self.assertEqual(item["options"][0]["value"], 4)
            finally:
                bridge.close()

    def test_the_rules_are_listed_added_and_removed_and_a_refusal_is_told(self):
        result, expected = self.of("scenario_rules")
        words = expected["words"]
        first, after = result["looks"]
        rules = next(card for card in first["cards"] if card[0] == words["page.rules"])
        self.assertIn("brandNewVariant \u00b7 500\u2013599 \u00b7 Server error \u00b7 %s: 0" % words["page.rule.hits"], rules)
        self.assertEqual(first["rules"], {"removes": [1], "add": True, "sampled": ["seenOnlyHere"],
                                          "kinds": ["Network problem", "Timeout", "Rate limit", "Server error",
                                                    "Interrupted response"]})
        generation = expected["listing"]["generation"]
        add, refused = sent(result, "advanced-rule-add")
        self.assertEqual(add, {"tag": "seenOnlyHere", "status_from": 502, "status_to": 504, "category": "timeout",
                               "generation": generation})
        self.assertEqual(refused["tag"], "policyRefused")
        self.assertEqual(sent(result, "advanced-rule-remove"), [{"rule": 1, "generation": generation}])
        self.assertEqual(after["note"], words["page.done.rule_removed"])
        self.assertEqual(result["told"], [words["page.refused.rule_decision"], words["page.refused.rule_shape"]])
        self.assertEqual(len(sent(result, "advanced-rule-add")), 2, "a code of the wrong shape is never sent")
        # Read again after each action: the list, the statement, the rules and (v0.6.14) the watch log.
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"][-4:]],
                         ["advanced-list", "advanced-statement", "advanced-rules", "advanced-watch-log"])

    def test_the_rules_the_page_sends_are_ones_the_real_bridge_takes_and_refuses(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                self.rules_home(bridge)
                lines = self.of("scenario_rules")[0]["sent"]
                add, refused = [line for line in lines if line.startswith("advanced-rule-add ")]
                self.assertTrue(bridge.request(add)["result"]["done"])
                removed = next(line for line in lines if line.startswith("advanced-rule-remove "))
                stale = bridge.request(removed)["result"]
                self.assertEqual(stale["refusal"], "stale_generation", "the add moved the generation on")
                self.assertTrue(bridge("advanced-rule-remove", dict(json.loads(removed.split(" ", 1)[1]),
                                                                    generation=stale["generation"]))["result"]["done"])
                current = bridge("advanced-list", {})["result"]["generation"]
                self.assertEqual(bridge("advanced-rule-add", dict(json.loads(refused.split(" ", 1)[1]), generation=current))
                                 ["result"]["refusal"], "rule_decision")
                self.assertEqual([rule["tag"] for rule in bridge("advanced-rules", {})["result"]["rules"]],
                                 ["seenOnlyHere"])
            finally:
                bridge.close()

    def test_the_samples_are_listed_codes_and_numbers_only(self):
        result, expected = self.of("scenario_samples")
        words = expected["words"]
        seen, none = result["looks"]
        samples = seen["cards"][-1]
        self.assertEqual(samples, [words["page.samples"],
                                   "%s: brandNewVariant \u00b7 %s: 503 \u00b7 %s: 2" % (
                                       words["page.sample.code"], words["page.sample.status"], words["page.sample.count"]),
                                   "%s: %s \u00b7 %s: - \u00b7 %s: 1" % (
                                       words["page.sample.code"], words["page.sample.no_code"], words["page.sample.status"],
                                       words["page.sample.count"])])
        self.assertEqual(seen["choices"], [{"key": "attempts", "enabled": True, "value": "1", "items": ["1", "2", "3"]}])
        self.assertEqual(none["cards"][-1], [words["page.samples"], words["page.samples.none"]])
        self.assertIsNone(seen["rules"])

    @staticmethod
    def on_the_clock(at) -> str:
        """A minute as the window prints it (gui/DashboardData.cs When): this PC's time."""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(at))

    def test_the_watch_log_shows_what_it_would_have_done_minutes_and_counts_only(self):
        result, expected = self.of("scenario_watch_log")
        words = expected["words"]
        replies = expected["replies"]
        lines, none, off, _full, report = result["looks"]
        title = words["page.watchlog"]
        since = words["page.watchlog.since"].replace("{time}", self.on_the_clock(replies["lines"]["watched_since"]))
        late = self.on_the_clock(watchlog.minute(ac.NOW - 60))
        self.assertEqual(lines["open"], "early_reset")
        self.assertEqual(lines["cards"][-1], [
            title, since,
            "%s \u00b7 %s: 2 \u00b7 %s: %s" % (words["page.watchlog.answer.early"], words["page.watchlog.times"],
                                              words["page.watchlog.last"], late),
            "%s \u00b7 %s: 1 \u00b7 %s: %s" % (words["page.watchlog.answer.hold"], words["page.watchlog.times"],
                                              words["page.watchlog.last"], late),
            words["page.watchlog.note"]])
        self.assertEqual(none["cards"][-1], [title, since, words["page.watchlog.none"], words["page.watchlog.note"]])
        self.assertEqual((replies["off"]["watched_since"], replies["off"]["entries"]), (None, []))
        self.assertNotIn(title, [card[0] for card in off["cards"]], "off, with nothing counted: no card")
        # Its other cards are where they were: the watch log is the last, and moves none of them.
        self.assertEqual([card[0] for card in lines["cards"][:-1]], [card[0] for card in off["cards"]])
        self.assertEqual(report["open"], REPORT)
        self.assertNotIn(title, [card[0] for card in report["cards"]], "an action is never asked anything")

    def test_a_full_log_says_from_when_it_counts(self):
        result, expected = self.of("scenario_watch_log")
        words = expected["words"]
        card = result["looks"][3]["cards"][-1]
        said = words["page.watchlog.from"].replace("{time}", self.on_the_clock(watchlog.minute(ac.NOW - 3600)))
        self.assertEqual(card[0], words["page.watchlog"])
        self.assertEqual(card[-2:], [said, words["page.watchlog.note"]])
        self.assertNotIn(said, result["looks"][0]["cards"][-1], "a log the bound has not cut says nothing of it")

    def test_what_the_watch_log_asks_is_one_the_real_bridge_takes(self):
        """Every request names one capability, the one whose cards are open, and never an action - not the report,
        open first before any is chosen; put to this edition's real bridge, each is answered."""
        result, _ = self.of("scenario_watch_log")
        asked = sent(result, "advanced-watch-log")
        self.assertTrue(asked)
        self.assertIn({"capability": "early_reset"}, asked)
        # Before any is chosen the first row is open, the compatibility report: an action, never asked.
        self.assertEqual({item["capability"] for item in asked}, {"early_reset"})
        self.assertNotIn({"capability": REPORT}, asked)
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                for line in [line for line in result["sent"] if line.startswith("advanced-watch-log ")]:
                    with self.subTest(line):
                        self.assertEqual(set(json.loads(line.split(" ", 1)[1])), {"capability"})
                        reply = bridge.request(line)["result"]
                        self.assertTrue(reply["done"], reply)
            finally:
                bridge.close()


if __name__ == "__main__":
    unittest.main()
