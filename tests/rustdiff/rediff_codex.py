"""Re-diff car-codex's readers (S3.2) against a tag: the one command the v0.6.26 final is checked with.

    python -X utf8 tests/rustdiff/rediff_codex.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_codex.py                      # reference.TAG (v0.6.26-beta.2 until the final)

S3.2 was ported from v0.6.26-beta.2, and none of its modules had changed on dev after that tag when it was ported (PLAN
5.1 lists `codex/` as moving: `git log v0.6.26-beta.2..origin/dev -- <file>` was empty for each). This says, in order:
which of the ported Python files differ between v0.6.26-beta.2 and the tag (`git diff --stat`, so a change is seen even
where no diff reaches it); whether the generated Unicode table is still what the interpreter gives
(`gen_codex.py --check`); and then runs every `diffs_codex_*` diff with the tag as the reference
(`run.py --build --reference TAG -k diffs_codex`). Exit 0 only when all three are clean; a file that changed is printed,
not failed on - the diffs decide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ("codex/__init__.py", "codex/errors.py", "codex/paths.py", "codex/schema.py", "codex/history.py", "codex/values.py",
          "codex/labels.py", "codex/payload.py", "codex/rollout.py", "codex/chains.py", "codex/eligibility.py",
          "codex/workspace.py", "codex/usage.py", "domain/ids.py", "domain/skips.py", "domain/states.py", "guards.py", "projects.py",
          "homes.py", "failures.py", "compat/model.py")
BASE = "v0.6.26-beta.2"
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
    paths = ["src/codex_auto_resume/" + each for each in PORTED]
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *paths], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    status = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "gen_codex.py"), "--check"], cwd=ROOT,
                            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
                            "-k", "diffs_codex"], cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: generated table %s, diffs %s" % (tag, "current" if status == 0 else "STALE",
                                                               "equal" if diffs == 0 else "DIFFER"))
    return 0 if status == 0 and diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
