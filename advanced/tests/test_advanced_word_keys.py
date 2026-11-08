# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Every word the advanced window asks for is one it is handed (the v0.6.22 reachability audit, M15 and M17).

The window's `Word("key", "English")` reads the key from advanced-words and falls back to the English written beside it,
so a key spelled wrong shows English in every language without any error: M15 found AdvancedChat.cs saying
`refused.not_on` where the catalog has `page.refused.not_on`, and "Turn it on first." never reached a Korean window.
The examples' own file was already held to this (test_advanced_examples); this holds every window source of the
advanced edition, and the core catalog for the S("key", ...) calls the same sources make.

M17: the editor's header comment said "up to four" pictures after the limits became ten of up to 20 MB each.

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_word_keys.py
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from advancedcase import ROOT  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume_advanced import images, statement  # noqa: E402

SOURCES = sorted((ROOT / "advanced" / "gui").glob("*.cs"))
# A literal key followed by `+` is a prefix the code finishes (Word("name." + id, ...)).
WORD = re.compile(r'\bWord\(\s*"([^"]+)"(\s*\+)?')
SAID = re.compile(r'\bS\(\s*"([^"]+)"(\s*\+)?')


def keys(pattern, source):
    return [(match.group(1), source.count("\n", 0, match.start()) + 1) for match in pattern.finditer(source)
            if not match.group(2)]


class WordKeyTests(unittest.TestCase):
    def test_there_are_sources_to_read(self):
        self.assertGreater(len(SOURCES), 10)

    def test_every_word_key_of_every_advanced_window_source_is_in_the_catalog(self):
        """Fails with a key missing its `page.` prefix (the M15 mistake) or spelled wrong, in any source."""
        words = statement.CATALOGS.words("en")
        missing = []
        for path in SOURCES:
            for key, line in keys(WORD, path.read_text(encoding="utf-8")):
                if key not in words:
                    missing.append("%s:%d %s" % (path.name, line, key))
        self.assertEqual(missing, [])

    def test_every_core_word_key_of_every_advanced_window_source_is_in_core(self):
        core = l10n.catalog("en")
        missing = []
        for path in SOURCES:
            for key, line in keys(SAID, path.read_text(encoding="utf-8")):
                if key not in core:
                    missing.append("%s:%d %s" % (path.name, line, key))
        self.assertEqual(missing, [])

    def test_the_chat_says_turn_it_on_first_by_its_page_key_in_every_language(self):
        source = (ROOT / "advanced" / "gui" / "AdvancedChat.cs").read_text(encoding="utf-8")
        self.assertIn('Word("page.refused.not_on", "Turn it on first.")', source)
        self.assertNotRegex(source, r'Word\("refused\.')
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertTrue(statement.CATALOGS.words(locale).get("page.refused.not_on", "").strip())


class EditorCommentTests(unittest.TestCase):
    def test_the_editors_comment_gives_the_limits_the_images_module_holds(self):
        self.assertEqual((images.MOST_IMAGES, images.MOST_BYTES), (10, 20 * 1024 * 1024))
        source = (ROOT / "advanced" / "gui" / "AdvancedEditor.cs").read_text(encoding="utf-8")
        header = source[:source.index("using System")]
        self.assertNotRegex(header, r"(?i)up to four|four pictures")
        self.assertIn("up to ten, each of up to\n// 20 MB (images.MOST_IMAGES, MOST_BYTES)", header)


if __name__ == "__main__":
    unittest.main()
