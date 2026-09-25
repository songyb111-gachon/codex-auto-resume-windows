"""The capability registry, the standards a capability departs from, and its statement.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.domain.plug import Point  # noqa: E402
from codex_auto_resume_advanced import registry, standards, statement  # noqa: E402
from codex_auto_resume_advanced.registry import (CAPABILITY_POINTS, Ceilings, Registry,  # noqa: E402
                                                 RegistryError, problems)
from codex_auto_resume_advanced.vocabulary import Field  # noqa: E402

# Where the owner keeps the standards file: beside the repository, not in it.
STANDARDS_FILE = ac.ROOT.parent / standards.BASIS


class ShippedTests(unittest.TestCase):
    def test_the_registry_this_edition_ships_is_empty(self):
        self.assertEqual(registry.DEFINITIONS, ())
        self.assertEqual(len(registry.REGISTRY), 0)
        self.assertEqual(registry.REGISTRY.ids, ())
        for point in Point:
            self.assertEqual(registry.REGISTRY.at(point), ())

    def test_the_global_ceiling_is_twelve_an_hour_and_core_caps_are_cores(self):
        from codex_auto_resume.engine import Engine
        self.assertEqual(registry.GLOBAL_HOURLY, 12)
        options = Engine(None, None, None).options
        self.assertEqual((registry.CORE_DAILY_CAP, registry.CORE_COOLDOWN_SECONDS),
                         (options["max_submissions_per_thread_per_day"],
                          options["thread_cooldown_seconds"]))


class DefinitionTests(unittest.TestCase):
    def test_the_tests_capability_keeps_every_rule(self):
        self.assertEqual(problems(ac.definition()), [])
        made = Registry((ac.definition(),))
        self.assertEqual(made.ids, ("test_wake",))
        self.assertEqual([d.id for d in made.at(Point.TEXT)], ["test_wake"])
        self.assertEqual(made.at(Point.RECORDS), ())
        self.assertIsNone(made.get("elsewhere"))
        self.assertIsNone(made.get(["test_wake"]))

    def test_a_capability_that_departs_from_nothing_belongs_in_the_standard_edition(self):
        """The membership rule, mechanical: an empty departs_from is refused."""
        found = problems(ac.definition(departs_from=()))
        self.assertTrue(any("keeps every standard" in problem for problem in found))
        with self.assertRaises(RegistryError):
            Registry((ac.definition(departs_from=()),))

    def test_every_standard_it_departs_from_is_one_the_standards_file_holds(self):
        for departs in (("A99",), ("K1",), ("A6", "A6"), ("a6",), (6,), ["A6"]):
            with self.subTest(departs=departs):
                self.assertNotEqual(problems(ac.definition(departs_from=departs)), [])
        self.assertEqual(problems(ac.definition(departs_from=("0.5", "A11", "B4", "J14"))), [])

    def test_each_field_is_checked(self):
        cases = {
            "id": dict(id="Wake"),
            "points": dict(points=frozenset()),
            "points the plug keeps for itself": dict(points=frozenset({Point.CLAIM_LEDGER})),
            "revision": dict(revision=0),
            "compat": dict(compat="Not Loaded"),
            "ceilings": dict(ceilings=Ceilings(per_day=2, per_conversation=3)),
            "journal_prefix": dict(journal_prefix="t.w"),
            "codes": dict(codes=("woke", "woke")),
            "make": dict(make=None),
        }
        for rule, change in cases.items():
            with self.subTest(rule):
                self.assertIn(rule, problems(ac.definition(**change)))
        self.assertIn("revision", problems(ac.definition(revision=True)))
        self.assertIn("ceilings", problems(ac.definition(ceilings=Ceilings(per_day=300, per_conversation=1))))
        self.assertIn("ceilings", problems(ac.definition(ceilings=Ceilings(per_day=6, per_conversation=6))))
        self.assertEqual(problems("not a definition"), ["not a definition"])

    def test_a_capability_never_holds_the_claim_ledger_or_a_surface(self):
        self.assertEqual(CAPABILITY_POINTS, frozenset(Point) - {Point.CLAIM_LEDGER, Point.SURFACES})

    def test_two_capabilities_never_share_an_id_or_a_prefix(self):
        with self.assertRaises(RegistryError):
            Registry((ac.definition(), ac.definition(journal_prefix="xx")))
        with self.assertRaises(RegistryError):
            Registry((ac.definition(), ac.definition(id="test_sleep")))
        self.assertEqual(len(Registry((ac.definition(), ac.definition(id="test_sleep", journal_prefix="ts")))), 2)

    def test_its_own_codes_are_written_after_its_prefix(self):
        made = ac.definition()
        self.assertEqual(made.code("woke"), "tw.woke")
        self.assertIsNone(made.code("dreamt"))


class StandardsTests(unittest.TestCase):
    def test_the_ids_are_the_families_numbered_without_gaps(self):
        self.assertEqual(len(standards.STANDARDS), 165)
        self.assertEqual(len(set(standards.STANDARDS)), 165)
        self.assertEqual(standards.STANDARDS[:2], ("0.1", "0.2"))
        self.assertEqual(standards.STANDARDS[-1], "J14")

    def test_they_are_exactly_the_ids_the_standards_file_numbers(self):
        """Read from the owner's file where it is at hand; it is not part of the repository."""
        if not STANDARDS_FILE.is_file():
            self.skipTest("the standards file is not beside this repository")
        text = STANDARDS_FILE.read_text(encoding="utf-8").split("# promised_not_enforced")[0]
        found = re.findall(r"(?m)^(0\.\d+|[A-J]\d+) ", text)
        self.assertEqual(tuple(found), standards.STANDARDS)


class StatementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.where = Path(temporary.name)

    def test_the_tests_capability_has_all_five_fields_in_all_nine_languages(self):
        catalogs = ac.catalogs(self.where, ac.definition())
        self.assertEqual(catalogs.missing(ac.definition()), [])
        self.assertEqual(len(l10n.LOCALES), 9)
        self.assertEqual([str(field) for field in statement.FIELDS],
                         ["does", "instead", "departs", "risks", "stop"])

    def test_a_field_missing_or_empty_in_any_language_is_found(self):
        catalogs = ac.catalogs(self.where, ac.definition(), leave_out={("ja", "risks")})
        path = self.where / "locales" / "de.json"
        table = json.loads(path.read_text(encoding="utf-8"))
        table[statement.key("test_wake", Field.STOP)] = "   "
        path.write_text(json.dumps(table), encoding="utf-8")
        self.assertEqual(sorted(catalogs.missing(ac.definition())), [("de", "stop"), ("ja", "risks")])
        self.assertTrue(catalogs.complete_in(ac.definition(), "en"))
        self.assertFalse(catalogs.complete_in(ac.definition(), "ja"))

    def test_the_statement_a_person_reads_names_its_revision_and_its_departures(self):
        catalogs = ac.catalogs(self.where, ac.definition())
        shown = catalogs.statement(ac.definition(revision=4), "ko")
        self.assertEqual((shown["revision"], shown["departs_from"], shown["locale"]), (4, ["A11"], "ko"))
        self.assertEqual([item["field"] for item in shown["fields"]], [str(f) for f in statement.FIELDS])
        self.assertEqual(shown["fields"][0]["text"], "test_wake does (ko)")
        self.assertEqual(shown["fields"][0]["title"], "하는 일")
        self.assertEqual(catalogs.statement(ac.definition(), "xx")["locale"], "en")

    def test_a_language_whose_catalog_breaks_is_english_underneath(self):
        catalogs = ac.catalogs(self.where, ac.definition())
        (self.where / "locales" / "fr.json").write_text("{", encoding="utf-8")
        self.assertEqual(catalogs.text(statement.title_key(Field.DOES), "fr"), "What it does")


class ShippedCatalogTests(unittest.TestCase):
    """The words this edition ships now: held to core's catalog rules by core's reader."""

    def tables(self) -> dict:
        return {locale: l10n.read_catalog(statement.DIRECTORY / ("%s.json" % locale))
                for locale in l10n.LOCALES}

    def test_every_language_has_exactly_the_english_keys_and_none_is_empty(self):
        tables = self.tables()
        english = set(tables["en"])
        self.assertEqual(english, {statement.SENTINEL_KEY, statement.ALL_OFF_KEY}
                         | {statement.title_key(field) for field in statement.FIELDS}
                         | {"state.off", "state.shadow", "state.armed"})
        for locale, table in tables.items():
            with self.subTest(locale):
                self.assertEqual(set(table), english)
                self.assertTrue(all(value.strip() for value in table.values()))
                self.assertEqual(table[statement.SENTINEL_KEY], tables["en"][statement.SENTINEL_KEY])
                if locale != "en":
                    self.assertNotEqual(table[statement.ALL_OFF_KEY], tables["en"][statement.ALL_OFF_KEY])

    def test_the_sentinel_is_the_first_key_so_the_audit_finds_it_at_the_top(self):
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                lines = (statement.DIRECTORY / ("%s.json" % locale)).read_text(encoding="utf-8").splitlines()
                self.assertIn("ADVANCED-EDITION-CODE", lines[1])

    def test_a_duplicated_key_is_refused_as_core_refuses_one(self):
        with tempfile.TemporaryDirectory() as where:
            path = Path(where) / "en.json"
            path.write_text('{"all_off": "a", "all_off": "b"}', encoding="utf-8")
            with self.assertRaises(l10n.CatalogError):
                statement.Catalogs(where).own("en")


if __name__ == "__main__":
    unittest.main()
