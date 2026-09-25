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
* The look is brand's. The panel is the design the window and the popup follow, so its lift,
  its status light and that light's glow are read from `brand` and not written here, and
  these tests hold each one to brand's numbers - the glow down to its curve.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

from codex_auto_resume import (brand,
                               compat,
                               continuation,
                               control,
                               l10n,
                               machine,
                               mcpserver,
                               reasons)
from codex_auto_resume.mcp import panel as mcpui
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


def css_rules(css: str, context: str = ""):
    """Every plain rule as (enclosing at-rule, selectors, declarations), at-rule bodies included."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found, position = [], 0
    while True:
        opening = css.find("{", position)
        if opening < 0:
            return found
        depth = 0
        for closing in range(opening, len(css)):
            depth += {"{": 1, "}": -1}.get(css[closing], 0)
            if depth == 0:
                break
        prelude, body = " ".join(css[position:opening].split()), css[opening + 1:closing]
        if prelude.startswith("@"):
            found.extend(css_rules(body, prelude))
        else:
            declarations = {}
            for part in body.split(";"):
                if ":" in part:
                    name, value = part.split(":", 1)
                    declarations[name.strip()] = " ".join(value.split())
            found.append((context, tuple(name.strip() for name in prelude.split(",")), declarations))
        position = closing + 1


RULES = css_rules(mcpui._STYLE)
ROOT_TOKENS = next(declarations for context, selectors, declarations in RULES
                   if context == "" and selectors == (":root",))


def declared(selector: str, prop: str, context: str = ""):
    """The last value a rule naming exactly `selector` gives `prop`, inside one at-rule."""
    values = [declarations[prop] for where, selectors, declarations in RULES
              if where == context and selector in selectors and prop in declarations]
    return values[-1] if values else None


def resolve(value: str) -> str:
    """A value with every var() replaced by what the bare :root declares."""
    while "var(" in value:
        value = re.sub(r"var\((--[a-z0-9-]+)\)", lambda match: ROOT_TOKENS[match.group(1)], value)
    return value


def painted(value: str, tokens: dict) -> str:
    """A colour of the stylesheet as the `#RRGGBB` it paints with one theme's tokens."""
    while "var(" in value:
        value = re.sub(r"var\((--[a-z0-9-]+)\)", lambda match: tokens[match.group(1)], value)
    mixed = re.fullmatch(r"color-mix\(in srgb, (#[0-9A-Fa-f]{6}) ([0-9.]+)%, (#[0-9A-Fa-f]{6})\)", value)
    return brand.mix(mixed.group(3), mixed.group(1), float(mixed.group(2)) / 100) if mixed else value


def number(value: str, unit: str = "") -> float:
    value = resolve(value)
    assert value.endswith(unit), (value, unit)
    return float(value[:len(value) - len(unit)] if unit else value)


