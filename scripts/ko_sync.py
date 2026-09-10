"""Turn a checkout of `main` into the `ko` branch's tree.

`ko` used to be a fork. It carried its own copy of the engine, the installer, the GUI,
the workflows and the tests, kept in step by someone remembering to merge - and by v0.5.4
it was three releases behind, still telling Korean readers that the tool made no network
request and that installing meant downloading a release archive. Nobody decided that; it
is simply what a second copy of a codebase does.

So there is no second copy any more. The code on ko is main's code at a tested commit, and
the only difference is which language the documents are written in: each Korean file on
main replaces its English sibling, and the Korean original is removed so the branch has
one document per subject rather than two.

    python scripts/ko_sync.py [--root .] [--check]

`--check` reports what would change and writes nothing, which is what the test suite runs.

Deliberately not a translator. Every Korean sentence on ko was written by a person and is
reviewable on main; nothing here generates prose, and nothing here calls a service.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

MAPPING_NAME = "scripts/ko_branch.json"
NOTICE_PATH = ".github/GENERATED-BRANCH.md"

NOTICE = """# This branch is generated

`ko` is built from `main` by `scripts/ko_sync.py` every time main's tests pass, and it is
force-updated. Nothing here is edited directly: an edit made on this branch is lost at the
next sync, without a conflict and without a warning.

* The code, the installer, the workflows and the tests are main's, at the commit named in
  the sync commit message.
* The documents are main's Korean ones - `README.ko.md` becomes `README.md`, and so on.
  `scripts/ko_branch.json` on main is the mapping, and its `not_yet_translated` list says
  which pages are still English here.

To change something on this branch, change it on `main`: the English source for code, or
the `.ko.md` file for Korean prose.
"""


def load_mapping(root: Path) -> dict:
    return json.loads((root / MAPPING_NAME).read_text(encoding="utf-8"))


def relink(text: str, english: str, base: str) -> str:
    """Point "the English version" at main, now that this file has taken its name.

    On main, `README.ko.md` links to `README.md` next to it. On ko that same file *is*
    `README.md`, so the link would point at itself - which is exactly what the old ko
    branch did, for four releases. Relative links to the English sibling therefore become
    absolute links to main's copy, which is the only place it still exists.
    """
    name = re.escape(english)
    text = re.sub(r'href="(?:\./)?%s"' % name, 'href="%s%s"' % (base, english), text)
    text = re.sub(r'\]\((?:\./)?%s\)' % name, '](%s%s)' % (base, english), text)
    # And links between the Korean documents themselves. On ko, `SECURITY.ko.md` *is*
    # `SECURITY.md`, so a link written for main would point at a file that is not there.
    text = re.sub(r'([\w/.-]+)\.ko\.md', lambda found: found.group(1) + '.md', text)
    return text


def build(root: Path, *, check: bool = False) -> list[str]:
    """Rewrite a checkout of main into ko's tree. Returns what it changed.

    Always run against a checkout of *main*: the Korean sources it reads only exist
    there. Running it twice over the same tree is not idempotent and is not meant to be -
    the workflow starts from a fresh checkout of a tested commit every time.
    """
    mapping = load_mapping(root)
    base = mapping["english_on_main"]
    changed = []
    for source, target in mapping["documents"].items():
        origin, destination = root / source, root / target
        if not origin.is_file():
            raise SystemExit("%s is listed in %s but does not exist; run this against a "
                             "checkout of main" % (source, MAPPING_NAME))
        wanted = relink(origin.read_text(encoding="utf-8"), destination.name, base)
        changed.append(target)
        if check:
            continue
        destination.write_text(wanted, encoding="utf-8")
        origin.unlink()

    changed.append(NOTICE_PATH)
    if not check:
        notice = root / NOTICE_PATH
        notice.parent.mkdir(parents=True, exist_ok=True)
        notice.write_text(NOTICE, encoding="utf-8")
    return changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the ko branch tree from main.")
    parser.add_argument("--root", default=".", help="checkout to rewrite in place")
    parser.add_argument("--check", action="store_true",
                        help="report what would change and write nothing")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    changed = build(root, check=args.check)
    for name in changed:
        print(("would replace " if args.check else "replaced ") + name)
    if not changed:
        print("nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
