"""Re-diff what the second review's fixes (REVIEW-int5, seat fix5) hold against a tag: the command for the v0.6.26 final.

    python -X utf8 tests/rustdiff/rediff_review5.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_review5.py                      # reference.TAG (v0.6.26-beta.2 until the final)

The fixes were made against v0.6.26-beta.2. This says which of the Python files they follow differ between
v0.6.26-beta.2 and the tag (`git diff --stat`, so a change is seen even where no diff reaches it), whether the embedded
catalogs are still the tag's (`gen_catalogs.py --check`, the tag's LF text against the LF copies: a CRLF checkout is no
difference), and then runs the diffs these fixes added or changed with the tag as the reference: the float texts, the
words, the classifier's policy and continuation (the non-finite cases and the product's clock, the zone "local"), and
car-store's (BLOBs, sign-ins, no settings row, non-finite caps, and the store diffs whose channel now carries the float
tag). Exit 0 only when all are clean; a changed file is printed, not failed on - the diffs decide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLLOWED = ("ui/words.py", "l10n.py", "quiet.py", "continuation.py", "ladder.py", "power.py", "store/__init__.py",
            "store/session.py", "store/legacy.py", "store/watcher.py", "store/ledger.py", "store/claims.py",
            "store/validate.py", "store/policy.py", "domain/usage.py", "locales")
BASE = "v0.6.26-beta.2"
DIFFS = ("FloatTextDiff", "diffs_leaves_words", "diffs_classify_policy", "diffs_classify_continuation", "diffs_classify_clock",
         "diffs_store")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=None)
    args = parser.parse_args(argv)
    tag = args.reference
    if tag is None:
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
        from rustdiff import reference
        tag = reference.TAG
    paths = ["src/codex_auto_resume/" + each for each in FOLLOWED]
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *paths], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("followed files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    catalogs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "gen_catalogs.py"), "--check"], cwd=ROOT,
                              stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag]
    for each in DIFFS:
        command += ["-k", each]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: catalogs %s, diffs %s" % (tag, "current" if catalogs == 0 else "STALE",
                                                        "equal" if diffs == 0 else "DIFFER"))
    return 0 if catalogs == 0 and diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
