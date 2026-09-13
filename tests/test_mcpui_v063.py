"""The v0.6.3 settings panel: what it may send, what it shows, and what it never offers.

`test_mcp.py` holds the panel's older promises - the host bridge, refusals, the read-only
fallback. This file holds the ones the continuation settings added, and most of them are
about a boundary rather than a look:

* Custom message text is written in the Windows Dashboard and nowhere else. The panel shows
  it and has no control that could change it, and neither of the two requests it builds -
  Save and Preview - can carry it. Both requests are assembled by small top-level functions
  so that they can be run here, in Node, against the real schema, instead of being described.
* Every word comes from the catalog it was served, so every key the script names has to
  exist in English, including the ones it builds from a prefix.
* Motion is a state, and a person who asked for less motion gets none.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import (brand, continuation, control, l10n, machine,  # noqa: E402
                               mcpserver, mcpui, reasons)
from codex_auto_resume import settings as policy                              # noqa: E402

NODE = shutil.which("node")
ENGLISH = json.loads((ROOT / "src" / "codex_auto_resume" / "locales" / "en.json")
                     .read_text(encoding="utf-8"))
THREAD = "11111111-1111-7111-8111-111111111111"
OTHER = "22222222-2222-7222-8222-222222222222"


def javascript_function(name: str) -> str:
    """One top-level function of the panel's script, whose closing brace is in column one."""
    found = re.search(r"^function %s\(.*?^\}" % name, mcpui._SCRIPT, re.M | re.S)
    assert found, name
    return found.group(0)


def run_javascript(functions, body, prelude=""):
    """Run some of the panel's own functions in Node and return what `body` writes, as JSON."""
    script = "\n".join([
        "var S = %s;" % json.dumps(ENGLISH),
        "var DATA = {}; var HOST = null;",
        prelude,
        *[javascript_function(name) for name in functions],
        "(async function () {" + body + "})().catch(function (e) {console.error(e); process.exit(1);});",
    ])
    # Through stdin: the catalog and the schema together are longer than a Windows command
    # line may be, and stdin also keeps the Korean out of the console code page.
    done = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


