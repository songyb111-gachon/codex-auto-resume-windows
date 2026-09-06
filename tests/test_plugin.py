"""Plugin packaging, locale and control-layer tests.

These never install a plugin into the user's real Codex home, never register real
autostart, and never send anything to a Codex conversation.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import messages, startup

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
SKILL = ROOT / "skills" / "codex-auto-resume" / "SKILL.md"
PLUGIN_NAME = "codex-auto-resume"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManifestTests(unittest.TestCase):
    """The shapes Codex's own plugin validator accepts; see docs/PLUGIN.md."""

    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))

    def test_manifest_uses_only_accepted_top_level_fields(self):
        accepted = {"id", "name", "version", "description", "skills", "apps", "mcpServers",
                    "interface", "author", "homepage", "repository", "license", "keywords"}
        self.assertEqual(set(self.manifest) - accepted, set())

    def test_manifest_declares_no_hooks(self):
        # Codex plugin validation rejects `hooks`; shipping it would fail installation.
        self.assertNotIn("hooks", self.manifest)

    def test_manifest_declares_no_mcp_server(self):
        # A skill is enough for this tool. An MCP server would add a process for no gain.
        self.assertNotIn("mcpServers", self.manifest)
        self.assertNotIn("apps", self.manifest)

    def test_manifest_version_is_strict_semver(self):
        import re
        self.assertRegex(self.manifest["version"], r"\A\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?\Z")

    def test_interface_has_every_required_field(self):
        interface = self.manifest["interface"]
        for field in ("displayName", "shortDescription", "longDescription", "developerName", "category"):
            self.assertTrue(interface.get(field))
        self.assertTrue(interface.get("defaultPrompt") or interface.get("default_prompt"))
        self.assertIsInstance(interface["capabilities"], list)

    def test_marketplace_points_at_the_repository_root(self):
        entry, = self.marketplace["plugins"]
        # Root-as-plugin keeps ONE copy of src/: the engine ships with the plugin and is
        # never duplicated into a nested plugin folder.
        self.assertEqual(entry["source"], {"source": "local", "path": "."})
        self.assertEqual(entry["name"], PLUGIN_NAME)
        self.assertEqual(entry["name"], self.manifest["name"])
        self.assertIn(entry["policy"]["installation"], ("NOT_AVAILABLE", "AVAILABLE", "INSTALLED_BY_DEFAULT"))
        self.assertIn(entry["policy"]["authentication"], ("ON_INSTALL", "ON_USE"))
        self.assertTrue(entry["category"])

    def test_skill_is_discoverable_where_the_manifest_says(self):
        self.assertEqual(self.manifest["skills"], "./skills/")
        self.assertTrue(SKILL.is_file())
        head = SKILL.read_text(encoding="utf-8").splitlines()
        self.assertEqual(head[0], "---")
        self.assertIn("name: %s" % PLUGIN_NAME, head)

    def test_skill_never_teaches_an_unsafe_shortcut(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("--last", text)          # mentioned only to forbid it
        self.assertIn("Never guess", text)
        self.assertNotIn("codex queue", text)  # the skill must not send messages itself


class LocaleTests(unittest.TestCase):
    def test_english_is_the_default_for_unknown_locales(self):
        for environ in ({}, {"LANG": "C"}, {"LANG": "fr_FR.UTF-8"}, {"LC_ALL": "de-DE"}):
            with self.subTest(environ=environ), patch.object(messages, "_windows_preferred", return_value=[]):
                self.assertEqual(messages.language(environ), "en")

    def test_korean_only_when_it_is_the_most_preferred_language(self):
        with patch.object(messages, "_windows_preferred", return_value=["ko-KR", "en-US"]):
            self.assertEqual(messages.language({}), "ko")
        # Korean merely present, but not preferred, is not an explicit request for Korean.
        with patch.object(messages, "_windows_preferred", return_value=["en-US", "ko-KR"]):
            self.assertEqual(messages.language({}), "en")

    def test_explicit_override_wins(self):
        with patch.object(messages, "_windows_preferred", return_value=["ko-KR"]):
            self.assertEqual(messages.language({messages.ENV_LANG: "en"}), "en")

    def test_every_key_exists_in_every_language(self):
        english = set(messages.MESSAGES["en"])
        for code in messages.SUPPORTED:
            self.assertEqual(set(messages.MESSAGES[code]), english, code)

    def test_a_failing_probe_falls_back_to_english_not_a_guess(self):
        with patch.object(messages, "_windows_preferred", side_effect=OSError("no api")):
            with self.assertRaises(OSError):
                messages.language({})    # the probe itself is guarded inside _windows_preferred
        with patch.object(messages, "_windows_preferred", return_value=[]):
            self.assertEqual(messages.language({}), "en")


class AutostartOwnershipTests(unittest.TestCase):
    """Regression: uninstall used to delete ANY registered value, including another
    installation's. That silently disabled a watcher it did not own."""

    def test_value_naming_this_home_belongs_to_it(self):
        home = Path(r"C:\Users\someone\project")
        command = startup.command_line(home / "src" / "auto_resume.py", home, launcher=Path(r"C:\Py\pythonw.exe"))
        self.assertTrue(startup.belongs_to(command, home))

    def test_launcher_inside_the_home_belongs_to_it(self):
        home = Path(r"C:\Users\someone\AppData\Local\codex-auto-resume")
        command = startup.command_line(home / "watcher-launcher.py", None, launcher=Path(r"C:\Py\pythonw.exe"))
        self.assertTrue(startup.belongs_to(command, home))

    def test_a_different_installation_is_not_ours(self):
        mine = Path(r"C:\Users\someone\AppData\Local\codex-auto-resume")
        theirs = Path(r"C:\Users\someone\checkout")
        command = startup.command_line(theirs / "src" / "auto_resume.py", theirs, launcher=Path(r"C:\Py\pythonw.exe"))
        self.assertFalse(startup.belongs_to(command, mine))

    def test_quoted_paths_with_spaces_are_split_correctly(self):
        home = Path(r"C:\Users\some one\My Project")
        command = startup.command_line(home / "src" / "auto_resume.py", home, launcher=Path(r"C:\Program Files\Py\pythonw.exe"))
        self.assertIn('"', command)
        self.assertTrue(startup.belongs_to(command, home))

    def test_unrelated_command_is_never_claimed(self):
        self.assertFalse(startup.belongs_to("notepad.exe", Path(r"C:\Users\someone\home")))
        self.assertFalse(startup.belongs_to("", Path(r"C:\Users\someone\home")))


class LauncherResolutionTests(unittest.TestCase):
    """The launcher must find the engine again after an update, and refuse otherwise."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.launcher = _load("watcher_launcher_under_test", ROOT / "scripts" / "watcher_launcher.py")
        self.cache = self.root / "codex" / "plugins" / "cache"
        patcher = patch.object(self.launcher, "codex_home", return_value=self.root / "codex")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _plant(self, marketplace: str, version: str) -> Path:
        root = self.cache / marketplace / PLUGIN_NAME / version
        (root / "src" / "codex_auto_resume").mkdir(parents=True)
        (root / "src" / "auto_resume.py").write_text("", encoding="utf-8")
        (root / "src" / "codex_auto_resume" / "cli.py").write_text("", encoding="utf-8")
        return root

    def config(self, **overrides) -> dict:
        base = {"mode": "plugin", "plugin_name": PLUGIN_NAME, "plugin_root": "", "home": str(self.root)}
        base.update(overrides)
        return base

    def test_finds_the_installed_plugin(self):
        planted = self._plant("mine", "0.2.0")
        self.assertEqual(self.launcher.resolve_plugin_root(self.config()), planted)

    def test_an_update_to_a_new_version_directory_is_picked_up(self):
        old = self._plant("mine", "0.2.0")
        new = self._plant("mine", "0.2.1+codex.local")
        import os
        os.utime(new, (2 ** 31, 2 ** 31))    # newest wins; version strings do not sort
        self.assertEqual(self.launcher.resolve_plugin_root(self.config()), new)
        self.assertNotEqual(self.launcher.resolve_plugin_root(self.config()), old)

    def test_incomplete_directory_is_ignored(self):
        (self.cache / "mine" / PLUGIN_NAME / "0.2.0").mkdir(parents=True)
        self.assertIsNone(self.launcher.resolve_plugin_root(self.config()))

    def test_removed_plugin_resolves_to_nothing_instead_of_starting(self):
        self.assertIsNone(self.launcher.resolve_plugin_root(self.config()))

    def test_local_checkout_mode_uses_the_recorded_root(self):
        checkout = self._plant("unused", "x")
        config = self.config(mode="local", plugin_root=str(checkout))
        self.assertEqual(self.launcher.resolve_plugin_root(config), checkout)

    def test_local_mode_with_a_deleted_checkout_refuses(self):
        config = self.config(mode="local", plugin_root=str(self.root / "gone"))
        self.assertIsNone(self.launcher.resolve_plugin_root(config))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        # Pin the language so assertions and captured output do not depend on the
        # machine's Windows display language.
        language = patch.object(messages, "language", return_value="en")
        language.start()
        self.addCleanup(language.stop)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "runtime"
        module = sys.modules.get("plugin_setup_under_test")
        self.bridge = module or _load("plugin_setup_under_test", ROOT / "scripts" / "plugin_setup.py")
        # Never let a bridge test reach the real HKCU Run key or spawn a real watcher.
        for target, replacement in (("install", None), ("uninstall", False), ("current_value", None)):
            guard = patch.object(startup, target, return_value=replacement)
            guard.start()
            self.addCleanup(guard.stop)
        spawn = patch.object(self.bridge, "start_watcher", return_value=True)
        spawn.start()
        self.addCleanup(spawn.stop)
        # Registered last so it runs FIRST (cleanups are LIFO): the core opens a
        # rotating log file, and an open handler keeps a Windows lock that would
        # make the temp-directory cleanup fail.
        self.addCleanup(self._close_log_handlers)

    @staticmethod
    def _close_log_handlers():
        import logging
        logger = logging.getLogger("codex_auto_resume")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_runtime_home_is_outside_the_plugin_directory(self):
        # State must not live in the versioned plugin cache, or every update loses it.
        with patch.dict(self.bridge.os.environ, {"USERPROFILE": r"C:\Users\someone"}, clear=False):
            self.bridge.os.environ.pop(self.bridge.ENV_RUNTIME_HOME, None)
            home = self.bridge.runtime_home()
        self.assertFalse(str(home).startswith(str(self.bridge.PLUGIN_ROOT)))
        self.assertEqual(home.name, self.bridge.RUNTIME_DIR_NAME)

    def test_runtime_home_avoids_appdata_entirely(self):
        """Regression: state once landed inside a packaged host's private LocalCache.

        Windows redirects a packaged (MSIX) process's AppData writes into its own
        sandbox while %LOCALAPPDATA% still reads as the normal path, so an installation
        run from such a host silently put its state inside an unrelated application.
        """
        with patch.dict(self.bridge.os.environ,
                        {"USERPROFILE": r"C:\Users\someone",
                         "LOCALAPPDATA": r"C:\Users\someone\AppData\Local"}, clear=False):
            self.bridge.os.environ.pop(self.bridge.ENV_RUNTIME_HOME, None)
            home = self.bridge.runtime_home()
        self.assertNotIn("AppData", home.parts)
        self.assertEqual(home.parent.name, "someone")

    def _through_launcher(self, command: str) -> list[str]:
        """What the launcher would hand to the command-line interface for this command."""
        sample = "codex-auto-resume:cancel?i=" + "ab" * 32
        argv = startup.parse_command(command)
        # Windows substitutes the real URI for %1 before launching.
        extra = [sample if a == "%1" else a for a in argv[2:]] or ["run"]
        return ["--home", str(self.home), "--quiet"] + extra

    def test_the_registered_commands_are_ones_the_cli_actually_accepts(self):
        """Regression: autostart registered `... watcher-launcher.py run`, and the launcher
        appended `run` again, so the login watcher died with an argparse error every time."""
        from codex_auto_resume import cli

        for command in (self.bridge.watcher_command(self.home), self.bridge.notification_command(self.home)):
            with self.subTest(command=command):
                cli.build_parser().parse_args(self._through_launcher(command))

    def test_both_registrations_go_through_the_stable_launcher(self):
        # Neither may name the versioned plugin directory, or an update orphans it.
        for command in (self.bridge.watcher_command(self.home), self.bridge.notification_command(self.home)):
            script = startup.parse_command(command)[1]
            self.assertEqual(Path(script).parent, self.home)
            self.assertNotIn(str(self.bridge.PLUGIN_ROOT), command)

    def test_install_launcher_records_how_to_find_the_engine(self):
        self.bridge.install_launcher(self.home, "plugin")
        payload = json.loads((self.home / self.bridge.RUNTIME_CONFIG).read_text(encoding="utf-8"))
        self.assertEqual(payload["mode"], "plugin")
        self.assertEqual(payload["plugin_name"], PLUGIN_NAME)
        self.assertEqual(payload["home"], str(self.home))
        self.assertTrue((self.home / self.bridge.LAUNCHER_NAME).is_file())

    def test_a_different_interpreter_is_the_same_installation_not_a_conflict(self):
        """Regression: upgrading Python changed the registered command, and setup then
        refused forever, believing a second installation existed."""
        from pathlib import Path as _Path
        other = startup.command_line(self.home / self.bridge.LAUNCHER_NAME, None,
                                     launcher=_Path(r"C:\Python313\pythonw.exe"))
        with patch.object(self.bridge, "runtime_home", return_value=self.home),              patch.object(startup, "current_value", return_value=other):
            self.assertIsNone(self.bridge.conflicting_autostart(self.home))

    def test_setup_refuses_when_another_installation_owns_autostart(self):
        foreign = startup.command_line(Path(r"C:\other\src\auto_resume.py"), Path(r"C:\other"),
                                       launcher=Path(r"C:\Py\pythonw.exe"))
        args = self.bridge.build_parser().parse_args(["setup"])
        with patch.object(self.bridge, "runtime_home", return_value=self.home), \
             patch.object(startup, "current_value", return_value=foreign), \
             patch.object(startup, "install") as install, \
             patch.object(self.bridge, "start_watcher") as start:
            code = self.bridge.cmd_setup(args)
        self.assertEqual(code, self.bridge.EXIT_ERROR)
        install.assert_not_called()
        start.assert_not_called()
        self.assertFalse(self.home.exists())    # nothing written when it refuses

    def test_setup_is_idempotent_and_keeps_existing_state(self):
        args = self.bridge.build_parser().parse_args(["setup", "--no-startup"])
        with patch.object(self.bridge, "runtime_home", return_value=self.home), \
             patch.object(startup, "current_value", return_value=None), \
             patch.object(startup, "install") as install, \
             patch.object(self.bridge, "start_watcher"):
            self.assertEqual(self.bridge.cmd_setup(args), self.bridge.EXIT_OK)
            marker = self.home / "config" / "keep-me.txt"
            marker.write_text("preserved", encoding="utf-8")
            self.assertEqual(self.bridge.cmd_setup(args), self.bridge.EXIT_OK)
        install.assert_not_called()             # --no-startup must never touch the registry
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserved")

    def test_no_startup_never_writes_the_registry(self):
        args = self.bridge.build_parser().parse_args(["setup", "--no-startup"])
        with patch.object(self.bridge, "runtime_home", return_value=self.home), \
             patch.object(startup, "current_value", return_value=None), \
             patch.object(startup, "install") as install, \
             patch.object(startup, "uninstall") as remove, \
             patch.object(self.bridge, "start_watcher"):
            self.bridge.cmd_setup(args)
        install.assert_not_called()
        remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
