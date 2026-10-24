"""What the setup's log says, in the order it says it (v0.6.17, the live acceptance's second round).

Three things the log said wrongly, each held here by a test that fails with its fix reverted:

* mid-log, setup printed "could not be confirmed" about a watcher the installer then looked at again, and its
  last word said the watcher runs - setup now says "not confirmed yet" where its caller will look again;
* a Repair's last word was "Updated." - it says it was repaired;
* the look's own line was in the PC's language inside a log that is otherwise English.

Nothing here reaches the real registry, the real install or a real watcher: setup runs against a scratch home with
the registry faked and the watcher start stubbed, and the installer's script is lifted by marker and run with its
setup stubbed (the way tests/test_upgrade_handover.py does it).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import l10n, shortcut, startup

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "build" / "install" / "install.ps1"
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
CATALOGS = ROOT / "src" / "codex_auto_resume" / "locales"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _plugin_setup():
    module = sys.modules.get("plugin_setup_under_test")
    if module is None:
        spec = importlib.util.spec_from_file_location("plugin_setup_under_test", ROOT / "scripts" / "plugin_setup.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class ScratchSetup(unittest.TestCase):
    """plugin_setup's `setup` against a scratch home: no real registry, no shortcut, no watcher."""

    PIN_ENGLISH = True       # the language is pinned, so a case's words do not depend on this PC's Windows language

    def setUp(self):
        from test_cli import FakeWinreg
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "runtime"
        self.bridge = _plugin_setup()
        patches = [patch.object(startup, "_winreg", return_value=FakeWinreg())]
        if self.PIN_ENGLISH:
            patches.append(patch.object(l10n, "current", return_value="en"))
        for target, replacement in (("install", None), ("uninstall", False), ("current_value", None),
                                    ("register_aumid", True), ("unregister_aumid", False)):
            patches.append(patch.object(startup, target, return_value=replacement))
        for target, replacement in (("install", True), ("uninstall", False)):
            patches.append(patch.object(shortcut, target, return_value=replacement))
        for guard in patches:
            guard.start()
            self.addCleanup(guard.stop)
        self.addCleanup(self._close_log_handlers)
        for name in ("python.exe", "pythonw.exe"):
            path = self.home / "runtime" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        package = self.home / "app" / "src" / "codex_auto_resume"
        package.mkdir(parents=True, exist_ok=True)
        (package / "cli.py").write_text("", encoding="utf-8")
        (self.home / "app" / "src" / "auto_resume.py").write_text("", encoding="utf-8")

    @staticmethod
    def _close_log_handlers():
        import logging
        logger = logging.getLogger("codex_auto_resume")
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    def setup(self, *flags, looks_again=False, started="unconfirmed", seen=False):
        """setup as the installer runs it: `looks_again` is the variable the installer sets for that one call."""
        args = self.bridge.build_parser().parse_args(["setup", "--no-startup", *flags])
        output = io.StringIO()
        environment = {self.bridge.ENV_WILL_LOOK_AGAIN: "1"} if looks_again else {}
        with patch.object(self.bridge, "runtime_home", return_value=self.home), \
             patch.object(self.bridge, "start_watcher", return_value=started), \
             patch.object(self.bridge, "watcher_seen", return_value=seen), \
             patch.dict(os.environ, environment), \
             contextlib.redirect_stdout(output):
            if not looks_again:
                os.environ.pop(self.bridge.ENV_WILL_LOOK_AGAIN, None)
            code = self.bridge.cmd_setup(args)
        return code, output.getvalue()


