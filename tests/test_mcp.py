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
import shutil
import subprocess
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
                if name == "thread_id":
                    # A conversation is named by its canonical, lowercase UUID and
                    # nothing else - never a title, a prefix or "the latest".
                    self.assertEqual(described.get("pattern"),
                                     "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                                     tool["name"])
                elif name.endswith("_id"):
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
        offered = {e["name"] for e in settings.describe() if e.get("group") in mcpserver.USER_GROUPS}
        self.assertEqual(set(properties), offered)
        self.assertIs(mcpserver.settings_schema()["additionalProperties"], False)

    def test_advanced_settings_are_not_offered_to_a_model(self):
        """codex_exe decides which binary the watcher runs; no GUI shows it, nor may MCP."""
        properties = mcpserver.settings_schema()["properties"]
        for name in ("codex_exe", "detection_lookback_hours"):
            self.assertNotIn(name, properties)

    def test_automation_can_be_reduced_freely_but_only_increased_with_approval(self):
        """Codex asks before a tool marked destructive. Content in a conversation must not
        be able to turn recovery back up behind the user's back."""
        hints = {tool["name"]: tool["annotations"]["destructiveHint"] for tool in mcpserver.TOOLS}
        self.assertNotIn("set_auto_recovery", hints, "one tool for both directions could not ask for one")
        self.assertIs(hints["pause_auto_recovery"], False)
        for name in ("resume_auto_recovery", "reset_recovery_budget", "start_watcher",
                     "update_settings", "restore_default_settings", "cancel_recovery"):
            with self.subTest(name):
                self.assertIs(hints[name], True)
        for name in ("open_settings", "get_status", "list_pending", "retry_now"):
            with self.subTest(name):
                self.assertIs(hints[name], False)

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
        # Start from "on": a fresh home is off already, and this test used to pass without
        # the pause ever happening - it kept passing when the tool it called was removed.
        self.control.set_enabled(True)
        self.assertNotIn("isError", self.call("pause_auto_recovery", {})["result"])
        self.assertIs(self.control.get_status()["enabled"], False)
        self.assertEqual(len(self.control.list_pending()), 1)

    def test_resume_turns_it_back_on(self):
        self.control.set_enabled(False)
        self.assertNotIn("isError", self.call("resume_auto_recovery", {})["result"])
        self.assertIs(self.control.get_status()["enabled"], True)

    def test_an_advanced_setting_is_refused_even_if_the_schema_is_ignored(self):
        response = self.call("update_settings", {"codex_exe": r"C:\somewhere\codex.exe"})
        self.assertIs(response["result"]["isError"], True)
        self.assertIsNone(self.control.get_settings().get("codex_exe"))

    def test_status_does_not_carry_the_install_path(self):
        """MCP output is part of the conversation Codex sends to OpenAI, and the default
        install path contains the Windows user name."""
        status = self.call("get_status", {})["result"]["structuredContent"]
        self.assertNotIn("home", status)
        self.assertNotIn(str(self.control.paths.home), json.dumps(status))

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


class RefusalTests(McpTestCase):
    """A refused call, as far as this layer carries it.

    The English sentence is what the model reads and what a bug report quotes, and it is
    unchanged. The code beside it is the same refusal as a stable machine value, and it is
    the only part of a refusal another surface can say in another language - so a refusal
    that leaves here without one is a panel that can only frame English in Korean.
    """

    def refuse(self, name, arguments=None) -> dict:
        result = self.call(name, arguments or {})["result"]
        self.assertIs(result["isError"], True, name)
        return result

    def test_a_refusal_carries_its_code_beside_the_sentence(self):
        self.register()
        result = self.refuse("reset_recovery_budget", {"interruption_id": KEY})
        self.assertEqual(result["content"][0]["text"], "that recovery has not been exhausted")
        self.assertEqual(result["structuredContent"], {"error_code": "not_exhausted"})

    def test_the_same_refusal_carries_the_same_code_every_time(self):
        # The panel keys its own wording off this, so it has to be stable across calls in
        # a way English prose never promised to be.
        codes = {self.refuse("cancel_recovery", {"interruption_id": "latest"})
                 ["structuredContent"]["error_code"] for _ in range(5)}
        self.assertEqual(codes, {"invalid_id"})

    def test_every_refusal_this_server_can_make_carries_a_code_from_the_set(self):
        self.register()
        for name, arguments in (("cancel_recovery", {"interruption_id": "latest"}),
                                ("retry_now", {"interruption_id": "b" * 64}),
                                ("reset_recovery_budget", {"interruption_id": KEY}),
                                ("enable_conversation_recovery", {"thread_id": "everything"}),
                                ("disable_conversation_recovery", {"thread_id": THREAD.upper()}),
                                ("update_settings", {"max_no_progress": 99}),
                                ("update_settings", {"codex_exe": r"C:\somewhere\codex.exe"}),
                                ("update_settings", {}),
                                ("get_recovery_statistics", {"days": 9999})):
            with self.subTest(name=name, arguments=arguments):
                code = self.refuse(name, arguments)["structuredContent"]["error_code"]
                self.assertIn(code, control.ERROR_CODES)

    def test_a_refusal_this_server_words_itself_carries_a_code_too(self):
        # Not every refusal comes from the control layer; this one is the tool refusing an
        # empty change. It has nothing more specific to say, and the generic code is a real
        # member of the set exactly so that no front end ever has to handle a missing one.
        self.assertEqual(self.refuse("update_settings", {})["structuredContent"]["error_code"],
                         control.FALLBACK_CODE)

    def test_a_refusal_carries_nothing_but_the_sentence_and_the_code(self):
        # This reply is part of the conversation Codex sends on. The code being the
        # machine-readable half is what lets everything else stay out of it.
        self.register()
        result = self.refuse("reset_recovery_budget", {"interruption_id": KEY})
        self.assertEqual(set(result), {"isError", "content", "structuredContent"})
        self.assertEqual(set(result["structuredContent"]), {"error_code"})
        for leak in (KEY, THREAD, str(self.home), "Traceback", "control.py"):
            self.assertNotIn(leak, json.dumps(result), leak)

    def test_a_call_that_succeeds_reports_no_refusal(self):
        result = self.call("get_status")["result"]
        self.assertNotIn("isError", result)
        self.assertNotIn("error_code", result["structuredContent"])


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
        """Vocabulary ships with the page; values do not.

        The served page carries the interface catalog, because the panel has to know what
        to call a setting in the user's language before any tool result arrives. It must
        still carry no *values*: those come from the tool result, so the page cannot be
        stale or disagree with what the control layer holds.

        Checked by looking for the seed object rather than for a setting's name - the
        catalog legitimately contains every setting name as a `field.` key, and an earlier
        substring check could not tell the two apart.
        """
        page = mcpui.settings_page()
        self.assertNotIn("__CODEX_AUTO_RESUME__=", page)
        self.assertIn("__CODEX_AUTO_RESUME_STRINGS__=", page)
        for value_only in ('"settings":', '"pending":', '"schema":', '"watcher_running"'):
            self.assertNotIn(value_only, page, value_only)

    def test_a_preview_seed_is_escaped(self):
        page = mcpui.settings_page({"status": {"version": "</script><script>x"}})
        self.assertNotIn("</script><script>x", page)

    def test_the_panel_is_served_a_sentence_for_every_refusal_it_may_be_handed(self):
        """The catalog shipped with the page has to cover the whole closed set.

        The panel is seeded once and never asks again, so a code whose string is missing
        from the catalog it was served is a refusal it can only show in English - which is
        the gap the codes exist to close.
        """
        catalog = json.loads(mcpui.settings_page().split("__CODEX_AUTO_RESUME_STRINGS__=", 1)[1]
                             .split(";</script>", 1)[0])
        missing = sorted(code for code in control.ERROR_CODES
                         if not catalog.get("error." + code))
        self.assertEqual(missing, [])

    def test_only_the_refusal_helper_reads_the_english_sentence(self):
        # Both failure paths word a refusal the same way. One that reached for
        # `error.message` itself would be the Korean-frame-around-an-English-sentence bug
        # coming back on exactly one button, which is how it went unnoticed the first time.
        self.assertEqual(mcpui._SCRIPT.count("{reason: refusal(error)}"), 2)
        self.assertNotIn("error.message",
                         mcpui._SCRIPT.replace(javascript_function("refusal"), ""))

    def test_the_one_code_the_panel_leaves_in_english_is_the_real_generic_one(self):
        # The panel keeps the sentence for the code the control layer gives a refusal it
        # deliberately leaves unworded, because that sentence names the setting it refused.
        # Renaming the code there without renaming it here would quietly replace those
        # details with "the request could not be completed".
        found = re.search(r"GENERIC_REFUSAL = '([a-z_]+)'", mcpui._SCRIPT)
        self.assertEqual(found.group(1), control.FALLBACK_CODE)


NODE = shutil.which("node")


def javascript_function(name: str) -> str:
    """One top-level function out of the panel's script, by name.

    The script is mostly DOM building, which is not worth running outside a browser. The
    few pieces that are pure string work are top-level functions whose closing brace is in
    the first column, so they can be lifted out and run on their own.
    """
    found = re.search(r"^function %s\(.*?^\}" % name, mcpui._SCRIPT, re.M | re.S)
    assert found, name
    return found.group(0)


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PanelWordingTests(unittest.TestCase):
    """What a Korean reader actually sees when a call is refused.

    Reading the source cannot tell a preference that works from one that throws, and this
    decides the wording of every refusal the panel shows, so the panel's own function is
    lifted out of the script and run rather than described.
    """

    KOREAN = {"error.already_finished": "이미 끝난 복구입니다.",
              "error.request_failed": "요청을 처리하지 못했습니다.",
              "panel.refused": "거부됨"}

    def word(self, error, strings=None) -> str:
        """What `refusal()` shows for one rejected call, run in the panel's own code."""
        script = "\n".join([
            # ASCII-escaped on purpose: the sentences are Korean and the script travels as
            # a command-line argument, so nothing here depends on the console code page.
            "var S = %s;" % json.dumps(self.KOREAN if strings is None else strings),
            re.search(r"var GENERIC_REFUSAL = '[a-z_]+';", mcpui._SCRIPT).group(0),
            javascript_function("t"),
            javascript_function("refusal"),
            "process.stdout.write(refusal(%s));" % json.dumps(error),
        ])
        done = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                              encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_a_coded_refusal_is_shown_in_the_language_the_panel_speaks(self):
        # The bug this closes: a Korean frame around an English sentence.
        self.assertEqual(self.word({"message": "that recovery has already finished",
                                    "structuredContent": {"error_code": "already_finished"}}),
                         self.KOREAN["error.already_finished"])

    def test_the_code_is_found_whether_or_not_the_host_wraps_the_result(self):
        # Hosts differ on what they hand a rejected call, the way they differ on a
        # fulfilled one, and the panel has no say in which shape it gets.
        self.assertEqual(self.word({"message": "that recovery has already finished",
                                    "error_code": "already_finished"}),
                         self.KOREAN["error.already_finished"])

    def test_a_refusal_with_no_code_still_says_what_went_wrong(self):
        # An older watcher, from before the codes. Its sentence is all there is, and it is
        # worth more than a panel that goes quiet about why nothing was saved.
        self.assertEqual(self.word({"message": "that recovery has already finished"}),
                         "that recovery has already finished")

    def test_a_code_this_catalog_cannot_say_falls_back_to_the_sentence(self):
        # A watcher newer than the page it is serving. Same rule, other direction.
        self.assertEqual(self.word({"message": "something new refused it",
                                    "structuredContent": {"error_code": "from_the_future"}}),
                         "something new refused it")

    def test_the_generic_code_keeps_the_detail_its_sentence_carries(self):
        # A value the validator rejected. Its sentence names the setting; the generic
        # string does not, so "Not saved: {reason}" would end up saying nothing twice.
        self.assertEqual(self.word({"message": "max_no_progress must be between 1 and 20",
                                    "structuredContent": {"error_code": "request_failed"}}),
                         "max_no_progress must be between 1 and 20")

    def test_a_refusal_that_says_nothing_at_all_is_still_worded(self):
        self.assertEqual(self.word({}), self.KOREAN["panel.refused"])


if __name__ == "__main__":
    unittest.main()
