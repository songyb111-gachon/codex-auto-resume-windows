"""v0.6.11: the edition beside the version, in both editions.

The owner's rule: wherever the version is shown, the edition is named beside it - the Dashboard's save
bar ("v0.6.11 · Standard"), Diagnostics' Version row, the panel's heading in Codex - and the
notification-area icon's tooltip names it after the product. Positions and every other word stay.

One code says which (edition.shown): `standard` or `advanced`, the edition that runs, or
`advanced_not_loaded` for an advanced installation whose package could not be taken - it runs as the
standard edition, and says so. The status carries it for the window and the panel, the watcher hands
it to its icon, and each surface says it in the catalog's word for the reader's language
(`edition.<code>`, in all 18 catalogs).
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import control, edition, interface, l10n  # noqa: E402
from codex_auto_resume.domain.plug import NULL, DamagedPlug, Edition, Plug, PlugFailure, guard  # noqa: E402
from codex_auto_resume.mcp import panel  # noqa: E402
from codex_auto_resume.ui import tray  # noqa: E402
from test_control import ControlTestCase  # noqa: E402

import guiscan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CODES = ("standard", "advanced", edition.NOT_LOADED)


class AdvancedPlug(Plug):
    """An advanced edition's plug that answers nothing: only its edition is asked here."""
    __slots__ = ()
    edition = Edition.ADVANCED
    badge = "Advanced"


class ShownTests(unittest.TestCase):
    def test_the_code_is_the_edition_that_runs(self):
        self.assertEqual(edition.shown(NULL), "standard")
        self.assertEqual(edition.shown(guard(NULL)), "standard")
        self.assertEqual(edition.shown(AdvancedPlug()), "advanced")
        self.assertEqual(edition.shown(guard(AdvancedPlug())), "advanced")
        for failure in PlugFailure:
            with self.subTest(failure):
                self.assertEqual(edition.shown(DamagedPlug(failure)), "advanced_not_loaded")
                self.assertEqual(edition.shown(guard(DamagedPlug(failure))), "advanced_not_loaded")
        self.assertEqual(edition.NOT_LOADED, "advanced_not_loaded")
        self.assertEqual(set(CODES), {str(item) for item in Edition} | {edition.NOT_LOADED})

    def test_every_catalog_says_each_in_a_word_of_its_own(self):
        for locale in l10n.LOCALES:
            table = l10n._read(locale)
            with self.subTest(locale):
                words = [table["edition." + code] for code in CODES]
                self.assertTrue(all(word.strip() for word in words))
                self.assertEqual(len(set(words)), len(words), words)
                self.assertFalse(any(l10n.placeholders(word) for word in words))
                # Not loaded is the advanced edition's word, and says more.
                self.assertTrue(words[2].startswith(words[1]), words)
        english = l10n._read(l10n.DEFAULT)
        self.assertEqual([english["edition." + code] for code in CODES],
                         ["Standard", "Advanced", "Advanced - not loaded"])


class StatusTests(ControlTestCase):
    def test_the_status_names_the_edition_after_the_version(self):
        status = self.control.get_status()
        self.assertEqual(status["edition"], "standard")
        self.assertEqual(list(status)[:2], ["version", "edition"])

    def test_an_advanced_plug_is_named_and_one_not_loaded_says_so(self):
        advanced = control.Control(self.paths, plug=AdvancedPlug())
        self.assertEqual(advanced.get_status()["edition"], "advanced")
        damaged = control.Control(self.paths, plug=DamagedPlug(PlugFailure.IMPORT_FAILED))
        self.assertEqual(damaged.get_status()["edition"], "advanced_not_loaded")


class TooltipTests(unittest.TestCase):
    def test_the_title_names_the_edition_in_the_readers_word(self):
        english, korean = interface.STRINGS["en"], interface.STRINGS["ko"]
        paused = {"enabled": False}
        self.assertEqual(tray.tooltip(paused, english, 0, "standard"), "Codex Auto Resume · Standard\nPaused")
        self.assertEqual(tray.tooltip(paused, english, 0, "advanced"), "Codex Auto Resume · Advanced\nPaused")
        self.assertEqual(tray.tooltip(paused, korean, 0, "advanced"),
                         "Codex Auto Resume · 고급판\n" + korean["tray.paused"])
        self.assertEqual(tray.tooltip({}, english, 0, "standard"), "Codex Auto Resume · Standard")
        # With no edition handed to it, the tooltip is what it was.
        self.assertEqual(tray.tooltip(paused, english, 0), "Codex Auto Resume\nPaused")

    def test_every_language_keeps_its_whole_tooltip_with_the_longest_edition(self):
        for language, strings in interface.STRINGS.items():
            for code in CODES:
                with self.subTest(language=language, edition=code):
                    busy = {"enabled": True, "waiting": 99, "running": 99, "next_at": 10 ** 6}
                    text = tray.tooltip(busy, strings, 0, code)
                    self.assertLess(len(text), tray.TIP_CHARS)
                    # Nothing cut: the status line is the one the tooltip without the edition ends in.
                    self.assertTrue(text.endswith(tray.tooltip(busy, strings, 0).split("\n", 1)[1]))

    def test_the_watcher_hands_its_icon_the_edition_that_runs(self):
        app = (ROOT / "src" / "codex_auto_resume" / "runtime" / "app.py").read_text(encoding="utf-8")
        self.assertIn("edition=edition.shown(self.plug)", app)
        icon = (ROOT / "src" / "codex_auto_resume" / "ui" / "tray" / "icon.py").read_text(encoding="utf-8")
        self.assertEqual(icon.count("tooltip("), icon.count("time.time(), self.edition)"))


class PanelTests(unittest.TestCase):
    def test_the_heading_names_the_edition_beside_the_version(self):
        script = (ROOT / "src" / "codex_auto_resume" / "mcp" / "assets" / "panel.js").read_text(encoding="utf-8")
        heading = script[script.index("function renderHero("):]
        heading = heading[:heading.index("var line = ")]
        self.assertIn("'Codex Auto Resume · v' + (status.version || '?')", heading)
        self.assertIn("' · ' + t('edition.' + status.edition, status.edition)", heading)
        _names, prefixes = panel.panel_keys()
        self.assertIn("edition.", prefixes)
        for locale, table in panel.panel_catalogs().items():
            with self.subTest(locale):
                for code in CODES:
                    self.assertIn("edition." + code, table)


class WindowTests(unittest.TestCase):
    def test_the_save_bar_and_diagnostics_show_the_version_line(self):
        window = guiscan.whole()
        method = window[window.index("private string VersionLine("):]
        method = method[:method.index("\n        }\n")]
        self.assertIn('"v" + Convert.ToString(Get(status, "version"), CultureInfo.InvariantCulture)', method)
        self.assertIn('S("edition." + edition, edition)', method)
        self.assertIn('" \\u00B7 "', method)
        self.assertEqual(re.findall(r"versionText\.Text = ([^;]+);", window), ["VersionLine(status)"])
        self.assertEqual(re.findall(r"diagVersion\.Text = ([^;]+);", window), ["VersionLine(status)"])

    def test_the_layout_audit_measures_the_longest_edition(self):
        from test_gui_layout import fullest_snapshot
        self.assertEqual(fullest_snapshot(0)["status"]["edition"], edition.NOT_LOADED)
        longest = {locale: max((l10n._read(locale)["edition." + code] for code in CODES), key=len)
                   for locale in l10n.LOCALES}
        for locale, word in longest.items():
            with self.subTest(locale):
                self.assertEqual(word, l10n._read(locale)["edition." + edition.NOT_LOADED])


if __name__ == "__main__":
    unittest.main()
