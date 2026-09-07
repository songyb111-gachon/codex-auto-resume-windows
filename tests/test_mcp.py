"""The MCP server, driven the way Codex drives it.

Most of these run the real transport - newline-delimited JSON-RPC over a pair of
streams - rather than calling handlers directly, because the failures that matter in a
stdio server are transport failures: a stray write to stdout, a reply to a
notification, a crash on a malformed line.

The rest assert the boundary. This server is a front end; it must not be able to
recover anything itself, and no tool it exposes may offer a way past a safety property.
Those tests are written against the published tool list, so adding a tool that breaks
the rule fails here rather than in a review.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import config, control, mcpserver, mcpui, settings
from codex_auto_resume.store import Store

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
KEY = "a" * 64


def detection(key=KEY, thread_id=THREAD, category="usage_limit"):
    return {"thread_id": thread_id, "turn_id": TURN, "completed_at": 110.0,
            "started_at": 105.0, "ordinal": 2, "interruption_id": key,
            "reset_at": 150.0, "limit_type": "codex.primary", "uncertain": False,
            "category": category}


class McpTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.paths = config.Paths(self.home)
        self.paths.ensure()
        self.control = control.Control(self.paths)
        self.running = patch.object(control.Control, "watcher_running", return_value=True)
        self.startup = patch.object(control.Control, "startup_enabled", return_value=False)
        self.running.start()
        self.startup.start()

    def tearDown(self):
        self.startup.stop()
        self.running.stop()
        self.temporary.cleanup()

    def register(self, **kwargs):
        with Store(self.paths.state_dir) as store:
            store.register(detection(**kwargs), 100.0)

    def converse(self, *messages) -> list:
        """Feed whole lines through the transport and read whatever comes back."""
        lines = "".join(json.dumps(message) + "\n" if not isinstance(message, str)
                        else message + "\n" for message in messages)
        out = io.StringIO()
        mcpserver.Server(self.control, io.StringIO(lines), out).serve()
        return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]

    def call(self, name, arguments=None, request_id=7):
        responses = self.converse({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                                   "params": {"name": name, "arguments": arguments or {}}})
        self.assertEqual(len(responses), 1)
        return responses[0]


class TransportTests(McpTestCase):
    def test_initialize_negotiates_a_supported_protocol(self):
        for requested in mcpserver.SUPPORTED_PROTOCOLS:
            responses = self.converse({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                       "params": {"protocolVersion": requested,
                                                  "capabilities": {}, "clientInfo": {"name": "t"}}})
            self.assertEqual(responses[0]["result"]["protocolVersion"], requested)

    def test_an_unknown_protocol_gets_our_supported_one(self):
        responses = self.converse({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(responses[0]["result"]["protocolVersion"], mcpserver.PROTOCOL_VERSION)

    def test_a_notification_is_never_answered(self):
        # Replying to a notification is a protocol violation that some clients treat as
        # a fatal stream error, so it is asserted rather than assumed.
        self.assertEqual(self.converse({"jsonrpc": "2.0", "method": "notifications/initialized"}), [])

    def test_a_malformed_line_does_not_end_the_connection(self):
        responses = self.converse("{not json",
                                  {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(responses[0]["error"]["code"], mcpserver.PARSE_ERROR)
        self.assertEqual(responses[1]["result"], {})

    def test_blank_lines_are_ignored(self):
        responses = self.converse("", "   ", {"jsonrpc": "2.0", "id": 3, "method": "ping"})
        self.assertEqual(len(responses), 1)

    def test_a_batch_is_answered_message_by_message(self):
        responses = self.converse([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                   {"jsonrpc": "2.0", "id": 2, "method": "ping"}])
        self.assertEqual([item["id"] for item in responses], [1, 2])

    def test_an_unknown_method_is_reported_not_ignored(self):
        responses = self.converse({"jsonrpc": "2.0", "id": 4, "method": "resources/subscribe"})
        self.assertEqual(responses[0]["error"]["code"], mcpserver.METHOD_NOT_FOUND)

    def test_every_response_is_one_json_object_per_line(self):
        out = io.StringIO()
        lines = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/list"}) + "\n"
                        for i in range(3))
        mcpserver.Server(self.control, io.StringIO(lines), out).serve()
        for line in out.getvalue().splitlines():
            self.assertIsInstance(json.loads(line), dict)

    def test_an_internal_failure_leaks_no_detail(self):
        with patch.object(control.Control, "get_status", side_effect=RuntimeError(str(self.home))):
            responses = self.converse({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                       "params": {"name": "get_status", "arguments": {}}})
        self.assertEqual(responses[0]["error"]["code"], mcpserver.INTERNAL_ERROR)
        self.assertNotIn(str(self.home), json.dumps(responses[0]))


class ToolSurfaceTests(McpTestCase):
    def test_every_tool_has_a_schema_and_an_implementation(self):
        for tool in mcpserver.TOOLS:
            self.assertIn("inputSchema", tool)
            self.assertTrue(hasattr(mcpserver.Server, "_tool_" + tool["name"]), tool["name"])

    def test_no_tool_can_send_a_continuation(self):
        # The property this whole layer exists to keep. A tool that submits would be a
        # second recovery engine, reachable by a model, outside the state machine.
        for tool in mcpserver.TOOLS:
            for word in ("submit", "send", "resume_thread", "force", "continuation"):
                self.assertNotIn(word, tool["name"], tool["name"])

    def test_no_tool_accepts_a_thread_by_anything_but_an_exact_id(self):
        for tool in mcpserver.TOOLS:
            for name, described in tool["inputSchema"].get("properties", {}).items():
                if name.endswith("_id"):
                    self.assertEqual(described.get("pattern"), "^[0-9a-fA-F]{64}$", tool["name"])
                self.assertNotIn(name, ("title", "project", "latest", "last", "recent"))

    def test_the_skill_lists_every_tool_and_no_others(self):
        """The skill tells the model to prefer the tools, then names them.

        A name missing from that list is a tool the model will not reach for, and a name
        that is on it and not in the server is a tool call that fails. Both had happened:
        `restore_default_settings` and `start_watcher` shipped and went unmentioned for
        two releases, because nothing checked.
        """
        skill = (Path(__file__).resolve().parents[1] / "skills" / "codex-auto-resume"
                 / "SKILL.md").read_text(encoding="utf-8")
        preferred = skill.split("## Prefer the tools", 1)[1].split("##", 1)[0]
        named = set(re.findall(r"`([a-z_]+)`", preferred))
        self.assertEqual(named, {tool["name"] for tool in mcpserver.TOOLS})

    def test_read_only_tools_are_marked_read_only(self):
        by_name = {tool["name"]: tool for tool in mcpserver.TOOLS}
        for name in ("open_settings", "get_status", "list_pending"):
            self.assertIs(by_name[name]["annotations"]["readOnlyHint"], True, name)

    def test_the_settings_schema_is_generated_from_the_shared_fields(self):
        properties = mcpserver.settings_schema()["properties"]
        self.assertEqual(set(properties), set(settings.FIELDS))
        self.assertIs(mcpserver.settings_schema()["additionalProperties"], False)

    def test_the_settings_schema_offers_no_unknown_failure_switch(self):
        for name in mcpserver.settings_schema()["properties"]:
            self.assertNotIn("unknown", name)

    def test_published_bounds_match_the_validator(self):
        properties = mcpserver.settings_schema()["properties"]
        for name, described in properties.items():
            if "minimum" in described:
                for value in (described["minimum"], described["maximum"]):
                    settings.validate_update({name: value})

    def test_the_instructions_tell_the_model_the_rules_it_cannot_break(self):
        text = mcpserver.Server(self.control)._initialize({})["instructions"]
        self.assertIn("exact interruption id", text)
        self.assertIn("never by title", text.lower())


class ToolBehaviourTests(McpTestCase):
    def test_status_reports_the_shared_state(self):
        result = self.call("get_status")["result"]
        self.assertIs(result["structuredContent"]["watcher_running"], True)

    def test_update_settings_persists_through_the_shared_layer(self):
        self.call("update_settings", {"max_no_progress": 8})
        self.assertEqual(self.control.get_settings()["max_no_progress"], 8)

    def test_a_refused_setting_is_a_tool_error_not_a_protocol_error(self):
        # The model should read the reason and correct itself, not lose the connection.
        response = self.call("update_settings", {"max_no_progress": 99})
        self.assertNotIn("error", response)
        self.assertIs(response["result"]["isError"], True)

    def test_an_unknown_setting_is_refused(self):
        response = self.call("update_settings", {"retry_unknown_failures": True})
        self.assertIs(response["result"]["isError"], True)

    def test_update_with_no_fields_is_refused(self):
        self.assertIs(self.call("update_settings", {})["result"]["isError"], True)

    def test_pause_keeps_pending_recoveries(self):
        self.register()
        self.call("set_auto_recovery", {"enabled": False})
        self.assertIs(self.control.get_status()["enabled"], False)
        self.assertEqual(len(self.control.list_pending()), 1)

    def test_cancel_requires_the_exact_identifier(self):
        self.register()
        for bad in ("latest", KEY[:-1], "", None):
            self.assertIs(self.call("cancel_recovery", {"interruption_id": bad})["result"]["isError"],
                          True, bad)
        self.assertNotIn("isError", self.call("cancel_recovery", {"interruption_id": KEY})["result"])

    def test_retry_now_does_not_submit(self):
        self.register()
        self.call("retry_now", {"interruption_id": KEY})
        with Store(self.paths.state_dir) as store:
            record = store.get(KEY)
        self.assertIsNone(record["submitted_at"])
        self.assertIsNone(record["queue_id"])
        self.assertEqual(record["attempt_count"], 0)

    def test_retry_now_says_the_checks_still_apply(self):
        self.register()
        text = self.call("retry_now", {"interruption_id": KEY})["result"]["content"][0]["text"]
        self.assertIn("revalidates", text)

    def test_reset_budget_refuses_a_recovery_that_is_not_exhausted(self):
        self.register()
        self.assertIs(self.call("reset_recovery_budget", {"interruption_id": KEY})["result"]["isError"],
                      True)

    def test_unknown_tool_is_an_invalid_params_error(self):
        response = self.call("delete_everything")
        self.assertEqual(response["error"]["code"], mcpserver.INVALID_PARAMS)

    def test_a_tool_name_cannot_reach_an_arbitrary_attribute(self):
        # The handler is looked up by name, so the lookup must not be able to escape
        # the tool namespace into the rest of the object.
        for name in ("_write", "serve", "control", "__init__", "handle"):
            self.assertIn("error", self.call(name), name)


class WidgetTests(McpTestCase):
    def test_open_settings_points_at_the_ui_resource(self):
        result = self.call("open_settings")["result"]
        self.assertEqual(result["_meta"]["openai/outputTemplate"], mcpserver.SETTINGS_UI)

    def test_open_settings_carries_everything_the_panel_renders(self):
        self.register()
        data = self.call("open_settings")["result"]["structuredContent"]
        self.assertEqual(set(data), {"status", "schema", "settings", "pending"})
        self.assertEqual(data["pending"][0]["interruption_id"], KEY)

    def test_open_settings_changes_nothing(self):
        before = self.control.get_settings()
        self.call("open_settings")
        self.assertEqual(self.control.get_settings(), before)
        self.assertFalse(self.paths.settings_file.exists())

    def test_the_ui_resource_is_listed_and_readable(self):
        listed = self.converse({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})[0]
        self.assertEqual(listed["result"]["resources"][0]["uri"], mcpserver.SETTINGS_UI)
        read = self.converse({"jsonrpc": "2.0", "id": 2, "method": "resources/read",
                              "params": {"uri": mcpserver.SETTINGS_UI}})[0]
        self.assertIn("<!doctype html>", read["result"]["contents"][0]["text"])

    def test_an_unknown_resource_is_refused(self):
        response = self.converse({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                                  "params": {"uri": "ui://somewhere/else"}})[0]
        self.assertEqual(response["error"]["code"], mcpserver.INVALID_PARAMS)

    def test_the_panel_fetches_nothing(self):
        # A widget that reaches for a CDN is a blank rectangle on the machine whose
        # network just failed - which is exactly the machine this runs on.
        page = mcpui.settings_page()
        for forbidden in ("http://", "https://", "<script src", "<link ", "@import", "fetch("):
            self.assertNotIn(forbidden, page, forbidden)

    def test_the_panel_carries_no_settings_of_its_own(self):
        # Values come from the tool result, so the page cannot be stale or disagree
        # with what the control layer holds.
        page = mcpui.settings_page()
        self.assertNotIn("max_recovery_attempts\":", page)
        self.assertNotIn("__CODEX_AUTO_RESUME__=", page)

    def test_a_preview_seed_is_escaped(self):
        page = mcpui.settings_page({"status": {"version": "</script><script>x"}})
        self.assertNotIn("</script><script>x", page)


if __name__ == "__main__":
    unittest.main()
