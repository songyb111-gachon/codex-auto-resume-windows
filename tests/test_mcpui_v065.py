"""The v0.6.5 settings panel: its own drop-down list, and controls that move when they change.

* **The drop-down is the page's own.** A native select opens the browser's list - square, flat,
  system blue - which belongs to no card on this page, so every select is shown through the list the
  Windows Dashboard opens: a combobox over a hidden select, and a listbox in the cards' material. It
  is the WAI-ARIA select-only combobox, keys and all, and the select underneath is still the value
  the page reads and the `change` it listens to. The native list can never open: the select is never
  shown, focused or reached by Tab.
* **Switches glide, check boxes fade.** On brand's one transition time and the page's one curve,
  paint only, and not at all with less motion or in High Contrast. A switch whose change waits for a
  confirmation moves once, when the change is confirmed - never on the press, never back.

Most of it runs the panel's own script in Node against the small stand-in for the DOM that
test_mcpui_v064 keeps, because the claims are about what the page does; the rest reads the
stylesheet rule by rule.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import guiscan                                                             # noqa: E402
import srcscan                                                             # noqa: E402
from codex_auto_resume import brand, l10n                          # noqa: E402
from codex_auto_resume.mcp import panel as mcpui
from codex_auto_resume import settings as policy                          # noqa: E402
from test_mcpui_v063 import (FORCED, REDUCED, RULES, ROOT_TOKENS, SUPPORTS_MIX,  # noqa: E402
                             cubic_bezier, declared, javascript_function)
from test_mcpui_v064 import run_page, say, snapshot                       # noqa: E402

NODE = shutil.which("node")
ENGLISH = l10n.catalog("en")
LANG = "car-interface_language"

# Helpers the tests run beside the page: events with the fields the page reads, and a look at one
# drop-down. `CLOCK` is the keys' time stamp, in milliseconds.
HELPERS = r"""
var CLOCK = 1000;
function send(node, type, props) {
  var event = {type: type, key: '', altKey: false, ctrlKey: false, metaKey: false, timeStamp: CLOCK,
               defaultPrevented: false, stopped: false, target: node,
               preventDefault: function () { this.defaultPrevented = true; },
               stopPropagation: function () { this.stopped = true; }};
  Object.keys(props || {}).forEach(function (name) { event[name] = props[name]; });
  (node.listeners[type] || []).forEach(function (fn) { fn(event); });
  return event;
}
function key(node, name, props) {
  CLOCK += (props && props.wait) || 100;
  return send(node, 'keydown', Object.assign({key: name, timeStamp: CLOCK}, props || {}));
}
function parts(id) {
  var list = byId(id + '-list');
  return {select: byId(id), box: byId(id + '-box'), list: list, scroll: list.children[0],
          options: list.children[0].children};
}
function look(id) {
  var p = parts(id);
  return {expanded: p.box.getAttribute('aria-expanded'), active: p.box.getAttribute('aria-activedescendant'),
          hidden: !!p.list.hidden, value: p.select.value, shown: p.box.textContent,
          keys: p.list.classList.contains('keys'), up: p.list.classList.contains('up'),
          focused: document.activeElement === p.box,
          selected: p.options.map(function (o) { return o.getAttribute('aria-selected'); }).indexOf('true')};
}
function option(id, index) { return id + '-option-' + index; }
// The pointer moving over `node`; a move Windows makes up for a pointer that stood still has no movement.
function point(node, props) {
  return send(node, 'mousemove', Object.assign({movementX: 3, movementY: 1, screenX: 0, screenY: 0}, props || {}));
}
"""


def page(body, **kwargs):
    return run_page(HELPERS + body, **kwargs)


def choices(name):
    return next(entry["choices"] for entry in policy.describe() if entry["name"] == name)


LANGS = choices("interface_language")

# The window's list, which the panel's is the same as: the window's control sources,
# concatenated in compile order, whichever files `gui/window.sources` names them in.
CONTROLS = guiscan.controls()
# How many rows a list shows before it scrolls (SoftCombo's MaxDropDownItems), and how long letters typed
# one after another make one search (SoftCombo.TypeAhead).
ROWS = 12
TYPING_MS = 1000
# Page Up and Page Down move what shows less one, as the window's list does - a list that shows all its
# rows, when nothing is measured.
PAGE = min(len(LANGS), ROWS) - 1


def window_find(texts, typed, start):
    """SoftCombo.Find, the window's type-to-find, written out once more: a first letter - or the same
    letter again and again - looks from the item after the one the keyboard is on; a longer search keeps
    that item while it still matches."""
    repeated = all(character.lower() == typed[0].lower() for character in typed)
    wanted = typed[0] if repeated else typed
    begin = start + 1 if repeated else start
    for step in range(len(texts)):
        at = (begin + step) % len(texts)
        if texts[at].lower().startswith(wanted.lower()):
            return at
    return -1


# ------------------------------------------------------------------------------------ markup
@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ComboMarkupTests(unittest.TestCase):
    def test_every_drop_down_is_a_combobox_over_a_hidden_select(self):
        observed = page("OPEN.limits = true; render();" + say("""ROOT_NODE.all(function (n) { return n.tagName === 'select'; })
          .map(function (select) {
            var wrap = select.parentNode, box = wrap.children[1], list = wrap.children[2];
            var labelled = byId(box.getAttribute('aria-labelledby'));
            return {id: select.id, hidden: select.hidden, aria: select.getAttribute('aria-hidden'),
                    tab: select.getAttribute('tabindex'), wrap: wrap.className, first: wrap.children[0] === select,
                    role: box.getAttribute('role'), popup: box.getAttribute('aria-haspopup'),
                    expanded: box.getAttribute('aria-expanded'), controls: box.getAttribute('aria-controls'),
                    boxId: box.id, boxTab: box.getAttribute('tabindex'), shown: box.textContent,
                    listId: list.id, listRole: list.getAttribute('role'), listHidden: list.hidden,
                    listTab: list.getAttribute('tabindex'), listLabel: list.getAttribute('aria-labelledby'),
                    label: labelled && labelled.tagName, labelText: labelled && labelled.textContent,
                    labelFor: (labelled && labelled.htmlFor) || null,
                    scroll: [list.children.length, list.children[0].className, list.children[0].getAttribute('role')],
                    options: list.children[0].children.map(function (o, i) {
                      return [o.id, o.getAttribute('role'), o.getAttribute('aria-selected'), o.textContent,
                              select.options[i].textContent, select.options[i].value === select.value]; })};
          })"""))
        ids = [drawn["id"] for drawn in observed]
        self.assertEqual(sorted(ids), sorted(["car-interface_language", "car-retry_timing", "car-continuation_language",
                                              "car-custom_message_mode", "car-preview-reason", "car-theme",
                                              "car-panel_theme"]))
        for drawn in observed:
            with self.subTest(drawn["id"]):
                name = drawn["id"]
                # The select is still there and still the value, and nothing can reach it.
                self.assertEqual((drawn["hidden"], drawn["aria"], drawn["tab"], drawn["wrap"], drawn["first"]),
                                 (True, "true", "-1", "combo", True))
                self.assertEqual((drawn["role"], drawn["popup"], drawn["expanded"], drawn["controls"], drawn["boxId"],
                                  drawn["boxTab"]),
                                 ("combobox", "listbox", "false", name + "-list", name + "-box", "0"))
                self.assertEqual((drawn["listId"], drawn["listRole"], drawn["listHidden"], drawn["listTab"],
                                  drawn["listLabel"]),
                                 (name + "-list", "listbox", True, "-1", name + "-label"))
                # The card holds one thing, what scrolls inside its padding, and it says nothing of its own:
                # its options are the listbox's.
                self.assertEqual(drawn["scroll"], [1, "combo-scroll", "none"])
                # The setting's name names both, and is not a label for the hidden select.
                self.assertEqual(drawn["label"], "label")
                self.assertTrue(drawn["labelText"])
                self.assertIsNone(drawn["labelFor"])
                self.assertTrue(drawn["options"])
                for index, (option_id, role, selected, text, native, current) in enumerate(drawn["options"]):
                    self.assertEqual((option_id, role, text), ("%s-option-%d" % (name, index), "option", native))
                    self.assertEqual(selected, "true" if current else "false")
                self.assertEqual([o[2] for o in drawn["options"]].count("true"), 1)
                self.assertEqual(drawn["shown"], next(o[3] for o in drawn["options"] if o[2] == "true"))

    def test_the_setting_name_names_the_field_and_a_press_on_it_focuses_it(self):
        observed = page("""
          var p = parts('car-theme');
          var label = byId(p.box.getAttribute('aria-labelledby'));
          var help = byId(p.box.getAttribute('aria-describedby'));
          document.activeElement = null;
          label.fire('click');
          """ + say("{label: label.textContent, help: help.textContent, cls: help.className,"
                    " focused: document.activeElement === p.box, expanded: p.box.getAttribute('aria-expanded'),"
                    " preview: parts('car-preview-reason').box.getAttribute('aria-describedby')}"))
        self.assertEqual(observed["label"], ENGLISH["field.theme"])
        self.assertEqual((observed["help"], observed["cls"]), (ENGLISH["help.theme"], "help"))
        self.assertEqual((observed["focused"], observed["expanded"]), (True, "false"))
        # A row with no help describes nothing.
        self.assertIsNone(observed["preview"])

    def test_without_a_host_the_field_cannot_be_reached_or_opened(self):
        observed = page("""window.openai = undefined; HOST = null; render();
          var p = parts('car-theme');
          send(p.box, 'click');
          var down = key(p.box, 'ArrowDown');
          key(p.box, 'd');
          """ + say("{look: look('car-theme'), disabled: p.box.getAttribute('aria-disabled'),"
                    " tab: p.box.getAttribute('tabindex'), prevented: down.defaultPrevented,"
                    " all: ROOT_NODE.all(function (n) { return n.getAttribute('role') === 'combobox'; })"
                    ".map(function (n) { return n.getAttribute('aria-disabled'); })}"))
        self.assertEqual((observed["look"]["expanded"], observed["look"]["hidden"]), ("false", True))
        self.assertEqual((observed["disabled"], observed["tab"], observed["prevented"]), ("true", None, False))
        self.assertTrue(observed["all"])
        self.assertEqual(set(observed["all"]), {"true"})

    def test_every_select_the_page_makes_is_given_the_list(self):
        """Not two of them, but each one there is: a select the page makes and does not hand to combo() opens the
        browser's own list, which is the one thing this whole control exists to stop. Read by name rather than by
        count so a third drop-down is covered the day it is written ("선택창 같은 거 ... 전역으로 설정")."""
        script = mcpui._SCRIPT
        made = re.findall(r"var (\w+) = document\.createElement\('select'\);", script)
        self.assertTrue(made, "no select is made; has the panel changed shape?")
        for name in made:
            with self.subTest(name):
                self.assertIn("combo(%s)" % name, script, "this select would open the browser's list")


# ---------------------------------------------------------------------------------- keyboard
@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ComboKeyboardTests(unittest.TestCase):
    def run_keys(self, steps, data=None):
        """Press each key on the interface-language field and look after each one."""
        body = "var p = parts('%s'); document.activeElement = p.box; var seen = [];\n" % LANG
        for step in steps:
            name, props = (step, {}) if isinstance(step, str) else step
            body += ("var e = key(p.box, %s, %s); seen.push(Object.assign(look('%s'), "
                     "{prevented: e.defaultPrevented, stopped: e.stopped}));\n"
                     % (json.dumps(name), json.dumps(props), LANG))
        return page(body + say("seen"), data=data)

    def test_closed_keys_open_the_list_where_the_pattern_says(self):
        last = len(LANGS) - 1
        for keys, active in ((["ArrowDown"], 0), (["ArrowUp"], 0), (["Enter"], 0), ([" "], 0), (["F4"], 0),
                             ([("ArrowDown", {"altKey": True})], 0), ([("ArrowUp", {"altKey": True})], 0),
                             (["Home"], 0), (["End"], last), (["PageDown"], min(PAGE, last)), (["PageUp"], 0)):
            with self.subTest(keys):
                seen = self.run_keys(keys)[-1]
                self.assertEqual((seen["expanded"], seen["hidden"], seen["active"], seen["keys"], seen["prevented"]),
                                 ("true", False, "%s-option-%d" % (LANG, active), True, True))
                # Opening changes nothing.
                self.assertEqual((seen["value"], seen["selected"]), ("system", 0))

    def test_it_opens_on_the_current_value(self):
        seen = self.run_keys(["ArrowDown"], data=snapshot(interface_language="de"))[-1]
        self.assertEqual(seen["active"], "%s-option-%d" % (LANG, LANGS.index("de")))

    def test_open_keys_move_and_hold_at_the_ends(self):
        last = len(LANGS) - 1
        seen = self.run_keys(["ArrowDown", "ArrowUp", "ArrowDown", "ArrowDown", "End", "ArrowDown", "Home",
                              "PageDown", "PageUp", "PageDown", "ArrowUp"])
        self.assertEqual([s["active"] for s in seen[1:]],
                         ["%s-option-%d" % (LANG, index) for index in
                          (0, 1, 2, last, last, 0, min(PAGE, last), 0, min(PAGE, last), min(PAGE, last) - 1)])
        for s in seen:
            self.assertEqual((s["expanded"], s["value"], s["focused"], s["prevented"]), ("true", "system", True, True))

    def test_left_and_right_do_nothing_while_it_is_open(self):
        # As in the window, where the list swallows them.
        seen = self.run_keys(["ArrowDown", "ArrowDown", "ArrowRight", "ArrowLeft"])
        for s in seen[2:]:
            self.assertEqual((s["expanded"], s["active"], s["value"], s["prevented"]),
                             ("true", "%s-option-1" % LANG, "system", True))
        # Closed, they are not the list's.
        self.assertEqual(self.run_keys(["ArrowRight"])[-1]["prevented"], False)

    def test_enter_space_f4_and_alt_arrows_pick_and_close(self):
        # Enter, Space, F4, Alt+Up and Alt+Down all take the item the keyboard is on, as the window's do.
        for pick, props in (("Enter", {}), (" ", {}), ("F4", {}), ("ArrowUp", {"altKey": True}),
                            ("ArrowDown", {"altKey": True})):
            with self.subTest(pick):
                seen = self.run_keys(["ArrowDown", "ArrowDown", "ArrowDown", (pick, props)])[-1]
                self.assertEqual((seen["expanded"], seen["hidden"], seen["active"], seen["value"], seen["selected"],
                                  seen["shown"], seen["focused"], seen["keys"], seen["prevented"]),
                                 ("false", True, None, LANGS[2], 2, l10n.ENDONYMS[LANGS[2]], True, False, True))

    def test_f4_opens_and_takes_as_in_the_window_and_alt_f4_is_left_alone(self):
        seen = self.run_keys(["F4", "ArrowDown", "F4", ("F4", {"altKey": True})])
        self.assertEqual((seen[0]["expanded"], seen[0]["active"], seen[0]["keys"], seen[0]["prevented"]),
                         ("true", "%s-option-0" % LANG, True, True))
        self.assertEqual((seen[2]["expanded"], seen[2]["value"], seen[2]["prevented"]), ("false", LANGS[1], True))
        # Alt+F4 closes the window it is in; the list never takes it.
        self.assertEqual((seen[3]["expanded"], seen[3]["prevented"]), ("false", False))
        opened = self.run_keys(["ArrowDown", ("F4", {"altKey": True})])[-1]
        self.assertEqual((opened["expanded"], opened["value"], opened["prevented"]), ("true", "system", False))

    def test_escape_closes_and_changes_nothing(self):
        seen = self.run_keys(["ArrowDown", "End", "Escape", "Escape"])
        self.assertEqual((seen[2]["expanded"], seen[2]["hidden"], seen[2]["active"], seen[2]["value"],
                          seen[2]["prevented"], seen[2]["stopped"]),
                         ("false", True, None, "system", True, True))
        # Closed, Escape is not the list's: it is left for the page and the host.
        self.assertEqual((seen[3]["prevented"], seen[3]["stopped"]), (False, False))

    def test_tab_picks_and_lets_focus_move_on(self):
        seen = self.run_keys(["ArrowDown", "ArrowDown", "Tab", "Tab"])
        self.assertEqual((seen[2]["expanded"], seen[2]["value"], seen[2]["prevented"]), ("false", LANGS[1], False))
        # Closed, Tab only moves on.
        self.assertEqual((seen[3]["value"], seen[3]["prevented"]), (LANGS[1], False))

    def test_letters_find_by_the_start_of_a_name(self):
        position = {code: index for index, code in enumerate(LANGS)}
        pause = TYPING_MS + 100
        seen = self.run_keys([
            "d",                                 # opens on Deutsch
            ("e", {"wait": 200}),                # "de": still Deutsch
            ("e", {"wait": pause}),              # after a pause, a new search: English
            ("e", {"wait": 100}),                # the same letter again: the next that begins with it
            ("e", {"wait": 100}),                # and round to the start
            ("x", {"wait": pause}),              # nothing begins with it: the keyboard stays where it was
            ("S", {"wait": pause}),              # letters match whatever their case
            "y", "s", "t", "e", "m",             # "system"
            " ",                                 # a space inside a search is a letter: "system ("...
            (" ", {"wait": pause}),              # ...and outside one it picks
        ])
        names = [s["active"] for s in seen]
        expected = ([position["de"], position["de"], position["en"], position["es"], position["en"], position["en"]]
                    + [position["system"]] * 7)
        self.assertEqual(names[:-1], ["%s-option-%d" % (LANG, i) for i in expected])
        for s in seen[:-1]:
            self.assertEqual((s["expanded"], s["prevented"], s["keys"], s["value"]), ("true", True, True, "system"))
        self.assertEqual((seen[-1]["expanded"], seen[-1]["value"], seen[-1]["prevented"]), ("false", "system", True))

    def type_word(self, locale, start, word, wait=100):
        """Type `word` on the Preview-for field, which holds reason `start`, a key every `wait` ms: where
        the keyboard is after each letter, by index."""
        body = ("var p = parts('car-preview-reason'); p.select.value = %s; p.select.fire('change');"
                " document.activeElement = p.box; var seen = [];\n" % json.dumps(start))
        for letter in word:
            body += ("key(p.box, %s, {wait: %d}); seen.push(p.options.map(function (o) { return o.id; })"
                     ".indexOf(p.box.getAttribute('aria-activedescendant')));\n" % (json.dumps(letter), wait))
        return page(body + say("seen"), locale=locale, data=snapshot(interface_language=locale))

    def test_a_longer_search_keeps_the_item_it_is_on_as_the_windows_does(self):
        # Two reasons share the start of their names in French, Spanish and Portuguese. Typing the word goes
        # to the first and stays there; it used to swap between the two on every letter.
        reasons = snapshot()["reasons"]
        for locale, word in (("fr", "limite"), ("es", "problema"), ("pt-BR", "limite"), ("en", "rate")):
            with self.subTest(locale):
                catalog = l10n.catalog(locale)
                texts = [catalog.get("reason." + reason, reason) for reason in reasons]
                start = reasons.index("server_5xx")
                seen = self.type_word(locale, reasons[start], word)
                expected, at = [], start
                for length in range(1, len(word) + 1):
                    found = window_find(texts, word[:length], at)
                    at = found if found >= 0 else at
                    expected.append(at)
                self.assertEqual(seen, expected)
                # One item, the whole way: the word's.
                self.assertEqual(len(set(seen)), 1)
                self.assertTrue(texts[seen[-1]].lower().startswith(word))

    def test_letters_are_one_search_for_the_windows_second(self):
        # "t", then "i" a moment later: "ti", still Timeout. A second later "i" is a search of its own.
        reasons = snapshot()["reasons"]
        start = reasons[0]
        self.assertEqual(self.type_word("en", start, "ti", wait=TYPING_MS - 1)[-1], reasons.index("timeout"))
        self.assertEqual(self.type_word("en", start, "ti", wait=TYPING_MS)[-1], reasons.index("stream_interrupted"))

    def test_a_letter_on_a_closed_field_opens_it_and_finds(self):
        seen = self.run_keys(["f"])[-1]
        self.assertEqual((seen["expanded"], seen["active"], seen["value"]),
                         ("true", "%s-option-%d" % (LANG, LANGS.index("fr")), "system"))

    def test_keys_the_list_does_not_own_are_left_alone(self):
        seen = self.run_keys([("d", {"ctrlKey": True}), ("ArrowDown", {"metaKey": True}), "F5", "Shift",
                              ("x", {"altKey": True})])
        for s in seen:
            self.assertEqual((s["expanded"], s["prevented"]), ("false", False))


# ----------------------------------------------------------------------------------- pointer
@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ComboPointerTests(unittest.TestCase):
    def test_a_press_on_the_field_opens_it_without_the_ring_and_a_second_closes_it(self):
        observed = page("""
          var p = parts('%s');
          document.activeElement = p.box;
          send(p.box, 'click');
          var opened = look('%s');
          key(p.box, 'ArrowDown');
          var keyed = look('%s');
          send(p.box, 'click');
          """ % (LANG, LANG, LANG) + say("{opened: opened, keyed: keyed, closed: look('%s')}" % LANG))
        self.assertEqual((observed["opened"]["expanded"], observed["opened"]["keys"], observed["opened"]["active"]),
                         ("true", False, "%s-option-0" % LANG))
        # The ring appears on the item as soon as the keyboard is used.
        self.assertEqual((observed["keyed"]["keys"], observed["keyed"]["active"]), (True, "%s-option-1" % LANG))
        self.assertEqual((observed["closed"]["expanded"], observed["closed"]["value"]), ("false", "system"))

    def test_a_press_on_an_item_picks_it_and_keeps_focus_on_the_field(self):
        observed = page("""
          var p = parts('%s');
          send(p.box, 'click');
          var down = send(p.list, 'mousedown');
          document.activeElement = null;
          byId(option('%s', 2)).fire('click');
          """ % (LANG, LANG) + say("{look: look('%s'), kept: down.defaultPrevented}" % LANG))
        self.assertTrue(observed["kept"])
        self.assertEqual((observed["look"]["expanded"], observed["look"]["value"], observed["look"]["focused"]),
                         ("false", LANGS[2], True))

    def test_the_item_under_the_pointer_is_the_one_enter_takes(self):
        # As in the window: the pointer moves the keyboard's item, shown by the item rising, not by a ring.
        observed = page("""
          var p = parts('%s');
          document.activeElement = p.box;
          send(p.box, 'click');
          point(byId(option('%s', 3)));
          var hovered = look('%s');
          var enter = key(p.box, 'Enter');
          """ % (LANG, LANG, LANG) + say("{hovered: hovered, look: look('%s'), prevented: enter.defaultPrevented}" % LANG))
        self.assertEqual((observed["hovered"]["active"], observed["hovered"]["keys"], observed["hovered"]["value"]),
                         ("%s-option-3" % LANG, False, "system"))
        self.assertEqual((observed["look"]["expanded"], observed["look"]["value"], observed["prevented"]),
                         ("false", LANGS[3], True))

    def test_a_pointer_that_stood_still_leaves_the_keyboard_where_it_is(self):
        observed = page("""
          var p = parts('%s');
          document.activeElement = p.box;
          key(p.box, 'ArrowDown');
          point(byId(option('%s', 4)), {movementX: 0, movementY: 0});
          var still = look('%s');
          point(byId(option('%s', 4)), {screenX: 40, screenY: 90});
          var moved = look('%s');
          point(byId(option('%s', 6)), {screenX: 40, screenY: 90, movementX: 0, movementY: 0});
          var again = look('%s');
          key(p.box, 'ArrowDown');
          """ % ((LANG,) * 7) + say("{still: still, moved: moved, again: again, keyed: look('%s')}" % LANG))
        # A move made up for a pointer that stood still - the list appeared or scrolled under it - is not one.
        self.assertEqual((observed["still"]["active"], observed["still"]["keys"]), ("%s-option-0" % LANG, True))
        # A real one takes the keyboard's item, and the ring gives way to the raised pill.
        self.assertEqual((observed["moved"]["active"], observed["moved"]["keys"]), ("%s-option-4" % LANG, False))
        # Once the pointer leads, the item it is over leads, however it came under it - the list scrolled.
        self.assertEqual((observed["again"]["active"], observed["again"]["keys"]), ("%s-option-6" % LANG, False))
        # The keyboard takes it back from there.
        self.assertEqual((observed["keyed"]["active"], observed["keyed"]["keys"]), ("%s-option-7" % LANG, True))

    def test_losing_focus_closes_it_and_changes_nothing(self):
        observed = page("""
          var p = parts('%s');
          document.activeElement = p.box;
          key(p.box, 'ArrowDown');
          key(p.box, 'End');
          send(p.box, 'blur');
          """ % LANG + say("look('%s')" % LANG))
        self.assertEqual((observed["expanded"], observed["hidden"], observed["active"], observed["value"]),
                         ("false", True, None, "system"))

    def test_only_one_list_is_open_at_a_time(self):
        # Opening another takes focus from the first, which closes it.
        observed = page("""
          var a = parts('%s'), b = parts('car-theme');
          send(a.box, 'click');
          send(a.box, 'blur');
          send(b.box, 'click');
          """ % LANG + say("[look('%s').expanded, look('car-theme').expanded]" % LANG))
        self.assertEqual(observed, ["false", "true"])


# ------------------------------------------------------------------------------ with the page
@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ComboPageTests(unittest.TestCase):
    def test_a_pick_is_a_change_the_page_records_and_saves(self):
        observed = page("""
          var p = parts('car-theme');
          send(p.box, 'click');
          byId(option('car-theme', 2)).fire('click');
          var primary = saveButton().className;
          saveButton().onclick();
          await settle();
          """ + say("{primary: primary, draft: DRAFT, sent: CALLS.filter(function (c) { return c[0] === 'update_settings'; })"
                    ".map(function (c) { return c[1].theme; }), stamp: document.documentElement.getAttribute('data-theme')}"))
        self.assertEqual(observed["primary"], "primary")
        self.assertEqual(observed["sent"], [policy.THEMES[2]])
        self.assertEqual(observed["stamp"], policy.THEMES[2])

    def test_picking_the_current_value_is_no_change(self):
        observed = page("""
          var p = parts('car-theme');
          var changes = 0;
          p.select.addEventListener('change', function () { changes++; });
          send(p.box, 'click');
          byId(option('car-theme', 0)).fire('click');
          """ + say("{changes: changes, primary: saveButton().className, look: look('car-theme')}"))
        self.assertEqual((observed["changes"], observed["primary"], observed["look"]["expanded"]), (0, "", "false"))

    def test_a_renamed_option_is_shown_in_the_field_and_the_list(self):
        observed = page("""
          var p = parts('%s');
          document.activeElement = p.box;
          key(p.box, 'ArrowDown');
          key(p.box, 'ArrowDown');
          key(p.box, 'ArrowDown');
          key(p.box, 'Enter');
          var c = parts('car-continuation_language');
          """ % LANG + say("{shown: c.box.textContent, item: c.options[0].textContent,"
                           " native: c.select.options[0].textContent}"))
        follow = ENGLISH["choice.continuation_language.follow"].replace("{language}", l10n.ENDONYMS[LANGS[2]])
        self.assertEqual(observed, {"shown": follow, "item": follow, "native": follow})

    def test_a_preview_pick_asks_for_that_preview(self):
        observed = page("""
          var p = parts('car-preview-reason');
          CALLS.length = 0;
          send(p.box, 'click');
          byId(option('car-preview-reason', 2)).fire('click');
          await settle();
          """ + say("CALLS.filter(function (c) { return c[0] === 'preview_recovery_message'; })"
                    ".map(function (c) { return c[1].category; })"))
        self.assertEqual(observed, [snapshot()["reasons"][2]])

    def test_a_value_the_page_sets_is_shown(self):
        observed = page("""
          var p = parts('car-theme');
          p.select.value = 'dark';
          p.select.fire('change');
          """ + say("look('car-theme')"))
        self.assertEqual((observed["shown"], observed["selected"]),
                         (ENGLISH["choice.theme.dark"], policy.THEMES.index("dark")))


# --------------------------------------------------------------------------------- placement
@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ComboPlacementTests(unittest.TestCase):
    # The list laid out as the stylesheet lays it out: an item 36 tall, 4 apart, the card's hairline and
    # padding 4 and what scrolls 4 more each side - the window's 8 - so a list of n rows is 16 + 40n - 4 tall.
    LAYOUT = """
      var p = parts('%s');
      function lay(rows) {
        p.options.forEach(function (item, index) { item.offsetTop = 4 + index * 40; item.offsetHeight = 36; });
        p.scroll.clientHeight = 8 + rows * 40 - 4;
        p.scroll.scrollHeight = 8 + p.options.length * 40 - 4;
        p.list.offsetHeight = p.scroll.clientHeight + 8;
      }
    """ % LANG
    PLACE = LAYOUT + """
      function at(view, top) {
        window.innerHeight = view;
        p.box.getBoundingClientRect = function () { return {top: top, bottom: top + 35, left: 40, right: 320}; };
        p.box.offsetHeight = 35;
        p.list.offsetTop = 39;
        lay(p.options.length);
        send(p.box, 'click');
        var seen = {up: p.list.classList.contains('up'), max: p.scroll.style.maxHeight || ''};
        send(p.box, 'blur');
        return seen;
      }
    """

    def test_below_with_room_above_near_the_bottom_and_cut_to_whole_rows_with_room_on_neither_side(self):
        self.assertEqual(len(LANGS), 10)
        observed = page(self.PLACE + say("[at(1000, 500), at(600, 500), at(300, 130), at(300, 170), at(120, 40),"
                                         " at(0, 500)]"))
        self.assertEqual(observed, [
            {"up": False, "max": ""},          # 457 px under it for a card of 412: fits
            {"up": True, "max": ""},           # 57 under, 492 over: upward, whole
            {"up": False, "max": "84px"},      # 127 under, 122 over: the larger, two whole rows
            {"up": True, "max": "124px"},      # 87 under, 162 over: three whole rows
            {"up": False, "max": "44px"},      # 37 under, 32 over: never fewer than one
            {"up": False, "max": ""},          # a renderer that cannot say: below, as drawn
        ])

    def test_it_starts_a_pad_left_of_the_field_and_keeps_to_the_page_across(self):
        observed = page(self.LAYOUT + """
          function across(width, left, wide) {
            document.documentElement.clientWidth = width;
            window.innerHeight = 1000;
            p.box.getBoundingClientRect = function () { return {top: 100, bottom: 135, left: 40, right: 320}; };
            p.list.offsetLeft = -8;
            p.list.getBoundingClientRect = function () { return {top: 139, bottom: 551, left: left, right: left + wide}; };
            lay(p.options.length);
            send(p.box, 'click');
            var seen = {left: p.list.style.left || '', max: p.list.style.maxWidth || ''};
            send(p.box, 'blur');
            return seen;
          }
          """ + say("[across(700, 32, 296), across(400, 100, 380), across(400, 30, 390), across(0, 30, 390)]"))
        self.assertEqual(observed, [
            {"left": "", "max": "700px"},       # where the stylesheet puts it
            {"left": "-88px", "max": "400px"},  # 80 past the right edge: moved left by as much
            {"left": "-28px", "max": "400px"},
            {"left": "", "max": ""},            # a renderer that cannot say
        ])

    def test_the_item_the_keyboard_is_on_is_scrolled_into_the_list_by_whole_rows(self):
        observed = page(self.LAYOUT + """
          lay(2);
          p.scroll.scrollTop = 0;
          document.activeElement = p.box;
          var tops = [];
          ['ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowDown', 'End', 'Home'].forEach(function (name) {
            key(p.box, name);
            tops.push(p.scroll.scrollTop);
          });
          """ + say("tops"))
        last = len(LANGS) - 1
        # The item and its ring (the room around the items) in view, moving no further than that - which
        # is always a whole number of rows, as the window's list scrolls.
        self.assertEqual(observed, [0, 0, 40, 80, (last - 1) * 40, 0])

    def test_page_keys_move_what_shows_less_one(self):
        observed = page(self.LAYOUT + """
          document.activeElement = p.box;
          var seen = [];
          key(p.box, 'ArrowDown');
          lay(3);
          ['PageDown', 'PageDown', 'End', 'PageUp', 'PageUp', 'PageUp', 'PageUp'].forEach(function (name) {
            key(p.box, name);
            seen.push(p.options.map(function (o) { return o.id; }).indexOf(p.box.getAttribute('aria-activedescendant')));
          });
          """ + say("seen"))
        last = len(LANGS) - 1
        self.assertEqual(observed, [2, 4, last, last - 2, last - 4, last - 6, max(0, last - 8)])


# -------------------------------------------------------------------------------- the stylesheet
def transitions():
    """Every rule outside an at-rule that declares a transition, with its timing function.

    Not the rules that stop every transition: since v0.6.10 a design that does not glide, and the product's
    own Reduce motion, say `transition: none !important` from the root's stamp, as the reduced-motion and
    High Contrast blocks do from inside theirs - they time nothing (stopping_rules, held below)."""
    return [(selectors, declarations) for where, selectors, declarations in RULES
            if where == "" and "transition" in declarations and declarations["transition"] != "none !important"]


def stopping_rules():
    """The rules outside an at-rule that stop every transition: each only under Reduce motion's stamp."""
    return [(selectors, declarations) for where, selectors, declarations in RULES
            if where == "" and declarations.get("transition") == "none !important"]


