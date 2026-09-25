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
import guiscan
import unittest
from unittest.mock import patch

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

    def test_a_file_with_the_reserved_category_s_switch_still_loads(self):
        """v0.6.3 to v0.6.9 stored a switch and a Custom message for `auth_service_transient`, which
        nothing ever produced; v0.6.10 has neither field (failures.RESERVED). Such a file loads as it
        always did - every other value kept, the two keys dropped - and the next save leaves them out.
        A write that names either is refused, as a write naming any field this build lacks is."""
        old = dict(settings.defaults(), config_version=2, max_no_progress=5, recover_timeout=False,
                   recover_auth_service_transient=False,
                   custom_message_auth_service_transient="Please carry on.")
        self.path.write_text(json.dumps(old), encoding="utf-8")
        self.assertEqual(settings.load(self.path),
                         dict(settings.defaults(), max_no_progress=5, recover_timeout=False))
        settings.update(self.path, {"notifications": False})
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("recover_auth_service_transient", stored)
        self.assertNotIn("custom_message_auth_service_transient", stored)
        self.assertEqual((stored["max_no_progress"], stored["recover_timeout"], stored["notifications"]),
                         (5, False, False))
        for name in ("recover_auth_service_transient", "custom_message_auth_service_transient"):
            with self.subTest(name), self.assertRaises(settings.SettingsError):
                settings.update(self.path, {name: None if name.startswith("custom") else True})


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self.described = settings.describe()
        self.by_name = {entry["name"]: entry for entry in self.described}

    def test_describes_every_field_exactly_once(self):
        # Every field but those held back until something reads them (NOT_YET_OFFERED): a
        # surface draws whatever is described, and a switch that changes nothing must not be drawn.
        offered = set(settings.FIELDS) - settings.NOT_YET_OFFERED
        self.assertEqual(sorted(self.by_name), sorted(offered))
        self.assertEqual(len(self.described), len(offered))
        self.assertLessEqual(settings.NOT_YET_OFFERED, set(settings.FIELDS), "held back, not unknown")
        with patch.object(settings, "NOT_YET_OFFERED", frozenset()):
            self.assertEqual(sorted(entry["name"] for entry in settings.describe()), sorted(settings.FIELDS))

    def test_every_entry_carries_a_group_the_interfaces_understand(self):
        # "windows" holds desktop preferences - the notification-area icon - shown in
        # the settings window's Windows card and not offered to Codex. "general" holds the
        # Interface language, and "continuation" the words a continuation is sent with.
        for entry in self.described:
            self.assertIn(entry["group"], {"general", "recovery", "limits", "notifications",
                                           "continuation", "appearance", "windows", "advanced"})

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
        # Every field that publishes choices, so a list a surface draws a picker from can
        # never offer one its validator refuses.
        for entry in self.described:
            for choice in entry.get("choices", ()):
                with self.subTest(name=entry["name"], choice=choice):
                    self.assertEqual(settings.validate_update({entry["name"]: choice}),
                                     {entry["name"]: choice})

    def test_exactly_one_master_notification_switch(self):
        masters = [entry["name"] for entry in self.described if entry.get("master")]
        self.assertEqual(masters, ["notifications"])

    def test_no_described_field_offers_to_retry_unknown_failures(self):
        for entry in self.described:
            self.assertNotIn("unknown", entry["name"])


