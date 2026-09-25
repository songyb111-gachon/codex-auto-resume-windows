"""One palette, checked everywhere it is copied to.

The product has four visual surfaces in three languages - a C# window, an HTML panel, a
generated icon and a JSON plugin manifest - and until v0.5.2 each carried its own hex
values. They had already drifted. The palette now lives in `codex_auto_resume.brand`,
two of the copies are generated from it, and these tests are what makes "generated"
mean something: a hand-edit to a generated file fails here rather than shipping.

The last test is the one that would have caught the original problem. It sweeps every
tracked text file for the retired colours, so a forgotten literal in a document or a
stylesheet is a failure and not a thing someone notices in a screenshot later.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import guiscan
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "assets"))

from codex_auto_resume import brand          # noqa: E402
from codex_auto_resume.mcp import panel as mcpui
import make_brand                                    # noqa: E402
import make_icon                                     # noqa: E402

MANIFEST = ROOT / ".codex-plugin" / "plugin.json"

# Retired with v0.5.2. The brand green and the status green it was paired with; a
# release that reintroduces either has lost an argument it never had.
RETIRED = ("#2F6F4E", "#2F8F5E", "#357D58", "#245A3F", "#6DC79A", "#F4FAF6")

TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".ps1", ".cmd", ".cs", ".yml", ".yaml",
                 ".svg", ".css", ".html", ".manifest"}
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def tracked_text_files():
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                             capture_output=True, text=True, encoding="utf-8").stdout
    for name in listing.splitlines():
        path = ROOT / name
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield name, path


class PaletteTests(unittest.TestCase):
    def test_themes_define_the_same_tokens(self):
        # A token defined in one theme and not the other renders one theme's text on
        # the other theme's ground, which is the classic unreadable-panel bug.
        self.assertEqual(set(brand.LIGHT), set(brand.DARK))

    def test_every_value_is_a_six_digit_hex(self):
        values = list(brand.LIGHT.values()) + list(brand.DARK.values()) + list(brand.RAMP)
        values += [brand.BRAND, brand.ICON_TOP, brand.ICON_BOTTOM, brand.ICON_MARK,
                   brand.ICON_ACCENT]
        for value in values:
            self.assertRegex(value, r"^#[0-9A-F]{6}$", value)

    def test_readable_colours_are_readable(self):
        # Anything a person has to read carries a contrast assertion, so a future
        # adjustment "for looks" cannot quietly make the panel unreadable.
        for theme in (brand.LIGHT, brand.DARK):
            self.assertGreaterEqual(brand.contrast(theme["ink"], theme["surface"]), 7.0)
            self.assertGreaterEqual(brand.contrast(theme["ink"], theme["canvas"]), 7.0)
            self.assertGreaterEqual(brand.contrast(theme["muted"], theme["surface"]), 4.5)
            self.assertGreaterEqual(brand.contrast(theme["accent"], theme["surface"]), 4.5)
            # The primary button is `on_accent` text on an `accent` fill, in both
            # themes, and the two are different colours for exactly this reason.
            self.assertGreaterEqual(brand.contrast(theme["accent"], theme["on_accent"]), 4.5)

    def test_state_colours_are_readable_where_they_are_drawn(self):
        """A state word is drawn in its state colour on a card, on a raised control and on
        its own tinted chip, so each has to be readable there; brand.py promises 4.5:1."""
        for name, theme in (("light", brand.LIGHT), ("dark", brand.DARK)):
            for state in ("success", "waiting", "warning", "danger", "paused"):
                for ground in ("surface", "raised"):
                    with self.subTest(theme=name, state=state, ground=ground):
                        self.assertGreaterEqual(brand.contrast(theme[state], theme[ground]), 4.5)

    def test_fill_only_tokens_are_documented_as_fill_only(self):
        # `active` does not reach text contrast and is not supposed to. The assertion
        # exists so that if someone raises it to text contrast they also have to come
        # here and say so, rather than quietly using it for text.
        self.assertLess(brand.contrast(brand.LIGHT["active"], brand.LIGHT["surface"]), 4.5)
        self.assertIn("fill-only", brand.__doc__.lower().replace("fill only", "fill-only"))


class ThemeTests(unittest.TestCase):
    """v0.6.4: the window and the popup draw dark too, on every ground the panel draws on, so the
    dark palette is held to the same readability as the light one wherever the window puts text.
    v0.6.10: and so is every design's, in both themes - each design is its own palette."""

    def grounds(self, theme, design="soft"):
        tokens = brand.palette(theme, design)
        return {"surface": tokens["surface"], "canvas": tokens["canvas"], "raised": tokens["raised"],
                "inset": tokens["inset"], "card": brand.card_ground(theme, design),
                "accent_soft": tokens["accent_soft"]}

    def looks(self):
        for design in brand.DESIGNS:
            for theme in brand.THEMES:
                yield design, theme

    def test_text_is_readable_on_every_ground_in_both_themes(self):
        for design, theme in self.looks():
            tokens = brand.palette(theme, design)
            for ground, value in self.grounds(theme, design).items():
                with self.subTest(design=design, theme=theme, ground=ground):
                    self.assertGreaterEqual(brand.contrast(tokens["ink"], value), 7.0)
                    self.assertGreaterEqual(brand.contrast(tokens["muted"], value), 4.5)
                    self.assertGreaterEqual(brand.contrast(tokens["accent"], value), 4.5)

    def test_state_words_are_readable_on_a_card_in_both_themes(self):
        for design, theme in self.looks():
            tokens = brand.palette(theme, design)
            for state in ("success", "waiting", "warning", "danger", "paused"):
                for ground in ("surface", "raised", "card"):
                    with self.subTest(design=design, theme=theme, state=state, ground=ground):
                        self.assertGreaterEqual(
                            brand.contrast(tokens[state], self.grounds(theme, design)[ground]), 4.5)

    def test_the_focus_ring_stands_off_every_ground_it_is_drawn_on(self):
        # A ring is not text: 3:1, the boundary of a control.
        for design, theme in self.looks():
            tokens = brand.palette(theme, design)
            for ground, value in self.grounds(theme, design).items():
                if ground == "accent_soft":
                    continue
                with self.subTest(design=design, theme=theme, ground=ground):
                    self.assertGreaterEqual(brand.contrast(tokens["focus"], value), 3.0)

    def test_the_primary_button_and_the_readable_colours_hold_in_every_design(self):
        for design, theme in self.looks():
            tokens = brand.palette(theme, design)
            with self.subTest(design=design, theme=theme):
                self.assertGreaterEqual(brand.contrast(tokens["accent"], tokens["on_accent"]), 4.5)
                self.assertEqual(set(tokens), set(brand.LIGHT))
                for value in tokens.values():
                    self.assertRegex(value, r"^#[0-9A-F]{6}$")

    def test_a_theme_is_named_light_or_dark_and_system_is_resolved_before(self):
        self.assertEqual(brand.THEMES, ("light", "dark"))
        self.assertIs(brand.palette("light"), brand.LIGHT)
        self.assertIs(brand.palette("dark"), brand.DARK)
        self.assertIs(brand.palette(brand.DARK), brand.DARK)
        self.assertEqual(brand.theme_name(brand.LIGHT), "light")
        for wrong in ("system", "", None, "Dark"):
            with self.assertRaises(ValueError):
                brand.palette(wrong)

    def test_shadows_and_the_status_colour_come_by_theme(self):
        for theme in brand.THEMES:
            for recipe in ("card", "control", "inset"):
                self.assertIs(brand.shadows(recipe, theme), brand.SHADOWS[theme][recipe])
            for state in ("monitoring", "attention", "failed", "paused", "idle", "unknown"):
                self.assertEqual(brand.status_colour(state, theme),
                                 brand.palette(theme)[brand.status_fill(state)])
        self.assertEqual(brand.status_colour("monitoring", "dark"), "#35B5CC")

    def test_the_card_ground_is_the_panels_color_mix(self):
        self.assertEqual(brand.card_ground("light"), brand.LIGHT["surface"])
        self.assertEqual(brand.card_ground("dark"), "#1B212C")
        self.assertIn("--card-ground: var(--surface);", brand.css_elevation("light"))
        self.assertIn("--card-ground: color-mix(in srgb, var(--raised) 22%, var(--surface));",
                      brand.css_elevation("dark"))
        # No channel lands near a half, so CSS's rounding and brand.mix's cannot disagree.
        for theme in brand.THEMES:
            tokens, lift = brand.palette(theme), brand.CARD_LIFT[theme]
            for low, high in zip(brand.rgb(tokens["surface"]), brand.rgb(tokens["raised"])):
                exact = low + (high - low) * lift
                self.assertGreater(abs(exact - math.floor(exact) - 0.5), 0.05)

    def test_dark_card_light_falls_inside_and_its_drops_outside(self):
        ground, card = brand.DARK["canvas"], brand.card_ground("dark")
        # Outside, only the two drops: straight above the card nothing but the drops' blur.
        outside = brand.elevation_colour("card", "top", 0.5, "canvas", "dark")
        by_hand = [float(part) for part in brand.rgb(ground)]
        for shadow in reversed(brand.shadows("card", "dark")):
            if not shadow.inset:
                alpha = brand.shadow_alpha(shadow, 0.5, "top")
                by_hand = [p + (t - p) * alpha for p, t in zip(by_hand, brand.rgb(brand.DARK[shadow.token]))]
        self.assertEqual(outside, tuple(by_hand))
        # Inside, the one-pixel top light and nothing else.
        light = brand.shadows("card", "dark")[-1]
        self.assertTrue(light.inset)
        inside = brand.elevation_colour("card", "top", 0.5, card, "dark", inside=True)
        expected = brand.mix(card, brand.DARK["shadow_light"], light.alpha)
        self.assertEqual(tuple(int(round(part)) for part in inside), brand.rgb(expected))
        self.assertEqual(brand.elevation_colour("card", "top", 1.5, card, "dark", inside=True),
                         tuple(float(part) for part in brand.rgb(card)))
        # Light is unchanged: its recipes are all outside or all inside.
        self.assertEqual(brand.elevation_colour("inset", "top", 0.25, "inset"),
                         brand.elevation_colour("inset", "top", 0.25, "inset", inside=True))


# What v0.6.2 shipped, the ten values of each theme, read from the tag:
# `git show v0.6.2:src/codex_auto_resume/brand.py`, LIGHT and DARK. Classic is pinned to these, so no
# later change to Soft - the design audit included - can move it.
V062 = {
    "light": {"ink": "#0F1B2D", "muted": "#5A6B7F", "line": "#DCE3EC", "surface": "#FFFFFF",
              "canvas": "#F2F5F9", "accent": "#1257B8", "on_accent": "#FFFFFF", "active": "#06B6D4",
              "idle": "#94A3B8", "attention": "#B45309"},
    "dark": {"ink": "#E8EEF6", "muted": "#9AACBF", "line": "#2E3A4B", "surface": "#191F29",
             "canvas": "#0C1118", "accent": "#5CA2EE", "on_accent": "#08111C", "active": "#35B5CC",
             "idle": "#5F6E80", "attention": "#E09B57"},
}


def _has_tag(name) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "refs/tags/" + name],
                          capture_output=True).returncode == 0


