"""build/edition_audit.py: the proof that the standard archive holds nothing of the advanced edition.

An audit that has never been seen to fail proves nothing, so each of its six checks is held to
small archives made here for the purpose: a clean pair it must pass, and beside it the same pair
with one fault put in, which it must catch and name. Then what it reads from this repository - the
advanced tree, and the core it tells that tree apart from - and its allowances, held to the files
the standard build really ships, so none of them can go stale or grow unnoticed.

(e) builds the standard archive again from a commit. It is held here on a small repository of its
own, with a stand-in build, because what matters is what it builds from: the commit and not the
working tree, and never with advanced/ in it. tests/test_edition_build.py makes the same proof on
the real build, and the release job runs the real one.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import edition_audit as audit  # noqa: E402
import make_release  # noqa: E402

PACKAGE, SKILL, SENTINEL = audit.PACKAGE, audit.SKILL, audit.SENTINEL
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
LAUNCHER = "payload/app/mcp/" + make_release.MCP_EXE

# A small advanced tree: a package, a window source and a skill, each carrying the sentinel.
PLUG = ("# %s: in the advanced edition's archive, never the standard one's.\n"
        "class AdvancedPlug:\n"
        "    ARMING_LIMIT = 12\n"
        "    edition = 'advanced'\n"
        "\n"
        "    def create(self, paths):\n"
        "        return paths\n" % SENTINEL).encode("utf-8")
PAGE = ("// %s: in the advanced edition's window, never the standard one's.\n"
        "namespace CodexAutoResume\n"
        "{\n"
        "    internal sealed partial class SettingsForm\n"
        "    {\n"
        "        partial void DashboardBuilt() { ArmingPage.Show(\"Watch first, then turn on\"); }\n"
        "    }\n"
        "    // A comment's words are not names: WordsInAComment\n"
        "    internal static class ArmingPage { internal static void Show(string title) { } }\n"
        "}\n" % SENTINEL).encode("utf-8")
ADVANCED_FILES = {
    "advanced/src/%s/__init__.py" % PACKAGE: ("# %s\n\"\"\"The advanced edition.\"\"\"\n" % SENTINEL).encode(),
    "advanced/src/%s/plug.py" % PACKAGE: PLUG,
    "advanced/gui/ArmingPage.cs": PAGE,
    "advanced/skills/%s/SKILL.md" % SKILL: ("<!-- %s -->\n# The advanced skill\n" % SENTINEL).encode(),
    "advanced/src/%s/empty.py" % PACKAGE: b"",
}
CORE_PYTHON = ["class Plug:\n    edition = 'standard'\n    PLUG_API = 1\n\n    def create(self): return 1\n",
               "def tick(view):\n    return view\n"]
CORE_CSHARP = ["namespace CodexAutoResume { internal sealed partial class SettingsForm {"
               " partial void DashboardBuilt(); string page = \"Overview\"; } }"]
MANIFEST = {"name": "codex-auto-resume", "version": "0.6.11",
            "interface": {"displayName": "Codex Auto Resume", "shortDescription": "Auto-resume"}}


def manifest(display: str) -> bytes:
    document = json.loads(json.dumps(MANIFEST))
    document["interface"]["displayName"] = display
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def inventory() -> audit.Inventory:
    return audit.Inventory.build(ADVANCED_FILES, CORE_PYTHON, CORE_CSHARP)


def pair() -> tuple[dict, dict]:
    """A clean standard archive and the advanced one beside it, as entry -> bytes."""
    standard = {
        "Install.cmd": b"@echo off\r\n",
        "install/install.ps1": ("$package = Join-Path $Src '%s'\r\n" % PACKAGE).encode(),
        audit.WINDOW: b"MZ\x00\x00the standard window\x00Overview",
        "payload/codex-auto-resume.ico": b"\x00\x00\x01\x00an icon",
        "payload/app/.codex-plugin/plugin.json": manifest("Codex Auto Resume"),
        "payload/app/src/codex_auto_resume/edition.py": ('ADVANCED_PACKAGE = "%s"\n' % PACKAGE).encode(),
        "payload/app/src/codex_auto_resume/engine.py": b"def tick(view):\n    return view\n",
        "payload/app/src/codex_auto_resume/__init__.py": b"",
        LAUNCHER: b"MZ\x00\x00the launcher",
        "payload/runtime/python.exe": b"MZ\x00\x00python",
    }
    advanced = dict(standard)
    advanced[audit.WINDOW] = b"MZ\x00\x00the advanced window\x00ArmingPage"
    advanced["payload/app/.codex-plugin/plugin.json"] = manifest("Codex Auto Resume Advanced")
    advanced["payload/app/src/%s/__init__.py" % PACKAGE] = ADVANCED_FILES["advanced/src/%s/__init__.py" % PACKAGE]
    advanced["payload/app/src/%s/plug.py" % PACKAGE] = PLUG
    advanced["payload/app/skills/%s/SKILL.md" % SKILL] = ADVANCED_FILES["advanced/skills/%s/SKILL.md" % SKILL]
    return standard, advanced


def write_zip(path: Path, entries: dict) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in entries.items():
            bundle.writestr(name, data)
    return path


class InventoryTests(unittest.TestCase):
    """What the audit looks for, from what the advanced tree declares and the core does not."""

    def setUp(self):
        self.tree = inventory()

    def test_the_names_are_the_ones_only_the_advanced_tree_has(self):
        self.assertEqual(self.tree.names, {PACKAGE, SKILL, SENTINEL, "AdvancedPlug", "ARMING_LIMIT"})

    def test_the_cores_words_and_plain_words_are_not_its(self):
        """`create` and `edition` are English as often as code; PLUG_API and DashboardBuilt are
        the core's own, declared where the advanced edition plugs in."""
        for name in ("create", "edition", "paths", "PLUG_API", "tick", "empty"):
            self.assertNotIn(name, self.tree.names)
        for name in ("SettingsForm", "DashboardBuilt", "partial", "WordsInAComment"):
            self.assertNotIn(name, self.tree.window)

    def test_the_window_is_read_for_its_own_names_and_strings(self):
        self.assertEqual(self.tree.window, {PACKAGE, SKILL, SENTINEL, "ArmingPage"})
        self.assertEqual(self.tree.literals, {"Watch first, then turn on"})

    def test_every_non_empty_file_is_known_by_its_bytes_in_either_line_ending(self):
        import hashlib
        for name, data in ADVANCED_FILES.items():
            with self.subTest(name):
                crlf = data.replace(b"\n", b"\r\n")
                known = hashlib.sha256(data).hexdigest() in self.tree.digests
                self.assertEqual(known, bool(data.strip()), "an empty file is every empty file")
                if data.strip():
                    self.assertIn(hashlib.sha256(crlf).hexdigest(), self.tree.digests)

    def test_the_repositorys_own_tree_is_read_and_loudly(self):
        import hashlib
        tree = audit.inventory()
        self.assertTrue({PACKAGE, SKILL, SENTINEL, "AdvancedPlug"} <= tree.names)
        shipped = audit.tracked(ROOT, *("advanced/" + name for name in audit.SHIPPED))
        self.assertIn("advanced/src/%s/plug.py" % PACKAGE, shipped)
        for name in shipped:
            with self.subTest(name):
                lf = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertIn(hashlib.sha256(lf).hexdigest(), tree.digests)
                self.assertIn(hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest(), tree.digests)
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(SystemExit):
            subprocess.run(["git", "init", "-q", empty], check=True, capture_output=True)
            audit.inventory(Path(empty))


