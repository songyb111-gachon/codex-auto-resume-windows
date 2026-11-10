"""What the release ships, and that it stays that way (v0.6.23).

The archive had grown from 14.2 MB to 18.5 MB, and most of what grew had no reader on a person's PC: pictures the README
shows on GitHub, the repository's own scripts, a changelog of which one entry is ever read, and standard-library modules
nothing imports. build/make_release.py now names what it ships from assets/ and scripts/, cuts the staged changelog to
the entry of its own version and trims the bundled runtime to a checked-in list. These hold each of those:

  (a) the pictures that ship are what the plugin's manifest names, and the icon;
  (b) every script that ships names the program that reads it;
  (c) the app's packed bytes stay inside a budget, tests/data/release_budget.json, which the owner edits when a feature
      earns it; on failure the test prints the bytes per group;
  (d) with the pinned runtime in build/cache (skipped otherwise; every release build does this itself): the trimmed
      runtime still imports every shipped module, and no import of the shipped code or the kept library is left that
      nobody has read.

Nothing here reaches the network, an installation or the registry; every build step writes into a temporary directory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_courier_start_build import stand_in_runtime  # noqa: E402

BUDGET = ROOT / "tests" / "data" / "release_budget.json"
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
# Each script the release ships, and the file that runs or reads it on a person's PC. A new script fails (b) until
# someone writes down who reads it; the reader has to name it.
READERS = {"bootstrap.ps1": "gui/DashboardMaintenance.cs",
           "plugin_setup.py": "build/install/install.ps1",
           "release.json": "scripts/bootstrap.ps1",
           "watcher_launcher.py": "src/codex_auto_resume/startup.py"}
MIB = 1024 * 1024


def load(name: str, relative: str):
    """A fresh copy of a build script, so a test can point it at its own directories."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def builder():
    return load("make_release_size", "build/make_release.py")


def checker():
    return load("runtime_check_size", "build/runtime_check.py")


def pyc(source: str, name: str = "<x>") -> bytes:
    """`source` as the running interpreter's compiled module, header and all."""
    import marshal
    return importlib.util.MAGIC_NUMBER + b"\0" * 12 + marshal.dumps(compile(source, name, "exec"))


def staged_app(make, with_advanced: bool) -> dict:
    """What collect_app (and collect_advanced) put in a payload: path under payload/app -> bytes."""
    with tempfile.TemporaryDirectory(prefix="car-size-") as work:
        stage = Path(work)
        make.collect_app(stage)
        if with_advanced:
            make.collect_advanced(stage)
        app = stage / "payload" / "app"
        return {path.relative_to(app).as_posix(): path.read_bytes() for path in sorted(app.rglob("*")) if path.is_file()}


class ShippedListTests(unittest.TestCase):
    """(a) and (b): what ships from assets/ and scripts/ is named, and each name has a reader."""

    @classmethod
    def setUpClass(cls):
        cls.make = builder()
        cls.app = staged_app(cls.make, False)

    def plugin_paths(self) -> set:
        interface = json.loads(MANIFEST.read_text(encoding="utf-8"))["interface"]
        named = [interface["composerIcon"], interface["logo"], interface["logoDark"]] + interface["screenshots"]
        return {name.replace("./assets/", "", 1) for name in named}

    def test_the_assets_that_ship_are_the_plugins_and_the_icon(self):
        self.assertEqual(set(self.make.SHIPPED_ASSETS), self.plugin_paths() | {"codex-auto-resume.ico"})

    def test_no_other_asset_reaches_the_payload(self):
        shipped = {name[len("assets/"):] for name in self.app if name.startswith("assets/")}
        self.assertEqual(shipped, set(self.make.SHIPPED_ASSETS))
        self.assertGreater(len(list((ROOT / "assets").iterdir())), len(shipped), "nothing is being left out")

    def test_every_script_that_ships_names_who_reads_it(self):
        shipped = {name[len("scripts/"):] for name in self.app if name.startswith("scripts/")}
        self.assertEqual(shipped, set(self.make.SHIPPED_SCRIPTS))
        self.assertEqual(shipped, set(READERS), "a script ships with no reader named in READERS")
        for script, reader in READERS.items():
            self.assertIn(script, (ROOT / reader).read_text(encoding="utf-8-sig"), "%s does not read %s" % (reader, script))

    def test_a_listed_file_that_is_missing_stops_the_build(self):
        with tempfile.TemporaryDirectory(prefix="car-size-") as work:
            make = builder()
            make.SHIPPED_ASSETS = make.SHIPPED_ASSETS + ("no-such-picture.png",)
            make.LISTED_TREES = dict(make.LISTED_TREES, assets=make.SHIPPED_ASSETS)
            with self.assertRaisesRegex(SystemExit, "no-such-picture"):
                make.collect_app(Path(work))


