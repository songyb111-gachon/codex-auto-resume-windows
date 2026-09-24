"""Bring dev to main without its Korean documents, and main back to dev without losing them.

The owner's rule (2026-09-25): **dev** holds every document in both languages - `X.md` and its
Korean sibling `X.ko.md`, written and reviewed in the same commit - and **main**, the
repository's front page, the plugin's install route and the branch releases are tagged on, is
English only. The generated `ko` branch is built from main's code and the Korean sources of the
dev commit main came from (scripts/ko_sync.py --bring-korean).

So the two branches differ by the Korean files, on purpose, and neither may be fast-forwarded to
the other. Both directions are a merge with one correction, and this script is the only place
that correction is written:

    python scripts/promote.py to-main --title "v0.6.10 - ..." [--body-file notes.txt] [--dev origin/dev]
    python scripts/promote.py into-dev [--main origin/main]

* `to-main`, on a clean checkout of main: dev must already contain main (run `into-dev` on dev
  first, which also brings the compatibility data main received), so the merge cannot conflict.
  It merges dev, deletes every `*.ko.md`, commits with a `Korean-sources: <dev sha>` trailer, and
  then proves the result is dev's tree minus exactly those files and nothing else.
* `into-dev`, on a clean checkout of dev: merges main and puts back every Korean file dev had -
  a promotion's deletion reaches dev as a deletion, and a merge that took it would empty dev of
  Korean - then proves each one is byte for byte what it was.

Neither pushes. The person running it reads the result, runs what the branch's rules require,
and pushes - dev first, green, then main.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

TRAILER = "Korean-sources:"


class Refused(SystemExit):
    pass


def git(root: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8")
    if check and done.returncode != 0:
        raise Refused("git %s failed: %s" % (" ".join(args), (done.stderr or done.stdout).strip()))
    return done.stdout


def korean_blobs(root: Path, ref: str) -> dict:
    """{path: blob} for every `*.ko.md` in `ref`'s tree."""
    listed = git(root, "ls-tree", "-r", "-z", ref)
    blobs = {}
    for entry in filter(None, listed.split(chr(0))):
        meta, _, path = entry.partition("\t")
        if path.endswith(".ko.md"):
            blobs[path] = meta.split()[2]
    return blobs


def require_clean_branch(root: Path, branch: str) -> None:
    current = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if current != branch:
        raise Refused("check out %s first; this checkout is on %s" % (branch, current))
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise Refused("the working tree has changes; commit or restore them first")


def to_main(root: Path, dev: str, title: str, body: str = "") -> str:
    require_clean_branch(root, "main")
    dev_sha = git(root, "rev-parse", dev + "^{commit}").strip()
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", "HEAD", dev_sha],
                      capture_output=True).returncode != 0:
        raise Refused("%s does not contain main yet. On dev, run `promote.py into-dev` (which "
                      "keeps the Korean documents), push it, and let dev's CI pass first." % dev)
    korean = korean_blobs(root, dev_sha)
    if not korean:
        raise Refused("%s holds no Korean document, and dev must hold every one" % dev)
    git(root, "merge", "--no-ff", "--no-commit", dev_sha)
    try:
        git(root, "rm", "-q", "-f", "--", *sorted(korean))
        message = title.strip() + "\n\n" + (body.strip() + "\n\n" if body.strip() else "") + \
            "The Korean documents stay on dev; main is English only.\n\n%s %s\n" % (TRAILER, dev_sha)
        done = subprocess.run(["git", "-C", str(root), "commit", "-q", "-F", "-"], input=message,
                              capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            raise Refused("git commit failed: " + (done.stderr or done.stdout).strip())
    except BaseException:
        git(root, "merge", "--abort", check=False)
        raise
    difference = git(root, "diff", "--name-status", "--no-renames", dev_sha, "HEAD").splitlines()
    expected = sorted("D\t" + path for path in korean)
    if sorted(difference) != expected:
        unexpected = sorted(set(difference) - set(expected))
        raise Refused("main is not dev without its Korean documents; it also differs by: "
                      + "; ".join(unexpected) + ". Nothing is pushed - inspect and reset main.")
    if korean_blobs(root, "HEAD"):
        raise Refused("a Korean document is still on main")
    return git(root, "rev-parse", "HEAD").strip()


def into_dev(root: Path, main: str) -> str | None:
    require_clean_branch(root, "dev")
    main_sha = git(root, "rev-parse", main + "^{commit}").strip()
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", main_sha, "HEAD"],
                      capture_output=True).returncode == 0:
        return None                                       # dev already contains main
    before = korean_blobs(root, "HEAD")
    merged = subprocess.run(["git", "-C", str(root), "merge", "--no-ff", "--no-commit", main_sha],
                            capture_output=True, text=True, encoding="utf-8")
    try:
        conflicted = git(root, "diff", "--name-only", "--diff-filter=U").split()
        other = [path for path in conflicted if not path.endswith(".ko.md")]
        if other:
            raise Refused("merging main into dev conflicts outside the Korean documents: "
                          + ", ".join(other) + ". Resolve that by hand.")
        if merged.returncode != 0 and not conflicted:
            raise Refused("git merge failed: " + (merged.stderr or merged.stdout).strip())
        # Every Korean file dev had, exactly as dev had it: the promotion deleted them on main,
        # and a merge that took the deletion would take them off dev.
        if before:
            git(root, "checkout", "HEAD", "--", *sorted(before))
        # A Korean file main somehow added and dev never had is not dev's to keep.
        added = sorted(set(korean_blobs_index(root)) - set(before))
        if added:
            git(root, "rm", "-q", "-f", "--", *added)
        message = ("Take main into dev; the Korean documents stay\n\n"
                   "Merges %s. Every *.ko.md dev had is kept as it was: main is English only, "
                   "and its deletions of them are not dev's.\n" % main_sha)
        done = subprocess.run(["git", "-C", str(root), "commit", "-q", "-F", "-"], input=message,
                              capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            raise Refused("git commit failed: " + (done.stderr or done.stdout).strip())
    except BaseException:
        git(root, "merge", "--abort", check=False)
        raise
    after = korean_blobs(root, "HEAD")
    if after != before:
        raise Refused("dev's Korean documents changed in the merge; nothing is pushed - inspect "
                      "and reset dev")
    return git(root, "rev-parse", "HEAD").strip()


def korean_blobs_index(root: Path) -> dict:
    listed = git(root, "ls-files", "-s", "-z")
    blobs = {}
    for entry in filter(None, listed.split(chr(0))):
        meta, _, path = entry.partition("\t")
        if path.endswith(".ko.md"):
            blobs[path] = meta.split()[1]
    return blobs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Move work between dev (both languages) and "
                                                 "main (English only).")
    parser.add_argument("--root", default=".", help="the checkout to act on")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("to-main", help="on main: merge dev, without its Korean documents")
    up.add_argument("--dev", default="origin/dev")
    up.add_argument("--title", required=True, help="the promotion commit's first line")
    up.add_argument("--body-file", help="a file whose text follows the title")
    down = sub.add_parser("into-dev", help="on dev: merge main, keeping the Korean documents")
    down.add_argument("--main", default="origin/main")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "to-main":
        body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
        sha = to_main(root, args.dev, args.title, body)
        print("main is now %s: dev without its Korean documents. Push it once dev is green." % sha[:12])
    else:
        sha = into_dev(root, args.main)
        print("dev already contains main; nothing to do" if sha is None
              else "dev is now %s, with main in it and its Korean documents as they were." % sha[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
