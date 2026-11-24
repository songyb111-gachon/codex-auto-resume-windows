"""The harness's one entry point, for CI's rustdiff job (PLAN 7, S0.1's workflow) and for a person:

    python -X utf8 tests/rustdiff/run.py --build      # cargo build the harness crate, then every diff
    python -X utf8 tests/rustdiff/run.py              # every diff, on binaries already built
    python -X utf8 tests/rustdiff/run.py --reference v0.6.26 -v

From the repository root, on any PYTHONPATH (it sets its own). Exit 0 when every diff is identical, 1 when one
differs or fails, 2 when the binaries are missing. The reference tag must be in the checkout (CI: fetch the
tags; a missing tag on CI fails, as tests/released.py has it). CARGO_BUILD_JOBS defaults to 4.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tests/rustdiff/run.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--build", action="store_true", help="cargo build --release --locked the harness crate first")
    parser.add_argument("--reference", metavar="TAG", help="the reference tag (default: reference.TAG)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.reference:
        os.environ["CODEX_AR_REFERENCE"] = args.reference
    # The script's own folder first on the path would make its modules top-level names; the harness is a
    # package of tests/, beside released.py, and the product is src/.
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != HERE]
    for entry in (ROOT / "src", ROOT / "tests"):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    from rustdiff import core, diffs, reference

    if args.build:
        core.build()
    absent = core.missing()
    if absent:
        print("not built: %s; run with --build" % ", ".join(absent), file=sys.stderr)
        return 2
    built = core.binary("car-core-stub").parent
    shown = built.relative_to(ROOT).as_posix() if built.is_relative_to(ROOT) else built.name
    print("reference %s; rust %s" % (reference.TAG, shown), flush=True)
    # Every seat's diffs are a module of their own, named `*_diffs` (this folder's diffs.py is the harness's): each is run,
    # and each prints what it saw (its RECORD).
    import importlib

    modules = [diffs] + [importlib.import_module("rustdiff." + path.stem) for path in sorted(HERE.glob("*_diffs.py"))]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    shown: set = set()
    for module in modules:
        for line in getattr(module, "RECORD", []):
            if line not in shown:  # the seats' modules share one list
                shown.add(line)
                print(line)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
