"""v0.6.11: every focus ring stands 3:1 off what it is drawn on, in every design and theme (J12).

A focus ring is the boundary of a control, so it is held to 3:1 - not to text's 7:1 - against every colour it
touches: the ground round it and the ground inside it, which is a control's own fill where the ring is its
edge. Where each surface draws its rings, and on what, is written out below, one line a ring, and held in
every design in both themes; the sources are held to drawing each ring in the one focus colour, 2 px wide, so
the table is the whole of it. The popup's rings are measured too, off its own drawing.

High Contrast draws in the colours the person chose, which no palette here decides.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import guiscan  # noqa: E402
from codex_auto_resume import brand  # noqa: E402
from codex_auto_resume.mcp import panel as mcpui  # noqa: E402

# Where each surface draws a focus ring, and every ground it touches there - a palette token, or "card" for
# a card's own ground (brand.card_ground).
RINGS = {
    "window": {
        # Soft.Ring, round a lifted face with brand's offset: a button, a switch, a check box's box, a choice
        # card - all on a card - and a tab, on the header's card or the Settings list's.
        "a control on its card": ("card",),
        "a tab": ("card", "canvas", "inset"),
        # Soft.InsetWell's edge in the focus colour: a drop-down, a number, a text box, between its well and
        # the card round it.
        "a field's edge": ("inset", "card"),
        # SoftDropList: the item the keys are on, a pill on the list's card, chosen (inset) or not (raised).
        "a drop-down's item": ("card", "inset", "raised"),
        # A list's chosen row: its mark, on the row pressed into the inset colour (DrawCell).
        "a list's chosen row": ("inset",),
    },
    "popup": {
        # A task's switch, round its line on the task's raised tile; a button, on the card.
        "a task's switch": ("raised",),
        "a button": ("card",),
    },
    "panel": {
        # :focus-visible's outline, 2 px out: a control on its card or on a raised tile (the master switch, a
        # waiting task), a field's well, and the save bar on the page's canvas.
        "a control": ("card", "raised", "inset", "canvas"),
        # A drop-down's list: the item the keys are on, on the list's raised card.
        "a drop-down's item": ("raised", "inset"),
    },
}
# The notification card draws no ring: it never takes the keyboard (WS_EX_NOACTIVATE), and its buttons are
# the toast's, which Windows reaches with its own keys.


def ground(token, theme, design):
    return brand.card_ground(theme, design) if token == "card" else brand.palette(theme, design)[token]


class FocusContrastTests(unittest.TestCase):
    def test_every_ring_stands_three_to_one_off_everything_it_touches(self):
        for design in brand.DESIGNS:
            for theme in brand.THEMES:
                focus = brand.palette(theme, design)["focus"]
                for surface, rings in RINGS.items():
                    for ring, grounds in rings.items():
                        for token in grounds:
                            with self.subTest(design=design, theme=theme, surface=surface, ring=ring, on=token):
                                self.assertGreaterEqual(brand.contrast(focus, ground(token, theme, design)), 3.0)

    def test_the_window_draws_every_ring_in_the_one_focus_colour_two_pixels_wide(self):
        controls = guiscan.controls()
        self.assertIn("using (var pen = new Pen(Palette.Focus, width))", controls, "Soft.Ring")
        self.assertIn("if (focused) Edge(g, face, radius, Palette.Focus, PxF(Brand.FocusWidth));", controls,
                      "Soft.InsetWell")
        self.assertIn("using (var pen = new Pen(Palette.Focus, PxF(2)))", controls, "Soft.FocusRing")
        self.assertIn("using (var pen = new Pen(Palette.Contrast ? ink : Palette.Focus, Soft.PxF(2)))", guiscan.dashboard(),
                      "a list's chosen row, in High Contrast in the row's own text colour")
        self.assertEqual(brand.LAYOUT["focus_width"], 2)
        every = guiscan.settings() + guiscan.dashboard() + controls
        pens = re.findall(r"new Pen\(([^,]+),", every)
        for colour in pens:
            if "Focus" in colour:
                self.assertIn(colour.strip(), ("Palette.Focus", "Palette.Contrast ? ink : Palette.Focus"))

    def test_the_panel_draws_every_ring_as_one_outline_in_the_focus_colour(self):
        style = mcpui._STYLE
        outlines = re.findall(r"outline:\s*([^;}]+)", style)
        rings = [outline.strip() for outline in outlines if outline.strip() != "none"]
        self.assertTrue(rings)
        for outline in rings:
            with self.subTest(outline):
                self.assertEqual(outline, "2px solid var(--focus)")
        self.assertIn(":focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }", style)


def _hex(rgb):
    return "#%02X%02X%02X" % rgb


@unittest.skipUnless(os.name == "nt", "the popup draws with GDI")
class PopupRingTests(unittest.TestCase):
    """The popup's rings as drawn: the ring is the focus colour, and 3:1 off the ground on each side of it."""

    def test_each_ring_as_drawn_stands_off_its_ground_in_every_design_and_theme(self):
        from codex_auto_resume import interface
        from codex_auto_resume.ui import popup
        import test_tray_popup as base
        renderer = popup.Renderer()
        try:
            vm = popup.view_model(base.WindowsTests.ROWS, base.STATUS, interface.STRINGS["en"], base.NOW)
            scale = 2.0
            plan = renderer.layout(vm, scale, "en")
            width = plan["size"][0]
            ring = max(2.0, 2.0 * scale)
            grow = ring + max(1.0, scale)
            for design in brand.DESIGNS:
                for theme in brand.THEMES:
                    renderer.theme, renderer.design, renderer.contrast = theme, design, False
                    focus = brand.rgb(brand.palette(theme, design)["focus"])
                    for target in popup.focus_order(plan["targets"]):
                        pixels = renderer.draw(vm, plan, focus=target).pixels()

                        def pixel(x, y):
                            index = (y * width + x) * 4
                            return pixels[index + 2], pixels[index + 1], pixels[index]

                        rect = next(item["rect"] for item in plan["items"]
                                    if item["kind"] == "focusable" and item["target"] == target)
                        # Leftward from the focused rectangle across its ring, at the middle of its height: the
                        # pixels drawn whole in the focus colour, and the ground on either side of them.
                        y = (rect[1] + rect[3]) // 2
                        line = [pixel(rect[0] - distance, y) for distance in range(0, int(3 * grow))]
                        matches = [distance for distance, colour in enumerate(line)
                                   if max(abs(a - b) for a, b in zip(colour, focus)) <= 2]
                        # The longest unbroken run is the ring; a lone pixel of ink in Plain's colour is not.
                        runs, current = [], []
                        for distance in matches:
                            if current and distance != current[-1] + 1:
                                runs.append(current)
                                current = []
                            current.append(distance)
                        runs.append(current)
                        run = max(runs, key=len)
                        with self.subTest(design=design, theme=theme, target=target[0]):
                            self.assertGreaterEqual(len(run), int(ring) - 1, line)
                            inside, outside = line[run[0] - 2], line[run[-1] + 2]
                            self.assertGreaterEqual(brand.contrast(_hex(focus), _hex(outside)), 3.0, (focus, outside))
                            self.assertGreaterEqual(brand.contrast(_hex(focus), _hex(inside)), 3.0, (focus, inside))
        finally:
            renderer.close()


if __name__ == "__main__":
    unittest.main()
