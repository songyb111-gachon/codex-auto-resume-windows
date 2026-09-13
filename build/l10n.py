"""Translation bookkeeping for the interface catalogs.

English (`src/codex_auto_resume/locales/en.json`) is canonical. Every other catalog is a
translation of it, and a translation is only as current as the English it was made from.
So beside each catalog this records, key by key, a short digest of the English sentence
the translation was made from, in `build/l10n/<locale>.basis.json`. When the English
changes the digest stops matching and the key is *stale*: it still ships - a slightly
old sentence in the reader's language beats an English one - but it is reported here and
the tests fail until somebody has looked at it again.

That is what makes translation incremental. A new release does not re-translate eight
catalogs; `export` hands a translator exactly the keys that are new or whose English
moved, and `import` merges them back, checks them, and records what they were made from.

    py build/l10n.py status
    py build/l10n.py export ja > work.json    # only what needs a translator; fill in "text"
    py build/l10n.py import ja work.json      # merge, validate, record the basis
    py build/l10n.py mark ja KEY [KEY ...]    # reviewed: still right for the new English
    py build/l10n.py prune ja                 # drop keys English no longer has
    py build/l10n.py check                    # exit 1 if anything is incomplete

Nothing here reaches the network. The basis files live under `build/`, which is not part
of a release.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import l10n  # noqa: E402

CATALOGS = ROOT / "src" / "codex_auto_resume" / "locales"
BASIS = ROOT / "build" / "l10n"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def read_catalog(locale: str) -> dict:
    path = CATALOGS / ("%s.json" % locale)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=l10n._no_duplicates)


def write_catalog(locale: str, table: dict) -> None:
    ordered = {key: table[key] for key in sorted(table)}
    (CATALOGS / ("%s.json" % locale)).write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_basis(locale: str) -> dict:
    path = BASIS / ("%s.basis.json" % locale)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_basis(locale: str, basis: dict) -> None:
    BASIS.mkdir(parents=True, exist_ok=True)
    ordered = {key: basis[key] for key in sorted(basis)}
    (BASIS / ("%s.basis.json" % locale)).write_text(
        json.dumps(ordered, indent=2) + "\n", encoding="utf-8")


def report(locale: str) -> dict:
    """What is incomplete about one translation, by kind."""
    english = read_catalog(l10n.DEFAULT)
    table = read_catalog(locale)
    basis = read_basis(locale)
    missing = sorted(key for key in english if key not in table)
    extra = sorted(key for key in table if key not in english)
    stale = sorted(key for key in english
                   if key in table and basis.get(key) != digest(english[key]))
    placeholders = sorted(key for key in english if key in table
                          and l10n.placeholders(table[key]) != l10n.placeholders(english[key]))
    empty = sorted(key for key, value in table.items()
                   if not isinstance(value, str) or not value.strip())
    return {"keys": len(table), "missing": missing, "stale": stale, "extra": extra,
            "placeholders": placeholders, "empty": empty}


def translations() -> list:
    return [locale for locale in l10n.LOCALES if locale != l10n.DEFAULT]


def cmd_status(_args) -> int:
    english = read_catalog(l10n.DEFAULT)
    print("%-6s %6s %8s %6s %6s %12s %6s" % ("locale", "keys", "missing", "stale", "extra",
                                              "placeholders", "empty"))
    print("%-6s %6d" % (l10n.DEFAULT, len(english)))
    for locale in translations():
        found = report(locale)
        print("%-6s %6d %8d %6d %6d %12d %6d" % (
            locale, found["keys"], len(found["missing"]), len(found["stale"]),
            len(found["extra"]), len(found["placeholders"]), len(found["empty"])))
    return 0


def cmd_export(args) -> int:
    """The keys a translator has to look at, with the English and what is there now."""
    locale = _locale(args)
    english = read_catalog(l10n.DEFAULT)
    table = read_catalog(locale)
    found = report(locale)
    wanted = sorted(set(found["missing"]) | set(found["stale"]) | set(found["placeholders"])
                    | (set(found["empty"]) & set(english)))
    # `text` is the one field a translator writes and `import` reads. `current` is only
    # there to be looked at: importing it back unread would record a stale sentence as
    # checked against the new English.
    work = {}
    for key in wanted:
        work[key] = {"en": english[key], "current": table.get(key),
                     "placeholders": sorted(l10n.placeholders(english[key])), "text": None}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(work, ensure_ascii=False, indent=2))
    return 0


def cmd_import(args) -> int:
    """Merge translated keys, refusing the whole file if any of it is wrong."""
    locale = _locale(args)
    if len(args) < 2:
        raise SystemExit("usage: import LOCALE FILE")
    incoming = json.loads(Path(args[1]).read_text(encoding="utf-8"),
                          object_pairs_hook=l10n._no_duplicates)
    english = read_catalog(l10n.DEFAULT)
    problems = []
    merged = {}
    for key, value in incoming.items():
        exported = isinstance(value, dict)
        if exported:
            value = value.get("text") or value.get("translation")
        if key not in english:
            problems.append("%s: not a key in the English catalog" % key)
            continue
        if not isinstance(value, str) or not value.strip():
            problems.append("%s: empty%s" % (key, " - write the translation in \"text\"" if exported else ""))
            continue
        if l10n.placeholders(value) != l10n.placeholders(english[key]):
            problems.append("%s: placeholders %s, English has %s" % (
                key, sorted(l10n.placeholders(value)), sorted(l10n.placeholders(english[key]))))
            continue
        merged[key] = value
    if problems:
        print("nothing imported:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    table = read_catalog(locale)
    table.update(merged)
    basis = read_basis(locale)
    for key in merged:
        basis[key] = digest(english[key])
    write_catalog(locale, table)
    write_basis(locale, basis)
    print("%s: %d keys imported" % (locale, len(merged)))
    return 0


def cmd_mark(args) -> int:
    """Record that these translations were checked against the English as it is now."""
    locale = _locale(args)
    english = read_catalog(l10n.DEFAULT)
    table = read_catalog(locale)
    keys = args[1:] or sorted(key for key in table if key in english)
    basis = read_basis(locale)
    for key in keys:
        if key not in english or key not in table:
            raise SystemExit("%s: not in both catalogs" % key)
        basis[key] = digest(english[key])
    write_basis(locale, basis)
    print("%s: %d keys marked current" % (locale, len(keys)))
    return 0


def cmd_prune(args) -> int:
    locale = _locale(args)
    english = read_catalog(l10n.DEFAULT)
    table = read_catalog(locale)
    basis = read_basis(locale)
    gone = sorted(key for key in table if key not in english)
    for key in gone:
        table.pop(key, None)
        basis.pop(key, None)
    for key in list(basis):
        if key not in english:
            basis.pop(key)
    write_catalog(locale, table)
    write_basis(locale, basis)
    print("%s: %d keys removed" % (locale, len(gone)))
    return 0


def cmd_check(_args) -> int:
    failed = False
    for locale in translations():
        found = report(locale)
        for kind in ("missing", "stale", "extra", "placeholders", "empty"):
            if found[kind]:
                failed = True
                print("%s %s: %s" % (locale, kind, ", ".join(found[kind][:12])
                                     + (" ..." if len(found[kind]) > 12 else "")))
    print("incomplete" if failed else "every catalog is complete and current")
    return 1 if failed else 0


def _locale(args) -> str:
    if not args or args[0] not in translations():
        raise SystemExit("name one of: %s" % ", ".join(translations()))
    return args[0]


COMMANDS = {"status": cmd_status, "export": cmd_export, "import": cmd_import,
            "mark": cmd_mark, "prune": cmd_prune, "check": cmd_check}


def main(argv) -> int:
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