class ComboStyleTests(unittest.TestCase):
    def test_the_field_is_the_well_a_value_sits_in(self):
        for prop, value in (("min-height", "var(--size-field-height)"), ("padding", "var(--size-select-pad)"),
                            ("background-color", "var(--inset)"), ("border", "1px solid var(--line)"),
                            ("border-radius", "var(--radius-control)"), ("box-shadow", "var(--elev-inset)"),
                            ("color", "var(--ink)")):
            with self.subTest(prop):
                self.assertEqual(declared(".combo-box", prop), value)
        disabled = '.combo-box[aria-disabled="true"]'
        self.assertEqual((declared(disabled, "background-color"), declared(disabled, "color"),
                          declared(disabled, "box-shadow"), declared(disabled, "opacity")),
                         ("var(--surface)", "var(--muted)", "none", "1"))
        self.assertEqual(declared(".combo-value", "text-overflow"), "ellipsis")

    def test_the_wedge_is_brands(self):
        wedge = ".combo-box::after"
        self.assertEqual(declared(wedge, "right"), "var(--size-chevron-right)")
        self.assertEqual(declared(wedge, "width"), "var(--size-chevron-width)")
        self.assertEqual(declared(wedge, "height"), "var(--size-chevron-height)")
        self.assertEqual(declared(wedge, "background"), "var(--muted)")
        self.assertEqual(declared(wedge, "clip-path"), "polygon(0 0, 100% 0, 50% 100%)")
        for name in ("chevron_right", "chevron_width", "chevron_height"):
            self.assertEqual(ROOT_TOKENS["--size-" + name.replace("_", "-")], "%dpx" % brand.LAYOUT[name])

    def test_the_list_is_a_card_floating_over_the_page(self):
        card = ".combo-list"
        self.assertEqual(declared(card, "background"), "var(--surface)")
        self.assertEqual(declared(card, "background", SUPPORTS_MIX), "var(--card-ground)")
        self.assertEqual(declared(card, "border"), "1px solid var(--line)")
        self.assertEqual(declared(card, "border-radius"), "var(--radius-card)")
        self.assertEqual(declared(card, "box-shadow"), "var(--elev-card)")
        self.assertEqual(declared(card, "position"), "absolute")
        # Over the save card, which is sticky over everything else.
        self.assertGreater(int(declared(card, "z-index")), int(declared(".savebar", "z-index")))
        self.assertEqual(declared(card, "top"), "calc(100% + var(--space-xs))")
        self.assertEqual((declared(".combo-list.up", "top"), declared(".combo-list.up", "bottom")),
                         ("auto", "calc(100% + var(--space-xs))"))
        self.assertEqual(declared(".combo-scroll", "overscroll-behavior"), "contain")
        self.assertEqual(declared(".combo", "position"), "relative")

    def test_no_native_list_can_open(self):
        # The select is hidden by the `hidden` attribute, which nothing on the page can undo.
        self.assertEqual(declared("[hidden]", "display"), "none !important")
        self.assertNotIn("appearance: auto", mcpui._STYLE)
        for where, selectors, declarations in RULES:
            for selector in selectors:
                self.assertFalse(re.match(r"(^|[\s,>+~])select\b", selector) and "display" in declarations, selector)

