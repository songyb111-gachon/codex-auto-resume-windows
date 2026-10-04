# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""gh, the GitHub CLI the person installed, asked for a report as codex-compat-reporter asks it.

The one module of this edition that names gh or starts it. Everything else of the report reaches
GitHub through here, and here reaches it through gh alone: no networking module is imported, no
address is called, and gh does every request with the person's own sign-in, which this code never
sees (B11, C1 by delegation).

gh is found as the reporter finds it (its find_gh): gh.exe in an absolute folder on PATH, never the
current folder, never the installation's home or anything in it - where a gh.exe beside the product
would otherwise be started before the real one. It is started by that full path with an argument
list, no shell, and an environment that is the process's own less GH_HOST and GH_REPO, with prompts
and the update notifier off and the current folder out of the executable search; every `api` call
names --hostname github.com and every `pr` call --repo github.com/<the project>, so nothing a local
configuration says can send a request elsewhere.

Every gh runs in this process's one job object, made with KILL_ON_JOB_CLOSE, whose only handle this
process holds: started suspended (with CREATE_NO_WINDOW, which CREATE_SUSPENDED does not void), put
in the job, then resumed - the chain codex/wmi_escape.py uses. So when the Dashboard's service ends,
however it ends, Windows ends every gh it started, and no write finishes after it unrecorded. A gh
that has not answered in TIMEOUT seconds is ended alone (gh_timeout, E8).

The file goes to GitHub on gh's standard input (`--input -`), never through a temporary file: nothing
is written outside config/ (F3 departs only for a file the person saves).

`inspect` is everything before the first write, and only reads; `publish` makes the writes, asking
`before` before each one whether it may still go on. A refusal is one closed word (ReportRefused).
"""
from __future__ import annotations

import base64
import ctypes
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from codex_auto_resume.win.kernel import JOB_KILL_ON_CLOSE, NO_WINDOW

from ..vocabulary import ReportRefusal, ReportWrite, WebReason
from . import document

HOST = "github.com"
REPOSITORY = document.REPOSITORY
OWNER, NAME = REPOSITORY.split("/")
COMMUNITY = "docs/evidence/community"
PROJECT_PAGE = "https://github.com/" + REPOSITORY
BRANCH_PREFIX = "compat-report/"
TIMEOUT = 120                                    # seconds one gh may take before it alone is ended
FORK_WAITS, FORK_WAIT_SECONDS = 20, 3            # how long a new fork is given to be copied (the reporter's)
PULL = re.compile(re.escape(PROJECT_PAGE + "/pull/") + r"\d{1,9}")
SHA = re.compile(r"\A[0-9a-f]{40}\Z")
# Started suspended, so it is in the job before it runs a single instruction; the bit does not void
# CREATE_NO_WINDOW the way DETACHED_PROCESS or CREATE_NEW_CONSOLE would (test_no_console_windows).
CREATE_SUSPENDED = 0x00000004
FLAGS = NO_WINDOW | CREATE_SUSPENDED
_JOB_EXTENDED_LIMIT_INFORMATION = 9


class ReportRefused(Exception):
    """Nothing more was done: `code` says why, and nothing else does."""

    def __init__(self, code):
        self.code = ReportRefusal(code)
        super().__init__(str(self.code))


class GhTimeout(Exception):
    """gh did not answer in time, and was ended."""


# ------------------------------------------------------------------------------ finding gh
def _inside(folder: Path, place: Path) -> bool:
    try:
        folder, place = folder.resolve(), place.resolve()
    except OSError:
        return False
    return folder == place or place in folder.parents


def _same(folder: Path, place: Path) -> bool:
    try:
        return folder.resolve() == place.resolve()
    except OSError:
        return False


def find_gh(path=None, *, unsafe=()):
    """gh.exe from an absolute PATH entry, or None. Never `.`, a relative entry, the current folder
    itself - as the reporter's find_gh, a folder under it is any other folder - or one of `unsafe`,
    the installation's home and everything in it, however PATH spells them."""
    here = Path.cwd()
    places = [Path(place) for place in unsafe]
    for entry in (os.environ.get("PATH", "") if path is None else path).split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or entry == "." or not Path(entry).is_absolute():
            continue
        folder = Path(entry)
        if _same(folder, here) or any(_inside(folder, place) for place in places):
            continue
        candidate = folder / "gh.exe"
        try:
            if candidate.is_file() and not any(_inside(candidate.parent, place) for place in places):
                return str(candidate)
        except OSError:
            continue
    return None


