"""The filer (build/community_file.py) and the step that writes what it plans (community-file.yml).

Everything runs on a scratch world: a bare repository standing for GitHub's copy, with main, dev,
a release tag and each pull request's head under refs/pull/N/head; the plan job's checkout of it;
and the files the job's read-only steps would have saved about each pull request. The planner is
run on that as the job runs it, with the tests it would run replaced by a stand-in. Then the write
step is run as it is written in the workflow - its own bash, with `gh` pointed at tests/fakegithub.py
and git at the scratch world - so what reaches "GitHub" is what the real step would send.

What is held here, beside each rule: a filing changes exactly the files it may, with our bytes and
never the sender's; nothing a sender wrote reaches a comment; every limit waits with its reason and
date; the kill switch writes nothing; dev takes main's filings only when that cannot touch its
Korean documents; and the write step moves main only onto the tree that was tested, from the
commit the plan was made on, refusing anything it was handed that the filer does not write.
"""
from __future__ import annotations

import ast
import calendar
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

import community_check as check  # noqa: E402
import community_file as filer  # noqa: E402
import community_report as reader  # noqa: E402

SAMPLE = ROOT / "tests" / "fixtures" / "community" / "codex-cli-0.155.0-alpha.9.2.json"
WORKFLOW = ROOT / ".github" / "workflows" / "community-file.yml"
FAKE = ROOT / "tests" / "fakegithub.py"
NOW = calendar.timegm((2026, 9, 25, 0, 0, 0))
OLD = "2020-01-01T00:00:00Z"
REPO = "owner/repo"
VERSION = "codex-cli 0.155.0-alpha.9.2"
HOSTILE = "::error::pwned%0A@everyone<script>"


def sample(login="ExampleUser", version=VERSION, failed=False) -> dict:
    report = json.loads(SAMPLE.read_text(encoding="utf-8"))
    report["reporter"]["github_login"] = login
    report["codex_version"] = version
    if failed:
        report["records"][1]["state"] = "recovery_turn_failed"
    return report


def git(root, *args, date="2026-09-20T00:00:00Z", data=None, env=None) -> str:
    environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="t",
                       GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@example.invalid", GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
                       **(env or {}))
    done = subprocess.run(["git", "-C", str(root), "-c", "core.autocrlf=false", *args],
                          input=data if data is not None else b"", capture_output=True, env=environment)
    if done.returncode:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr.decode("utf-8", "replace")))
    return done.stdout.decode("utf-8").strip()


def commit(repo, parent, files, message, date="2026-09-20T00:00:00Z") -> str:
    """A commit on `parent` with `files` ({path: bytes or None}) set or removed, made with plumbing."""
    with tempfile.TemporaryDirectory() as folder:
        index = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
        if parent:
            git(repo, "read-tree", parent, env=index)
        for path, data in files.items():
            if data is None:
                git(repo, "update-index", "--index-info", data=("0 %s\t%s\n" % ("0" * 40, path)).encode("utf-8"),
                    env=index)
                continue
            blob = git(repo, "hash-object", "-w", "--no-filters", "--stdin", data=data)
            git(repo, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path), env=index)
        tree = git(repo, "write-tree", env=index)
    return git(repo, "commit-tree", tree, *(["-p", parent] if parent else []), "-m", message, date=date)


def git_bash():
    """Git's own bash on Windows (never WSL's), or the system's elsewhere; None when there is none."""
    if os.name != "nt":
        return shutil.which("bash")
    found = shutil.which("git")
    if not found:
        return None
    for place in Path(found).resolve().parents:
        if (place / "bin" / "bash.exe").is_file() and (place / "usr" / "bin").is_dir():
            return str(place / "bin" / "bash.exe")
    return None


