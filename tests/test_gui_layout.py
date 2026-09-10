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


class WatcherStartReportingTests(unittest.TestCase):
    """The window may not say the watcher is running on the strength of a launch."""

    def setUp(self):
        self.source = SETTINGS.read_text(encoding="utf-8")
        start = self.source.index("private void StartWatcher()")
        # Both halves: the click handler that dispatches, and the continuation that
        # BeginInvoke brings back to the UI thread.
        self.method = self.source[start:self.source.index("private void Save()", start)]

    def test_it_does_not_wait_a_fixed_time_and_hope(self):
        self.assertNotIn("Thread.Sleep", self.method,
                         "a fixed wait is both slower than an ordinary start and shorter "
                         "than a slow one; the engine now waits for the real answer")

    def test_the_wait_does_not_happen_on_the_ui_thread(self):
        """A guard the first version of this needed and did not have.

        Removing `Thread.Sleep` did not remove the wait: it moved into the bridge call,
        which starts python.exe and blocks until it exits, and the engine behind it now
        waits up to six seconds for the watcher to report in. On the click handler that
        is six seconds without pumping messages, and Windows retitles a window that has
        not pumped for five "Not Responding" and paints a grey ghost of it. The old test
        passed throughout, because it only looked for the word `Sleep`.
        """
        self.assertIn("QueueUserWorkItem", self.method,
                      "the blocking call must not run on the click handler")
        self.assertIn("BeginInvoke", self.method,
                      "the answer has to come back to the UI thread to touch a control")
        call = self.method.index('bridge.Call("start-watcher"')
        worker = self.method.index("QueueUserWorkItem")
        self.assertLess(worker, call, "the call must be inside the worker, not before it")

    def test_it_reads_the_state_the_engine_reported(self):
        self.assertIn('"state"', self.method,
                      "the window must report what the engine observed, not that the call "
                      "returned")
        for state in ('"running"', '"already-running"', '"exited"'):
            self.assertIn(state, self.method, state)


class FooterTests(unittest.TestCase):
    """The strip along the bottom is as tall as what it holds.

    A user reported the three buttons losing their bottom borders. The cause was not the
    buttons: the strip's height was `MeasureText("Ag") + Px(46)`, a text measurement plus
    a constant, and the row of buttons needed six pixels more than that arithmetic left -
    the FlowLayoutPanel's default margin is 3px on every side and does not scale with the
    display. The strip came out two pixels short, the row was clipped to 46 of its 48
    pixels, and the last thing inside those two rows was every button's own bottom border.

    Measured from a layout dump of the running window at 150%: the strip was 94 tall with
    42 of padding, giving 52 to a grid whose preferred height was 54.
    """

    def setUp(self):
        self.source = SETTINGS.read_text(encoding="utf-8")
        start = self.source.index("private void BuildFooter()")
        self.method = self.source[start:self.source.index("private void ", start + 10)]

    def test_the_height_is_measured_rather_than_derived_from_a_font(self):
        self.assertNotIn('MeasureText("Ag", Font).Height + Px(46)', self.method,
                         "a strip sized by a formula cannot know how tall an AutoSize "
                         "button becomes once the font is applied")
        self.assertIn("PreferredSize.Height", self.method,
                      "the strip must be sized from what it contains")
        self.assertIn("footer.Padding.Vertical", self.method,
                      "and must add the padding it declares")

    def test_the_button_row_declares_its_margin(self):
        self.assertIn("row.Margin = new Padding(0)", self.method,
                      "the default 3px margin does not scale and is what went missing")

    def test_the_height_is_set_after_the_content_exists(self):
        add = self.method.index("footer.Controls.Add(grid)")
        height = self.method.index("footer.Height =")
        self.assertLess(add, height,
                        "measuring before the children are added measures nothing")


if __name__ == "__main__":
    unittest.main()
