"""v0.6.10 in the notification-area popup: the Design setting.

The popup draws in the stored design as it draws in the stored theme - taken up from every read and
before every opening, and drawn again whole when it changes. Two things about it are held here
beyond the colours. What moves is two gates: the light moves where the design breathes, the switches
where it glides, and every stopper - Reduce motion, Windows' animation setting, High Contrast - holds
both in every design, so a design can take motion away and never bring any back. And a design
without depth draws no shadow at all: the canvas kept round the card for its lift is canvas, pixel
for pixel, and no cached ground or shadow image survives a change of design.
"""
from __future__ import annotations

import os
import time
import unittest
import unittest.mock

from codex_auto_resume import brand
from codex_auto_resume.ui import popup
from test_tray_popup import EN, NOW, STATUS, FakeControl
from test_tray_popup_v064 import OFFSCREEN, pixel_reader, task_rows

STATES = brand.GLOW_BREATHES + ("checking",)


def keep_preferences(case):
    case.addCleanup(popup.set_theme, popup.THEME_SYSTEM)
    case.addCleanup(popup.set_design, "soft")
    case.addCleanup(popup.set_reduce_motion, False)


class AdoptedDesignTests(unittest.TestCase):
    """The stored design, as the popup, the card and the icon take it up."""

    def setUp(self):
        keep_preferences(self)
        windows = unittest.mock.patch.object(popup.theme, "reduced_motion",
                                             lambda: bool(popup.theme._reduce_motion_setting))
        windows.start()
        self.addCleanup(windows.stop)

    def test_the_stored_design_is_adopted_and_anything_else_is_soft(self):
        for value in brand.DESIGNS:
            popup.adopt_settings({"design": value})
            self.assertEqual(popup.design_setting(), value)
        for junk in ("Soft", "look", "", None, 3, True):
            popup.adopt_settings({"design": junk})
            self.assertEqual(popup.design_setting(), "soft")
        popup.set_design("plain")
        popup.adopt_settings("not a dict")
        self.assertEqual(popup.design_setting(), "plain")
        self.assertEqual(popup.design_choice("classic"), "classic")
        self.assertEqual(popup.design_choice(["classic"]), "soft")

    def test_still_holds_the_light_and_the_switches_and_classic_and_plain_only_the_switches(self):
        expected = {"soft": (False, False), "still": (True, True), "classic": (False, True), "plain": (False, True)}
        for design, (light, controls) in expected.items():
            with self.subTest(design):
                popup.adopt_settings({"design": design})
                self.assertEqual((popup.light_still(), popup.controls_still()), (light, controls))

    def test_reduce_motion_holds_every_design_still(self):
        for design in brand.DESIGNS:
            with self.subTest(design):
                popup.adopt_settings({"design": design, "reduce_motion": True})
                self.assertTrue(popup.light_still())
                self.assertTrue(popup.controls_still())


class WindowGateTests(unittest.TestCase):
    """The window's two gates, over every design and every stopper: a truth table."""

    def setUp(self):
        keep_preferences(self)

    def gates(self, design, reduce_motion, windows_animates, contrast):
        popup.set_design(design)
        popup.set_reduce_motion(reduce_motion)
        shown = object.__new__(popup.Popup)
        with unittest.mock.patch.object(popup.theme, "high_contrast", lambda: contrast), \
                unittest.mock.patch.object(popup.theme, "apps_use_light_theme", lambda: True), \
                unittest.mock.patch.object(popup.theme, "reduced_motion",
                                           lambda: reduce_motion or not windows_animates):
            shown._read_look()
        return shown

    def test_the_light_moves_where_the_design_breathes_and_the_switches_where_it_glides(self):
        for design in brand.DESIGNS:
            for reduce_motion in (False, True):
                for windows_animates in (True, False):
                    for contrast in (False, True):
                        shown = self.gates(design, reduce_motion, windows_animates, contrast)
                        stopped = reduce_motion or not windows_animates or contrast
                        with self.subTest(design=design, reduce_motion=reduce_motion,
                                          windows_animates=windows_animates, contrast=contrast):
                            self.assertEqual(shown._design, design)
                            self.assertEqual(shown._light_still, stopped or not brand.DESIGN[design]["breathes"])
                            self.assertEqual(shown._controls_still, stopped or not brand.DESIGN[design]["glides"])

    def frames(self, design, reduced, state):
        shown = object.__new__(popup.Popup)
        shown._vm, shown._reduced, shown._state_since, shown._design = {"light": state}, reduced, 100.0, design
        found = []
        for moment in (100.0, 100.3, 100.9, 101.7, 102.2, 103.1, 104.0, 105.5):
            with unittest.mock.patch.object(popup.window.time, "monotonic", return_value=moment):
                found.append(shown.frame())
        return found

    def test_still_draws_every_frame_reduce_motion_draws(self):
        for state in STATES:
            with self.subTest(state):
                self.assertEqual(self.frames("still", False, state), self.frames("soft", True, state))

    def test_plain_dims_the_light_with_no_glow_and_classic_glows_as_soft_does(self):
        for state in brand.GLOW_BREATHES:
            plain, soft, classic = (self.frames(design, False, state) for design in ("plain", "soft", "classic"))
            with self.subTest(state):
                self.assertEqual({frame["opacity"] for frame in plain}, {0.0})
                self.assertEqual([frame["dim"] for frame in plain], [frame["dim"] for frame in soft])
                self.assertGreater(len({round(frame["dim"], 4) for frame in plain}), 3)
                self.assertEqual(classic, soft)

    def test_a_switch_glides_only_in_soft(self):
        plan = {"items": [{"kind": "switch", "target": ("switch", "a"), "checked": True}]}
        for design in brand.DESIGNS:
            shown = object.__new__(popup.Popup)
            shown.visible, shown._reduced, shown._design = True, False, design
            shown._switches, shown._glides = {("switch", "a"): False}, {}
            shown._follow_switches(plan)
            with self.subTest(design):
                self.assertEqual(bool(shown._glides), design == "soft")


