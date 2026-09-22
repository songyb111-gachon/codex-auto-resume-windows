"""The Korean branch is generated, and the Korean documents are current.

`ko` was an independent fork for four releases. It carried its own engine, installer, GUI,
workflows and tests, and it drifted three releases behind while still telling Korean
readers the tool made no network request and that installing meant downloading a release
archive. Nobody chose that; it is what a second copy of a codebase does when a person has
to remember to merge it.

So the branch is generated now, and these are the invariants that keep it honest. They run
on `main`, against the Korean sources, because that is where the Korean text lives - there
is no checkout of ko to test, by design.

Deliberately not asserted: that a Korean page says the same *sentences* as its English
counterpart. Translations reorganise, and a test that demanded line-for-line agreement
would be satisfied by a bad translation and broken by a good one. What is asserted is the
handful of claims where being out of date would mislead somebody: the network, the install
route, and the guarantees.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "scripts" / "ko_branch.json"
sys.path.insert(0, str(ROOT / "scripts"))


# The notice the generator writes, and the only honest way to tell the two branches apart.
NOTICE_NAME = ".github/GENERATED-BRANCH.md"
GENERATED_NOTICE = ROOT / NOTICE_NAME


def skip_if_generated() -> None:
    """These tests run on main. On `ko` there is nothing for them to read.

    `ko` carries main's tests unchanged - that is the point of generating it - but not
    main's Korean *sources*: the sync writes each `<name>.ko.md` over its English sibling
    and deletes the original. Opening them by name on ko raises FileNotFoundError, so a
    suite that is supposed to travel with the branch instead errors twelve times on it,
    and a pull request opened against ko is answered with failures about the wrong thing.

    Skipping rather than dropping the file from the generated tree keeps "ko is main's
    code exactly" true, which is the property the whole arrangement exists to have.

    Keyed on the notice the generator writes, not on a missing file: "the Korean sources
    are absent" is also true of a half-deleted working tree, and a test that quietly
    skips because somebody deleted a file guards nothing.
    """
    if not GENERATED_NOTICE.is_file():
        return
    # Present is not enough: the marker must be *tracked*.
    #
    # `python scripts/ko_sync.py --root .` is a documented command, and running it in a
    # checkout of main leaves this file behind as an untracked residue that `git restore .`
    # does not remove. If mere presence were the switch, that one stray run would silently
    # disarm every invariant below - on main, where they are the only thing checking the
    # Korean text - and the suite would still report success.
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", str(NOTICE_NAME)],
                            capture_output=True, text=True, encoding="utf-8")
    if listed.returncode == 0 and listed.stdout.strip():
        raise unittest.SkipTest("this is the generated ko branch; the sources live on main")


def mapping() -> dict:
    return json.loads(MAPPING.read_text(encoding="utf-8"))


# Three numbers, and what follows them. A tag with a suffix - `v0.6.6-alpha`, the candidate this
# release was first cut from and then set aside - is not the current version: it is a name that
# was fixed the day it was written and that nothing will ever move, which is exactly the thing the
# rule below lets a document name.
VERSION = re.compile(r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?")
# A changelog names the release it is announcing, and a page that recounts what happened up to
# a version names it. Those are history, and history that must not mention the newest release
# is not history. The rule is about *current-facing* prose claiming a version that nothing will
# update - the same split the English side draws in tests/test_privacy_claims.py.
HISTORICAL = {"CHANGELOG.ko.md", "CONTRIBUTING.ko.md", "DEVELOPMENT.ko.md"}
# A roadmap is a plan written in versions, and every version it names becomes the current one in
# its turn. Under the prose rule the release that moves the manifest would fail on headings that
# are still right, and the only way through would be to write each future release as "the one
# after" another. What does go stale in a roadmap is a release's status - out, or in development -
# and RoadmapTests holds that to the manifest, in both languages, instead.
PLANS = {"ROADMAP.ko.md"}


def version_key(version: str) -> tuple:
    """A version in order, a pre-release just before its release: v0.6.9-alpha, then v0.6.9."""
    number, _, suffix = version.lstrip("v").partition("-")
    return tuple(int(part) for part in number.split(".")) + (0 if suffix else 1,)


def versions_named_as_current(current: str) -> list:
    """`name:line` for every line of a current-facing Korean document that names `current`."""
    offenders = []
    for path in korean_documents():
        if path.name in HISTORICAL or path.name in PLANS:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for found in VERSION.findall(line):
                # Past releases are history and may be named; the current one may not,
                # because nothing would update it.
                if found.lstrip("v") == current:
                    offenders.append("%s:%d" % (path.name, number))
    return offenders


def korean_documents() -> list[Path]:
    return sorted(ROOT.glob("*.ko.md")) + sorted((ROOT / "docs").glob("*.ko.md"))


class MappingTests(unittest.TestCase):
    def setUp(self):
        skip_if_generated()
        self.mapping = mapping()

    def test_every_korean_document_is_mapped(self):
        """A Korean page nobody mapped is a page that never reaches Korean readers."""
        declared = set(self.mapping["documents"])
        present = {str(path.relative_to(ROOT)).replace("\\", "/")
                   for path in korean_documents()}
        self.assertEqual(present, declared,
                         "add it to scripts/ko_branch.json, or delete it")

    def test_every_mapping_target_exists_in_english(self):
        for source, target in self.mapping["documents"].items():
            with self.subTest(source):
                self.assertTrue((ROOT / target).is_file(),
                                "%s replaces %s, which does not exist" % (source, target))

    def test_every_human_facing_document_is_classified(self):
        """Translated, or English for a stated reason. There is no third pile.

        v0.5.5 shipped a `not_yet_translated` list, which was honest at the time and
        would have stayed there indefinitely: a list of documents nobody has got to is
        indistinguishable from a list of documents nobody will. So the rule is that every
        tracked Markdown document a person reads is either mapped to a Korean source or
        named in `intentionally_english` with the reason it is not.

        `docs/evidence/` and the tests' own fixtures are not documents in this sense; they
        are data a reader is pointed at, not prose.
        """
        translated = set(self.mapping["documents"].values())
        exempt = set(self.mapping["intentionally_english"])
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "*.md", "LICENSE"],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(listing.returncode, 0, "git ls-files failed")
        unclassified = []
        for name in [n for n in listing.stdout.split(chr(0)) if n]:
            if name.endswith(".ko.md") or name.startswith("docs/evidence/"):
                continue
            if name in translated or name in exempt:
                continue
            unclassified.append(name)
        self.assertEqual(sorted(unclassified), [],
                         "add these to `documents` with a Korean source, or to "
                         "`intentionally_english` with the reason they stay English")

    def test_no_translation_is_stale(self):
        """A complete translation can still go out of date, silently.

        This is the documentation half of the screenshot freshness check: record what the
        Korean was translated from, and fail when the English moves without it. CI does
        not translate anything - a person decides what the Korean should say, then runs
        `python scripts/ko_sync.py --reviewed <english path>`.

        It is exactly how ko came to promise Korean readers that the tool made no network
        request, for three releases after it started making one.
        """
        import ko_sync
        stale = ko_sync.stale_translations(ROOT)
        self.assertEqual(stale, [],
                         "update the Korean document, then record it with "
                         "`python scripts/ko_sync.py --reviewed <english path>`")

    def test_every_exemption_gives_a_reason(self):
        for name, reason in self.mapping["intentionally_english"].items():
            with self.subTest(name):
                self.assertTrue((ROOT / name).is_file() or name.startswith(".github/"),
                                "%s does not exist" % name)
                self.assertGreater(len(reason.strip()), 30,
                                   "an exemption without a reason is a to-do wearing a hat")

    def test_nothing_is_both_translated_and_exempt(self):
        overlap = (set(self.mapping["documents"].values())
                   & set(self.mapping["intentionally_english"]))
        self.assertEqual(overlap, set())


class GeneratorTests(unittest.TestCase):
    """What the sync does, checked without pushing anything anywhere."""

    def setUp(self):
        # `build(check=True)` reads the Korean sources to decide what it would write.
        skip_if_generated()

    def test_it_touches_no_code(self):
        import ko_sync
        changed = set(ko_sync.build(ROOT, check=True))
        code = [name for name in changed
                if name.startswith(("src/", "gui/", "tests/", "build/", "install/",
                                    "scripts/", ".github/workflows/"))]
        self.assertEqual(code, [],
                         "ko must be main's code exactly; only documents may differ")

    def test_it_reports_every_mapped_document(self):
        import ko_sync
        changed = set(ko_sync.build(ROOT, check=True))
        self.assertTrue(set(mapping()["documents"].values()) <= changed)

    def test_a_link_to_the_english_sibling_becomes_a_link_to_main(self):
        import ko_sync
        out = ko_sync.relink('<a href="README.md">English</a>', "README.md", "https://x/")
        self.assertIn('href="https://x/README.md"', out)

    def test_a_link_between_korean_documents_loses_the_ko_suffix(self):
        # On ko, SECURITY.ko.md *is* SECURITY.md, so the main-side name is dead there.
        import ko_sync
        out = ko_sync.relink("[a](SECURITY.ko.md) [b](docs/COMPARISON.ko.md)", "README.md", "")
        self.assertIn("(SECURITY.md)", out)
        self.assertIn("(docs/COMPARISON.md)", out)
        self.assertNotIn(".ko.md", out)

    def test_a_link_up_out_of_docs_loses_the_ko_suffix_too(self):
        # docs/GUIDE.ko.md links to ../SECURITY.ko.md; a pattern that stopped at the first
        # dot left those links pointing at files ko does not have.
        import ko_sync
        out = ko_sync.relink("[a](../SECURITY.ko.md) [b](./PLUGIN.ko.md)", "GUIDE.md", "")
        self.assertIn("(../SECURITY.md)", out)
        self.assertIn("(./PLUGIN.md)", out)
        self.assertNotIn(".ko.md", out)

    def test_it_rewrites_links_and_leaves_everything_else_alone(self):
        """The first version rewrote the suffix anywhere it appeared.

        That edited prose inside fenced code blocks and renamed any absolute URL that
        happened to end in `.ko.md` - a file on somebody else's host. Each case below is
        one it got wrong or one it must keep getting right.
        """
        import ko_sync
        base = "https://example.invalid/main/"
        unchanged = (
            "[x](https://example.com/README.md)",       # already absolute
            "[y](https://example.com/docs/T.ko.md)",    # someone else's file
            "The English README.md has more.",          # prose, not a link
            '<img src="docs/images/settings-panel.png">',
        )
        for text in unchanged:
            with self.subTest(text):
                self.assertEqual(ko_sync.relink(text, "README.md", base), text)

        fenced = "```\npython x.py README.md\n```\n"
        out = ko_sync.relink(fenced + '<a href="README.md">E</a>', "README.md", base)
        self.assertTrue(out.startswith(fenced), "prose in a code block must survive")
        self.assertIn('href="%sREADME.md"' % base, out)

    def test_the_workflow_builds_from_the_tested_commit(self):
        """`github.sha` on a workflow_run event is main's head, not what was tested."""
        text = (ROOT / ".github" / "workflows" / "sync-ko.yml").read_text(encoding="utf-8")
        self.assertIn("github.event.workflow_run.head_sha", text)
        self.assertIn("workflow_run.conclusion == 'success'", text)
        self.assertIn("head_branch == 'main'", text)
        self.assertIn("head_repository.full_name == github.repository", text,
                      "a fork's run must not be able to publish this branch")
        self.assertIn("concurrency:", text)
        self.assertNotIn("cancel-in-progress: true", text,
                         "a cancelled force-push can leave ko half-written")


