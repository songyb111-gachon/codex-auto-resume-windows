"""Re-diff S7.4 (car-adv's measurement harness: `measure`, `evidence`, `runtime::measurement`) against a tag.

    python -X utf8 tests/rustdiff/rediff_s74.py --reference v0.6.26

S7.4 was ported from the v0.6.26 final. This says which of the ported Python files differ between the final and the
tag (`git diff --stat v0.6.26 TAG`), then runs every diff of `diffs_advmeasure.py` with the tag as the reference
(`run.py --build --reference TAG -k MeasureEvidenceDiff -k MeasureProbeDiff -k MeasureUsageDiff -k MeasureLookDiff`; the diffs build
the `advmeasure` example themselves). Exit 0 only when the diffs are equal. Never runs a real Codex.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ["advanced/src/codex_auto_resume_advanced/%s.py" % name for name in ("measure", "evidence", "runtime")] + [
    "advanced/src/codex_auto_resume_advanced/codex/credits.py", "advanced/src/codex_auto_resume_advanced/codex/protocol.py",
    "advanced/src/codex_auto_resume_advanced/vocabulary.py", "src/codex_auto_resume/diagnostics.py",
    "src/codex_auto_resume/mcp/tools.py", "src/codex_auto_resume/domain/ids.py"]
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAMILIES = ("MeasureEvidenceDiff", "MeasureProbeDiff", "MeasureUsageDiff", "MeasureLookDiff")


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
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag]
    for family in FAMILIES:
        command += ["-k", family]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
