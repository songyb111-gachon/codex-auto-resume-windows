"""The build, release and workflow findings of the v0.6.23 tooling audit (Area C), one class each.

* SidecarLineEndingTests (T1) - a .sha256 sidecar and release-notes.md are written with LF, so
  `sha256sum -c` finds the file it names; the digest is the file's, as before.
* JobTimeoutTests (W1, W2) - each long job of test.yml, release.yml and sync-ko.yml has a limit far
  above a healthy run and far below GitHub's six-hour default.
* TagOnMainTests (W3) - release.yml's build refuses a pushed tag whose commit is not on main, before it
  builds anything; a dispatch, which publishes nothing, is not refused.
* ForkGuardTests (W4) - sync-ko and ko-watch run only in this repository, as the other automations do.
* PayloadFolderTests (T2) - a folder inside a shipped tree named like a top-level one the build skips
  (config, logs, tests, ...) still ships; caches and virtual environments never do.
* RuntimeDownloadTests (T3) - a runtime download whose digest is wrong is removed, so the next build
  downloads it again instead of failing on the same cached file every time.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str, path: Path):
    here = str(path.parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job(workflow: str, name: str) -> str:
    """The text of one job of a workflow: its header line up to the next job's, read as text."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    found = re.search(r"^  %s:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)" % re.escape(name), text, re.M | re.S)
    if not found:
        raise AssertionError("%s has no job %s" % (workflow, name))
    return found.group(1)


def _timeout(workflow: str, name: str):
    found = re.search(r"^    timeout-minutes: (\d+)\s*$", _job(workflow, name), re.M)
    return int(found.group(1)) if found else None


class SidecarLineEndingTests(unittest.TestCase):
    def test_a_sidecar_ends_in_lf_and_holds_the_files_digest(self):
        make_release = _load("make_release", ROOT / "build" / "make_release.py")
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "sample.bin"
            target.write_bytes(b"sample bytes")
            digest = make_release.write_sidecar(target)
            written = (Path(scratch) / "sample.bin.sha256").read_bytes()
        self.assertEqual(digest, hashlib.sha256(b"sample bytes").hexdigest())
        self.assertEqual(written, ("%s  sample.bin\n" % digest).encode("ascii"))

    def test_release_notes_are_written_with_lf(self):
        notes = _load("release_notes", ROOT / "build" / "release_notes.py")
        with tempfile.TemporaryDirectory() as scratch:
            changelog = Path(scratch) / "CHANGELOG.md"
            changelog.write_text("# Changelog\n\n## v9.9.9\n\nOne line.\nTwo lines.\n\n## v9.9.8\n\nOld.\n",
                                 encoding="utf-8")
            output = Path(scratch) / "release-notes.md"
            notes.main(["9.9.9", "--changelog", str(changelog), "--output", str(output)])
            written = output.read_bytes()
        self.assertIn(b"One line.", written)
        self.assertNotIn(b"\r", written)


class JobTimeoutTests(unittest.TestCase):
    LIMITS = {
        ("test.yml", "test"): 150,
        ("test.yml", "main-tree"): 150,
        ("release.yml", "test"): 150,
        ("release.yml", "build"): 150,
        ("release.yml", "publish"): 15,
        ("sync-ko.yml", "test"): 90,
        ("sync-ko.yml", "publish"): 15,
    }

    def test_each_job_has_its_limit(self):
        for (workflow, name), minutes in self.LIMITS.items():
            with self.subTest(workflow=workflow, job=name):
                self.assertEqual(_timeout(workflow, name), minutes)


class TagOnMainTests(unittest.TestCase):
    def setUp(self):
        self.build = _job("release.yml", "build")
        found = re.search(r"- name: Refuse a tag that is not on main\n(.*?)(?=\n      - |\Z)", self.build, re.S)
        self.assertIsNotNone(found, "release.yml's build has no step refusing a tag that is not on main")
        self.step = found.group(1)

    def test_the_step_runs_for_a_tag_push_only(self):
        self.assertIn("if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')", self.step)

    def test_the_tagged_commit_must_be_on_main(self):
        self.assertIn("git fetch --no-tags origin main", self.step)
        self.assertIn("git merge-base --is-ancestor HEAD FETCH_HEAD", self.step)
        self.assertIn("exit 1", self.step)

    def test_it_comes_before_anything_is_built(self):
        self.assertLess(self.build.index("Refuse a tag that is not on main"),
                        self.build.index("make_release.py"))
        self.assertIn("fetch-depth: 0", self.build[:self.build.index("Refuse a tag that is not on main")])


