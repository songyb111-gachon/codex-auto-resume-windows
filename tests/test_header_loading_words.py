"""The window's header says it is loading in the window's language (v0.6.20 final, A5).

Until the first status arrives the header's headline holds a placeholder. It was the literal "Loading...", so after a
reopen - a language changed and saved, an update - the header said it in English for a moment, in every language. It is
the catalog's `status.loading` now, translated in all eighteen catalogs.
"""
from __future__ import annotations

import unittest

import guiscan

from codex_auto_resume import l10n


class LoadingWordsTests(unittest.TestCase):
    def test_the_headline_starts_with_the_catalogs_words(self):
        body = guiscan.member_body("SettingsForm", "BuildHeader")
        self.assertIn('headline.Text = S("status.loading", "Loading...");', body)
        self.assertNotIn('headline.Text = "', body, "a headline in English whatever the language")

    def test_every_catalog_says_it_in_its_own_language(self):
        english = l10n.catalog("en")["status.loading"]
        self.assertEqual(english, "Loading...", "the window's fallback is the English sentence")
        for locale in l10n.LOCALES:
            if locale == "en":
                continue
            with self.subTest(locale=locale):
                words = l10n.catalog(locale).get("status.loading")
                self.assertTrue(words)
                self.assertNotEqual(words, english)


if __name__ == "__main__":
    unittest.main()
