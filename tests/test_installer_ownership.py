"""Nothing is destroyed unless the installer can prove it owns it.

The installer is PowerShell, and PowerShell is where the destructive operations live:
deleting `app/` and `runtime/`, sweeping `*.old-*`, purging `config/` and `logs/`,
force-stopping a running MCP launcher, removing a Codex marketplace. Every one of those
used to act on a *name* - a directory called `app` under whatever `$InstallHome` pointed
at, a process called `codex-auto-resume-mcp.exe`, a marketplace called
`codex-auto-resume-windows` - and a name is not ownership.

These tests drive the real functions out of `install/install.ps1` rather than a copy of
them, by extracting the helper block and dot-sourcing it into a throwaway PowerShell
process. That costs a second per test and buys the thing that matters: if someone edits
the installer, these fail. A reimplementation in Python would only ever test itself.

Nothing here touches the user's real installation, registry or processes. The fixtures
are temporary directories, and the only process ever started is a copy of `cmd.exe`
renamed to look like ours - which is precisely the case that must NOT be killed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install" / "install.ps1"
WINDOWS = os.name == "nt"

# The block of pure helpers, lifted verbatim. Taking it by markers rather than by line
# number means a reordering of the file cannot silently test the wrong thing.
HELPERS_FROM = "function Quote-Argument"
HELPERS_TO = "function Invoke-Setup"


def helper_source() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    start, end = text.index(HELPERS_FROM), text.index(HELPERS_TO)
    return text[start:end]


def ps_literal(value) -> str:
    r"""One value as a PowerShell single-quoted string.

    Backslash is not an escape character in PowerShell - backtick is - so escaping
    separators the way one would for C or Python turns `C:\Users` into a path with
    doubled separators. `GetFullPath` happens to normalise those away, which is why the
    path comparisons passed anyway while the argument round-trip, which compares
    verbatim, did not. Single quotes take everything literally; only a quote needs
    doubling.
    """
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as name:
        path = Path(name) / "probe.ps1"
        # PowerShell 5.1 decodes a .ps1 as the ANSI code page unless it carries a UTF-8
        # BOM, so a Unicode path in a probe would arrive mangled.
        path.write_text(helper_source() + "\n" + script, encoding="utf-8-sig")
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)


# PowerShell writes stdout in the console code page by default, so a Korean path comes
# back as replacement characters on a cp949 machine and the comparison fails for a reason
# that has nothing to do with the quoting under test.
PREAMBLE = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n"


def emit_json(expression: str) -> str:
    return (PREAMBLE + "$result = %s\n"
            "[Console]::Out.Write((ConvertTo-Json $result -Compress -Depth 6))\n") % expression


class InstallHomeProvenanceTests(unittest.TestCase):
    """Which directories the installer is allowed to call its own.

    `$InstallHome` comes from an environment variable, so the uninstaller can be pointed
    at anything. The question "is this an installation?" therefore cannot be answered by
    what the directory is called or by what it happens to contain - a `D:\\Development`
    holding `app`, `runtime`, `config` and `logs` looks exactly like one.

    This is the rule the PowerShell installer asks for through `verify-home`, so it is
    tested here once rather than approximated on both sides.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def paths(self, home):
        from codex_auto_resume import config
        return config.Paths(home)

    def look_alike(self) -> Path:
        """A stranger's directory with all four of our directory names in it."""
        home = self.root / "Development"
        for name in ("app", "runtime", "config", "logs"):
            (home / name).mkdir(parents=True)
        (home / "config" / "important.txt").write_text("theirs", encoding="utf-8")
        return home

    def test_a_look_alike_directory_is_not_an_installation(self):
        self.assertFalse(self.paths(self.look_alike()).owns_home())

    def test_a_marker_at_the_root_proves_ownership(self):
        home = self.root / "fresh"
        paths = self.paths(home)
        self.assertTrue(paths.claim_home())
        self.assertTrue(paths.owns_home())

    def test_an_installation_made_before_the_root_marker_existed_still_qualifies(self):
        # Every installation has carried a marker in `config/` since v0.1, so uninstall
        # must keep working for one that predates the root marker.
        home = self.root / "legacy"
        paths = self.paths(home)
        paths.ensure()
        self.assertFalse((home / ".owned-by-codex-auto-resume").exists())
        self.assertTrue(paths.owns_home())

    def test_a_runtime_record_naming_this_home_qualifies(self):
        home = self.root / "recorded"
        home.mkdir()
        (home / "runtime.json").write_text(json.dumps({"home": str(home)}), encoding="utf-8")
        self.assertTrue(self.paths(home).owns_home())

    def test_a_runtime_record_naming_somewhere_else_does_not(self):
        home = self.root / "lying"
        home.mkdir()
        (home / "runtime.json").write_text(
            json.dumps({"home": str(self.root / "elsewhere")}), encoding="utf-8")
        self.assertFalse(self.paths(home).owns_home())

    def test_an_unreadable_runtime_record_does_not_qualify(self):
        home = self.root / "corrupt"
        home.mkdir()
        (home / "runtime.json").write_text("{ not json", encoding="utf-8")
        self.assertFalse(self.paths(home).owns_home())

    def test_a_missing_directory_is_not_an_installation(self):
        self.assertFalse(self.paths(self.root / "nothing-here").owns_home())

    def test_a_file_where_the_home_should_be_is_not_an_installation(self):
        home = self.root / "afile"
        home.write_text("not a directory", encoding="utf-8")
        self.assertFalse(self.paths(home).owns_home())

    def test_a_junction_inside_the_home_pointing_out_is_not_confined(self):
        """The escape that matters, and the one `is_symlink()` does not see.

        A junction *as* the home is not an escape: `Paths` resolves the home on the way
        in, so the installation simply is wherever the junction points. The dangerous
        shape is a junction sitting inside an owned home and pointing somewhere else,
        because a recursive delete would follow it.
        """
        if not WINDOWS:
            self.skipTest("junctions are a Windows concern")
        home = self.root / "home"
        home.mkdir()
        outside = self.root / "outside"
        (outside / "precious").mkdir(parents=True)
        link = home / "escape"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside / "precious")],
                       capture_output=True, text=True, check=False)
        if not link.exists():
            self.skipTest("could not create an NTFS junction here")
        try:
            paths = self.paths(home)
            self.assertFalse(paths.confined(link),
                             "a junction leaving the home must not read as inside it")
            self.assertTrue(paths.confined(home / "app"))
        finally:
            try:
                link.rmdir()          # removes the link, never its target
            except OSError:
                pass


