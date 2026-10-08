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
import shutil
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.mcp import panel as mcpui, server as mcp_server, tools  # noqa: E402
import test_mcpui_v064 as panelpage  # noqa: E402
from test_mcpui_v063 import RULES  # noqa: E402

ENTRYPOINT_TYPES = ("thread", "global", "settings", "file")
NODE = shutil.which("node")
ENGLISH = l10n.catalog("en")
say = panelpage.say


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


def read_page() -> dict:
    """resources/read of the panel's page, the page itself stood in for: only its envelope is asked."""
    with patch("codex_auto_resume.mcp.panel.settings_page", return_value="<!doctype html>"):
        (reply,) = converse({"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                             "params": {"uri": tools.SETTINGS_UI}})
    (item,) = reply["result"]["contents"]
    return item


class DisplayModeTests(unittest.TestCase):
    """The page tells Codex it may be shown in the conversation or beside it - in the conversation first.
    The Codex app reads both from the resources/read item's `_meta["openai/ui"]`; a page that names its
    modes and no preferred one starts beside the chat there."""

    def test_the_page_says_it_can_sit_in_the_conversation_or_beside_it_in_the_conversation_first(self):
        self.assertEqual(read_page()["_meta"], {"openai/ui": {"availableDisplayModes": ["inline", "fullscreen"],
                                                              "preferredDisplayMode": "inline"}})

    def test_a_preferred_mode_is_one_of_its_modes_and_is_said_whenever_they_are(self):
        ui = read_page()["_meta"]["openai/ui"]
        self.assertTrue(ui["availableDisplayModes"])
        self.assertIn(ui["preferredDisplayMode"], ui["availableDisplayModes"])
        self.assertEqual(tools.PANEL_PREFERRED_MODE, "inline", "beside the chat by default waits for MP2")

    def test_picture_in_picture_is_not_offered(self):
        """The Codex app never shows a page in pip, so the page does not ask for it."""
        self.assertNotIn("pip", read_page()["_meta"]["openai/ui"]["availableDisplayModes"])
        self.assertEqual(set(tools.PANEL_DISPLAY_MODES), {"inline", "fullscreen"})

    def test_it_is_still_the_same_skybridge_page_and_the_listing_is_unchanged(self):
        item = read_page()
        self.assertEqual((item["uri"], item["mimeType"], item["text"]),
                         (tools.SETTINGS_UI, "text/html+skybridge", "<!doctype html>"))
        (reply,) = converse({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
        self.assertEqual(reply["result"]["resources"], [{
            "uri": tools.SETTINGS_UI, "name": "Codex Auto Resume settings",
            "description": "The settings panel shown by open_settings.", "mimeType": "text/html+skybridge"}])


# ------------------------------------------------------------------------------ the page in Node
# The panel's own script in the stand-in document of test_mcpui_v064. Its host is the one `stored()` makes
# there, given what the Codex app adds to it - requestDisplayMode, displayMode - after `stored()` has made it
# (run_page's `host`), and listeners the test can fire: the stand-in's window and document have none.
LISTENERS = r"""
var LISTENED = {};
window.addEventListener = function (type, fn) { (LISTENED['window:' + type] = LISTENED['window:' + type] || []).push(fn); };
document.addEventListener = function (type, fn) { (LISTENED['document:' + type] = LISTENED['document:' + type] || []).push(fn); };
document.visibilityState = 'visible';
function fire(where, type, detail) {
  (LISTENED[where + ':' + type] || []).forEach(function (fn) { fn({type: type, detail: detail}); });
}
"""


def host(mode="inline", request=True, answer="{mode: 'fullscreen'}"):
    """What the Codex app adds to the page's host: the mode it says the page is shown in, and a
    requestDisplayMode that records each request and answers `answer` (a JavaScript expression; a
    rejection is `Promise.reject(new Error('no'))`)."""
    lines = ["var MODES = [];"]
    if mode is not None:
        lines.append("window.openai.displayMode = %s;" % json.dumps(mode))
    if request:
        lines.append("window.openai.requestDisplayMode = function (args) { MODES.push(args); return Promise.resolve(%s); };"
                     % answer)
    return "\n".join(lines)


def page(body, mode="inline", request=True, answer="{mode: 'fullscreen'}", data=None, extra=""):
    if not NODE:
        raise unittest.SkipTest("needs Node to run the panel's own code")
    return panelpage.run_page(body, data=data, prelude=LISTENERS,
                              host=host(mode, request, answer) + "\n" + extra)


SAVEBAR = r"""
function savebar() { return ROOT_NODE.all(function (n) { return n.tagName === 'footer' && n.className === 'savebar'; })[0]; }
function beside() { var bar = savebar(); return bar ? bar.children.filter(function (n) { return n.className === 'beside'; })[0] : undefined; }
function shown() { var b = beside(); return b ? (b.hidden ? 'hidden' : 'shown') : 'absent'; }
"""


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class BesideButtonTests(unittest.TestCase):
    """Open beside the chat: offered only where the host can move the page and says it is inline, at
    the save bar's leading edge, asking only from its click, and gone for good once Codex keeps it."""

    def test_it_is_offered_where_the_host_can_move_an_inline_page_first_in_the_save_bar(self):
        seen = page(SAVEBAR + say("""{shown: shown(), first: savebar().children[0] === beside(),
            last: savebar().children[savebar().children.length - 1].textContent, text: beside().textContent,
            modes: MODES}"""))
        self.assertEqual(seen, {"shown": "shown", "first": True, "last": ENGLISH["action.save"],
                                "text": ENGLISH["action.open_beside"], "modes": []})
        self.assertEqual(ENGLISH["action.open_beside"], "Open beside the chat")

    def test_it_is_not_offered_beside_the_chat_nor_where_the_host_cannot_say_or_move(self):
        for mode, request, expected in (("fullscreen", True, "hidden"), (None, True, "hidden"),
                                        ("pip", True, "hidden"), ("inline", False, "absent")):
            with self.subTest(mode=mode, request=request):
                self.assertEqual(page(SAVEBAR + say("shown()"), mode=mode, request=request), expected)

    def test_without_a_host_there_is_nothing_to_offer(self):
        seen = page(SAVEBAR + say("shown()"), extra="window.openai = {requestDisplayMode: function () {}, "
                                                     "displayMode: 'inline'};")
        self.assertEqual(seen, "absent")

    def test_its_click_asks_once_for_beside_the_chat_and_calls_no_tool(self):
        seen = page(SAVEBAR + """var before = CALLS.length; beside().onclick(); await settle();"""
                    + say("{modes: MODES, calls: CALLS.slice(before), shown: shown(), note: footerNote().textContent}"))
        self.assertEqual(seen, {"modes": [{"mode": "fullscreen"}], "calls": [], "shown": "hidden", "note": ""})

    def test_an_answer_that_keeps_the_page_here_or_a_refusal_hides_it_for_good_and_says_so(self):
        for answer in ("{mode: 'inline'}", "Promise.reject(new Error('no'))", "undefined"):
            with self.subTest(answer=answer):
                seen = page(SAVEBAR + """beside().onclick(); await settle(); var note = footerNote().textContent;
                    var after = shown(); render(); fire('window', 'openai:set_globals', {globals: {displayMode: 'inline'}});"""
                            + say("{note: note, after: after, redrawn: shown(), modes: MODES.length}"), answer=answer)
                self.assertEqual(seen, {"note": ENGLISH["panel.beside_refused"], "after": "hidden",
                                        "redrawn": "absent", "modes": 1})
        self.assertEqual(ENGLISH["panel.beside_refused"], "Codex kept the panel here.")

    def test_the_page_never_asks_by_itself(self):
        seen = page(SAVEBAR + """render(); fire('window', 'openai:set_globals', {globals: {}});
            window.openai.displayMode = 'fullscreen'; fire('window', 'openai:set_globals', {globals: {}});
            window.openai.displayMode = 'inline'; fire('window', 'openai:set_globals', {globals: {}});
            fire('window', 'focus'); fire('document', 'visibilitychange'); await settle();""" + say("MODES"))
        self.assertEqual(seen, [])

    def test_a_change_of_mode_shows_or_hides_it_in_place(self):
        seen = page(SAVEBAR + """var drawn = ROOT_NODE.children[0], button = beside(), seen = [shown()];
            window.openai.displayMode = 'fullscreen'; fire('window', 'openai:set_globals', {globals: {displayMode: 'fullscreen'}});
            seen.push(shown());
            window.openai.displayMode = 'inline'; fire('window', 'openai:set_globals', {globals: {displayMode: 'inline'}});
            seen.push(shown());"""
                    + say("{seen: seen, same: ROOT_NODE.children[0] === drawn && beside() === button}"))
        self.assertEqual(seen, {"seen": ["shown", "hidden", "shown"], "same": True})

    def test_the_bar_keeps_it_at_its_leading_edge_when_it_wraps(self):
        """Every button in the bar takes an automatic start margin, which would push this one to the end
        of a wrapped line; its own rule puts it back at the start."""
        rules = [(selectors, declarations) for context, selectors, declarations in RULES if context == ""]
        own = [declarations for selectors, declarations in rules if ".savebar .beside" in selectors]
        self.assertEqual([declarations.get("margin-inline-start") for declarations in own], ["0"])
        shared = [declarations for selectors, declarations in rules if ".savebar button" in selectors]
        self.assertEqual([declarations.get("margin-inline-start") for declarations in shared], ["auto"])

    def test_every_language_has_its_words(self):
        names, _prefixes = mcpui.panel_keys()
        self.assertLessEqual({"action.open_beside", "panel.beside_refused"}, names)
        for locale in l10n.OFFERED:
            catalog = mcpui.panel_catalogs()[locale]
            with self.subTest(locale):
                for key in ("action.open_beside", "panel.beside_refused"):
                    self.assertTrue(catalog[key].strip())
                    if locale != "en":
                        self.assertNotEqual(catalog[key], ENGLISH[key])
        self.assertEqual(mcpui.panel_catalogs()["ko"]["action.open_beside"], "채팅 옆에 열기")


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class LateResultTests(unittest.TestCase):
    """The side panel's tab calls the tool itself, and Codex may hand the page its result after the page
    has started: a page with nothing to draw from takes it when the host says it changed."""

    EMPTY = "window.__CODEX_AUTO_RESUME__ = undefined;"

    def test_a_result_that_arrives_after_the_page_started_is_drawn(self):
        for given in ("window.openai.toolOutput = window.LATE; fire('window', 'openai:set_globals', {globals: {}});",
                      "fire('window', 'openai:set_globals', {globals: {toolOutput: window.LATE}});",
                      "window.openai.toolOutput = JSON.stringify(window.LATE); fire('window', 'openai:set_globals', {globals: {}});"):
            with self.subTest(given=given):
                seen = page(SAVEBAR + "var before = ROOT_NODE.textContent; " + given + " await settle();"
                            + say("{before: before, drawn: !!savebar(), offered: shown()}"),
                            extra=self.EMPTY + " window.LATE = %s;" % json.dumps(panelpage.snapshot()))
                self.assertEqual(seen, {"before": ENGLISH["panel.unavailable"], "drawn": True, "offered": "shown"})

    def test_nothing_that_is_not_a_result_is_drawn_and_a_drawn_page_is_not_replaced(self):
        seen = page(SAVEBAR + """fire('window', 'openai:set_globals', {globals: {toolOutput: 'not json'}});
            fire('window', 'openai:set_globals', {globals: {toolOutput: [1, 2]}}); var empty = ROOT_NODE.textContent;"""
                    + say("empty"), extra=self.EMPTY)
        self.assertEqual(seen, ENGLISH["panel.unavailable"])
        seen = page(SAVEBAR + """var drawn = ROOT_NODE.children[0];
            fire('window', 'openai:set_globals', {globals: {toolOutput: {status: {}, settings: {}, pending: []}}});"""
                    + say("ROOT_NODE.children[0] === drawn"))
        self.assertIs(seen, True)


if __name__ == "__main__":
    unittest.main()
