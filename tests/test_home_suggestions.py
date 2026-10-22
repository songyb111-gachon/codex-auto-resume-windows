"""The Dashboard finds a Codex home this PC's Codex uses that is not watched yet, and suggests it (v0.6.18).

Where it looks, and nowhere else: the account's CODEX_HOME as Windows holds it (HKEY_CURRENT_USER\\Environment,
read only - win/userenv.py) and the Codex app's own list of where it ran (chrome-native-hosts-v2.json under
LOCALAPPDATA, each entry's paths.codexHome alone). Only an installed copy looks; a checkout - this suite - finds
nothing unless a test stands in for `homefind.looks`. A folder is offered only if the product could watch it,
it is neither the default home nor one added (by key and by folder identity), and it was not set aside with
Not now. Add is the one way a home is added (Control.update_settings, homes.strict: at most three); with three
added the offer says so instead. A switch turns the looking off.

Never the real registry and never the real Codex home: the registry is a stand-in, every folder is a scratch one
and CODEX_HOME points at a scratch folder for every test that asks the default home.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import config, control, controlcli, diagnostics, homefind, homes, settings  # noqa: E402
from codex_auto_resume.control import ControlError  # noqa: E402
from codex_auto_resume.win import userenv  # noqa: E402


class FakeRegistry:
    """winreg as win/userenv.py uses it: HKEY_CURRENT_USER\\Environment holding `values` {name: (data, type)}."""
    HKEY_CURRENT_USER = object()
    KEY_READ = 0x20019
    KEY_SET_VALUE = 0x0002
    REG_SZ, REG_EXPAND_SZ, REG_DWORD = 1, 2, 4

    def __init__(self, values=None, *, missing_key=False, denied=False):
        self.values = dict(values or {})
        self.missing_key, self.denied = missing_key, denied
        self.opened = []

    def OpenKey(self, root, name, reserved, access):  # noqa: N802 - winreg's own name
        self.opened.append((root, name, access))
        if self.missing_key:
            raise FileNotFoundError(name)
        if self.denied:
            raise PermissionError(name)
        registry = self

        class Key:
            def __enter__(self):
                return registry

            def __exit__(self, *_exc):
                return False
        return Key()

    def QueryValueEx(self, _key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    @staticmethod
    def ExpandEnvironmentStrings(text):  # noqa: N802
        return text.replace("%USERPROFILE%", "C:\\Users\\ExampleUser")


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.default = self.codex_home("default")
        environment = patch.dict(os.environ, {"CODEX_HOME": str(self.default)})
        environment.start()
        self.addCleanup(environment.stop)

    def codex_home(self, name):
        folder = self.root / name
        folder.mkdir(parents=True)
        (folder / "state_5.sqlite").write_bytes(b"")
        return folder


class EnvironmentTests(unittest.TestCase):
    def test_the_accounts_codex_home_is_read_for_reading_alone(self):
        registry = FakeRegistry({"CODEX_HOME": ("D:\\codex-work", FakeRegistry.REG_SZ)})
        self.assertEqual(userenv.codex_home(registry), "D:\\codex-work")
        self.assertEqual(registry.opened, [(FakeRegistry.HKEY_CURRENT_USER, "Environment", FakeRegistry.KEY_READ)])

    def test_a_value_to_expand_is_expanded_as_windows_would(self):
        registry = FakeRegistry({"CODEX_HOME": ("%USERPROFILE%\\.codex-two", FakeRegistry.REG_EXPAND_SZ)})
        self.assertEqual(userenv.codex_home(registry), "C:\\Users\\ExampleUser\\.codex-two")

    def test_nothing_there_unreadable_or_of_another_type_is_no_answer(self):
        for registry in (FakeRegistry(), FakeRegistry(missing_key=True), FakeRegistry(denied=True),
                         FakeRegistry({"CODEX_HOME": (7, FakeRegistry.REG_DWORD)}),
                         FakeRegistry({"CODEX_HOME": ("   ", FakeRegistry.REG_SZ)})):
            with self.subTest(registry.values):
                self.assertIsNone(userenv.codex_home(registry))


class AppFileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.local = Path(folder.name)

    def write(self, document, *, packaged=False):
        place = self.local.joinpath(*(homefind.APP_PACKAGE if packaged else ()), *homefind.APP_FILE)
        place.parent.mkdir(parents=True, exist_ok=True)
        place.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")
        return place

    def test_only_each_entrys_codex_home_is_kept(self):
        self.write({"schemaVersion": 2, "entries": [
            {"installId": "secret-install", "presence": {"pid": 4242}, "proxyPort": 9,
             "paths": {"codexHome": "D:\\one", "nodePath": "C:\\node.exe"}},
            {"paths": {"codexHome": "D:\\two"}}, {"paths": {}}, "not an entry"]})
        self.assertEqual(homefind.app_homes(str(self.local)), ["D:\\one", "D:\\two"])

    def test_the_apps_package_folder_is_read_when_the_plain_one_is_not_there(self):
        self.write({"entries": [{"paths": {"codexHome": "D:\\packaged"}}]}, packaged=True)
        self.assertEqual(homefind.app_homes(str(self.local)), ["D:\\packaged"])

    def test_too_big_not_json_or_another_shape_answers_nothing(self):
        # Too big: a whole, valid list followed by more than the cap allows - never read in part and believed.
        too_big = json.dumps({"entries": [{"paths": {"codexHome": "D:\\big"}}]}) + " " * homefind.APP_FILE_MAX
        for document in (too_big, "not json", '{"entries": 3}', "[1]"):
            with self.subTest(document[:20]):
                self.write(document)
                self.assertEqual(homefind.app_homes(str(self.local)), [])
        self.assertEqual(homefind.app_homes(str(self.local / "nowhere")), [])


class FoundTests(unittest.TestCase):
    def test_a_checkout_looks_nowhere(self):
        def never():
            raise AssertionError("a checkout asked a place")
        self.assertIsNone(config.installed_home())
        self.assertEqual(homefind.found(never, never, installed=config.installed_home()), [])

    def test_the_variable_first_then_the_app_each_folder_once(self):
        with patch.object(homefind, "looks", return_value=True):
            named = homefind.found(lambda: "D:\\Work\\", lambda: ["d:\\work", "E:\\other", None, " "])
        self.assertEqual(named, ["D:\\Work", "E:\\other"])

    def test_each_place_is_asked_when_looked_up(self):
        with patch.object(homefind, "looks", return_value=True), \
                patch.object(homefind, "app_homes", return_value=["E:\\app"]):
            self.assertEqual(homefind.found(), ["E:\\app"])


class CandidateTests(Case):
    def offer(self, values, named, identity=None):
        return homefind.offer(values, self.default, named, identity)

    def test_a_codex_home_not_watched_is_offered(self):
        other = self.codex_home("other")
        self.assertEqual(self.offer({}, [str(other)]), {"on": True, "path": str(other), "full": False})

    def test_only_a_folder_the_product_could_watch(self):
        empty = self.root / "empty"
        empty.mkdir()
        named = [str(empty), str(self.root / "nowhere"), "\\\\server\\share\\codex", "relative\\codex", ""]
        self.assertIsNone(self.offer({}, named)["path"])

    def test_never_the_default_home_or_one_added_however_spelled(self):
        work = self.codex_home("work")
        values = {homes.FIELD: [{"path": str(work), "alias": "Work"}]}
        named = [str(self.default).upper() + "\\", str(work).lower(), str(work) + "\\.\\"]
        self.assertIsNone(self.offer(values, named)["path"])

    def test_never_the_same_folder_by_identity(self):
        twin = self.codex_home("twin")
        self.assertIsNone(self.offer({}, [str(twin)], identity=lambda path: "one-folder")["path"])
        self.assertEqual(self.offer({}, [str(twin)], identity=lambda path: str(path))["path"], str(twin))

    def test_never_a_folder_set_aside(self):
        other = self.codex_home("other")
        values = {homefind.DISMISSED: [str(other).upper()]}
        self.assertIsNone(self.offer(values, [str(other)])["path"])

    def test_the_switch_off_looks_at_nothing(self):
        other = self.codex_home("other")
        self.assertEqual(self.offer({homefind.SWITCH: False}, [str(other)]), {"on": False, "path": None, "full": False})

    def test_with_every_home_added_it_says_so(self):
        added = [{"path": str(self.codex_home("h%d" % n)), "alias": "h%d" % n} for n in range(homes.MAX_EXTRA)]
        other = self.codex_home("other")
        self.assertEqual(self.offer({homes.FIELD: added}, [str(other)]), {"on": True, "path": str(other), "full": True})

    def test_not_now_remembers_each_folder_once_and_the_newest(self):
        kept = homefind.dismissed_with(["C:\\a"], "c:\\A\\")
        self.assertEqual(kept, ["c:\\A"])
        many = []
        for n in range(homefind.DISMISSED_MAX + 3):
            many = homefind.dismissed_with(many, "C:\\h%d" % n)
        self.assertEqual(len(many), homefind.DISMISSED_MAX)
        self.assertEqual(many[-1], "C:\\h%d" % (homefind.DISMISSED_MAX + 2))
        self.assertEqual(many[0], "C:\\h3")


class SettingsTests(Case):
    def test_on_by_default_none_set_aside_and_both_the_dashboards_alone(self):
        defaults = settings.defaults()
        self.assertIs(defaults[homefind.SWITCH], True)
        self.assertEqual(defaults[homefind.DISMISSED], [])
        described = {entry["name"] for entry in settings.describe()}
        for name in (homefind.SWITCH, homefind.DISMISSED):
            self.assertIn(name, settings.DASHBOARD_ONLY)
            self.assertNotIn(name, described)

    def test_a_stored_file_without_them_or_in_another_shape_reads_as_the_defaults(self):
        paths = config.Paths(self.root / "product")
        paths.ensure()
        for stored in ({}, {homefind.SWITCH: "yes", homefind.DISMISSED: "C:\\a"},
                       {homefind.DISMISSED: ["C:\\a", "c:\\A"]}, {homefind.DISMISSED: ["relative"]}):
            with self.subTest(stored):
                paths.settings_file.write_text(json.dumps(dict(stored, config_version=settings.CONFIG_VERSION)),
                                               encoding="utf-8")
                loaded = settings.load(paths.settings_file)
                self.assertIs(loaded[homefind.SWITCH], True)
                self.assertEqual(loaded[homefind.DISMISSED], [])

    def test_codex_is_never_told_a_folder_set_aside_and_cannot_write_either(self):
        from codex_auto_resume.mcp import server, tools
        reply = server._no_homes({"settings": {homefind.DISMISSED: ["C:\\Users\\ExampleUser\\x"],
                                               homefind.SWITCH: True, "notifications": True}})
        self.assertEqual(reply, {"settings": {"notifications": True}})
        self.assertNotIn(homefind.SWITCH, tools.settings_schema()["properties"])

    def test_a_diagnostics_file_counts_the_folders_set_aside_and_never_names_them(self):
        paths = config.Paths(self.root / "product")
        paths.ensure()
        layer = control.Control(paths)
        aside = self.codex_home("Users\\ExampleUser\\codex-aside")
        layer.update_settings({homefind.DISMISSED: [str(aside)]})
        with patch.object(control.Control, "watcher_running", return_value=False), \
                patch.object(control.Control, "startup_enabled", return_value=False):
            text = diagnostics.write(layer, self.root / "out" / "d.json").read_text(encoding="utf-8")
        self.assertNotIn("codex-aside", text)
        self.assertEqual(json.loads(text)["settings"][homefind.DISMISSED], 1)


class ControlTests(Case):
    """Through the control layer and the bridge, as the Dashboard asks: one folder found by the account's variable."""

    def setUp(self):
        super().setUp()
        self.paths = config.Paths(self.root / "product")
        self.paths.ensure()
        self.control = control.Control(self.paths)
        self.other = self.codex_home("other")
        for target, name, value in ((homefind, "looks", True), (userenv, "codex_home", str(self.other)),
                                    (homefind, "app_homes", []), (control.Control, "watcher_running", True),
                                    (control.Control, "startup_enabled", False)):
            patcher = patch.object(target, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ask(self, command, argument=None):
        return controlcli.dispatch(self.control, command, argument if argument is not None else {})

    def test_the_bridge_offers_it_and_adds_nothing(self):
        self.assertEqual(self.ask("home-suggestion"),
                         {"ok": True, "result": {"on": True, "path": str(self.other), "full": False}})
        self.assertEqual(settings.load(self.paths.settings_file)[homes.FIELD], [])

    def test_add_goes_through_the_one_add_path_and_is_then_not_offered(self):
        path = self.control.home_suggestion()["path"]
        self.control.update_settings({homes.FIELD: [{"path": path, "alias": "other"}]})
        self.assertIsNone(self.control.home_suggestion()["path"])

    def test_not_now_sets_it_aside_for_good(self):
        self.assertEqual(self.ask("home-dismiss", {"path": str(self.other)})["result"]["path"], None)
        self.assertEqual(settings.load(self.paths.settings_file)[homefind.DISMISSED], [str(self.other)])
        self.assertIsNone(self.control.home_suggestion()["path"])
        with self.assertRaises(ControlError):
            self.control.dismiss_home_suggestion(None)

    def test_three_added_it_says_so_and_a_fourth_is_refused(self):
        added = [{"path": str(self.codex_home("h%d" % n)), "alias": "h%d" % n} for n in range(homes.MAX_EXTRA)]
        self.control.update_settings({homes.FIELD: added})
        self.assertEqual(self.control.home_suggestion(), {"on": True, "path": str(self.other), "full": True})
        with self.assertRaises(ControlError):
            self.control.update_settings({homes.FIELD: added + [{"path": str(self.other), "alias": "other"}]})

    def test_the_switch_turns_the_looking_off(self):
        self.control.update_settings({homefind.SWITCH: False})
        with patch.object(homefind, "found", side_effect=AssertionError("looked while off")):
            self.assertEqual(self.ask("home-suggestion")["result"], {"on": False, "path": None, "full": False})


if __name__ == "__main__":
    unittest.main()
