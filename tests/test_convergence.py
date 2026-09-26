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
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import plugin_setup                    # noqa: E402
import watcher_launcher                # noqa: E402

BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
RELEASE = ROOT / "scripts" / "release.json"


def block(text, start, end):
    """One region of a script, lifted verbatim between two markers rather than by line
    number, so reordering a file cannot quietly point a test at something else."""
    first = text.index(start)
    return text[first:text.index(end, first)]


CHANGELOG_TEXT = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
INSTALLER = ROOT / "build" / "install" / "install.ps1"
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

    def test_a_runtime_without_pythonw_is_not_an_installation(self):
        """It used to be one, with python.exe registered in its place: Windows starts the Run
        value and the notification button plainly, so each opened a console window, and the
        sign-in watcher's stayed for the whole session. Setup now says the runtime is not
        installed and prints the command that installs it again."""
        with tempfile.TemporaryDirectory() as name:
            home = make_home(Path(name))
            (home / "runtime" / "pythonw.exe").unlink()
            self.assertFalse(plugin_setup.installed(home))
            self.assertIsNone(plugin_setup.bundled_python(home))
            self.assertEqual(plugin_setup.bundled_python(home, windowless=False), home / "runtime" / "python.exe")

    def test_no_route_names_a_console_interpreter(self):
        with tempfile.TemporaryDirectory() as name:
            home = make_home(Path(name))
            (home / "runtime" / "pythonw.exe").unlink()
            # Not the bundled python.exe beside the missing pythonw.exe, whatever else happens.
            with mock.patch.object(plugin_setup.startup.sys, "executable", str(home / "runtime" / "python.exe")):
                with self.assertRaises(plugin_setup.startup.StartupError):
                    plugin_setup.python_for_watcher(home)
                with self.assertRaises(plugin_setup.startup.StartupError):
                    plugin_setup.watcher_command(home)
                with self.assertRaises(plugin_setup.startup.StartupError):
                    plugin_setup.notification_command(home)
                with mock.patch.object(plugin_setup, "App") as app,                         mock.patch.object(plugin_setup.subprocess, "Popen") as popen:
                    app.return_value.watcher_running.return_value = False
                    self.assertEqual(plugin_setup.start_watcher(home), "not-started")
                popen.assert_not_called()

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
        Skipped where the checkout has no tags, and on the commit the tag points at: the digest
        is of the archive built from that commit, so the commit cannot carry it, and its pin
        is always a later commit. That was said first of the release run for the tag alone,
        and main's own run for the same commit went red at v0.6.6 - its checkout saw the tag
        pushed moments earlier, the tree it tested could not hold the pin, and the pin commit
        after it was green. Skipped too where the tag exists but the release it points at is a
        pre-release, which `prerelease` records: `latest` never answers with one, so nothing
        is served it and nothing can be verified against a pin it does not have.
        """
        import os
        import subprocess
        from codex_auto_resume import config
        current = config.version()
        if os.environ.get("GITHUB_REF") == "refs/tags/v" + current:
            self.skipTest("this is the release run for the current version")
        if current in self.release.get("prerelease", []):
            self.skipTest("v%s is tagged, and published as a pre-release" % current)
        tags = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "v" + current],
                              capture_output=True, text=True).stdout.split()
        if not tags:
            self.skipTest("v%s is not tagged in this checkout" % current)
        tagged, head = (subprocess.run(["git", "-C", str(ROOT), "rev-parse", ref], capture_output=True,
                                       text=True).stdout.strip() for ref in ("v%s^{commit}" % current, "HEAD"))
        if tagged and tagged == head:
            self.skipTest("this is the commit v%s tags, which cannot carry its own digest" % current)
        self.assertTrue(self.release["sha256"].get(current),
                        "v%s is tagged but its digest is not pinned" % current)

    def test_a_prerelease_is_the_version_being_developed_and_carries_no_digest(self):
        """The exemption above is only safe while it cannot outlive what it exempts.

        A pre-release entry says "this tag exists and nothing is served it yet". Left behind
        after the version was published, it would go on excusing a missing pin for ever - so
        it may name the version under development and nothing else, which empties it at the
        next bump, and it may not name a version that already carries a digest.
        """
        from codex_auto_resume import config
        listed = self.release.get("prerelease", [])
        self.assertIsInstance(listed, list)
        self.assertEqual([version for version in listed if version != config.version()], [],
                         "a pre-release entry outlived the version it was written for")
        for version in listed:
            self.assertIsNone(self.release["sha256"].get(version),
                              "v%s is pinned, so it is published; take it off `prerelease`" % version)

    def test_no_other_substitution_is_possible(self):
        for value in (self.release["download"], self.release["archive"]):
            self.assertEqual(set(re.findall(r"\{(\w+)\}", value)), {"version"})

    def test_digests_are_absent_or_real(self):
        for version, digest in self.release["sha256"].items():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")
            if digest is not None:
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_the_advanced_edition_has_a_template_of_its_own(self):
        """A second constant, pinned exactly as the first is, and never a variation of it. The
        top-level keys stay the standard edition's: every published bootstrap builds the
        standard archive's name from its own copy of `archive`, so that key cannot change what
        it means."""
        advanced = self.release["advanced"]
        self.assertEqual(set(advanced), {"archive", "sha256", "since"})
        self.assertEqual(advanced["archive"], "CodexAutoResume-Advanced-v{version}-win-x64.zip")
        self.assertEqual(set(re.findall(r"\{(\w+)\}", advanced["archive"])), {"version"})
        self.assertNotEqual(advanced["archive"], self.release["archive"])
        self.assertEqual(advanced["since"], "0.6.11")
        self.assertIsInstance(advanced["sha256"], dict)

    def test_advanced_digests_are_real_and_pinned_with_the_standard_ones(self):
        """The same shape as the standard table, only for versions the edition exists in, and
        pinned in the same commit: a version with one edition's digest and not the other's is a
        release verified by halves."""
        def number(version):
            return tuple(int(part) for part in version.split("."))
        advanced = self.release["advanced"]
        since = number(advanced["since"])
        for version, digest in advanced["sha256"].items():
            with self.subTest(version):
                self.assertRegex(version, r"^\d+\.\d+\.\d+$")
                self.assertGreaterEqual(number(version), since)
                if digest is not None:
                    self.assertRegex(digest, r"^[0-9a-f]{64}$")
        standard = {version for version, digest in self.release["sha256"].items()
                    if digest and number(version) >= since}
        self.assertEqual({version for version, digest in advanced["sha256"].items() if digest},
                         standard)

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
        is recorded that cannot be forgotten separately - a release's, that is: a pre-release
        such as `v0.6.6-beta` has an entry too, and is not a version anything pins.
        """
        from codex_auto_resume import config
        current = config.version()
        shipped = [found.group(1) for found in
                   re.finditer(r"^##\s+v(\d+\.\d+\.\d+)(?![\w.-])", CHANGELOG_TEXT, re.M)]
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

    def test_the_digest_is_computed_without_depending_on_a_cmdlet_resolving(self):
        """`Get-FileHash` is not available everywhere this script runs.

        It has failed to resolve twice while every other cmdlet in the same script
        still worked: under the release runner's PSModulePath, which is why
        `build/make_gui.ps1` stopped using it, and in the process the Dashboard's
        update button starts on a user's machine, where the archive downloaded and
        then could not be verified. The script refused to install, which was right,
        and the update was unusable, which was not.

        The digest decides whether anything is installed at all, so it is computed
        with the runtime PowerShell is already hosted in.
        """
        self.assertNotIn("(Get-FileHash", self.text,
                         "the one number that gates installation must not depend on "
                         "module autoloading")
        self.assertIn("[Security.Cryptography.SHA256]::Create()", self.text)

    def test_no_shipped_powershell_asks_for_that_cmdlet(self):
        """The installer runs in the same places the bootstrap does."""
        for script in sorted((ROOT / "scripts").glob("*.ps1")) + \
                sorted((ROOT / "build" / "install").glob("*.ps1")):
            with self.subTest(script.name):
                body = script.read_text(encoding="utf-8")
                calls = [line for line in body.splitlines()
                         if "Get-FileHash" in line and not line.lstrip().startswith("#")
                         and "`Get-FileHash`" not in line]
                self.assertEqual(calls, [], "%s calls Get-FileHash" % script.name)

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
        """No parameter feeds a URL.

        -ArchivePath names a local file, which is checked the same way as a download;
        everything else is a switch and carries no value at all. -Update does move the
        version that is fetched, but not to anywhere a caller chooses: the resolver takes
        it from a redirect under this repository and rebuilds it out of three integers,
        which `tests/test_update_check.py` exercises against the shipped function.
        -Compatibility (v0.6.5) is a switch too: the compatibility data's address is one
        constant, and nothing a caller passes reaches it. -Edition (v0.6.11) carries a value,
        but one of two words the parameter itself closes, and the word only chooses which of
        two constant templates in release.json names the archive; it is never spliced.
        """
        parameters = re.search(r"param\((.*?)\n\)", self.text, re.S).group(1)
        self.assertEqual(set(re.findall(r"\$(\w+)", parameters)),
                         {"Force", "NoStartup", "ArchivePath", "CheckOnly", "Update",
                          "Compatibility", "Edition"})
        values = [name for name in re.findall(r"\[(\w+)\]\$(\w+)", parameters)]
        self.assertEqual([name for kind, name in values if kind != "switch"], ["ArchivePath", "Edition"])
        self.assertIn("[ValidateSet('Standard', 'Advanced')]\n    [string]$Edition", parameters)
        # And neither value reaches the URL the archive is fetched from.
        fetch = self.text[self.text.index("$base = $release.download"):]
        self.assertNotIn("$ArchivePath", fetch[:fetch.index("Get-Remote")])
        self.assertNotIn("$Edition", fetch[:fetch.index("Get-Remote")])
        named = self.text[self.text.index("    $name = "):]
        named = named[:named.index("\n")]
        self.assertNotIn("$Edition", named, "the typed word, rather than the settled one")
        self.assertIn(".archive.Replace('{version}', $target)", named)

    def test_the_update_check_never_parses_what_the_server_sends(self):
        """The answer is the URL the request ended at. Nothing reads the page."""
        resolver = block(self.text, "function Get-NewestPublishedVersion", "\n}\n")
        self.assertIn("-Method Head", resolver, "a body that is never read should not be sent")
        for forbidden in ("ConvertFrom-Json", ".Content", "ParsedHtml", "-Body"):
            self.assertNotIn(forbidden, resolver, forbidden)

    def test_the_redirect_has_to_land_under_this_exact_repository(self):
        resolver = block(self.text, "function Get-NewestPublishedVersion", "\n}\n")
        self.assertIn("$expected = '/' + $Release.owner + '/' + $Release.repo + '/releases/tag/'",
                      resolver)
        # Ordinal, and a prefix rather than a substring: `-like '*repo*'` would accept a
        # fork, and a culture-sensitive comparison is not a thing to rest this on.
        self.assertIn("StartsWith($expected, [StringComparison]::Ordinal)", resolver)
        self.assertNotIn("-like", resolver)
        self.assertNotIn("-match $Release", resolver)

    def test_the_version_it_learned_is_rebuilt_from_integers(self):
        resolver = block(self.text, "function Get-NewestPublishedVersion", "\n}\n")
        self.assertIn("[int]$parts[0]", resolver)
        self.assertIn("[int]$parts[1]", resolver)
        self.assertIn("[int]$parts[2]", resolver)

    def test_the_four_answers_have_four_codes(self):
        codes = dict(re.findall(r"\$(Exit\w+)\s*=\s*(\d+)", self.text))
        # -Compatibility (v0.6.5) answers refreshed / unavailable with the same 0 and 12,
        # and has one answer of its own - the data arrived and was refused - on its own code.
        refused = codes.pop("ExitCompatibilityRefused")
        self.assertNotIn(refused, codes.values(), "the refresh's own answer shares a code")
        # v0.6.11: an install refused because the other edition is there, which is no answer
        # to the update question and must never read as one - nor as the refresh's refusal.
        other = codes.pop("ExitOtherEdition")
        self.assertNotIn(other, list(codes.values()) + [refused], "the edition refusal shares a code")
        self.assertEqual(set(codes), {"ExitCurrent", "ExitAvailable", "ExitLocalNewer",
                                      "ExitUnavailable"})
        self.assertEqual(len(set(codes.values())), 4, "two answers share a code")
        # "Could not ask" must never be the code for "you are up to date".
        self.assertNotEqual(codes["ExitUnavailable"], codes["ExitCurrent"])
        self.assertEqual(codes["ExitCurrent"], "0")

    def test_nothing_checks_for_an_update_unless_asked(self):
        """No timer, no schedule, no check on the way to an ordinary install."""
        definition = self.text.index("function Get-NewestPublishedVersion")
        calls = [i for i in range(len(self.text))
                 if self.text.startswith("Get-NewestPublishedVersion", i)
                 and i != definition + len("function ")]
        self.assertEqual(len(calls), 1, "the resolver is reached from more than one place")
        # And that one call sits inside the branch only a switch opens.
        guarded = block(self.text, "if ($CheckOnly -or $Update) {", "    $target = $newest")
        self.assertIn("Get-NewestPublishedVersion -Release $release", guarded)

    def test_required_contents_match_the_release_workflow(self):
        # Two lists of the same thing, in two languages, in two files. They drift.
        def entries(text, marker):
            block = text[text.index(marker):]
            return set(re.findall(r"'((?:payload|install|Install)[^']*)'",
                                  block[:block.index(")")]))
        mine = entries(self.text, "$required = @(")
        # The payload root's files are required too, through their own list (Test-Archive).
        root = self.text[self.text.index("$rootFiles = @("):]
        mine |= {"payload/" + name for name in re.findall(r"'([^']+)'", root[:root.index(")")])}
        theirs = entries(WORKFLOW.read_text(encoding="utf-8"), "foreach ($required in @(")
        self.assertTrue(theirs, "the release workflow's required list was not found")
        self.assertTrue(theirs.issubset(mine),
                        "the bootstrap accepts an archive the release would reject: "
                        + str(sorted(theirs - mine)))
        self.assertTrue(mine.issubset(theirs),
                        "the release would publish an archive the bootstrap refuses: "
                        + str(sorted(mine - theirs)))


