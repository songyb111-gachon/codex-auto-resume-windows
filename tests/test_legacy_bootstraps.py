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
                   "0.6.10-alpha", "0.6.10", "0.6.11-alpha", "0.6.11-beta", "0.6.11", "0.6.12-alpha"]
        self.assertEqual(sorted(reversed(ordered), key=legacy.order), ordered)

    def test_anything_else_is_not_a_version(self):
        """The two suffixes scripts/bootstrap.ps1 accepts, and no other word: one that sorted by its
        spelling would put an `rc` after a `beta` by accident, and a `gamma` too."""
        for bad in ("0.6", "0.6.1.2", "v0.6.1", "0.6.1-RC1", "0.6.1-rc", "0.6.1-gamma", "0.6.1-Beta",
                    "0.6.1-alpha1", "0.6.1-alpha-beta", "0.6.1\n", "0.6.1-beta\n", ""):
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
        # From v0.6.11-alpha a published bootstrap knows the advanced edition too, and is asked
        # about both archives: each (tag, edition) is a case of its own. Until that tag existed
        # every case here was a tag's standard one, and these tests counted tags - which is how
        # the release of v0.6.11-alpha, the first run to see its own tag, failed on them.
        cls.cases = [(bootstrap.tag, edition) for bootstrap in cls.bootstraps
                     for edition in (("standard", "advanced") if bootstrap.knows_advanced()
                                     else ("standard",))]
        cls.folder = tempfile.TemporaryDirectory()
        cls.work = Path(cls.folder.name)

    def both(self, name, **shape):
        """The archive of each edition, built to one shape."""
        return (archive(self.work / (name + ".zip"), **shape),
                archive(self.work / (name + "-advanced.zip"),
                        extra=list(shape.pop("extra", ())) + ["payload/app/src/%s/__init__.py" % PACKAGE],
                        **shape))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_list_starts_at_the_first_bootstrap_and_ends_before_the_release(self):
        self.assertEqual(self.tags[0], "v0.5.2", "v0.5.2 is the first release with a bootstrap")
        self.assertNotIn("v0.5.1", legacy.published(ROOT, VERSION))
        self.assertIn("v0.6.9-alpha", self.tags, "a pre-release is installed and updates too")
        # A later pre-release of the same version is checked against the earlier one's bootstrap.
        self.assertIn("v0.6.11-alpha", legacy.published(ROOT, "0.6.11-beta"))
        self.assertNotIn("v0.6.11-beta", legacy.published(ROOT, "0.6.11-beta"))
        self.assertEqual(legacy.published(ROOT, "0.6.9"), self.tags[:self.tags.index("v0.6.9")])

    def test_every_published_bootstrap_takes_an_archive_shaped_like_this_release(self):
        self.assertEqual(legacy.check(self.bootstraps, VERSION, *self.both("standard")), [])

    def test_an_entry_every_bootstrap_requires_is_missed_by_every_one(self):
        found = legacy.check(self.bootstraps, VERSION, *self.both("no_mcp_json", omit=["payload/app/.mcp.json"]))
        self.assertEqual(len(found), len(self.cases), found)
        for (tag, edition), finding in zip(self.cases, found):
            name = "no_mcp_json.zip" if edition == "standard" else "no_mcp_json-advanced.zip"
            self.assertTrue(finding.startswith("%s refuses %s: " % (tag, name)), finding)
            self.assertIn("missing payload/app/.mcp.json", finding)

    def test_each_bootstrap_is_judged_by_its_own_code(self):
        """A stray file at the payload root is refused from v0.6.0, when the check came in, and
        not before - which only the tags' own Test-Archive can know."""
        stray = self.both("stray", extra=["payload/stray.txt"])
        refusing = {finding.split(" ", 1)[0] for finding in legacy.check(self.bootstraps, VERSION, *stray)}
        self.assertEqual(refusing, {tag for tag in self.tags if legacy.order(tag[1:]) >= (0, 6, 0)})

    def test_a_name_the_old_template_cannot_build_is_found(self):
        renamed = [legacy.Bootstrap(tag.tag, tag.script, tag.release.replace(
            b"CodexAutoResume-v{version}", b"CodexAutoResume-Renamed-v{version}")) for tag in self.bootstraps]
        # Only the standard template is renamed, so an advanced case still names its archive.
        found = legacy.check(renamed, VERSION, *self.both("renamed"))
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


