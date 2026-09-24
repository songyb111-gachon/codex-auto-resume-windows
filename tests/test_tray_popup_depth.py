"""v0.6.5, requirement 11: depth inside the notification-area popup.

Until v0.6.5 the popup's card was neumorphic and everything on it was flat. Now a task tile is
raised off the card (brand's control lift - a soft drop and a light top edge; in dark, the drop and
the one-pixel top light of brand's dark card, on `raised`, a step brighter than the card's ground),
the counts and an empty list sit in sunken wells as the panel's fields do, a pressed button sinks,
and a switch's track is a well. High Contrast draws none of it. These tests hold the recipe to
brand's own shadows and grounds (the panel is the reference: a tile and a resting button stand on
one ground there), the layout to one well for the counts and one for the quiet line - with no count
label cut inside a word, in any language or scale - and the pixels to what each part is meant to
look like, in light, dark and High Contrast; and the notification card, which is drawn by the same
renderer, gets the same raised tile.
"""
from __future__ import annotations

import os
import time
import unittest

from codex_auto_resume import brand, interface, l10n
from codex_auto_resume.ui import popup
from test_tray_popup import EN, NOW, STATUS, measure, row

ROWS = [row("a", "waiting_reset", "usage_limit", eligible=NOW + 3600, reset=NOW + 3600, name="Add translations"),
        row("b", eligible=NOW + 42, name="Fix flaky CI"),
        row("c", eligible=NOW + 90, enabled=False, name="Refactor the retry ladder")]
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)


def luminance(colour):
    return 0.2126 * colour[0] + 0.7152 * colour[1] + 0.0722 * colour[2]


def words(text):
    """The runs of a label no line may break inside: its words. (Every count label in the nine
    catalogs without a space is two to four Chinese or Japanese characters, which fit whole.)"""
    return str(text).split()


def count_labels(plan):
    return [item for item in plan["items"] if item["kind"] == "text" and item["role"] == "label"]