# ------------------------------------------------------------------ the window's list, and this one
def resolved(value: str) -> float:
    """A length of the list's own stylesheet in px: brand's tokens, the list's own names, and calc()."""
    names = {name: declared(".combo", name) for name in ("--combo-line", "--combo-words", "--combo-pill")}
    while "var(" in value:
        value = re.sub(r"var\((--[a-z0-9-]+)\)",
                       lambda m: "(%s)" % (names.get(m.group(1)) or ROOT_TOKENS[m.group(1)]), value)
    value = value.replace("calc", "").replace("px", "")
    assert re.fullmatch(r"[\d\s.()+*/-]+", value), value
    return float(eval(value))  # noqa: S307 - digits and arithmetic only, checked above


def sides(value: str):
    """A padding written in one or two lengths, as (top, right, bottom, left) in px."""
    parts, depth, word = [], 0, ""
    for character in value.strip() + " ":
        depth += {"(": 1, ")": -1}.get(character, 0)
        if character == " " and depth == 0:
            if word:
                parts.append(word)
            word = ""
        else:
            word += character
    across = parts[1] if len(parts) > 1 else parts[0]
    return (resolved(parts[0]), resolved(across), resolved(parts[0]), resolved(across))


class OneListTests(unittest.TestCase):
    """The drop-down list is one design on both surfaces: the panel's is drawn by the numbers the
    Windows Dashboard's SoftDropList is drawn by (gui/SoftCombo.cs, read through guiscan), each on its own
    surface's type - the window's field is set in the system's message font, this one's in the panel's."""

    PAD = brand.SPACING["s"]
    GAP = brand.SPACING["xs"]
    HAIRLINE = brand.LAYOUT["hairline"]

    def test_the_window_builds_its_list_from_these_numbers(self):
        for source in (r"pad = Soft\.Px\(Brand\.SpaceS\);", r"rowGap = Soft\.Px\(Brand\.SpaceXs\);",
                       r"pill = TextRenderer\.MeasureText\(\"Ag\", font, unbounded, Flags\)\.Height"
                       r" \+ 2 \* Soft\.Px\(Brand\.SpaceS\);",
                       # v0.6.10: the design's small radius (Palette), as the panel's list takes its design's.
                       r"float radius = Soft\.PxF\(Palette\.RadiusSmall\);\s+int words = Soft\.Px\(Brand\.SelectPadLeft\);",
                       r"field\.X - pad", r"MaxDropDownItems = %d;" % ROWS, r"const int TypeAhead = %d;" % TYPING_MS):
            with self.subTest(source):
                self.assertRegex(CONTROLS, source)

    def test_the_card_holds_its_items_a_pad_in_from_its_edge(self):
        # The window's pad, SPACING s: the card's hairline and its padding, then the room around the items
        # inside what scrolls - the room the keyboard's ring is drawn in, so a scrolling list never cuts it.
        card = sides(declared(".combo-list", "padding"))
        room = sides(declared(".combo-scroll", "padding"))
        for side in range(4):
            self.assertEqual(self.HAIRLINE + card[side] + room[side], self.PAD)
        self.assertLessEqual(brand.LAYOUT["focus_width"] + brand.LAYOUT["focus_offset"], room[0])
        # Items SPACING xs apart, and the card SPACING xs from the field, above or below.
        self.assertEqual(declared(".combo-scroll", "gap"), "var(--space-xs)")
        self.assertEqual(resolved(declared(".combo-scroll", "gap")), self.GAP)

    def test_its_words_start_under_the_fields(self):
        # The card is a pad left of the field and at least a pad wider on each side, so each pill's left
        # edge is the field's and its words start where the field's do (SelectPadLeft, past a hairline).
        self.assertEqual(declared(".combo-list", "left"), "calc(-1 * var(--space-s))")
        self.assertEqual(declared(".combo-list", "min-width"), "calc(100% + 2 * var(--space-s))")
        self.assertEqual(declared(".combo-list", "width"), "max-content")
        self.assertEqual(resolved(declared(".combo-list", "left")) + self.PAD, 0)
        field = brand.padding("select_pad")
        item = sides(declared(".combo-option", "padding"))
        self.assertEqual((item[1], item[3]), (field[3], field[3]))
        self.assertEqual(declared(".combo-option", "border"), "1px solid transparent")
        # One line, cut short with an ellipsis where the page is too narrow for it, as the window's are.
        self.assertEqual((declared(".combo-option", "white-space"), declared(".combo-option", "text-overflow")),
                         ("nowrap", "ellipsis"))

    def test_an_item_is_the_fields_line_and_a_pad_above_and_below(self):
        # The window's pill: its field's line, and SPACING s above and below it - on each surface, that
        # surface's line. The field and its items share theirs here.
        line = declared(".combo", "--combo-line")
        self.assertEqual((declared(".combo-box", "line-height"), declared(".combo-option", "line-height")),
                         ("var(--combo-line)", "var(--combo-line)"))
        item = sides(declared(".combo-option", "padding"))
        height = resolved(line) + item[0] + item[2] + 2 * self.HAIRLINE
        self.assertEqual(height, resolved(line) + 2 * self.PAD)
        self.assertEqual(resolved(declared(".combo", "--combo-pill")), height)
        # The line every control on the page has, and the field is still the field's height.
        self.assertEqual(resolved(line), 20)
        self.assertLessEqual(resolved(line) + sum(brand.padding("select_pad")[0::2]) + 2 * self.HAIRLINE,
                             brand.LAYOUT["field_height"])
        self.assertEqual(declared(".combo-option", "border-radius"), "var(--radius-small)")

    def test_items_are_pills_raised_under_the_pointer_and_sunken_when_current(self):
        item, current = ".combo-option", '.combo-option[aria-selected="true"]'
        # Under the pointer, as in the window, only while the pointer leads - not over the item that is
        # current, which stays sunken, and not while the keyboard's ring shows.
        hover = '.combo-list:not(.keys) .combo-option:not([aria-selected="true"]):hover'
        self.assertEqual((declared(hover, "background"), declared(hover, "border-color"), declared(hover, "box-shadow")),
                         ("var(--raised)", "var(--line)", "var(--elev-control)"))
        self.assertEqual((declared(current, "background"), declared(current, "box-shadow"),
                          declared(current, "color")), ("var(--inset)", "var(--elev-inset)", "var(--accent)"))
        # Set as the field is set - the window's items are its drop-down's own font - the current value
        # said by its well and its colour, not by a heavier weight.
        for selector in (item, current, hover):
            self.assertIsNone(declared(selector, "font-weight"), selector)
        self.assertNotIn(".combo-option:hover", mcpui._STYLE)
        # The segmented control's pill is the same stuff.
        self.assertEqual(declared(".segment input:checked + span", "box-shadow"), declared(current, "box-shadow"))

    def test_the_keyboard_ring_is_every_controls(self):
        ring = ".combo-list.keys .combo-option.active"
        self.assertIn(":focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }", mcpui._STYLE)
        self.assertEqual((declared(ring, "outline"), declared(ring, "outline-offset")),
                         ("2px solid var(--focus)", "2px"))
        self.assertEqual((brand.LAYOUT["focus_width"], brand.LAYOUT["focus_offset"]), (2, 2))
        # The field gives its own ring up while its list is open.
        self.assertEqual(declared('.combo-box[aria-expanded="true"]', "outline"), "none")

    def test_it_shows_twelve_whole_rows_and_scrolls_by_whole_rows(self):
        self.assertIn("var COMBO_ROWS = %d;" % ROWS, mcpui._SCRIPT)
        self.assertEqual(declared(".combo-scroll", "max-height"),
                         "calc(2 * var(--space-xs) + %d * var(--combo-pill) + %d * var(--space-xs))" % (ROWS, ROWS - 1))
        # Every list the panel has shows whole: the longest, the Interface language, has ten choices.
        self.assertLessEqual(len(LANGS), ROWS)
        # What scrolls stops inside the card's padding, never at its edge, and settles on whole rows.
        self.assertEqual(declared(".combo-scroll", "overflow-y"), "auto")
        self.assertIsNone(declared(".combo-list", "overflow-y"))
        self.assertEqual((declared(".combo-scroll", "scroll-snap-type"), declared(".combo-scroll", "scroll-padding"),
                          declared(".combo-option", "scroll-snap-align")), ("y mandatory", "var(--space-xs) 0", "start"))

    def test_the_bar_it_scrolls_on_is_the_windows_soft_bar(self):
        # SoftBar: a well 12 across, a pad from its ends and SPACING xs from its side, and a raised pill 2
        # inside it, never shorter than 32. Since v0.6.6 the rules are the panel's, not one list's: any
        # overflow anywhere gets them, on either axis.
        self.assertEqual(declared("::-webkit-scrollbar", "width"), "var(--space-m)")
        self.assertEqual(declared("::-webkit-scrollbar", "height"), "var(--space-m)")
        self.assertEqual(resolved(declared("::-webkit-scrollbar", "width")), 12)
        self.assertRegex(CONTROLS, r"const int TrackWidth = 12;")
        self.assertEqual(declared("::-webkit-scrollbar-track:horizontal", "margin"), "0 var(--space-xs)")
        self.assertEqual(declared("::-webkit-scrollbar-corner", "background"), "var(--inset)")
        self.assertEqual(declared("::-webkit-scrollbar-thumb", "min-width"), "var(--space-xxl)")
        for selector in (".combo-scroll::-webkit-scrollbar", ".combo-scroll::-webkit-scrollbar-track",
                         ".combo-scroll::-webkit-scrollbar-thumb"):
            self.assertIsNone(declared(selector, "width"), "one list's own bar is gone: every bar is the same")
        track, thumb = "::-webkit-scrollbar-track", "::-webkit-scrollbar-thumb"
        self.assertEqual((declared(track, "margin"), declared(track, "background"), declared(track, "border"),
                          declared(track, "border-radius")),
                         ("var(--space-xs) 0", "var(--inset)", "1px solid var(--line)", "999px"))
        self.assertEqual((declared(thumb, "background"), declared(thumb, "background-clip"), declared(thumb, "border"),
                          declared(thumb, "box-shadow"), declared(thumb, "min-height")),
                         ("var(--raised)", "padding-box", "2px solid transparent", "inset 0 0 0 1px var(--line)",
                          "var(--space-xxl)"))
        self.assertRegex(CONTROLS, r"const int ThumbInset = 2;")
        self.assertRegex(CONTROLS, r"const int MinThumb = 32;")
        self.assertEqual(resolved(declared(thumb, "min-height")), 32)

    def test_it_rises_into_place_on_the_one_curve(self):
        self.assertEqual(declared(".combo-list", "animation"), "combo-rise var(--transition) var(--transition-ease)")
        rise = [declarations for where, selectors, declarations in RULES if where == "@keyframes combo-rise"]
        self.assertEqual(rise, [{"opacity": "0", "transform": "translateY(var(--space-xs))"}])
        # Less motion and High Contrast: the page-wide rules take every animation off, this one included,
        # as the window's list simply appears in both.
        self.assertEqual(declared("*", "animation", REDUCED), "none !important")
        self.assertEqual(declared("*", "animation", FORCED), "none !important")

    def test_high_contrast_draws_it_in_system_colours_and_no_shadow(self):
        for selector in (".combo-box", ".combo-list", ".combo-option"):
            self.assertEqual(declared(selector, "box-shadow", FORCED), "none", selector)
        self.assertEqual((declared(".combo-box::after", "forced-color-adjust", FORCED),
                          declared(".combo-box::after", "background", FORCED)), ("none", "CanvasText"))
        self.assertEqual(declared('.combo-box[aria-disabled="true"]::after', "background", FORCED), "GrayText")
        self.assertEqual(declared('.combo-box[aria-disabled="true"]', "color", FORCED), "GrayText")
        item, current = ".combo-option", '.combo-option[aria-selected="true"]'
        hover = '.combo-list:not(.keys) .combo-option:not([aria-selected="true"]):hover'
        self.assertEqual((declared(item, "forced-color-adjust", FORCED), declared(item, "background", FORCED),
                          declared(item, "color", FORCED)), ("none", "Canvas", "CanvasText"))
        # Having opted out, nothing of the palette may be left on it in any state.
        self.assertEqual((declared(hover, "background", FORCED), declared(hover, "border-color", FORCED),
                          declared(hover, "box-shadow", FORCED)), ("Canvas", "Highlight", "none"))
        self.assertEqual((declared(current, "background", FORCED), declared(current, "color", FORCED),
                          declared(current, "box-shadow", FORCED)), ("Highlight", "HighlightText", "none"))
        self.assertEqual(declared(".combo-list.keys .combo-option.active", "outline-color", FORCED), "Highlight")


