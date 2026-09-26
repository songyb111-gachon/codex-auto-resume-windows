"""The check a compatibility report's pull request runs (.github/workflows/community-report.yml).

It runs from main's own copy of this file, on a checkout of the pull request's base, under a
read-only token and no secrets. It never checks out, imports or runs anything from the pull
request: it reads the head's commits with git plumbing - which paths changed, and one file's bytes
- as data, and judges those bytes with build/community_report.py.

A pull request that changes nothing under docs/evidence/community/ is not a report and passes,
so the check can be required on every pull request. One that does, from anyone but the owner,
passes only when:

* it comes from a branch whose name starts with compat-report/, as codex-compat-reporter's `submit`
  makes it: the filer answers for those pull requests only, so one from another branch (patch-1,
  GitHub's name for an edit on the web) would pass here and then wait for no one;
* it changes exactly one path, and adds it, as an ordinary file (mode 100644: no link, no
  submodule);
* that path is docs/evidence/community/<the login that opened it>/codex-cli-<version>.json, where
  <version> is the report's own `codex_version`, in the one spelling the product writes it, and
  `reporter.github_login` is that login;
* the login is not a name Windows keeps for a device (con, nul, com1...): no Windows checkout
  could hold that folder, and one such file on main would stop every one of them;
* no folder already filed differs from that login only in letter case (the product and its CI
  run on Windows, where the two are one folder);
* nothing is filed at that path yet, on the base or on main: reports are add-only, one per login
  per Codex version;
* the file is at most 1 MB, which is known before it is read;
* the reader refuses nothing in it (the format, the words, the times, the counts, the
  fingerprint), with this repository's own releases as the product versions a report may name;
* it is not a copy. That rule is narrower than it sounds: it applies only to a report with at
  least one record, and compares only with reports filed for the same Codex version, whose
  records - their times and states, in order - must not be the same. A report with no records has
  nothing to copy; many honest machines will send exactly that.

What a report claims beyond its records is recomputed, not refused, and said.

Passing this check files nothing. An accepted report is filed by .github/workflows/community-file.yml,
which judges it again with this same function (`judge_coded`, whose codes say what the sender can do
about each refusal) against main as it is by then, and writes main's own regeneration of it, never
the sender's bytes. The owner's pull requests are the maintainer's tool filing a report the filer
held back, rewriting the index, or withdrawing one. For those every report the pull request adds or
changes is read the same way, without the one-file and own-folder rules; the test suite then holds
the index to the files (tests/test_reported_data.py).

What it prints is fixed text. A value from the pull request is printed only when it already
matched the pattern it had to match; anything else prints as <refused>, so a file name cannot
become a workflow command (::error) or break a line (%0A).

Exit codes: 0 accepted, or not a report; 1 refused; 2 the check could not run.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import community_report as reader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PREFIX = reader.COMMUNITY + "/"
SHA = re.compile(r"[0-9a-f]{40}")
ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR",
                "FIRST_TIMER", "MANNEQUIN", "NONE")
MAIN = "refs/remotes/origin/main"
REFUSED = "<refused>"
ACCEPTED, REFUSES, CANNOT = 0, 1, 2
# What the owner's filing may touch in the folder, beside reports: the index and README every filing
# rewrites, and the list of withdrawn reports, which only the owner writes and the filer reads.
OWNER_FILES = (PREFIX + "index.json", PREFIX + "README.md", PREFIX + "withdrawn.json")

# What each line is, as a word the filer turns into what the sender can do about it
# (build/community_file.py TEXTS). Every line judge_coded() gives carries one; CODES are refusals.
NOT_A_REPORT, ACCEPTED_LINE, RECOMPUTED, OWNER_LINE = "not-a-report", "accepted", "recomputed", "owner"
PATHS, CHANGED, MODE, FOLDER, RESERVED_NAME, CASE, FILED, SIZE, READER, NAME, COPY, BRANCH = (
    "paths", "changed", "mode", "folder", "reserved", "case", "filed", "size", "reader", "name", "copy", "branch")
CODES = (PATHS, CHANGED, MODE, FOLDER, RESERVED_NAME, CASE, FILED, SIZE, READER, NAME, COPY, BRANCH)
# The branch codex-compat-reporter's `submit` sends a report from; the filer answers for those only,
# so a report from any other branch would pass here and then wait for no one.
BRANCH_PREFIX = "compat-report/"
# docs/evidence/community/<login>/codex-cli-<version>.json, and nothing else, is a report's path.
REPORT_PATH = re.compile(r"%s(%s)/codex-cli-(\d[0-9A-Za-z.\-]{0,39})\.json"
                         % (re.escape(PREFIX), reader.LOGIN.pattern))
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}


class Git:
    """git plumbing on one repository, read only: fixed argument lists, no shell, no pager."""

    def __init__(self, root):
        self.root = str(root)

    def run(self, *arguments):
        done = subprocess.run(["git", "-C", self.root, "--no-pager", *arguments], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False, timeout=120,
                              env=dict(os.environ, **GIT_ENV), check=False)
        return done.returncode, done.stdout

    def text(self, *arguments):
        code, out = self.run(*arguments)
        if code:
            raise CheckError("git could not answer")
        return out.decode("utf-8", errors="strict")

    def resolves(self, ref) -> bool:
        return self.run("rev-parse", "--verify", "--quiet", ref + "^{commit}")[0] == 0

    def has(self, ref, path) -> bool:
        return self.run("cat-file", "-e", "%s:%s" % (ref, path))[0] == 0

    def size(self, sha) -> int:
        return int(self.text("cat-file", "-s", sha).strip())

    def blob(self, sha) -> bytes:
        code, out = self.run("cat-file", "blob", sha)
        if code:
            raise CheckError("git could not read the file")
        return out

    def changes(self, base, head):
        """(status, mode, blob, path) for every path the head changes since it left the base."""
        start = self.text("merge-base", base, head).strip()
        code, out = self.run("diff", "--raw", "-z", "--no-renames", "--no-ext-diff", "--no-textconv",
                             "--no-abbrev", start, head)
        if code:
            raise CheckError("git could not list the changes")
        fields = out.split(b"\0")
        found = []
        for meta, path in zip(fields[0::2], fields[1::2]):
            parts = meta.decode("ascii", errors="replace").lstrip(":").split()
            if len(parts) != 5:
                raise CheckError("git listed a change it could not be read as")
            try:
                name = path.decode("utf-8")
            except UnicodeDecodeError:
                name = None
            found.append((parts[4], parts[1], parts[3], name))
        return found

    def filed(self, ref):
        """{path: bytes} of every report kept under the folder on that ref."""
        code, out = self.run("ls-tree", "-r", "-z", "--full-tree", ref, "--", PREFIX)
        if code:
            return {}
        kept = {}
        for line in out.split(b"\0"):
            if not line:
                continue
            meta, _tab, path = line.partition(b"\t")
            name = path.decode("utf-8", errors="replace")
            kind, sha = meta.split()[1].decode("ascii"), meta.split()[2].decode("ascii")
            if kind == "blob" and name.endswith(".json") and name not in OWNER_FILES:
                kept[name] = sha
        return {name: self.blob(sha) for name, sha in kept.items()
                if self.size(sha) <= reader.MAX_BYTES}

    def releases(self) -> dict:
        """This repository's tags and when each was made - the product versions a report may name."""
        out = self.text("for-each-ref", "--format=%(refname:strip=2)%09%(creatordate:unix)", "refs/tags")
        found = {}
        for line in out.splitlines():
            name, _tab, when = line.partition("\t")
            if when.isdigit():
                found[name] = int(when)
        return found


