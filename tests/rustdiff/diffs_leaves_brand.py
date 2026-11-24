"""S1.1, car-brand: the panel's CSS, gui/Brand.cs and every function of `brand/` the surfaces read, held to the tag.

* BrandCsDiff - gui/Brand.cs as car-brand writes it (the port of build/make_brand.py's `render()`) is the committed file
  (as git stores it, LF) and what the tag's own make_brand.py renders, byte for byte; and `mark_frames` for every size
  the window asks plus others, the icon's frames as the window reads them.
* CssDiff - every function of brand/css.py: `css_scale`, `css_variables` of every theme and design palette and of other
  dicts, `css_elevation`, `css_design_blocks` (with no `extra` and with one), `css_glow_keyframes`, `css_ease`,
  `css_check_box`, `css_corner`, `css_glow_geometry`, `_number` and `_css_length`.
* PaletteDiff - the tables themselves, `rgb`, `mix`, `brighten`, `luminance`, `contrast`, `palette`, `theme_name`,
  `design_name`, `padding`, the design rules, `ease` and `_bezier`.
* LightDiff - the shadows (`shadows`, `reach`, `shadow_offset`, `shadow_alpha`, `elevation_colour` - math.erfc is the C
  runtime's in both - and `card_ground`), the check box and its mark, and the status light frame by frame.
* MarkDiff - the mark's rasteriser: `icon_rounded_square`, `icon_ring_arc` (math.atan2 and CPython's own math.hypot),
  `icon_head_centre`, `icon_head_box`, `icon_samples`, `icon_pixel` and `icon_render` (its bytes by SHA-256).
* ShapeDiff - the corner: `corner`, `outline`, `flatten`, `profile` (with its two kept tables, asked in an order that
  makes them answer a nearby radius from what they kept, and clear when full), `edge_at`, `inside_corner`, `inside`,
  `distance`.
* DaysDiff - `day_look` for every date 2025-2101, `path_points`, `mark_colour`, the scenes, specks and marks as elements
  and as text, `speck_reach`, `scene_frame`, `speck_frame`, `element_at`, `day_band`, `PressRun` and `sweep_at`.
* TrayDiff - the parts of ui/tray/motion.py gui/Brand.cs is made from: the icon's states, head colours, levels, turns,
  frames and frame times, and `IconFrames` (ground, boxes, samples, composed frames by SHA-256) with and without a look.

Floats are compared by their JSON text, so a float answer is equal only when it is the same double.
"""
from __future__ import annotations

import subprocess

from rustdiff import core, reference
from rustdiff.leaves import Leaves

ROOT = core.ROOT
RECORD: list[str] = []
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Shared by the scripts below (after the PRELUDE): the brand's modules and a bytes digest.
COMMON = r'''
import hashlib, math
from codex_auto_resume import brand
from codex_auto_resume.brand import css as bcss, days, shape
from codex_auto_resume.ui.tray import motion
rng = random.Random(627)

def sha(data):
    return hashlib.sha256(bytes(data)).hexdigest()

THEMES = ["light", "dark", "Dark", "", None, 5]
DESIGNS = ["soft", "classic", "plain", "Soft", "still", "", None, 3]
'''


class BrandCsDiff(Leaves):
    def test_render_and_frames(self):
        script = COMMON + r'''
import base64, os, subprocess, types
root, tag = sys.argv[1], sys.argv[2]
source = subprocess.run(["git", "-C", root, "show", tag + ":build/make_brand.py"], capture_output=True,
                        creationflags=0x08000000).stdout.decode("utf-8")
make = types.ModuleType("make_brand")
make.__file__ = os.path.join(os.getcwd(), "build", "make_brand.py")
exec(compile(source, "make_brand.py", "exec"), make.__dict__)
cases = [["make_brand.render"]] + [["make_brand.mark_frames", size] for size in (32, 40, 48, 64, 16, 20, 24, 72, 96)]
ops = {"make_brand.render": make.render,
       "make_brand.mark_frames": lambda size: base64.b64encode(make.mark_frames(size)).decode("ascii")}
finish(cases, ops)
'''
        done = self.family(script, str(ROOT), reference.TAG, label="brand-cs")
        rendered = done["results"][0]["ok"]
        committed = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:gui/Brand.cs"], capture_output=True,
                                   creationflags=NO_WINDOW).stdout.decode("utf-8")
        self.assertEqual(rendered, committed, "the tag's make_brand.render() is not the committed gui/Brand.cs")
        RECORD.append("gui/Brand.cs: car-brand's render() is the committed file and the tag's make_brand.render(), byte for byte "
                      "(%d bytes, %d lines), and mark_frames for 9 sizes identical to the tag's" % (
                          len(rendered.encode("utf-8")), rendered.count("\n")))