class DesignTests(unittest.TestCase):
    """v0.6.10: the Design setting - Soft, Still, Classic, Plain - as data, one table the surfaces read."""

    STATES = brand.GLOW_BREATHES + ("checking", "paused", "idle")

    def test_the_designs_and_soft_the_default(self):
        self.assertEqual(brand.DESIGNS, ("soft", "still", "classic", "plain"))
        self.assertEqual(brand.DEFAULT_DESIGN, "soft")
        for table in (brand.DESIGN, brand.DESIGN_RADII, brand.DESIGN_TOKENS):
            self.assertEqual(tuple(table), brand.DESIGNS)

    def test_each_design_is_its_row_of_the_table(self):
        axes = ("depth", "glow", "breathes", "glides", "accent_bar")
        self.assertEqual({design: tuple(brand.DESIGN[design][axis] for axis in axes) for design in brand.DESIGNS},
                         {"soft": (True, True, True, True, False), "still": (True, False, False, False, False),
                          "classic": (False, True, True, False, True), "plain": (False, False, True, False, False)})
        for design in brand.DESIGNS:
            with self.subTest(design):
                self.assertEqual(brand.design_depth(design), brand.DESIGN[design]["depth"])
                self.assertEqual(brand.design_glow(design), brand.DESIGN[design]["glow"])
                self.assertEqual(brand.design_breathes(design), brand.DESIGN[design]["breathes"])
                self.assertEqual(brand.design_glides(design), brand.DESIGN[design]["glides"])
                self.assertEqual(brand.design_accent_bar(design), brand.DESIGN[design]["accent_bar"])

    def test_a_design_is_named_and_anything_else_is_a_mistake(self):
        for wrong in ("Soft", "", None, "classic ", 1, "system"):
            with self.subTest(wrong=wrong):
                with self.assertRaises(ValueError):
                    brand.design_name(wrong)
                with self.assertRaises(ValueError):
                    brand.palette("light", wrong)
                with self.assertRaises(ValueError):
                    brand.design_depth(wrong)

    def test_soft_and_still_draw_in_the_palette_every_surface_drew_before(self):
        for theme in brand.THEMES:
            self.assertIs(brand.palette(theme, "soft"), brand.palette(theme))
            self.assertIs(brand.palette(theme, "still"), brand.palette(theme))
        self.assertIs(brand.palette("light"), brand.LIGHT)
        self.assertIs(brand.palette("dark", "soft"), brand.DARK)

    def test_classic_is_what_v062_shipped(self):
        for theme, values in V062.items():
            tokens = brand.palette(theme, "classic")
            with self.subTest(theme):
                self.assertEqual({key: tokens[key] for key in values}, values)
                # v0.6.2 filled a button with the surface and a field with the canvas, and ringed the
                # keyboard's focus in the accent.
                self.assertEqual((tokens["raised"], tokens["inset"], tokens["focus"]),
                                 (values["surface"], values["canvas"], values["accent"]))
        # What v0.6.2 had no token for is Soft's - but for the quiet accent ground, on which v0.6.2's muted
        # would not read: Classic's is the accent a tenth of the way from white.
        for key in ("accent_hover", "accent_pressed", "success", "waiting", "warning", "danger", "paused"):
            self.assertEqual(brand.CLASSIC_LIGHT[key], brand.LIGHT[key])
        self.assertEqual(brand.CLASSIC_LIGHT["accent_soft"], brand.mix("#FFFFFF", brand.BRAND, 0.10))
        self.assertLess(brand.contrast(V062["light"]["muted"], brand.LIGHT["accent_soft"]), 4.5)
        self.assertEqual(brand.CLASSIC_DARK["accent_soft"], brand.DARK["accent_soft"])

    @unittest.skipUnless(_has_tag("v0.6.2"), "the v0.6.2 tag is not in this clone")
    def test_the_pinned_values_are_the_tags_own(self):
        source = subprocess.run(["git", "-C", str(ROOT), "show", "v0.6.2:src/codex_auto_resume/brand.py"],
                                capture_output=True, text=True, encoding="utf-8", check=True).stdout
        tagged = {"__name__": "v062_brand"}
        exec(compile(source, "v0.6.2:brand.py", "exec"), tagged)
        self.assertEqual(tagged["LIGHT"], V062["light"])
        self.assertEqual(tagged["DARK"], V062["dark"])

    def test_plain_is_neutral_grey_with_the_products_accent_and_states(self):
        for theme in brand.THEMES:
            tokens, soft = brand.palette(theme, "plain"), brand.palette(theme)
            with self.subTest(theme):
                for key in ("ink", "muted", "line", "surface", "canvas", "raised", "inset"):
                    red, green, blue = brand.rgb(tokens[key])
                    self.assertTrue(red == green == blue, key)
                for key in ("accent", "accent_hover", "accent_pressed", "accent_soft", "on_accent", "active",
                            "idle", "attention", "success", "waiting", "warning", "danger", "paused"):
                    self.assertEqual(tokens[key], soft[key], key)
                self.assertEqual(tokens["focus"], tokens["ink"])

    def test_no_design_is_rounder_than_soft(self):
        for design in brand.DESIGNS:
            radii = brand.design_radii(design)
            with self.subTest(design):
                self.assertEqual(set(radii), set(brand.RADII))
                for role, value in radii.items():
                    self.assertLessEqual(value, brand.RADII[role], role)
        self.assertEqual(brand.design_radii("soft"), brand.RADII)
        self.assertEqual(brand.design_radii("still"), brand.RADII)
        self.assertEqual(brand.design_radii("classic"), {"card": 8, "control": 7, "chip": 999, "small": 6, "check": 4})
        self.assertEqual(brand.design_radii("plain"), {"card": 8, "control": 4, "chip": 999, "small": 4, "check": 4})

    def test_a_design_without_depth_has_no_shadow_and_its_card_is_its_surface(self):
        for theme in brand.THEMES:
            for recipe in ("card", "control", "inset"):
                self.assertIs(brand.shadows(recipe, theme), brand.SHADOWS[theme][recipe])
                self.assertIs(brand.shadows(recipe, theme, "soft"), brand.SHADOWS[theme][recipe])
                self.assertIs(brand.shadows(recipe, theme, "still"), brand.SHADOWS[theme][recipe])
                for design in ("classic", "plain"):
                    self.assertEqual(brand.shadows(recipe, theme, design), ())
            self.assertEqual(brand.card_ground(theme, "still"), brand.card_ground(theme))
            for design in ("classic", "plain"):
                tokens = brand.palette(theme, design)
                self.assertEqual(brand.card_ground(theme, design), tokens["surface"])
                self.assertEqual(brand.elevation_colour("card", "right", 2.0, "canvas", theme, design=design),
                                 tuple(float(part) for part in brand.rgb(tokens["canvas"])))

    def test_soft_draws_exactly_what_it_drew_before(self):
        for elapsed in range(0, 12000, 97):
            for state in self.STATES:
                self.assertEqual(brand.glow(state, elapsed, design="soft"), brand.glow(state, elapsed))
                self.assertEqual(brand.glow(state, elapsed, reduced=True, design="soft"),
                                 brand.glow(state, elapsed, reduced=True))
        for state in self.STATES:
            self.assertEqual(brand.glow_moves(state, design="soft"), brand.glow_moves(state))
            self.assertEqual(brand.status_colour(state, "dark", "soft"), brand.status_colour(state, "dark"))

    def test_still_holds_every_light_as_reduce_motion_does(self):
        for elapsed in range(0, 12000, 97):
            for state in self.STATES:
                self.assertEqual(brand.glow(state, elapsed, design="still"), brand.glow(state, elapsed, reduced=True))
        for state in self.STATES:
            self.assertFalse(brand.glow_moves(state, design="still"))

    def test_plain_dims_on_the_breath_with_no_glow_at_any_frame(self):
        dims = set()
        for elapsed in range(0, 12000, 97):
            for state in brand.GLOW_BREATHES + ("checking",):
                frame, soft = brand.glow(state, elapsed, design="plain"), brand.glow(state, elapsed)
                self.assertEqual((frame["opacity"], frame["spread"]), (0.0, 0.0))
                self.assertEqual((frame["dim"], frame["arc"]), (soft["dim"], soft["arc"]))
                dims.add(round(frame["dim"], 4))
        self.assertGreater(len(dims), 10)             # the light still moves
        self.assertTrue(brand.glow_moves("monitoring", design="plain"))
        self.assertIsNone(brand.glow("paused", 0, design="plain"))

    def test_classic_breathes_with_its_glow(self):
        for elapsed in range(0, 12000, 97):
            for state in self.STATES:
                self.assertEqual(brand.glow(state, elapsed, design="classic"), brand.glow(state, elapsed))

    def test_reduce_motion_holds_every_design_still(self):
        for design in brand.DESIGNS:
            for state in brand.GLOW_BREATHES + ("checking",):
                with self.subTest(design=design, state=state):
                    self.assertFalse(brand.glow_moves(state, reduced=True, design=design))
                    frame = brand.glow(state, 1100, reduced=True, design=design)
                    self.assertEqual((frame["dim"], frame["opacity"]), (0.0, 0.0))

    def test_the_two_gates_are_the_design_and_no_stopper(self):
        for design in brand.DESIGNS:
            for stopped in (False, True):
                with self.subTest(design=design, stopped=stopped):
                    self.assertEqual(brand.light_moves(design, stopped=stopped),
                                     brand.DESIGN[design]["breathes"] and not stopped)
                    self.assertEqual(brand.controls_move(design, stopped=stopped),
                                     brand.DESIGN[design]["glides"] and not stopped)
        self.assertEqual([design for design in brand.DESIGNS if brand.controls_move(design)], ["soft"])
        self.assertEqual([design for design in brand.DESIGNS if brand.light_moves(design)],
                         ["soft", "classic", "plain"])

    def test_the_stylesheet_blocks_are_each_flat_designs_properties_in_four_places(self):
        blocks = brand.css_design_blocks()
        self.assertNotIn('data-design="soft"', blocks)
        self.assertNotIn('data-design="still"', blocks)      # Soft's colours, depth and radii: motion only
        for design in ("classic", "plain"):
            root = ':root[data-design="%s"]' % design
            for form in (root + " {", root + ':not([data-theme="light"]) {', root + '[data-theme="dark"] {',
                         root + '[data-theme="light"] {'):
                with self.subTest(design=design, form=form):
                    self.assertEqual(blocks.count(form), 1)
            light = re.search(re.escape(root) + r" \{([^}]*)\}", blocks).group(1)
            for text in ("--elev-card: none;", "--elev-control: none;", "--elev-inset: none;",
                         "--card-ground: var(--surface);", "--radius-card: 8px;",
                         brand.css_variables(brand.palette("light", design))):
                self.assertIn(text, light)
            dark = re.search(re.escape(root) + r'\[data-theme="dark"\] \{([^}]*)\}', blocks).group(1)
            self.assertIn(brand.css_variables(brand.palette("dark", design)), dark)
        extra = brand.css_design_blocks(lambda theme, design: "--elev-own: none;")
        self.assertEqual(extra.count("--elev-own: none;"), 8)