class CheckError(Exception):
    """The check could not run; it judges nothing then."""


def shown(value, pattern) -> str:
    """The value, only when it already matched what it had to match."""
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else REFUSED


def touches(path) -> bool:
    """Whether Windows would open a path inside the folder: in any letter case, through "." or
    "..", or with the dots and spaces it drops from a segment's end ("community."). Reading more
    paths as the folder's only makes more pull requests answer to the report rules."""
    if path is None:
        return True
    parts = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            parts = parts[:-1]
            continue
        parts.append(part.rstrip(". ").casefold())
    return parts[:3] == reader.COMMUNITY.casefold().split("/")


def sequence(report):
    return [(record.get("detected_at"), record.get("delivered_at"), record.get("outcome_at"), record.get("state"))
            for record in report.get("records", []) if isinstance(record, dict)]


def judge(git, *, base, head, author, association, now=None, branch=None):
    """(verdict, lines): verdict is ACCEPTED, REFUSES or CANNOT; lines are what to print."""
    verdict, coded = judge_coded(git, base=base, head=head, author=author, association=association, now=now,
                                 branch=branch)
    return verdict, [text for _code, text in coded]


def judge_coded(git, *, base, head, author, association, now=None, branch=None):
    """(verdict, [(code, line)]): judge(), with each line's code - one of CODES for a refusal.

    `branch` is the name of the pull request's head branch, compared and never shown; None skips
    that one rule (the filer, which answers for BRANCH_PREFIX branches only)."""
    now = time.time() if now is None else now
    changes = git.changes(base, head)
    ours = [change for change in changes if touches(change[3])]
    if not ours:
        return ACCEPTED, [(NOT_A_REPORT, "not a report: this pull request changes nothing under %s/"
                           % reader.COMMUNITY)]
    releases = git.releases()
    if not releases:
        raise CheckError("this repository's releases could not be read")
    if association == "OWNER":
        return _owner(git, ours, releases, now)

    filed_on = [base] + ([MAIN] if git.resolves(MAIN) else [])
    filed = {}
    for ref in filed_on:
        filed.update(git.filed(ref))
    refused = []
    if branch is not None and not branch.startswith(BRANCH_PREFIX):
        refused.append((BRANCH, "a report is sent from a branch named %s<its name>, as codex-compat-reporter's "
                                "submit makes it; this pull request's branch is another" % BRANCH_PREFIX))
    status, mode, blob, path = changes[0]
    if len(changes) != 1:
        refused.append((PATHS, "a report adds exactly one file, and this pull request changes %d paths"
                         % len(changes)))
    elif status != "A":
        refused.append((CHANGED, "a report adds a new file; this pull request changes or removes one "
                                 "(reports are add-only)"))
    elif mode != "100644":
        refused.append((MODE, "a report is an ordinary file, not a link or a submodule"))
    else:
        expected = REPORT_PATH.fullmatch(path or "")
        if not expected or expected.group(1) != author:
            refused.append((FOLDER, "a report is added as %s/%s/codex-cli-<version>.json, under the login "
                                    "that opened the pull request"
                            % (reader.COMMUNITY, shown(author, reader.LOGIN.pattern))))
        elif not reader.login_name(author):
            refused.append((RESERVED_NAME, "a report's folder cannot be a name Windows keeps for a device "
                                           "(con, nul, aux, prn, com0-9, lpt0-9)"))
        folders = {name[len(PREFIX):].split("/", 1)[0] for name in filed}
        if any(folder != author and folder.casefold() == author.casefold() for folder in folders):
            refused.append((CASE, "a folder differing from this login only in letter case is already filed"))
        if path is not None and any(git.has(ref, path) for ref in filed_on):
            refused.append((FILED, "a report for this login and version is already filed; reports are add-only"))
    if refused:
        return REFUSES, refused

    if git.size(blob) > reader.MAX_BYTES:
        return REFUSES, [(SIZE, "the file is larger than 1 MB")]
    report, problems, recomputed = reader.inspect(git.blob(blob), author=author, now=now, releases=releases)
    refused.extend((READER, problem) for problem in problems)
    if not problems:
        if path != reader.canonical_path(author, report["codex_version"]):
            refused.append((NAME, "the file is not named for its own codex_version: codex-cli-<version>.json"))
        mine = sequence(report)
        for _path, raw in sorted(filed.items()):
            other = _readable(raw)
            if mine and other is not None and other.get("codex_version") == report["codex_version"] \
                    and sequence(other) == mine:
                refused.append((COPY, "its records are the same, in order, as a report already filed for "
                                      "this version"))
                break
    if refused:
        return REFUSES, refused
    return ACCEPTED, [(ACCEPTED_LINE, "a report for %s from %s" % (shown(report["codex_version"],
                                                                         reader.VERSION.pattern),
                                                                   shown(author, reader.LOGIN.pattern)))] + [
        (RECOMPUTED, "recomputed: " + said) for said in recomputed]


