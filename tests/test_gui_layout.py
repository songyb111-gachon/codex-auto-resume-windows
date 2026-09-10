"""The two settings-window rules that a clipped control taught us.

The "Retry timing" ComboBox rendered without a bottom border at every display scaling
above 100%, and the cause was not drawing but measurement. Two facts about Windows Forms
produced it together:

* a ComboBox under-reports its height until it has been shown, then resizes itself to
  fit the font while keeping the position it was given; and
* `TableLayoutPanel` sizes a row from its cells' *reported* heights, so the row was
  measured from the label, and a Right-only anchor centred the editor inside it using
  the height it no longer had.

The result overhung the row by 0/2/4/6/6/9 pixels at 100/125/150/175/200/250%, and a
child is clipped to its parent, so the overhang was the bottom border.

Neither half of the fix is obvious from reading the line it sits on, so both are pinned
here. These are source-shape assertions rather than a rendering test on purpose: the
rendering was measured directly, at six scalings and against the real window at 144 DPI,
and what a test can usefully protect is the reasoning, which is what a later edit would
throw away.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "gui" / "SettingsApp.cs"


class RowLayoutTests(unittest.TestCase):
    def setUp(self):
        self.source = SETTINGS.read_text(encoding="utf-8")
        start = self.source.index("private Control NewRow(")
        self.row = self.source[start:self.source.index("private static string Humanise(", start)]

    def test_the_editor_is_anchored_to_the_top_and_not_only_to_the_right(self):
        anchors = re.findall(r"editor\.Anchor\s*=\s*([^;]+);", self.row)
        self.assertEqual(len(anchors), 1, "NewRow should set the editor anchor exactly once")
        self.assertIn("Top", anchors[0],
                      "a Right-only anchor centres the editor using a height the ComboBox "
                      "no longer has, and its bottom border is clipped away")
        self.assertIn("Right", anchors[0], "the editor still aligns to the right of its cell")

    def test_the_row_height_is_reserved_from_the_editors_own_preferred_height(self):
        # The label's margins are what make the row tall enough, because the row is
        # measured from the label's cell. A fixed margin cannot know how tall the
        # editor will turn out to be at this scaling, in this font.
        self.assertIn("editor.PreferredSize.Height", self.row,
                      "the row must be sized from the editor, not from a fixed number")
        self.assertIn("label.PreferredSize.Height", self.row,
                      "centring the label needs its own measured height")
        self.assertNotRegex(
            self.row, r"label\.Margin\s*=\s*Pad\(",
            "a Pad(...) margin here is a fixed row height again; use the measured one")

    def test_the_editor_carries_no_vertical_margin(self):
        """Measured: a vertical margin on the editor re-introduces the clipping at 125%.

        The row does not grow to accommodate it, because the row is measured from the
        label's cell and from the ComboBox's stale height - so the margin only pushes
        the editor further down inside a row that never got taller.
        """
        margins = re.findall(r"editor\.Margin\s*=\s*([^;]+);", self.row)
        self.assertEqual(len(margins), 1)
        self.assertIn("new Padding(0)", margins[0])


if __name__ == "__main__":
    unittest.main()
