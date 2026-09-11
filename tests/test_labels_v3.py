"""Every status a person can be shown has words, in every language the product speaks.

The interfaces show the public code (machine.public_code) and the overlays, never the
engine's stored state. A code without a label would fall back to its identifier, which
is exactly the kind of internal vocabulary the public codes exist to keep out of sight.
"""
from __future__ import annotations

import unittest

from codex_auto_resume import interface, machine


class LabelTests(unittest.TestCase):
    def test_every_public_code_and_overlay_has_a_label_in_every_language(self):
        for language, strings in interface.STRINGS.items():
            for code in machine.PUBLIC_CODES:
                with self.subTest(language=language, code=code):
                    self.assertTrue(strings.get("code." + code), code)
            for overlay in machine.OVERLAYS:
                with self.subTest(language=language, overlay=overlay):
                    self.assertTrue(strings.get("overlay." + overlay), overlay)

    def test_every_stored_state_maps_to_a_public_code(self):
        for state in machine.STATES:
            with self.subTest(state=state):
                self.assertIn(machine.public_code({"state": state}), machine.PUBLIC_CODES)

    def test_a_failed_record_is_never_described_as_retrying(self):
        # Whether attempts "remain" is a setting; a stored failure is final either way.
        self.assertEqual(machine.public_code({"state": "failed"}), "failed_terminal")
        self.assertEqual(machine.public_code({"state": "terminal_failure"}), "failed_terminal")


if __name__ == "__main__":
    unittest.main()
