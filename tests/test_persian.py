"""Persian language selection, message construction and bidirectional values."""
from __future__ import annotations

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


if __name__ == '__main__':
    unittest.main()
