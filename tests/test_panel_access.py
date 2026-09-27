"""v0.6.11: the panel in Codex - a needs-you notice's parts that follow their switch, and Windows' text size.

* **The needs-you notice's parts follow it.** Its four kinds, its stall and its sound only matter while When a
  conversation needs you is on, under notifications on (needsyou.told), so they are drawn one step in under it
  and are live only while both are on - as the Dashboard draws them - and what they store is sent as it is.
* **Windows' text size.** The page is served a second stylesheet at a text size past 1 (panel.text_scale_style)
  that makes its type, and everything that holds a line of it, that many times larger; every other line wraps.
  The stylesheet itself holds no line at a fixed height and cuts nothing but where it says so with an ellipsis,
  and headless Edge, where it is installed, lays the page out at 225% and finds nothing cut and nothing wider
  than the panel.
"""
from __future__ import annotations

import html as html_text
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from codex_auto_resume import brand, l10n  # noqa: E402
from codex_auto_resume.mcp import panel as mcpui  # noqa: E402
from codex_auto_resume.win import textsize  # noqa: E402
from test_mcpui_v064 import NODE, run_page, say, snapshot  # noqa: E402

ENGLISH = l10n.catalog("en")
PARTS = ("notify_needs_you_invalid", "notify_needs_you_policy", "notify_needs_you_auth", "notify_needs_you_failure",
         "stall_after", "needs_you_sound")

# The page's own drawing of each notification setting: whether it is live, where it stands, and its value.
SEEN = """(function () {
  function row(name) {
    if (name === 'stall_after') return byId('car-stall_after');
    var node = ROOT_NODE.all(function (n) { return n.className === 'setting-label' && n.textContent === S['field.' + name]; })[0];
    while (node && node.tagName !== 'label') node = node.parentNode;
    return node;
  }
  function input(node) {
    if (!node) return null;
    if (node.tagName === 'input' || node.tagName === 'select') return node;
    for (var i = 0; i < node.children.length; i++) { var found = input(node.children[i]); if (found) return found; }
    return null;
  }
  function holder(node) {
    while (node && node.className.indexOf('toggles') < 0) node = node.parentNode;
    return node ? node.className : null;
  }
  var seen = {};
  NAMES.forEach(function (name) {
    var drawn = row(name), field = input(drawn);
    var box = name === 'stall_after' ? byId('car-stall_after-box') : null;
    seen[name] = {disabled: !!field.disabled, holder: holder(drawn),
                  checked: field.type === 'checkbox' ? !!field.checked : field.value,
                  ariaDisabled: box ? box.getAttribute('aria-disabled') : null};
  });
  return seen;
})()"""
NAMES = ("notifications", "notify_needs_you") + PARTS


def flip(name: str, on: bool) -> str:
    return """(function () {
      var text = S['field.%s'];
      var label = ROOT_NODE.all(function (n) { return n.tagName === 'label' && n.textContent === text; })[0];
      var box = label.all(function (n) { return n.tagName === 'input'; })[0];
      box.checked = %s;
      box.fire('change');
    })();""" % (name, "true" if on else "false")


