# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""See an example (v0.6.20; the owner's decision of 2026-10-29): every capability's before and after, drawn by the window
itself from sample data (advanced/gui/AdvancedExamples.cs) - its table of samples held to the registry and its words to the
catalogs, without compiling anything.

Every capability the registry defines, and every one registry.WAITING holds back until its measurement passes, has exactly
one example with a Before and an After; a capability added without one fails here. The samples name only the tests'
fixtures, and every word a pane says is one the window is handed (core's catalog, advanced-words).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_examples.py
"""
from __future__ import annotations

from pathlib import Path
import json
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from advancedcase import ROOT  # noqa: E402
import guiscan  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402

SOURCE = ROOT / "advanced" / "gui" / "AdvancedExamples.cs"
FIXTURES = {"ExampleProject": "example-project", "ExampleService": "example-service", "ExampleApp": "example-app",
            "ExampleDocs": "example-docs"}
KEYS = ("page.example.button", "page.example.title", "page.example.before", "page.example.after", "page.example.note")


def text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def member(name: str) -> str:
    """One method of the file, by its braces (guiscan's own block finder)."""
    source = text()
    found = re.search(r"(?m)^[ \t]*(?:private|internal)[^\n(]*\b%s\(" % re.escape(name), source)
    if found is None:
        raise AssertionError("AdvancedExamples.cs has no %s" % name)
    return guiscan._block(source, found.start())


def table() -> str:
    return member("Examples")


def examples() -> dict:
    """{id: the text of its Ex(...)}, in the table's order (a repeated id kept twice, under id#2)."""
    body = table()
    starts = [match for match in re.finditer(r'\bEx\("([a-z_]+)"', body)]
    found = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(body)
        key = match.group(1)
        while key in found:
            key += "#2"
        found[key] = body[match.start():end]
    return found


def capabilities() -> list:
    return [definition.id for definition in registry.DEFINITIONS] + [definition.id for definition, _m in registry.WAITING]


class TableTests(unittest.TestCase):
    def test_every_capability_has_exactly_one_example(self):
        """Fails with an example taken out of the table, or a capability added to the registry without one."""
        table_ids = list(examples())
        self.assertEqual([each for each in table_ids if "#" in each], [], "no capability twice")
        missing = [each for each in capabilities() if each not in table_ids]
        self.assertEqual(missing, [], "every capability has an example")
        self.assertEqual([each for each in table_ids if each not in capabilities()], [], "no example of nothing")

    def test_each_example_has_a_before_and_an_after_with_something_in_each(self):
        for capability, made in examples().items():
            with self.subTest(capability):
                scenes = [match.start() for match in re.finditer(r"\bScene\(", made)]
                self.assertEqual(len(scenes), 2, "a Before and an After")
                for index, start in enumerate(scenes):
                    scene = made[start:scenes[index + 1] if index + 1 < len(scenes) else len(made)]
                    self.assertRegex(scene, r"\b(OnHistory|OnPending|InReport|Sent|Says)\(", "each scene has a part")

    def test_the_samples_name_only_the_fixtures_and_nothing_real(self):
        source = text()
        for constant, value in FIXTURES.items():
            self.assertIn('%s = "%s"' % (constant, value), source)
        named = re.findall(r"\b(?:Rec|ResetRule|Queued)\((\w+)", table())
        self.assertTrue(named)
        self.assertEqual(sorted(set(named) - set(FIXTURES) - {"null"}), [], "a conversation is one of the fixtures")
        literals = re.findall(r'"((?:[^"\\]|\\.)*)"', source)
        for literal in literals:
            self.assertNotRegex(literal, r"(?i)[a-z]:\\|\\users\\|/users/", "no path")
            for found in re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}", literal):
                self.assertTrue(found.startswith("0a1b2c3d"), "a thread id of the fixtures' shape: %s" % literal)
        conversations = [literal for literal in literals if literal.startswith("example-")]
        self.assertEqual(sorted(set(conversations) - set(FIXTURES.values()) - {"example-"}), [])

    def test_every_row_says_a_state_and_a_kind_core_has_words_for(self):
        core = l10n.catalog("en")
        rows = re.findall(r'\bRec\(\w+, "(\w+)", "(\w+)"', table())
        self.assertTrue(rows)
        for code, category in rows:
            self.assertIn("code." + code, core, "the state is said in core's words")
            self.assertTrue("reason." + category in core or "field.recover_" + category in core, category)

    def test_every_word_a_pane_says_is_one_the_window_is_handed(self):
        """Each Word(...) of the file is in advanced-words, and each S(...) in core's catalog: a key spelled wrong would
        show its English fallback in every language."""
        source = text()
        words = statement.CATALOGS.words("en")
        core = l10n.catalog("en")
        page = set(re.findall(r'\bWord\("([\w.]+)"', source))
        self.assertTrue(page)
        self.assertEqual(sorted(page - set(words)), [])
        said = set(re.findall(r'\bS\("([\w.]+)"', source))
        self.assertTrue(said)
        self.assertEqual(sorted(said - set(core)), [])


class WordTests(unittest.TestCase):
    def test_the_view_s_words_are_in_every_language_with_their_placeholders(self):
        english = statement.CATALOGS.own("en")
        for key in KEYS:
            self.assertIn(key, statement.PAGE_KEYS)
        self.assertIn("{name}", english["page.example.title"])
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                own = statement.CATALOGS.own(locale)
                for key in KEYS:
                    self.assertTrue(isinstance(own.get(key), str) and own[key].strip(), key)
                    self.assertEqual(l10n.placeholders(own[key]), l10n.placeholders(english[key]), key)
                if locale != "en":
                    for key in ("page.example.button", "page.example.before", "page.example.after", "page.example.note"):
                        self.assertNotEqual(own[key], english[key], key)
                    self.assertTrue(own["page.example.button"].endswith("..."), "it opens a dialog, as Find... does")

    def test_advanced_words_hands_over_the_continuations_a_pane_shows(self):
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                words = statement.CATALOGS.words(locale)
                for key in ("continue.keep_going", "continue.empty_response", "continue.wrap_up.standard",
                            "continue.subagent.line", "continue.subagent.kind.temporary"):
                    self.assertIn(key, words)
        self.assertEqual(json.dumps(sorted(statement.CONTINUATION_KEYS)),
                         json.dumps(sorted(key for key in statement.CATALOGS.words("en") if key.startswith("continue."))))


if __name__ == "__main__":
    unittest.main()