def environment() -> dict:
    """The environment every gh starts with: this process's, less what would point gh elsewhere."""
    found = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1",
                 NoDefaultCurrentDirectoryInExePath="1")
    for name in ("GH_HOST", "GH_REPO"):
        found.pop(name, None)
    return found


# ------------------------------------------------------------------------------ the job
_LOCK = threading.Lock()
_JOB = None


def _kernel():
    from ..codex.wmi_escape import _kernel as kernel        # the job object's calls, declared once
    return kernel()


def _job(k):
    """This process's one job object for gh: KILL_ON_JOB_CLOSE, its one handle never inheritable and
    never closed here, so it closes - and ends every gh in it - when this process ends."""
    global _JOB
    with _LOCK:
        if _JOB is None:
            from ..codex.wmi_escape import _ExtendedLimits
            handle = k.CreateJobObjectW(None, None)
            if not handle:
                raise OSError("no job object")
            info = _ExtendedLimits()
            info.basic.flags = JOB_KILL_ON_CLOSE
            if not k.SetInformationJobObject(handle, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                             ctypes.sizeof(info)):
                k.CloseHandle(handle)
                raise OSError("the job object refused its limits")
            _JOB = handle
        return _JOB


def _adopt(process) -> None:
    """`process`, started suspended, put in the job and resumed - or ended, and OSError. Whatever
    fails first - the kernel's calls, the job object itself, opening, adopting or resuming gh - it
    is ended before the error goes on: a suspended gh that nobody ends would be waited for for ever."""
    try:
        k = _kernel()
        job = _job(k)
        handle = k.OpenProcess(0x0001 | 0x0100 | 0x0800, False, process.pid)   # TERMINATE | SET_QUOTA | SUSPEND_RESUME
        if not handle:
            raise OSError("gh could not be opened")
        try:
            if not k.AssignProcessToJobObject(job, handle):
                raise OSError("gh could not be put in the job")
            if ctypes.WinDLL("ntdll").NtResumeProcess(ctypes.c_void_p(handle)) != 0:
                raise OSError("gh could not be resumed")
        finally:
            k.CloseHandle(handle)
    except BaseException:
        process.kill()
        raise


def run_process(argv, *, env, cwd, stdin, timeout, creationflags=FLAGS):
    """(exit code, standard output, standard error) of one gh, started in this process's job. Its
    output is decoded as UTF-8 with replacement; one that has not answered in `timeout` seconds is
    ended, and only it (GhTimeout). It is always started windowless and suspended, whatever
    `creationflags` a caller names (a stand-in runner reads them). One that cannot be put in the job
    is ended before it runs, and OSError."""
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd,
                               creationflags=NO_WINDOW | CREATE_SUSPENDED, close_fds=True, shell=False)
    try:
        _adopt(process)
    except BaseException:
        process.communicate()                    # _adopt ended it: its pipes are closed and it is reaped
        raise
    try:
        out, err = process.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise GhTimeout() from None
    return process.returncode, out.decode("utf-8", "replace").strip(), err.decode("utf-8", "replace").strip()


# ------------------------------------------------------------------------------ asking
def _not_found(result) -> bool:
    code, out, err = result
    return code != 0 and ("(HTTP 404)" in err or '"status":"404"' in "".join(out.split()))


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _pages(text) -> list:
    """Every entry of `gh api --paginate`'s answer: one JSON array a page, written one after another."""
    decoder, found, at = json.JSONDecoder(), [], 0
    text = text or ""
    while at < len(text):
        while at < len(text) and text[at].isspace():
            at += 1
        if at >= len(text):
            break
        try:
            value, at = decoder.raw_decode(text, at)
        except ValueError:
            raise ReportRefused(ReportRefusal.GH_FAILED) from None
        if not isinstance(value, list):
            raise ReportRefused(ReportRefusal.GH_FAILED)
        found.extend(value)
    return found


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def blob_sha(raw: bytes) -> str:
    """The git blob SHA-1 of `raw`: what GitHub calls the file's `sha`."""
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def destination(codex_version, login) -> tuple:
    """(path, branch): the one place a report of `codex_version` filed under `login` can have."""
    name = "codex-cli-%s.json" % codex_version[len("codex-cli "):]
    return "%s/%s/%s" % (COMMUNITY, login, name), BRANCH_PREFIX + name[:-len(".json")]