class StagedChangelogTests(unittest.TestCase):
    """The staged changelog is the entry of the version the archive holds. The one in the repository stays whole."""

    SAMPLE = "# Changelog\n\n## v2.0 \u2014 New\n\nbody two\n\n## v2.0-beta \u2014 Earlier\n\nbeta\n\n## v1.0\n\nold\n"

    def setUp(self):
        self.make = builder()

    def test_the_payload_holds_this_versions_entry_and_no_other(self):
        staged = staged_app(self.make, False)["docs/CHANGELOG.md"].decode("utf-8")
        version = self.make.version()
        headings = [line for line in staged.splitlines() if line.startswith("## ")]
        self.assertEqual(len(headings), 1, headings[:3])
        self.assertTrue(headings[0].startswith("## v%s " % version), headings[0])
        self.assertIn(self.make.CHANGELOG_PAGE, staged)
        whole = (ROOT / "docs" / "CHANGELOG.md").read_bytes().decode("utf-8")
        self.assertGreater(len(whole), len(staged), "the repository's copy is the whole one")
        self.assertGreater(whole.count("\n## v"), 1, "the repository's copy is the whole one")

    def test_what_the_notes_page_reads_is_all_there(self):
        """The section InstallerNotes.Section would find in the repository's file is in the staged one, line for line."""
        release_notes = load("release_notes_size", "build/release_notes.py")
        whole = (ROOT / "docs" / "CHANGELOG.md").read_bytes().decode("utf-8").replace("\r\n", "\n")
        cut = self.make.newest_changelog(whole, self.make.version())
        self.assertEqual(release_notes.section(cut, self.make.version()),
                         release_notes.section(whole, self.make.version()))

    def test_the_entry_is_the_versions_not_a_pre_releases_of_it(self):
        cut = self.make.newest_changelog(self.SAMPLE, "2.0")
        self.assertIn("body two", cut)
        self.assertNotIn("beta", cut)
        self.assertEqual(cut.split("\n")[:2], ["# Changelog", ""])
        self.assertIn(self.make.CHANGELOG_PAGE, cut.split("\n")[2])
        self.assertIn("beta", self.make.newest_changelog(self.SAMPLE, "2.0-beta"))
        self.assertNotIn("body two", self.make.newest_changelog(self.SAMPLE, "2.0-beta"))

    def test_the_files_own_line_endings_stay(self):
        cut = self.make.newest_changelog(self.SAMPLE.replace("\n", "\r\n"), "2.0")
        self.assertEqual(cut.count("\n"), cut.count("\r\n"))

    def test_a_version_with_no_entry_stops_the_build(self):
        with self.assertRaisesRegex(SystemExit, "no entry"):
            self.make.newest_changelog(self.SAMPLE, "3.0")

    def test_the_two_readers_ask_for_the_version_the_archive_holds(self):
        """Why one entry is enough: each reader of an archive's changelog asks for that archive's own version."""
        window = (ROOT / "build" / "setup" / "SetupWindow.cs").read_text(encoding="utf-8")
        self.assertIn('InstallerNotes.Section(own ?? Text(Docs + "CHANGELOG.md"), Version)', window)
        dashboard = (ROOT / "gui" / "DashboardMaintenance.cs").read_text(encoding="utf-8")
        self.assertIn("InstallerNotes.Section(ReadText(file), version)", dashboard)


