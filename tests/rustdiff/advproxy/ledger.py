"""The per-file table of the advanced proxy (owner Q3 (c)): every `advanced/tests/test_*.py` of the reference tag, and
whether it runs green on Rust through the proxy - or what it waits for.

    python -X utf8 tests/rustdiff/advproxy/ledger.py [--tag v0.6.26] [--markdown] [--seat S7.2b]
    python -X utf8 tests/rustdiff/advproxy/ledger.py --run test_advanced_x.py ... [--debug]

A file is

* **green on Rust** - in GREEN below: it passed on the proxy lane (CODEX_AR_CORE=rust, the advanced lane's path) as on
  the reference lane, test by test, and reached car-adv (its calls to advserve counted), and every name it imports is
  forwarded, handed or data (table.py);
* **ready** - nothing it imports waits, but no run has put it in GREEN yet (`--run` it);
* **waits for <seat>** - it imports a module (or a name of a module) table.py has not forwarded: the latest of their
  seats in the waves (P7-DESIGN 2.3) is the one that unlocks it; the C# page (`pagecase.py`) is S6.2a's window and
  runs on the reference only, as do the files retired by D8.

`--run` runs each file named, one process at a time, on both lanes through scripts/test_parts.py's worker, compares
the outcomes test by test and prints the counts of calls it made to advserve - what a seat pastes into GREEN.
GREEN only grows; a file leaves it only with the row of table.py that put it there.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


table = _load("rustdiff_advproxy_table", HERE / "table.py")
advledger = _load("rustdiff_advledger_s72a", HERE.parent / "advledger_s72a.py")

# Proved green on Rust (`--run`: both lanes pass test by test, calls to advserve made), with the seat whose rows did it.
GREEN = {
}

# The names a HANDED or THROUGH module hands car-adv as data (a test may build them): any other function of the module
# imported by name is its own rule, not yet forwarded. ALL-CAPS names are constants and always data.
HANDED_NAMES = {
    "registry": {"CapabilityDef", "Ceilings", "Option", "Registry", "RegistryError"},
    "policy": {"Policy"},
    "statement": {"Catalogs"},
    "state": {"StateError", "StaleGeneration", "Refused", "Scoped"},
    "ledger": {"ClaimLedger"},
}


def blocking(imports: set) -> dict:
    """{module or module.Name: its seat} of every import table.py does not cover."""
    found = {}
    for each in imports:
        module = advledger.real(each, set(table.MODULES))
        row = table.MODULES.get(module)
        if row is None:
            continue
        name = each[len(module) + 1:] if each != module else ""
        if row.status in ("forwarded", "data"):
            if row.status == "forwarded" and name and name not in row.forwards and not name.isupper() \
                    and name not in HANDED_NAMES.get(module, ()):
                found[each] = row.seat
            continue
        if row.status in ("through", "handed"):
            if name and not name.isupper() and name not in HANDED_NAMES.get(module, ()):
                found[each] = row.seat
            continue
        found[each] = row.seat
    return found


def rows(tag: str) -> list:
    ledger = {row["file"]: row for row in advledger.ledger(tag)}
    tests = advledger.files(tag)
    known = set(table.MODULES)
    out = []
    for name in sorted(ledger):
        base = ledger[name]
        imports = {advledger.real(each, known) if advledger.real(each, known) == each else each
                   for each in advledger.imported(tests[name], tests)}
        waits = blocking(imports)
        if base["reason"] != "proxy":
            status, why = "waits for %s" % base["unlock"], base["reason"]
        elif name in GREEN:
            status, why = "green on Rust", GREEN[name]
        elif not waits:
            status, why = "ready", "nothing it imports waits: --run it"
        else:
            seats = {seat for seat in waits.values()}
            latest = [each for each in advledger.ORDER if each in seats]
            unlock = latest[-1] if latest else sorted(seats)[0]
            status, why = "waits for %s" % unlock, ", ".join(sorted(waits))
        out.append({"file": name, "status": status, "why": why, "advancedcase": base["advancedcase"]})
    return out


# ------------------------------------------------------------------ --run

def _lane(files, proxied: bool, scratch: Path, debug: bool):
    report = scratch / ("rust.json" if proxied else "python.json")
    counts = scratch / "counts.txt"
    environment = dict(os.environ, CODEX_AR_EDITION="advanced",
                       PYTHONPATH=os.pathsep.join(("src", os.path.join("advanced", "src"))))
    environment.pop("CODEX_AR_CORE", None)
    if proxied:
        environment.update(CODEX_AR_CORE="rust", CODEX_AR_ADVPROXY_COUNT=str(counts))
        if debug:
            environment["CODEX_AR_ADVSERVE_EXE"] = str(ROOT / "advanced" / "rust" / "target" / "debug" / "examples"
                                                       / "advserve.exe")
    subprocess.run([sys.executable, "scripts/test_parts.py", "--worker", "advanced/tests", "--report", str(report),
                    *files], cwd=str(ROOT), env=environment, creationflags=NO_WINDOW, capture_output=True)
    outcomes = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    calls = {}
    if proxied and counts.is_file():
        for line in counts.read_text(encoding="utf-8").splitlines():
            for call, number in json.loads(line)["counts"].items():
                calls[call] = calls.get(call, 0) + number
    return outcomes, calls


def _outcomes(report) -> dict:
    """scripts/test_parts.py's report: {"outcomes": {test id: "pass" | "fail" | "error" | "skip" | ...}}."""
    outcomes = report.get("outcomes") if isinstance(report, dict) else None
    return dict(outcomes) if isinstance(outcomes, dict) else {}


def run(files, debug: bool) -> int:
    worst = 0
    for name in files:
        with tempfile.TemporaryDirectory(prefix="car-advproxy-") as scratch:
            scratch = Path(scratch)
            python, _ = _lane([name], False, scratch, debug)
            rust, calls = _lane([name], True, scratch, debug)
            want, got = _outcomes(python), _outcomes(rust)
            differ = sorted(key for key in set(want) | set(got) if want.get(key) != got.get(key))
            bad = sorted(key for key, outcome in got.items() if outcome not in ("pass", "skip", "expected-failure"))
            ok = bool(got) and not differ and not bad and sum(calls.values()) > 0
            worst = worst or (0 if ok else 1)
            print("%-52s %s  tests %d  calls %s%s" % (name, "GREEN" if ok else "NOT GREEN", len(got),
                                                     json.dumps(calls, sort_keys=True),
                                                     "" if not differ else "  differ: " + ", ".join(differ[:6])))
    return worst


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.6.26")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--seat")
    parser.add_argument("--run", nargs="+")
    parser.add_argument("--debug", action="store_true", help="the debug build of advserve")
    args = parser.parse_args()
    if args.run:
        return run(args.run, args.debug)
    found = rows(args.tag)
    if args.markdown:
        counts = {}
        for row in found:
            key = row["status"]
            counts.setdefault(key, [0, 0])
            counts[key][0] += 1
            counts[key][1] += row["advancedcase"]
        print("| status | files | of them advancedcase |")
        print("|---|---:|---:|")
        for key in sorted(counts, key=lambda each: (each != "green on Rust", each != "ready", each)):
            print("| %s | %d | %d |" % (key, counts[key][0], counts[key][1]))
        print("| **all** | %d | %d |" % (len(found), sum(row["advancedcase"] for row in found)))
        return 0
    for row in found:
        if args.seat and args.seat not in row["status"]:
            continue
        print("%-56s %-18s %s" % (row["file"], row["status"], row["why"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