class CheckBoxTests(unittest.TestCase):
    """v0.6.4's check box: the switch's material, sized to sit with the switch and the body text,
    and readable - unchecked included - in both themes and in High Contrast."""

    def test_its_size_is_the_knob_in_a_hairline_frame_and_fits_a_line_of_text(self):
        layout = brand.LAYOUT
        self.assertEqual(layout["check_size"], layout["knob"] + 2 * layout["hairline"])
        self.assertLessEqual(layout["check_size"], layout["switch_height"])
        self.assertLessEqual(layout["check_size"],
                             brand.TYPE_SCALE["body"] * brand.LINE_HEIGHT["body"])
        self.assertLess(brand.RADII["check"], layout["check_size"] / 3.0)
        self.assertGreater(layout["check_gap"], 0)
        self.assertEqual(layout["check_stroke"], 2)

    def test_the_table_names_tokens_both_themes_have(self):
        self.assertEqual(set(brand.CHECKBOX), {"off", "on", "off_disabled", "on_disabled"})
        self.assertEqual(set(brand.CHECKBOX_SYSTEM), set(brand.CHECKBOX))
        for state, entry in brand.CHECKBOX.items():
            for part in ("fill", "edge", "mark"):
                if entry[part] is not None:
                    self.assertIn(entry[part], brand.LIGHT, (state, part))
            self.assertEqual(entry["mark"] is not None, state.startswith("on"))
        for state, entry in brand.CHECKBOX_SYSTEM.items():
            for part in ("fill", "edge", "mark"):
                if entry[part] is not None:
                    self.assertIn(entry[part], brand.SYSTEM_CSS, (state, part))
            self.assertEqual(entry["mark"] is not None, state.startswith("on"))

    def test_unchecked_is_the_well_and_checked_is_the_accent_with_its_mark(self):
        for theme in brand.THEMES:
            tokens = brand.palette(theme)
            self.assertEqual(brand.check_box(False, True, theme),
                             {"fill": tokens["inset"], "edge": tokens["muted"], "mark": None, "well": True})
            self.assertEqual(brand.check_box(True, True, theme),
                             {"fill": tokens["accent"], "edge": tokens["accent"],
                              "mark": tokens["on_accent"], "well": False})
            for checked in (False, True):
                disabled = brand.check_box(checked, False, theme)
                self.assertEqual((disabled["fill"], disabled["edge"], disabled["well"]),
                                 (tokens["surface"], tokens["line"], False))
                self.assertEqual(disabled["mark"], tokens["muted"] if checked else None)
        self.assertEqual(brand.check_box_state(True, False), "on_disabled")
        self.assertEqual(brand.check_box_system(True, True),
                         {"fill": "Highlight", "edge": "Highlight", "mark": "HighlightText"})
        self.assertEqual(brand.css_system("WindowText"), "CanvasText")

    def test_every_state_can_be_seen_in_both_themes(self):
        for design in brand.DESIGNS:
            for theme in brand.THEMES:
                tokens = brand.palette(theme, design)
                grounds = (tokens["surface"], tokens["raised"], tokens["canvas"], brand.card_ground(theme, design))
                off, on = brand.check_box(False, True, theme, design), brand.check_box(True, True, theme, design)
                for ground in grounds:
                    with self.subTest(design=design, theme=theme, ground=ground):
                        # An empty box is found by its edge, a checked one by its fill: 3:1 each.
                        self.assertGreaterEqual(brand.contrast(off["edge"], ground), 3.0)
                        self.assertGreaterEqual(brand.contrast(on["fill"], ground), 3.0)
                        self.assertGreaterEqual(brand.contrast(tokens["focus"], ground), 3.0)
                with self.subTest(design=design, theme=theme):
                    self.assertGreaterEqual(brand.contrast(off["edge"], off["fill"]), 3.0)
                    self.assertGreaterEqual(brand.contrast(on["mark"], on["fill"]), 4.5)
                    disabled = brand.check_box(True, False, theme, design)
                    self.assertGreaterEqual(brand.contrast(disabled["mark"], disabled["fill"]), 4.5)

    def test_a_design_without_depth_draws_no_well_and_takes_its_own_colours(self):
        for design in brand.DESIGNS:
            for theme in brand.THEMES:
                tokens = brand.palette(theme, design)
                with self.subTest(design=design, theme=theme):
                    self.assertEqual(brand.check_box(False, True, theme, design),
                                     {"fill": tokens["inset"], "edge": tokens["muted"], "mark": None,
                                      "well": brand.design_depth(design)})
                    self.assertEqual(brand.check_box(True, True, theme, design)["mark"], tokens["on_accent"])
        self.assertEqual(brand.check_box(False, True, "light"), brand.check_box(False, True, "light", "soft"))

    def test_the_mark_is_a_mitred_tick_centred_in_the_box(self):
        (x0, y0), (x1, y1), (x2, y2) = brand.CHECK_MARK
        self.assertAlmostEqual(abs(x1 - x0), abs(y1 - y0))            # 45 degrees
        self.assertAlmostEqual(abs(x2 - x1), abs(y2 - y1))
        self.assertAlmostEqual((x1 - x0) * (x2 - x1) + (y1 - y0) * (y2 - y1), 0.0)   # a right angle
        self.assertAlmostEqual(math.hypot(x2 - x1, y2 - y1), 2 * math.hypot(x1 - x0, y1 - y0))
        outline = brand.check_mark_outline()
        self.assertEqual(len(outline), 6)
        size, hairline = brand.LAYOUT["check_size"], brand.LAYOUT["hairline"]
        xs, ys = [x for x, _ in outline], [y for _, y in outline]
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, size / 2.0)
        self.assertLess(abs((min(ys) + max(ys)) / 2 - size / 2.0), 0.25)
        for x, y in outline:
            self.assertTrue(hairline + 1 < x < size - hairline - 1, x)
            self.assertTrue(hairline + 1 < y < size - hairline - 1, y)
        # Filling the outline is stroking the centre line: stroke times the arms' lengths (a mitred
        # right angle adds a square outside and takes the same square away inside).
        area = abs(sum(ax * by - bx * ay for (ax, ay), (bx, by)
                       in zip(outline, outline[1:] + outline[:1]))) / 2
        arms = math.hypot(x1 - x0, y1 - y0) + math.hypot(x2 - x1, y2 - y1)
        self.assertAlmostEqual(area, brand.LAYOUT["check_stroke"] * arms)
        self.assertEqual(brand.check_mark(2.0, 10, 20)[1], (10 + 2 * x1, 20 + 2 * y1))
        self.assertEqual(brand.check_mark_outline(2.0, 10, 20)[0],
                         (10 + 2 * outline[0][0], 20 + 2 * outline[0][1]))

    def test_the_stylesheet_gets_the_check_box_under_names_the_panel_can_use(self):
        scale = brand.css_scale()
        for text in ("--size-check-size: 18px;", "--size-check-gap: 10px;", "--size-check-stroke: 2px;",
                     "--radius-check: 5px;", "--check-off-fill: var(--inset);",
                     "--check-off-edge: var(--muted);", "--check-off-elev: var(--elev-inset);",
                     "--check-on-fill: var(--accent);", "--check-on-mark: var(--on-accent);",
                     "--check-on-elev: none;", "--check-on-disabled-mark: var(--muted);",
                     "--check-mark-shape: polygon("):
            self.assertIn(text, scale)
        colours = set(re.findall(r"(--[a-z-]+)\s*:", brand.css_variables(brand.LIGHT)))
        for name in re.findall(r"var\((--[a-z-]+)\)", brand.css_check_box()):
            self.assertTrue(name in colours or name.startswith("--elev-"), name)
        shape = re.search(r"--check-mark-shape: polygon\(([^)]*)\);", scale).group(1)
        points = [tuple(float(part[:-2]) for part in pair.split()) for pair in shape.split(", ")]
        for have, want in zip(points, brand.check_mark_outline()):
            self.assertAlmostEqual(have[0], want[0], places=3)
            self.assertAlmostEqual(have[1], want[1], places=3)


def png_content(data):
    """The chunk sequence, header and uncompressed scanlines of a PNG - everything in it
    except how the scanlines happened to be deflated."""
    import struct
    import zlib
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    tags, header, compressed, pos = [], None, b"", 8
    while pos < len(data):
        length, tag = struct.unpack_from(">I4s", data, pos)
        payload = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack_from(">I", data, pos + 8 + length)
        if crc != zlib.crc32(tag + payload) & 0xFFFFFFFF:
            raise ValueError("bad %r chunk checksum" % tag)
        tags.append(tag)
        if tag == b"IHDR":
            header = payload
        elif tag == b"IDAT":
            compressed += payload
        pos += 12 + length
    return tags, header, zlib.decompress(compressed)


def ico_content(data):
    """An .ico's directory, minus the byte counts and offsets that depend on compression,
    and the decoded content of every PNG entry."""
    import struct
    reserved, kind, count = struct.unpack_from("<HHH", data)
    entries = []
    for index in range(count):
        width, height, colours, spare, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index)
        entries.append(((width, height, colours, spare, planes, bits),
                        png_content(data[offset:offset + length])))
    return (reserved, kind, count), entries


class GeneratedFileTests(unittest.TestCase):
    def test_gui_brand_cs_is_current(self):
        self.assertEqual(make_brand.TARGET.read_text(encoding="utf-8"), make_brand.render(),
                         "gui/Brand.cs is stale; run python build/make_brand.py")

    def test_vector_master_is_current(self):
        vector = ROOT / "assets" / "brand" / "icon.svg"
        self.assertEqual(vector.read_text(encoding="utf-8"), make_icon.svg(),
                         "assets/brand/icon.svg is stale; run python assets/make_icon.py")

    def test_icon_matches_its_generator(self):
        # The .ico is committed, so it can go stale against the code that draws it.
        # Rendering it here is the only way "generated" stays true. What is compared is
        # what each entry decodes to, not the compressed bytes, which depend on the zlib
        # the running Python was built with (zlib-ng deflates the same pixels differently).
        images = [(size, make_icon.png(size, make_icon.render(size))) for size in make_icon.SIZES]
        current = (ROOT / "assets" / "codex-auto-resume.ico").read_bytes()
        self.assertEqual(ico_content(current), ico_content(make_icon.ico(images)),
                         "assets/codex-auto-resume.ico is stale; run python assets/make_icon.py")

    def test_icon_comparison_still_sees_a_changed_pixel(self):
        # Comparing decoded content must not become comparing nothing.
        images = [(size, make_icon.png(size, make_icon.render(size))) for size in make_icon.SIZES]
        pixels = bytearray(make_icon.render(16))
        pixels[0] ^= 0xFF
        altered = [(16, make_icon.png(16, bytes(pixels)))] + images[1:]
        self.assertNotEqual(ico_content(make_icon.ico(images)), ico_content(make_icon.ico(altered)))

    def test_the_icon_s_geometry_is_brand_s_under_its_old_names(self):
        """v0.6.5 moved the mark's numbers and rasteriser into brand, so the watcher can draw the
        icon's motion from them; make_icon.py writes the same bytes from there."""
        shape = brand.ICON_SHAPE
        self.assertEqual((make_icon.RING_INNER, make_icon.RING_OUTER, make_icon.ARC_START, make_icon.ARC_END,
                          make_icon.HEAD_RADIUS, make_icon.CORNER_LARGE, make_icon.CORNER_SMALL,
                          make_icon.CORNER_THRESHOLD),
                         (0.34, 0.53, 125.0, 55.0, 0.155, 0.30, 0.24, 32))
        self.assertEqual((shape["ring_inner"], shape["arc_end"], shape["head_radius"]), (0.34, 55.0, 0.155))
        self.assertEqual(make_icon.render(24), brand.icon_render(24))
        self.assertEqual(make_icon.HEAD_CENTRE, brand.icon_head_centre())
        # The head kept apart gives the whole render back, in any colour it is given.
        head = brand.rgb(brand.ICON_ACCENT)
        for size in (16, 32):
            rows = brand.icon_samples(size)
            self.assertEqual(b"".join(bytes(part for sample in row for part in brand.icon_pixel(sample, head))
                                      for row in rows), brand.icon_render(size))

    def test_the_two_names_for_the_256_icon_agree(self):
        assets = ROOT / "assets"
        self.assertEqual((assets / "icon.png").read_bytes(),
                         (assets / "codex-auto-resume-256.png").read_bytes())


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.interface = self.manifest["interface"]

    def test_plugin_card_uses_the_brand_colour(self):
        self.assertEqual(self.interface["brandColor"], brand.BRAND)

    def test_plugin_card_artwork_exists_and_is_png(self):
        # Codex validates that these resolve inside the plugin; a manifest that names a
        # file the build does not ship fails at install time, on someone else's machine.
        named = [self.interface[key] for key in ("composerIcon", "logo", "logoDark")
                 if key in self.interface]
        named += list(self.interface.get("screenshots", []))
        self.assertTrue(named, "the plugin card names no artwork at all")
        for reference in named:
            self.assertTrue(reference.startswith("./assets/"), reference)
            self.assertTrue(reference.endswith(".png"), reference)
            self.assertTrue((ROOT / reference[2:]).is_file(), "missing: " + reference)

    def test_panel_stylesheet_is_built_from_the_palette(self):
        for value in brand.LIGHT.values():
            self.assertIn(value, mcpui._STYLE)
        for value in brand.DARK.values():
            self.assertIn(value, mcpui._STYLE)

    def test_every_variable_the_panel_uses_is_defined(self):
        # An undefined custom property is not an error: the declaration is dropped and
        # the element silently inherits. That is how a button ends up with the page's
        # text colour on the accent fill and nobody notices until a screenshot.
        used = set(re.findall(r"var\(\s*(--[a-z-]+)\s*\)", mcpui._STYLE))
        defined = set(re.findall(r"(--[a-z-]+)\s*:", mcpui._STYLE))
        self.assertEqual(used - defined, set(), "undefined custom properties")

    def test_panel_declares_a_background_on_the_body(self):
        # The host paints its own ground behind the page, so a transparent body silently
        # borrows the host's theme and can put dark text on a dark panel.
        self.assertRegex(mcpui._STYLE, r"body\s*\{[^}]*background:\s*var\(--canvas\)")

    def test_settings_window_writes_no_colour_of_its_own(self):
        source = guiscan.settings()
        stray = [line.strip() for line in source.splitlines()
                 if "Color.FromArgb" in line]
        self.assertEqual(stray, [], "colours belong in brand.py, not in the window")