def step_script(name) -> str:
    """The `run:` script of one step of community-file.yml, as bash will read it."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- name: %s" % name)
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body) + "\n"


def base_files() -> dict:
    index = reader.build_index({}, generated_at=NOW - 5 * 86400)
    return {"README.md": b"# Tool\n",
            filer.COMPAT_DATA: (ROOT / filer.COMPAT_DATA).read_bytes(),
            filer.COUNTS: reader.encode(reader.project(index)),
            filer.INDEX: reader.encode(index),
            filer.README: reader.build_readme(index).encode("ascii")}


class World:
    """GitHub's copy, the plan job's checkout of it, and what the read-only steps saved."""

    def __init__(self, root: Path, template=None):
        self.root = root
        self.origin, self.checkout = root / "origin.git", root / "checkout"
        self.queue, self.out, self.work = root / "queue", root / "plan", root / "filer"
        if template is not None:
            shutil.copytree(template.origin, self.origin)
            self.base, self.dev = template.base, template.dev
        else:
            root.mkdir(parents=True, exist_ok=True)
            git(root, "init", "-q", "--bare", str(self.origin))
            git(self.origin, "config", "uploadpack.allowFilter", "true")
            git(self.origin, "config", "uploadpack.allowAnySHA1InWant", "true")
            self.base = commit(self.origin, None, base_files(), "start")
            git(self.origin, "update-ref", "refs/heads/main", self.base)
            git(self.origin, "tag", "v0.6.9", self.base)
            self.dev = commit(self.origin, self.base, {"docs/GUIDE.ko.md": "# 안내\n".encode("utf-8")},
                              "Korean", date="2026-09-21T00:00:00Z")
            git(self.origin, "update-ref", "refs/heads/dev", self.dev)
        self.queue.mkdir()
        self.pulls, self.comments, self.runs, self.rate = [], [], [], 5000
        self.github = {"pulls": {}, "comments": {}, "runs": [], "calls": [], "commits": [], "moves": [],
                       "dispatches": []}

    def copy_to(self, root: Path) -> "World":
        """This world, files and all, somewhere else: a plan made once and written from many times."""
        shutil.copytree(self.root, root)
        other = World.__new__(World)
        other.__dict__.update(copy.deepcopy({key: value for key, value in self.__dict__.items()
                                             if not isinstance(value, Path)}))
        other.root = root
        other.origin, other.checkout = root / "origin.git", root / "checkout"
        other.queue, other.out, other.work = root / "queue", root / "plan", root / "filer"
        return other

    # ------------------------------------------------------------ GitHub's side
    def main(self) -> str:
        return git(self.origin, "rev-parse", "refs/heads/main")

    def on_main(self, files, message="change", date="2026-09-24T00:00:00Z") -> str:
        made = commit(self.origin, self.main(), files, message, date=date)
        git(self.origin, "update-ref", "refs/heads/main", made)
        return made

    def on_dev(self, files, message="dev work"):
        made = commit(self.origin, git(self.origin, "rev-parse", "refs/heads/dev"), files, message,
                      date="2026-09-24T00:00:00Z")
        git(self.origin, "update-ref", "refs/heads/dev", made)
        return made

    def filed_by_hand(self, report, *, reporter_id=1, number=1, date="2026-09-24T00:00:00Z"):
        """A report on main as the filer or the maintainer's tool would have put it there."""
        path = reader.canonical_path(report["reporter"]["github_login"], report["codex_version"])
        filed = {}
        for name in git(self.origin, "ls-tree", "-r", "--name-only", "refs/heads/main", "--",
                        reader.COMMUNITY).splitlines():
            if check.REPORT_PATH.fullmatch(name):
                filed[name] = json.loads(git(self.origin, "cat-file", "blob", "refs/heads/main:" + name))
        files = filer.filing(filed, path, report, NOW)
        message = filer.commit_message(report["reporter"]["github_login"], report["codex_version"],
                                       reporter_id, number)
        return self.on_main(files, message, date=date)

    def pr(self, number, report=None, *, user_id=None, login=None, raw=None, path=None, created=OLD,
           association="CONTRIBUTOR", files=None, commits=1, changed=1, head=True, opened=None):
        report = report if report is not None else sample()
        login = login or report["reporter"]["github_login"]
        user_id = user_id if user_id is not None else 500 + number
        path = path or reader.canonical_path(login, report["codex_version"])
        raw = raw if raw is not None else reader.encode(report)
        made = commit(self.origin, self.main(), {path: raw}, "Compatibility report", date="2026-09-23T00:00:00Z")
        if head:
            git(self.origin, "update-ref", "refs/pull/%d/head" % number, made)
        self.pulls.append({"number": number, "draft": False,
                           "created_at": opened or reader.iso(NOW - 86400 + number), "head_sha": made,
                           "head_ref": "compat-report/" + reader.file_name(report["codex_version"])[:-5],
                           "user_id": user_id, "login": login, "type": "User", "association": association})
        self.save("pull-%d.json" % number, {"state": "open", "draft": False, "base": "main", "head_sha": made,
                                            "commits": commits, "changed_files": changed, "user_id": user_id})
        self.save("files-%d.json" % number, files if files is not None else [{"filename": path, "status": "added"}])
        self.save("user-%d.json" % user_id, {"id": user_id, "type": "User", "created_at": created})
        self.github["pulls"][str(number)] = {"state": "open", "association": association,
                                             "branch": "compat-report/x"}
        return made

    def sticky(self, number, state, head, at, until=None, why=None, comment_id=None):
        comment_id = comment_id or 900 + number
        text = filer.marker(state, head, at, until, why)
        self.comments.append({"id": comment_id, "issue": str(number), "marker": text})
        self.github["comments"][str(comment_id)] = {"user": filer.BOT, "issue": str(number), "body": text + "\n"}

    def save(self, name, value):
        (self.queue / name).write_text(json.dumps(value) + "\n", encoding="utf-8")

    def survey(self):
        (self.queue / "pulls-1.jsonl").write_text("".join(json.dumps(p) + "\n" for p in self.pulls), encoding="utf-8")
        (self.queue / "comments-1.jsonl").write_text("".join(json.dumps(c) + "\n" for c in self.comments),
                                                     encoding="utf-8")
        (self.queue / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.runs), encoding="utf-8")
        (self.queue / "rate").write_text(str(self.rate), encoding="ascii")

    # ------------------------------------------------------------ the plan job
    def sync(self):
        """The plan job's checkout: a clone of GitHub's copy, brought up to date."""
        self.survey()
        if not self.checkout.exists():
            git(self.root, "clone", "-q", self.origin.resolve().as_uri(), str(self.checkout))
        else:
            git(self.checkout, "fetch", "-q", "--tags", "origin", "+refs/heads/*:refs/remotes/origin/*")

    def choose(self, environ=None):
        self.sync()
        environment = {"GITHUB_REPOSITORY": REPO}
        environment.update(environ or {})
        return filer.choose(self.queue, environ=environment, now=NOW, root=self.checkout)

    def plan(self, environ=None, run_tests=None):
        self.sync()
        environment = {"GITHUB_REPOSITORY": REPO}
        environment.update(environ or {})
        self.work.mkdir(exist_ok=True)
        return filer.plan(self.queue, self.out, self.work, environ=environment, now=NOW, root=self.checkout,
                          run_tests=run_tests or (lambda tree: True))

    def actions(self) -> dict:
        found = {}
        for line in (self.out / "actions").read_text(encoding="utf-8").splitlines():
            number, state, what, comment, post = line.split()
            text = self.out / "texts" / ("%s.md" % number)
            found[int(number)] = {"state": state, "close": what == "close", "comment": int(comment),
                                  "text": text.read_text(encoding="utf-8") if post == "post" else None}
        return found

    def chain(self) -> list:
        return (self.out / "chain").read_text(encoding="utf-8").split()

    def fetched(self, number) -> bool:
        return subprocess.run(["git", "-C", str(self.checkout), "rev-parse", "--verify", "-q",
                               "refs/community/pr/%d" % number], capture_output=True).returncode == 0

    def show(self, ref, path, repo=None) -> bytes:
        done = subprocess.run(["git", "-C", str(repo or self.checkout), "cat-file", "blob", "%s:%s" % (ref, path)],
                              capture_output=True)
        return done.stdout if done.returncode == 0 else None

    # ------------------------------------------------------------ the write job
    def write(self, environ=None):
        bash = git_bash()
        script = step_script("Write to GitHub")
        wrapper = self.root / "gh"
        wrapper.write_text('#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n' % (Path(sys.executable).as_posix(),
                                                                           FAKE.as_posix()), encoding="utf-8")
        wrapper.chmod(0o755)
        for old, new in (("git=/usr/bin/git", "git=git"), ("gh=/usr/bin/gh", "gh=%s" % wrapper.as_posix()),
                         ('remote="https://github.com/$GITHUB_REPOSITORY.git"',
                          'remote="%s"' % self.origin.resolve().as_uri())):
            assert script.count(old) == 1, old
            script = script.replace(old, new)
        state = self.root / "github"
        state.mkdir(exist_ok=True)
        (state / "github.json").write_text(json.dumps(dict(self.github, runs=self.runs)), encoding="utf-8")
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update(RUNNER_TEMP=self.root.resolve().as_posix(), GITHUB_REPOSITORY=REPO, GH_TOKEN="not-a-token",
                           AUTOFILE="", EVENT="workflow_run", ATTEMPT="", FAKE_GITHUB=str(state),
                           FAKE_ORIGIN=str(self.origin.resolve()))
        environment.update(environ or {})
        shutil.rmtree(self.root / "work", ignore_errors=True)
        # A file, not `bash -c`: Windows' command line would re-quote the script's own quotes.
        step = self.root / "write.sh"
        step.write_bytes(script.encode("utf-8"))
        done = subprocess.run([bash, step.as_posix()], capture_output=True, env=environment, timeout=300)
        self.github = json.loads((state / "github.json").read_text(encoding="utf-8"))
        return done.returncode, done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")