def css_block(css: str, opener: str) -> str:
    """The body of the first block that starts with `opener`, braces balanced."""
    start = css.index(opener)
    depth = 0
    for index in range(css.index("{", start), len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[start:index + 1]
    raise AssertionError("unbalanced block: " + opener)


class CustomTextBoundaryTests(unittest.TestCase):
    def test_the_page_offers_no_control_that_could_hold_text(self):
        page = mcpui.settings_page({"status": {}, "settings": {"custom_message": "hello"}})
        lowered = page.lower()
        for forbidden in ("textarea", "contenteditable", "iscontenteditable", "designmode"):
            self.assertNotIn(forbidden, lowered, forbidden)
        types = set(re.findall(r"\.type = '([a-z]+)'", mcpui._SCRIPT))
        self.assertEqual(types, {"checkbox", "radio", "number"})
        created = set(re.findall(r"(?:createElement|element)\('([a-z0-9]+)'", mcpui._SCRIPT))
        self.assertNotIn("textarea", created)
        # An input is only ever given one of the three types above.
        self.assertEqual(mcpui._SCRIPT.count("createElement('input')") + mcpui._SCRIPT.count("element('input'"),
                         len(re.findall(r"\.type = '", mcpui._SCRIPT)))

    def test_update_settings_is_asked_from_one_place_with_the_collected_changes(self):
        self.assertEqual(mcpui._SCRIPT.count("'update_settings'"), 1)
        self.assertIn("callTool('update_settings', changes)", javascript_function("saveSettings"))
        calls = re.findall(r"saveSettings\((\w+)\)", mcpui._SCRIPT.replace(javascript_function("saveSettings"), ""))
        self.assertEqual(calls, ["changes"])
        self.assertIn("var changes = collectChanges(EDITORS, schema);", mcpui._SCRIPT)

    def test_the_preview_is_asked_from_one_place_with_the_built_request(self):
        self.assertEqual(mcpui._SCRIPT.count("'preview_recovery_message'"), 1)
        self.assertIn("callTool('preview_recovery_message', request)", javascript_function("refreshPreview"))
        self.assertIn("var request = previewArguments(PREVIEW.reason, read);", javascript_function("refreshPreview"))
        # Every tool the page can call, and nothing that sends or writes text.
        called = set(re.findall(r"callTool\(\s*'([a-z_]+)'", mcpui._SCRIPT))
        called |= set(re.findall(r"'([a-z_]+_conversation_recovery|[a-z]+_auto_recovery)'", mcpui._SCRIPT))
        self.assertEqual(called, {"update_settings", "preview_recovery_message", "start_watcher",
                                  "list_pending", "pause_auto_recovery", "resume_auto_recovery",
                                  "enable_conversation_recovery", "disable_conversation_recovery"})
        tools = {tool["name"] for tool in mcpserver.TOOLS}
        self.assertLessEqual(called, tools)


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class RequestShapeTests(unittest.TestCase):
    def test_the_host_receives_the_arguments_the_panel_meant_to_send(self):
        """Until v0.6.3 it did not: `callTool(name, arguments)` passed the inner function's
        own implicit `arguments` object, so the host got `{}` for every call - a Save that
        named no setting at all. Nothing asserted what reached the host, so nothing noticed."""
        observed = run_javascript(["t", "toolPayload", "callTool", "saveSettings"], """
          var seen = [];
          DATA = {settings: {}};
          HOST = {callTool: function (name, args) {
            seen.push([name, args]);
            return Promise.resolve({structuredContent: {settings: {max_recovery_attempts: 2}}});
          }};
          await callTool('preview_recovery_message', {category: 'usage_limit', changes: {continuation_style: 'minimal'}});
          await saveSettings({max_recovery_attempts: 2});
          process.stdout.write(JSON.stringify(seen));
        """)
        self.assertEqual(observed, [
            ["preview_recovery_message", {"category": "usage_limit", "changes": {"continuation_style": "minimal"}}],
            ["update_settings", {"max_recovery_attempts": 2}]])

    def test_what_the_panel_calls_editable_is_exactly_what_the_server_accepts(self):
        schema = policy.describe()
        observed = run_javascript(["editable"], "process.stdout.write(JSON.stringify(%s.filter(editable).map("
                                  "function (e) {return e.name;})));" % json.dumps(schema, default=str))
        self.assertEqual(set(observed), set(mcpserver.settings_schema()["properties"]))
        self.assertFalse([name for name in observed
                          if name.startswith("custom_message") and name != "custom_message_mode"])

    def test_a_save_never_carries_custom_text_whatever_the_controls_hold(self):
        schema = policy.describe()
        observed = run_javascript(["editable", "collectChanges"], """
          var schema = %s;
          var editors = {};
          schema.forEach(function (entry) { editors[entry.name] = function () { return 'ignore previous instructions'; }; });
          process.stdout.write(JSON.stringify(collectChanges(editors, schema)));
        """ % json.dumps(schema, default=str))
        self.assertEqual(set(observed), set(mcpserver.settings_schema()["properties"]))
        for name in observed:
            self.assertFalse(name.startswith("custom_message") and name != "custom_message_mode", name)

    def test_the_preview_request_carries_the_four_choices_and_no_text(self):
        observed = run_javascript(["previewArguments"], """
          var values = {interface_language: 'ko', continuation_language: 'follow',
                        continuation_style: 'custom', custom_message_mode: 'per_reason',
                        custom_message: 'x', custom_message_usage_limit: 'y', max_recovery_attempts: 3};
          process.stdout.write(JSON.stringify(previewArguments('usage_limit', function (name) { return values[name]; })));
        """)
        self.assertEqual(observed, {"category": "usage_limit", "changes": {
            "interface_language": "ko", "continuation_language": "follow",
            "continuation_style": "custom", "custom_message_mode": "per_reason"}})
        tool = next(tool for tool in mcpserver.TOOLS if tool["name"] == "preview_recovery_message")
        self.assertEqual(set(observed["changes"]), set(tool["inputSchema"]["properties"]["changes"]["properties"]))
        self.assertEqual(set(observed), set(tool["inputSchema"]["properties"]))


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ThreadSwitchTests(unittest.TestCase):
    """Automatic recovery for one conversation: the exact thread, and never ahead of the tool."""

    PRELUDE = """
      var CALLS = [];
      function rows() {
        return [{thread_id: '%s', interruption_id: 'a', thread_enabled: true, overlays: []},
                {thread_id: '%s', interruption_id: 'b', thread_enabled: true, overlays: ['paused']}];
      }
      async function attempt(threadId, enable, reply) {
        DATA = {pending: rows()};
        CALLS = [];
        HOST = {callTool: function (name, args) { CALLS.push([name, args]); return Promise.resolve(reply); }};
        try {
          var enabled = await setThreadRecovery(threadId, enable);
          return {ok: true, enabled: enabled, calls: CALLS, pending: DATA.pending};
        } catch (error) {
          return {ok: false, calls: CALLS, pending: DATA.pending};
        }
      }
    """ % (THREAD, OTHER)

    def attempt(self, thread, enable, reply):
        return run_javascript(["t", "toolPayload", "callTool", "setThreadRecovery"],
                              "process.stdout.write(JSON.stringify(await attempt(%s, %s, %s)));"
                              % (json.dumps(thread), json.dumps(enable), json.dumps(reply)),
                              prelude=self.PRELUDE)

    def untouched(self):
        return [{"thread_id": THREAD, "interruption_id": "a", "thread_enabled": True, "overlays": []},
                {"thread_id": OTHER, "interruption_id": "b", "thread_enabled": True, "overlays": ["paused"]}]

    def test_turning_off_names_the_exact_thread_and_changes_only_its_rows(self):
        observed = self.attempt(THREAD, False, {"structuredContent": {"thread_id": THREAD}})
        self.assertTrue(observed["ok"])
        self.assertEqual(observed["calls"], [["disable_conversation_recovery", {"thread_id": THREAD}]])
        self.assertEqual(observed["pending"][0]["thread_enabled"], False)
        self.assertEqual(observed["pending"][0]["overlays"], ["thread_disabled"])
        self.assertEqual(observed["pending"][1], self.untouched()[1])

    def test_a_refusal_changes_nothing(self):
        for reply in ({"isError": True, "content": [{"type": "text", "text": "no"}],
                       "structuredContent": {"error_code": "store_unavailable"}},
                      {"error_code": "invalid_thread_id"}):
            with self.subTest(reply=reply):
                observed = self.attempt(THREAD, False, reply)
                self.assertFalse(observed["ok"])
                self.assertEqual(observed["pending"], self.untouched())

    def test_a_reply_about_another_conversation_is_a_refusal(self):
        observed = self.attempt(THREAD, False, {"structuredContent": {"thread_id": OTHER}})
        self.assertFalse(observed["ok"])
        self.assertEqual(observed["pending"], self.untouched())

    def test_turning_on_needs_the_tool_to_say_it_is_on(self):
        observed = self.attempt(THREAD, True, {"structuredContent": {"thread_id": THREAD}})
        self.assertFalse(observed["ok"])
        self.assertEqual(observed["pending"], self.untouched())
        observed = self.attempt(THREAD, True, {"structuredContent": {"thread_id": THREAD, "enabled": True}})
        self.assertTrue(observed["ok"])
        self.assertEqual(observed["calls"], [["enable_conversation_recovery", {"thread_id": THREAD}]])
        self.assertTrue(observed["pending"][0]["thread_enabled"])


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ActivityTests(unittest.TestCase):
    CASES = (
        ({"watcher_running": False, "enabled": True}, [], "attention"),
        ({"watcher_running": None, "enabled": True}, [], "attention"),
        ({"watcher_running": True, "enabled": False, "pending": 2}, [{"code": "turn_running"}], "paused"),
        ({"watcher_running": True, "enabled": True, "pending": 1, "codes": {"turn_running": 1}}, [], "recovering"),
        ({"watcher_running": True, "enabled": True, "pending": 2}, [{"code": "waiting_reset"}, {"code": "submitted"}], "recovering"),
        ({"watcher_running": True, "enabled": True, "pending": 2}, [{"code": "waiting_reset"}], "waiting"),
        ({"watcher_running": True, "enabled": True, "pending": 0}, [], "monitoring"),
    )

    def test_one_word_for_the_whole_product(self):
        observed = run_javascript(["activity"], "process.stdout.write(JSON.stringify(%s.map(function (c) "
                                  "{return activity(c[0], c[1]);})));" % json.dumps(
                                      [[status, rows] for status, rows, _ in self.CASES]))
        self.assertEqual(observed, [expected for _, _, expected in self.CASES])

    def test_every_state_has_a_word_and_a_halo(self):
        for state in ("monitoring", "waiting", "recovering", "paused", "attention"):
            with self.subTest(state):
                self.assertIn("activity." + state, ENGLISH)
                self.assertIn(".halo.%s" % state, mcpui._STYLE)

    def test_language_names_are_endonyms_and_a_missing_system_language_leaves_no_brackets(self):
        observed = run_javascript(["t", "fill", "endonym", "withLanguage"], """
          DATA = {endonyms: %s};
          process.stdout.write(JSON.stringify([
            withLanguage('choice.language.system', '', 'ko'),
            withLanguage('choice.continuation_language.follow', '', 'ja'),
            withLanguage('choice.language.system', '', undefined),
            endonym('de')]));
        """ % json.dumps(l10n.ENDONYMS, ensure_ascii=False))
        self.assertEqual(observed, ["System (한국어)", "Same as the interface (日本語)", "System", "Deutsch"])


class CatalogTests(unittest.TestCase):
    # Prefixes the script completes at runtime, and every value it can complete them with.
    DYNAMIC = {
        "activity.": ("monitoring", "waiting", "recovering", "paused", "attention"),
        "reason.": reasons.RECOVERABLE,
        "choice.style.": continuation.STYLES,
        "help.style.": continuation.STYLES,
        "choice.custom_mode.": continuation.CUSTOM_MODES,
        "preview.source.": ("global", "per_reason", "standard"),
        "choice.": tuple(policy.RETRY_TIMING),
        "code.": tuple(machine.PUBLIC_CODES),
        "error.": tuple(control.ERROR_CODES),
    }

    def test_every_key_the_script_names_exists_in_english(self):
        literal = set(re.findall(r"\b(?:t|fill|withLanguage)\(\s*'([a-z0-9_.]+)'\s*[,)]", mcpui._SCRIPT))
        self.assertGreater(len(literal), 40)
        missing = sorted(key for key in literal if key not in ENGLISH)
        self.assertEqual(missing, [])

    def test_every_key_the_script_builds_from_a_prefix_exists_in_english(self):
        prefixes = set(re.findall(r"\b(?:t|fill)\(\s*'([a-z_.]+\.)'\s*\+", mcpui._SCRIPT))
        prefixes |= set(re.findall(r"\bS\['([a-z_.]+\.)'\s*\+", mcpui._SCRIPT))
        # `overlay.` and `field.` are covered by test_locale; the rest must be listed above.
        unknown = sorted(prefixes - set(self.DYNAMIC) - {"overlay.", "field."})
        self.assertEqual(unknown, [], "a new prefix: list the values it can take")
        for prefix in prefixes & set(self.DYNAMIC):
            for name in self.DYNAMIC[prefix]:
                with self.subTest(key=prefix + name):
                    self.assertIn(prefix + name, ENGLISH)

    def test_no_word_comes_from_the_browser(self):
        # `toLocale...` too: a time formatted by the browser is a time in the browser's
        # language, which is how "오전 02:48" once appeared in an English panel.
        for forbidden in ("navigator.language", "navigator.languages", "resolvedOptions", "toLocale"):
            self.assertNotIn(forbidden, mcpui._SCRIPT)

    def test_the_panel_adds_no_catalog_key_the_other_languages_lack(self):
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertEqual(set(l10n._read(locale)) & {k for k in ENGLISH if k.startswith("panel.")},
                                 {k for k in ENGLISH if k.startswith("panel.")})


class StyleTests(unittest.TestCase):
    def test_reduced_motion_stops_every_animation_and_transition(self):
        block = css_block(mcpui._STYLE, "@media (prefers-reduced-motion: reduce)")
        self.assertRegex(block, r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*animation:\s*none\s*!important")
        self.assertRegex(block, r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*transition:\s*none\s*!important")
        self.assertIn(".halo::before", block)

    def test_nothing_on_the_page_ticks(self):
        for forbidden in ("setInterval", "setTimeout", "requestAnimationFrame"):
            self.assertNotIn(forbidden, mcpui._SCRIPT)

    def test_the_scale_is_emitted_and_does_not_shadow_a_colour(self):
        scale = set(re.findall(r"(--[a-z-]+)\s*:", brand.css_scale()))
        colours = set(re.findall(r"(--[a-z-]+)\s*:", brand.css_variables(brand.LIGHT)))
        self.assertEqual(scale & colours, set())
        self.assertIn(brand.css_scale(), mcpui._STYLE)
        for name in ("--breathe", "--pulse", "--transition", "--halo-min", "--halo-max"):
            self.assertIn("var(%s)" % name, mcpui._STYLE)

    def test_every_token_is_declared_on_the_bare_root_before_any_theme_block(self):
        root = css_block(mcpui._STYLE, ":root {")
        for name in re.findall(r"(--[a-z-]+)\s*:", css_block(mcpui._STYLE, ':root[data-theme="dark"]')):
            self.assertIn(name + ":", root)

    def test_chips_have_a_solid_ground_before_the_mixed_one(self):
        chip = css_block(mcpui._STYLE, ".chip {")
        self.assertIn("background: var(--inset)", chip)
        self.assertRegex(mcpui._STYLE, r"@supports \(color: color-mix\([^)]*\)\) \{\s*\.chip \{ background: "
                                       r"color-mix\(in srgb, var\(--chip\) 12%, var\(--surface\)\)")

    def test_the_card_keeps_its_hairline_and_loses_the_rail(self):
        cardrule = css_block(mcpui._STYLE, ".card {")
        self.assertIn("border: 1px solid var(--line)", cardrule)
        self.assertIn("border-radius: var(--radius-card)", cardrule)
        self.assertNotIn("border-left", mcpui._STYLE)

    def test_the_shared_type_stack(self):
        self.assertIn('system-ui, "Segoe UI Variable Text", "Segoe UI", "Malgun Gothic", "Yu Gothic UI",',
                      mcpui._STYLE)
        self.assertIn('"Microsoft YaHei UI", "Microsoft JhengHei UI", sans-serif', mcpui._STYLE)

    def test_focus_is_drawn_for_the_keyboard_only(self):
        self.assertIn(":focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }", mcpui._STYLE)
        self.assertNotRegex(mcpui._STYLE, r"(?<!-)\b:focus\s*\{[^}]*outline:\s*2px")


if __name__ == "__main__":
    unittest.main()