def names(text: str, tag: str) -> bool:
    """Whether `text` names `tag` itself - not v0.6.1 inside v0.6.10, and in Korean too, where a
    particle follows the tag with no space."""
    return re.search(r"(?<![0-9A-Za-z_.-])%s(?![0-9A-Za-z_-]|\.[0-9])" % re.escape(tag), text) is not None


@unittest.skipUnless(legacy.POWERSHELL.is_file(), "the published bootstraps are Windows PowerShell")
class CopiesThatCannotReadThisVersionTests(unittest.TestCase):
    """A published bootstrap reads only the version words of its day.

    From v0.6.0 a bootstrap compares the installed version with its own, and leaves a newer
    installation alone. One that cannot read the installed version cannot tell it from none: the
    published v0.6.10 and v0.6.11-alpha bootstraps, run from a plugin copy Codex still held,
    installed their own older release over 0.6.11-beta, whose `-beta` they had never heard of,
    and died with no answer under -CheckOnly. Those copies cannot be changed. So a release whose
    version the newest published bootstrap cannot read says so in its changelog entry - which
    copies, and that it is this version they cannot read - in each language the tree holds.
    """

    @classmethod
    def setUpClass(cls):
        cls.version = make_release.version()
        cls.tags = legacy.published(ROOT, cls.version)
        if not cls.tags:
            if os.environ.get("CI"):
                raise AssertionError("no tag from v0.5.2 on is in this checkout; CI must fetch the tags")
            raise unittest.SkipTest("no tag from v0.5.2 on is in this checkout")
        cls.answers = legacy.readers([legacy.lift(ROOT, tag) for tag in cls.tags], cls.version)

    def test_each_bootstrap_is_asked_with_its_own_code(self):
        """v0.5.x compares nothing; v0.6.0 to v0.6.8 read no word after a version; v0.6.9-alpha on
        reads -alpha - which only each tag's own Get-VersionParts can say."""
        tags = [tag for tag in ("v0.5.7", "v0.6.8", "v0.6.10") if tag in self.tags]
        found = legacy.readers([legacy.lift(ROOT, tag) for tag in tags], "0.6.11-alpha")
        self.assertEqual(found, {tag: answer for tag, answer in
                                 {"v0.5.7": "unguarded", "v0.6.8": "refuses", "v0.6.10": "reads"}.items()
                                 if tag in tags})
        self.assertEqual(legacy.readers([this_tree()], self.version), {"this tree": "reads"})

    def test_the_changelog_names_the_published_copies_that_cannot_read_this_version(self):
        if self.answers[self.tags[-1]] != "refuses":
            self.skipTest("the newest published bootstrap reads v%s" % self.version)
        refusing = [tag for tag in self.tags if self.answers[tag] == "refuses"]
        guarded = [tag for tag in self.tags if self.answers[tag] != "unguarded"]
        # The entry names them as a range, from the oldest to the newest; that is true only when
        # every guarded bootstrap in between refuses too.
        self.assertEqual(refusing, guarded[guarded.index(refusing[0]):])
        import release_notes
        wanted = (refusing[0], refusing[-1])
        for path in (ROOT / "docs" / "CHANGELOG.md", ROOT / "docs" / "CHANGELOG.ko.md"):
            if not path.is_file():
                continue
            with self.subTest(path.name):
                entry = release_notes.section(path.read_text(encoding="utf-8"), self.version)
                said = [paragraph for paragraph in re.split(r"\n\s*\n", entry)
                        if all(names(paragraph, tag) for tag in wanted) and "`%s`" % self.version in paragraph]
                self.assertTrue(said, "%s: the v%s entry does not say that the bootstraps published from %s "
                                      "to %s cannot read `%s`" % (path.name, self.version, wanted[0],
                                                                  wanted[1], self.version))


class CommandLineTests(unittest.TestCase):
    def test_it_wants_the_standard_archive(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(SystemExit) as refused:
            legacy.main(["--dist", empty])
        self.assertIn("build the standard edition first", str(refused.exception))

    def test_the_release_runs_it_on_what_it_built_before_keeping_anything(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        step = text.index("run: python build/legacy_bootstraps.py")
        self.assertLess(text.index("run: python build/make_release.py"), step)
        self.assertLess(step, text.index("Keep the archives even when nothing is published"))
        self.assertIn("fetch-depth: 0", text[:step])


if __name__ == "__main__":
    unittest.main()
