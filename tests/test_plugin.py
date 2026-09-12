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

from codex_auto_resume import messages, shortcut, startup

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
SKILL = ROOT / "skills" / "codex-auto-resume" / "SKILL.md"
MCP_COMPANION = ROOT / ".mcp.json"
PLUGIN_NAME = "codex-auto-resume"
OURS = "codex-auto-resume-windows"   # the marketplace this product ships under


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

    def test_the_repository_manifest_declares_no_mcp_server(self):
        """A marketplace install from GitHub must not register a missing command.

        The MCP server needs the bundled interpreter, and only the release installer
        puts that on disk. Measured: with the declaration in the repository manifest,
        `codex plugin add` from a clone succeeds and registers the server as enabled,
        pointing at an executable that is not there - so the user gets a permanently
        failing server rather than an error they can act on. The declaration is added
        to the payload at build time instead.
        """
        self.assertNotIn("mcpServers", self.manifest)
        self.assertNotIn("apps", self.manifest)
        self.assertTrue(MCP_COMPANION.is_file(),
                        ".mcp.json stays in the repository as reviewable source")

    def test_the_release_build_adds_the_declaration_to_the_payload(self):
        builder = _load("make_release", ROOT / "build" / "make_release.py")
        source = Path(builder.__file__).read_text(encoding="utf-8")
        self.assertIn('ordered["mcpServers"] = "./.mcp.json"', source)
        # And refuses to run if the repository ever starts declaring it as well, which
        # would mean a GitHub install registers the broken command again.
        self.assertIn("the repository manifest must not declare mcpServers", source)

    def test_the_companion_declares_only_our_own_stdio_server(self):
        companion = json.loads(MCP_COMPANION.read_text(encoding="utf-8"))
        self.assertEqual(set(companion) - {"$schema"}, {"mcpServers"})
        self.assertEqual(list(companion["mcpServers"]), [PLUGIN_NAME])
        server = companion["mcpServers"][PLUGIN_NAME]
        self.assertEqual(server["type"], "stdio")

    def test_the_mcp_command_is_a_path_codex_accepts(self):
        # Codex requires a bare executable name or a path contained in the plugin. An
        # absolute path to the bundled interpreter is neither, and a bare `python` would
        # put back the system-Python requirement the product removed - hence a launcher
        # inside the plugin that finds the interpreter itself.
        server = json.loads(MCP_COMPANION.read_text(encoding="utf-8"))["mcpServers"][PLUGIN_NAME]
        command = server["command"]
        self.assertTrue(command.startswith("./"), command)
        self.assertNotIn("..", command)
        self.assertNotIn(":", command)
        self.assertIn(command.rsplit("/", 1)[-1], {"codex-auto-resume-mcp.exe"})

    def test_the_mcp_server_declares_no_environment_or_network(self):
        server = json.loads(MCP_COMPANION.read_text(encoding="utf-8"))["mcpServers"][PLUGIN_NAME]
        self.assertNotIn("url", server)
        self.assertNotIn("headers", server)
        self.assertEqual(server.get("env", {}), {})

    def test_the_release_ships_the_launcher_the_companion_names(self):
        # A companion file naming an executable the payload does not contain would fail
        # only at plugin load, on a user's machine.
        builder = _load("make_release", ROOT / "build" / "make_release.py")
        server = json.loads(MCP_COMPANION.read_text(encoding="utf-8"))["mcpServers"][PLUGIN_NAME]
        self.assertEqual(server["command"], "./mcp/" + builder.MCP_EXE)
        self.assertIn(".mcp.json", builder.APP_FILES)

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
        home = Path(r"C:\Users\Example User\My Project")
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
        planted = self._plant(OURS, "0.2.0")
        self.assertEqual(self.launcher.resolve_plugin_root(self.config()), planted)

    def test_an_update_to_a_new_version_directory_is_picked_up(self):
        old = self._plant(OURS, "0.2.0")
        new = self._plant(OURS, "0.2.1+codex.local")
        import os
        os.utime(new, (2 ** 31, 2 ** 31))    # newest wins; version strings do not sort
        self.assertEqual(self.launcher.resolve_plugin_root(self.config()), new)
        self.assertNotEqual(self.launcher.resolve_plugin_root(self.config()), old)

    def test_incomplete_directory_is_ignored(self):
        (self.cache / OURS / PLUGIN_NAME / "0.2.0").mkdir(parents=True)
        self.assertIsNone(self.launcher.resolve_plugin_root(self.config()))

    def test_removed_plugin_resolves_to_nothing_instead_of_starting(self):
        self.assertIsNone(self.launcher.resolve_plugin_root(self.config()))

    def test_a_same_named_plugin_from_another_marketplace_is_never_run(self):
        """The sign-in launcher used to take the newest copy from any marketplace."""
        ours = self._plant(OURS, "0.5.7")
        theirs = self._plant("someone-else", "9.9.9")
        import os
        os.utime(theirs, (2 ** 31, 2 ** 31))    # newer, which used to be enough to win
        self.assertEqual(self.launcher.resolve_plugin_root(self.config()), ours)

    def test_only_another_marketplace_means_nothing_starts(self):
        self._plant("someone-else", "9.9.9")
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
        # Never let a bridge test reach the real registry or spawn a real watcher.
        #
        # The named functions below were guarded one at a time, and `install_protocol`
        # was not among them - so every run of this suite wrote a real
        # `codex-auto-resume:` handler into the user's HKCU, pointing at a temp
        # directory that no longer existed by the time the test finished. It was found
        # by an uninstall correctly reporting that the handler belonged to a different
        # installation. Faking the registry module itself covers every function at once,
        # including any added later, which is why the other test modules do it that way.
        from test_cli import FakeWinreg          # the shared key-tree fake
        registry = patch.object(startup, "_winreg", return_value=FakeWinreg())
        registry.start()
        self.addCleanup(registry.stop)
        for target, replacement in (("install", None), ("uninstall", False), ("current_value", None),
                                    ("register_aumid", True), ("unregister_aumid", False)):
            guard = patch.object(startup, target, return_value=replacement)
            guard.start()
            self.addCleanup(guard.stop)
        # setup() runs the real `install`, which writes a Start Menu entry for the
        # actual user. Tests must never touch it.
        for target, replacement in (("install", True), ("uninstall", False)):
            guard = patch.object(shortcut, target, return_value=replacement)
            guard.start()
            self.addCleanup(guard.stop)
        spawn = patch.object(self.bridge, "start_watcher", return_value="running")
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
            # Compared the way the product compares them. Windows can spell one
            # directory several ways - an 8.3 short name, a different case - and a
            # literal comparison passes or fails depending on which spelling the
            # machine's TEMP happens to use.
            self.assertTrue(startup._same_path(Path(script).parent, self.home),
                            "%s is not %s" % (Path(script).parent, self.home))
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
             patch.object(self.bridge, "start_watcher", return_value="running") as start:
            code = self.bridge.cmd_setup(args)
        self.assertEqual(code, self.bridge.EXIT_ERROR)
        install.assert_not_called()
        start.assert_not_called()
        self.assertFalse(self.home.exists())    # nothing written when it refuses

    def pretend_installed(self):
        """Lay down the shape of a real installation under `self.home`.

        `setup` refuses to run against anything else, on purpose: without the bundled
        runtime and the application beside it there is nothing for the watcher to run,
        and configuring one anyway is how a second, lesser installation used to appear.
        Tests of the post-install path therefore have to look installed.
        tests/test_convergence.py covers the refusal itself.
        """
        for name in ("python.exe", "pythonw.exe"):
            path = self.home / "runtime" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        package = self.home / "app" / "src" / "codex_auto_resume"
        package.mkdir(parents=True, exist_ok=True)
        (package / "cli.py").write_text("", encoding="utf-8")
        (self.home / "app" / "src" / "auto_resume.py").write_text("", encoding="utf-8")

    def test_setup_reports_a_watcher_it_could_not_confirm(self):
        """Setup succeeding and the watcher running are two different facts.

        Everything asked for was done, so failing would roll back a good installation -
        but the installer's closing line used to be "Installed and running." whatever
        happened here, which is the overclaim this release exists to remove. A third exit
        code is what lets the shell wrapper tell the two apart.
        """
        self.pretend_installed()
        args = self.bridge.build_parser().parse_args(["setup", "--no-startup"])
        for state, expected in (("running", self.bridge.EXIT_OK),
                                ("already-running", self.bridge.EXIT_OK),
                                ("unconfirmed", self.bridge.EXIT_UNCONFIRMED),
                                ("exited", self.bridge.EXIT_UNCONFIRMED)):
            with self.subTest(state),                  patch.object(self.bridge, "runtime_home", return_value=self.home),                  patch.object(startup, "current_value", return_value=None),                  patch.object(startup, "install"),                  patch.object(self.bridge, "start_watcher", return_value=state):
                self.assertEqual(self.bridge.cmd_setup(args), expected)

    def test_setup_is_idempotent_and_keeps_existing_state(self):
        self.pretend_installed()
        args = self.bridge.build_parser().parse_args(["setup", "--no-startup"])
        with patch.object(self.bridge, "runtime_home", return_value=self.home), \
             patch.object(startup, "current_value", return_value=None), \
             patch.object(startup, "install") as install, \
             patch.object(self.bridge, "start_watcher", return_value="running"):
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
             patch.object(self.bridge, "start_watcher", return_value="running"):
            self.bridge.cmd_setup(args)
        install.assert_not_called()
        remove.assert_not_called()

    def setup_paused(self, argv, current):
        """Run setup against a paused installation whose Run value is `current`.

        The core commands run for real, through a wrapper that only records them, so the
        pause state read back afterwards is the one the store actually holds.
        """
        from codex_auto_resume import config
        from codex_auto_resume.store import Store
        self.pretend_installed()
        self.assertEqual(self.bridge._cli_silent(self.home, ["--quiet", "disable"]), self.bridge.EXIT_OK)
        args = self.bridge.build_parser().parse_args(argv)
        output = io.StringIO()
        with patch.object(self.bridge, "runtime_home", return_value=self.home), \
             patch.object(startup, "current_value", return_value=current), \
             patch.object(startup, "install") as install, \
             patch.object(self.bridge, "_cli_silent", wraps=self.bridge._cli_silent) as core, \
             patch.object(self.bridge, "start_watcher", return_value="running"), \
             contextlib.redirect_stdout(output):
            code = self.bridge.cmd_setup(args)
        with Store(config.Paths(self.home).state_dir) as store:
            enabled = bool(store.settings()["enabled"])
        commands = [call.args[1][-1] for call in core.call_args_list]
        return code, install, commands, enabled, output.getvalue()

    def test_keep_state_neither_resumes_nor_adds_an_autostart(self):
        code, install, commands, enabled, text = self.setup_paused(["setup", "--keep-state"], None)
        self.assertEqual(code, self.bridge.EXIT_OK)
        self.assertNotIn("enable", commands)
        self.assertIn("install", commands)          # the rest of the repair still runs
        self.assertFalse(enabled, "a repair must not switch a paused installation back on")
        install.assert_not_called()                 # there was no entry of ours to repair
        self.assertNotIn(messages.text("setup_autostart"), text)

    def test_keep_state_repairs_an_autostart_that_is_already_ours(self):
        # Ours, but stale: registered with a different interpreter.
        stale = startup.command_line(self.home / self.bridge.LAUNCHER_NAME, None,
                                     launcher=Path(r"C:\Python313\pythonw.exe"))
        code, install, commands, enabled, text = self.setup_paused(["setup", "--keep-state"], stale)
        self.assertEqual(code, self.bridge.EXIT_OK)
        self.assertNotIn("enable", commands)
        self.assertFalse(enabled)
        install.assert_called_once_with(self.bridge.watcher_command(self.home))
        self.assertIn(messages.text("setup_autostart"), text)

    def test_without_keep_state_setup_still_enables_and_registers(self):
        code, install, commands, enabled, text = self.setup_paused(["setup"], None)
        self.assertEqual(code, self.bridge.EXIT_OK)
        self.assertEqual(commands, ["install", "enable"])
        self.assertTrue(enabled)
        install.assert_called_once_with(self.bridge.watcher_command(self.home))
        self.assertIn(messages.text("setup_autostart"), text)


