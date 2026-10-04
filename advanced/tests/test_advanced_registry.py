"""The capability registry, the standards a capability departs from, and its statement.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import importlib.util
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
# Any capital letter, and whatever follows the bold id: a family added to the file (`## L.`, `**L1**`)
# or a rule written `**A31**: ...` is still found, and fails against FAMILIES until it follows.
STANDARDS_FILE = ac.ROOT / standards.BASIS
RULE_LINE = re.compile(r"(?m)^\*\*(0\.\d+|[A-Z]\d+)\*\*")
FAMILY_HEADING = re.compile(r"(?m)^## (0|[A-Z])\. ")
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
    SHIPPED = ("start_with_codex", "goal_continuation", "marker_free_continuation", "capacity_retry",
               "structured_rules", "unknown_failure_budget", "codex_gave_up", "sign_in_retry", "early_reset")

    def test_the_registry_this_edition_ships_is_its_capabilities_in_their_order(self):
        self.assertEqual([d.id for d in registry.DEFINITIONS], list(self.SHIPPED))
        self.assertEqual(len(registry.REGISTRY), len(self.SHIPPED))
        self.assertEqual(registry.REGISTRY.ids, self.SHIPPED)
        # Start-with-Codex answers at P9 alone - it starts the watcher, it does not send; the goal
        # continuation at P16, P3 and P5 - the route, the hold while a goal carries a conversation on,
        # and the channel where M2b passed; the marker-free continuation at P5 and P15, the channel
        # and the way it carries the words. At P5 the goal continuation comes first, so where both
        # are on and the goal applies its channel carries the send. Those that take failures up (v0.6.13)
        # answer at P17 and again at P3, in the order that is precedence where two would answer.
        answering = {Point.START_ROUTE: ("start_with_codex",), Point.SCHEDULE: ("early_reset",),
                     Point.UNLOADED: ("goal_continuation",),
                     Point.GATES: ("goal_continuation", "capacity_retry", "structured_rules",
                                   "unknown_failure_budget", "codex_gave_up", "sign_in_retry", "early_reset"),
                     Point.ADMISSION: ("capacity_retry", "structured_rules", "unknown_failure_budget",
                                       "codex_gave_up", "sign_in_retry"),
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

    def test_the_capacity_retries_depart_and_rest_on_what_the_design_says(self):
        """A20 (five a conversation a day, fifteen minutes apart), A21 (the budgets), A22 (waits only
        from the retry timing) and B9 (it reads Codex's code); 48 a day in one conversation - core's
        capacity day, which only the A20 departure allows - and one to twelve hours, two by default."""
        from codex_auto_resume_advanced.vocabulary import OptionKey
        cap = registry.REGISTRY.get("capacity_retry")
        self.assertEqual(cap.departs_from, ("A20", "A21", "A22", "B9"))
        self.assertEqual((cap.compat, cap.measurements, cap.revision), ("transient_classification", (), 1))
        self.assertEqual(cap.points, frozenset({Point.ADMISSION, Point.GATES}))
        self.assertEqual((cap.ceilings.per_day, cap.ceilings.per_conversation), (48, 48))
        from codex_auto_resume import ladder
        self.assertEqual(cap.ceilings.per_conversation, ladder.CAPACITY_PER_DAY)
        option = cap.option(OptionKey.CEILING_HOURS)
        self.assertEqual((option.choices, option.default), ((1, 2, 3, 4, 6, 8, 12), 2))
        self.assertLessEqual(max(option.choices) * 3600, ladder.CAPACITY_MAX_SECONDS)
        self.assertEqual((cap.rules_editor, cap.samples, cap.codes), (False, False, ()))

    def test_the_rules_depart_and_rest_on_what_the_design_says(self):
        """0.5, A13, A14 (an unknown failure is never retried), A26 (continuation text only for a
        recovered kind) and B9 (it reads Codex's code); five a conversation, two dozen a day; the one
        capability whose rules the Dashboard edits, counting its hits as `matched`."""
        rules = registry.REGISTRY.get("structured_rules")
        self.assertEqual(rules.departs_from, ("0.5", "A13", "A14", "A26", "B9"))
        self.assertEqual((rules.compat, rules.measurements, rules.revision), ("transient_classification", (), 1))
        self.assertEqual(rules.points, frozenset({Point.ADMISSION, Point.GATES}))
        self.assertEqual((rules.ceilings.per_day, rules.ceilings.per_conversation), (24, 5))
        self.assertEqual((rules.rules_editor, rules.samples, rules.codes, rules.options), (True, False, ("matched",), ()))
        self.assertEqual([definition.id for definition in registry.DEFINITIONS if definition.rules_editor],
                         ["structured_rules"])

    def test_the_unknown_failure_budget_departs_and_rests_on_what_the_design_says(self):
        """As the rules, and D2 too - a sample keeps a code Codex chose; three a conversation, a dozen
        a day; one to three tries a task, one by default; the one capability that samples."""
        from codex_auto_resume_advanced.vocabulary import OptionKey
        unknown = registry.REGISTRY.get("unknown_failure_budget")
        self.assertEqual(unknown.departs_from, ("0.5", "A13", "A14", "A26", "B9", "D2"))
        self.assertEqual((unknown.compat, unknown.measurements, unknown.revision), ("transient_classification", (), 1))
        self.assertEqual(unknown.points, frozenset({Point.ADMISSION, Point.GATES}))
        self.assertEqual((unknown.ceilings.per_day, unknown.ceilings.per_conversation), (12, 3))
        option = unknown.option(OptionKey.ATTEMPTS)
        self.assertEqual((option.choices, option.default), ((1, 2, 3), 1))
        self.assertEqual((unknown.rules_editor, unknown.samples, unknown.codes), (False, True, ("sampled",)))
        self.assertEqual([definition.id for definition in registry.DEFINITIONS if definition.samples],
                         ["unknown_failure_budget"])
        ids = registry.REGISTRY.ids
        self.assertLess(ids.index("structured_rules"), ids.index("unknown_failure_budget"), "rules come first")

    def test_the_retries_when_codex_gave_up_depart_and_rest_on_what_the_design_says(self):
        """A14 (Codex giving up without a 429 is never retried), A26 and B9; two a conversation, a
        dozen a day; no choice, no rules, no samples."""
        gave_up = registry.REGISTRY.get("codex_gave_up")
        self.assertEqual(gave_up.departs_from, ("A14", "A26", "B9"))
        self.assertEqual((gave_up.compat, gave_up.measurements, gave_up.revision), ("transient_classification", (), 1))
        self.assertEqual(gave_up.points, frozenset({Point.ADMISSION, Point.GATES}))
        self.assertEqual((gave_up.ceilings.per_day, gave_up.ceilings.per_conversation), (12, 2))
        self.assertEqual((gave_up.options, gave_up.rules_editor, gave_up.samples, gave_up.codes), ((), False, False, ()))

    def test_the_sign_in_retry_departs_and_rests_on_what_the_design_says(self):
        """0.5 (sign-in failures are never retried), A14 (401 and 403) and A26; the usage read is its
        proof, so it stands on usage_probe; two a conversation and two a day; no choice, no rules, no
        samples, and no app-server method of its own."""
        sign_in = registry.REGISTRY.get("sign_in_retry")
        self.assertEqual(sign_in.departs_from, ("0.5", "A14", "A26"))
        self.assertEqual((sign_in.compat, sign_in.measurements, sign_in.revision), ("usage_probe", (), 1))
        self.assertEqual(sign_in.points, frozenset({Point.ADMISSION, Point.GATES}))
        self.assertEqual((sign_in.ceilings.per_day, sign_in.ceilings.per_conversation), (2, 2))
        self.assertEqual((sign_in.options, sign_in.rules_editor, sign_in.samples, sign_in.codes), ((), False, False, ()))

    def test_the_early_reset_departs_and_rests_on_what_the_design_says(self):
        """A12 (never before the real reset time) and C9 (usage read only when a recovery is due); the
        usage read is what it asks, so it stands on usage_probe; three a conversation, a dozen a day; its
        two words; no choice, no rules, no samples, and no app-server method of its own."""
        early = registry.REGISTRY.get("early_reset")
        self.assertEqual(early.departs_from, ("A12", "C9"))
        self.assertEqual((early.compat, early.measurements, early.revision), ("usage_probe", (), 1))
        self.assertEqual(early.points, frozenset({Point.SCHEDULE, Point.GATES}))
        self.assertEqual((early.ceilings.per_day, early.ceilings.per_conversation), (12, 3))
        self.assertEqual((early.options, early.rules_editor, early.samples, early.codes),
                         ((), False, False, ("probed", "lifted")))

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

    def test_one_conversations_ceiling_passes_cores_five_only_for_one_that_departs_from_a20(self):
        """A20 is the standard edition's five a conversation a day, fifteen minutes apart: a ceiling
        above it is a departure the statement has to name (v0.6.13, the capacity retries)."""
        over = Ceilings(per_day=48, per_conversation=48)
        self.assertIn("ceilings", problems(ac.definition(ceilings=over)))
        self.assertIn("ceilings", problems(ac.definition(ceilings=over, departs_from=("A21", "A22"))))
        self.assertEqual(problems(ac.definition(ceilings=over, departs_from=("A20",))), [])
        self.assertIn("ceilings", problems(ac.definition(ceilings=Ceilings(per_day=6, per_conversation=7),
                                                         departs_from=("A20",))))

    def test_a_choice_it_offers_has_a_key_whole_numbers_smallest_first_and_one_of_them_by_default(self):
        from codex_auto_resume_advanced.registry import Option
        from codex_auto_resume_advanced.vocabulary import OptionKey
        good = Option(OptionKey.ATTEMPTS, (1, 2, 3), 1)
        made = ac.definition(options=(good, Option(OptionKey.CEILING_HOURS, (1, 2, 12), 2)))
        self.assertEqual(problems(made), [])
        self.assertIs(made.option(OptionKey.ATTEMPTS), good)
        self.assertIsNone(ac.definition().option(OptionKey.ATTEMPTS))
        for options in ((Option("tries", (1, 2), 1),), (Option(OptionKey.ATTEMPTS, (), 1),),
                        (Option(OptionKey.ATTEMPTS, (2, 1), 1),), (Option(OptionKey.ATTEMPTS, (1, 1), 1),),
                        (Option(OptionKey.ATTEMPTS, (0, 1), 1),), (Option(OptionKey.ATTEMPTS, (1, 2), 3),),
                        (Option(OptionKey.ATTEMPTS, [1, 2], 1),), (Option(OptionKey.ATTEMPTS, (1, True), 1),),
                        (good, good), [good], ("attempts",)):
            with self.subTest(options=options):
                self.assertIn("options", problems(ac.definition(options=options)))
        self.assertIn("rules_editor or samples", problems(ac.definition(samples=1)))

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
        self.assertEqual(len(standards.STANDARDS), 174)
        self.assertEqual(len(set(standards.STANDARDS)), 174)
        self.assertEqual(standards.STANDARDS[:2], ("0.1", "0.2"))
        self.assertEqual(standards.STANDARDS[-1], "K7")
        self.assertEqual(len(standards.DEPARTABLE), 167)
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
                         | set(statement.PAGE_KEYS)
                         | {statement.name_key(definition.id) for definition in registry.DEFINITIONS}
                         | shipped_statements)
        self.assertEqual(len(statement.WARNING_KEYS), 2 + len(ArmingWarning))
        for locale, table in tables.items():
            with self.subTest(locale):
                self.assertEqual(set(table), english)
                self.assertTrue(all(value.strip() for value in table.values()))
                self.assertEqual(table[statement.SENTINEL_KEY], tables["en"][statement.SENTINEL_KEY])
                if locale != "en":
                    self.assertNotEqual(table[statement.ALL_OFF_KEY], tables["en"][statement.ALL_OFF_KEY])

    def test_the_page_s_words_are_every_page_key_every_name_and_the_three_states(self):
        """What advanced-words hands the Dashboard's Advanced features page: its own words, a name for every
        capability the edition ships and the three states' words - in the person's language, each language's own."""
        english = statement.CATALOGS.words("en")
        wanted = (set(statement.PAGE_KEYS) | {"state.off", "state.shadow", "state.armed"}
                  | {statement.name_key(definition.id) for definition in registry.DEFINITIONS})
        self.assertEqual(set(english), wanted)
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                words = statement.CATALOGS.words(locale)
                self.assertEqual(set(words), wanted)
                self.assertEqual(words, {key: statement.CATALOGS.own(locale)[key] for key in wanted})
                for key in wanted:
                    self.assertEqual(l10n.placeholders(words[key]), l10n.placeholders(english[key]), key)
                if locale != "en":
                    # A page in the person's language: its tab, its buttons and the capabilities' names are theirs.
                    for key in ("page.nav", "page.turn_on", "page.watch", "page.all_off"):
                        self.assertNotEqual(words[key], english[key], key)

    def test_every_translation_is_current_by_the_bookkeeping(self):
        """build/l10n.py --advanced: each language's words are a translation of the English as it is now - its basis
        in build/l10n/advanced/ records the English each was made from - with no key missing, stale, extra or with a
        placeholder lost, as core's catalogs are held (tests/test_l10n.py)."""
        spec = importlib.util.spec_from_file_location("l10n_tool", ac.ROOT / "build" / "l10n.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        self.assertEqual(tool.ADVANCED_CATALOGS.resolve(), statement.DIRECTORY.resolve())
        tool.CATALOGS, tool.BASIS = tool.ADVANCED_CATALOGS, tool.ADVANCED_BASIS
        for locale in tool.translations():
            with self.subTest(locale):
                found = tool.report(locale)
                for kind in ("missing", "stale", "extra", "placeholders", "empty"):
                    self.assertEqual(found[kind], [], "%s %s" % (locale, kind))

    def test_each_language_reads_as_one_voice(self):
        """The Advanced features page shows the statements beside its own words and joins both in one question
        (ArmQuestion), so a language says them in one voice: German in Sie throughout, as core's catalog and the page
        are, with the feature as "sie" (die Funktion) in its titles and its text alike; Korean and Japanese with one
        word for the standard edition, in the field's title and under it; and Korean's Watch first saying that the
        feature is consulted, not that the person will be asked."""
        tables = self.tables()
        for key, value in tables["de"].items():
            with self.subTest(locale="de", key=key):
                self.assertIsNone(re.search(r"\b(du|dich|dir|dein\w*|Schalte|pausiere)\b", value, re.I), value)
                self.assertIsNone(re.search(r"\b(setzt|handelt|beruht|registriert) es\b"
                                            r"|\bEs (setzt|startet|registriert|beruht|handelt)\b|\bSein einziger\b",
                                            value), value)
                self.assertNotIn("Standardedition", value)
        for definition in registry.DEFINITIONS:
            self.assertIn("Schalten Sie", tables["de"][statement.key(definition.id, Field.STOP)])
        for locale, edition, other in (("ko", "표준판", "표준 에디션"), ("ja", "標準版", "標準エディション")):
            with self.subTest(locale=locale):
                self.assertIn(edition, tables[locale][statement.title_key(Field.INSTEAD)])
                self.assertFalse([key for key, value in tables[locale].items() if other in value])
        self.assertNotIn("물어보고", tables["ko"]["page.confirm.watch"])

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