class Case(unittest.TestCase):
    """One scratch world per test, copied from one built once."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.template = World(Path(cls.folder.name) / "template")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.world = World(Path(scratch.name) / "world", self.template)

    def assertTold(self, number, state, fragment=None, close=None):
        action = self.world.actions().get(number)
        self.assertIsNotNone(action, "nothing was planned for #%d" % number)
        self.assertEqual(action["state"], state, action)
        if fragment is not None:
            self.assertIn(fragment, action["text"] or "")
        if close is not None:
            self.assertEqual(action["close"], close)
        return action


# ============================================================================== the filing itself
class FilingTests(Case):
    def test_a_filing_changes_exactly_the_four_files_with_our_bytes(self):
        report = sample()
        report["capabilities"]["usage_probe"]["level"] = "VERIFIED"      # claimed beyond its records
        report["note"] = "My own words."
        self.world.pr(7, report)
        planner = self.world.plan()
        chain = self.world.chain()
        self.assertEqual(len(chain), 1)
        main = git(self.world.checkout, "rev-parse", "refs/remotes/origin/main")
        changed = git(self.world.checkout, "diff", "--name-only", main, chain[0]).splitlines()
        path = reader.canonical_path("ExampleUser", VERSION)
        self.assertEqual(sorted(changed), sorted([path, filer.INDEX, filer.README, filer.COUNTS]))
        self.assertTrue(all(filer.writable(name) for name in changed))
        kept = reader.filed_copy(report)
        self.assertEqual(self.world.show(chain[0], path), reader.encode(kept))
        self.assertNotIn(b"My own words", self.world.show(chain[0], path))
        index = json.loads(self.world.show(chain[0], filer.INDEX))
        self.assertEqual(index, reader.build_index({path: kept}, generated_at=NOW))
        self.assertEqual(self.world.show(chain[0], filer.README).decode("ascii"), reader.build_readme(index))
        self.assertEqual(json.loads(self.world.show(chain[0], filer.COUNTS)), reader.project(index))
        message = git(self.world.checkout, "cat-file", "commit", chain[0]).split("\n\n", 1)[1]
        self.assertEqual(message, filer.commit_message("ExampleUser", VERSION, 507, 7).rstrip("\n"))
        action = self.assertTold(7, filer.FILED, "Filed as `%s` in {commit}" % path, close=True)
        self.assertIn("- recomputed: capabilities.usage_probe: VERIFIED is more than its records show", action["text"])
        self.assertTrue(action["text"].startswith("<!-- community-file state=filed head="))
        self.assertEqual(len(planner.filings), 1)
        self.assertTrue((self.world.out / "plan.bundle").is_file())

    def test_two_reports_with_the_same_records_in_one_run_file_the_first_only(self):
        self.world.pr(7, sample())
        self.world.pr(8, sample(login="ExampleUser2"))
        self.world.plan()
        self.assertEqual(len(self.world.chain()), 1)
        self.assertTold(7, filer.FILED)
        self.assertTold(8, filer.REFUSED, "same, in order", close=False)
        self.assertIn(filer.ACTIONS[check.COPY], self.world.actions()[8]["text"])

    def test_a_report_filed_already_with_these_bytes_is_closed_as_filed(self):
        """A run that died after main moved, or the maintainer's tool filing it first."""
        filed = self.world.filed_by_hand(sample(), reporter_id=507, number=7)
        self.world.pr(7, sample())
        self.world.plan()
        self.assertEqual(self.world.chain(), [])
        self.assertTold(7, filer.FILED, "in %s" % filed, close=True)

    def test_the_same_login_and_version_with_other_bytes_is_refused_as_filed(self):
        other = sample()
        other["records"] = other["records"][:2]
        self.world.pr(9, other, user_id=507)
        self.world.filed_by_hand(sample(), reporter_id=507, number=7)
        self.world.plan()
        self.assertTold(9, filer.REFUSED, filer.ACTIONS[check.FILED])

    def test_a_withdrawal_takes_the_report_out_and_keeps_it_out(self):
        """What the maintainer's tool commits to withdraw one, and what the filer does when the same
        report is sent again."""
        self.world.filed_by_hand(sample(), reporter_id=507, number=7)
        path = reader.canonical_path("ExampleUser", VERSION)
        filed = {path: json.loads(git(self.world.origin, "cat-file", "blob", "refs/heads/main:" + path))}
        files = filer.withdrawal(filed, path, 507, None, NOW)
        self.assertIsNone(files[path])
        self.assertEqual(json.loads(files[filer.INDEX])["versions"], {})
        self.assertEqual(json.loads(files[filer.WITHDRAWN]), {"format": filer.WITHDRAWN_FORMAT, "withdrawn": [
            {"reporter_id": 507, "login": "ExampleUser", "version": "0.155.0-alpha.9.2", "at": reader.iso(NOW)}]})
        again = filer.withdrawal(filed, path, 507, files[filer.WITHDRAWN], NOW + 60)
        self.assertEqual(len(json.loads(again[filer.WITHDRAWN])["withdrawn"]), 1, "withdrawn once, listed once")
        self.world.on_main(files, "Community report withdrawn")
        self.world.pr(8, sample(), user_id=507)
        self.world.plan()
        self.assertTold(8, filer.REFUSED, "not accepted from this account")

    def test_nothing_is_filed_until_the_folder_is_open(self):
        self.world.on_main({filer.INDEX: None, filer.README: None})
        self.world.pr(7)
        planner = self.world.plan()
        self.assertEqual(self.world.chain(), [])
        self.assertFalse(self.world.fetched(7))
        self.assertTrue(any("not on main" in line for line in planner.summary))

    def test_a_filing_that_fails_the_tests_is_dropped_and_the_maintainer_told(self):
        self.world.pr(7, sample())
        self.world.pr(8, sample(login="BadUser", version="codex-cli 0.153.4"))
        bad = reader.canonical_path("BadUser", "codex-cli 0.153.4")
        self.world.plan(run_tests=lambda tree: not (tree / bad).exists())
        chain = self.world.chain()
        self.assertEqual(len(chain), 1)
        self.assertIsNone(self.world.show(chain[0], bad))
        self.assertTold(7, filer.FILED)
        self.assertTold(8, filer.NEEDS_OWNER, "maintainer has been told", close=False)
        self.assertEqual((self.world.out / "red").read_text(encoding="utf-8"), "tests 8\n")

    def test_the_tests_run_on_the_tree_that_would_become_main(self):
        self.world.pr(7)
        seen = []
        self.world.plan(run_tests=lambda tree: seen.append(sorted(p.name for p in (tree / reader.COMMUNITY).iterdir()))
                        or True)
        self.assertIn(["ExampleUser", "README.md", "index.json"], seen)


