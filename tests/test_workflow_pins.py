"""Every external GitHub Action is pinned to a full commit, and says which release it is.

A tag such as `actions/checkout@v4` is a pointer the action's owner can move. The
release workflow builds the archive users install and signs its provenance, so whatever
runs there runs with this repository's `contents: write` and `id-token: write`. A moved
tag would change that code without a commit here saying so. A 40-character commit SHA
cannot be moved.

The readable version stays beside the SHA as a comment, because a bare hash tells a
reviewer nothing, and Dependabot updates both together in a pull request that a person
reviews. Nothing here is auto-merged.

Local actions (`./path`) and `docker://` references with a digest are the only other
forms allowed.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>[^\s#]+)\s*(?:#\s*(?P<comment>.*))?$")
PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^v\d+(?:\.\d+){0,2}\b")


def workflow_files():
    return sorted(list(WORKFLOWS.glob("*.yml")) + list(WORKFLOWS.glob("*.yaml")))


def references():
    """Every `uses:` line in every workflow, with where it is."""
    for path in workflow_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.match(line)
            if match:
                yield path.name, number, match.group("ref"), (match.group("comment") or "").strip()


class ActionPinTests(unittest.TestCase):
    def test_there_are_workflows_to_check(self):
        # A glob that silently matches nothing would pass every test below.
        self.assertTrue(workflow_files(), "no workflow files found")
        self.assertTrue(list(references()), "no uses: lines found - the parser is broken")

    def test_every_external_action_is_pinned_to_a_full_commit(self):
        for name, number, ref, _ in references():
            if ref.startswith("./"):
                continue
            with self.subTest("%s:%d %s" % (name, number, ref)):
                if ref.startswith("docker://"):
                    self.assertIn("@sha256:", ref, "a container action must be pinned by digest")
                    continue
                self.assertRegex(ref, PINNED,
                                 "pin to a 40-character commit SHA, not a tag or branch")

    def test_every_pin_says_which_release_it_is(self):
        for name, number, ref, comment in references():
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            with self.subTest("%s:%d %s" % (name, number, ref)):
                self.assertRegex(comment, VERSION_COMMENT,
                                 "follow the SHA with '# vX.Y.Z' so a reviewer can read it")

    def test_the_same_action_is_pinned_to_one_commit_everywhere(self):
        """Two workflows on two versions of checkout is drift nobody chose."""
        seen = {}
        for name, number, ref, _ in references():
            if "@" not in ref or ref.startswith("./"):
                continue
            action, sha = ref.split("@", 1)
            seen.setdefault(action, {}).setdefault(sha, []).append("%s:%d" % (name, number))
        for action, shas in seen.items():
            with self.subTest(action):
                self.assertEqual(len(shas), 1, "pinned to different commits: %s" % shas)

    def test_dependabot_proposes_action_updates_for_review(self):
        config = ROOT / ".github" / "dependabot.yml"
        self.assertTrue(config.is_file(), "without it, pinned SHAs silently age")
        text = config.read_text(encoding="utf-8")
        self.assertIn("package-ecosystem: \"github-actions\"", text)
        # Updates arrive as pull requests. Nothing in this repository merges them.
        self.assertNotIn("automerge", text.lower())

    def test_the_artifact_actions_are_only_proposed_together(self):
        """The build job uploads what the publish job downloads; the two must agree.

        Dependabot's first run opened separate pull requests bumping upload-artifact to
        v7 and download-artifact to v8. Merging one of them alone would have broken the
        release at the next tag, in a job that only runs on a tag.
        """
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        group = text[text.index("groups:"):]
        self.assertIn('"actions/upload-artifact"', group)
        self.assertIn('"actions/download-artifact"', group)


class ParserTests(unittest.TestCase):
    """The checks above are only as good as the line parser under them."""

    def test_floating_tags_are_recognised_as_unpinned(self):
        for bad in ("actions/checkout@v4", "actions/checkout@main",
                    "actions/checkout@11d5960", "owner/repo/sub@v1.2.3"):
            with self.subTest(bad):
                self.assertNotRegex(bad, PINNED)

    def test_a_full_sha_is_recognised(self):
        self.assertRegex("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", PINNED)
        self.assertRegex("owner/repo/sub/path@11d5960a326750d5838078e36cf38b85af677262", PINNED)

    def test_the_line_parser_reads_both_yaml_shapes(self):
        for line, ref in (("      - uses: actions/checkout@abc  # v4.4.0", "actions/checkout@abc"),
                          ("        uses: actions/setup-python@abc # v5.6.0", "actions/setup-python@abc")):
            with self.subTest(line):
                match = USES.match(line)
                self.assertIsNotNone(match)
                self.assertEqual(match.group("ref"), ref)


if __name__ == "__main__":
    unittest.main()