class ReleaseNotesTests(unittest.TestCase):
    """The published release notes come from the changelog, so they cannot drift.

    The version guard matters more than the extraction: a tag whose version has no
    changelog section, or a manifest bumped without a changelog entry, would publish a
    release describing the wrong thing. Both fail here instead.
    """

    def setUp(self):
        self.notes = _load("release_notes", ROOT / "build" / "release_notes.py")
        self.changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]

    def test_the_current_version_has_a_changelog_section(self):
        body = self.notes.section(self.changelog, self.version)
        self.assertTrue(body.strip())

    def test_a_leading_v_is_accepted(self):
        self.assertEqual(self.notes.section(self.changelog, "v" + self.version),
                         self.notes.section(self.changelog, self.version))

    def test_the_section_stops_at_the_next_release(self):
        body = self.notes.section(self.changelog, self.version)
        self.assertNotIn("\n## v", body)

    def test_an_unknown_version_is_refused_not_invented(self):
        with self.assertRaises(SystemExit):
            self.notes.section(self.changelog, "9.9.9")

    def test_a_prefix_version_does_not_match_a_longer_one(self):
        # Without a word boundary, "0.5" would match the "0.5.0" heading and publish
        # the wrong notes under the right name.
        with self.assertRaises(SystemExit):
            self.notes.section("## v0.50.0 - other\n\nbody\n", "0.5")

    def test_the_newest_changelog_entry_is_the_current_version(self):
        import re
        first = re.search(r"^##\s+v(\S+)", self.changelog, re.MULTILINE)
        self.assertEqual(first.group(1), self.version)


