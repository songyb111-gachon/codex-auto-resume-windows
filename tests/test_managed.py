r"""v0.6.11: the standard edition's policy keys - read, never written, and only ever holding back.

An administrator's six values under Software\Policies\CodexAutoResume (managed.py) are read by
win/policykeys.py and applied after the settings are read and coerced, never to the file. Each one
restricts: a switch pauses recovery, forces Observe only, turns off the update check or the status
file; a number is a ceiling on the attempts; a window of quiet hours holds beside a person's own. A
value that is malformed is ignored. Nothing here reads this machine's registry: the reader is only
asked by an installed copy, the suite runs from a checkout (a test below holds that), and every
test that means to be managed stands in for the one function that asks.
"""
from __future__ import annotations

import ast
import itertools
import json
from pathlib import Path
import random
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import srcscan  # noqa: E402
from codex_auto_resume import config, control, diagnostics, managed, quiet, settings  # noqa: E402
from codex_auto_resume.control import policy as control_policy  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.win import policykeys  # noqa: E402
from test_control import ControlTestCase  # noqa: E402
from test_engine import EngineCase  # noqa: E402

DWORD, SZ = managed.REG_DWORD, managed.REG_SZ
NIGHT = {"quiet_hours_start": "22:00", "quiet_hours_end": "07:00", "quiet_hours_days": "every_day"}
MORNING = {"quiet_hours_start": "06:00", "quiet_hours_end": "09:00", "quiet_hours_days": "every_day"}


def held(**values) -> managed.Managed:
    return managed.Managed(**values)


def local(hour, minute=0, day=28):
    """A moment on this machine's own clock, on a day in September 2026."""
    return time.mktime((2026, 9, day, hour, minute, 0, 0, 0, -1))


# ------------------------------------------------------------------------------------ parsing
class ParseTests(unittest.TestCase):
    def test_no_key_is_nothing_held(self):
        for places in ([], [{}, {}], None):
            with self.subTest(places=places):
                self.assertEqual(managed.parse(places), managed.NONE)
        self.assertFalse(managed.NONE.active)
        self.assertEqual(managed.NONE.codes(), [])

    def test_each_switch_is_a_dword_that_is_not_zero(self):
        for name, attribute in ((managed.DISABLE_AUTO_RESUME, "disable_auto_resume"),
                                (managed.FORCE_OBSERVE_ONLY, "force_observe_only"),
                                (managed.DISABLE_UPDATE_CHECK, "disable_update_check"),
                                (managed.DISABLE_STATUS_FILE, "disable_status_file")):
            with self.subTest(name):
                self.assertTrue(getattr(managed.parse([{name: (1, DWORD)}]), attribute))
                self.assertTrue(getattr(managed.parse([{}, {name: (2, managed.REG_QWORD)}]), attribute))
                self.assertEqual(managed.parse([{name: (1, DWORD)}]).codes(), [name])
                self.assertFalse(getattr(managed.parse([{name: (0, DWORD)}]), attribute))

    def test_a_malformed_value_is_ignored(self):
        malformed = [{managed.DISABLE_AUTO_RESUME: ("1", SZ)}, {managed.FORCE_OBSERVE_ONLY: (True, DWORD)},
                     {managed.MAX_RECOVERY_ATTEMPTS: (0, DWORD)}, {managed.MAX_RECOVERY_ATTEMPTS: (21, DWORD)},
                     {managed.MAX_RECOVERY_ATTEMPTS: ("3", SZ)}, {managed.QUIET_HOURS: (2200, DWORD)},
                     {managed.QUIET_HOURS: ("22:15-07:00", SZ)}, {managed.QUIET_HOURS: ("22:00-22:00", SZ)},
                     {managed.QUIET_HOURS: ("22:00-07:00 mondays", SZ)}, {managed.QUIET_HOURS: ("night", SZ)},
                     {managed.QUIET_HOURS: ("25:00-07:00", SZ)}, {managed.DISABLE_UPDATE_CHECK: [1, DWORD]},
                     {managed.DISABLE_STATUS_FILE: (1,)}, "not a place", {"SomethingElse": (1, DWORD)}]
        for place in malformed:
            with self.subTest(place=place):
                self.assertEqual(managed.parse([place]), managed.NONE)

    def test_every_restriction_either_place_makes_holds(self):
        found = managed.parse([
            {managed.DISABLE_AUTO_RESUME: (1, DWORD), managed.MAX_RECOVERY_ATTEMPTS: (5, DWORD),
             managed.QUIET_HOURS: ("22:00-07:00", SZ)},
            {managed.FORCE_OBSERVE_ONLY: (1, DWORD), managed.MAX_RECOVERY_ATTEMPTS: (3, DWORD),
             managed.QUIET_HOURS: ("06:00 - 09:00 every_day", managed.REG_EXPAND_SZ)}])
        self.assertTrue(found.disable_auto_resume and found.force_observe_only)
        self.assertEqual(found.max_recovery_attempts, 3, "the lower ceiling is the ceiling")
        self.assertEqual(found.quiet_hours, (NIGHT, MORNING), "each place's quiet hours, the machine's first")
        self.assertEqual(found.codes(), [managed.DISABLE_AUTO_RESUME, managed.FORCE_OBSERVE_ONLY,
                                         managed.MAX_RECOVERY_ATTEMPTS, managed.QUIET_HOURS])

    def test_quiet_hours_take_the_days_by_their_closed_word(self):
        self.assertEqual(managed.quiet_window("23:30-06:00 weekdays"),
                         {"quiet_hours_start": "23:30", "quiet_hours_end": "06:00", "quiet_hours_days": "weekdays"})
        self.assertEqual(managed.quiet_window(" 09:00-17:30 "),
                         {"quiet_hours_start": "09:00", "quiet_hours_end": "17:30", "quiet_hours_days": "every_day"})
        self.assertIsNone(managed.quiet_window(None))

    def test_the_reader_asks_for_exactly_the_values_this_reads(self):
        self.assertEqual(policykeys.NAMES, managed.VALUES)
        self.assertEqual(policykeys.KEY, managed.KEY)
        self.assertEqual(managed.KEY, r"Software\Policies\CodexAutoResume")


