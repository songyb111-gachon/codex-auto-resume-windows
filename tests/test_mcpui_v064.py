"""The v0.6.4 settings panel: the theme it applies to itself, the language it switches to at once,
and which on/off settings are switches and which are check boxes.

* **Theme.** Light and Dark stamp `data-theme` on the page's root, Use system setting stamps nothing
  and leaves Codex's own scheme in charge, and a stamp the page was served with (the documentation
  capture's) is left alone. Applied from the stored setting before the first paint and again the
  moment a save is confirmed. High Contrast needs no rule of its own: forced colours replace
  whichever palette is stamped.
* **Language.** Every language's words for this page ship with it, so a saved Interface language is
  spoken at once, by the same rule Python adopts a stored choice with.
* **Switch or check box.** A switch turns something that runs on or off; a check box picks which
  items of a list apply. The check box is brand's, token for token, in both themes and in forced
  colours, and it sits left of its label.
* **Pinned to the bottom-right.** A switch or a button at the right of a row sits at the row's
  bottom-right - beside the last line of text that wraps, right-aligned still when it drops under
  it - and comes after its text in the markup. A select, a chip, a check box and the buttons that
  were already at the bottom keep their places.

Most of this runs the panel's own script in Node against a small stand-in for the DOM, because the
claims are about what the page does, not about what its source says.
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
sys.path.insert(0, str(ROOT / "tests"))

from codex_auto_resume import brand, interface, l10n, mcpserver, reasons   # noqa: E402
from codex_auto_resume.mcp import panel as mcpui
from codex_auto_resume import settings as policy                                   # noqa: E402
from test_mcpui_v063 import (FORCED, RULES, ROOT_TOKENS, declared, javascript_function,  # noqa: E402
                             painted, run_javascript)

NODE = shutil.which("node")
ENGLISH = l10n.catalog("en")
KOREAN = l10n.catalog("ko")
THREAD = "11111111-1111-7111-8111-111111111111"

DARK_TOKENS = dict(ROOT_TOKENS, **next(
    declarations for context, selectors, declarations in RULES
    if context == "" and selectors == (':root[data-theme="dark"]',)))
LIGHT_TOKENS = dict(ROOT_TOKENS, **next(
    declarations for context, selectors, declarations in RULES
    if context == "" and selectors == (':root[data-theme="light"]',)))


def served(page: str, name: str):
    """One of the values the page assigns to `window` before its script runs. None of them can
    contain `;window.` or `;</script>`: the page escapes every `<`, and the catalogs hold no
    `;window.`."""
    value = page.split("window.%s=" % name, 1)[1]
    return json.loads(re.split(r";(?:window\.|</script>)", value, maxsplit=1)[0])


# ------------------------------------------------------------------------------ the page in Node
# Just enough of a document for the panel's script to draw itself: elements with children,
# attributes, listeners, a class list, and a select whose value is its selected option's.
FAKE_DOM = r"""
function El(tag) {
  this.tagName = tag; this.children = []; this.attributes = {}; this.listeners = {};
  this.className = ''; this.style = {}; this._text = ''; this.parentNode = null;
  var self = this;
  this.classList = {
    contains: function (name) { return self.className.split(/\s+/).indexOf(name) >= 0; },
    toggle: function (name, force) {
      var names = self.className.split(/\s+/).filter(function (n) { return n && n !== name; });
      var on = force === undefined ? !this.contains(name) : !!force;
      if (on) names.push(name);
      self.className = names.join(' ');
      return on;
    }
  };
  if (tag === 'select') {
    Object.defineProperty(this, 'options', {get: function () {
      return self.children.filter(function (c) { return c.tagName === 'option'; });
    }});
    Object.defineProperty(this, 'value', {
      get: function () {
        var options = self.options, chosen = options.filter(function (o) { return o.selected; });
        return chosen.length ? chosen[chosen.length - 1].value : (options[0] ? options[0].value : '');
      },
      set: function (v) { self.options.forEach(function (o) { o.selected = o.value === v; }); }
    });
  }
}
Object.defineProperty(El.prototype, 'textContent', {
  get: function () { return this._text + this.children.map(function (c) { return c.textContent; }).join(''); },
  set: function (v) { this.children = []; this._text = String(v); }
});
El.prototype.appendChild = function (child) { child.parentNode = this; this.children.push(child); return child; };
El.prototype.setAttribute = function (n, v) { this.attributes[n] = String(v); };
El.prototype.getAttribute = function (n) {
  return Object.prototype.hasOwnProperty.call(this.attributes, n) ? this.attributes[n] : null;
};
El.prototype.hasAttribute = function (n) { return Object.prototype.hasOwnProperty.call(this.attributes, n); };
El.prototype.removeAttribute = function (n) { delete this.attributes[n]; };
El.prototype.focus = function () { document.activeElement = this; };
El.prototype.addEventListener = function (type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); };
El.prototype.fire = function (type) { var self = this; (this.listeners[type] || []).forEach(function (fn) { fn({target: self}); }); };
// What a drop-down's list does when an item is picked: it fires the select's own `change`.
El.prototype.dispatchEvent = function (event) {
  (this.listeners[event.type] || []).forEach(function (fn) { fn(event); });
  return !event.defaultPrevented;
};
El.prototype.all = function (test) {
  var found = [];
  (function walk(node) { node.children.forEach(function (c) { if (test(c)) found.push(c); walk(c); }); })(this);
  return found;
};
var ROOT_NODE = new El('div');
var document = {
  documentElement: new El('html'),
  createElement: function (tag) { return new El(tag); },
  getElementById: function (id) { return id === 'root' ? ROOT_NODE : null; }
};
// The light's phase is a custom property on the root (v0.6.10), which a test reads back.
document.documentElement.style.setProperty = function (name, value) { this[name] = String(value); };
// The page's one timer (v0.6.10), held rather than run: one left armed would keep Node alive until it
// fired. A test runs what is armed, as the browser would when its time came, with runTimers().
var TIMERS = [], TIMER_IDS = 0;
function setTimeout(fn, ms) { TIMERS.push({id: ++TIMER_IDS, fn: fn, ms: ms}); return TIMER_IDS; }
function clearTimeout(id) { TIMERS = TIMERS.filter(function (timer) { return timer.id !== id; }); }
function runTimers() { var armed = TIMERS; TIMERS = []; armed.forEach(function (timer) { timer.fn(); }); }
var window = {};
async function settle() { for (var i = 0; i < 10; i++) await new Promise(function (r) { setImmediate(r); }); }
function byId(id) { return ROOT_NODE.all(function (n) { return n.id === id; })[0]; }
function saveButton() {
  return ROOT_NODE.all(function (n) { return n.tagName === 'button' && n.parentNode.className === 'savebar'; })[0];
}
function footerNote() {
  return ROOT_NODE.all(function (n) { return n.tagName === 'p' && n.parentNode.className === 'savebar'; })[0];
}
function stored(settings) {
  window.__STORED__ = settings;
  window.openai = {callTool: function (name, args) {
    CALLS.push([name, args]);
    if (name === 'update_settings') {
      window.__STORED__ = Object.assign({}, window.__STORED__, args);
      return Promise.resolve({structuredContent: {settings: Object.assign({}, window.__STORED__)}});
    }
    if (name === 'preview_recovery_message') {
      return Promise.resolve({structuredContent: {preview: {text: 'preview', source: 'standard'}}});
    }
    return new Promise(function () {});
  }};
}
var CALLS = [];
"""


def snapshot(**settings):
    """What open_settings hands the panel, with the stored settings changed as asked."""
    values = policy.defaults()
    values.update(settings)
    return {"status": {"enabled": True, "watcher_running": True, "pending": 1, "version": "0"},
            "schema": policy.describe(), "settings": values,
            "pending": [{"thread_id": THREAD, "interruption_id": "a" * 64, "code": "waiting_reset",
                         "category": "usage_limit", "thread_enabled": True, "overlays": [],
                         "name": "example-project", "eligible_at": None, "recovery_attempts": 0}],
            "reasons": list(reasons.RECOVERABLE), "endonyms": dict(l10n.ENDONYMS),
            "system_language": "en"}


def run_page(body, data=None, locale="en", catalogs=None, root_attributes=None, prelude=""):
    """Serve the whole panel script into the stand-in document, then run `body` against it. `prelude` runs before the
    script does - a clock of the test's own, say."""
    data = snapshot() if data is None else data
    script = "\n".join([
        FAKE_DOM,
        prelude,
        "document.documentElement.attributes = %s;" % json.dumps(root_attributes or {}),
        "window.__CODEX_AUTO_RESUME_STRINGS__ = %s;" % json.dumps(l10n.catalog(locale)),
        "window.__CODEX_AUTO_RESUME_LOCALE__ = %s;" % json.dumps(locale),
        "window.__CODEX_AUTO_RESUME_CATALOGS__ = %s;" % json.dumps(
            mcpui.panel_catalogs() if catalogs is None else catalogs),
        "window.__CODEX_AUTO_RESUME__ = %s;" % json.dumps(data),
        "stored(window.__CODEX_AUTO_RESUME__.settings);",
        mcpui._SCRIPT,
        "(async function () { await settle();" + body + "})().catch(function (e) {console.error(e); process.exit(1);});",
    ])
    done = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


