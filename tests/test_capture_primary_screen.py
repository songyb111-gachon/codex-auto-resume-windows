"""A window opened for a picture opens on the primary screen, whatever monitor the pointer is on (2026-10-28).

A second monitor at 100% beside the 150% primary, with the pointer on it, made the capture windows open there and draw at
96 DPI: pictures 1006 px wide where the manifest records 1500, and the pass failed. The window opens where the pointer is
(SettingsForm.OpeningPlace) - right for a person - so while build/capture_window.ps1 takes a picture (Soft.StillReady set)
the point it opens at is the middle of the primary screen instead, both for the screen it opens on and for the scale it
adopts before it is built.
"""
from __future__ import annotations

import unittest

import guiscan


class CaptureOpensOnThePrimaryScreenTests(unittest.TestCase):
    def test_a_picture_opens_at_the_middle_of_the_primary_screen_and_a_person_at_the_pointer(self):
        pointer = guiscan.member_body("SettingsForm", "OpeningPointer")
        self.assertIn("if (Soft.StillReady == null) return Cursor.Position;", pointer)
        self.assertIn("Screen.PrimaryScreen.WorkingArea", pointer)

    def test_the_screen_and_the_scale_both_ask_it(self):
        self.assertIn("OpeningPlace(request, OpeningPointer())", guiscan.member_body("SettingsForm", "OpeningScreen"))
        main = guiscan.member_body("Program", "Main")
        self.assertIn("SettingsForm.OpeningPlace(request, SettingsForm.OpeningPointer())", main)
        self.assertNotIn("Cursor.Position", main)


    def test_the_setup_window_opens_on_the_primary_screen_for_a_picture(self):
        """CenterScreen is the monitor under the pointer: the setup window's Welcome still was captured there (fidelity 84.9%)."""
        window = guiscan.type_body("InstallerWindow")
        self.assertIn("StartPosition = Soft.StillReady == null ? FormStartPosition.CenterScreen : FormStartPosition.Manual;", window)
        self.assertIn("Rectangle primary = Screen.PrimaryScreen.WorkingArea;", window)


if __name__ == "__main__":
    unittest.main()
