"""build/vocab_export.py: `vocab.json`, the closed vocabularies of one commit, for the Rust port to be held to.

The port generates its enums from this file and holds them to it both ways, so the file has to be right in
the ways a generator cannot check: it is read from a tag and never from a working tree, it is the same bytes
whenever the vocabularies are the same, it leaves out what is not a word (a number, a version, a sentence),
and the standard file carries no name of the advanced edition.

Most of it is held on a small repository of its own made here (src/ and advanced/src/ with a few
vocabularies, a tag, a commit after it and a file edited and not committed), because what matters is what
is read - the tag and not the working tree - and that nothing is written in the repository the tool is run on.
One run is on this repository's own HEAD: it parses, it holds the words every other test holds the code to,
it is the same bytes twice, and the edition audit's own name check (build/edition_audit.py, (c)) finds
nothing in it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "build" / "vocab_export.py"
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import vocab_export  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
IDENTITY = ("-c", "user.name=ExampleUser", "-c", "user.email=user@example.invalid", "-c", "commit.gpgsign=false")

PACKAGE = vocab_export.CORE
ADVANCED = vocab_export.ADVANCED

VOCABULARY = '''\
"""A small vocabulary of every shape the exporter reads."""
from enum import IntEnum, StrEnum


class Color(StrEnum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    CRIMSON = "red"


class Level(IntEnum):
    LOW = 1
    HIGH = 2


SET = frozenset({"b", "a", "c"})
ORDER = ("z", "y", "x")
WRITTEN = {"two": "2", "one": "1"}
BUILT = {name: "x" for name in SET}
NESTED = {"b": ("q", "p"), "a": frozenset({"n", "m"})}
BY_PAIR = {("k", "l"): "v"}
SOLO = "solo"
VERSION = "1.2.3-beta.4"
LONG = "x" * 65
SENTENCE = "one line\\nanother"
NUMBERS = (1, 2)
MIXED = ("a", 1)
_PRIVATE = ("p",)
lowercase = ("l",)
'''
EDITION = 'ADVANCED_PACKAGE = "%s"\nEDITIONS = ("standard", "advanced")\n' % ADVANCED
BROKEN = "raise ImportError('a module this interpreter cannot import')\n"
WINDOW = 'WORDS = ("drawn", "by", "the", "window")\n'
ADVANCED_VOCABULARY = '''\
from enum import StrEnum


class Mode(StrEnum):
    ON = "on"
    OFF = "off"


KEYS = ("alpha", "beta")
'''


def _git(repo: Path, *arguments: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *IDENTITY, *arguments], capture_output=True, timeout=120,
                          creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise AssertionError("git %s: %s" % (arguments[0], done.stderr.decode("utf-8", "replace")))
    return done.stdout.decode("utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _run(*arguments, cwd=None):
    return subprocess.run([sys.executable, str(TOOL), *arguments], capture_output=True, timeout=600,
                          creationflags=NO_WINDOW, cwd=cwd)


def _state(repo: Path, deep: bool = True) -> tuple:
    """What a tool could have changed in a repository: its files (`deep`), its head, and what git says."""
    files = {}
    if deep:
        files = {path.relative_to(repo).as_posix(): path.read_bytes()
                 for path in sorted(repo.rglob("*")) if path.is_file() and ".git" not in path.relative_to(repo).parts}
    return files, _git(repo, "rev-parse", "HEAD"), _git(repo, "status", "--porcelain")


def build_repo(repo: Path, advanced: bool = True) -> None:
    """The scratch repository: tag v1, a commit after it (Color gains PINK), and the file edited again, uncommitted."""
    base = repo / "src" / PACKAGE
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True, creationflags=NO_WINDOW)
    _write(base / "__init__.py", '"""The package."""\n')
    _write(base / "domain" / "__init__.py", "")
    _write(base / "domain" / "vocabulary.py", VOCABULARY)
    _write(base / "edition.py", EDITION)
    _write(base / "broken.py", BROKEN)
    _write(base / "win" / "__init__.py", WINDOW)
    if advanced:
        _write(repo / "advanced" / "src" / ADVANCED / "__init__.py", '"""The edition."""\n')
        _write(repo / "advanced" / "src" / ADVANCED / "vocabulary.py", ADVANCED_VOCABULARY)
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "-m", "One")
    _git(repo, "tag", "v1")
    vocabulary = base / "domain" / "vocabulary.py"
    _write(vocabulary, VOCABULARY.replace('    CRIMSON = "red"\n', '    CRIMSON = "red"\n    PINK = "pink"\n'))
    _git(repo, "commit", "--quiet", "-am", "Two")
    _write(vocabulary, vocabulary.read_text(encoding="utf-8").replace(
        '    PINK = "pink"\n', '    PINK = "pink"\n    BLACK = "black"\n'))


class Scratch(unittest.TestCase):
    """A repository of its own: tag v1, a commit after it, and a file edited and not committed."""

    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls._temp.name) / "repo"
        cls.out = Path(cls._temp.name) / "out"
        cls.out.mkdir()
        build_repo(cls.repo)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def export(self, ref, *more, name="vocab.json"):
        done = _run("--repo", str(self.repo), "--ref", ref, "--out", str(self.out / name), *more)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def vocabulary(self, document):
        return document["modules"]["domain.vocabulary"]


class WhatIsReadTests(Scratch):
    def test_a_tag_is_read_and_not_the_working_tree(self):
        members = [name for name, _ in self.vocabulary(self.export("v1"))["enums"]["Color"]["members"]]
        self.assertEqual(members, ["RED", "GREEN", "BLUE", "CRIMSON"])

    def test_head_is_read_and_not_what_is_edited_and_not_committed(self):
        members = [name for name, _ in self.vocabulary(self.export("HEAD"))["enums"]["Color"]["members"]]
        self.assertEqual(members, ["RED", "GREEN", "BLUE", "CRIMSON", "PINK"])

    def test_a_commit_is_read_as_a_tag_is(self):
        commit = _git(self.repo, "rev-parse", "v1").strip()
        self.assertEqual(self.export(commit, name="by-commit.json"), self.export("v1", name="by-tag.json"))

    def test_the_repository_is_not_touched(self):
        before = _state(self.repo)
        self.export("v1", "--advanced", name="touched.json")
        self.assertEqual(_state(self.repo), before, "the tool changed the repository it read")

    def test_it_writes_only_what_it_was_asked_to(self):
        folder = self.out / "only"
        folder.mkdir()
        done = _run("--repo", str(self.repo), "--ref", "v1", "--out", str(folder / "a.json"), cwd=str(folder))
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["a.json"])

    def test_an_unknown_ref_writes_nothing_and_fails(self):
        target = self.out / "none.json"
        done = _run("--repo", str(self.repo), "--ref", "v9", "--out", str(target))
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(target.exists())

    def test_a_ref_that_is_an_option_is_refused(self):
        target = self.out / "option.json"
        done = _run("--repo", str(self.repo), "--ref=--output=" + str(target), "--out", str(target))
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(target.exists())

    def test_a_ref_is_required(self):
        self.assertNotEqual(_run("--repo", str(self.repo)).returncode, 0)


class ShapeTests(Scratch):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        done = _run("--repo", str(cls.repo), "--ref", "v1", "--out", str(cls.out / "shape.json"))
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        cls.export_document = json.loads((cls.out / "shape.json").read_text(encoding="utf-8"))
        cls.document = cls.export_document["modules"]["domain.vocabulary"]

    def test_an_enum_keeps_its_members_in_order_with_its_aliases_and_its_base(self):
        enums = self.document["enums"]
        self.assertEqual(enums["Color"], {"base": "StrEnum", "members": [
            ["RED", "red"], ["GREEN", "green"], ["BLUE", "blue"], ["CRIMSON", "red"]]})
        self.assertEqual(enums["Level"], {"base": "IntEnum", "members": [["LOW", 1], ["HIGH", 2]]})

    def test_a_set_is_sorted_a_tuple_keeps_its_order_and_a_written_dict_its_keys(self):
        constants = self.document["constants"]
        self.assertEqual(constants["SET"], ["a", "b", "c"])
        self.assertEqual(constants["ORDER"], ["z", "y", "x"])
        self.assertEqual(list(constants["WRITTEN"]), ["two", "one"])
        self.assertEqual(constants["NESTED"], {"b": ["q", "p"], "a": ["m", "n"]})

    def test_a_dict_built_by_code_is_sorted_for_it_has_the_order_of_a_set(self):
        self.assertEqual(list(self.document["constants"]["BUILT"]), ["a", "b", "c"])

    def test_a_dict_with_keys_that_are_not_strings_is_pairs(self):
        self.assertEqual(self.document["constants"]["BY_PAIR"], {"pairs": [[["k", "l"], "v"]]})

    def test_a_word_is_a_word_and_nothing_else_is(self):
        constants = self.document["constants"]
        self.assertEqual(constants["SOLO"], "solo")
        for name in ("VERSION", "LONG", "SENTENCE", "NUMBERS", "MIXED", "_PRIVATE", "lowercase"):
            self.assertNotIn(name, constants)

    def test_a_module_that_does_not_import_is_named_and_the_windows_interface_is_left_out(self):
        document = self.export_document
        self.assertEqual(document["unimportable"], [["broken", "ImportError"]])
        self.assertNotIn("win", document["modules"])

    def test_no_edition_names_the_other(self):
        text = json.dumps(self.export_document)
        self.assertNotIn(ADVANCED, text)
        self.assertEqual(self.export_document["withheld"], 1)
        self.assertEqual(self.export_document["modules"]["edition"]["constants"], {"EDITIONS": ["standard", "advanced"]})

    def test_a_tree_without_the_settings_has_no_tables_to_give(self):
        self.assertEqual(self.export_document["tables"], {})


class AdvancedApartTests(Scratch):
    def test_without_the_flag_there_is_no_advanced_file_and_no_advanced_tree_is_read(self):
        self.export("v1", name="plain.json")
        self.assertEqual(sorted(path.name for path in self.out.glob("plain*")), ["plain.json"])

    def test_with_the_flag_the_standard_file_is_the_same_bytes(self):
        self.export("v1", name="a.json")
        self.export("v1", "--advanced", name="b.json")
        self.assertEqual((self.out / "a.json").read_bytes(), (self.out / "b.json").read_bytes())

    def test_the_advanced_file_holds_its_own_vocabularies_and_the_core_names_it_was_relieved_of(self):
        self.export("v1", "--advanced", name="c.json")
        advanced = json.loads((self.out / "c-advanced.json").read_text(encoding="utf-8"))
        self.assertEqual(advanced["edition"], "advanced")
        self.assertEqual(advanced["core_edition"], {"edition.ADVANCED_PACKAGE": ADVANCED})
        self.assertEqual(advanced["modules"]["vocabulary"]["enums"]["Mode"]["members"],
                         [["ON", "on"], ["OFF", "off"]])
        self.assertEqual(advanced["modules"]["vocabulary"]["constants"], {"KEYS": ["alpha", "beta"]})
        self.assertEqual(json.loads((self.out / "c.json").read_text(encoding="utf-8"))["edition"], "standard")

    def test_a_ref_without_an_advanced_tree_cannot_give_one(self):
        bare = Path(self._temp.name) / "bare"
        build_repo(bare, advanced=False)
        plain = _run("--repo", str(bare), "--ref", "v1", "--out", str(self.out / "bare.json"))
        self.assertEqual(plain.returncode, 0, plain.stderr.decode("utf-8", "replace"))
        done = _run("--repo", str(bare), "--ref", "v1", "--out", str(self.out / "bare2.json"), "--advanced")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("advanced", done.stderr.decode("utf-8", "replace"))
        self.assertFalse((self.out / "bare2.json").exists() or (self.out / "bare2-advanced.json").exists())


class ThisRepositoryTests(unittest.TestCase):
    """The real thing, once: this repository's HEAD."""

    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._temp.name)
        cls.before = _state(ROOT, deep=False)
        for name in ("first.json", "second.json"):
            done = _run("--ref", "HEAD", "--out", str(cls.out / name))
            assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        cls.after = _state(ROOT, deep=False)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def document(self):
        return json.loads((self.out / "first.json").read_text(encoding="utf-8"))

    def test_it_is_the_same_bytes_twice(self):
        self.assertEqual((self.out / "first.json").read_bytes(), (self.out / "second.json").read_bytes())

    def test_it_ends_in_one_lf_and_is_utf8_without_a_mark(self):
        data = (self.out / "first.json").read_bytes()
        self.assertTrue(data.endswith(b"}\n") and not data.endswith(b"\n\n"))
        self.assertFalse(data.startswith(b"\xef\xbb\xbf") or b"\r" in data)

    def test_the_words_every_other_test_holds_the_code_to_are_in_it(self):
        modules = self.document()["modules"]
        enums = modules["domain.vocabulary"]["enums"]
        states = [value for _, value in enums["RecordState"]["members"]]
        self.assertIn("waiting_reset", states)
        self.assertEqual(len(states), len(set(states)))
        for name, word in (("EventCode", "detected"), ("PublicCode", "waiting_reset"), ("GateName", None),
                           ("ErrorCode", None), ("Actor", "engine")):
            self.assertIn(name, enums)
            if word:
                self.assertIn(word, [value for _, value in enums[name]["members"]])
        for name in ("ReasonCode", "HomeState", "WithdrawReason"):
            self.assertIn(name, modules["domain.reason_vocabulary"]["enums"])
        self.assertIn("PowerAction", modules["domain.power_vocabulary"]["enums"])
        self.assertIn("CompatState", modules["domain.compat_vocabulary"]["enums"])
        self.assertIn("PLAIN", modules["controlcli"]["constants"])
        self.assertIn("BEFORE_WINDOW", modules["domain.skips"]["constants"])

    def test_the_settings_keys_and_the_interruption_categories_are_tables(self):
        tables = self.document()["tables"]
        self.assertIn("recover_usage_limit", tables["settings"]["keys"])
        self.assertEqual(sorted(tables["settings"]["keys"]), sorted(tables["settings"]["types"]))
        self.assertIn("usage_limit", [entry["category"] for entry in tables["interruption_categories"]])

    def test_every_module_imported(self):
        self.assertEqual(self.document()["unimportable"], [])

    def test_the_edition_audits_own_name_check_finds_no_advanced_name_in_it(self):
        import edition_audit
        found, _used = edition_audit.check_names({"vocab.json": (self.out / "first.json").read_bytes()},
                                                 edition_audit.inventory(ROOT))
        self.assertEqual(found, [])

    def test_nothing_of_this_machine_or_the_version_is_in_it(self):
        text = (self.out / "first.json").read_text(encoding="utf-8")
        for needle in ("\\\\Users\\\\", "C:\\\\", "/Users/"):
            self.assertNotIn(needle, text)
        version = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertNotIn(version, text)

    def test_the_repository_it_read_is_as_it_was(self):
        self.assertEqual(self.after, self.before)


class ExcludedTests(unittest.TestCase):
    def test_every_excluded_module_is_one_the_tree_has(self):
        known = {name for name, _ in vocab_export.module_names(ROOT / "src", PACKAGE, (), ())}
        for name in vocab_export.EXCLUDED_MODULES:
            self.assertIn(name, known, "EXCLUDED_MODULES names a module that is gone")
        for package in vocab_export.EXCLUDED_PACKAGES:
            self.assertTrue(any(name == package or name.startswith(package + ".") for name in known),
                            "EXCLUDED_PACKAGES names a package that is gone")


if __name__ == "__main__":
    unittest.main()
