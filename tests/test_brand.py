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
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "assets"))

from codex_auto_resume import brand, mcpui          # noqa: E402
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

    def test_fill_only_tokens_are_documented_as_fill_only(self):
        # `active` does not reach text contrast and is not supposed to. The assertion
        # exists so that if someone raises it to text contrast they also have to come
        # here and say so, rather than quietly using it for text.
        self.assertLess(brand.contrast(brand.LIGHT["active"], brand.LIGHT["surface"]), 4.5)
        self.assertIn("fill-only", brand.__doc__.lower().replace("fill only", "fill-only"))


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
        # Rendering it here is the only way "generated" stays true.
        images = [(size, make_icon.png(size, make_icon.render(size))) for size in make_icon.SIZES]
        current = (ROOT / "assets" / "codex-auto-resume.ico").read_bytes()
        self.assertEqual(current, make_icon.ico(images),
                         "assets/codex-auto-resume.ico is stale; run python assets/make_icon.py")

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
        source = (ROOT / "gui" / "SettingsApp.cs").read_text(encoding="utf-8")
        stray = [line.strip() for line in source.splitlines()
                 if "Color.FromArgb" in line]
        self.assertEqual(stray, [], "colours belong in brand.py, not in the window")


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
