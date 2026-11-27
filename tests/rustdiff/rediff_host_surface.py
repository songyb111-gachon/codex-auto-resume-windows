"""Re-diff the host's drawn surfaces (S6.3, gui/host.sources [surface]) against a tag: the one command they are checked
with again at the final.

    python -X utf8 tests/rustdiff/rediff_host_surface.py --reference v0.6.26

The surfaces the host draws are C#, not Rust, so their diff is comparison A (tests/test_surface_parity.py) rather than a
car-harness diff: the C# plans against the Python reference's, exactly, over the fixed matrix (rediff_surface.py is
car-surface's, S6.0's, the decision half). This says, in order: which of the ported Python files - and the ones the
matrix's view models are made from - differ between the tag and this checkout (`git diff --stat`, so a change is seen
even where no case reaches it); then runs test_surface_parity and test_surface_windows (the windows' halves, S6.3c-f: the
icon, its menu, MSAA, the live-path proofs) with the tag's own package as the reference (its `src`,
taken out of git as tests/released.py takes it, first on the path; this checkout's tests/ and build/ for the matrix).
Exit 0 only when the comparison is exact; a file that changed is printed, not failed on - the comparison decides.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# The Python the [surface] files port (P6-DESIGN 2.3), and the brand and language rules their plans read.
PORTED = ("ui/popup/layout.py", "ui/popup/words.py", "ui/popup/fonts.py", "ui/popup/theme.py", "ui/popup/motion.py",
          "ui/popup/placement.py", "ui/popup/menuplan.py", "ui/popup/renderer.py", "ui/popup/win32.py",
          "ui/popup/menuwindow.py", "ui/tray/tipplan.py", "ui/tray/motion.py", "ui/tray/tipcard.py", "ui/card/card.py",
          "notice_card.py", "brand", "win/typeface.py", "win/textsize.py", "l10n.py", "ui/popup/light.py",
          "ui/popup/gdiplus.py", "ui/popup/elevation.py", "ui/popup/layers.py", "ui/card/surfaces.py",
          "ui/tray/words.py", "ui/words.py", "tray_place.py", "ui/popup/window.py", "ui/popup/messages.py",
          "ui/popup/hidden.py", "ui/card/stack.py", "ui/card/win32.py",
          # S6.3e/f: the icon, its menu, its motion, its clicks and cards, MSAA (TrayIcon.cs, TrayMenu.cs, SurfaceAccess.cs).
          "ui/tray/icon.py", "ui/tray/menu.py", "ui/tray/animation.py", "ui/tray/clicks.py", "ui/tray/cards.py",
          "ui/tray/win32.py", "ui/tray/__init__.py", "ui/popup/access.py")
# What the matrix's view models are made from.
INPUTS = ("ui/popup/model.py", "notifier.py", "notify.py", "locales")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# The tag's tests run on the reference's Python with the guard's boot (refguard: no lookup of this PC's processes, no
# engine), as unittest's command line would run them.
UNITTEST = "import sys, unittest; unittest.main(module=None, argv=['python -m unittest', *sys.argv[1:]])"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default="v0.6.26")
    args = parser.parse_args(argv)
    tag = args.reference
    paths = ["src/codex_auto_resume/" + each for each in PORTED + INPUTS]
    changed = subprocess.run(["git", "diff", "--stat", tag, "HEAD", "--", *paths], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to this checkout:\n%s" % (tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    sys.path[:0] = [str(ROOT / "tests")]
    import released
    from rustdiff import refpython
    source = released.package(tag)
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join([str(source), str(ROOT / "tests")]))
    environment.pop("CODEX_AR_EDITION", None)
    status = subprocess.run(refpython.command(UNITTEST, "test_surface_parity", "test_surface_windows",
                                              paths=[source, ROOT / "tests"]), cwd=ROOT,
                            env=environment, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff of the host's surfaces against %s: %s" % (tag, "exact" if status == 0 else "DIFFER"))
    return 0 if status == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
