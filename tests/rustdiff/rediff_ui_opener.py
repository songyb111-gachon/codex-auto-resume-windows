"""Re-diff S6.4e (the Dashboard opener: `ui/tray/dashboard.py`, `win/handover.py`) against a tag.

    python -X utf8 tests/rustdiff/rediff_ui_opener.py --reference v0.6.26            # builds first (run.py --build)
    python -X utf8 tests/rustdiff/rediff_ui_opener.py --reference v0.6.26 --no-build # binaries already built

S6.4e was written against the v0.6.26 final. This says which of the opener's Python files differ between the final and the
tag (`git diff --stat v0.6.26 TAG`), runs `diffs_ui_opener.py` with the tag as the reference (`run.py --reference TAG -k
OpenerDiff -k PiecesDiff`), and then the proxy's own test and the opener rows' tests on CODEX_AR_CORE=rust
(`tests/test_surface_opener.py` and every `host_tests` entry of the rows this seat moved), with the tag's package first on the
path. Exit 0 only when all of it passes. Never runs a real Codex, never starts the Dashboard, shows no window.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ["src/codex_auto_resume/ui/tray/dashboard.py", "src/codex_auto_resume/win/handover.py",
          "src/codex_auto_resume/domain/ids.py", "src/codex_auto_resume/machine.py"]
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# The bundled embeddable runtime is isolated (its ._pth): it never imports tests/sitecustomize.py, which installs the shim, so
# the script imports it itself (a no-op where site already did) and fails where the shim did not install.
UNITTEST = ("import sys, sitecustomize, unittest\n"
            "assert 'rustdiff_shim' in sys.modules, 'the CODEX_AR_CORE=rust shim is not installed'\n"
            "unittest.main(module=None, argv=['python -m unittest', *sys.argv[1:]])")
FAMILIES = ("OpenerDiff", "PiecesDiff")
# The rows whose opener tests S6.4e routed (their `host_tests` in surface_ledger.json are run on the shim).
ROWS = ("test_notice_click_chat.py", "test_tray_reuses_window.py", "test_popup_row_menu_parity.py", "test_single_rules.py",
        "test_surface_properties.py")


def shim_tests() -> list[str]:
    ledger = json.loads((HERE / "surface_ledger.json").read_text(encoding="utf-8"))["files"]
    names = ["test_surface_opener"]
    for row in ROWS:
        names += ["%s.%s" % (row[:-3], test) for test in ledger[row]["host_tests"]]
    return names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    parser.add_argument("--no-build", action="store_true", help="use the binaries already built")
    args = parser.parse_args(argv)
    tag = args.reference
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *PORTED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("opener files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--reference", tag]
    if not args.no_build:
        command.append("--build")
    for family in FAMILIES:
        command += ["-k", family]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    sys.stdout.flush()
    sys.path[:0] = [str(ROOT / "tests")]
    import released
    from rustdiff import refpython
    source = released.package(tag)
    environment = dict(os.environ, CODEX_AR_CORE="rust", CAR_NO_REAL_ENGINE="1",
                       CODEX_AUTO_RESUME_CODEX_EXE=str(ROOT / "no-codex" / "codex.exe"),
                       PYTHONPATH=os.pathsep.join([str(source), str(ROOT / "tests")]))
    environment.pop("CODEX_AR_EDITION", None)
    tests = subprocess.run(refpython.command(UNITTEST, *shim_tests(), paths=[source, ROOT / "tests"]), cwd=ROOT,
                           stdin=subprocess.DEVNULL, env=environment, creationflags=NO_WINDOW).returncode
    print("the opener's tests on CODEX_AR_CORE=rust against %s: %s" % (tag, "pass" if tests == 0 else "FAIL"))
    return 0 if diffs == 0 and tests == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