def say(expression: str) -> str:
    return "process.stdout.write(JSON.stringify(%s));" % expression


# ------------------------------------------------------------------------------------ the kinds
def expected_kind(entry) -> str:
    """The rule, written out once more in Python: a list item is a check box, the rest switches."""
    if entry.get("master"):
        return "switch"
    return "check" if re.fullmatch(r"(recover|notify)_[a-z0-9_]+", entry["name"]) else "switch"


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ControlKindTests(unittest.TestCase):
    def test_a_list_item_is_a_check_box_and_anything_that_runs_is_a_switch(self):
        booleans = [entry for entry in policy.describe() if entry["type"] == "boolean"]
        observed = run_javascript(["booleanKind"], say("%s.map(booleanKind)" % json.dumps(booleans)))
        self.assertEqual(dict(zip((e["name"] for e in booleans), observed)),
                         {e["name"]: expected_kind(e) for e in booleans})
        kinds = dict(zip((e["name"] for e in booleans), observed))
        # Named, so the rule cannot quietly drift into something that happens to fit today's schema.
        self.assertEqual(kinds["notifications"], "switch")
        self.assertEqual(kinds["show_tray"], "switch")
        self.assertEqual(kinds["reduce_motion"], "switch")
        for name in reasons.RECOVERABLE:
            self.assertEqual(kinds["recover_" + name], "check", name)
        self.assertTrue([name for name in kinds if name.startswith("notify_")])
        for name in kinds:
            if name.startswith("notify_"):
                self.assertEqual(kinds[name], "check", name)

    def test_the_drawn_panel_uses_each_kind_where_it_belongs(self):
        observed = run_page(say("""(function () {
          function describe(input) {
            var row = input.parentNode.className === 'setting-control' ? input.parentNode.parentNode : input.parentNode;
            return {cls: input.className, role: input.getAttribute('role'), type: input.type,
                    first: row.children[0] === input, rowClass: row.className, row: row.tagName,
                    text: row.textContent, disabled: !!input.disabled};
          }
          var sections = ROOT_NODE.all(function (n) { return n.tagName === 'section' || n.tagName === 'details'; });
          function inputsOf(title) {
            var section = sections.filter(function (s) {
              return s.all(function (n) { return n.tagName === 'h2' && n.textContent === title; }).length;
            })[0];
            return section.all(function (n) { return n.tagName === 'input' && n.type === 'checkbox'; }).map(describe);
          }
          return {recovery: inputsOf(S['group.recovery']), notifications: inputsOf(S['group.notifications']),
                  pending: inputsOf(S['panel.pending_title'])};
        })()"""))
        recover = [e for e in policy.describe() if e["name"].startswith("recover_")]
        self.assertEqual(len(observed["recovery"]), len(recover))
        self.assertEqual(sorted(i["text"] for i in observed["recovery"]),
                         sorted(ENGLISH["field." + e["name"]] for e in recover))
        for drawn in observed["recovery"]:
            with self.subTest(drawn["text"]):
                self.assertEqual((drawn["cls"], drawn["role"], drawn["first"], drawn["rowClass"], drawn["row"]),
                                 ("check", None, True, "setting check", "label"))
        master = [i for i in observed["notifications"] if i["text"] == ENGLISH["field.notifications"]]
        self.assertEqual(len(master), 1)
        self.assertEqual((master[0]["cls"], master[0]["role"], master[0]["first"]), ("switch", "switch", False))
        events = [i for i in observed["notifications"] if i["text"] != master[0]["text"]]
        self.assertEqual(len(events), len([e for e in policy.describe() if e["name"].startswith("notify_")]))
        for drawn in events:
            with self.subTest(drawn["text"]):
                self.assertEqual((drawn["cls"], drawn["role"], drawn["first"]), ("check", None, True))
        # A conversation's auto-resume turns something that runs on or off.
        self.assertEqual([(i["cls"], i["role"]) for i in observed["pending"]], [("switch", "switch")])

    def test_a_check_box_saves_like_any_other_choice(self):
        observed = run_page("""
          var box = ROOT_NODE.all(function (n) { return n.className === 'check'; })[0];
          box.checked = !box.checked;
          box.fire('change');
          var primary = saveButton().className;
          saveButton().onclick();
          await settle();
          """ + say("{primary: primary, calls: CALLS.filter(function (c) { return c[0] === 'update_settings'; })}"))
        self.assertEqual(observed["primary"], "primary")
        self.assertEqual(len(observed["calls"]), 1)
        sent = observed["calls"][0][1]
        # Everything the panel may write, except the language and the themes it did not change here
        # (ChangedElsewhereTests says why).
        self.assertEqual(set(sent), set(mcpserver.settings_schema()["properties"])
                         - {"theme", "panel_theme", "interface_language"})
        self.assertEqual(sent["recover_" + reasons.RECOVERABLE[0]], False)

    def test_without_a_host_every_box_is_disabled_and_still_drawn(self):
        observed = run_page("window.openai = undefined; HOST = null; render();" + say(
            "ROOT_NODE.all(function (n) { return n.className === 'check'; }).map(function (n) { return n.disabled; })"))
        self.assertTrue(observed)
        self.assertTrue(all(observed))


