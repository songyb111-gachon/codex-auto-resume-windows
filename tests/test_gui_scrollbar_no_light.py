"""The soft scroll bar's pill has no lit edge (v0.6.20 final, the owner's word of 2026-11-02).

The pill stood in its groove with the control recipe's whole lift: a drop below and to the right, and a highlight thrown
up and to the left, which read as a glow on the bar (the owner: "스크롤바에서도 빛을 없애야할 거 같더라", after the drawn
menus lost theirs). It now keeps the drop only: Elevation.StampOuter's `lights` false leaves out every outer shadow thrown
up or to the left. The buttons, switches and cards keep their highlights.

    PYTHONPATH=src python -m unittest tests.test_gui_scrollbar_no_light
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

GUI = Path(__file__).resolve().parents[1] / "gui"


class ScrollBarLightTests(unittest.TestCase):
    def setUp(self):
        self.layout = (GUI / "SoftLayout.cs").read_text(encoding="utf-8-sig")
        self.depth = (GUI / "SoftDepth.cs").read_text(encoding="utf-8-sig")

    def test_the_pill_is_stamped_without_its_highlight(self):
        """Fails with the pill's lift stamped whole again."""
        self.assertIn('Elevation.StampOuter(g, thumb, "control", knob, groove, false);', self.layout)
        self.assertNotIn('Elevation.StampOuter(g, thumb, "control", knob, groove);', self.layout)

    def test_a_highlight_is_an_outer_shadow_thrown_up_or_to_the_left(self):
        body = self.depth[self.depth.index("private static bool IsLight("):]
        body = body[:body.index("}") + 1]
        self.assertIn("!inset && (dx < 0 || dy < 0)", body)
        self.assertIn("(lights || !IsLight(recipe, index))", self.depth)

    def test_every_other_lift_keeps_its_highlight(self):
        """Only the scroll bar asks for no light: every other outer stamp is the whole recipe."""
        calls = re.findall(r"Elevation\.StampOuter\(([^;]*)\);", "\n".join(
            path.read_text(encoding="utf-8-sig") for path in sorted(GUI.rglob("*.cs"))))
        without = [call for call in calls if call.rstrip().endswith("false")]
        self.assertEqual(without, ['g, thumb, "control", knob, groove, false'])


if __name__ == "__main__":
    unittest.main()