# ---------------------------------------------------------------------------------- clamping
class ClampTests(unittest.TestCase):
    def test_with_no_key_the_settings_are_the_ones_read(self):
        values = settings.defaults()
        self.assertIs(managed.clamp(values, managed.NONE), values)
        self.assertEqual(managed.fields(managed.NONE), frozenset())
        self.assertEqual(managed.admit({"max_recovery_attempts": 9}, values, managed.NONE),
                         ({"max_recovery_attempts": 9}, None))

    def test_each_key_holds_its_settings_and_no_other(self):
        values = dict(settings.defaults(), max_recovery_attempts=9, quiet_hours_start="12:00")
        clamped = managed.clamp(values, held(force_observe_only=True, max_recovery_attempts=3,
                                             quiet_hours=(MORNING,), disable_auto_resume=True))
        self.assertIs(clamped["observe_only"], True)
        self.assertEqual(clamped["max_recovery_attempts"], 3)
        self.assertEqual({name: clamped[name] for name in MORNING}, MORNING)
        untouched = set(settings.FIELDS) - {"observe_only", "max_recovery_attempts", *MORNING}
        self.assertEqual({name: clamped[name] for name in untouched}, {name: values[name] for name in untouched})
        self.assertEqual(values["max_recovery_attempts"], 9, "the settings read are not changed")

    def test_a_ceiling_never_raises_what_a_person_chose(self):
        self.assertEqual(managed.clamp(dict(settings.defaults(), max_recovery_attempts=2),
                                       held(max_recovery_attempts=5))["max_recovery_attempts"], 2)

    def test_the_status_file_is_held_off_once_it_is_a_setting(self):
        self.assertEqual(managed.fields(held(disable_status_file=True)), frozenset(),
                         "until item 17 adds the setting, DisableStatusFile holds nothing back")
        fields = dict(settings.FIELDS, status_file=(False, settings._boolean))
        with patch.object(settings, "FIELDS", fields), \
                patch.object(settings, "DEFAULTS", dict(settings.DEFAULTS, status_file=False)):
            self.assertEqual(managed.fields(held(disable_status_file=True)), frozenset({"status_file"}))
            clamped = managed.clamp(dict(settings.DEFAULTS, status_file=True), held(disable_status_file=True))
            self.assertIs(clamped["status_file"], False)

    def test_settings_after_the_keys_are_never_less_restrictive_than_before(self):
        """The property the design asks for, over many settings and every combination of keys."""
        drawn = random.Random(611)
        windows = [None, NIGHT, MORNING, {"quiet_hours_start": "13:00", "quiet_hours_end": "14:30",
                                          "quiet_hours_days": "weekdays"}]
        moments = [local(hour, minute, day) for day in (26, 27, 28) for hour in range(24) for minute in (0, 45)]
        engine = types.SimpleNamespace()
        from codex_auto_resume.engine.options import OptionsMixin
        for _ in range(120):
            raw = {"observe_only": drawn.choice([True, False]),
                   "max_recovery_attempts": drawn.randint(1, 20)}
            own = drawn.choice(windows)
            if own:
                raw.update(own)
            own_values = settings.coerce(raw)
            keys = held(force_observe_only=drawn.choice([True, False]),
                        max_recovery_attempts=drawn.choice([None, drawn.randint(1, 20)]),
                        quiet_hours=tuple(window for window in drawn.sample(windows[1:], drawn.randint(0, 2))),
                        disable_auto_resume=drawn.choice([True, False]))
            clamped = managed.clamp(own_values, keys)
            self.assertGreaterEqual(clamped["observe_only"], own_values["observe_only"])
            self.assertLessEqual(clamped["max_recovery_attempts"], own_values["max_recovery_attempts"])
            if keys.max_recovery_attempts is not None:
                self.assertLessEqual(clamped["max_recovery_attempts"], keys.max_recovery_attempts)
            # Quiet hours as the engine asks them: never ending sooner than the person's own did.
            engine.policy_values, engine._more_quiet = clamped, (
                managed.quiet_sources(own_values, keys) if keys.quiet_hours else ())
            for moment in moments:
                before = quiet.quiet_until(moment, own_values)
                after = OptionsMixin.quiet_until(engine, moment)
                if before is not None:
                    self.assertIsNotNone(after)
                    self.assertGreaterEqual(after, before)
                for window in keys.quiet_hours:
                    theirs = quiet.quiet_until(moment, window)
                    if theirs is not None:
                        self.assertGreaterEqual(after, theirs)

    def test_a_write_keeps_what_a_key_says_out_of_the_file_and_refuses_what_it_forbids(self):
        keys = held(force_observe_only=True, max_recovery_attempts=4, quiet_hours=(NIGHT,))
        effective = managed.clamp(dict(settings.defaults(), max_recovery_attempts=3), keys)
        everything = dict(effective)
        kept, refused = managed.admit(everything, effective, keys)
        self.assertIsNone(refused)
        self.assertEqual(set(everything) - set(kept), {"observe_only", *NIGHT, "max_recovery_attempts"},
                         "what the page shows of a managed setting is never written")
        self.assertEqual(managed.admit({"max_recovery_attempts": 2}, effective, keys),
                         ({"max_recovery_attempts": 2}, None))
        self.assertEqual(managed.admit({"max_recovery_attempts": 4}, effective, keys),
                         ({"max_recovery_attempts": 4}, None), "within the ceiling is the person's")
        for loosening in ({"max_recovery_attempts": 5}, {"observe_only": False},
                          {"quiet_hours_start": "off"}, {"quiet_hours_days": "weekends"}):
            with self.subTest(loosening):
                self.assertEqual(managed.admit(loosening, effective, keys)[1], next(iter(loosening)))


