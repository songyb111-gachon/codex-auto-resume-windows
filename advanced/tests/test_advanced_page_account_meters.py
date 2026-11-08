"""The saved-accounts card's usage meters (v0.6.22 final, advanced/gui/AdvancedMeter.cs and AdvancedAccounts.cs), read as
source: a groove in the scroll bar's well, the bar in the accent below 90 per cent and the warning colour from it, an
empty groove and "not read yet" without a reading, Read usage at the card's top right and every field the window reads
one the bridge writes.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
import guiscan  # noqa: E402
from test_advanced_autoswitch_profiles import opened, sealed  # noqa: E402
from codex_auto_resume_advanced import profiles, statement  # noqa: E402
from codex_auto_resume_advanced.control import autoswitch as accounts  # noqa: E402

METER = ac.ROOT / "advanced" / "gui" / "AdvancedMeter.cs"
CARD = ac.ROOT / "advanced" / "gui" / "AdvancedAccounts.cs"
LOCALES = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales"


def source(path) -> str:
    return path.read_text(encoding="utf-8")


def code(text) -> str:
    """The source without its // comments, so a word in a comment never passes for code."""
    return re.sub(r"//[^\n]*", "", text)


class MeterTests(unittest.TestCase):
    def test_it_is_compiled_before_the_card(self):
        listed = [line.split("#", 1)[0].strip() for line in
                  (ac.ROOT / "advanced" / "gui" / "window.sources").read_text(encoding="utf-8").splitlines()]
        self.assertLess(listed.index("advanced/gui/AdvancedMeter.cs"), listed.index("advanced/gui/AdvancedAccounts.cs"))
        self.assertTrue(source(METER).startswith("// ADVANCED-EDITION-CODE:"))

    def test_the_bar_is_the_warning_colour_from_90_per_cent(self):
        """Fails with WarnAt moved or Warns' comparison turned: the 90 % bar would be in the accent."""
        meter = code(guiscan.type_body("AccountMeter", source(METER)))
        self.assertIn("internal const double WarnAt = 90.0;", meter)
        self.assertIn("return share >= WarnAt;", code(guiscan.type_body("AccountMeter", source(METER))))
        self.assertRegex(meter, r"return Warns\(share\) \? Palette\.Warning : Palette\.Accent;")
        self.assertIn("Color tone = BarColor(used);", meter)

    def test_no_reading_leaves_the_groove_empty(self):
        """Fails if the bar were drawn without a reading, or a row without one were given a share."""
        meter = code(guiscan.type_body("AccountMeter", source(METER)))
        paint = meter[meter.index("protected override void OnPaint"):]
        self.assertLess(paint.index("SoftBar.TrackFill"), paint.index("if (used < 0) return;"))
        self.assertLess(paint.index("if (used < 0) return;"), paint.index("BarColor(used)"))
        self.assertIn('meter.Used = window != null ? Number(window, "used") : -1;', code(source(METER)))
        self.assertIn('if (window == null) return Word("page.accounts.not_read", "not read yet");', code(source(CARD)))

    def test_the_groove_is_the_scroll_bar_s_well(self):
        """The design's own inset groove (SoftBar's fill and edge, the inset recipe's depth) - no colour of its own."""
        meter = code(source(METER))
        self.assertIn("Soft.Body(g, track, radius, SoftBar.TrackFill(contrast, Palette.Card), SoftBar.TrackEdge(contrast), "
                      "Palette.Depth);", meter)
        self.assertNotIn("FromArgb", meter)
        self.assertNotIn("Color.", meter.replace("Color tone", "").replace("static Color BarColor", ""))

    def test_read_usage_stands_at_the_card_s_top_right_only_while_it_stands(self):
        card = code(source(CARD))
        build = card[card.index("private void BuildAccounts("):card.index("private void ForgetAccountsCard(")]
        self.assertRegex(build, r"if \(standing\)\s*\{\s*accountsRead = MakeButton\(Word\(\"page\.accounts\.read\"")
        self.assertIn("AccountsHeading(card, accountsRead);", build)
        self.assertIn("button.Anchor = AnchorStyles.Right | AnchorStyles.Top;", code(source(METER)))
        self.assertIn('AdvancedCall("advanced-accounts-read", "{}"', card)

    def test_every_word_is_a_page_key_in_every_catalog(self):
        used = set(re.findall(r'Word\("(page\.[a-z_.]+)"', source(METER) + source(CARD)))
        self.assertTrue({"page.accounts.read", "page.accounts.five_hour", "page.accounts.weekly", "page.accounts.in_use",
                         "page.accounts.not_read", "page.accounts.unread", "page.accounts.candidate"} <= used)
        for key in sorted(used):
            with self.subTest(key):
                self.assertIn(key, statement.PAGE_KEYS)
                for catalog in sorted(LOCALES.glob("*.json")):
                    self.assertTrue(json.loads(catalog.read_text(encoding="utf-8")).get(key, "").strip(), catalog.name)


class FieldTests(unittest.TestCase):
    def answer(self) -> dict:
        folder = Path(tempfile.mkdtemp(prefix="car-account-meters-fields-"))
        self.addCleanup(lambda: shutil.rmtree(folder, ignore_errors=True))
        store = profiles.Profiles(folder, seal=sealed, open_=opened)
        store.save(json.dumps({"fixture": "two"}).encode("utf-8"), "two@example.com", "plus")
        return accounts.meters(None, store, {}, ac.NOW, usage={})

    def test_every_field_the_window_reads_is_one_the_bridge_writes(self):
        """Fails with a field renamed on either side: the window would read nothing and show no meter."""
        answer = self.answer()
        top = set(answer) | {"done", "refusal", "store", "add_state", "switched_at", "offered", "standing", "switch_state",
                             "switch_mask"}
        both = source(CARD) + source(METER)
        read_top = set(re.findall(r'(?:Str|Number|Get|Items)\(advancedAccounts, "([a-z_]+)"\)', both))
        read_row = set(re.findall(r'(?:Str|Number|Get)\(row, "([a-z_]+)"\)', both))
        read_window = set(re.findall(r'Number\(window, "([a-z_]+)"\)', both))
        self.assertTrue({"read_next_at", "read_state", "candidate", "candidate_state", "read_at"} <= read_top)
        self.assertLessEqual(read_top, top)
        self.assertTrue({"in_use", "five_hour", "weekly", "unread"} <= read_row)
        self.assertLessEqual(read_row, set(answer["profiles"][0]))
        self.assertEqual(read_window, {"used", "resets_at"})


if __name__ == "__main__":
    unittest.main()
