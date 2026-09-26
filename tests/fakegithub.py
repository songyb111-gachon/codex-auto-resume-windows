"""A stand-in for `gh`, and for the part of GitHub the filer's write step talks to.

tests/test_community_file.py runs the write step of .github/workflows/community-file.yml as it is
written - the same bash, line for line - with `gh` pointed here. Refs, blobs, trees and commits are
kept in a real bare repository, so a tree GitHub "makes" has the hash git gives it, exactly as on
GitHub; commits are made with another author and date, so they get hashes of their own, as GitHub's
do. Pull requests, comments, workflow runs and dispatches live in one JSON file.

It answers only the calls and `--jq` expressions the step makes. Anything else fails loudly (exit
99), so a new call in the step cannot pass here unnoticed.

    python fakegithub.py api [-X METHOD] ENDPOINT [--input FILE] [--jq EXPR] [-f K=V] [-F K=V]
    python fakegithub.py workflow run NAME --ref REF [-f K=V]
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

STATE = Path(os.environ["FAKE_GITHUB"])
DOCUMENT = STATE / "github.json"
ORIGIN = Path(os.environ["FAKE_ORIGIN"])
REPO = "owner/repo"
BOT = "github-actions[bot]"


def load():
    return json.loads(DOCUMENT.read_text(encoding="utf-8"))


def save(state):
    DOCUMENT.write_text(json.dumps(state, indent=1), encoding="utf-8")


def git(*args, data=None, env=None):
    done = subprocess.run(["git", "-C", str(ORIGIN), *args], input=data if data is not None else b"",
                          capture_output=True, env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, **(env or {})))
    return done.returncode, done.stdout.decode("utf-8").strip()


def fail(status, message):
    print(json.dumps({"message": message, "status": str(status)}))
    sys.stderr.write("gh: %s (HTTP %d)\n" % (message, status))
    sys.exit(1)


JQ = {
    ".sha": lambda r: r["sha"],
    ".object.sha": lambda r: r["object"]["sha"],
    '[.state, .base.ref, .author_association, (.head.ref | startswith("compat-report/") | tostring)] | join(" ")':
        lambda r: " ".join([r["state"], r["base"]["ref"], r["author_association"],
                            "true" if r["head"]["ref"].startswith("compat-report/") else "false"]),
    '[.user.login, (.issue_url | split("/") | last)] | join(" ")':
        lambda r: "%s %s" % (r["user"]["login"], r["issue_url"].rsplit("/", 1)[-1]),
    '[.workflow_runs[] | select(.status != "completed")] | length':
        lambda r: len([run for run in r["workflow_runs"] if run["status"] != "completed"]),
    '[.workflow_runs[] | select(.event == "push" or .event == "workflow_dispatch") | .head_sha] | first // ""':
        lambda r: next((run["head_sha"] for run in r["workflow_runs"]
                        if run["event"] in ("push", "workflow_dispatch")), ""),
}


def fields(pairs):
    found = {}
    for kind, pair in pairs:
        key, _sep, value = pair.partition("=")
        if kind == "-F" and value in ("true", "false"):
            value = value == "true"
        found[key] = value
    return found


def api(arguments):
    method, endpoint, given, jq, pairs = "GET", None, None, None, []
    rest = list(arguments)
    while rest:
        word = rest.pop(0)
        if word == "-X":
            method = rest.pop(0)
        elif word == "--input":
            given = json.loads(Path(rest.pop(0)).read_text(encoding="utf-8"))
        elif word == "--jq":
            jq = rest.pop(0)
        elif word in ("-f", "-F"):
            pairs.append((word, rest.pop(0)))
        elif endpoint is None:
            endpoint = word
        else:
            sys.stderr.write("unexpected argument %r\n" % word)
            sys.exit(99)
    body = given if given is not None else fields(pairs)
    state = load()
    state["calls"].append([method, endpoint])
    answer = route(state, method, endpoint, body)
    save(state)
    if jq is not None:
        if jq not in JQ:
            sys.stderr.write("the fake does not know the expression %r\n" % jq)
            sys.exit(99)
        answer = JQ[jq](answer)
    print(answer if isinstance(answer, (str, int)) else json.dumps(answer))


def route(state, method, endpoint, body):
    prefix = "repos/%s/" % REPO
    if not endpoint.startswith(prefix):
        sys.exit(99)
    path = endpoint[len(prefix):]
    parts = path.split("?")[0].split("/")
    if method == "GET" and parts[:3] == ["git", "ref", "heads"]:
        code, sha = git("rev-parse", "--verify", "-q", "refs/heads/" + parts[3])
        if code:
            fail(404, "Not Found")
        return {"object": {"sha": sha}}
    if method == "POST" and path == "git/blobs":
        if state.get("break") == "blobs":
            return {"sha": "0" * 40}
        data = base64.b64decode(body["content"])
        return {"sha": git("hash-object", "-w", "--stdin", data=data)[1]}
    if method == "POST" and path == "git/trees":
        with tempfile.TemporaryDirectory() as folder:
            index = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
            git("read-tree", body["base_tree"], env=index)
            for entry in body["tree"]:
                assert entry["mode"] == "100644" and entry["type"] == "blob", entry
                code, _ = git("update-index", "--add", "--cacheinfo",
                              "%s,%s,%s" % (entry["mode"], entry["sha"], entry["path"]), env=index)
                if code:
                    fail(422, "GitRPC::BadObjectState")
            sha = git("write-tree", env=index)[1]
        return {"sha": sha}
    if method == "POST" and path == "git/commits":
        arguments = ["commit-tree", body["tree"]]
        for parent in body["parents"]:
            arguments += ["-p", parent]
        stamp = {"GIT_AUTHOR_NAME": BOT, "GIT_AUTHOR_EMAIL": "bot@github.invalid", "GIT_COMMITTER_NAME": "GitHub",
                 "GIT_COMMITTER_EMAIL": "noreply@github.com", "GIT_AUTHOR_DATE": "2026-09-25T00:10:00Z",
                 "GIT_COMMITTER_DATE": "2026-09-25T00:10:00Z"}
        code, sha = git(*arguments, "-F", "-", data=body["message"].encode("utf-8"), env=stamp)
        if code:
            fail(422, "Invalid commit")
        state["commits"].append({"sha": sha, "message": body["message"], "parents": body["parents"]})
        return {"sha": sha}
    if method == "PATCH" and parts[:3] == ["git", "refs", "heads"]:
        ref = "refs/heads/" + parts[3]
        assert body.get("force") is False, "the filer never forces a ref"
        _code, current = git("rev-parse", "--verify", "-q", ref)
        if git("merge-base", "--is-ancestor", current, body["sha"])[0]:
            fail(422, "Update is not a fast forward")
        git("update-ref", ref, body["sha"], current)
        state["moves"].append([parts[3], body["sha"]])
        return {"object": {"sha": body["sha"]}}
    if method == "GET" and parts[0] == "pulls" and len(parts) == 2:
        pull = state["pulls"].get(parts[1])
        if pull is None:
            fail(404, "Not Found")
        return {"state": pull["state"], "base": {"ref": "main"}, "author_association": pull["association"],
                "head": {"ref": pull["branch"]}}
    if method == "PATCH" and parts[0] == "pulls" and len(parts) == 2:
        state["pulls"][parts[1]]["state"] = body["state"]
        return {}
    if parts[:2] == ["issues", "comments"] and len(parts) == 3:
        comment = state["comments"].get(parts[2])
        if comment is None:
            fail(404, "Not Found")
        if method == "GET":
            return {"user": {"login": comment["user"]}, "issue_url": "https://api.github.com/repos/%s/issues/%s"
                    % (REPO, comment["issue"])}
        if method == "PATCH":
            comment["body"] = body["body"]
            return {}
    if method == "POST" and parts[0] == "issues" and parts[2:] == ["comments"]:
        number = str(1000 + len(state["comments"]))
        state["comments"][number] = {"user": BOT, "issue": parts[1], "body": body["body"]}
        return {"id": int(number)}
    if method == "GET" and path.startswith("actions/workflows/test.yml/runs"):
        branch = path.split("branch=")[1].split("&")[0]
        return {"workflow_runs": [run for run in state["runs"] if run["head_branch"] == branch]}
    sys.stderr.write("the fake does not know %s %s\n" % (method, endpoint))
    sys.exit(99)


def workflow(arguments):
    assert arguments[0] == "run", arguments
    name, rest = arguments[1], arguments[2:]
    ref = rest[rest.index("--ref") + 1]
    inputs = [rest[i + 1] for i, word in enumerate(rest) if word == "-f"]
    state = load()
    state["dispatches"].append([name, ref] + inputs)
    save(state)


def main():
    arguments = sys.argv[1:]
    if arguments[:1] == ["api"]:
        api(arguments[1:])
    elif arguments[:1] == ["workflow"]:
        workflow(arguments[1:])
    else:
        sys.stderr.write("the fake does not know gh %s\n" % " ".join(arguments))
        sys.exit(99)


if __name__ == "__main__":
    main()
