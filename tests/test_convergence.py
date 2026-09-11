"""One installation, whichever way you arrive at it.

There are three ways in - a downloaded archive, the Codex plugin, and a repair of an
existing install - and before v0.5.2 the second one produced a different, lesser product:
a watcher pointing at whatever system Python happened to run setup, no settings window,
no panel, and an engine resolved from the plugin cache rather than from the installation.
Two of those could be true at once on the same machine, sharing one database.

These tests pin the convergence rules that removed that:

* the interpreter every registration names is the one the installer deploys;
* the engine the watcher loads is the installed application, not a plugin cache copy;
* setup refuses to build a half-installation and says what to run instead;
* what the bootstrap is allowed to fetch, and what it must check before executing any
  of it.

The bootstrap is PowerShell, so it is checked by reading it. That is worth less than
running it and is not nothing: the properties asserted here - no shell interpolation of
downloaded text, no elevation, verification before execution, and a required-contents
list that matches the one the release workflow enforces - are exactly the ones that go
wrong silently when someone edits the script later.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import plugin_setup                    # noqa: E402
import watcher_launcher                # noqa: E402

BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
RELEASE = ROOT / "scripts" / "release.json"
CHANGELOG_TEXT = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
INSTALLER = ROOT / "install" / "install.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def make_home(tmp: Path, runtime: bool = True, app: bool = True) -> Path:
    """A directory shaped like an installation, with either half optionally missing."""
    home = tmp / ".codex-auto-resume"
    if runtime:
        (home / "runtime").mkdir(parents=True, exist_ok=True)
        (home / "runtime" / "python.exe").write_bytes(b"")
        (home / "runtime" / "pythonw.exe").write_bytes(b"")
    if app:
        package = home / "app" / "src" / "codex_auto_resume"
        package.mkdir(parents=True, exist_ok=True)
        (package / "cli.py").write_text("", encoding="utf-8")
        (home / "app" / "src" / "auto_resume.py").write_text("", encoding="utf-8")
    home.mkdir(parents=True, exist_ok=True)
    return home


class InstalledStateTests(unittest.TestCase):
    def test_both_halves_are_required(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.assertTrue(plugin_setup.installed(make_home(tmp / "both")))
            self.assertFalse(plugin_setup.installed(make_home(tmp / "no-runtime", runtime=False)))
            self.assertFalse(plugin_setup.installed(make_home(tmp / "no-app", app=False)))

    def test_an_empty_directory_is_not_an_installation(self):
        with tempfile.TemporaryDirectory() as name:
            self.assertFalse(plugin_setup.installed(Path(name)))


class InterpreterTests(unittest.TestCase):
    def test_the_bundled_windowless_interpreter_wins(self):
        with tempfile.TemporaryDirectory() as name:
            home = make_home(Path(name))
            self.assertEqual(plugin_setup.python_for_watcher(home),
                             home / "runtime" / "pythonw.exe")

    def test_console_interpreter_is_used_when_there_is_no_windowless_one(self):
        with tempfile.TemporaryDirectory() as name:
            home = make_home(Path(name))
            (home / "runtime" / "pythonw.exe").unlink()
            self.assertEqual(plugin_setup.python_for_watcher(home),
                             home / "runtime" / "python.exe")

    def test_it_falls_back_only_when_nothing_is_installed(self):
        with tempfile.TemporaryDirectory() as name:
            home = make_home(Path(name), runtime=False)
            # Whatever is running the tests: the point is that it is not under `home`.
            self.assertNotEqual(plugin_setup.python_for_watcher(home).parent,
                                home / "runtime")

    def test_every_registration_names_the_installed_interpreter(self):
        with tempfile.TemporaryDirectory() as name:
            home = make_home(Path(name))
            bundled = str(home / "runtime" / "pythonw.exe")
            # The sign-in entry, the notification button and the watcher itself. All
            # three used to be able to disagree.
            self.assertIn(bundled, plugin_setup.watcher_command(home))
            self.assertIn(bundled, plugin_setup.notification_command(home))


class SetupRefusalTests(unittest.TestCase):
    """`setup` on a plugin with nothing installed must stop, not improvise."""

    def run_setup(self, home: Path):
        import argparse
        import contextlib
        import io
        args = argparse.Namespace(no_startup=True, replace_existing=False)
        original = plugin_setup.runtime_home
        plugin_setup.runtime_home = lambda: home
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                code = plugin_setup.cmd_setup(args)
        finally:
            plugin_setup.runtime_home = original
        return code, output.getvalue()

    def test_it_refuses_and_names_the_setup_script(self):
        with tempfile.TemporaryDirectory() as name:
            home = make_home(Path(name), runtime=False)
            code, text = self.run_setup(home)
        self.assertEqual(code, plugin_setup.EXIT_ERROR)
        self.assertIn("bootstrap.ps1", text)

    def test_it_registers_nothing_when_it_refuses(self):
        with tempfile.TemporaryDirectory() as name:
            home = make_home(Path(name), runtime=False)
            self.run_setup(home)
            # No launcher, no runtime record: a refusal leaves no half-installation
            # behind for a later run to mistake for a real one.
            self.assertFalse((home / plugin_setup.LAUNCHER_NAME).exists())
            self.assertFalse((home / plugin_setup.RUNTIME_CONFIG).exists())

    def test_the_named_command_is_a_real_script(self):
        command = plugin_setup.bootstrap_command()
        self.assertIn("-ExecutionPolicy Bypass", command)
        self.assertIn("-File", command)
        self.assertTrue(BOOTSTRAP.is_file())
        self.assertIn(BOOTSTRAP.name, command)


class EngineResolutionTests(unittest.TestCase):
    """Which copy of the code the watcher loads. There is usually more than one."""

    def cache(self, tmp: Path, name: str = "codex-auto-resume") -> Path:
        version = tmp / ".codex" / "plugins" / "cache" / "codex-auto-resume-windows" / name / "9.9.9"
        (version / "src" / "codex_auto_resume").mkdir(parents=True)
        (version / "src" / "codex_auto_resume" / "cli.py").write_text("", encoding="utf-8")
        (version / "src" / "auto_resume.py").write_text("", encoding="utf-8")
        return version

    def setUp(self):
        self._codex_home = watcher_launcher.codex_home

    def tearDown(self):
        watcher_launcher.codex_home = self._codex_home

    def test_the_installed_application_beats_a_newer_plugin_cache_copy(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            home = make_home(tmp)
            cached = self.cache(tmp)
            # The cache copy is deliberately the newer of the two: preferring it by
            # modification time is exactly the bug this replaces.
            import os
            import time
            os.utime(cached, (time.time() + 600, time.time() + 600))
            watcher_launcher.codex_home = lambda: tmp / ".codex"
            resolved = watcher_launcher.resolve_plugin_root(
                {"mode": "plugin", "plugin_name": "codex-auto-resume", "home": str(home),
                 "plugin_root": str(cached)})
            self.assertEqual(resolved, home / "app")

    def test_the_cache_is_still_used_when_there_is_no_installed_application(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            home = make_home(tmp, app=False)
            cached = self.cache(tmp)
            watcher_launcher.codex_home = lambda: tmp / ".codex"
            resolved = watcher_launcher.resolve_plugin_root(
                {"mode": "plugin", "plugin_name": "codex-auto-resume", "home": str(home)})
            self.assertEqual(resolved, cached)

    def test_a_recorded_checkout_is_the_last_resort(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            home = make_home(tmp, app=False)
            checkout = self.cache(tmp, name="checkout")
            watcher_launcher.codex_home = lambda: tmp / ".codex"
            resolved = watcher_launcher.resolve_plugin_root(
                {"mode": "local", "home": str(home), "plugin_root": str(checkout)})
            self.assertEqual(resolved, checkout)

    def test_nothing_installed_resolves_to_nothing(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            watcher_launcher.codex_home = lambda: tmp / ".codex"
            self.assertIsNone(watcher_launcher.resolve_plugin_root(
                {"mode": "plugin", "plugin_name": "codex-auto-resume",
                 "home": str(tmp / "nowhere")}))


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.release = json.loads(RELEASE.read_text(encoding="utf-8"))

    def test_the_download_location_is_pinned_and_https(self):
        download = self.release["download"]
        self.assertTrue(download.startswith(
            "https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/download/"),
            download)
        # The version is substituted, never supplied: the plugin can only ask for the
        # release that matches itself.
        self.assertIn("{version}", download)
        self.assertIn("{version}", self.release["archive"])
        self.assertTrue(self.release["archive"].endswith(".zip"))

    def test_the_templates_are_exactly_these(self):
        """Pinned exactly. A merged edit to either would change what every future install
        downloads - the security review found `archive` accepted a path-traversal value
        with the whole suite green."""
        self.assertEqual(self.release["download"],
                         "https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/download/v{version}/")
        self.assertEqual(self.release["archive"], "CodexAutoResume-v{version}-win-x64.zip")

    def test_a_tagged_current_version_is_pinned(self):
        """Once the current version has been tagged here, its pin must not go missing.

        The released-versions check exempts the current version, because its digest cannot
        exist until it is published - which also let the current version's pin be deleted
        after publication with the suite green. Where the tag is visible, that is caught.
        Skipped where the checkout has no tags, and on the release run for that very tag,
        which is the one moment the pin legitimately does not exist yet.
        """
        import os
        import subprocess
        from codex_auto_resume import config
        current = config.version()
        if os.environ.get("GITHUB_REF") == "refs/tags/v" + current:
            self.skipTest("this is the release run for the current version")
        tags = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "v" + current],
                              capture_output=True, text=True).stdout.split()
        if not tags:
            self.skipTest("v%s is not tagged in this checkout" % current)
        self.assertTrue(self.release["sha256"].get(current),
                        "v%s is tagged but its digest is not pinned" % current)

    def test_no_other_substitution_is_possible(self):
        for value in (self.release["download"], self.release["archive"]):
            self.assertEqual(set(re.findall(r"\{(\w+)\}", value)), {"version"})

    def test_digests_are_absent_or_real(self):
        for version, digest in self.release["sha256"].items():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")
            if digest is not None:
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_every_released_version_is_pinned(self):
        """Released versions carry a digest; the one being developed need not appear.

        This used to demand an entry for the current version too, so bumping the manifest
        turned the suite red until someone hand-added `"0.5.5": null` - a manual step
        whose only purpose was to satisfy this test. The bootstrap already handles a
        missing version exactly as it handles a null one: it verifies against the
        published `.sha256` sidecar instead and says out loud that it did.

        What is worth checking is the opposite direction: that a version which has been
        released did not stay unpinned because someone forgot the post-release commit.

        Checking it means looking at the versions that shipped, not at the entries that
        happen to be here. An earlier version of this test filtered `release.json` for a
        `null` digest - which could only ever see a placeholder somebody had written, and
        the practice of writing them was removed in the same release. The forgotten pin it
        claimed to catch leaves no entry at all, so nothing was being checked.

        The shipped list is the changelog's own headings, which is the one place a release
        is recorded that cannot be forgotten separately.
        """
        from codex_auto_resume import config
        current = config.version()
        shipped = [found.group(1) for found in
                   re.finditer(r"^##\s+v(\d+\.\d+\.\d+)", CHANGELOG_TEXT, re.M)]
        self.assertTrue(shipped, "no released versions found in the changelog")
        digests = self.release["sha256"]
        # The bootstrap only pins from 0.5.2 onwards; earlier releases predate the plugin
        # route entirely and are not fetchable by it.
        pinnable = [version for version in shipped
                    if version >= "0.5.2" and version != current]
        unpinned = [version for version in pinnable if not digests.get(version)]
        self.assertEqual(unpinned, [],
                         "these versions were released but never had their digest pinned")


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.text = BOOTSTRAP.read_text(encoding="utf-8")

    def test_nothing_downloaded_reaches_a_shell(self):
        for forbidden in ("Invoke-Expression", "iex ", "| iex", "DownloadString"):
            self.assertNotIn(forbidden, self.text, forbidden)

    def test_it_never_asks_for_administrator_rights(self):
        for forbidden in ("RunAs", "Set-ExecutionPolicy", "Set-MpPreference",
                          "Add-MpPreference", "netsh "):
            self.assertNotIn(forbidden, self.text, forbidden)

    def test_it_verifies_before_it_executes(self):
        # Order matters more than presence: extraction and the installer call both have
        # to come after the digest comparison and the contents check.
        digest = self.text.index("Get-FileHash")
        contents = self.text.index("Test-Archive -Zip")
        extract = self.text.index("ExtractToDirectory")
        run = self.text.index("& $installer")
        self.assertLess(digest, contents)
        self.assertLess(contents, extract)
        self.assertLess(extract, run)

    def test_a_failed_check_leaves_nothing_behind(self):
        self.assertIn("Remove-Item -Recurse -Force $work", self.text)

    def test_only_github_hosts_are_accepted(self):
        allowed = re.search(r"\$AllowedHosts\s*=\s*@\(([^)]*)\)", self.text)
        self.assertIsNotNone(allowed)
        hosts = re.findall(r"'([^']+)'", allowed.group(1))
        self.assertTrue(hosts)
        for host in hosts:
            self.assertTrue(host == "github.com" or host.endswith(".githubusercontent.com"), host)

    def test_the_version_it_fetches_cannot_be_supplied(self):
        # No parameter feeds the URL. -ArchivePath names a local file, which is checked
        # the same way as a download, and -Force and -NoStartup are switches.
        parameters = re.search(r"param\((.*?)\n\)", self.text, re.S).group(1)
        self.assertEqual(set(re.findall(r"\$(\w+)", parameters)),
                         {"Force", "NoStartup", "ArchivePath"})

    def test_required_contents_match_the_release_workflow(self):
        # Two lists of the same thing, in two languages, in two files. They drift.
        def entries(text, marker):
            block = text[text.index(marker):]
            return set(re.findall(r"'((?:payload|install|Install)[^']*)'",
                                  block[:block.index(")")]))
        mine = entries(self.text, "$required = @(")
        theirs = entries(WORKFLOW.read_text(encoding="utf-8"), "foreach ($required in @(")
        self.assertTrue(theirs, "the release workflow's required list was not found")
        self.assertTrue(theirs.issubset(mine),
                        "the bootstrap accepts an archive the release would reject: "
                        + str(sorted(theirs - mine)))


class ArgumentQuotingTests(unittest.TestCase):
    r"""A path with a space must survive the trip to `codex`.

    `Start-Process -ArgumentList` joins its array with single spaces and quotes nothing,
    so a home under `C:\Users\Example User\` reached codex as two arguments: the
    marketplace was never registered, the failure was a warning rather than an error,
    and the installer still finished with "Installed and running." The registry side has
    had the equivalent right since v0.5.0, which is why the two are checked together.
    """

    def test_the_installer_quotes_every_argument_it_passes_to_codex(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("function Quote-Argument", text)
        # The array must not reach Start-Process unquoted.
        self.assertNotIn("-ArgumentList $Arguments", text)
        self.assertRegex(text, r"Quote-Argument \$_.*-join ' '")

    def test_the_quoting_follows_the_same_backslash_rule_as_the_registry_side(self):
        # Doubling a run of backslashes only before a quote is the CommandLineToArgvW
        # rule; getting it wrong turns `D:\` into an unterminated quoted string that
        # swallows the next argument.
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("$slashes * 2 + 1", text)
        self.assertIn("$slashes * 2", text)
        source = (ROOT / "src" / "codex_auto_resume" / "startup.py").read_text(encoding="utf-8")
        self.assertIn("slashes * 2 + 1", source, "the two sides must agree")


class HostPortabilityTests(unittest.TestCase):
    def test_the_final_host_check_reads_both_powershell_shapes(self):
        """Windows PowerShell and PowerShell 7 name it differently.

        5.1 hands back an HttpWebResponse, which has ResponseUri. 7 hands back an
        HttpResponseMessage, which does not have that property at all. Under
        Set-StrictMode reading the missing one throws - so a check written for 5.1 only
        does not weaken security on pwsh, it fails every download on pwsh.
        """
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("ResponseUri", text)
        self.assertIn("RequestMessage", text)
        # And neither present has to be a refusal, not a pass.
        self.assertRegex(text, r"if \(\$null -eq \$final\)[\s\S]{0,200}?throw")

    def test_an_unverified_archive_is_not_announced_as_verified(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        unchecked = text.index("NOT checked against anything")
        line_start = text.rindex(chr(10), 0, unchecked)
        self.assertNotIn("Ok ", text[line_start:unchecked],
                         "the case where nothing was compared must not print an [ok]")

    def test_the_mcp_launcher_honours_the_same_home_override(self):
        # Every other component resolves CODEX_AUTO_RESUME_PLUGIN_HOME first. The panel's
        # launcher read only the older, narrower CODEX_AUTO_RESUME_HOME, so moving the
        # installation left the MCP server looking for it in the profile.
        text = (ROOT / "gui" / "McpLauncher.cs").read_text(encoding="utf-8")
        first = text.index("CODEX_AUTO_RESUME_PLUGIN_HOME")
        second = text.index('"CODEX_AUTO_RESUME_HOME"')
        self.assertLess(first, second, "the plugin home must be consulted first")


class ReleaseImmutabilityTests(unittest.TestCase):
    """A published version names one archive, for as long as the release exists.

    The plugin's bootstrap pins a version's SHA-256 and refuses anything else, so a
    workflow that can replace a published asset can silently make every install of that
    version fail - or, worse, succeed with different bytes than the digest describes.
    The workflow used to have exactly that: a dispatch that rebuilt an existing tag and
    re-uploaded over its assets with `--clobber`.
    """

    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_nothing_can_overwrite_a_published_asset(self):
        # The comment explaining why it is gone is allowed to say the word; a command
        # is not. Look only at what would run.
        commands = [line for line in self.workflow.splitlines()
                    if "--clobber" in line and not line.lstrip().startswith("#")]
        self.assertEqual(commands, [], "a published release asset must not be replaceable")

    def test_publishing_is_refused_when_the_version_already_has_assets(self):
        self.assertIn("Refuse to republish a version that already has assets", self.workflow)
        self.assertIn("gh release view", self.workflow)
        self.assertRegex(self.workflow, r"A published version is immutable")

    def test_the_refusal_runs_before_the_publish(self):
        self.assertLess(self.workflow.index("Refuse to republish"),
                        self.workflow.index("Publish the GitHub release"))

    def test_a_dispatch_cannot_publish(self):
        """The dry run may build and verify; it may not create or change a release."""
        # Every step that talks to the releases API lives in the publish job, and that
        # job - not each step - is gated on a tag *push*. Gating steps on
        # startsWith(github.ref, 'refs/tags/v') alone was the old shape, and a dispatch
        # whose ref is a tag satisfies it.
        publish = self.workflow.index("\n  publish:")
        guard = "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
        self.assertIn(guard, self.workflow[publish:self.workflow.index("steps:", publish)])
        for marker in ("gh release create", "gh release view"):
            with self.subTest(marker):
                self.assertGreater(self.workflow.index(marker), publish,
                                   "%s must be reachable only from the publish job" % marker)

    def test_the_dispatch_input_no_longer_names_a_release(self):
        # It used to be `tag`, and it meant "rebuild this published release".
        self.assertNotRegex(self.workflow, r"inputs:\s+tag:")
        self.assertIn("Never publishes.", self.workflow)


class InstallerLockTests(unittest.TestCase):
    def test_the_installer_takes_the_lock_before_it_touches_anything(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("System.Threading.Mutex", text)
        self.assertLess(text.index("System.Threading.Mutex"), text.index("$InstallHome ="))

    def test_an_abandoned_lock_is_taken_rather_than_treated_as_contention(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("AbandonedMutexException", text)

    def test_the_bootstrap_locks_only_where_it_bypasses_the_installer(self):
        """The download path must not lock; the repair path must.

        Almost every route into the installation goes through install.ps1 and is
        serialised by the lock there, so the bootstrap deliberately does not take one
        around the download - that would only refuse a second bootstrap earlier than
        the moment it could actually collide. The exception is the already-installed
        branch, which skips install.ps1 entirely and runs setup itself: it writes the
        same registrations, so it takes the same lock, and it used to take none.
        """
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertEqual(text.count("System.Threading.Mutex"), 1,
                         "exactly one lock, in the repair branch")
        lock = text.index("System.Threading.Mutex")
        # It has to sit in the already-installed branch, which ends before the download.
        self.assertLess(lock, text.index("Downloading v"),
                        "the lock belongs to the repair branch, not the download")
        self.assertIn("AbandonedMutexException", text)


if __name__ == "__main__":
    unittest.main()
