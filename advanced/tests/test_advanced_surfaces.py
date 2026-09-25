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
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import control, controlcli, mcpserver  # noqa: E402
from codex_auto_resume.mcp.tools import TOOLS as CORE_TOOLS  # noqa: E402
from codex_auto_resume_advanced import arming, surfaces  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, BridgeCommand,  # noqa: E402
                                                   McpTool, Refusal)


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
        self.assertFalse(self.bridge("advanced-statement", {"capability": "nope"})["result"]["done"])

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
                         {"id", "state", "since", "by", "reason", "departs_from"})
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


if __name__ == "__main__":
    unittest.main()
