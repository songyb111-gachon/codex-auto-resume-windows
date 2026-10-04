"""gh, as the compatibility report runs it (report/github.py): found only in an absolute PATH folder that
is not the current one or the installation's, started by its full path with no shell, no window and no
host but github.com, each in a job that ends with the process, and the file on its standard input.

Every gh here is ghfake's stand-in, which starts nothing and answers as GitHub would. The job object is
held to its promise with real processes - python.exe running a script of these tests' own, never gh -
on Windows only: a process that sleeps, started through the real runner, is gone once the process that
started it ends, and one that does not answer in time is ended, alone.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ghfake  # noqa: E402
from ghfake import LOGIN, MAIN, FakeGh, pull, uploaded  # noqa: E402

from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced.report import github  # noqa: E402
from codex_auto_resume_advanced.report.github import Ready, ReportRefused, Sent, Web  # noqa: E402

VERSION = "codex-cli 0.158.0"
REPORT = {"codex_version": VERSION, "reporter": {"tool_version": "0.6.13-beta"}}
RAW = b'{"format": "a report"}\n'
TARGET = "docs/evidence/community/%s/codex-cli-0.158.0.json" % LOGIN
BRANCH = "compat-report/codex-cli-0.158.0"
FORK = "%s/codex-auto-resume-windows" % LOGIN
EXE = r"C:\Tools\gh\gh.exe"
ADVANCED = HERE.parent / "src"
CORE = HERE.parents[1] / "src"


def check(fake, raw=RAW, login=LOGIN, exe=EXE):
    return github.inspect(raw, REPORT, login, exe=exe, cwd=tempfile.gettempdir(), runner=fake, sleep=lambda _s: None)


def ready(fake, **changes) -> Ready:
    found = check(fake)
    assert isinstance(found, Ready), found
    for name, value in changes.items():
        setattr(found, name, value)
    return found


class FindingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def folder(self, name) -> Path:
        made = self.root / name
        made.mkdir(parents=True)
        (made / "gh.exe").write_bytes(b"MZ")
        return made

    def test_gh_is_the_first_gh_exe_in_an_absolute_folder_on_path(self):
        first, second = self.folder("first"), self.folder("second")
        path = os.pathsep.join([str(self.root / "empty"), str(first), str(second)])
        self.assertEqual(github.find_gh(path), str(first / "gh.exe"))

    def test_never_a_relative_entry_dot_the_current_folder_or_the_installation(self):
        here, home = self.folder("here"), self.root / "home"
        app = self.folder("home/app")
        real = self.folder("real")
        path = os.pathsep.join([".", "here", '"%s"' % here, str(here) + os.sep, str(app), str(home), str(real)])
        with mock.patch("pathlib.Path.cwd", return_value=here):
            self.assertEqual(github.find_gh(path, unsafe=(home,)), str(real / "gh.exe"))
            self.assertIsNone(github.find_gh(os.pathsep.join([".", str(here), str(app)]), unsafe=(home,)))
        self.assertIsNone(github.find_gh(""))

    def test_a_folder_under_the_current_one_is_any_other_folder_as_the_reporter_reads_it(self):
        """The Dashboard started from a terminal in the person's profile: scoop's shims under it are where
        gh is, as codex-compat-reporter's find_gh finds it. Under the installation's home, still never."""
        profile, home = self.root / "profile", self.root / "home"
        shims = self.folder("profile/scoop/shims")
        inside = self.folder("home/tools")
        (profile / "gh.exe").write_bytes(b"MZ")
        with mock.patch("pathlib.Path.cwd", return_value=profile):
            self.assertEqual(github.find_gh(os.pathsep.join([str(profile), str(shims)]), unsafe=(home,)),
                             str(shims / "gh.exe"))
            self.assertIsNone(github.find_gh(os.pathsep.join([str(profile), str(inside)]), unsafe=(home,)))

    def test_gh_runs_without_gh_host_or_gh_repo_and_never_prompts(self):
        with mock.patch.dict(os.environ, {"GH_HOST": "elsewhere.example", "GH_REPO": "someone/else"}):
            found = github.environment()
        self.assertNotIn("GH_HOST", found)
        self.assertNotIn("GH_REPO", found)
        self.assertEqual((found["GH_PROMPT_DISABLED"], found["GH_NO_UPDATE_NOTIFIER"],
                          found["NoDefaultCurrentDirectoryInExePath"]), ("1", "1", "1"))


class CheckTests(unittest.TestCase):
    def test_a_first_report_reads_and_names_every_write_it_would_make(self):
        fake = FakeGh()
        found = check(fake)
        self.assertIsInstance(found, Ready)
        self.assertEqual(found.writes(), [{"kind": "fork_new", "name": FORK}, {"kind": "branch_new", "name": BRANCH},
                                          {"kind": "file", "name": TARGET},
                                          {"kind": "pr", "name": github.REPOSITORY}])
        self.assertEqual((found.who, found.base, found.target, found.branch), (LOGIN, MAIN, TARGET, BRANCH))
        self.assertEqual(fake.writes(), [], "a check only reads")

    def test_every_call_is_pinned_to_github_com_and_never_asks_github_s_search(self):
        fake = FakeGh(fork="fork", branch=True)
        check(fake)
        for words in fake.arguments():
            with self.subTest(words=words):
                if words[0] == "api":
                    self.assertEqual(words[1:3], ["--hostname", "github.com"])
                self.assertNotIn("--author", words)
                self.assertNotIn("search", " ".join(words))
        self.assertEqual(fake.arguments()[0], ["auth", "status", "--hostname", "github.com"])
        listed = [words for words in fake.arguments() if any("pulls?" in word for word in words)]
        self.assertEqual(listed, [["api", "--hostname", "github.com", "-X", "GET",
                                   "repos/%s/pulls?state=open&per_page=100" % github.REPOSITORY, "--paginate"]])

    def test_each_call_is_gh_by_its_path_with_no_window_suspended_and_no_stdin(self):
        fake = FakeGh()
        check(fake)
        for call in fake.calls:
            self.assertEqual(call["argv"][0], EXE)
            self.assertEqual(call["creationflags"] & NO_WINDOW, NO_WINDOW)
            self.assertEqual(call["creationflags"] & github.CREATE_SUSPENDED, github.CREATE_SUSPENDED)
            self.assertIsNone(call["stdin"])
            self.assertEqual(call["timeout"], github.TIMEOUT)
            self.assertNotIn("GH_HOST", call["env"])

    def test_no_gh_is_the_web_with_no_call_at_all(self):
        self.assertEqual(github.inspect(RAW, REPORT, LOGIN, exe=None, cwd=".", runner=None), Web("no_gh"))

    def test_signed_out_or_as_another_login_is_the_web(self):
        self.assertEqual(check(FakeGh(signed_in=False)), Web("gh_signed_out"))
        self.assertEqual(check(FakeGh(who="SomeoneElse")), Web("gh_other_login", who="SomeoneElse"))

    def test_the_same_login_in_other_letters_is_refused(self):
        with self.assertRaises(ReportRefused) as raised:
            check(FakeGh(who="exampleuser"))
        self.assertEqual(raised.exception.code, "gh_spelling")

    def refused(self, code, fake):
        with self.assertRaises(ReportRefused) as raised:
            check(fake)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(fake.writes(), [])

    def test_what_github_says_refuses_it_before_any_write(self):
        self.refused("not_open", FakeGh(open_door=False))
        self.refused("already_filed", FakeGh(filed=True))
        self.refused("pr_open", FakeGh(pulls=[pull(ref="compat-report/codex-cli-0.157.0")]))
        self.refused("fork_named_otherwise", FakeGh(fork="other"))
        self.refused("base_invalid", FakeGh(base="not a sha"))
        self.refused("gh_failed", FakeGh(fail=("repos/%s/pulls" % github.REPOSITORY,)))

    def test_another_person_s_pull_request_is_none_of_this_login_s(self):
        fake = FakeGh(pulls=[pull(login="SomeoneElse"), pull(owner="SomeoneElse"), pull(ref="patch-1")])
        self.assertIsInstance(check(fake), Ready)

    def test_an_open_pull_request_of_this_very_file_is_sent_already_and_of_other_bytes_is_open(self):
        open_one = pull(ref=BRANCH)
        same = FakeGh(fork="fork", branch=True, pulls=[open_one], contents={(TARGET, BRANCH): github.blob_sha(RAW)})
        self.assertEqual(check(same), Sent(open_one["html_url"]))
        self.assertEqual(same.writes(), [])
        other = FakeGh(fork="fork", branch=True, pulls=[open_one],
                       contents={(TARGET, BRANCH): github.blob_sha(b"other bytes\n")})
        self.refused("pr_open", other)

    def test_the_blob_is_git_s(self):
        # `git hash-object` of "hello\n".
        self.assertEqual(github.blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_a_fork_and_a_branch_left_behind_are_kept_and_reset(self):
        found = check(FakeGh(fork="fork", branch=True))
        self.assertEqual([write["kind"] for write in found.writes()], ["fork_kept", "branch_reset", "file", "pr"])

    def test_a_hung_gh_is_its_timeout(self):
        self.refused("gh_timeout", FakeGh(hang=("user",)))


class WriteTests(unittest.TestCase):
    def publish(self, fake, found, before=lambda: None):
        return github.publish(found, RAW, REPORT, before=before, runner=fake, sleep=lambda _s: None)

    def test_the_writes_are_the_ones_shown_in_their_order_and_the_pull_request_is_opened(self):
        fake = FakeGh()
        found = ready(fake)
        url = self.publish(fake, found)
        self.assertEqual(url, "https://github.com/%s/pull/42" % github.REPOSITORY)
        self.assertEqual(found.written, found.writes())
        self.assertEqual(fake.writes(), [("POST", "repos/%s/forks" % github.REPOSITORY),
                                         ("POST", "repos/%s/git/refs" % FORK),
                                         ("PUT", "repos/%s/contents/%s" % (FORK, TARGET)), ("pr", "create")])
        create = fake.arguments()[-1]
        self.assertEqual(create[create.index("--repo") + 1], "github.com/" + github.REPOSITORY)
        self.assertEqual(create[create.index("--head") + 1], "%s:%s" % (LOGIN, BRANCH))
        self.assertEqual(create[create.index("--title") + 1], "Compatibility report: %s (%s)" % (VERSION, LOGIN))
        self.assertIn("Codex Auto Resume 0.6.13-beta (advanced edition)", create[create.index("--body") + 1])

    def test_the_file_goes_on_stdin_and_nothing_is_written_to_disk(self):
        """No temporary file, as the reporter's upload.json was: the temporary folder is one of this test's own,
        empty before and after - this machine's is shared with every other process - and nothing of tempfile is
        asked for anything."""
        fake = FakeGh(fork="fork", branch=True)
        found = ready(fake)
        with tempfile.TemporaryDirectory() as folder:
            asked = AssertionError("a temporary file was asked for")
            with mock.patch.dict(os.environ, {"TEMP": folder, "TMP": folder}),                     mock.patch.object(tempfile, "tempdir", folder),                     mock.patch.object(tempfile, "mkstemp", side_effect=asked),                     mock.patch.object(tempfile, "mkdtemp", side_effect=asked),                     mock.patch.object(tempfile, "NamedTemporaryFile", side_effect=asked):
                self.publish(fake, found)
            self.assertEqual(list(Path(folder).iterdir()), [])
        (put,) = [call for call in fake.calls if "PUT" in call["argv"]]
        self.assertEqual(put["argv"][-2:], ["--input", "-"])
        self.assertEqual(uploaded(put), RAW)
        self.assertEqual(fake.writes()[0], ("PATCH", "repos/%s/git/refs/heads/%s" % (FORK, BRANCH)))

    def test_a_stop_after_the_fork_writes_nothing_more(self):
        fake = FakeGh()
        found = ready(fake)
        asked = []

        def before():
            asked.append(len(found.written))
            if found.written:
                raise ReportRefused("not_on")
        with self.assertRaises(ReportRefused) as raised:
            self.publish(fake, found, before)
        self.assertEqual(raised.exception.code, "not_on")
        self.assertEqual(found.written, [{"kind": "fork_new", "name": FORK}])
        self.assertEqual(fake.writes(), [("POST", "repos/%s/forks" % github.REPOSITORY)])
        self.assertEqual(asked, [0, 1])

    def test_a_fork_github_names_otherwise_or_never_finishes_is_refused(self):
        with self.assertRaises(ReportRefused) as raised:
            fake = FakeGh(made_fork="ExampleUser/codex-auto-resume-windows-1")
            self.publish(fake, ready(fake))
        self.assertEqual(raised.exception.code, "fork_named_otherwise")
        fake = FakeGh(fork_ready_after=github.FORK_WAITS)
        found = ready(fake)
        with self.assertRaises(ReportRefused) as raised:
            self.publish(fake, found)
        self.assertEqual(raised.exception.code, "fork_not_ready")
        self.assertEqual(found.written, [{"kind": "fork_new", "name": FORK}])

    def test_a_pull_request_gh_refuses_because_it_is_open_is_read_as_sent(self):
        fake = FakeGh(fork="fork", branch=True, pr_answer=(1, "", "a pull request already exists"),
                      contents={(TARGET, BRANCH): github.blob_sha(RAW)})
        found = ready(fake)
        fake.pulls = [pull(ref=BRANCH, number=9)]
        self.assertEqual(self.publish(fake, found), "https://github.com/%s/pull/9" % github.REPOSITORY)
        fake = FakeGh(pr_answer=(1, "", "it failed"))
        found = ready(fake)
        with self.assertRaises(ReportRefused) as raised:
            self.publish(fake, found)
        self.assertEqual(raised.exception.code, "gh_failed")
        self.assertEqual([write["kind"] for write in found.written], ["fork_new", "branch_new", "file"])


def _alive(pid) -> bool:
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    handle = k.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
    if not handle:
        return False
    try:
        return k.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102
    finally:
        k.CloseHandle(ctypes.c_void_p(handle))


def _gone(pid, seconds=10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


SLEEPER = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(120)"
# A stand-in for the Dashboard's service: it starts a sleeper through the real runner, on a thread, and
# lives until its standard input closes - as controlcli.serve does.
HOLDER = """
import sys, threading
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from codex_auto_resume_advanced.report import github
import os
def run():
    github.run_process([sys.executable, "-c", sys.argv[3], sys.argv[4]], env=dict(os.environ), cwd=sys.argv[5],
                       stdin=None, timeout=300, creationflags=github.FLAGS)
