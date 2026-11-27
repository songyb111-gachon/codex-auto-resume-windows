"""Re-diff the host shell and the engine join (S6.2b) against a tag: the one command they are checked with again.

    python -X utf8 tests/rustdiff/rediff_host.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_host.py --reference <a later tag of the archived repository>

S6.2b was ported from the v0.6.26 final. This says which of the files the host shell and the engine join follow differ
between v0.6.26 and the tag (`git diff --stat`, so a change is seen even where no diff reaches it): App's engine,
backend, compatibility tick, layout look, notifier and notice actions (runtime/app.py), the recovery facts and the homes'
engines (runtime/loop.py, runtime/homes.py), the engine's keywords (engine/__init__.py, engine/options.py), discovery
(config.py, codex/pairing.py), the Compatibility Registry's evaluator and word (compat/), the layout watch, the words
for this time, the engine's log lines, the Dashboard's openers and handover, the notifier, and the launcher the host
starts (scripts/watcher_launcher.py). Then it runs the diffs that reach them with the tag as the reference - car-watcher's
(`diffs_watcher`), the bridge's acting commands (`diffs_bridge_acting`), the engine's (`diffs_engine`) and the
notifier's (`diffs_surface_notifier`) - through `run.py --build --reference TAG`. Exit 0 only when the diffs are equal; a
changed file is printed, not failed on - the diffs decide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

FOLLOWED = tuple("src/codex_auto_resume/" + each for each in (
    "runtime/app.py", "runtime/loop.py", "runtime/homes.py", "runtime/toasts.py", "engine/__init__.py",
    "engine/options.py", "config.py", "codex/pairing.py", "codex/transport.py", "codex/layout.py", "compat",
    "compatio.py", "oncewords.py", "logbook.py", "notifier.py", "notify.py", "notice_kinds.py", "notice_presence.py",
    "notice_inbox.py", "ui/card/stack.py", "ui/tray/dashboard.py",
    "win/handover.py", "win/network.py")) + ("scripts/watcher_launcher.py",)
DIFFS = ("diffs_watcher", "diffs_bridge_acting", "diffs_engine", "diffs_surface_notifier")
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    args = parser.parse_args(argv)
    tag = args.reference
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *FOLLOWED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("followed files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag]
    for each in DIFFS:
        command += ["-k", each]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
