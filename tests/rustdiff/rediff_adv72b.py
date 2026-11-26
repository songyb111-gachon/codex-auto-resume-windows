"""Re-diff seat S7.2b (the saved accounts: codex/authfile, codex/account, codex/swap, codex/restart, win/appclose,
engine/account, engine/autoswitch, and the profiles' host) against a tag: the final's one command.

    python -X utf8 tests/rustdiff/rediff_adv72b.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_adv72b.py                        # the advaccount diffs' own default, v0.6.26

The seat ported from the v0.6.26 final (D17). This says which of the ported Python files differ between the final and
the tag (`git diff --stat v0.6.26 TAG`), then runs every diff of `diffs_advaccount_{pure,files,swap,engines}.py` with the
tag as the reference (`run.py --build --reference TAG -k AccountPureDiff -k StoreModeDiff -k AppCloseDiff -k RestartDiff -k
SwapPureDiff -k AuthFileActsDiff -k SwitchDiff -k RecoverDiff -k ReadAndSaveDiff -k AccountWatchDiff -k
AutoSwitchDiff`; the diffs build car-adv's `advaccount` example themselves). Exit 0 only when all are clean. Nothing
real is asked: every sign-in file is synthetic and every Windows hand a scripted stand-in.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADVANCED = "advanced/src/codex_auto_resume_advanced/"
PORTED = ([ADVANCED + "codex/%s.py" % name for name in ("authfile", "account", "swap", "restart")]
          + [ADVANCED + "win/appclose.py", ADVANCED + "engine/account.py", ADVANCED + "engine/autoswitch.py",
             ADVANCED + "profiles.py", "src/codex_auto_resume/codex/pairing.py", "src/codex_auto_resume/codex/usage.py",
             "src/codex_auto_resume/domain/usage.py", "src/codex_auto_resume/poweraction.py",
             "src/codex_auto_resume/codex_link.py"])
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAMILIES = ("AccountPureDiff", "StoreModeDiff", "AppCloseDiff", "RestartDiff", "SwapPureDiff", "AuthFileActsDiff",
            "SwitchDiff", "RecoverDiff", "ReadAndSaveDiff", "AccountWatchDiff", "AutoSwitchDiff")


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