def rgb_at(pixel, x, y):
    return tuple(pixel(int(x), int(y)))


@unittest.skipUnless(os.name == "nt", "the popup is a Windows window")
class DesignRendererTests(unittest.TestCase):
    def setUp(self):
        self.renderer = popup.Renderer()
        self.addCleanup(self.renderer.close)

    def draw(self, design, theme="light", scale=1.0, contrast=False, frame_at=0, state=None):
        self.renderer.theme, self.renderer.design, self.renderer.contrast = theme, design, contrast
        vm = popup.view_model(task_rows(), STATUS, EN, NOW)
        plan = self.renderer.layout(vm, scale, "en")
        light = state or vm["light"]
        frame = popup.halo(light, frame_at, design=design)
        canvas = self.renderer.draw(vm, plan, frame=frame)
        return vm, plan, pixel_reader(canvas, plan["size"][0])

    def margin_pixels(self, plan, pixel):
        """Every pixel between the canvas's edge and the card, where only a shadow could fall."""
        width, height = plan["size"]
        left, top, right, bottom = plan["card"]
        for y in range(height):
            for x in range(width):
                if not (left <= x < right and top <= y < bottom):
                    yield x, y, pixel(x, y)

    def test_without_depth_the_margin_is_canvas_and_the_card_is_its_ground(self):
        for design in ("classic", "plain"):
            for theme in brand.THEMES:
                for scale in (1.0, 1.5):
                    with self.subTest(design=design, theme=theme, scale=scale):
                        _, plan, pixel = self.draw(design, theme, scale)
                        canvas = brand.rgb(brand.palette(theme, design)["canvas"])
                        stray = [(x, y, value) for x, y, value in self.margin_pixels(plan, pixel) if value != canvas]
                        self.assertEqual(stray[:5], [])
                        card = plan["card"]
                        self.assertEqual(pixel(card[0] + 30, card[1] + 6),
                                         brand.rgb(brand.card_ground(theme, design)))

    def test_soft_and_still_lift_the_card_off_the_canvas(self):
        for design in ("soft", "still"):
            _, plan, pixel = self.draw(design)
            canvas = brand.rgb(brand.LIGHT["canvas"])
            card = plan["card"]
            self.assertNotEqual(pixel((card[0] + card[2]) // 2, card[3] + 4), canvas, design)

    def test_a_design_switched_under_a_drawn_frame_leaves_no_shadow_behind(self):
        _, plan, pixel = self.draw("soft")
        self.assertTrue(self.renderer._images)
        _, plan, pixel = self.draw("plain")
        canvas = brand.rgb(brand.PLAIN_LIGHT["canvas"])
        self.assertEqual([value for _, _, value in self.margin_pixels(plan, pixel) if value != canvas][:5], [])
        self.assertEqual(self.renderer._ground_key[3], "plain")
        self.assertEqual({key[2] for key in self.renderer._images} - {"plain"}, set())

    def test_classic_draws_its_accent_bar_inside_the_left_hairline_and_soft_does_not(self):
        for theme in brand.THEMES:
            _, plan, pixel = self.draw("classic", theme)
            card = plan["card"]
            middle = (card[1] + card[3]) // 2
            accent, ground = (brand.rgb(value) for value in (brand.palette(theme, "classic")["accent"],
                                                              brand.card_ground(theme, "classic")))
            with self.subTest(theme):
                self.assertEqual(pixel(card[0] + 2, middle), accent)
                self.assertEqual(pixel(card[0] + 3, middle), accent)
                self.assertEqual(pixel(card[0] + 1 + brand.ACCENT_BAR + 2, middle), ground)
            _, plan, pixel = self.draw("soft", theme)
            card = plan["card"]
            self.assertNotEqual(pixel(card[0] + 2, (card[1] + card[3]) // 2), accent)

    def test_plain_draws_no_glow_round_its_light(self):
        cycle = brand.GLOW["monitoring_ms"]
        for design, glows in (("plain", False), ("soft", True)):
            vm, plan, pixel = self.draw(design, frame_at=cycle, state="monitoring")
            halo = next(item for item in plan["items"] if item["kind"] == "halo")
            ground = brand.rgb(brand.card_ground("light", design))
            beyond = halo["cx"] - (brand.STATUS_DOT["popup"] + 2) * plan["scale"]
            with self.subTest(design):
                self.assertEqual(pixel(int(beyond), int(halo["cy"])) != ground, glows)

    def test_the_flat_designs_round_the_card_by_their_own_radius(self):
        for design in ("classic", "plain"):
            _, plan, pixel = self.draw(design)
            card = plan["card"]
            radius = brand.design_radii(design)["card"]
            self.assertLess(radius, brand.RADII["card"])
            canvas = brand.rgb(brand.palette("light", design)["canvas"])
            with self.subTest(design):
                # Outside the corner's curve it is canvas; along the top edge past it, the hairline - where
                # Soft's corner, twice as round, would still be curving away from the edge.
                self.assertEqual(pixel(card[0], card[1]), canvas)
                self.assertNotEqual(pixel(card[0] + radius + 1, card[1]), canvas)

    def test_high_contrast_is_one_look_whatever_the_design(self):
        drawn = {}
        for design in brand.DESIGNS:
            self.draw(design, "dark", 1.25, contrast=True)
            drawn[design] = self.renderer.canvas.pixels()
        self.assertEqual(len(set(drawn.values())), 1)

    def test_soft_is_what_it_was(self):
        self.renderer.design = "soft"
        _, _, pixel = self.draw("soft", "dark", 1.5)
        soft = self.renderer.canvas.pixels()
        other = popup.Renderer()
        self.addCleanup(other.close)
        other.theme = "dark"
        vm = popup.view_model(task_rows(), STATUS, EN, NOW)
        plan = other.layout(vm, 1.5, "en")
        other.draw(vm, plan, frame=popup.halo(vm["light"], 0))
        self.assertEqual(other.canvas.pixels(), soft)


@unittest.skipUnless(os.name == "nt", "the popup is a Windows window")
class PopupDesignTests(unittest.TestCase):
    def setUp(self):
        keep_preferences(self)
        for name, value in (("apps_use_light_theme", lambda: True), ("high_contrast", lambda: False),
                            ("reduced_motion", lambda: bool(popup.theme._reduce_motion_setting))):
            patcher = unittest.mock.patch.object(popup.theme, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def window(self):
        window = popup.Popup(control=FakeControl(task_rows()), strings=EN)
        window.create()
        self.addCleanup(window.destroy)
        window.model.apply_outcome(("read",), popup.perform(("read",), window.control), time.time())
        return window

    def test_a_design_stored_while_it_is_open_is_drawn_on_the_next_frame(self):
        window = self.window()
        window.show(activate=False, origin=OFFSCREEN)
        canvas = window.render()
        pixel = pixel_reader(canvas, canvas.width)
        self.assertEqual(pixel(1, 1), brand.rgb(brand.LIGHT["canvas"]))
        window.follow_settings(dict(theme="light", design="plain"))
        window._update()
        self.assertEqual(window._design, "plain")
        self.assertTrue(window._static_dirty)
        canvas = window.render()
        self.assertEqual(window._renderer.design, "plain")
        self.assertEqual(pixel_reader(canvas, canvas.width)(1, 1), brand.rgb(brand.PLAIN_LIGHT["canvas"]))
        self.assertTrue(window._controls_still)
        self.assertFalse(window._light_still)
        window.follow_settings(dict(theme="light", design="still"))
        window._update()
        self.assertTrue(window._light_still)
        self.assertFalse(window._frame_running)
