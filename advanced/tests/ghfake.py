"""A stand-in for gh, for every test of the compatibility report's sending (report/github.py).

`FakeGh` is the runner report/github.py is given in place of starting a process: it writes down every
call - the argument list, the environment, the creation flags, the folder and the bytes on standard
input - and answers it as GitHub would for one person, from a few facts a test sets: who gh is signed
in as, whether the project takes reports, the fork, the branch, the open pull requests. Nothing is
started and nothing reaches the network.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import base64
import json

from codex_auto_resume_advanced.report import github

LOGIN = "ExampleUser"
MAIN = "0123456789abcdef0123456789abcdef01234567"
NOT_FOUND = (1, "", "gh: Not Found (HTTP 404)")


class FakeGh:
    """gh signed in as `who`, against the project as the fields say, recording every call."""

    def __init__(self, who=LOGIN, *, signed_in=True, open_door=True, filed=False, fork=None, branch=False,
                 pulls=(), base=MAIN, made_fork=None, fork_ready_after=0, pr_answer=None, contents=None,
                 hang=(), fail=()):
        self.who = who
        self.signed_in = signed_in
        self.open_door = open_door
        self.filed = filed
        self.fork = fork                      # None: no fork; "fork": a fork of the project; "other": not one
        self.branch = branch
        self.pulls = list(pulls)
        self.base = base
        self.made_fork = made_fork
        self.fork_ready_after = fork_ready_after
        self.pr_answer = pr_answer
        self.contents = dict(contents or {})  # {(fork, path, branch): blob sha}
        self.hang = tuple(hang)               # argument words that make that call hang
        self.fail = tuple(fail)               # argument words that make that call fail
        self.calls = []
        self.fork_polls = 0

    # The runner report/github.py calls.
    def __call__(self, argv, *, env, cwd, stdin, timeout, creationflags):
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "stdin": stdin, "timeout": timeout,
                           "creationflags": creationflags})
        words = argv[1:]
        joined = " ".join(words)
        if any(word in joined for word in self.hang):
            raise github.GhTimeout()
        if any(word in joined for word in self.fail):
            return 1, "", "gh: Something went wrong (HTTP 500)"
        return self.answer(words)

    def arguments(self) -> list:
        return [call["argv"][1:] for call in self.calls]

    def writes(self) -> list:
        """The calls that change something on GitHub, as (method or pr, endpoint)."""
        found = []
        for words in self.arguments():
            if words[:1] == ["pr"]:
                found.append(("pr", words[1]))
            elif words[:1] == ["api"] and words[words.index("-X") + 1] != "GET":
                found.append((words[words.index("-X") + 1], words[words.index("-X") + 2]))
        return found

    def answer(self, words):
        if words[:2] == ["auth", "status"]:
            return (0, "", "Logged in") if self.signed_in else (1, "", "not logged in")
        if words[:1] == ["pr"]:
            if self.pr_answer is not None:
                return self.pr_answer
            return 0, "https://github.com/%s/pull/42" % github.REPOSITORY, ""
        method = words[words.index("-X") + 1]
        endpoint = words[words.index("-X") + 2]
        fork = "%s/%s" % (LOGIN, github.NAME)
        if endpoint == "repos/%s/forks" % github.REPOSITORY:
            return 0, self.made_fork or fork, ""
        if method in ("POST", "PATCH", "PUT"):
            return 0, "{}", ""
        if endpoint == "user":
            return 0, self.who, ""
        if endpoint == "repos/%s/contents/%s" % (github.REPOSITORY, github.COMMUNITY):
            return (0, "[]", "") if self.open_door else NOT_FOUND
        if endpoint.startswith("repos/%s/contents/" % github.REPOSITORY):
            return (0, "{}", "") if self.filed else NOT_FOUND
        if endpoint.startswith("repos/%s/pulls?" % github.REPOSITORY):
            half = len(self.pulls) // 2
            return 0, json.dumps(self.pulls[:half]) + json.dumps(self.pulls[half:]), ""
        if endpoint.startswith("repos/%s/contents/" % fork):
            path, _, ref = endpoint[len("repos/%s/contents/" % fork):].partition("?ref=")
            found = self.contents.get((path, ref))
            return (0, found, "") if found else NOT_FOUND
        if endpoint == "repos/" + fork and method == "GET":
            if self.fork is None:
                return NOT_FOUND
            parent = github.REPOSITORY if self.fork == "fork" else "someone/else"
            return 0, json.dumps({"fork": self.fork == "fork", "parent": {"full_name": parent}}), ""
        if endpoint == "repos/%s/git/ref/heads/main" % fork:
            self.fork_polls += 1
            return (0, MAIN, "") if self.fork_polls > self.fork_ready_after else NOT_FOUND
        if endpoint.startswith("repos/%s/git/ref/heads/" % fork):
            return (0, "{}", "") if self.branch else NOT_FOUND
        if endpoint == "repos/%s/git/ref/heads/main" % github.REPOSITORY:
            return 0, self.base, ""
        return NOT_FOUND


def pull(login=LOGIN, ref="compat-report/codex-cli-0.158.0", number=7, owner=None) -> dict:
    """One open pull request as GitHub's list of them gives it."""
    return {"html_url": "https://github.com/%s/pull/%d" % (github.REPOSITORY, number), "user": {"login": login},
            "head": {"ref": ref, "repo": {"owner": {"login": owner or login}}}}


def uploaded(call) -> bytes:
    """The file a PUT's standard input carries."""
    return base64.b64decode(json.loads(call["stdin"].decode("ascii"))["content"])