def seen(body="", data=None):
    return run_page("var NAMES = %s;" % json.dumps(NAMES) + body + say(SEEN), data=data)


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class NeedsYouFollowsItsSwitchTests(unittest.TestCase):
    def test_at_the_defaults_the_parts_are_one_step_in_and_not_live(self):
        drawn = seen()
        self.assertFalse(drawn["notify_needs_you"]["disabled"])
        self.assertEqual(drawn["notify_needs_you"]["holder"], "toggles")
        for name in PARTS:
            with self.subTest(name):
                self.assertTrue(drawn[name]["disabled"], "live while the notice is off")
                self.assertEqual(drawn[name]["holder"], "toggles needs-you quiet")
        self.assertEqual(drawn["stall_after"]["ariaDisabled"], "true", "the drop-down says so as well")

    def test_they_are_live_while_the_notice_and_notifications_are_on(self):
        told = seen(flip("notify_needs_you", True))
        silent = seen(flip("notify_needs_you", True) + flip("notifications", False))
        for name in PARTS:
            with self.subTest(name):
                self.assertFalse(told[name]["disabled"], "not live while the notice is on")
                self.assertEqual(told[name]["holder"], "toggles needs-you")
                self.assertTrue(silent[name]["disabled"], "live while notifications are off")
        self.assertIsNone(told["stall_after"]["ariaDisabled"])
        self.assertFalse(silent["notify_needs_you"]["disabled"], "the notice itself stays as the panel drew it")

    def test_a_part_an_administrator_decides_stays_greyed(self):
        data = snapshot(notify_needs_you=True)
        for entry in data["schema"]:
            if entry["name"] == "notify_needs_you_auth":
                entry["managed"] = True
        drawn = seen(data=data)
        self.assertTrue(drawn["notify_needs_you_auth"]["disabled"])
        self.assertFalse(drawn["notify_needs_you_policy"]["disabled"])

    def test_without_a_host_every_part_is_greyed_and_still_drawn(self):
        drawn = run_page("window.openai = undefined; HOST = null; render(); var NAMES = %s;" % json.dumps(NAMES)
                         + say(SEEN), data=snapshot(notify_needs_you=True))
        for name in PARTS:
            self.assertTrue(drawn[name]["disabled"])

    def test_what_they_store_is_sent_as_it_stands(self):
        """Only whether they can be changed follows the switch: a save sends their values untouched."""
        observed = run_page(flip("notify_needs_you", True) + flip("notify_needs_you", False) + """
          saveButton().onclick();
          await settle();
          """ + say("CALLS.filter(function (c) { return c[0] === 'update_settings'; })"))
        self.assertEqual(len(observed), 1)
        sent = observed[0][1]
        defaults = snapshot()["settings"]
        for name in PARTS:
            with self.subTest(name):
                self.assertEqual(sent[name], defaults[name])

    def test_the_parts_start_where_the_notices_words_do(self):
        rule = re.search(r"\.toggles\.needs-you \{([^}]*)\}", mcpui._STYLE)
        self.assertIsNotNone(rule)
        self.assertIn("margin-inline-start: calc(var(--size-check-size) + var(--size-check-gap));", rule.group(1))
        help_text = run_page(say("""ROOT_NODE.all(function (n) { return n.className === 'toggles needs-you quiet'; })[0]
                                   .children.map(function (c) { return c.className; })"""))
        self.assertEqual(help_text[-1], "help", "what the notice is, under the last of its settings")


class TextSizeStyleTests(unittest.TestCase):
    def test_at_the_usual_size_the_page_is_served_as_it_always_was(self):
        for text in (1.0, 0.5, True, "2", None):
            with self.subTest(text=text):
                self.assertEqual(mcpui.text_scale_style(text), "")
        with unittest.mock.patch.object(textsize, "read", lambda: 1.0):
            page = mcpui.settings_page()
        self.assertEqual(page.count("<style>"), 1)
        self.assertEqual(page, mcpui.settings_page(text=1.0))

    def test_a_larger_size_makes_the_type_and_what_holds_a_line_that_much_larger(self):
        style = mcpui.text_scale_style(2.25)
        declared = dict(re.findall(r"(--[a-z-]+): ([0-9.]+)px;", style))
        for name, value in brand.TYPE_SCALE.items():
            with self.subTest(name):
                self.assertAlmostEqual(float(declared["--type-" + name.replace("_", "-")]), value * 2.25, places=3)
        for name in mcpui.TEXT_HOLDERS:
            with self.subTest(name):
                self.assertAlmostEqual(float(declared["--size-" + name.replace("_", "-")]), brand.LAYOUT[name] * 2.25,
                                       places=3)
        self.assertEqual(declared["--line-control"], "45")
        self.assertTrue(style.startswith("<style>:root {"))
        self.assertEqual(mcpui.text_scale_style(3.0), mcpui.text_scale_style(2.25), "225% is Windows' largest")

    def test_codex_is_served_windows_own_size_each_time(self):
        with unittest.mock.patch.object(textsize, "read", lambda: 1.5):
            page = mcpui.settings_page()
            self.assertIn("</style>" + mcpui.text_scale_style(1.5) + "</head>", page)
            self.assertEqual(mcpui.settings_page(text=1.0).count("<style>"), 1, "the capture's size is its own")

    def test_the_stylesheet_holds_no_line_at_a_fixed_height_and_cuts_only_with_an_ellipsis(self):
        style = mcpui._STYLE
        self.assertEqual(re.findall(r"line-height:\s*\d+(?:\.\d+)?px", style), [])
        self.assertIn("--combo-line: var(--line-control);", style)
        for match in re.finditer(r"font-size:\s*([^;}]+)", style):
            with self.subTest(match.group(0)):
                self.assertTrue(match.group(1).strip().startswith("var(--type-"), match.group(0))
        for rule in re.findall(r"\{([^{}]*overflow:\s*hidden[^{}]*)\}", style):
            with self.subTest(rule):
                self.assertIn("text-overflow: ellipsis", rule)
        # Each declared once, on the root, so the served stylesheet after it is what they are.
        for name in list(brand.TYPE_SCALE) + list(mcpui.TEXT_HOLDERS):
            prefix = "--type-" if name in brand.TYPE_SCALE else "--size-"
            self.assertEqual(len(re.findall(re.escape(prefix + name.replace("_", "-")) + r"\s*:", style)), 1, name)


