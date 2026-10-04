"""The Dashboard's bridge commands and a model's MCP tools, driven through core's own bridge and
MCP server: the Dashboard reads, arms, watches and turns off; MCP lists and turns off, and can
never turn anything on.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ast
import inspect
import io
import json
from pathlib import Path
import re
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import control, controlcli, mcpserver  # noqa: E402
from codex_auto_resume.mcp.tools import TOOLS as CORE_TOOLS  # noqa: E402
from codex_auto_resume.domain.plug import Alternative, FailureForm, Surface  # noqa: E402
from codex_auto_resume_advanced import arming, surfaces  # noqa: E402
from codex_auto_resume_advanced.registry import Option  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, BridgeCommand,  # noqa: E402
                                                   McpTool, OptionKey, Refusal)

# The day a sample kept at the tests' clock (advancedcase.NOW) is shown as.
DAY = time.strftime("%Y-%m-%d", time.gmtime(ac.NOW))


class SurfaceCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.paths.ensure()
        self.advanced = self.plug()
        self.control = control.Control(self.paths, plug=self.advanced)

    def bridge(self, command, argument=None):
        request = {"id": 1, "command": command}
        if argument is not None:
            request["argument"] = argument
        out = io.StringIO()
        controlcli.serve(self.control, io.StringIO(json.dumps(request) + "\n"), out)
        return json.loads(out.getvalue())["reply"]

    def converse(self, *messages):
        lines = "".join(json.dumps(message) + "\n" for message in messages)
        out = io.StringIO()
        with patch.object(control.Control, "watcher_running", return_value=True), \
                patch.object(control.Control, "startup_enabled", return_value=False):
            mcpserver.Server(self.control, io.StringIO(lines), out).serve()
        return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]

    def call(self, name, arguments=None):
        (reply,) = self.converse({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                  "params": {"name": name, "arguments": arguments or {}}})
        return reply

    def stored(self):
        return self.advanced.runtime.state.arming().get("test_wake")


class DashboardTests(SurfaceCase):
    def test_the_dashboard_reads_the_list_and_the_statement(self):
        reply = self.bridge("advanced-list", {})
        self.assertTrue(reply["ok"])
        listing = reply["result"]
        self.assertEqual((listing["generation"], listing["global_hourly"], listing["on"]), (0, 12, 0))
        (item,) = listing["capabilities"]
        self.assertEqual((item["id"], item["state"], item["departs_from"]), ("test_wake", "off", ["A11"]))
        statement = self.bridge("advanced-statement", {"capability": "test_wake", "locale": "ko"})["result"]
        self.assertEqual((statement["revision"], statement["locale"]), (1, "ko"))
        self.assertEqual(len(statement["fields"]), 5)
        self.assertEqual((statement["warnings"]["items"], statement["engine_version"]), ([], ac.ENGINE))
        self.assertEqual((item["warnings"], item["confirmed_warnings"]), ([], []))
        self.assertFalse(self.bridge("advanced-statement", {"capability": "nope"})["result"]["done"])

    def test_the_dashboard_reads_its_page_s_words_in_the_person_s_language(self):
        """The Advanced features page is built from these: the window's own catalog is core's, and holds none."""
        reply = self.bridge("advanced-words", {"locale": "ko"})
        self.assertTrue(reply["ok"])
        words = reply["result"]
        self.assertEqual((words["done"], words["locale"]), (True, "ko"))
        self.assertEqual(words["words"], self.catalogs.words("ko"))
        self.assertEqual((words["words"]["page.nav"], words["words"]["state.shadow"]), ("고급 기능", "지켜보는 중"))
        self.assertEqual(self.bridge("advanced-words", {"locale": "ko", "capability": "test_wake"})["result"],
                         {"done": False, "refusal": Refusal.INVALID_REQUEST})

    def test_the_dashboard_watches_arms_and_turns_off(self):
        watch = self.bridge("advanced-arm", {"capability": "test_wake", "state": "shadow",
                                              "revision": 1, "generation": 0})["result"]
        self.assertEqual((watch["done"], watch["generation"]), (True, 1))
        arm = self.bridge("advanced-arm", {"capability": "test_wake", "state": "armed", "revision": 1,
                                            "generation": 1, "engine_version": ac.ENGINE})["result"]
        self.assertTrue(arm["done"])
        self.assertEqual((self.stored()["state"], self.stored()["actor"]), (ArmingState.ARMED, Actor.DASHBOARD))
        self.assertEqual(self.bridge("advanced-list", {})["result"]["on"], 1)
        off = self.bridge("advanced-disarm", {"capability": "test_wake"})["result"]
        self.assertEqual((off["done"], off["changed"]), (True, True))
        self.assertTrue(self.bridge("advanced-arm", {"capability": "test_wake", "state": "shadow",
                                                     "revision": 1, "generation": 3})["result"]["done"])
        self.assertEqual(self.bridge("advanced-disarm-all", {})["result"]["count"], 1)

    def test_the_statements_warnings_go_back_as_the_persons_confirmation(self):
        """A grade the tests' capability should not have: the statement warns of it, in the
        person's language, and the same words sent back turn it on. Left out, the request is a
        stale confirmation that hands back what holds now - never a refusal of the capability."""
        self.compat = ac.view("FAILED_HERE", reason="local_check_failed_here")
        statement = self.bridge("advanced-statement", {"capability": "test_wake", "locale": "ko"})["result"]
        (item,) = statement["warnings"]["items"]
        self.assertEqual((item["warning"], statement["warnings"]["title"]), ("failed_here", "경고"))
        request = {"capability": "test_wake", "state": "armed", "revision": 1, "generation": 0,
                   "engine_version": statement["engine_version"]}
        stale = self.bridge("advanced-arm", request)["result"]
        self.assertEqual((stale["done"], stale["refusal"], stale["warnings"]),
                         (False, Refusal.STALE_CONFIRMATION, ["failed_here"]))
        arm = self.bridge("advanced-arm", dict(request, warnings=[item["warning"]]))["result"]
        self.assertEqual((arm["done"], arm["warnings"]), (True, ["failed_here"]))
        listed = self.bridge("advanced-list", {})["result"]
        self.assertEqual(listed["on"], 1)
        self.assertEqual(listed["capabilities"][0]["confirmed_warnings"], ["failed_here"])

    def test_a_stale_revision_or_generation_is_refused(self):
        stale = self.bridge("advanced-arm", {"capability": "test_wake", "state": "shadow",
                                              "revision": 1, "generation": 5})["result"]
        self.assertEqual(stale["refusal"], Refusal.STALE_GENERATION)
        old = self.bridge("advanced-arm", {"capability": "test_wake", "state": "shadow",
                                            "revision": 0, "generation": 0})["result"]
        self.assertEqual(old["refusal"], Refusal.STALE_REVISION)

    def test_an_argument_a_command_does_not_take_refuses_it(self):
        reply = self.bridge("advanced-disarm-all", {"everything": True})["result"]
        self.assertEqual(reply, {"done": False, "refusal": "invalid_request"})

    def test_the_global_ceiling_is_the_dashboards_to_lower(self):
        self.assertTrue(self.bridge("advanced-ceiling", {"global_hourly": 4, "generation": 0})["result"]["done"])
        self.assertEqual(self.bridge("advanced-list", {})["result"]["global_hourly"], 4)
        self.assertEqual(self.bridge("advanced-ceiling", {"global_hourly": 20, "generation": 1})["result"]["refusal"],
                         Refusal.INVALID_REQUEST)

    def test_a_command_this_edition_does_not_have_is_refused_as_every_unknown_one_is(self):
        self.assertEqual(self.bridge("advanced-arm-everything", {}),
                         {"ok": False, "error": "unknown command", "error_code": "request_failed"})

    def test_the_one_shot_bridge_never_reaches_the_plug(self):
        """Only the long-lived bridge, the Dashboard's, puts a command to the plug: the one-shot
        form's parser knows the bridge's own commands and nothing else."""
        for command in BridgeCommand:
            with self.subTest(command), patch.object(sys, "stdout", io.StringIO()), \
                    patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit) as refused:
                controlcli.main(["--home", str(self.home), str(command), "{}"])
            self.assertEqual(refused.exception.code, 2)


class McpTests(SurfaceCase):
    def test_its_three_tools_come_after_cores_and_none_turns_anything_on(self):
        (reply,) = self.converse({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = reply["result"]["tools"]
        self.assertEqual(tools[:len(CORE_TOOLS)], json.loads(json.dumps(CORE_TOOLS)))
        added = tools[len(CORE_TOOLS):]
        self.assertEqual([tool["name"] for tool in added], [str(name) for name in McpTool])
        for tool in added:
            with self.subTest(tool["name"]):
                self.assertIs(tool["annotations"]["destructiveHint"], False)
                self.assertNotRegex(tool["name"], r"(?<!dis)arm")
                self.assertIn("Dashboard", tool["description"])
        self.assertIs(added[0]["annotations"]["readOnlyHint"], True)

    def test_a_model_lists_and_turns_one_off(self):
        self.arm(self.advanced.runtime)
        listing = self.call("list_advanced_capabilities")["result"]
        self.assertFalse(listing.get("isError"))
        self.assertEqual(listing["structuredContent"]["on"], 1)
        self.assertEqual(set(listing["structuredContent"]["capabilities"][0]),
                         {"id", "state", "since", "by", "reason", "departs_from", "options", "keep_on",
                          "notice"})
        off = self.call("disarm_advanced_capability", {"capability": "test_wake"})["result"]
        self.assertEqual(off["structuredContent"], {"capability": "test_wake", "state": "off", "changed": True})
        self.assertEqual((self.stored()["state"], self.stored()["actor"]), (ArmingState.OFF, Actor.MCP))
        refused = self.call("disarm_advanced_capability", {"capability": "nope"})["result"]
        self.assertTrue(refused["isError"])
        self.assertEqual(refused["structuredContent"], {"error_code": "request_failed"})

    def test_a_model_turns_all_advanced_features_off(self):
        self.arm(self.advanced.runtime)
        reply = self.call("disarm_all_advanced")["result"]
        self.assertEqual(reply["structuredContent"], {"count": 1})
        self.assertEqual(self.stored()["actor"], Actor.MCP)

    def test_a_model_cannot_arm_even_when_it_ignores_the_schema(self):
        """The Custom message's precedent (tests/test_mcp.py): no tool, and a client that sends
        what no schema offers is refused before anything could act on it."""
        attempts = [("arm_advanced_capability", {"capability": "test_wake"}),
                    ("advanced-arm", {"capability": "test_wake", "state": "armed", "revision": 1,
                                      "generation": 0, "engine_version": ac.ENGINE}),
                    ("advanced-arm", {"capability": "test_wake", "state": "armed", "revision": 1,
                                      "generation": 0, "engine_version": ac.ENGINE, "warnings": []}),
                    ("disarm_advanced_capability", {"capability": "test_wake", "warnings": []}),
                    ("disarm_advanced_capability", {"capability": "test_wake", "state": "armed"}),
                    ("disarm_all_advanced", {"state": "armed", "revision": 1, "generation": 0}),
                    ("list_advanced_capabilities", {"arm": True}),
                    ("update_settings", {"advanced": {"test_wake": "armed"}})]
        with patch.object(arming.Arming, "arm") as armed:
            for name, arguments in attempts:
                with self.subTest(name):
                    reply = self.call(name, arguments)
                    refused = "error" in reply or reply["result"].get("isError")
                    self.assertTrue(refused, reply)
            armed.assert_not_called()
        self.assertIsNone(self.stored())

    def test_nothing_the_mcp_surface_reaches_can_arm(self):
        """Read from the source: the MCP half of surfaces.py never names `arm`."""
        tree = ast.parse(inspect.getsource(surfaces.mcp))
        named = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertNotIn("arm", named)
        self.assertNotIn("set_global_hourly", named)
        for write in ("set_option", "add_rule", "remove_rule", "rules_view", "samples_view"):
            self.assertNotIn(write, named)
        self.assertIn("disarm", named)

    def test_the_advanced_skill_names_every_tool_and_none_that_turns_anything_on(self):
        text = (ac.ROOT / "advanced" / "skills" / "codex-auto-resume-advanced" / "SKILL.md").read_text(
            encoding="utf-8")
        for tool in McpTool:
            self.assertIn("`%s`" % tool, text)
        self.assertEqual(set(re.findall(r"`(\w*arm\w*)`", text)) - {str(tool) for tool in McpTool}, set())

    def test_the_bridge_commands_and_the_tools_are_the_vocabularys(self):
        self.assertEqual(set(surfaces.ARGUMENTS), set(BridgeCommand))
        self.assertEqual([tool["name"] for tool in surfaces.TOOLS], list(McpTool))



SAMPLE = {"code": "brandNewVariant", "status": 503, "form": FailureForm.TAGGED, "has_message": True,
          "items": {"agentMessage": 2, "commandExecution": 1}, "duration": 42.0}


class ChoicesCase(SurfaceCase):
    """A capability of the tests' own with a choice, the rules editor and samples (v0.6.13)."""

    def setUp(self):
        ac.AdvancedCase.setUp(self)
        self.paths.ensure()
        self.advanced = self.plug(ac.definition(options=(Option(OptionKey.ATTEMPTS, (1, 2, 3), 1),),
                                                rules_editor=True, samples=True, codes=("sampled", "matched")))
        self.control = control.Control(self.paths, plug=self.advanced)

    def generation(self):
        return self.bridge("advanced-list", {})["result"]["generation"]

    def sampled(self, key, shape=SAMPLE):
        """One failure taken up and sampled, as the runtime keeps one (state/choices.py)."""
        state = self.advanced.runtime.state
        self.assertTrue(state.admit(key, "test_wake", Alternative.ADMIT, shape=shape, at=self.now))
        self.assertTrue(state.taken(key, "test_wake", "sampled", sample=shape, at=self.now))


