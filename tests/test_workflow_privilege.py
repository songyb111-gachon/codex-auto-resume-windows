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
# Every workflow, named: a new one is looked at here before anything else.
KNOWN = ["community-report.yml", "release.yml", "sync-ko.yml", "test.yml"]


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
        for name in ("release.yml", "community-report.yml"):
            with self.subTest(name):
                self.assertRegex(text(name), r"(?m)^permissions: \{\}\s*$")

    def test_every_workflow_is_known(self):
        self.assertEqual(sorted(path.name for path in WORKFLOWS.glob("*.y*ml")), KNOWN)

    def test_only_the_report_check_runs_on_a_strangers_pull_request_with_the_bases_token(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            with self.subTest(path.name):
                if path.name == "community-report.yml":
                    self.assertIn("pull_request_target", path.read_text(encoding="utf-8"))
                else:
                    self.assertNotIn("pull_request_target", path.read_text(encoding="utf-8"))

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
        self.assertIn(r"-notmatch '^\d+\.\d+\.\d+(-alpha)?$'", text("release.yml"))

    def test_a_pre_release_never_becomes_the_latest_release(self):
        publish = job(text("release.yml"), "publish")
        self.assertIn("prerelease=(--prerelease --latest=false)", publish)
        self.assertIn('"v*.*.*-alpha"', text("release.yml"))

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


class ReleaseAttestationTests(unittest.TestCase):
    """Every archive a release publishes is attested, by one step, before it is published.

    Build provenance is how a download is traced back to the run and the commit that made it
    (docs/VERIFY.md). Until v0.6.11 nothing asserted that the step making it exists - only that
    the build job could not make one - and two editions are what made that worth closing: a
    second archive is a second subject, and a step naming only the first would publish the
    other unattested with every check green.
    """

    ARCHIVES = ("STANDARD_ZIP", "ADVANCED_ZIP")

    def setUp(self):
        self.source = text("release.yml")
        self.publish = job(self.source, "publish")

    def step(self, name):
        start = self.publish.index("- name: %s\n" % name)
        end = self.publish.find("\n      - name:", start)
        return self.publish[start:] if end < 0 else self.publish[start:end]

    def test_the_publish_job_names_one_archive_per_edition(self):
        named = dict(re.findall(r"(?m)^      ([A-Z]+_ZIP): (.+?)\s*$", self.publish))
        self.assertEqual(sorted(named), sorted(self.ARCHIVES))
        for path in named.values():
            self.assertRegex(path, r"^dist/CodexAutoResume-(Advanced-)?v\$\{\{ needs\.build\.outputs\.version \}\}-win-x64\.zip$")

    def test_one_step_attests_every_archive(self):
        self.assertEqual(self.source.count("uses: actions/attest-build-provenance@"), 1)
        step = self.step("Attest the archives")
        self.assertIn("uses: actions/attest-build-provenance@", step)
        subjects = re.search(r"subject-path: \|\n((?:            \S.*\n?)+)", step)
        self.assertIsNotNone(subjects, "the attestation names no list of subjects")
        self.assertEqual([line.strip() for line in subjects.group(1).splitlines()],
                         ["${{ env.%s }}" % name for name in self.ARCHIVES])

    def test_only_the_publish_job_can_attest(self):
        for grant in ("id-token: write", "attestations: write"):
            with self.subTest(grant):
                line = r"(?m)^ +%s\s*$" % re.escape(grant)
                self.assertEqual(len(re.findall(line, self.publish)), 1)
                self.assertEqual(len(re.findall(line, self.source)), 1)

    def test_it_attests_after_every_check_and_before_the_release_exists(self):
        order = [self.publish.index("- name: %s\n" % name) for name in (
            "Check it again, here", "Check each archive is its own edition",
            "Refuse to republish a version that already has assets", "Attest the archives",
            "Publish the GitHub release")]
        self.assertEqual(order, sorted(order))

    def test_the_release_carries_exactly_each_archive_and_its_checksum(self):
        self.assertEqual(self.source.count("gh release create"), 1)
        publish = self.step("Publish the GitHub release")
        command = publish[publish.index('gh release create "v$VERSION"'):publish.index("--title")]
        self.assertEqual(re.findall(r'"(\$[A-Z_]+(?:\.sha256)?)"', command),
                         ["$STANDARD_ZIP", "$STANDARD_ZIP.sha256", "$ADVANCED_ZIP", "$ADVANCED_ZIP.sha256"])

    def test_both_archives_are_checked_again_here(self):
        self.assertIn('for zip in "$STANDARD_ZIP" "$ADVANCED_ZIP"; do', self.step("Check it again, here"))


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


class CommunityReportPrivilegeTests(unittest.TestCase):
    """community-report.yml judges a stranger's pull request under pull_request_target.

    That trigger runs main's definition of the workflow with the base repository's token, which
    is what keeps a fork from rewriting the check it is judged by - and the classic way to be
    taken over, the moment someone adds a checkout of the head, a cache, an artifact or a secret
    to "just look at the file". So each of those is held here, not only today's shape, and the
    script it runs is held to reading git as data."""

    def setUp(self):
        self.source = text("community-report.yml")
        self.check = (ROOT / "build" / "community_check.py").read_text(encoding="utf-8")

    def test_the_only_trigger_is_pull_request_target_on_main(self):
        on = self.source[self.source.index("\non:"):self.source.index("\npermissions:")]
        self.assertEqual(re.findall(r"(?m)^  ([a-z_]+):", on), ["pull_request_target"])
        self.assertIn("branches: [main]", on)
        for other in ("workflow_dispatch", "workflow_run", "issue_comment", "push:", "schedule"):
            self.assertNotIn(other, self.source)

    def test_nothing_at_the_top_level_and_only_read_in_the_job(self):
        self.assertRegex(self.source, r"(?m)^permissions: \{\}\s*$")
        grants = re.findall(r"(?m)^      ([a-z-]+): (read|write|none)\s*$", self.source)
        self.assertEqual(grants, [("contents", "read")])
        self.assertEqual(self.source.count("permissions:"), 2)

    def test_every_checkout_is_the_base(self):
        checkouts = re.findall(r"uses: actions/checkout@", self.source)
        self.assertEqual(len(checkouts), 1)
        refs = re.findall(r"(?m)^\s*ref: (.+)$", self.source)
        self.assertEqual(refs, ["${{ github.event.pull_request.base.sha }}"])
        for head in ("head.ref", "merge_commit_sha", "refs/pull/${{", "github.head_ref", "/merge"):
            self.assertNotIn(head, self.source)
        # The head's SHA reaches the job only through env:, to be compared and handed to the check.
        uses_blocks = re.split(r"(?m)^      - ", self.source)
        for block in uses_blocks:
            if "uses:" in block:
                self.assertNotIn("head.", block)

    def test_no_secret_no_cache_no_artifact_no_install(self):
        for forbidden in ("secrets.", "GITHUB_TOKEN", "actions/cache", "upload-artifact", "download-artifact",
                          "cache:", "pip ", "pip3", "requirements", "npm ", "id-token", "attestations"):
            self.assertNotIn(forbidden, self.source)

    def test_it_runs_no_suite_and_only_the_bases_check(self):
        self.assertNotIn("unittest", self.source)
        runs = re.findall(r"(?m)^\s*run: (?!\|)(.+)$", self.source)
        self.assertEqual(runs, ["python build/community_check.py"])
        self.assertIn("PYTHONPATH: src", self.source)
        self.assertNotIn("git checkout", self.source)
        self.assertNotIn("git switch", self.source)
        self.assertNotIn("git worktree", self.source)
        self.assertNotIn("git merge ", self.source)

    def test_it_is_bounded(self):
        self.assertIn("runs-on: ubuntu-latest", self.source)
        self.assertIn("timeout-minutes: 5", self.source)
        self.assertIn("group: community-report-${{ github.event.pull_request.number }}", self.source)

    def test_the_check_reads_git_as_data_and_nothing_else(self):
        """No exec, eval, import machinery or shell; every process it starts is git."""
        import ast
        tree = ast.parse(self.check)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, ("exec", "eval", "compile", "__import__"))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] + [getattr(node, "module", None) or ""]
                for name in names:
                    self.assertNotIn(name.split(".")[0], ("importlib", "runpy", "pickle", "marshal", "shlex",
                                                          "urllib", "http", "socket", "requests"))
            if isinstance(node, ast.keyword) and node.arg == "shell":
                self.assertIs(getattr(node.value, "value", None), False)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in ("subprocess", "os"):
                self.assertIn(node.func.attr, ("run",), "only subprocess.run, and only for git")
                argv = node.args[0]
                self.assertIsInstance(argv, ast.List)
                self.assertEqual(getattr(argv.elts[0], "value", None), "git")
        self.assertEqual(self.check.count("subprocess.run("), 1)
        for porcelain in ("checkout", "switch", "worktree", "reset", "merge", "apply", "am", "fetch", "pull"):
            self.assertNotIn('"%s"' % porcelain, self.check, "the check reads; it never changes the checkout")


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