class MotionStyleTests(unittest.TestCase):
    def test_one_curve_brands_ease_out(self):
        # Brand's, emitted with the scale; the panel names it and never writes a curve of its own.
        self.assertEqual(ROOT_TOKENS["--transition-ease"], brand.css_ease())
        self.assertEqual(ROOT_TOKENS["--transition"], "%dms" % brand.MOTION["transition_ms"])
        source = (ROOT / "src" / "codex_auto_resume" / "mcp" / "panel.py").read_text(encoding="utf-8")
        self.assertNotIn("--transition-ease:", source)
        self.assertNotIn("--transition:", source)
        # One file of the package writes either token - `brand/css.py`, which is the one file
        # of the palette that writes CSS at all - so the panel's style cannot move to a module
        # of its own and start writing a curve there.
        for token in ("--transition-ease:", "--transition:"):
            self.assertEqual(srcscan.holders(token), {"codex_auto_resume/brand/css.py"}, token)
        # An ease-out: it leaves at once and settles, and it is the path brand.ease() gives the
        # window and the popup.
        for step in range(101):
            progress = step / 100
            eased = cubic_bezier(ROOT_TOKENS["--transition-ease"], progress)
            self.assertAlmostEqual(eased, brand.ease(progress), delta=0.002)
            self.assertAlmostEqual(eased, 1 - (1 - progress) ** 3, delta=0.003)

    def test_every_transition_is_brands_time_on_the_one_curve(self):
        found = transitions()
        self.assertGreater(len(found), 8)
        for selectors, declarations in found:
            with self.subTest(selectors):
                parts = [part.strip() for part in re.split(r",(?![^(]*\))", declarations["transition"])]
                for part in parts:
                    self.assertRegex(part, r"^[a-z-]+ var\(--transition\)( var\(--transition-ease\))?$")
                on_curve = [part.endswith("var(--transition-ease)") for part in parts]
                if not all(on_curve):
                    self.assertFalse(any(on_curve))
                    self.assertEqual(declarations.get("transition-timing-function"), "var(--transition-ease)")
        # No other curve anywhere a transition or an animation is timed - except the status light's, whose
        # curve is in its keyframes since v0.6.6 (sampled from brand.glow_phase every 2.5% of the cycle), so
        # what lies between two of them is walked straight rather than eased a second time; and the checking
        # arc's turn, which is even all the way round, as the window and the popup turn it (v0.6.10). Each starts
        # where the script puts the page's one phase (--light-delay, v0.6.10).
        for where, selectors, declarations in RULES:
            for prop in ("transition", "transition-timing-function", "animation", "animation-timing-function"):
                value = declarations.get(prop, "")
                if value.startswith(("glow-dot ", "glow-spread ", "glow-arc ")):
                    with self.subTest(selectors=selectors, prop=prop):
                        self.assertRegex(value, r"^glow-(dot|spread|arc) var\(--glow-[a-z]+-ms\) linear "
                                                r"var\(--light-delay\) (infinite|1)$")
                    continue
                with self.subTest(selectors=selectors, prop=prop):
                    self.assertNotRegex(value, r"(?<![-\w])(ease|ease-in|ease-out|ease-in-out|linear|step-start"
                                               r"|step-end)(?![-\w])|steps\(|cubic-bezier\(")

    def test_a_switch_glides_its_knob_and_cross_fades_its_track(self):
        self.assertEqual(declared("input.switch::before", "transition"),
                         "transform var(--transition), background-color var(--transition)")
        self.assertEqual(declared("input.switch", "transition"),
                         "background-color var(--transition), border-color var(--transition), box-shadow var(--transition)")
        self.assertEqual(declared("input.switch:checked::before", "transform"), "translateX(var(--size-knob-travel))")
        # The well goes as the accent comes: the track loses its inset shadow when checked.
        self.assertEqual((declared("input.switch", "box-shadow"), declared("input.switch:checked", "box-shadow")),
                         ("var(--elev-inset)", "none"))
        self.assertEqual(ROOT_TOKENS["--size-knob-travel"], "%dpx" % brand.LAYOUT["knob_travel"])

    def test_a_check_box_fades_its_fill_and_its_mark(self):
        self.assertEqual(declared("input.check", "transition"),
                         "background-color var(--transition), border-color var(--transition), box-shadow var(--transition)")
        self.assertEqual(declared("input.check::before", "transition"),
                         "opacity var(--transition), visibility var(--transition), background-color var(--transition)")
        self.assertEqual((declared("input.check::before", "opacity"), declared("input.check::before", "visibility")),
                         ("0", "hidden"))
        self.assertEqual((declared("input.check:checked::before", "opacity"),
                          declared("input.check:checked::before", "visibility")), ("1", "visible"))

    def test_nothing_moves_in_high_contrast_or_with_less_motion(self):
        # High Contrast is less motion too, as the window has it (Soft.ReduceMotion): a switch, a check box,
        # a list and its items - everything on the page simply changes, with or without Windows' animations.
        self.assertRegex(CONTROLS, r"Palette\.Contrast")
        for context in (FORCED, REDUCED):
            for selector in ("*", "*::before", "*::after"):
                with self.subTest(context=context, selector=selector):
                    self.assertEqual(declared(selector, "transition", context), "none !important")
                    self.assertEqual(declared(selector, "animation", context), "none !important")
        # Nothing in either says otherwise for one control.
        for where, selectors, declarations in RULES:
            if where in (FORCED, REDUCED) and selectors != ("*", "*::before", "*::after"):
                for prop in ("transition", "animation"):
                    with self.subTest(where=where, selectors=selectors, prop=prop):
                        self.assertNotIn(prop, declarations)

    def test_the_motion_is_paint_only(self):
        # What moves is a transform, an opacity and colours - never a size or a place.
        for selectors, declarations in transitions():
            for part in re.split(r",(?![^(]*\))", declarations["transition"]):
                prop = part.split()[0]
                with self.subTest(selectors=selectors, prop=prop):
                    self.assertIn(prop, {"transform", "opacity", "visibility", "background-color", "border-color",
                                         "box-shadow", "color"})

    def test_a_rule_that_stops_every_transition_stands_only_under_reduce_motions_stamp(self):
        """v0.6.10: outside the reduced-motion and High Contrast blocks, `transition: none` is said only for the
        product's own Reduce motion - never for the page as a whole, and since v0.6.11 never for a design: v0.6.10's
        Still, the one that did not glide, is Reduce motion now."""
        found = stopping_rules()
        self.assertEqual(len(found), 1)
        for selectors, _ in found:
            for selector in selectors:
                with self.subTest(selector):
                    self.assertRegex(selector, r'^:root\[data-motion="reduced"\] ')