class CssDiff(Leaves):
    def test_every_css_function(self):
        script = COMMON + r'''
cases = [["brand.css_scale"], ["brand.css_corner"], ["brand.css_ease"], ["brand.css_check_box"], ["brand.css_glow_keyframes"],
         ["brand.css_design_blocks", None], ["brand.css_design_blocks", "--x-{theme}-{design}: 1;"], ["brand.css_design_blocks", ""]]
for theme in THEMES:
    cases.append(["brand.css_elevation", theme])
    for design in DESIGNS:
        cases.append(["brand.css_variables_of", theme, design])
cases += [["brand.css_variables", {}], ["brand.css_variables", {"on_accent": "#FFF", "a_b_c": "x y", "plain": ""}]]
for dot in list(brand.STATUS_DOT.values()) + [0, 1, 2.5, 3.3, 7, 10.25, 12.345678, 100]:
    cases.append(["brand.css_glow_geometry", dot])
values = [0, 0.0, -0.0, 1, -1, 14, 12.5, 0.3, 0.1 + 0.2, 1 / 3, 2 / 3, 0.00005, 0.00004999, 0.00015, 0.123456, 99.99995, 1e15, 1e16, 1e17,
          1e300, -1e300, 2 ** 53, 0.5, 1.5, 2.5, 0.00025, 0.00035, 1e-5, 123456.78915, 67.00000000000001, 1.57 * 16, 1.57 * 7]
values += [rng.uniform(-1000, 1000) for _ in range(400)] + [round(rng.uniform(0, 100), rng.randint(0, 6)) for _ in range(400)]
values += [rng.randint(-10 ** 6, 10 ** 6) for _ in range(50)] + [k / 1000.0 for k in range(-2000, 2001, 7)] + [k * 2.5 for k in range(41)]
for value in values:
    cases.append(["brand._number", value])
    cases.append(["brand._css_length", value])
ops = {"brand.css_scale": brand.css_scale, "brand.css_corner": bcss.css_corner, "brand.css_ease": brand.css_ease,
       "brand.css_check_box": brand.css_check_box, "brand.css_glow_keyframes": brand.css_glow_keyframes,
       "brand.css_design_blocks": lambda template: brand.css_design_blocks(
           None if template is None else (lambda theme, design: template.replace("{theme}", theme).replace("{design}", design))),
       "brand.css_elevation": brand.css_elevation,
       "brand.css_variables_of": lambda theme, design: brand.css_variables(brand.palette(theme, design)),
       "brand.css_variables": brand.css_variables, "brand.css_glow_geometry": brand.css_glow_geometry,
       "brand._number": bcss._number, "brand._css_length": brand._css_length}
finish(cases, ops)
'''
        done = self.family(script, label="css")
        named = sum(1 for case in done["cases"] if not case[0].startswith("brand._"))
        RECORD.append("css: %d cases - css_scale, css_corner, css_ease, css_check_box, css_glow_keyframes, css_design_blocks (none, "
                      "an extra, an empty one), css_elevation and css_variables of every theme and design palette, css_glow_geometry "
                      "(%d whole stylesheet strings), and _number/_css_length over %d values - identical to the tag's" % (
                          len(done["cases"]), named, (len(done["cases"]) - named) // 2))


class PaletteDiff(Leaves):
    def test_colours_tokens_scale_design_motion(self):
        script = COMMON + r'''
cases = [["brand.tables"]]
colours = ["#0B2545", "#ffffff", "#000000", "0B2545", "##0B2545", "#0B254", "#0B25456", "#GG0000", "# f0000", "#f 0000", "#+f0000",
           "#-f0000", "#0x0000", "", "#", "#00_000", "#é00000", "#\t00000", "#00000\n"] + list(brand.RAMP) + list(brand.LIGHT.values())
colours += ["#%06X" % rng.randrange(1 << 24) for _ in range(150)]
for value in colours:
    cases.append(["brand.rgb", value])
    cases.append(["brand.luminance", value])
amounts = [0, 0.0, 1, 0.5, 0.12, 0.22, 0.1, 1.07, -0.5, 2.0, 1e-9, 0.999999] + [rng.uniform(-0.5, 1.5) for _ in range(40)]
for _ in range(600):
    one, other = rng.choice(colours), rng.choice(colours)
    amount = rng.choice(amounts)
    cases.append(["brand.mix", one, other, amount])
    cases.append(["brand.brighten", one, amount * 2])
    cases.append(["brand.contrast", one, other])
for theme in THEMES + [[1], {"a": 1}]:
    cases.append(["brand.theme_name", theme])
    for design in DESIGNS:
        cases.append(["brand.palette", theme, design])
for design in DESIGNS + [[1]]:
    cases.append(["brand.design_name", design])
    for rule in ("design_depth", "design_glow", "design_accent_bar", "design_radii"):
        cases.append(["brand." + rule, design])
for key in list(brand.LAYOUT) + ["nothing", ""]:
    cases.append(["brand.padding", key])
progress = [-1, 0, 0.0, -0.0, 1, 1.0, 2, 1e-12, 1e-7, 0.5, 0.999999, 1 - 1e-12] + [k / 997.0 for k in range(998)] + [rng.random() for _ in range(300)]
for value in progress:
    cases.append(["brand.ease", value])
for _ in range(200):
    cases.append(["brand._bezier", rng.uniform(-1, 2), rng.uniform(-1, 2), rng.uniform(0, 1)])
tables = lambda: {"RAMP": brand.RAMP, "BRAND": brand.BRAND, "EDITION_INK": brand.tokens.EDITION_INK, "RADII": brand.RADII,
                  "SPACING": brand.SPACING, "TYPE": brand.TYPE, "TYPE_SCALE": brand.TYPE_SCALE, "LINE_HEIGHT": brand.LINE_HEIGHT,
                  "TYPE_ROLES": brand.TYPE_ROLES, "LAYOUT": brand.LAYOUT, "DESIGN": brand.DESIGN, "DESIGN_RADII": brand.DESIGN_RADII,
                  "MOTION": brand.MOTION, "SHADOWS": brand.SHADOWS, "CHECKBOX": brand.CHECKBOX, "GLOW": brand.GLOW,
                  "ICON_SHAPE": brand.ICON_SHAPE, "DAY_LOOKS": brand.DAY_LOOKS, "LUNAR_DAYS": brand.LUNAR_DAYS,
                  "DAY_EGG_COLOURS": days.DAY_EGG_COLOURS, "ICON_MOTION": motion.ICON_MOTION}
ops = {"brand.tables": tables, "brand.rgb": brand.rgb, "brand.luminance": brand.luminance, "brand.mix": brand.mix,
       "brand.brighten": brand.brighten, "brand.contrast": brand.contrast, "brand.theme_name": brand.theme_name,
       "brand.palette": brand.palette, "brand.design_name": brand.design_name, "brand.design_depth": brand.design_depth,
       "brand.design_glow": brand.design_glow, "brand.design_accent_bar": brand.design_accent_bar,
       "brand.design_radii": brand.design_radii, "brand.padding": brand.padding, "brand.ease": brand.ease,
       "brand._bezier": brand._bezier}
finish(cases, ops)
'''
        done = self.family(script, label="palette")
        RECORD.append("palette: %d cases - the tables, rgb/mix/brighten/luminance/contrast over well-formed and malformed colours, "
                      "palette/theme_name/design_name/the design rules for every name and others, padding, ease and _bezier - "
                      "identical to the tag's" % len(done["cases"]))


class LightDiff(Leaves):
    def test_shadows_check_box_status_light(self):
        script = COMMON + r'''
cases = []
recipes = ["card", "control", "inset", "nothing"]
sides = ["left", "top", "right", "bottom", "middle"]
every = [list(shadow) for theme in ("light", "dark") for listed in brand.SHADOWS[theme].values() for shadow in listed]
every += [[3, -2, 0, "shadow_dark", 0.5, False], [0, 0, 0, "shadow_light", 1, True], [1.5, 2.5, 3.5, "shadow_dark", 0.25, False]]
for recipe in recipes:
    for theme in THEMES:
        for design in DESIGNS:
            cases.append(["brand.shadows", recipe, theme, design])
        for factor in (1.0, 1, 1.25, 1.5, 2.0, 0.75, 3):
            cases.append(["brand.reach", recipe, theme, factor])
for theme in THEMES:
    for design in DESIGNS:
        cases.append(["brand.card_ground", theme, design])
for shadow in every:
    for side in sides:
        cases.append(["brand.shadow_offset", shadow, side])
        for d in (-6, -1, 0, 0.5, 1, 2, 3.25, 4, 7, 14, 30, -2.5):
            for factor in (1.0, 1.25, 2):
                cases.append(["brand.shadow_alpha", shadow, d, side, factor])
grounds = ["surface", "canvas", "raised", "inset", "#123456", "#FFFFFF"]
for recipe in recipes:
    for side in sides:
        for theme in ("light", "dark"):
            for design in ("soft", "classic"):
                for inside in (None, True, False):
                    for d in (0, 0.5, 1, 2, 3, 5.5, 9, 16):
                        cases.append(["brand.elevation_colour", recipe, side, d, rng.choice(grounds), theme, rng.choice((1.0, 1.5, 2)), inside, design])
cases.append(["brand.elevation_colour", "card", "left", 1, "surface", "dusk", 1.0, None, "soft"])
cases.append(["brand.elevation_colour", "card", "left", 1, "#XYZ", "light", 1.0, None, "soft"])
for checked in (True, False, 0, 1, "", "x", None):
    for enabled in (True, False, 0, 1):
        cases.append(["brand.check_box_state", checked, enabled])
        cases.append(["brand.check_box_system", checked, enabled])
        for theme in THEMES[:3]:
            for design in DESIGNS[:5]:
                cases.append(["brand.check_box", checked, enabled, theme, design])
for name in list(brand.SYSTEM_CSS) + ["Nothing", "", 5, None, [1]]:
    cases.append(["brand.css_system", name])
for factor, left, top in [(1.0, 0.0, 0.0), (1, 0, 0), (1.25, 3, 4.5), (1.5, 10.25, -2), (2.0, 0.1, 0.2), (1.75, 100, 200), (3, 1e-9, 1e9)]:
    cases.append(["brand.check_mark", factor, left, top])
    cases.append(["brand.check_mark_outline", factor, left, top])
states = list(brand.STATUS_FILL) + ["unknown", "", None, 5]
for state in states + [[1]]:
    cases.append(["brand.status_fill", state])
    cases.append(["brand.status_system", state])
    for theme in THEMES[:3]:
        for design in DESIGNS[:5]:
            cases.append(["brand.status_colour", state, theme, design])
cases.append(["brand.glow_floor"])
for fraction in [k / 211.0 for k in range(-40, 460)] + [rng.uniform(-5, 5) for _ in range(200)] + [0, 1, 0.5, -0.0, 1e9 + 0.25]:
    cases.append(["brand.glow_phase", fraction])
elapsed = [0, 1, -1, 4399, 4400, 4401, 2200, 1100.5, 123456789, 1e12 + 0.5, -2200.25] + [rng.uniform(0, 30000) for _ in range(80)] + [rng.randrange(0, 10 ** 7) for _ in range(40)]
for ms in elapsed:
    for cycle in (4400, 1200, 5600.0, 2800, 1):
        cases.append(["brand._breath", ms, cycle])
    for state in states:
        for reduced in (False, True):
            cases.append(["brand.glow", state, ms, reduced, rng.choice(DESIGNS[:4])])
for state in states:
    for reduced in (False, True, 0, 1, None):
        cases.append(["brand.glow_moves", state, reduced])
for radius in list(brand.STATUS_DOT.values()) + [0, 1, 2.5, 7.25, 100, 0.1]:
    cases.append(["brand.glow_reach", radius])
    cases.append(["brand.glow_extent", radius])
    for spread in (0, 0.0, 0.25, 0.5, 1, 1.0, 0.123456789):
        cases.append(["brand.glow_radius", radius, spread])
    if radius:
        cases.append(["brand.glow_stops", radius])
ops = {"brand.shadows": brand.shadows, "brand.reach": brand.reach, "brand.card_ground": brand.card_ground,
       "brand.shadow_offset": lambda shadow, side: brand.shadow_offset(brand.Shadow(*shadow), side),
       "brand.shadow_alpha": lambda shadow, d, side, factor: brand.shadow_alpha(brand.Shadow(*shadow), d, side, factor),
       "brand.elevation_colour": brand.elevation_colour, "brand.check_box_state": brand.check_box_state,
       "brand.check_box_system": brand.check_box_system, "brand.check_box": brand.check_box, "brand.css_system": brand.css_system,
       "brand.check_mark": brand.check_mark, "brand.check_mark_outline": brand.check_mark_outline,
       "brand.status_fill": brand.status_fill, "brand.status_system": brand.status_system, "brand.status_colour": brand.status_colour,
       "brand.glow_floor": brand.glow_floor, "brand.glow_phase": brand.glow_phase, "brand._breath": brand._breath,
       "brand.glow": lambda state, ms, reduced, design: brand.glow(state, ms, None, reduced=reduced, design=design),
       "brand.glow_moves": lambda state, reduced: brand.glow_moves(state, None, reduced=reduced),
       "brand.glow_reach": brand.glow_reach, "brand.glow_extent": brand.glow_extent, "brand.glow_radius": brand.glow_radius,
       "brand.glow_stops": brand.glow_stops}
finish(cases, ops)
'''
        done = self.family(script, label="light")
        count = lambda prefix: sum(1 for case in done["cases"] if case[0] == prefix)
        RECORD.append("shadows, check box and light: %d cases (%d shadow_alpha and %d elevation_colour through math.erfc, %d glow frames) "
                      "identical to the tag's" % (len(done["cases"]), count("brand.shadow_alpha"), count("brand.elevation_colour"),
                                                  count("brand.glow")))


class MarkDiff(Leaves):
    def test_the_rasteriser(self):
        script = COMMON + r'''
cases = []
for _ in range(3000):
    cases.append(["brand.icon_rounded_square", rng.uniform(-1.2, 1.2), rng.uniform(-1.2, 1.2), rng.choice((0.3, 0.24, 0.0, 0.5, 1.0))])
for _ in range(3000):
    start, end = rng.uniform(-7, 7), rng.uniform(-7, 7)
    cases.append(["brand.icon_ring_arc", rng.uniform(-0.7, 0.7), rng.uniform(-0.7, 0.7), 0.34, 0.53, start, end])
for x, y in [(0.0, 0.0), (0.0, -0.0), (-0.0, 0.0), (-0.0, -0.0), (0.4, 0.0), (-0.4, 0.0), (-0.4, -0.0), (0.0, 0.4), (0.0, -0.4)]:
    cases.append(["brand.icon_ring_arc", x, y, 0.0, 0.53, math.radians(125), math.radians(55)])
for angle in [None, 0, 55, 55.0, -305, 125, 360, 721.5] + [rng.uniform(-400, 400) for _ in range(100)]:
    cases.append(["brand.icon_head_centre", angle])
    for size in (16, 20, 24, 32, 48, 64, 256):
        cases.append(["brand.icon_head_box", size, angle])
for size in (1, 2, 16, 20, 24, 31, 32, 40, 48, 64):
    cases.append(["brand.icon_samples", size, 0.0, None, True, None, None])
for size, rim, angle, head, box, body in [(32, 0.06, None, True, None, None), (48, 0.1, 10.0, True, None, ["#EE8468", "#9E3A4B"]),
                                          (64, 0.0, -100.0, False, None, None), (64, 0.0, 200.0, True, [10, 5, 40, 30], None),
                                          (24, 0.2, 55, True, [0, 0, 24, 24], ["#D2453E", "#7A1F2B"]), (32, -0.1, 0, True, None, None),
                                          (16, 0.0, None, True, [3, 3, 3, 9], None), (32, 0.0, None, True, None, ["#XYZ", "#000000"])]:
    cases.append(["brand.icon_samples", size, rim, angle, head, box, body])
for _ in range(400):
    covered = rng.randint(0, 16)
    heads = rng.randint(0, covered)
    rest = covered - heads
    sample = [covered, heads, rng.randint(0, 255 * rest), rng.randint(0, 255 * rest), rng.randint(0, 255 * rest)]
    cases.append(["brand.icon_pixel", sample, [rng.randint(0, 255) for _ in range(3)]])
for size, rim in [(16, 0.0), (24, 0.0), (32, 0.0), (48, 0.0), (64, 0.0), (128, 0.0), (256, 0.0), (64, 0.05), (256, 0.035)]:
    cases.append(["brand.icon_render", size, rim])
ops = {"brand.icon_rounded_square": brand.icon_rounded_square, "brand.icon_ring_arc": brand.icon_ring_arc,
       "brand.icon_head_centre": brand.icon_head_centre, "brand.icon_head_box": brand.icon_head_box,
       "brand.icon_samples": lambda size, rim, angle, head, box, body: brand.icon_samples(
           size, rim, head_angle=angle, head=head, box=None if box is None else tuple(box), body=None if body is None else tuple(body)),
       "brand.icon_pixel": lambda sample, head: brand.icon_pixel(tuple(sample), tuple(head)),
       "brand.icon_render": lambda size, rim: (lambda data: [len(data), sha(data)])(brand.icon_render(size, rim))}
finish(cases, ops)
'''
        done = self.family(script, label="mark", chunk=2000)
        RECORD.append("mark: %d cases - the signed distance, the ring sector (atan2's zeros among them), the head's centre and box, "
                      "icon_samples at 18 sizes and options, icon_pixel, and icon_render's bytes at 16 to 256 px with and without a "
                      "rim - identical to the tag's" % len(done["cases"]))


class ShapeDiff(Leaves):
    def test_the_corner(self):
        script = COMMON + r'''
cases = []
for design in DESIGNS:
    cases.append(["shape.design_smoothing", design])
radii = [0, -1, 0.5, 0.51, 1, 2, 4, 7, 8, 11, 16, 999, 3.3, 15.999999]
for radius in radii:
    for smoothing in (0, 0.0, 0.6, 1.0, 0.3, -0.2, 2.0, 1e-10):
        for budget in (0, 0.25, 1, 4, 8, 8.8, 12.8, 16, 25.6, 100, -3):
            cases.append(["shape.corner", radius, smoothing, budget])
rects = [[0, 0, 100, 40], [0.5, 0.5, 30.5, 30.5], [10, 20, 13, 60], [0, 0, 1, 1], [-5, -5, 5, 5], [3.25, 7.75, 103.5, 31.125], [0, 0, 22, 22]]
for rect in rects:
    for radius in (0, 4, 8, 11, 16, 999, 0.5):
        for smoothing in (0.0, 0.6, 1.0):
            for corners in (None, ["top_left", "bottom_right"], [], ["top_right"]):
                cases.append(["shape.outline", rect, radius, smoothing, corners])
outlines = [shape.outline(rect, radius, smoothing) for rect in rects[:4] for radius in (4, 16) for smoothing in (0.0, 0.6)]
for segments in outlines:
    for steps in (1, 2, 8, 32):
        cases.append(["shape.flatten", [list(segment) for segment in segments], steps])
# The kept profiles: a nearby radius after a kept one is answered with the kept one (both sides keep the same), then
# enough others to clear the table, then the first again.
asked = [(16, 0.6, 50), (16.0000001, 0.6, 50), (16.0000004, 0.6, 50), (16.0000006, 0.6, 50), (16, 0.6000000004, 50), (16, 0.6000004, 50),
         (8, 0.0, 30), (8, 0.6, 4.4), (8, 0.6, 12.8), (8, 0.6, 9.6), (11, 0.6, 17.6), (7, 0.6, 7), (0, 0.6, 10), (3, 0.3, 100)]
asked += [(1 + k * 0.37, rng.choice((0.0, 0.6, 0.45, 0.6000000001)), rng.uniform(1, 60)) for k in range(80)]
asked += [(16.0000002, 0.6, 50), (16, 0.6, 50)]
for radius, smoothing, budget in asked:
    cases.append(["shape.profile", radius, smoothing, budget])
    for _ in range(3):
        cases.append(["shape.edge_at", radius, smoothing, budget, rng.uniform(-1, radius * 2)])
        cases.append(["shape.inside_corner", radius, smoothing, budget, rng.uniform(-1, radius * 2), rng.uniform(-1, radius * 2)])
for _ in range(1500):
    rect = rng.choice(rects)
    radius, smoothing = rng.choice((4, 8, 11, 16, 999, 0.5)), rng.choice((0.0, 0.6))
    cases.append(["shape.inside", rng.uniform(rect[0] - 2, rect[2] + 2), rng.uniform(rect[1] - 2, rect[3] + 2), rect, radius, smoothing])
for _ in range(2500):
    w, h = rng.uniform(1, 80), rng.uniform(1, 80)
    cases.append(["shape.distance", rng.uniform(-w - 20, w + 20), rng.uniform(-h - 20, h + 20), w, h, rng.choice((4, 8, 11, 16, 999, 2.5)),
                  rng.choice((0.0, 0.6, 1.0))])
def profile(radius, smoothing, budget):
    made = shape.profile(radius, smoothing, budget)
    return [list(made.corner), made.p, made.middle, made.joint, list(made.bezier_u), list(made.bezier_v), list(made.rho), list(made.lean)]
ops = {"shape.design_smoothing": shape.design_smoothing, "shape.corner": lambda r, s, b: list(shape.corner(r, s, b)),
       "shape.outline": lambda rect, r, s, corners: shape.outline(rect, r, s) if corners is None else shape.outline(rect, r, s, corners),
       "shape.flatten": lambda segments, steps: shape.flatten([tuple(each) for each in segments], steps),
       "shape.profile": profile,
       "shape.edge_at": lambda r, s, b, u: shape.edge_at(shape.profile(r, s, b), u),
       "shape.inside_corner": lambda r, s, b, u, v: shape.inside_corner(shape.profile(r, s, b), u, v),
       "shape.inside": shape.inside, "shape.distance": shape.distance}
finish(cases, ops)
'''
        done = self.family(script, label="shape", chunk=1500)
        count = lambda prefix: sum(1 for case in done["cases"] if case[0] == prefix)
        RECORD.append("shape: %d cases - corner, outline, flatten, %d profiles in an order that makes the kept tables answer a nearby "
                      "radius and clear when full, edge_at, inside_corner, %d inside and %d distance - identical to the tag's" % (
                          len(done["cases"]), count("shape.profile"), count("shape.inside"), count("shape.distance")))


class DaysDiff(Leaves):
    def test_the_days(self):
        script = COMMON + r'''
import datetime
cases = []
day = datetime.date(2025, 1, 1)
while day.year <= 2101:
    cases.append(["days.day_look", day.year, day.month, day.day])
    day += datetime.timedelta(days=1)
looks = list(brand.DAY_LOOKS)
paths = ["M25.5 2l1 3.5 3.5 1-3.5 1-1 3.5-1-3.5-3.5-1 3.5-1z", "M142 48q4.7 7 9.5 0t9.5 0 9.5 0 9.5 0v-3q0-3-3-3h-32q-3 0-3 3z",
         "M60 66q24-14 48-5t44-5 44 4v8z", "M60 42q4-6 11-3 5-6 12-1 6-2 8 4z", "M138 26q-13 12-11 24 2 12 22 12t22-12q2-12-11-24z",
         "M149 39v12", "M143 45h12", "m10 10l5 5 5-5zm20 0h5v5H20z", "M1 1 2 2 3 3", "M.5.5L-.5-.5l.25.25", "M1 1Q2 2 3 3T5 5t1 1",
         "M1 1Z 3 3", "L1 1", "1 1", "M1", "M1 L2 2", "", "M1 1 h", "M1.5e3 2", "M 1 2 Z z M 3 4 V 9", "M0 0q1 1 2 2 3",
         "M0 0T4 4", "M1. 2.", "M-1-2-3-4", "x M1 2 y L3 4"]
for path in paths:
    for steps in (8, 1, 0, 3, -1):
        cases.append(["days.path_points", path, steps])
for look in looks + ["nothing"]:
    for name in ("days.scene_elements", "days.speck_elements", "days.mark_text", "days.scene_text", "days.speck_text", "days.speck_reach"):
        cases.append([name, look])
    for _ in range(120 if look != "nothing" else 1):
        cases.append(["days.mark_colour", look, rng.uniform(-1, 33), rng.uniform(-1, 33)])
    for ms in [0, 1, 999, 1000, -1500, 123456, 4.5e6, 1e9 + 0.5] + [rng.uniform(0, 60000) for _ in range(40)]:
        cases.append(["days.scene_frame", look, ms])
        cases.append(["days.speck_frame", look, ms, None])
        cases.append(["days.speck_frame", look, ms, [rng.uniform(-50, 300), rng.uniform(0, 400)]])
    if look == "nothing":
        continue
    for px, py in ((x + 0.5, y + 0.5) for x in range(0, 32, 2) for y in range(0, 16)):
        cases.append(["days.mark_colour", look, px, py])
    for mode, factor in (("round", 1), ("round", 1.25), ("round", 1.5), ("round", 2), ("float", 1.0), ("float", 1.75), ("float", 3)):
        for band, words_end in ([[0, 0, 400, 66], 120], [[10, 4, 300, 70], 200], [[0, 0, 220, 40], 100], [[0, 0, 160, 40], 40],
                                [[0, 0, 200, 40], 199], [[0, 10, 500, 10], 0], [[0.5, 0.25, 333.3, 44.4], 77.7], [[0, 0, 1000, 120], 2.5]):
            cases.append(["days.day_band", look, mode, factor, band, words_end])
elements = [["round", [100, 50, 46, 7, 3.5], "#3A3F86", 1.0, "drift", [8.0]], ["poly", [1, 2, 3, 4, 5, 6], "#fff", 1, "fall", [3.2, -1, 320.0]],
            ["circle", [10, 20, 3], "#fff", 0.9, "fall", [4, 0, 0.0]], ["stroke", [1.4, 1, 2, 3, 4], "#000", 1, "sway", [3.4, 149, 21]],
            ["ellipse", [161, 26, 2.6, 4.4], "#F6B73C", 1, "flame", [1.1, 30.4]], ["glow", [150, 72, 62, 0.45], "#FFC766", 1, "breathe", [4, 0.34, 0.3]],
            ["poly", [0, 0, 4, 0, 4, 4], "#abc", 1, "twinkle", [2.5, 0.5]], ["round", [0, 1, 2, 3, 4], "#abc", 1, "", []],
            ["stroke", [1.3, 149, 39, 149, 51], "#F2C230", 1.0, "drift", [7.0]], ["poly", [1, 2, 3], "#fff", 1, "fall", [3, 0, 0]],
            ["ring", [149, 45, 8.5, 1.5], "#F2C230", 1, "sway", [3.4, 149.0, 21.0]]]
for element in elements:
    for seconds in (0, 0.5, 1, 2.75, -3.3, 7.5, 100.25, 12345.678, 13, 14, 21):
        cases.append(["days.element_at", element, seconds])
for presses in ([0, 100, 200, 300, 400, 500, 600], [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300],
                [0, 1800, 3600, 5400, 7200, 9000, 10800, 12600], [0, 1801, 2000, 2100, 2200, 2300, 2400, 2500, 2600], [5, 5, 5, 5, 5, 5, 5, 5.5],
                [0, -1000, -2000, 10, 20, 30, 40, 50, 60, 70], list(range(0, 50000, 1700)), [rng.uniform(0, 30000) for _ in range(60)]):
    cases.append(["days.PressRun", sorted(presses) if len(presses) == 60 else presses])
for ms in [-100, 0, 1, 734, 735, 736, 749, 750, 900, 999, 1000, 1049, 1050, 1650, 1899, 1900, 1901, 2000, 5000, 367.5, 1e9] + [rng.uniform(-200, 2500) for _ in range(300)]:
    cases.append(["days.sweep_at", ms])
def as_elements(found):
    return [list(each) for each in found]
ops = {"days.day_look": days.day_look, "days.path_points": days.path_points, "days.mark_colour": days.mark_colour,
       "days.scene_elements": days.scene_elements, "days.speck_elements": days.speck_elements, "days.mark_text": days.mark_text,
       "days.scene_text": days.scene_text, "days.speck_text": days.speck_text, "days.speck_reach": days.speck_reach,
       "days.scene_frame": days.scene_frame, "days.speck_frame": lambda look, ms, within: days.speck_frame(look, ms, None if within is None else tuple(within)),
       "days.element_at": days.element_at,
       "days.day_band": lambda look, mode, factor, band, end: days.day_band(
           look, (lambda v: int(round(v * factor))) if mode == "round" else (lambda v: v * factor), tuple(band), end),
       "days.PressRun": lambda presses: (lambda run: [run.press(each) for each in presses])(days.PressRun()),
       "days.sweep_at": lambda ms: days.sweep_at(ms, brand.ease)}
finish(cases, ops)
'''
        done = self.family(script, label="days", chunk=3000)
        count = lambda prefix: sum(1 for case in done["cases"] if case[0] == prefix)
        RECORD.append("days: %d cases - day_look for %d dates (2025-2101, LUNAR_DAYS among them), path_points (the scenes' paths and "
                      "malformed ones), mark_colour, the five scenes, specks and marks as elements and text, %d scene/speck frames, "
                      "element_at, %d day_band, PressRun, sweep_at - identical to the tag's" % (
                          len(done["cases"]), count("days.day_look"), count("days.scene_frame") + count("days.speck_frame"),
                          count("days.day_band")))


class TrayDiff(Leaves):
    def test_the_icon_motion(self):
        script = COMMON + r'''
cases = [["tray.ICON_SWEEP"]]
states = list(motion.ICON_STATES) + ["monitoring", "unknown", "", None, 5]
for state in states:
    cases.append(["tray.icon_brand_state", state])
    cases.append(["tray.icon_head_colour", state])
for colour in ([79, 224, 245], [0, 0, 0], [255, 255, 255], [201, 7, 99], [-10, 300, 5]):
    for level in (-3, 0, 1, 11.5, 12, 22, 23, 24, 100, 7.9):
        cases.append(["tray.icon_level_colour", colour, level])
elapsed = [0, 1, -1, 4400, 13200, 13201, 17600, 21999, 22000, 2200, 3960, 1980, 39600, 123456789, 1e12 + 0.25] + [rng.uniform(0, 100000) for _ in range(250)]
for ms in elapsed:
    for cycle in (4400, 5600, 1200):
        cases.append(["tray._breath_level", ms, cycle])
    for state in states:
        cases.append(["tray.icon_turn", state, ms])
        for reduced in (False, True):
            for fine in (1, 4):
                cases.append(["tray.icon_frame", state, ms, reduced, fine])
                cases.append(["tray.icon_frame_ms", state, ms, reduced, fine])
cases.append(["tray.icon_frame", "watching", 100, False, 0])
for flags in ([False] * 5 + [True], [True] + [False] * 4 + [True], [False] * 6, [0, 0, 0, 1, 0, 1], [None, "", 0, False, [], "x"]):
    cases.append(["tray.icon_motion_allowed"] + flags)
compose = [[position, colour] for position in (0, 1, 5, 12, 23, 24, 47, -1, 95) for colour in ([79, 224, 245], [0, 0, 0], [255, 255, 255], [201, 7, 99])]
for size, fine, look, heads in [(16, 1, None, True), (20, 1, None, True), (24, 1, None, True), (32, 1, None, False), (32, 4, None, False),
                                (48, 1, None, False), (64, 1, None, False), (64, 4, None, False), (24, 1, "birthday", True),
                                (32, 1, "new_year", False), (32, 4, "christmas", False), (40, 1, "seollal", False), (48, 1, "chuseok", False),
                                (64, 1, "birthday", False), (16, 1, "chuseok", True), (0, 1, None, False), (16, 0, None, False),
                                (32, 1, "nothing", False), (32, 1, "", False)]:
    cases.append(["tray.IconFrames", size, fine, look, compose, heads])
def icon_frames(size, fine, look, compose, heads):
    frames = motion.IconFrames(size, fine, look)
    return {"ground": sha(frames.ground), "boxes": [list(box) for box, _ in frames.heads],
            "heads": [rows for _, rows in frames.heads] if heads else None,
            "composed": [sha(frames.compose(position, tuple(colour))) for position, colour in compose]}
ops = {"tray.ICON_SWEEP": lambda: motion.ICON_SWEEP, "tray.icon_brand_state": motion.icon_brand_state,
       "tray.icon_head_colour": motion.icon_head_colour, "tray.icon_level_colour": lambda colour, level: motion.icon_level_colour(tuple(colour), level),
       "tray._breath_level": motion._breath_level, "tray.icon_turn": motion.icon_turn,
       "tray.icon_frame": lambda state, ms, reduced, fine: motion.icon_frame(state, ms, None, reduced=reduced, fine=fine),
       "tray.icon_frame_ms": lambda state, ms, reduced, fine: motion.icon_frame_ms(state, ms, None, reduced=reduced, fine=fine),
       "tray.icon_motion_allowed": lambda *flags: motion.icon_motion_allowed(reduced=flags[0], contrast=flags[1], battery_saver=flags[2],
                                                                           locked=flags[3], hidden=flags[4], frames=flags[5]),
       "tray.IconFrames": icon_frames}
finish(cases, ops)
'''
        done = self.family(script, label="tray", chunk=2000)
        count = lambda prefix: sum(1 for case in done["cases"] if case[0] == prefix)
        RECORD.append("tray motion (the parts gui/Brand.cs is made from): %d cases - head colours, levels, %d turns, %d frames and "
                      "frame times, and IconFrames at %d sizes, fines and looks with 36 composed frames each - identical to the tag's" % (
                          len(done["cases"]), count("tray.icon_turn"), count("tray.icon_frame") + count("tray.icon_frame_ms"),
                          count("tray.IconFrames")))