@unittest.skipUnless(WINDOWS, "the installer is PowerShell on Windows")
class PathConfinementTests(unittest.TestCase):
    """`Test-PathInside` is the gate every deletion passes through."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.home = root / "home"
        cls.outside = root / "outside"
        (cls.home / "app").mkdir(parents=True)
        (cls.outside / "precious").mkdir(parents=True)
        (cls.outside / "precious" / "keep.txt").write_text("do not delete", encoding="utf-8")
        # An NTFS junction inside the installation pointing out of it. `is_symlink()`
        # does not see these, which is exactly why the check resolves rather than
        # inspects.
        cls.junction = cls.home / "escape"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(cls.junction),
                        str(cls.outside / "precious")],
                       capture_output=True, text=True, check=False)
        cls.has_junction = cls.junction.exists()

    @classmethod
    def tearDownClass(cls):
        if cls.junction.exists():
            try:
                cls.junction.rmdir()      # removes the link, never the target
            except OSError:
                pass
        cls.temp.cleanup()

    def inside(self, child, parent) -> bool:
        done = run_powershell(emit_json("Test-PathInside %s %s"
                                        % (ps_literal(child), ps_literal(parent))))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_a_child_of_the_installation_is_inside_it(self):
        self.assertTrue(self.inside(self.home / "app", self.home))

    def test_the_installation_root_is_inside_itself(self):
        self.assertTrue(self.inside(self.home, self.home))

    def test_an_unrelated_directory_is_not_inside(self):
        self.assertFalse(self.inside(self.outside, self.home))

    def test_case_differences_do_not_make_a_path_foreign(self):
        self.assertTrue(self.inside(str(self.home).upper() + "\\APP", self.home))

    def test_a_sibling_sharing_a_prefix_is_not_inside(self):
        # `...\home-other` starts with `...\home` as a string and is a different place.
        self.assertFalse(self.inside(str(self.home) + "-other", self.home))

    def test_a_junction_escaping_the_installation_is_not_inside(self):
        if not self.has_junction:
            self.skipTest("could not create an NTFS junction here")
        self.assertFalse(self.inside(self.junction, self.home))

    def test_a_path_under_an_escaping_junction_is_not_inside(self):
        if not self.has_junction:
            self.skipTest("could not create an NTFS junction here")
        self.assertFalse(self.inside(self.junction / "keep.txt", self.home))


@unittest.skipUnless(WINDOWS, "the installer is PowerShell on Windows")
class RemoveOwnedItemTests(unittest.TestCase):
    """The deletion helper refuses anything it cannot place inside the verified root."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        (self.home / "app").mkdir(parents=True)
        (self.home / "app" / "file.txt").write_text("ours", encoding="utf-8")
        self.stranger = self.root / "stranger"
        self.stranger.mkdir()
        (self.stranger / "file.txt").write_text("theirs", encoding="utf-8")

    def remove(self, target, owned_home) -> bool:
        script = textwrap.dedent("""
            $OwnedHome = %s
            function Warn { param([string]$m) }
            %s
        """) % (ps_literal(owned_home) if owned_home else "$null",
                emit_json("Remove-OwnedItem %s" % ps_literal(target)))
        # Remove-OwnedItem lives after the helper block, so bring it along.
        text = INSTALLER.read_text(encoding="utf-8")
        start = text.index("function Remove-OwnedItem")
        end = text.index("function Invoke-Setup")
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "probe.ps1"
            path.write_text(helper_source() + text[start:end] + script, encoding="utf-8-sig")
            done = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_it_removes_a_directory_inside_the_verified_root(self):
        self.assertTrue(self.remove(self.home / "app", self.home))
        self.assertFalse((self.home / "app").exists())

    def test_it_refuses_a_directory_outside_the_verified_root(self):
        self.assertFalse(self.remove(self.stranger, self.home))
        self.assertTrue((self.stranger / "file.txt").is_file(),
                        "a foreign directory must survive untouched")

    def test_it_refuses_everything_when_the_root_was_never_verified(self):
        self.assertFalse(self.remove(self.home / "app", None))
        self.assertTrue((self.home / "app" / "file.txt").is_file())


