"""build/legacy_bootstraps.py, held to archives made for the purpose.

The release build job runs it on the archives it built: every published bootstrap from v0.5.2,
taken out of git, has to name the standard archive the way the build did and accept it with its
own Test-Archive, because that copy - not this tree's - is what updates an installation. Here the
same checks run on small archives shaped like a release, where each way of breaking an installed
copy's update can be put in on purpose and seen to be caught.

The tags have to be in the checkout (test.yml fetches them, fetch-depth: 0). Where they are not,
CI fails loudly rather than passing on an empty list, and a local checkout skips.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
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

BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PACKAGE = make_release.ADVANCED_PACKAGE
# Later than every tag, so every published bootstrap is one that could update to it.
VERSION = "9.9.9"


def required_entries() -> list:
    listed = re.search(r"\$required = @\((.*?)\)", BOOTSTRAP.read_text(encoding="utf-8"), re.S)
    return re.findall(r"'([^']+)'", listed.group(1)) + ["payload/codex-auto-resume.ico"]


def archive(path: Path, extra=(), omit=(), version=VERSION) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for entry in required_entries() + list(extra):
            if entry in omit:
                continue
            if entry.endswith(".codex-plugin/plugin.json"):
                bundle.writestr(entry, json.dumps({"name": "codex-auto-resume", "version": version}))
            else:
                bundle.writestr(entry, "x")
    return path


def this_tree() -> legacy.Bootstrap:
    """The bootstrap this build ships, as the next release's check will take it out of its tag."""
    return legacy.Bootstrap("this tree", BOOTSTRAP.read_bytes(),
                            (ROOT / "scripts" / "release.json").read_bytes())


class OrderTests(unittest.TestCase):
    def test_versions_sort_as_releases_do(self):
        ordered = ["0.5.2", "0.5.10", "0.6.6-alpha", "0.6.6-beta", "0.6.6", "0.6.9-alpha", "0.6.9",
                   "0.6.10-alpha", "0.6.10", "0.6.11"]
        self.assertEqual(sorted(reversed(ordered), key=legacy.order), ordered)

    def test_anything_else_is_not_a_version(self):
        for bad in ("0.6", "0.6.1.2", "v0.6.1", "0.6.1-RC1", "0.6.1-alpha1", ""):
            with self.subTest(bad), self.assertRaises(ValueError):
                legacy.order(bad)


@unittest.skipUnless(legacy.POWERSHELL.is_file(), "the published bootstraps are Windows PowerShell")
class PublishedBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tags = legacy.published(ROOT, VERSION)
        if not cls.tags:
            if os.environ.get("CI"):
                raise AssertionError("no tag from v0.5.2 on is in this checkout; CI must fetch the tags")
            raise unittest.SkipTest("no tag from v0.5.2 on is in this checkout")
        cls.bootstraps = [legacy.lift(ROOT, tag) for tag in cls.tags]
        cls.folder = tempfile.TemporaryDirectory()
        cls.work = Path(cls.folder.name)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_list_starts_at_the_first_bootstrap_and_ends_before_the_release(self):
        self.assertEqual(self.tags[0], "v0.5.2", "v0.5.2 is the first release with a bootstrap")
        self.assertNotIn("v0.5.1", legacy.published(ROOT, VERSION))
        self.assertIn("v0.6.9-alpha", self.tags, "a pre-release is installed and updates too")
        self.assertEqual(legacy.published(ROOT, "0.6.9"), self.tags[:self.tags.index("v0.6.9")])

    def test_every_published_bootstrap_takes_an_archive_shaped_like_this_release(self):
        standard = archive(self.work / "standard.zip")
        self.assertEqual(legacy.check(self.bootstraps, VERSION, standard), [])

    def test_an_entry_every_bootstrap_requires_is_missed_by_every_one(self):
        broken = archive(self.work / "no_mcp_json.zip", omit=["payload/app/.mcp.json"])
        found = legacy.check(self.bootstraps, VERSION, broken)
        self.assertEqual(len(found), len(self.tags), found)
        for tag, finding in zip(self.tags, found):
            self.assertTrue(finding.startswith(tag + " refuses no_mcp_json.zip: "), finding)
            self.assertIn("missing payload/app/.mcp.json", finding)

    def test_each_bootstrap_is_judged_by_its_own_code(self):
        """A stray file at the payload root is refused from v0.6.0, when the check came in, and
        not before - which only the tags' own Test-Archive can know."""
        stray = archive(self.work / "stray.zip", extra=["payload/stray.txt"])
        refusing = {finding.split(" ", 1)[0] for finding in legacy.check(self.bootstraps, VERSION, stray)}
        self.assertEqual(refusing, {tag for tag in self.tags if legacy.order(tag[1:]) >= (0, 6, 0)})

    def test_a_name_the_old_template_cannot_build_is_found(self):
        renamed = [legacy.Bootstrap(tag.tag, tag.script, tag.release.replace(
            b"CodexAutoResume-v{version}", b"CodexAutoResume-Renamed-v{version}")) for tag in self.bootstraps]
        found = legacy.check(renamed, VERSION, archive(self.work / "renamed.zip"))
        self.assertEqual(len(found), len(self.tags), found)
        self.assertTrue(all("would download CodexAutoResume-Renamed-v9.9.9-win-x64.zip" in line
                            for line in found), found)


@unittest.skipUnless(legacy.POWERSHELL.is_file(), "the published bootstraps are Windows PowerShell")
class EditionAwareBootstrapTests(unittest.TestCase):
    """From v0.6.11 a published bootstrap knows both editions, and an advanced installation
    updates within its own - so from the release after, the check asks for the advanced archive
    too. This tree's bootstrap stands in for that tag."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        cls.standard = archive(work / "standard.zip")
        cls.advanced = archive(work / "advanced.zip", extra=["payload/app/src/%s/__init__.py" % PACKAGE])

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_it_takes_each_edition_under_its_own_name(self):
        self.assertTrue(this_tree().knows_advanced())
        self.assertEqual(legacy.check([this_tree()], VERSION, self.standard, self.advanced), [])

    def test_the_advanced_archive_has_to_be_given(self):
        found = legacy.check([this_tree()], VERSION, self.standard)
        self.assertEqual(found, ["this tree updates advanced installations, and no advanced archive "
                                 "was given to check it with"])

    def test_each_is_asked_for_as_its_own_edition(self):
        found = legacy.check([this_tree()], VERSION, self.advanced, self.standard)
        self.assertEqual(len(found), 2, found)
        self.assertIn("holds the advanced edition", found[0])
        self.assertIn("not the advanced edition", found[1])


class CommandLineTests(unittest.TestCase):
    def test_it_wants_the_standard_archive(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(SystemExit) as refused:
            legacy.main(["--dist", empty])
        self.assertIn("build the standard edition first", str(refused.exception))

    def test_the_release_runs_it_on_what_it_built_before_keeping_anything(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        step = text.index("run: python build/legacy_bootstraps.py")
        self.assertLess(text.index("run: python build/make_release.py"), step)
        self.assertLess(step, text.index("Keep the archive even when nothing is published"))
        self.assertIn("fetch-depth: 0", text[:step])


if __name__ == "__main__":
    unittest.main()
