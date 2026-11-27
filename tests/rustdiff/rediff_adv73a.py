"""Re-diff car-adv's control cards and surfaces (S7.3a) against a tag: the one command the v0.6.26 final is checked with.

    python -X utf8 tests/rustdiff/rediff_adv73a.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_adv73a.py                      # reference.TAG

S7.3a was ported from the v0.6.26 final's own sources. This says, in order: which of the ported Python files differ between
v0.6.26 (the tree the seat was written from) and the tag (`git diff --stat`) - surfaces.py and control/{resets, sendnow,
keepgoing, steer, prompts, chat, conversations, follow, earlycheck, opencodex, fleet, account}.py - and then runs the
seat's diff (`diffs_advsurface`, through the advanced proxy: run.py builds advserve) with the tag as the reference
(`run.py --build --reference TAG`). Exit 0 only when every diff is equal.

A changed file is listed, not judged: the diffs are what says whether the port still equals it.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADVANCED = "advanced/src/codex_auto_resume_advanced/"
PORTED = ([ADVANCED + "surfaces.py"]
          + [ADVANCED + "control/%s.py" % name for name in ("resets", "sendnow", "keepgoing", "steer", "prompts", "chat",
                                                            "conversations", "follow", "earlycheck", "opencodex", "fleet",
                                                            "account")])
BASE = "v0.6.26"
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
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *PORTED], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
                             creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag, "-k",
                            "diffs_advsurface"], cwd=ROOT, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
