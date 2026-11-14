"""The owner, 2026-11-14, compared both looks and kept these three fields off the card (the second round's F9 set aside for them).

The Statistics page's Period row, the Log dialog's search row and the advanced Find a conversation dialog's search row stand
as they did in v0.6.23-beta.2: the Period row on the page's ground above the cards, the two search rows on the dialog
itself above the list's card. Every other field still stands on a card (tests/test_gui_v0623_motion.py, DialogBodyCard).

Read from the C# source through tests/guiscan.py, by braces: a member's body, never a slice by searched text. No window is
built here, so this is not a GUI module and needs no GUI lock.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

import guiscan

ROOT = Path(__file__).resolve().parents[1]


def find_body() -> str:
    """BuildFind of the advanced edition, which `gui/window.sources` does not list: its own file, by its braces."""
    text = (ROOT / "advanced" / "gui" / "AdvancedFind.cs").read_text(encoding="utf-8")
    match = re.search(r"(?m)^[ \t]*(?:\w+[ \t]+)*Form[ \t]+BuildFind[ \t]*\(", text)
    if match is None:
        raise guiscan.ScanError("AdvancedFind.cs has no BuildFind")
    return guiscan._block(text, match.start())


class PeriodOnTheGround(unittest.TestCase):
    def test_the_period_row_is_added_to_the_page_not_to_a_card(self):
        body = guiscan.member_body("SettingsForm", "BuildStatistics")
        self.assertIn("page.Controls.Add(top);", body, "the Period row goes on the page's ground")
        self.assertIn("top.Dock = DockStyle.Top;", body)
        self.assertNotIn("SoftCard", body, "no card wraps the Period row")
        self.assertNotIn("periodCard", body)
        self.assertNotIn("periodGround", body)

    def test_the_period_row_is_not_given_the_cards_own_material(self):
        body = guiscan.member_body("SettingsForm", "BuildStatistics")
        row = body[:body.index("var label")]
        self.assertNotIn("BackColor = Card", row)


class SearchOnTheDialog(unittest.TestCase):
    def test_the_log_dialog_adds_its_search_row_to_the_dialog(self):
        body = guiscan.member_body("SettingsForm", "BuildLogs")
        self.assertIn("dialog.Controls.Add(top);", body)
        self.assertIn("DialogListCard(view)", body, "the list still stands on its card")

    def test_find_a_conversation_adds_its_search_row_to_the_dialog(self):
        body = find_body()
        self.assertIn("dialog.Controls.Add(top);", body)
        self.assertIn("DialogListCard(findList)", body, "the list still stands on its card")

    def test_no_search_row_is_put_onto_the_lists_card(self):
        for name, body in (("BuildLogs", guiscan.member_body("SettingsForm", "BuildLogs")),
                           ("BuildFind", find_body())):
            with self.subTest(name):
                self.assertNotIn("SearchOnCard", body)
                self.assertNotRegex(body, r"listGround\.Controls\.Add\(top\)")

    def test_the_find_dialog_holds_its_status_line_to_the_dialogs_width(self):
        self.assertIn("MaximumSize = new Size(Px(across - 32), 0);", find_body())

    def test_no_search_on_card_helper_exists(self):
        self.assertNotIn("SearchOnCard", guiscan.whole())
        self.assertNotIn("SearchOnCard", (ROOT / "advanced" / "gui" / "AdvancedFind.cs").read_text(encoding="utf-8"))
        with self.assertRaises(guiscan.ScanError):
            guiscan.member_body("SettingsForm", "SearchOnCard")


if __name__ == "__main__":
    unittest.main()