class ChoiceBridgeTests(ChoicesCase):
    def test_the_list_carries_each_choice_with_what_it_offers_and_whether_rules_and_samples_show(self):
        (item,) = self.bridge("advanced-list", {})["result"]["capabilities"]
        self.assertEqual(item["options"], [{"key": "attempts", "choices": [1, 2, 3], "value": 1, "default": 1}])
        self.assertEqual((item["rules_editor"], item["samples"]), (True, True))
        self.assertFalse(self.home.joinpath("config", "advanced").exists(), "reading the list made nothing")

    def test_the_dashboard_sets_a_choice_against_the_generation_it_read(self):
        done = self.bridge("advanced-option", {"capability": "test_wake", "key": "attempts", "value": 2,
                                               "generation": 0})["result"]
        self.assertEqual((done["done"], done["generation"]), (True, 1))
        (item,) = self.bridge("advanced-list", {})["result"]["capabilities"]
        self.assertEqual(item["options"][0]["value"], 2)
        for argument, refusal in (({"value": 3, "generation": 0}, Refusal.STALE_GENERATION),
                                  ({"value": 9, "generation": 1}, Refusal.OPTION_INVALID),
                                  ({"value": "3", "generation": 1}, Refusal.OPTION_INVALID),
                                  ({"key": "ceiling_hours", "value": 2, "generation": 1}, Refusal.OPTION_INVALID),
                                  ({"capability": "nope", "value": 2, "generation": 1}, Refusal.UNKNOWN_CAPABILITY)):
            with self.subTest(argument=argument):
                request = dict({"capability": "test_wake", "key": "attempts"}, **argument)
                self.assertEqual(self.bridge("advanced-option", request)["result"]["refusal"], refusal)
        self.assertEqual(self.bridge("advanced-option", {"capability": "test_wake", "key": "attempts", "value": 2,
                                                         "generation": 1, "state": "armed"})["result"]["refusal"],
                         Refusal.INVALID_REQUEST)
        self.assertEqual(self.stored(), None, "a choice turns nothing on")

    def test_the_dashboard_adds_reads_and_removes_rules_and_each_refusal_is_its_own(self):
        added = self.bridge("advanced-rule-add", {"tag": "brandNewVariant", "status_from": 500, "status_to": 599,
                                                  "category": "server_5xx", "generation": 0})["result"]
        self.assertEqual((added["done"], added["rule"], added["generation"]), (True, 1, 1))
        rules = self.bridge("advanced-rules", {})["result"]
        self.assertEqual(rules, {"done": True, "generation": 1, "limit": 10, "tags": [], "rules": [
            {"rule": 1, "tag": "brandNewVariant", "status_from": 500, "status_to": 599, "category": "server_5xx",
             "known": False, "hits": 0}]})
        for tag, low, high, refusal in (("serverOverloaded", None, None, Refusal.RULE_KNOWN),
                                        ("policyRefused", None, None, Refusal.RULE_DECISION),
                                        ("not a code", None, None, Refusal.RULE_SHAPE),
                                        ("anotherCode", 600, 700, Refusal.RULE_RANGE),
                                        ("brandNewVariant", 503, 503, Refusal.RULE_OVERLAP)):
            with self.subTest(tag=tag):
                refused = self.bridge("advanced-rule-add", {"tag": tag, "status_from": low, "status_to": high,
                                                            "category": "timeout", "generation": 1})["result"]
                self.assertEqual((refused["done"], refused["refusal"]), (False, refusal))
        self.assertEqual(self.bridge("advanced-rule-add", {"tag": "anotherCode", "status_from": None, "status_to": None,
                                                           "category": "usage_limit", "generation": 1})["result"]
                         ["refusal"], Refusal.INVALID_REQUEST, "no rule makes a failure a usage limit")
        self.assertEqual(self.bridge("advanced-rule-remove", {"rule": 1, "generation": 0})["result"]["refusal"],
                         Refusal.STALE_GENERATION)
        self.assertTrue(self.bridge("advanced-rule-remove", {"rule": 1, "generation": 1})["result"]["done"])
        self.assertEqual(self.bridge("advanced-rule-remove", {"rule": 1, "generation": 2})["result"]["refusal"],
                         Refusal.UNKNOWN_RULE)
        self.assertEqual(self.bridge("advanced-rules", {})["result"]["rules"], [])

    def test_a_rule_shows_its_uses_in_thirty_days_and_the_samples_offer_the_codes_a_rule_may_name(self):
        self.arm(self.advanced.runtime, state="shadow")
        self.bridge("advanced-rule-add", {"tag": "brandNewVariant", "status_from": None, "status_to": None,
                                          "category": "timeout", "generation": self.generation()})
        state = self.advanced.runtime.state
        self.assertTrue(state.admit(ac.KEY, "test_wake", Alternative.AS_TIMEOUT, rule_id=1, at=self.now))
        self.assertTrue(state.taken(ac.KEY, "test_wake", "matched", at=self.now))
        self.sampled("b" * 64)
        self.sampled("c" * 64, dict(SAMPLE, code="policyRefused"))
        rules = self.bridge("advanced-rules", {})["result"]
        self.assertEqual(rules["rules"][0]["hits"], 1)
        self.assertEqual(rules["tags"], ["brandNewVariant"], "a code that may name a decision is never offered")

    def test_the_samples_are_aggregated_codes_and_numbers_with_no_id_and_no_word(self):
        self.arm(self.advanced.runtime, state="shadow")
        for index in range(3):
            self.sampled("%064x" % (index + 1))
        self.sampled("%064x" % 9, {"code": None, "status": None, "form": FailureForm.ABSENT, "has_message": False})
        samples = self.bridge("advanced-samples", {})["result"]
        self.assertEqual(samples, {"done": True, "samples": [
            {"tag": "brandNewVariant", "status": 503, "form": "tagged", "count": 3, "last": DAY},
            {"tag": None, "status": None, "form": "absent", "count": 1, "last": DAY}]})
        written = json.dumps(samples)
        for key in ("%064x" % 1, ac.THREAD):
            self.assertNotIn(key, written)
        self.now += 31 * 86400
        self.assertEqual(self.bridge("advanced-samples", {})["result"]["samples"], [], "thirty days back, no more")

    def test_diagnostics_carry_the_samples_and_the_status_and_tray_never_do(self):
        runtime = self.advanced.runtime
        self.assertEqual(surfaces.answer(runtime, Surface.DIAGNOSTICS, {}), {"edition": "advanced", "on": 0})
        self.arm(runtime, state="shadow")
        self.sampled(ac.KEY)
        shown = surfaces.answer(runtime, Surface.DIAGNOSTICS, {})
        self.assertEqual(shown["samples"], [{"tag": "brandNewVariant", "status": 503, "form": "tagged", "count": 1,
                                             "last": DAY}])
        self.assertNotIn(ac.KEY, json.dumps(shown))
        for surface in (Surface.STATUS, Surface.TRAY):
            self.assertNotIn("samples", surfaces.answer(runtime, surface, {}))

    def test_a_model_reads_the_choices_and_writes_none_of_them_whatever_it_sends(self):
        listing = self.call("list_advanced_capabilities")["result"]["structuredContent"]
        self.assertEqual(listing["capabilities"][0]["options"], {"attempts": 1})
        attempts = [("advanced-option", {"capability": "test_wake", "key": "attempts", "value": 3, "generation": 0}),
                    ("set_advanced_option", {"capability": "test_wake", "key": "attempts", "value": 3}),
                    ("advanced-rule-add", {"tag": "brandNewVariant", "category": "timeout", "generation": 0}),
                    ("disarm_advanced_capability", {"capability": "test_wake", "key": "attempts", "value": 3}),
                    ("list_advanced_capabilities", {"rule": "brandNewVariant"}),
                    ("list_advanced_capabilities", {"samples": True})]
        with patch.object(arming.Arming, "set_option") as option, patch.object(arming.Arming, "add_rule") as add, \
                patch.object(arming.Arming, "remove_rule") as remove:
            for name, arguments in attempts:
                with self.subTest(name):
                    reply = self.call(name, arguments)
                    self.assertTrue("error" in reply or reply["result"].get("isError"), reply)
            for write in (option, add, remove):
                write.assert_not_called()
        self.assertEqual(self.advanced.runtime.state.options("test_wake"), {OptionKey.ATTEMPTS: 1})


if __name__ == "__main__":
    unittest.main()