class CheckBoxStyleTests(unittest.TestCase):
    """The check box is brand's CHECKBOX, through the `--check-*` names, in light, dark and forced colours."""

    STATES = {"off": "input.check", "on": "input.check:checked",
              "off_disabled": "input.check:disabled", "on_disabled": "input.check:checked:disabled"}

    def fill_edge_elev(self, state):
        selector = self.STATES[state]
        fill = declared(selector, "background")
        edge = declared(selector, "border-color")
        if edge is None:
            edge = declared(selector, "border").split(" solid ", 1)[1]
        return fill, edge, declared(selector, "box-shadow")

    def test_every_state_is_drawn_with_its_own_check_properties(self):
        for state in self.STATES:
            prefix = "--check-%s-" % state.replace("_", "-")
            with self.subTest(state):
                self.assertEqual(self.fill_edge_elev(state),
                                 ("var(%sfill)" % prefix, "var(%sedge)" % prefix, "var(%selev)" % prefix))
        self.assertEqual(declared("input.check::before", "background"), "var(--check-on-mark)")
        self.assertEqual(declared("input.check:checked:disabled::before", "background"),
                         "var(--check-on-disabled-mark)")
        self.assertEqual(declared("input.check::before", "visibility"), "hidden")
        self.assertEqual(declared("input.check:checked::before", "visibility"), "visible")

    def test_each_state_paints_brands_colours_in_both_themes(self):
        for theme, tokens in (("light", LIGHT_TOKENS), ("dark", DARK_TOKENS), ("light", ROOT_TOKENS)):
            for state in self.STATES:
                checked, enabled = state.startswith("on"), not state.endswith("disabled")
                expected = brand.check_box(checked, enabled, theme)
                fill, edge, elev = self.fill_edge_elev(state)
                with self.subTest(theme=theme, state=state):
                    self.assertEqual(painted(fill, tokens).upper(), expected["fill"].upper())
                    self.assertEqual(painted(edge, tokens).upper(), expected["edge"].upper())
                    self.assertEqual(painted(elev, tokens),
                                     painted("var(--elev-inset)", tokens) if expected["well"] else "none")
                    mark = declared("input.check:checked:disabled::before" if state == "on_disabled"
                                    else "input.check::before", "background")
                    if expected["mark"]:
                        self.assertEqual(painted(mark, tokens).upper(), expected["mark"].upper())

    def test_its_size_shape_and_mark_are_brands(self):
        self.assertEqual(declared("input.check", "width"), "var(--size-check-size)")
        self.assertEqual(declared("input.check", "height"), "var(--size-check-size)")
        self.assertEqual(declared("input.check", "border-radius"), "var(--radius-check)")
        self.assertEqual(declared("input.check", "appearance"), "none")
        self.assertEqual(declared("input.check", "position"), "relative")
        self.assertEqual(declared(".setting.check", "gap"), "var(--size-check-gap)")
        self.assertEqual(ROOT_TOKENS["--size-check-size"], "%dpx" % brand.LAYOUT["check_size"])
        self.assertEqual(ROOT_TOKENS["--size-check-gap"], "%dpx" % brand.LAYOUT["check_gap"])
        self.assertEqual(ROOT_TOKENS["--radius-check"], "%dpx" % brand.RADII["check"])
        # The mark's layer covers the whole box, border included, and is cut to brand's tick.
        self.assertEqual(declared("input.check::before", "content"), '""')
        self.assertEqual(declared("input.check::before", "position"), "absolute")
        self.assertEqual(declared("input.check::before", "inset"), "calc(-1 * var(--size-hairline))")
        self.assertEqual(declared("input.check::before", "clip-path"), "var(--check-mark-shape)")
        self.assertEqual(ROOT_TOKENS["--size-hairline"], "%dpx" % brand.LAYOUT["hairline"])

    def test_the_box_is_centred_on_the_first_line_of_its_label(self):
        self.assertEqual(declared(".setting.check", "align-items"), "flex-start")
        self.assertEqual(declared(".setting.check", "justify-content"), "flex-start")
        margin = declared("input.check", "margin")
        self.assertEqual(margin, "calc((var(--type-body) * var(--lh-body) - var(--size-check-size)) / 2) 0 0")
        line = brand.TYPE_SCALE["body"] * brand.LINE_HEIGHT["body"]
        self.assertGreaterEqual(line, brand.LAYOUT["check_size"])
        self.assertEqual(ROOT_TOKENS["--type-body"], "%gpx" % brand.TYPE_SCALE["body"])
        self.assertEqual(float(ROOT_TOKENS["--lh-body"]), brand.LINE_HEIGHT["body"])

    def test_disabled_is_said_by_brands_colours_not_by_fading(self):
        for selector in ("input.check:disabled", "input.check:checked:disabled"):
            self.assertIsNone(declared(selector, "opacity"))
            self.assertIsNone(declared(selector, "opacity", FORCED))

    def test_forced_colours_draw_brands_system_colours_and_no_shadow(self):
        for state, selector in self.STATES.items():
            system = brand.check_box_system(state.startswith("on"), not state.endswith("disabled"))
            with self.subTest(state):
                self.assertEqual(declared(selector, "background", FORCED), brand.css_system(system["fill"]))
                self.assertEqual(declared(selector, "border-color", FORCED), brand.css_system(system["edge"]))
                self.assertEqual(declared(selector, "box-shadow", FORCED), "none")
                if system["mark"]:
                    before = selector + "::before"
                    self.assertEqual(declared(before, "background", FORCED), brand.css_system(system["mark"]))
        # Left to forced colours, the mark's layer would be painted the page's ground.
        self.assertEqual(declared("input.check", "forced-color-adjust", FORCED), "none")
        # Having opted out, it draws its own focus ring in a system colour; so does the switch.
        self.assertEqual(declared("input.check:focus-visible", "outline-color", FORCED), "Highlight")
        self.assertEqual(declared("input.switch:focus-visible", "outline-color", FORCED), "Highlight")

    def test_the_focus_ring_is_the_one_every_control_has(self):
        self.assertIn(":focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }", mcpui._STYLE)
        # Nothing of its own outside forced colours: the ring follows the box's corners, as it
        # follows every control's.
        for prop in ("outline", "outline-offset", "outline-color"):
            self.assertIsNone(declared("input.check", prop))
            self.assertIsNone(declared("input.check:focus-visible", prop))