class GhSession:
    """gh, by its full path, pinned to github.com, never prompting, each call in the job."""

    def __init__(self, exe, cwd, *, runner=run_process, sleep=time.sleep):
        self.exe = exe
        self.cwd = cwd
        self.runner = runner
        self.sleep = sleep

    def run(self, *arguments, stdin=None) -> tuple:
        try:
            return self.runner([self.exe, *arguments], env=environment(), cwd=str(self.cwd), stdin=stdin,
                               timeout=TIMEOUT, creationflags=FLAGS)
        except GhTimeout:
            raise ReportRefused(ReportRefusal.GH_TIMEOUT) from None
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ReportRefused(ReportRefusal.GH_FAILED) from None

    def api(self, method, endpoint, *more, stdin=None) -> tuple:
        return self.run("api", "--hostname", HOST, "-X", method, endpoint, *more, stdin=stdin)

    @staticmethod
    def must(result) -> str:
        if result[0]:
            raise ReportRefused(ReportRefusal.GH_FAILED)
        return result[1]


# ------------------------------------------------------------------------------ what a check finds
@dataclass
class Web:
    """gh cannot send it from here: the person sends it on the web, as `why` says."""
    why: WebReason
    who: str | None = None


@dataclass
class Sent:
    """A pull request of this very file is open already: nothing is to be written."""
    url: str


@dataclass
class Ready:
    """Everything before the first write: where it goes and every write sending would make."""
    exe: str
    who: str
    login: str
    fork: str
    branch: str
    target: str
    base: str
    has_fork: bool
    has_branch: bool
    cwd: str
    written: list = field(default_factory=list)

    def writes(self) -> list:
        """The writes, in order, as the person is shown them: [{"kind", "name"}]."""
        return [{"kind": str(ReportWrite.FORK_KEPT if self.has_fork else ReportWrite.FORK_NEW), "name": self.fork},
                {"kind": str(ReportWrite.BRANCH_RESET if self.has_branch else ReportWrite.BRANCH_NEW),
                 "name": self.branch},
                {"kind": str(ReportWrite.FILE), "name": self.target},
                {"kind": str(ReportWrite.PR), "name": REPOSITORY}]


def spelling(login, who):
    """gh's spelling of `login`, where `who` is that account typed in other letters, else None."""
    return who if who and who != login and who.casefold() == login.casefold() else None


def _open_reports(github, login) -> list:
    """(url, branch) of every open report pull request of `login`, from the project's own list of open
    pull requests, page by page - never `pr list --author`, which GitHub answers through its search."""
    listed = _pages(github.must(github.api("GET", "repos/%s/pulls?state=open&per_page=100" % REPOSITORY,
                                           "--paginate")))
    found = []
    for entry in listed:
        entry = _dict(entry)
        head = _dict(entry.get("head"))
        ref = head.get("ref")
        if (_dict(entry.get("user")).get("login") == login and isinstance(ref, str) and ref.startswith(BRANCH_PREFIX)
                and _dict(_dict(head.get("repo")).get("owner")).get("login") == login):
            found.append((entry.get("html_url") if isinstance(entry.get("html_url"), str) else "", ref))
    return found


def _sent_already(github, login, branch, target, raw, open_ones):
    """The pull request of exactly `raw` from `login:branch` that is open, or None."""
    for url, ref in open_ones:
        if ref != branch or not PULL.fullmatch(url or ""):
            continue
        fork = "%s/%s" % (login, NAME)
        sha = github.api("GET", "repos/%s/contents/%s?ref=%s" % (fork, target, branch), "--jq", ".sha")
        if sha[0] == 0 and sha[1] == blob_sha(raw):
            return url
    return None