def cubic_bezier(easing: str, progress: float) -> float:
    """What a CSS `cubic-bezier()` timing function gives at `progress`."""
    x1, y1, x2, y2 = (float(part) for part in
                      re.fullmatch(r"cubic-bezier\(([^)]*)\)", resolve(easing)).group(1).split(","))
    low, high = 0.0, 1.0
    for _ in range(60):
        middle = (low + high) / 2
        at = 3 * (1 - middle) ** 2 * middle * x1 + 3 * (1 - middle) * middle ** 2 * x2 + middle ** 3
        low, high = (middle, high) if at < progress else (low, middle)
    middle = (low + high) / 2
    return 3 * (1 - middle) ** 2 * middle * y1 + 3 * (1 - middle) * middle ** 2 * y2 + middle ** 3


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
        # v0.6.10: the one rule every header keeps (tests/data/light_states.json, tests/test_light_parity.py). A
        # watcher that runs but is not well needs a person here too, as it did in the popup and the window; a record
        # being withdrawn is recovering; recovery not known to be on is paused.
        ({"watcher_running": True, "enabled": True, "watcher": {"ticking": False}}, [], "attention"),
        ({"watcher_running": True, "enabled": True, "upgrade_pending": True, "pending": 1}, [], "attention"),
        ({"watcher_running": True, "enabled": True, "watcher": {"engine_state": "incompatible"}}, [], "attention"),
        ({"watcher_running": True, "enabled": False, "pending": 1},
         [{"code": "scheduled", "overlays": ["paused", "watcher_not_ticking"]}], "attention"),
        ({"watcher_running": True, "enabled": True, "pending": 1}, [{"code": "withdrawing"}], "recovering"),
        ({"watcher_running": True, "pending": 0}, [], "paused"),
    )

    def test_one_word_for_the_whole_product(self):
        observed = run_javascript(["activity", "attentionCause"], "process.stdout.write(JSON.stringify(%s.map(function (c) "
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
        "choice.theme.": policy.THEMES,
        "choice.panel_theme.": policy.PANEL_THEMES,
        "preview.source.": ("global", "per_reason", "standard"),
        "choice.": tuple(policy.RETRY_TIMING),
        "code.": tuple(machine.PUBLIC_CODES),
        "error.": tuple(control.ERROR_CODES),
        # v0.6.5, the Codex compatibility card: every part the registry names, its four states and what
        # each means, why a report cannot be used, and where the data in force came from.
        "compat.capability.": tuple(compat.CAPABILITIES),
        "compat.state.": compat.STATES,
        "compat.meaning.": compat.STATES,
        "compat.status.": tuple(status for status in compat.VIEW_STATUSES if status != "ok"),
        "compat.source.": compat.DATA_SOURCES,
        # The refreshed data's standings that are more than "in force", said as the window says them.
        "compat.cache.": tuple(state for state in compat.CACHE_STATES if state not in ("absent", "ok")),
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
        for name in ("--transition", "--glow-reach", "--glow-edge", "--glow-near", "--glow-far",
                     "--glow-outer", "--glow-edge-mix", "--glow-near-mix", "--glow-far-mix",
                     "--glow-from", "--glow-monitoring-ms", "--glow-recovering-ms", "--glow-attention-ms"):
            self.assertIn("var(%s)" % name, mcpui._STYLE)
        # Since v0.6.6 the breath's own numbers are in the keyframes, sampled from the curve, so the peak and
        # the dot's low are not variables the stylesheet reads any more.
        for gone in ("--glow-peak", "--glow-dot-low"):
            self.assertNotIn(gone, brand.css_scale())
        # v0.6.3's halo numbers, which the glow replaced, and the first v0.6.5 cut's breathing glow, which
        # the blink replaced, are neither used nor emitted.
        for name in ("--breathe", "--pulse", "--halo-min", "--halo-max", "--glow-still", "--glow-attention-peak",
                     "--glow-monitoring-low", "--glow-monitoring-rest", "--glow-recovering-scale-high"):
            self.assertNotIn("var(%s)" % name, mcpui._STYLE)
            self.assertNotIn(name + ":", brand.css_scale())

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


# The lift exactly as v0.6.3 wrote it by hand in this module, which brand now writes.
V063_ELEVATION_LIGHT = (
    "--elev-card: 4px 4px 14px color-mix(in srgb, var(--shadow-dark) 55%, transparent), "
    "-4px -4px 14px color-mix(in srgb, var(--shadow-light) 90%, transparent); "
    "--elev-control: 2px 2px 6px color-mix(in srgb, var(--shadow-dark) 45%, transparent), "
    "-2px -2px 6px color-mix(in srgb, var(--shadow-light) 90%, transparent); "
    "--elev-inset: inset 2px 2px 6px color-mix(in srgb, var(--shadow-dark) 38%, transparent), "
    "inset -2px -2px 6px color-mix(in srgb, var(--shadow-light) 50%, transparent); "
    "--card-ground: var(--surface);")
V063_ELEVATION_DARK = (
    "--elev-card: 0 1px 2px color-mix(in srgb, var(--shadow-dark) 70%, transparent), "
    "0 6px 18px color-mix(in srgb, var(--shadow-dark) 35%, transparent), "
    "inset 0 1px 0 color-mix(in srgb, var(--shadow-light) 45%, transparent); "
    "--elev-control: 0 1px 2px color-mix(in srgb, var(--shadow-dark) 60%, transparent); "
    "--elev-inset: inset 0 1px 2px color-mix(in srgb, var(--shadow-dark) 55%, transparent); "
    "--card-ground: color-mix(in srgb, var(--raised) 22%, var(--surface));")

SUPPORTS_MIX = "@supports (color: color-mix(in srgb, red 50%, blue))"
FORCED = "@media (forced-colors: active)"
REDUCED = "@media (prefers-reduced-motion: reduce)"
# Every state the light can be given a class for. `checking` is the window's and the popup's;
# the panel draws it like the others should activity() ever say it.
LIGHT_STATES = ("monitoring", "waiting", "checking", "recovering", "attention", "paused", "idle")


class MaterialTests(unittest.TestCase):
    """The same stuff the window and the popup are made of, read from brand."""

    def test_the_lift_is_brands_recipe_and_resolves_to_the_css_v063_wrote(self):
        self.assertFalse(hasattr(mcpui, "_ELEVATION_LIGHT"))
        self.assertFalse(hasattr(mcpui, "_ELEVATION_DARK"))
        # Nor anywhere else the panel's code could move to: no module binds either name, and
        # no file of the package spells the old shadow.
        bound = {target.id for tree in srcscan.package_asts().values() for node in ast.walk(tree)
                 if isinstance(node, (ast.Assign, ast.AnnAssign))
                 for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                 if isinstance(target, ast.Name)}
        self.assertFalse({"_ELEVATION_LIGHT", "_ELEVATION_DARK"} & bound)
        self.assertEqual(srcscan.holders("var(--shadow-dark)"), set())
        source = (ROOT / "src" / "codex_auto_resume" / "mcp" / "panel.py").read_text(encoding="utf-8")
        self.assertNotIn("var(--shadow-dark)", source)
        self.assertIn('.replace("@ELEVATION_LIGHT@", brand.css_elevation("light"))', source)
        self.assertIn('.replace("@ELEVATION_DARK@", brand.css_elevation("dark"))', source)
        for opener, expected in ((":root {", V063_ELEVATION_LIGHT),
                                 (':root[data-theme="light"]', V063_ELEVATION_LIGHT),
                                 (':root[data-theme="dark"]', V063_ELEVATION_DARK),
                                 ("@media (prefers-color-scheme: dark)", V063_ELEVATION_DARK)):
            with self.subTest(opener):
                self.assertIn(expected, css_block(mcpui._STYLE, opener))

    def test_the_primary_button_is_brightened_by_a_token_not_a_filter(self):
        # A filter brightened the border and the shadow with the fill, and is a colour no native
        # surface can draw; accent_hover and accent_pressed are colours every surface can.
        self.assertNotIn("filter", mcpui._STYLE)
        hover, pressed = "button.primary:hover:not([disabled])", "button.primary:active:not([disabled])"
        self.assertEqual(declared(hover, "background"), "var(--accent-hover)")
        self.assertEqual(declared(hover, "border-color"), "var(--accent-hover)")
        self.assertEqual(declared(pressed, "background"), "var(--accent-pressed)")
        self.assertEqual(declared(pressed, "border-color"), "var(--accent-pressed)")
        self.assertEqual(declared(pressed, "box-shadow"), "var(--elev-inset)")
        # Equally specific, so pressed has to come second or a mouse press shows hover.
        self.assertGreater(mcpui._STYLE.index(pressed + " {"), mcpui._STYLE.index(hover + " {"))

    def test_a_disabled_control_says_so_in_muted_text_not_in_opacity(self):
        # Saying nothing about opacity is not saying 1. The browser's own stylesheet fades a
        # disabled field to 0.7, and muted text at 0.7 is about 3:1 in light. So the fields say 1,
        # and each control is measured at the opacity it resolves to, composited over the card it
        # stands on, in light and in both ways of being dark. Since v0.6.5 a drop-down's field is
        # the page's own combobox (the select behind it is never shown), disabled by aria-disabled.
        combo = '.combo-box[aria-disabled="true"]'
        browser = {"input[type=number]:disabled": "0.7"}
        themes = (ROOT_TOKENS,) + tuple(
            dict(ROOT_TOKENS, **declarations) for context, selectors, declarations in RULES
            if (context, selectors) in (("@media (prefers-color-scheme: dark)", (':root:not([data-theme="light"])',)),
                                        ("", (':root[data-theme="dark"]',))))
        self.assertEqual(len(themes), 3)
        for selector in ("button[disabled]", combo, "input[type=number]:disabled",
                         ".segment input:disabled + span"):
            with self.subTest(selector):
                self.assertEqual(declared(selector, "color"), "var(--muted)")
                self.assertEqual(declared(selector, "box-shadow"), "none")
                ground = declared(selector, "background") or declared(selector, "background-color")
                self.assertEqual(ground, "var(--surface)")
                opacity = float(declared(selector, "opacity") or browser.get(selector, "1"))
                for tokens in themes:
                    card = painted("var(--card-ground)", tokens)
                    text = brand.mix(card, painted("var(--muted)", tokens), opacity)
                    well = brand.mix(card, painted(ground, tokens), opacity)
                    self.assertGreaterEqual(brand.contrast(text, well), 4.5, (tokens["--muted"], opacity))
                if selector in (combo, "input[type=number]:disabled"):
                    self.assertEqual(declared(selector, "opacity"), "1")
                else:
                    self.assertIn(declared(selector, "opacity"), (None, "1"))
                # High Contrast recolours a disabled control; it does not fade one either.
                self.assertIsNone(declared(selector, "opacity", FORCED))
        # A switch carries no text, so it may still fade.
        self.assertEqual(declared("input.switch:disabled", "opacity"), ".5")

    def test_the_save_card_stands_on_the_card_ground(self):
        self.assertEqual(declared(".savebar", "background", SUPPORTS_MIX), "var(--card-ground)")
        # After the save card's own solid ground, which is equally specific and would win.
        self.assertGreater(mcpui._STYLE.index(".savebar { background: var(--card-ground); }"),
                           mcpui._STYLE.index(".savebar {"))

    def test_type_and_shared_sizes_are_brands(self):
        sizes = re.findall(r"font-size:\s*([^;}]+)", mcpui._STYLE)
        self.assertGreater(len(sizes), 10)
        self.assertEqual([size for size in sizes if not size.startswith("var(--type-")], [])
        shorthands = re.findall(r"(?<![-\w])font:\s*([^;}]+)", mcpui._STYLE)
        self.assertEqual([font for font in shorthands if font != "inherit" and "var(--type-" not in font], [])
        for selector, prop, value in (
                ("body", "padding", "var(--size-page-pad)"), (".page", "gap", "var(--size-page-gap)"),
                (".card", "padding", "var(--size-card-pad)"), (".hero", "padding", "var(--size-hero-pad)"),
                (".savebar", "padding", "var(--size-savebar-pad)"), (".setting", "padding", "var(--size-row-pad)"),
                (".prow", "padding", "var(--size-tile-pad)"), (".master", "padding", "var(--size-tile-pad)"),
                ("button", "min-height", "var(--size-button-height)"), ("button", "padding", "var(--size-button-pad)"),
                (".combo-box", "min-height", "var(--size-field-height)"),
                (".combo-box", "padding", "var(--size-select-pad)"),
                ("input[type=number]", "width", "var(--size-number-width)"),
                ("input.switch", "width", "var(--size-switch-width)"),
                ("input.switch", "height", "var(--size-switch-height)"),
                ("input.switch::before", "width", "var(--size-knob)"),
                (".segment span", "padding", "var(--size-segment-pad)"),
                (".bubble", "padding", "var(--size-well-pad)"), (".stored-text", "padding", "var(--size-stored-pad)"),
                (".callout", "padding", "var(--size-callout-pad)")):
            with self.subTest(selector=selector, prop=prop):
                self.assertEqual(declared(selector, prop), value)


class StatusLightTests(unittest.TestCase):
    """The light: a flat dot in brand's colour for its state, blinking on brand's cycle, and brand's glow."""

    def static_opacity(self, state):
        return number(declared(".halo.%s::before" % state, "opacity") or declared(".halo::before", "opacity"))

    def glows(self, state):
        """Whether any of brand's frames for the state ever shows a glow."""
        return any((brand.glow(state, ms, ms) or {}).get("opacity", 0) > 0 for ms in range(0, 3200, 20))

    def test_the_light_is_a_flat_dot_of_the_size_it_always_had(self):
        self.assertEqual(declared(".halo", "width"), "%dpx" % (2 * brand.STATUS_DOT["panel"]))
        self.assertEqual(declared(".halo", "height"), declared(".halo", "width"))
        self.assertEqual(declared(".dot", "width"), "%dpx" % (2 * brand.STATUS_DOT["mini"]))
        self.assertEqual(declared(".dot", "height"), declared(".dot", "width"))
        for selector in (".halo", ".dot"):
            self.assertEqual(declared(selector, "border-radius"), "50%")
        # No gradient core, highlight or ring: only the glow, behind it, is soft.
        for context, selectors, declarations in RULES:
            for selector in selectors:
                if re.match(r"\.(halo|dot)\b", selector) and "::before" not in selector:
                    self.assertFalse([value for value in declarations.values() if "gradient" in value], selector)
                    self.assertNotIn("::after", selector)

    def test_each_state_is_filled_in_brands_colour_for_it(self):
        for state in LIGHT_STATES:
            with self.subTest(state):
                selector = ".halo" if state == "idle" else ".halo." + state
                self.assertEqual(declared(selector, "--halo-color"),
                                 "var(--%s)" % brand.status_fill(state).replace("_", "-"))
        # The master row's small light, which knows only on, paused and off.
        self.assertEqual(declared(".dot", "background"), "var(--%s)" % brand.status_fill("idle"))
        self.assertEqual(declared(".dot.on", "background"), "var(--%s)" % brand.status_fill("waiting"))
        self.assertEqual(declared(".dot.paused", "background"), "var(--%s)" % brand.status_fill("paused"))

    def test_only_a_light_that_is_on_glows(self):
        self.assertEqual(declared(".halo::before", "content"), "none")
        glowing = {selector[len(".halo."):-len("::before")]
                   for context, selectors, declarations in RULES
                   if context == "" and declarations.get("content") == '""'
                   for selector in selectors if selector.startswith(".halo.") and selector.endswith("::before")}
        self.assertEqual(glowing, {state for state in LIGHT_STATES if self.glows(state)})
        self.assertEqual(glowing, {"monitoring", "waiting", "recovering", "attention"})
        # Between its moments a glow is not there at all: nothing is lit round a still dot.
        self.assertEqual(self.static_opacity("monitoring"), 0.0)
        self.assertEqual(declared(".halo::before", "transform"), "scale(var(--glow-from))")

    def test_the_glow_falls_off_as_brand_says_with_no_edge(self):
        before = ".halo::before"
        self.assertEqual(declared(before, "inset"), "calc(-1 * var(--glow-reach))")
        self.assertAlmostEqual(number("var(--glow-reach)", "px"), brand.glow_reach(brand.STATUS_DOT["panel"]))
        dot = number(declared(".halo", "width"), "px") / 2
        gradient = declared(before, "background")
        self.assertTrue(gradient.startswith("radial-gradient(circle closest-side, ") and gradient.endswith(")"))
        parts, depth, current = [], 0, ""
        for character in gradient[len("radial-gradient("):-1]:
            depth += {"(": 1, ")": -1}.get(character, 0)
            if character == "," and depth == 0:
                parts.append(current.strip())
                current = ""
            else:
                current += character
        parts.append(current.strip())
        self.assertEqual(parts[0], "circle closest-side")
        # closest-side of a box `reach` wider than the dot on every side.
        outer = dot + brand.glow_reach(dot)
        observed = []
        for stop in parts[1:]:
            colour, position = stop.rsplit(" ", 1)
            mixed = re.fullmatch(r"color-mix\(in srgb, var\(--halo-color\) (.+), transparent\)", colour)
            alpha = (1.0 if colour == "var(--halo-color)" else 0.0 if colour == "transparent"
                     else number(mixed.group(1), "%") / 100)
            observed.append((number(position, "px") / outer, alpha))
        observed.insert(0, (0.0, observed[0][1]))          # a gradient holds its first colour to the centre
        expected = brand.glow_stops(dot)
        self.assertEqual(len(observed), len(expected))
        for (at, alpha), (want_at, want_alpha) in zip(observed, expected):
            self.assertAlmostEqual(at, want_at, places=6)
            self.assertAlmostEqual(alpha, want_alpha, places=6)

    def keyframes(self, name):
        frames = []
        for context, selectors, declarations in RULES:
            if context == "@keyframes " + name:
                scale = 1.0
                if "transform" in declarations:
                    scale = float(re.fullmatch(r"scale\((.+)\)", resolve(declarations["transform"])).group(1))
                for selector in selectors:
                    frames.append((float(selector.rstrip("%")) / 100,
                                   number(declarations["opacity"]), scale))
        self.assertTrue(frames, name)
        return sorted(frames)

    def animation(self, selector):
        value = resolve(declared(selector, "animation"))
        name, duration, easing, count = re.fullmatch(r"(\S+) (\d+(?:\.\d+)?)ms (cubic-bezier\([^)]*\)|linear) (\S+)",
                                                     value).groups()
        return self.keyframes(name), float(duration), easing, count

    def frame(self, animation, elapsed):
        frames, duration, easing, _ = animation
        progress = (elapsed % duration) / duration
        for (start, low, small), (end, high, large) in zip(frames, frames[1:]):
            if start <= progress <= end:
                step = (progress - start) / (end - start)
                # The curve is in the stops since v0.6.6, so what is between them is walked straight.
                eased = step if easing == "linear" else cubic_bezier(easing, step)
                return low + (high - low) * eased, small + (large - small) * eased
        raise AssertionError(progress)

    def light(self, state, elapsed):
        """The dot's opacity, the glow's opacity and the glow's scale the stylesheet draws at `elapsed`."""
        dot = self.animation(".halo.%s" % state)
        glow = self.animation(".halo.%s::before" % state)
        for animation in (dot, glow):
            self.assertEqual(animation[3], "infinite")
            self.assertEqual(animation[1], brand.GLOW[state + "_ms"])
        return self.frame(dot, elapsed)[0], self.frame(glow, elapsed)[0], self.frame(glow, elapsed)[1]

    def assertBrands(self, drawn, frame):
        dot = number(declared(".halo", "width"), "px") / 2
        self.assertAlmostEqual(drawn[0], 1 - frame["dim"], delta=0.002)
        self.assertAlmostEqual(drawn[1], frame["opacity"], delta=0.002)
        self.assertAlmostEqual(drawn[2], brand.glow_radius(dot, frame["spread"]) / brand.glow_extent(dot), delta=0.002)

    def test_the_light_runs_brands_cycle_on_brands_curve(self):
        # Sampled over two cycles against brand.glow(), which the window and the popup draw too: the dot's
        # opacity over the card is its dimming, and the glow's opacity and scale are its spread. The easing is
        # a Bezier, so each phase is a half-cosine only to within a small error. Attention loops too since
        # v0.6.8, the slowest of the three, where it used to run the cycle once and hold.
        for state in ("monitoring", "waiting", "recovering", "attention"):
            cycle = brand.GLOW[state + "_ms"]
            for step in range(193):
                elapsed = cycle * 2 * step / 192
                with self.subTest(state=state, elapsed=elapsed):
                    self.assertBrands(self.light(state, elapsed), brand.glow(state, elapsed))

    def test_attention_breathes_for_as_long_as_it_lasts_and_nothing_pulses_once(self):
        """v0.6.8: "확인필요는 천천히 계속 부드럽게 깜빡이고" - the hero no longer marks a light to run once."""
        self.assertLess(brand.GLOW["monitoring_ms"], brand.GLOW["attention_ms"])
        self.assertNotIn(".once", mcpui._STYLE)
        self.assertNotIn("LAST_STATE", mcpui._SCRIPT)
        self.assertIsNone(declared(".halo", "opacity"))

    def test_checking_holds_lit_with_no_glow_and_waiting_breathes(self):
        # v0.6.9: waiting breathes on its own rhythm, which is monitoring's; checking still holds lit.
        self.assertEqual(declared(".halo.waiting", "animation"), "glow-dot var(--glow-waiting-ms) linear infinite")
        self.assertEqual(declared(".halo.waiting::before", "animation"),
                         "glow-spread var(--glow-waiting-ms) linear infinite")
        for state in ("checking",):
            with self.subTest(state):
                self.assertIsNone(declared(".halo.%s" % state, "animation"))
                self.assertIsNone(declared(".halo.%s::before" % state, "animation"))
                self.assertIsNone(declared(".halo.%s::before" % state, "content"))
                self.assertEqual(brand.glow(state, 1234)["opacity"], 0.0)
                self.assertEqual(brand.glow(state, 1234)["dim"], 0.0)

    def test_with_less_motion_every_light_holds_lit_with_no_glow(self):
        # Reduced motion removes the animations; what is left is the dot at full strength and no glow at all.
        self.assertEqual(declared(".halo::before", "display", REDUCED), "none")
        self.assertIsNone(declared(".halo", "opacity"))
        for state in LIGHT_STATES:
            frame = brand.glow(state, 5000, since_entered_ms=0, reduced=True)
            if frame is None:
                continue
            with self.subTest(state):
                self.assertEqual((frame["dim"], frame["opacity"], frame["spread"]), (0.0, 0.0, 0.0))

    def test_high_contrast_draws_a_solid_system_colour_and_no_glow(self):
        # CSS names Windows' text colour CanvasText.
        system = {"Highlight": "Highlight", "WindowText": "CanvasText", "GrayText": "GrayText"}
        self.assertEqual(declared(".halo::before", "display", FORCED), "none")
        for state in LIGHT_STATES:
            with self.subTest(state):
                selector = ".halo" if state == "idle" else ".halo." + state
                self.assertEqual(declared(selector, "background", FORCED), system[brand.status_system(state)])
        for selector, state in ((".dot", "idle"), (".dot.on", "waiting"), (".dot.paused", "paused")):
            self.assertEqual(declared(selector, "background", FORCED), system[brand.status_system(state)])
        for selector in (".halo", ".dot", "input.switch::before", "input.switch:checked"):
            self.assertEqual(declared(selector, "forced-color-adjust", FORCED), "none", selector)
        # A rule that opts out of forced colours keeps its shadow unless it takes it off itself.
        for selector in (".card", ".savebar", "button", "select", "input", ".segment span", ".bubble",
                         ".segment input:checked + span", ".combo-box", ".combo-list", ".combo-option"):
            self.assertEqual(declared(selector, "box-shadow", FORCED), "none", selector)


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class HeroLightTests(unittest.TestCase):
    """The word and the light: a watcher that is not running asks for attention with a grey light."""

    PRELUDE = """
      var document = {createElement: function (tag) {
        return {tag: tag, children: [], attributes: {}, className: '', textContent: '',
                setAttribute: function (name, value) { this.attributes[name] = value; },
                appendChild: function (child) { this.children.push(child); return child; }};
      }};
    """
    CASES = (
        ({"watcher_running": False, "enabled": True}, "attention", "idle"),
        ({"watcher_running": None, "enabled": True, "pending": 1}, "attention", "idle"),
        ({"enabled": True}, "attention", "idle"),
        ({"watcher_running": True, "enabled": False, "pending": 2}, "paused", "paused"),
        ({"watcher_running": True, "enabled": True, "pending": 1}, "waiting", "waiting"),
        ({"watcher_running": True, "enabled": True, "pending": 1, "codes": {"turn_running": 1}},
         "recovering", "recovering"),
        ({"watcher_running": True, "enabled": True, "pending": 0}, "monitoring", "monitoring"),
        # v0.6.10: amber, for a watcher that runs and is not well.
        ({"watcher_running": True, "enabled": True, "pending": 1, "watcher": {"ticking": False}},
         "attention", "attention"),
    )

    def test_the_hero_keeps_its_word_and_greys_the_light_of_a_stopped_watcher(self):
        observed = run_javascript(
            ["t", "fill", "element", "activity", "attentionCause", "lightFor", "nextCheck", "heroFacts",
             "soonestFact", "renderHero"], """
          DATA = {pending: []};
          process.stdout.write(JSON.stringify(%s.map(function (status) {
            var hero = renderHero(status).node;
            var line = hero.children[1];
            return [hero.attributes['data-state'], line.children[0].className, line.children[1].textContent];
          })));
        """ % json.dumps([status for status, _, _ in self.CASES]), prelude=self.PRELUDE)
        self.assertEqual(observed, [[state, "halo " + light, ENGLISH["activity." + state]]
                                    for _, state, light in self.CASES])

    def test_amber_is_for_a_watcher_that_runs(self):
        observed = run_javascript(["lightFor"], "process.stdout.write(JSON.stringify(["
                                  "lightFor({watcher_running: true}, 'attention'),"
                                  "lightFor({watcher_running: false}, 'attention'),"
                                  "lightFor(null, 'monitoring')]));")
        self.assertEqual(observed, ["attention", "idle", "idle"])


if __name__ == "__main__":
    unittest.main()
