"""Re-diff the S7.2c remainder (seat adv72d: win/stopflag, win/waketimer, codex/tokens, codex/wmi_escape,
protocol.Session/submitted, codex/headless, codex/ipc, turns.booted_of) against a tag: the final's one command.

    python -X utf8 tests/rustdiff/rediff_adv72d.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_adv72d.py                        # the advcodex diffs' own default, v0.6.26

The seat ported from the v0.6.26 final (D17). This says which of the ported Python files differ between the final and
the tag (`git diff --stat v0.6.26 TAG`), then runs every diff of `diffs_advcodex_{win,booted,tokens,wmi,session,
headless,ipc}.py` with the tag as the reference (`run.py --build --reference TAG -k WinDiff -k BootedDiff -k
TokensDiff -k WmiDiff -k SessionDiff -k HeadlessDiff -k IpcDiff`; the build makes the `advcodex` and `advfake` examples
and car-harness's `car-fake-codex`). Exit 0 only when all are clean. Nothing real is asked of Windows: the timer, the
power settings, the stop event and the WMI chain are stand-ins, and the IPC pipe is the test's own.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADVANCED = "advanced/src/codex_auto_resume_advanced/"
PORTED = ([ADVANCED + "win/%s.py" % name for name in ("stopflag", "waketimer")]
          + [ADVANCED + "codex/%s.py" % name for name in ("tokens", "wmi_escape", "protocol", "headless", "ipc", "turns")]
          + ["advanced/tests/fakeipc.py", "src/codex_auto_resume/win/sync.py", "src/codex_auto_resume/codex/rollout.py",
             "src/codex_auto_resume/codex/transport.py", "src/codex_auto_resume/codex/appserver.py",
             "src/codex_auto_resume/codex/pairing.py", "src/codex_auto_resume/projects.py",
             "src/codex_auto_resume/homes.py", "src/codex_auto_resume/pwsh.py", "src/codex_auto_resume/startup.py",
             "src/codex_auto_resume/store/watcher.py", "src/codex_auto_resume/continuation.py"])
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAMILIES = ("WinDiff", "BootedDiff", "TokensDiff", "WmiDiff", "SessionDiff", "HeadlessDiff", "IpcDiff")


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