# ------------------------------------------------------------------------------------ the theme
@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ThemeTests(unittest.TestCase):
    def test_light_and_dark_stamp_and_everything_else_follows_codex(self):
        cases = ["light", "dark", "system", None, "", "Dark", "high-contrast", 1]
        observed = run_javascript(["themeStamp", "applyTheme"], """
          function root(stamp) {
            var attributes = stamp ? {'data-theme': stamp} : {};
            return {attributes: attributes,
                    getAttribute: function (n) { return n in attributes ? attributes[n] : null; },
                    setAttribute: function (n, v) { attributes[n] = v; },
                    removeAttribute: function (n) { delete attributes[n]; }};
          }
          var cases = %s;
          process.stdout.write(JSON.stringify({
            stamps: cases.map(themeStamp),
            fromLight: cases.map(function (c) { var r = root('light'); applyTheme(r, {theme: c}, false); return r.getAttribute('data-theme'); }),
            noSettings: (function () { var r = root('dark'); applyTheme(r, null, false); return r.getAttribute('data-theme'); })(),
            pinned: cases.map(function (c) { var r = root('dark'); applyTheme(r, {theme: c}, true); return r.getAttribute('data-theme'); })
          }));
        """ % json.dumps(cases))
        self.assertEqual(observed["stamps"], ["light", "dark", "", "", "", "", "", ""])
        self.assertEqual(observed["fromLight"], ["light", "dark", None, None, None, None, None, None])
        self.assertIsNone(observed["noSettings"])
        self.assertEqual(observed["pinned"], ["dark"] * len(cases))

    def test_the_panel_theme_wins_and_same_or_nothing_is_the_themes(self):
        """v0.6.6: the panel is drawn in its own theme where it has one, and in the Theme's where it
        says "same" - or says nothing, from a watcher too old to send it, which must look exactly as
        every panel did before the setting existed."""
        pairs = [
            # (theme, panel_theme) -> the stamp on the root
            ("light", "dark"), ("dark", "light"),           # its own choice, whatever the Theme is
            ("dark", "system"), ("light", "system"),        # Codex's own: no stamp at all
            ("dark", "same"), ("light", "same"), ("system", "same"),
            ("dark", None), ("light", None), ("system", None),   # an older watcher sends none
            ("dark", "Dark"), ("light", "codex"), ("dark", 1),   # nothing this page knows: the Theme's
        ]
        observed = run_javascript(["themeStamp", "applyTheme"], """
          function root() {
            var attributes = {};
            return {getAttribute: function (n) { return n in attributes ? attributes[n] : null; },
                    setAttribute: function (n, v) { attributes[n] = v; },
                    removeAttribute: function (n) { delete attributes[n]; }};
          }
          process.stdout.write(JSON.stringify(%s.map(function (pair) {
            var settings = {theme: pair[0]};
            if (pair[1] !== null) settings.panel_theme = pair[1];
            var r = root(); applyTheme(r, settings, false); return r.getAttribute('data-theme');
          })));
        """ % json.dumps(pairs))
        self.assertEqual(observed, ["dark", "light", None, None, "dark", "light", None,
                                    "dark", "light", None, "dark", "light", "dark"])

    def test_the_stored_theme_is_on_the_root_before_the_first_paint(self):
        for theme, stamp in (("light", "light"), ("dark", "dark"), ("system", None)):
            with self.subTest(theme):
                observed = run_page(say("document.documentElement.getAttribute('data-theme')"),
                                    data=snapshot(theme=theme))
                self.assertEqual(observed, stamp)
        # A watcher older than the setting sends no theme at all: that is Use system setting.
        data = snapshot()
        del data["settings"]["theme"]
        self.assertIsNone(run_page(say("document.documentElement.getAttribute('data-theme')"), data=data))

    def test_a_pinned_page_keeps_its_stamp_whatever_is_stored(self):
        observed = run_page(say("document.documentElement.getAttribute('data-theme')"),
                            data=snapshot(theme="light"),
                            root_attributes={"data-theme": "dark", "data-theme-pinned": ""})
        self.assertEqual(observed, "dark")

    def test_a_saved_theme_applies_at_once_in_place(self):
        observed = run_page("""
          var steps = [];
          var first = ROOT_NODE.children[0];
          async function choose(value) {
            var select = byId('car-theme');
            select.value = value;
            select.fire('change');
            var before = document.documentElement.getAttribute('data-theme');
            saveButton().onclick();
            await settle();
            steps.push({before: before, after: document.documentElement.getAttribute('data-theme'),
                        samePage: ROOT_NODE.children[0] === first, note: footerNote().textContent});
          }
          await choose('dark');
          await choose('light');
          await choose('system');
          """ + say("{steps: steps, sent: CALLS.filter(function (c) { return c[0] === 'update_settings'; })"
                    ".map(function (c) { return c[1].theme; })}"))
        self.assertEqual([(s["before"], s["after"]) for s in observed["steps"]],
                         [(None, "dark"), ("dark", "light"), ("light", None)])
        # Not before the save is confirmed, and without redrawing a page whose words did not change.
        self.assertTrue(all(s["samePage"] for s in observed["steps"]))
        self.assertEqual({s["note"] for s in observed["steps"]}, {ENGLISH["panel.saved"]})
        self.assertEqual(observed["sent"], ["dark", "light", "system"])

    def test_a_refused_save_leaves_the_theme_as_it_was(self):
        observed = run_page("""
          window.openai.callTool = HOST.callTool = function (name) {
            if (name === 'update_settings') return Promise.resolve({isError: true, content: [], structuredContent: {error_code: 'invalid_setting'}});
            return new Promise(function () {});
          };
          var select = byId('car-theme');
          select.value = 'dark';
          select.fire('change');
          saveButton().onclick();
          await settle();
          """ + say("document.documentElement.getAttribute('data-theme')"), data=snapshot(theme="light"))
        self.assertEqual(observed, "light")

    def test_the_appearance_card_offers_the_three_choices_in_the_panels_words(self):
        observed = run_page(say("""(function () {
          var select = byId('car-theme');
          // select -> its drop-down -> the row's control -> the row -> the rows -> the card
          var row = select.parentNode.parentNode.parentNode;
          var card = row.parentNode.parentNode;
          return {options: select.options.map(function (o) { return [o.value, o.textContent, !!o.selected]; }),
                  title: card.children[0].textContent, help: row.textContent,
                  last: ROOT_NODE.children[0].children.slice(-2)[0] === card,
                  editors: Object.keys(collectChanges(EDITORS, DATA.schema))};
        })()"""), data=snapshot(theme="dark"))
        self.assertEqual(observed["options"], [[choice, ENGLISH["choice.theme." + choice], choice == "dark"]
                                               for choice in policy.THEMES])
        self.assertEqual(observed["title"], ENGLISH["group.appearance"])
        self.assertIn(ENGLISH["help.theme"], observed["help"])
        self.assertIn(ENGLISH["field.theme"], observed["help"])
        # Where the Windows Dashboard puts it: after the continuation message, before the save card.
        self.assertTrue(observed["last"])
        self.assertIn("theme", observed["editors"])
        self.assertNotIn("reduce_motion", observed["editors"])

    def test_the_panels_own_row_offers_its_four_choices_in_the_panels_words(self):
        observed = run_page(say("""(function () {
          var select = byId('car-panel_theme');
          var row = select.parentNode.parentNode.parentNode;
          var theme = byId('car-theme').parentNode.parentNode.parentNode;
          var rows = row.parentNode.children;
          return {options: select.options.map(function (o) { return [o.value, o.textContent, !!o.selected]; }),
                  help: row.textContent, sameCard: row.parentNode === theme.parentNode,
                  after: rows.indexOf(row) === rows.indexOf(theme) + 1};
        })()"""), data=snapshot(panel_theme="light"))
        self.assertEqual(observed["options"], [[choice, ENGLISH["choice.panel_theme." + choice], choice == "light"]
                                               for choice in policy.PANEL_THEMES])
        self.assertIn(ENGLISH["field.panel_theme"], observed["help"])
        self.assertIn(ENGLISH["help.panel_theme"], observed["help"])
        # Right under the Theme, in the same card.
        self.assertTrue(observed["sameCard"])
        self.assertTrue(observed["after"])

    def test_a_saved_panel_theme_is_sent_alone_and_applies_at_once_in_place(self):
        observed = run_page("""
          var steps = [];
          var first = ROOT_NODE.children[0];
          async function choose(value) {
            var select = byId('car-panel_theme');
            select.value = value;
            select.fire('change');
            saveButton().onclick();
            await settle();
            steps.push([document.documentElement.getAttribute('data-theme'), ROOT_NODE.children[0] === first]);
          }
          await choose('light');
          await choose('system');
          await choose('same');
          """ + say("{steps: steps, sent: CALLS.filter(function (c) { return c[0] === 'update_settings'; })"
                    ".map(function (c) { return [c[1].panel_theme, c[1].theme]; })}"), data=snapshot(theme="dark"))
        # Its own Light, then Codex's (no stamp), then the Theme's Dark again - each without a redraw.
        self.assertEqual([step[0] for step in observed["steps"]], ["light", None, "dark"])
        self.assertTrue(all(step[1] for step in observed["steps"]))
        # Each save carries the choice made here, and never the Theme nobody touched.
        self.assertEqual(observed["sent"], [["light", None], ["system", None], ["same", None]])

    def test_only_the_themes_of_the_appearance_settings_are_the_panels_to_change(self):
        schema = policy.describe()
        observed = run_javascript(["editable"], say("%s.filter(editable).map(function (e) { return e.name; })"
                                                    % json.dumps(schema, default=str)))
        appearance = {e["name"] for e in schema if e["group"] == "appearance"}
        self.assertEqual(set(observed) & appearance, {"theme", "panel_theme"})
        self.assertEqual(set(observed), set(mcpserver.settings_schema()["properties"]))


