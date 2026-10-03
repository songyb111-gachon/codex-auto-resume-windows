"""The localization architecture: catalogs, normalization, fallback, preference.

`test_locale.py` holds the older, surface-level promises (every surface speaks the
language that was resolved). This file holds the mechanism under them, including the
translation bookkeeping in `build/l10n.py` - a translation that is missing, stale or has
lost a placeholder fails here, not in front of a reader.
"""
from __future__ import annotations

import importlib.util
import json
import re
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

    def test_eighteen_catalogs_sixteen_offered_and_two_held(self):
        """v0.6.11 ships eighteen complete catalogs and offers sixteen: Arabic and Hebrew are held
        until every surface mirrors right to left (l10n.HELD). Every rule in this file holds for all
        eighteen - a held catalog is complete, current and well formed - and none of them is ever
        offered: not in a picker, not as a setting, not as where Windows' language leads."""
        from codex_auto_resume import settings
        self.assertEqual(len(l10n.LOCALES), 18)
        self.assertEqual(l10n.HELD, frozenset({"ar", "he"}))
        self.assertEqual(l10n.OFFERED, tuple(locale for locale in l10n.LOCALES if locale not in l10n.HELD))
        self.assertEqual(len(l10n.OFFERED), 16)
        self.assertEqual(l10n.CHOICES, (l10n.SYSTEM,) + l10n.OFFERED)
        self.assertEqual(settings.CONTINUATION_LANGUAGES, (settings.FOLLOW_INTERFACE,) + l10n.OFFERED)
        # The window and the panel label their pickers from what they are given: the offered names only.
        self.assertEqual(list(l10n.offered_endonyms()), list(l10n.OFFERED))
        # The nine languages v0.6.10 spoke keep their places, first; the new ones follow them.
        self.assertEqual(l10n.LOCALES[:9], ("en", "ko", "ja", "zh-CN", "zh-TW", "es", "de", "fr", "pt-BR"))
        for held in l10n.HELD:
            with self.subTest(held):
                self.assertIn(held, l10n.available())
                self.assertIsNone(l10n.normalize(held))
                with patch.object(l10n, "preferred_languages", return_value=["ko-KR"]):
                    self.assertEqual(l10n.resolve(held), "en", "a held language stored is English, not Windows'")
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update({"interface_language": held})
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update({"continuation_language": held})
                # A settings file that holds one anyway - hand-edited, or from a later version - reads
                # as the defaults.
                read = settings.coerce({"interface_language": held, "continuation_language": held})
                self.assertEqual((read["interface_language"], read["continuation_language"]),
                                 (l10n.SYSTEM, settings.FOLLOW_INTERFACE))

    def test_each_language_is_named_in_itself_and_nothing_else(self):
        """The pickers show a language by its own name only - no English name beside it, no globe (the
        owner, v0.6.11) - so an endonym is the bare name: no brackets but Portuguese's country, and no
        English name of another language inside it."""
        english_names = ("English", "Korean", "Japanese", "Chinese", "Spanish", "German", "French",
                         "Portuguese", "Russian", "Italian", "Turkish", "Polish", "Ukrainian",
                         "Vietnamese", "Indonesian", "Arabic", "Hebrew")
        for locale, name in l10n.ENDONYMS.items():
            with self.subTest(locale):
                self.assertEqual(name, name.strip())
                for other in english_names:
                    if other != name:
                        self.assertNotRegex(name, r"\b%s\b" % other)
                if locale != "pt-BR":
                    self.assertNotIn("(", name)
        self.assertEqual(len(set(l10n.ENDONYMS.values())), len(l10n.ENDONYMS))

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