def scaled(scale):
    """The tests' stand-in for DrawTextW (test_tray_popup.measure) at a display scale."""
    def measure_at(role, text, width, wrap):
        size = popup.ROLES[role][0] * scale
        advance, line = size * 0.55, int(size * 1.4)
        natural = int(len(text) * advance)
        if not wrap:
            return natural, line
        lines = max(1, -(-len(text) // max(1, int(width // advance))))
        return min(natural, int(width)), lines * line
    return measure_at


class RecipeTests(unittest.TestCase):
    def test_the_tile_recipe_is_brand_shaped_and_made_of_brand_tokens(self):
        for theme in brand.THEMES:
            shadows = popup.recipe_shadows("tile", theme)
            self.assertTrue(shadows, theme)
            for shadow in shadows:
                with self.subTest(theme=theme, shadow=shadow):
                    self.assertIsInstance(shadow, brand.Shadow)
                    self.assertIn(shadow.token, brand.palette(theme))
                    self.assertTrue(0.0 < shadow.alpha <= 1.0)
                    self.assertGreaterEqual(shadow.blur, 0)

    def test_brand_s_recipes_are_still_brand_s(self):
        for theme in brand.THEMES:
            for recipe in ("card", "control", "inset"):
                self.assertEqual(popup.recipe_shadows(recipe, theme), brand.shadows(recipe, theme))

    def test_light_lifts_a_tile_with_a_drop_and_a_highlight(self):
        shadows = popup.recipe_shadows("tile", "light")
        self.assertIn("shadow_dark", [shadow.token for shadow in shadows if not shadow.inset and shadow.dy > 0])
        self.assertIn("shadow_light", [shadow.token for shadow in shadows if not shadow.inset and shadow.dy < 0])
        self.assertEqual(popup.tile_ground("light"), brand.LIGHT["raised"])

    def test_dark_is_the_panel_s_dark_recipe_at_a_tile_s_scale(self):
        """A drop alone is lost on a dark card at this size: a top light inside the hairline, a drop
        under it, and a ground a step brighter than the card's - `raised`, as the panel's rows are."""
        shadows = popup.recipe_shadows("tile", "dark")
        tops = [shadow for shadow in shadows if shadow.inset and shadow.dy > 0 and shadow.blur == 0]
        self.assertEqual(len(tops), 1)
        ground = popup.tile_ground("dark")
        self.assertGreater(brand.luminance(brand.DARK[tops[0].token]), brand.luminance(ground))
        self.assertTrue(any(not shadow.inset and shadow.dy > 0 and shadow.token == "shadow_dark" for shadow in shadows))
        self.assertGreater(brand.luminance(ground), brand.luminance(brand.card_ground("dark")))

    def test_a_tile_wears_only_brand_s_own_shadows_on_brand_s_raised_ground(self):
        """The panel is the reference, and its rows and its buttons stand on one `raised` ground with
        brand's recipes and nothing else. A popup tile is lifted by brand's control recipe - what the
        panel's buttons and segments wear - and in dark also by the one-pixel top light of brand's
        dark card: no number of the popup's own, and no ground of its own that would put a tile a
        step above the resting button under it."""
        for theme in brand.THEMES:
            with self.subTest(theme=theme):
                ours = {shadow for recipe in brand.SHADOWS[theme].values() for shadow in recipe}
                for shadow in popup.recipe_shadows("tile", theme):
                    self.assertIn(shadow, ours)
                self.assertEqual(popup.tile_ground(theme), brand.palette(theme)["raised"])
        self.assertEqual(popup.recipe_shadows("tile", "light"), brand.shadows("control", "light"))
        dark = popup.recipe_shadows("tile", "dark")
        self.assertEqual([shadow for shadow in dark if not shadow.inset], list(brand.shadows("control", "dark")))
        self.assertEqual([shadow for shadow in dark if shadow.inset],
                         [shadow for shadow in brand.shadows("card", "dark") if shadow.inset])

    def test_a_tile_s_shadow_stays_small_enough_for_the_gap_between_tiles(self):
        """Tiles stand eight pixels apart: a shadow reaching much further smears into the next one."""
        for theme in brand.THEMES:
            for shadow in popup.recipe_shadows("tile", theme):
                if not shadow.inset:
                    self.assertLessEqual(max(abs(shadow.dx), abs(shadow.dy)) + 1.5 * shadow.blur,
                                         2 * brand.SPACING["s"], (theme, shadow))


class LayoutTests(unittest.TestCase):
    def plan(self, rows=ROWS, **kwargs):
        vm = popup.view_model(rows, STATUS, EN, NOW, **kwargs)
        return vm, popup.layout(vm, 1.0, measure)

    def test_the_counts_sit_in_one_well_with_a_hairline_between_them(self):
        vm, plan = self.plan()
        wells = [item for item in plan["items"] if item["kind"] == "well"]
        self.assertEqual(len(wells), 1)
        well = wells[0]["rect"]
        counted = [item for item in plan["items"] if item["kind"] == "text" and item["role"] in ("label", "value")]
        self.assertEqual(len(counted), 6)
        pad = brand.SPACING["m"]
        for item in counted:
            left, top, right, bottom = item["rect"]
            self.assertGreaterEqual(left, well[0] + pad)
            self.assertLessEqual(right, well[2] - pad)
            self.assertGreaterEqual(top, well[1] + pad)
            self.assertLessEqual(bottom, well[3] - pad)
        rules = [item for item in plan["items"] if item["kind"] == "rule"]
        self.assertEqual(len(rules), 2, "a divider between the three values, and no rule across the card")
        for rule in rules:
            self.assertTrue(well[0] < rule["rect"][0] < well[2] and well[1] < rule["rect"][1] < well[3])
        # The tasks come after the well, a spacing step below it.
        first = next(item for item in plan["items"] if item["kind"] == "panel")
        self.assertEqual(first["rect"][1] - well[3], brand.SPACING["m"])

    def test_nothing_to_list_is_said_from_a_well_and_so_is_a_failed_read(self):
        for vm_rows, kwargs in (([], {}), (None, {"error": EN["pending.unavailable"]})):
            vm, plan = self.plan(rows=vm_rows, **kwargs)
            quiet = vm["error"] or vm["empty"]
            self.assertTrue(quiet)
            text = next(item for item in plan["items"] if item["kind"] == "text" and item["text"] == quiet)
            wells = [item["rect"] for item in plan["items"] if item["kind"] == "well"]
            self.assertEqual(len(wells), 2, "the counts' well and the quiet line's")
            self.assertTrue(any(rect[0] <= text["rect"][0] and text["rect"][2] <= rect[2]
                                and rect[1] <= text["rect"][1] and text["rect"][3] <= rect[3] for rect in wells))
            self.assertEqual([item for item in plan["items"] if item["kind"] == "panel"], [])

    def test_the_tasks_are_still_tiles(self):
        _, plan = self.plan()
        self.assertEqual(len([item for item in plan["items"] if item["kind"] == "panel"]), 3)

    def assert_columns(self, plan, measure_with):
        """The three counts side by side in order, inside the well's padding, a divider between each
        two, and no label's word wider than its column (GDI would cut it in two)."""
        well = next(item["rect"] for item in plan["items"] if item["kind"] == "well")
        labels = count_labels(plan)
        self.assertEqual(len(labels), 3)
        pad = brand.SPACING["m"] * plan["scale"]
        self.assertGreaterEqual(labels[0]["rect"][0], well[0] + int(pad))
        self.assertLessEqual(labels[-1]["rect"][2], well[2] - int(pad))
        rules = sorted(item["rect"][0] for item in plan["items"] if item["kind"] == "rule")
        for (before, after), rule in zip(zip(labels, labels[1:]), rules):
            self.assertLess(before["rect"][2], rule)
            self.assertLess(rule, after["rect"][0])
        for item in labels:
            left, _, right, _ = item["rect"]
            for word in words(item["text"]):
                self.assertLessEqual(measure_with("label", word, 100000, False)[0], right - left,
                                     (item["text"], word, plan["scale"]))
        return labels

    def test_a_count_label_is_never_cut_inside_a_word(self):
        """The well's padding comes out of the three columns: at an equal third, the German
        'In Wiederherstellung' has a word wider than its column, and GDI cut it as
        'Wiederherstellun' / 'g'. The column that needs more takes it from the others."""
        vm = popup.view_model(ROWS, STATUS, l10n.catalog("de"), NOW)
        for scale in SCALES:
            with self.subTest(scale=scale):
                plan = popup.layout(vm, scale, scaled(scale))
                labels = self.assert_columns(plan, scaled(scale))
                widths = [item["rect"][2] - item["rect"][0] for item in labels]
                self.assertEqual(widths[0], widths[2], "the two that fit share what is left alike")
                self.assertGreater(widths[1], widths[0])

    def test_columns_are_shared_equally_until_one_needs_more(self):
        self.assertEqual(popup.share_columns(256, [40, 60, 50]), [85, 85, 85])
        self.assertEqual(popup.share_columns(256, [40, 90, 50]), [83, 90, 83])
        self.assertEqual(popup.share_columns(256, [40, 110, 100]), [46, 110, 100], "each wide one is given its need")
        self.assertEqual(popup.share_columns(256, [80, 110, 60]), [80, 110, 66], "until what is left fits the rest")
        self.assertEqual(popup.share_columns(256, [100, 120, 110]), [77, 93, 85],
                         "needs that cannot all fit are cut down together, by one fraction")
        for needs in ([0, 0, 0], [256, 0, 0], [85, 86, 85], [300, 1, 1]):
            self.assertLessEqual(sum(popup.share_columns(256, needs)), 256, needs)

    def test_a_piece_no_line_may_break_is_a_word_or_one_chinese_or_japanese_character(self):
        self.assertEqual(popup.unbroken("In Wiederherstellung"), ["In", "Wiederherstellung"])
        self.assertEqual(popup.unbroken("복구 중"), ["복구", "중"])
        self.assertEqual(popup.unbroken("次の確認"), ["次", "の", "確", "認"])
        self.assertEqual(popup.unbroken(""), [""])

    def test_labels_that_fit_keep_three_equal_columns(self):
        vm = popup.view_model(ROWS, STATUS, EN, NOW)
        for scale in SCALES:
            plan = popup.layout(vm, scale, scaled(scale))
            widths = {item["rect"][2] - item["rect"][0] for item in self.assert_columns(plan, scaled(scale))}
            self.assertEqual(len(widths), 1, scale)


@unittest.skipUnless(os.name == "nt", "the popup's renderer is GDI+")
class PixelTests(unittest.TestCase):
    def setUp(self):
        self.renderer = popup.Renderer()
        self.addCleanup(self.renderer.close)

    def draw(self, theme, *, rows=ROWS, scale=1.0, contrast=False, pressed=None):
        self.renderer.theme, self.renderer.contrast = theme, contrast
        vm = popup.view_model(rows, STATUS, EN, NOW)
        plan = self.renderer.layout(vm, scale, "en")
        canvas = self.renderer.draw(vm, plan, frame=popup.halo(vm["state"], 0, reduced=True), pressed=pressed)
        pixels, width = canvas.pixels(), plan["size"][0]

        def pixel(x, y):
            index = (int(y) * width + int(x)) * 4
            return pixels[index + 2], pixels[index + 1], pixels[index]
        return plan, pixel

    @staticmethod
    def tiles(plan):
        return [item["rect"] for item in plan["items"] if item["kind"] == "panel"]

    def test_a_tile_and_the_resting_button_under_it_stand_on_one_ground(self):
        """As in the panel, where a row and a button are both `raised`: in dark the tiles were a step
        brighter than 'Pause recovery', which then looked sunk below them."""
        for theme in brand.THEMES:
            for scale in (1.0, 2.0):
                plan, pixel = self.draw(theme, rows=ROWS[:1], scale=scale)
                left, top, right, bottom = self.tiles(plan)[0]
                hairline = max(1, int(round(scale)))
                tile = pixel((left + right) // 2 - 40 * scale, top + hairline + 3 * scale)
                b_left, b_top, b_right, b_bottom = dict(plan["targets"])[("toggle",)]
                button = pixel(b_left + 14 * scale, (b_top + b_bottom) // 2)
                with self.subTest(theme=theme, scale=scale):
                    self.assertEqual(tile, button)
                    self.assertEqual(tile, brand.rgb(brand.palette(theme)["raised"]))

    def test_light_tiles_lift_off_the_card(self):
        for scale in (1.0, 1.5, 2.0):
            plan, pixel = self.draw("light", scale=scale)
            surface = brand.rgb(brand.LIGHT["surface"])
            tiles = self.tiles(plan)
            for upper, lower in zip(tiles, tiles[1:]):
                middle = (upper[0] + upper[2]) // 2
                # Under a tile, in the gap before the next: its drop, darker than the card.
                below = pixel(middle, upper[3] + max(1, int(2 * scale)))
                self.assertLess(luminance(below), luminance(surface) - 2, (scale, below))
                # The next tile's highlight never lies across this tile's bottom edge.
                self.assertEqual(pixel(middle, upper[3] - 1), brand.rgb(brand.LIGHT["line"]), scale)
            # Inside a tile: its own ground.
            left, top, right, bottom = tiles[0]
            self.assertEqual(pixel((left + right) // 2 - 40 * scale, top + 3 * scale), brand.rgb(popup.tile_ground("light")))

    def test_dark_tiles_have_a_top_light_a_brighter_ground_and_a_drop(self):
        for scale in (1.0, 1.5, 2.0):
            plan, pixel = self.draw("dark", scale=scale)
            ground = brand.rgb(popup.tile_ground("dark"))
            card = brand.rgb(brand.card_ground("dark"))
            hairline = max(1, int(round(scale)))
            left, top, right, bottom = self.tiles(plan)[0]
            middle = (left + right) // 2 - int(40 * scale)
            self.assertEqual(pixel(middle, top + hairline + 3 * scale), ground, scale)
            self.assertGreater(luminance(pixel(middle, top + hairline)), luminance(ground) + 2, "the top light")
            self.assertLess(luminance(pixel(middle, bottom + max(1, int(2 * scale)))), luminance(card) - 1, "the drop")
            self.assertGreater(luminance(ground), luminance(card) + 3, "a step brighter than the card")

    def test_the_counts_and_an_empty_list_are_sunken(self):
        for theme in brand.THEMES:
            for rows in (ROWS, []):
                plan, pixel = self.draw(theme, rows=rows)
                inset = brand.rgb(brand.palette(theme)["inset"])
                rules = [item["rect"] for item in plan["items"] if item["kind"] == "rule"]
                for left, top, right, bottom in (item["rect"] for item in plan["items"] if item["kind"] == "well"):
                    with self.subTest(theme=theme, rows=len(rows), well=(left, top)):
                        # Clear of the rounded corners, of the shading along its edges and of any text:
                        # beside a divider in the counts, beside the centred line in a quiet well.
                        inside = [rule for rule in rules if left < rule[0] < right and top < rule[1] < bottom]
                        x = inside[0][0] + 3 if inside else left + 16
                        self.assertEqual(pixel(x, (top + bottom) // 2), inset, "a well's middle is the inset fill")
                        # Shade along the inside of its top: it is below the card, not on it.
                        self.assertLess(luminance(pixel(left + 16, top + 2)), luminance(inset) - 1)

    def test_a_pressed_button_sinks_and_a_resting_one_stands(self):
        for theme in brand.THEMES:
            plan, pixel = self.draw(theme, rows=ROWS[:1])
            left, top, right, bottom = dict(plan["targets"])[("toggle",)]
            x = left + 14                                  # past the corner, before the centred label
            resting = pixel(x, top + 2), pixel(x, (top + bottom) // 2)
            plan, pixel = self.draw(theme, rows=ROWS[:1], pressed=("toggle",))
            pressed = pixel(x, top + 2), pixel(x, (top + bottom) // 2)
            with self.subTest(theme=theme):
                self.assertEqual(resting[0], resting[1], "a resting face is one colour")
                self.assertLess(luminance(pressed[0]), luminance(pressed[1]) - 1, "a pressed one is shaded at its top")
                self.assertEqual(pressed[1], brand.rgb(brand.palette(theme)["inset"]))

    def test_a_switch_that_is_off_sits_in_a_well_on_its_raised_tile(self):
        for theme in brand.THEMES:
            plan, pixel = self.draw(theme)
            off = next(item for item in plan["items"] if item["kind"] == "switch" and not item["checked"])
            left, top, right, bottom = off["rect"]
            self.assertLess(luminance(pixel(left + 25, top + 2)), luminance(pixel(left + 25, (top + bottom) // 2)) - 1,
                            theme)

    def test_high_contrast_draws_no_depth_at_all(self):
        plan, pixel = self.draw("light", contrast=True)
        window = popup.system_rgb("Window")
        tiles = self.tiles(plan)
        for upper, lower in zip(tiles, tiles[1:]):
            middle = (upper[0] + upper[2]) // 2
            for y in range(upper[3] + 1, lower[1] - 1):
                self.assertEqual(pixel(middle, y), window, "no shadow between tiles")
        for left, top, right, bottom in (item["rect"] for item in plan["items"] if item["kind"] == "well"):
            self.assertEqual(pixel(left + 16, top + 2), window, "no shade inside a well")
            self.assertEqual(pixel(left + 16, bottom - 3), window)


@unittest.skipUnless(os.name == "nt", "the popup's renderer is GDI")
class CountsFitTests(unittest.TestCase):
    """The counts' columns measured with the fonts the popup really draws with, in every catalog at
    every common scaling: no word of a label wider than its column, which DrawText would cut."""

    def test_no_count_label_is_cut_inside_a_word_in_any_language_or_scale(self):
        renderer = popup.Renderer()
        self.addCleanup(renderer.close)
        for locale in l10n.LOCALES:
            vm = popup.view_model(ROWS, STATUS, l10n.catalog(locale), NOW)
            for scale in SCALES:
                plan = renderer.layout(vm, scale, locale)
                with self.subTest(locale=locale, scale=scale):
                    LayoutTests.assert_columns(self, plan, renderer.measure)
                    # And none takes a third line for want of a column: the tallest label is two lines.
                    _, line = renderer.measure("label", "Ag", 100000, False)
                    self.assertLessEqual(max(item["rect"][3] - item["rect"][1] for item in count_labels(plan)),
                                         2 * line)


@unittest.skipUnless(os.name == "nt", "the card is a Windows window")
class CardTileTests(unittest.TestCase):
    def test_the_notification_card_s_tile_is_raised_as_the_popup_s_are(self):
        from codex_auto_resume import notice_window, notifier
        from test_notice_card import FULL, THREAD
        notice = notifier.build("interruption", {"thread_id": THREAD, "interruption_id": "a1" * 32,
                                                 "reset_at": None, "category": "server_5xx"}, FULL)
        where = {"work": (-24000, -24000, -22000, -22800), "monitor": (-24000, -24000, -22000, -22752),
                 "anchor": None, "dpi": 96}
        popup._gdiplus_acquire()
        self.addCleanup(popup._gdiplus_release)
        for theme in brand.THEMES:
            stack = notice_window.CardStack(clock=lambda: 0.0)
            card = notice_window.Card(stack, notice, now_ms=0, where=where,
                                      drawn={"theme": theme, "contrast": False, "reduced": False}, windows=False)
            try:
                card._paint_body(1.0)
                data, width = card.body.pixels(), card.size[0]

                def pixel(x, y):
                    index = (int(y) * width + int(x)) * 4
                    return data[index + 2], data[index + 1], data[index]
                left, top, right, bottom = next(item["rect"] for item in card.plan["items"] if item["kind"] == "panel")
                middle = (left + right) // 2
                ground = brand.rgb(brand.card_ground(theme))
                with self.subTest(theme=theme):
                    self.assertEqual(pixel(middle, top + 4), brand.rgb(popup.tile_ground(theme)))
                    self.assertLess(luminance(pixel(middle, bottom + 2)), luminance(ground) - 1, "its drop")
            finally:
                card.close()


if __name__ == "__main__":
    unittest.main()