class WindowScalingTests(unittest.TestCase):
    """Fixed pixel sizes in the settings window must follow the display.

    Windows Forms scales the font and leaves explicit sizes alone, so a window written
    at 96 DPI keeps its width while its text doubles. At 200% the second column's labels
    clipped, the spin boxes crowded the card edge and the last row fell off the bottom.
    It looked right at 100% and 150%, which is why it survived two releases.
    """

    def setUp(self):
        self.source = guiscan.settings()

    def test_no_size_or_padding_is_written_in_raw_pixels(self):
        # `new Size(a, b)` and `new Padding(...)` with bare integers are the shape that
        # does not scale. Zeros are fine: zero is zero at any DPI.
        offenders = []
        for match in re.finditer(r"new (?:Size|Padding)\(([^)]*)\)", self.source):
            parts = [p.strip() for p in match.group(1).split(",")]
            if all(p == "0" or not p.isdigit() for p in parts):
                continue
            offenders.append(match.group(0))
        self.assertEqual(offenders, [], "write these through Px()/Pad() so they scale")

    def test_the_scale_does_not_come_from_deviceDpi(self):
        """`DeviceDpi` answers 96 on a 192-DPI screen here, so a fix using it does nothing.

        The manifest declares per-monitor awareness, but .NET Framework WinForms only
        honours that with an app.config opt-in this product does not ship. Measured: the
        first attempt at this fix scaled by DeviceDpi and changed the rendered window by
        not one pixel.
        """
        code = "\n".join(line for line in self.source.splitlines()
                         if not line.lstrip().startswith("//"))
        self.assertNotIn("DeviceDpi", code, "the comment may name it; the code may not")
        self.assertIn("GetDpiForSystem", code)

    def test_the_absolute_column_holding_the_state_dot_scales_too(self):
        # It was a bare 22 while the dot became 24 wide, which sliced a third off it.
        self.assertRegex(self.source, r"ColumnStyle\(SizeType\.Absolute, Px\(")


class DerivedColourTests(unittest.TestCase):
    """v0.6.4's hover and pressed accents are written out as hex, so each is held to the
    formula it came from and to the text it carries."""

    def test_hover_is_the_accent_brightened_as_the_panel_brightened_it(self):
        for theme in (brand.LIGHT, brand.DARK):
            self.assertEqual(theme["accent_hover"], brand.brighten(theme["accent"], 1.07))

    def test_pressed_is_the_accent_a_step_toward_the_dark(self):
        self.assertEqual(brand.LIGHT["accent_pressed"],
                         brand.mix(brand.LIGHT["accent"], brand.LIGHT["ink"], 0.12))
        # Dark ink is near-white, so the dark theme presses toward its shadow instead.
        self.assertEqual(brand.DARK["accent_pressed"],
                         brand.mix(brand.DARK["accent"], brand.DARK["shadow_dark"], 0.12))

    def test_the_primary_button_stays_readable_in_every_state(self):
        for name, theme in (("light", brand.LIGHT), ("dark", brand.DARK)):
            for token in ("accent", "accent_hover", "accent_pressed"):
                with self.subTest(theme=name, token=token):
                    self.assertGreaterEqual(brand.contrast(theme["on_accent"], theme[token]), 4.5)

    def test_mixing_rounds_half_up_and_brightening_holds_at_white(self):
        self.assertEqual(brand.mix("#000000", "#FFFFFF", 0.5), "#808080")
        self.assertEqual(brand.brighten("#FF8000", 1.5), "#FFC000")


# The panel's elevation custom properties exactly as v0.6.3 wrote them by hand in mcpui.py.
PANEL_ELEVATION_LIGHT = (
    "--elev-card: 4px 4px 14px color-mix(in srgb, var(--shadow-dark) 55%, transparent), "
    "-4px -4px 14px color-mix(in srgb, var(--shadow-light) 90%, transparent); "
    "--elev-control: 2px 2px 6px color-mix(in srgb, var(--shadow-dark) 45%, transparent), "
    "-2px -2px 6px color-mix(in srgb, var(--shadow-light) 90%, transparent); "
    "--elev-inset: inset 2px 2px 6px color-mix(in srgb, var(--shadow-dark) 38%, transparent), "
    "inset -2px -2px 6px color-mix(in srgb, var(--shadow-light) 50%, transparent); "
    "--card-ground: var(--surface);")
PANEL_ELEVATION_DARK = (
    "--elev-card: 0 1px 2px color-mix(in srgb, var(--shadow-dark) 70%, transparent), "
    "0 6px 18px color-mix(in srgb, var(--shadow-dark) 35%, transparent), "
    "inset 0 1px 0 color-mix(in srgb, var(--shadow-light) 45%, transparent); "
    "--elev-control: 0 1px 2px color-mix(in srgb, var(--shadow-dark) 60%, transparent); "
    "--elev-inset: inset 0 1px 2px color-mix(in srgb, var(--shadow-dark) 55%, transparent); "
    "--card-ground: color-mix(in srgb, var(--raised) 22%, var(--surface));")

# Pixels measured on docs/images/settings-panel.png (rendered at 2x, so a first device pixel
# is 0.25 CSS px from the edge): (recipe, side, CSS px from the edge, ground, pixel).
PANEL_PIXELS = (
    ("card", "right", 10.25, "canvas", (228, 234, 242)),
    ("card", "right", 18.25, "canvas", (232, 237, 243)),
    ("card", "top", 0.25, "canvas", (237, 241, 244)),
    ("control", "bottom", 0.25, "surface", (225, 231, 238)),
    ("inset", "top", 0.25, "inset", (216, 224, 233)),
    ("inset", "bottom", 0.25, "inset", (231, 236, 241)),
)


class ElevationTests(unittest.TestCase):
    def test_the_stylesheet_elevation_is_what_the_panel_always_wrote(self):
        self.assertEqual(brand.css_elevation("light"), PANEL_ELEVATION_LIGHT)
        self.assertEqual(brand.css_elevation("dark"), PANEL_ELEVATION_DARK)
        self.assertEqual(brand.css_elevation(brand.LIGHT), PANEL_ELEVATION_LIGHT)
        self.assertEqual(brand.css_elevation(brand.DARK), PANEL_ELEVATION_DARK)

    def test_both_themes_have_the_same_recipes_in_their_own_tokens(self):
        self.assertEqual(list(brand.SHADOWS["light"]), list(brand.SHADOWS["dark"]))
        for theme in brand.SHADOWS.values():
            for shadows in theme.values():
                for shadow in shadows:
                    self.assertIn(shadow.token, ("shadow_dark", "shadow_light"))
                    self.assertTrue(0 < shadow.alpha <= 1)

    def test_the_shadow_model_reproduces_the_panel_to_two_levels(self):
        for recipe, side, distance, ground, measured in PANEL_PIXELS:
            with self.subTest(recipe=recipe, side=side, d=distance):
                predicted = brand.elevation_colour(recipe, side, distance, ground)
                for have, want in zip(predicted, measured):
                    self.assertLessEqual(abs(int(round(have)) - want), 2, (predicted, measured))

    def test_an_inset_shadow_falls_inside_the_edges_an_outer_one_falls_outside(self):
        drop, well = brand.SHADOWS["light"]["card"][0], brand.SHADOWS["light"]["inset"][0]
        self.assertEqual(brand.shadow_offset(drop, "bottom"), 4)
        self.assertEqual(brand.shadow_offset(drop, "top"), -4)
        self.assertEqual(brand.shadow_offset(well, "top"), 2)
        self.assertEqual(brand.shadow_offset(well, "bottom"), -2)
        self.assertGreater(brand.shadow_alpha(drop, 2, "bottom"), brand.shadow_alpha(drop, 2, "top"))

    def test_reach_is_three_sigmas_past_the_offset(self):
        self.assertEqual(brand.reach("card"), (25, 25, 25, 25))
        self.assertEqual(brand.reach("control"), (11, 11, 11, 11))
        self.assertEqual(brand.reach("inset"), (0, 0, 0, 0))
        self.assertEqual(brand.reach("card", "dark"), (27, 21, 27, 33))
        self.assertEqual(brand.reach("card", scale=1.5), (38, 38, 38, 38))
        self.assertEqual(brand.reach("card", scale=2.0), (50, 50, 50, 50))
        # Past its reach a shadow is below a fifth of a percent of its own strength.
        for recipe in ("card", "control"):
            for side, distance in zip(("left", "top", "right", "bottom"), brand.reach(recipe)):
                for shadow in brand.SHADOWS["light"][recipe]:
                    self.assertLess(brand.shadow_alpha(shadow, distance, side), shadow.alpha * 0.002)


class ScaleTests(unittest.TestCase):
    def test_paddings_expand_the_way_css_expands_them(self):
        self.assertEqual(brand.padding("page_pad"), (16, 14, 20, 14))
        self.assertEqual(brand.padding("card_pad"), (16, 18, 16, 18))
        self.assertEqual(brand.padding("tile_pad"), (10, 12, 10, 14))
        self.assertEqual(brand.padding("page_gap"), (14, 14, 14, 14))

    def test_every_size_is_a_whole_pixel_the_window_can_scale(self):
        for key, value in brand.LAYOUT.items():
            for part in (value if isinstance(value, tuple) else (value,)):
                self.assertIsInstance(part, int, key)

    def test_type_roles_name_sizes_that_exist(self):
        for role, (size, weight) in brand.TYPE_ROLES.items():
            self.assertIn(size, brand.TYPE_SCALE, role)
            self.assertIn(weight, (400, 500, 600), role)

    def test_the_stylesheet_gets_every_size_once_under_a_name_the_panel_can_use(self):
        scale = brand.css_scale()
        names = re.findall(r"(--[^:\s]+)\s*:", scale)
        self.assertEqual(len(names), len(set(names)), "a custom property declared twice")
        for name in names:
            self.assertRegex(name, r"^--[a-z-]+$")
        for key, value in brand.TYPE_SCALE.items():
            self.assertIn("--type-%s: %gpx;" % (key.replace("_", "-"), value), scale)
        for key in brand.LINE_HEIGHT:
            self.assertIn("--lh-%s:" % key.replace("_", "-"), scale)
        for key in brand.LAYOUT:
            self.assertIn("--size-%s:" % key.replace("_", "-"), scale)
        self.assertIn("--size-card-pad: 16px 18px;", scale)
        self.assertIn("--size-row-pad: 11px 0;", scale)
        self.assertIn("--glow-reach: 3.6px;", scale)            # 0.6 of the panel's 6 px dot
        self.assertIn("--glow-edge: 6px;", scale)
        self.assertIn("--glow-outer: 9.6px;", scale)
        # The dot's depth is not a property any more: the panel walks the breath's own stops
        # (css_glow_keyframes), sampled from glow_phase, so there is nothing here to keep in step.
        self.assertIn("--glow-from: 0.625;", scale)
        self.assertNotIn("--glow-dot-low", scale)
        self.assertIn("--glow-monitoring-ms: 4400ms;", scale)
        self.assertIn("--transition: 160ms;", scale)
        self.assertIn("--transition-ease: cubic-bezier(0.33, 1, 0.68, 1);", scale)