# ---------------------------------------------------------------------------------- the reader
class FakeRegistry:
    """HKEY_LOCAL_MACHINE and HKEY_CURRENT_USER, each a mapping of key path to values, read only."""
    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER = "HKLM", "HKCU"
    KEY_READ, KEY_WOW64_64KEY = 0x20019, 0x0100

    def __init__(self, places):
        self.places, self.opened = places, []

    def OpenKey(self, root, path, reserved, access):
        self.opened.append((root, path, access))
        if path not in self.places.get(root, {}):
            raise FileNotFoundError(path)
        values = self.places[root][path]

        class Key:
            def __enter__(self_inner):
                return values

            def __exit__(self_inner, *_):
                return False
        return Key()

    @staticmethod
    def QueryValueEx(values, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name]

    def __getattr__(self, name):
        raise AssertionError("the reader asked the registry for %s" % name)


class ReaderTests(unittest.TestCase):
    def test_both_places_are_read_for_the_six_values_alone_and_opened_for_reading(self):
        registry = FakeRegistry({
            "HKLM": {managed.KEY: {"DisableAutoResume": (1, DWORD), "Unrelated": (5, DWORD)}},
            "HKCU": {managed.KEY: {"QuietHours": ("22:00-07:00", SZ)}}})
        with patch.object(policykeys, "_winreg", return_value=registry):
            places = policykeys.read()
        self.assertEqual(places, [{"DisableAutoResume": (1, DWORD)}, {"QuietHours": ("22:00-07:00", SZ)}])
        self.assertEqual([(root, path) for root, path, _ in registry.opened],
                         [("HKLM", managed.KEY), ("HKCU", managed.KEY)])
        self.assertTrue(all(access == registry.KEY_READ | registry.KEY_WOW64_64KEY
                            for _, _, access in registry.opened))

    def test_no_key_anywhere_and_no_registry_are_empty_answers(self):
        with patch.object(policykeys, "_winreg", return_value=FakeRegistry({})):
            self.assertEqual(policykeys.read(), [{}, {}])
        with patch.object(policykeys, "_winreg", return_value=None):
            self.assertEqual(policykeys.read(), [])

    def test_a_checkout_never_asks_this_machines_registry(self):
        """What keeps the suite off the registry: the reader is asked by an installed copy only."""
        self.assertIsNone(config.installed_home(), "the suite runs from a checkout")

        def refuse():
            raise AssertionError("the real registry was asked")
        with patch.object(policykeys, "read", side_effect=refuse), \
                patch.object(policykeys, "_winreg", side_effect=refuse):
            self.assertEqual(control_policy.managed_policy(), managed.NONE)

    def test_an_installed_copy_asks_and_is_held(self):
        with patch.object(config, "installed_home", return_value=r"C:\Users\ExampleUser\.codex-auto-resume"), \
                patch.object(policykeys, "read", return_value=[{"ForceObserveOnly": (1, DWORD)}, {}]):
            self.assertEqual(control_policy.managed_policy(), held(force_observe_only=True))

    def test_only_startup_writes_the_registry_and_only_three_modules_read_it(self):
        writers = {"CreateKey", "CreateKeyEx", "SetValue", "SetValueEx", "DeleteKey", "DeleteKeyEx",
                   "DeleteValue", "SaveKey", "LoadKey", "RestoreKey"}
        written, importers = set(), set()
        for name, path in srcscan.modules().items():
            tree = srcscan.package_asts()[path]
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in writers and \
                        isinstance(node.value, ast.Name) and node.value.id == "winreg":
                    written.add(name)
                if isinstance(node, ast.Import) and any(alias.name == "winreg" for alias in node.names):
                    importers.add(name)
        package = srcscan.PACKAGE
        self.assertEqual(written, {package + ".startup"})
        self.assertEqual(importers, {package + ".startup", package + ".tray_place", package + ".win.policykeys"})


