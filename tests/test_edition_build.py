"""Each edition's build: the standard one as it always was, the advanced one that and its own.

build/make_release.py builds either edition from the same code (v0.6.11, decision C1). These
build both in a temporary directory, with a stub runtime and stub executables standing in for
the ones a release downloads and compiles, and hold what the pair has to be:

* the standard archive is the same file whether the repository's advanced/ tree is there or not,
  because the standard build only ever adds and nothing it adds is under advanced/;
* each archive is named by its edition's template in scripts/release.json, the one file every
  bootstrap builds the name it downloads from, and each is staged in a directory of its own;
* each payload root holds exactly the two files every bootstrap requires there, and each archive
  every entry a bootstrap requires;
* the advanced archive is the standard one plus the package, the skill, a window of its own and
  one display name - which build/edition_audit.py, run on the pair, confirms.

And the installer and the bootstrap say which edition they install, by the one fact the product
reads itself, so the three cannot disagree about an installation.

Nothing here touches an installation, the registry or a real home: the builds write only into
their own temporary directories, and the two PowerShell functions are lifted out of the scripts
and run on folders made for them.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # editions lives next to this file
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import editions  # noqa: E402
import edition_audit  # noqa: E402
from codex_auto_resume import edition  # noqa: E402

BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
INSTALLER = ROOT / "build" / "install" / "install.ps1"
MAKE_GUI = ROOT / "build" / "make_gui.ps1"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
# What stands in for what a release downloads and compiles. Each edition's window is its own.
STANDARD_WINDOW = b"MZ the standard window"
ADVANCED_WINDOW = b"MZ the advanced window"
LAUNCHER = b"MZ the MCP launcher"


def load_builder(name: str):
    """A fresh copy of make_release, so a test can point it at its own directories without
    reaching the one every other test imports."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "build" / "make_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stand_in(builder, work: Path, root: Path = ROOT) -> None:
    """Point a builder at `root` for its sources and at `work` for everything it writes or reads
    that a release would download or compile: the runtime, the executables and the stages."""
    runtime = io.BytesIO()
    with zipfile.ZipFile(runtime, "w") as bundle:
        bundle.writestr("python.exe", b"MZ a stand-in interpreter")
        bundle.writestr("python313._pth", "python313.zip\n.\n")
    cache = work / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / builder.PYTHON_ZIP).write_bytes(runtime.getvalue())
    built = work / "built"
    (built / "advanced").mkdir(parents=True, exist_ok=True)
    (built / builder.GUI_EXE).write_bytes(STANDARD_WINDOW)
    (built / "advanced" / builder.GUI_EXE).write_bytes(ADVANCED_WINDOW)
    (built / builder.MCP_EXE).write_bytes(LAUNCHER)
    builder.ROOT = root
    builder.CACHE = cache
    builder.BUILT = built
    builder.STAGES = work / "stage"
    builder.PYTHON_SHA256 = hashlib.sha256(runtime.getvalue()).hexdigest()


def build(builder, edition_name: str, output: Path) -> Path:
    # The build puts its source tree on the path to validate the bundled data with; a copy's is
    # a temporary directory, and is taken off again rather than left for every later test.
    path = list(sys.path)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            builder.main(["--edition", edition_name, "--output", str(output)])
    finally:
        sys.path[:] = path
    return output / builder.archive_name(edition_name, builder.version())


def standard_sources(target: Path) -> Path:
    """What the standard build reads, copied as it is on disk, and nothing of advanced/."""
    builder = load_builder("make_release_sources")
    skip = shutil.ignore_patterns("__pycache__", "*.pyc")
    for tree in builder.APP_TREES:
        if (ROOT / tree).is_dir():
            shutil.copytree(ROOT / tree, target / tree, ignore=skip)
    for name in builder.APP_FILES:
        source = builder.APP_SOURCES.get(name, name)
        (target / source).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, target / source)
    shutil.copytree(ROOT / "build" / "install", target / "build" / "install")
    return target


def required_by_bootstrap() -> list:
    """The entries every bootstrap requires of an archive before it installs it (Test-Archive)."""
    text = BOOTSTRAP.read_text(encoding="utf-8")
    listed = re.search(r"\$required = @\((.*?)\)", text, re.S)
    assert listed, "Test-Archive has no $required list"
    return re.findall(r"'([^']+)'", listed.group(1))