RUNNING_STATES = ("monitoring", "waiting", "checking", "recovering")


class StatusLightTests(unittest.TestCase):
    """The status light: the flat dot each surface already drew, every running state the cyan the dot had
    before v0.6.3, the greys exactly as they were, and - since v0.6.6 - the ordinary breath a status light
    of this size is built from: one symmetric cosine a cycle, taken in light and drawn through the screen's
    gamma, with the glow riding the brightness and reaching a share of the dot rather than a flat 3 px."""

    def test_every_running_state_is_the_cyan_from_before_v063(self):
        for state in RUNNING_STATES:
            self.assertEqual(brand.status_fill(state), "active", state)
        self.assertEqual(brand.LIGHT["active"], "#06B6D4")
        self.assertEqual(brand.DARK["active"], "#35B5CC")

    def test_stopped_unknown_and_paused_keep_their_greys_and_have_no_glow(self):
        self.assertEqual(brand.status_fill("idle"), "idle")
        self.assertEqual(brand.status_fill("paused"), "paused")
        for unknown in ("", None, "stopped", "not a state"):
            self.assertEqual(brand.status_fill(unknown), "idle")
        self.assertEqual((brand.LIGHT["idle"], brand.LIGHT["paused"]), ("#94A3B8", "#55657A"))
        self.assertEqual((brand.DARK["idle"], brand.DARK["paused"]), ("#5F6E80", "#9AACBF"))
        for state in ("idle", "paused", "", None, "stopped"):
            for reduced in (False, True):
                self.assertIsNone(brand.glow(state, 1234, 50, reduced=reduced))
                self.assertFalse(brand.glow_moves(state, 50, reduced=reduced))

    def test_alarms_keep_their_colours(self):
        self.assertEqual(brand.status_fill("attention"), "attention")
        self.assertEqual(brand.status_fill("failed"), "danger")

    def test_high_contrast_is_a_system_colour(self):
        for state in RUNNING_STATES:
            self.assertEqual(brand.status_system(state), "Highlight")
        self.assertEqual(brand.status_system("attention"), "WindowText")
        self.assertEqual(brand.status_system("failed"), "WindowText")
        for state in ("paused", "idle", "unknown"):
            self.assertEqual(brand.status_system(state), "GrayText")

    def test_the_decided_numbers(self):
        # v0.6.6, chosen against the earlier cuts side by side: a resting-breath cycle, a dot that keeps
        # `low` of its light at the bottom, and a glow that reaches a share of the dot rather than 3 px
        # everywhere - which had been two thirds of the popup's radius and half of the panel's.
        expected = {"low": 0.35, "gamma": 2.2, "peak": 0.50, "reach_of_radius": 0.6,
                    "edge_alpha": 0.67, "near_at": 0.14, "near_alpha": 0.58, "far_at": 0.66,
                    "far_alpha": 0.50, "monitoring_ms": 4400, "waiting_ms": 4400, "recovering_ms": 2800,
                    "attention_ms": 5600,
                    "failed_ms": 1200, "arc_ms": 1600, "arc_alpha": 0.55}
        self.assertEqual({key: brand.GLOW[key] for key in expected}, expected)
        self.assertEqual(brand.STATUS_DOT, {"window": 5, "popup": 4.5, "panel": 6, "mini": 4})
        self.assertAlmostEqual(brand.glow_floor(), 0.35 ** (1 / 2.2))          # 62% of the colour, as drawn
        # A breath is a rhythm, not a length: every surface breathes alike and only the reach is a size.
        for surface, radius in brand.STATUS_DOT.items():
            with self.subTest(surface):
                self.assertAlmostEqual(brand.glow_reach(radius), 0.6 * radius)
                self.assertAlmostEqual(brand.glow_extent(radius), 1.6 * radius)
        # The phases and the first cut's ring are gone, not left beside the new numbers.
        for gone in ("fall", "rise", "bloom", "withdraw", "dot_dim", "reach", "still", "attention_peak",
                     "monitoring_low", "monitoring_high", "recovering_low", "recovering_high"):
            self.assertNotIn(gone, brand.GLOW)
        self.assertFalse(hasattr(brand, "GLOW_PHASES"))

    def assertFrame(self, frame, expected):
        self.assertEqual(set(frame), set(expected))
        for key, value in expected.items():
            if value is None:
                self.assertIsNone(frame[key], key)
            else:
                self.assertAlmostEqual(frame[key], value, places=9, msg=key)

    def cycle(self, state, step=1.0):
        cycle = brand.GLOW[state + "_ms"]
        count = int(cycle / step)
        return [(elapsed, brand.glow(state, elapsed)) for elapsed in (index * step for index in range(count))]

    def test_the_glow_rides_the_brightness(self):
        """It takes no turn of its own: out when the dot is lit, gone when the dot is at its lowest, and
        never anywhere the brightness has not put it. Squared, so it keeps to the top of the breath."""
        for state in brand.GLOW_BREATHES:
            with self.subTest(state):
                pairs = []
                for elapsed, frame in self.cycle(state):
                    self.assertAlmostEqual(frame["opacity"], brand.GLOW["peak"] * frame["spread"])
                    pairs.append((1.0 - frame["dim"], frame["spread"]))
                floor = brand.glow_floor()
                for lit, spread in pairs:
                    with self.subTest(lit=round(lit, 3)):
                        self.assertAlmostEqual(spread, ((lit - floor) / (1.0 - floor)) ** 2, places=9)
                self.assertAlmostEqual(max(spread for _, spread in pairs), 1.0, places=3)
                self.assertAlmostEqual(min(spread for _, spread in pairs), 0.0, places=3)

    def test_the_cycle_is_one_symmetric_breath(self):
        """Down for half of it and up for the other half, with the light never still, the two halves
        mirror images, and no step anywhere a frame could land."""
        cycle = brand.GLOW["monitoring_ms"]

        def at(fraction):
            return brand.glow("monitoring", fraction * cycle)

        self.assertAlmostEqual(at(0)["dim"], 0.0)                                   # the top of the breath
        self.assertAlmostEqual(at(0.5)["dim"], 1.0 - brand.glow_floor())            # its bottom
        self.assertAlmostEqual(at(0.5)["spread"], 0.0)
        for fraction in (0.05, 0.17, 0.25, 0.4, 0.49):
            with self.subTest(fraction=fraction):
                self.assertAlmostEqual(at(fraction)["dim"], at(1.0 - fraction)["dim"], places=9)
        frames = self.cycle("monitoring")
        dims = [frame["dim"] for _, frame in frames]
        half = int(cycle * 0.5)
        self.assertEqual(dims[:half + 1], sorted(dims[:half + 1]))                  # down, all the way
        self.assertEqual(dims[half:], sorted(dims[half:], reverse=True))            # and back up
        levels = set(round(dim, 4) for dim in dims)
        self.assertGreater(len(levels), 0.9 * len(dims) / 2 - 100)      # a cosine meets each level twice
        for index in range(1, len(frames) + 1):
            now = frames[index % len(frames)][1]
            before = frames[index - 1][1]
            self.assertLess(abs(now["dim"] - before["dim"]), 0.003, index)
            self.assertLess(abs(now["spread"] - before["spread"]), 0.01, index)

    def test_the_curve_is_taken_in_light_and_drawn_through_the_gamma(self):
        """Walking a cosine straight along an alpha bunches at the top and rushes at the bottom. The
        cosine is in light; what is drawn is that raised to 1/gamma, which is even to look at."""
        import math
        cycle = brand.GLOW["monitoring_ms"]
        for fraction in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9):
            with self.subTest(fraction=fraction):
                breath = 0.5 + 0.5 * math.cos(2.0 * math.pi * fraction)
                light = brand.GLOW["low"] + (1.0 - brand.GLOW["low"]) * breath
                drawn = light ** (1.0 / brand.GLOW["gamma"])
                self.assertAlmostEqual(1.0 - brand.glow("monitoring", fraction * cycle)["dim"], drawn, places=9)
        # Halfway down in time is brighter than halfway down in light: that is the correction.
        self.assertGreater(1.0 - brand.glow("monitoring", cycle * 0.25)["dim"],
                           (1.0 + brand.GLOW["low"]) / 2.0)

    def test_a_cycle_starts_and_ends_at_full_brightness(self):
        """A breath begins and ends at the top, where the still light also sits, so a light that starts
        moving does not jump in brightness. The glow is the one thing that appears with the motion: it
        rides the brightness, so at the top it is out, and a still light never has one."""
        for state in brand.GLOW_BREATHES:
            with self.subTest(state):
                cycle = brand.GLOW[state + "_ms"]
                self.assertAlmostEqual(brand.glow(state, 0)["dim"], 0.0)
                self.assertAlmostEqual(brand.glow(state, cycle)["dim"], 0.0)
                self.assertAlmostEqual(brand.glow(state, cycle * 2)["dim"], 0.0)
                self.assertAlmostEqual(brand.glow(state, cycle - 1)["dim"], 0.0, places=5)

    def test_recovering_runs_the_same_cycle_faster(self):
        self.assertLess(brand.GLOW["recovering_ms"], brand.GLOW["monitoring_ms"])
        for step in range(0, 100):
            fraction = step / 100.0
            self.assertFrame(brand.glow("recovering", fraction * brand.GLOW["recovering_ms"]),
                             brand.glow("monitoring", fraction * brand.GLOW["monitoring_ms"]))
        self.assertTrue(brand.glow_moves("recovering"))
        self.assertTrue(brand.glow_moves("monitoring"))

    def test_every_light_that_moves_loops_attention_slowest_and_a_failure_quickest(self):
        """v0.6.8, the user: "빨간 상태등일 때도 상태등이 움직이게 해줘", then "확인필요는 천천히 계속 부드럽게
        깜빡이고, 실패는 빠르게 움직이는거도 필요해". The same breath as the others, for as long as the state is
        shown however long ago it arrived; attention the slowest and a failure the quickest. Nothing pulses once."""
        self.assertEqual(brand.GLOW_BREATHES, ("monitoring", "waiting", "recovering", "attention", "failed"))
        self.assertFalse(hasattr(brand, "GLOW_PULSES"))
        rhythms = sorted(brand.GLOW_BREATHES, key=lambda state: brand.GLOW[state + "_ms"])
        self.assertEqual(rhythms, ["failed", "recovering", "monitoring", "waiting", "attention"])
        for state in ("attention", "failed"):
            cycle = brand.GLOW[state + "_ms"]
            with self.subTest(state):
                for step in range(0, 100):
                    fraction = step / 100.0
                    for since in (None, -5, 0, 700, 5000, 99999):
                        self.assertFrame(brand.glow(state, 3 * cycle + fraction * cycle, since),
                                         brand.glow("monitoring", fraction * brand.GLOW["monitoring_ms"]))
                for since in (None, -5, 0, 700, 5000, 99999):
                    self.assertTrue(brand.glow_moves(state, since))
                self.assertFalse(brand.glow_moves(state, 5000, reduced=True))

    def test_waiting_breathes_exactly_as_monitoring_does(self):
        """v0.6.9, the user, of the panel: "상태등이 맨위에 있는건 안 깜빡이네?". Waiting held lit and still
        while the notification-area icon, which draws it as watching, kept moving. It is watching with something
        to watch for, so it breathes as watching does, frame for frame, and only the word says which."""
        self.assertEqual(brand.GLOW["waiting_ms"], brand.GLOW["monitoring_ms"])
        for elapsed in range(0, 9000, 333):
            self.assertEqual(brand.glow("waiting", elapsed), brand.glow("monitoring", elapsed), elapsed)
        self.assertTrue(brand.glow_moves("waiting", 0))
        self.assertFalse(brand.glow_moves("waiting", 0, reduced=True))

    def test_checking_holds_lit_with_no_glow_and_turns_its_arc(self):
        for elapsed in range(0, 3200, 50):
            frame = brand.glow("checking", elapsed)
            self.assertEqual((frame["dim"], frame["opacity"], frame["spread"]), (0.0, 0.0, 0.0))

    def test_checking_turns_its_arc_once_every_1600ms(self):
        self.assertAlmostEqual(brand.glow("checking", 400)["arc"] - brand.glow("checking", 0)["arc"], 90.0)
        self.assertAlmostEqual(brand.glow("checking", 1600)["arc"], 0.0)
        self.assertEqual(brand.glow("checking", 400, reduced=True)["arc"], 300)
        self.assertTrue(brand.glow_moves("checking"))

    def test_attention_is_at_its_lowest_halfway_through_its_slow_breath_and_lit_at_either_end(self):
        cycle = brand.GLOW["attention_ms"]
        self.assertAlmostEqual(brand.glow("attention", cycle * 0.5)["dim"], 1.0 - brand.glow_floor())
        self.assertAlmostEqual(brand.glow("attention", cycle * 0.5)["opacity"], 0.0)
        for at in (0, cycle, 7 * cycle):
            self.assertAlmostEqual(brand.glow("attention", at)["dim"], 0.0)
            self.assertAlmostEqual(brand.glow("attention", at)["opacity"], brand.GLOW["peak"])

    def test_reduced_motion_holds_every_light_lit_with_no_glow(self):
        for state in ("monitoring", "waiting", "checking", "recovering", "attention", "failed"):
            with self.subTest(state):
                for elapsed in (0, 350, 700, 800, 1800, 2700, 9999):
                    frame = brand.glow(state, elapsed, elapsed, reduced=True)
                    self.assertEqual(frame, {"dim": 0.0, "opacity": 0.0, "spread": 0.0,
                                             "arc": 300 if state == "checking" else None})
                self.assertFalse(brand.glow_moves(state, 0, reduced=True))
        self.assertFalse(hasattr(brand, "glow_rest"))

    def test_the_glow_falls_off_from_the_dot_to_nothing_at_its_reach(self):
        stops = brand.glow_stops(5)                       # the window's dot: 0.6 of 5 px is 3
        self.assertEqual([alpha for _, alpha in stops], [0.67, 0.67, 0.58, 0.50, 0.0])
        positions = [position for position, _ in stops]
        self.assertEqual(positions, sorted(positions))
        self.assertAlmostEqual(positions[1], 5 / 8.0)
        self.assertAlmostEqual(positions[2], (5 + 0.14 * 3) / 8.0)
        self.assertAlmostEqual(positions[3], (5 + 0.66 * 3) / 8.0)
        self.assertEqual(positions[-1], 1.0)
        self.assertEqual(brand.glow_radius(5), 8.0)
        self.assertEqual(brand.glow_radius(5, 0.0), 5.0)
        self.assertEqual(brand.glow_radius(5, 0.5), 6.5)
        # Never a dip and a second rise: a gap between the dot and a ring reads as a target.
        alphas = [alpha for _, alpha in stops]
        self.assertEqual(alphas, sorted(alphas, reverse=True))

    def test_the_spread_reaches_its_share_of_the_dot_and_no_further(self):
        """"지금은 너무 많이 커지는거 같아": the first cut reached 7 px past the dot's edge and a little more as it
        swelled. v0.6.5 answered with a flat 3 px, which is a different light on each surface - two thirds of
        the popup's radius, half of the panel's. It is a share of the dot now, and no frame of any state
        passes it."""
        for surface, dot in brand.STATUS_DOT.items():
            with self.subTest(surface):
                reach = brand.GLOW["reach_of_radius"] * dot
                self.assertAlmostEqual(brand.glow_extent(dot) - dot, reach)
                reached = max(brand.glow_radius(dot, frame["spread"]) - dot
                              for state in ("monitoring", "recovering")
                              for _, frame in self.cycle(state, step=5.0))
                self.assertAlmostEqual(reached, reach, places=3)
        self.assertEqual(brand.glow_extent(brand.STATUS_DOT["window"]), 8)
        self.assertAlmostEqual(brand.glow_extent(brand.STATUS_DOT["popup"]), 7.2)

    def test_the_largest_glow_fits_the_column_the_window_keeps_for_it(self):
        """The window's header gives the light a 28 px column and asks 2 * ceil(extent) of it at
        every scaling (SettingsApp's LayoutAudit)."""
        extent = brand.glow_extent(brand.STATUS_DOT["window"])
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0):
            with self.subTest(scale=scale):
                self.assertLessEqual(2 * math.ceil(extent * scale - 1e-9), int(28 * scale + 0.5))

    def test_the_transition_eases_out_on_one_curve(self):
        """v0.6.5: a switch glides in MOTION's time on MOTION's curve, on every surface."""
        self.assertEqual(brand.MOTION["transition_ms"], 160)
        self.assertEqual(brand.css_ease(), "cubic-bezier(0.33, 1, 0.68, 1)")
        self.assertEqual((brand.ease(-1), brand.ease(0), brand.ease(1), brand.ease(2)), (0.0, 0.0, 1.0, 1.0))
        values = [brand.ease(step / 100.0) for step in range(101)]
        self.assertEqual(values, sorted(values))
        # An ease-out: it leaves at once and settles - past halfway at a fifth of its time.
        self.assertGreater(brand.ease(0.2), 0.45)
        self.assertLess(1.0 - brand.ease(0.9), 0.01)
        # easeOutCubic, 1 - (1 - t)^3, to within the curve's fit.
        for step in range(1, 100):
            t = step / 100.0
            self.assertAlmostEqual(brand.ease(t), 1 - (1 - t) ** 3, delta=0.03)
        # Solved, not approximated: the curve's x at the parameter found is the progress asked for.
        x1, _, x2, _ = brand.MOTION["ease"]
        for step in range(1, 100):
            progress = step / 100.0
            low, high = 0.0, 1.0
            for _ in range(60):
                middle = (low + high) / 2.0
                if brand._bezier(x1, x2, middle) < progress:
                    low = middle
                else:
                    high = middle
            self.assertAlmostEqual(brand.ease(progress), brand._bezier(*brand.MOTION["ease"][1::2], low),
                                   delta=1e-5)