# ------------------------------------------------------------------------------ control layer
class ManagedControlTests(ControlTestCase):
    def manage(self, **values):
        stand_in = patch.object(control_policy, "managed_policy", return_value=held(**values))
        stand_in.start()
        self.addCleanup(stand_in.stop)

    def stored(self) -> dict:
        return json.loads(self.paths.settings_file.read_text(encoding="utf-8"))

    def test_with_no_key_everything_is_what_it_was(self):
        self.assertEqual(self.control.describe_settings(), settings.describe())
        self.assertEqual(self.control.get_settings(), settings.defaults())
        self.assertNotIn("managed", self.control.get_status())

    def test_the_settings_are_shown_held_and_the_file_keeps_the_persons_own(self):
        self.control.update_settings({"max_recovery_attempts": 9})
        self.manage(max_recovery_attempts=3, force_observe_only=True, quiet_hours=(NIGHT,))
        shown = self.control.get_settings()
        self.assertEqual((shown["max_recovery_attempts"], shown["observe_only"]), (3, True))
        self.assertEqual({name: shown[name] for name in NIGHT}, NIGHT)
        # The window sends every value back; what a key says is never written over the person's own.
        saved = self.control.update_settings(dict(shown, notifications=False))
        self.assertEqual(saved["max_recovery_attempts"], 3)
        stored = self.stored()
        self.assertEqual((stored["max_recovery_attempts"], stored["observe_only"], stored["quiet_hours_start"],
                          stored["notifications"]), (9, False, "off", False))
        with Store(self.paths.state_dir) as store:
            self.assertTrue(store.settings()["observe_only"], "the claim's own switch is written too")

    def test_a_write_that_would_loosen_a_key_is_refused_with_its_code(self):
        self.manage(max_recovery_attempts=3, force_observe_only=True)
        for change in ({"max_recovery_attempts": 4}, {"observe_only": False}):
            with self.subTest(change), self.assertRaises(control.ControlError) as caught:
                self.control.update_settings(change)
            self.assertEqual(caught.exception.code, "managed_by_policy")
        self.assertFalse(self.paths.settings_file.exists(), "nothing was written")
        self.assertEqual(self.control.update_settings({"max_recovery_attempts": 2})["max_recovery_attempts"], 2)
        with self.assertRaises(control.ControlError) as caught:
            self.control.update_settings({"max_recovery_attempts": "3"})
        self.assertEqual(caught.exception.code, "request_failed", "a wrong value is refused as ever")

    def test_disable_auto_resume_is_a_pause_nobody_here_can_lift(self):
        with Store(self.paths.state_dir) as store:
            store.set_enabled(True, 100.0)
        self.manage(disable_auto_resume=True)
        status = self.control.get_status()
        self.assertIs(status["enabled"], False)
        self.assertEqual(status["managed"], ["DisableAutoResume"])
        with self.assertRaises(control.ControlError) as caught:
            self.control.set_enabled(True)
        self.assertEqual(caught.exception.code, "managed_by_policy")
        self.assertEqual(self.control.set_enabled(False), {"enabled": False})

    def test_the_schema_marks_what_a_key_decides(self):
        self.manage(max_recovery_attempts=3, quiet_hours=(NIGHT,), disable_update_check=True)
        marked = {entry["name"] for entry in self.control.describe_settings() if entry.get("managed")}
        self.assertEqual(marked, {"max_recovery_attempts", *NIGHT})
        self.assertEqual(self.control.get_status()["managed"],
                         ["DisableUpdateCheck", "MaxRecoveryAttempts", "QuietHours"])

    def test_restore_defaults_is_still_held(self):
        self.manage(force_observe_only=True)
        self.assertIs(self.control.restore_defaults()["observe_only"], True)
        self.assertIs(self.stored()["observe_only"], False)

    def test_diagnostics_name_the_keys_and_no_value(self):
        self.assertNotIn("managed", diagnostics.collect(self.control)["status"])
        self.manage(max_recovery_attempts=3, quiet_hours=(NIGHT,))
        bundle = diagnostics.collect(self.control)
        self.assertEqual(bundle["status"]["managed"], ["MaxRecoveryAttempts", "QuietHours"])
        self.assertNotIn("22:00-07:00", json.dumps(bundle["status"]))


