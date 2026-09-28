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
import languages  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.domain.plug import Point  # noqa: E402
from codex_auto_resume_advanced import registry, standards, statement  # noqa: E402
from codex_auto_resume_advanced.registry import (CAPABILITY_POINTS, Ceilings, Registry,  # noqa: E402
                                                 RegistryError, problems)
from codex_auto_resume_advanced.vocabulary import ArmingWarning, Field, Measurement  # noqa: E402

# The standards file, public in the repository: each rule a line `**A1** <sentence>`, under its
# family's heading `## A. <title>`, then the line that says how it is held and which tests hold it.
STANDARDS_FILE = ac.ROOT / standards.BASIS
RULE_LINE = re.compile(r"(?m)^\*\*(0\.\d+|[A-K]\d+)\*\* ")
FAMILY_HEADING = re.compile(r"(?m)^## (0|[A-K])\. ")
# The line under a rule: its strength in italics, then the tests that hold it, if any.
HELD_LINE = re.compile(r"^\*([^*\n]+)\*(?:: (.+))?$")
TEST_NAME = re.compile(r"`([^`]+\.py)`")
# B4: all the standard edition asks of the app server - initialize (with initialized),
# account/rateLimits/read and thread/queue/delete.
B4_METHODS = frozenset({"initialize", "initialized", "account/rateLimits/read", "thread/queue/delete"})
# The app-server methods this edition may call beyond those, each a read or a change of Codex's
# state; B3 lets Codex's state change only through `codex queue`, thread/queue/delete and the
# plugin command. A method in neither set is a decision this table has to make first.
READS = frozenset({"thread/loaded/list", "thread/queue/list", "thread/goal/get"})
CHANGES = frozenset({"thread/queue/add", "thread/goal/set"})


