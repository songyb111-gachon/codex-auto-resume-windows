"""The drawn tray-icon menu has no bright edge round it (v0.6.20 final, the owner's word of 2026-11-01).

The menu is the product's neumorphic card, but the raised look's lit edge does not belong round a menu: in light the
card's highlight - a white glow up and to the left, `shadow_light` - made a bright halo round it, and in dark the card's
one-pixel top light lay inside its border (the owner: "트레이 우클릭했을 때 뜨는거 ... 가장자리를 밝게 하는 것이 남아있더라.
없어야 하는 부분인데"). Its drop shadow, ground, hairline, items and the item in hand stay as they were, in both themes, in both
designs, and mirrored in Arabic and Hebrew. The popup and the window's cards keep their lit edges: only the menu asks the
renderer for none (`_lift(..., lights=False)`, no `_inner`).

The renderer draws into memory here, as test_tray_menu_drawn's LookTests do: nothing is shown and nothing is captured.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import brand, interface  # noqa: E402
from codex_auto_resume.ui import popup, tray  # noqa: E402

NOW = 1_800_000_000.0
LOCALES = ("en", "ar", "he")


@unittest.skipUnless(os.name == "nt", "the drawn menu is a Windows window")
class NoGlowTests(unittest.TestCase):
    def setUp(self):
        self.renderer = popup.MenuRenderer()
        self.addCleanup(self.renderer.close)

    def draw(self, theme="light", design="soft", locale="en", selected=None, scale=1.0):
        renderer = self.renderer
        renderer.theme, renderer.contrast, renderer.design = theme, False, design
        items = tray.menu_items({"enabled": True, "waiting": 2}, interface.STRINGS[locale], NOW, True, None)
        plan = renderer.menu_layout(items, scale, locale)
        return plan, bytes(renderer.draw_menu(plan, selected).pixels())

    @staticmethod
    def pixel(plan, pixels, x, y):
        index = (y * plan["size"][0] + x) * 4
        blue, green, red, alpha = pixels[index:index + 4]
        return red, green, blue, alpha

    def outside(self, plan, pixels):
        """Every pixel of the window that is round the card, not on it, with its colour taken out of its alpha."""
        width, height = plan["size"]
        left, top, right, bottom = plan["card"]
        found = []
        for y in range(height):
            for x in range(width):
                if left <= x < right and top <= y < bottom:
                    continue
                red, green, blue, alpha = self.pixel(plan, pixels, x, y)
                if alpha:
                    found.append((x, y, tuple(min(255, int(round(value * 255.0 / alpha))) for value in (red, green, blue)), alpha))
        return found

    def test_round_the_card_there_is_only_the_drop_shadow_in_the_shadow_s_colour_never_a_glow(self):
        for theme in ("light", "dark"):
            dark = brand.rgb(brand.palette(theme)["shadow_dark"])
            for locale in LOCALES:
                with self.subTest(theme=theme, locale=locale):
                    plan, pixels = self.draw(theme, locale=locale)
                    around = self.outside(plan, pixels)
                    self.assertGreater(len(around), 100, "the drop shadow is still there")
                    # Where the shadow is strong enough for its colour to be read back out of a premultiplied pixel.
                    bright = [(x, y, colour) for x, y, colour, alpha in around
                              if alpha >= 32 and max(abs(a - b) for a, b in zip(colour, dark)) > 12]
                    self.assertEqual(bright[:5], [], "a pixel round the card is lit, not the drop shadow's colour")

    def test_the_drop_shadow_still_falls_below_and_to_the_right(self):
        plan, pixels = self.draw("light")
        left, top, right, bottom = plan["card"]
        middle_x, middle_y = (left + right) // 2, (top + bottom) // 2
        below = self.pixel(plan, pixels, middle_x, bottom + 3)[3]
        above = self.pixel(plan, pixels, middle_x, top - 3)[3]
        self.assertGreater(below, above, "deeper below than above, as the cards' own lift")
        self.assertGreater(self.pixel(plan, pixels, right + 3, middle_y)[3], 0)

    def test_in_dark_the_card_has_no_one_pixel_top_light_inside_its_border(self):
        plan, pixels = self.draw("dark")
        left, top, right, bottom = plan["card"]
        ground = brand.rgb(brand.card_ground("dark", "soft"))
        border = max(1, int(round(1.0)))
        for x in range((left + right) // 2 - 20, (left + right) // 2 + 20):
            with self.subTest(x=x):
                self.assertEqual(self.pixel(plan, pixels, x, top + border)[:3], ground)

    def test_the_rest_of_the_menu_is_as_it_was(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                plan, pixels = self.draw(theme)
                card = plan["card"]
                stop = next(item for item in plan["items"] if item["kind"] == "item" and item["id"] == tray.MENU_STOP)
                x, y = (card[0] + card[2]) // 2, (stop["rect"][3] + card[3]) // 2
                self.assertEqual(self.pixel(plan, pixels, x, y), brand.rgb(brand.card_ground(theme, "soft")) + (255,))
        plan, idle = self.draw("light")
        _, held = self.draw("light", selected=2)
        item = next(item for item in plan["items"] if item.get("index") == 2)
        at = (item["rect"][0] + 6, (item["rect"][1] + item["rect"][3]) // 2)
        self.assertEqual(self.pixel(plan, held, *at)[:3], brand.rgb(brand.palette("light")["raised"]), "the item in hand rises")
        self.assertNotEqual(self.pixel(plan, idle, *at), self.pixel(plan, held, *at))

    def test_a_design_without_depth_has_none_and_still_none(self):
        plan, pixels = self.draw("light", design="classic")
        self.assertEqual(self.outside(plan, pixels), [])


class SourceTests(unittest.TestCase):
    def test_only_the_menu_leaves_the_lit_edge_out(self):
        from codex_auto_resume.ui.popup import menuwindow, renderer
        menu = Path(menuwindow.__file__).read_text(encoding="utf-8")
        self.assertIn('self._lift(paint, "card", card, radius, scale, lights=False)', menu)
        self.assertNotIn("self._inner(paint", menu)
        base = Path(renderer.__file__).read_text(encoding="utf-8")
        self.assertIn("def _lift(self, paint, recipe, rect, radius, scale, lights=True):", base)
        self.assertNotIn("lights=False", base.replace("`lights` False", ""), "the popup and the cards keep their highlights")


if __name__ == "__main__":
    unittest.main()
