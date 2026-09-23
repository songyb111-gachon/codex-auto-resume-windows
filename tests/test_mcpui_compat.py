"""The Codex compatibility card in the settings panel (v0.6.5).

The panel shows the Codex Compatibility Registry as the Windows Dashboard's Diagnostics page does: the
overall word, when it was checked, which data was in force, and each part the product relies on with its
state - verified, compatible, incompatible, unknown - and what each of those words means. Read-only, and
more than read-only: nothing on it can make the machine talk to GitHub, because a refresh is a request a
model must never be able to cause.

Most of it runs the panel's own script in Node against the stand-in document test_mcpui_v064 keeps, fed
the status the MCP server really sends (the Compatibility Registry's fixture, hermetic: its own Codex, its
own home), because the claims are about what the page draws from what it is given.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from codex_auto_resume import compat, control, l10n, mcpserver      # noqa: E402
from codex_auto_resume.mcp import panel as mcpui
from test_mcpui_v063 import declared                                        # noqa: E402
from test_mcpui_v064 import run_page, say, snapshot                          # noqa: E402

NODE = shutil.which("node")
ENGLISH = l10n.catalog("en")
# Node is started through subprocess.run, which the registry's fixture replaces with its fake Codex.
REAL_RUN = subprocess.run

# What the page shows of the card, read back out of the stand-in document.
LOOK = r"""
function compatCard() {
  return ROOT_NODE.all(function (n) { return n.tagName === 'details' && n.classList.contains('compat'); })[0] || null;
}
function look() {
  var card = compatCard();
  if (!card) return null;
  var summary = card.children[0];
  var chip = summary.all(function (n) { return n.classList.contains('chip'); })[0];
  var rows = card.all(function (n) { return n.tagName === 'li'; }).map(function (li) {
    var label = li.all(function (n) { return n.classList.contains('setting-label'); })[0];
    var state = li.all(function (n) { return n.classList.contains('chip'); })[0];
    return [label.textContent, state.textContent, state.className];
  });
  return {open: card.open, title: summary.children[0].textContent, chip: chip.textContent, tone: chip.className,
          meta: card.all(function (n) { return n.classList.contains('compat-meta'); })[0].textContent,
          callout: card.all(function (n) { return n.classList.contains('callout'); }).map(function (n) { return n.textContent; }),
          rows: rows,
          legend: card.all(function (n) { return n.parentNode && n.parentNode.classList.contains('compat-legend'); })
                      .map(function (n) { return n.textContent; }),
          hint: card.all(function (n) { return n.classList.contains('compat-refresh'); }).map(function (n) { return n.textContent; }),
          buttons: card.all(function (n) { return n.tagName === 'button' || n.tagName === 'input'; }).length,
          place: ROOT_NODE.children[0].children.map(function (n) { return n.className; })};
}
"""


def summary(overall="structurally_compatible", status="ok", source="bundled", checked_at=None, acting=None,
            cache=None, sequence=None, **states):
    """A `watcher.compatibility` summary as compat.mcp_view gives it - and, where a test names them, the three codes
    the window also shows: what the watcher acts on (`acting`, a word of compat.ENGINE_STATES), the refreshed data's
    standing (`cache`, a word of compat.CACHE_STATES) and the sequence number of the data in force."""
    capabilities = {}
    for name, (_, tier) in compat.CAPABILITIES.items():
        if tier == "unsupported":
            capabilities[name] = {"state": "UNKNOWN", "reason": "not_implemented"}
        else:
            capabilities[name] = {"state": "COMPATIBLE", "reason": "local_checks_passed"}
    for name, state in states.items():
        capabilities[name] = {"state": state, "reason": "registry_incompatible" if state == "INCOMPATIBLE"
                              else "local_check_unavailable" if state == "UNKNOWN" else "registry_verified"}
    view = {"status": status, "overall": overall, "data": {"source": source},
            "checked_at": time.time() - 300 if checked_at is None else checked_at, "capabilities": capabilities}
    made = compat.mcp_view(view)
    made.update({name: code for name, code in (("acting", acting), ("cache", cache), ("sequence", sequence))
                 if code is not None})
    return made


def with_compat(view, **settings):
    data = snapshot(**settings)
    data["status"]["watcher"] = {"running": True, "ticking": True, "engine_state": "structurally_compatible",
                                 "compatibility": view}
    return data


def page(data, locale="en", body=""):
    return run_page(LOOK + body + say("look()"), data=data, locale=locale)


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class CardTests(unittest.TestCase):
    def test_a_status_without_a_view_draws_no_card(self):
        """An older watcher, or a summary the server could not make: nothing is said rather than a guess."""
        self.assertIsNone(page(snapshot()))
        data = snapshot()
        data["status"]["watcher"] = {"running": True, "compatibility": None}
        self.assertIsNone(page(data))

    def test_the_card_is_folded_under_what_is_waiting_and_its_chip_says_the_headline(self):
        seen = page(with_compat(summary()))
        self.assertEqual(seen["title"], ENGLISH["compat.title"])
        self.assertIs(seen["open"], False, "folded until it is opened, as the other read-mostly cards are")
        self.assertEqual(seen["chip"], ENGLISH["compat.state.COMPATIBLE"])
        self.assertIn("success", seen["tone"])
        place = seen["place"]
        self.assertLess(place.index("card pending"), place.index("card fold compat"))
        self.assertEqual(place.index("card fold compat"), place.index("card pending") + 1,
                         "whether this Codex can be relied on comes before what is configured")

    def test_each_part_the_product_does_is_a_row_with_its_state_in_words(self):
        seen = page(with_compat(summary(overall="incompatible", queue_withdraw="INCOMPATIBLE",
                                        loaded_state_detection="UNKNOWN")))
        rows = {name: (word, tone) for name, word, tone in seen["rows"]}
        offered = [name for name, (_, tier) in compat.CAPABILITIES.items() if tier != "unsupported"]
        self.assertEqual([row[0] for row in seen["rows"]],
                         [ENGLISH["compat.capability." + name] for name in offered],
                         "the registry's order, and the four it does not offer yet left out")
        self.assertEqual(rows[ENGLISH["compat.capability.queue_withdraw"]][0], ENGLISH["compat.state.INCOMPATIBLE"])
        self.assertIn("danger", rows[ENGLISH["compat.capability.queue_withdraw"]][1])
        self.assertEqual(rows[ENGLISH["compat.capability.loaded_state_detection"]][0], ENGLISH["compat.state.UNKNOWN"])
        self.assertIn("paused", rows[ENGLISH["compat.capability.loaded_state_detection"]][1])
        self.assertIn("success", rows[ENGLISH["compat.capability.engine_present"]][1])
        self.assertEqual(seen["chip"], ENGLISH["compat.state.INCOMPATIBLE"])

    def test_every_state_word_shown_is_explained_and_no_other(self):
        seen = page(with_compat(summary(queue_withdraw="INCOMPATIBLE")))
        self.assertEqual(seen["legend"], [ENGLISH["compat.meaning.COMPATIBLE"], ENGLISH["compat.meaning.INCOMPATIBLE"]])
        seen = page(with_compat(summary(overall="verified", engine_present="VERIFIED", exact_thread_recovery="VERIFIED",
                                        usage_probe="UNKNOWN")))
        self.assertEqual(seen["legend"], [ENGLISH["compat.meaning." + state]
                                          for state in ("VERIFIED", "COMPATIBLE", "UNKNOWN")])

    def test_when_it_was_checked_and_which_data_is_in_force(self):
        at = time.mktime((2025, 3, 4, 14, 2, 0, 0, 0, -1))
        seen = page(with_compat(summary(source="cache", checked_at=at)))
        self.assertIn(ENGLISH["compat.checked"], seen["meta"])
        self.assertIn(ENGLISH["compat.source.cache"], seen["meta"])
        self.assertIn("14:02", seen["meta"], "a time written out, never in the browser's own format")
        self.assertIn("2025-03-04", seen["meta"], "a day that is not today is said")
        today = page(with_compat(summary(checked_at=time.time() - 60)))["meta"]
        self.assertNotRegex(today, r"\d{4}-\d{2}-\d{2}", "today's is the time alone")
        for source, key in (("bundled", "compat.source.bundled"), ("none", "compat.source.none"),
                            ("elsewhere", "compat.source.none")):
            with self.subTest(source):
                data = with_compat(dict(summary(), source=source))
                self.assertIn(ENGLISH[key], page(data)["meta"])

    def test_a_report_that_cannot_be_used_says_why_once_and_lists_nothing(self):
        for status in ("absent", "invalid", "stale", "engine_changed"):
            with self.subTest(status):
                view = compat.mcp_view(compat.unusable_view(status))
                seen = page(with_compat(view))
                self.assertEqual(seen["callout"], [ENGLISH["compat.status." + status]])
                self.assertEqual(seen["rows"], [], "every part is unknown for that one reason; a list of them says nothing more")
                self.assertEqual(seen["chip"], ENGLISH["compat.state.UNKNOWN"])
                self.assertEqual(seen["legend"], [], "the callout says why; the legend's reason for unknown would contradict it")
                self.assertTrue(seen["meta"].endswith(ENGLISH["compat.data"] + " -"),
                                "nothing is known about the data in force either: '-', as the window says, never 'none'")
                self.assertTrue(seen["meta"].startswith(ENGLISH["compat.checked"] + " " + ENGLISH["time.never"]),
                                "never checked, in the window's word for it")

    def test_which_data_is_in_force_is_said_by_its_sequence_as_the_window_says_it(self):
        seen = page(with_compat(summary(source="cache", sequence=12)))
        self.assertIn(ENGLISH["compat.data"] + " " + ENGLISH["compat.source_sequence"]
                      .replace("{source}", ENGLISH["compat.source.cache"]).replace("{sequence}", "12"), seen["meta"])
        korean = l10n.catalog("ko")
        seen = page(with_compat(summary(source="bundled", sequence=1), interface_language="ko"), locale="ko")
        self.assertIn(korean["compat.source_sequence"].replace("{source}", korean["compat.source.bundled"])
                      .replace("{sequence}", "1"), seen["meta"])
        for source, sequence in (("none", 3), ("cache", -1), ("cache", "12"), ("cache", True), ("cache", 1.5), ("cache", None)):
            with self.subTest(source=source, sequence=sequence):
                meta = page(with_compat(dict(summary(source=source), sequence=sequence)))["meta"]
                self.assertNotIn("#", meta, "no number but a sequence, and none for no data")
                self.assertTrue(meta.endswith(ENGLISH["compat.source." + source]))
        unusable = dict(compat.mcp_view(compat.unusable_view("stale")), sequence=4)
        self.assertTrue(page(with_compat(unusable))["meta"].endswith(ENGLISH["compat.data"] + " -"))

    def test_the_watcher_acting_on_what_it_found_at_its_start_is_said(self):
        """The watcher decides on the verdict it started with; after Codex changed in place the fresh report can say
        something else. The window says so, and so does the panel - pointing to where the watcher is started again."""
        seen = page(with_compat(summary(overall="incompatible", acting="structurally_compatible",
                                        queue_withdraw="INCOMPATIBLE")))
        self.assertEqual(seen["callout"], [ENGLISH["panel.compat_acting_differs"]])
        for acting in (None, "structurally_compatible"):
            with self.subTest(acting=acting):
                self.assertEqual(page(with_compat(summary(acting=acting)))["callout"], [])

    def test_refreshed_data_it_cannot_fully_trust_is_said_in_the_windows_words(self):
        caveats = ("expired", "from_the_future", "rejected", "superseded", "from_newer_product")
        for cache in caveats:
            with self.subTest(cache):
                seen = page(with_compat(summary(source="bundled" if cache in ("rejected", "superseded", "from_newer_product")
                                                else "cache", cache=cache)))
                self.assertEqual(seen["callout"], [ENGLISH["compat.cache." + cache]])
        for cache in ("ok", "absent", "something"):
            with self.subTest(cache):
                self.assertEqual(page(with_compat(summary(cache=cache)))["callout"], [])
        # Both, in the window's order; and neither for a report that cannot be used, which says its one reason.
        both = page(with_compat(summary(overall="incompatible", acting="structurally_compatible", cache="expired",
                                        queue_withdraw="INCOMPATIBLE")))
        self.assertEqual(both["callout"], [ENGLISH["panel.compat_acting_differs"], ENGLISH["compat.cache.expired"]])
        unusable = dict(compat.mcp_view(compat.unusable_view("engine_changed")), acting="incompatible", cache="expired")
        self.assertEqual(page(with_compat(unusable))["callout"], [ENGLISH["compat.status.engine_changed"]])
        # The same caveats as the window's card names, no more and no fewer.
        dashboard = (ROOT / "gui" / "Dashboard.cs").read_text(encoding="utf-8")
        window = re.search(r'if \((cache == "[a-z_]+"(?: \|\| cache == "[a-z_]+")*)\)', dashboard).group(1)
        self.assertEqual(set(re.findall(r'"([a-z_]+)"', window)), set(caveats))
        self.assertEqual(set(caveats), set(compat.CACHE_STATES) - {"absent", "ok"})

    def test_nothing_on_it_can_be_pressed_and_it_says_where_the_data_is_refreshed(self):
        seen = page(with_compat(summary()))
        self.assertEqual(seen["buttons"], 0)
        self.assertEqual(seen["hint"], [ENGLISH["panel.compat_refresh"]])

    def test_it_stays_open_across_a_redraw_once_opened(self):
        body = ("compatCard().open = true; compatCard().fire('toggle'); render();")
        self.assertIs(page(with_compat(summary()), body=body)["open"], True)

    def test_it_speaks_the_language_the_panel_speaks(self):
        korean = l10n.catalog("ko")
        seen = page(with_compat(summary(queue_withdraw="INCOMPATIBLE"), interface_language="ko"), locale="ko")
        self.assertEqual(seen["title"], korean["compat.title"])
        self.assertEqual(seen["chip"], korean["compat.state.COMPATIBLE"])
        self.assertIn([korean["compat.capability.queue_withdraw"], korean["compat.state.INCOMPATIBLE"]],
                      [row[:2] for row in seen["rows"]])
        self.assertIn(korean["compat.meaning.INCOMPATIBLE"], seen["legend"])


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class FromTheServerTests(unittest.TestCase):
    """What the MCP server really sends, drawn: the summary `open_settings` carries, from a report the
    watcher's evaluator wrote for the fixture's own fake Codex."""

    def test_the_card_draws_the_summary_open_settings_sends(self):
        from test_compat_characterization import FakeCodex, Fixture
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0"))
        fixture.backend()
        ctl = control.Control(fixture.paths)
        with patch.object(control.Control, "watcher_running", return_value=True), \
             patch.object(control.Control, "startup_enabled", return_value=False):
            data = mcpserver.Server(ctl, None, None)._snapshot()
        view = data["status"]["watcher"]["compatibility"]
        # The words this test reads are English whatever Windows on the machine running it speaks.
        data["system_language"] = "en"
        self.assertEqual((view["status"], view["overall"]), ("ok", "structurally_compatible"))
        with patch.object(subprocess, "run", REAL_RUN):
            seen = page(json.loads(json.dumps(data, default=str)))
        self.assertEqual(seen["chip"], ENGLISH["compat.state.COMPATIBLE"])
        self.assertEqual(len(seen["rows"]), sum(1 for _, tier in compat.CAPABILITIES.values() if tier != "unsupported"))
        self.assertIn(ENGLISH["compat.source.bundled"], seen["meta"])
        self.assertEqual(seen["callout"], [], "the watcher acts on what the report says, and the data is simply in force")
        # The three codes the window's card also reads travel with it, and the data is said by its number.
        self.assertTrue({"acting", "cache", "sequence"} <= set(view), sorted(view))
        self.assertEqual(view["acting"], view["overall"])
        self.assertIsInstance(view["sequence"], int)
        self.assertIn(ENGLISH["compat.data"] + " " + ENGLISH["compat.source_sequence"]
                      .replace("{source}", ENGLISH["compat.source.bundled"])
                      .replace("{sequence}", str(view["sequence"])), seen["meta"])

    def test_the_card_says_what_the_registry_says_with_nothing_added(self):
        """A report whose watcher still acts on what it found at its start, on refreshed data that has expired:
        compat.mcp_view's summary of it, drawn as it is - the number and both caveats, in the window's order and
        words, in English and in Korean."""
        from test_compat import NOW, a_report
        refreshed = {"bundled": "ok", "bundled_sequence": 1, "cache": "expired", "cache_sequence": 12,
                     "cache_origin": "main", "fetched_at": NOW, "source": "cache", "expired": True}
        view = compat.mcp_view(compat.view_of(a_report(data=refreshed, acting="incompatible")))
        for locale in ("en", "ko"):
            with self.subTest(locale):
                words = l10n.catalog(locale)
                seen = page(with_compat(view, interface_language=locale), locale=locale)
                self.assertIn(words["compat.data"] + " " + words["compat.source_sequence"]
                              .replace("{source}", words["compat.source.cache"]).replace("{sequence}", "12"),
                              seen["meta"])
                self.assertEqual(seen["callout"], [words["panel.compat_acting_differs"], words["compat.cache.expired"]])
                self.assertEqual(seen["chip"], words["compat.state.COMPATIBLE"],
                                 "the report's own word leads; what the watcher acts on is the caveat")


class NoRefreshTests(unittest.TestCase):
    """A refresh is a request to GitHub. The panel cannot ask for one, and its words point to where a
    person can."""

    def test_the_script_calls_no_tool_that_refreshes_or_imports(self):
        tools = set(re.findall(r"callTool\(\s*'([a-z_]+)'", mcpui._SCRIPT))
        tools |= set(re.findall(r"'((?:enable|disable)_conversation_recovery|(?:pause|resume)_auto_recovery)'", mcpui._SCRIPT))
        self.assertTrue(tools)
        for name in tools:
            self.assertIsNone(re.search(r"compat|registry|refresh|import|fetch", name), name)
        offered = {tool["name"] for tool in mcpserver.TOOLS}
        self.assertFalse([name for name in offered if re.search(r"compat|refresh|import|fetch", name)])

    def test_the_card_reads_only_the_status_it_was_given(self):
        card = mcpui._SCRIPT[mcpui._SCRIPT.index("function renderCompatibility("):]
        card = card[:card.index("\nfunction ", 1)]
        self.assertNotIn("callTool", card)
        self.assertIn("status.watcher.compatibility", card)
        self.assertIn("folding('compat'", card)


class StyleTests(unittest.TestCase):
    def test_its_rows_are_the_settings_rows_in_one_column(self):
        self.assertEqual(declared(".compat-rows", "list-style"), "none")
        self.assertEqual(declared(".compat-rows", "grid-template-columns"), "minmax(0, 1fr)",
                         "at the panel's width two columns wrapped most names onto a second line")
        self.assertEqual(declared(".compat-state", "flex"), "none", "a state is never cut to make room")
        self.assertEqual(declared(".compat-refresh", "margin-top"), "var(--space-m)")
        self.assertIn("var(--space-", declared(".fold-end", "gap"))
        script = mcpui._SCRIPT
        self.assertIn("element('ul', 'toggles compat-rows')", script, "the switches' columns and hairlines")
        self.assertIn("element('li', 'setting')", script, "each part is a settings row")

    def test_every_word_it_can_show_ships_in_every_language(self):
        names, prefixes = mcpui.panel_keys()
        wanted = ["compat.title", "compat.checked", "compat.data", "compat.status.invalid", "panel.compat_refresh",
                  "panel.compat_acting_differs", "compat.source_sequence"]
        wanted += ["compat.cache." + state for state in compat.CACHE_STATES if state not in ("absent", "ok")]
        wanted += ["compat.state." + state for state in compat.STATES]
        wanted += ["compat.meaning." + state for state in compat.STATES]
        wanted += ["compat.capability." + name for name in compat.CAPABILITIES]
        wanted += ["compat.status." + status for status in compat.VIEW_STATUSES if status != "ok"]
        wanted += ["compat.source." + source for source in compat.DATA_SOURCES]
        catalogs = mcpui.panel_catalogs()
        for key in wanted:
            self.assertTrue(key in names or key.startswith(prefixes), key)
            for locale in l10n.LOCALES:
                with self.subTest(key=key, locale=locale):
                    self.assertTrue(catalogs[locale].get(key), key)
                    # Sentences are translated, never copied. (A state word may be the same word in another
                    # language: "compatible" is French and Spanish too.)
                    if locale != "en" and key.startswith(("compat.meaning.", "compat.capability.", "compat.status.",
                                                          "compat.cache.", "panel.")):
                        self.assertNotEqual(catalogs[locale][key], ENGLISH[key], "translated, not copied")


if __name__ == "__main__":
    unittest.main()