# ----------------------------------------------------------------------- a switch that asks first
@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ConfirmedSwitchTests(unittest.TestCase):
    """A conversation's switch changes only when a tool has said so, and its answer comes with a
    redraw. The new switch is drawn where the old one was and moved after one style flush, so it
    glides; a press never moves it first."""

    WATCH = r"""
      // Each time the page is styled - its one flush before a switch moves - what every pending
      // row's switch shows at that moment.
      var FLUSHES = [];
      function switches() {
        return ROOT_NODE.all(function (n) { return n.className === 'switch' && n.parentNode.className === 'prow-switch'; });
      }
      Object.defineProperty(El.prototype, 'offsetWidth', {configurable: true, get: function () {
        FLUSHES.push(switches().map(function (n) { return n.checked; }));
        return 0;
      }});
      var ANSWER = null;
      HOST.callTool = function (name, args) {
        CALLS.push([name, args]);
        if (name === 'disable_conversation_recovery' || name === 'enable_conversation_recovery') {
          return new Promise(function (resolve, reject) { ANSWER = {resolve: resolve, reject: reject, args: args, name: name}; });
        }
        if (name === 'list_pending') return Promise.reject(new Error('not now'));
        return new Promise(function () {});
      };
      function press(input) { input.checked = !input.checked; input.fire('change'); }
      function states() { return switches().map(function (n) { return n.checked; }); }
    """

    def row(self, enabled):
        data = snapshot()
        data["pending"][0]["thread_enabled"] = enabled
        return data

    def test_a_press_on_a_switch_that_asks_first_does_not_move_it(self):
        observed = page(self.WATCH + """
          var first = switches()[0];
          press(first);
          """ + say("{old: first.checked, now: states(), confirm: ROOT_NODE.all(function (n) {"
                    " return n.className === 'prow-confirm'; }).length, flushes: FLUSHES}"))
        self.assertEqual(observed, {"old": True, "now": [True], "confirm": 1, "flushes": []})

    def test_it_glides_only_once_the_tool_confirms(self):
        observed = page(self.WATCH + """
          press(switches()[0]);
          var off = ROOT_NODE.all(function (n) { return n.tagName === 'button' && n.className === 'danger'; })[0];
          off.onclick();
          await settle();
          var asking = {now: states(), flushes: FLUSHES.slice()};
          ANSWER.resolve({structuredContent: {thread_id: ANSWER.args.thread_id}});
          await settle();
          """ + say("{asking: asking, now: states(), flushes: FLUSHES}"))
        # While the tool is asked, nothing has moved.
        self.assertEqual(observed["asking"], {"now": [True], "flushes": []})
        # The answer redraws the row: its switch is styled on, once, and then turned off.
        self.assertEqual(observed["flushes"], [[True]])
        self.assertEqual(observed["now"], [False])

    def test_cancelling_leaves_it_where_it_was(self):
        observed = page(self.WATCH + """
          press(switches()[0]);
          var keep = ROOT_NODE.all(function (n) { return n.tagName === 'button' && n.parentNode.className === 'actions'; })[1];
          keep.onclick();
          """ + say("{now: states(), flushes: FLUSHES, calls: CALLS.length}"))
        self.assertEqual((observed["now"], observed["flushes"]), ([True], []))

    def test_turning_on_moves_when_the_tool_answers(self):
        observed = page(self.WATCH + """
          var first = switches()[0];
          press(first);
          var pressed = {checked: first.checked, disabled: first.disabled};
          await settle();
          ANSWER.resolve({structuredContent: {thread_id: ANSWER.args.thread_id, enabled: true}});
          await settle();
          """ + say("{pressed: pressed, now: states(), flushes: FLUSHES, tool: ANSWER.name}"), data=self.row(False))
        self.assertEqual(observed["pressed"], {"checked": False, "disabled": True})
        self.assertEqual(observed["tool"], "enable_conversation_recovery")
        self.assertEqual((observed["flushes"], observed["now"]), ([[False]], [True]))

    def test_a_refusal_moves_nothing(self):
        observed = page(self.WATCH + """
          press(switches()[0]);
          await settle();
          ANSWER.resolve({isError: true, content: [], structuredContent: {error_code: 'store_unavailable'}});
          await settle();
          """ + say("{now: states(), flushes: FLUSHES}"), data=self.row(False))
        self.assertEqual(observed, {"now": [False], "flushes": []})

    def test_a_redraw_for_anything_else_moves_nothing(self):
        observed = page(self.WATCH + """
          render();
          render();
          """ + say("{now: states(), flushes: FLUSHES}"))
        self.assertEqual(observed, {"now": [True], "flushes": []})


