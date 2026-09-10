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
import subprocess
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
    return drop_ko_suffix(text)


# A relative link target naming a Korean document. The lookahead rejects a scheme and the
# character class stops before a dot, so an absolute URL that merely ends in `.ko.md` - a
# file on somebody else's host - cannot be rewritten, and a target cannot run across a
# domain name. A first attempt rewrote the suffix wherever it appeared and edited prose
# inside a fenced code block.
KO_TARGET = r'(?!\w+:)((?:\./)?[\w/-]+)\.ko\.md'


def tracked_markdown(root: Path) -> list[Path]:
    """The Markdown files this branch actually ships, in a stable order.

    Tracked rather than globbed: `build/stage/` holds a staged copy of the payload after
    a release build, and sweeping that too made the generator report that it had rewritten
    code - which is precisely what `test_it_touches_no_code` exists to catch, and it did.
    """
    listing = subprocess.run(["git", "-C", str(root), "ls-files", "*.md"],
                             capture_output=True, text=True, encoding="utf-8")
    if listing.returncode != 0:
        raise SystemExit("ko_sync needs a git checkout; `git ls-files` failed here")
    return sorted((root / name) for name in listing.stdout.split() if (root / name).is_file())


def drop_ko_suffix(text: str) -> str:
    """Point links at the name a Korean document has on ko.

    On ko, `SECURITY.ko.md` *is* `SECURITY.md`, so a link written for main points at a
    file that is not there. Both halves of the link need rewriting:

    * the **target**, or the reader gets a dead link;
    * the **label**, because these documents write the filename as the link text, and
      sending a Korean reader to look for `SECURITY.ko.md` on a branch that has no such
      file is the same defect one layer up. Rewriting only the target is how the old ko
      branch came to link to itself for four releases.
    """
    text = re.sub(r'\]\(%s\)' % KO_TARGET, lambda found: "](%s.md)" % found.group(1), text)
    text = re.sub(r'href="%s"' % KO_TARGET, lambda found: 'href="%s.md"' % found.group(1), text)
    text = re.sub(r'\[%s\]' % KO_TARGET, lambda found: "[%s.md]" % found.group(1), text)
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

    # Every other page ships untouched *except* for links naming a Korean document.
    #
    # `not_yet_translated` pages are English on ko, which is accurate - but an English
    # page with a dead link is not. CHANGELOG.md linked to README.ko.md, a file this
    # very function had just deleted from the branch.
    for markdown in tracked_markdown(root):
        if markdown.name == Path(NOTICE_PATH).name:
            continue
        before = markdown.read_text(encoding="utf-8")
        after = drop_ko_suffix(before)
        if after == before:
            continue
        relative = markdown.relative_to(root).as_posix()
        if relative not in changed:
            changed.append(relative)
        if not check:
            markdown.write_text(after, encoding="utf-8")

    changed.append(NOTICE_PATH)
    if not check:
        notice = root / NOTICE_PATH
        notice.parent.mkdir(parents=True, exist_ok=True)
        notice.write_text(NOTICE, encoding="utf-8")
        broken = dead_links(root)
        if broken:
            raise SystemExit("the generated tree has links to files it does not contain:"
                             + "".join("\n  " + entry for entry in broken))
    return changed


# A relative link target: not a scheme, not a bare anchor, not a mail address.
LINK = re.compile(r'\]\(\s*(?!\w+:|#)([^)\s]+)|href="(?!\w+:|#)([^"]+)"')


def dead_links(root: Path) -> list[str]:
    """Relative links in the generated tree that point at nothing.

    The sync renames five documents and deletes their originals, so every link naming
    one has to be rewritten - and the way that goes wrong is silent: the page still
    renders, the link still looks like a link, and it 404s only for the reader. Checking
    the result is cheaper than remembering every page that might mention a Korean file.
    """
    missing = []
    for markdown in tracked_markdown(root):
        here = markdown.parent
        for found in LINK.finditer(markdown.read_text(encoding="utf-8")):
            target = (found.group(1) or found.group(2)).split("#")[0].strip()
            if not target:
                continue
            try:
                if (here / target).exists():
                    continue
            except OSError:
                pass
            missing.append("%s -> %s" % (markdown.relative_to(root).as_posix(), target))
    return missing


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