class GeneratedWindowTokenTests(unittest.TestCase):
    def setUp(self):
        self.source = make_brand.TARGET.read_text(encoding="utf-8")

    def test_brand_cs_declares_no_array(self):
        """The in-box compiler keeps a constant array's initializer in a class it names with a
        random GUID, and normalize_pe.py refuses the build that carries one."""
        code = "\n".join(line.split("//")[0] for line in self.source.splitlines())
        self.assertIsNone(re.search(r"\[\s*\]|new\s+\w+\s*\[|stackalloc", code))
        self.assertNotRegex(code, r"\bswitch\s*\(")

    def test_brand_cs_carries_the_new_tokens(self):
        for text in ("AccentHover", "AccentPressed", "internal const int FieldHeight = 35;",
                     "internal const float ElevCardShadowAlpha = 0.55f;",
                     "internal const int ElevCardReachBottom = 25;",
                     "internal const double GlowMonitoringMs = 4400;",
                     "internal const double TransitionEaseX1 = 0.33;", "internal static double Ease(",
                     "internal static bool Glow(", "internal static bool GlowMoves(",
                     "internal static Color StatusFill(", "internal static Color StatusSystem("):
            self.assertIn(text, self.source)

    def test_brand_cs_has_a_dark_twin_with_the_same_names(self):
        """Every theme-dependent name in Brand is declared again, once, in Brand.Dark.

        Brand.Dark is its own body, up to its closing brace: since v0.6.10 the designs' classes follow it, each with
        a Dark of its own, and those are held to the same names by the next test."""
        head, _, dark = self.source.partition("\n        internal static class Dark\n")
        self.assertTrue(dark, "Brand.cs declares no Brand.Dark")
        dark = dark[:dark.index("\n        }\n")]
        twins = [name for name, _, _ in make_brand.FIELDS] + [name for name, _, _ in make_brand.DERIVED]
        for name in twins:
            pattern = r"internal static readonly Color %s\s*=" % name
            self.assertEqual(len(re.findall(pattern, head)), 1, name)
            self.assertEqual(len(re.findall(pattern, dark)), 1, name)
        for signature in ("internal static Color StatusFill(string state)",
                          "internal static Color CheckFill(bool on, bool enabled)",
                          "internal static Color CheckEdge(bool on, bool enabled)",
                          "internal static bool CheckMark(bool on, bool enabled, out Color mark)",
                          "internal static int ElevationCount(string recipe)",
                          "internal static bool ElevationShadow(string recipe, int index,"):
            self.assertEqual(head.count(signature), 1, signature)
            self.assertEqual(dark.count(signature), 1, signature)
        for side in ("Left", "Top", "Right", "Bottom"):
            for recipe in ("Card", "Control", "Inset"):
                self.assertIn("internal const int Elev%sReach%s = " % (recipe, side), dark)
        # What does not change with the theme lives in Brand alone.
        for name in ("CheckWell(", "CheckSystemFill(", "CheckSystemEdge(", "CheckSystemMark(",
                     "StatusSystem(", "Glow(", "CheckMarkCornerX", "CheckSize", "RadiusCheck"):
            self.assertIn(name, head)
            self.assertNotIn(name, dark)

    def test_each_design_with_colours_of_its_own_has_a_class_and_a_dark_twin_with_brands_names(self):
        """v0.6.10. Classic and Plain have colours of their own, Still draws in Soft's: each of the two is a class beside
        Brand.Dark with a Dark of its own, and each of the four declares every colour, the card's ground and the check
        box under the names Brand gives Soft's - and nothing else. Its status light is Brand's, its elevation its theme's
        or none, and what else a design decides is one of Brand's Design rules."""
        own = [design for design in brand.DESIGNS if brand.palette("light", design) is not brand.LIGHT]
        self.assertEqual(own, ["classic", "plain"])
        twins = [name for name, _, _ in make_brand.FIELDS] + [name for name, _, _ in make_brand.DERIVED]
        for design in own:
            name = design.capitalize()
            opening = "\n        internal static class %s\n        {\n" % name
            self.assertEqual(self.source.count(opening), 1, name)
            body = self.source[self.source.index(opening):]
            body = body[:body.index("\n        }\n")]
            light, _, dark = body.partition("\n            internal static class Dark\n")
            self.assertTrue(dark, name + " has no Dark")
            for part, text in (("light", light), ("dark", dark)):
                with self.subTest(design=design, theme=part):
                    for field in twins:
                        self.assertEqual(len(re.findall(r"internal static readonly Color %s\s*=" % field, text)), 1, field)
                    self.assertEqual(len(re.findall(r"internal static readonly Color ", text)), len(twins))
                    for signature in ("internal static Color CheckFill(bool on, bool enabled)",
                                      "internal static Color CheckEdge(bool on, bool enabled)",
                                      "internal static bool CheckMark(bool on, bool enabled, out Color mark)"):
                        self.assertEqual(text.count(signature), 1, signature)
                    for absent in ("StatusFill(", "ElevationCount(", "ElevationShadow(", "internal const"):
                        self.assertNotIn(absent, text)
        # The rules take a design's name and live in Brand alone.
        head = self.source[:self.source.index("\n        internal static class Dark\n")]
        for rule in ("DesignOf(object value)", "DesignColours(string design)", "DesignDepth(string design)",
                     "DesignGlow(string design)", "DesignBreathes(string design)", "DesignGlides(string design)",
                     "DesignAccentBar(string design)", "DesignRadius(string design, string role)"):
            self.assertEqual(self.source.count(rule), 1, rule)
            self.assertIn(rule, head)


CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

GLOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
$invariant = [Globalization.CultureInfo]::InvariantCulture
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_DLL)
$brand = $assembly.GetType('CodexAutoResume.Brand', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
$glow = $brand.GetMethod('Glow', $flags)
$moves = $brand.GetMethod('GlowMoves', $flags)
$fill = $brand.GetMethod('StatusFill', $flags)
$system = $brand.GetMethod('StatusSystem', $flags)
foreach ($pair in @(@('Glow', $glow), @('GlowMoves', $moves), @('StatusFill', $fill), @('StatusSystem', $system))) {
    if (-not $pair[1]) { throw ('missing ' + $pair[0]) }
}
function Text([object]$value) { return ([double]$value).ToString('R', $invariant) }
$moments = ConvertFrom-Json $env:CAR_MOMENTS
$since = ConvertFrom-Json $env:CAR_SINCE
foreach ($state in (ConvertFrom-Json $env:CAR_STATES)) {
    $state = [string]$state
    'fill|' + $state + '|' + ('{0:X8}' -f $fill.Invoke($null, [object[]]@($state)).ToArgb())
    'system|' + $state + '|' + [string]$system.Invoke($null, [object[]]@($state)).Name
    foreach ($reduced in @($false, $true)) {
        foreach ($entered in $since) {
            'moves|' + $state + '|' + (Text $entered) + '|' + $reduced + '|' + [bool]$moves.Invoke($null, [object[]]@($state, [double]$entered, [bool]$reduced))
            foreach ($ms in $moments) {
                $call = [object[]]@($state, [double]$ms, [double]$entered, [bool]$reduced, $null, $null, $null, $null)
                $shown = [bool]$glow.Invoke($null, $call)
                'glow|' + $state + '|' + (Text $ms) + '|' + (Text $entered) + '|' + $reduced + '|' + $shown + '|' + (Text $call[4]) + '|' + (Text $call[5]) + '|' + (Text $call[6]) + '|' + (Text $call[7])
            }
        }
    }
}
foreach ($field in $brand.GetFields($flags)) {
    if ($field.IsLiteral -and $field.FieldType -ne [string]) { 'const|' + $field.Name + '|' + (Text $field.GetRawConstantValue()) }
}
$ease = $brand.GetMethod('Ease', $flags)
if (-not $ease) { throw 'missing Ease' }
foreach ($step in -10..110) {
    $progress = [double]$step / 100.0
    'ease|' + (Text $progress) + '|' + (Text $ease.Invoke($null, [object[]]@($progress)))
}
function Argb([object]$value) { return ('{0:X8}' -f $value.ToArgb()) }
$dark = $assembly.GetType('CodexAutoResume.Brand+Dark', $true)
foreach ($pair in @(@('light', $brand), @('dark', $dark))) {
    $theme = $pair[0]
    $type = $pair[1]
    foreach ($field in $type.GetFields($flags)) {
        if ($field.FieldType.FullName -eq 'System.Drawing.Color') { 'colour|' + $theme + '|' + $field.Name + '|' + (Argb $field.GetValue($null)) }
        elseif ($theme -eq 'dark' -and $field.IsLiteral) { 'darkconst|' + $field.Name + '|' + (Text $field.GetRawConstantValue()) }
    }
    $themeFill = $type.GetMethod('StatusFill', $flags)
    foreach ($state in (ConvertFrom-Json $env:CAR_STATES)) {
        'themefill|' + $theme + '|' + [string]$state + '|' + (Argb $themeFill.Invoke($null, [object[]]@([string]$state)))
    }
    $count = $type.GetMethod('ElevationCount', $flags)
    $shadow = $type.GetMethod('ElevationShadow', $flags)
    foreach ($recipe in @('card', 'control', 'inset', 'page')) {
        'count|' + $theme + '|' + $recipe + '|' + [int]$count.Invoke($null, [object[]]@($recipe))
        foreach ($index in 0..3) {
            $call = [object[]]@($recipe, [int]$index, $null, $null, $null, $null, $null, $null)
            $shown = [bool]$shadow.Invoke($null, $call)
            'shadow|' + $theme + '|' + $recipe + '|' + $index + '|' + $shown + '|' + (Text $call[2]) + '|' + (Text $call[3]) + '|' + (Text $call[4]) + '|' + (Text $call[5]) + '|' + [bool]$call[6] + '|' + (Argb $call[7])
        }
    }
    foreach ($on in @($false, $true)) {
        foreach ($enabled in @($false, $true)) {
            $fill = $type.GetMethod('CheckFill', $flags).Invoke($null, [object[]]@($on, $enabled))
            $edge = $type.GetMethod('CheckEdge', $flags).Invoke($null, [object[]]@($on, $enabled))
            $call = [object[]]@($on, $enabled, $null)
            $marked = [bool]$type.GetMethod('CheckMark', $flags).Invoke($null, $call)
            'check|' + $theme + '|' + $on + '|' + $enabled + '|' + (Argb $fill) + '|' + (Argb $edge) + '|' + $marked + '|' + (Argb $call[2])
        }
    }
}
foreach ($on in @($false, $true)) {
    foreach ($enabled in @($false, $true)) {
        $fill = $brand.GetMethod('CheckSystemFill', $flags).Invoke($null, [object[]]@($on, $enabled))
        $edge = $brand.GetMethod('CheckSystemEdge', $flags).Invoke($null, [object[]]@($on, $enabled))
        $call = [object[]]@($on, $enabled, $null)
        $marked = [bool]$brand.GetMethod('CheckSystemMark', $flags).Invoke($null, $call)
        $well = [bool]$brand.GetMethod('CheckWell', $flags).Invoke($null, [object[]]@($on, $enabled))
        'checksystem|' + $on + '|' + $enabled + '|' + $fill.Name + '|' + $edge.Name + '|' + $marked + '|' + $(if ($marked) { $call[2].Name } else { '' }) + '|' + $well
    }
}
# v0.6.10: each design with colours of its own, light and dark, and the Design rules for every design and for names
# that are none.
foreach ($design in (ConvertFrom-Json $env:CAR_DESIGN_CLASSES)) {
    $name = [string]$design[1]
    foreach ($pair in @(@('light', ('CodexAutoResume.Brand+' + $name)), @('dark', ('CodexAutoResume.Brand+' + $name + '+Dark')))) {
        $type = $assembly.GetType($pair[1], $true)
        foreach ($field in $type.GetFields($flags)) {
            if ($field.FieldType.FullName -eq 'System.Drawing.Color') { 'designcolour|' + $design[0] + '|' + $pair[0] + '|' + $field.Name + '|' + (Argb $field.GetValue($null)) }
            else { 'designother|' + $design[0] + '|' + $pair[0] + '|' + $field.Name }
        }
        foreach ($on in @($false, $true)) {
            foreach ($enabled in @($false, $true)) {
                $fill = $type.GetMethod('CheckFill', $flags).Invoke($null, [object[]]@($on, $enabled))
                $edge = $type.GetMethod('CheckEdge', $flags).Invoke($null, [object[]]@($on, $enabled))
                $call = [object[]]@($on, $enabled, $null)
                $marked = [bool]$type.GetMethod('CheckMark', $flags).Invoke($null, $call)
                'designcheck|' + $design[0] + '|' + $pair[0] + '|' + $on + '|' + $enabled + '|' + (Argb $fill) + '|' + (Argb $edge) + '|' + $marked + '|' + (Argb $call[2])
            }
        }
    }
}
$designNames = (ConvertFrom-Json $env:CAR_DESIGN_NAMES)
$roles = (ConvertFrom-Json $env:CAR_DESIGN_ROLES)
for ($i = 0; $i -lt $designNames.Count; $i++) {
    $design = [string]$designNames[$i]
    foreach ($rule in @('DesignDepth', 'DesignGlow', 'DesignBreathes', 'DesignGlides', 'DesignAccentBar')) {
        'designrule|' + $i + '|' + $rule + '|' + [bool]$brand.GetMethod($rule, $flags).Invoke($null, [object[]]@($design))
    }
    'designcolours|' + $i + '|' + [string]$brand.GetMethod('DesignColours', $flags).Invoke($null, [object[]]@($design))
    for ($r = 0; $r -lt $roles.Count; $r++) {
        'designradius|' + $i + '|' + $r + '|' + [int]$brand.GetMethod('DesignRadius', $flags).Invoke($null, [object[]]@($design, [string]$roles[$r]))
    }
}
$stored = (ConvertFrom-Json $env:CAR_DESIGN_STORED)
for ($i = 0; $i -lt $stored.Count; $i++) {
    'designof|' + $i + '|' + [string]$brand.GetMethod('DesignOf', $flags).Invoke($null, [object[]]@(,$stored[$i]))
}
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class GeneratedStatusLightTests(unittest.TestCase):
    """Brand.cs's status light is compiled and called, and must say what brand.py says: the
    window, the popup and the panel all draw one light. The moments fall in every phase of both
    cycles and on their edges: 800 and 2080 end monitoring's fall and rise, 2720 is its peak."""

    STATES = ("monitoring", "waiting", "checking", "recovering", "attention", "failed", "paused",
              "idle", "", "stopped")
    MOMENTS = (0, 250, 400, 500, 700, 800, 900, 1100, 1300, 1399, 1400, 1700, 1800, 1900, 2080, 2200,
               2400, 2700, 2720, 3000, 3199, 3600, 5000, 7777)
    SINCE = (-1, 0, 350, 700, 1000, 1190, 1300, 1399, 1400, 5000)       # read by neither side since v0.6.8
    # v0.6.10: the designs by name, and names that are none, which every rule answers as the default design.
    DESIGN_NAMES = brand.DESIGNS + ("", "Soft", "CLASSIC", "plain ", "bogus")
    DESIGN_ROLES = tuple(brand.RADII) + ("", "Card", "bogus")
    # Stored values, as settings.json may hold them.
    DESIGN_STORED = list(brand.DESIGNS) + ["Soft", "Plain", "", " classic", None, 1, 0, True, False, 2.5]

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        dll = work / "Brand.dll"
        compiled = subprocess.run([str(CSC), "/nologo", "/target:library", "/out:" + str(dll),
                                   "/reference:System.Drawing.dll", str(make_brand.TARGET)],
                                  capture_output=True, text=True, errors="replace", timeout=300)
        cls.error, cls.records = "", {}
        if compiled.returncode != 0:
            cls.error = "Brand.cs does not compile: " + compiled.stdout + compiled.stderr
            return
        probe = work / "probe.ps1"
        probe.write_text(GLOW_PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_DLL=str(dll), CAR_STATES=json.dumps(list(cls.STATES)),
                     CAR_MOMENTS=json.dumps(list(cls.MOMENTS)), CAR_SINCE=json.dumps(list(cls.SINCE)),
                     CAR_DESIGN_CLASSES=json.dumps([[design, design.capitalize()] for design in brand.DESIGNS
                                                    if brand.palette("light", design) is not brand.LIGHT]),
                     CAR_DESIGN_NAMES=json.dumps(list(cls.DESIGN_NAMES)),
                     CAR_DESIGN_ROLES=json.dumps(list(cls.DESIGN_ROLES)),
                     CAR_DESIGN_STORED=json.dumps(cls.DESIGN_STORED)))
        if result.returncode != 0:
            cls.error = "the probe did not run: " + (result.stderr or result.stdout)[-2000:]
            return
        for line in result.stdout.splitlines():
            kind, _, rest = line.strip().partition("|")
            if rest:
                cls.records.setdefault(kind, []).append(rest.split("|"))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if self.error:
            self.fail(self.error)

    def test_the_window_glow_is_brand_glow(self):
        rows = self.records.get("glow", [])
        self.assertEqual(len(rows), len(self.STATES) * 2 * len(self.SINCE) * len(self.MOMENTS))
        for state, ms, since, reduced, shown, dim, opacity, spread, arc in rows:
            entered = float(since)
            expected = brand.glow(state, float(ms), entered if entered >= 0 else None,
                                  reduced=reduced == "True")
            with self.subTest(state=state, ms=ms, since=since, reduced=reduced):
                self.assertEqual(shown == "True", expected is not None)
                if expected is not None:
                    self.assertAlmostEqual(float(dim), expected["dim"], delta=1e-9)
                    self.assertAlmostEqual(float(opacity), expected["opacity"], delta=1e-9)
                    self.assertAlmostEqual(float(spread), expected["spread"], delta=1e-9)
                    if expected["arc"] is None:
                        self.assertEqual(float(arc), -1.0)
                    else:
                        self.assertAlmostEqual(float(arc), expected["arc"], delta=1e-9)

    def test_the_window_timer_rule_is_brand_glow_moves(self):
        rows = self.records.get("moves", [])
        self.assertEqual(len(rows), len(self.STATES) * 2 * len(self.SINCE))
        for state, since, reduced, moves in rows:
            entered = float(since)
            with self.subTest(state=state, since=since, reduced=reduced):
                self.assertEqual(moves == "True", brand.glow_moves(
                    state, entered if entered >= 0 else None, reduced=reduced == "True"))

    def test_the_window_eases_a_transition_as_brand_ease_does(self):
        rows = self.records.get("ease", [])
        self.assertEqual(len(rows), 121)
        for progress, value in rows:
            with self.subTest(progress=progress):
                self.assertAlmostEqual(float(value), brand.ease(float(progress)), delta=1e-9)

    def test_the_window_fills_the_dot_from_the_palette(self):
        fills = dict(self.records.get("fill", []))
        systems = dict(self.records.get("system", []))
        for state in self.STATES:
            with self.subTest(state=state):
                self.assertEqual("#" + fills[state][-6:], brand.LIGHT[brand.status_fill(state)])
                self.assertEqual(systems[state], brand.status_system(state))

    def test_every_generated_constant_reads_back_as_brand_py_wrote_it(self):
        for kind, sections in (("const", make_brand.sections()), ("darkconst", make_brand.dark_sections())):
            constants = dict(self.records.get(kind, []))
            expected = [item for _, items in sections for item in items]
            self.assertTrue(expected)
            self.assertEqual(set(constants), {name for name, _, _ in expected})
            for name, _, value in expected:
                with self.subTest(kind=kind, name=name):
                    self.assertIn(name, constants)
                    self.assertAlmostEqual(float(constants[name]), value, delta=1e-6 * max(1.0, abs(value)))

    def test_both_themes_colours_read_back_as_the_palette(self):
        colours = {}
        for theme, name, value in self.records.get("colour", []):
            colours.setdefault(theme, {})[name] = value
        for theme in brand.THEMES:
            tokens = brand.palette(theme)
            expected = {name: tokens[token] for name, token, _ in make_brand.FIELDS}
            expected.update({name: function(theme) for name, function, _ in make_brand.DERIVED})
            with self.subTest(theme=theme):
                self.assertEqual({name: "#" + value[-6:] for name, value in colours[theme].items()}, expected)
                self.assertTrue(all(value.startswith("FF") for value in colours[theme].values()))

    def test_each_theme_fills_the_dot_from_its_own_palette(self):
        rows = self.records.get("themefill", [])
        self.assertEqual(len(rows), 2 * len(self.STATES))
        for theme, state, value in rows:
            with self.subTest(theme=theme, state=state):
                self.assertEqual("#" + value[-6:], brand.status_colour(state, theme))

    def test_each_theme_elevation_is_brand_shadows(self):
        counts = {(theme, recipe): int(value) for theme, recipe, value in self.records.get("count", [])}
        rows = self.records.get("shadow", [])
        self.assertEqual(len(rows), 2 * 4 * 4)
        for theme, recipe, index, shown, dx, dy, blur, alpha, inset, tone in rows:
            listed = brand.SHADOWS[theme].get(recipe, ())
            index = int(index)
            with self.subTest(theme=theme, recipe=recipe, index=index):
                self.assertEqual(counts[(theme, recipe)], len(listed))
                self.assertEqual(shown == "True", index < len(listed))
                if index < len(listed):
                    shadow = listed[index]
                    self.assertEqual((float(dx), float(dy), float(blur)), (shadow.dx, shadow.dy, shadow.blur))
                    self.assertEqual(float(alpha), shadow.alpha)          # a double: exactly as written
                    self.assertEqual(inset == "True", shadow.inset)
                    self.assertEqual("#" + tone[-6:], brand.palette(theme)[shadow.token])

    def test_each_theme_check_box_is_brand_check_box(self):
        rows = self.records.get("check", [])
        self.assertEqual(len(rows), 2 * 4)
        for theme, on, enabled, fill, edge, marked, mark in rows:
            expected = brand.check_box(on == "True", enabled == "True", theme)
            with self.subTest(theme=theme, on=on, enabled=enabled):
                self.assertEqual("#" + fill[-6:], expected["fill"])
                self.assertEqual("#" + edge[-6:], expected["edge"])
                self.assertEqual(marked == "True", expected["mark"] is not None)
                if expected["mark"] is not None:
                    self.assertEqual("#" + mark[-6:], expected["mark"])
        rows = self.records.get("checksystem", [])
        self.assertEqual(len(rows), 4)
        for on, enabled, fill, edge, marked, mark, well in rows:
            expected = brand.check_box_system(on == "True", enabled == "True")
            with self.subTest(on=on, enabled=enabled):
                self.assertEqual((fill, edge), (expected["fill"], expected["edge"]))
                self.assertEqual(mark or None, expected["mark"])
                self.assertEqual(marked == "True", expected["mark"] is not None)
                self.assertEqual(well == "True", brand.check_box(on == "True", enabled == "True")["well"])

    # ------------------------------------------------------------------ v0.6.10: the designs

    OWN_COLOURS = ("classic", "plain")

    def test_each_designs_colours_read_back_as_its_palette(self):
        """Brand.Classic, Brand.Plain and their Dark twins are brand.palette(theme, design) and brand.card_ground(theme,
        design), name for name, and hold nothing else; Soft's and Still's are Brand's and Brand.Dark's."""
        colours, other = {}, self.records.get("designother", [])
        for design, theme, name, value in self.records.get("designcolour", []):
            colours.setdefault((design, theme), {})[name] = value
        self.assertEqual(other, [], "a design's class holds colours only")
        self.assertEqual(sorted(colours), sorted((design, theme) for design in self.OWN_COLOURS for theme in brand.THEMES))
        for (design, theme), found in colours.items():
            tokens = brand.palette(theme, design)
            expected = {name: tokens[token] for name, token, _ in make_brand.FIELDS}
            expected.update({name: function(theme, design) for name, function, _ in make_brand.DERIVED})
            with self.subTest(design=design, theme=theme):
                self.assertEqual({name: "#" + value[-6:] for name, value in found.items()}, expected)
                self.assertTrue(all(value.startswith("FF") for value in found.values()))

    def test_each_designs_check_box_is_brand_check_box_in_that_design(self):
        rows = self.records.get("designcheck", [])
        self.assertEqual(len(rows), len(self.OWN_COLOURS) * 2 * 4)
        for design, theme, on, enabled, fill, edge, marked, mark in rows:
            expected = brand.check_box(on == "True", enabled == "True", theme, design)
            with self.subTest(design=design, theme=theme, on=on, enabled=enabled):
                self.assertEqual("#" + fill[-6:], expected["fill"])
                self.assertEqual("#" + edge[-6:], expected["edge"])
                self.assertEqual(marked == "True", expected["mark"] is not None)
                if expected["mark"] is not None:
                    self.assertEqual("#" + mark[-6:], expected["mark"])

    def test_every_design_rule_is_brand_designs_and_a_name_that_is_none_is_the_default(self):
        rules = {"DesignDepth": brand.design_depth, "DesignGlow": brand.design_glow,
                 "DesignBreathes": brand.design_breathes, "DesignGlides": brand.design_glides,
                 "DesignAccentBar": brand.design_accent_bar}
        found = self.records.get("designrule", [])
        self.assertEqual(len(found), len(self.DESIGN_NAMES) * len(rules))
        for index, rule, answer in found:
            name = self.DESIGN_NAMES[int(index)]
            design = name if name in brand.DESIGNS else brand.DEFAULT_DESIGN
            with self.subTest(design=name, rule=rule):
                self.assertEqual(answer == "True", rules[rule](design))
        for index, answer in self.records.get("designcolours", []):
            name = self.DESIGN_NAMES[int(index)]
            design = name if name in brand.DESIGNS else brand.DEFAULT_DESIGN
            with self.subTest(design=name, rule="DesignColours"):
                self.assertIs(brand.palette("light", answer), brand.palette("light", design))
                self.assertIs(brand.palette("dark", answer), brand.palette("dark", design))
                self.assertTrue(answer in self.OWN_COLOURS or answer == brand.DEFAULT_DESIGN, answer)
        radii = self.records.get("designradius", [])
        self.assertEqual(len(radii), len(self.DESIGN_NAMES) * len(self.DESIGN_ROLES))
        for index, role, value in radii:
            name, role = self.DESIGN_NAMES[int(index)], self.DESIGN_ROLES[int(role)]
            design = name if name in brand.DESIGNS else brand.DEFAULT_DESIGN
            with self.subTest(design=name, role=role):
                self.assertEqual(int(value), brand.design_radii(design).get(role, 0))
                self.assertLessEqual(int(value), brand.RADII.get(role, 0), "never rounder than Soft")

    def test_a_stored_design_is_read_as_the_settings_layer_reads_it(self):
        from codex_auto_resume import settings
        found = dict(self.records.get("designof", []))
        self.assertEqual(len(found), len(self.DESIGN_STORED))
        for index, value in enumerate(self.DESIGN_STORED):
            with self.subTest(value=value):
                self.assertEqual(found[str(index)], settings.design_preference({"design": value}))


class RetiredColourTests(unittest.TestCase):
    def test_no_tracked_file_still_carries_a_retired_colour(self):
        wanted = {value.lower() for value in RETIRED}
        offenders = []
        for name, path in tracked_text_files():
            if name == "tests/test_brand.py":
                continue          # this file has to name them to forbid them
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for found in HEX.findall(text):
                if found.lower() in wanted:
                    offenders.append("%s: %s" % (name, found))
        self.assertEqual(offenders, [], "retired colours are still in the tree")


if __name__ == "__main__":
    unittest.main()
