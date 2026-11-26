"""Re-diff car-adv's compatibility report and Stop hook (S7.3c) against a tag: the one command the v0.6.26 final is checked with.

    python -X utf8 tests/rustdiff/rediff_adv73c.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_adv73c.py                      # reference.TAG (v0.6.26-beta.2 until the final)

S7.3c was ported from the tag's own sources. This says, in order: which of the ported Python files differ between
v0.6.26-beta.2 (the tree the seat was written in) and the tag (`git diff --stat`) - the advanced report, the Stop hook, its
claim and its declaration, the core `ownreport` modules the report reads through, and the six goldens - and then runs every
diff of the seat (`diffs_advreport_*`, `diffs_advhook_*`) with the tag as the reference (`run.py --build --reference TAG`; the
diffs build the `advreport` and `advhook` examples themselves, and cargo says when one is stale). Exit 0 only when no ported
file changed in a way a diff does not hold, and every diff is equal.

A changed file is listed, not judged: the diffs are what says whether the port still equals it.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADVANCED = "advanced/src/codex_auto_resume_advanced/"
PORTED = ([ADVANCED + "report/%s.py" % name for name in ("__init__", "document", "flow", "github", "records")]
          + [ADVANCED + "hook/%s.py" % name for name in ("__init__", "format", "handler")]
          + [ADVANCED + "engine/hookclaims.py", ADVANCED + "control/hookplugin.py"]
          + ["src/codex_auto_resume/ownreport/%s.py" % name for name in ("__init__", "document", "evidence", "reading")]
          + ["advanced/tests/golden/report", "advanced/tests/reportfixtures.py", "advanced/tests/ghfake.py"])
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
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *PORTED], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
                             creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag, "-k",
                            "diffs_advreport", "-k", "diffs_advhook"], cwd=ROOT, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