# ============================================================================== what waits, and why
class LimitTests(Case):
    def test_a_young_account_is_closed_with_the_day_it_can_send_again(self):
        self.world.pr(7, created=reader.iso(NOW - 10 * 86400))
        self.world.plan()
        self.assertTold(7, filer.CLOSED, "this one is on 2026-10-15", close=True)
        self.assertFalse(self.world.fetched(7))
        self.assertEqual(self.world.chain(), [])

    def test_three_filings_from_one_account_in_a_week_make_the_fourth_wait(self):
        for number, version in enumerate(("0.153.4", "0.154.0-alpha.6.2", "0.155.0-alpha.2.6"), 1):
            self.world.filed_by_hand(sample(version="codex-cli " + version), reporter_id=507, number=number,
                                     date=reader.iso(NOW - (5 - number) * 86400))
        self.world.pr(7)
        self.world.plan()
        action = self.assertTold(7, filer.QUEUED, "3 reports filed in the last 7 days", close=False)
        self.assertIn("Looked at again automatically on 2026-09-28", action["text"])
        self.assertIn("until=2026-09-28T00:00:00Z", action["text"])

    def test_five_filings_for_one_version_in_a_week_make_the_sixth_wait(self):
        for number in range(1, 6):
            self.world.filed_by_hand(sample(login="Someone%d" % number), reporter_id=600 + number, number=number,
                                     date=reader.iso(NOW - 86400))
        mine = sample()
        mine["records"][3]["detected_at"] = "2026-09-22T17:27:31Z"          # not a copy of theirs
        self.world.pr(7, mine)
        self.world.plan()
        self.assertTold(7, filer.QUEUED, "this Codex version has had 5 reports filed")

    def test_a_version_older_than_the_data_names_waits_for_the_maintainer(self):
        self.world.pr(7, sample(version="codex-cli 0.150.0"))
        self.world.plan()
        self.assertTold(7, filer.QUEUED, "older than the ones the project's own data names")

    def test_newer_versions_the_data_does_not_name_are_filed_up_to_the_budget(self):
        self.world.pr(7, sample(version="codex-cli 0.160.0"))
        self.world.pr(8, sample(login="ExampleUser2", version="codex-cli 0.161.0"))
        self.world.pr(9, sample(login="ExampleUser3", version="codex-cli 0.160.0"))
        with mock.patch.object(filer, "MAX_UNLISTED", 1):
            self.world.plan()
        self.assertTold(7, filer.FILED)
        self.assertTold(8, filer.QUEUED, "Codex versions the project's own data does not name")
        self.assertTold(9, filer.REFUSED, "same, in order")

    def test_a_counts_file_without_half_its_room_left_waits(self):
        self.world.pr(7)
        with mock.patch.object(reader.product_reported, "MAX_VERSIONS", 1):
            self.world.plan()
        self.assertTold(7, filer.QUEUED, "no room for another version")

    def test_a_failure_on_a_version_this_project_verifies_is_held_for_the_maintainer(self):
        self.world.pr(7, sample(failed=True))
        self.world.plan()
        self.assertTold(7, filer.NEEDS_OWNER, "a person looks at that first", close=False)
        self.assertEqual((self.world.out / "red").read_text(encoding="utf-8"), "contradicts 7\n")
        self.assertEqual(self.world.chain(), [])

    def test_a_failure_on_a_version_nobody_verified_is_filed(self):
        self.world.pr(7, sample(failed=True, version="codex-cli 0.155.0-alpha.16.4"))
        self.world.plan()
        self.assertTold(7, filer.FILED)

    def test_a_blocked_or_withdrawn_account_is_refused(self):
        self.world.on_main({filer.WITHDRAWN: json.dumps({"format": filer.WITHDRAWN_FORMAT, "withdrawn": [
            {"reporter_id": 508, "login": "ExampleUser2", "version": "0.155.0-alpha.9.2",
             "at": "2026-09-24T00:00:00Z"}]}).encode("ascii")})
        self.world.pr(7)
        self.world.pr(8, sample(login="ExampleUser2"))
        self.world.plan(environ={"BLOCKED": "507, 9999"})
        for number in (7, 8):
            self.assertTold(number, filer.REFUSED, "not accepted from this account")
            self.assertFalse(self.world.fetched(number))

    def test_the_switch_pauses_on_anything_but_unset_or_on(self):
        """A switch that fails open is not a switch: `OFF`, `false` and `0` pause too."""
        for value in ("off", "OFF", "false", "0", "no", " paused ", "onn"):
            self.assertTrue(filer.Settings({"AUTOFILE": value}).paused, value)
        for value in ("", "on", "ON", " On ", None):
            self.assertFalse(filer.Settings({"AUTOFILE": value}).paused, value)
        self.world.pr(7)
        self.world.plan(environ={"AUTOFILE": "False"})
        self.assertEqual(self.world.chain(), [])
        self.assertFalse((self.world.out / "plan.bundle").exists())
        self.assertFalse(self.world.fetched(7))
        action = self.assertTold(7, filer.QUEUED, "filing is paused for now", close=False)
        self.assertIn("once filing is resumed", action["text"])
        self.world.plan(environ={"AUTOFILE": "ON"})
        self.assertEqual(len(self.world.chain()), 1)

    def test_nothing_is_filed_onto_a_red_main(self):
        self.world.runs = [{"status": "completed", "conclusion": "failure", "head_sha": "a" * 40, "event": "push",
                            "repo": REPO, "branch": "main"}]
        self.world.pr(7)
        self.world.plan()
        self.assertTold(7, filer.QUEUED, "tests on main are not passing")
        self.assertFalse(self.world.fetched(7))

    def test_a_red_run_of_a_fork_branch_called_main_does_not_stop_filing(self):
        self.world.runs = [{"status": "completed", "conclusion": "failure", "head_sha": "a" * 40,
                            "event": "pull_request", "repo": "someone/fork", "branch": "main"},
                           {"status": "completed", "conclusion": "success", "head_sha": "b" * 40, "event": "push",
                            "repo": REPO, "branch": "main"}]
        self.world.pr(7)
        self.world.plan()
        self.assertTold(7, filer.FILED)

    def test_with_few_requests_left_nothing_is_looked_at(self):
        self.world.rate = filer.MIN_RATE - 1
        self.world.pr(7)
        self.world.plan()
        self.assertEqual(self.world.actions(), {})
        self.assertFalse(self.world.fetched(7))


# ============================================================================== the queue itself
class QueueTests(Case):
    def test_one_open_report_per_account_the_others_are_closed(self):
        first = self.world.pr(7, opened="2026-09-20T00:00:00Z")
        self.world.pr(8, sample(version="codex-cli 0.153.4"), user_id=507, opened="2026-09-21T00:00:00Z")
        self.world.plan()
        self.assertTold(8, filer.CLOSED, "#7 is still open", close=True)
        self.assertFalse(self.world.fetched(8))
        self.assertTold(7, filer.FILED)
        self.assertTrue(first)

    def test_a_thousand_pull_requests_from_one_account_cost_one_look(self):
        for number in range(10, 40):
            self.world.pulls.append({"number": number, "draft": False, "created_at": reader.iso(NOW - 3600 + number),
                                     "head_sha": "%040x" % number, "head_ref": "compat-report/codex-cli-9.9.%d" % number,
                                     "user_id": 4242, "login": "Flooder", "type": "User",
                                     "association": "FIRST_TIME_CONTRIBUTOR"})
        self.world.pr(7)
        looked = self.world.choose()
        self.assertEqual(sorted(pull["user_id"] for pull in looked), [507, 4242])
        self.assertEqual(len((self.world.queue / "look").read_text(encoding="utf-8").splitlines()), 2)
        planner = self.world.plan()
        closed = [n for n, action in self.world.actions().items() if action["state"] == filer.CLOSED]
        self.assertEqual(len(closed), filer.MAX_CLOSED)
        self.assertTrue(planner)

    def test_at_most_eight_are_read_closer_the_least_recently_looked_first(self):
        for number in range(10, 22):
            self.world.pr(number, sample(login="User%d" % number), user_id=1000 + number)
            if number < 14:
                self.world.sticky(number, filer.QUEUED, "f" * 40, NOW - 86400 * (20 - number), NOW - 60,
                                  "reporter")
        looked = self.world.choose()
        self.assertEqual(len(looked), filer.MAX_LOOKED)
        self.assertEqual([pull["number"] for pull in looked][:4], [14, 15, 16, 17])

    def test_members_drafts_other_branches_and_ghosts_are_not_the_filers(self):
        self.world.pr(7, association="OWNER")
        self.world.pr(8, sample(login="ExampleUser2"), user_id=filer.GHOST)
        self.world.pr(9, sample(login="ExampleUser3"))
        self.world.pulls[-1]["head_ref"] = "patch-1"
        self.world.pr(10, sample(login="ExampleUser4"))
        self.world.pulls[-1]["draft"] = True
        self.world.plan()
        self.assertEqual(self.world.actions(), {})

    def test_a_refused_pull_request_is_not_read_again_until_it_changes(self):
        head = self.world.pr(7, sample(login="ExampleUser"), files=[{"filename": "x.json", "status": "added"}])
        self.world.sticky(7, filer.REFUSED, head, NOW - 86400, why="not-a-report")
        self.world.plan()
        self.assertEqual(self.world.actions(), {})
        self.assertFalse(self.world.fetched(7))

    def test_a_refusal_unchanged_for_fourteen_days_is_closed(self):
        head = self.world.pr(7)
        self.world.sticky(7, filer.REFUSED, head, NOW - filer.STALE_DAYS * 86400, why="copy")
        self.world.plan()
        self.assertTold(7, filer.CLOSED, "refused 14 days ago and unchanged since", close=True)
        self.assertEqual(self.world.actions()[7]["comment"], 907)

    def test_a_new_commit_starts_the_fourteen_days_again(self):
        self.world.pr(7)
        self.world.sticky(7, filer.REFUSED, "e" * 40, NOW - 30 * 86400, why="copy")
        self.world.plan()
        self.assertTold(7, filer.FILED)

    def test_a_wait_that_has_not_passed_is_not_looked_at_and_one_that_has_is(self):
        head = self.world.pr(7)
        self.world.sticky(7, filer.QUEUED, head, NOW - 86400, NOW + 3600, "reporter")
        self.world.plan()
        self.assertEqual(self.world.actions(), {})
        world = World(self.world.root.parent / "passed", self.template)
        head = world.pr(7)
        world.sticky(7, filer.QUEUED, head, NOW - 86400, NOW - 60, "reporter")
        world.plan()
        self.assertEqual(world.actions()[7]["state"], filer.FILED)
        self.assertEqual(world.actions()[7]["comment"], 907, "the sticky comment is edited, not a second one posted")

    def test_a_filed_pull_request_still_open_is_closed_again_without_a_word(self):
        head = self.world.pr(7)
        self.world.sticky(7, filer.FILED, head, NOW - 3600)
        self.world.plan()
        action = self.world.actions()[7]
        self.assertEqual((action["state"], action["close"], action["text"]), (filer.FILED, True, None))

    def test_a_report_the_maintainer_filed_is_closed_as_filed(self):
        """codex-compat-admin's `community accept` files a held report through a pull request of its own,
        with the same trailer; the next run finds it filed and closes the sender's pull request."""
        report = sample(failed=True)
        head = self.world.pr(7, report)
        self.world.sticky(7, filer.NEEDS_OWNER, head, NOW - 3 * 86400, why="contradicts")
        self.world.plan()
        self.assertEqual(self.world.actions(), {}, "held, and not looked at again")
        filed = self.world.filed_by_hand(report, reporter_id=507, number=7)
        self.world.plan()
        self.assertTold(7, filer.FILED, "in %s" % filed, close=True)
        self.assertEqual((self.world.out / "red").read_text(encoding="utf-8"), "")

    def test_the_same_wait_is_not_said_twice(self):
        head = self.world.pr(7)
        self.world.sticky(7, filer.QUEUED, head, NOW - 3600, None, "paused")
        self.world.plan(environ={"AUTOFILE": "off"})
        self.assertEqual(self.world.actions(), {})


