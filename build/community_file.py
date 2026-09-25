"""Files the compatibility reports people send, with no step by the maintainer.

.github/workflows/community-file.yml runs this from main's own copy, in a job that holds no token
while it does. It is the planner: it reads what the job's read-only steps saved about the open
report pull requests, judges each again with build/community_check.py against main as it is now,
and writes - into its out directory, never to GitHub - the commits that would file the accepted
ones, the comment each sender is owed, and a git bundle of those commits. A second job, on a fresh
runner with no Python and no repository code, reads that bundle as data, re-derives every commit
from git, and is the only thing that writes to GitHub (community-file.yml says how).

    python build/community_file.py choose --queue DIR
    python build/community_file.py plan --queue DIR --out DIR --work DIR

What it files is never the sender's bytes. A report is read by build/community_report.py and kept
as `encode(filed_copy(report))`; the index, the folder's README and the counts a release carries
(src/codex_auto_resume/data/reported.json) are written again from the reports on main by that same
file. One commit per filing, adding exactly one report and rewriting only those three.

The limits a person used to apply are constants here, and every number they count comes from
main's own history, never from what a pull request says:

* an account under MIN_AGE_DAYS old is closed with the date it can send again;
* one open report per account: the oldest is looked at, the others are closed;
* PER_REPORTER filings per account and PER_VERSION per Codex version in WINDOW_DAYS, counted
  from the `Community-reporter-id:` and `Community-report:` trailers on main; more wait;
* a Codex version the project's data does not name waits, unless it is newer than every version
  that data names and fewer than MAX_UNLISTED such versions are filed; so one sender cannot fill
  the counts file with invented versions, and the counts file keeps at least half its room;
* a failure reported on a version this project's own evidence verifies waits for the maintainer;
* the repository variable COMMUNITY_AUTOFILE pauses everything unless it is unset or `on`, and
  COMMUNITY_BLOCKED (numeric account ids) and docs/evidence/community/withdrawn.json refuse an
  account;
* nothing is filed while main's own tests are red, or while fewer than MIN_RATE requests of the
  hour's budget are left.

Accounts are keyed by their numeric id, which a rename does not change. A pull request is looked at
again only when its head moves, the reason it waits has passed, or main says the maintainer's tool
filed it; at most MAX_LOOKED of them per run, so a thousand pull requests from one account cost
what one does.

Before anything is written the tests that read the files being written (FIXED_MODULES) run on the
tree that would become main; a filing that fails them is dropped and the maintainer is told. dev
takes main's filings too, keeping its Korean documents, when dev has not changed those files
itself and its own tests pass on the result; otherwise dev is left for the next run or the
maintainer's promote.py into-dev.

Every text a sender is shown is fixed (TEXTS). A value from a pull request appears only when it
already matched the pattern it had to match (community_check.shown), and no text holds a mention,
a link, a quotation mark or a backslash.

build/ never enters a release, so nothing here runs on anyone's machine. It has no network code of
its own: every process it starts is git - whose one fetch is a pull request's commits, anonymously,
from this public repository - or the fixed test modules under this interpreter.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import community_check as check  # noqa: E402
import community_report as reader  # noqa: E402

DAY = 86400
MAX_LOOKED = 8                  # pull requests read closer, and so filed, per run
MAX_CLOSED = 10                 # closed without a closer look per run: extra and stale ones
MAX_COMMITS = 20                # a pull request with more is refused from its metadata alone
MIN_AGE_DAYS = 30
PER_REPORTER, PER_VERSION, WINDOW_DAYS = 3, 5, 7
MAX_UNLISTED = 5
STALE_DAYS = 14
UNLISTED_AGAIN_DAYS = 7
MIN_RATE = 300
MAX_TEXT = 4096
GHOST = 10137                   # what GitHub shows for a deleted account
BOT = "github-actions[bot]"
MEMBERS = ("OWNER", "MEMBER", "COLLABORATOR")
BRANCH_PREFIX = "compat-report/"
MAIN = "refs/remotes/origin/main"
DEV = "refs/remotes/origin/dev"
COMPAT_DATA = "src/codex_auto_resume/data/codex_compat.json"
COUNTS = "src/codex_auto_resume/data/reported.json"
INDEX = reader.COMMUNITY + "/index.json"
README = reader.COMMUNITY + "/README.md"
WITHDRAWN = reader.COMMUNITY + "/withdrawn.json"
WITHDRAWN_FORMAT = "codex-auto-resume-compat-withdrawn/1"

# The tests that read the files a filing writes: they run on the tree that would become main before
# anything is written. tests/test_community_file.py holds that every test module naming those files
# is here or says why it need not be.
FIXED_MODULES = ("tests.test_community_report", "tests.test_community_check", "tests.test_reported_data",
                 "tests.test_reported_counts", "tests.test_reported_isolation", "tests.test_compat")
TEST_TIMEOUT = 20 * 60
FETCH_TIMEOUT = 120

# What the write job may put on main, and the only shapes it accepts: one added report, and the three
# files every filing writes again. community-file.yml holds these three lines verbatim, and
# tests/test_workflow_privilege.py holds them equal. POSIX extended regular expressions, so bash's
# [[ =~ ]] reads them as Python does; a login's length (at most MAX_LOGIN) is checked beside them.
REPORT_ADD = (r"^docs/evidence/community/[A-Za-z0-9](-?[A-Za-z0-9]){0,38}/codex-cli-(0|[1-9][0-9]{0,5})"
              r"[.](0|[1-9][0-9]{0,5})[.](0|[1-9][0-9]{0,5})(-alpha[.](0|[1-9][0-9]{0,8})([.][1-9][0-9]{0,8})?)?"
              r"[.]json$")
REGENERATED = (r"^(docs/evidence/community/index[.]json|docs/evidence/community/README[.]md"
               r"|src/codex_auto_resume/data/reported[.]json)$")
RESERVED_LOGIN = r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])$"
MAX_LOGIN = 39

# The commit that files a report, word for word; the write job rebuilds it from the trailers and
# refuses a commit whose message is anything else. No quotation mark, backslash, percent sign,
# dollar sign or backtick, so bash's printf builds it and JSON carries it with only newlines escaped.
COMMIT_SUBJECT = "Community report: codex-cli %s from %s"
COMMIT_BODY = ("Filed by .github/workflows/community-file.yml from the pull request named below: the counts,"
               " states and times the sender measured, with every conclusion recomputed from its records and"
               " every sentence replaced by ours. It raises the tier of no version.")
DEV_MESSAGE = ("Take the community reports on main into dev; the Korean documents stay\n\n"
               "Made by .github/workflows/community-file.yml: dev with the reports main has filed, their index,"
               " README and counts, and nothing else. Every Korean document dev has is as it was.\n")
IDENTITY = {"GIT_AUTHOR_NAME": BOT, "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": BOT, "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"}

FILED, QUEUED, REFUSED, NEEDS_OWNER, CLOSED = "filed", "queued", "refused", "needs-owner", "closed"
STATES = (FILED, QUEUED, REFUSED, NEEDS_OWNER, CLOSED)
MARKER = re.compile(r"<!-- community-file state=(filed|queued|refused|needs-owner|closed) head=([0-9a-f]{40}) "
                    r"at=(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) until=(-|\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) "
                    r"why=(-|[a-z][a-z-]{0,23}) -->")
SHA = re.compile(r"[0-9a-f]{40}")
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
# What no text a sender is shown may hold: a mention, markup, a link, or what JSON or a shell would
# have to escape.
FORBIDDEN = re.compile(r"[@<>\"\\\r\t\x00-\x08\x0b-\x1f\x7f]|\]\(|://")

# ---------------------------------------------------------------------------------------- texts
# Why a report waits, and when it is looked at again.
WAITING = {
    "paused": "filing is paused for now",
    "red": "the project's own tests on main are not passing, and nothing is filed onto that",
    "reporter": "this account has had %d reports filed in the last %d days" % (PER_REPORTER, WINDOW_DAYS),
    "version": "this Codex version has had %d reports filed in the last %d days" % (PER_VERSION, WINDOW_DAYS),
    "unlisted": "this Codex version is older than the ones the project's own data names, so the maintainer files it",
    "unlisted-many": "%d Codex versions the project's own data does not name already have reports" % MAX_UNLISTED,
    "full": "the counts file a release carries has no room for another version until the maintainer makes some",
}
# What a sender can do about each refusal, by its code (community_check.CODES, and the filer's own).
AGAIN = "run `submit --yes` again, which resets the branch to main and adds only the file"
REGENERATE = "write it again with the latest codex-compat-reporter, do not edit it, and submit again"
ISSUE = "open an issue"
ACTIONS = {
    check.PATHS: AGAIN, check.CHANGED: AGAIN, check.MODE: AGAIN, "commits": AGAIN,
    check.FOLDER: "submit from the account whose login was given to `report --login`",
    check.RESERVED_NAME: ISSUE, check.CASE: ISSUE,
    check.FILED: "nothing to do; a newer Codex version can be reported",
    check.SIZE: REGENERATE, check.READER: REGENERATE, check.NAME: REGENERATE,
    check.COPY: "send this machine's own records, or " + ISSUE,
    check.NOT_A_REPORT: "a report adds one file under docs/evidence/community/, and is sent with "
                        "codex-compat-reporter's `submit`",
    "cannot": "it could not be read; " + AGAIN,
    "blocked": "not accepted from this account; " + ISSUE,
}
TEXTS = {
    FILED: ("Filed as `%s` in %s, thank you. The kept file was written by this project's own code from what "
            "your report measured: every conclusion recomputed from its records, every sentence replaced by "
            "ours."),
    "counted": ("It counts under Reported from the next release, beside the tier and never as one "
                "(docs/evidence/community/README.md). Closed, not merged, because the kept file is the "
                "regenerated one."),
    QUEUED: "Waiting, nothing for you to do: %s. Looked at again automatically %s.",
    NEEDS_OWNER: ("A check on our side failed; the maintainer has been told. Nothing is known to be wrong "
                  "with your file."),
    "contradicts": ("Held for the maintainer: this report says a recovery failed on a Codex version this "
                    "project's own evidence verifies, and a person looks at that first. Nothing is known to be "
                    "wrong with your file."),
    REFUSED: "Not filed.",
    "again": ("A new commit here is judged again. Unchanged, this closes in %d days; a new report is welcome "
              "any time." % STALE_DAYS),
    "young": ("Closed, and nothing is wrong with your file: reports are filed from accounts at least %d days "
              "old, and this one is on %%s. Send it again then with `submit --yes`; nothing was filed."
              % MIN_AGE_DAYS),
    "one": ("Closed, and nothing is wrong with your file: one report at a time from one account, and #%s is "
            "still open. Send this one again with `submit --yes` once that one is closed; nothing was filed."),
    "stale": ("Closed: refused %d days ago and unchanged since. Nothing was filed; send a new report any time."
              % STALE_DAYS),
}
# What the job says to the maintainer: a code and a pull request number, nothing from it.
RED = {"tests": "a filing failed the tests that read the files it writes",
       "contradicts": "a report says a version this project verifies failed"}


def iso(seconds) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def day(seconds) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(seconds))


def moment(text):
    return reader.moment(text) if isinstance(text, str) and TIME.fullmatch(text) else None


def writable(path) -> bool:
    """Whether the write job would put this path on main: REPORT_ADD or REGENERATED, as it reads them."""
    if not isinstance(path, str):
        return False
    if re.fullmatch(REGENERATED, path):
        return True
    if not re.fullmatch(REPORT_ADD, path):
        return False
    login = path[len(reader.COMMUNITY) + 1:].split("/", 1)[0]
    return len(login) <= MAX_LOGIN and not re.fullmatch(RESERVED_LOGIN, login.lower())


def commit_message(login, version, reporter_id, number) -> str:
    bare = version[len("codex-cli "):]
    return "%s\n\n%s\n\nCommunity-report: %s %s\nCommunity-reporter-id: %d\nPull-request: #%d\n" % (
        COMMIT_SUBJECT % (bare, login), COMMIT_BODY, login, bare, reporter_id, number)


def marker(state, head, at, until=None, why=None) -> str:
    return "<!-- community-file state=%s head=%s at=%s until=%s why=%s -->" % (
        state, head, iso(at), iso(until) if until is not None else "-", why or "-")


def parse_marker(text):
    """{state, head, at, until, why} from a sticky comment's first line, or None."""
    found = MARKER.fullmatch(text.strip()) if isinstance(text, str) else None
    if not found:
        return None
    state, head, at, until, why = found.groups()
    return {"state": state, "head": head, "at": moment(at), "until": None if until == "-" else moment(until),
            "why": None if why == "-" else why}


