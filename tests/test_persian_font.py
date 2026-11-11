"""Bundled Persian fonts are private to the process; absent assets retain Windows fallback."""
import ctypes as C
import os
import unittest
from unittest.mock import Mock, patch

from codex_auto_resume.win import typeface
from codex_auto_resume.ui.popup import fonts


class PersianFontTests(unittest.TestCase):
    def test_registration_is_private_and_only_done_once_for_both_weights(self):
        add = Mock(return_value=1)
        with patch.object(typeface, "_PERSIAN_READY", None), \
                patch.object(typeface, "_dll", return_value=Mock(AddFontResourceExW=add)):
            self.assertTrue(typeface.ensure_persian_font())
            self.assertTrue(typeface.ensure_persian_font())
        self.assertEqual(add.call_count, 2)
        self.assertEqual([call.args[0].split("Vazirmatn-")[-1] for call in add.call_args_list],
                         ["Regular.ttf", "Bold.ttf"])
        for call in add.call_args_list:
            self.assertEqual(call.args[1:], (typeface.FR_PRIVATE, None))

    def test_absent_assets_do_not_register_any_font(self):
        with patch.object(typeface, "_PERSIAN_READY", None), \
                patch("pathlib.Path.is_file", return_value=False), patch.object(typeface, "_dll") as dll:
            self.assertFalse(typeface.ensure_persian_font())
            dll.assert_not_called()

    def test_persian_uses_regular_and_real_bold_with_existing_fallback(self):
        with patch.object(typeface, "ensure_persian_font", return_value=True):
            self.assertEqual(fonts.font_candidates("fa", 400, "Segoe UI")[0], ("Vazirmatn", 400))
            self.assertEqual(fonts.font_candidates("fa", 600, "Segoe UI")[0], ("Vazirmatn", 700))
            self.assertEqual(fonts.font_faces("en", "Segoe UI"), ("Segoe UI",))
        with patch.object(typeface, "ensure_persian_font", return_value=False):
            self.assertEqual(fonts.font_faces("fa", "Segoe UI"), ("Segoe UI",))

    @unittest.skipUnless(os.name == "nt", "Windows GDI")
    def test_gdi_realizes_both_persian_weights_and_has_persian_letters(self):
        self.assertTrue(typeface.ensure_persian_font())
        self.assertTrue(typeface.installed(typeface.PERSIAN_FACE))
        self.assertEqual(typeface.lacks(typeface.PERSIAN_FACE, "فارسیپچژگیک"), "")
        gdi = typeface._dll("gdi32")
        typeface._declare(gdi, typeface._dll("user32"))
        dc = gdi.CreateCompatibleDC(None)
        self.assertTrue(dc)
        try:
            for weight in (400, 700):
                font = gdi.CreateFontW(-18, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, "Vazirmatn")
                self.assertTrue(font)
                previous = gdi.SelectObject(dc, font)
                try:
                    face = C.create_unicode_buffer(64)
                    self.assertTrue(gdi.GetTextFaceW(dc, 64, face))
                    self.assertEqual(face.value, "Vazirmatn")
                finally:
                    gdi.SelectObject(dc, previous)
                    gdi.DeleteObject(font)
        finally:
            gdi.DeleteDC(dc)