class ClaimTests(unittest.TestCase):
    """The claims where being out of date would mislead a Korean reader."""

    def setUp(self):
        skip_if_generated()
        self.readme = (ROOT / "README.ko.md").read_text(encoding="utf-8")
        self.security = (ROOT / "SECURITY.ko.md").read_text(encoding="utf-8")

    def test_the_korean_readme_leads_with_the_plugin_route(self):
        install = self.readme.index("## 설치")
        plugin = self.readme.index("Codex에서 설치", install)
        archive = self.readme.index("릴리스 압축 파일로 설치", install)
        self.assertLess(plugin, archive,
                        "the plugin route is the recommended one and must come first")

    def test_the_korean_readme_admits_the_download(self):
        for required in ("GitHub", "HTTPS"):
            self.assertIn(required, self.readme,
                          "the Korean privacy section must say installing downloads")

    def test_no_korean_document_claims_nothing_leaves_the_machine(self):
        """The claim that was false in every Korean document until v0.5.5.

        Shape-based rather than exact-string: an absolute claim about the network needs a
        qualifier near it, exactly as tests/test_privacy_claims.py requires in English.
        """
        absolutes = re.compile(r"아무것도 이 PC 밖으로 나가지|네트워크 요청 자체가 없|"
                               r"외부 서비스나 엔드포인트가\s*관여하지 않")
        offenders = []
        for path in korean_documents():
            text = path.read_text(encoding="utf-8")
            for found in absolutes.finditer(text):
                line = text.count("\n", 0, found.start()) + 1
                offenders.append("%s:%d" % (path.name, line))
        self.assertEqual(offenders, [],
                         "an absolute no-network claim that stopped being true in v0.5.2")

    def test_the_korean_security_document_points_somewhere_real(self):
        self.assertIn("github.com", self.security,
                      "it used to say there was no third party to report to")

    def test_the_korean_documents_name_no_version_as_current(self):
        """A version written into prose is a version that goes stale on its own."""
        from codex_auto_resume import config
        self.assertEqual(versions_named_as_current(config.version()), [],
                         "the current version must come from the manifest, not from prose")

    def test_a_version_bump_does_not_fail_on_a_roadmap_heading_that_is_still_right(self):
        """The roadmap names every release it plans, and each becomes the current one in turn.

        Under the prose rule the release that moved the manifest to 0.6.5 would have failed on
        `## v0.6.5 — ...` - a heading that is still exactly right - and on every sentence about
        what 0.6.5 is for, and again at each bump after it. What goes stale in a roadmap is a
        release's status, which RoadmapTests holds to the manifest instead.
        """
        from codex_auto_resume import config
        # Every bump still ahead: the versions the roadmap plans after the manifest's.
        planned = sorted({found.lstrip("v") for found in VERSION.findall(
            (ROOT / "docs" / "ROADMAP.ko.md").read_text(encoding="utf-8"))
            if version_key(found) > version_key(config.version())}, key=version_key)
        for version in planned:
            with self.subTest(version):
                self.assertEqual([name for name in versions_named_as_current(version)
                                  if name.startswith("ROADMAP.ko.md:")], [])

    def test_the_korean_readme_keeps_the_guarantees_it_promises(self):
        for claim in ("UUID",          # the exact-thread guarantee
                      "Uninstall.cmd",  # uninstall, and what it preserves
                      "provenance"):    # the ownership rule uninstall applies
            with self.subTest(claim):
                self.assertIn(claim, self.readme)


