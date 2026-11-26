"""Re-diff car-codex's app-server half and the registry (S3.3) against a tag: the one command the v0.6.26 final is
checked with.

    python -X utf8 tests/rustdiff/rediff_appserver.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_appserver.py                      # reference.TAG (v0.6.26-beta.2 until then)

S3.3 was ported from v0.6.26-beta.2; `git log v0.6.26-beta.2..origin/dev` was empty for every file below when it was.
This says which of them (and of the modules they read) differ between v0.6.26-beta.2 and the tag (`git diff --stat`,
so a change is seen even where no diff reaches it), then runs every S3.3 diff with the tag as the reference
(`run.py --build --reference TAG -k diffs_codex_appserver -k diffs_codex_compat`). Exit 0 only when the diffs are
equal; a file that changed is printed, not failed on - the diffs decide, and a changed file a diff does not reach is the
reader's to port.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ("codex/layout.py", "codex/pairing.py", "codex/appserver.py", "codex/transport.py", "compat/__init__.py",
          "compat/cache.py", "compat/evaluator.py", "compat/files.py", "compat/model.py", "compat/permits.py",
          "compat/probes.py", "compat/report.py", "compat/reported.py", "compat/standing.py", "compat/views.py",
          "compatio.py",
          # what they read and S3.3 did not port itself
          "codex/paths.py", "codex/usage.py", "codex/errors.py", "domain/ids.py", "domain/errors.py",
          "domain/vocabulary.py", "domain/compat_vocabulary.py", "domain/states.py", "continuation.py", "config.py",
          "win/kernel.py", "win/inventory.py", "win/authenticode.py", "windows.py",
          "data/codex_compat.json", "data/reported.json")
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
    print("S3.3 files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
                            "-k", "diffs_codex_appserver", "-k", "diffs_codex_compat"], cwd=ROOT,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
