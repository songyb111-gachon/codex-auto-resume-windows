"""The check a compatibility report's pull request runs (build/community_check.py).

Each rule is tried on a scratch repository that plays the base and the pull request's head, because
the check's whole contract is what it does with git: it reads the head's commits as data, with
plumbing, and never checks out, imports or runs any of it. So beside the rules, the tests hold that
a run leaves the working tree and HEAD exactly as they were, that an oversized file is refused
before its bytes are read, and that a hostile file name is never printed as it is.
"""
from __future__ import annotations

import calendar
import contextlib
import io
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
import community_report as reader  # noqa: E402

SAMPLE = ROOT / "tests" / "fixtures" / "community" / "codex-cli-0.155.0-alpha.9.2.json"
NOW = calendar.timegm((2026, 9, 25, 0, 0, 0))
VERSION = "codex-cli 0.155.0-alpha.9.2"
HOSTILE = "::error::pwned%0A"


def sample(login="ExampleUser", version=VERSION, records=None) -> dict:
    report = json.loads(SAMPLE.read_text(encoding="utf-8"))
    report["reporter"]["github_login"] = login
    report["codex_version"] = version
    if records is not None:
        report["records"] = records
        for entry in report["capabilities"].values():
            entry.update(confirmed=0, missed=0, last_confirmed=None, level=None)
        report["verdict"] = "NONE"
        report = reader.recompute(report)
    return report


def path_of(report) -> str:
    return reader.canonical_path(report["reporter"]["github_login"], report["codex_version"])


class Scratch:
    """A repository with a base on main, tagged as one release, and branches for pull requests."""

    def __init__(self, root: Path, template=None):
        self.root = root
        if template is not None:
            # A copy of one built repository: the same commits, without building them again.
            shutil.copytree(template.root, root)
            self.start = template.start
            return
        root.mkdir()
        hooks = root.parent / (root.name + "-nohooks")
        hooks.mkdir()
        self.git("init", "-q", "-b", "main")
        for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("core.autocrlf", "false"),
                           ("commit.gpgsign", "false"), ("tag.gpgsign", "false"), ("core.hooksPath", str(hooks))):
            self.git("config", key, value)
        self.write({"README.md": b"# Tool\n"})
        self.start = self.commit("start")
        self.git("tag", "v0.6.9")

    def git(self, *args: str) -> str:
        environment = {"GIT_COMMITTER_DATE": "2026-09-20T00:00:00Z", "GIT_AUTHOR_DATE": "2026-09-20T00:00:00Z",
                       "GIT_CONFIG_NOSYSTEM": "1"}
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                              env=dict(os.environ, **environment))
        if done.returncode != 0:
            raise AssertionError("git %s: %s" % (" ".join(args), done.stderr.decode("utf-8", "replace")))
        return done.stdout.decode("utf-8")

    def write(self, files: dict) -> None:
        for name, data in files.items():
            path = self.root / name
            if data is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def on(self, branch: str, start: str, files: dict, message="change") -> str:
        """A commit on `branch` from `start`, back on main after."""
        self.git("checkout", "-q", "-B", branch, start)
        self.write(files)
        made = self.commit(message)
        self.git("checkout", "-q", "main")
        return made

    def main(self, files: dict, message="filed") -> str:
        self.write(files)
        return self.commit(message)


def report_bytes(report) -> bytes:
    return reader.encode(report)


class CheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.template = Scratch(Path(cls.folder.name) / "template")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.repo = Scratch(Path(scratch.name) / "repo", self.template)
        self.git = check.Git(self.repo.root)

    def judge(self, head, *, author="ExampleUser", association="CONTRIBUTOR", base=None):
        base = base or self.repo.git("rev-parse", "main").strip()
        return check.judge(self.git, base=base, head=head, author=author, association=association, now=NOW)

    def report_pr(self, report=None, *, path=None, start=None, more=None):
        report = report or sample()
        files = {path or path_of(report): report_bytes(report)}
        files.update(more or {})
        return self.repo.on("pr", start or self.repo.git("rev-parse", "main").strip(), files)

    def assertRefused(self, answer, fragment):
        verdict, lines = answer
        self.assertEqual(verdict, check.REFUSES, lines)
        self.assertTrue(any(fragment in line for line in lines), (fragment, lines))

    def assertAccepted(self, answer):
        verdict, lines = answer
        self.assertEqual(verdict, check.ACCEPTED, lines)

    # ---------------------------------------------------------------- what is not a report
    def test_a_pull_request_that_touches_no_report_is_not_one(self):
        head = self.repo.on("pr", self.repo.start, {"README.md": b"# Tool, better\n"})
        verdict, lines = self.judge(head)
        self.assertEqual(verdict, check.ACCEPTED)
        self.assertIn("not a report", lines[0])

    # ---------------------------------------------------------------- the one file
    def test_a_report_as_the_reporter_sends_it_is_accepted(self):
        verdict, lines = self.judge(self.report_pr())
        self.assertEqual(verdict, check.ACCEPTED, lines)
        self.assertIn("a report for %s from ExampleUser" % VERSION, lines)

    def test_exactly_one_path(self):
        self.assertRefused(self.judge(self.report_pr(more={"README.md": b"changed\n"})), "exactly one file")
        second = sample(version="codex-cli 0.153.4")
        self.assertRefused(self.judge(self.report_pr(more={path_of(second): report_bytes(second)})),
                           "exactly one file")

    def test_reports_are_add_only(self):
        self.repo.main({path_of(sample()): report_bytes(sample())})
        changed = sample()
        changed["records"] = changed["records"][:2]
        self.assertRefused(self.judge(self.report_pr(changed)), "add-only")
        removed = self.repo.on("pr", "main", {path_of(sample()): None})
        self.assertRefused(self.judge(removed), "add-only")

    def test_an_ordinary_file_only(self):
        self.repo.git("checkout", "-q", "-B", "pr", "main")
        target = self.repo.root / "target.txt"
        target.write_bytes(b"../../../README.md")
        blob = self.repo.git("hash-object", "-w", str(target)).strip()
        target.unlink()
        self.repo.git("update-index", "--add", "--cacheinfo", "120000,%s,%s" % (blob, path_of(sample())))
        self.repo.git("commit", "-q", "-m", "a link")
        head = self.repo.git("rev-parse", "HEAD").strip()
        self.repo.git("checkout", "-q", "-f", "main")
        self.assertRefused(self.judge(head), "not a link or a submodule")

    def test_under_the_login_that_opened_it(self):
        self.assertRefused(self.judge(self.report_pr(), author="SomeoneElse"), "under the login that opened")
        self.assertRefused(self.judge(self.report_pr(path=path_of(sample()).replace("ExampleUser", "exampleuser"))),
                           "under the login that opened")
        self.assertRefused(self.judge(self.report_pr(path="docs/evidence/community/ExampleUser/report.json")),
                           "under the login that opened")
        self.assertRefused(self.judge(self.report_pr(path="Docs/Evidence/Community/ExampleUser/"
                                                         "codex-cli-0.155.0-alpha.9.2.json")),
                           "under the login that opened")

    def test_named_for_its_own_version(self):
        self.assertRefused(self.judge(self.report_pr(path="docs/evidence/community/ExampleUser/codex-cli-0.153.4.json")),
                           "named for its own codex_version")

    def test_the_sender_is_the_login_that_opened_it(self):
        other = sample(login="SomeoneElse")
        self.assertRefused(self.judge(self.report_pr(other, path=path_of(sample()))), "not the login that opened")

    def test_no_folder_differing_only_in_letter_case(self):
        filed = sample(login="exampleuser", version="codex-cli 0.153.4")
        self.repo.main({path_of(filed): report_bytes(reader.filed_copy(filed))})
        self.assertRefused(self.judge(self.report_pr()), "only in letter case")

    def test_nothing_already_filed_at_the_base_as_well_as_the_merge_base(self):
        """The maintainer's tool files a report at the same path, so absent where the pull request
        left main is not enough: it has to be absent from main as it is now."""
        start = self.repo.git("rev-parse", "main").strip()
        head = self.report_pr(start=start)
        self.repo.main({path_of(sample()): report_bytes(reader.filed_copy(sample()))})
        self.assertRefused(self.judge(head), "already filed")

    def test_nothing_already_filed_on_main_either(self):
        head = self.report_pr()
        filed = self.repo.on("elsewhere", "main", {path_of(sample()): report_bytes(reader.filed_copy(sample()))})
        self.repo.git("update-ref", check.MAIN, filed)
        self.assertRefused(self.judge(head), "already filed")

    def test_an_oversized_file_is_refused_before_it_is_read(self):
        big = report_bytes(sample()) + b" " * (reader.MAX_BYTES + 1)
        head = self.repo.on("pr", "main", {path_of(sample()): big})
        with mock.patch.object(check.Git, "blob", side_effect=AssertionError("read")):
            self.assertRefused(self.judge(head), "larger than 1 MB")

    def test_what_the_reader_refuses_is_refused(self):
        broken = sample()
        broken["records"][0]["state"] = "exploded"
        self.assertRefused(self.judge(self.report_pr(broken)), "records[1].state")
        unreleased = sample()
        unreleased["reporter"]["product_version"] = "0.6.8"
        self.assertRefused(self.judge(self.report_pr(unreleased)), "not one of this repository's releases")

    def test_what_a_report_claims_beyond_its_records_is_recomputed_and_said(self):
        claimed = sample()
        claimed["capabilities"]["usage_probe"]["level"] = "VERIFIED"
        verdict, lines = self.judge(self.report_pr(claimed))
        self.assertEqual(verdict, check.ACCEPTED, lines)
        self.assertIn("recomputed: capabilities.usage_probe: VERIFIED is more than its records show; kept as null",
                      lines)

    # ---------------------------------------------------------------- copies
    def test_a_copy_under_another_login_is_refused(self):
        other = sample(login="ExampleUser2")
        self.repo.main({path_of(other): report_bytes(reader.filed_copy(other))})
        self.assertRefused(self.judge(self.report_pr()), "same, in order")

    def test_two_reports_with_no_records_are_both_accepted(self):
        other = sample(login="ExampleUser2", records=[])
        self.repo.main({path_of(other): report_bytes(reader.filed_copy(other))})
        self.assertAccepted(self.judge(self.report_pr(sample(records=[]))))

    def test_the_same_records_under_another_version_are_not_a_copy(self):
        other = sample(login="ExampleUser2", version="codex-cli 0.153.4")
        self.repo.main({path_of(other): report_bytes(reader.filed_copy(other))})
        self.assertAccepted(self.judge(self.report_pr()))

    def test_one_record_changed_is_not_a_copy(self):
        other = sample(login="ExampleUser2")
        self.repo.main({path_of(other): report_bytes(reader.filed_copy(other))})
        mine = sample()
        mine["records"][3]["detected_at"] = "2026-09-22T17:27:31Z"
        self.assertAccepted(self.judge(self.report_pr(mine)))

    # ---------------------------------------------------------------- the owner's filing
    def owner_pr(self, files):
        return self.repo.on("filing", "main", files)

    def test_the_owners_filing_is_read_report_by_report(self):
        one, two = reader.filed_copy(sample()), reader.filed_copy(sample(login="ExampleUser2", records=[]))
        index = reader.build_index({path_of(one): one, path_of(two): two}, generated_at=NOW)
        files = {path_of(one): report_bytes(one), path_of(two): report_bytes(two),
                 reader.COMMUNITY + "/index.json": json.dumps(index).encode("ascii"),
                 reader.COMMUNITY + "/README.md": b"# Reported\n",
                 "src/codex_auto_resume/data/reported.json": json.dumps(reader.project(index)).encode("ascii")}
        self.assertAccepted(self.judge(self.owner_pr(files), author="ExampleOwner", association="OWNER"))

    def test_the_owners_filing_holds_the_recomputed_reading(self):
        unfiled = sample()
        unfiled["capabilities"]["usage_probe"]["level"] = "VERIFIED"
        self.assertRefused(self.judge(self.owner_pr({path_of(unfiled): report_bytes(unfiled)}),
                                      author="ExampleOwner", association="OWNER"), "recomputed reading")
        stray = {reader.COMMUNITY + "/notes.txt": b"x\n"}
        self.assertRefused(self.judge(self.owner_pr(stray), author="ExampleOwner", association="OWNER"),
                           "reports, index.json, README.md and withdrawn.json only")

    def test_the_owner_can_withdraw_a_report(self):
        self.repo.main({path_of(sample()): report_bytes(reader.filed_copy(sample()))})
        self.assertAccepted(self.judge(self.owner_pr({path_of(sample()): None}), author="ExampleOwner",
                                       association="OWNER"))

    # ---------------------------------------------------------------- names every checkout can hold
    def test_a_folder_windows_keeps_for_a_device_is_refused(self):
        """git for Windows will not check out docs/evidence/community/nul/..., and one such file on main
        would stop every Windows checkout of it. git for Windows will not make that commit either, so
        the head's one change is handed to the check as git would list it."""
        head = self.report_pr(sample(login="nul"), path=path_of(sample()))
        blob = self.repo.git("rev-parse", "%s:%s" % (head, path_of(sample()))).strip()
        for login in ("nul", "CON", "Aux", "prn", "com1", "LPT9"):
            listed = [("A", "100644", blob, "docs/evidence/community/%s/codex-cli-0.155.0-alpha.9.2.json" % login)]
            with self.subTest(login), mock.patch.object(check.Git, "changes", return_value=listed):
                self.assertRefused(self.judge(head, author=login), "a name Windows keeps for a device")

    def test_a_version_has_one_spelling(self):
        for version in ("codex-cli 00.155.0", "codex-cli 0.155.0-alpha.09.2", "codex-cli 0.155.0-alpha.9.0"):
            with self.subTest(version):
                self.assertRefused(self.judge(self.report_pr(sample(version=version))), "no leading zero")

    def test_every_refusal_carries_a_code_the_filer_can_answer(self):
        import community_file as filer
        self.assertLessEqual(set(check.CODES), set(filer.ACTIONS))
        verdict, coded = check.judge_coded(self.git, base=self.repo.git("rev-parse", "main").strip(),
                                           head=self.report_pr(more={"README.md": b"changed\n"}),
                                           author="ExampleUser", association="CONTRIBUTOR", now=NOW)
        self.assertEqual((verdict, [code for code, _text in coded]), (check.REFUSES, [check.PATHS]))
        verdict, coded = check.judge_coded(self.git, base=self.repo.git("rev-parse", "main").strip(),
                                           head=self.report_pr(), author="ExampleUser",
                                           association="CONTRIBUTOR", now=NOW)
        self.assertEqual((verdict, coded[0][0]), (check.ACCEPTED, check.ACCEPTED_LINE))

    # ---------------------------------------------------------------- what it prints and touches
    def run_main(self, head, **environ):
        environment = {"BASE_SHA": self.repo.git("rev-parse", "main").strip(), "HEAD_SHA": head,
                       "PR_AUTHOR": "ExampleUser", "AUTHOR_ASSOCIATION": "CONTRIBUTOR"}
        environment.update(environ)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), mock.patch.object(check.time, "time", return_value=NOW):
            code = check.main(environment, self.git)
        return code, printed.getvalue()

    def test_a_hostile_file_name_is_never_printed(self):
        head = self.report_pr(path="docs/evidence/community/ExampleUser/%s.json" % HOSTILE.replace(":", "_"))
        code, printed = self.run_main(head)
        self.assertEqual(code, check.REFUSES)
        hostile = sample()
        hostile["codex_version"] = "codex-cli 0.155.0-%s" % "::error::"
        head = self.report_pr(hostile, path=path_of(sample()))
        code, printed_too = self.run_main(head, PR_AUTHOR="ExampleUser")
        self.assertEqual(code, check.REFUSES)
        for text in (printed, printed_too):
            self.assertNotIn("pwned", text)
            self.assertNotIn("::", text)
            self.assertNotIn("%0A", text)

    def test_every_line_it_prints_is_fixed_text(self):
        for line in self.run_main(self.report_pr())[1].splitlines():
            self.assertRegex(line, r"^(community report: (accepted|refused)|  - [ -~]+)$")

    def test_it_needs_what_the_workflow_hands_it(self):
        head = self.report_pr()
        for broken in ({"BASE_SHA": "main"}, {"HEAD_SHA": "refs/pull/1/head"}, {"PR_AUTHOR": HOSTILE},
                       {"AUTHOR_ASSOCIATION": "ADMIN"}, {"PR_AUTHOR": ""}):
            with self.subTest(broken):
                code, printed = self.run_main(head, **broken)
                self.assertEqual(code, check.CANNOT)
                self.assertNotIn("pwned", printed)

    def test_without_this_repositorys_releases_it_judges_nothing(self):
        head = self.report_pr()
        self.repo.git("tag", "-d", "v0.6.9")
        self.assertEqual(self.run_main(head)[0], check.CANNOT)

    def test_a_run_leaves_the_checkout_as_it_was(self):
        head = self.report_pr()
        before = (self.repo.git("rev-parse", "HEAD"), self.repo.git("status", "--porcelain", "--ignored"),
                  sorted(str(path.relative_to(self.repo.root)) for path in self.repo.root.rglob("*")
                         if ".git" not in path.parts))
        self.assertEqual(self.run_main(head)[0], check.ACCEPTED)
        after = (self.repo.git("rev-parse", "HEAD"), self.repo.git("status", "--porcelain", "--ignored"),
                 sorted(str(path.relative_to(self.repo.root)) for path in self.repo.root.rglob("*")
                        if ".git" not in path.parts))
        self.assertEqual(before, after)
        self.assertFalse((self.repo.root / path_of(sample())).exists())