class ServedThemeTests(unittest.TestCase):
    def test_codex_is_served_no_stamp_and_a_capture_is_served_a_pinned_one(self):
        self.assertTrue(mcpui.settings_page().startswith("<!doctype html><html><head>"))
        for theme in ("light", "dark"):
            with self.subTest(theme):
                self.assertTrue(mcpui.settings_page(theme=theme).startswith(
                    '<!doctype html><html data-theme="%s" data-theme-pinned=""><head>' % theme))
        self.assertTrue(mcpui.settings_page(theme="system").startswith("<!doctype html><html><head>"))

    def test_the_theme_is_stamped_on_the_root_where_the_check_aliases_are_declared(self):
        script = mcpui._SCRIPT
        self.assertIn("applyTheme(document.documentElement, settings, THEME_PINNED);", script)
        self.assertEqual(len(re.findall(r"setAttribute\('data-theme'", script)), 1)
        self.assertIn("hasAttribute('data-theme-pinned')", script)
        # Applied before the first render, and from a confirmed save - nowhere else.
        self.assertEqual(re.findall(r"(?<!function )\badopt\(([^)]*)\)", script),
                         ["payload.settings", "DATA && DATA.settings"])
        self.assertLess(script.index("adopt(DATA && DATA.settings);"), script.rindex("render();"))