def inspect(raw, report, login, *, exe, cwd, runner=run_process, sleep=time.sleep):
    """What sending `raw` - the report `report`, filed under `login` - would do, asking GitHub only
    questions: Web, Sent, or Ready; ReportRefused where it may not be sent at all."""
    target, branch = destination(report["codex_version"], login)
    if exe is None:
        return Web(WebReason.NO_GH)
    github = GhSession(exe, cwd, runner=runner, sleep=sleep)
    if github.run("auth", "status", "--hostname", HOST)[0]:
        return Web(WebReason.GH_SIGNED_OUT)
    who = github.must(github.api("GET", "user", "--jq", ".login"))
    if spelling(login, who):
        raise ReportRefused(ReportRefusal.GH_SPELLING)
    if who != login:
        return Web(WebReason.GH_OTHER_LOGIN, who=who if document.LOGIN.match(who or "") else None)
    door = github.api("GET", "repos/%s/contents/%s" % (REPOSITORY, COMMUNITY))
    if _not_found(door):
        raise ReportRefused(ReportRefusal.NOT_OPEN)
    github.must(door)
    open_ones = _open_reports(github, login)
    url = _sent_already(github, login, branch, target, raw, open_ones)
    if url is not None:
        return Sent(url)
    filed = github.api("GET", "repos/%s/contents/%s" % (REPOSITORY, target))
    if filed[0] == 0:
        raise ReportRefused(ReportRefusal.ALREADY_FILED)
    if not _not_found(filed):
        github.must(filed)
    if open_ones:
        raise ReportRefused(ReportRefusal.PR_OPEN)
    fork = "%s/%s" % (login, NAME)
    looked = github.api("GET", "repos/" + fork)
    has_fork = not _not_found(looked)
    if has_fork:
        info = _dict(_json(github.must(looked) or "{}"))
        if not info.get("fork") or _dict(info.get("parent")).get("full_name") != REPOSITORY:
            raise ReportRefused(ReportRefusal.FORK_NAMED_OTHERWISE)
    has_branch = False
    if has_fork:
        found = github.api("GET", "repos/%s/git/ref/heads/%s" % (fork, branch))
        has_branch = found[0] == 0
        if not has_branch and not _not_found(found):
            github.must(found)
    base = github.must(github.api("GET", "repos/%s/git/ref/heads/main" % REPOSITORY, "--jq", ".object.sha"))
    if not SHA.match(base):
        raise ReportRefused(ReportRefusal.BASE_INVALID)
    return Ready(exe=exe, who=who, login=login, fork=fork, branch=branch, target=target, base=base,
                 has_fork=has_fork, has_branch=has_branch, cwd=str(cwd))


# ------------------------------------------------------------------------------ the writes
def title(report, login) -> str:
    return "Compatibility report: %s (%s)" % (report["codex_version"], login)


def body(product_version) -> str:
    return ("Written by Codex Auto Resume %s (advanced edition) from my own machine's records. Counts, states and "
            "times only. It counts towards the Reported grade beside the version and nothing else." % product_version)


def publish(ready, raw, report, *, before, runner=run_process, sleep=time.sleep) -> str:
    """The writes `ready.writes()` names, in order - each one done added to `ready.written` - and the
    pull request's address. `before()` is asked before every write and raises to stop it; a refusal
    after a write leaves what was written in `ready.written`."""
    github = GhSession(ready.exe, ready.cwd, runner=runner, sleep=sleep)
    written = ready.written
    writes = ready.writes()
    login, fork, branch, target = ready.login, ready.fork, ready.branch, ready.target
    if not ready.has_fork:
        before()
        made = github.must(github.api("POST", "repos/%s/forks" % REPOSITORY, "--jq", ".full_name"))
        if made != fork:
            raise ReportRefused(ReportRefusal.FORK_NAMED_OTHERWISE)
        written.append(writes[0])
        # A new fork answers as a repository before GitHub has copied its git data into it, and a
        # branch cannot be made until it has: wait for its main, not for its name.
        for _attempt in range(FORK_WAITS):
            if github.api("GET", "repos/%s/git/ref/heads/main" % fork, "--jq", ".object.sha")[0] == 0:
                break
            sleep(FORK_WAIT_SECONDS)
        else:
            raise ReportRefused(ReportRefusal.FORK_NOT_READY)
    before()
    if ready.has_branch:
        github.must(github.api("PATCH", "repos/%s/git/refs/heads/%s" % (fork, branch),
                               "-f", "sha=" + ready.base, "-F", "force=true"))
    else:
        github.must(github.api("POST", "repos/%s/git/refs" % fork,
                               "-f", "ref=refs/heads/" + branch, "-f", "sha=" + ready.base))
    written.append(writes[1])
    before()
    upload = json.dumps({"message": "Compatibility report for %s from %s" % (report["codex_version"], login),
                         "branch": branch, "content": base64.b64encode(raw).decode("ascii")}).encode("ascii")
    github.must(github.api("PUT", "repos/%s/contents/%s" % (fork, target), "--input", "-", stdin=upload))
    written.append(writes[2])
    before()
    made = github.run("pr", "create", "--repo", "%s/%s" % (HOST, REPOSITORY), "--base", "main",
                      "--head", "%s:%s" % (login, branch), "--title", title(report, login),
                      "--body", body(report["reporter"]["tool_version"]))
    found = PULL.search(made[1]) if made[0] == 0 else None
    if found is None:
        # gh refused it because one is open already, or answered without its address: what is open
        # from this branch with exactly this file is the pull request.
        url = _sent_already(github, login, branch, target, raw, _open_reports(github, login))
        if url is None:
            raise ReportRefused(ReportRefusal.GH_FAILED)
        written.append(writes[3])
        return url
    written.append(writes[3])
    return found.group(0)