class DesignWordsTests(unittest.TestCase):
    """v0.6.10: the Design setting is drawn from the schema like the themes, so each choice needs a
    label of its own in every language - and a name that is not the Theme's, which German already
    calls Design."""

    def test_the_design_has_its_name_its_choices_and_its_help_in_every_language(self):
        from codex_auto_resume import settings
        english = l10n._read(l10n.DEFAULT)
        keys = ["field.design", "help.design"] + ["choice.design." + choice for choice in settings.DESIGNS]
        for locale in l10n.available():
            table = l10n._read(locale)
            labels = [table["choice.design." + choice] for choice in settings.DESIGNS]
            with self.subTest(locale):
                for key in keys:
                    self.assertTrue(table[key].strip(), key)
                    if locale != l10n.DEFAULT and key != "choice.design.classic":
                        self.assertNotEqual(table[key], english[key], "translated, not copied: " + key)
                # Different words for each, and a name for the setting that neither theme has.
                self.assertEqual(len(set(labels)), len(labels), labels)
                self.assertNotIn(table["field.design"], (table["field.theme"], table["field.panel_theme"]))
                # The help names each choice as the picker spells it - and says no more than what
                # each looks like: the owner found the longer one, which listed every surface and
                # what the Theme and Reduce motion do, too much for a picker of three looks.
                for label in labels:
                    self.assertIn(label, table["help.design"])
                # Classic says which release it is.
                self.assertIn("v0.6.2", table["choice.design.classic"])

    def test_reduce_motion_names_every_surface_it_stops_and_no_design_escapes_it(self):
        """Since v0.6.11 Reduce motion is the one way to stop motion, in every design: v0.6.10's "Soft, without motion"
        is gone from every catalog, and neither its help nor the Design's names it or sets a design apart."""
        from codex_auto_resume import settings
        for locale in l10n.available():
            table = l10n._read(locale)
            with self.subTest(locale):
                self.assertNotIn("choice.design.still", table)
                for choice in settings.DESIGNS:
                    self.assertNotIn(table["choice.design." + choice], table["help.reduce_motion"])
                self.assertIn("Codex", table["help.reduce_motion"])
                self.assertIn("Windows", table["help.reduce_motion"])
        english = l10n._read(l10n.DEFAULT)["help.reduce_motion"]
        for surface in ("Dashboard", "popup", "icon", "notification card", "taskbar button", "panel in Codex"):
            self.assertIn(surface, english)


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


class ChoiceNamingTests(unittest.TestCase):
    """v0.6.11: a sentence names a choice as the list it is chosen from shows it, and a switch is named for
    what it does when it is on - in every catalog, the two held ones included."""

    def test_every_help_that_names_off_names_the_lists_own_off(self):
        """The guards' drop-downs show choice.off; Russian's help called it «Нет», a choice no list has."""
        english = l10n._read(l10n.DEFAULT)
        naming = sorted(key for key, value in english.items()
                        if key.startswith("help.") and re.search(r"\b%s\b" % re.escape(english["choice.off"]), value))
        self.assertGreaterEqual(len(naming), 3, "the check has sentences to look at")
        for locale in l10n.LOCALES:
            table = l10n._read(locale)
            for key in naming:
                with self.subTest(locale=locale, key=key):
                    self.assertIn(table["choice.off"], table[key])

    def test_the_per_task_switch_never_reads_as_do_not_resume(self):
        """pending.col_resume names each task's switch in the popup, the panel and the Pending page. Turkish's
        bare verbal noun, Sürdürme, is also its negative imperative - msg.ready_b4 uses it so, for "Do not
        resume" - so a switch shown on read "Don't resume". With the adjective it is the feature's name, as
        msg.enabled calls it; no catalog's switch is the words it says "do not resume" with."""
        for locale in l10n.LOCALES:
            table = l10n._read(locale)
            with self.subTest(locale=locale):
                self.assertNotIn(table["pending.col_resume"].casefold(), table["msg.ready_b4"].casefold())
        turkish = l10n._read("tr")
        self.assertEqual(turkish["pending.col_resume"], "Otomatik sürdürme")
        self.assertTrue(turkish["msg.enabled"].startswith(turkish["pending.col_resume"]))


