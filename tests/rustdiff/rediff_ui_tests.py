"""Re-diff the Python UI's tests on the C# host (S6.4, tests/rustdiff/surface_ledger.json) against a tag: the one command they
are checked with again at the final.

    python -X utf8 tests/rustdiff/rediff_ui_tests.py --reference v0.6.26

In order: which Python files of the UI (and which of its 84 test files) differ between the tag and this checkout; which test
files import the UI at the tag and have no row in the ledger (a test file the tag has and the ledger lacks); then, with the
tag's own package first on the path and this checkout's tests, (1) every ledger test that runs on the host through the shim
(`CODEX_AR_CORE=rust`: car-surface, car-words and the host's render and probe modes behind the popup's, the shared and the icon's
words and its menu) - the same tests the Python product runs - and (2) the host twins (tests/test_host_shape.py,
tests/test_host_tray_place.py, which read this checkout's C#). Exit 0 only when all pass; a file that changed is printed, not
failed on - the tests decide. It shows no window and captures nothing.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
UI_SOURCES = ("ui", "notice_window.py", "tray_place.py", "notice_card.py", "notifier.py", "notify.py", "notice_inbox.py",
              "notice_presence.py", "notice_uris.py", "codex_link.py")


def git(*arguments, **more):
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, creationflags=NO_WINDOW, **more)


# The tag's tests run on the reference's Python with the guard's boot (refguard: no lookup of this PC's processes, no
# engine), as unittest's command line would run them.
UNITTEST = "import sys, unittest; unittest.main(module=None, argv=['python -m unittest', *sys.argv[1:]])"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default="v0.6.26")
    tag = parser.parse_args(argv).reference
    ledger = json.loads((HERE / "surface_ledger.json").read_text(encoding="utf-8"))["files"]
    paths = ["src/codex_auto_resume/" + each for each in UI_SOURCES] + ["tests/" + name for name in ledger]
    changed = git("diff", "--stat", tag, "HEAD", "--", *paths)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("UI files and ledgered tests changed from %s to this checkout:\n%s" % (tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    sys.path[:0] = [str(ROOT / "tests")]
    import released
    import test_surface_ledger as rule
    from rustdiff import refpython
    with tempfile.TemporaryDirectory(prefix="car-ui-rediff-") as folder:
        archive = Path(folder, "tests.tar")
        done = subprocess.run(["git", "archive", "--format=tar", "-o", str(archive), tag, "tests"], cwd=ROOT,
                              capture_output=True, creationflags=NO_WINDOW)
        if done.returncode != 0:
            print(done.stderr.decode("utf-8", "replace").strip())
            return 2
        subprocess.run(["tar", "-xf", str(archive), "-C", folder], check=True, creationflags=NO_WINDOW)
        at_tag = {path.name for path in Path(folder, "tests").glob("test_*.py") if rule.imports_the_ui(path)}
    print("test files that import the UI at %s: %d; with no row in the ledger: %s" % (
        tag, len(at_tag), sorted(at_tag - set(ledger)) or "none"))
    source = released.package(tag)
    # S6.3's own comparisons (test_surface_*) are not run here: they compare the C# host with the Python window, whose reference side must
    # stay Python's (under the shim its words would be Rust's too); rediff_host_surface.py re-runs them against the tag.
    ids = sorted("%s.%s" % (name[:-3], test) for name, row in ledger.items() if not name.startswith("test_surface_")
                 for test in row.get("host_tests", []))
    ids.append("test_surface_askback")        # perform and PopupModel held to the tag's own, call for call
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join([str(source), str(ROOT / "tests")]), CODEX_AR_CORE="rust")
    environment.pop("CODEX_AR_EDITION", None)
    shim = subprocess.run(refpython.command(UNITTEST, *ids, paths=[source, ROOT / "tests"]), cwd=ROOT, env=environment,
                          stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("%d ledger tests on the host through the shim against %s: %s" % (len(ids), tag, "pass" if shim == 0 else "FAIL"))
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join([str(source), str(ROOT / "tests")]))
    environment.pop("CODEX_AR_EDITION", None)
    twins = subprocess.run(refpython.command(UNITTEST, "test_surface_ledger", "test_host_shape", "test_host_tray_place",
                                             paths=[source, ROOT / "tests"]), cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW).returncode
    print("the ledger and the host twins against %s: %s" % (tag, "pass" if twins == 0 else "FAIL"))
    return 0 if shim == 0 and twins == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
