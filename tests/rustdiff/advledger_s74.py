"""S7.4's ledger of the advanced tests (P7-DESIGN 3.1, the owner's Q3 (c)): every `advanced/tests/test_*.py` of the
reference tag that S7.2a's ledger gives to S7.4 (it imports `measure` or `evidence`), with what it waits for before
it can run unedited on Rust through the advanced proxy: the proxy itself (S7.2a3, being built), the other seats whose
modules it imports and that have not landed, and the measurements it drives whose probe car-adv has not ported yet.

    python -X utf8 tests/rustdiff/advledger_s74.py [--tag v0.6.26] [--markdown]

PORTED is `car_adv::measure::ported()` written out (the diffs_advmeasure cases hold each of them to the tag); the
table only shrinks. Reads the tag out of git; runs nothing of it.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rustdiff import advledger_s72a as base  # noqa: E402

PORTED = {"M1", "M2", "M2b", "M3", "M5", "M6", "M7", "MH", "MA", "MQ", "MT", "MW", "MP1", "MP2", "MP3", "MU", "MN",
          "MR", "MIPC", "MAWS", "MCLOUD", "M6B"}
# The measurements' words as the tests spell them: Measurement.M2B, "m2b", "measure mqo", ...
WORDS = ["M1", "M2", "M2B", "M3", "M4", "M5", "M6", "M7", "MH", "MA", "MW", "MP1", "MP2", "MP3", "MU", "MN", "MR", "MQ",
         "ME", "MS", "MK", "MT", "MIPC", "MAWS", "MCLOUD", "M6B", "MO", "MX", "MXA", "MF", "M3B", "MB", "MC1", "MC2",
         "MQO", "MQP", "MQG", "MTOK", "MOPEN", "MAL", "MALR", "MWAKE", "MHK", "M4B", "MANCHOR", "MIMG", "MSTEER",
         "MSTEER2", "MGAVE", "MB2", "MPROFILE", "MSWAP", "MAUTO"]
SPELLED = {"M2B": "M2b"}
# The seats that have landed on this branch's base (car-v0627-s72a at 8e6362cbf) besides S7.4 itself.
LANDED = {"S7.1", "S7.2c", "S7.3c", "S7.2a", "S7.4"}


def measurements(source: str) -> set:
    found = set()
    for word in WORDS:
        if re.search(r"Measurement\.%s\b" % word, source) or re.search(r"[\"']%s[\"' ]" % word.lower(), source):
            found.add(SPELLED.get(word, word))
    return found


def rows(tag: str) -> list:
    tests = base.files(tag)
    made = []
    for row in base.ledger(tag):
        if row["unlock"] != "S7.4":
            continue
        source = tests[row["file"]]
        driven = measurements(source)
        waits = ["the advanced proxy (S7.2a3)"]
        waits += ["%s's modules" % seat for seat in row["seats"] if seat not in LANDED and seat != "retired"]
        missing = sorted(driven - PORTED)
        if missing:
            waits.append("probes not ported: " + " ".join(missing))
        made.append({"file": row["file"], "advancedcase": row["advancedcase"], "measurements": sorted(driven),
                     "waits": waits})
    return made


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.6.26")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    found = rows(args.tag)
    if args.markdown:
        print("| file | waits for |")
        print("|---|---|")
        for row in found:
            print("| `%s` | %s |" % (row["file"], "; ".join(row["waits"])))
        print("| **%d files** | |" % len(found))
    else:
        for row in found:
            print("%-48s %s" % (row["file"], "; ".join(row["waits"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
