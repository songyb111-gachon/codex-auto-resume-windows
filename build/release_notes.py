"""Extract one version's section from CHANGELOG.md, for the GitHub release body.

The changelog is the only place release notes are written, so the published notes cannot
drift from the repository's own history: there is nothing to keep in step.

It fails rather than inventing anything. A tag whose version has no changelog section is
a mistake worth stopping the release for, not something to paper over with a generated
list of commit subjects.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"


def section(text: str, version: str) -> str:
    """The body under `## v<version> ...`, up to the next top-level entry."""
    wanted = re.escape(str(version).lstrip("v"))
    pattern = re.compile(r"^##\s+v%s\b.*?$" % wanted, re.MULTILINE)
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
    body = section(text, args.version)
    if args.output:
        Path(args.output).write_text(body + "\n", encoding="utf-8")
    else:
        sys.stdout.write(body + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
