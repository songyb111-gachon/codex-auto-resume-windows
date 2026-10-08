"""The settings panel beside a conversation, in the Codex app's right side panel (v0.6.14).

The Codex app shows an MCP tool's page in a conversation inline or "fullscreen", and in a conversation
its fullscreen is the right side panel; a tool that declares a `thread` entrypoint is offered in that
side panel's New tab, under More tools..., and the tab calls it with no arguments. So the panel's tool
declares that entrypoint and nothing else new: the one tool, the one entrypoint, the template Codex
needs (a `ui://` resource), and arguments the tab's empty call satisfies.

Whether the Codex app does what its bundle says is measured on a real machine (MP1-MP3, the advanced
edition's harness); these hold what this product declares.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from codex_auto_resume.mcp import server as mcp_server, tools  # noqa: E402

ENTRYPOINT_TYPES = ("thread", "global", "settings", "file")


class StubControl:
    """Just what the server asks of a control to list its tools and serve its page: no installation,
    no Codex home, no registry - nothing is read or started."""
    plug = types.SimpleNamespace(null=True)

    def get_settings(self):
        return {}


def converse(*messages) -> list:
    lines = "".join(json.dumps(message) + "\n" for message in messages)
    out = io.StringIO()
    mcp_server.Server(StubControl(), io.StringIO(lines), out).serve()
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def listed() -> dict:
    (reply,) = converse({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return {tool["name"]: tool for tool in reply["result"]["tools"]}


def entrypoints(tool) -> list:
    ui = (tool.get("_meta") or {}).get("openai/ui")
    return list(ui.get("entrypoints", [])) if isinstance(ui, dict) else []


class EntrypointTests(unittest.TestCase):
    def test_open_settings_offers_itself_to_a_conversations_side_panel(self):
        self.assertEqual(listed()["open_settings"]["_meta"]["openai/ui"], {"entrypoints": [{"type": "thread"}]})
        self.assertEqual(list(tools.SIDE_PANEL_ENTRYPOINTS), [{"type": "thread"}])

    def test_nothing_else_in_its_meta_changed(self):
        meta = listed()["open_settings"]["_meta"]
        self.assertEqual(set(meta), {"openai/outputTemplate", "openai/toolInvocation/invoking",
                                     "openai/toolInvocation/invoked", "openai/ui"})
        self.assertEqual(meta["openai/outputTemplate"], tools.SETTINGS_UI)

    def test_its_template_is_a_ui_resource_as_codex_requires_of_an_entrypoint(self):
        """Codex drops an entrypoint whose tool's template does not start with ui://."""
        self.assertTrue(listed()["open_settings"]["_meta"]["openai/outputTemplate"].startswith("ui://"))

    def test_the_side_panel_tab_can_call_it_with_nothing_and_it_only_reads(self):
        """The tab calls the tool itself, with {}: it takes no argument, needs none, changes nothing."""
        tool = listed()["open_settings"]
        self.assertEqual(tool["inputSchema"], {"type": "object", "properties": {}, "additionalProperties": False})
        self.assertNotIn("required", tool["inputSchema"])
        self.assertIs(tool["annotations"]["readOnlyHint"], True)
        self.assertIs(tool["annotations"]["destructiveHint"], False)
        answered = {"content": [], "structuredContent": {}}
        with patch.object(mcp_server.Server, "_tool_open_settings", return_value=answered) as opened:
            (reply,) = converse({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                 "params": {"name": "open_settings", "arguments": {}}})
        self.assertEqual(reply["result"], answered)
        opened.assert_called_once_with({})

    def test_no_other_tool_has_an_entrypoint_and_none_reaches_anywhere_else(self):
        """Only the panel's tool, and only beside a conversation: no global sidebar destination, no
        page in Codex's settings, no file opener."""
        offered = {name: entrypoints(tool) for name, tool in listed().items() if entrypoints(tool)}
        self.assertEqual(offered, {"open_settings": [{"type": "thread"}]})
        for tool in tools.TOOLS:
            for entry in entrypoints(tool):
                self.assertIn(entry.get("type"), ENTRYPOINT_TYPES)
                self.assertEqual(entry, {"type": "thread"})

    def test_the_declaration_is_a_copy_a_reply_cannot_change(self):
        tool = next(tool for tool in tools.TOOLS if tool["name"] == "open_settings")
        tool["_meta"]["openai/ui"]["entrypoints"][0]["type"] = "changed"
        try:
            self.assertEqual(list(tools.SIDE_PANEL_ENTRYPOINTS), [{"type": "thread"}])
        finally:
            tool["_meta"]["openai/ui"]["entrypoints"][0]["type"] = "thread"


if __name__ == "__main__":
    unittest.main()
