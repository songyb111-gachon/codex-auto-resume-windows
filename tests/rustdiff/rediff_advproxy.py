"""Re-diff the advanced proxy (seat S7.2a3, owner Q3 (c)) against a tag: the final's one command.

    python -X utf8 tests/rustdiff/rediff_advproxy.py --reference v0.6.26 [--build]

Says which advanced test files and forwarded modules differ between v0.6.26 (what the proxy was proved against) and the
tag, then runs every file of the per-file table's GREEN (advproxy/ledger.py) on both lanes again - the advanced lane's
Python and the same files with CODEX_AR_CORE=rust, test by test, each having to reach advserve - with `--build`
building advserve's release first. Exit 0 only when every GREEN file is green again.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SCOPE = ["advanced/tests", "advanced/src/codex_auto_resume_advanced/runtime.py",
         "advanced/src/codex_auto_resume_advanced/plug.py", "advanced/src/codex_auto_resume_advanced/arming.py",
         "advanced/src/codex_auto_resume_advanced/state", "advanced/src/codex_auto_resume_advanced/registry.py"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args(argv)
    changed = subprocess.run(["git", "diff", "--stat", BASE, args.reference, "--", *SCOPE], cwd=ROOT,
                             capture_output=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("proxy scope changed from %s to %s:\n%s" % (BASE, args.reference, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    if args.build:
        subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", "advserve"],
                       cwd=str(ROOT / "advanced" / "rust"), check=True, creationflags=NO_WINDOW)
    spec = importlib.util.spec_from_file_location("rustdiff_advproxy_ledger", HERE / "advproxy" / "ledger.py")
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    worst = ledger.run(sorted(ledger.GREEN), False)
    print("rediff against %s: %s" % (args.reference, "every GREEN file green" if worst == 0 else "NOT GREEN"))
    return worst


if __name__ == "__main__":
    sys.exit(main())