# ------------------------------------------------------------------------------------ the engine
class ManagedEngineTests(EngineCase):
    def test_with_no_key_the_engine_adopts_exactly_what_it_did(self):
        values = dict(settings.defaults(), max_recovery_attempts=7, quiet_hours_start="22:00")
        self.h.engine.apply_policy(values)
        before = (dict(self.h.engine.options), dict(self.h.engine.policy_values))
        self.h.engine.apply_policy(values, managed.NONE)
        self.assertEqual((dict(self.h.engine.options), dict(self.h.engine.policy_values)), before)
        self.assertEqual(self.h.engine._more_quiet, ())

    def test_disable_auto_resume_sends_nothing_even_before_the_pause_is_written(self):
        self.h.engine.apply_policy(settings.defaults(), held(disable_auto_resume=True))
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertTrue(self.h.store.settings()["enabled"], "the state's own switch was left to the watcher")

    def test_force_observe_only_sends_nothing_and_says_what_would_have_gone(self):
        self.h.engine.apply_policy(settings.defaults(), held(force_observe_only=True))
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertIn("would_send", self.h.codes())

    def test_the_ceiling_is_the_engines_limit(self):
        self.h.engine.apply_policy(dict(settings.defaults(), max_recovery_attempts=9),
                                   held(max_recovery_attempts=2))
        self.assertEqual(self.h.engine.limits()["max_recovery_attempts"], 2)

    def test_quiet_hours_hold_until_the_latest_window_ends(self):
        self.h.engine.apply_policy(dict(settings.defaults(), **NIGHT), held(quiet_hours=(MORNING,)))
        self.assertEqual(self.h.engine.quiet_until(local(6, 30)), local(9, 0), "the administrator's is later")
        self.assertEqual(self.h.engine.quiet_until(local(23, 0)), local(7, 0, day=29), "the person's own holds")
        self.assertIsNone(self.h.engine.quiet_until(local(12, 0)))
        self.h.engine.apply_policy(settings.defaults(), held(quiet_hours=(MORNING,)))
        self.assertEqual(self.h.engine.quiet_until(local(6, 30)), local(9, 0))


