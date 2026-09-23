"""The shape of the state database, on every path that can produce one.

v0.6.10-alpha turns `store.py` into a package. Nothing about the database may move while it
happens: a column dropped from a `CREATE TABLE`, an index that stops being made, a migration
that lands one version short - each of those is a state file somebody already has, which the
next release then cannot read.

So the shape is written down: for a fresh installation, for each upgrade path, and for the
downgrade, every table's columns in order with their types, defaults, null-ness and keys, every
index with the columns it covers, and `PRAGMA user_version`. `tests/test_schema_golden.py`
builds each one again and compares it with the file.

The old versions are built by the store code of real tagged releases - the same way
`tests/test_control_v3.py` does it - so the upgrade paths are the ones people's machines
actually took, not a reconstruction of them.

    py tests/schemagolden.py --write
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for entry in (str(ROOT / "src"), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

GOLDEN = HERE / "fixtures" / "schema.json"
# The releases whose state files are still out there and still upgraded on open.
V1_TAG, V2_TAG = "v0.5.0", "v0.5.7"


def legacy_store(tag):
    """The store module exactly as a tagged release shipped it."""
    shown = subprocess.run(["git", "-C", str(ROOT), "show", tag + ":src/codex_auto_resume/store.py"],
                           capture_output=True, text=True, encoding="utf-8")
    if shown.returncode != 0:
        if os.environ.get("CI"):
            raise AssertionError("%s is not in this checkout; CI must fetch the tags" % tag)
        raise unittest.SkipTest("%s is not in this checkout" % tag)
    source = shown.stdout.replace("from . import failures", "from codex_auto_resume import failures")
    folder = Path(tempfile.mkdtemp())
    path = folder / ("store_%s.py" % tag.replace(".", "_"))
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shape(path: Path) -> dict:
    """Everything about the file that is its shape, and nothing that is its contents."""
    connection = sqlite3.connect(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {}
        for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"):
            columns = [{"name": row[1], "type": row[2], "notnull": bool(row[3]),
                        "default": row[4], "primary_key": row[5]}
                       for row in connection.execute("PRAGMA table_info(%s)" % name)]
            indexes = {}
            for row in connection.execute("PRAGMA index_list(%s)" % name):
                index = row[1]
                if index.startswith("sqlite_autoindex"):
                    continue
                indexes[index] = {
                    "unique": bool(row[2]),
                    "columns": [entry[2] for entry in
                                connection.execute("PRAGMA index_info(%s)" % index)]}
            tables[name] = {"columns": columns, "indexes": dict(sorted(indexes.items()))}
        return {"user_version": version, "tables": tables}
    finally:
        connection.close()


def fresh(folder: Path) -> dict:
    from codex_auto_resume.store import Store
    with Store(folder):
        pass
    return shape(folder / "state.sqlite")


def upgraded(folder: Path, tag: str) -> dict:
    """A database written by `tag`, then opened by today's store, which upgrades it."""
    from codex_auto_resume.store import Store
    old = legacy_store(tag)
    with old.Store(folder):
        pass
    # Only the watcher, or something holding its mutex, upgrades a schema - so the upgrade is
    # asked for here as the watcher asks for it.
    with Store(folder, migrate=True):
        pass
    return shape(folder / "state.sqlite")


def downgraded(folder: Path) -> dict:
    """What `codex-auto-resume downgrade-state` leaves for an older release to open."""
    from codex_auto_resume.store import Store, downgrade_to_v2
    with Store(folder):
        pass
    downgrade_to_v2(folder)
    return shape(folder / "state.sqlite")


PATHS = {
    "fresh": fresh,
    "upgraded-from-%s" % V1_TAG: lambda folder: upgraded(folder, V1_TAG),
    "upgraded-from-%s" % V2_TAG: lambda folder: upgraded(folder, V2_TAG),
    "downgraded-to-v2": downgraded,
}


def produce() -> dict:
    made = {}
    for name, build in PATHS.items():
        folder = Path(tempfile.mkdtemp(prefix="schema-"))
        try:
            made[name] = build(folder)
        except unittest.SkipTest as skipped:
            made[name] = {"skipped": str(skipped)}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    return made


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    made = produce()
    text = json.dumps(made, indent=2, ensure_ascii=False) + "\n"
    if "--write" in argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
        print("wrote %s (%d paths)" % (GOLDEN.name, len(made)))
        return 0
    stored = GOLDEN.read_text(encoding="utf-8") if GOLDEN.exists() else ""
    print("%s: %s" % (GOLDEN.name, "same" if stored == text else "DIFFERENT"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