# --------------------------------------------------------------------------------- the language
class ServedLanguageTests(unittest.TestCase):
    def test_every_language_ships_every_word_the_script_can_ask_for(self):
        page = mcpui.settings_page()
        catalogs = served(page, "__CODEX_AUTO_RESUME_CATALOGS__")
        self.assertEqual(set(catalogs), set(l10n.LOCALES))
        names, prefixes = mcpui.panel_keys()
        self.assertGreater(len(names), 40)
        for locale in l10n.LOCALES:
            full = l10n.catalog(locale)
            wanted = {key for key in full if key in names or key.startswith(prefixes)}
            with self.subTest(locale):
                self.assertEqual(catalogs[locale], {key: full[key] for key in wanted})
                self.assertEqual(sorted(name for name in names if name not in catalogs[locale]), [])
        # The prefixes are the ones the catalog test lists values for, so none of them is empty.
        for prefix in prefixes:
            self.assertTrue([key for key in catalogs["en"] if key.startswith(prefix)], prefix)

    def test_the_served_words_are_the_resolved_language_and_say_which_it_is(self):
        page = mcpui.settings_page()
        self.assertEqual(served(page, "__CODEX_AUTO_RESUME_LOCALE__"), interface.language())
        self.assertEqual(served(page, "__CODEX_AUTO_RESUME_STRINGS__"), interface.catalog())
        # Every value before the script, which reads them as it starts.
        script = page.index("<script>" + mcpui._SCRIPT)
        for name in ("__CODEX_AUTO_RESUME_STRINGS__", "__CODEX_AUTO_RESUME_LOCALE__", "__CODEX_AUTO_RESUME_CATALOGS__"):
            self.assertLess(page.index("window.%s=" % name), script, name)

    def test_the_script_asks_for_words_only_by_a_written_key_or_prefix(self):
        """`panel_catalogs` ships the keys it can read out of the script. A key computed any other
        way would be a word no other language ships, so the only computed lookups are the helpers'."""
        rest = mcpui._SCRIPT
        for helper in ("t", "fill", "withLanguage"):
            self.assertIn(javascript_function(helper), rest)
            rest = rest.replace(javascript_function(helper), "")
        self.assertEqual(re.findall(r"(?<![\w.])(?:t|fill|withLanguage)\(\s*(?!')|(?<![\w.])S\[(?!')", rest), [])
        literal = re.findall(r"(?<![\w.])(?:t|fill|withLanguage)\(\s*'|(?<![\w.])S\['", rest)
        matched = (re.findall(r"\b(?:t|fill|withLanguage)\(\s*'[a-z0-9_.]+'\s*[,)]", rest)
                   + re.findall(r"\b(?:t|fill)\(\s*'[a-z0-9_.]+\.'\s*\+|\bS\['[a-z0-9_.]+\.'\s*\+", rest))
        self.assertEqual(len(literal), len(matched))

    def test_the_page_stays_self_contained_and_escaped(self):
        page = mcpui.settings_page()
        for forbidden in ("http://", "https://", "<script src", "textarea", "contenteditable"):
            self.assertNotIn(forbidden, page.lower() if forbidden != "<script src" else page)
        catalogs = page.split("window.__CODEX_AUTO_RESUME_CATALOGS__=", 1)[1].split(";</script>", 1)[0]
        self.assertNotIn("<", catalogs)


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class LanguageTests(unittest.TestCase):
    def test_a_stored_language_resolves_as_python_adopts_it(self):
        """`_read_resource` adopts the stored value with `l10n.set_preference` and resolves it;
        `system_language` is Windows' answer, which Python worked out."""
        preferences = list(l10n.CHOICES) + ["", None, 3]
        cases = [[preference, system] for preference in preferences for system in l10n.LOCALES]
        catalogs = {locale: {} for locale in l10n.LOCALES}
        observed = run_javascript(["localeFor"], say("%s.map(function (c) { return localeFor(c[0], c[1], %s); })"
                                                     % (json.dumps(cases), json.dumps(catalogs))))
        for (preference, system), locale in zip(cases, observed):
            adopted = preference if preference in l10n.CHOICES else l10n.SYSTEM
            with self.subTest(preference=preference, system=system):
                self.assertEqual(locale, l10n.resolve(adopted, {l10n.ENV_LANG: system}))

    def test_a_language_the_page_has_no_words_for_keeps_the_words_it_was_served(self):
        # Not English, and not Windows' language either: a stored choice this page cannot speak -
        # which the settings file's validation leaves to a page older than the watcher - is not
        # a reason to speak a language nobody chose.
        observed = run_javascript(["localeFor"], say(
            "[localeFor('system', undefined, {en: {}}), localeFor('ko', undefined, {en: {}}),"
            " localeFor('ko', 'en', {en: {}}), localeFor('ko', 'en', {}), localeFor('en', null, null),"
            " localeFor('ko-KR', 'en', {en: {}, ko: {}}), localeFor('EN', 'ko', {en: {}, ko: {}})]"))
        self.assertEqual(observed, ["", "", "", "", "", "", ""])

    def test_a_saved_language_redraws_the_panel_in_it_at_once(self):
        observed = run_page("""
          var before = ROOT_NODE.textContent;
          var select = byId('car-interface_language');
          select.value = 'ko';
          select.fire('change');
          saveButton().onclick();
          await settle();
          """ + say("{before: before, after: ROOT_NODE.textContent, note: footerNote().textContent,"
                    " locale: LOCALE, save: saveButton().textContent, primary: saveButton().className,"
                    " focused: document.activeElement === saveButton(),"
                    " language: byId('car-interface_language').value}"))
        keys = ("group.general", "group.recovery", "group.notifications", "group.continuation",
                "group.appearance", "preview.title", "field.theme", "activity.waiting")
        for key in keys:
            with self.subTest(key):
                self.assertNotEqual(ENGLISH[key], KOREAN[key])
                self.assertIn(ENGLISH[key], observed["before"])
                self.assertNotIn(KOREAN[key], observed["before"])
                self.assertIn(KOREAN[key], observed["after"])
                self.assertNotIn(ENGLISH[key], observed["after"])
        self.assertEqual(observed["locale"], "ko")
        self.assertEqual(observed["note"], KOREAN["panel.saved"])
        self.assertEqual(observed["save"], KOREAN["action.save"])
        self.assertEqual(observed["primary"], "")
        # The pressed button was replaced by the redraw; the keyboard stays on its successor.
        self.assertTrue(observed["focused"])
        self.assertEqual(observed["language"], "ko")
        self.assertNotIn(ENGLISH["settings.language_changed"], observed["after"])

    def test_a_language_saved_as_system_speaks_windows_language(self):
        data = snapshot(interface_language="en")
        data["system_language"] = "ja"
        observed = run_page("""
          var select = byId('car-interface_language');
          select.value = 'system';
          select.fire('change');
          saveButton().onclick();
          await settle();
          """ + say("{locale: LOCALE, note: footerNote().textContent}"), data=data)
        self.assertEqual(observed, {"locale": "ja", "note": l10n.catalog("ja")["panel.saved"]})

    def test_the_stored_language_wins_over_a_page_served_in_another(self):
        # Codex may show a page it read before the language was changed somewhere else.
        observed = run_page(say("{locale: LOCALE, text: ROOT_NODE.textContent}"),
                            data=snapshot(interface_language="ko"), locale="en")
        self.assertEqual(observed["locale"], "ko")
        self.assertIn(KOREAN["group.recovery"], observed["text"])
        self.assertNotIn(ENGLISH["group.recovery"], observed["text"])

    def test_without_the_words_it_says_the_change_waits_and_keeps_its_language(self):
        catalogs = {"en": mcpui.panel_catalogs()["en"]}
        observed = run_page("""
          var first = ROOT_NODE.children[0];
          var select = byId('car-interface_language');
          select.value = 'ko';
          select.fire('change');
          saveButton().onclick();
          await settle();
          """ + say("{locale: LOCALE, note: footerNote().textContent, same: ROOT_NODE.children[0] === first}"),
                            catalogs=catalogs)
        self.assertEqual(observed, {"locale": "en", "note": ENGLISH["settings.language_changed"], "same": True})

    def test_a_save_that_changes_no_language_does_not_redraw(self):
        observed = run_page("""
          var first = ROOT_NODE.children[0];
          var box = ROOT_NODE.all(function (n) { return n.className === 'check'; })[0];
          box.checked = !box.checked;
          box.fire('change');
          saveButton().onclick();
          await settle();
          """ + say("{same: ROOT_NODE.children[0] === first, note: footerNote().textContent}"))
        self.assertEqual(observed, {"same": True, "note": ENGLISH["panel.saved"]})


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ChangedElsewhereTests(unittest.TestCase):
    """The page keeps the settings it was drawn with, and the Windows Dashboard, another panel or
    Codex itself may change the language or the theme while it stays open. A save of anything else
    must not send the old ones back: that quietly undid the change, and the Dashboard, which
    reopens itself in a new language or theme, then reopened in the one it had just left."""

    ELSEWHERE = """
      window.__STORED__ = Object.assign({}, window.__STORED__, {theme: 'dark', interface_language: 'ko'});
    """

    def test_saving_something_else_leaves_a_language_and_theme_changed_elsewhere_alone(self):
        observed = run_page(self.ELSEWHERE + """
          var box = ROOT_NODE.all(function (n) { return n.className === 'check'; })[0];
          box.checked = !box.checked;
          box.fire('change');
          saveButton().onclick();
          await settle();
          var sent = CALLS.filter(function (c) { return c[0] === 'update_settings'; }).map(function (c) { return c[1]; });
          """ + say("{sent: sent, stored: window.__STORED__, locale: LOCALE,"
                    " stamp: document.documentElement.getAttribute('data-theme'),"
                    " theme: byId('car-theme').value, language: byId('car-interface_language').value,"
                    " primary: saveButton().className, note: footerNote().textContent}"))
        self.assertEqual(len(observed["sent"]), 1)
        sent = observed["sent"][0]
        self.assertNotIn("theme", sent)
        self.assertNotIn("panel_theme", sent)
        self.assertNotIn("interface_language", sent)
        self.assertEqual(sent["recover_" + reasons.RECOVERABLE[0]], False)
        # Everything else is still sent whole, as it always was.
        self.assertEqual(set(sent), set(mcpserver.settings_schema()["properties"])
                         - {"theme", "panel_theme", "interface_language"})
        self.assertEqual((observed["stored"]["theme"], observed["stored"]["interface_language"]), ("dark", "ko"))
        # The confirmed settings are drawn: the controls say what is stored, so nothing is left
        # looking unsaved and the next save cannot send the old values back either.
        self.assertEqual((observed["stamp"], observed["theme"], observed["language"], observed["locale"]),
                         ("dark", "dark", "ko", "ko"))
        self.assertEqual(observed["primary"], "")
        self.assertEqual(observed["note"], KOREAN["panel.saved"])

    def test_a_theme_changed_elsewhere_is_drawn_after_a_save_and_a_second_save_keeps_it(self):
        observed = run_page("""
          window.__STORED__ = Object.assign({}, window.__STORED__, {theme: 'dark'});
          var boxes = ROOT_NODE.all(function (n) { return n.className === 'check'; });
          boxes[0].checked = !boxes[0].checked;
          boxes[0].fire('change');
          saveButton().onclick();
          await settle();
          var after = {theme: byId('car-theme').value, primary: saveButton().className,
                       stamp: document.documentElement.getAttribute('data-theme')};
          boxes = ROOT_NODE.all(function (n) { return n.className === 'check'; });
          boxes[1].checked = !boxes[1].checked;
          boxes[1].fire('change');
          saveButton().onclick();
          await settle();
          """ + say("{after: after, stored: window.__STORED__.theme, locale: LOCALE,"
                    " sent: CALLS.filter(function (c) { return c[0] === 'update_settings'; })"
                    ".map(function (c) { return 'theme' in c[1]; })}"))
        self.assertEqual(observed["after"], {"theme": "dark", "primary": "", "stamp": "dark"})
        self.assertEqual(observed["sent"], [False, False])
        self.assertEqual((observed["stored"], observed["locale"]), ("dark", "en"))

    def test_a_language_or_theme_chosen_here_is_still_sent(self):
        observed = run_page(self.ELSEWHERE + """
          var theme = byId('car-theme');
          theme.value = 'light';
          theme.fire('change');
          var language = byId('car-interface_language');
          language.value = 'de';
          language.fire('change');
          saveButton().onclick();
          await settle();
          """ + say("{sent: CALLS.filter(function (c) { return c[0] === 'update_settings'; }).map(function (c) {"
                    " return [c[1].theme, c[1].interface_language]; }), stored: window.__STORED__, locale: LOCALE}"))
        self.assertEqual(observed["sent"], [["light", "de"]])
        self.assertEqual((observed["stored"]["theme"], observed["stored"]["interface_language"], observed["locale"]),
                         ("light", "de", "de"))

    def test_only_the_language_and_theme_are_left_out_when_unchanged(self):
        observed = run_javascript(["unedited"], say(
            "[unedited({theme: 'system', interface_language: 'en', notifications: true, continuation_language: 'en'},"
            " {theme: 'system', interface_language: 'en', notifications: true, continuation_language: 'en'}),"
            " unedited({theme: 'dark', interface_language: 'en'}, {theme: 'system', interface_language: 'ko'}),"
            " unedited({theme: 'system'}, {}), unedited({}, {theme: 'system'}), unedited({theme: 'dark'}, null)]"))
        self.assertEqual(observed, [["interface_language", "theme"], [], [], [], []])


