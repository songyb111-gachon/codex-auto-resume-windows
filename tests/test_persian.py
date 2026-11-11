"""Persian language selection, message construction and bidirectional values."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from codex_auto_resume import continuation, l10n, settings


class PersianTests(unittest.TestCase):
    def test_system_and_explicit_selection_reach_persian(self):
        for tag in ('fa', 'fa-IR', 'fa_AF', 'FA-ir'):
            with self.subTest(tag=tag):
                self.assertEqual(l10n.normalize(tag), 'fa')
                with patch.object(l10n, 'preferred_languages', return_value=[tag]):
                    self.assertEqual(l10n.resolve('system'), 'fa')
        with patch.object(l10n, 'preferred_languages', return_value=['en-US']):
            self.assertEqual(l10n.resolve('fa'), 'fa')
        settings.validate_update({'interface_language': 'fa', 'continuation_language': 'fa'})
        self.assertEqual(l10n.offered_endonyms()['fa'], 'فارسی')

    def test_follow_interface_constructs_a_persian_continuation(self):
        values = dict(settings.defaults(), interface_language='fa', continuation_language='follow')
        message = continuation.for_settings('network_transient', values)
        self.assertEqual(message, l10n.text('continuation.standard.network_transient', 'fa'))
        self.assertIn('شبکه', message)
        self.assertNotEqual(message, continuation.build('network_transient', locale='en'))
        self.assertNotRegex(message, r'\{[a-z_]+\}')

    def test_persian_reads_right_to_left_and_latin_values_keep_their_order(self):
        self.assertTrue(l10n.right_to_left('fa'))
        self.assertEqual(l10n.first_strong('۱۲۳ فارسی'), 'R')
        path = r'C:\Projects\music'
        embedded = l10n.embedded(path, 'fa')
        self.assertIn(path, embedded)
        self.assertEqual(l10n.first_strong(path), 'L')


class DigitTests(unittest.TestCase):
    """Every catalog writes its numbers in the digits 0-9, as the values the product fills in are written (the owner,
    2026-11-11: Persian as Arabic, "일반 숫자"): a choice in Persian digits beside a count the panel prints in Latin
    ones reads as two number systems on one screen (test_gui_own_values)."""

    NATIVE = re.compile("[٠-٩۰-۹٪-٬๐-๙]")

    def test_no_catalog_of_either_edition_writes_another_script_s_digits(self):
        root = Path(__file__).resolve().parents[1]
        folders = [root / "src" / "codex_auto_resume" / "locales"]
        folders += sorted((root / "advanced" / "src").glob("*/locales"))
        for folder in folders:
            for catalog in sorted(folder.glob("*.json")):
                words = json.loads(catalog.read_text(encoding="utf-8"))
                with self.subTest(catalog=str(catalog.relative_to(root))):
                    self.assertEqual([key for key, text in words.items()
                                      if isinstance(text, str) and self.NATIVE.search(text)], [])


if __name__ == '__main__':
    unittest.main()
