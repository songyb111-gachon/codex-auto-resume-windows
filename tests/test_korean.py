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
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "scripts" / "ko_branch.json"
sys.path.insert(0, str(ROOT / "scripts"))


def mapping() -> dict:
    return json.loads(MAPPING.read_text(encoding="utf-8"))


def korean_documents() -> list[Path]:
    return sorted(ROOT.glob("*.ko.md")) + sorted((ROOT / "docs").glob("*.ko.md"))


class MappingTests(unittest.TestCase):
    def setUp(self):
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

    def test_the_untranslated_list_is_accurate(self):
        """It is the visible to-do; a stale to-do is worse than none."""
        for name in self.mapping["not_yet_translated"]:
            with self.subTest(name):
                self.assertTrue((ROOT / name).is_file(), "%s does not exist" % name)
                korean = ROOT / name.replace(".md", ".ko.md")
                self.assertFalse(korean.is_file(),
                                 "%s exists, so %s is no longer untranslated"
                                 % (korean.name, name))

    def test_nothing_is_both_mapped_and_listed_as_untranslated(self):
        overlap = set(self.mapping["documents"].values()) & set(self.mapping["not_yet_translated"])
        self.assertEqual(overlap, set())


class GeneratorTests(unittest.TestCase):
    """What the sync does, checked without pushing anything anywhere."""

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
        pattern = re.compile(r"v?\d+\.\d+\.\d+")
        current = config.version()
        offenders = []
        for path in korean_documents():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for found in pattern.findall(line):
                    # Past releases are history and may be named; the current one may not,
                    # because nothing would update it.
                    if found.lstrip("v") == current:
                        offenders.append("%s:%d" % (path.name, number))
        self.assertEqual(offenders, [],
                         "the current version must come from the manifest, not from prose")

    def test_the_korean_readme_keeps_the_guarantees_it_promises(self):
        for claim in ("UUID",          # the exact-thread guarantee
                      "Uninstall.cmd",  # uninstall, and what it preserves
                      "provenance"):    # the ownership rule uninstall applies
            with self.subTest(claim):
                self.assertIn(claim, self.readme)


if __name__ == "__main__":
    unittest.main()