class CleanPairTests(unittest.TestCase):
    def test_a_clean_pair_has_no_finding(self):
        standard, advanced = pair()
        tree = inventory()
        self.assertEqual(audit.check_paths(standard), [])
        self.assertEqual(audit.check_digests(standard, tree), [])
        found, used = audit.check_names(standard, tree)
        self.assertEqual(found, [])
        self.assertEqual(used, {("payload/app/src/codex_auto_resume/edition.py", PACKAGE),
                                ("install/install.ps1", PACKAGE)})
        self.assertEqual(audit.check_executables(standard, tree), [])
        self.assertEqual(audit.check_superset(standard, advanced), [])

    def test_the_whole_audit_reads_the_two_files(self):
        standard, advanced = pair()
        with tempfile.TemporaryDirectory() as work:
            ours = write_zip(Path(work) / "standard.zip", standard)
            theirs = write_zip(Path(work) / "advanced.zip", advanced)
            self.assertEqual(audit.audit(ours, theirs, rebuild=lambda root, where: ours), [])
            # The repository's own plug, which is what audit() reads the advanced tree from.
            real = (ROOT / "advanced" / "src" / PACKAGE / "plug.py").read_bytes()
            broken = write_zip(Path(work) / "broken.zip", dict(standard, **{"payload/app/x.py": real}))
            found = audit.audit(broken, theirs, rebuild=lambda root, where: ours)
            self.assertTrue(any(line.startswith("(b)") for line in found), found)
            self.assertTrue(any(line.startswith("(e)") for line in found), found)


