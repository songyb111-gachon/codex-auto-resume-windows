"""Re-diff the follow-3.14 seat's work against a tag: the nesting limits, the drive-like realpath tail, the generators.

    python -X utf8 tests/rustdiff/rediff_follow314.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_follow314.py                      # reference.TAG

The seat holds Rust to the Python the product ships (3.14.10): `json.loads` and `json.dumps` nesting limits per container kind
(car-machine's `json/depth.rs`, `diffs_nesting_314.py`), the `ntpath.realpath` join of a drive-like tail
(`diffs_paths_314.py`), and the generated Unicode tables and parser tables, which every generator checks under the bundled
runtime. It was made against v0.6.26, the final, so its files cannot have moved; this says, in order: which of the Python files
it reads differ between v0.6.26 and the tag (`git diff --stat`, a change is printed, not failed on); whether every generated
table is still what the bundled interpreter gives (each generator's `--check`); and then runs both diffs with the tag as the
reference on the bundled Python (`run.py --build --reference TAG --reference-python bundled`). Exit 0 only when all three are
clean. Under `--reference-python system` (3.13) both diffs differ BY DESIGN.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
READ = ("compat/model.py", "config.py")
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# the generators that hold a table of the product's Python (and the parser tables read from the tag under it)
GENERATORS = ("gen_advcodex.py", "gen_tables.py", "gen_codex.py")
WITH_TAG = ("gen_policy.py", "gen_cli.py")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=None)
    args = parser.parse_args(argv)
    tag = args.reference
    if tag is None:
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
        from rustdiff import reference
        tag = reference.TAG
    paths = ["src/codex_auto_resume/" + each for each in READ]
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *paths], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("files read by this seat changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    stale = []
    for name in GENERATORS + WITH_TAG:
        words = [sys.executable, "-X", "utf8", str(HERE / name), "--check"]
        if name in WITH_TAG:
            words += ["--ref" if name == "gen_policy.py" else "--reference", tag]
        if subprocess.run(words, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode != 0:
            stale.append(name)
    environment = dict(os.environ)
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
                            "--reference-python", environment.get("CODEX_AR_REFERENCE_PYTHON", "bundled"),
                            "-k", "nesting_314", "-k", "paths_314"], cwd=ROOT, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW, env=environment).returncode
    print("rediff against %s: generated tables %s, diffs %s" % (tag, "current" if not stale else "STALE (%s)" % ", ".join(stale),
                                                                "equal" if diffs == 0 else "DIFFER"))
    return 0 if not stale and diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
