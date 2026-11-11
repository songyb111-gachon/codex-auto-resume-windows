"""The standalone panel carries Persian fonts locally, including before a language change."""
from __future__ import annotations

import base64
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume.mcp import panel


class PersianPanelFontTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fonts = self.root / "assets" / "fonts" / "vazirmatn"
        self.fonts.mkdir(parents=True)
        self.regular = b"test regular font\x00\xff"
        self.bold = b"test bold font\x00\xfe"
        (self.fonts / "Vazirmatn-Regular.ttf").write_bytes(self.regular)
        (self.fonts / "Vazirmatn-Bold.ttf").write_bytes(self.bold)
        self.project = patch.object(panel.config, "PROJECT_ROOT", self.root)
        self.project.start()
        self.addCleanup(self.project.stop)

    def test_both_faces_are_embedded_as_their_exact_bytes_without_external_urls(self):
        style = panel.persian_font_style()
        fonts = re.findall(r'data:font/ttf;base64,([A-Za-z0-9+/=]+)', style)
        self.assertEqual([base64.b64decode(value) for value in fonts], [self.regular, self.bold])
        self.assertIn("font-weight: 400", style)
        self.assertIn("font-weight: 700", style)
        self.assertNotIn("http", style)
        self.assertNotIn("file:", style)

    def test_only_persian_selects_the_family_with_segoe_fallback(self):
        style = panel.persian_font_style()
        self.assertIn(':root:lang(fa) { --font: "Vazirmatn", "Segoe UI", sans-serif; }', style)
        self.assertNotIn(":lang(en)", style)
        self.assertNotIn(":lang(ar)", style)

    def test_missing_fonts_leave_the_normal_stack_available(self):
        for path in self.fonts.iterdir():
            path.unlink()
        self.assertEqual(panel.persian_font_style(), "")

    def test_missing_bold_still_embeds_regular(self):
        (self.fonts / "Vazirmatn-Bold.ttf").unlink()
        style = panel.persian_font_style()
        self.assertEqual(style.count("@font-face"), 1)
        self.assertIn("font-weight: 400", style)

    def test_empty_font_is_ignored(self):
        (self.fonts / "Vazirmatn-Regular.ttf").write_bytes(b"")
        self.assertNotIn("font-weight: 400", panel.persian_font_style())

    def test_english_page_carries_faces_for_an_instant_switch_to_persian(self):
        with patch.object(panel.interface, "language", return_value="en"), \
             patch.object(panel, "typeface_style", return_value=""):
            page = panel.settings_page(text=1, face="Segoe UI")
        self.assertIn(panel.persian_font_style(), page)
        self.assertIn('window.__CODEX_AUTO_RESUME_LOCALE__="en"', page)

    def test_special_day_data_and_persian_faces_ship_together(self):
        look = next(iter(panel.brand.DAY_LOOKS))
        with patch.object(panel.interface, "language", return_value="en"), \
             patch.object(panel, "typeface_style", return_value=""):
            page = panel.settings_page(text=1, face="Segoe UI", day=look)
        self.assertIn(panel.persian_font_style(), page)
        self.assertIn("window.__CODEX_AUTO_RESUME_DAY__=", page)
        self.assertIn(panel._script_json(panel.day_data(look)), page)


if __name__ == "__main__":
    unittest.main()