class OwnValueWordsTests(unittest.TestCase):
    """v0.6.11: the words Custom... says a range and the days of the week in, in every catalog."""

    def test_a_range_never_ends_in_two_full_stops(self):
        """German writes its durations with an abbreviation point - 7 Tg. - so a range that ended on {high} and its
        own full stop read "Von 5 Min. bis 7 Tg..", in the Dashboard's dialog and in the panel."""
        for locale in l10n.LOCALES:
            table = l10n._read(locale)
            for unit in ("time.seconds", "time.minutes", "time.hours", "time.days"):
                said = table[unit].replace("{n}", "5")
                with self.subTest(locale=locale, unit=unit):
                    self.assertNotIn("..", table["own.range"].replace("{low}", said).replace("{high}", said))

    def test_the_days_hint_asks_for_days_of_the_week_not_a_length_of_a_day(self):
        """Above the seven boxes 月 火 水 ... the hint asks for weekdays: 1 日以上 and 하루 이상 read as a span of one
        day or more."""
        self.assertIn("曜日", l10n._read("ja")["own.days"])
        self.assertIn("요일", l10n._read("ko")["own.days"])


class OneNameTests(unittest.TestCase):
    """The window has one name, the Dashboard (v0.6.10).

    It had four: the Dashboard, the Windows Dashboard, the Codex Auto Resume window and the Codex
    Auto Resume settings window; the icon's menu said Open Codex Auto Resume beside a popup and a
    card that said Open Dashboard. And help written from inside the window - "Used by this window"
    - was shown in the panel in Codex too, where it is not that window. Only the window's title
    bar and its Start Menu entry keep the product's name.
    """

    # Each language's one word for it. Spanish says Panel, capitalised as a name, beside "el panel de
    # Codex": the notification's Abrir Panel is pinned byte for byte to what v0.6.4 raised.
    DASHBOARD = {"en": "Dashboard", "ko": "대시보드", "ja": "ダッシュボード", "zh-CN": "仪表板",
                 "zh-TW": "儀表板", "es": "Panel", "de": "Dashboard", "fr": "Tableau de bord",
                 "pt-BR": "Dashboard",
                 # v0.6.11: Russian declines its loanword (Дашборде, Дашбордом), Turkish suffixes its
                 # name after an apostrophe, Polish and Ukrainian keep the English name as de does.
                 "ru": "Дашборд", "it": "Dashboard", "tr": "Gösterge Paneli", "pl": "Dashboard",
                 "uk": "Dashboard", "vi": "Bảng điều khiển", "id": "Dasbor", "ar": "لوحة المعلومات",
                 "he": "לוח המחוונים"}
    # Every sentence that names the window, on whichever surface shows it.
    NAMING = ("menu.open", "popup.open_dashboard", "msg.toast_button_open", "popup.more",
              "custom.dashboard_only", "help.interface_language", "help.theme", "help.reduce_motion",
              "msg.setup_unconfirmed", "panel.compat_acting_differs", "panel.compat_refresh",
              "panel.compat_reported", "panel.readonly")
    # The window's own words, where "this window" is the window reading them.
    WINDOW_ONLY = ("diag.update_reopen", "pick.reopen")
    THIS_WINDOW = {"en": "this window", "ko": "이 창"}

    def test_every_language_has_its_word(self):
        self.assertEqual(set(self.DASHBOARD), set(l10n.LOCALES))

    def test_every_sentence_that_names_the_window_calls_it_the_dashboard(self):
        for locale in l10n.available():
            table = l10n._read(locale)
            for key in self.NAMING:
                with self.subTest(locale=locale, key=key):
                    self.assertIn(self.DASHBOARD[locale], table[key])

    def test_the_menu_the_popup_and_the_notifications_open_it_in_the_same_words(self):
        for locale in l10n.available():
            table = l10n._read(locale)
            with self.subTest(locale):
                self.assertEqual(table["menu.open"], table["popup.open_dashboard"])
                self.assertEqual(table["msg.toast_button_open"], table["popup.open_dashboard"])

    def test_no_other_name_is_left_in_the_words_or_the_panel(self):
        english = l10n._read(l10n.DEFAULT)
        panel = (ROOT / "src" / "codex_auto_resume" / "mcp" / "assets" / "panel.js").read_text(encoding="utf-8")
        for name in ("settings window", "Codex Auto Resume window", "Windows Dashboard", "Open Codex Auto Resume"):
            with self.subTest(name):
                self.assertEqual([key for key, value in english.items() if name in value], [])
                self.assertNotIn(name, panel)

    def test_only_the_windows_own_words_say_this_window(self):
        """A sentence the panel, the popup or a notification shows names the surfaces it means;
        "this window" is right only where the window is the one saying it."""
        for locale, phrase in self.THIS_WINDOW.items():
            table = l10n._read(locale)
            with self.subTest(locale):
                self.assertEqual(sorted(key for key, value in table.items() if phrase in value),
                                 sorted(self.WINDOW_ONLY))
        import guiscan
        window = guiscan.whole()
        panel = (ROOT / "src" / "codex_auto_resume" / "mcp" / "assets" / "panel.js").read_text(encoding="utf-8")
        python = "\n".join(srcscan.read(path) for path in srcscan.package_files())
        for key in self.WINDOW_ONLY:
            with self.subTest(key):
                self.assertIn('"%s"' % key, window)
                self.assertNotIn(key, panel)
                self.assertNotIn(key, python)

    # A string literal as the window, the panel and the Python package write these sentences.
    LITERAL = r'"(?:[^"\\\r\n]|\\.)*"' + r"|'(?:[^'\\\r\n]|\\.)*'"

    def test_every_fallback_written_for_them_is_the_english_sentence(self):
        """A fallback is what a surface says when its catalog lacks the key, so it says what the
        English catalog says. The first pass at the one name renamed the window in the catalogs and
        the panel and left the window's own fallbacks for help.interface_language, help.theme and
        help.reduce_motion saying "this window"; the panel's for custom.dashboard_only was half the
        sentence. Every literal written after one of these keys - S("key", "...") in the window,
        t('key', '...') in the panel, strings.get("key", "...") in Python - is the English
        sentence, or empty where the surface says nothing; and every mention of the key in the
        window is such a call, so a fallback written some other way cannot slip past this."""
        import ast
        import re
        import guiscan
        english = l10n._read(l10n.DEFAULT)
        sources = {
            "window": guiscan.whole(),
            "panel": (ROOT / "src" / "codex_auto_resume" / "mcp" / "assets" / "panel.js").read_text(encoding="utf-8"),
            "python": "\n".join(srcscan.read(path) for path in srcscan.package_files()),
        }
        found = set()
        for key in self.NAMING + self.WINDOW_ONLY:
            call = re.compile(r"""(["'])%s\1\s*,\s*((?:(?:%s)\s*\+?\s*)+)\)""" % (re.escape(key), self.LITERAL))
            for surface, text in sources.items():
                calls = list(call.finditer(text))
                for match in calls:
                    said = "".join(ast.literal_eval(literal) for literal in re.findall(self.LITERAL, match.group(2)))
                    found.add((surface, key))
                    if said:
                        with self.subTest(surface=surface, key=key):
                            self.assertEqual(said, english[key])
                if surface == "window":
                    with self.subTest(surface=surface, key=key, every_mention=True):
                        self.assertEqual(len(calls), text.count('"%s"' % key))
        # The scan found the fallbacks it was written for, so it cannot pass by matching nothing.
        self.assertLessEqual({("window", "help.interface_language"), ("window", "help.theme"),
                              ("window", "help.reduce_motion"), ("window", "diag.update_reopen"),
                              ("panel", "help.interface_language"), ("panel", "custom.dashboard_only"),
                              ("panel", "panel.readonly"), ("panel", "panel.compat_refresh"),
                              ("python", "menu.open")}, found)


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

    def test_a_catalog_anywhere_is_read_and_filled_by_the_same_rules(self):
        """v0.6.11: the advanced edition keeps its words in a directory of its own, and they are
        read by the one reader and filled by the one formatter core's are."""
        path = self.directory / "anywhere.json"
        for broken in ('{"a": "one", "a": "two"}', '{"a": 3}', '["a"]', '{"a": '):
            with self.subTest(broken=broken):
                path.write_text(broken, encoding="utf-8")
                with self.assertRaises(l10n.CatalogError):
                    l10n.read_catalog(path)
        path.write_text(json.dumps({"on": "{n} on, {left} left"}), encoding="utf-8")
        self.assertEqual(l10n.fill(l10n.read_catalog(path)["on"], n=2, other=5), "2 on, {left} left")
        self.assertEqual(l10n._read(l10n.DEFAULT), l10n.read_catalog(l10n.DIRECTORY / "en.json"))


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
        # A held language (l10n.HELD) is one this release does not have either.
        for tag in ("sv-SE", "nb", "fi-FI", "ar", "he-IL", "iw", "", "   ", None, 7, "-"):
            with self.subTest(tag=tag):
                self.assertIsNone(l10n.normalize(tag))

    def test_only_the_first_windows_preference_counts(self):
        with patch.object(l10n, "preferred_languages", return_value=["sv-SE", "ko-KR"]):
            self.assertEqual(l10n.from_system(), "en")
        with patch.object(l10n, "preferred_languages", return_value=["ar-SA", "ko-KR"]):
            self.assertEqual(l10n.from_system(), "en")
        with patch.object(l10n, "preferred_languages", return_value=["ko-KR", "en-US"]):
            self.assertEqual(l10n.from_system(), "ko")