def _readable(raw):
    try:
        found = reader.compat.decode(raw, reader.MAX_BYTES)
    except reader.compat.DocumentError:
        return None
    return found if isinstance(found, dict) else None


def _owner(git, ours, releases, now):
    """The maintainer's tool: every report it adds or changes is read; the suite holds the index."""
    refused, lines = [], [(OWNER_LINE, "the owner's filing")]
    for status, mode, blob, path in ours:
        if status == "D":
            continue
        if mode != "100644":
            refused.append((MODE, "the folder holds ordinary files only"))
            continue
        if path in OWNER_FILES:
            continue
        if not REPORT_PATH.fullmatch(path or ""):
            refused.append((FOLDER, "the folder holds reports, index.json, README.md and withdrawn.json only"))
            continue
        if not reader.login_name(REPORT_PATH.fullmatch(path).group(1)):
            refused.append((RESERVED_NAME, "a report's folder cannot be a name Windows keeps for a device"))
            continue
        if git.size(blob) > reader.MAX_BYTES:
            refused.append((SIZE, "a report is larger than 1 MB"))
            continue
        report, problems, _recomputed = reader.inspect(git.blob(blob), now=now, releases=releases)
        refused.extend((READER, problem) for problem in problems)
        if not problems and path != reader.canonical_path(report["reporter"]["github_login"], report["codex_version"]):
            refused.append((NAME, "a report is not filed under its own login and version"))
        if not problems and report != reader.filed_copy(report):
            refused.append((READER, "a filed report holds its recomputed reading and our sentences"))
    return (REFUSES if refused else ACCEPTED), lines + refused


def main(environ=None, git=None) -> int:
    environ = os.environ if environ is None else environ
    git = git or Git(ROOT)
    base, head = environ.get("BASE_SHA", ""), environ.get("HEAD_SHA", "")
    author, association = environ.get("PR_AUTHOR", ""), environ.get("AUTHOR_ASSOCIATION", "")
    branch = environ.get("HEAD_REF", "")
    if not (SHA.fullmatch(base) and SHA.fullmatch(head) and reader.LOGIN.fullmatch(author)
            and association in ASSOCIATIONS and branch):
        print("community report: the check was started without what it needs")
        return CANNOT
    try:
        verdict, lines = judge(git, base=base, head=head, author=author, association=association, branch=branch)
    except (CheckError, OSError, ValueError, subprocess.SubprocessError):
        print("community report: the check could not read this pull request")
        return CANNOT
    print("community report: %s" % ("accepted" if verdict == ACCEPTED else "refused"))
    for line in lines:
        print("  - " + line)
    return verdict


if __name__ == "__main__":
    sys.exit(main())