class ShippedTests(unittest.TestCase):
    def test_the_registry_this_edition_ships_is_its_three_capabilities_in_their_order(self):
        self.assertEqual([d.id for d in registry.DEFINITIONS],
                         ["start_with_codex", "goal_continuation", "marker_free_continuation"])
        self.assertEqual(len(registry.REGISTRY), 3)
        self.assertEqual(registry.REGISTRY.ids,
                         ("start_with_codex", "goal_continuation", "marker_free_continuation"))
        # Start-with-Codex answers at P9 alone - it starts the watcher, it does not send; the goal
        # continuation at P16, P3 and P5 - the route, the hold while a goal carries a conversation on,
        # and the channel where M2b passed; the marker-free continuation at P5 and P15, the channel
        # and the way it carries the words. At P5 the goal continuation comes first, so where both
        # are on and the goal applies its channel carries the send.
        answering = {Point.START_ROUTE: ("start_with_codex",),
                     Point.UNLOADED: ("goal_continuation",),
                     Point.GATES: ("goal_continuation",),
                     Point.SENDER: ("goal_continuation", "marker_free_continuation"),
                     Point.DELIVERY: ("marker_free_continuation",)}
        for point in Point:
            self.assertEqual(tuple(d.id for d in registry.REGISTRY.at(point)), answering.get(point, ()))

    def test_every_shipped_capability_keeps_every_rule_and_has_a_complete_statement(self):
        """The shipped definitions - not a test's own - each pass the registry's rules and have a
        statement in every language (owner rule: ar/he ship held, so the key is present too)."""
        for definition in registry.DEFINITIONS:
            with self.subTest(definition.id):
                self.assertEqual(problems(definition), [])
                self.assertEqual(statement.CATALOGS.missing(definition), [])
                self.assertTrue(set(definition.departs_from) <= set(standards.DEPARTABLE))

    def test_a_capability_whose_session_asks_the_app_server_more_departs_from_b4_and_b3(self):
        """What a capability's own session may call (codex/protocol.CAPABILITY_METHODS) is part of
        what it departs from: a method beyond B4's is B4, and one that changes Codex's state is B3
        as well. The marker-free continuation's thread/queue/add is both, as the goal
        continuation's is - its statement named A2 and A4 alone at revision 1."""
        from codex_auto_resume_advanced.codex import protocol
        for definition in registry.DEFINITIONS:
            with self.subTest(definition.id):
                beyond = protocol.methods_for_capability(definition.id) - B4_METHODS
                self.assertLessEqual(beyond, READS | CHANGES, "a method this table has not placed")
                self.assertEqual("B4" in definition.departs_from, bool(beyond))
                self.assertEqual("B3" in definition.departs_from, bool(beyond & CHANGES))

    def test_every_statement_names_every_standard_it_departs_from_in_every_language(self):
        for definition in registry.DEFINITIONS:
            for locale in l10n.LOCALES:
                with self.subTest(definition.id, locale=locale):
                    text = statement.CATALOGS.own(locale)[statement.key(definition.id, Field.DEPARTS)]
                    for standard in definition.departs_from:
                        self.assertRegex(text, r"(?<![\w.])%s(?![\w.])" % re.escape(standard))

    def test_the_marker_free_continuation_departs_and_rests_on_what_the_owner_asked(self):
        """A2 and A4 as the owner named them, and B3 and B4 for the thread/queue/add its session
        makes; revision 2, since revision 1's statement named the first two alone."""
        mfc = registry.REGISTRY.get("marker_free_continuation")
        self.assertEqual(mfc.departs_from, ("A2", "A4", "B3", "B4"))
        self.assertEqual(mfc.revision, 2)
        self.assertEqual(mfc.compat, "recovery_turn_tracking")
        self.assertEqual(mfc.measurements, (Measurement.M7,))
        self.assertEqual(mfc.points, frozenset({Point.SENDER, Point.DELIVERY}))
        self.assertEqual(mfc.ceilings.per_conversation, registry.CORE_DAILY_CAP)

    def test_the_goal_continuation_departs_and_rests_on_what_the_owner_asked(self):
        """0.5 (goal-state manipulation), A2 (one channel), A11 (nothing for a conversation the app
        does not hold), B3 (Codex's state changes only through the queue) and B4 (the app server's
        three methods); it stands on loaded_state_detection, which has local checks and decides its
        route - core's own goal_continuation entry has none and stays unsupported (G12) - and its
        route on M2."""
        goal = registry.REGISTRY.get("goal_continuation")
        self.assertEqual(goal.departs_from, ("0.5", "A2", "A11", "B3", "B4"))
        self.assertEqual(goal.compat, "loaded_state_detection")
        from codex_auto_resume.compat.model import CAPABILITIES
        self.assertTrue(CAPABILITIES[goal.compat][0], "a compatibility capability with local checks")
        self.assertEqual(CAPABILITIES["goal_continuation"], ((), "unsupported"),
                         "core's own entry is the standard edition's, untouched")
        self.assertEqual(goal.measurements, (Measurement.M2,))
        self.assertEqual(goal.points, frozenset({Point.UNLOADED, Point.GATES, Point.SENDER}))
        self.assertLessEqual(goal.ceilings.per_conversation, registry.CORE_DAILY_CAP)

    def test_start_with_codex_departs_and_rests_on_what_the_plan_says(self):
        swc = registry.REGISTRY.get("start_with_codex")
        self.assertEqual(swc.departs_from, ("C4", "F6"))
        self.assertEqual(swc.compat, "engine_present")
        self.assertEqual(swc.measurements, (Measurement.MW,))
        self.assertEqual(swc.points, frozenset({Point.START_ROUTE}))

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
        for departs in (("A99",), ("L1",), ("A6", "A6"), ("a6",), (6,), ["A6"]):
            with self.subTest(departs=departs):
                self.assertNotEqual(problems(ac.definition(departs_from=departs)), [])
        self.assertEqual(problems(ac.definition(departs_from=("0.5", "A11", "B4", "J14"))), [])

    def test_the_advanced_editions_own_rules_are_never_departed_from(self):
        """Family K binds every capability - arming only in the Dashboard, pause and consent
        first, the tripwires - so naming one is a mistake the registry refuses, like an id the
        file does not hold."""
        for standard in ("K1", "K5", "K7"):
            with self.subTest(standard):
                self.assertIn(standard, standards.STANDARDS)
                self.assertNotIn(standard, standards.DEPARTABLE)
                self.assertNotEqual(problems(ac.definition(departs_from=(standard,))), [])
                self.assertNotEqual(problems(ac.definition(departs_from=("A11", standard))), [])

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
            "measurements": dict(measurements=("m1",)),
        }
        for rule, change in cases.items():
            with self.subTest(rule):
                self.assertIn(rule, problems(ac.definition(**change)))
        self.assertIn("revision", problems(ac.definition(revision=True)))
        self.assertIn("ceilings", problems(ac.definition(ceilings=Ceilings(per_day=300, per_conversation=1))))
        self.assertIn("ceilings", problems(ac.definition(ceilings=Ceilings(per_day=6, per_conversation=6))))
        self.assertEqual(problems("not a definition"), ["not a definition"])
        self.assertIn("measurements", problems(ac.definition(measurements=[Measurement.M1])))
        self.assertIn("measurements", problems(ac.definition(measurements=(Measurement.M1,) * 2)))
        self.assertEqual(problems(ac.definition(measurements=(Measurement.M1, Measurement.MW))), [])

    def test_a_capability_never_holds_the_claim_ledger_or_a_surface(self):
        """Nor the moves core tells of, which the tripwires read (P14)."""
        self.assertEqual(CAPABILITY_POINTS,
                         frozenset(Point) - {Point.CLAIM_LEDGER, Point.SURFACES, Point.MOVED})

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
        self.assertEqual(len(standards.STANDARDS), 172)
        self.assertEqual(len(set(standards.STANDARDS)), 172)
        self.assertEqual(standards.STANDARDS[:2], ("0.1", "0.2"))
        self.assertEqual(standards.STANDARDS[-1], "K7")
        self.assertEqual(len(standards.DEPARTABLE), 165)
        self.assertEqual(standards.DEPARTABLE[-1], "J14")

    def test_they_are_exactly_the_ids_the_standards_file_numbers(self):
        """docs/STANDARDS.md, in the repository since the standards were published (v0.6.11)."""
        found = RULE_LINE.findall(STANDARDS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(tuple(found), standards.STANDARDS)

    def test_a_rule_added_or_removed_moves_the_count_of_its_family(self):
        """Each family's heading holds as many rules as FAMILIES counts for it, each of its own
        family: a rule written into the file without FAMILIES following - or FAMILIES changed
        without the file - names this family and both counts."""
        text = STANDARDS_FILE.read_text(encoding="utf-8")
        headings = list(FAMILY_HEADING.finditer(text))
        counted = {prefix.rstrip("."): count for prefix, count in standards.FAMILIES}
        self.assertEqual([heading.group(1) for heading in headings], list(counted))
        for index, heading in enumerate(headings):
            family = heading.group(1)
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            rules = RULE_LINE.findall(text, heading.end(), end)
            with self.subTest(family=family):
                self.assertEqual(len(rules), counted[family],
                                 "the file and standards.FAMILIES disagree on family %s" % family)
                prefix = family + "." if family == "0" else family
                self.assertTrue(all(rule.startswith(prefix) for rule in rules), rules)

    def test_every_rule_says_how_it_is_held_and_every_test_it_names_is_here(self):
        """A rule held by tests names them, and each is a file in this repository: a bare name in
        tests/ or advanced/tests/, a path from the root otherwise. A test renamed or deleted
        without the file following leaves a rule citing nothing."""
        lines = STANDARDS_FILE.read_text(encoding="utf-8").splitlines()
        places = (ac.ROOT / "tests", ac.ROOT / "advanced" / "tests")
        named = 0
        for index, line in enumerate(lines):
            rule = RULE_LINE.match(line)
            if rule is None:
                continue
            with self.subTest(rule.group(1)):
                held = HELD_LINE.match(lines[index + 1]) if index + 1 < len(lines) else None
                self.assertIsNotNone(held, "no line under it says how it is held")
                strength, tests = held.group(1), TEST_NAME.findall(held.group(2) or "")
                if strength.startswith("tested"):
                    self.assertTrue(tests, "held by tests, and names none")
                for name in tests:
                    named += 1
                    found = ((ac.ROOT / name).is_file() if "/" in name
                             else any((place / name).is_file() for place in places))
                    self.assertTrue(found, "%s is not in the repository" % name)
        self.assertGreater(named, len(standards.STANDARDS))

    def test_the_korean_twin_holds_the_same_rules_and_names_the_same_tests(self):
        """docs/STANDARDS.ko.md, rule by rule: the same ids in the same order, each naming the
        tests the English names. On dev, where the Korean sources are; main is English only."""
        if not languages.both_languages():
            self.skipTest(languages.ON_DEV)

        def rules(path):
            lines = path.read_text(encoding="utf-8").splitlines()
            return [(match.group(1), TEST_NAME.findall(lines[index + 1]))
                    for index, line in enumerate(lines) for match in [RULE_LINE.match(line)] if match]

        english = rules(STANDARDS_FILE)
        self.assertEqual(rules(STANDARDS_FILE.with_name("STANDARDS.ko.md")), english)
        self.assertEqual(len(english), len(standards.STANDARDS))


class StatementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.where = Path(temporary.name)

    def test_the_tests_capability_has_all_five_fields_in_every_language(self):
        # Every catalog core has, the held ones too (v0.6.11: eighteen, l10n.HELD not yet offered).
        catalogs = ac.catalogs(self.where, ac.definition())
        self.assertEqual(catalogs.missing(ac.definition()), [])
        self.assertEqual(len(l10n.LOCALES), 18)
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

    def test_the_statement_shows_the_warnings_it_is_given_above_its_fields_in_their_words(self):
        """The warnings' words ship in every language, title and note too: a warning is read,
        and confirmed, in the person's own language."""
        catalogs = ac.catalogs(self.where, ac.definition())
        shown = catalogs.statement(ac.definition(), "ko", warnings=(ArmingWarning.FAILED_HERE,
                                                                    ArmingWarning.UNMEASURED))
        self.assertEqual([item["warning"] for item in shown["warnings"]["items"]],
                         ["failed_here", "unmeasured"])
        self.assertEqual(shown["warnings"]["title"], "경고")
        self.assertIn("켤 수 있습니다", shown["warnings"]["note"])
        self.assertIn("컴퓨터", shown["warnings"]["items"][0]["text"])
        self.assertEqual(catalogs.statement(ac.definition(), "en")["warnings"]["items"], [])
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                table = catalogs.own(locale)
                for name in statement.WARNING_KEYS:
                    self.assertTrue(table.get(name, "").strip(), name)
                    if locale != "en":
                        self.assertNotEqual(table[name], catalogs.own("en")[name], name)

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
        # The fixed words, plus the five statement fields of every capability the edition ships.
        shipped_statements = {statement.key(definition.id, field)
                              for definition in registry.DEFINITIONS for field in statement.FIELDS}
        self.assertEqual(english, {statement.SENTINEL_KEY, statement.ALL_OFF_KEY}
                         | set(statement.EDITION_KEYS)
                         | {statement.title_key(field) for field in statement.FIELDS}
                         | {"state.off", "state.shadow", "state.armed"}
                         | set(statement.WARNING_KEYS)
                         | shipped_statements)
        self.assertEqual(len(statement.WARNING_KEYS), 2 + len(ArmingWarning))
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

    def test_the_badge_reads_the_count_in_each_locale_and_the_not_loaded_word(self):
        """The badge (decision C12) is this package's own words, in every locale: the summary
        takes the count of what is armed, and the not-loaded word is separate."""
        catalogs = statement.CATALOGS
        english = catalogs.badge(0, "en")
        self.assertIn("0", english)
        self.assertNotEqual(catalogs.badge(0, "ko"), english)      # each locale its own words
        self.assertIn("2", catalogs.badge(2, "en"))
        self.assertEqual(catalogs.badge(0, "en", loaded=False), "Advanced - not loaded")


if __name__ == "__main__":
    unittest.main()
