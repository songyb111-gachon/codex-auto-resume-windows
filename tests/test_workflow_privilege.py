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
- the report check reads a stranger's pull request as data and writes nothing;
- the filer that files what the check accepts plans with no write access, writes from a job that
  runs no Python and no repository code, and reads nothing from the event that woke it;
- no expression is spliced into a shell script where a value could become code.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
# Every workflow, named: a new one is looked at here before anything else.
KNOWN = ["community-file.yml", "community-report.yml", "release.yml", "sync-ko.yml", "test.yml"]


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
        for name in ("release.yml", "community-report.yml", "community-file.yml"):
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


def steps(block):
    """{name or uses: text} for each step of a job, without its comment lines: a comment runs nothing,
    and the one above a step would otherwise be read as the end of the step before it."""
    found = {}
    for chunk in re.split(r"(?m)^      - ", block)[1:]:
        named = re.match(r"(?:name: (.+)|uses: ([^\s#]+))", chunk)
        lines = [line for line in chunk.splitlines() if not line.lstrip().startswith("#")]
        found[(named.group(1) or named.group(2)).strip()] = "\n".join(lines) + "\n"
    return found


class CommunityFilePrivilegeTests(unittest.TestCase):
    """community-file.yml files what the report check accepts, with write access to main.

    It is the one workflow here that writes what strangers sent, so each of the ways that goes wrong
    is held, not just today's shape: the job that reads their files holds no write access and no
    token while Python runs; the job that writes runs no Python and no repository code, only gh and
    git on data it re-derives; nothing is read from the event that woke it; main moves by
    compare-and-swap after the tree check; and the only artifact passes from one job to the other."""

    TOKEN_STEPS = ("Read the queue", "Read those closer", "Write to GitHub")
    EXPRESSIONS = {"secrets.GITHUB_TOKEN", "vars.COMMUNITY_AUTOFILE", "vars.COMMUNITY_BLOCKED",
                   "github.event_name", "inputs.attempt", "runner.temp"}

    def setUp(self):
        self.source = text("community-file.yml")
        self.plan, self.write = job(self.source, "plan"), job(self.source, "write")
        self.plan_steps, self.write_steps = steps(self.plan), steps(self.write)

    def test_the_triggers_are_a_finished_check_a_schedule_and_a_retry(self):
        on = self.source[self.source.index("\non:"):self.source.index("\npermissions:")]
        self.assertEqual(re.findall(r"(?m)^  ([a-z_]+):", on), ["workflow_run", "schedule", "workflow_dispatch"])
        self.assertIn('workflows: ["community report"]', on)
        self.assertIn("types: [completed]", on)
        self.assertRegex(on, r'cron: "\d+ \d+ \* \* \*"')
        for other in ("pull_request", "push:", "issue_comment", "issues:", "repository_dispatch"):
            self.assertNotIn(other, on)

    def test_nothing_at_the_top_and_exactly_these_grants(self):
        self.assertRegex(self.source, r"(?m)^permissions: \{\}\s*$")
        self.assertEqual(self.source.count("permissions:"), 3)
        grants = lambda block: re.findall(r"(?m)^      ([a-z-]+): (read|write|none)\s*$", block)  # noqa: E731
        self.assertEqual(grants(self.plan), [("contents", "read"), ("pull-requests", "read"), ("issues", "read"),
                                             ("actions", "read")])
        self.assertEqual(grants(self.write), [("contents", "write"), ("pull-requests", "write"),
                                              ("actions", "write")])

    def test_nothing_is_read_from_the_event_or_a_pull_request(self):
        for expression in re.findall(r"\$\{\{([^}]*)\}\}", self.source):
            with self.subTest(expression):
                self.assertIn(expression.strip(), self.EXPRESSIONS)
        for head in ("github.event.", "github.head_ref", "workflow_run.head_", "git checkout", "git switch",
                     "git merge ", "git worktree", "git pull", "refs/pull/"):
            self.assertNotIn(head, self.source)

    def test_one_checkout_of_main_with_no_token_left_and_every_tag(self):
        self.assertEqual(self.source.count("uses: actions/checkout@"), 1)
        checkout = self.plan_steps[next(name for name in self.plan_steps if name.startswith("actions/checkout@"))]
        self.assertIn("ref: main\n", checkout)
        self.assertIn("persist-credentials: false", checkout)
        self.assertIn("fetch-depth: 0", checkout)
        self.assertNotIn("actions/checkout", self.write)

    def test_only_the_named_steps_see_the_token_and_they_run_nothing_of_ours(self):
        holders = {name for name, block in {**self.plan_steps, **self.write_steps}.items()
                   if "secrets.GITHUB_TOKEN" in block}
        self.assertEqual(holders, set(self.TOKEN_STEPS))
        self.assertEqual(self.source.count("secrets.GITHUB_TOKEN"), len(self.TOKEN_STEPS))
        for name in self.TOKEN_STEPS:
            block = {**self.plan_steps, **self.write_steps}[name]
            with self.subTest(name):
                for code in ("python", ".py", ".ps1", "unittest", "pip install", "source ", "eval", "bash -c",
                             "npm", "node ", "build/", "scripts/"):
                    self.assertNotIn(code, block)
        for name, block in {**self.plan_steps, **self.write_steps}.items():
            if name not in self.TOKEN_STEPS:
                with self.subTest(name):
                    self.assertNotIn("GH_TOKEN", block)
                    self.assertNotIn("GITHUB_TOKEN", block)

    def test_the_plan_jobs_token_only_reads(self):
        for name in ("Read the queue", "Read those closer"):
            block = self.plan_steps[name]
            with self.subTest(name):
                self.assertNotIn("-X ", block)
                self.assertNotIn("--method", block)
                self.assertNotIn("--input", block)
                self.assertNotIn("workflow run", block)
                self.assertNotIn("git ", block)
                self.assertTrue(all(line.lstrip().startswith(("gh api", "--jq", ">")) or "gh " not in line
                                    for line in block.splitlines()))

    def test_python_runs_only_the_filer_and_only_without_a_token(self):
        for name, block in self.plan_steps.items():
            if "python " in block:
                with self.subTest(name):
                    self.assertRegex(block, r"run: python build/community_file\.py (choose|plan) --queue ")
                    self.assertIn("PYTHONPATH: src", block)
        self.assertNotIn("python", self.write)
        self.assertNotIn("setup-python", self.write)
        self.assertIn("runs-on: ubuntu-latest", self.write)
        self.assertIn("needs: plan", self.write)

    def test_the_write_step_trusts_neither_the_runner_nor_the_plan(self):
        write = self.write_steps["Write to GitHub"]
        for setting in ("GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_NO_LAZY_FETCH=1",
                        "core.hooksPath=/dev/null", "git=/usr/bin/git", "gh=/usr/bin/gh"):
            self.assertIn(setting, write)
        self.assertEqual(re.findall(r"(?m)^\s+(?:git|gh) ", write), [], "tools only by their absolute paths")

    def test_main_and_dev_move_only_forward_and_only_after_the_tree_check(self):
        write = self.write_steps["Write to GitHub"]
        for branch, check in (("main", "GitHub made a tree other than the one tested"),
                              ("dev", "GitHub made a tree for dev other than the one tested")):
            move = write.index('-X PATCH "repos/$repo/git/refs/heads/%s"' % branch)
            self.assertLess(write.index(check), move)
            self.assertIn("-F force=false", write[move:move + 120])
        self.assertLess(write.index('[ "$(api "repos/$repo/git/ref/heads/main" --jq .object.sha)" = "$main" ] '
                                    '|| lost_race\n            if ! answer=$(api -X PATCH'),
                        write.index('-X PATCH "repos/$repo/git/refs/heads/main"'))
        self.assertEqual(write.count("git/refs/heads/"), 2)
        for forbidden in ("git push", "--force", "force=true", '"force":true', "force: true", "git/refs\"",
                          "-X DELETE", "-X PUT"):
            self.assertNotIn(forbidden, self.source)

    def test_comments_and_closes_come_last_and_only_on_open_report_pull_requests(self):
        write = self.write_steps["Write to GitHub"]
        self.assertLess(write.index('-X PATCH "repos/$repo/git/refs/heads/dev"'),
                        write.index('-X POST "repos/$repo/issues/$number/comments"'))
        self.assertIn('"open main "*" true") ;;', write)
        self.assertIn('= "github-actions[bot] $number" ]', write)

    def test_the_only_artifact_is_the_plan_passed_from_one_job_to_the_other(self):
        self.assertEqual(self.source.count("actions/upload-artifact@"), 1)
        self.assertEqual(self.source.count("actions/download-artifact@"), 1)
        self.assertIn("actions/upload-artifact@", self.plan)
        self.assertIn("actions/download-artifact@", self.write)
        self.assertEqual(re.findall(r"name: (community-plan)", self.source), ["community-plan", "community-plan"])
        self.assertIn("retention-days: 1", self.plan)
        for forbidden in ("actions/cache", "cache:", "pip install", "npm ", "apt-get", "choco ", "id-token",
                          "attestations"):
            self.assertNotIn(forbidden, self.source)

    def test_it_is_bounded(self):
        self.assertIn("concurrency:\n  group: community-file\n  cancel-in-progress: false", self.source)
        self.assertNotRegex(self.source, r"(?m)^\s*queue:")
        self.assertIn("timeout-minutes: 30", self.plan)
        self.assertIn("timeout-minutes: 15", self.write)
        for block in (self.plan, self.write):
            self.assertIn("if: github.repository == 'songyb111-gachon/codex-auto-resume-windows'", block)
        for line in self.source.splitlines():
            if "vars." in line:
                self.assertRegex(line, r"^          [A-Z]+: \$\{\{ vars\.[A-Z_]+ \}\}$")


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
