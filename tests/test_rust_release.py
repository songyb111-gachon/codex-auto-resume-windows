"""The Rust-shaped release archive (build/rust_release.py, seat S8.1), held on archives built here from stand-ins.

What a Rust release may never lose (D9): every published updater takes it - by the compatibility entry (each tag's
Test-Archive accepts it: payload/runtime/python.exe and the content-free stubs) or by the setup handover (v0.6.26's
Read-SetupHandover and Resolve-SetupProgram) - its standard archive holds nothing of the advanced edition, its app
stays inside tests/data/rust_release_budget.json, and the same inputs give the same bytes.

The archives here are built from the tree with stand-in executables (small PE images of the right subsystem), so
nothing needs the Rust toolchain or the C# compiler; the real archives are built and checked the same way by the
scripts themselves (rust/GROUNDWORK.md, S8.1). Nothing here reaches the network, an installation or the registry:
every build step writes into a temporary folder, and the bootstraps run only their own function definitions.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import legacy_bootstraps as legacy  # noqa: E402
import make_release  # noqa: E402
import rust_edition_audit  # noqa: E402
import rust_legacy_bootstraps  # noqa: E402
import rust_release  # noqa: E402

# Later than every tag, so every published bootstrap is one that could update to it.
VERSION = "9.9.9"
BUDGET = ROOT / "tests" / "data" / "rust_release_budget.json"
MIB = 1024 * 1024
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def pe(subsystem: int, dll: bool = False, filler: bytes = b"") -> bytes:
    """The smallest image `rust_release.subsystem` and v0.6.26's Resolve-SetupProgram read as a Windows program."""
    image = bytearray(512)
    image[0:2] = b"MZ"
    image[60:64] = (64).to_bytes(4, "little")
    image[64:68] = b"PE\0\0"
    image[64 + 22:64 + 24] = (0x0002 | (0x2000 if dll else 0)).to_bytes(2, "little")
    image[64 + 92:64 + 94] = subsystem.to_bytes(2, "little")
    return bytes(image) + filler


def stand_ins(folder: Path, edition: str, extra: dict | None = None) -> dict:
    """Stand-in binaries for one edition: the paths rust_release's --bins, --legacy-bins, --window and --mcp-launcher
    take. `extra` maps a file name to bytes put at its end."""
    extra = extra or {}
    bins, legacy_bins = folder / ("bins-" + edition), folder / "legacy"
    bins.mkdir(parents=True, exist_ok=True)
    legacy_bins.mkdir(parents=True, exist_ok=True)
    tag = edition.encode("ascii")
    files = {bins / "codex-auto-resume.exe": pe(3, filler=b"core " + tag),
             bins / "codex-auto-resume-setup.exe": pe(2, filler=b"setup " + tag),
             bins / "car_core.dll": pe(2, dll=True, filler=b"dll " + tag),
             legacy_bins / "python.exe": pe(3, filler=b"car-legacy console"),
             legacy_bins / "pythonw.exe": pe(2, filler=b"car-legacy windowless"),
             folder / ("window-" + edition + ".exe"): pe(2, filler=b"window " + tag),
             folder / "launcher.exe": pe(3, filler=b"launcher"),
             folder / "host.exe": pe(2, filler=b"watcher host")}
    for path, data in files.items():
        path.write_bytes(data + extra.get(path.name, b""))
    return {"bins": bins, "legacy": legacy_bins, "window": folder / ("window-" + edition + ".exe"),
            "launcher": folder / "launcher.exe", "host": folder / "host.exe"}


def build(folder: Path, edition: str, version: str = VERSION, extra: dict | None = None, after=None) -> Path:
    """One edition's archive in folder/dist; `after(stage)` may change the stage before it is packed."""
    given = stand_ins(folder / "in", edition, extra)
    stage = rust_release.stage_edition(folder / ("stage-" + edition), edition, version, bins=given["bins"],
                                       legacy=given["legacy"], window=given["window"], launcher=given["launcher"], host=given["host"])
    if after:
        after(stage)
    return make_release.write_archive(stage, folder / "dist" / rust_release.archive_name(edition, version))


