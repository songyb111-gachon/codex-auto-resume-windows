"""The harness's one entry point, for CI's rustdiff job (PLAN 7, S0.1's workflow) and for a person:

    python -X utf8 tests/rustdiff/run.py --build      # cargo build the harness crate, then every diff
    python -X utf8 tests/rustdiff/run.py              # every diff, on binaries already built
    python -X utf8 tests/rustdiff/run.py --reference v0.6.26 -v
    python -X utf8 tests/rustdiff/run.py -k Ids              # only the tests whose name has Ids (unittest's -k)

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
    parser.add_argument("-k", dest="pattern", action="append", help="only tests whose name matches (unittest's -k)")
    args = parser.parse_args(argv)
    if args.reference:
        os.environ["CODEX_AR_REFERENCE"] = args.reference
    # The script's own folder first on the path would make its modules top-level names; the harness is a
    # package of tests/, beside released.py, and the product is src/.
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != HERE]
    for entry in (ROOT / "src", ROOT / "tests"):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    import importlib

    from rustdiff import core, reference
    # `diffs` (S0.4's proof) and every `diffs_*.py` beside it: each seat's cases are a module of their own
    # (diffs_leaves_machine, diffs_leaves_domain, ...) with its own RECORD, and none edits another's.
    modules = [importlib.import_module("rustdiff." + name)
               for name in ["diffs"] + sorted(path.stem for path in HERE.glob("diffs_*.py"))]

    if args.build:
        core.build()
    absent = core.missing()
    if absent:
        print("not built: %s; run with --build" % ", ".join(absent), file=sys.stderr)
        return 2
    built = core.binary("car-core-stub").parent
    shown = built.relative_to(ROOT).as_posix() if built.is_relative_to(ROOT) else built.name
    print("reference %s; rust %s" % (reference.TAG, shown), flush=True)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
    if args.pattern:
        unittest.defaultTestLoader.testNamePatterns = ["*%s*" % each for each in args.pattern]
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    for module in modules:
        for line in getattr(module, "RECORD", []):
            print(line)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