# ============================================================================== read as data
class MetadataTests(Case):
    """A pull request that cannot be a report is refused from what GitHub says about it, unfetched."""

    def refused_unfetched(self, number, fragment, **options):
        self.world.pr(number, **options)
        self.world.plan()
        self.assertTold(number, filer.REFUSED, fragment)
        self.assertFalse(self.world.fetched(number))

    def test_more_than_one_path(self):
        self.refused_unfetched(7, "changes 2 paths", changed=2)

    def test_more_commits_than_a_report_has(self):
        self.refused_unfetched(7, "more than 20", commits=21)

    def test_a_changed_file(self):
        self.refused_unfetched(7, "changes or removes one", files=[
            {"filename": reader.canonical_path("ExampleUser", VERSION), "status": "modified"}])

    def test_another_folder(self):
        self.refused_unfetched(7, "under the login that opened", files=[
            {"filename": reader.canonical_path("SomeoneElse", VERSION), "status": "added"}])

    def test_a_folder_windows_cannot_hold(self):
        report = sample(login="nul")
        self.refused_unfetched(7, "a name Windows keeps for a device", report=report,
                               path=reader.canonical_path("ExampleUser", VERSION),
                               files=[{"filename": "docs/evidence/community/nul/codex-cli-0.155.0-alpha.9.2.json",
                                       "status": "added"}])
        self.assertIn(filer.ACTIONS[check.RESERVED_NAME], self.world.actions()[7]["text"])

    def test_not_a_report(self):
        self.refused_unfetched(7, "changes nothing under docs/evidence/community/",
                               files=[{"filename": "README.md", "status": "added"}])

    def test_a_head_that_cannot_be_fetched_is_refused_and_the_run_goes_on(self):
        self.world.pr(7, head=False)
        self.world.pr(8, sample(login="ExampleUser2", version="codex-cli 0.153.4"))
        self.world.plan()
        self.assertTold(7, filer.REFUSED, "could not be fetched")
        self.assertIn(filer.ACTIONS["cannot"], self.world.actions()[7]["text"])
        self.assertTold(8, filer.FILED)
        self.assertEqual((self.world.out / "red").read_text(encoding="utf-8"), "")

    def test_a_file_over_one_megabyte_is_never_brought_over(self):
        self.world.pr(7, raw=reader.encode(sample()) + b" " * (reader.MAX_BYTES + 1))
        self.world.plan()
        self.assertTold(7, filer.REFUSED, "larger than 1 MB")
        self.assertTrue(self.world.fetched(7))

    def test_a_version_in_another_spelling_is_refused(self):
        spellings = ("codex-cli 00.155.0", "codex-cli 0.155.00", "codex-cli 0.155.0-alpha.09.2",
                     "codex-cli 0.155.0-alpha.9.0")
        for number, version in enumerate(spellings, 10):
            self.world.pr(number, sample(login="User%d" % number, version=version))
        self.world.plan()
        for number, version in enumerate(spellings, 10):
            with self.subTest(version):
                self.assertTold(number, filer.REFUSED, "no leading zero")


class HostileTests(Case):
    """Nothing a sender wrote reaches a comment: every text is fixed, and a value in it is one that
    matched its pattern."""

    def test_hostile_values_never_reach_a_text(self):
        values = [HOSTILE, "](http://x)", "a\nb", "\"quoted\" back\\slash", "<!-- x -->", "con", "x" * 300]
        number = 10
        for value in values:
            # Every free field at once, in the file; then the same value as the file's name.
            report = sample(login="User%d" % number)
            report.update(codex_version=value, note=value, recorded_by=value)
            report["records"][0]["state"] = value
            report["reporter"]["windows"] = value
            self.world.pr(number, report, path=reader.canonical_path("User%d" % number, VERSION))
            number += 1
            self.world.pr(number, sample(login="User%d" % number), files=[
                {"filename": "docs/evidence/community/User%d/%s.json" % (number, value), "status": "added"}])
            number += 1
        with mock.patch.object(filer, "MAX_LOOKED", 100):
            self.world.plan()
        texts = [action["text"] for action in self.world.actions().values() if action["text"]]
        self.assertEqual(len(texts), len(values) * 2)
        for text in texts:
            first, _newline, rest = text.partition("\n")
            self.assertIsNotNone(filer.MARKER.fullmatch(first))
            filer.clean(rest)
            for value in values:
                if len(value) > 3:
                    self.assertNotIn(value, rest)
            self.assertNotIn("::", rest)
            self.assertNotIn("@", rest)
            self.assertTrue(rest.isascii())

    def test_a_hostile_survey_line_is_dropped(self):
        self.world.pulls.append({"number": 7, "draft": False, "created_at": OLD, "head_sha": "a" * 40,
                                 "head_ref": "compat-report/x", "user_id": 1, "login": HOSTILE, "type": "User",
                                 "association": "NONE"})
        self.world.pulls.append({"number": "8; rm -rf /", "draft": False, "created_at": OLD, "head_sha": "a" * 40,
                                 "head_ref": "compat-report/x", "user_id": 1, "login": "ok", "type": "User",
                                 "association": "NONE"})
        self.world.survey()
        self.assertEqual(filer.Survey(self.world.queue).pulls, [])

    def test_a_marker_is_read_only_when_it_is_exactly_the_filers(self):
        good = filer.marker(filer.QUEUED, "a" * 40, NOW, NOW + 60, "reporter")
        self.assertEqual(filer.parse_marker(good)["why"], "reporter")
        for bad in (good.replace("queued", "merged"), good + " extra", good.replace("a" * 40, "a" * 39),
                    "<!-- community-file state=filed -->", HOSTILE):
            self.assertIsNone(filer.parse_marker(bad))

    def test_every_fixed_text_is_one_a_comment_may_carry(self):
        for text in list(filer.TEXTS.values()) + list(filer.ACTIONS.values()) + list(filer.WAITING.values()):
            filer.clean(text.replace("%s", "x").replace("%d", "1"))