def names(archive: Path) -> list:
    with zipfile.ZipFile(archive) as bundle:
        return bundle.namelist()


def read(archive: Path, entry: str) -> bytes:
    with zipfile.ZipFile(archive) as bundle:
        return bundle.read(entry)


def required_entries() -> set:
    """Every entry any published Test-Archive requires, from each tag's own list (git, not the working tree)."""
    import re
    found = set()
    for tag in legacy.published(ROOT, VERSION):
        text = legacy.lift(ROOT, tag).script.decode("utf-8", "replace")
        listed = re.search(r"\$required = @\((.*?)\)", text, re.S)
        found |= set(re.findall(r"'([^']+)'", listed.group(1)))
    return found


def tags_present() -> bool:
    try:
        return bool(legacy.published(ROOT, VERSION))
    except SystemExit:
        return False


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix="car-rust-release-")
        folder = Path(cls.work.name)
        cls.standard = build(folder, "standard")
        cls.advanced = build(folder, "advanced")

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_the_marker_is_the_one_bridge_md_describes_at_the_archive_root(self):
        for archive, edition in ((self.standard, "standard"), (self.advanced, "advanced")):
            listed = [name for name in names(archive) if name.lower().endswith("setup-handover.json")]
            self.assertEqual(listed, ["setup-handover.json"])
            said = json.loads(read(archive, "setup-handover.json"))
            self.assertEqual(said, {"format": "codex-auto-resume/setup-handover/1", "version": VERSION,
                                    "edition": edition, "setup": "payload/app/bin/codex-auto-resume-setup.exe"})
            self.assertIn(said["setup"], names(archive))
            self.assertLessEqual(len(read(archive, "setup-handover.json")), 65536)

    def test_the_payload_root_holds_the_window_and_its_icon_alone(self):
        for archive in (self.standard, self.advanced):
            root = sorted(name for name in names(archive) if name.count("/") == 1 and name.startswith("payload/"))
            self.assertEqual(root, ["payload/CodexAutoResumeSettings.exe", "payload/codex-auto-resume.ico"])

    def test_every_entry_this_trees_test_archive_requires_is_there(self):
        import re
        listed = re.search(r"\$required = @\((.*?)\)", (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8"),
                           re.S)
        for archive in (self.standard, self.advanced):
            for entry in re.findall(r"'([^']+)'", listed.group(1)):
                self.assertIn(entry, names(archive))

    @unittest.skipUnless(tags_present(), "no tag from v0.5.2 in this checkout")
    def test_every_entry_any_published_test_archive_requires_is_there(self):
        wanted = required_entries()
        self.assertIn("payload/runtime/python.exe", wanted)
        for archive in (self.standard, self.advanced):
            self.assertEqual(wanted - set(names(archive)), set())

    def test_the_only_python_files_are_the_content_free_stubs(self):
        stubs = set(rust_release.STUBS)
        self.assertEqual({name for name in names(self.standard) if name.endswith(".py")}, stubs)
        self.assertEqual({name for name in names(self.advanced) if name.endswith(".py")},
                         stubs | {rust_release.ADVANCED_STUB[0]})
        for entry in stubs:
            self.assertEqual(read(self.standard, entry), read(self.advanced, entry))
            self.assertTrue(all(line.startswith("#") for line in read(self.standard, entry).decode().splitlines()))
        self.assertTrue(read(self.advanced, rust_release.ADVANCED_STUB[0]).startswith(b"# ADVANCED-EDITION-CODE"))

    def test_car_legacy_is_the_same_in_both_editions_and_the_runtime_holds_nothing_else(self):
        for archive in (self.standard, self.advanced):
            runtime = sorted(name for name in names(archive) if name.startswith("payload/runtime/"))
            self.assertEqual(runtime, ["payload/runtime/python.exe", "payload/runtime/pythonw.exe"])
        for entry in ("payload/runtime/python.exe", "payload/runtime/pythonw.exe"):
            self.assertEqual(read(self.standard, entry), read(self.advanced, entry))

    def test_the_manifest_is_this_product_at_the_version_built(self):
        manifest = json.loads(read(self.standard, "payload/app/.codex-plugin/plugin.json"))
        self.assertEqual((manifest["name"], manifest["version"], manifest["mcpServers"]),
                         ("codex-auto-resume", VERSION, "./.mcp.json"))

    def test_a_program_of_the_wrong_subsystem_stops_the_build(self):
        with tempfile.TemporaryDirectory(prefix="car-rust-release-") as work:
            given = stand_ins(Path(work), "standard")
            (given["bins"] / "codex-auto-resume-setup.exe").write_bytes(pe(3))
            with self.assertRaisesRegex(SystemExit, "codex-auto-resume-setup.exe is of subsystem 3, not 2"):
                rust_release.stage_edition(Path(work) / "stage", "standard", VERSION, bins=given["bins"],
                                           legacy=given["legacy"], window=given["window"], launcher=given["launcher"], host=given["host"])

    def test_a_core_with_the_test_forward_that_is_not_the_stub_stops_the_build(self):
        """Review 9, note 8: the installer proofs' forward (CODEX_AUTO_RESUME_TEST_CORE) never reaches a release."""
        with tempfile.TemporaryDirectory(prefix="car-rust-release-") as work:
            given = stand_ins(Path(work), "standard")
            core = given["bins"] / "codex-auto-resume.exe"
            core.write_bytes(core.read_bytes() + rust_release.TEST_HOOK)
            with self.assertRaisesRegex(SystemExit, "carries the installer proofs' test forward"):
                rust_release.stage_edition(Path(work) / "stage", "standard", VERSION, bins=given["bins"],
                                           legacy=given["legacy"], window=given["window"], launcher=given["launcher"], host=given["host"])
            # The stub core may carry it: it is never a release.
            core.write_bytes(core.read_bytes() + rust_release.STUB_CORE)
            rust_release.stage_edition(Path(work) / "stage", "standard", VERSION, bins=given["bins"],
                                       legacy=given["legacy"], window=given["window"], launcher=given["launcher"], host=given["host"])

    def test_the_same_inputs_give_the_same_bytes_in_another_folder(self):
        with tempfile.TemporaryDirectory(prefix="car-rust-release-again-") as work:
            again = build(Path(work) / "elsewhere", "standard")
            self.assertEqual(again.read_bytes(), self.standard.read_bytes())

    def test_the_installer_is_the_rust_payloads_and_parses(self):
        # S8.2's installer, as the tree has it; it is run only with its reach outside the home stood in
        # (tests/test_rust_install.py): run whole here it would look for this PC's Codex.
        for archive in (self.standard, self.advanced):
            self.assertEqual(read(archive, "install/install.ps1"), rust_release.INSTALLER.read_bytes())
        check = ("$errors = $null; $null = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_SCRIPT, "
                 "[ref]$null, [ref]$errors); if ($errors -and $errors.Count) { $errors | ForEach-Object { $_.Message }; "
                 "exit 1 }")
        done = subprocess.run([str(legacy.POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", check],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                              creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                              env=dict(os.environ, CAR_SCRIPT=str(rust_release.INSTALLER)))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


@unittest.skipUnless(legacy.POWERSHELL.is_file(), "the published bootstraps are Windows PowerShell")
@unittest.skipUnless(tags_present(), "no tag from v0.5.2 in this checkout")
class PublishedUpdaterTests(unittest.TestCase):
    """D9's proof: every published bootstrap takes both Rust-shaped archives, and the ways it would refuse one are
    caught."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix="car-rust-legacy-")
        folder = Path(cls.work.name)
        cls.standard = build(folder, "standard")
        cls.advanced = build(folder, "advanced")
        cls.dist = cls.standard.parent

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def bridge(self):
        """A bootstrap that knows the handover: a tag's from v0.6.26, else this checkout's dev branch, else none."""
        for tag in reversed(legacy.published(ROOT, VERSION)):
            bootstrap = legacy.lift(ROOT, tag)
            if rust_legacy_bootstraps.knows_handover(bootstrap):
                return bootstrap
        try:
            bootstrap = rust_legacy_bootstraps.lift_ref("dev")
        except SystemExit:
            return None
        return bootstrap if rust_legacy_bootstraps.knows_handover(bootstrap) else None

    def test_every_published_bootstrap_takes_both_archives(self):
        bridge = self.bridge()
        # Stand-in binaries cannot run: (c) is EntryRunTests', on the cargo build.
        found, means = rust_legacy_bootstraps.run(self.dist, VERSION, entry=False)
        self.assertEqual(found, [])
        self.assertEqual(set(means), set(legacy.published(ROOT, VERSION)))
        if bridge is not None:
            self.assertEqual(rust_legacy_bootstraps.check_handover([bridge], VERSION, self.standard, self.advanced), [])

    def test_an_archive_without_a_stub_is_refused_by_the_compatibility_entry(self):
        def drop(stage):
            (stage / "payload" / "app" / "scripts" / "plugin_setup.py").unlink()
        with tempfile.TemporaryDirectory(prefix="car-rust-legacy-") as work:
            broken = build(Path(work), "standard", after=drop)
            # The newest tag: v0.5.2's list, the first, did not name plugin_setup.py yet.
            newest = legacy.lift(ROOT, legacy.published(ROOT, VERSION)[-1])
            found = legacy.check([newest], VERSION, broken, self.advanced)
        self.assertEqual(len(found), 1)
        self.assertIn("payload/app/scripts/plugin_setup.py", found[0])

    def test_a_marker_for_the_other_edition_or_a_console_setup_is_refused_by_the_handover(self):
        bridge = self.bridge()
        if bridge is None:
            self.skipTest("no bootstrap of v0.6.26 (tag or dev branch) in this checkout")

        def other_edition(stage):
            (stage / "setup-handover.json").write_bytes(rust_release.marker("advanced", VERSION))
        with tempfile.TemporaryDirectory(prefix="car-rust-legacy-") as work:
            wrong = build(Path(work) / "edition", "standard", after=other_edition)
            console = build(Path(work) / "console", "standard",
                            after=lambda stage: (stage / rust_release.SETUP).write_bytes(pe(3)))
            found = rust_legacy_bootstraps.check_handover([bridge], VERSION, wrong, self.advanced)
            self.assertEqual(len(found), 1)
            self.assertIn("for the advanced edition, not the standard one", found[0])
            found = rust_legacy_bootstraps.check_handover([bridge], VERSION, console, self.advanced)
            self.assertEqual(len(found), 1)
            self.assertIn("is not a Windows program", found[0])


class EntryRunTests(unittest.TestCase):
    """(c) of the bootstrap proof on the cargo build: each published bootstrap's own runtime\\python.exe lines, run by
    its own Invoke-InstalledSetup (or its repair branch's call operator), reach the core through car-legacy."""

    @classmethod
    def setUpClass(cls):
        release = ROOT / "rust" / "target" / "release"
        cls.legacy, cls.core = release / "python.exe", release / "codex-auto-resume.exe"
        if not (cls.legacy.is_file() and cls.core.is_file()):
            raise unittest.SkipTest("not built: cargo build --release --manifest-path rust/Cargo.toml")
        if not tags_present():
            raise unittest.SkipTest("no published tag in this checkout")
        cls.bootstraps = [legacy.lift(ROOT, tag) for tag in legacy.published(ROOT, VERSION)]

    def test_every_bootstrap_line_reaches_the_core(self):
        self.assertEqual(rust_legacy_bootstraps.check_entry(self.bootstraps, self.legacy, self.core), [])

    def test_a_refusing_entry_is_found(self):
        # car-legacy given as the core too refuses every line handed to it (it is not in a runtime folder): code 2.
        found = rust_legacy_bootstraps.check_entry(self.bootstraps[-1:], self.legacy, self.legacy)
        self.assertTrue(found and all("refused by car-legacy" in line for line in found), found)


class AuditTests(unittest.TestCase):
    """The edition audit over the Rust payload: nothing of the advanced edition in the standard archive, the
    allowances only where the Python audit makes the same one."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix="car-rust-audit-")
        cls.folder = Path(cls.work.name)
        cls.standard = build(cls.folder / "clean", "standard")
        cls.advanced = build(cls.folder / "clean", "advanced")
        cls.tree = rust_edition_audit.audit.inventory(ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_the_clean_archives_pass(self):
        found, used = rust_edition_audit.run(self.standard, self.advanced, VERSION, rebuild=False, tree=self.tree)
        self.assertEqual(found, [])
        self.assertIn(("payload/app/scripts/bootstrap.ps1", rust_edition_audit.audit.PACKAGE), used)
        self.assertLessEqual(used, set(rust_edition_audit.audit.ALLOWED) | set(rust_edition_audit.RUST_EXECUTABLE_ALLOWED))

    def test_each_allowance_is_one_the_python_audit_makes(self):
        audit = rust_edition_audit.audit
        for (entry, name), reason in rust_edition_audit.RUST_EXECUTABLE_ALLOWED.items():
            self.assertEqual(name, audit.PACKAGE, entry)
            self.assertTrue(reason.endswith((audit.INSTALLER_WINDOW, rust_edition_audit.EDITION_LOOK)), entry)
        self.assertNotIn("payload/runtime/python.exe", {entry for entry, _ in rust_edition_audit.RUST_EXECUTABLE_ALLOWED})

    def test_the_package_name_is_allowed_in_the_core_and_found_in_car_legacy(self):
        package = rust_edition_audit.audit.PACKAGE.encode("utf-8")
        standard = build(self.folder / "named", "standard",
                         extra={"codex-auto-resume.exe": package, "pythonw.exe": package})
        found, used = rust_edition_audit.check_executables(rust_edition_audit.audit.entries(standard), self.tree)
        self.assertIn(("payload/app/bin/codex-auto-resume.exe", rust_edition_audit.audit.PACKAGE), used)
        self.assertEqual([line for line in found if line.startswith("(d)")],
                         ["(d) payload/runtime/pythonw.exe holds %s" % rust_edition_audit.audit.PACKAGE])

    def test_the_mcp_launcher_is_read_as_every_other_rust_binary(self):
        # D18: the launcher is car-bin's, and carries the standard library's messages ("capacity overflow") as the core
        # does. A one-plain-word literal of the advanced window is left out of both; any other literal and any advanced
        # name is still found in the launcher, which no allowance covers.
        audit = rust_edition_audit.audit
        self.assertIn(rust_release.MCP_LAUNCHER, rust_edition_audit.RUST_EXECUTABLES)
        self.assertIn(rust_release.MCP_LAUNCHER, rust_release.RUST_BUILT)
        words = sorted(literal for literal in self.tree.literals if rust_edition_audit.plain_word(literal))[:5]
        other = next(literal for literal in sorted(self.tree.literals)
                     if literal.isascii() and " " in literal.strip() and not rust_edition_audit.plain_word(literal))
        std = " ".join(words).encode("ascii")
        standard = build(self.folder / "launcher", "standard",
                         extra={"codex-auto-resume.exe": std, "launcher.exe": std})
        found, _ = rust_edition_audit.check_executables(audit.entries(standard), self.tree)
        self.assertEqual([line for line in found if line.startswith("(d)")], [])
        planted = build(self.folder / "launcher-planted", "standard",
                        extra={"launcher.exe": std + b" " + other.encode("ascii") + b" " + audit.PACKAGE.encode("ascii")})
        found, used = rust_edition_audit.check_executables(audit.entries(planted), self.tree)
        launcher = [line for line in found if line.startswith("(d) %s " % rust_release.MCP_LAUNCHER)]
        self.assertIn("(d) %s holds %s" % (rust_release.MCP_LAUNCHER, audit.PACKAGE), launcher)
        self.assertIn("(d) %s holds the literal %r" % (rust_release.MCP_LAUNCHER, other), launcher)
        self.assertFalse([line for line in launcher for word in words if line.endswith("literal %r" % word)], launcher)
        self.assertNotIn((rust_release.MCP_LAUNCHER, audit.PACKAGE), used)

    def test_the_sentinel_anywhere_in_the_standard_archive_is_found(self):
        def leak(stage):
            target = stage / "payload" / "app" / "src" / "codex_auto_resume" / "data" / "extra.json"
            target.write_text('{"x": "%s"}' % rust_edition_audit.audit.SENTINEL, encoding="utf-8")
        standard = build(self.folder / "leak", "standard", after=leak)
        entries = rust_edition_audit.audit.entries(standard)
        found, _ = rust_edition_audit.audit.check_names(
            {name: data for name, data in entries.items() if name.endswith(".json")}, self.tree)
        self.assertTrue(any("extra.json spells %s" % rust_edition_audit.audit.SENTINEL in line for line in found), found)

    def test_the_editions_may_differ_only_where_each_builds_its_own(self):
        found = rust_edition_audit.check_superset(
            {"payload/app/bin/codex-auto-resume.exe": b"a", "payload/app/docs/x.md": b"same",
             "setup-handover.json": rust_release.marker("standard", VERSION)},
            {"payload/app/bin/codex-auto-resume.exe": b"b", "payload/app/docs/x.md": b"other",
             "setup-handover.json": rust_release.marker("advanced", VERSION),
             rust_edition_audit.REQUIRED_ADVANCED[0]: b"#", "payload/app/extra.txt": b"x"})
        self.assertEqual(found, ["(f) payload/app/docs/x.md differs in the advanced archive",
                                 "(f) the advanced archive adds payload/app/extra.txt outside its own places"])


class BudgetTests(unittest.TestCase):
    """The app's packed bytes and, where the workspaces are built, the binaries', inside the budget."""

    @classmethod
    def setUpClass(cls):
        cls.budget = json.loads(BUDGET.read_text(encoding="utf-8"))

    def app(self, edition: str) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory(prefix="car-rust-size-") as work:
            stage = Path(work)
            rust_release.collect_app(stage, edition, VERSION)
            app = stage / "payload" / "app"
            groups: dict = {}
            for path in sorted(app.rglob("*")):
                if path.is_file():
                    group = "/".join(path.relative_to(app).parts[:2])
                    groups[group] = groups.get(group, 0) + rust_release.deflated(path.read_bytes())
            return sum(groups.values()), groups

    def test_the_app_stays_inside_its_budget(self):
        standard, groups = self.app("standard")
        advanced, more = self.app("advanced")
        self.assertLessEqual(standard, self.budget["standard_app_mib"] * MIB, groups)
        self.assertLessEqual(advanced - standard, self.budget["advanced_extra_mib"] * MIB, more)

    def test_the_binaries_stay_inside_their_budget_where_they_are_built(self):
        wanted = {edition: [rust_release.built(edition) / name for name in rust_release.EDITION_BINARIES]
                  for edition in ("standard", "advanced")}
        legacy_files = [rust_release.built("standard") / name for name in rust_release.LEGACY_BINARIES]
        missing = [str(path) for path in wanted["standard"] + wanted["advanced"] + legacy_files if not path.is_file()]
        if missing:
            self.skipTest("the Rust workspaces are not built here (%s)" % missing[0])
        size = {edition: sum(rust_release.deflated(path.read_bytes()) for path in paths)
                for edition, paths in wanted.items()}
        legacy_size = sum(rust_release.deflated(path.read_bytes()) for path in legacy_files)
        self.assertLessEqual(size["standard"] + legacy_size, self.budget["standard_binaries_mib"] * MIB)
        self.assertLessEqual(size["advanced"] - size["standard"], self.budget["advanced_binaries_extra_mib"] * MIB)


@unittest.skipUnless(tags_present(), "no tag from v0.5.2 in this checkout")
class PublishedLinesTests(unittest.TestCase):
    def test_car_legacys_list_is_what_the_tags_say(self):
        done = subprocess.run([sys.executable, str(ROOT / "rust" / "tools" / "legacy_lines.py"), "--check"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                              creationflags=NO_WINDOW, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
