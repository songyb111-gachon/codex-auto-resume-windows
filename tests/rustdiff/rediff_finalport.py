"""Re-diff the final-port seat's rows (FINAL-DELTA.md) against a tag: the one command they are checked with.

    python -X utf8 tests/rustdiff/rediff_finalport.py --reference v0.6.26

The final-port seat ported the rows of the v0.6.26 final whose crates existed (HistoryNotYet and the fresh home's checks,
the engine's catch, the package engines and the binding, get_status's usage rule) from the v0.6.26 tag itself. This says
which of those Python files differ between v0.6.26 and the tag (`git diff --stat`: a later tag that moves one is seen
even where no diff reaches it), then runs the diffs that hold them (`run.py --build --reference TAG` with the classes
below). Exit 0 only when the diffs are equal; a file that changed is printed, not failed on - the diffs decide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ("codex/errors.py", "codex/__init__.py", "codex/schema.py", "codex/history.py", "compat/probes.py",
          "compat/views.py", "codex/pairing.py", "win/kernel.py", "windows.py", "engine/detect.py",
          "control/watcher.py", "domain/usage.py")
BASE = "v0.6.26"
DIFFS = ("test_schema_variants", "test_source_and_api_checks", "EngineReview6", "StatusMeterDiff",
         "PackageEnginesDiff", "ViewsDiff")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    args = parser.parse_args(argv)
    tag = args.reference
    paths = ["src/codex_auto_resume/" + each for each in PORTED]
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *paths], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag]
    for each in DIFFS:
        command += ["-k", each]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
