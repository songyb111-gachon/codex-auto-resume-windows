"""Re-diff car-watcher (S6.1) against a tag: the one command its port is checked with again.

    python -X utf8 tests/rustdiff/rediff_watcher.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_watcher.py --reference <a later tag of the archived repository>

S6.1 was ported from the v0.6.26 final. This says which of the ported files - runtime/, checkup.py, rescan.py,
setaside.py and scripts/watcher_launcher.py - and the Python they read that another crate holds (the store's watcher
rows, the status file, the memory guard, power and the power action, the homes, the self-check, the words) differ
between v0.6.26 and the tag (`git diff --stat`, so a change is seen even where no diff reaches it), and then runs every
`diffs_watcher_*` diff with the tag as the reference (`run.py --build --reference TAG -k diffs_watcher`). Exit 0 only
when the diffs are equal; a changed file is printed, not failed on - the diffs decide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ("src/codex_auto_resume/runtime", "src/codex_auto_resume/checkup.py", "src/codex_auto_resume/rescan.py",
          "src/codex_auto_resume/setaside.py", "scripts/watcher_launcher.py")
READ = tuple("src/codex_auto_resume/" + each for each in (
    "store/watcher.py", "store/records.py", "statusfile.py", "memguard.py", "power.py", "poweraction.py", "homes.py",
    "engine/impossible.py", "domain/public.py", "domain/ids.py", "domain/plug.py", "domain/vocabulary.py", "failures.py",
    "l10n.py", "locales", "logbook.py", "config.py", "control/power.py", "control/watcher.py", "codex/layout.py",
    "compatio.py", "win/sync.py", "win/power.py", "win/powerdown.py", "win/ownprocess.py", "win/homelock.py",
    "ui/tray/model.py", "interface.py"))
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    args = parser.parse_args(argv)
    tag = args.reference
    for title, paths in (("ported", PORTED), ("read", READ)):
        changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *paths], cwd=ROOT, capture_output=True,
                                 encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        if changed.returncode != 0:
            print(changed.stderr.strip())
            return 2
        print("%s files changed from %s to %s:\n%s" % (title, BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
                            "-k", "diffs_watcher"], cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
