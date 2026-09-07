"""The shared settings layer: schema, validation, persistence and migration.

The behaviour worth protecting is asymmetric, and the tests are grouped that way:

* Reading is total. A truncated, hand-edited, hostile or simply newer settings file
  must still produce a complete, valid, conservative configuration, because the
  alternative is a watcher that refuses to start and a recovery that never happens.
* Writing is strict. An explicit edit that cannot be honoured is refused, so nobody
  sets a value, is told it worked, and gets something else.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from codex_auto_resume import failures, settings


class DefaultsTests(unittest.TestCase):
    def test_every_field_has_a_default(self):
        self.assertEqual(set(settings.defaults()), set(settings.FIELDS))

    def test_defaults_survive_their_own_validator(self):
        # A default that its own validator rewrites would silently become something
        # else on the first save, which is the hardest kind of bug to see.
        self.assertEqual(settings.coerce(settings.defaults()), settings.defaults())

    def test_recovery_categories_are_all_classifier_categories(self):
        # A toggle for a category the classifier cannot produce would be dead UI; a
        # category the classifier CAN produce with no toggle is a silent policy.
        for category in settings.CONFIGURABLE_CATEGORIES:
            self.assertIn(category, failures.CATEGORIES, category)

    def test_recovery_defaults_to_on_for_every_category(self):
        values = settings.defaults()
        for category in settings.CONFIGURABLE_CATEGORIES:
            self.assertTrue(values["recover_" + category], category)

    def test_no_setting_can_enable_recovery_of_an_unknown_failure(self):
        # The single most important property of this module: policy is configurable,
        # safety is not. Nothing here may name a category outside the recoverable set.
        for name in settings.FIELDS:
            if name.startswith("recover_"):
                self.assertIn(name[len("recover_"):], settings.CONFIGURABLE_CATEGORIES)


class CoerceTests(unittest.TestCase):
    def test_unknown_keys_are_dropped(self):
        values = settings.coerce({"nonsense": 1, "max_recovery_attempts": 7})
        self.assertNotIn("nonsense", values)
        self.assertEqual(values["max_recovery_attempts"], 7)

    def test_out_of_range_falls_back_to_the_default(self):
        self.assertEqual(settings.coerce({"max_recovery_attempts": 999})["max_recovery_attempts"],
                         settings.DEFAULTS["max_recovery_attempts"])
        self.assertEqual(settings.coerce({"max_recovery_attempts": 0})["max_recovery_attempts"],
                         settings.DEFAULTS["max_recovery_attempts"])

    def test_wrong_type_falls_back_to_the_default(self):
        for raw in ({"notifications": "yes"}, {"notifications": 1}, {"notifications": None}):
            self.assertIs(settings.coerce(raw)["notifications"], True)

    def test_booleans_are_not_accepted_as_integers(self):
        # bool is a subclass of int in Python, so `True` would otherwise pass a bounds
        # check and become an attempt budget of 1.
        self.assertEqual(settings.coerce({"max_recovery_attempts": True})["max_recovery_attempts"],
                         settings.DEFAULTS["max_recovery_attempts"])

    def test_unknown_timing_preset_falls_back(self):
        self.assertEqual(settings.coerce({"retry_timing": "instant"})["retry_timing"],
                         settings.DEFAULT_TIMING)

    def test_non_mapping_yields_defaults(self):
        for raw in (None, [], "settings", 3):
            self.assertEqual(settings.coerce(raw), settings.defaults())


class ValidateUpdateTests(unittest.TestCase):
    def test_unknown_setting_is_refused(self):
        with self.assertRaises(settings.SettingsError):
            settings.validate_update({"retry_unknown_failures": True})

    def test_out_of_range_is_refused_rather_than_clamped(self):
        with self.assertRaises(settings.SettingsError):
            settings.validate_update({"max_recovery_attempts": 999})

    def test_valid_edit_is_returned_unchanged(self):
        self.assertEqual(settings.validate_update({"max_recovery_attempts": 9, "notifications": False}),
                         {"max_recovery_attempts": 9, "notifications": False})

    def test_clearing_the_codex_path_is_allowed(self):
        self.assertEqual(settings.validate_update({"codex_exe": None}), {"codex_exe": None})

    def test_non_mapping_is_refused(self):
        with self.assertRaises(settings.SettingsError):
            settings.validate_update(["max_recovery_attempts", 4])


class PolicyTests(unittest.TestCase):
    def test_timing_ladder_is_strictly_increasing(self):
        for name, ladder in settings.RETRY_TIMING.items():
            self.assertTrue(all(b > a for a, b in zip(ladder, ladder[1:])), name)
            self.assertTrue(all(delay > 0 for delay in ladder), name)

    def test_timing_ladder_falls_back_for_a_bad_preset(self):
        self.assertEqual(settings.timing_ladder({"retry_timing": "nope"}),
                         settings.RETRY_TIMING[settings.DEFAULT_TIMING])
        self.assertEqual(settings.timing_ladder(None),
                         settings.RETRY_TIMING[settings.DEFAULT_TIMING])

    def test_category_toggle_is_respected(self):
        values = settings.defaults()
        values["recover_timeout"] = False
        self.assertFalse(settings.category_enabled(values, "timeout"))
        self.assertTrue(settings.category_enabled(values, failures.USAGE_LIMIT))

    def test_category_without_a_toggle_is_treated_as_enabled(self):
        # Absence of a switch is not an instruction to stop: the classifier already
        # decided the category is recoverable.
        self.assertTrue(settings.category_enabled(settings.defaults(), "some_future_category"))

    def test_master_notification_switch_silences_every_event(self):
        values = settings.defaults()
        values["notifications"] = False
        for event in settings.NOTIFICATION_EVENTS:
            self.assertFalse(settings.notification_enabled(values, event), event)

    def test_individual_notification_events_are_independent(self):
        values = settings.defaults()
        values["notify_starting"] = False
        self.assertFalse(settings.notification_enabled(values, "starting"))
        self.assertTrue(settings.notification_enabled(values, "interruption"))


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "settings.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_missing_file_reads_as_defaults(self):
        self.assertEqual(settings.load(self.path), settings.defaults())

    def test_round_trip(self):
        settings.save(self.path, dict(settings.defaults(), max_no_progress=7))
        self.assertEqual(settings.load(self.path)["max_no_progress"], 7)

    def test_saved_file_records_its_schema_version(self):
        settings.save(self.path, settings.defaults())
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(stored["config_version"], settings.CONFIG_VERSION)

    def test_corrupt_file_reads_as_defaults(self):
        self.path.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(settings.load(self.path), settings.defaults())

    def test_oversized_file_is_ignored(self):
        self.path.write_text("{}" + " " * (settings.MAX_SETTINGS_BYTES + 10), encoding="utf-8")
        self.assertEqual(settings.load(self.path), settings.defaults())

    def test_update_merges_rather_than_replaces(self):
        settings.save(self.path, dict(settings.defaults(), max_no_progress=7))
        settings.update(self.path, {"max_recovery_attempts": 9})
        values = settings.load(self.path)
        self.assertEqual(values["max_no_progress"], 7)
        self.assertEqual(values["max_recovery_attempts"], 9)

    def test_rejected_update_leaves_the_file_untouched(self):
        settings.save(self.path, dict(settings.defaults(), max_no_progress=7))
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(settings.SettingsError):
            settings.update(self.path, {"max_no_progress": 99})
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_no_temporary_file_is_left_behind(self):
        settings.save(self.path, settings.defaults())
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_migration_from_an_unversioned_v04_file(self):
        # v0.4.x wrote a flat file with no version marker. Fields that still exist keep
        # their values; anything else takes the current default rather than failing.
        self.path.write_text(json.dumps({"max_recovery_attempts": 6, "poll_seconds": 30}),
                             encoding="utf-8")
        values = settings.load(self.path)
        self.assertEqual(values["max_recovery_attempts"], 6)
        self.assertNotIn("poll_seconds", values)
        self.assertEqual(values["retry_timing"], settings.DEFAULT_TIMING)

    def test_a_newer_config_version_still_loads(self):
        self.path.write_text(json.dumps({"config_version": 99, "max_no_progress": 5}),
                             encoding="utf-8")
        self.assertEqual(settings.load(self.path)["max_no_progress"], 5)


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self.described = settings.describe()
        self.by_name = {entry["name"]: entry for entry in self.described}

    def test_describes_every_field_exactly_once(self):
        self.assertEqual(sorted(self.by_name), sorted(settings.FIELDS))
        self.assertEqual(len(self.described), len(settings.FIELDS))

    def test_every_entry_carries_a_group_the_interfaces_understand(self):
        for entry in self.described:
            self.assertIn(entry["group"], {"recovery", "limits", "notifications", "advanced"})

    def test_published_ranges_accept_their_own_bounds(self):
        # A user interface builds its spin boxes from these numbers, so a bound the
        # validator would reject means an interface that offers an unsaveable value.
        for name, bounds in settings.RANGES.items():
            if "min" not in bounds:
                continue
            for value in (bounds["min"], bounds["max"]):
                candidate = int(value) if isinstance(settings.DEFAULTS[name], int) else value
                self.assertEqual(settings.validate_update({name: candidate})[name], candidate)

    def test_published_choices_are_all_accepted(self):
        for choice in self.by_name["retry_timing"]["choices"]:
            self.assertEqual(settings.validate_update({"retry_timing": choice})["retry_timing"], choice)

    def test_exactly_one_master_notification_switch(self):
        masters = [entry["name"] for entry in self.described if entry.get("master")]
        self.assertEqual(masters, ["notifications"])

    def test_no_described_field_offers_to_retry_unknown_failures(self):
        for entry in self.described:
            self.assertNotIn("unknown", entry["name"])


if __name__ == "__main__":
    unittest.main()