class ScriptTests(unittest.TestCase):
    def test_the_list_keeps_the_windows_numbers_and_nothing_ticks(self):
        script = mcpui._SCRIPT
        self.assertIn("var COMBO_ROWS = %d;" % ROWS, script)
        self.assertIn("var COMBO_TYPING_MS = %d;" % TYPING_MS, script)
        self.assertNotIn("COMBO_PAGE", script)
        for forbidden in ("setInterval", "requestAnimationFrame"):
            self.assertNotIn(forbidden, script)
        # The page's one timeout is the clock's (watchClock, v0.6.10), never the list's: typing times its search by
        # the moment each key comes, and nothing waits.
        self.assertEqual(script.count("setTimeout("), 1)
        self.assertIn("setTimeout(", javascript_function("watchClock"))
        # A pick is a select's own change, heard by whatever listens to the select.
        self.assertEqual(script.count("select.dispatchEvent(new Event('change', {bubbles: true}));"), 1)

    def test_the_status_light_is_still_brands(self):
        # The light's numbers are brand's; this release's panel work redefines none of them. The one place a
        # `--glow-*` is declared outside brand's scale is the tile's smaller light (v0.6.10), and that is brand's
        # too: the glow's reach and stops for its radius, as brand.css_glow_geometry writes them.
        scale = brand.css_scale()
        mini = brand.css_glow_geometry(brand.STATUS_DOT["mini"])
        self.assertEqual(mcpui._STYLE.count(mini), 1)
        for name in re.findall(r"(--glow-[a-z-]+):", scale):
            self.assertNotRegex(mcpui._STYLE.replace(scale, "").replace(mini, ""), re.escape(name) + r"\s*:")