@unittest.skipUnless(WINDOWS, "the installer is PowerShell on Windows")
class ProcessOwnershipTests(unittest.TestCase):
    """A process name is not ownership.

    The installer force-stops MCP launchers so that Codex releases the files it holds
    open. It used to match on `Name='codex-auto-resume-mcp.exe'` alone, so anything
    else running under that filename - another installation, a build, a test fixture -
    was killed by an unrelated install.

    The fixture here is a copy of `cmd.exe` under our executable's name, sitting in a
    directory that is deliberately *not* an installation. It must survive.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.foreign_dir = self.root / "somewhere-else"
        self.foreign_dir.mkdir()
        self.foreign = self.foreign_dir / "codex-auto-resume-mcp.exe"
        shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe", self.foreign)

    def start(self, executable: Path) -> subprocess.Popen:
        """A live process under our executable name, that stays alive to be asked about.

        `cmd.exe` with a redirected stdin reads end-of-file and exits immediately, so the
        first version of this fixture was dead before the question was asked and the test
        passed for the wrong reason. Waiting on a ping keeps it running.
        """
        process = subprocess.Popen(
            [str(executable), "/c", "ping", "-n", "60", "127.0.0.1"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.addCleanup(self.stop, process)
        for _ in range(50):
            if process.poll() is None:
                break
            time.sleep(0.05)
        return process

    @staticmethod
    def stop(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass

    def owned_process_ids(self, roots) -> list:
        joined = ", ".join(ps_literal(r) for r in roots)
        done = run_powershell(emit_json(
            "@(Get-OwnedMcpProcess -Roots @(%s) | ForEach-Object { $_.ProcessId })" % joined))
        self.assertEqual(done.returncode, 0, done.stderr)
        value = json.loads(done.stdout) if done.stdout.strip() else []
        return value if isinstance(value, list) else [value]

    def test_a_foreign_process_with_our_name_is_never_owned(self):
        # `cmd /k` idles instead of exiting, so the process is genuinely running while
        # the question is asked.
        process = self.start(self.foreign)
        installation = self.root / "home"
        (installation / "app").mkdir(parents=True)
        # It has to be genuinely running, or the check below proves nothing.
        self.assertIsNone(process.poll(), "the fixture process died before it was checked")
        self.assertNotIn(process.pid, self.owned_process_ids([installation]),
                         "a same-named process outside the installation must not be owned")

    def test_a_process_inside_the_installation_is_owned(self):
        installation = self.root / "home"
        mcp = installation / "app" / "mcp"
        mcp.mkdir(parents=True)
        ours = mcp / "codex-auto-resume-mcp.exe"
        shutil.copyfile(self.foreign, ours)
        process = self.start(ours)
        self.assertIsNone(process.poll(), "the fixture process died before it was checked")
        self.assertIn(process.pid, self.owned_process_ids([installation]))


@unittest.skipUnless(WINDOWS, "the installer is PowerShell on Windows")
class ArgumentQuotingTests(unittest.TestCase):
    """Issue #3: a path with a space has to reach Codex as one argument.

    Checked by round-tripping through `CommandLineToArgvW`, the function Windows itself
    uses to split a command line, rather than by eyeballing the quoting rules.
    """

    def parsed(self, arguments) -> list:
        joined = ", ".join(ps_literal(a) for a in arguments)
        # Written flat rather than through textwrap.dedent: a PowerShell here-string's
        # closing `'@` has to sit at column zero, and an indented block that dedent
        # cannot fully strip makes the whole script a parse error with no output at all.
        script = PREAMBLE + "\n".join([
            r"Add-Type -Namespace Probe -Name Cmd -MemberDefinition @'",
            r'[DllImport("shell32.dll", SetLastError=true)] public static extern IntPtr CommandLineToArgvW(',
            r"    [MarshalAs(UnmanagedType.LPWStr)] string lpCmdLine, out int pNumArgs);",
            r"'@",
            r"$line = ((@(%s) | ForEach-Object { Quote-Argument $_ }) -join ' ')" % joined,
            r"$n = 0",
            r'$ptr = [Probe.Cmd]::CommandLineToArgvW("prog.exe " + $line, [ref]$n)',
            r"$out = @()",
            r"for ($i = 1; $i -lt $n; $i++) {",
            r"    $p = [Runtime.InteropServices.Marshal]::ReadIntPtr($ptr, $i * [IntPtr]::Size)",
            r"    $out += [Runtime.InteropServices.Marshal]::PtrToStringUni($p)",
            r"}",
            r"[Console]::Out.Write((ConvertTo-Json @($out) -Compress))",
        ])
        done = run_powershell(script)
        self.assertEqual(done.returncode, 0, done.stderr)
        value = json.loads(done.stdout)
        return value if isinstance(value, list) else [value]

    def round_trip(self, arguments):
        self.assertEqual(self.parsed(arguments), list(arguments))

    def test_a_home_with_a_space_survives(self):
        self.round_trip(["plugin", "marketplace", "add",
                         r"C:\Users\Example User\.codex-auto-resume\app"])

    def test_a_folder_with_spaces_and_a_dash_survives(self):
        # `OneDrive - Company` also injects a bare `-` into option parsing when unquoted.
        self.round_trip(["plugin", "marketplace", "add",
                         r"C:\Users\Example User\OneDrive - Company\.codex-auto-resume\app"])

    def test_a_trailing_backslash_does_not_swallow_the_next_argument(self):
        self.round_trip(["plugin", "marketplace", "add", "D:\\", "extra"])

    def test_an_embedded_quote_survives(self):
        self.round_trip(['a"b', "plain"])

    def test_a_unicode_path_survives(self):
        self.round_trip(["plugin", "marketplace", "add",
                         "C:\\Users\\\uc0ac\uc6a9\uc790 \uc774\ub984\\.codex-auto-resume\\app"])

    def test_the_ordinary_case_is_unchanged(self):
        self.round_trip(["plugin", "add", "codex-auto-resume@codex-auto-resume-windows"])


class UninstallVerifierTests(unittest.TestCase):
    """The uninstaller has to ask an engine that can answer the question.

    `verify-home` arrived in v0.5.4, and v0.5.4's uninstaller deletes nothing until it
    passes. Asking the *installed* engine therefore broke uninstalling a v0.5.3
    installation outright: argparse rejects the unknown subcommand, the exit status is
    not zero, and a perfectly legitimate installation is refused. Found by running the
    real uninstaller against a real v0.5.3 tree, so it is pinned here.

    The payload travels with the script and is always the script's own version, so it can
    always answer; the installed copy is a fallback for a payload that is not there.
    """

    def uninstall_branch(self) -> str:
        """The part of the installer that runs before anything can be deleted."""
        text = INSTALLER.read_text(encoding="utf-8")
        start = text.index("if ($Uninstall) {")
        return text[start:text.index("$OwnedHome = Resolve-Canonical", start)]

    def run_engine(self, script: Path, home: Path) -> subprocess.CompletedProcess:
        environ = dict(os.environ)
        environ["CODEX_AUTO_RESUME_PLUGIN_HOME"] = str(home)
        environ["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run([sys.executable, str(script), "verify-home"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=environ, timeout=120)

    def test_the_verifier_is_taken_from_the_payload_first(self):
        branch = self.uninstall_branch()
        payload = branch.index("$verifier = Join-Path $Payload")
        installed = branch.index("$verifier = Join-Path $AppDir")
        self.assertLess(payload, installed,
                        "the installed engine may be a fallback, never the first choice")
        guard = branch[branch.rindex("\n", 0, installed):installed]
        self.assertIn("-not (Test-Path $verifier)", guard,
                      "the fallback must apply only when the payload carries no engine")

    def test_the_check_runs_the_verifier_that_was_chosen(self):
        branch = self.uninstall_branch()
        self.assertIn("& $interpreter $verifier 'verify-home'", branch,
                      "the chosen verifier is the one that must be asked")
        self.assertIn("$LASTEXITCODE -ne 0", branch,
                      "a failed check must still refuse")

    def test_the_previous_release_engine_cannot_answer(self):
        """Why the payload's copy is used, against the real v0.5.3 engine.

        Skipped where the tag is absent - CI checks out without tags - because the
        alternative is a stand-in that only proves what it was written to prove.
        """
        shown = subprocess.run(
            ["git", "-C", str(ROOT), "show", "v0.5.3:scripts/plugin_setup.py"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if shown.returncode != 0:
            self.skipTest("v0.5.3 is not in this checkout")
        with tempfile.TemporaryDirectory() as name:
            older = Path(name) / "plugin_setup.py"
            older.write_text(shown.stdout, encoding="utf-8")
            home = Path(name) / "installation"
            from codex_auto_resume import config
            config.Paths(home).ensure()
            result = self.run_engine(older, home)
        self.assertNotEqual(result.returncode, 0,
                            "if v0.5.3 could answer, the payload fallback is untested")
        self.assertIn("usage", (result.stderr + result.stdout).lower())

    def test_this_engine_answers_for_an_installation_made_before_it(self):
        """The same home, asked through the engine that ships with this uninstaller."""
        from codex_auto_resume import config
        with tempfile.TemporaryDirectory() as name:
            home = Path(name) / "installation"
            config.Paths(home).ensure()
            self.assertFalse((home / config.OWNER_MARKER).exists(),
                             "the fixture must have the shape v0.5.3 left behind")
            result = self.run_engine(ROOT / "scripts" / "plugin_setup.py", home)
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(lines[0], "owned")
            self.assertEqual(Path(lines[-1]), home.resolve())


if __name__ == "__main__":
    unittest.main()