class FaultTests(unittest.TestCase):
    """One fault at a time, each caught by its own check and named."""

    def setUp(self):
        self.standard, self.advanced = pair()
        self.tree = inventory()

    def test_a_an_entry_where_the_advanced_files_go(self):
        for name in ("payload/app/src/%s/__init__.py" % PACKAGE,
                     "payload/app/skills/%s/SKILL.md" % SKILL,
                     "Payload/App/Src/%s/plug.py" % PACKAGE.upper(),
                     "payload/app/advanced/src/anything.py",
                     "payload/app/src/elsewhere/%s/x.py" % PACKAGE):
            with self.subTest(name):
                found = audit.check_paths(dict(self.standard, **{name: b"x = 1\n"}))
                self.assertEqual(found, ["(a) %s lies where the advanced edition's files go" % name])

    def test_b_a_file_of_the_advanced_tree_under_another_name(self):
        for data in (PLUG, PLUG.replace(b"\n", b"\r\n")):
            found = audit.check_digests(dict(self.standard, **{"payload/app/src/renamed.txt": data}), self.tree)
            self.assertEqual(found, ["(b) payload/app/src/renamed.txt has the bytes of a file of the advanced tree"])

    def test_c_a_text_entry_that_spells_an_advanced_name(self):
        for name in ("AdvancedPlug", "ARMING_LIMIT", SENTINEL, PACKAGE, SKILL):
            with self.subTest(name):
                entry = "payload/app/src/codex_auto_resume/leak.py"
                found, _ = audit.check_names(dict(self.standard, **{entry: ("# %s\n" % name).encode()}), self.tree)
                self.assertEqual(found, ["(c) %s spells %s" % (entry, name)])

    def test_c_an_allowance_is_for_one_name_in_one_entry(self):
        entry = "payload/app/src/codex_auto_resume/edition.py"
        spoiled = self.standard[entry] + b"from x import AdvancedPlug\n"
        found, _ = audit.check_names(dict(self.standard, **{entry: spoiled}), self.tree)
        self.assertEqual(found, ["(c) %s spells AdvancedPlug" % entry])

    def test_c_a_name_inside_a_longer_one_is_another_name(self):
        entry = "payload/app/src/codex_auto_resume/engine.py"
        found, _ = audit.check_names(dict(self.standard, **{entry: b"AdvancedPlugin = MyAdvancedPlug = 1\n"}),
                                     self.tree)
        self.assertEqual(found, [])

    def test_c_reads_text_and_leaves_binaries_to_d(self):
        found, _ = audit.check_names(dict(self.standard, **{"payload/runtime/x.dll": b"\x00AdvancedPlug"}),
                                     self.tree)
        self.assertEqual(found, [])

    def test_d_an_executable_that_holds_an_advanced_name_or_string(self):
        cases = {
            "ArmingPage": (audit.WINDOW, b"MZ\x00ArmingPage\x00"),
            # As the #US heap holds a literal: a length byte, the UTF-16 text, a flag byte.
            "ArmingPage as UTF-16": (audit.WINDOW, b"MZ\x00\x00\x15" + "ArmingPage".encode("utf-16-le") + b"\x00"),
            "the literal": (audit.WINDOW, b"MZ" + "Watch first, then turn on".encode("utf-16-le")),
            "the sentinel in the launcher": (LAUNCHER, b"MZ" + SENTINEL.encode("utf-16-le")),
        }
        for label, (entry, data) in cases.items():
            with self.subTest(label):
                found = audit.check_executables(dict(self.standard, **{entry: data}), self.tree)
                self.assertEqual(len(found), 1, found)
                self.assertTrue(found[0].startswith("(d) %s holds" % entry), found)

    def test_d_a_longer_name_is_not_the_advanced_one_and_a_missing_window_is_a_finding(self):
        longer = dict(self.standard, **{audit.WINDOW: b"MZ\x00ArmingPageHelper\x00" +
                                        "SmallArmingPage".encode("utf-16-le")})
        self.assertEqual(audit.check_executables(longer, self.tree), [])
        missing = dict(self.standard)
        del missing[audit.WINDOW]
        self.assertEqual(audit.check_executables(missing, self.tree),
                         ["(d) the standard archive has no %s to read" % audit.WINDOW])

    def test_d_reads_only_our_executables(self):
        runtime = dict(self.standard, **{"payload/runtime/python.exe": b"MZ\x00ArmingPage\x00"})
        self.assertEqual(audit.check_executables(runtime, self.tree), [])

    def test_e_the_same_file_or_a_list_of_what_differs(self):
        with tempfile.TemporaryDirectory() as work:
            ours = write_zip(Path(work) / "a.zip", self.standard)
            again = write_zip(Path(work) / "b.zip", self.standard)
            self.assertEqual(audit.check_rebuild(ours, again), [])
            other = dict(self.standard, **{"payload/app/src/codex_auto_resume/engine.py": b"changed\n",
                                           "payload/app/extra.txt": b"x"})
            changed = write_zip(Path(work) / "c.zip", other)
            found = audit.check_rebuild(ours, changed)
            self.assertTrue(found[0].startswith("(e) the standard archive is not the one built"), found)
            self.assertEqual(found[1:], ["(e)   payload/app/extra.txt: only in the rebuild",
                                         "(e)   payload/app/src/codex_auto_resume/engine.py: differs"])

    def test_f_every_way_the_advanced_archive_can_be_more_than_the_standard_one_plus_its_own(self):
        manifest_entry = "payload/app/.codex-plugin/plugin.json"
        engine = "payload/app/src/codex_auto_resume/engine.py"
        wrong_name = json.loads(self.advanced[manifest_entry])
        wrong_name["interface"]["displayName"] = "Codex Auto Resume Pro"
        more = json.loads(self.advanced[manifest_entry])
        more["version"] = "0.6.12"
        cases = {
            "missing": ({engine: None}, "(f) %s is missing from the advanced archive" % engine),
            "differs": ({engine: b"def tick(view):\n    return None\n"},
                        "(f) %s differs in the advanced archive" % engine),
            "display name": ({manifest_entry: json.dumps(wrong_name, indent=2).encode() + b"\n"},
                             "(f) the advanced manifest's display name is not 'Codex Auto Resume Advanced'"),
            "more than the name": ({manifest_entry: json.dumps(more, indent=2).encode() + b"\n"},
                                   "(f) the manifests differ in more than the display name"),
            "added elsewhere": ({"payload/app/src/codex_auto_resume/armed.py": b"x = 1\n"},
                                "(f) the advanced archive adds payload/app/src/codex_auto_resume/armed.py "
                                "outside its own places"),
            "no plug": ({"payload/app/src/%s/plug.py" % PACKAGE: None},
                        "(f) the advanced archive has no payload/app/src/%s/plug.py" % PACKAGE),
        }
        for label, (change, expected) in cases.items():
            with self.subTest(label):
                advanced = dict(self.advanced)
                for name, data in change.items():
                    if data is None:
                        del advanced[name]
                    else:
                        advanced[name] = data
                self.assertEqual(audit.check_superset(self.standard, advanced), [expected])

    def test_f_the_window_is_each_editions_own(self):
        self.assertNotEqual(self.standard[audit.WINDOW], self.advanced[audit.WINDOW])
        self.assertEqual(audit.check_superset(self.standard, self.advanced), [])