class ForkGuardTests(unittest.TestCase):
    GUARD = "github.repository == 'songyb111-gachon/codex-auto-resume-windows'"

    def _condition(self, workflow: str, name: str) -> str:
        found = re.search(r"^    if: (>-\n(?:      .*\n)+|.*\n)", _job(workflow, name), re.M)
        self.assertIsNotNone(found, "%s's %s has no if" % (workflow, name))
        return " ".join(found.group(1).replace(">-", "").split())

    def test_sync_ko_runs_only_here_whatever_the_trigger(self):
        condition = self._condition("sync-ko.yml", "test")
        self.assertTrue(condition.startswith(self.GUARD + " && ("), condition)
        self.assertTrue(condition.endswith(")"), condition)
        self.assertIn("needs: test", _job("sync-ko.yml", "publish"))

    def test_ko_watch_runs_only_here(self):
        self.assertEqual(self._condition("ko-watch.yml", "watch"), self.GUARD)


class PayloadFolderTests(unittest.TestCase):
    def setUp(self):
        self.release = _load("make_release", ROOT / "build" / "make_release.py")

    def test_a_folder_named_like_a_top_level_one_inside_a_shipped_tree_ships(self):
        for name in ("src/codex_auto_resume/config/__init__.py", "src/codex_auto_resume/logs/view.py",
                     "skills/example/tests/case.md", "scripts/build/step.py", "assets/comparison/a.png",
                     "advanced/src/codex_auto_resume_advanced/tests/x.py"):
            with self.subTest(name=name):
                self.assertTrue(self.release._wanted(Path(name)))

    def test_caches_and_the_top_level_folders_still_do_not(self):
        for name in ("src/codex_auto_resume/__pycache__/a.cpython-314.pyc", "src/x/__pycache__/b.py",
                     "skills/example/node_modules/m/index.js", "src/.venv/lib/a.py", "scripts/.git/HEAD",
                     "build/make_release.py", "tests/test_x.py", "config/settings.toml", "logs/a.txt",
                     ".github/workflows/test.yml", "comparison/a.md"):
            with self.subTest(name=name):
                self.assertFalse(self.release._wanted(Path(name)))


class RuntimeDownloadTests(unittest.TestCase):
    """No network: urlopen is replaced, and the cache is a scratch folder."""

    def setUp(self):
        self.release = _load("make_release", ROOT / "build" / "make_release.py")
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.cache = Path(scratch.name)
        patcher = mock.patch.object(self.release, "CACHE", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _serve(self, payload: bytes):
        return mock.patch.object(self.release.urllib.request, "urlopen",
                                 side_effect=lambda *a, **k: io.BytesIO(payload))

    def test_a_bad_download_is_not_kept(self):
        with self._serve(b"<html>proxy error</html>") as urlopen:
            with self.assertRaises(SystemExit) as raised:
                self.release.fetch_runtime()
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("downloads it again", str(raised.exception))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_a_bad_cached_file_is_removed_and_the_next_build_downloads_again(self):
        (self.cache / self.release.PYTHON_ZIP).write_bytes(b"cut off")
        with self._serve(b"never asked") as urlopen:
            with self.assertRaises(SystemExit):
                self.release.fetch_runtime()
        self.assertEqual(urlopen.call_count, 0)
        self.assertFalse((self.cache / self.release.PYTHON_ZIP).exists())
        with self._serve(b"still bad") as urlopen:
            with self.assertRaises(SystemExit):
                self.release.fetch_runtime()
        self.assertEqual(urlopen.call_count, 1)

    def test_a_good_download_is_kept_and_used(self):
        payload = b"the right runtime"
        with mock.patch.object(self.release, "PYTHON_SHA256", hashlib.sha256(payload).hexdigest()):
            with self._serve(payload):
                archive = self.release.fetch_runtime()
            with self._serve(b"never asked") as urlopen:
                self.assertEqual(self.release.fetch_runtime(), archive)
        self.assertEqual(urlopen.call_count, 0)
        self.assertEqual(archive.read_bytes(), payload)
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()), [self.release.PYTHON_ZIP])


if __name__ == "__main__":
    unittest.main()
