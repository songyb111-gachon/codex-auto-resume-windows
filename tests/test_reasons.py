"""The reason registry and the classifier describe the same categories, in both directions.

`reasons.py` names, words and configures categories; `failures.py` decides them. The
registry may never know a category the classifier cannot produce, and the classifier may
never produce one the registry cannot name - v0.6.2 shipped `auth_service_transient` as
recoverable, with no switch and no label, because nothing checked this.

Nor may a category be recoverable that nothing produces. v0.6.3 gave `auth_service_transient` its
switch and its Custom message, and no code, status or message had ever mapped to it: a switch that
could never fire, and a changelog and a guide that said it had been recovered. v0.6.10 reserves it
(failures.RESERVED), and ReachabilityTests fails if a name nothing produces is made recoverable again.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

from codex_auto_resume import engine, failures, l10n, reasons, settings  # noqa: E402


class RegistryAgreementTests(unittest.TestCase):
    def test_every_classifier_category_has_exactly_one_entry(self):
        self.assertEqual(set(reasons.REASONS), set(failures.CATEGORIES))

    def test_recoverable_means_what_the_classifier_means(self):
        recoverable = set(failures.TRANSIENT) | {failures.USAGE_LIMIT}
        self.assertEqual(set(reasons.RECOVERABLE), recoverable)
        for category in set(failures.TERMINAL) | {failures.UNKNOWN} | set(failures.RESERVED):
            with self.subTest(category):
                self.assertFalse(reasons.is_recoverable(category))
                self.assertFalse(failures.is_recoverable(category))

    def test_every_recoverable_category_has_a_switch_and_every_switch_a_category(self):
        self.assertEqual(set(reasons.configurable()), set(settings.CONFIGURABLE_CATEGORIES))
        for category in reasons.configurable():
            with self.subTest(category):
                self.assertIn("recover_" + category, settings.FIELDS)
                self.assertIs(settings.DEFAULTS["recover_" + category], True)

    def test_no_recoverable_category_is_recovered_without_a_switch(self):
        """`Engine.recovers` recovers any category that has no switch. That rule is only
        safe while every recoverable category has one, so this holds it there.

        The rule is followed to wherever it lives rather than read from one function's code
        object, which a wrapper around a moved rule would no longer show: the one place in the
        package that lets a category through for being outside CONFIGURABLE_CATEGORIES is
        found by its shape (a move updates the entry on purpose), and what the engine then
        decides is asked of it - with every switch off, nothing recoverable is recovered."""
        self.assertLessEqual(set(reasons.RECOVERABLE), set(settings.CONFIGURABLE_CATEGORIES))
        found = set()
        for path, tree in srcscan.package_asts().items():
            names = srcscan.qualnames(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Compare) and any(isinstance(op, ast.NotIn) for op in node.ops)
                        and any("CONFIGURABLE_CATEGORIES" in ast.unparse(side) for side in node.comparators)):
                    found.add((srcscan.relative(path), names[node]))
        self.assertEqual(found, {("codex_auto_resume/engine/options.py", "OptionsMixin.recovers")})
        switched_off = engine.Engine(None, None, None)
        switched_off.apply_policy({"recover_" + category: False for category in settings.CONFIGURABLE_CATEGORIES})
        for category in reasons.RECOVERABLE:
            with self.subTest(category):
                self.assertFalse(switched_off.recovers(category))

    def test_a_custom_message_field_exists_for_exactly_the_recoverable_categories(self):
        per_reason = {name[len("custom_message_"):] for name in settings.FIELDS
                      if name.startswith("custom_message_") and name != "custom_message_mode"}
        self.assertEqual(per_reason, set(reasons.RECOVERABLE))


def produced() -> set:
    """Every category the classifier can hand back, found by asking it and by reading its tables.

    Asked: every variant it knows, bare; every HTTP status, alone and under every variant (so a
    rule such as `responseTooManyFailedAttempts` with 429 is found); nothing at all. Read: the
    category of each message pattern, since a sentence that matches one cannot be derived from it.
    """
    found = {failures.classify(tag) for tag in failures.CODES}
    found |= {failures.classify({"httpStatusCode": status}) for status in range(1000)}
    found |= {failures.classify({"type": tag, "httpStatusCode": status})
              for tag in failures.CODES for status in range(1000)}
    found |= {failures.classify(None, None), failures.classify("somethingNew")}
    found |= {category for _pattern, category in failures._MESSAGE_PATTERNS}
    return found


def unproduced(transient) -> set:
    return set(transient) - produced()


class ReachabilityTests(unittest.TestCase):
    """A recoverable category is one the classifier produces, or its switch is a switch for nothing."""

    def test_every_transient_category_has_a_producer(self):
        self.assertEqual(sorted(unproduced(failures.TRANSIENT)), [],
                         "in TRANSIENT with no CODES entry, status rule or message pattern: reserve it "
                         "(failures.RESERVED) until a real Codex error is seen to carry it")

    def test_the_check_sees_a_reserved_name_put_back(self):
        for category in failures.RESERVED:
            with self.subTest(category):
                self.assertEqual(unproduced(failures.TRANSIENT | {category}), {category})

    def test_every_recoverable_and_every_switchable_category_is_produced(self):
        found = produced()
        self.assertLessEqual(set(reasons.RECOVERABLE), found)
        self.assertLessEqual(set(settings.CONFIGURABLE_CATEGORIES), found)
        self.assertLessEqual(found, set(failures.CATEGORIES))

    def test_a_reserved_category_is_a_word_and_nothing_more(self):
        """Its word and its label stay, so a row or a file that names it still reads; nothing else
        does - no classification, no recovery, no switch, no Custom message, no continuation text,
        no place in the schema every surface is drawn from, and no place in the Preview."""
        english = l10n._read(l10n.DEFAULT)
        described = settings.describe()
        found = produced()
        self.assertEqual(set(failures.RESERVED), {"auth_service_transient"})
        for category in failures.RESERVED:
            with self.subTest(category):
                self.assertIn(category, failures.CATEGORIES)
                self.assertNotIn(category, found)
                self.assertNotIn(category, failures.TRANSIENT)
                self.assertNotIn(category, settings.CONFIGURABLE_CATEGORIES)
                self.assertNotIn(category, reasons.RECOVERABLE)
                self.assertNotIn(category, reasons.configurable())
                self.assertNotIn("recover_" + category, settings.FIELDS)
                self.assertNotIn("custom_message_" + category, settings.FIELDS)
                self.assertEqual([entry for entry in described
                                  if category in (entry.get("category"), entry["name"])], [])
                entry = reasons.get(category)
                self.assertEqual(entry.category, category)
                self.assertIn(entry.label_key, english)
                self.assertIsNone(entry.standard_key)
                self.assertIsNone(entry.detailed_key)
                self.assertFalse(entry.configurable)


class EntryTests(unittest.TestCase):
    def test_every_label_and_message_key_exists_in_english(self):
        english = l10n._read(l10n.DEFAULT)
        for entry in reasons.REASONS.values():
            with self.subTest(entry.category):
                self.assertIn(entry.label_key, english)
                if entry.recoverable:
                    self.assertIn(entry.standard_key, english)
                    self.assertIn(entry.detailed_key, english)
                else:
                    self.assertIsNone(entry.standard_key)
                    self.assertIsNone(entry.detailed_key)

    def test_only_a_usage_limit_carries_a_reset_time(self):
        self.assertEqual({c for c in reasons.ALL if reasons.has_reset_time(c)}, {failures.USAGE_LIMIT})

    def test_presentation_order_is_unique_and_stable(self):
        orders = [entry.order for entry in reasons.REASONS.values()]
        self.assertEqual(len(orders), len(set(orders)))
        self.assertEqual(reasons.RECOVERABLE[0], failures.USAGE_LIMIT)

    def test_an_unheard_of_category_is_named_as_unknown_and_is_not_recoverable(self):
        self.assertEqual(reasons.get("from_the_future").category, failures.UNKNOWN)
        self.assertFalse(reasons.is_recoverable("from_the_future"))


if __name__ == "__main__":
    unittest.main()
