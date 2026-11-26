"""Re-diff S7.2a (the plug, the runtime, the core side of the plug) against a tag: the final's one command.

    python -X utf8 tests/rustdiff/rediff_adv72a.py --reference v0.6.26

Says which of the ported Python files differ between v0.6.26 (what S7.2a ported) and the tag, then runs the plug's
runtime diffs (`diffs_advplug.py`, AdvPlugDiff) and the engine's plug traces, which hold the standard edition's equality
the core side must not move (`diffs_engine_plug.py` EnginePlugDiff, `EngineTraceDiff`), with the tag as the reference
(`run.py --build --reference TAG`; advplug builds `advtrace` when it is missing). Exit 0 only when all are equal.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADVANCED = "advanced/src/codex_auto_resume_advanced/"
PORTED = ([ADVANCED + name for name in ("plug.py", "runtime.py", "credentials.py", "win/dpapi.py", "__init__.py",
                                        "engine/hookclaims.py", "report/__init__.py", "engine/continued.py",
                                        "engine/resetmessage.py", "engine/promptqueue.py", "engine/chat.py",
                                        "engine/foropen.py")]
          + ["src/codex_auto_resume/domain/plug.py", "src/codex_auto_resume/domain/plughands.py",
             "src/codex_auto_resume/engine/storeview.py", "src/codex_auto_resume/engine/__init__.py",
             "src/codex_auto_resume/store/plugclaims.py", "src/codex_auto_resume/store/ledger.py"])
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAMILIES = ("AdvPlugDiff", "EnginePlugDiff", "EngineTraceDiff")


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
