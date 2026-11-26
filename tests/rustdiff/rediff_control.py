"""Re-diff car-control's bridge (S5.1a's quiet commands, S5.1b's acting ones) against a tag: the one command the v0.6.26
final is checked with.

    python -X utf8 tests/rustdiff/rediff_control.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_control.py                    # reference.TAG (v0.6.26-beta.2 until the final)

S5.1a was ported from v0.6.26-beta.2. The main session checked which files moved on dev after that tag
(`control/watcher.py` among them: its reading half - `_watcher`, `get_status`, `how_it_ended`, `plugin_copy` - is
ported, its starting and stopping is S5.1b's). This says, in order: which of the ported Python files differ between
v0.6.26-beta.2 and the tag (`git diff --stat`, so a change is seen even where no diff reaches it); and then runs every
`diffs_bridge*` diff with the tag as the reference (`run.py --build --reference TAG -k diffs_bridge`). Exit 0 only when
the diffs are equal; a file that changed is printed, not failed on - the diffs decide.

S5.1b (seat bridge6) added the acting half: `control/actions.py`, `control/codexstart.py`, `control/poweraction.py` and
`controlcli.py`'s compat, rescan, check and diagnostics glue, held by `diffs_bridge_acting.py` (which `-k diffs_bridge`
runs too). Its diffs follow the v0.6.26 final, whose `control/watcher.py` changed (`get_status`'s meter reading, which
the standard edition's null plug never reaches).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ("controlcli.py", "control/__init__.py", "control/errors.py", "control/layer.py", "control/state.py",
          "control/policy.py", "control/seen.py", "control/records.py", "control/preview.py", "control/tools.py",
          "control/wire.py", "control/watcher.py", "oncewords.py", "homefind.py", "openstate.py", "ownreport/__init__.py",
          "ownreport/document.py", "ownreport/evidence.py", "ownreport/reading.py", "diagnostics.py",
          # S5.1b
          "control/actions.py", "control/codexstart.py", "control/poweraction.py", "poweraction.py", "startup.py",
          "demo.py", "projects.py", "quiet.py", "domain/gates.py")
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
    paths = ["src/codex_auto_resume/" + each for each in PORTED]
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *paths], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
                            "-k", "diffs_bridge"], cwd=ROOT, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
