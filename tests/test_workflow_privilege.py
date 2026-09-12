"""Workflows hold write access only where they need it, and never while running our code.

The v0.6.0 security review found the release workflow's "dry run" was not one. A
dispatch ran the build with the workflow-wide contents: write and id-token: write, the
checkout left that token in .git/config for the build scripts and tests to read, and the
three publishing steps were gated only on github.ref being a tag - which a dispatch
against a tag satisfies. The ko sync had the same shape: its dispatch input accepted any
SHA, ran that commit's code with a write token, and force-pushed the result.

What these tests hold:
- no workflow grants anything at the top level; each job asks for what it uses;
- no checkout leaves its token on disk;
- the release job that can write runs none of the repository's code, and runs only on a
  real tag push;
- the ko sync refuses a commit that is not on main, and only its push step sees a token;
- no expression is spliced into a shell script where a value could become code.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def text(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def job(source, name):
    """The text of one job, from its key to the next top-level job key or the end."""
    start = re.search(r"(?m)^  %s:\s*$" % re.escape(name), source)
    if not start:
        raise AssertionError("job %s not found" % name)
    rest = source[start.end():]
    end = re.search(r"(?m)^  [A-Za-z0-9_-]+:\s*$", rest)
    return rest[:end.start()] if end else rest


class WorkflowPrivilegeTests(unittest.TestCase):
    def test_nothing_is_granted_at_the_top_level_where_jobs_write(self):
        for name in ("release.yml",):
            with self.subTest(name):
                self.assertRegex(text(name), r"(?m)^permissions: \{\}\s*$")

    def test_no_checkout_leaves_its_token_behind(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            source = path.read_text(encoding="utf-8")
            checkouts = len(re.findall(r"uses: actions/checkout@", source))
            with self.subTest(path.name):
                self.assertEqual(source.count("persist-credentials: false"), checkouts)

    def test_the_build_job_cannot_write(self):
        build = job(text("release.yml"), "build")
        self.assertIn("contents: read", build)
        for grant in ("contents: write", "id-token: write", "attestations: write"):
            self.assertNotIn(grant, build)
        self.assertNotIn("secrets.", build, "the build job needs no secret at all")

    def test_the_publish_job_runs_no_repository_code(self):
        publish = job(text("release.yml"), "publish")
        self.assertNotIn("actions/checkout", publish)
        for code in ("python ", "make_gui", "make_release", "unittest", ".ps1"):
            self.assertNotIn(code, publish, "publish must only move the built archive")

    def test_only_a_tag_push_publishes(self):
        publish = job(text("release.yml"), "publish")
        self.assertIn("if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')", publish)

    def test_the_publish_job_rechecks_what_it_was_handed(self):
        publish = job(text("release.yml"), "publish")
        self.assertIn("sha256sum", publish)
        self.assertIn('refs/tags/v$VERSION', publish)

    def test_the_version_is_validated_before_anything_uses_it(self):
        self.assertIn(r"-notmatch '^\d+\.\d+\.\d+$'", text("release.yml"))

    def test_no_expression_is_spliced_into_a_run_script(self):
        """`${{ }}` inside `run:` is text substitution into a shell script.

        Values reach scripts through `env:` instead, where the shell treats them as data.
        runner.temp and matrix values are the only exceptions allowed, and neither is
        influenced by anyone outside the repository.
        """
        for path in sorted(WORKFLOWS.glob("*.yml")):
            lines = path.read_text(encoding="utf-8").splitlines()
            in_run, indent = False, 0
            for number, line in enumerate(lines, 1):
                stripped = line.lstrip()
                current = len(line) - len(stripped)
                if in_run and stripped and current <= indent:
                    in_run = False
                if re.match(r"(- )?run: ?\|?", stripped):
                    in_run, indent = True, current
                    inline = stripped.split("run:", 1)[1]
                    if "${{" in inline:
                        for expression in re.findall(r"\$\{\{([^}]*)\}\}", inline):
                            with self.subTest("%s:%d" % (path.name, number)):
                                self.assertRegex(expression.strip(), r"^(runner\.temp|matrix\.[a-z-]+)$")
                    continue
                if in_run:
                    for expression in re.findall(r"\$\{\{([^}]*)\}\}", line):
                        with self.subTest("%s:%d" % (path.name, number)):
                            self.assertRegex(expression.strip(), r"^(runner\.temp|matrix\.[a-z-]+)$",
                                             "pass it through env: instead")


class KoSyncPrivilegeTests(unittest.TestCase):
    def setUp(self):
        self.source = text("sync-ko.yml")

    def test_a_commit_that_is_not_on_main_is_refused(self):
        self.assertIn("git merge-base --is-ancestor HEAD FETCH_HEAD", self.source)
        refuse = self.source.index("Refuse anything that is not on main")
        first_code = self.source.index("python scripts/ko_sync.py")
        self.assertLess(refuse, first_code, "the check must run before the tree's own code")

    def test_only_the_push_step_holds_the_token(self):
        self.assertEqual(self.source.count("secrets.GITHUB_TOKEN"), 1)
        push = self.source[self.source.index("- name: Publish the branch"):]
        self.assertIn("secrets.GITHUB_TOKEN", push)


class YamlShapeTests(unittest.TestCase):
    def test_every_workflow_parses(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML is not installed here; GitHub validates on push")
        import yaml
        for path in sorted(WORKFLOWS.glob("*.yml")):
            with self.subTest(path.name):
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIn("jobs", document)


class TagsAreFetchedWhereTheSuiteRunsTests(unittest.TestCase):
    """A job that runs the suite has to check out the tags the suite reads.

    `tests/test_control_v3.py:legacy_store_module` builds a database with the store code
    of a real tagged release - `git show v0.5.7:src/codex_auto_resume/store.py` - so a
    shallow checkout makes eight tests fail, and the message they fail with is "CI must
    fetch the tags".

    `test.yml` and `sync-ko.yml` had `fetch-depth: 0` from the day those tests were
    written. `release.yml` runs the same suite and did not, and nothing noticed for two
    releases because a dispatch never ran the tests to completion and no tag had ever
    reached the job. The first real tag push - v0.6.0 - failed there, before publishing
    anything. This is what stops the next one being found the same way.
    """

    def workflows_that_run_the_suite(self):
        found = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if "unittest discover" in text:
                found.append((path.name, text))
        return found

    def test_the_set_of_workflows_that_run_the_suite_is_known(self):
        self.assertEqual([name for name, _ in self.workflows_that_run_the_suite()],
                         ["release.yml", "sync-ko.yml", "test.yml"])

    def test_each_of_them_checks_out_the_tags(self):
        for name, text in self.workflows_that_run_the_suite():
            with self.subTest(name):
                self.assertIn("fetch-depth: 0", text,
                              "%s runs the suite, which reads tagged releases' source, so "
                              "its checkout has to fetch the history and the tags" % name)

    def test_fetching_the_history_does_not_come_with_a_token_on_disk(self):
        """The two options sit together, and only one of them is about privilege."""
        for name, text in self.workflows_that_run_the_suite():
            with self.subTest(name):
                self.assertIn("persist-credentials: false", text)


if __name__ == "__main__":
    unittest.main()