# ------------------------------------------------------------------------ pinned to the bottom-right
NARROW = "@media (max-width: 520px)"
# Every control at the right of a row that is pinned, and the row it is pinned in.
PINNED = {".setting.toggle > input.switch": ".setting", ".master > button": ".master",
          ".prow-switch": ".prow"}


def own_declarations(selector: str) -> dict:
    """Every declaration the plain rules naming exactly `selector` give it, outside any at-rule."""
    found = {}
    for where, selectors, declarations in RULES:
        if where == "" and selector in selectors:
            found.update(declarations)
    return found


class PinnedControlStyleTests(unittest.TestCase):
    """A switch or a button at the right of a row sits at the row's bottom-right: its right edge on
    the row's, its bottom on the bottom of the text beside it. The renderer's own measurements are
    not available here, so what is held is the flex arrangement that produces it - and that nothing
    else was moved, resized or given a way to slide under the text."""

    def test_each_control_is_pinned_to_the_end_of_its_row_on_both_axes(self):
        for control, row in PINNED.items():
            with self.subTest(control):
                # Bottom: the end of the flex line, which is as tall as the text beside it.
                self.assertEqual(declared(control, "align-self"), "flex-end")
                # Right: on the row's right edge, and still there when it wraps under the text.
                self.assertEqual(declared(control, "margin-left"), "auto")
                self.assertEqual(declared(row, "display"), "flex")
                self.assertEqual(declared(row, "flex-wrap"), "wrap")
                # Text shorter than the control is still centred on it: a one-line row is unchanged.
                self.assertEqual(declared(row, "align-items"), "center")

    def test_the_text_beside_a_control_wraps_and_never_runs_under_it(self):
        # The text shrinks and wraps; the control keeps its size. Neither is positioned, so the
        # text cannot be laid out underneath the control - it wraps, or the control drops a line.
        for text, basis in ((".setting-text", "1 1 180px"), (".master-body", "1 1 200px"),
                            (".prow-main", "1 1 220px")):
            with self.subTest(text):
                self.assertEqual(declared(text, "flex"), basis)
                self.assertEqual(declared(text, "min-width"), "0")
        self.assertEqual(declared("input.switch", "flex"), "none")
        for control in PINNED:
            self.assertIsNone(declared(control, "position"), control)
        # The note under the state is part of the text block, not a line that runs under the button.
        self.assertEqual(declared(".master-body", "display"), "grid")
        self.assertIsNone(declared(".master .note", "flex"))
        # An open confirmation is a line of its own, under the text and the switch alike.
        self.assertEqual(declared(".prow-confirm", "flex"), "1 1 100%")

    def test_pinning_moves_a_control_and_changes_nothing_about_it(self):
        # Hit targets, focus rings and colours are the controls' own rules, untouched.
        self.assertEqual(set(own_declarations(".setting.toggle > input.switch")), {"align-self", "margin-left"})
        self.assertEqual(set(own_declarations(".master > button")), {"align-self", "margin-left"})
        self.assertEqual(declared("input.switch", "width"), "var(--size-switch-width)")
        self.assertEqual(declared("input.switch", "height"), "var(--size-switch-height)")
        self.assertEqual(declared("button", "min-height"), "var(--size-button-height)")
        # Narrow, High Contrast and less motion keep the same place: none of them re-aligns a pinned
        # control or the row it is pinned in.
        for context in (NARROW, FORCED, "@media (prefers-reduced-motion: reduce)"):
            for selector in set(PINNED) | set(PINNED.values()) | {"input.switch", "button", ".master-body"}:
                for prop in ("align-self", "align-items", "margin-left", "flex-wrap", "display", "order"):
                    with self.subTest(context=context, selector=selector, prop=prop):
                        self.assertIsNone(declared(selector, prop, context))

    def test_only_the_controls_at_the_right_of_a_row_are_pinned(self):
        pinned = {selector for where, selectors, declarations in RULES
                  if declarations.get("align-self") == "flex-end" for selector in selectors}
        self.assertEqual(pinned, set(PINNED))
        # A check box stays left of its label, on the label's first line.
        self.assertEqual(declared(".setting.check", "align-items"), "flex-start")
        # A select or a number stays centred beside its name.
        self.assertIsNone(declared(".setting-control", "align-self"))
        # The buttons already at the bottom - the save card's and the confirmation's - keep their places.
        self.assertEqual(declared(".savebar", "align-items"), "center")
        self.assertIsNone(declared(".savebar button", "align-self"))
        self.assertIsNone(declared(".actions", "justify-content"))
        # No control is reordered by CSS: what is seen first is what is read and reached first.
        self.assertEqual([selectors for where, selectors, declarations in RULES if "order" in declarations], [])


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PinnedControlMarkupTests(unittest.TestCase):
    """Content first, then the control: the order the page is read in and Tab moves in."""

    DESCRIBE = """
      function describe(node) {
        return {tag: node.tagName, cls: node.className, role: node.getAttribute('role'),
                children: node.children.map(function (c) { return c.tagName + '.' + c.className; })};
      }
    """

    def test_each_pinned_control_is_the_last_thing_in_its_row(self):
        observed = run_page(self.DESCRIBE + "OPEN.notifications = true; render();" + say("""(function () {
          var master = ROOT_NODE.all(function (n) { return n.className === 'master'; })[0];
          var body = master.children[0];
          var toggle = ROOT_NODE.all(function (n) { return n.className === 'setting toggle'; })[0];
          var prow = ROOT_NODE.all(function (n) { return n.className === 'prow'; })[0];
          var wrap = prow.children[1];
          return {master: describe(master), body: describe(body), note: describe(body.children[1]),
                  toggle: describe(toggle), prow: describe(prow), wrap: describe(wrap)};
        })()"""))
        self.assertEqual(observed["master"]["children"], ["div.master-body", "button."])
        self.assertEqual(observed["body"]["children"], ["div.master-text", "p.note"])
        self.assertEqual(observed["note"]["role"], "status")
        self.assertEqual(observed["toggle"]["children"], ["span.setting-text", "input.switch"])
        self.assertEqual(observed["prow"]["children"], ["div.prow-main", "label.prow-switch"])
        self.assertEqual(observed["wrap"]["children"], ["span.", "input.switch"])

    def test_an_open_confirmation_follows_the_switch_it_asks_about(self):
        observed = run_page(
            "CONFIRM_ROW = DATA.pending[0].interruption_id; render();" + say(
                "ROOT_NODE.all(function (n) { return n.className === 'prow'; })[0].children"
                ".map(function (c) { return c.className; })"))
        self.assertEqual(observed, ["prow-main", "prow-switch", "prow-confirm"])

    def test_a_refused_pause_is_written_under_the_state_beside_the_button(self):
        observed = run_page("""
          window.openai.callTool = function (name) {
            CALLS.push([name]);
            return name === 'pause_auto_recovery' ? Promise.reject(new Error('not now')) : new Promise(function () {});
          };
          var master = ROOT_NODE.all(function (n) { return n.className === 'master'; })[0];
          var pause = master.children[master.children.length - 1];
          pause.onclick();
          await settle();
          var note = master.all(function (n) { return n.className === 'note'; })[0];
          """ + say("{called: CALLS.map(function (c) { return c[0]; }), text: note.textContent,"
                    " parent: note.parentNode.className, last: master.children[master.children.length - 1] === pause,"
                    " enabled: !pause.disabled}"))
        self.assertIn("pause_auto_recovery", observed["called"])
        self.assertEqual((observed["text"], observed["parent"], observed["last"], observed["enabled"]),
                         ("not now", "master-body", True, True))


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class LightClockTests(unittest.TestCase):
    """v0.6.10: the page's two lights share one phase that a redraw does not reset (F2), and a task that comes due
    while the page is open turns it to checking, with its arc, as the popup and the Dashboard do - by the page's one
    timer, which says it again in place (F3)."""

    # The page's clocks, the test's own: the wall clock the rows' times are read by, and the one the light's phase
    # is counted on. `Date` is shadowed for the whole script, so the global one is taken first.
    CLOCK = """
      var REAL_DATE = globalThis.Date, NOW_MS = %d, PERF_MS = 1000;
      var Date = function (value) { return arguments.length ? new REAL_DATE(value) : new REAL_DATE(NOW_MS); };
      Date.now = function () { return NOW_MS; };
      var performance = {now: function () { return PERF_MS; }};
    """ % int(1_800_000_000 * 1000)
    LOOK = """
      function look() {
        var hero = ROOT_NODE.all(function (n) { return n.className === 'card hero'; })[0];
        return {state: hero.getAttribute('data-state'),
                word: ROOT_NODE.all(function (n) { return n.tagName === 'h1'; })[0].textContent,
                lights: ROOT_NODE.all(function (n) { return n.classList.contains('halo'); })
                                 .map(function (n) { return n.className; }),
                due: ROOT_NODE.all(function (n) { return n.getAttribute('data-due') !== null; })
                              .map(function (n) { return n.textContent; }),
                facts: ROOT_NODE.all(function (n) { return n.className === 'facts'; })[0].children
                                .map(function (n) { return n.textContent; }),
                timers: TIMERS.map(function (timer) { return timer.ms; }),
                delay: document.documentElement.style['--light-delay']};
      }
    """

    def data(self, *later):
        """A running watcher with recovery on and a waiting row for each of `later`, seconds from the clock."""
        data = snapshot()
        row = data["pending"][0]
        data["pending"] = [dict(row, interruption_id=str(index) * 64, eligible_at=1_800_000_000 + seconds)
                           for index, seconds in enumerate(later, 1)]
        data["status"]["pending"] = len(later)
        return data

    def page(self, body, data):
        return run_page(self.LOOK + body, data=data, prelude=self.CLOCK)

    def test_a_task_that_comes_due_while_the_page_is_open_turns_it_to_checking(self):
        observed = self.page("""
          var steps = [look()];
          NOW_MS += 60000; PERF_MS += 60000;
          runTimers();
          steps.push(look());
          NOW_MS += 30000; PERF_MS += 30000;
          runTimers();
          steps.push(look());
          """ + say("steps"), self.data(60, 90))
        waiting, checking, later = observed
        self.assertEqual((waiting["state"], waiting["word"]), ("waiting", ENGLISH["activity.waiting"]))
        self.assertEqual(waiting["lights"], ["halo waiting", "halo mini waiting"])
        self.assertNotIn(ENGLISH["panel.due"], waiting["due"])
        # One timer, for the soonest time still to come, and nothing else ticking.
        self.assertEqual(waiting["timers"], [60000])
        # Its time comes: the word, both lights, the facts and the row say so, in place.
        self.assertEqual((checking["state"], checking["word"]), ("checking", ENGLISH["activity.checking"]))
        self.assertEqual(checking["lights"], ["halo checking", "halo mini checking"])
        self.assertEqual(checking["due"][0], ENGLISH["panel.due"])
        self.assertNotEqual(checking["due"][1], ENGLISH["panel.due"])
        self.assertIn(ENGLISH["status.next_check"].replace("{time}", ENGLISH["panel.due"]), checking["facts"])
        self.assertEqual(checking["delay"], "0ms", "a light that has just changed starts at the top of its cycle")
        self.assertEqual(checking["timers"], [30000])
        # The next one's time comes too: nothing about the light changed, so its phase is left alone, and nothing
        # is left to wait for.
        self.assertEqual(later["lights"], ["halo checking", "halo mini checking"])
        self.assertEqual(later["due"], [ENGLISH["panel.due"]] * 2)
        self.assertEqual(later["delay"], "0ms")
        self.assertEqual(later["timers"], [])

    def test_a_page_with_no_time_to_come_keeps_no_timer(self):
        for data, state in ((snapshot(), "waiting"), (self.data(-5), "checking"), (self.data(-5, 60), "checking")):
            with self.subTest(state=state, rows=len(data["pending"])):
                observed = self.page(say("look()"), data)
                self.assertEqual(observed["state"], state)
                self.assertEqual(observed["lights"], ["halo " + state, "halo mini " + state])
                self.assertEqual(observed["timers"], [60000] if len(data["pending"]) == 2 else [])

    def test_a_redraw_keeps_the_light_s_phase_and_a_new_light_starts_its_own(self):
        observed = self.page("""
          var delays = [look().delay];
          PERF_MS += 2500; render(); delays.push(look().delay);
          PERF_MS += 1000; render(); delays.push(look().delay);
          DATA.status.enabled = false;
          PERF_MS += 500; render(); delays.push(look().delay, look().lights);
          PERF_MS += 700; render(); delays.push(look().delay);
          """ + say("delays"), self.data(60))
        self.assertEqual(observed, ["0ms", "-2500ms", "-3500ms", "0ms", ["halo paused", "halo mini paused"], "-700ms"])
        # A redraw arms the timer anew rather than a second one beside it.
        self.assertEqual(self.page("render(); render();" + say("look().timers"), self.data(60)), [60000])


if __name__ == "__main__":
    unittest.main()