class EditionReleaseTests(unittest.TestCase):
    """The release names, checks and tells apart the two editions' archives as the bootstrap does.

    An installed copy fetches the archive its own release.json names for its edition, and
    installs it only if its Test-Archive, asked for that edition, accepts it. The release
    workflow names the same two archives in both of its jobs, checks the same entries in the
    build job, and tells the editions apart in the publish job - which runs nothing of the
    repository's, so it does that with `unzip` and `grep`. Two rules, written four times in
    three languages: they drift, so they are compared here.
    """

    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.build = self.workflow[:self.workflow.index("\n  publish:")]
        self.publish = self.workflow[self.workflow.index("\n  publish:"):]
        release = json.loads(RELEASE.read_text(encoding="utf-8"))
        self.templates = {"standard": release["archive"], "advanced": release["advanced"]["archive"]}
        test_archive = block(BOOTSTRAP.read_text(encoding="utf-8"), "function Test-Archive", "\n}\n")
        self.package = re.search(r"\$package = '([^']+)'", test_archive).group(1)
        self.skill = re.search(r"\$skill = '([^']+)'", test_archive).group(1)

    def step(self, text, name):
        start = text.index("- name: %s\n" % name)
        return text[start:text.index("\n      - name:", start)]

    def test_both_jobs_name_each_archive_by_its_template(self):
        for edition, template in self.templates.items():
            with self.subTest(edition):
                built = "build/dist/" + template.replace("{version}", "$($env:VERSION)")
                self.assertIn('%s = "%s"' % (edition, built), self.build)
                published = "dist/" + template.replace("{version}", "${{ needs.build.outputs.version }}")
                self.assertIn(": %s\n" % published, self.publish)
        named = re.findall(r'(?m)^ +(\w+) = "build/dist/[^"]+\.zip"\s*$', self.build)
        self.assertEqual(named, list(self.templates), "the build job checks an archive of no edition")

    def test_every_archive_is_held_to_the_required_list(self):
        """The list itself is BootstrapTests' (test_required_contents_match_the_release_workflow);
        this is that each edition's archive is held to it, since the bootstrap holds both."""
        check = self.step(self.build, "Check each archive is what it claims to be")
        self.assertLess(check.index("foreach ($edition in $archives.Keys)"),
                        check.index("foreach ($required in @("))

    def test_the_advanced_archive_needs_what_the_bootstrap_needs_of_it(self):
        check = self.step(self.build, "Check each archive is what it claims to be")
        self.assertIn("$package = '%s__init__.py'" % self.package, check)
        self.assertIn("if ($edition -eq 'advanced' -and $names -notcontains $package)", check)

    def test_the_publish_job_tells_the_editions_apart_by_the_bootstraps_rule(self):
        check = self.step(self.publish, "Check each archive is its own edition")
        for zip_ in ("$STANDARD_ZIP", "$ADVANCED_ZIP"):
            self.assertIn('unzip -Z1 "%s" | tr \'\\\\\' \'/\'' % zip_, check)
        found = re.search(r"grep -iE '([^']+)' <<<\"\$standard\"", check)
        self.assertIsNotNone(found, "the standard archive's listing is not searched")
        refused = re.compile(found.group(1), re.IGNORECASE)
        # Every name the bootstrap refuses in a standard archive, in any case, and nothing of core.
        for prefix in (self.package, self.skill):
            for name in (prefix + "__init__.py", (prefix + "SKILL.md").upper()):
                with self.subTest(name):
                    self.assertIsNotNone(refused.search(name))
        for name in ("payload/app/src/codex_auto_resume/edition.py",
                     "payload/app/skills/codex-auto-resume/SKILL.md", "payload/runtime/python.exe"):
            with self.subTest(name):
                self.assertIsNone(refused.search(name))
        self.assertIn("grep -qx '%s__init__.py' <<<\"$advanced\"" % self.package, check)

    def test_the_publish_job_reads_each_name_as_the_extraction_writes_it(self):
        """ExtractToDirectory writes 'src/./x', 'src//x' and 'src/x./y' into src/x - Windows drops
        a segment's trailing dots and spaces - so the grep has to read them there too, as the
        bootstrap's Test-Archive does."""
        check = self.step(self.publish, "Check each archive is its own edition")
        written = re.search(r"written='([^']+)'", check)
        self.assertIsNotNone(written, "the listing is not normalised")
        for zip_ in ("$STANDARD_ZIP", "$ADVANCED_ZIP"):
            self.assertIn('unzip -Z1 "%s" | tr \'\\\\\' \'/\' | sed -E "$written"' % zip_, check)
        sed = shutil.which("sed")
        if sed is None:
            self.skipTest("no sed here to run the job's program with")
        package = self.package.rstrip("/").rsplit("/", 1)[-1]
        names = ["payload/app/src/./%s/__init__.py" % package, "payload/app/src//%s/__init__.py" % package,
                 "./payload/app/src/././%s/plug.py" % package, "payload/runtime/python.exe",
                 "payload/app/src/%s./__init__.py" % package, "payload/app/src/%s. . /plug.py" % package,
                 "payload/app/.codex-plugin/plugin.json"]
        done = subprocess.run([sed, "-E", written.group(1)], input="\n".join(names) + "\n",
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(),
                         [self.package + "__init__.py"] * 2
                         + [self.package + "plug.py", "payload/runtime/python.exe"]
                         + [self.package + "__init__.py", self.package + "plug.py",
                            "payload/app/.codex-plugin/plugin.json"])

    def test_both_editions_are_built_audited_and_checked_before_anything_is_kept(self):
        order = [self.build.index(marker) for marker in (
            "./build/make_gui.ps1 -Edition advanced",
            "run: python build/make_release.py --edition standard",
            "run: python build/make_release.py --edition advanced",
            "- name: Check each archive is what it claims to be",
            "run: python build/edition_audit.py",
            "run: python build/legacy_bootstraps.py",
            "- name: Keep the archives even when nothing is published")]
        self.assertEqual(order, sorted(order))


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
