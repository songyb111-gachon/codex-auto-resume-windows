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


def tracked_markdown(root: Path, expected_missing=()) -> list[Path]:
    """The Markdown files this branch actually ships, in a stable order.

    Tracked rather than globbed: `build/stage/` holds a staged copy of the payload after
    a release build, and sweeping that too made the generator report that it had rewritten
    code - which is precisely what `test_it_touches_no_code` exists to catch, and it did.
    """
    listing = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
                             capture_output=True, text=True, encoding="utf-8")
    if listing.returncode != 0:
        raise SystemExit("ko_sync needs a git checkout; `git ls-files` failed here")
    # NUL-separated, because git prints a path containing a space raw and a non-ASCII
    # path C-quoted. Splitting on whitespace turned `a b.md` into two names and a Korean
    # filename into a quoted string, none of which is a file - and the `is_file()` filter
    # below then dropped them in exactly the same silence as the files this really is
    # meant to skip.
    names = [name for name in listing.stdout.split(chr(0)) if name]
    missing = [name for name in names if not (root / name).is_file()]
    unexplained = [name for name in missing if name not in expected_missing]
    if unexplained:
        raise SystemExit("git lists Markdown this checkout does not have:"
                         + "".join(chr(10) + "  " + entry for entry in unexplained))
    return sorted((root / name) for name in names if (root / name).is_file())


# Fenced blocks and inline code spans, captured so `re.split` keeps them: an odd index in
# the result is code and is passed through untouched. The label rewrite below is a bare
# `[...]` with no link syntax around it, so without this it edits documentation *about*
# these filenames - and the guard test that was supposed to cover fences built its fence
# out of a filename none of the patterns could match, so it passed either way.
CODE = re.compile("(```.*?```|~~~.*?~~~|`[^`" + chr(10) + "]*`)", re.S)


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
    def rewrite(chunk: str) -> str:
        chunk = re.sub(r'\]\(%s\)' % KO_TARGET, lambda f: "](%s.md)" % f.group(1), chunk)
        chunk = re.sub(r'href="%s"' % KO_TARGET, lambda f: 'href="%s.md"' % f.group(1), chunk)
        return re.sub(r'\[%s\]' % KO_TARGET, lambda f: "[%s.md]" % f.group(1), chunk)

    return "".join(part if index % 2 else rewrite(part)
                   for index, part in enumerate(CODE.split(text)))


def keep_english_anchor(text: str, targets, base: str) -> str:
    """Send an anchored link into a translated page to main's English copy instead.

    A page that stays English on ko may link into a document that does not: SUPPORT.md
    points at README.md's "please read this limitation first" heading. On ko that path is
    still valid and the heading is Korean, so the link lands on the right file at the
    wrong place - the one kind of breakage a path check cannot see, and the reason
    `dead_links` now reads fragments.

    Only anchored links are moved. Without a fragment the Korean page is the better
    destination for a Korean reader, which is the whole point of the branch.
    """
    for target in targets:
        pattern = r'\]\((?:\./)?%s#([\w%%-]+)\)' % re.escape(target)
        text = re.sub(pattern,
                      lambda found: "](%s%s#%s)" % (base, target, found.group(1)), text)
    return text


def review_digest(root: Path, english: str) -> str:
    """What a Korean document was translated from, as a hash of the English text.

    Read as text so a checkout's line endings cannot change the answer - the same reason
    the screenshot manifest normalises before hashing.
    """
    import hashlib
    body = (root / english).read_text(encoding="utf-8")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def stale_translations(root: Path) -> list[str]:
    """English documents that moved since their Korean counterpart was last reviewed."""
    mapping = load_mapping(root)
    recorded = mapping.get("reviewed", {})
    stale = []
    for korean, english in sorted(mapping["documents"].items()):
        was = recorded.get(english)
        if was is None:
            stale.append("%s has no recorded review point" % english)
        elif was != review_digest(root, english):
            stale.append("%s changed after %s was last reviewed" % (english, korean))
    return stale


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
    unlinked = () if check else tuple(mapping["documents"])
    for markdown in tracked_markdown(root, unlinked):
        if markdown.name == Path(NOTICE_PATH).name:
            continue
        before = markdown.read_text(encoding="utf-8")
        after = keep_english_anchor(before, mapping["documents"].values(), base)
        after = drop_ko_suffix(after)
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
        broken = dead_links(root, tuple(mapping["documents"]))
        if broken:
            raise SystemExit("the generated tree has links to files it does not contain:"
                             + "".join("\n  " + entry for entry in broken))
    return changed


# A relative link target: not a scheme, not a bare anchor, not a mail address.
LINK = re.compile(r'\]\(\s*(?!\w+:|#)([^)\s]+)|href="(?!\w+:|#)([^"]+)"')


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens.

    Korean survives unchanged, which is the case that matters here.
    """
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text).strip("-")


def anchor_exists(path: Path, fragment: str) -> bool:
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return True                      # unreadable: not this check's business
    wanted = fragment.strip().lower()
    for line in body.splitlines():
        found = re.match(r"#{1,6}\s+(.*)$", line)
        if found and slug(found.group(1)) == wanted:
            return True
    return False


def dead_links(root: Path, expected_missing=()) -> list[str]:
    """Relative links in the generated tree that point at nothing.

    The sync renames five documents and deletes their originals, so every link naming
    one has to be rewritten - and the way that goes wrong is silent: the page still
    renders, the link still looks like a link, and it 404s only for the reader. Checking
    the result is cheaper than remembering every page that might mention a Korean file.
    """
    missing = []
    for markdown in tracked_markdown(root, expected_missing):
        here = markdown.parent
        for found in LINK.finditer(markdown.read_text(encoding="utf-8")):
            raw = (found.group(1) or found.group(2)).strip()
            target, _, fragment = raw.partition("#")
            if not target:
                continue
            destination = here / target
            try:
                if not destination.exists():
                    missing.append("%s -> %s" % (markdown.relative_to(root).as_posix(), target))
                    continue
            except OSError:
                missing.append("%s -> %s" % (markdown.relative_to(root).as_posix(), target))
                continue
            # The fragment is the half this sync invalidates. Replacing an English page
            # with a Korean one keeps every path valid and kills every anchor into it,
            # so checking only the path is checking the half that cannot break.
            if fragment and destination.suffix == ".md" and not anchor_exists(destination, fragment):
                missing.append("%s -> %s#%s"
                               % (markdown.relative_to(root).as_posix(), target, fragment))
    return missing


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the ko branch tree from main.")
    parser.add_argument("--root", default=".", help="checkout to rewrite in place")
    parser.add_argument("--check", action="store_true",
                        help="report what would change and write nothing")
    parser.add_argument("--reviewed", nargs="+", metavar="ENGLISH",
                        help="record that these English documents' translations are current")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.reviewed:
        import json as _json
        mapping = load_mapping(root)
        english = set(mapping["documents"].values())
        unknown = [name for name in args.reviewed if name not in english]
        if unknown:
            raise SystemExit("not translated documents: " + ", ".join(unknown))
        mapping.setdefault("reviewed", {})
        for name in args.reviewed:
            mapping["reviewed"][name] = review_digest(root, name)
            print("reviewed " + name)
        (root / MAPPING_NAME).write_text(
            _json.dumps(mapping, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")
        return 0
    changed = build(root, check=args.check)
    for name in changed:
        print(("would replace " if args.check else "replaced ") + name)
    if not changed:
        print("nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
