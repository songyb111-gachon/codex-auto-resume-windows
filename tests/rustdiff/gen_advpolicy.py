"""Generate the advanced edition's tables for car-adv (S7.1b), from the reference tag's own advanced package.

    python -X utf8 tests/rustdiff/gen_advpolicy.py --write      # write the five generated files
    python -X utf8 tests/rustdiff/gen_advpolicy.py --check      # fail when a file differs from what the tag gives
    python -X utf8 tests/rustdiff/gen_advpolicy.py --ref v0.6.26 --check

The tag's advanced package is imported in a child (advref.run: PYTHONPATH the tag's src and advanced/src, edition
advanced, every home a scratch folder) and dumps, as JSON:

* `vocabulary`: every enum of advanced/vocabulary.py (members in definition order) and its four set/tuple constants
                                                                           -> car-adv/src/vocabulary_gen.rs
* `measured`:   measured.MEASURED, the build-time table of what each measurement found
                                                                           -> car-adv/src/measured_gen.rs
* `registry`:   each capability of registry.DEFINITIONS, WAITING, INSTALLED_ONLY and SHOWN_ORDER as data (every field
                but `make`, the factory the plug seat attaches) and registry's constants -> car-adv/src/registry_gen.rs
* `statement`:  the catalog key lists (statement.PAGE_KEYS, CONTINUATION_KEYS, EDITION_KEYS)
                                                                           -> car-adv/src/statement_gen.rs
(autocheck.CHECKS is no longer generated: S7.2c's car-adv/src/autocheck.rs holds the whole table, and
diffs_advcodex_autocheck.py holds every row of it to the tag's.)

Nothing here is written by hand: a word that changes in Python fails `--check`, and the diffs (diffs_advpolicy_*.py)
hold what the Rust code does with the tables.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "advanced" / "rust" / "crates" / "car-adv" / "src"

DUMP = r'''
import enum, json, sys
from codex_auto_resume_advanced import vocabulary, measured, registry, statement, autocheck, standards

def enums(module):
    found = {}
    for name, value in vars(module).items():
        if isinstance(value, type) and issubclass(value, enum.Enum) and value.__module__ == module.__name__:
            found[name] = [[member, item.value] for member, item in value.__members__.items()]
    return found

def option(item):
    return {"key": str(item.key), "choices": list(item.choices), "default": item.default,
            "custom": None if item.custom is None else list(item.custom)}

def definition(item):
    return {"id": item.id, "kind": str(item.kind), "points": sorted(str(point) for point in item.points),
            "revision": item.revision, "departs_from": list(item.departs_from), "compat": item.compat,
            "ceilings": None if item.ceilings is None else [item.ceilings.per_day, item.ceilings.per_conversation],
            "journal_prefix": item.journal_prefix, "codes": list(item.codes),
            "measurements": [str(each) for each in item.measurements],
            "options": [option(each) for each in item.options], "rules_editor": item.rules_editor,
            "samples": item.samples, "resends": item.resends, "requires": list(item.requires),
            "wordings": [str(each) for each in item.wordings],
            "narrowed_by": [str(each) for each in item.narrowed_by], "sends": item.sends}

def names(many):
    many = many if isinstance(many, tuple) else (many,)
    return [str(each) for each in many]

shown = {name: value for name, value in vars(vocabulary).items() if name in ("TRIPWIRES", "KEPT_NOTICES", "NOTE_FOR_PASS", "NOTE_FOR_FAIL")}
print(json.dumps({
    "vocabulary": {"enums": enums(vocabulary),
                   "TRIPWIRES": [str(each) for each in vocabulary.OffReason if each in vocabulary.TRIPWIRES],
                   "KEPT_NOTICES": [str(each) for each in vocabulary.KEPT_NOTICES],
                   "NOTE_FOR_PASS": [str(each) for each in vocabulary.NoteCode if each in vocabulary.NOTE_FOR_PASS],
                   "NOTE_FOR_FAIL": [str(each) for each in vocabulary.NoteCode if each in vocabulary.NOTE_FOR_FAIL]},
    "measured": [[str(key), str(verdict), engine] for key, (verdict, engine) in measured.MEASURED.items()],
    "registry": {"definitions": [definition(each) for each in registry.DEFINITIONS],
                 "waiting": [[each.id, names(measurement)] for each, measurement in registry.WAITING],
                 "waiting_tuple": [isinstance(measurement, tuple) for _each, measurement in registry.WAITING],
                 "installed_only": [each.id for each in registry.INSTALLED_ONLY],
                 "waiting_definitions": [definition(each) for each, _m in registry.WAITING],
                 "installed_definitions": [definition(each) for each in registry.INSTALLED_ONLY],
                 "shown_order": list(registry.SHOWN_ORDER),
                 "global_hourly": registry.GLOBAL_HOURLY, "core_daily_cap": registry.CORE_DAILY_CAP,
                 "core_cooldown_seconds": registry.CORE_COOLDOWN_SECONDS},
    "statement": {"page_keys": list(statement.PAGE_KEYS), "continuation_keys": list(statement.CONTINUATION_KEYS),
                  "edition_keys": list(statement.EDITION_KEYS), "warning_keys": list(statement.WARNING_KEYS)},
    "autocheck": [[str(key), str(row.reach)] for key, row in autocheck.CHECKS.items()],
    "standards": [[prefix, count] for prefix, count in standards.FAMILIES],
}, ensure_ascii=False))
'''

KEYWORDS = {"Self", "self", "crate", "super", "type", "match", "loop", "move", "ref", "mod", "fn", "as", "use"}


def camel(name: str) -> str:
    text = "".join(part.capitalize() for part in name.lower().split("_"))
    if text[:1].isdigit():
        text = "V" + text
    return text + "_" if text in KEYWORDS else text


def lit(text) -> str:
    return json.dumps(text, ensure_ascii=False)


def strs(items) -> str:
    return "&[%s]" % ", ".join(lit(item) for item in items)


HEADER = ("// Generated by tests/rustdiff/gen_advpolicy.py from the reference tag's advanced package. Do not edit:\n"
          "// `gen_advpolicy.py --check` regenerates it and compares, and diffs_advpolicy_*.py hold what the code does with it.\n"
          "#![allow(clippy::all)]\n")


def vocabulary(found: dict) -> str:
    out = [HEADER, "use crate::vocabulary::ClosedWord;", ""]
    for name, members in found["enums"].items():
        names = [camel(member) for member, _value in members]
        values = [value for _member, value in members]
        assert len(set(names)) == len(names) and len(set(values)) == len(values), name
        out.append("#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]")
        out.append("pub enum %s { %s }" % (name, ", ".join(names)))
        out.append("impl %s {" % name)
        out.append("    pub const ALL: &[%s] = &[%s];" % (name, ", ".join("%s::%s" % (name, each) for each in names)))
        out.append("    pub const fn as_str(self) -> &'static str {")
        out.append("        match self { %s }" % ", ".join("%s::%s => %s" % (name, each, lit(value))
                                                          for each, value in zip(names, values)))
        out.append("    }")
        out.append("    pub fn parse(text: &str) -> Option<%s> {" % name)
        out.append("        match text { %s, _ => None }" % ", ".join("%s => Some(%s::%s)" % (lit(value), name, each)
                                                                     for each, value in zip(names, values)))
        out.append("    }")
        out.append("}")
        out.append("impl ClosedWord for %s {" % name)
        out.append("    fn word(self) -> &'static str { self.as_str() }")
        out.append("    fn all() -> &'static [Self] { Self::ALL }")
        out.append("}")
        out.append("")
    byvalue = {name: {value: camel(member) for member, value in members} for name, members in found["enums"].items()}

    def listing(constant, enum):
        return "pub const %s: &[%s] = &[%s];" % (
            constant, enum, ", ".join("%s::%s" % (enum, byvalue[enum][each]) for each in found[constant]))
    out.append("/// Every enum with its values, in definition order: what a surface or a test lists the vocabulary by.")
    out.append("pub const ENUMS: &[(&str, &[&str])] = &[")
    for name, members in found["enums"].items():
        out.append("    (%s, %s)," % (lit(name), strs([value for _member, value in members])))
    out.append("];")
    out.append("")
    out.append("/// `Enum(text)` by the enum's name: the value it names, or `None` where the tag raises `ValueError`.")
    out.append("/// The outer `None` is an enum this vocabulary does not have.")
    out.append("pub fn parse_member(enum_name: &str, text: &str) -> Option<Option<&'static str>> {")
    out.append("    Some(match enum_name {")
    for name in found["enums"]:
        out.append("        %s => %s::parse(text).map(%s::as_str)," % (lit(name), name, name))
    out.append("        _ => return None,")
    out.append("    })")
    out.append("}")
    out.append("")
    out.append("/// The off reasons that are tripwires, in the enum's order (a set in Python).")
    out.append(listing("TRIPWIRES", "OffReason"))
    out.append("/// What a kept-on capability notes, most serious first: the order matters.")
    out.append(listing("KEPT_NOTICES", "OffReason"))
    out.append(listing("NOTE_FOR_PASS", "NoteCode"))
    out.append(listing("NOTE_FOR_FAIL", "NoteCode"))
    out.append("")
    return "\n".join(out)


def measured(rows: list, enums: dict) -> str:
    verdict = {value: camel(member) for member, value in enums["Verdict"]}
    measurement = {value: camel(member) for member, value in enums["Measurement"]}
    out = [HEADER, "use crate::vocabulary::{Measurement, Verdict};", "",
           "/// What each measurement found, as this build ships it: (measurement, verdict, the Codex it was made on), in the",
           "/// table's order.", "pub const MEASURED: &[(Measurement, Verdict, &str)] = &["]
    for key, found, engine in rows:
        out.append("    (Measurement::%s, Verdict::%s, %s)," % (measurement[key], verdict[found], lit(engine)))
    out += ["];", ""]
    return "\n".join(out)


def registry(found: dict, enums: dict) -> str:
    measurement = {value: camel(member) for member, value in enums["Measurement"]}
    option_key = {value: camel(member) for member, value in enums["OptionKey"]}
    wording = {value: camel(member) for member, value in enums["WordingKey"]}
    kind = {value: camel(member) for member, value in enums["CapabilityKind"]}
    point = lambda text: "".join(part.capitalize() for part in text.split("_"))  # noqa: E731

    def one(item) -> str:
        ceilings = "None" if item["ceilings"] is None else "Some(Ceilings { per_day: %d, per_conversation: %d })" % tuple(item["ceilings"])
        options = ", ".join("OptionDef { key: OptionKey::%s, choices: vec![%s], default: %d, custom: %s }" % (
            option_key[each["key"]], ", ".join(str(choice) for choice in each["choices"]), each["default"],
            "None" if each["custom"] is None else "Some((%d, %d))" % tuple(each["custom"])) for each in item["options"])
        sends = "None" if item["sends"] is None else "Some(%s)" % str(item["sends"]).lower()
        return ("CapabilityDef { id: %s.into(), kind: CapabilityKind::%s, points: vec![%s], revision: %d, departs_from: %s, "
                "compat: %s, ceilings: %s, journal_prefix: %s.into(), codes: %s, measurements: vec![%s], options: vec![%s], "
                "rules_editor: %s, samples: %s, resends: %s, requires: %s, wordings: vec![%s], narrowed_by: vec![%s], "
                "sends: %s }") % (
            lit(item["id"]), kind[item["kind"]], ", ".join("Point::" + point(each) for each in item["points"]),
            item["revision"], "owned(%s)" % strs(item["departs_from"]),
            "None" if item["compat"] is None else "Some(%s.into())" % lit(item["compat"]), ceilings,
            lit(item["journal_prefix"]), "owned(%s)" % strs(item["codes"]),
            ", ".join("Measurement::" + measurement[each] for each in item["measurements"]), options,
            str(item["rules_editor"]).lower(), str(item["samples"]).lower(), str(item["resends"]).lower(),
            "owned(%s)" % strs(item["requires"]), ", ".join("WordingKey::" + wording[each] for each in item["wordings"]),
            ", ".join("Measurement::" + measurement[each] for each in item["narrowed_by"]), sends)

    out = [HEADER, "use car_policy::plug::Point;", "",
           "use crate::registry::{CapabilityDef, Ceilings, OptionDef, owned};",
           "use crate::vocabulary::{CapabilityKind, Measurement, OptionKey, WordingKey};", "",
           "pub const GLOBAL_HOURLY: i64 = %d;" % found["global_hourly"],
           "pub const CORE_DAILY_CAP: i64 = %d;" % found["core_daily_cap"],
           "pub const CORE_COOLDOWN_SECONDS: i64 = %d;" % found["core_cooldown_seconds"], "",
           "/// registry.DEFINITIONS, in the order they answer in.",
           "pub fn definitions() -> Vec<CapabilityDef> {", "    vec!["]
    out += ["        %s," % one(each) for each in found["definitions"]]
    out += ["    ]", "}", "",
            "/// registry.WAITING: the hidden capabilities, each with the measurements that must all pass first.",
            "pub fn waiting() -> Vec<(CapabilityDef, Vec<Measurement>)> {", "    vec!["]
    for definition, (_id, needs) in zip(found["waiting_definitions"], found["waiting"]):
        out.append("        (%s, vec![%s])," % (one(definition), ", ".join("Measurement::" + measurement[each] for each in needs)))
    out += ["    ]", "}", "",
            "/// registry.INSTALLED_ONLY: what only an installation (a bundled runtime beside the source) can have.",
            "pub fn installed_only() -> Vec<CapabilityDef> {", "    vec!["]
    out += ["        %s," % one(each) for each in found["installed_definitions"]]
    out += ["    ]", "}", "", "/// registry.SHOWN_ORDER.", "pub const SHOWN_ORDER: &[&str] = %s;" % strs(found["shown_order"]), ""]
    return "\n".join(out)


def statement(found: dict) -> str:
    out = [HEADER]
    for name, key in (("PAGE_KEYS", "page_keys"), ("CONTINUATION_KEYS", "continuation_keys"),
                      ("EDITION_KEYS", "edition_keys"), ("WARNING_KEYS", "warning_keys")):
        out.append("pub const %s: &[&str] = %s;" % (name, strs(found[key])))
    out.append("")
    return "\n".join(out)


def autocheck(rows: list) -> str:
    out = [HEADER, "use crate::vocabulary::{CheckReach, Measurement};", "",
           "/// autocheck.CHECKS' reach column: the rows the check has, with how much of each it can answer.",
           "pub const REACH: &[(Measurement, CheckReach)] = &["]
    for key, reach in rows:
        out.append("    (Measurement::%s, CheckReach::%s)," % (camel(key), camel(reach)))
    out += ["];", ""]
    return "\n".join(out)


def standards(rows: list) -> str:
    return "\n".join([HEADER, "/// standards.FAMILIES: (prefix, how many), in the order the file has them.",
                      "pub const FAMILIES: &[(&str, u32)] = &[%s];" % ", ".join("(%s, %d)" % (lit(p), n) for p, n in rows), ""])


def dump(ref: str | None) -> dict:
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != Path(__file__).resolve().parent]
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    from rustdiff import advref, reference
    if ref:
        reference.TAG = ref
    done = advref.run(DUMP, tag=ref or reference.TAG)
    if done.returncode != 0:
        raise SystemExit("the reference could not dump its tables:\n" + done.stderr[-3000:].decode("utf-8", "replace"))
    return json.loads(done.stdout.decode("utf-8"))


def generate(found: dict) -> dict:
    enums = {name: members for name, members in found["vocabulary"]["enums"].items()}
    voc = dict(found["vocabulary"])
    return {"vocabulary_gen.rs": vocabulary(voc),
            "measured_gen.rs": measured(found["measured"], enums),
            "registry_gen.rs": registry(found["registry"], enums),
            "statement_gen.rs": statement(found["statement"]),
            "standards_gen.rs": standards(found["standards"])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ref", default=None, help="the tag (default: rustdiff.reference.TAG)")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    files = generate(dump(args.ref))
    status = 0
    for name, text in files.items():
        path = CRATE / name
        if args.write:
            path.write_bytes(text.encode("utf-8"))
        elif not path.is_file() or path.read_bytes().decode("utf-8") != text:
            print("%s differs from what %s gives: run gen_advpolicy.py --write" % (path.relative_to(ROOT), args.ref or "the reference"))
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