class MidLogWordTests(ScratchSetup):
    """A watcher setup could not confirm is "not confirmed yet" where the installer looks again, a verdict where
    nothing does."""

    def test_the_installer_s_setup_says_not_confirmed_yet(self):
        code, text = self.setup(looks_again=True)
        self.assertEqual(code, self.bridge.EXIT_UNCONFIRMED, "the exit code is still the unconfirmed one")
        self.assertIn(l10n.message("setup_unconfirmed_yet"), text)
        self.assertNotIn(l10n.message("setup_unconfirmed"), text, "no final verdict where a later look follows")

    def test_a_setup_run_alone_keeps_the_final_word(self):
        code, text = self.setup()
        self.assertEqual(code, self.bridge.EXIT_UNCONFIRMED)
        self.assertIn(l10n.message("setup_unconfirmed"), text)
        self.assertNotIn(l10n.message("setup_unconfirmed_yet"), text)

    def test_a_variable_that_is_not_1_changes_nothing(self):
        with patch.dict(os.environ, {self.bridge.ENV_WILL_LOOK_AGAIN: "0"}):
            code, text = self.setup()
        self.assertIn(l10n.message("setup_unconfirmed"), text)

    def test_a_confirmed_watcher_is_the_same_word_either_way(self):
        for looks_again in (False, True):
            with self.subTest(looks_again=looks_again):
                code, text = self.setup(looks_again=looks_again, started="running")
                self.assertEqual(code, self.bridge.EXIT_OK)
                self.assertIn(l10n.message("setup_done"), text)
                self.assertNotIn(l10n.message("setup_unconfirmed"), text)
                self.assertNotIn(l10n.message("setup_unconfirmed_yet"), text)

    def test_a_watcher_left_stopped_is_still_said_to_be_left_stopped(self):
        code, text = self.setup("--keep-state", "--watcher-was-stopped", looks_again=True)
        self.assertIn(l10n.message("setup_left_stopped"), text)
        self.assertNotIn(l10n.message("setup_unconfirmed_yet"), text)

    def test_the_two_words_say_different_things(self):
        yet, final = l10n.message("setup_unconfirmed_yet"), l10n.message("setup_unconfirmed")
        self.assertNotEqual(yet, final)
        self.assertIn("yet", yet)
        self.assertNotIn("could not be confirmed", yet, "no verdict in the word that is not one")

    def test_every_language_has_the_new_word_of_its_own(self):
        english = l10n.text("msg.setup_unconfirmed_yet", "en")
        for locale in l10n.LOCALES:
            if locale == "en":
                continue
            table = json.loads((CATALOGS / ("%s.json" % locale)).read_text(encoding="utf-8"))
            with self.subTest(locale):
                self.assertIn("msg.setup_unconfirmed_yet", table)
                self.assertNotEqual(table["msg.setup_unconfirmed_yet"], english)
                self.assertNotEqual(table["msg.setup_unconfirmed_yet"], table["msg.setup_unconfirmed"])

    def test_korean_calls_the_watcher_the_way_the_catalog_does(self):
        """The window and the setup say 워처 for the watcher, as every other line of the Korean catalog does."""
        self.assertIn("워처", l10n.text("msg.setup_unconfirmed_yet", "ko"))
        self.assertNotIn("감시기", l10n.text("msg.setup_unconfirmed_yet", "ko"))


