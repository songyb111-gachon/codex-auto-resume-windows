"""Copy the tag's 22 catalogs into car-words, where Rust embeds them (`include_str!`).

    python -X utf8 tests/rustdiff/gen_catalogs.py --write | --check

The Rust workspace builds from an archive of `rust/` alone (the edition rebuild check), so the catalogs it speaks
are copies, taken from the reference tag's `src/codex_auto_resume/locales/` as `git archive` holds them (LF). The
words diff (diffs_leaves_words.py) compares what Rust embeds with the tag's files text for text, so a catalog that
changes in Python fails it until this is run again.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "rust" / "crates" / "car-words" / "locales"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != Path(__file__).resolve().parent]
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    import released
    from rustdiff import reference
    source = released.package(reference.TAG) / "codex_auto_resume" / "locales"
    status = 0
    for each in sorted(source.glob("*.json")):
        wanted = each.read_bytes().replace(b"\r\n", b"\n")
        path = TARGET / each.name
        if args.write:
            TARGET.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wanted)
        elif not path.is_file() or path.read_bytes() != wanted:
            print("%s differs from %s's: run gen_catalogs.py --write" % (path.relative_to(ROOT), reference.TAG))
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
