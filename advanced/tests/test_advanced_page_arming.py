"""The Dashboard's Advanced features page in the window itself: the list, Turn on and Watch, Turn off, the hourly
limit, a policy, a stale confirmation, a capability that turned itself off, the keys, the reopen and an installation
that cannot answer.

The window is compiled once for this module and every scenario_* below runs in one window process
(pagecase.PageCase); each makes its replies with this edition's real bridge in a home of its own, so nothing
here reads the real installation, the real Software\\Policies keys or a real Codex.

Held here: the page's rows are every capability in the owner's order (registry.SHOWN_ORDER), by name and state in
the person's language; the open one shows its statement's five fields, its warnings, what a policy refuses
and its limits; Turn on and Watch first ask in the dialog with the statement and every warning, send
exactly what the page showed - which the real bridge then accepts - and ask again, with what holds now,
when the bridge says something changed, or say why they cannot (it could not be read again, or a policy
now refuses it); a refusal is told; a capability that turned itself off says so and why; Turn off and
Turn every advanced feature off send theirs; the hourly limit is a spin box, and the lowered limit is one
the real bridge takes; the list is read again after every action and when the snapshot's badge says it
changed; Ctrl+Tab reaches the page; a window that reopens itself on the page comes back to it; and an
installation that cannot answer shows no tab.

GUI test module: compiles real executables, so it runs on its own.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_page_arming.py
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import policy, registry, statement  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, Verdict  # noqa: E402
from pagecase import CSC, IDS, MARKER_FREE, POWERSHELL, SHOWN, Bridge, PageCase, sent, snapshot  # noqa: E402


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    """The page driven as a person would, every scenario of this module in one window process."""

    @classmethod
    def scenario_reading(cls, bridge):
        """Opened in Korean: the words, the list and the first statement read as a snapshot arrives; then the tab."""
        script = cls.opening(bridge, "ko")
        steps = [{"do": "look"}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"}, {"do": "show"},
                 {"do": "choose", "id": IDS[1]}]
        statements = {capability: script["advanced-statement " + capability][0]["result"] for capability in IDS}
        return "ko", {"script": script, "steps": steps}, {"statements": statements,
                                                          "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_turn_on(cls, bridge):
        """Turn on, answered yes - with a warning the statement carries, which the request confirms."""
        bridge.measured = {}
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": MARKER_FREE},
                 {"do": "look"}, {"do": "reply", "key": "advanced-arm", "with": [{"ok": True, "result": {"done": True}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True], "script": script, "steps": steps}, {
            "statement": script["advanced-statement " + MARKER_FREE][0]["result"],
            "generation": script["advanced-list"][0]["result"]["generation"]}

    @classmethod
    def scenario_requires(cls, bridge):
        """v0.6.16-beta.3: Turn on for Wrap up near a limit while the usage meter it needs is off - one question with
        both statements, one yes, and the request carries the meter's confirmation in `also`."""
        bridge.measured = {}
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "usage_wrap_up"},
                 {"do": "reply", "key": "advanced-arm", "with": [{"ok": True, "result": {"done": True}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True], "script": script, "steps": steps}, {
            "wrap": script["advanced-statement usage_wrap_up"][0]["result"],
            "meter": script["advanced-statement usage_meter"][0]["result"],
            "generation": script["advanced-list"][0]["result"]["generation"]}

    @classmethod
    def scenario_required_off(cls, bridge):
        """v0.6.16-beta.3: Turn off for the usage meter while Wrap up near a limit needs it: the note names the wrap-up
        first, as the bridge's `also_off` does."""
        cls.watched(bridge, "usage_meter", "armed")
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "usage_meter"},
                 {"do": "reply", "key": "advanced-disarm",
                  "with": [{"ok": True, "result": {"done": True, "changed": True, "also_off": ["usage_wrap_up"]}}]},
                 {"do": "press", "button": "off"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_declined(cls, bridge):
        """Turn on and Watch first, both answered Cancel: nothing is sent."""
        script = cls.opening(bridge, "de")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": IDS[0]},
                 {"do": "press", "button": "on"}, {"do": "press", "button": "watch"}]
        return "de", {"answers": [False, False], "script": script, "steps": steps}, {}

    @classmethod
    def scenario_changed(cls, bridge):
        """Turn on, answered yes; meanwhile a local check failed here, so the bridge answers that the confirmation
        is stale. The page reads again, asks again with what holds now, and the second yes sends that."""
        script = cls.opening(bridge, "en")
        capability = IDS[0]
        before = script["advanced-statement " + capability][0]["result"]
        compat = registry.REGISTRY.get(capability).compat
        bridge.view["capabilities"][compat] = {"state": "FAILED_HERE", "reason": "local_check_failed_here"}
        stale = bridge("advanced-arm", {"capability": capability, "state": "armed", "revision": before["revision"],
                                        "generation": 0, "engine_version": before["engine_version"], "warnings": []})
        after = bridge("advanced-statement", {"capability": capability, "locale": "en"})
        listing = bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": capability},
                 {"do": "reply", "key": "advanced-list", "with": [listing]},
                 {"do": "reply", "key": "advanced-statement " + capability, "with": [after]},
                 {"do": "reply", "key": "advanced-arm", "with": [stale, {"ok": True, "result": {"done": True}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "stale": stale["result"], "after": after["result"], "listing": listing["result"]}

    @classmethod
    def scenario_refused(cls, bridge):
        """Watch first, answered yes, refused by an administrator's policy that arrived meanwhile: said, in words."""
        script = cls.opening(bridge, "fr")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"},
                 {"do": "reply", "key": "advanced-arm",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "forbidden_by_policy", "warnings": []}}]},
                 {"do": "press", "button": "watch"}]
        return "fr", {"answers": [True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_policy(cls, bridge):
        """An administrator allows one capability and forces the rest to be watched: the others say so, and cannot be
        turned on or watched; the allowed one can only be watched."""
        bridge.policy = policy.Policy(force_shadow=True, allowed=frozenset({IDS[1]}))
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": IDS[0]},
                 {"do": "look"}, {"do": "choose", "id": IDS[1]}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_off(cls, bridge):
        """One capability watched: Turn off sends advanced-disarm for it, and Turn every advanced feature off sends
        advanced-disarm-all; each is read again after, and says what it did."""
        definition = registry.REGISTRY.get(IDS[1])
        listed = bridge("advanced-statement", {"capability": IDS[1], "locale": "ja"})["result"]
        done = bridge("advanced-arm", {"capability": IDS[1], "state": "shadow", "revision": definition.revision,
                                       "generation": 0, "engine_version": listed["engine_version"],
                                       "warnings": [item["warning"] for item in listed["warnings"]["items"]]})
        assert done["result"]["done"], done
        script = cls.opening(bridge, "ja")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": IDS[1]},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-disarm", "with": [{"ok": True, "result": {"done": True, "changed": True}}]},
                 {"do": "press", "button": "off"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-disarm-all", "with": [{"ok": True, "result": {"done": True, "count": 0}}]},
                 {"do": "press", "button": "all_off"}]
        return "ja", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_hourly(cls, bridge):
        """The hourly limit lowered to 5: sent with the generation the list was read at, never above the registry's."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-ceiling", "with": [{"ok": True, "result": {"done": True}}]},
                 {"do": "hourly", "value": 5}]
        return "en", {"script": script, "steps": steps}, {"listing": script["advanced-list"][0]["result"]}

    @classmethod
    def scenario_followed(cls, bridge):
        """Away from the page, a snapshot whose badge says nothing changed reads nothing, and one whose badge changed -
        a capability turned on or off, here or anywhere - reads the list again; on the page, every snapshot does."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot(on=1)}, {"do": "look"},
                 {"do": "show"}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot(on=1)}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_measured(cls, bridge):
        """On the page, every snapshot reads the list again (scenario_followed): twice the same list, then one where a
        capability is watched. The cells are measured when the rows come, and again only when a state's word changed."""
        script = cls.opening(bridge, "en")
        definition = registry.REGISTRY.get(IDS[1])
        listed = bridge("advanced-statement", {"capability": IDS[1], "locale": "en"})["result"]
        done = bridge("advanced-arm", {"capability": IDS[1], "state": "shadow", "revision": definition.revision,
                                       "generation": 0, "engine_version": listed["engine_version"],
                                       "warnings": [item["warning"] for item in listed["warnings"]["items"]]})
        assert done["result"]["done"], done
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "reply", "key": "advanced-list", "with": [bridge("advanced-list", {})]},
                 {"do": "snapshot", "reply": snapshot(on=1)}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_keys(cls, bridge):
        """Ctrl+Tab goes from Settings to this page and on to the Overview; Ctrl+Shift+Tab back."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "page", "name": "settings"}, {"do": "ctrl-tab"},
                 {"do": "look"}, {"do": "ctrl-tab"}, {"do": "look"}, {"do": "ctrl-tab", "shift": True}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_changed_unreadable(cls, bridge):
        """Turn on, answered yes; the bridge says the confirmation is stale, and the statement read again cannot be
        read. Nothing can be asked again: the person is told so, and the page says why it cannot be turned on."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": IDS[0]},
                 {"do": "reply", "key": "advanced-statement " + IDS[0], "with": [{"ok": False, "error": "timed out"}]},
                 {"do": "reply", "key": "advanced-arm",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "stale_confirmation"}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_changed_unlisted(cls, bridge):
        """As above, but it is the list read again that cannot be read."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"},
                 {"do": "reply", "key": "advanced-list", "with": [{"ok": False, "error": "timed out"}]},
                 {"do": "reply", "key": "advanced-arm",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "stale_generation"}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_changed_to_policy(cls, bridge):
        """Turn on, answered yes; meanwhile an administrator's policy came to forbid every capability. The list read
        again says so: the person is not asked to confirm what the page knows cannot happen, but told why."""
        script = cls.opening(bridge, "en")
        bridge.policy = policy.Policy(forbid=True)
        forbidden = bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"},
                 {"do": "reply", "key": "advanced-list", "with": [forbidden]},
                 {"do": "reply", "key": "advanced-arm",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "stale_generation"}},
                           {"ok": True, "result": {"done": False, "refusal": "forbidden_by_policy"}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_tripped(cls, bridge):
        """Marker-free continuation turned on with the statement's own confirmation, and then the measurement it rests
        on failed: the real bridge's list says a tripwire turned it off, and why. The page says so; then, for the
        same capability turned off by a person, it says nothing of the kind; and for one Codex's new version turned
        off, it says that."""
        capability = "marker_free_continuation"
        shown = bridge("advanced-statement", {"capability": capability, "locale": "en"})["result"]
        armed = bridge("advanced-arm", {"capability": capability, "state": "armed", "revision": shown["revision"],
                                        "generation": bridge("advanced-list", {})["result"]["generation"],
                                        "engine_version": shown["engine_version"],
                                        "warnings": [item["warning"] for item in shown["warnings"]["items"]]})
        assert armed["result"]["done"], armed
        bridge.measured = dict(bridge.measured, **{Measurement.M7: (Verdict.FAIL, ac.ENGINE)})
        script = cls.opening(bridge, "en")
        listing = script["advanced-list"][0]
        item = next(entry for entry in listing["result"]["capabilities"] if entry["id"] == capability)
        by_person, by_engine = copy.deepcopy(listing), copy.deepcopy(listing)
        for changed, (by, reason) in ((by_person, ("dashboard", "disarmed")), (by_engine, ("engine_change", "engine_changed"))):
            entry = next(entry for entry in changed["result"]["capabilities"] if entry["id"] == capability)
            entry["by"], entry["reason"] = by, reason
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": capability},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-list", "with": [by_person]}, {"do": "snapshot", "reply": snapshot()},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-list", "with": [by_engine]}, {"do": "snapshot", "reply": snapshot()},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "item": item, "words": script["advanced-words"][0]["result"]["words"]}

    # What a window on this page passes on when it reopens itself (ReopenArguments): the page, and the keyboard on its tab.
    REOPENED = ("--page=advanced --section=general --bounds=100,100,1000,700 --theme=system --design=soft --reopened=1 "
                "--focus=page.advanced")

    @classmethod
    def scenario_reopen(cls, bridge):
        """On this page, a reopen - a theme, a language, Windows' colours - names it for the window that replaces it."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "reopen"},
                 {"do": "page", "name": "history"}, {"do": "reopen"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_reopened(cls, bridge):
        """The window that replaces it opens on the Overview, as one asked for a page it does not have yet, and comes
        back to this page once this edition has answered."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "open", "arguments": cls.REOPENED}, {"do": "look"}, {"do": "snapshot", "reply": snapshot()},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_unloaded(cls, bridge):
        """An installation whose advanced package could not be loaded answers every advanced command as unknown:
        no tab, and nothing but the one question, asked again with each read."""
        refused = {"ok": False, "error": "unknown command", "error_code": "request_failed"}
        script = {"advanced-words": [refused], "advanced-list": [refused]}
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "snapshot", "reply": snapshot()}, {"do": "show"}]
        return "en", {"script": script, "steps": steps}, {}

    # ---------------------------------------------------------------- tests
    def test_the_tab_shows_once_this_edition_has_answered_with_its_words(self):
        result, expected = self.of("scenario_reading")
        before, after = result["looks"][0], result["looks"][1]
        self.assertFalse(before["tab_visible"])
        self.assertTrue(after["tab_visible"])
        self.assertEqual(after["tab"], expected["words"]["page.nav"])
        self.assertEqual(after["tab"], "고급 기능")
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"][:3]],
                         ["advanced-words", "advanced-list", "advanced-statement"])
        self.assertEqual(sent(result, "advanced-words")[0], {"locale": "ko"})

    def test_every_capability_is_a_row_in_the_owner_s_order_by_name_and_state(self):
        """Fails with the list in the registry's order again (arming.listing walking the registry): the owner's order
        of 2026-10-10, the compatibility report first, and every capability once."""
        result, expected = self.of("scenario_reading")
        words = expected["words"]
        self.assertEqual([row[:2] for row in result["rows"]],
                         [[words["name." + capability], words["state.off"]] for capability in SHOWN])
        # v0.6.16-beta.3: which conversations are recovered at all, right after what starts the recovering.
        self.assertEqual(SHOWN[:4], ["compat_report", "start_with_codex", "every_conversation", "queue_for_open"])
        self.assertEqual(sorted(SHOWN), sorted(IDS))
        # v0.6.16-beta.3: every conversation, the usage meter, the wrap-up, the pause; beta.4: a conversation run here,
        # other sessions, compacting, the model fallback, no words; v0.6.18: Open Codex on a notice, the weekly update
        # check; v0.6.19: switching the Codex account.
        self.assertEqual(len(IDS), 33)
        self.assertEqual(result["page"], "advanced")
        # The row chosen is the capability open, and nothing else is.
        self.assertEqual(result["open"], IDS[1])
        self.assertEqual([row[2] for row in result["rows"]], [capability == IDS[1] for capability in SHOWN])

    def test_the_open_capability_shows_its_statement_in_the_person_s_language(self):
        result, expected = self.of("scenario_reading")
        statement_ = expected["statements"][IDS[1]]
        words = expected["words"]
        head, about, limits = result["cards"]
        self.assertEqual(head[0], words["name." + IDS[1]])
        self.assertEqual(about[0], words["page.about"])
        # The five fields, each under its title - the standards it departs from among them, in words.
        fields = [text for field in statement_["fields"] for text in (field["title"], field["text"])]
        self.assertEqual(about[1:], fields)
        self.assertEqual(len(statement_["fields"]), 5)
        departs = next(field["text"] for field in statement_["fields"] if field["field"] == "departs")
        for standard in registry.REGISTRY.get(IDS[1]).departs_from:
            self.assertIn(standard, departs)
        self.assertGreater(len(departs), 12 * len(registry.REGISTRY.get(IDS[1]).departs_from),
                           "the standards are glossed in words, not listed as ids")
        self.assertEqual(limits[0], words["page.limits"])
        self.assertIn(words["page.hourly"], limits)
        # A number with a ceiling, edited as the Settings page edits every one: a spin box from 1 to the registry's.
        self.assertEqual(result["hourly"], {"minimum": 1, "maximum": registry.GLOBAL_HOURLY,
                                            "value": registry.GLOBAL_HOURLY})
        # It was read in Korean.
        self.assertEqual({json.loads(line.split(" ", 1)[1]).get("locale") for line in result["sent"]
                          if line.startswith("advanced-statement ")}, {"ko"})

    def test_turn_on_asks_with_the_statement_and_every_warning_and_sends_exactly_what_was_shown(self):
        result, expected = self.of("scenario_turn_on")
        shown = expected["statement"]
        self.assertTrue(shown["warnings"]["items"], "the scenario's statement carries a warning")
        head = result["looks"][0]["cards"][0]
        for item in shown["warnings"]["items"]:
            self.assertIn(item["text"], head)
        (question,) = result["asked"]
        for item in shown["warnings"]["items"]:
            self.assertIn(item["text"], question)
        self.assertIn(shown["warnings"]["note"], question)
        for field in shown["fields"]:
            self.assertIn(field["title"], question)
            self.assertIn(field["text"], question)
        self.assertIn(shown["engine_version"], question)
        (arm,) = sent(result, "advanced-arm")
        self.assertEqual(arm, {"capability": MARKER_FREE, "state": "armed", "revision": shown["revision"],
                               "generation": expected["generation"], "engine_version": shown["engine_version"],
                               "warnings": [item["warning"] for item in shown["warnings"]["items"]]})
        self.assertEqual(result["note"], "%s is on." % "Marker-free continuation")
        # Read again after the action: the list, the statement and (v0.6.14) the watch log.
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"][-3:]],
                         ["advanced-list", "advanced-statement", "advanced-watch-log"])

    def test_what_the_page_sends_is_what_the_real_bridge_takes(self):
        """The request the page wrote, put to this edition's real bridge in the state the page read: it turns the
        capability on, with the warnings confirmed - it is the person's own, current confirmation."""
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                bridge.measured = {}
                result, _ = self.of("scenario_turn_on")
                arm_line = next(line for line in result["sent"] if line.startswith("advanced-arm "))
                reply = bridge.request(arm_line)["result"]
                self.assertTrue(reply["done"], reply)
                listed = bridge("advanced-list", {})["result"]
                item = next(entry for entry in listed["capabilities"] if entry["id"] == MARKER_FREE)
                self.assertEqual((item["state"], item["by"]), ("armed", "dashboard"))
                self.assertEqual(item["confirmed_warnings"], json.loads(arm_line.split(" ", 1)[1])["warnings"])
            finally:
                bridge.close()

    def test_what_it_needs_is_asked_for_in_the_same_question_and_turned_on_with_it(self):
        """Fails with the page's requirement handling reverted: the request would carry no `also`, which the real
        bridge refuses (requirement_refused)."""
        result, expected = self.of("scenario_requires")
        (question,) = result["asked"]
        self.assertIn("It needs Usage meter, so turning it on turns that on too.", question)
        self.assertIn("Needed by it: Usage meter", question)
        for shown in (expected["wrap"], expected["meter"]):
            for field in shown["fields"]:
                self.assertIn(field["text"], question)
        (arm,) = sent(result, "advanced-arm")
        meter = expected["meter"]
        self.assertEqual(arm["also"], [{"capability": "usage_meter", "revision": meter["revision"],
                                        "engine_version": meter["engine_version"],
                                        "warnings": [item["warning"] for item in meter["warnings"]["items"]]}])
        self.assertEqual(result["note"], "Wrap up near a limit is on, and so is what it needs: Usage meter.")
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                bridge.measured = {}
                arm_line = next(line for line in result["sent"] if line.startswith("advanced-arm "))
                reply = bridge.request(arm_line)["result"]
                self.assertTrue(reply["done"], reply)
                states = {entry["id"]: entry["state"] for entry in bridge("advanced-list", {})["result"]["capabilities"]}
                self.assertEqual((states["usage_wrap_up"], states["usage_meter"]), ("armed", "armed"))
            finally:
                bridge.close()

    def test_turning_off_what_another_needs_names_that_one_first(self):
        result, _ = self.of("scenario_required_off")
        self.assertEqual(result["note"], "Wrap up near a limit turned off first, because it needs Usage meter. "
                                         "Then Usage meter turned off.")

    def test_cancel_sends_nothing(self):
        result, _ = self.of("scenario_declined")
        self.assertEqual(len(result["asked"]), 2)
        self.assertEqual(sent(result, "advanced-arm"), [])
        self.assertTrue(result["asked"][1].startswith("„%s“ erst beobachten?" % "Mit Codex starten"), result["asked"][1])

    def test_a_confirmation_that_went_stale_is_read_again_and_asked_again(self):
        result, expected = self.of("scenario_changed")
        self.assertEqual(expected["stale"]["refusal"], "stale_confirmation")
        first, second = sent(result, "advanced-arm")
        self.assertEqual(first["warnings"], [])
        after = expected["after"]
        self.assertEqual(second, {"capability": IDS[0], "state": "armed", "revision": after["revision"],
                                  "generation": expected["listing"]["generation"],
                                  "engine_version": after["engine_version"],
                                  "warnings": [item["warning"] for item in after["warnings"]["items"]]})
        self.assertIn("failed_here", second["warnings"])
        asked_first, asked_second = result["asked"]
        self.assertNotIn("Something changed", asked_first)
        self.assertTrue(asked_second.startswith("Something changed since this was shown."))
        (failed,) = [item for item in after["warnings"]["items"] if item["warning"] == "failed_here"]
        self.assertIn(failed["text"], asked_second)
        self.assertNotIn(failed["text"], asked_first)
        self.assertEqual(result["told"], [])
        # Between the two: the list and the statement read again.
        lines = [line.split(" ", 1)[0] for line in result["sent"]]
        between = lines[lines.index("advanced-arm") + 1:len(lines) - 1 - lines[::-1].index("advanced-arm")]
        self.assertEqual(between, ["advanced-list", "advanced-statement", "advanced-watch-log"])

    def test_the_second_confirmation_is_one_the_real_bridge_takes(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                capability = IDS[0]
                compat = registry.REGISTRY.get(capability).compat
                bridge.view["capabilities"][compat] = {"state": "FAILED_HERE", "reason": "local_check_failed_here"}
                arms = [line for line in self.of("scenario_changed")[0]["sent"] if line.startswith("advanced-arm ")]
                self.assertEqual(bridge.request(arms[0])["result"]["refusal"], "stale_confirmation")
                self.assertTrue(bridge.request(arms[1])["result"]["done"])
            finally:
                bridge.close()

    def test_a_refusal_is_told_in_the_person_s_words(self):
        result, expected = self.of("scenario_refused")
        self.assertEqual(len(sent(result, "advanced-arm")), 1)
        self.assertEqual(sent(result, "advanced-arm")[0]["state"], "shadow")
        self.assertEqual(result["told"], [expected["words"]["page.policy.forbid"]])
        self.assertEqual(result["note"], "")

    def test_a_policy_says_what_it_refuses_and_the_buttons_follow_it(self):
        result, expected = self.of("scenario_policy")
        words = expected["words"]
        refused, allowed = result["looks"]
        self.assertEqual(refused["open"], IDS[0])
        self.assertIn(words["page.policy.not_allowed"], refused["cards"][0])
        self.assertEqual(refused["buttons"], {"on": False, "watch": False, "off": False, "all_off": True})
        self.assertEqual(allowed["open"], IDS[1])
        self.assertIn(words["page.policy.shadow_only"], allowed["cards"][0])
        self.assertEqual(allowed["buttons"], {"on": False, "watch": True, "off": False, "all_off": True})

    def test_turn_off_and_every_feature_off_send_theirs(self):
        result, expected = self.of("scenario_off")
        words = expected["words"]
        watched, off = result["looks"]
        self.assertEqual(watched["rows"][SHOWN.index(IDS[1])][1], words["state.shadow"])
        self.assertEqual(watched["buttons"], {"on": True, "watch": False, "off": True, "all_off": True})
        self.assertEqual(sent(result, "advanced-disarm"), [{"capability": IDS[1]}])
        self.assertEqual(off["note"], words["page.done.off"].replace("{name}", words["name." + IDS[1]]))
        self.assertEqual(sent(result, "advanced-disarm-all"), [{}])
        self.assertEqual(result["note"], words["page.done.all_off"])
        self.assertEqual(result["asked"], [], "turning off asks nothing")
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"][-3:]],
                         ["advanced-list", "advanced-statement", "advanced-watch-log"])

    def test_the_hourly_limit_is_lowered_with_the_generation_read(self):
        result, expected = self.of("scenario_hourly")
        self.assertEqual(result["looks"][0]["hourly"], {"minimum": 1,
                                                        "maximum": expected["listing"]["global_hourly_default"],
                                                        "value": expected["listing"]["global_hourly"]})
        self.assertEqual(sent(result, "advanced-ceiling"),
                         [{"global_hourly": 5, "generation": expected["listing"]["generation"]}])

    def test_the_hourly_request_is_one_the_real_bridge_takes(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                (line,) = [line for line in self.of("scenario_hourly")[0]["sent"] if line.startswith("advanced-ceiling ")]
                self.assertTrue(bridge.request(line)["result"]["done"])
                self.assertEqual(bridge("advanced-list", {})["result"]["global_hourly"], 5)
            finally:
                bridge.close()

    def test_the_list_is_read_again_when_the_snapshot_says_it_changed(self):
        result, _ = self.of("scenario_followed")
        commands = [line.split(" ", 1)[0] for line in result["sent"]]
        counts = [int(look["requests"]) for look in result["looks"]]
        # The open capability is the first row, the compatibility report: an action, which has no watch log to read.
        read = ["advanced-list", "advanced-statement"]
        # The words, the list and the statement once this edition answers; then, with the first badge seen, read again.
        self.assertEqual(commands[:counts[0]], ["advanced-words"] + read + read)
        # Away from the page, the same badge: nothing read.
        self.assertEqual(counts[1], counts[0])
        # Away from the page, a badge that changed: the list read again, and the open capability's statement.
        self.assertEqual(commands[counts[1]:counts[2]], read)
        # The tab pressed, and then on the page, each snapshot: read again.
        self.assertEqual(commands[counts[2]:counts[3]], read)
        self.assertEqual(commands[counts[3]:counts[4]], read)
        self.assertEqual(result["page"], "advanced")

    def test_the_cells_are_measured_again_only_when_a_word_changed(self):
        """With the page in front, every snapshot read the list again and measured all its cells (32 measurements every
        few seconds); the same rows in the same words now measure nothing, and a state that changed is measured."""
        result, _ = self.of("scenario_measured")
        first, again, third, changed = result["looks"]
        self.assertEqual(first["page"], "advanced")
        self.assertGreater(int(first["requests"]), 0)
        self.assertLess(int(first["requests"]), int(again["requests"]), "the snapshot read the list again")
        self.assertGreaterEqual(int(first["measures"]), 1, "the rows that came were not measured")
        self.assertEqual([int(look["measures"]) for look in (again, third)], [int(first["measures"])] * 2,
                         "the same list in the same words was measured again")
        row = SHOWN.index(IDS[1])
        self.assertNotEqual(changed["rows"][row][1], third["rows"][row][1])
        self.assertEqual(int(changed["measures"]), int(first["measures"]) + 1, "a state's new word was not measured")

    def test_ctrl_tab_goes_from_settings_to_this_page_and_on(self):
        pages = [look["page"] for look in self.of("scenario_keys")[0]["looks"]]
        self.assertEqual(pages, ["advanced", "overview", "advanced"])

    def test_a_confirmation_that_went_stale_and_cannot_be_read_again_is_told(self):
        """The person said yes and nothing was turned on: they are told, never left with a page that did nothing."""
        result, expected = self.of("scenario_changed_unreadable")
        words = expected["words"]
        self.assertEqual(len(sent(result, "advanced-arm")), 1)
        self.assertEqual(len(result["asked"]), 1)
        self.assertEqual(result["told"], [words["page.refused.unread"]])
        # Where the statement would be, why it cannot be turned on or watched.
        self.assertEqual(result["cards"][1], [words["page.about"], words["page.statement_unavailable"]])
        self.assertEqual((result["buttons"]["on"], result["buttons"]["watch"]), (False, False))
        result, expected = self.of("scenario_changed_unlisted")
        self.assertEqual(len(result["asked"]), 1)
        self.assertEqual(result["told"], [expected["words"]["page.refused.unread"]])
        self.assertEqual(result["cards"], [[expected["words"]["page.nav"], expected["words"]["page.unavailable"]]])

    def test_a_confirmation_that_went_stale_is_not_asked_again_where_a_policy_now_refuses_it(self):
        result, expected = self.of("scenario_changed_to_policy")
        forbid = expected["words"]["page.policy.forbid"]
        self.assertEqual(len(result["asked"]), 1, "nothing a policy refuses is asked for")
        self.assertEqual(len(sent(result, "advanced-arm")), 1)
        self.assertEqual(result["told"], [forbid])
        self.assertIn(forbid, result["cards"][0])
        self.assertEqual((result["buttons"]["on"], result["buttons"]["watch"]), (False, False))

    def test_a_capability_that_turned_itself_off_says_so_and_why(self):
        result, expected = self.of("scenario_tripped")
        words, item = expected["words"], expected["item"]
        self.assertEqual((item["stored"], item["state"], item["by"], item["reason"]),
                         ("off", "off", "tripwire", "measurement_failed"))
        tripped, by_person, by_engine = result["looks"]
        self.assertEqual(tripped["open"], "marker_free_continuation")
        self.assertEqual(tripped["cards"][0][:4], [words["name.marker_free_continuation"], words["page.col_state"],
                                                   words["state.off"], words["page.tripped.measurement_failed"]])
        said = {key: words[key] for key in words if key.startswith("page.tripped")}
        self.assertFalse(set(by_person["cards"][0]) & set(said.values()), "a person's own turning off is not a tripwire")
        self.assertIn(words["page.tripped.engine_changed"], by_engine["cards"][0])

    def test_a_window_that_reopens_on_this_page_comes_back_to_it(self):
        result, _ = self.of("scenario_reopen")
        here, elsewhere = result["reopened"]
        self.assertEqual(here, self.REOPENED)
        self.assertNotIn("advanced", elsewhere)
        self.assertTrue(elsewhere.startswith("--page=history "), elsewhere)
        result, _ = self.of("scenario_reopened")
        opened, answered = result["looks"]
        self.assertEqual((opened["page"], opened["tab_visible"]), ("overview", False))
        self.assertEqual((answered["page"], answered["tab_visible"], answered["focus"]),
                         ("advanced", True, "page.advanced"))
        self.assertEqual([row[0] for row in answered["rows"]],
                         [statement.CATALOGS.words("en")["name." + capability] for capability in SHOWN])

    def test_an_installation_that_cannot_answer_shows_no_tab(self):
        result, _ = self.of("scenario_unloaded")
        self.assertFalse(result["tab_visible"])
        self.assertEqual(result["page"], None)
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"]], ["advanced-words", "advanced-words"])
        self.assertEqual(result["rows"], [])


if __name__ == "__main__":
    unittest.main()