class CallersLookAgainTests(unittest.TestCase):
    """Every script that says setup's last word looks again after it, and says so to setup - by a variable set for
    that one call, never an argument (an older installed setup rejects an argument it does not know)."""

    def test_install_ps1_tells_setup_it_will_look_again_and_does(self):
        text = INSTALL.read_text(encoding="utf-8")
        flag = text.index("$env:CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN = '1'")
        run = text.index("$code = Invoke-Setup $setupArgs", flag)
        self.assertLess(run - flag, 200, "set for that call")
        self.assertIn("$env:CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN = $null", text[run:run + 200], "and not for any other")
        self.assertIn("Invoke-Setup @('watcher-running')", text[run:], "and the look that follows is the reason for it")

    def test_the_bootstraps_check_over_tells_setup_it_will_look_again_and_does(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        start = text.index("$arguments = @('-X', 'disable-remote-debug', $setup, 'setup', '--keep-state')")
        branch = text[start:text.index("exit $code", start)]
        self.assertIn("$lookAgain = @{ CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN = '1' }", branch)
        self.assertIn("-Environment $lookAgain", branch, "the run outside gets it too")
        self.assertIn("$env:CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN = '1'", branch, "and the run here")
        self.assertIn("'watcher-running'", branch)

    def test_no_script_passes_setup_an_argument_an_older_setup_lacks(self):
        """The bootstrap's check-over runs the INSTALLED plugin_setup.py, so what it passes is only what setup has
        always taken; the two hints are variables."""
        for path in (INSTALL, BOOTSTRAP):
            text = path.read_text(encoding="utf-8")
            for argument in ("--will-look-again", "--english"):
                self.assertNotIn(argument, text, path.name)
        self.assertNotIn("--will-look-again", " ".join(self.bridge_parser_options()))
        self.assertNotIn("--english", " ".join(self.bridge_parser_options()))

    @staticmethod
    def bridge_parser_options():
        parser = _plugin_setup().build_parser()
        options = []
        for action in parser._subparsers._group_actions:
            for sub in action.choices.values():
                options += [string for a in sub._actions for string in a.option_strings]
        return options

    def test_the_plugin_s_own_setup_does_not(self):
        """Run from Codex (the skill) nothing looks again: nothing there says the variable."""
        for path in (ROOT / "skills" / "codex-auto-resume" / "SKILL.md", ROOT / "docs" / "PLUGIN.md"):
            if path.is_file():
                self.assertNotIn("CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN", path.read_text(encoding="utf-8"), path.name)


class OlderInstalledSetupTests(unittest.TestCase):
    """The bootstrap's check-over runs the installed plugin_setup.py, which can be older than the script that runs it:
    a 0.6.17 candidate built before these hints exist. What the bootstrap passes it must still run."""

    OLDER = "ede362004"        # the commit before the hints: its plugin_setup.py has neither the variables nor the look

    def older_parser(self):
        done = subprocess.run(["git", "show", "%s:scripts/plugin_setup.py" % self.OLDER], cwd=str(ROOT),
                              capture_output=True, text=True, encoding="utf-8",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if done.returncode != 0:
            self.skipTest("the commit the older setup is read from is not in this checkout")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plugin_setup.py"
            path.write_text(done.stdout, encoding="utf-8")
            # Imported from where the real one sits, so its own sys.path lines find this tree's src.
            text = done.stdout.replace("Path(__file__).resolve().parents[1]", "Path(%r)" % str(ROOT))
            path.write_text(text, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("plugin_setup_older", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module.build_parser()

    def test_what_the_bootstrap_passes_an_older_setup_still_parses(self):
        parser = self.older_parser()
        for argv in (["setup", "--keep-state"], ["setup", "--keep-state", "--no-startup"]):
            with self.subTest(argv):
                self.assertEqual(parser.parse_args(argv).command, "setup")

    def test_an_argument_for_the_hint_would_have_stopped_it(self):
        """Why the hint is a variable: the older setup exits 2 on an unknown argument - the code the bootstrap reads
        as 'watcher not confirmed' - without having run."""
        parser = self.older_parser()
        for argument in ("--will-look-again", "--english"):
            with self.subTest(argument), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                parser.parse_args(["setup", "--keep-state", argument])
            self.assertEqual(stopped.exception.code, 2)

    def test_the_variables_reach_the_run_outside_another_app_s_view(self):
        """Get-OutsideSource, lifted from bootstrap.ps1: the variables a call is given are lines of the source the
        run outside executes, before the call; none given, none added."""
        from test_installer import block
        text = BOOTSTRAP.read_text(encoding="utf-8")
        function = block(text, "function Get-OutsideSource {", "function Send-OutsideLines {")
        script = (function + "$with = Get-OutsideSource -Script 'C:\\python.exe' -Arguments @('x') -Log 'l' -CodeFile 'c' "
                  "-Environment @{ CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN = '1' }\n"
                  "$without = Get-OutsideSource -Script 'C:\\python.exe' -Arguments @('x') -Log 'l' -CodeFile 'c'\n"
                  "Write-Host ('WITH ' + (($with -split \"`r`n\") -join '|'))\n"
                  "Write-Host ('WITHOUT ' + (($without -split \"`r`n\") -join '|'))\n")
        said = run_powershell(script)
        with_line = next(line for line in said.splitlines() if line.startswith("WITH "))
        without_line = next(line for line in said.splitlines() if line.startswith("WITHOUT "))
        self.assertIn("|$env:CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN = '1'|try {", with_line)
        self.assertNotIn("$env:", without_line)
        self.assertIn("|$code = 1|try {", without_line)


class EnglishLookTests(ScratchSetup):
    """The installer's look at the watcher says its line in English, whatever Interface language is stored: the
    language is the person's own and an explicit one outranks the environment's override, so the call asks for English."""
    PIN_ENGLISH = False

    def setUp(self):
        super().setUp()
        from codex_auto_resume import config
        self.addCleanup(l10n.set_preference, l10n.SYSTEM)
        config.Paths(self.home).ensure()
        config.update_settings(config.Paths(self.home), {"interface_language": "ko"})

    def look(self, english=False):
        args = self.bridge.build_parser().parse_args(["watcher-running"])
        output = io.StringIO()
        environment = {self.bridge.ENV_ENGLISH: "1"} if english else {}
        with patch.object(self.bridge, "runtime_home", return_value=self.home), patch.dict(os.environ, environment), \
             contextlib.redirect_stdout(output):
            if not english:
                os.environ.pop(self.bridge.ENV_ENGLISH, None)
            code = self.bridge.COMMANDS[args.command](args)
        return code, output.getvalue().strip()

    def test_a_korean_pc_s_look_is_korean_unless_english_is_asked_for(self):
        code, said = self.look()
        self.assertEqual((code, said), (self.bridge.EXIT_UNCONFIRMED, l10n.text("msg.watcher_stopped", "ko")))
        self.assertNotEqual(said, l10n.text("msg.watcher_stopped", "en"))

    def test_asked_for_english_the_same_look_is_english_with_the_same_answer(self):
        code, said = self.look(english=True)
        self.assertEqual((code, said), (self.bridge.EXIT_UNCONFIRMED, l10n.text("msg.watcher_stopped", "en")))

    def test_a_running_watcher_is_said_in_english_too(self):
        with patch.object(self.bridge, "watcher_seen", return_value=True):
            code, said = self.look(english=True)
        self.assertEqual((code, said), (self.bridge.EXIT_OK, "Watcher: running"))

    def test_the_installer_and_the_bootstrap_ask_for_english_and_nothing_else_does(self):
        for path in (INSTALL, BOOTSTRAP):
            text = path.read_text(encoding="utf-8")
            self.assertIn("$env:CODEX_AUTO_RESUME_SETUP_ENGLISH = '1'", text, path.name)
            self.assertIn("$env:CODEX_AUTO_RESUME_SETUP_ENGLISH = $null", text, "and only for that call: " + path.name)
        for window in sorted((ROOT / "gui").glob("*.cs")):
            self.assertNotIn("CODEX_AUTO_RESUME_SETUP_ENGLISH", window.read_text(encoding="utf-8"), window.name)


def run_powershell(script: str) -> str:
    """A script run in Windows PowerShell, its output returned; the test is skipped where there is none."""
    if not POWERSHELL.is_file():
        raise unittest.SkipTest("Windows PowerShell")
    with tempfile.TemporaryDirectory() as folder:
        probe = Path(folder) / "probe.ps1"
        probe.write_text(script, encoding="utf-8-sig")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(probe)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0:
        raise AssertionError(done.stdout + done.stderr)
    return done.stdout


def tree(root: Path, version) -> Path:
    """An app tree whose plugin manifest declares `version` (none at all for None)."""
    manifest = root / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if version is not None:
        manifest.write_text(json.dumps({"name": "codex-auto-resume", "version": version}), encoding="utf-8")
    return root


class RepairIsToldFromUpdateTests(unittest.TestCase):
    """A Repair is this archive's version over the same version, in the same edition: its last word says so."""

    def setUp(self):
        self.text = INSTALL.read_text(encoding="utf-8")

    def decided(self, installed, payload, edition_change=False, upgrade=True):
        """install.ps1's own decision block, lifted by marker, over two trees: whether it called the run a repair."""
        from test_installer import block
        function = block(self.text, "function Get-AppVersion {", "function Get-EditionStatement {")
        decision = block(self.text, "    $repair = $false", "    if ($editionChange) {")
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            tree(base / "installed", installed)
            tree(base / "payload" / "app", payload)
            script = (function + "$AppDir = '%s'\n$Payload = '%s'\n$upgrade = $%s\n$editionChange = $%s\n"
                      % (base / "installed", base / "payload", str(upgrade).lower(), str(edition_change).lower())
                      + decision + "Write-Host ('REPAIR ' + $repair)\n")
            out = run_powershell(script)
        return out.split("REPAIR ")[-1].strip() == "True"

    def test_the_same_version_over_itself_is_a_repair(self):
        self.assertTrue(self.decided("0.6.17", "0.6.17"))

    def test_another_version_is_an_update_either_way(self):
        for installed, payload in (("0.6.16", "0.6.17"), ("0.6.18", "0.6.17"), ("0.6.17-beta.2", "0.6.17"),
                                   ("0.6.17", "0.6.17-beta.2")):
            with self.subTest(installed=installed, payload=payload):
                self.assertFalse(self.decided(installed, payload))

    def test_nothing_that_cannot_be_read_is_a_repair(self):
        self.assertFalse(self.decided(None, "0.6.17"), "no manifest in the installation")
        self.assertFalse(self.decided("0.6.17", None), "no manifest in the archive")
        self.assertFalse(self.decided(None, None))

    def test_a_first_installation_and_an_edition_change_are_neither(self):
        self.assertFalse(self.decided("0.6.17", "0.6.17", upgrade=False))
        self.assertFalse(self.decided("0.6.17", "0.6.17", edition_change=True))

    def test_the_decision_is_read_before_the_program_files_move(self):
        """The installed tree is moved aside after this point: the decision comes before every write."""
        decision = self.text.index("    $repair = $false")
        self.assertLess(decision, self.text.index("Step 'Updating program files'"))

    START, END = "    Step 'Checking the installation'", "    Write-Host 'To change anything"

    def last_words(self, repair, upgrade=True, unconfirmed=False, previous_running=False):
        """install.ps1's closing block, lifted from the health check to the last word, with setup stubbed."""
        from test_installer import VOICE, block
        look = 2 if unconfirmed else 0      # what the look at the watcher finds: not running, or running
        stubs = ("function Invoke-Setup { param([string[]]$Arguments)\n"
                 "    $global:LASTEXITCODE = %d; return %d }\n" % (look, look)
                 + "function Open-ClosedDashboard { param([switch]$Updated) }\n")
        script = ("$script:Failed = $false\n$upgrade = $%s\n$repair = $%s\n$watcherUnconfirmed = $%s\n"
                  "$previousWatcherStillRunning = $%s\n"
                  % tuple(str(v).lower() for v in (upgrade, repair, unconfirmed, previous_running))
                  + block(self.text, self.START, self.END))
        return run_powershell(VOICE + stubs + script)

    def test_a_repair_says_it_repaired_in_every_ending(self):
        for case in ({}, {"unconfirmed": True}, {"previous_running": True}):
            with self.subTest(case):
                said = self.last_words(True, **case)
                self.assertIn("Repaired. Your settings and pending recoveries were kept.", said)
                self.assertNotIn("Updated.", said)
                self.assertEqual("could not be confirmed" in said, bool(case.get("unconfirmed")), said)

    def test_an_update_still_says_updated_and_a_first_installation_installed(self):
        for case in ({}, {"unconfirmed": True}, {"previous_running": True}):
            with self.subTest(case):
                said = self.last_words(False, **case)
                self.assertIn("Updated. Your settings and pending recoveries were kept.", said)
                self.assertNotIn("Repaired", said)
                self.assertEqual("could not be confirmed" in said, bool(case.get("unconfirmed")), said)
        self.assertIn("Installed and running.", self.last_words(False, upgrade=False))
        self.assertIn("Installed.", self.last_words(False, upgrade=False, unconfirmed=True))

    def test_the_setup_window_s_finished_page_and_the_log_agree(self):
        """The window's finished page for Repair says repaired (installer.done.repaired) and keys only on the
        watcher sentences of the log, never on "Updated.": the log's new word changes neither page."""
        window = (ROOT / "gui" / "InstallerWindow.cs").read_text(encoding="utf-8")
        self.assertIn('flow.Repair && code == 0 ? words.Say("installer.done.repaired"', window)
        self.assertNotIn("Updated.", window)
        self.assertNotIn("Repaired.", window)
        for locale in l10n.LOCALES:
            self.assertIn("installer.done.repaired", json.loads((CATALOGS / ("%s.json" % locale)).read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
