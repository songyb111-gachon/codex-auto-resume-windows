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
                               reasons,
                               runtime)
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
        observed = run_javascript(["activity", "attentionCause", "due", "checkingRow"], "process.stdout.write(JSON.stringify(%s.map("
                                  "function (c) {return activity(c[0], c[1]);})));" % json.dumps(
                                      [[status, rows] for status, rows, _ in self.CASES]))
        self.assertEqual(observed, [expected for _, _, expected in self.CASES])

    def test_a_task_whose_time_has_come_is_checking_by_the_clock_it_is_given(self):
        """v0.6.10 (F3): the popup's and the Dashboard's step, on the clock the page is given. Until then the panel
        took none and said waiting; without one, nothing has come due."""
        running = {"watcher_running": True, "enabled": True, "pending": 2}
        cases = (
            (running, [{"code": "waiting_reset", "eligible_at": 1000.0}], 999.5, "waiting"),
            (running, [{"code": "waiting_reset", "eligible_at": 1000.0}], 1000.0, "checking"),
            (running, [{"code": "scheduled", "eligible_at": 2000.0}, {"code": "waiting_reset", "eligible_at": 900.0}],
             1000.0, "checking"),
            (running, [{"code": "waiting_reset", "eligible_at": None}], 1000.0, "waiting"),
            (running, [{"code": "waiting_reset", "eligible_at": 900.0}], None, "waiting"),
            # The steps before it still come first: a row in Codex, a pause, a watcher that is not well.
            (running, [{"code": "waiting_reset", "eligible_at": 900.0}, {"code": "submitted"}], 1000.0, "recovering"),
            (dict(running, enabled=False), [{"code": "waiting_reset", "eligible_at": 900.0}], 1000.0, "paused"),
            (dict(running, watcher={"ticking": False}), [{"code": "waiting_reset", "eligible_at": 900.0}], 1000.0,
             "attention"),
        )
        observed = run_javascript(["activity", "attentionCause", "due", "checkingRow"], "process.stdout.write(JSON.stringify(%s.map("
                                  "function (c) {return activity(c[0], c[1], c[2] === null ? undefined : c[2]);})));"
                                  % json.dumps([[status, rows, now] for status, rows, now, _ in cases]))
        self.assertEqual(observed, [expected for _, _, _, expected in cases])

    def test_the_page_says_checking_for_one_watcher_pass_after_what_it_read(self):
        """The popup and the Dashboard read the record every second and leave checking at the watcher's next pass;
        the panel reads it once. So it says checking for one pass - the watcher's own pace, DEFAULT_POLL - after the
        later of the row's time and when it read the row, and then waiting, with the row still "due now": past that,
        what it read no longer says what the watcher is doing (standard J7). The reviewer on F3: a panel left open
        kept turning the arc for as long as it stayed open."""
        self.assertIn("var CHECKING_HOLD = %d;" % runtime.DEFAULT_POLL, mcpui._SCRIPT)
        hold = runtime.DEFAULT_POLL
        running = {"watcher_running": True, "enabled": True, "pending": 1}
        row = [{"code": "waiting_reset", "eligible_at": 1000.0}]
        cases = (
            # Read before the time came: checking from the time, for one pass.
            (row, 1000.0, 900.0, "checking"),
            (row, 1000.0 + hold - 0.001, 900.0, "checking"),
            (row, 1000.0 + hold, 900.0, "waiting"),
            (row, 1000.0 + 4 * 3600, 900.0, "waiting"),
            # Read after it came, the watcher not yet at it: checking from the reading, for one pass.
            (row, 1100.0, 1090.0, "checking"),
            (row, 1090.0 + hold, 1090.0, "waiting"),
            # Read as it is shown, as the popup and the Dashboard read theirs: checking.
            (row, 1000.0 + 4 * 3600, 1000.0 + 4 * 3600, "checking"),
            (row, 1000.0 + 4 * 3600, None, "checking"),
            # Two rows: one still held keeps the page checking.
            ([{"code": "waiting_reset", "eligible_at": 1000.0}, {"code": "scheduled", "eligible_at": 1020.0}],
             1000.0 + hold + 5, 900.0, "checking"),
            # Nothing before checking moves: a row in Codex is still recovering, whenever it was read.
            ([{"code": "waiting_reset", "eligible_at": 1000.0}, {"code": "submitted"}], 1000.0 + 4 * 3600, 900.0,
             "recovering"),
        )
        observed = run_javascript(["activity", "attentionCause", "due", "checkingRow"], "process.stdout.write("
                                  "JSON.stringify(%s.map(function (c) {return activity(%s, c[0], c[1], "
                                  "c[2] === null ? undefined : c[2]);})));"
                                  % (json.dumps([[rows, now, read] for rows, now, read, _ in cases]),
                                     json.dumps(running)),
                                  prelude="var CHECKING_HOLD = %d;" % hold)
        self.assertEqual(observed, [expected for _, _, _, expected in cases])

    def test_every_state_has_a_word_and_a_halo(self):
        for state in ("monitoring", "waiting", "checking", "recovering", "paused", "attention"):
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
        "activity.": ("monitoring", "waiting", "checking", "recovering", "paused", "attention"),
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
    def test_the_hero_s_light_and_word_stand_as_they_do_in_every_header(self):
        """v0.6.10 (F7): the hero is the header every surface follows - the product as a muted eyebrow, then the
        light and its word in ink - and the light stands LAYOUT's `light_inset` from the line's start and
        `light_gap` from its word, as it does in the window, the popup and the card. Until then `.hero-state` had
        its own 18px and 9px, and the word stood 18.5 px from the light where the others had 15 to 17.5."""
        self.assertEqual(declared(".hero-state", "gap"), "var(--size-light-gap)")
        self.assertEqual(declared(".hero-state", "padding").split()[-1], "var(--size-light-inset)")
        self.assertEqual(number("var(--size-light-gap)", "px"), brand.LAYOUT["light_gap"])
        self.assertEqual(number("var(--size-light-inset)", "px"), brand.LAYOUT["light_inset"])
        self.assertEqual(number(declared(".halo", "width"), "px"), 2 * brand.STATUS_DOT["panel"],
                         "the gap is from the dot's own edge: the light's box is the dot")
        self.assertEqual(declared(".eyebrow", "color"), "var(--muted)")
        self.assertIsNone(declared(".hero h1", "color"), "the word is the page's ink, never the state's colour")

    def test_reduced_motion_stops_every_animation_and_transition(self):
        block = css_block(mcpui._STYLE, "@media (prefers-reduced-motion: reduce)")
        self.assertRegex(block, r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*animation:\s*none\s*!important")
        self.assertRegex(block, r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*transition:\s*none\s*!important")
        self.assertIn(".halo::before", block)
        # The checking arc stops with every other animation, and stays: held still, it rests where the window's
        # and the popup's does.
        for context, selectors, declarations in RULES:
            if context == REDUCED and any("::after" in selector for selector in selectors):
                self.assertNotIn("display", declarations, selectors)

    def test_the_page_keeps_one_timer_and_only_for_a_change_to_come(self):
        """Until v0.6.10 nothing on the page ticked, and so a task that came due while it was open stayed "waiting"
        beside a window and a popup that said "checking" (F3). The rule now: no frame loop and no interval - the
        motion is the stylesheet's - and one timeout, which watchClock sets for the soonest moment what the page says
        of its rows changes - a time a row carries comes, or one watcher pass after it the page stops saying
        checking - and which retell() uses to say again what that changes."""
        for forbidden in ("setInterval", "requestAnimationFrame"):
            self.assertNotIn(forbidden, mcpui._SCRIPT)
        self.assertEqual(mcpui._SCRIPT.count("setTimeout("), 1)
        self.assertIn("CLOCK = setTimeout(retell, wait);", javascript_function("watchClock"))
        self.assertIn("clearTimeout(CLOCK);", javascript_function("watchClock"))
        self.assertIn("watchClock();", javascript_function("render"))
        self.assertIn("watchClock();", javascript_function("retell"))

    def test_the_scale_is_emitted_and_does_not_shadow_a_colour(self):
        scale = set(re.findall(r"(--[a-z-]+)\s*:", brand.css_scale()))
        colours = set(re.findall(r"(--[a-z-]+)\s*:", brand.css_variables(brand.LIGHT)))
        self.assertEqual(scale & colours, set())
        self.assertIn(brand.css_scale(), mcpui._STYLE)
        for name in ("--transition", "--glow-reach", "--glow-edge", "--glow-near", "--glow-far",
                     "--glow-outer", "--glow-edge-mix", "--glow-near-mix", "--glow-far-mix",
                     "--glow-from", "--glow-monitoring-ms", "--glow-recovering-ms", "--glow-attention-ms",
                     # v0.6.10: the checking arc's numbers, which until then were written and read by nothing.
                     "--glow-arc-ms", "--glow-arc-mix", "--glow-arc-gap", "--glow-arc-width", "--glow-arc-sweep",
                     "--glow-arc-still"):
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
# Every state the light can be given a class for. `checking` was the window's and the popup's alone
# until v0.6.10, when the panel's clock came (F3). No `failed`: no header shows red (J14).
LIGHT_STATES = ("monitoring", "waiting", "checking", "recovering", "attention", "paused", "idle")
# The panel's states whose light breathes and glows - brand.GLOW_BREATHES less `failed`, which the
# panel never shows (the critic's correction to F1's test).
BREATHING = ("monitoring", "waiting", "recovering", "attention")


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

    def themes(self):
        """Each theme's tokens as the bare root and a dark block leave them: light, and dark."""
        dark = next(declarations for context, selectors, declarations in RULES
                    if context == "" and selectors == (':root[data-theme="dark"]',))
        return {"light": ROOT_TOKENS, "dark": dict(ROOT_TOKENS, **dark)}

    def test_the_light_is_a_flat_dot_of_the_size_it_always_had(self):
        self.assertEqual(declared(".halo", "width"), "%dpx" % (2 * brand.STATUS_DOT["panel"]))
        self.assertEqual(declared(".halo", "height"), declared(".halo", "width"))
        # v0.6.10 (F1): the Automatic recovery tile's light, the size its still dot had.
        self.assertEqual(declared(".halo.mini", "width"), "%dpx" % (2 * brand.STATUS_DOT["mini"]))
        self.assertEqual(declared(".halo.mini", "height"), declared(".halo.mini", "width"))
        self.assertEqual(declared(".halo", "border-radius"), "50%")
        # No gradient core, highlight or ring on the dot: only the glow behind it is soft, and the one thing drawn
        # round it is checking's arc.
        arcs = set()
        for context, selectors, declarations in RULES:
            for selector in selectors:
                if not re.match(r"\.halo\b", selector):
                    continue
                if "::after" in selector:
                    arcs.add(selector)
                elif "::before" not in selector:
                    self.assertFalse([value for value in declarations.values() if "gradient" in value], selector)
        self.assertEqual(arcs, {".halo.checking::after"})
        # The still dot it replaced is gone from the stylesheet and the script.
        self.assertFalse([selectors for context, selectors, declarations in RULES
                          if any(re.match(r"\.dot\b", selector) for selector in selectors)])
        self.assertNotRegex(mcpui._SCRIPT, r"'dot( |')")

    def test_each_state_is_filled_in_brands_colour_for_it(self):
        for state in LIGHT_STATES:
            with self.subTest(state):
                selector = ".halo" if state == "idle" else ".halo." + state
                self.assertEqual(declared(selector, "--halo-color"),
                                 "var(--%s)" % brand.status_fill(state).replace("_", "-"))
        # The tile's light has no colour, motion or glow of its own: it is the state's light, smaller.
        for context, selectors, declarations in RULES:
            for selector in selectors:
                if ".mini" in selector:
                    with self.subTest(selector=selector, context=context):
                        self.assertEqual((context, selector), ("", ".halo.mini"))
                        self.assertEqual(set(declarations), {"width", "height", "--glow-reach", "--glow-edge",
                                                             "--glow-near", "--glow-far", "--glow-outer"})

    def test_only_a_light_that_is_on_glows(self):
        self.assertEqual(declared(".halo::before", "content"), "none")
        glowing = {selector[len(".halo."):-len("::before")]
                   for context, selectors, declarations in RULES
                   if context == "" and declarations.get("content") == '""'
                   for selector in selectors if selector.startswith(".halo.") and selector.endswith("::before")}
        self.assertEqual(glowing, {state for state in LIGHT_STATES if self.glows(state)})
        self.assertEqual(glowing, set(BREATHING))
        # Between its moments a glow is not there at all: nothing is lit round a still dot.
        self.assertEqual(self.static_opacity("monitoring"), 0.0)
        self.assertEqual(declared(".halo::before", "transform"), "scale(var(--glow-from))")

    def falloff(self, dot, tokens):
        """The glow's stops as (fraction of the outer radius, alpha), for a dot of `dot` px and the tokens it reads."""
        def length(value, unit):
            while "var(" in value:
                value = re.sub(r"var\((--[a-z0-9-]+)\)", lambda match: tokens[match.group(1)], value)
            self.assertTrue(value.endswith(unit), (value, unit))
            return float(value[:-len(unit)])

        before = ".halo::before"
        self.assertEqual(declared(before, "inset"), "calc(-1 * var(--glow-reach))")
        self.assertAlmostEqual(length("var(--glow-reach)", "px"), brand.glow_reach(dot))
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
                     else length(mixed.group(1), "%") / 100)
            observed.append((length(position, "px") / outer, alpha))
        observed.insert(0, (0.0, observed[0][1]))          # a gradient holds its first colour to the centre
        return observed

    def test_the_glow_falls_off_as_brand_says_with_no_edge(self):
        dot = number(declared(".halo", "width"), "px") / 2
        expected = brand.glow_stops(dot)
        observed = self.falloff(dot, ROOT_TOKENS)
        self.assertEqual(len(observed), len(expected))
        for (at, alpha), (want_at, want_alpha) in zip(observed, expected):
            self.assertAlmostEqual(at, want_at, places=6)
            self.assertAlmostEqual(alpha, want_alpha, places=6)

    def test_the_tile_s_light_glows_as_far_as_brand_says_for_its_size(self):
        """v0.6.10 (F1): the same falloff at the mini size - its reach and its stops are brand's for a 4 px radius,
        written by brand.css_glow_geometry, and every other number of the breath is a share of the dot."""
        mini = next(declarations for context, selectors, declarations in RULES
                    if context == "" and selectors == (".halo.mini",))
        dot = number(mini["width"], "px") / 2
        self.assertEqual(dot, brand.STATUS_DOT["mini"])
        self.assertAlmostEqual(float(mini["--glow-reach"][:-2]), brand.glow_reach(brand.STATUS_DOT["mini"]))
        self.assertIn(brand.css_glow_geometry(brand.STATUS_DOT["mini"]), mcpui._STYLE)
        observed = self.falloff(dot, dict(ROOT_TOKENS, **mini))
        for (at, alpha), (want_at, want_alpha) in zip(observed, brand.glow_stops(dot)):
            self.assertAlmostEqual(at, want_at, places=6)
            self.assertAlmostEqual(alpha, want_alpha, places=6)
        # The glow's scale with no spread, a share of the dot, is the same at both sizes.
        self.assertAlmostEqual(number("var(--glow-from)"), dot / brand.glow_extent(dot))

    def keyframes(self, name):
        """A keyframes rule's stops as (fraction of the cycle, declarations), in order."""
        frames = []
        for context, selectors, declarations in RULES:
            if context == "@keyframes " + name:
                for selector in selectors:
                    at = {"from": 0.0, "to": 1.0}.get(selector)
                    frames.append((float(selector.rstrip("%")) / 100 if at is None else at, declarations))
        self.assertTrue(frames, name)
        return sorted(frames, key=lambda frame: frame[0])

    DIMMED = re.compile(r"color-mix\(in srgb, var\(--halo-color\) ([0-9.]+)%, var\(--halo-ground\)\)")

    def breath(self, name):
        """(fraction, level, scale) for each stop: glow-dot's share of the dot's own colour, or glow-spread's opacity
        and scale."""
        stops = []
        for at, declarations in self.keyframes(name):
            if name == "glow-dot":
                self.assertEqual(set(declarations), {"background-color"})
                share = float(self.DIMMED.fullmatch(declarations["background-color"]).group(1)) / 100
                stops.append((at, share, 1.0))
            else:
                scale = float(re.fullmatch(r"scale\((.+)\)", resolve(declarations["transform"])).group(1))
                stops.append((at, number(declarations["opacity"]), scale))
        return stops

    def animation(self, selector):
        written = declared(selector, "animation")
        # Every light starts its cycle where the script puts it (v0.6.10, F2): one phase for the page's lights.
        self.assertEqual(written.split()[3], "var(--light-delay)", written)
        name, duration, count = re.fullmatch(r"(\S+) (\d+(?:\.\d+)?)ms linear -?\d+(?:\.\d+)?ms (\S+)",
                                             resolve(written)).groups()
        return self.breath(name), float(duration), count

    def frame(self, animation, elapsed):
        frames, duration, _ = animation
        progress = (elapsed % duration) / duration
        for (start, low, small), (end, high, large) in zip(frames, frames[1:]):
            if start <= progress <= end:
                # The curve is in the stops since v0.6.6, so what is between them is walked straight.
                step = (progress - start) / (end - start)
                return low + (high - low) * step, small + (large - small) * step
        raise AssertionError(progress)

    def light(self, state, elapsed):
        """How much of its colour the dot is drawn with, the glow's opacity and the glow's scale at `elapsed`."""
        dot = self.animation(".halo.%s" % state)
        glow = self.animation(".halo.%s::before" % state)
        for animation in (dot, glow):
            self.assertEqual(animation[2], "infinite")
            self.assertEqual(animation[1], brand.GLOW[state + "_ms"])
        return self.frame(dot, elapsed)[0], self.frame(glow, elapsed)[0], self.frame(glow, elapsed)[1]

    def assertBrands(self, drawn, frame):
        dot = number(declared(".halo", "width"), "px") / 2
        self.assertAlmostEqual(drawn[0], 1 - frame["dim"], delta=0.002)
        self.assertAlmostEqual(drawn[1], frame["opacity"], delta=0.002)
        self.assertAlmostEqual(drawn[2], brand.glow_radius(dot, frame["spread"]) / brand.glow_extent(dot), delta=0.002)

    def test_the_light_runs_brands_cycle_on_brands_curve(self):
        # Sampled over two cycles against brand.glow(), which the window and the popup draw too: the share of its
        # colour the dot is drawn with is its dimming, and the glow's opacity and scale are its spread. Attention
        # loops too since v0.6.8, the slowest of the three, where it used to run the cycle once and hold.
        for state in BREATHING:
            cycle = brand.GLOW[state + "_ms"]
            for step in range(193):
                elapsed = cycle * 2 * step / 192
                with self.subTest(state=state, elapsed=elapsed):
                    self.assertBrands(self.light(state, elapsed), brand.glow(state, elapsed))

    def test_the_dot_dims_toward_its_ground_and_never_dims_its_glow(self):
        """v0.6.10 (F2): the dot's colour is mixed with the ground under it - the card's under the state, the tile's
        under the tile's light - as the window and the popup draw theirs. Until then the dot's element faded, and
        the glow drawn inside it faded with it: halfway through a breath the panel's glow was about a fifth weaker
        than theirs."""
        for _, declarations in self.keyframes("glow-dot"):
            self.assertNotIn("opacity", declarations)
        for context, selectors, declarations in RULES:
            for selector in selectors:
                if re.match(r"\.halo\b", selector) and "::" not in selector:
                    self.assertNotIn("opacity", declarations, selector)
        self.assertEqual(declared(".hero", "--halo-ground"), "var(--card-ground)")
        self.assertEqual(declared(".master", "--halo-ground"), "var(--raised)")
        grounds = {"var(--card-ground)": brand.card_ground, "var(--raised)": lambda theme: brand.palette(theme)["raised"]}
        for theme, tokens in self.themes().items():
            for ground, ground_of in grounds.items():
                under = painted(ground, tokens)
                self.assertEqual(under, ground_of(theme))
                for state in BREATHING:
                    colour = brand.status_colour(state, theme)
                    self.assertEqual(painted(declared(".halo." + state, "--halo-color"), tokens), colour)
                    for at, declarations in self.keyframes("glow-dot"):
                        with self.subTest(theme=theme, ground=ground, state=state, at=at):
                            drawn = painted(declarations["background-color"].replace("var(--halo-color)", colour)
                                            .replace("var(--halo-ground)", under), tokens)
                            wanted = brand.mix(colour, under, brand.glow_phase(at)[0])
                            for one, other in zip(brand.rgb(drawn), brand.rgb(wanted)):
                                self.assertLessEqual(abs(one - other), 1)

    def test_attention_breathes_for_as_long_as_it_lasts_and_nothing_pulses_once(self):
        """v0.6.8: "확인필요는 천천히 계속 부드럽게 깜빡이고" - the hero no longer marks a light to run once."""
        self.assertLess(brand.GLOW["monitoring_ms"], brand.GLOW["attention_ms"])
        self.assertNotIn(".once", mcpui._STYLE)
        self.assertNotIn("LAST_STATE", mcpui._SCRIPT)
        self.assertIsNone(declared(".halo", "opacity"))

    def test_checking_holds_lit_with_no_glow_and_waiting_breathes(self):
        # v0.6.9: waiting breathes on its own rhythm, which is monitoring's; checking still holds lit.
        self.assertEqual(declared(".halo.waiting", "animation"),
                         "glow-dot var(--glow-waiting-ms) linear var(--light-delay) infinite")
        self.assertEqual(declared(".halo.waiting::before", "animation"),
                         "glow-spread var(--glow-waiting-ms) linear var(--light-delay) infinite")
        for state in ("checking",):
            with self.subTest(state):
                self.assertIsNone(declared(".halo.%s" % state, "animation"))
                self.assertIsNone(declared(".halo.%s::before" % state, "animation"))
                self.assertIsNone(declared(".halo.%s::before" % state, "content"))
                self.assertEqual(brand.glow(state, 1234)["opacity"], 0.0)
                self.assertEqual(brand.glow(state, 1234)["dim"], 0.0)

    def test_checking_turns_brands_arc(self):
        """v0.6.10 (F3): the arc the window and the popup turn round a task whose time has come. Until then the
        stylesheet was written its numbers and read none of them, and a checking light here would have held still."""
        after = ".halo.checking::after"
        self.assertEqual(declared(after, "content"), '""')
        self.assertEqual(declared(after, "animation"), "glow-arc var(--glow-arc-ms) linear var(--light-delay) infinite")
        self.assertEqual(number("var(--glow-arc-ms)", "ms"), brand.GLOW["arc_ms"])
        # One turn a cycle, clockwise, from where brand's arc starts: at 0 degrees, which is where it is at 0 ms.
        self.assertEqual([(at, declarations) for at, declarations in self.keyframes("glow-arc")],
                         [(0.0, {"transform": "rotate(0deg)"}), (1.0, {"transform": "rotate(360deg)"})])
        for elapsed in (0, 400, 1200):
            self.assertAlmostEqual(brand.glow("checking", elapsed)["arc"], elapsed / brand.GLOW["arc_ms"] * 360)
        # Held still, it rests where the window's and the popup's does.
        self.assertEqual(declared(after, "transform"), "rotate(var(--glow-arc-still))")
        self.assertEqual(number("var(--glow-arc-still)", "deg"), brand.GLOW["arc_still_at"])
        self.assertEqual(brand.glow("checking", 5000, reduced=True)["arc"], brand.GLOW["arc_still_at"])
        # Their angles run clockwise from three o'clock, where a conic gradient starts once turned from twelve; the
        # arc is `arc_sweep` of it, in the light's colour at `arc_alpha`.
        self.assertEqual(declared(after, "background"),
                         "conic-gradient(from 90deg, var(--halo-arc) 0deg var(--glow-arc-sweep), transparent 0deg)")
        self.assertEqual(number("var(--glow-arc-sweep)", "deg"), brand.GLOW["arc_sweep"])
        self.assertEqual(declared(after, "--halo-arc"),
                         "color-mix(in srgb, var(--halo-color) var(--glow-arc-mix), transparent)")
        self.assertAlmostEqual(number("var(--glow-arc-mix)", "%") / 100, brand.GLOW["arc_alpha"])
        # The ring: its middle `arc_gap` past the dot's edge and `arc_width` wide, as their pens stroke it, each edge
        # softened across one pixel centred on it - at both sizes of the light.
        gap, width = number("var(--glow-arc-gap)", "px"), number("var(--glow-arc-width)", "px")
        self.assertEqual((gap, width), (brand.GLOW["arc_gap"], brand.GLOW["arc_width"]))
        self.assertEqual(declared(after, "inset"), "calc(-1 * (var(--glow-arc-gap) + var(--glow-arc-width) / 2 + 1px))")
        mask = declared(after, "mask")
        self.assertEqual(declared(after, "-webkit-mask"), mask)
        stops = re.fullmatch(r"radial-gradient\(circle closest-side, transparent (calc\(.*?\)), #000 (calc\(.*?\)), "
                             r"#000 (calc\(.*?\)), transparent (calc\(.*?\))\)", mask).groups()
        for dot in (brand.STATUS_DOT["panel"], brand.STATUS_DOT["mini"]):
            box = dot + gap + width / 2 + 1                 # closest-side of the box the inset makes

            def at(position):
                value = resolve(position).replace("100%", repr(box)).replace("px", "")
                self.assertRegex(value, r"^calc\([0-9. +*/-]+\)$")
                return eval(value[4:], {"__builtins__": {}})

            inner_from, inner_to, outer_from, outer_to = (at(position) for position in stops)
            with self.subTest(dot=dot):
                self.assertAlmostEqual((inner_from + inner_to + outer_from + outer_to) / 4, dot + gap)
                self.assertAlmostEqual((outer_from + outer_to) / 2 - (inner_from + inner_to) / 2, width)
                self.assertAlmostEqual(inner_to - inner_from, 1.0)
                self.assertAlmostEqual(outer_to - outer_from, 1.0)
                self.assertLessEqual(outer_to, box)

    def test_with_less_motion_every_light_holds_lit_with_no_glow(self):
        # Reduced motion removes the animations; what is left is the dot at full strength and no glow at all - and
        # checking's arc, held where it rests.
        self.assertEqual(declared(".halo::before", "display", REDUCED), "none")
        self.assertIsNone(declared(".halo.checking::after", "display", REDUCED))
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
        # The tile's light is the state's, in High Contrast too: nothing there names it apart.
        self.assertFalse([selectors for context, selectors, declarations in RULES
                          if context == FORCED and any(".mini" in selector for selector in selectors)])
        # Checking's arc, still, in the light's own system colour - as the popup and the window draw it.
        self.assertEqual(declared(".halo.checking::after", "--halo-arc", FORCED),
                         system[brand.status_system("checking")])
        for selector in (".halo", "input.switch::before", "input.switch:checked"):
            self.assertEqual(declared(selector, "forced-color-adjust", FORCED), "none", selector)
        # A rule that opts out of forced colours keeps its shadow unless it takes it off itself.
        for selector in (".card", ".savebar", "button", "select", "input", ".segment span", ".bubble",
                         ".segment input:checked + span", ".combo-box", ".combo-list", ".combo-option"):
            self.assertEqual(declared(selector, "box-shadow", FORCED), "none", selector)


# The panel's functions the hero and the tile are drawn with, and what they call.
DRAWING = ["t", "fill", "element", "card", "activity", "attentionCause", "due", "checkingRow", "lightFor", "lightNode",
           "lightClass", "nextCheck", "heroFacts", "soonestFact", "showFacts", "renderHero", "renderRecovery"]


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class HeroLightTests(unittest.TestCase):
    """The word and the light: a watcher that is not running asks for attention with a grey light."""

    PRELUDE = """
      var document = {createElement: function (tag) {
        return {tag: tag, children: [], attributes: {}, className: '', textContent: '',
                setAttribute: function (name, value) { this.attributes[name] = value; },
                appendChild: function (child) { this.children.push(child); return child; }};
      }};
      // When the rows were read (the page's READ_AT): unset, at the clock each test draws at.
      var READ_AT; var CHECKING_HOLD = %d;
    """ % runtime.DEFAULT_POLL
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
        observed = run_javascript(DRAWING, """
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
                                  "lightFor(null, 'monitoring'),"
                                  "lightFor({watcher_running: true}, 'attention', [{overlays: ['watcher_not_ticking']}]),"
                                  "lightFor({watcher_running: true}, 'attention', [{overlays: ['engine_unavailable']}])]));")
        # A row held for a watcher not running outweighs a status that says it runs: no moving light beside
        # "Watcher not running" (tests/data/light_states.json).
        self.assertEqual(observed, ["attention", "idle", "idle", "attention", "idle"])

    def test_the_hero_reads_the_rows_for_its_light(self):
        observed = run_javascript(DRAWING, """
          DATA = {pending: [{code: 'scheduled', eligible_at: null, overlays: ['engine_unavailable']}]};
          var hero = renderHero({watcher_running: true, enabled: true, pending: 1}).node;
          var line = hero.children[1];
          process.stdout.write(JSON.stringify([hero.attributes['data-state'], line.children[0].className,
                                               hero.children[2].children.map(function (f) { return f.textContent; })]));
        """, prelude=self.PRELUDE)
        self.assertEqual(observed, ["attention", "halo idle", [ENGLISH["status.not_running"], ENGLISH["status.pending_one"]]])

    def test_a_task_whose_time_has_come_is_checking_with_its_arc(self):
        """v0.6.10 (F3): by the clock the page is drawn at, as the popup and the Dashboard say it - for one watcher
        pass after the later of the task's time and the page's reading of it (the reviewer on F3)."""
        observed = run_javascript(DRAWING, """
          DATA = {pending: [{code: 'waiting_reset', eligible_at: 1000, overlays: []}]};
          var status = {watcher_running: true, enabled: true, pending: 1};
          function draw(now) {
            var hero = renderHero(status, now);
            return [hero.state, hero.light, hero.node.children[1].children[0].className, hero.word.textContent];
          }
          var fresh = [999, 1000, 1500].map(draw);
          READ_AT = 990;
          var read = [1000, 1029, 1030, 1500].map(draw);
          process.stdout.write(JSON.stringify([fresh, read]));
        """, prelude=self.PRELUDE)
        waiting = ["waiting", "waiting", "halo waiting", ENGLISH["activity.waiting"]]
        checking = ["checking", "checking", "halo checking", ENGLISH["activity.checking"]]
        # Read at the clock it is drawn at, as the popup and the Dashboard read theirs.
        self.assertEqual(observed[0], [waiting, checking, checking])
        # Read at 990: checking from the task's time for one pass, then waiting.
        self.assertEqual(observed[1], [checking, checking, waiting, waiting])

    def test_the_tile_s_light_is_the_hero_s_light_smaller(self):
        """v0.6.10 (F1): the Automatic recovery tile's light was a dot of its own that never moved - cyan while
        recovery was on, whatever the light above it said. It is that light now, read by the same rule at the same
        moment, at the mini size."""
        due = [{"code": "waiting_reset", "eligible_at": 1000, "overlays": []}]
        cases = [(status, [], 2000) for status, _, _ in self.CASES] + [
            ({"watcher_running": True, "enabled": True, "pending": 1}, due, 999),
            ({"watcher_running": True, "enabled": True, "pending": 1}, due, 1000),
            ({"watcher_running": True, "enabled": True, "pending": 1},
             [{"code": "scheduled", "eligible_at": None, "overlays": ["engine_unavailable"]}], 2000)]
        observed = run_javascript(DRAWING, """
          process.stdout.write(JSON.stringify(%s.map(function (c) {
            DATA = {pending: c[1]};
            var hero = renderHero(c[0], c[2]);
            var tile = renderRecovery(c[0], [], c[2]).children[1];
            var light = tile.children[0].children[0].children[0];
            return [hero.node.children[1].children[0].className, light.className, light.attributes['aria-hidden']];
          })));
        """ % json.dumps(cases), prelude=self.PRELUDE)
        words = [state for _, state, _ in self.CASES] + ["waiting", "checking", "attention"]
        lights = [light for _, _, light in self.CASES] + ["waiting", "checking", "idle"]
        self.assertEqual(len(observed), len(words))
        for (hero, tile, hidden), light in zip(observed, lights):
            with self.subTest(light=light):
                self.assertEqual(hero, "halo " + light)
                self.assertEqual(tile, "halo mini " + light)
                self.assertEqual(hidden, "true")
        # Running with recovery on and something pending, as the old dot's "on" was: the waiting light, breathing.
        self.assertIn("halo mini waiting", [tile for _, tile, _ in observed])


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class LightPhaseTests(unittest.TestCase):
    def test_the_light_keeps_its_phase_while_its_word_holds_and_starts_again_when_it_changes(self):
        """v0.6.10 (F2): every draw built the light anew, and its breath jumped back to the top on any click even
        when nothing it says had changed. The window and the popup keep the phase for as long as the state holds;
        so does this page, as the negative delay that starts a new light where the old one was."""
        observed = run_javascript(["lightDelay"], """
          process.stdout.write(JSON.stringify([
            lightDelay('waiting', 1000), lightDelay('waiting', 3500), lightDelay('waiting', 9000.4),
            lightDelay('checking', 9100), lightDelay('checking', 9350), lightDelay('waiting', 9400)]));
        """, prelude="var LIGHT = {light: '', since: 0};")
        self.assertEqual(observed, [0, -2500, -8000, 0, -250, 0])

    def test_the_timer_waits_for_the_soonest_change_still_to_come(self):
        """The page's one timer (watchClock): for the soonest of the times a row carries that have not come and the
        moments one watcher pass after a row came due - or after the page read it, if later - when the page stops
        saying checking (checkingRow); never for one that has passed, none at all when nothing is to come, and never
        longer than a day - a timer asked to wait longer than about 24.8 days fires at once. Until the reviewer on
        F3 it waited only for times to come, and a page that had turned to checking kept it for as long as it was
        open."""
        observed = run_javascript(["due", "untilChange"], """
          process.stdout.write(JSON.stringify([
            untilChange([{eligible_at: 1060}, {eligible_at: 1010.5}, {eligible_at: 990}], 1000),
            untilChange([{eligible_at: 1060}, {eligible_at: 1010.5}, {eligible_at: 990}], 1000, 950),
            untilChange([{eligible_at: 990}, {eligible_at: null}, {}], 1000),
            untilChange([{eligible_at: 990}, {eligible_at: null}, {}], 1000, 950),
            untilChange([{eligible_at: 990}], 1000, 995),
            untilChange([{eligible_at: 990}], 1020, 950),
            untilChange([{eligible_at: 990}], 1000 + 4 * 3600, 950),
            untilChange([], 1000, 950),
            untilChange(null, 1000, 950),
            untilChange([{eligible_at: 1000.0001}], 1000, 950),
            untilChange([{eligible_at: 1000 + 40 * 86400}], 1000, 950),
            untilChange([{eligible_at: 1060}], undefined, 950)]));
        """, prelude="var CLOCK_LONGEST = 86400000; var CHECKING_HOLD = 30;")
        self.assertEqual(observed, [10500, 10500, None, 20000, 25000, None, None, None, None, 1, 86400000, None])
        self.assertIn("var CLOCK_LONGEST = 86400000;", mcpui._SCRIPT)
        self.assertIn("var CHECKING_HOLD = 30;", mcpui._SCRIPT)

if __name__ == "__main__":
    unittest.main()
