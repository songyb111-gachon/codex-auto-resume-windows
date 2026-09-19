"""The localization architecture: catalogs, normalization, fallback, preference.

`test_locale.py` holds the older, surface-level promises (every surface speaks the
language that was resolved). This file holds the mechanism under them, including the
translation bookkeeping in `build/l10n.py` - a translation that is missing, stale or has
lost a placeholder fails here, not in front of a reader.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import l10n

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("l10n_tool", ROOT / "build" / "l10n.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShippedCatalogTests(unittest.TestCase):
    def test_every_supported_language_ships_a_catalog(self):
        self.assertEqual(l10n.available(), l10n.LOCALES)

    def test_every_catalog_is_well_formed(self):
        for locale in l10n.available():
            with self.subTest(locale):
                table = l10n._read(locale)
                self.assertTrue(table)
                for key, value in table.items():
                    self.assertTrue(value.strip(), "%s is empty" % key)

    def test_every_translation_is_complete_and_current(self):
        """Missing, stale (English changed since it was translated), extra, or with a
        placeholder lost or invented: each is a string a reader would see wrong."""
        tool = _tool()
        for locale in tool.translations():
            with self.subTest(locale):
                found = tool.report(locale)
                for kind in ("missing", "stale", "extra", "placeholders", "empty"):
                    self.assertEqual(found[kind], [], "%s %s" % (locale, kind))

    def test_names_stay_names(self):
        """Names a reader has to recognise, and commands they have to type, are never
        translated. (Whether a sentence names Codex at all is the translator's call.)"""
        english = l10n._read(l10n.DEFAULT)
        for locale in l10n.available():
            table = l10n._read(locale)
            for key, source in english.items():
                for name in ("GitHub", "Python", "MCP", "`doctor`"):
                    if name in source and key in table:
                        with self.subTest(locale=locale, key=key, name=name):
                            self.assertIn(name, table[key])

    def test_the_endonyms_cover_exactly_the_shipped_languages(self):
        self.assertEqual(set(l10n.ENDONYMS), set(l10n.LOCALES))

    def test_every_catalog_has_exactly_the_english_keys(self):
        """Parity stated directly, beside the bookkeeping above: a key one catalog lacks
        is an English word in that language, and a key only one has is dead weight."""
        english = set(l10n._read(l10n.DEFAULT))
        for locale in l10n.available():
            with self.subTest(locale):
                self.assertEqual(set(l10n._read(locale)), english)

    def test_every_theme_choice_and_the_reopen_note_have_words_in_every_language(self):
        """The theme picker is drawn from the settings schema, so a choice without a label
        would show its raw value in the middle of a translated card."""
        from codex_auto_resume import settings
        wanted = ["field.theme", "help.theme", "note.reopen_pending"]
        wanted += ["choice.theme." + choice for choice in settings.THEMES]
        english = l10n._read(l10n.DEFAULT)
        for locale in l10n.available():
            table = l10n._read(locale)
            labels = [table.get("choice.theme." + choice) for choice in settings.THEMES]
            with self.subTest(locale):
                for key in wanted:
                    self.assertIn(key, table)
                # Three different words: "Light" and "Dark" must never read the same.
                self.assertEqual(len(set(labels)), len(labels), labels)
                if locale != l10n.DEFAULT:
                    self.assertNotEqual(table["choice.theme.system"], english["choice.theme.system"])
                    self.assertNotEqual(table["note.reopen_pending"], english["note.reopen_pending"])
        # The help sentence names the choice the way the picker spells it.
        for locale in l10n.available():
            table = l10n._read(locale)
            with self.subTest(locale=locale, key="help.theme"):
                self.assertIn(table["choice.theme.system"], table["help.theme"])


class NotificationCardWordsTests(unittest.TestCase):
    def test_the_card_setting_has_its_label_and_help_in_every_language(self):
        english = l10n._read(l10n.DEFAULT)
        for key in ("field.notification_card", "help.notification_card"):
            self.assertTrue(english[key].strip())
            for locale in l10n.available():
                table = l10n._read(locale)
                with self.subTest(locale=locale, key=key):
                    self.assertTrue(table[key].strip())
                    if locale != l10n.DEFAULT:
                        self.assertNotEqual(table[key], english[key], "translated, not copied")
        # The help names the product's own neighbour, the notification area, in each language's own
        # words - the words the icon's label already uses.
        for locale in l10n.available():
            table = l10n._read(locale)
            with self.subTest(locale=locale):
                self.assertIn("Windows", table["help.notification_card"])


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.saved_cache = dict(l10n._CACHE)
        l10n._CACHE.clear()
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        l10n._CACHE.clear()
        l10n._CACHE.update(self.saved_cache)
        self.temporary.cleanup()

    def write(self, locale, text):
        (self.directory / ("%s.json" % locale)).write_text(text, encoding="utf-8")

    def test_a_duplicated_key_is_refused_rather_than_last_one_wins(self):
        self.write("en", '{"a": "one", "a": "two"}')
        with patch.object(l10n, "DIRECTORY", self.directory):
            with self.assertRaises(l10n.CatalogError):
                l10n._read("en")

    def test_a_broken_translation_falls_back_to_english_instead_of_failing(self):
        self.write("en", json.dumps({"hello": "Hello", "bye": "Bye"}))
        for broken in ('{"hello": ', '["not", "an", "object"]', '{"hello": 3}',
                       '{"hello": "안녕", "hello": "또"}'):
            with self.subTest(broken=broken):
                l10n._CACHE.clear()
                self.write("ko", broken)
                with patch.object(l10n, "DIRECTORY", self.directory):
                    self.assertEqual(l10n.catalog("ko"), {"hello": "Hello", "bye": "Bye"})

    def test_a_missing_key_is_english_and_a_present_one_is_translated(self):
        self.write("en", json.dumps({"hello": "Hello", "bye": "Bye"}))
        self.write("ja", json.dumps({"hello": "こんにちは"}))
        with patch.object(l10n, "DIRECTORY", self.directory):
            self.assertEqual(l10n.catalog("ja"), {"hello": "こんにちは", "bye": "Bye"})

    def test_an_unknown_locale_is_english(self):
        self.write("en", json.dumps({"hello": "Hello"}))
        with patch.object(l10n, "DIRECTORY", self.directory):
            self.assertEqual(l10n.catalog("sv"), {"hello": "Hello"})

    def test_formatting_never_raises_on_a_stray_brace(self):
        self.write("en", json.dumps({"odd": "Use {braces} and { this }", "n": "{n} left"}))
        with patch.object(l10n, "DIRECTORY", self.directory):
            self.assertEqual(l10n.text("odd"), "Use {braces} and { this }")
            self.assertEqual(l10n.text("n", n=3), "3 left")
            with self.assertRaises(KeyError):
                l10n.text("absent")


class NormalizationTests(unittest.TestCase):
    CASES = {
        "en": "en", "en-US": "en", "en_GB": "en", "ko": "ko", "ko-KR": "ko", "ko_KR": "ko",
        "ja-JP": "ja", "zh": "zh-CN", "zh-CN": "zh-CN", "zh-Hans": "zh-CN", "zh-Hans-CN": "zh-CN",
        "zh-SG": "zh-CN", "zh-TW": "zh-TW", "zh-Hant": "zh-TW", "zh-Hant-TW": "zh-TW",
        "zh-HK": "zh-TW", "zh-MO": "zh-TW", "es": "es", "es-419": "es", "es-MX": "es",
        "de-AT": "de", "fr-CA": "fr", "pt": "pt-BR", "pt-BR": "pt-BR", "pt-PT": "pt-BR",
    }

    def test_real_tags_reach_their_catalog(self):
        for tag, expected in self.CASES.items():
            with self.subTest(tag):
                self.assertEqual(l10n.normalize(tag), expected)

    def test_a_language_this_product_does_not_have_is_none_not_english(self):
        for tag in ("ru", "sv-SE", "it", "", "   ", None, 7, "-"):
            with self.subTest(tag=tag):
                self.assertIsNone(l10n.normalize(tag))

    def test_only_the_first_windows_preference_counts(self):
        with patch.object(l10n, "preferred_languages", return_value=["ru-RU", "ko-KR"]):
            self.assertEqual(l10n.from_system(), "en")
        with patch.object(l10n, "preferred_languages", return_value=["ko-KR", "en-US"]):
            self.assertEqual(l10n.from_system(), "ko")


class PreferenceTests(unittest.TestCase):
    def tearDown(self):
        l10n.set_preference(l10n.SYSTEM)

    def test_an_explicit_choice_beats_windows(self):
        with patch.object(l10n, "preferred_languages", return_value=["ko-KR"]):
            self.assertEqual(l10n.resolve("ja"), "ja")
            self.assertEqual(l10n.resolve("system"), "ko")
            self.assertEqual(l10n.resolve(None), "ko")
            self.assertEqual(l10n.resolve(""), "ko")

    def test_an_explicit_choice_this_build_lacks_is_english_not_windows(self):
        with patch.object(l10n, "preferred_languages", return_value=["ko-KR"]):
            self.assertEqual(l10n.resolve("sv"), "en")

    def test_the_process_preference_is_adopted_and_an_invalid_one_is_system(self):
        with patch.object(l10n, "preferred_languages", return_value=["de-DE"]):
            self.assertEqual(l10n.set_preference("fr"), "fr")
            self.assertEqual((l10n.preference(), l10n.current()), ("fr", "fr"))
            self.assertEqual(l10n.set_preference("klingon"), "de")
            self.assertEqual(l10n.preference(), l10n.SYSTEM)
            self.assertEqual(l10n.set_preference(None), "de")

    def test_every_choice_is_a_valid_setting(self):
        from codex_auto_resume import settings
        for choice in l10n.CHOICES:
            with self.subTest(choice):
                self.assertEqual(settings.validate_update({"interface_language": choice})
                                 ["interface_language"], choice)
        with self.assertRaises(settings.SettingsError):
            settings.validate_update({"interface_language": "klingon"})


class NoNetworkTests(unittest.TestCase):
    def test_localization_reaches_no_network(self):
        # "Reaches" as the imports do: the three localization modules and every module of this
        # product they import, lazily or not - so a split, or a helper they start to use, is
        # read too (a root that no longer exists is a KeyError, not a pass). The build tool is
        # outside the package and is named.
        reached = srcscan.closure("codex_auto_resume.l10n", "codex_auto_resume.continuation",
                                  "codex_auto_resume.reasons")
        files = ["src/" + srcscan.relative(srcscan.modules()[module]) for module in sorted(reached)]
        for relative in files + ["build/l10n.py"]:
            source = (ROOT / relative).read_text(encoding="utf-8")
            for word in ("urllib", "http.client", "socket", "requests", "https://"):
                with self.subTest(file=relative, word=word):
                    self.assertNotIn(word, source)


class ToolTests(unittest.TestCase):
    """The incremental-translation bookkeeping, on a scratch copy."""

    def setUp(self):
        self.tool = _tool()
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.catalogs = base / "locales"
        self.basis = base / "basis"
        self.catalogs.mkdir()
        (self.catalogs / "en.json").write_text(json.dumps({"a": "Apple", "b": "{n} bananas"}),
                                               encoding="utf-8")
        self.patches = [patch.object(self.tool, "CATALOGS", self.catalogs),
                        patch.object(self.tool, "BASIS", self.basis)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temporary.cleanup()

    def import_work(self, work):
        path = Path(self.temporary.name) / "work.json"
        path.write_text(json.dumps(work, ensure_ascii=False), encoding="utf-8")
        with patch("sys.stdout"), patch("sys.stderr"):
            return self.tool.cmd_import(["ja", str(path)])

    def test_import_records_the_basis_and_a_changed_english_is_stale(self):
        self.assertEqual(self.import_work({"a": "りんご", "b": "バナナ{n}本"}), 0)
        self.assertEqual(self.tool.report("ja")["stale"], [])
        (self.catalogs / "en.json").write_text(json.dumps({"a": "Red apple", "b": "{n} bananas"}),
                                               encoding="utf-8")
        found = self.tool.report("ja")
        self.assertEqual(found["stale"], ["a"])
        self.assertEqual(found["missing"], [])

    def test_a_lost_placeholder_refuses_the_whole_file(self):
        self.assertEqual(self.import_work({"a": "りんご", "b": "バナナ"}), 1)
        self.assertEqual(self.tool.read_catalog("ja"), {})

    def test_an_unknown_key_refuses_the_whole_file(self):
        self.assertEqual(self.import_work({"a": "りんご", "zzz": "?"}), 1)
        self.assertEqual(self.tool.read_catalog("ja"), {})

    def test_what_export_writes_is_what_import_reads_once_filled_in(self):
        import io
        stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with patch("sys.stdout", stream):
            self.assertEqual(self.tool.cmd_export(["ja"]), 0)
            stream.flush()
            work = json.loads(stream.buffer.getvalue().decode("utf-8"))
        self.assertEqual(sorted(work), ["a", "b"])
        self.assertEqual(self.import_work(work), 1)             # nothing written yet
        work["a"]["text"] = "りんご"
        work["b"]["text"] = "バナナ{n}本"
        self.assertEqual(self.import_work(work), 0)
        self.assertEqual(self.tool.read_catalog("ja"), {"a": "りんご", "b": "バナナ{n}本"})
        self.assertEqual(self.tool.report("ja")["stale"], [])


if __name__ == "__main__":
    unittest.main()