RELEASED, IN_DEVELOPMENT = "✅", "\U0001F6A7"     # the roadmap's two status marks


def roadmap_marks(text: str) -> list:
    """(version, mark) for each line that carries a status mark, in order; the version is the first
    one the line names, or None."""
    marks = []
    for line in text.splitlines():
        for mark in (RELEASED, IN_DEVELOPMENT):
            if mark in line:
                found = VERSION.search(line)
                marks.append((found.group(0).lstrip("v") if found else None, mark))
    return marks


def stale_marks(text: str, current: str) -> list:
    """What a roadmap marks wrongly for a manifest at `current`: a release still in development
    that is not the current one, or a release marked out that is still ahead."""
    wrong = []
    for version, mark in roadmap_marks(text):
        if version is None:
            wrong.append("a %s mark names no version" % mark)
        elif mark == IN_DEVELOPMENT and version != current:
            wrong.append("v%s is marked in development, and the manifest says %s" % (version, current))
        elif mark == RELEASED and version_key(version) > version_key(current):
            wrong.append("v%s is marked released, and the manifest says %s" % (version, current))
    return wrong


class RoadmapTests(unittest.TestCase):
    """The roadmap's statuses, which are the part of it that goes stale.

    Its version names are plans and stay right (PLANS, above). Which release is out and which is
    in development changes at every bump, so that is held to the manifest here: in English directly,
    and in Korean by marking exactly what the English marks, in the same order.
    """

    def setUp(self):
        skip_if_generated()
        self.english = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
        self.korean = (ROOT / "docs" / "ROADMAP.ko.md").read_text(encoding="utf-8")

    def test_the_roadmap_marks_releases_by_the_manifest(self):
        from codex_auto_resume import config
        current = config.version()
        self.assertIn(current, {version for version, _ in roadmap_marks(self.english)},
                      "docs/ROADMAP.md gives the manifest's version no status")
        self.assertEqual(stale_marks(self.english, current), [],
                         "docs/ROADMAP.md: mark the releases that are out and the one in development, "
                         "then docs/ROADMAP.ko.md the same way")

    def test_a_bump_that_leaves_the_roadmap_behind_is_caught(self):
        from codex_auto_resume import config
        ahead = sorted({version for version, _ in roadmap_marks(self.english)} | {
            found.lstrip("v") for found in VERSION.findall(self.english)}, key=version_key)
        after = [version for version in ahead if version_key(version) > version_key(config.version())]
        if not after:
            self.skipTest("the roadmap plans nothing after the manifest's version")
        if IN_DEVELOPMENT not in {mark for _, mark in roadmap_marks(self.english)}:
            # Between releases. From v0.6.5 the work happens on the dev branch and main holds what
            # was released, so main's roadmap marks the manifest's own release out and nothing in
            # development. A bump is then caught by the rule above - the new version has no mark -
            # provided the roadmap has not already marked the next release.
            self.assertNotIn(after[0], {version for version, _ in roadmap_marks(self.english)},
                             "the next release carries a mark before the manifest reaches it")
            return
        self.assertTrue(stale_marks(self.english, after[0]),
                        "a manifest one release ahead should find the in-development mark stale")

    def test_at_most_one_release_is_in_development(self):
        marked = [version for version, mark in roadmap_marks(self.english) if mark == IN_DEVELOPMENT]
        self.assertLessEqual(len(set(marked)), 1, "more than one release is marked in development")

    def test_the_korean_roadmap_marks_what_the_english_one_marks(self):
        self.assertEqual([mark for _, mark in roadmap_marks(self.korean)],
                         [mark for _, mark in roadmap_marks(self.english)],
                         "docs/ROADMAP.ko.md marks releases differently from docs/ROADMAP.md")


if __name__ == "__main__":
    unittest.main()