class ReleaseWorkflowTests(unittest.TestCase):
    """The release job is the only thing that publishes, so its guards are asserted."""

    def setUp(self):
        self.text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_it_runs_the_tests_before_publishing(self):
        self.assertIn("unittest discover", self.text)

    def test_it_publishes_only_from_a_tag(self):
        # A tag *push*: a dispatch whose ref is a tag satisfies startsWith() alone.
        self.assertIn("if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')", self.text)

    def test_it_refuses_a_tag_that_disagrees_with_the_manifest(self):
        self.assertIn("does not match plugin.json version", self.text)

    def test_it_uses_only_the_repository_token(self):
        # No personal credential is ever involved in publishing: the job's only secret
        # is the short-lived token GitHub mints for the repository itself.
        import re
        referenced = set(re.findall(r"secrets\.([A-Za-z0-9_]+)", self.text))
        self.assertEqual(referenced, {"GITHUB_TOKEN"})

    def test_it_verifies_the_published_checksum(self):
        self.assertIn("checksum mismatch", self.text)

    def test_it_checks_the_archive_carries_the_runtime_and_the_plugin(self):
        for required in ("payload/runtime/python.exe", "payload/app/mcp/codex-auto-resume-mcp.exe",
                         "payload/CodexAutoResumeSettings.exe"):
            self.assertIn(required, self.text)