class ShownTests(unittest.TestCase):
    def test_a_value_is_shown_only_when_it_matched(self):
        self.assertEqual(check.shown("ExampleUser", reader.LOGIN.pattern), "ExampleUser")
        for value in (HOSTILE, "a\nb", None, 7, "x" * 40):
            self.assertEqual(check.shown(value, reader.LOGIN.pattern), check.REFUSED)

    def test_the_folder_is_found_however_windows_would_open_it(self):
        """In any letter case, through "." or "..", and with the trailing dots and spaces Windows
        drops: a pull request adding docs/evidence/community./<login>/... from a machine that allows
        the name would otherwise pass as not a report."""
        for path in ("docs/evidence/community/x.json", "Docs/Evidence/COMMUNITY/y/z.json", "docs/evidence/community",
                     None, "docs/evidence/./community/x.json", "docs/evidence/community./x.json",
                     "docs/evidence/Community ./x.json", "docs/evidence/community../y/z.json",
                     "docs/evidence/compat/../community/x.json", "docs\\evidence\\community\\x.json"):
            self.assertTrue(check.touches(path), path)
        for path in ("docs/evidence/communityish/x.json", "docs/evidence/compat/x.json", "README.md",
                     "docs/evidence/community.json", "docs/evidence/compat/community/x.json"):
            self.assertFalse(check.touches(path), path)


if __name__ == "__main__":
    unittest.main()