# ------------------------------------------------------------------------------------ tiles
try:
    from codex_auto_resume.ui import popup as tray_popup
except Exception:                                                         # pragma: no cover - not Windows
    tray_popup = None

# Where each theme's variables are declared, as test_mcpui_v063 finds them.
THEME_BLOCKS = {("", (":root",)): "light", ("", (':root[data-theme="light"]',)): "light",
                ("", (':root[data-theme="dark"]',)): "dark",
                ("@media (prefers-color-scheme: dark)", (':root:not([data-theme="light"])',)): "dark"}
TILES = (".prow", ".master")


class TileLiftTests(unittest.TestCase):
    """A tile on a card - a waiting task's row, the master switch's - stands on it as the popup's task tiles
    do since they gained depth: the three surfaces are one product, so what one gains the others wear too."""

    def test_the_panels_tiles_are_raised_as_the_popups_are(self):
        for selector in TILES:
            with self.subTest(selector):
                self.assertEqual((declared(selector, "background"), declared(selector, "border"),
                                  declared(selector, "box-shadow")),
                                 ("var(--raised)", "1px solid var(--line)", "var(--elev-tile)"))
                self.assertEqual(declared(selector, "box-shadow", FORCED), "none",
                                 "High Contrast: system colours and hairlines, no shadow")
        # Only the tiles: nothing else on the page changed its lift.
        wearing = sorted(selector for _, selectors, declarations in RULES
                         for selector in selectors if "var(--elev-tile)" in declarations.get("box-shadow", ""))
        self.assertEqual(wearing, sorted(TILES))

    def test_the_lift_is_declared_for_each_theme_from_brand(self):
        found = {}
        for context, selectors, declarations in RULES:
            theme = THEME_BLOCKS.get((context, selectors))
            if theme:
                found[(context, selectors)] = declarations.get("--elev-tile")
                self.assertEqual("--elev-tile: %s;" % declarations.get("--elev-tile"), mcpui.tile_elevation(theme))
        self.assertEqual(len(found), len(THEME_BLOCKS), "every theme block declares it")
        # Written the way brand writes its own recipes, word for word - so it is brand's lift, not the page's.
        for theme in ("light", "dark"):
            for recipe in brand.SHADOWS[theme]:
                with self.subTest(theme=theme, recipe=recipe):
                    written = ", ".join(mcpui.css_shadow(shadow) for shadow in brand.shadows(recipe, theme))
                    self.assertIn("--elev-%s: %s;" % (recipe, written), brand.css_elevation(theme))

    @unittest.skipUnless(tray_popup, "the popup draws only on Windows")
    def test_it_is_the_popups_task_tile_shadow_for_shadow(self):
        for theme in ("light", "dark"):
            with self.subTest(theme):
                control = re.search(r"--elev-control: ([^;]+);", brand.css_elevation(theme)).group(1)
                tile = re.fullmatch(r"--elev-tile: (.+);", mcpui.tile_elevation(theme)).group(1)
                self.assertEqual(tile.replace("var(--elev-control)", control),
                                 ", ".join(mcpui.css_shadow(shadow)
                                           for shadow in tray_popup.recipe_shadows("tile", theme)))
                self.assertEqual(tray_popup.tile_ground(theme), brand.palette(theme)["raised"],
                                 "and on the same ground as the panel's tiles, `raised`")
        # Dark carries the card's one-pixel top light inside the hairline; light has none to carry.
        self.assertIn("inset ", mcpui.tile_elevation("dark"))
        self.assertNotIn("inset ", mcpui.tile_elevation("light"))


