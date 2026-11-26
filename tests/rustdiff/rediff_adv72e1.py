"""Re-diff S7.2e1 (the engine's capabilities for sends and turns) against a tag: the final's one command.

    python -X utf8 tests/rustdiff/rediff_adv72e1.py --reference v0.6.26

Says which of the ported Python files differ between v0.6.26 (what S7.2e1 ported) and the tag, rebuilds the example
`advturns` (release), then runs the seat's diffs (`diffs_advturns_*.py`: AdvTurnsSmallDiff, AdvTurnsRunsDiff) with the
tag as the reference (`run.py --build --reference TAG`). Exit 0 only when all are equal.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = "advanced/src/codex_auto_resume_advanced/engine/"
PORTED = [ENGINE + name + ".py" for name in ("silent", "everyconversation", "parallel", "sessions", "oncemore",
                                             "headless", "compact", "fallback", "retries")] + [
    # what the ported code reads beside them
    "advanced/src/codex_auto_resume_advanced/codex/headless.py", "advanced/src/codex_auto_resume_advanced/runtime.py",
    "advanced/src/codex_auto_resume_advanced/state/runs.py", "src/codex_auto_resume/machine.py",
    "src/codex_auto_resume/domain/gates.py"]
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAMILIES = ("AdvTurnsSmallDiff", "AdvTurnsRunsDiff")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    args = parser.parse_args(argv)
    tag = args.reference
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *PORTED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    from rustdiff import advturns
    advturns.build()
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag]
    for family in FAMILIES:
        command += ["-k", family]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