# ------------------------------------------------------------------------------------ the watcher
class ManagedWatcherTests(ControlTestCase):
    def app(self, keys):
        from codex_auto_resume import app
        with patch.object(control_policy, "managed_policy", return_value=keys):
            return app.App(self.paths, codex_home=self.home / "codex-home", enable_logging=False)

    def test_the_watcher_works_from_the_held_settings_and_writes_the_pause(self):
        settings.update(self.paths.settings_file, {"max_recovery_attempts": 9})
        with Store(self.paths.state_dir) as store:
            store.set_enabled(True, 100.0)
            keys = held(disable_auto_resume=True, max_recovery_attempts=3)
            instance = self.app(keys)
            self.assertEqual(instance.settings["max_recovery_attempts"], 3)
            engine = types.SimpleNamespace(store=store)
            instance._managed_pause(engine)
            self.assertFalse(store.settings()["enabled"])
            store.set_enabled(True, 200.0)
            instance._settings_stamp_seen = instance._settings_stamp()
            with patch.object(control_policy, "managed_policy", return_value=keys):
                self.assertFalse(instance.refresh_settings(engine))
            self.assertFalse(store.settings()["enabled"], "made good before every tick")

    def test_a_key_that_comes_or_goes_is_taken_up_without_a_change_to_the_file(self):
        adopted = []
        with Store(self.paths.state_dir) as store:
            instance = self.app(managed.NONE)
            engine = types.SimpleNamespace(store=store, apply_policy=lambda values, keys=None: adopted.append(keys))
            instance._settings_stamp_seen = instance._settings_stamp()
            with patch.object(control_policy, "managed_policy", return_value=managed.NONE):
                self.assertFalse(instance.refresh_settings(engine))
            keys = held(force_observe_only=True)
            with patch.object(control_policy, "managed_policy", return_value=keys):
                self.assertTrue(instance.refresh_settings(engine))
            self.assertEqual(adopted, [keys])
            self.assertIs(instance.settings["observe_only"], True)
            self.assertTrue(store.settings()["observe_only"])
            with patch.object(control_policy, "managed_policy", return_value=managed.NONE):
                self.assertTrue(instance.refresh_settings(engine))
            self.assertIs(instance.settings["observe_only"], False)
            self.assertFalse(store.settings()["observe_only"])


class ManagedStringsTests(unittest.TestCase):
    def test_every_surface_says_it_in_the_same_words(self):
        from codex_auto_resume import l10n
        english = json.loads((Path(l10n.__file__).parent / "locales" / "en.json").read_text(encoding="utf-8"))
        root = Path(_HERE).parent
        for key in ("settings.managed", "overview.off_managed", "overview.managed", "diag.update_managed",
                    "error.managed_by_policy"):
            self.assertIn(key, english)
        window = "".join(path.read_text(encoding="utf-8") for path in (root / "gui").glob("*.cs"))
        panel = (root / "src" / "codex_auto_resume" / "mcp" / "assets" / "panel.js").read_text(encoding="utf-8")
        for key in ("settings.managed", "overview.off_managed", "overview.managed", "diag.update_managed"):
            self.assertIn('S("%s", "%s"' % (key, english[key]), window)
        self.assertIn("t('settings.managed', '%s')" % english["settings.managed"], panel)


if __name__ == "__main__":
    unittest.main()