class ShortPathOwnershipTests(unittest.TestCase):
    """One directory, several spellings, one answer.

    Windows hands out the same location under an 8.3 short name, a different case, or
    through a junction. An autostart value written when TEMP or USERPROFILE was in
    short form used to compare unequal to the same home resolved to its long form, so
    setup reported the installation's own entry as a conflicting second installation
    and refused to run - with nothing on screen explaining why. Found on CI, where the
    runner's temporary directory is handed out as RUNNER~1.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)

    def spellings(self):
        """The long form, plus the 8.3 short form when Windows offers one."""
        found = [str(self.home)]
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            buffer = ctypes.create_unicode_buffer(1024)
            if kernel32.GetShortPathNameW(str(self.home), buffer, 1024):
                if buffer.value and buffer.value != str(self.home):
                    found.append(buffer.value)
        return found

    def test_every_spelling_of_the_home_canonicalises_the_same(self):
        canonical = {startup._canonical(spelling) for spelling in self.spellings()}
        self.assertEqual(len(canonical), 1, canonical)

    def test_case_does_not_change_ownership(self):
        self.assertTrue(startup._same_path(str(self.home).upper(), self.home))

    def test_a_short_form_launcher_still_belongs_to_this_installation(self):
        for spelling in self.spellings():
            with self.subTest(spelling=spelling):
                command = startup.command_line(Path(spelling) / "watcher-launcher.py", None,
                                               launcher=Path(r"C:\Py\pythonw.exe"))
                self.assertTrue(startup.belongs_to(command, self.home))

    def test_a_short_form_home_argument_still_belongs(self):
        for spelling in self.spellings():
            with self.subTest(spelling=spelling):
                command = startup.command_line(Path(r"C:\elsewhere\auto_resume.py"), Path(spelling),
                                               launcher=Path(r"C:\Py\pythonw.exe"))
                self.assertTrue(startup.belongs_to(command, self.home))

    def test_a_different_installation_is_still_not_ours(self):
        # The fix must not make everything look like ours; that would let uninstall
        # remove another copy's autostart entry.
        command = startup.command_line(Path(r"C:\other\src\auto_resume.py"), Path(r"C:\other"),
                                       launcher=Path(r"C:\Py\pythonw.exe"))
        self.assertFalse(startup.belongs_to(command, self.home))

    def test_a_sibling_with_a_shared_prefix_is_not_inside(self):
        # "...\home-2" must not count as living inside "...\home".
        sibling = Path(str(self.home) + "-2")
        self.assertFalse(startup._inside(sibling / "watcher-launcher.py", self.home))

    def test_a_path_that_does_not_exist_still_compares_stably(self):
        missing = self.home / "gone" / "watcher-launcher.py"
        self.assertEqual(startup._canonical(missing), startup._canonical(str(missing)))
        self.assertTrue(startup._inside(missing, self.home))


class PythonFloorTests(unittest.TestCase):
    """The version the plugin path enforces must be a version CI actually runs.

    They had drifted: setup refused anything below 3.10 while the test matrix only ever
    ran 3.12 and 3.13, so two whole releases of Python were accepted by the installer
    and never tested. The message shown to the user has to agree with both.
    """

    def setUp(self):
        self.bridge = _load("plugin_setup", ROOT / "scripts" / "plugin_setup.py")
        self.workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")

    def lowest_tested(self):
        import re
        line = re.search(r"python-version:\s*\[([^\]]+)\]", self.workflow).group(1)
        versions = [tuple(int(p) for p in v.strip().strip('"\'').split("."))
                    for v in line.split(",")]
        return min(versions)

    def test_the_enforced_floor_is_the_lowest_tested_version(self):
        self.assertEqual(self.bridge.MIN_PYTHON, self.lowest_tested())

    def test_the_message_names_the_same_version(self):
        from codex_auto_resume import messages
        wanted = "%d.%d" % self.bridge.MIN_PYTHON
        for code in messages.SUPPORTED:
            self.assertIn(wanted, messages.MESSAGES[code]["python_missing"], code)

    def test_the_skill_does_not_send_anyone_looking_for_a_python(self):
        """It used to, and that is what produced a second installation.

        The skill's first instruction was "use the first Python that works", which meant
        the watcher, the sign-in entry and the notification handler were registered
        against whatever interpreter answered - a different product from the one the
        installer deploys, sharing its state directory. The floor above still applies to
        the engine and is still reported by `python_missing`; it is no longer something
        the skill asks anyone to satisfy, because the installer brings its own.
        """
        text = SKILL.read_text(encoding="utf-8")
        for gone in ("py -3 scripts/plugin_setup.py",
                     "python scripts/plugin_setup.py",
                     "python3 scripts/plugin_setup.py"):
            self.assertNotIn(gone, text, gone)
        self.assertIn("bootstrap.ps1", text)
        self.assertIn(r".codex-auto-resume\runtime\python.exe", text)

    def test_the_bundled_runtime_is_at_least_the_floor(self):
        builder = _load("make_release", ROOT / "build" / "make_release.py")
        shipped = tuple(int(p) for p in builder.PYTHON_VERSION.split(".")[:2])
        self.assertGreaterEqual(shipped, self.bridge.MIN_PYTHON)


class PayloadDocumentTests(unittest.TestCase):
    """The installed copy must not link to documents it does not carry.

    `app/` in the release payload is the plugin Codex installs from, and README.md ships
    with it. It linked to PRIVACY.md, SUPPORT.md and CONTRIBUTING.md, none of which were
    in the payload - so the installed README promised a privacy policy that was not
    beside it. Cheap to get wrong again the next time a document is added.
    """

    def test_every_top_level_document_the_readme_links_to_is_shipped(self):
        import re
        builder = _load("make_release_payload", ROOT / "build" / "make_release.py")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        linked = {target for target in re.findall(r"\]\(([^)#:]+?\.md)\)", readme)
                  if "/" not in target}
        self.assertTrue(linked, "the README links to no top-level document at all")
        missing = sorted(name for name in linked if name not in builder.APP_FILES)
        self.assertEqual(missing, [], "the payload README links to documents it does not ship")

    def test_the_shipped_documents_all_exist(self):
        """Every document the payload names, except the Korean ones on the ko branch.

        A release is always built from a tag on `main`, where all of them exist. The
        generated `ko` branch has written each Korean document over its English sibling
        and deleted the original, so asserting the `.ko.md` names there fails on a
        checkout that is behaving exactly as designed - and `collect_app` already skips
        a name it cannot find, so the payload is correct either way.
        """
        builder = _load("make_release_payload", ROOT / "build" / "make_release.py")
        # Tracked, not merely present: a stray local `ko_sync.py --root .` leaves the
        # marker behind untracked, and that must not excuse a genuinely missing document.
        import subprocess
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", ".github/GENERATED-BRANCH.md"],
            capture_output=True, text=True, encoding="utf-8")
        generated = bool(listed.returncode == 0 and listed.stdout.strip())
        for name in builder.APP_FILES:
            if generated and name.endswith(".ko.md"):
                continue
            self.assertTrue((ROOT / name).is_file(), name)


class VersionConsistencyTests(unittest.TestCase):
    """One version, read everywhere it is shown.

    `__version__` used to be a literal in `__init__.py`, and it stayed at the first
    release's number through four more of them while the manifest, the settings window
    and the release archive all moved on.
    """

    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_the_package_version_is_the_manifest_version(self):
        import codex_auto_resume
        from codex_auto_resume import config
        self.assertEqual(codex_auto_resume.__version__, self.manifest["version"])
        self.assertEqual(config.version(), self.manifest["version"])

    def test_the_control_layer_reports_the_same_version(self):
        from codex_auto_resume import control
        self.assertEqual(control._version(), self.manifest["version"])

    def test_no_second_version_literal_is_hiding_in_the_package(self):
        import re
        for path in sorted((ROOT / "src" / "codex_auto_resume").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for match in re.findall(r'__version__\s*=\s*["\']([^"\']+)["\']', text):
                self.fail("%s hardcodes a version: %s" % (path.name, match))

    def test_the_changelog_leads_with_this_version(self):
        import re
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        first = re.search(r"^##\s+v(\S+)", changelog, re.MULTILINE)
        self.assertEqual(first.group(1), self.manifest["version"])


if __name__ == "__main__":
    unittest.main()
