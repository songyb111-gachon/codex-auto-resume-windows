"""Extract one version's section from docs/CHANGELOG.md, for the GitHub release body.

The changelog is the only place release notes are written, so the published notes cannot
drift from the repository's own history: there is nothing to keep in step.

It fails rather than inventing anything. A tag whose version has no changelog section is
a mistake worth stopping the release for, not something to paper over with a generated
list of commit subjects.

The changelog lives in docs/ since the front page was tidied, and its relative links are
written from there (`GUIDE.md`, `../README.md`). A release body is not in docs/: GitHub
resolves a relative link in it from the repository's root. So each relative link is rebased
to the root on the way out - left as written, every link in every release body from then on
would have pointed one folder too high.
"""
from __future__ import annotations

import argparse
import posixpath
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "docs" / "CHANGELOG.md"
# The folder the changelog's relative links are written from, as the root sees it.
WRITTEN_FROM = "docs"

CODE = re.compile("(```.*?```|~~~.*?~~~|`[^`\n]*`)", re.S)
LINK = re.compile(r'(\]\(\s*)([^)\s]+)(\s*\))|((?:href|src)=")([^"]+)(")')


def rebase(body: str, folder: str = WRITTEN_FROM) -> str:
    """Relative links written from `folder`, re-expressed from the repository's root. Absolute
    URLs, anchors, and anything inside code are left as they are."""
    def fix(target: str) -> str:
        if re.match(r"^[a-zA-Z][\w+.-]*:", target) or target.startswith(("#", "/")):
            return target
        path, hashmark, fragment = target.partition("#")
        if not path:
            return target
        rooted = posixpath.normpath(posixpath.join(folder, path))
        if rooted.startswith(".."):
            return target
        return rooted + (hashmark + fragment if hashmark else "")

    def one(found):
        if found.group(2) is not None:
            return found.group(1) + fix(found.group(2)) + found.group(3)
        return found.group(4) + fix(found.group(5)) + found.group(6)

    return "".join(part if index % 2 else LINK.sub(one, part)
                   for index, part in enumerate(CODE.split(body)))


def section(text: str, version: str) -> str:
    """The body under `## v<version> ...`, up to the next top-level entry.

    A pre-release's heading - `## v0.6.6-beta` - is an entry of its own, and never the release's:
    the version has to end where the heading's version does, so neither a suffix nor a longer
    number is read as a match, wherever in the file the pre-release sits."""
    wanted = re.escape(str(version).lstrip("v"))
    pattern = re.compile(r"^##\s+v%s(?![\w.-]).*?$" % wanted, re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise SystemExit("CHANGELOG.md has no section for v%s" % version)
    rest = text[match.end():]
    following = re.search(r"^##\s+v", rest, re.MULTILINE)
    body = rest[:following.start()] if following else rest
    body = body.strip("\n")
    if not body:
        raise SystemExit("the CHANGELOG.md section for v%s is empty" % version)
    return body


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Print a version's changelog section.")
    parser.add_argument("version", help="version, with or without a leading v")
    parser.add_argument("--changelog", default=str(CHANGELOG))
    parser.add_argument("--output", help="write here instead of standard output")
    args = parser.parse_args(argv)

    text = Path(args.changelog).read_text(encoding="utf-8")
    body = rebase(section(text, args.version))
    if args.output:
        Path(args.output).write_text(body + "\n", encoding="utf-8")
    else:
        # The changelog contains em dashes and other punctuation a legacy console
        # codepage cannot represent, and printing it should not depend on which
        # locale the machine happens to use.
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
        sys.stdout.write(body + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
