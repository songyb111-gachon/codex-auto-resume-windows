"""Writes advanced/tests/golden/report/: what codex-compat-reporter's own `build` writes of each of
reportfixtures.SCENARIOS - the report's body, and what it left out and why.

    python advanced/tests/reportgolden.py --reporter <its codex_compat_report.py, at 1.5.0> [--write]

Without --write it only compares, and exits 1 on any difference. The reporter is loaded from the
file given, for this run only - nothing of it is kept here, and no bytecode is written beside it -
and it must say it is 1.5.0, the release the reader was written against. Each home is made by
reportfixtures and the reporter is pointed at it (its PRODUCT, CODEX and HOME), with its clock at
reportfixtures.NOW, which is what the reader is given too: nothing real is read.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import reportfixtures as fixtures  # noqa: E402

GOLDEN = HERE / "golden" / "report"
REPORTER_VERSION = "1.5.0"
BODY = ("codex_version", "verdict", "local_checks", "records", "capabilities")
# The reporter's sentences for a record it could not place, and the reader's codes for them.
UNPLACED = {"no engine line before it in the logs kept": "no_engine_line_before",
            "the engine changed while it ran": "engine_changed_during",
            "the next engine line after it names another version": "next_line_other_version",
            "the engine changed after it": "engine_changed_after"}


def load(path: Path):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("codex_compat_report_for_goldens", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.__version__ != REPORTER_VERSION:
        raise SystemExit("the reporter at %s is %s, not %s" % (path, module.__version__, REPORTER_VERSION))
    return module


def left_out(notes: dict) -> dict:
    unplaced = {code: 0 for code in UNPLACED.values()}
    for said, many in (notes.get("unplaced") or {}).items():
        unplaced[UNPLACED[said]] += many
    return {"hidden": notes["hidden"], "another_route": notes["routed"], "beyond_reach": notes["route_unknown"],
            "elsewhere": notes["elsewhere"], "unplaced": unplaced}


def golden(reporter, name) -> dict:
    home, asked = fixtures.scenario(name)
    try:
        with fixtures.isolated(home), mock.patch.object(reporter, "PRODUCT", home.paths.home), \
                mock.patch.object(reporter, "CODEX", home.codex), mock.patch.object(reporter, "HOME", home.root), \
                mock.patch.object(reporter.time, "time", return_value=fixtures.NOW):
            notes = {}
            report = reporter.build(fixtures.LOGIN, asked, notes)
    finally:
        home.close()
    return {"scenario": name, "reporter": REPORTER_VERSION, "body": {field: report[field] for field in BODY},
            "left_out": left_out(notes)}


def encode(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reporter", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    options = parser.parse_args(argv)
    reporter = load(options.reporter)
    differs = []
    for name in fixtures.SCENARIOS:
        text = encode(golden(reporter, name))
        target = GOLDEN / ("%s.json" % name)
        if options.write:
            GOLDEN.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="ascii", newline="\n")
        elif not target.is_file() or target.read_text(encoding="ascii") != text:
            differs.append(target.name)
    for name in differs:
        print("differs: %s" % name)
    return 1 if differs else 0


if __name__ == "__main__":
    raise SystemExit(main())
