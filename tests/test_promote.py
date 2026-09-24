"""dev holds both languages, main holds English only, and ko is built from main plus dev's Korean.

Each rule is checked on a scratch repository that plays all three parts, because the real ones
cannot be promoted in a test: `scripts/promote.py` moves work between dev and main in both
directions, and `scripts/ko_sync.py --bring-korean` puts the Korean sources back into a checkout of
main from the dev commit it came from. What must never happen is in the names below: a Korean
file reaching main, dev losing its Korean files to main's deletions, a promotion that carries
anything but dev, and a ko build from Korean written against English that main has since changed.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ko_sync  # noqa: E402
import promote  # noqa: E402

MAPPING = {"documents": {"README.ko.md": "README.md", "docs/X.ko.md": "docs/X.md"},
           "english_on_main": "https://example.invalid/blob/main/", "intentionally_english": {}}


class Scratch:
    """A repository with main and dev, both languages on dev, English only on main."""

    def __init__(self, root: Path):
        self.root = root
        self.git("init", "-q", "-b", "main")
        for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"),
                           ("core.autocrlf", "false")):
            self.git("config", key, value)
        self.write({"README.md": "# Tool\n", "docs/X.md": "# X\n\nEnglish.\n", "code.py": "A = 1\n",
                    "scripts/ko_branch.json": json.dumps(MAPPING)})
        self.commit("start")
        self.git("checkout", "-q", "-b", "dev")
        self.write({"README.ko.md": "# 도구\n", "docs/X.ko.md": "# X\n\n한국어.\n", "code.py": "A = 2\n"})
        self.commit("both languages on dev")

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                              encoding="utf-8")
        if done.returncode != 0:
            raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
        return done.stdout

    def write(self, files: dict) -> None:
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def tree(self, ref: str) -> dict:
        return {line.split("\t")[1]: line.split()[2]
                for line in self.git("ls-tree", "-r", ref).splitlines()}


class PromotionTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.repo = Scratch(Path(scratch.name))

    def promote(self, title="Promote"):
        self.repo.git("checkout", "-q", "main")
        return promote.to_main(self.repo.root, "dev", title)

    def test_main_is_dev_without_its_korean_documents(self):
        dev = self.repo.git("rev-parse", "dev").strip()
        self.promote()
        main, source = self.repo.tree("main"), self.repo.tree("dev")
        self.assertEqual(main, {name: blob for name, blob in source.items()
                                if not name.endswith(".ko.md")})
        self.assertIn("%s %s" % (promote.TRAILER, dev), self.repo.git("log", "-1", "--format=%B"))

    def test_a_promotion_needs_dev_to_contain_main_first(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write({"data.json": "{}\n"})
        self.repo.commit("data on main, not yet on dev")
        with self.assertRaises(promote.Refused):
            promote.to_main(self.repo.root, "dev", "Promote")
        self.assertEqual(self.repo.git("status", "--porcelain").strip(), "",
                         "a refused promotion must leave main as it was")

    def test_taking_main_back_keeps_every_korean_document(self):
        self.promote()
        self.repo.write({"data.json": "{\"sequence\": 3}\n"})
        self.repo.commit("data on main")
        self.repo.git("checkout", "-q", "dev")
        self.repo.write({"docs/X.ko.md": "# X\n\n고친 한국어.\n"})
        self.repo.commit("a Korean fix on dev")
        before = {name: blob for name, blob in self.repo.tree("dev").items() if name.endswith(".ko.md")}
        self.assertIsNotNone(promote.into_dev(self.repo.root, "main"))
        after = self.repo.tree("dev")
        self.assertEqual({name: blob for name, blob in after.items() if name.endswith(".ko.md")}, before)
        self.assertIn("data.json", after, "main's own change must reach dev")
        self.repo.git("merge-base", "--is-ancestor", "main", "dev")

    def test_the_cycle_repeats(self):
        self.promote("first")
        self.repo.git("checkout", "-q", "dev")
        promote.into_dev(self.repo.root, "main")
        self.repo.write({"docs/X.md": "# X\n\nEnglish, second.\n", "docs/X.ko.md": "# X\n\n두 번째.\n"})
        dev = self.repo.commit("second round, both languages")
        self.promote("second")
        self.assertNotIn("docs/X.ko.md", self.repo.tree("main"))
        self.assertEqual(self.repo.tree("main")["docs/X.md"], self.repo.tree("dev")["docs/X.md"])
        self.assertIn(dev, self.repo.git("log", "-1", "--format=%B", "main"))

    def test_notes_that_imitate_the_trailer_are_refused(self):
        self.repo.git("checkout", "-q", "main")
        with self.assertRaises(promote.Refused):
            promote.to_main(self.repo.root, "dev", "Promote",
                            "How ko finds its Korean:\nKorean-sources: the dev commit, below.")
        self.assertEqual(self.repo.git("status", "--porcelain").strip(), "")

    def test_main_that_already_is_dev_has_nothing_to_promote(self):
        self.repo.git("checkout", "-q", "-B", "main", "dev")
        with self.assertRaises(promote.Refused):
            promote.to_main(self.repo.root, "dev", "Promote")
        self.assertEqual(self.repo.git("status", "--porcelain").strip(), "",
                         "a refusal must not leave the Korean files staged for deletion")

    def test_a_failed_commit_leaves_main_as_it_was(self):
        self.repo.git("checkout", "-q", "main")
        hook = self.repo.root / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        before = self.repo.git("rev-parse", "HEAD")
        with self.assertRaises(promote.Refused):
            promote.to_main(self.repo.root, "dev", "Promote")
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.repo.git("status", "--porcelain").strip(), "")

    def test_dev_that_already_contains_main_has_nothing_to_take(self):
        self.repo.git("checkout", "-q", "dev")
        self.assertIsNone(promote.into_dev(self.repo.root, "main"))


class BringKoreanTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.repo = Scratch(Path(scratch.name))
        self.repo.git("checkout", "-q", "main")
        promote.to_main(self.repo.root, "dev", "Promote")

    def test_main_gets_the_korean_sources_of_the_dev_commit_it_came_from(self):
        brought = ko_sync.bring_korean(self.repo.root)
        self.assertEqual(brought, ["README.ko.md", "docs/X.ko.md"])
        self.assertEqual((self.repo.root / "docs" / "X.ko.md").read_text(encoding="utf-8"),
                         "# X\n\n한국어.\n")

    def test_a_later_data_change_on_main_does_not_hide_the_trailer(self):
        self.repo.write({"data.json": "{}\n"})
        self.repo.commit("data on main")
        self.assertEqual(len(ko_sync.bring_korean(self.repo.root)), 2)

    def test_english_main_changed_after_the_promotion_is_refused(self):
        """Korean written against older English must not be published as current."""
        self.repo.write({"docs/X.md": "# X\n\nEnglish changed on main alone.\n"})
        self.repo.commit("an English edit that skipped dev")
        with self.assertRaises(SystemExit):
            ko_sync.bring_korean(self.repo.root)

    def test_a_checkout_that_has_them_is_left_alone(self):
        self.repo.git("checkout", "-q", "dev")
        self.assertEqual(ko_sync.bring_korean(self.repo.root), [])

    def test_the_last_trailer_is_the_one(self):
        """A line in the prose above the trailer - a squash-merged message quoting one, say -
        must not break the sync or outvote the promotion's own."""
        real = ko_sync.korean_sources_commit(self.repo.root)
        self.repo.write({"data.json": "{}\n"})
        self.repo.git("add", "-A")
        self.repo.git("commit", "-q", "-m", "data\n\nKorean-sources: is how ko finds its text")
        with self.assertRaises(SystemExit):
            ko_sync.korean_sources_commit(self.repo.root)
        self.repo.git("reset", "-q", "--hard", "HEAD~1")
        self.assertEqual(ko_sync.korean_sources_commit(self.repo.root), real)

    def test_no_trailer_no_sources(self):
        self.repo.git("checkout", "-q", "-b", "stray", "main~1")
        with self.assertRaises(SystemExit):
            ko_sync.bring_korean(self.repo.root)


if __name__ == "__main__":
    unittest.main()