def clean(text) -> str:
    """A sender's text, refused rather than posted if anything in it could be more than text."""
    if not text.isascii() or FORBIDDEN.search(text) or len(text) > MAX_TEXT - 200:
        raise ValueError("a text would carry something it may not")
    return text


# ---------------------------------------------------------------------------------------- git
class Repo(check.Git):
    """git on the job's checkout: plumbing, a fetch of a pull request's head as data, commits built
    from blobs this file wrote, and worktrees to test them in. No hook, no filter, no lazy fetch."""

    ENV = dict(check.GIT_ENV, GIT_NO_LAZY_FETCH="1", GIT_CONFIG_GLOBAL=os.devnull)

    def run(self, *arguments, data=None, env=None, timeout=FETCH_TIMEOUT):
        clean_env = {key: value for key, value in os.environ.items() if "TOKEN" not in key.upper()}
        done = subprocess.run(["git", "-C", self.root, "-c", "core.hooksPath=" + os.devnull, "--no-pager",
                               *arguments], input=data if data is not None else b"",
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False, timeout=timeout,
                              env=dict(clean_env, **self.ENV, **(env or {})), check=False)
        return done.returncode, done.stdout

    def must(self, *arguments, data=None, env=None, timeout=FETCH_TIMEOUT) -> str:
        code, out = self.run(*arguments, data=data, env=env, timeout=timeout)
        if code:
            raise check.CheckError("git %s could not answer" % arguments[0])
        return out.decode("utf-8", errors="strict").strip()

    def sha(self, ref):
        code, out = self.run("rev-parse", "--verify", "--quiet", ref + "^{commit}")
        return out.decode("ascii").strip() if code == 0 else None

    def show(self, ref, path):
        code, out = self.run("cat-file", "blob", "%s:%s" % (ref, path))
        return out if code == 0 else None

    def fetch_head(self, number) -> bool:
        """The pull request's commits, as data: no tags, no submodules, no blob over 1 MB, bounded."""
        try:
            code, _out = self.run("fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
                                  "--filter=blob:limit=1m", "origin",
                                  "+refs/pull/%d/head:refs/community/pr/%d" % (number, number))
        except subprocess.TimeoutExpired:
            return False
        return code == 0

    def commit(self, parent, files, message, when) -> str:
        """A commit on `parent` whose tree is the parent's with `files` ({path: bytes}) set."""
        with tempfile.TemporaryDirectory() as folder:
            index = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
            self.must("read-tree", parent, env=index)
            for path, data in sorted(files.items()):
                blob = self.must("hash-object", "-w", "--no-filters", "--stdin", data=data)
                self.must("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path), env=index)
            tree = self.must("write-tree", env=index)
        stamp = {"GIT_AUTHOR_DATE": "%d +0000" % when, "GIT_COMMITTER_DATE": "%d +0000" % when}
        return self.must("commit-tree", tree, "-p", parent, "-F", "-", data=message.encode("utf-8"),
                         env=dict(IDENTITY, **stamp))

    def merge_commit(self, tree, parents, message, when) -> str:
        stamp = {"GIT_AUTHOR_DATE": "%d +0000" % when, "GIT_COMMITTER_DATE": "%d +0000" % when}
        arguments = ["commit-tree", tree]
        for parent in parents:
            arguments += ["-p", parent]
        return self.must(*arguments, "-F", "-", data=message.encode("utf-8"), env=dict(IDENTITY, **stamp))

    def tree_with(self, base, blobs) -> str:
        """`base`'s tree with each path in `blobs` ({path: blob sha}) set."""
        with tempfile.TemporaryDirectory() as folder:
            index = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
            self.must("read-tree", base, env=index)
            for path, blob in sorted(blobs.items()):
                self.must("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path), env=index)
            return self.must("write-tree", env=index)

    def blob_of(self, ref, path):
        code, out = self.run("rev-parse", "--verify", "--quiet", "%s:%s" % (ref, path))
        return out.decode("ascii").strip() if code == 0 else None

    def reports_on(self, ref) -> dict:
        """{path: report} for every report filed on `ref`, read by the one reader."""
        kept = {}
        for path, raw in self.filed(ref).items():
            report = _decoded(raw)
            if report is not None and check.REPORT_PATH.fullmatch(path):
                kept[path] = report
        return kept

    def filed_numbers(self, ref) -> frozenset:
        """Every pull request main's history says was filed, from the `Pull-request: #N` trailer the
        filer and the maintainer's tool both write."""
        code, out = self.run("log", "--first-parent", "--format=%B", ref, timeout=600)
        if code:
            return frozenset()
        return frozenset(int(number) for number in
                         re.findall(r"(?m)^Pull-request: #(\d{1,7})$", out.decode("utf-8", errors="replace")))

    def filings_since(self, ref, since):
        """[(when, reporter id, version)] for every filing on `ref`'s first-parent history since then,
        from the trailers the filer and the maintainer's tool write - never from a pull request."""
        out = self.must("log", "--first-parent", "--since=%d" % since, "--format=%x01%ct%x02%B", ref)
        found = []
        for entry in out.split("\x01"):
            stamp, _sep, body = entry.partition("\x02")
            ids = re.findall(r"(?m)^Community-reporter-id: (\d{1,12})$", body)
            reports = re.findall(r"(?m)^Community-report: (\S{1,39}) (\S{1,40})$", body)
            if ids and reports and stamp.strip().isdigit():
                found.append((int(stamp.strip()), int(ids[-1]), "codex-cli " + reports[-1][1]))
        return found

    def worktree(self, work, name, commit) -> Path:
        place = Path(work) / name
        if place.exists():
            self.run("worktree", "remove", "--force", str(place))
            shutil.rmtree(place, ignore_errors=True)
        self.must("worktree", "add", "--quiet", "--detach", str(place), commit, timeout=600)
        return place

    def drop_worktree(self, place):
        self.run("worktree", "remove", "--force", str(place))
        shutil.rmtree(place, ignore_errors=True)


# ---------------------------------------------------------------------------------------- what is written
# One implementation of every file a filing or a withdrawal writes, for the filer and for the
# maintainer's tool, which imports this file from main rather than keeping a copy of its own.
def regenerated(filed, now) -> dict:
    """{path: bytes}: the index, README and counts for the reports filed ({path: report})."""
    index = reader.build_index(filed, generated_at=now)
    return {INDEX: reader.encode(index), README: reader.build_readme(index).encode("ascii"),
            COUNTS: reader.encode(reader.project(index))}


def filing(filed, path, report, now) -> dict:
    """{path: bytes}: a report as it is kept - recomputed, with our sentences - and the index, README
    and counts written again with it."""
    kept = reader.filed_copy(report)
    return dict(regenerated(dict(filed, **{path: kept}), now), **{path: reader.encode(kept)})


def withdrawal(filed, path, reporter_id, withdrawn_raw, now) -> dict:
    """{path: bytes, or None to remove}: a filed report taken out, the index, README and counts
    without it, and its account added to withdrawn.json, so the filer does not file it again."""
    report = filed[path]
    document = _decoded(withdrawn_raw) if withdrawn_raw else None
    if not (isinstance(document, dict) and document.get("format") == WITHDRAWN_FORMAT
            and isinstance(document.get("withdrawn"), list)):
        document = {"format": WITHDRAWN_FORMAT, "withdrawn": []}
    entry = {"reporter_id": int(reporter_id), "login": report["reporter"]["github_login"],
             "version": report["codex_version"][len("codex-cli "):], "at": iso(now)}
    document["withdrawn"] = [kept for kept in document["withdrawn"]
                             if not (isinstance(kept, dict) and kept.get("reporter_id") == entry["reporter_id"]
                                     and kept.get("version") == entry["version"])] + [entry]
    files = regenerated({name: kept for name, kept in filed.items() if name != path}, now)
    files[path] = None
    files[WITHDRAWN] = reader.encode(document)
    return files


def _decoded(raw):
    try:
        found = reader.compat.decode(raw, reader.MAX_BYTES)
    except reader.compat.DocumentError:
        return None
    return found if isinstance(found, dict) else None


def run_fixed_tests(tree: Path) -> bool:
    """The tests that read the files a filing writes, on the tree that would become the branch."""
    environment = {key: value for key, value in os.environ.items() if "TOKEN" not in key.upper()}
    environment.update(PYTHONPATH="src", PYTHONDONTWRITEBYTECODE="1", GIT_NO_LAZY_FETCH="1")
    try:
        done = subprocess.run([sys.executable, "-m", "unittest", *FIXED_MODULES], cwd=str(tree), env=environment,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              shell=False, timeout=TEST_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


# ---------------------------------------------------------------------------------------- the queue
def _json_lines(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def _json_file(path: Path):
    items = _json_lines(path)
    return items[0] if len(items) == 1 else None


def _int(value, low=1, high=10 ** 12):
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else None


def _pull(entry):
    """One open pull request as the survey saved it, or None when anything in it is not what it must be."""
    if not isinstance(entry, dict):
        return None
    number, user = _int(entry.get("number"), high=10 ** 7), _int(entry.get("user_id"))
    head, login = entry.get("head_sha"), entry.get("login")
    if (number is None or user is None or not isinstance(head, str) or not SHA.fullmatch(head)
            or not isinstance(login, str) or not reader.LOGIN.fullmatch(login)
            or entry.get("association") not in check.ASSOCIATIONS or moment(entry.get("created_at")) is None):
        return None
    return {"number": number, "user_id": user, "head": head, "login": login, "type": entry.get("type"),
            "association": entry["association"], "created": moment(entry["created_at"]),
            "draft": entry.get("draft") is not False,
            "branch": entry.get("head_ref") if isinstance(entry.get("head_ref"), str) else ""}


class Survey:
    """What the job's first read-only step saved: the open pull requests on main, the sticky comments
    it could see, main's recent test runs and the hour's request budget."""

    def __init__(self, queue: Path):
        self.queue = Path(queue)
        pulls = {}
        for page in sorted(self.queue.glob("pulls-*.jsonl")):
            for entry in _json_lines(page):
                pull = _pull(entry)
                if pull is not None:
                    pulls[pull["number"]] = pull
        self.pulls = [pulls[number] for number in sorted(pulls)]
        self.stickies = {}
        for page in sorted(self.queue.glob("comments-*.jsonl")):
            for entry in _json_lines(page):
                self._sticky(entry, entry.get("issue") if isinstance(entry, dict) else None)
        for saved in sorted(self.queue.glob("sticky-*.json")):
            number = saved.stem[len("sticky-"):]
            comments = _json_file(saved)
            if number.isdigit() and isinstance(comments, list):
                for entry in comments:
                    self._sticky(entry, int(number))
        self.runs = [run for run in _json_lines(self.queue / "runs.jsonl") if isinstance(run, dict)]
        try:
            rate = (self.queue / "rate").read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            rate = ""
        self.rate = int(rate) if rate.isdigit() else 0

    def _sticky(self, entry, issue):
        if not isinstance(entry, dict):
            return
        number = _int(int(issue) if isinstance(issue, str) and issue.isdigit() else issue, high=10 ** 7)
        comment = _int(entry.get("id"))
        found = parse_marker(entry.get("marker"))
        if number is None or comment is None or found is None:
            return
        held = self.stickies.get(number)
        if held is None or comment < held["id"]:          # the first one is the sticky one
            self.stickies[number] = dict(found, id=comment)

    def look(self, number):
        """What the second read-only step saved about one pull request, or None."""
        pull = _json_file(self.queue / ("pull-%d.json" % number))
        files = _json_file(self.queue / ("files-%d.json" % number))
        if not isinstance(pull, dict) or not isinstance(files, list):
            return None
        user_id = _int(pull.get("user_id"))
        user = _json_file(self.queue / ("user-%d.json" % user_id)) if user_id else None
        if not isinstance(user, dict):
            return None
        return {"pull": pull, "files": files, "user": user}

    def main_is_red(self, repository) -> bool:
        """Whether main's latest finished test run, a push or a dispatch in this repository, failed."""
        for run in self.runs:
            if (run.get("status") == "completed" and run.get("branch") == "main" and run.get("repo") == repository
                    and run.get("event") in ("push", "workflow_dispatch")
                    and run.get("conclusion") in ("success", "failure", "timed_out", "startup_failure")):
                return run["conclusion"] != "success"
        return False


# ---------------------------------------------------------------------------------------- deciding
class Settings:
    def __init__(self, environ):
        switch = (environ.get("AUTOFILE") or "").strip().casefold()
        # Anything but unset or `on` pauses: a switch that fails open is not a switch.
        self.paused = switch not in ("", "on")
        self.blocked = {int(part) for part in re.split(r"[\s,]+", environ.get("BLOCKED") or "")
                        if part.isdigit() and len(part) <= 12}
        self.repository = environ.get("GITHUB_REPOSITORY") or ""


def triage(survey, settings, now, filed_numbers=frozenset()):
    """(to_look, actions): which open pull requests to read closer, and what to do about the rest now.

    Cheap: nothing here asks GitHub or fetches anything. `actions` are closes and waits decided from
    the survey alone; the rest are left as they are. `filed_numbers` are the pull requests main's
    history says were filed (`Pull-request: #N`): one waiting for the maintainer that the maintainer's
    tool has filed is looked at again, found filed, and closed as filed."""
    if survey.rate < MIN_RATE:
        return [], []
    red = survey.main_is_red(settings.repository)
    ours = [pull for pull in survey.pulls
            if not pull["draft"] and pull["association"] not in MEMBERS and pull["type"] == "User"
            and pull["user_id"] != GHOST and pull["branch"].startswith(BRANCH_PREFIX)]
    first = {}
    for pull in sorted(ours, key=lambda one: (one["created"], one["number"])):
        first.setdefault(pull["user_id"], pull)
    actions, candidates, closed = [], [], 0
    for pull in ours:
        sticky = survey.stickies.get(pull["number"])
        same = sticky is not None and sticky["head"] == pull["head"]
        oldest = first[pull["user_id"]]
        if oldest is not pull:
            if closed < MAX_CLOSED:
                closed += 1
                actions.append(Action(pull, CLOSED, "one", now, close=True,
                                      text=TEXTS["one"] % oldest["number"], sticky=sticky))
            continue
        if same and sticky["state"] == REFUSED and sticky["at"] + STALE_DAYS * DAY <= now:
            if closed < MAX_CLOSED:
                closed += 1
                actions.append(Action(pull, CLOSED, "stale", now, close=True, text=TEXTS["stale"], sticky=sticky))
            continue
        if same and sticky["state"] in (FILED, CLOSED):
            # Filed or closed before, and still open: the close did not happen. Close it again.
            actions.append(Action(pull, sticky["state"], sticky["why"], now, close=True, text=None, sticky=sticky))
            continue
        filed_since = pull["number"] in filed_numbers
        if same and sticky["state"] in (REFUSED, NEEDS_OWNER) and not filed_since:
            continue
        if same and sticky["state"] == QUEUED and sticky["why"] not in ("paused", "red") \
                and sticky["until"] is not None and sticky["until"] > now and not filed_since:
            continue
        if settings.paused or red:
            why = "paused" if settings.paused else "red"
            if not (same and sticky["state"] == QUEUED and sticky["why"] == why):
                actions.append(Action(pull, QUEUED, why, now, text=_waiting(why, None), sticky=sticky))
            continue
        candidates.append((sticky["at"] if sticky else 0, pull["created"], pull["number"], pull))
    looked = [entry[-1] for entry in sorted(candidates, key=lambda entry: entry[:3])]
    return looked[:MAX_LOOKED], actions


def _waiting(why, until):
    when = ("on %s" % day(until)) if until is not None else {
        "paused": "once filing is resumed", "red": "once they pass again"}.get(why, "on the next run")
    return TEXTS[QUEUED] % (WAITING[why], when)


class Action:
    """What one pull request is told, and whether it is closed."""

    def __init__(self, pull, state, why, now, *, close=False, text=None, until=None, sticky=None):
        self.pull, self.state, self.why, self.close = pull, state, why, close
        self.until, self.now, self.sticky, self.text = until, now, sticky, text
        self.red = None

    def comment(self):
        """(comment id or 0, body) to post, or None when the sticky comment already says this."""
        if self.text is None:
            return None
        sticky = self.sticky
        if (sticky is not None and sticky["state"] == self.state and sticky["head"] == self.pull["head"]
                and sticky["why"] == self.why and sticky["until"] == self.until):
            return None
        body = marker(self.state, self.pull["head"], self.now, self.until, self.why) + "\n" + clean(self.text) + "\n"
        return (sticky["id"] if sticky else 0), body


def refusal(lines) -> str:
    """Not filed: each of the check's lines with what to do about it. The check writes a placeholder
    as <version>; here it is (version), since no text a sender is shown holds an angle bracket."""
    said = [TEXTS[REFUSED], ""]
    for code, text in lines:
        text = text.replace("<", "(").replace(">", ")")
        said.append("- %s: %s" % (text, ACTIONS.get(code, ACTIONS[check.READER])))
    said += ["", TEXTS["again"]]
    return "\n".join(said)


class Planner:
    def __init__(self, repo: Repo, survey: Survey, settings: Settings, now, *, run_tests=run_fixed_tests,
                 work=None):
        self.git, self.survey, self.settings, self.now = repo, survey, settings, int(now)
        self.run_tests, self.work = run_tests, Path(work or tempfile.mkdtemp(prefix="community-file-"))
        self.main = repo.sha(MAIN)
        self.dev = repo.sha(DEV)
        self.tip = self.main
        self.actions, self.filings, self.summary = [], [], []
        self.releases = repo.releases() if self.main else {}
        self._reports = (None, {})
        self.listed, self.verified = self._compat_data()
        self.withdrawn = self._withdrawn()

    # -------------------------------------------------------------- what main says
    def _compat_data(self):
        raw = self.git.show(MAIN, COMPAT_DATA) if self.main else None
        document = _decoded(raw) if raw else None
        listed, verified = set(), set()
        for engine in (document or {}).get("engines", []) if isinstance(document, dict) else []:
            version = engine.get("version") if isinstance(engine, dict) else None
            if isinstance(version, str) and reader.compat.parse_version(version) is not None:
                listed.add(version)
                claims = engine.get("capabilities") if isinstance(engine.get("capabilities"), dict) else {}
                if any(isinstance(claim, dict) and claim.get("state") == "VERIFIED" for claim in claims.values()):
                    verified.add(version)
        return listed, verified

    def _withdrawn(self):
        """The accounts whose reports the maintainer withdrew (docs/evidence/community/withdrawn.json):
        a withdrawal sticks, so a pull request sent again from that account is not filed again."""
        raw = self.git.show(MAIN, WITHDRAWN) if self.main else None
        document = _decoded(raw) if raw else None
        ids = set()
        if isinstance(document, dict) and document.get("format") == WITHDRAWN_FORMAT:
            for entry in document.get("withdrawn", []) if isinstance(document.get("withdrawn"), list) else []:
                if isinstance(entry, dict) and _int(entry.get("reporter_id")):
                    ids.add(entry["reporter_id"])
        return ids

    def reports(self) -> dict:
        """{path: report} filed on the tip as it is now, read once per tip."""
        if self._reports[0] != self.tip:
            self._reports = (self.tip, self.git.reports_on(self.tip))
        return dict(self._reports[1])

    # -------------------------------------------------------------- one pull request
    def examine(self, pull):
        """Judge one pull request against the growing tip, and file it there when it passes."""
        looked = self.survey.look(pull["number"])
        sticky = self.survey.stickies.get(pull["number"])
        if looked is None:
            return None                       # nothing saved: looked at again on the next run
        meta, files, user = looked["pull"], looked["files"], looked["user"]
        if (meta.get("state") != "open" or meta.get("head_sha") != pull["head"] or meta.get("base") != "main"
                or meta.get("user_id") != pull["user_id"] or meta.get("draft") is not False):
            return None                       # it moved since the survey; the move wakes another run
        number, login = pull["number"], pull["login"]

        def refused(lines):
            return Action(pull, REFUSED, lines[0][0], self.now, text=refusal(lines), sticky=sticky)

        if user.get("id") != pull["user_id"] or user.get("type") != "User":
            return None
        if pull["user_id"] in self.settings.blocked or pull["user_id"] in self.withdrawn:
            return refused([("blocked", "this account's reports are not filed here")])
        created = moment(user.get("created_at"))
        if created is None:
            return None
        if created + MIN_AGE_DAYS * DAY > self.now:
            return Action(pull, CLOSED, "young", self.now, close=True,
                          text=TEXTS["young"] % day(created + MIN_AGE_DAYS * DAY), sticky=sticky)
        # The metadata first: a pull request that cannot be a report is refused without fetching it.
        commits, changed = _int(meta.get("commits")), _int(meta.get("changed_files"), low=0)
        if commits is None or commits > MAX_COMMITS:
            return refused([("commits", "a report is one commit; this pull request has more than %d" % MAX_COMMITS)])
        named = [entry for entry in files if isinstance(entry, dict)]
        if changed != 1 or len(named) != 1:
            return refused([(check.PATHS, "a report adds exactly one file, and this pull request changes %s paths"
                                          % (changed if changed is not None else "several"))])
        path, status = named[0].get("filename"), named[0].get("status")
        if not check.touches(path if isinstance(path, str) else None):
            return refused([(check.NOT_A_REPORT, "this pull request changes nothing under %s/" % reader.COMMUNITY)])
        if status != "added":
            return refused([(check.CHANGED, "a report adds a new file; this pull request changes or removes one")])
        shape = check.REPORT_PATH.fullmatch(path)
        if not shape or shape.group(1) != login:
            return refused([(check.FOLDER, "a report is added as %s/%s/codex-cli-<version>.json, under the login "
                                           "that opened the pull request"
                             % (reader.COMMUNITY, check.shown(login, reader.LOGIN.pattern)))])
        if not reader.login_name(login):
            return refused([(check.RESERVED_NAME, "a report's folder cannot be a name Windows keeps for a device")])

        if not self.git.fetch_head(number):
            return refused([("cannot", "the pull request's commits could not be fetched")])
        head = "refs/community/pr/%d" % number
        if self.git.sha(head) != pull["head"]:
            return None
        blob = self.git.blob_of(head, path)
        if blob is None or self.git.run("cat-file", "-e", blob)[0] != 0:
            return refused([(check.SIZE, "the file is larger than 1 MB")])

        already = self.already_filed(pull, head, path)
        if already is not None:
            return already
        try:
            verdict, lines = check.judge_coded(self.git, base=self.tip, head=head, author=login,
                                               association=pull["association"], now=self.now)
        except (check.CheckError, OSError, ValueError, subprocess.SubprocessError):
            return refused([("cannot", "the pull request could not be read")])
        if verdict != check.ACCEPTED:
            return refused(lines)
        if lines and lines[0][0] == check.NOT_A_REPORT:
            return refused(lines)
        report, problems, _recomputed = reader.inspect(self.git.blob(blob), author=login, now=self.now,
                                                       releases=self.releases)
        if problems:
            return refused([(check.READER, problem) for problem in problems])
        return self.limits(pull, report, sticky) or self.file(pull, report, sticky)

    def already_filed(self, pull, head, path):
        """Filed already with exactly what this pull request regenerates to: say so and close it."""
        kept = self.git.show(self.tip, path)
        if kept is None:
            return None
        report, problems, _ = reader.inspect(self.git.blob(self.git.blob_of(head, path)), author=pull["login"],
                                             now=self.now, releases=self.releases)
        if problems or reader.encode(reader.filed_copy(report)) != kept:
            return None
        commit = self.git.must("log", "--format=%H", "--diff-filter=A", "-1", self.tip, "--", path)
        return self.filed_action(pull, path, commit if SHA.fullmatch(commit) else "main", report,
                                 self.survey.stickies.get(pull["number"]))

    def limits(self, pull, report, sticky):
        """What waits, and until when: a person's limits, counted from main's history."""
        version = report["codex_version"]

        def wait(why, until):
            return Action(pull, QUEUED, why, self.now, text=_waiting(why, until), until=until, sticky=sticky)

        recent = self.git.filings_since(self.tip, self.now - WINDOW_DAYS * DAY)
        mine = sorted(when for when, who, _said in recent if who == pull["user_id"])
        if len(mine) >= PER_REPORTER:
            return wait("reporter", mine[len(mine) - PER_REPORTER] + WINDOW_DAYS * DAY)
        same = sorted(when for when, _who, said in recent if said == version)
        if len(same) >= PER_VERSION:
            return wait("version", same[len(same) - PER_VERSION] + WINDOW_DAYS * DAY)
        filed = self.reports()
        on_main = {kept["codex_version"] for kept in filed.values()}
        if version not in self.listed:
            newest = max((reader.compat.parse_version(v) for v in self.listed), default=None)
            if newest is not None and reader.compat.parse_version(version) <= newest:
                return wait("unlisted", self.now + UNLISTED_AGAIN_DAYS * DAY)
            unlisted = {kept for kept in on_main if kept not in self.listed}
            if version not in unlisted and len(unlisted) >= MAX_UNLISTED:
                return wait("unlisted-many", self.now + UNLISTED_AGAIN_DAYS * DAY)
        counts = reader.encode(reader.project(reader.build_index(
            dict(filed, **{reader.canonical_path(pull["login"], version): reader.filed_copy(report)}),
            generated_at=self.now)))
        try:
            table = reader.product_reported.parse(counts)
        except reader.compat.DocumentError:
            table = None
        if (table is None or len(counts) > reader.product_reported.MAX_BYTES // 2
                or len(table) > reader.product_reported.MAX_VERSIONS // 2):
            return wait("full", self.now + UNLISTED_AGAIN_DAYS * DAY)
        if reader.graded(report)["failed"] and version in self.verified:
            action = Action(pull, NEEDS_OWNER, "contradicts", self.now, text=TEXTS["contradicts"], sticky=sticky)
            action.red = "contradicts"
            return action
        return None

    def filing_files(self, filed, path, report):
        return filing(filed, path, report, self.now)

    def file(self, pull, report, sticky):
        path = reader.canonical_path(pull["login"], report["codex_version"])
        files = self.filing_files(self.reports(), path, report)
        if not all(writable(name) for name in files):
            return Action(pull, REFUSED, check.RESERVED_NAME, self.now, sticky=sticky,
                          text=refusal([(check.RESERVED_NAME, "this report's path is not one this project keeps")]))
        message = commit_message(pull["login"], report["codex_version"], pull["user_id"], pull["number"])
        commit = self.git.commit(self.tip, files, message, self.now)
        self.tip = commit
        self.filings.append({"pull": pull, "report": report, "path": path, "commit": commit, "message": message})
        return self.filed_action(pull, path, "{commit}", report, sticky)

    def filed_action(self, pull, path, commit, report, sticky):
        text = TEXTS[FILED] % (path, commit)
        recomputed = reader.changes(report)
        if recomputed:
            text += "\n\n" + "\n".join("- recomputed: " + said for said in recomputed)
        text += "\n\n" + TEXTS["counted"]
        return Action(pull, FILED, None, self.now, close=True, text=text, sticky=sticky)

    # -------------------------------------------------------------- the run
    def run(self):
        if self.main is None:
            self.summary.append("main could not be read; nothing was planned")
            return self
        folder_open = self.git.run("cat-file", "-e", "%s:%s" % (self.main, INDEX))[0] == 0
        looked, self.actions = triage(self.survey, self.settings, self.now, self.git.filed_numbers(self.main))
        if self.survey.rate < MIN_RATE:
            self.summary.append("fewer than %d GitHub requests are left this hour; nothing was looked at" % MIN_RATE)
        if not folder_open:
            self.summary.append("the folder %s/ is not on main; nothing is filed until it is" % reader.COMMUNITY)
            looked = []
        for pull in looked:
            action = self.examine(pull)
            if action is not None:
                self.actions.append(action)
        self.test_filings()
        if not (self.settings.paused or self.survey.main_is_red(self.settings.repository)):
            self.heal_dev()
        else:
            self.dev_plan = None
        return self

    def test_filings(self):
        """The tests that read what is written, on the tree that would become main; a filing that fails
        them is dropped, and the maintainer told."""
        self.dev_plan = None
        if not self.filings:
            return
        if self._passes(self.tip):
            return
        kept, self.tip = [], self.main
        for filing in self.filings:
            path, report, pull = filing["path"], filing["report"], filing["pull"]
            files = self.filing_files(self.reports(), path, report)
            commit = self.git.commit(self.tip, files, filing["message"], self.now)
            if self._passes(commit):
                self.tip = commit
                kept.append(dict(filing, commit=commit))
                continue
            for action in self.actions:
                if action.pull is pull:
                    action.state, action.why, action.close = NEEDS_OWNER, "tests", False
                    action.text, action.red = TEXTS[NEEDS_OWNER], "tests"
        self.filings = kept

    def _passes(self, commit) -> bool:
        place = self.git.worktree(self.work, "tree", commit)
        try:
            return bool(self.run_tests(place))
        finally:
            self.git.drop_worktree(place)

    def heal_dev(self):
        """dev takes what main filed, keeping its Korean documents: only when every path main changed
        since the two last met is one the filer writes, dev has not changed any of them itself, and
        dev's own tests pass on the result. Otherwise dev is left for the next run or promote.py."""
        self.dev_plan = None
        if self.dev is None or self.tip is None:
            return
        if self.git.run("merge-base", "--is-ancestor", self.tip, self.dev)[0] == 0:
            return
        base = self.git.must("merge-base", self.dev, self.tip)
        changed = [line for line in self.git.must("diff", "--name-only", "--no-renames", base, self.tip).splitlines()
                   if line]
        if not changed or not all(writable(path) for path in changed):
            self.summary.append("dev was left as it is: main changed more than the filer writes since dev last "
                                "took it (python scripts/promote.py into-dev, on dev)")
            return
        blobs = {}
        for path in changed:
            new = self.git.blob_of(self.tip, path)
            if new is None or self.git.blob_of(self.dev, path) != self.git.blob_of(base, path):
                self.summary.append("dev was left as it is: dev changed a file the filer writes")
                return
            blobs[path] = new
        tree = self.git.tree_with(self.dev, blobs)
        merge = self.git.merge_commit(tree, [self.dev, self.tip], DEV_MESSAGE, self.now)
        if not self._passes(merge):
            self.summary.append("dev was left as it is: its own tests do not pass with main's filings")
            return
        self.dev_plan = merge

    # -------------------------------------------------------------- what is handed to the write job
    def write(self, out: Path):
        out = Path(out)
        texts = out / "texts"
        if out.exists():
            shutil.rmtree(out)
        texts.mkdir(parents=True)
        chain = []
        if self.filings:
            chain = self.git.must("rev-list", "--first-parent", "--reverse", "%s..%s" % (self.main, self.tip)).split()
        _write(out, "main", (self.main or "") + "\n")
        _write(out, "chain", "".join(sha + "\n" for sha in chain))
        _write(out, "dev", ("%s %s\n" % (self.dev, self.dev_plan)) if self.dev_plan else "")
        lines, red = [], []
        for action in self.actions:
            said = action.comment()
            if said is None and not action.close:
                continue
            comment_id, body = said if said else (0, None)
            if body is not None:
                _write(texts, "%d.md" % action.pull["number"], body)
            lines.append("%d %s %s %d %s\n" % (action.pull["number"], action.state,
                                               "close" if action.close else "keep", comment_id,
                                               "post" if body is not None else "none"))
            if action.red and said is not None:
                red.append("%s %d\n" % (action.red, action.pull["number"]))
        _write(out, "actions", "".join(lines))
        _write(out, "red", "".join(red))
        if chain or self.dev_plan:
            prerequisites, names = ["^" + self.main], []
            if chain:
                self.git.must("update-ref", "refs/plan/main", self.tip)
                names.append("refs/plan/main")
            if self.dev_plan:
                self.git.must("update-ref", "refs/plan/dev", self.dev_plan)
                names.append("refs/plan/dev")
                prerequisites.append("^" + self.dev)
            self.git.must("bundle", "create", str(out / "plan.bundle"), *names, *prerequisites, timeout=600)
        states = {}
        for action in self.actions:
            states[action.state] = states.get(action.state, 0) + 1
        summary = ["## Community reports", "",
                   "- filed now: %d" % len(chain),
                   "- told: " + (", ".join("%s %d" % item for item in sorted(states.items())) or "nobody"),
                   "- dev: " + ("takes the filings too" if self.dev_plan else "unchanged by this run")]
        summary += ["- " + line for line in self.summary]
        if self.settings.paused:
            summary.append("- paused by COMMUNITY_AUTOFILE")
        _write(out, "summary.md", "\n".join(summary) + "\n")
        return out


def _write(folder: Path, name: str, text):
    """Every file this writes goes through here, and only ever inside the folder it was given."""
    target = (Path(folder) / name).resolve()
    if Path(folder).resolve() not in target.parents:
        raise ValueError("a file outside its folder")
    data = text.encode("utf-8") if isinstance(text, str) else text
    target.write_bytes(data)


# ---------------------------------------------------------------------------------------- commands
def choose(queue, environ=None, now=None, root=None):
    """Which pull requests the job's second read-only step reads closer: `look`, as `NUMBER USER_ID`."""
    survey = Survey(Path(queue))
    repo = Repo(root or os.getcwd())
    main = repo.sha(MAIN)
    looked, _actions = triage(survey, Settings(os.environ if environ is None else environ),
                              int(time.time() if now is None else now),
                              repo.filed_numbers(main) if main else frozenset())
    _write(Path(queue), "look", "".join("%d %d\n" % (pull["number"], pull["user_id"]) for pull in looked))
    return looked


def plan(queue, out, work, *, environ=None, now=None, root=None, run_tests=run_fixed_tests):
    environ = os.environ if environ is None else environ
    planner = Planner(Repo(root or os.getcwd()), Survey(Path(queue)), Settings(environ),
                      int(time.time() if now is None else now), run_tests=run_tests, work=work)
    planner.run()
    planner.write(Path(out))
    return planner


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("choose", "plan"))
    parser.add_argument("--queue", required=True)
    parser.add_argument("--out")
    parser.add_argument("--work")
    arguments = parser.parse_args(argv)
    if arguments.command == "choose":
        looked = choose(arguments.queue)
        print("community file: %d pull request(s) to read closer" % len(looked))
        return 0
    if not (arguments.out and arguments.work):
        parser.error("plan needs --out and --work")
    Path(arguments.work).mkdir(parents=True, exist_ok=True)
    planner = plan(arguments.queue, arguments.out, arguments.work)
    print("community file: %d filing(s) planned, %d pull request(s) told" % (
        len(planner.filings), len(planner.actions)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
