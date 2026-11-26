"""Re-diff car-engine and car-scheduler (S4.1) against a tag: the one command the v0.6.26 final is checked with.

    python -X utf8 tests/rustdiff/rediff_engine.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_engine.py                      # reference.TAG (v0.6.26-beta.2 until the final)

S4.1 was ported from v0.6.26-beta.2, and none of engine/ had changed on dev after that tag when it was ported (the main
session's check: only advanced codex/inuse.py, advanced engine/usage.py, advanced plug.py, control/watcher.py,
domain/usage.py, machine.py, runtime/app.py, ui/popup/model.py, gui/*, scripts/ and build/ moved). This says which of
the ported Python files - every module of engine/, and codexsim, which builds the traces' worlds - differ between
v0.6.26-beta.2 and the tag (`git diff --stat`, so a change is seen even where no scenario reaches it), then runs the
engine traces, and the plug's (a scripted plug on both sides, diffs_engine_plug.py), with the tag as the reference
(`run.py --build --reference TAG -k EngineTraceDiff -k EnginePlugDiff`). Exit 0 only when the
diffs are equal; a file that changed is printed, not failed on - the traces decide, and a changed file with equal traces
is a file the corpus should learn a scenario for.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = ("__init__", "announce", "compaction", "delivery", "detect", "dispatch", "foropen", "freshness", "guard",
          "impossible", "kinds", "launches", "notices", "options", "outcome", "plugrecords", "reconcile",
          "recordchannel", "relaxed", "resend", "routes", "storeview", "tosession")
# And what the plug traces (diffs_engine_plug.py) lean on: the plug itself and the claim's plug branches in the store.
PORTED = (tuple("src/codex_auto_resume/engine/%s.py" % name for name in ENGINE)
          + ("tests/codexsim.py", "src/codex_auto_resume/domain/plug.py", "src/codex_auto_resume/store/claims.py",
             "src/codex_auto_resume/store/ledger.py", "src/codex_auto_resume/store/validate.py"))
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
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *PORTED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
                            "-k", "EngineTraceDiff", "-k", "EnginePlugDiff"], cwd=ROOT, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW).returncode
    print("rediff against %s: engine traces %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