# ------------------------------------------------------------------------------------ line breaks
AUTO_PHRASE = "@supports (word-break: auto-phrase)"


class LineBreakStyleTests(unittest.TestCase):
    """A line breaks between words, never inside one: Korean at its spaces ('진단', never '진/단'), Japanese
    between phrases where the engine knows them, Chinese between characters as it is set; Latin as ever."""

    def test_korean_keeps_its_words_whole_and_japanese_its_phrases(self):
        self.assertEqual(declared(":root:lang(ko)", "word-break"), "keep-all")
        self.assertEqual(declared(":root:lang(ja)", "word-break", AUTO_PHRASE), "auto-phrase")
        # Not keep-all for Japanese or Chinese, which have no spaces: that broke them only at their commas and
        # stops and left lines half empty. An engine without phrases breaks Japanese as it always did.
        for locale in ("ja", "zh"):
            self.assertIsNone(declared(":root:lang(%s)" % locale, "word-break"), locale)
        self.assertIsNone(declared(":root:lang(zh)", "word-break", AUTO_PHRASE))
        # A word longer than its whole line still breaks rather than running past the edge.
        for locale in ("ko", "ja", "zh"):
            self.assertEqual(declared(":root:lang(%s)" % locale, "overflow-wrap"), "anywhere", locale)

    def test_nothing_else_changes_how_lines_break(self):
        breaking = sorted((context, selector) for context, selectors, declarations in RULES
                          for selector in selectors if "word-break" in declarations)
        self.assertEqual(breaking, [("", ":root:lang(ko)"), (AUTO_PHRASE, ":root:lang(ja)")])
        rooted = [selector for _, selectors, declarations in RULES for selector in selectors
                  if "overflow-wrap" in declarations and selector.startswith(":root")]
        self.assertEqual(sorted(rooted), [":root:lang(ja)", ":root:lang(ko)", ":root:lang(zh)"],
                         "only the three languages' roots; Latin pages keep the browser's own wrapping")


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PageLanguageTests(unittest.TestCase):
    """The rules above read the page's language off its root, which says the language the words are in."""

    def test_the_root_says_the_language_the_page_speaks(self):
        for locale in ("en", "ko", "ja", "zh-CN", "zh-TW"):
            with self.subTest(locale):
                self.assertEqual(page(say("document.documentElement.getAttribute('lang')"),
                                      data=snapshot(interface_language=locale), locale=locale), locale)

    def test_a_language_saved_elsewhere_is_said_on_the_root_once_the_page_speaks_it(self):
        observed = page("""
          window.__STORED__ = Object.assign({}, window.__STORED__, {interface_language: 'ko'});
          var before = document.documentElement.getAttribute('lang');
          var box = ROOT_NODE.all(function (n) { return n.className === 'check'; })[0];
          box.checked = !box.checked;
          box.fire('change');
          saveButton().onclick();
          await settle();
          """ + say("{before: before, after: document.documentElement.getAttribute('lang'), locale: LOCALE}"))
        self.assertEqual(observed, {"before": "en", "after": "ko", "locale": "ko"})

    def test_a_page_with_no_locale_names_none(self):
        self.assertIsNone(page("LOCALE = ''; render();" + say("document.documentElement.getAttribute('lang')"),
                               root_attributes={"lang": "fr"}))


if __name__ == "__main__":
    unittest.main()