# ============================================================================== dev
class DevTests(Case):
    def dev_merge(self):
        line = (self.world.out / "dev").read_text(encoding="utf-8").split()
        return line[1] if line else None

    def test_dev_takes_the_filing_and_keeps_its_korean_documents(self):
        self.world.pr(7)
        self.world.plan()
        merge = self.dev_merge()
        self.assertIsNotNone(merge)
        checkout = self.world.checkout
        dev = git(checkout, "rev-parse", "refs/remotes/origin/dev")
        self.assertEqual(git(checkout, "rev-list", "--parents", "-n", "1", merge).split(),
                         [merge, dev, self.world.chain()[-1]])
        changed = git(checkout, "diff", "--name-only", dev, merge).splitlines()
        self.assertTrue(changed and all(filer.writable(path) for path in changed))
        self.assertFalse(any(path.endswith(".ko.md") for path in changed))
        for path in changed:
            self.assertEqual(git(checkout, "rev-parse", "%s:%s" % (merge, path)),
                             git(checkout, "rev-parse", "%s:%s" % (self.world.chain()[-1], path)))
        self.assertEqual(self.world.show(merge, "docs/GUIDE.ko.md"), "# 안내\n".encode("utf-8"))

    def test_dev_that_changed_a_file_the_filer_writes_is_left_alone(self):
        self.world.on_dev({filer.README: b"# edited on dev\n"})
        self.world.pr(7)
        planner = self.world.plan()
        self.assertEqual(len(self.world.chain()), 1)
        self.assertIsNone(self.dev_merge())
        self.assertTrue(any("dev changed a file the filer writes" in line for line in planner.summary))

    def test_main_that_changed_more_than_the_filer_writes_leaves_dev_to_promote(self):
        self.world.on_main({"README.md": b"# Tool, promoted\n"})
        self.world.pr(7)
        planner = self.world.plan()
        self.assertEqual(len(self.world.chain()), 1)
        self.assertIsNone(self.dev_merge())
        self.assertTrue(any("promote.py into-dev" in line for line in planner.summary))

    def test_red_dev_tests_still_file_to_main_and_leave_dev(self):
        self.world.pr(7)
        planner = self.world.plan(run_tests=lambda tree: not (tree / "docs" / "GUIDE.ko.md").exists())
        self.assertEqual(len(self.world.chain()), 1)
        self.assertIsNone(self.dev_merge())
        self.assertTrue(any("its own tests do not pass" in line for line in planner.summary))
        self.assertEqual((self.world.out / "red").read_text(encoding="utf-8"), "")

    def test_dev_is_healed_with_no_report_waiting(self):
        self.world.filed_by_hand(sample(), reporter_id=507, number=7)
        self.world.plan()
        self.assertEqual(self.world.chain(), [])
        self.assertIsNotNone(self.dev_merge())
        self.assertTrue((self.world.out / "plan.bundle").is_file())


