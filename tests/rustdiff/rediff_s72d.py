"""Re-diff S7.2d (the usage meter, the wrap-up, the forced stop, the reset actions, the early reset, the capacity retry and
their words) against a tag: the final's one command.

    python -X utf8 tests/rustdiff/rediff_s72d.py --reference v0.6.26

S7.2d was ported from the v0.6.26 final itself (D17; `engine/usage.py` is the final's). This says, in order: which of
the ported Python files differ between the final and the tag (`git diff --stat v0.6.26 TAG`), then runs every diff of
`diffs_advusage_*.py` with the tag as the reference on the bundled interpreter (`run.py --build --reference TAG
--reference-python bundled -k diffs_advusage`; the diffs build the `advusage` example when it is missing, set
CODEX_AR_ADVUSAGE_EXE to use another build). Exit 0 only when all are clean.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = ("usage", "usagestop", "resetmessage", "resetwatch", "credits", "earlyreset", "wrapwords", "continued",
          "capacity")
PORTED = (["advanced/src/codex_auto_resume_advanced/engine/%s.py" % name for name in ENGINE]
          + ["advanced/src/codex_auto_resume_advanced/codex/%s.py" % name for name in ("credits", "inuse", "ipc")]
          + ["advanced/src/codex_auto_resume_advanced/state/%s.py" % name
             for name in ("meter", "continuations", "resets", "choices")]
          + ["src/codex_auto_resume/continuation.py", "src/codex_auto_resume/domain/plughands.py"])
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
               "--reference-python", "bundled", "-k", "diffs_advusage"]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