class TrimTests(unittest.TestCase):
    """trim_runtime, on a runtime made for the purpose."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="car-trim-")
        self.addCleanup(folder.cleanup)
        self.work = Path(folder.name)
        self.keep = {"python": "9.9.9", "sha256": "ab" * 32, "library_zip": "python99.zip",
                     "files": ["python.exe", "python99.zip", "_keep.pyd"],
                     "library": ["os.pyc", "pack/__init__.pyc", "pack/data.txt"], "reviewed": {}}
        self.make = self.pointed(self.keep)
        self.stage = self.staged(self.work / "stage")

    def pointed(self, keep):
        make = builder()
        make.ROOT = self.work / "root"
        make.PYTHON_VERSION, make.PYTHON_SHA256 = "9.9.9", "ab" * 32
        (make.ROOT / "build").mkdir(parents=True, exist_ok=True)
        (make.ROOT / "build" / "runtime_keep.json").write_text(json.dumps(keep), encoding="utf-8")
        return make

    def staged(self, stage: Path) -> Path:
        runtime = stage / "payload" / "runtime"
        runtime.mkdir(parents=True)
        for name in ("python.exe", "_keep.pyd", "_gone.pyd", "other.dll"):
            (runtime / name).write_bytes(b"MZ " + name.encode())
        with zipfile.ZipFile(runtime / "python99.zip", "w", zipfile.ZIP_DEFLATED) as library:
            for name in ("os.pyc", "gone.pyc", "pack/__init__.pyc", "pack/data.txt", "gonepack/__init__.pyc",
                         "gonepack/sub.pyc"):
                library.writestr(zipfile.ZipInfo(name, (2026, 3, 4, 5, 6, 8)), b"bytes of " + name.encode())
        return stage

    def test_only_what_the_list_names_stays(self):
        removed = self.make.trim_runtime(self.stage)
        runtime = self.stage / "payload" / "runtime"
        self.assertEqual({path.name for path in runtime.iterdir()}, set(self.keep["files"]))
        with zipfile.ZipFile(runtime / "python99.zip") as library:
            self.assertEqual(library.namelist(), self.keep["library"], "the kept members keep their order")
            self.assertEqual(library.read("os.pyc"), b"bytes of os.pyc")
            self.assertEqual(library.getinfo("os.pyc").date_time, (2026, 3, 4, 5, 6, 8))
        self.assertEqual(removed, ["_gone", "gone", "gonepack", "gonepack.sub"])

    def test_the_same_inputs_give_the_same_bytes(self):
        self.make.trim_runtime(self.stage)
        again = self.staged(self.work / "again")
        self.make.trim_runtime(again)
        first, second = [(stage / "payload" / "runtime" / "python99.zip").read_bytes() for stage in (self.stage, again)]
        self.assertEqual(first, second)

    def test_a_list_made_for_another_runtime_stops_the_build(self):
        make = self.pointed(dict(self.keep, sha256="cd" * 32))
        with self.assertRaisesRegex(SystemExit, "was made for Python"):
            make.trim_runtime(self.stage)

    def test_a_named_file_the_runtime_lacks_stops_the_build(self):
        make = self.pointed(dict(self.keep, files=self.keep["files"] + ["missing.dll"]))
        with self.assertRaisesRegex(SystemExit, "missing.dll"):
            make.trim_runtime(self.stage)

    def test_a_named_member_the_library_lacks_stops_the_build(self):
        make = self.pointed(dict(self.keep, library=self.keep["library"] + ["missing.pyc"]))
        with self.assertRaisesRegex(SystemExit, "missing.pyc"):
            make.trim_runtime(self.stage)


class BuildOrderTests(unittest.TestCase):
    def test_the_digest_comes_first_and_the_check_before_the_archive(self):
        source = (ROOT / "build" / "make_release.py").read_text(encoding="utf-8")
        body = source[source.index("def main(argv=None)"):]
        steps = ["fetch_runtime()", "collect_runtime(stage, archive)", "trim_runtime(stage)", "collect_app(stage)",
                 "check_trimmed_runtime(stage, removed)", "check_courier_starts(stage)", "write_archive(stage"]
        places = [body.index(step) for step in steps]
        self.assertEqual(places, sorted(places), "the build's steps moved")


class RuntimeKeepListTests(unittest.TestCase):
    """The checked-in list, as far as it can be read with no runtime at hand."""

    def setUp(self):
        self.make = builder()
        self.keep = self.make.runtime_keep()

    def test_it_is_the_list_for_the_runtime_the_build_bundles(self):
        self.assertEqual((self.keep["python"], self.keep["sha256"]),
                         (self.make.PYTHON_VERSION, self.make.PYTHON_SHA256),
                         "the bundled Python moved: see trim_runtime")

    def test_what_the_owner_kept_is_kept(self):
        """The OpenSSL set stays (v0.6.23 decision), and what the watcher, the store and a courier stand on."""
        for name in ("libcrypto-3.dll", "libssl-3.dll", "_ssl.pyd", "_hashlib.pyd", "_sqlite3.pyd", "sqlite3.dll",
                     "_ctypes.pyd", "unicodedata.pyd", "python.exe", "pythonw.exe", "python314.zip", "python314._pth"):
            self.assertIn(name, self.keep["files"])
        for member in ("encodings/__init__.pyc", "encodings/cp949.pyc", "encodings/idna.pyc", "ssl.pyc", "sqlite3/__init__.pyc",
                       "ctypes/__init__.pyc", "zipfile/__init__.pyc", "runpy.pyc", "_ast_unparse.pyc", "difflib.pyc",
                       "_strptime.pyc", "_pylong.pyc"):
            self.assertIn(member, self.keep["library"])

    def test_every_review_says_why(self):
        for key, reason in self.keep["reviewed"].items():
            self.assertIn(" -> ", key)
            self.assertGreater(len(reason), 15, key)


class RuntimeCheckTests(unittest.TestCase):
    """build/runtime_check.py's readings, one by one."""

    def setUp(self):
        self.check = checker()

    def test_an_import_deep_in_a_function_and_guarded_is_read(self):
        source = ("import a.b\nfrom c import d\nfrom . import ours\n"
                  "def f():\n    try:\n        import lazy\n    except ImportError:\n        pass\n"
                  "    __import__('dunder')\n    importlib.import_module('named')\n    importlib.import_module(x)\n")
        self.assertEqual(self.check.statements(source), {"a.b", "c", "c.d", "lazy", "dunder", "named"})

    def test_a_shipped_import_of_a_module_that_went_is_a_finding(self):
        with tempfile.TemporaryDirectory(prefix="car-check-") as work:
            path = Path(work) / "m.py"
            path.write_text("def rare():\n    import xml.etree.ElementTree\n", encoding="utf-8")
            found = self.check.shipped_findings([path], {"xml.etree", "xml.etree.ElementTree"})
            self.assertEqual(len(found), 1, found)
            self.assertIn("xml.etree.ElementTree", found[0])
            self.assertEqual(self.check.shipped_findings([path], {"gone"}), [])

    def make_library(self, folder: Path) -> Path:
        library = folder / "library.zip"
        with zipfile.ZipFile(library, "w") as bundle:
            bundle.writestr("kept.pyc", pyc("def rare():\n    import gone.sub\n\nclass A:\n    import fine\n"))
            bundle.writestr("pack/__init__.pyc", pyc("from . import gonesib\nfrom .here import x\n"))
            bundle.writestr("pack/mod.pyc", pyc("from .. import gonetop\nfrom gonefrom import y\n"))
            bundle.writestr("note.txt", b"not a module")
        return library

    def test_the_imports_of_the_kept_library_are_read_from_its_bytecode(self):
        with tempfile.TemporaryDirectory(prefix="car-check-") as work:
            edges = self.check.library_edges(self.make_library(Path(work)), {"gone", "pack.gonesib", "gonefrom", "gonetop"})
        self.assertEqual(edges, {("kept", "gone.sub"), ("pack", "pack.gonesib"), ("pack.mod", "gonefrom"),
                                 ("pack.mod", "gonefrom.y")})

    def test_an_import_nobody_read_is_a_finding_and_so_is_a_stale_review(self):
        edges = {("a", "gone.x"), ("b", "gone")}
        self.assertEqual(self.check.library_findings(edges, {"a -> gone": "why", "b -> gone": "why"}), [])
        unread = self.check.library_findings(edges, {"a -> gone": "why"})
        self.assertEqual(len(unread), 1, unread)
        self.assertIn("b can import gone", unread[0])
        stale = self.check.library_findings(edges, {"a -> gone": "why", "b -> gone": "why", "c -> gone": "why"})
        self.assertEqual(len(stale), 1, stale)
        self.assertIn("c -> gone", stale[0])

    def test_a_module_that_acts_when_imported_is_stopped(self):
        for event in ("subprocess.Popen", "winreg.SetValue", "socket.connect", "os.system"):
            with self.assertRaisesRegex(RuntimeError, "importing a module tried"):
                self.check._no_effects(event, ())
        self.check._no_effects("open", ())

    def test_a_module_that_does_not_import_is_a_finding(self):
        with tempfile.TemporaryDirectory(prefix="car-check-") as work:
            (Path(work) / "car_size_bad.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
            sys.path.insert(0, work)
            self.addCleanup(sys.path.remove, work)
            found = self.check.import_findings(["car_size_bad"])
            self.assertEqual(len(found), 1, found)
            self.assertIn("SystemExit", found[0])


class TrimmedCheckBuildTests(unittest.TestCase):
    """check_trimmed_runtime, the build step, under an interpreter that ignores the environment as the bundled one does."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="car-trim-check-")
        self.addCleanup(folder.cleanup)
        self.work = Path(folder.name)
        self.stage = self.work / "stage"
        runtime = self.stage / "payload" / "runtime"
        if not stand_in_runtime(runtime):
            self.skipTest("this interpreter has no python3XX.dll, python.exe and pythonw.exe to stand in with")
        with zipfile.ZipFile(runtime / "library.zip", "w") as library:
            library.writestr("kept.pyc", pyc("def rare():\n    import gone\n"))
        src = self.stage / "payload" / "app" / "src"
        (src / "car_app").mkdir(parents=True)
        (src / "car_app" / "__init__.py").write_text("import json\n", encoding="utf-8")
        (self.stage / "payload" / "app" / "scripts").mkdir()
        root = self.work / "root"
        (root / "build").mkdir(parents=True)
        shutil.copyfile(ROOT / "build" / "runtime_check.py", root / "build" / "runtime_check.py")
        (root / "build" / "smoke_archive.py").write_text("import json\n", encoding="utf-8")
        (root / "build" / "runtime_keep.json").write_text(json.dumps(
            {"library_zip": "library.zip", "reviewed": {"kept -> gone": "the reason"}}), encoding="utf-8")
        self.make = builder()
        self.make.ROOT = root
        self.src = src

    def test_a_payload_that_holds_passes_and_leaves_no_bytecode(self):
        self.make.check_trimmed_runtime(self.stage, ["gone"])
        self.assertEqual(list((self.stage / "payload").rglob("__pycache__")), [])

    def test_a_module_that_needs_a_module_that_went_stops_the_build(self):
        (self.src / "car_app" / "broken.py").write_text("import no_such_module_at_all\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "car_app.broken does not import"):
            self.make.check_trimmed_runtime(self.stage, ["gone"])

    def test_a_rare_path_that_imports_a_module_that_went_stops_the_build(self):
        (self.src / "car_app" / "rare.py").write_text("def only_sometimes():\n    import gone\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "imports gone"):
            self.make.check_trimmed_runtime(self.stage, ["gone"])

    def test_an_import_of_the_library_nobody_read_stops_the_build(self):
        (self.make.ROOT / "build" / "runtime_keep.json").write_text(json.dumps(
            {"library_zip": "library.zip", "reviewed": {}}), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "kept can import gone"):
            self.make.check_trimmed_runtime(self.stage, ["gone"])


class BudgetTests(unittest.TestCase):
    """(c) The app's packed bytes, as write_archive packs them: each staged file deflated at level 9."""

    @staticmethod
    def group(name: str) -> str:
        if name.startswith("src/codex_auto_resume/locales/"):
            return "locales"
        if name.startswith("src/codex_auto_resume/mcp/assets/"):
            return "panel assets"
        if name.startswith(("src/codex_auto_resume_advanced/", "skills/codex-auto-resume-advanced/")):
            return "advanced"
        return name.split("/")[0]

    def table(self, app: dict) -> str:
        groups = {}
        for name, data in app.items():
            group = self.group(name)
            groups[group] = groups.get(group, 0) + len(zlib.compress(data, 9))
        return "\n".join("%-14s %9d bytes" % (group, size) for group, size in sorted(groups.items(), key=lambda g: -g[1]))

    @staticmethod
    def packed(app: dict) -> int:
        return sum(len(zlib.compress(data, 9)) for data in app.values())

    def setUp(self):
        self.budget = json.loads(BUDGET.read_text(encoding="utf-8"))

    def test_the_standard_app_stays_inside_its_budget(self):
        app = staged_app(builder(), False)
        limit = self.budget["standard_app_mib"] * MIB
        self.assertLessEqual(self.packed(app), limit, "over tests/data/release_budget.json; per group:\n" + self.table(app))

    @unittest.skipUnless((ROOT / "advanced").is_dir(), "no advanced/ tree in this checkout")
    def test_the_advanced_edition_adds_no_more_than_its_budget(self):
        standard, advanced = staged_app(builder(), False), staged_app(builder(), True)
        limit = self.budget["advanced_extra_mib"] * MIB
        self.assertLessEqual(self.packed(advanced) - self.packed(standard), limit,
                             "over tests/data/release_budget.json; per group:\n" + self.table(advanced))


class TrimmedRuntimeTests(unittest.TestCase):
    """(d) Under the pinned runtime as the build trims it, every module of this lane's edition imports."""

    def test_the_trimmed_runtime_runs_every_shipped_module(self):
        make = builder()
        cached = make.CACHE / make.PYTHON_ZIP
        if not cached.is_file() or hashlib.sha256(cached.read_bytes()).hexdigest() != make.PYTHON_SHA256:
            self.skipTest("the pinned runtime is not in build/cache; every release build runs this check itself")
        with tempfile.TemporaryDirectory(prefix="car-runtime-") as work:
            stage = Path(work)
            make.collect_runtime(stage, cached)
            removed = make.trim_runtime(stage)
            self.assertGreater(len(removed), 100)
            make.collect_app(stage)
            if os.environ.get("CODEX_AR_EDITION") == "advanced":
                make.collect_advanced(stage)
            make.check_trimmed_runtime(stage, removed)


if __name__ == "__main__":
    unittest.main()