class ThemeTests(unittest.TestCase):
    """Light, dark, or whatever the host is using - an ordinary appearance setting.

    "system" is the default because it is the one choice that is right for everybody on
    the first start: a person whose Windows is dark does not open a white window.
    """

    def test_the_choices_and_the_default(self):
        self.assertEqual(settings.THEMES, ("system", "light", "dark"))
        self.assertEqual(settings.DEFAULTS["theme"], "system")
        self.assertEqual(settings.defaults()["theme"], settings.DEFAULT_THEME)

    def test_every_choice_is_accepted_as_written(self):
        for choice in settings.THEMES:
            with self.subTest(choice):
                self.assertEqual(settings.validate_update({"theme": choice}), {"theme": choice})
                self.assertEqual(settings.coerce({"theme": choice})["theme"], choice)

    def test_anything_else_is_refused_on_write_and_is_system_on_read(self):
        # Not "light": an unreadable theme follows the host, which is what the person had
        # before they ever chose one.
        for bad in ("Dark", "DARK", "sepia", "high_contrast", "", " dark", None, True, 0, ["dark"]):
            with self.subTest(bad=bad):
                with self.assertRaises(settings.SettingsError) as caught:
                    settings.validate_update({"theme": bad})
                self.assertIn("theme", str(caught.exception))
                self.assertEqual(settings.coerce({"theme": bad})["theme"], "system")

    def test_the_preference_helper_only_ever_answers_a_choice(self):
        self.assertEqual(settings.theme_preference({"theme": "dark"}), "dark")
        self.assertEqual(settings.theme_preference({"theme": "light"}), "light")
        for values in (None, {}, {"theme": "purple"}, {"theme": 1}, "dark"):
            with self.subTest(values=values):
                self.assertEqual(settings.theme_preference(values), "system")

    def test_it_is_described_first_in_appearance_with_its_choices(self):
        described = settings.describe()
        entry = next(entry for entry in described if entry["name"] == "theme")
        self.assertEqual(entry, {"name": "theme", "default": "system", "type": "string",
                                 "choices": ["system", "light", "dark"], "group": "appearance"})
        appearance = [entry["name"] for entry in described if entry["group"] == "appearance"]
        # v0.6.10: the design between the themes and Reduce motion.
        self.assertEqual(appearance, ["theme", "panel_theme", "design", "reduce_motion"])

    def test_it_round_trips_through_the_file_and_survives_an_unrelated_update(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings.update(path, {"theme": "dark"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["theme"], "dark")
            settings.update(path, {"reduce_motion": True})
            self.assertEqual(settings.load(path)["theme"], "dark")
            # A settings file written before the theme existed reads as "system".
            path.write_text(json.dumps({"config_version": 2, "reduce_motion": True}), encoding="utf-8")
            self.assertEqual(settings.load(path)["theme"], "system")
            # And a hand-edited nonsense value does too, without losing its neighbours.
            path.write_text(json.dumps({"config_version": 2, "theme": "neon", "max_no_progress": 5}),
                            encoding="utf-8")
            loaded = settings.load(path)
            self.assertEqual((loaded["theme"], loaded["max_no_progress"]), ("system", 5))


class PanelThemeTests(unittest.TestCase):
    """The panel in Codex's own light or dark (v0.6.6).

    Use system setting already let each surface follow its host; what nobody could do was keep the
    window Light or Dark and give the panel a different answer ("mcp 와 나머지의 테마 설정을 별도로").
    "same" follows the Theme, which is what every panel did before the setting existed, so it is the
    default: an upgrade changes nothing anybody can see. How the panel resolves the pair is the
    panel's own (applyTheme), pinned in test_mcpui_v064.
    """

    def test_the_choices_and_a_default_that_changes_nothing(self):
        self.assertEqual(settings.PANEL_THEMES, ("same", "system", "light", "dark"))
        self.assertEqual(settings.defaults()["panel_theme"], "same")

    def test_every_choice_is_accepted_and_anything_else_is_same(self):
        for choice in settings.PANEL_THEMES:
            with self.subTest(choice):
                self.assertEqual(settings.validate_update({"panel_theme": choice}), {"panel_theme": choice})
        for bad in ("Same", "codex", "", None, 0, ["dark"]):
            with self.subTest(bad=bad):
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update({"panel_theme": bad})
                self.assertEqual(settings.coerce({"panel_theme": bad})["panel_theme"], "same")

    def test_it_sits_beside_the_theme_in_appearance(self):
        entry = next(entry for entry in settings.describe() if entry["name"] == "panel_theme")
        self.assertEqual(entry, {"name": "panel_theme", "default": "same", "type": "string",
                                 "choices": ["same", "system", "light", "dark"], "group": "appearance"})

    def test_it_round_trips_and_leaves_the_theme_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings.save(path, {"theme": "light", "panel_theme": "dark"})
            loaded = settings.load(path)
            self.assertEqual((loaded["theme"], loaded["panel_theme"]), ("light", "dark"))


class DesignTests(unittest.TestCase):
    """How every surface is drawn (v0.6.10): Soft, Classic or Plain.

    Soft is what every surface drew before the setting existed, so it is the default and a settings
    file without the key reads as Soft: an upgrade changes nothing anybody can see, and the setting
    is additive - CONFIG_VERSION stays where panel_theme left it.
    """

    def test_the_choices_the_default_and_the_vocabulary(self):
        from codex_auto_resume import brand
        from codex_auto_resume.domain.vocabulary import Design
        self.assertEqual(settings.DESIGNS, ("soft", "classic", "plain"))
        self.assertEqual(settings.DESIGNS, tuple(Design))
        self.assertEqual(settings.DESIGNS, brand.DESIGNS)
        self.assertEqual(settings.DEFAULT_DESIGN, brand.DEFAULT_DESIGN)
        self.assertEqual(settings.defaults()["design"], "soft")
        self.assertEqual(settings.CONFIG_VERSION, 2)

    def test_every_choice_is_accepted_and_anything_else_is_refused_or_soft(self):
        for choice in settings.DESIGNS:
            with self.subTest(choice):
                self.assertEqual(settings.validate_update({"design": choice}), {"design": choice})
                self.assertEqual(settings.coerce({"design": choice})["design"], choice)
        for bad in ("Soft", "SOFT", " soft", "", "look", "system", 1, 0, None, True, False, ["soft"], {"soft": 1}):
            with self.subTest(bad=bad):
                with self.assertRaises(settings.SettingsError) as caught:
                    settings.validate_update({"design": bad})
                self.assertIn("design", str(caught.exception))
                self.assertEqual(settings.coerce({"design": bad})["design"], "soft")
                self.assertEqual(settings.design_preference({"design": bad}), "soft")
        for values in (None, {}, "plain", ["plain"]):
            with self.subTest(values=values):
                self.assertEqual(settings.design_preference(values), "soft")
        self.assertEqual(settings.design_preference({"design": "classic"}), "classic")

    def test_it_is_described_in_appearance_after_the_themes(self):
        entry = next(entry for entry in settings.describe() if entry["name"] == "design")
        self.assertEqual(entry, {"name": "design", "default": "soft", "type": "string",
                                 "choices": ["soft", "classic", "plain"], "group": "appearance"})

    def test_a_file_without_it_reads_as_soft_and_it_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            # What v0.6.9 wrote: no design at all.
            path.write_text(json.dumps({"config_version": 2, "theme": "dark", "reduce_motion": True}),
                            encoding="utf-8")
            loaded = settings.load(path)
            self.assertEqual((loaded["design"], loaded["theme"], loaded["reduce_motion"]), ("soft", "dark", True))
            settings.update(path, {"design": "classic"})
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((stored["design"], stored["config_version"]), ("classic", 2))
            settings.update(path, {"theme": "light"})
            self.assertEqual(settings.load(path)["design"], "classic")
            # A hand-edited nonsense value is Soft, without losing its neighbours.
            path.write_text(json.dumps({"config_version": 2, "design": "neon", "max_no_progress": 5}),
                            encoding="utf-8")
            loaded = settings.load(path)
            self.assertEqual((loaded["design"], loaded["max_no_progress"]), ("soft", 5))


def released_settings_module(tag: str, scratch: Path) -> Path:
    """The package exactly as a tagged release shipped it, extracted under `scratch`; its `src` folder.

    Skipped where the tag is not in the checkout, except on CI, which fetches the tags: there a missing
    tag is a failure, not a quiet skip (tests/test_control_v3.py, legacy_store_module)."""
    import io
    import os
    import subprocess
    import tarfile
    root = Path(__file__).resolve().parents[1]
    archive = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", tag, "src/codex_auto_resume"],
                             capture_output=True)
    if archive.returncode != 0:
        if os.environ.get("CI"):
            raise AssertionError("%s is not in this checkout; CI must fetch the tags" % tag)
        raise unittest.SkipTest("%s is not in this checkout" % tag)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(scratch, filter="data")
    return scratch / "src"


class StillFoldTests(unittest.TestCase):
    """v0.6.10's fourth design, Still, drew exactly what Soft draws under Reduce motion; since v0.6.11 it is Reduce
    motion. A stored Still reads as Soft with Reduce motion on, so its owner keeps the picture they chose; a
    request for it is refused, naming the designs there are, and every other refusal keeps v0.6.10's words; and
    what this version writes, v0.6.10 still reads as that picture.
    """

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.path = self.folder / "settings.json"

    def write(self, **values):
        self.path.write_text(json.dumps(dict({"config_version": 2}, **values)), encoding="utf-8")

    def test_a_stored_still_reads_as_soft_with_reduce_motion_on(self):
        for motion in (False, True, None, "yes"):
            with self.subTest(reduce_motion=motion):
                self.write(design="still", reduce_motion=motion, theme="dark", max_no_progress=5)
                loaded = settings.load(self.path)
                self.assertEqual((loaded["design"], loaded["reduce_motion"]), ("soft", True))
                self.assertEqual((loaded["theme"], loaded["max_no_progress"]), ("dark", 5), "its neighbours kept")
        self.write(design="still")                              # v0.6.10 wrote no Reduce motion beside it
        self.assertEqual((settings.load(self.path)["design"], settings.load(self.path)["reduce_motion"]),
                         ("soft", True))
        self.assertEqual(settings.design_preference({"design": "still"}), "soft")
        # A file with no version marker (v0.4's flat file, or one written by hand) keeps the picture too.
        self.path.write_text(json.dumps({"design": "still", "reduce_motion": False, "theme": "dark"}),
                             encoding="utf-8")
        loaded = settings.load(self.path)
        self.assertEqual((loaded["design"], loaded["reduce_motion"], loaded["theme"]), ("soft", True, "dark"))

    def test_the_next_save_writes_the_fold_and_nothing_else_changes(self):
        self.write(design="still", theme="light", notify_result=False)
        settings.update(self.path, {"theme": "dark"})
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((stored["design"], stored["reduce_motion"], stored["theme"], stored["notify_result"]),
                         ("soft", True, "dark", False))
        self.assertEqual(stored["config_version"], settings.CONFIG_VERSION)
        # And Reduce motion is an ordinary setting again from then on: turned off, it stays off.
        settings.update(self.path, {"reduce_motion": False})
        self.assertEqual((settings.load(self.path)["design"], settings.load(self.path)["reduce_motion"]),
                         ("soft", False))

    def test_other_designs_keep_their_reduce_motion(self):
        for design in settings.DESIGNS:
            with self.subTest(design):
                self.write(design=design, reduce_motion=False)
                self.assertEqual((settings.load(self.path)["design"], settings.load(self.path)["reduce_motion"]),
                                 (design, False))

    def test_asking_for_still_is_refused_with_the_choices_there_are(self):
        with self.assertRaises(settings.SettingsError) as caught:
            settings.validate_update({"design": "still"})
        self.assertEqual(str(caught.exception), "invalid value for design: expected one of soft, classic, plain")
        self.write(design="plain")
        before = self.path.read_bytes()
        with self.assertRaises(settings.SettingsError):
            settings.update(self.path, {"design": "still", "theme": "dark"})
        self.assertEqual(self.path.read_bytes(), before, "a refused write writes nothing")
        # Only the retired choice names the ones there are: every other refusal says what it said in v0.6.10.
        for change, said in (({"design": "neon"}, "invalid value for design"),
                             ({"theme": "sepia"}, "invalid value for theme"),
                             ({"retry_timing": "soon"}, "invalid value for retry_timing"),
                             ({"max_no_progress": 99}, "invalid value for max_no_progress")):
            with self.subTest(change):
                with self.assertRaises(settings.SettingsError) as caught:
                    settings.validate_update(change)
                self.assertEqual(str(caught.exception), said)

    def test_what_this_version_writes_for_a_stored_still_loads_in_v0_6_10_as_that_picture(self):
        """Going back to v0.6.10 after the fold loses nothing: its own settings.load, from its tag, in a process of
        its own, reads what this version wrote as Soft with Reduce motion on - the picture Still drew there."""
        import os
        import subprocess
        import sys
        self.write(design="still", theme="dark")
        settings.update(self.path, {"max_no_progress": 5})
        source = released_settings_module("v0.6.10", self.folder / "release")
        probe = ("import json, sys\n"
                 "from pathlib import Path\n"
                 "from codex_auto_resume import settings\n"
                 "values = settings.load(Path(sys.argv[1]))\n"
                 "print(json.dumps([values['design'], values['reduce_motion'], values['theme'],"
                 " values['max_no_progress'], list(settings.DESIGNS)]))\n")
        home = self.folder / "home"
        home.mkdir()
        environment = dict(os.environ, PYTHONPATH=str(source), **{name: str(home) for name in (
            "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "CODEX_HOME", "CODEX_AUTO_RESUME_HOME")})
        done = subprocess.run([sys.executable, "-c", probe, str(self.path)], capture_output=True, text=True,
                              encoding="utf-8", env=environment, cwd=str(self.folder))
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        design, motion, theme, limit, known = json.loads(done.stdout)
        self.assertIn("still", known, "the tag is v0.6.10, which had Still")
        self.assertEqual((design, motion, theme, limit), ("soft", True, "dark", 5))


class NotificationCardTests(unittest.TestCase):
    """v0.6.5: the card is a desktop preference beside the icon, on unless somebody turns it off."""

    def test_it_is_on_by_default_and_a_true_or_false(self):
        self.assertIs(settings.DEFAULTS["notification_card"], True)
        self.assertEqual(settings.field_type("notification_card"), "boolean")

    def test_it_is_described_in_the_windows_group_right_after_the_icon(self):
        described = settings.describe()
        names = [entry["name"] for entry in described]
        self.assertEqual(names.index("notification_card"), names.index("show_tray") + 1)
        entry = described[names.index("notification_card")]
        self.assertEqual(entry["group"], "windows")
        self.assertNotIn("master", entry)

    def test_now_that_the_icon_draws_the_card_the_switch_is_offered(self):
        """The watcher hands notices to the notifier and the icon's thread hosts the card (tests/
        test_notice_card.py SettingTests holds the two together), so describe() - which the
        Dashboard draws from - offers the switch. The value is kept across other saves and checked."""
        self.assertNotIn("notification_card", settings.NOT_YET_OFFERED)
        self.assertIn("notification_card", [entry["name"] for entry in settings.describe()])
        self.assertIs(settings.defaults()["notification_card"], True)
        self.assertEqual(settings.validate_update({"notification_card": False}), {"notification_card": False})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings.update(path, {"notification_card": False})
            settings.update(path, {"show_tray": True})
            self.assertIs(settings.load(path)["notification_card"], False, "kept across other saves")

    def test_writes_take_a_boolean_and_nothing_else(self):
        self.assertEqual(settings.validate_update({"notification_card": False}), {"notification_card": False})
        for value in (0, 1, "false", None, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update({"notification_card": value})

    def test_a_hand_edited_file_falls_back_to_on(self):
        for value in (0, "off", None, 2):
            with self.subTest(value=value):
                self.assertIs(settings.coerce({"notification_card": value})["notification_card"], True)
        self.assertIs(settings.coerce({"notification_card": False})["notification_card"], False)

    def test_turning_it_off_silences_nothing(self):
        # Where a notification is drawn is not whether there is one.
        values = dict(settings.defaults(), notification_card=False)
        for event in settings.NOTIFICATION_EVENTS:
            self.assertTrue(settings.notification_enabled(values, event), event)

    def test_it_round_trips_through_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings.update(path, {"notification_card": False})
            self.assertIs(settings.load(path)["notification_card"], False)
            self.assertIs(json.loads(path.read_text(encoding="utf-8"))["notification_card"], False)


class OfferedWithItsHelpTests(unittest.TestCase):
    """A setting that describe() offers, and whose catalogs carry a help line for it, is drawn in the
    Dashboard with that line under it. describe() is what puts a switch in the window, so emptying
    NOT_YET_OFFERED is what put the card's switch there - and the card's help line is where a person
    learns that Do not disturb, full screen, a screen reader, a locked or a remote session bring
    Windows' own notification back instead (PLAN v2 B-D7: the user is to be told)."""

    def test_every_offered_setting_with_a_help_line_is_drawn_with_it(self):
        from codex_auto_resume import l10n
        window = guiscan.settings()
        helps = l10n.catalog("en")
        missing = []
        for entry in settings.describe():
            key = "help." + entry["name"]
            if key in helps and ('"%s"' % key) not in window:
                missing.append(key)
        self.assertEqual(missing, [], "gui/SettingsPage.cs draws these switches without the help line the "
                                      "catalogs have for them; beside `if (name == \"reduce_motion\")` add "
                                      "`if (name == \"notification_card\") host.Controls.Add(HelpText(S("
                                      "\"help.notification_card\", ...)));`")


class WrongTypeTests(unittest.TestCase):
    """A value of the wrong type is refused, whatever it happens to equal.

    `validate_update` decided by comparing the coerced result with the value supplied:
    `if coerced != value: raise`. A coercer answers a value it does not like with the
    field's *default*, so whenever a wrong-typed value happened to equal that default the
    comparison saw nothing wrong and the write went through. The effect was per-field,
    because the default decides: `{"reduce_motion": 0}` was accepted (its default is
    False, and False == 0 in Python) while `{"notifications": 0}` was refused (its default
    is True); `{"max_no_progress": 3.0}` was accepted and `{"max_no_progress": 5.0}`
    refused. The same defect, opposite answers, and nothing outside could predict which.

    The table below is every field crossed with a value of every type the field does not
    publish - both the half whose coerced result equals the value supplied and the half
    whose does not - so neither can regress on its own. The published type is
    `describe()`'s, which is what the MCP schema and every window's editor are built from:
    what the schema will not offer, the validator will not take.
    """

    # One or two values of each JSON type, plus the two that are not JSON at all.
    OTHER = {"boolean": [True, False],
             "integer": [2, 7],
             "number": [2.5, 7.5],
             "string": ["", "7", "true"],
             "array": [[]],
             "object": [{}]}
    # What each published type accepts. A number takes an integer - JSON has one numeric
    # type, and a person who types 6 into a box that measures hours has given a number -
    # and nothing takes a boolean but a boolean, because `bool` is an `int` in Python and
    # is not one in JSON.
    ACCEPTS = {"boolean": {"boolean"}, "integer": {"integer"},
               "number": {"integer", "number"}, "string": {"string"}}

    def twins(self, entry):
        """The wrong-typed values that used to slip through for this field.

        The defect's signature: another type, and equal to the field's default anyway. A
        switch has two (0 and 0.0, or 1 and 1.0), a count has one (its default written as
        a float), and nothing of another type equals a string, an hour count of 6.0 or the
        `null` of a field that has no value - which is why the other half of the table
        matters just as much.
        """
        default = entry["default"]
        if isinstance(default, bool):
            return [int(default), float(default)]
        if isinstance(default, int):
            return [float(default)]
        return []

    def candidates(self, entry):
        """(type name, value) for everything this field should refuse."""
        found = [(kind, value) for kind in sorted(self.OTHER) for value in self.OTHER[kind]]
        for value in self.twins(entry):
            found.append(("integer" if isinstance(value, int) else "number", value))
        return [(kind, value) for kind, value in found
                if kind not in self.ACCEPTS[entry["type"]]]

    def test_a_value_of_a_type_the_schema_does_not_publish_is_refused(self):
        for entry in settings.describe():
            for kind, value in self.candidates(entry):
                with self.subTest(name=entry["name"], kind=kind, value=repr(value)):
                    with self.assertRaises(settings.SettingsError) as caught:
                        settings.validate_update({entry["name"]: value})
                    # The refusal names the field, because a Save sends many at once -
                    # unless the field has words of its own, which the custom messages do
                    # and which say more than the field name would.
                    if entry["name"] not in settings.EXPLAIN:
                        self.assertIn(entry["name"], str(caught.exception))

    def test_the_table_holds_both_halves_of_the_defect(self):
        """Without the first half this file would pass against the code that had the bug.

        `slipped` is the set of fields with a wrong-typed value whose coerced result
        equals the value supplied - the ones the old rule let through. It has to be
        exactly the switches and the counts, and it has to be non-empty, or the table
        above has quietly stopped exercising the defect.
        """
        slipped, refused = set(), set()
        for entry in settings.describe():
            default, coercer = settings.FIELDS[entry["name"]]
            for _kind, value in self.candidates(entry):
                side = slipped if coercer(value, default) == value else refused
                side.add(entry["name"])
        described = {entry["name"] for entry in settings.describe()}
        self.assertEqual(slipped, {entry["name"] for entry in settings.describe()
                                   if entry["type"] in ("boolean", "integer")})
        self.assertEqual(refused, described)
        self.assertTrue(slipped)

    def test_the_values_the_design_pass_named(self):
        # Stated one by one as well as by table, because these are the sentences the
        # report will be read against.
        for change in ({"reduce_motion": 0}, {"notifications": 0}, {"show_tray": 1},
                       {"max_no_progress": 3.0}, {"max_no_progress": 5.0},
                       {"max_recovery_attempts": 4.0}, {"max_chain_continuations": 6.0}):
            with self.subTest(change=change):
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update(change)

    def test_every_default_is_still_accepted_as_a_write(self):
        # The strongest statement that nothing was tightened past the schema: the whole
        # field set, written at once, in the types the product itself uses.
        self.assertEqual(settings.validate_update(settings.defaults()), settings.defaults())

    def test_an_integer_is_still_a_number(self):
        # What every window's spin box sends for the one field measured in hours.
        self.assertEqual(settings.validate_update({"detection_lookback_hours": 6}),
                         {"detection_lookback_hours": 6.0})
        self.assertEqual(settings.validate_update({"detection_lookback_hours": 6.5}),
                         {"detection_lookback_hours": 6.5})

    def test_clearing_is_allowed_exactly_where_it_was_allowed(self):
        # `null` is how a field that can have no value is emptied - the Codex path, and
        # each custom message. Every other field has a value, and null is not one.
        for name in sorted(settings.FIELDS):
            default, _coerce = settings.FIELDS[name]
            with self.subTest(name=name):
                if default is None:
                    self.assertEqual(settings.validate_update({name: None}), {name: None})
                else:
                    with self.assertRaises(settings.SettingsError):
                        settings.validate_update({name: None})

    def test_a_reading_still_falls_back_instead_of_refusing(self):
        # `coerce` is the file path and it is unchanged: a hand-edited settings.json with
        # a wrong type still starts the watcher on defaults rather than stopping it.
        for name, value in (("reduce_motion", 0), ("notifications", 0), ("max_no_progress", 3.0)):
            with self.subTest(name=name):
                self.assertEqual(settings.coerce({name: value})[name], settings.DEFAULTS[name])


if __name__ == "__main__":
    unittest.main()