class Repository:
    """A small repository to rebuild from, with a stand-in build: make_gui.ps1 does nothing, and
    make_release.py zips every file of the tree it is in but build/, advanced/ included if it is
    there - so the rebuild's archive shows exactly what the tree held."""

    FAKE_RELEASE = (
        "import argparse, json, pathlib, zipfile\n"
        "root = pathlib.Path(__file__).resolve().parents[1]\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--edition')\n"
        "parser.add_argument('--output')\n"
        "args = parser.parse_args()\n"
        "version = json.loads((root / '.codex-plugin' / 'plugin.json').read_text())['version']\n"
        "out = pathlib.Path(args.output)\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "with zipfile.ZipFile(out / ('CodexAutoResume-v%s-win-x64.zip' % version), 'w') as bundle:\n"
        "    for path in sorted(root.rglob('*')):\n"
        "        if path.is_file() and path.relative_to(root).parts[0] != 'build':\n"
        "            bundle.writestr(path.relative_to(root).as_posix(), path.read_bytes())\n"
    )

    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        hooks = root.parent / "nohooks"
        hooks.mkdir()
        self.git("init", "-q", "-b", "main")
        for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("core.autocrlf", "false"),
                           ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks))):
            self.git("config", key, value)
        self.write({".codex-plugin/plugin.json": b'{"version": "9.9.9"}',
                    "src/codex_auto_resume/engine.py": b"committed = True\n",
                    "advanced/src/%s/plug.py" % PACKAGE: PLUG,
                    "build/make_gui.ps1": b"param([string]$Root)\r\n",
                    "build/make_release.py": self.FAKE_RELEASE.encode()})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "a commit to rebuild")

    def write(self, files: dict) -> None:
        for name, data in files.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(data)

    def git(self, *args: str) -> None:
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                              env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1"))
        if done.returncode != 0:
            raise AssertionError("git %s: %s" % (" ".join(args), done.stderr.decode("utf-8", "replace")))