threading.Thread(target=run, daemon=True).start()
sys.stdin.read()
"""


def _pid(path, seconds=20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            return int(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.1)
    return None


@unittest.skipUnless(os.name == "nt", "the job object is Windows'")
class JobTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_a_process_is_run_in_the_job_and_answers(self):
        code, out, err = github.run_process([sys.executable, "-c", "import sys; print('answered'); sys.exit(3)"],
                                            env=dict(os.environ), cwd=str(self.root), stdin=None, timeout=60,
                                            creationflags=github.FLAGS)
        self.assertEqual((code, out), (3, "answered"))
        code, out, _err = github.run_process([sys.executable, "-c", "import sys; print(sys.stdin.read())"],
                                             env=dict(os.environ), cwd=str(self.root), stdin=b"on stdin",
                                             timeout=60, creationflags=github.FLAGS)
        self.assertEqual((code, out), (0, "on stdin"))

    def test_one_that_does_not_answer_in_time_is_ended_and_only_it(self):
        pid_file = self.root / "pid"
        with self.assertRaises(github.GhTimeout):
            github.run_process([sys.executable, "-c", SLEEPER, str(pid_file)], env=dict(os.environ),
                               cwd=str(self.root), stdin=None, timeout=3, creationflags=github.FLAGS)
        pid = _pid(pid_file)
        self.assertIsNotNone(pid)
        self.assertTrue(_gone(pid))
        self.assertTrue(_alive(os.getpid()), "the process that ran it goes on")

    def test_one_that_cannot_be_put_in_the_job_is_ended_unrun_and_gh_failed(self):
        """No job object, or no kernel to make one: the suspended process is ended there and then, never
        waited for - otherwise the check or send would hold the report mutex for the life of the service."""
        def no_job(_k):
            raise OSError("no job object")

        def no_kernel():
            raise OSError("no kernel32")
        for name, failing in (("_job", no_job), ("_kernel", no_kernel)):
            with self.subTest(failing=name):
                started, outcome = [], []
                real = subprocess.Popen

                def keep(*a, **k):
                    made = real(*a, **k)
                    started.append(made)
                    return made

                def call():
                    try:
                        outcome.append(github.GhSession(sys.executable, self.root).run("-c", "print('answered')"))
                    except ReportRefused as refusal:
                        outcome.append(refusal.code)
                with mock.patch.object(github, name, failing), mock.patch.object(subprocess, "Popen", keep):
                    worker = threading.Thread(target=call, daemon=True)
                    worker.start()
                    worker.join(30)
                try:
                    self.assertFalse(worker.is_alive(), "a process that could not be adopted was waited for")
                    self.assertEqual(outcome, ["gh_failed"])
                    self.assertEqual(len(started), 1)
                    self.assertIsNotNone(started[0].poll(), "it was left suspended")
                    self.assertNotEqual(started[0].returncode, 0, "it was ended, never resumed to run")
                finally:
                    if started and started[0].poll() is None:
                        started[0].kill()
                        started[0].wait()

    def test_a_process_still_running_when_its_starter_ends_is_ended_with_it(self):
        pid_file = self.root / "pid"
        holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(ADVANCED), str(CORE), SLEEPER, str(pid_file),
                                   str(self.root)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        try:
            pid = _pid(pid_file)
            self.assertIsNotNone(pid, "the sleeper never started")
            self.assertTrue(_alive(pid))
            holder.stdin.close()                       # as the window closes the service's input
            holder.wait(timeout=30)
            self.assertTrue(_gone(pid), "a process the service started outlived it")
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait()


if __name__ == "__main__":
    unittest.main()