# ============================================================================== the write step, run
@unittest.skipUnless(git_bash(), "no bash to run the workflow's step with")
class WriteStepTests(unittest.TestCase):
    """The workflow's own write step, run against the fake GitHub on the plan the planner made.

    One report from User7 is planned once for the class; each test writes from a copy of that."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.template = World(Path(cls.folder.name) / "template")
        cls.planned = World(Path(cls.folder.name) / "planned", cls.template)
        cls.planned.pr(7, sample(login="User7"))
        cls.planned.plan()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.world = self.planned.copy_to(self.scratch / "world")

    def fresh(self):
        return World(self.scratch / "fresh", self.template)

    def test_it_files_what_was_tested_tells_the_sender_and_brings_dev_along(self):
        before = self.world.main()
        dev_before = git(self.world.origin, "rev-parse", "refs/heads/dev")
        planned = self.world.chain()[-1]
        code, said = self.world.write()
        self.assertEqual(code, 0, said)
        main = self.world.main()
        self.assertNotEqual(main, planned, "GitHub makes its own commit")
        self.assertEqual(git(self.world.origin, "rev-parse", main + "^{tree}"),
                         git(self.world.checkout, "rev-parse", planned + "^{tree}"))
        self.assertEqual(git(self.world.origin, "rev-parse", main + "^"), before)
        self.assertEqual(git(self.world.origin, "cat-file", "commit", main).split("\n\n", 1)[1],
                         filer.commit_message("User7", VERSION, 507, 7).rstrip("\n"))
        dev = git(self.world.origin, "rev-parse", "refs/heads/dev")
        self.assertEqual(git(self.world.origin, "rev-list", "--parents", "-n", "1", dev).split(), [dev, dev_before, main])
        self.assertEqual(git(self.world.origin, "diff", "--name-only", dev_before, dev).splitlines(),
                         git(self.world.origin, "diff", "--name-only", before, main).splitlines())
        comments = [c for c in self.world.github["comments"].values() if c["issue"] == "7"]
        self.assertEqual(len(comments), 1)
        self.assertIn("in %s, thank you" % main, comments[0]["body"])
        self.assertNotIn("{commit}", comments[0]["body"])
        self.assertEqual(self.world.github["pulls"]["7"]["state"], "closed")
        self.assertEqual(self.world.github["dispatches"], [])

    def test_a_paused_switch_at_write_time_writes_nothing(self):
        before = self.world.main()
        code, said = self.world.write({"AUTOFILE": "Off"})
        self.assertEqual(code, 0, said)
        self.assertEqual(self.world.main(), before)
        self.assertEqual(self.world.github["comments"], {})
        self.assertEqual(self.world.github["calls"], [])

    def test_a_lost_race_writes_nothing_and_asks_for_another_try(self):
        moved = self.world.on_main({"README.md": b"# someone else\n"})
        code, said = self.world.write()
        self.assertEqual(code, 0, said)
        self.assertEqual(self.world.main(), moved)
        self.assertEqual(self.world.github["dispatches"], [["community-file.yml", "main", "attempt=2"]])
        self.assertEqual(self.world.github["comments"], {})
        code, said = self.world.write({"ATTEMPT": "3"})
        self.assertEqual(code, 1, said)
        self.assertIn("three tries", said)

    def test_main_moved_backwards_is_a_lost_race_too(self):
        world = self.fresh()
        world.on_main({"README.md": b"# a commit the owner drops\n"})
        world.pr(7, sample(login="User7"))
        world.plan()
        git(world.origin, "update-ref", "refs/heads/main", world.base)
        code, said = world.write()
        self.assertEqual(code, 0, said)
        self.assertEqual(world.main(), world.base)
        self.assertEqual(world.github["dispatches"][0][:2], ["community-file.yml", "main"])

    def replace_plan(self, made, world=None):
        """The plan made to name one commit that is not what the filer makes, with its bundle."""
        world = world or self.world
        main = git(world.checkout, "rev-parse", "refs/remotes/origin/main")
        (world.out / "chain").write_bytes(made.encode("ascii") + b"\n")
        (world.out / "dev").write_bytes(b"")
        git(world.checkout, "update-ref", "refs/plan/main", made)
        (world.out / "plan.bundle").unlink()
        git(world.checkout, "bundle", "create", str(world.out / "plan.bundle"), "refs/plan/main", "^" + main)

    def tamper(self, files, message=None, world=None):
        world = world or self.world
        main = git(world.checkout, "rev-parse", "refs/remotes/origin/main")
        self.replace_plan(commit(world.checkout, main, files, message or filer.commit_message("User7", VERSION, 507, 7)),
                          world)

    def assertRefusedWrite(self, fragment, world=None):
        world = world or self.world
        before = world.main()
        code, said = world.write()
        self.assertEqual(code, 1, said)
        self.assertIn(fragment, said)
        self.assertEqual(world.main(), before)
        self.assertEqual(world.github["moves"], [])
        self.assertEqual(world.github["comments"], {})

    def test_a_commit_touching_anything_else_is_refused(self):
        path = reader.canonical_path("User7", VERSION)
        self.tamper({path: reader.encode(sample(login="User7")), "README.md": b"# taken over\n"})
        self.assertRefusedWrite("touches a path the filer does not write")

    def test_a_commit_that_changes_a_filed_report_is_refused(self):
        world = self.fresh()
        world.filed_by_hand(sample(login="User7"), reporter_id=507, number=7)
        world.pr(8, sample(login="User8"))
        world.plan()
        self.tamper({reader.canonical_path("User7", VERSION): b"{}\n",
                     reader.canonical_path("User8", VERSION): reader.encode(sample(login="User8"))},
                    filer.commit_message("User8", VERSION, 508, 8), world)
        self.assertRefusedWrite("adds exactly one new report", world)

    def test_a_folder_no_windows_checkout_can_hold_is_refused(self):
        """Made with mktree, which git for Windows lets make a tree its index would refuse."""
        checkout = self.world.checkout
        main = git(checkout, "rev-parse", "refs/remotes/origin/main")
        blob = git(checkout, "hash-object", "-w", "--stdin", data=b"{}\n")

        def put(tree, parts):
            """`tree` with the file at `parts` set to that blob, one level at a time."""
            entries = {line.split("\t", 1)[1]: line for line in git(checkout, "ls-tree", tree).splitlines()} \
                if tree else {}
            name = parts[0]
            if len(parts) == 1:
                entries[name] = "100644 blob %s\t%s" % (blob, name)
            else:
                inner = entries[name].split()[2] if name in entries else None
                entries[name] = "040000 tree %s\t%s" % (put(inner, parts[1:]), name)
            return git(checkout, "mktree", data="".join(line + "\n" for line in entries.values()).encode("utf-8"))

        tree = put(main + "^{tree}", "docs/evidence/community/nul/codex-cli-0.155.0-alpha.9.2.json".split("/"))
        self.replace_plan(git(checkout, "commit-tree", tree, "-p", main, "-F", "-",
                              data=filer.commit_message("nul", VERSION, 507, 7).encode("utf-8")))
        self.assertRefusedWrite("no Windows checkout can hold")

    def test_a_message_that_is_not_the_filers_is_refused(self):
        path = reader.canonical_path("User7", VERSION)
        self.tamper({path: reader.encode(sample(login="User7"))},
                    filer.commit_message("User7", VERSION, 507, 7) + "\nCo-authored-by: someone\n")
        self.assertRefusedWrite("message is not the filer's")

    def test_a_blob_github_stores_otherwise_moves_nothing(self):
        self.world.github["break"] = "blobs"
        self.assertRefusedWrite("stored a file other than the one tested")

    def test_a_text_with_a_mention_is_not_posted(self):
        text = self.world.out / "texts" / "7.md"
        text.write_bytes(text.read_bytes() + b"Thanks @someone\n")
        code, said = self.world.write()
        self.assertEqual(code, 1, said)
        self.assertIn("holds something a text may not", said)
        self.assertEqual(self.world.github["comments"], {})

    def test_a_comment_to_change_must_be_the_filers_on_that_pull_request(self):
        world = self.fresh()
        head = world.pr(7, sample(login="User7"))
        world.sticky(7, filer.QUEUED, head, NOW - 86400, NOW - 60, "reporter", comment_id=950)
        world.plan()
        world.github["comments"]["950"]["issue"] = "8"
        code, said = world.write()
        self.assertEqual(code, 1, said)
        self.assertIn("not the filer's on that pull request", said)

    def test_a_pull_request_that_is_no_longer_an_open_report_is_left_alone(self):
        self.world.github["pulls"]["7"]["state"] = "closed"
        code, said = self.world.write()
        self.assertEqual(code, 0, said)
        self.assertIn("#7: not an open report pull request now; left alone", said)
        self.assertEqual(self.world.github["comments"], {})

    def test_the_daily_run_asks_for_tests_only_where_none_runs_or_waits(self):
        self.world.runs = [{"status": "in_progress", "head_sha": "a" * 40, "event": "push", "head_branch": "dev"}]
        code, said = self.world.write({"EVENT": "schedule"})
        self.assertEqual(code, 0, said)
        self.assertEqual(self.world.github["dispatches"], [["test.yml", "main"]])

    def test_the_plan_is_read_as_data(self):
        (self.world.out / "actions").write_bytes(b"7; true filed close 0 post\n")
        code, said = self.world.write()
        self.assertEqual(code, 1, said)
        self.assertIn("not a state", said)


# ============================================================================== what holds the code
class WritableTests(unittest.TestCase):
    def test_what_the_planner_writes_is_writable_and_nothing_else_is(self):
        for path in (reader.canonical_path("ExampleUser", VERSION), reader.canonical_path("a", "codex-cli 0.1.0"),
                     reader.canonical_path("a-b-c" + "d" * 34, "codex-cli 999999.999999.999999"),
                     filer.INDEX, filer.README, filer.COUNTS):
            self.assertTrue(filer.writable(path), path)
        for path in (filer.WITHDRAWN, "README.md", filer.COMPAT_DATA, ".github/workflows/test.yml",
                     "docs/evidence/community/ExampleUser/codex-cli-00.1.0.json",
                     "docs/evidence/community/ExampleUser/codex-cli-0.1.0-alpha.9.0.json",
                     "docs/evidence/community/-x/codex-cli-0.1.0.json",
                     "docs/evidence/community/a--b/codex-cli-0.1.0.json",
                     "docs/evidence/community/" + "a" * 40 + "/codex-cli-0.1.0.json",
                     "docs/evidence/community/ExampleUser/codex-cli-0.1.0.json\n",
                     "docs/evidence/community/ExampleUser/../codex-cli-0.1.0.json",
                     "docs/evidence/Community/ExampleUser/codex-cli-0.1.0.json"):
            self.assertFalse(filer.writable(path), path)
        for name in sorted(reader.RESERVED) + ["NUL", "Con", "cOm1", "LPT9"]:
            self.assertFalse(filer.writable("docs/evidence/community/%s/codex-cli-0.1.0.json" % name), name)

    def test_every_canonical_version_names_a_writable_file(self):
        for version in ("codex-cli 0.155.0", "codex-cli 0.155.0-alpha.9.2", "codex-cli 0.155.0-alpha.0",
                        "codex-cli 10.0.1-alpha.16.4"):
            self.assertTrue(reader.engine_version(version), version)
            self.assertTrue(filer.writable(reader.canonical_path("ExampleUser", version)), version)

    @unittest.skipUnless(os.name == "nt", "a Windows checkout is the point")
    def test_every_writable_path_checks_out_on_windows_and_a_reserved_name_does_not(self):
        """git for Windows refuses a device name as a folder, so one such file would stop every checkout
        of main - the tests, the ko sync, the release, and the filer itself."""
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / "repo"
            git(folder, "init", "-q", str(repo))
            blob = git(repo, "hash-object", "-w", "--stdin", data=b"{}\n")

            def tree(paths):
                """A tree built level by level with mktree, which does not ask Windows about names."""
                children = {}
                for path in paths:
                    head, _sep, rest = path.partition("/")
                    children.setdefault(head, []).append(rest)
                lines = []
                for name, rests in sorted(children.items()):
                    if rests == [""]:
                        lines.append("100644 blob %s\t%s" % (blob, name))
                    else:
                        lines.append("040000 tree %s\t%s" % (tree([r for r in rests if r]), name))
                return git(repo, "mktree", data=("\n".join(lines) + "\n").encode("utf-8"))

            def checks_out(paths, name):
                made = git(repo, "commit-tree", tree(paths), "-m", "x")
                return subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach",
                                       str(Path(folder) / name), made], capture_output=True).returncode == 0

            fine = [reader.canonical_path(login, version) for login in ("ExampleUser", "a", "com10", "nul0", "a" * 39)
                    for version in ("codex-cli 0.1.0", "codex-cli 999999.999999.999999-alpha.9.2")]
            fine += [filer.INDEX, filer.README, filer.COUNTS]
            self.assertTrue(all(filer.writable(path) for path in fine))
            self.assertTrue(checks_out(fine, "fine"))
            for number, name in enumerate(("nul", "con", "aux", "prn", "com1", "lpt1", "NUL", "Con")):
                path = "docs/evidence/community/%s/codex-cli-0.1.0.json" % name
                self.assertFalse(filer.writable(path), name)
                self.assertFalse(checks_out([path], "reserved-%d" % number), name)


class WorkflowAgreementTests(unittest.TestCase):
    """What the write step and the planner must say alike, they say word for word."""

    def setUp(self):
        self.write = step_script("Write to GitHub")

    def test_the_paths_and_names_are_the_planners(self):
        self.assertIn("report_add='%s'" % filer.REPORT_ADD, self.write)
        self.assertIn("regenerated='%s'" % filer.REGENERATED, self.write)
        self.assertIn("reserved='%s'" % filer.RESERVED_LOGIN, self.write)
        self.assertIn('[ "${#login}" -le %d ]' % filer.MAX_LOGIN, self.write)
        self.assertIn('-le %d ] || fail "a text is missing or too long"' % filer.MAX_TEXT, self.write)

    def test_the_messages_are_the_planners(self):
        self.assertIn("commit_body='%s'" % filer.COMMIT_BODY, self.write)
        subject, _blank, body = filer.DEV_MESSAGE.rstrip("\n").partition("\n\n")
        self.assertIn("dev_subject='%s'" % subject, self.write)
        self.assertIn("dev_body='%s'" % body, self.write)
        self.assertIn(filer.COMMIT_SUBJECT.replace("%s", "%s", 2), self.write)
        self.assertIn("Community-report: %s %s\\nCommunity-reporter-id: %s\\nPull-request: #%s\\n", self.write)
        self.assertEqual(filer.marker(filer.QUEUED, "a" * 40, NOW, NOW, "x")[:24], "<!-- community-file stat")
        self.assertIn("marker='^<!-- community-file state=(filed|queued|refused|needs-owner|closed) ", self.write)

    def test_the_numbers_are_the_planners(self):
        read = step_script("Read those closer")
        self.assertIn('[ "$looked" -le %d ] || break' % filer.MAX_LOOKED, read)
        self.assertIn('[ "${#chain[@]}" -le %d ]' % filer.MAX_LOOKED, self.write)
        for code, said in filer.RED.items():
            self.assertIn('%s) said="%s" ;;' % (code, said), step_script("Tell the maintainer what needs a person"))

    def test_every_step_that_asks_github_saves_what_the_survey_reads(self):
        queue = step_script("Read the queue")
        for name in ("rate", "pulls-$page.jsonl", "comments-$page.jsonl", "runs.jsonl"):
            self.assertIn('"$q/%s"' % name, queue)
        read = step_script("Read those closer")
        for name in ("pull-$number.json", "files-$number.json", "user-$user.json", "sticky-$number.json"):
            self.assertIn('"$q/%s"' % name, read)


class PlannerCodeTests(unittest.TestCase):
    """build/community_file.py reads git as data and starts nothing else but the fixed tests."""

    def setUp(self):
        self.source = (ROOT / "build" / "community_file.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_no_network_no_import_machinery_no_exec(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, ("exec", "eval", "compile", "__import__"))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] + [getattr(node, "module", None) or ""]
                for name in names:
                    self.assertNotIn(name.split(".")[0], ("importlib", "runpy", "pickle", "marshal", "shlex", "urllib",
                                                          "http", "socket", "requests", "ssl", "ftplib"))
            if isinstance(node, ast.keyword) and node.arg == "shell":
                self.assertIs(getattr(node.value, "value", None), False)

    def test_every_process_is_git_or_the_fixed_tests(self):
        calls = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                 and node.func.value.id in ("subprocess", "os")]
        self.assertEqual(sorted({call.func.attr for call in calls if call.func.value.id == "os"}), ["getcwd"])
        calls = [call for call in calls if call.func.value.id == "subprocess"]
        self.assertEqual([call.func.attr for call in calls], ["run", "run"])
        first, second = (call.args[0] for call in calls)
        self.assertEqual(getattr(first.elts[0], "value", None), "git")
        self.assertEqual(ast.unparse(second), "[sys.executable, '-m', 'unittest', *FIXED_MODULES]")
        self.assertNotIn("os.system", self.source)
        self.assertNotIn("Popen", self.source)

    def test_it_never_reads_a_token(self):
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "secrets"):
            self.assertNotIn(name, self.source)

    def test_it_writes_only_through_one_helper_that_stays_in_its_folder(self):
        writers = [node for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)
                   and node.attr in ("write_text", "write_bytes", "open", "mkdir", "unlink", "rmtree", "touch")]
        places = []
        for function in ast.walk(self.tree):
            if isinstance(function, ast.FunctionDef):
                for node in ast.walk(function):
                    if node in writers:
                        places.append((function.name, node.attr))
        self.assertEqual(sorted(set(places)), sorted({("_write", "write_bytes"), ("write", "mkdir"),
                                                      ("write", "rmtree"), ("worktree", "rmtree"),
                                                      ("drop_worktree", "rmtree"), ("main", "mkdir")}))
        self.assertNotIn("open(", self.source)

    def test_the_helper_refuses_a_file_outside_its_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            filer._write(Path(folder), "inside", "x")
            for name in ("../outside", "/outside"):
                with self.assertRaises(ValueError):
                    filer._write(Path(folder) / "sub", name, "x")


class FixedModulesTests(unittest.TestCase):
    """Every test module that names a file a filing writes runs before the write, or says why not."""

    # Modules that name those files but read their own copies, never the tree being filed.
    OWN_COPIES = {
        "test_compat_surfaces": "points reported.BUNDLED at counts files it writes itself",
        "test_gui_compat": "reads the frozen stand-in (tests/frozen_registry.py)",
        "test_screenshots": "reads the frozen stand-in (tests/frozen_registry.py)",
        "test_wire_types": "writes its own reported.json",
        "test_community_file": "builds its own scratch world",
        "test_workflow_privilege": "reads the workflows, not the data",
    }
    # The files, the reader that writes them, and the one module that reads the counts in the product.
    NAMES = ("reported.json", "evidence/community", "reader.COMMUNITY", "community_report",
             "compat import reported", "reported as compat_reported", "reported.BUNDLED")

    def test_the_list_is_complete(self):
        fixed = {name.split(".", 1)[1] for name in filer.FIXED_MODULES}
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            text = path.read_text(encoding="utf-8")
            if any(name in text for name in self.NAMES):
                with self.subTest(path.name):
                    self.assertTrue(path.stem in fixed or path.stem in self.OWN_COPIES,
                                    "%s names a file the filer writes: add it to FIXED_MODULES, or to "
                                    "OWN_COPIES with the reason it reads its own copy" % path.name)

    def test_every_fixed_module_exists(self):
        for name in filer.FIXED_MODULES:
            self.assertTrue((ROOT / (name.replace(".", "/") + ".py")).is_file(), name)


if __name__ == "__main__":
    unittest.main()