@unittest.skipUnless(POWERSHELL.is_file(), "the rebuild runs make_gui.ps1, which needs PowerShell")
class RebuildTests(unittest.TestCase):
    """(e) builds from the commit, never the working tree, and never with advanced/ in it."""

    def test_the_rebuild_is_of_the_commit_with_advanced_deleted(self):
        with tempfile.TemporaryDirectory() as work:
            repository = Repository(Path(work) / "repository")
            # Neither an edit nor an untracked file is what the commit holds.
            repository.write({"src/codex_auto_resume/engine.py": b"committed = False\n",
                              "src/codex_auto_resume/untracked.py": b"stray = 1\n"})
            (Path(work) / "rebuild").mkdir()
            archive = audit.rebuild_standard(repository.root, Path(work) / "rebuild")
            self.assertEqual(archive.name, make_release.archive_name("standard", "9.9.9"))
            built = audit.entries(archive)
            self.assertEqual(sorted(built), [".codex-plugin/plugin.json", "src/codex_auto_resume/engine.py"])
            self.assertEqual(built["src/codex_auto_resume/engine.py"], b"committed = True\n")


class AllowanceTests(unittest.TestCase):
    """The allowances, held to the files the standard build ships: each is needed, and nothing
    else the build copies spells an advanced name or holds an advanced file."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="edition-allowances-"))
        make_release.collect_app(cls.work)
        make_release.collect_launchers(cls.work)
        make_release.declare_mcp_server(cls.work)
        cls.shipped = {path.relative_to(cls.work).as_posix(): path.read_bytes()
                       for path in sorted(cls.work.rglob("*")) if path.is_file()}
        cls.tree = audit.inventory()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_what_the_standard_build_copies_is_read(self):
        self.assertIn("payload/app/src/codex_auto_resume/edition.py", self.shipped)
        self.assertIn("install/install.ps1", self.shipped)
        self.assertGreater(len(self.shipped), 150, "the copy itself looks wrong")

    def test_every_allowance_is_needed_and_nothing_else_is_named(self):
        found, used = audit.check_names(self.shipped, self.tree)
        self.assertEqual(found, [])
        self.assertEqual(used, set(audit.ALLOWED))
        for (entry, name), reason in audit.ALLOWED.items():
            with self.subTest(entry):
                self.assertTrue(reason.strip())
                if name == SKILL:
                    # One more name, in one file: what the bootstrap refuses to find in a
                    # standard archive. Nothing reads it to decide which edition anything is.
                    self.assertEqual(entry, "payload/app/scripts/bootstrap.ps1")
                    continue
                self.assertEqual(name, PACKAGE, "only the package's name tells one edition from the other")

    def test_nothing_shipped_lies_where_the_advanced_files_go_or_is_one_of_them(self):
        self.assertEqual(audit.check_paths(self.shipped), [])
        self.assertEqual(audit.check_digests(self.shipped, self.tree), [])


class CommandLineTests(unittest.TestCase):
    def test_it_wants_both_archives(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(SystemExit) as refused:
            audit.main(["--dist", empty])
        self.assertIn("build both editions first", str(refused.exception))


if __name__ == "__main__":
    unittest.main()