EDGE = next((path for path in (Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
                               Path(os.environ.get("ProgramFiles", "C:/Program Files")))
             if (path / "Microsoft/Edge/Application/msedge.exe").is_file()), None)
PROBE = "CAR-TEXT-PROBE:"


@unittest.skipUnless(EDGE is not None, "needs Microsoft Edge to lay the page out")
class TextSizeLayoutTests(unittest.TestCase):
    """The page laid out by a real browser engine at 225%, 900 and 480 CSS pixels wide - a wide Codex side panel
    and a narrow one - in English and German: nothing cut but by an ellipsis, nothing wider than the panel."""

    def measure(self, locale, width, text, extra=""):
        data = snapshot()
        with unittest.mock.patch.object(l10n, "preference", lambda: locale), \
                unittest.mock.patch("codex_auto_resume.interface.language", lambda: locale):
            page = mcpui.settings_page(data, theme="light", design="soft", text=text)
        script = ("<script>window.addEventListener('load',function(){setTimeout(function(){"
                  "var cut=[];Array.prototype.forEach.call(document.querySelectorAll('body *'),function(n){"
                  "var s=getComputedStyle(n);if(s.display==='none'||!n.textContent.trim())return;"
                  "var hides=/hidden|clip/.test(s.overflowX+s.overflowY);"
                  "if(hides&&s.textOverflow!=='ellipsis'&&(n.scrollWidth>n.clientWidth+1||n.scrollHeight>n.clientHeight+1)"
                  "&&n.children.length===0)cut.push(n.tagName+'.'+n.className+': '+n.textContent.slice(0,40));});"
                  "document.title='%s'+JSON.stringify({wide:document.documentElement.scrollWidth,"
                  "window:window.innerWidth,cut:cut});},300);});</script>" % PROBE)
        with tempfile.TemporaryDirectory() as folder:
            probe = Path(folder) / "panel.html"
            probe.write_text(page.replace("</head>", extra + "</head>").replace("</body>", script + "</body>"),
                             encoding="utf-8")
            done = subprocess.run([str(EDGE / "Microsoft/Edge/Application/msedge.exe"), "--headless=new", "--disable-gpu",
                                   "--hide-scrollbars", "--virtual-time-budget=3000", "--user-data-dir=" + folder + "/p",
                                   "--window-size=%d,%d" % (width, 1600), "--dump-dom", probe.as_uri()],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for piece in done.stdout.split(PROBE)[1:]:
            try:
                return json.loads(html_text.unescape(piece.split("</title>", 1)[0]))
            except ValueError:
                continue
        self.fail("the browser said nothing: " + done.stderr[-1500:])

    def test_nothing_is_cut_or_wider_than_the_panel_at_the_largest_text_size(self):
        for locale in ("en", "de"):
            for width in (900, 480):
                found = self.measure(locale, width, 2.25)
                with self.subTest(locale=locale, width=width):
                    self.assertEqual(found["cut"], [])
                    self.assertLessEqual(found["wide"], found["window"], "wider than the panel")

    def test_the_measurement_finds_a_line_cut_and_a_page_too_wide(self):
        """So a quiet report is the browser having looked."""
        found = self.measure("en", 480, 2.25, "<style>.setting-label { display: block; height: 4px; overflow: hidden; }"
                                              " .page { min-width: 900px; }</style>")
        self.assertTrue(found["cut"])
        self.assertGreater(found["wide"], found["window"])


if __name__ == "__main__":
    unittest.main()