class EditionBuildTests(unittest.TestCase):
    """Both editions built once, the standard one twice: from the repository as it is, and from
    a copy of what it reads with no advanced/ beside it."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="edition-build-"))
        cls.builder = load_builder("make_release_editions")
        stand_in(cls.builder, cls.work / "here")
        cls.standard = build(cls.builder, "standard", cls.work / "dist")
        cls.advanced = build(cls.builder, "advanced", cls.work / "dist")
        without = load_builder("make_release_without")
        stand_in(without, cls.work / "there", standard_sources(cls.work / "without"))
        cls.without = build(without, "standard", cls.work / "dist-without")
        cls.ours = edition_audit.entries(cls.standard)
        cls.theirs = edition_audit.entries(cls.advanced)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_the_standard_archive_does_not_depend_on_the_advanced_tree(self):
        """The by-construction proof, here: the same bytes with advanced/ beside the build and
        without it. build/edition_audit.py's (e) makes it again from the commit at release."""
        self.assertFalse((self.work / "without" / "advanced").exists())
        self.assertEqual(self.standard.read_bytes(), self.without.read_bytes())

    def test_each_archive_is_named_by_its_editions_template(self):
        templates = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
        release = self.builder.version()
        self.assertEqual(self.standard.name, templates["archive"].replace("{version}", release))
        self.assertEqual(self.advanced.name, templates["advanced"]["archive"].replace("{version}", release))
        for archive in (self.standard, self.advanced):
            with self.subTest(archive.name):
                sidecar = (archive.parent / (archive.name + ".sha256")).read_text(encoding="utf-8")
                self.assertEqual(sidecar, "%s  %s\n" % (hashlib.sha256(archive.read_bytes()).hexdigest(),
                                                         archive.name))

    def test_each_edition_is_staged_on_its_own(self):
        """Building the advanced edition after the standard one left the standard stage alone."""
        stages = self.work / "here" / "stage"
        self.assertEqual(sorted(path.name for path in stages.iterdir()), ["advanced", "standard"])
        self.assertTrue((stages / "standard" / "payload" / self.builder.GUI_EXE).is_file())
        self.assertFalse((stages / "standard" / "payload" / "app" / "src" / editions.PACKAGE).exists())

    def test_each_payload_root_holds_the_two_files_every_bootstrap_requires_there(self):
        for entries in (self.ours, self.theirs):
            root = {name for name in entries if re.fullmatch(r"payload/[^/]+", name)}
            self.assertEqual(root, {"payload/CodexAutoResumeSettings.exe", "payload/codex-auto-resume.ico"})

    def test_both_carry_every_entry_a_bootstrap_requires(self):
        required = required_by_bootstrap()
        self.assertGreater(len(required), 5)
        for label, entries in (("standard", self.ours), ("advanced", self.theirs)):
            with self.subTest(label):
                self.assertEqual([name for name in required if name not in entries], [])

    def test_the_advanced_archive_adds_the_package_and_the_skill_and_the_standard_neither(self):
        added = sorted(set(self.theirs) - set(self.ours))
        expected = []
        for tree, placed in self.builder.ADVANCED_TREES:
            for path in sorted((ROOT / tree).rglob("*")):
                if path.is_file() and self.builder._wanted(path.relative_to(ROOT)):
                    expected.append("payload/app/%s/%s" % (placed, path.relative_to(ROOT / tree).as_posix()))
        self.assertIn("payload/app/src/%s/plug.py" % editions.PACKAGE, expected)
        self.assertIn("payload/app/skills/%s/SKILL.md" % self.builder.ADVANCED_SKILL, expected)
        self.assertEqual(added, sorted(expected))
        for name in self.ours:
            self.assertNotIn(editions.PACKAGE, name)
            self.assertNotIn(self.builder.ADVANCED_SKILL, name)

    def test_the_manifests_differ_only_in_the_display_name(self):
        ours = json.loads(self.ours[edition_audit.MANIFEST])
        theirs = json.loads(self.theirs[edition_audit.MANIFEST])
        self.assertEqual((theirs["name"], theirs["version"]), (ours["name"], ours["version"]))
        self.assertEqual(ours["interface"]["displayName"], "Codex Auto Resume")
        self.assertEqual(theirs["interface"]["displayName"], "Codex Auto Resume Advanced")
        theirs["interface"]["displayName"] = ours["interface"]["displayName"]
        self.assertEqual(list(theirs.items()), list(ours.items()))

    def test_each_edition_ships_its_own_window_and_the_one_launcher(self):
        launcher = "payload/app/mcp/" + self.builder.MCP_EXE
        self.assertEqual(self.ours[edition_audit.WINDOW], STANDARD_WINDOW)
        self.assertEqual(self.theirs[edition_audit.WINDOW], ADVANCED_WINDOW)
        self.assertEqual((self.ours[launcher], self.theirs[launcher]), (LAUNCHER, LAUNCHER))

    def test_the_audit_finds_nothing_in_the_pair(self):
        """(a)-(d), (f) and (g) on the two archives this build made; (e) needs a commit to
        rebuild from and is held in tests/test_edition_audit.py."""
        tree = edition_audit.inventory()
        opened = edition_audit.expand(self.ours)
        found = (edition_audit.check_paths(opened) + edition_audit.check_digests(opened, tree)
                 + edition_audit.check_names(opened, tree)[0]
                 + edition_audit.check_executables(self.ours, tree)
                 + edition_audit.check_binaries(opened)
                 + edition_audit.check_superset(self.ours, self.theirs))
        self.assertEqual(found, [])