class WindowsLanguageTableTests(unittest.TestCase):
    """What each Windows display language is answered in (v0.6.11, the owner's rule), as a table.

    The same language in any region goes to that language's catalog - Portuguese from Portugal or
    Angola to Brazilian Portuguese; Chinese goes by its script, and by the region only where no
    script is named; a language not in the list is English, and so is a held one (l10n.HELD).
    Only the first Windows language counts (NormalizationTests)."""

    TABLE = {
        "en-US": "en", "en-GB": "en", "en-IN": "en", "en-AU": "en",
        "ko-KR": "ko", "ja-JP": "ja",
        "zh-CN": "zh-CN", "zh-SG": "zh-CN", "zh-Hans": "zh-CN", "zh-Hans-CN": "zh-CN",
        "zh-Hans-SG": "zh-CN", "zh-Hans-HK": "zh-CN", "zh": "zh-CN",
        "zh-TW": "zh-TW", "zh-HK": "zh-TW", "zh-MO": "zh-TW", "zh-Hant": "zh-TW",
        "zh-Hant-TW": "zh-TW", "zh-Hant-HK": "zh-TW", "zh-Hant-MO": "zh-TW",
        "es-ES": "es", "es-MX": "es", "es-419": "es", "es-US": "es", "es-AR": "es",
        "de-DE": "de", "de-AT": "de", "de-CH": "de", "de-LI": "de",
        "fr-FR": "fr", "fr-CA": "fr", "fr-BE": "fr", "fr-CH": "fr",
        "pt-BR": "pt-BR", "pt-PT": "pt-BR", "pt-AO": "pt-BR", "pt": "pt-BR",
        "ru-RU": "ru", "ru-UA": "ru", "ru-KZ": "ru", "ru-BY": "ru",
        "it-IT": "it", "it-CH": "it",
        "tr-TR": "tr", "tr-CY": "tr",
        "pl-PL": "pl",
        "uk-UA": "uk",
        "vi-VN": "vi",
        "id-ID": "id", "in-ID": "id",
        # Held in this release: English, as any language without a catalog is.
        "ar-SA": "en", "ar-EG": "en", "ar-AE": "en", "he-IL": "en", "iw-IL": "en",
        # Not in the list: English, however close a neighbour is.
        "sv-SE": "en", "nb-NO": "en", "nl-NL": "en", "fi-FI": "en", "da-DK": "en", "cs-CZ": "en",
        "el-GR": "en", "hu-HU": "en", "th-TH": "en", "hi-IN": "en", "fa-IR": "en", "ca-ES": "en",
        "gl-ES": "en", "be-BY": "en", "kk-KZ": "en", "ms-MY": "en", "sr-Latn-RS": "en",
        "sr-Cyrl-RS": "en", "yue-HK": "en",
    }

    def test_each_windows_language_reaches_its_catalog(self):
        for tag, expected in self.TABLE.items():
            for spelled in (tag, tag.replace("-", "_"), tag.lower()):
                with self.subTest(tag=spelled):
                    with patch.object(l10n, "preferred_languages", return_value=[spelled]):
                        self.assertEqual(l10n.from_system(), expected)
                        self.assertEqual(l10n.resolve(l10n.SYSTEM), expected)

    def test_the_table_reaches_every_offered_language_and_no_held_one(self):
        reached = set(self.TABLE.values())
        self.assertEqual(reached, set(l10n.OFFERED))
        self.assertFalse(reached & l10n.HELD)


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
