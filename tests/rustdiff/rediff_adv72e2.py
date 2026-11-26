"""Re-diff seat S7.2e2 (time, fleet and the weekly look: `engine/{supervise,powertasks,wake,analytics,updatecheck,fleet,
anchor}.py`) against a tag: the final's one command.

    python -X utf8 tests/rustdiff/rediff_adv72e2.py --reference v0.6.26

The seat ported from the v0.6.26 final (D17). This says which of the ported Python files (and the core and advanced
files they read through) differ between the final and the tag (`git diff --stat v0.6.26 TAG`), then runs every diff of
`diffs_advtime_*.py` with the tag as the reference (`run.py --reference TAG -k ...`; the diffs build car-adv's
`advtime` example themselves). Exit 0 only when all are clean. Nothing real is asked of Windows or a network: the stop
flag, the wake timer, the update check, the usage sessions and the request are stand-ins; the request is a child the
test starts itself.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADVANCED = "advanced/src/codex_auto_resume_advanced/"
PORTED = ([ADVANCED + "engine/%s.py" % name for name in ("supervise", "powertasks", "wake", "analytics",
                                                           "updatecheck", "fleet", "anchor")]
          + [ADVANCED + name for name in ("win/stopflag.py", "win/waketimer.py", "codex/tokens.py",
                                          "codex/credits.py", "codex/inuse.py", "state/choices.py",
                                          "state/restarts.py", "state/analytics.py", "state/meter.py")]
          + ["src/codex_auto_resume/statusfile.py", "src/codex_auto_resume/domain/public.py",
             "src/codex_auto_resume/domain/ids.py", "src/codex_auto_resume/domain/states.py"])
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAMILIES = ("SuperviseDiff", "PowerTasksDiff", "WakeDiff", "AnalyticsDiff", "UpdateCheckDiff", "FleetPureDiff",
            "FleetDiff", "AnchorPureDiff", "AnchorTomlDiff", "AnchorCodeDiff")


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
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--reference", tag]
    for family in FAMILIES:
        command += ["-k", family]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