class CommandLineTests(unittest.TestCase):
    def test_the_edition_is_one_of_the_two_and_standard_unless_said(self):
        builder = load_builder("make_release_arguments")
        self.assertEqual(builder.EDITIONS, ("standard", "advanced"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            builder.main(["--edition", "premium"])
        source = (ROOT / "build" / "make_release.py").read_text(encoding="utf-8")
        self.assertIn('default="standard"', source)

    def test_the_build_list_is_only_ever_added_to(self):
        """No tree the standard build copies is advanced/, and the advanced build adds its trees
        after the standard ones rather than choosing among them."""
        builder = load_builder("make_release_lists")
        self.assertNotIn("advanced", builder.APP_TREES)
        for tree, placed in builder.ADVANCED_TREES:
            with self.subTest(tree):
                self.assertTrue(tree.startswith("advanced/"))
                self.assertTrue((ROOT / tree).is_dir())
                self.assertTrue(placed.startswith(("src/", "skills/")))
        main = (ROOT / "build" / "make_release.py").read_text(encoding="utf-8")
        body = main[main.index("def main("):]
        self.assertLess(body.index("collect_app(stage)"), body.index("collect_advanced(stage)"))
        self.assertEqual(main.count("collect_advanced(stage)"), 1)


class WindowBuildScriptTests(unittest.TestCase):
    """build/make_gui.ps1 -Edition: the overlay is read for the advanced window and only then."""

    def setUp(self):
        self.script = MAKE_GUI.read_text(encoding="utf-8")

    def test_it_takes_the_two_editions_and_builds_the_standard_one_unless_told(self):
        self.assertIn("[ValidateSet('standard', 'advanced')]", self.script)
        self.assertIn("[string]$Edition = 'standard'", self.script)

    def test_the_overlay_is_read_only_for_the_advanced_window(self):
        self.assertEqual(self.script.count(r"Read-SourceList 'advanced\gui\window.sources'"), 1)
        self.assertEqual(self.script.count("Read-SourceList '"), 2, "the window's list and the overlay")
        branch = self.script[self.script.index("if ($Edition -eq 'advanced') {\n    $WindowSources"):]
        branch = branch[:branch.index("}")]
        self.assertIn(r"Read-SourceList 'advanced\gui\window.sources'", branch)

    def test_the_advanced_window_goes_where_the_release_build_takes_it_from(self):
        builder = load_builder("make_release_window")
        self.assertIn("if ($Edition -eq 'advanced') { $Out = Join-Path $Out 'advanced' }", self.script)
        self.assertEqual(builder.BUILT / "advanced", ROOT / "build" / "advanced")
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("build/advanced/", ignored)

    def test_only_the_standard_run_builds_the_shared_launcher(self):
        launcher = self.script.index("-Name 'codex-auto-resume-mcp.exe'")
        guard = self.script.rindex("if ($Edition -eq 'standard') {", 0, launcher)
        self.assertNotIn("}", self.script[guard + len("if ($Edition -eq 'standard') {"):launcher])


LIFT = r"""
$ErrorActionPreference = 'Stop'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_SCRIPT, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'the script does not parse' }
$found = $false
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($node.Name -eq 'Get-Edition') { Invoke-Expression $node.Extent.Text; $found = $true }
}
if (-not $found) { throw 'the script has no Get-Edition' }
foreach ($src in ($env:CAR_CASES -split '\|')) { Write-Output (Get-Edition -Src $src) }
"""


class EditionWordTests(unittest.TestCase):
    """The installer and the bootstrap say which edition they install, by the fact the product
    reads (src/codex_auto_resume/edition.py, name()): the package beside core, with its
    `__init__.py`."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="edition-word-"))
        cases = {"absent": [], "present": ["%s/__init__.py" % editions.PACKAGE],
                 # A directory of that name with no __init__.py is no package, and no edition.
                 "only_a_cache": ["%s/__pycache__/plug.cpython-313.pyc" % editions.PACKAGE],
                 "init_is_a_folder": ["%s/__init__.py/placeholder" % editions.PACKAGE]}
        cls.cases = {}
        for name, files in cases.items():
            src = cls.work / name / "src"
            (src / "codex_auto_resume").mkdir(parents=True)
            for relative in files:
                (src / relative).parent.mkdir(parents=True, exist_ok=True)
                (src / relative).write_text("# a stand-in\n", encoding="utf-8")
            cls.cases[name] = src

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def answers(self, script: Path) -> dict:
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", LIFT],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                              env=dict(os.environ, CAR_SCRIPT=str(script),
                                       CAR_CASES="|".join(str(src) for src in self.cases.values())))
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return dict(zip(self.cases, done.stdout.split()))

    @unittest.skipUnless(POWERSHELL.is_file(), "needs Windows PowerShell")
    def test_the_bootstrap_the_installer_and_the_product_agree(self):
        product = {name: str(edition.name(src)) for name, src in self.cases.items()}
        self.assertEqual(product, {"absent": "standard", "present": "advanced",
                                   "only_a_cache": "standard", "init_is_a_folder": "standard"})
        for script in (BOOTSTRAP, INSTALLER):
            with self.subTest(script.name):
                self.assertEqual(self.answers(script), product)

    def test_the_installer_says_it_before_anything_is_moved(self):
        text = INSTALLER.read_text(encoding="utf-8")
        read = text.index("$edition = Get-Edition -Src (Join-Path $Payload 'app\\src')")
        said = text.index("Write-Host ('edition: ' + $edition)")
        self.assertLess(text.index("if (-not (Test-Path $Payload))"), read)
        self.assertLess(read, said)
        self.assertLess(said, text.index("$upgrade = Test-Path $AppDir"))
        self.assertEqual(text.count(editions.PACKAGE), 1, "the package is spelled once, in Get-Edition")

    def test_the_bootstrap_says_it_before_it_asks_or_fetches_anything(self):
        """Once, as soon as the edition is settled - the one the run installs, checks over or
        asks about - and before github.com is asked, the repair branch is reached or anything
        is downloaded. A run refused for the other edition names the installed one instead."""
        text = BOOTSTRAP.read_text(encoding="utf-8")
        said = text.index("Write-Host ('edition: ' + $targetEdition)")
        self.assertLess(text.index("$plan = Resolve-Edition"), said)
        for later in ("Step 'Asking github.com", "$standing = $null", "Downloading v"):
            with self.subTest(later):
                self.assertLess(said, text.index(later))
        refused = text.index("Write-Host ('edition: ' + $installedEdition)")
        self.assertLess(refused, text.index("exit $ExitOtherEdition"))
        self.assertEqual(text.count("Write-Host ('edition: '"), 2)
        # Only the `update:` line is read by the window (gui/DashboardMaintenance.cs); this one is
        # a line of its own and changes none that is read.
        self.assertNotIn("update: edition", text)

    def test_the_bootstrap_spells_the_package_only_where_it_reads_an_edition(self):
        """In Get-Edition, for an installed tree, and in Test-Archive, for an archive not yet
        unpacked: the two places that tell one edition from the other."""
        text = BOOTSTRAP.read_text(encoding="utf-8")
        spans = []
        for name in ("Get-Edition", "Test-Archive"):
            first = text.index("function %s {" % name)
            spans.append((first, text.index("\n}\n", first)))
        places = [match.start() for match in re.finditer(re.escape(editions.PACKAGE), text)]
        self.assertEqual(len(places), 2)
        for place in places:
            self.assertTrue(any(first < place < last for first, last in spans), text[place - 80:place])


if __name__ == "__main__":
    unittest.main()
