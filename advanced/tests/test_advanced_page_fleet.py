"""See your other PCs in the window itself (v0.6.22, advanced/gui/AdvancedFleet.cs): the Overview's Other PCs list while it
is on and none while it is off, a greyed row, a clock that differs, how the folder stands; the card's name, folder and Save.
The window is driven as the other page modules drive it (pagecase.py), its replies made by the real bridge or here.

GUI test module: compiles real executables, so it runs on its own.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest advanced/tests/test_advanced_page_fleet.py
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from pagecase import PageCase, sent, snapshot  # noqa: E402
from codex_auto_resume_advanced import statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.engine import fleet  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand  # noqa: E402

CAP = "fleet_view"
CARD = ac.ROOT / "advanced" / "gui" / "AdvancedFleet.cs"
PAGE = ac.ROOT / "advanced" / "gui" / "AdvancedPage.cs"
FOLDER = "C:\\Sync\\codex-pcs"


def source(path=CARD) -> str:
    return path.read_text(encoding="utf-8")


def row(alias, seen="fresh", watcher="running", recovery="on", pending=2):
    return {"alias": alias, "watcher": watcher, "recovery": recovery, "pending": pending, "seen": seen,
            "written_at": None if seen == "clock" else ac.NOW - 60,
            "next_check_at": ac.NOW + 600 if seen == "fresh" else None}


def answer(peers=(), stand="ok", ignored=0, state="armed", alias="laptop", folder=FOLDER):
    return {"ok": True, "result": {"done": True, "refusal": None, "state": state, "alias": alias, "folder": folder,
                                   "stand": stand, "peers": list(peers), "ignored": ignored, "generation": 1}}


def on_snapshot():
    made = snapshot()
    made["status"]["advanced"]["fleet_on"] = True
    return made


class CardSourceTests(unittest.TestCase):
    def test_it_is_compiled_into_the_advanced_window(self):
        listed = [line.split("#", 1)[0].strip() for line in
                  (ac.ROOT / "advanced" / "gui" / "window.sources").read_text(encoding="utf-8").splitlines()]
        self.assertIn("advanced/gui/AdvancedFleet.cs", listed)

    def test_the_page_reads_builds_forgets_and_enables_it(self):
        page = source(PAGE)
        for call in ("FleetApplied(reply)", "ReadFleet(after)", "BuildFleet(item)", "ForgetFleetCard()",
                     "UpdateFleetButtons(idle)", "FleetCardShown(item)"):
            with self.subTest(call):
                self.assertIn(call, page)

    def test_it_draws_only_the_window_s_own_pieces_and_opens_no_window_of_its_own(self):
        """A flat list of the window's own (DrawCell), help lines, buttons: no tile, picture, icon, colour or Form."""
        card = source()
        for piece in ("MakeCard(", "NewGroup(", "List(", "ListCard(fleetList)", "HelpText(", "CardButton("):
            self.assertIn(piece, card)
        for foreign in ("new Panel", "PictureBox", "Icon", "BackColor", "Color.", "new Button", "new Label", "new Form",
                        "Tile", "DrawSubItem"):
            with self.subTest(foreign):
                self.assertNotIn(foreign, card)

    def test_no_row_has_an_action(self):
        """Read-only: no click on the list, no selection used, one save and one folder choice and no other request."""
        card = source()
        for handler in ("fleetList.Click", "fleetList.DoubleClick", "ItemActivate", "MouseClick", "SelectedItems",
                        "SelectedIndices", "ContextMenu"):
            self.assertNotIn(handler, card)
        self.assertEqual(sorted(set(re.findall(r'AdvancedCall\("([a-z-]+)"', card))), ["advanced-fleet", "advanced-fleet-save"])
        self.assertEqual(set(re.findall(r'\\"([a-z_]+)\\"', card)),
                         set(surfaces.ARGUMENTS[BridgeCommand.ADVANCED_FLEET_SAVE]))

    def test_every_word_is_a_page_key_in_every_catalog_and_says_the_same_in_english(self):
        card = source()
        used = re.findall(r'Word\(\s*"(page\.[a-z_.]+)",\s*"((?:[^"\\]|\\.)*)"', card)
        self.assertGreaterEqual(len(used), 25)
        english = statement.CATALOGS.catalog("en")
        for key, fallback in used:
            with self.subTest(key):
                self.assertIn(key, statement.PAGE_KEYS)
                self.assertEqual(english[key], fallback)
        for key in {key for key, _fallback in used}:
            for locale_file in sorted((ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales").glob("*.json")):
                self.assertTrue(json.loads(locale_file.read_text(encoding="utf-8")).get(key, "").strip(), locale_file.name)

    def test_it_says_each_word_the_engine_can_stand_on(self):
        card = source()
        for word in (fleet.UNSET, fleet.MISSING, fleet.HELD, fleet.NOT_OURS) + fleet.REFUSALS:
            with self.subTest(word):
                self.assertIn('stand == "%s"' % word, card)

    def test_it_is_not_asked_for_while_off_or_audited(self):
        body = source()
        self.assertIn("if (fleetReading || (auditing && advancedScript == null))", body)
        self.assertIn("if (!fleetOn)", body)

    def test_the_standard_window_only_declares_the_point(self):
        dashboard = (ac.ROOT / "gui" / "Dashboard.cs").read_text(encoding="utf-8")
        self.assertIn("partial void OverviewRoomAsked(ref int under);", dashboard)
        self.assertNotIn("fleet", dashboard.lower())
        self.assertNotIn("fleet", (ac.ROOT / "gui" / "DashboardPages.cs").read_text(encoding="utf-8").lower())


class PageTests(PageCase):
    @classmethod
    def scenario_overview(cls, bridge):
        """On: the list with every way a row reads; then off: the card is gone."""
        script = cls.opening(bridge, "en")
        script["advanced-fleet"] = [answer([row("desk"), row("attic", seen="old"), row("den", seen="clock"),
                                            row("hall", watcher="stopped"), row("lab", recovery="paused"),
                                            row("loft", recovery="observe_only")], ignored=3)]
        steps = [{"do": "snapshot", "reply": on_snapshot()}, {"do": "page", "name": "overview"},
                 {"do": "snapshot", "reply": on_snapshot()}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_waiting(cls, bridge):
        """The folder gone: no rows, and the line says it waits."""
        script = cls.opening(bridge, "en")
        script["advanced-fleet"] = [answer(stand="missing")]
        steps = [{"do": "page", "name": "overview"}, {"do": "snapshot", "reply": on_snapshot()}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_off(cls, bridge):
        """Never on: no card and no read of the folder."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "page", "name": "overview"}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_card(cls, bridge):
        """On, on the page: a name typed, a folder chosen, Save sends them once."""
        cls.watched(bridge, CAP, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-fleet"] = [answer(stand="unset", alias=None, folder=None)] * 3 + [answer()] * 3
        script["advanced-fleet-save"] = [answer()]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": CAP}, {"do": "look"},
                 {"do": "fleet_alias", "text": "laptop"}, {"do": "look"},
                 {"do": "fleet_folder", "path": FOLDER}, {"do": "look"}, {"do": "fleet_save"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_card_off(cls, bridge):
        """Off with a folder saved: only that this PC's file stays there."""
        script = cls.opening(bridge, "en")
        script["advanced-fleet"] = [answer(stand="unset", state="off")] * 3
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": CAP}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    def card(self, look, title):
        return next((card for card in look["cards"] if card[0] == title), None)

    def test_the_list_shows_each_way_a_row_reads(self):
        result, expected = self.of("scenario_overview")
        words = expected["words"]
        on, off = result["looks"]
        self.assertTrue(on["fleet_shown"])
        rows = {cells[0]: cells for cells in on["fleet_rows"]}
        self.assertEqual(rows["desk"][1], words["page.fleet.state.running"])
        self.assertEqual(rows["desk"][2], "2")
        self.assertEqual(rows["attic"][1], words["page.fleet.state.not_seen"])
        self.assertEqual((rows["attic"][2], rows["attic"][3]), ("", ""), "an old file's counts mean nothing now")
        self.assertRegex(rows["attic"][4], r"\d{4}-\d\d-\d\d")
        self.assertEqual(rows["den"][4], words["page.fleet.state.clock"])
        self.assertEqual(rows["hall"][1], words["page.fleet.state.stopped"])
        self.assertEqual(rows["lab"][1], words["page.fleet.state.paused"])
        self.assertEqual(rows["loft"][1], words["page.fleet.state.observing"])
        self.assertIn(words["page.fleet.ignored"].replace("{n}", "3"), on["fleet_said"])
        self.assertFalse(off["fleet_shown"], "off, the Overview is the standard window's")

    def test_it_is_read_at_most_once_a_minute(self):
        result, _expected = self.of("scenario_overview")
        self.assertEqual(len(sent(result, "advanced-fleet")), 1)

    def test_a_folder_gone_says_it_waits(self):
        result, expected = self.of("scenario_waiting")
        look = result["looks"][0]
        self.assertTrue(look["fleet_shown"])
        self.assertEqual(look["fleet_rows"], [])
        self.assertEqual(look["fleet_said"], expected["words"]["page.fleet.stand.missing"])

    def test_off_there_is_no_card_and_no_read(self):
        result, _expected = self.of("scenario_off")
        self.assertFalse(result["looks"][0]["fleet_shown"])
        self.assertEqual(sent(result, "advanced-fleet"), [])

    def test_save_is_offered_once_both_are_there_and_sends_them_once(self):
        result, expected = self.of("scenario_card")
        words = expected["words"]
        first, typed, chosen, saved = result["looks"]
        self.assertIsNotNone(self.card(first, words["page.fleet.card"]), first["cards"])
        self.assertEqual(first["fleet_folder"], words["page.fleet.no_folder"])
        self.assertIs(first["fleet_save"], False)
        self.assertIs(typed["fleet_save"], False, "no folder yet")
        self.assertEqual(chosen["fleet_folder"], FOLDER)
        self.assertIs(chosen["fleet_save"], True)
        (asked,) = sent(result, "advanced-fleet-save")
        self.assertEqual((asked["alias"], asked["folder"]), ("laptop", FOLDER))
        self.assertEqual(saved["fleet_alias"], "laptop")

    def test_off_the_card_says_its_file_stays(self):
        result, expected = self.of("scenario_card_off")
        words = expected["words"]
        card = self.card(result["looks"][0], words["page.fleet.card"])
        self.assertIsNotNone(card)
        self.assertIn(words["page.fleet.off_note"], card)
        self.assertIsNone(result["looks"][0]["fleet_save"])


if __name__ == "__main__":
    unittest.main()
