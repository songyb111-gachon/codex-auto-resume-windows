"""Write (or check) the advanced store's generated Rust files from a tag (seat S7.1a, car-adv `state/`).

    python -X utf8 tests/rustdiff/gen_advstore.py --write [--ref v0.6.26-beta.2]
    python -X utf8 tests/rustdiff/gen_advstore.py --check [--ref v0.6.26]

Three files, each read out of the tag's own modules in a process of its own (advreference.run), never typed by hand:

* `advanced/rust/crates/car-adv/src/state/schema_gen.rs` - every public constant of `state/schema.py` that is a
  number, a word, a list of words or a table of columns: the CREATE statements and every upgrade step exactly as
  the tag builds them (the dumps compare `sqlite_master` text, so a statement is the tag's bytes or it is wrong).
* `advanced/rust/crates/car-adv/src/state/seam/words_gen.rs` - the members of every closed vocabulary the store
  writes or reads (`vocabulary.py`'s StrEnums named in WORDS), in their definition order, and KEPT_NOTICES.
* `advanced/rust/crates/car-adv/src/state/seam/registry_gen.rs` - what the store asks of each capability of the
  tag's REGISTRY (its id, points, departures, ceilings, journal prefix and codes, options, wordings, flags), in the
  registry's order, and the three numbers it reads (GLOBAL_HOURLY, CORE_DAILY_CAP, CORE_COOLDOWN_SECONDS).

The last two are seams: seat S7.1b ports `vocabulary.py` and `registry.py` into car-adv beside this seat, and the
integration replaces both files with S7.1b's modules (rust/GROUNDWORK.md, "The advanced store").
`--check` exits 1 naming each file that differs from what the tag gives.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import advreference  # noqa: E402
import reference  # noqa: E402

ROOT = HERE.parents[1]
STATE = ROOT / "advanced" / "rust" / "crates" / "car-adv" / "src" / "state"
SCHEMA = STATE / "schema_gen.rs"
WORDS_FILE = STATE / "seam" / "words_gen.rs"
REGISTRY_FILE = STATE / "seam" / "registry_gen.rs"

# The vocabularies the store reads or writes (state/*.py, ledger.py, watchlog.py).
WORDS = ("ArmingState", "Actor", "OffReason", "ArmingWarning", "Refusal", "JournalCode", "RecordState",
         "OverrideKind", "OptionKey", "WordingKey", "KeepOn", "Ceiling", "RunEnd", "ChatState", "ChatReason",
         "RuleState", "RuleReason", "SpendOutcome", "ContinuationKind", "ContinuationReason", "KeepState",
         "KeepReason", "PromptTrigger", "PromptEvery", "PromptState", "PromptReason", "WhileRunning",
         "CourierChannel", "CourierEvent", "OutboxState", "FeedWord", "OpenOutcome", "HookOutcome", "PlanWord",
         "SteerState", "SteerReason")

READ = r'''
import enum, json, sys
from codex_auto_resume_advanced.state import schema
from codex_auto_resume_advanced import vocabulary, registry

def plain(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return {"int": value}
    if isinstance(value, str):
        return {"str": str(value)}
    if isinstance(value, (tuple, list)) and all(isinstance(each, str) for each in value):
        return {"strs": [str(each) for each in value]}
    if isinstance(value, dict) and all(isinstance(key, str) and isinstance(each, (tuple, list))
                                       and all(isinstance(word, str) for word in each) for key, each in value.items()):
        return {"tables": [[key, [str(word) for word in each]] for key, each in value.items()]}
    return None

constants = []
for name, value in vars(schema).items():
    if name.startswith("_") or not name.isupper():
        continue
    found = plain(value)
    if found is not None:
        constants.append([name, found])
words = {}
for name in sys.argv[1].split(","):
    kind = getattr(vocabulary, name)
    words[name] = [[member.name, str(member.value)] for member in kind]
kept = [str(word) for word in vocabulary.KEPT_NOTICES]
definitions = []
for definition in registry.REGISTRY:
    ceilings = definition.ceilings
    definitions.append({
        "id": definition.id, "points": sorted(str(point) for point in definition.points),
        "departs_from": [str(each) for each in definition.departs_from],
        "ceilings": None if ceilings is None else [ceilings.per_day, ceilings.per_conversation],
        "journal_prefix": definition.journal_prefix, "codes": [str(code) for code in definition.codes],
        "options": [{"key": str(option.key), "choices": list(option.choices), "default": option.default,
                     "custom": None if option.custom is None else list(option.custom)}
                    for option in definition.options],
        "rules_editor": bool(definition.rules_editor), "samples": bool(definition.samples),
        "resends": bool(definition.resends), "wordings": [str(each) for each in definition.wordings]})
numbers = {name: getattr(registry, name) for name in ("GLOBAL_HOURLY", "CORE_DAILY_CAP", "CORE_COOLDOWN_SECONDS")}
print(json.dumps({"constants": constants, "words": words, "kept": kept, "registry": definitions,
                  "numbers": numbers}, ensure_ascii=False))
'''

HEADER = ("// Generated by tests/rustdiff/gen_advstore.py from {ref}'s {source}; do not edit.\n"
          "// `python -X utf8 tests/rustdiff/gen_advstore.py --check --ref TAG` says whether it is stale.\n")


def rust_str(text: str) -> str:
    out = []
    for character in text:
        if character == "\\":
            out.append("\\\\")
        elif character == '"':
            out.append('\\"')
        elif character == "\n":
            out.append("\\n")
        elif character == "\t":
            out.append("\\t")
        elif ord(character) < 0x20 or ord(character) == 0x7F:
            out.append("\\u{%x}" % ord(character))
        else:
            out.append(character)
    return '"%s"' % "".join(out)


def strs(items) -> str:
    return "&[%s]" % ", ".join(rust_str(each) for each in items)


def snake(name: str) -> str:
    out = []
    for index, character in enumerate(name):
        if character.isupper() and index:
            out.append("_")
        out.append(character.lower())
    return "".join(out)


def read(ref: str) -> dict:
    done = advreference.run(READ, ",".join(WORDS), tag=ref)
    if done.returncode != 0:
        raise SystemExit("the tag's modules could not be read:\n%s" % done.stderr.decode("utf-8", "replace")[-3000:])
    return json.loads(done.stdout.decode("utf-8"))


def schema_file(found: dict, ref: str) -> str:
    lines = [HEADER.format(ref=ref, source="advanced/src/codex_auto_resume_advanced/state/schema.py"),
             "//! Every public constant of the tag's `state/schema.py` that is a number, a word, a list of words or a",
             "//! table of columns, in the module's order.", "",
             "#![allow(dead_code)]", ""]
    for name, value in found["constants"]:
        if "int" in value:
            lines.append("pub const %s: i64 = %d;" % (name, value["int"]))
        elif "str" in value:
            lines.append("pub const %s: &str = %s;" % (name, rust_str(value["str"])))
        elif "strs" in value:
            lines.append("pub const %s: &[&str] = %s;" % (name, strs(value["strs"])))
        else:
            tables = ", ".join("(%s, %s)" % (rust_str(table), strs(columns)) for table, columns in value["tables"])
            lines.append("pub const %s: &[(&str, &[&str])] = &[%s];" % (name, tables))
    return "\n".join(lines) + "\n"


def words_file(found: dict, ref: str) -> str:
    lines = [HEADER.format(ref=ref, source="advanced/src/codex_auto_resume_advanced/vocabulary.py"),
             "//! SEAM (seat S7.1a): the closed vocabularies the advanced store reads and writes, each a module of its",
             "//! members' words and `ALL` in definition order. Seat S7.1b ports `vocabulary.py` itself; the integration",
             "//! replaces this file with its module.", "",
             "#![allow(dead_code)]", ""]
    for name in WORDS:
        lines.append("pub mod %s {" % snake(name))
        for member, word in found["words"][name]:
            lines.append("    pub const %s: &str = %s;" % (member, rust_str(word)))
        lines.append("    pub const ALL: &[&str] = %s;" % strs(word for _member, word in found["words"][name]))
        lines.append("}")
    lines.append("/// `KEPT_NOTICES`, least serious first.")
    lines.append("pub const KEPT_NOTICES: &[&str] = %s;" % strs(found["kept"]))
    return "\n".join(lines) + "\n"


def registry_file(found: dict, ref: str) -> str:
    lines = [HEADER.format(ref=ref, source="advanced/src/codex_auto_resume_advanced/registry.py"),
             "//! SEAM (seat S7.1a): what the advanced store asks of the tag's REGISTRY, in its order. Seat S7.1b ports",
             "//! `registry.py`; the integration replaces this table with its `REGISTRY`.", "",
             "use super::registry::{Definition, OptionDef};", ""]
    for name, value in found["numbers"].items():
        lines.append("pub const %s: i64 = %d;" % (name, value))
    lines.append("")
    lines.append("pub static SHIPPED: &[Definition] = &[")
    for each in found["registry"]:
        options = ", ".join(
            "OptionDef { key: %s, choices: &[%s], default: %d, custom: %s }"
            % (rust_str(option["key"]), ", ".join(str(choice) for choice in option["choices"]), option["default"],
               "None" if option["custom"] is None else "Some((%d, %d))" % tuple(option["custom"]))
            for option in each["options"])
        lines.append("    Definition {")
        lines.append("        id: %s," % rust_str(each["id"]))
        lines.append("        points: %s," % strs(each["points"]))
        lines.append("        departs_from: %s," % strs(each["departs_from"]))
        lines.append("        ceilings: %s," % ("None" if each["ceilings"] is None
                                                 else "Some((%d, %d))" % tuple(each["ceilings"])))
        lines.append("        journal_prefix: %s," % rust_str(each["journal_prefix"]))
        lines.append("        codes: %s," % strs(each["codes"]))
        lines.append("        options: &[%s]," % options)
        lines.append("        rules_editor: %s," % str(each["rules_editor"]).lower())
        lines.append("        samples: %s," % str(each["samples"]).lower())
        lines.append("        resends: %s," % str(each["resends"]).lower())
        lines.append("        wordings: %s," % strs(each["wordings"]))
        lines.append("    },")
    lines.append("];")
    return "\n".join(lines) + "\n"


def generate(ref: str) -> dict:
    found = read(ref)
    return {SCHEMA: schema_file(found, ref), WORDS_FILE: words_file(found, ref), REGISTRY_FILE: registry_file(found, ref)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default=reference.TAG)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    options = parser.parse_args(argv)
    files = generate(options.ref)
    stale = []
    for path, text in files.items():
        # The header names the tag; a check against another tag compares what follows it.
        body = text.split("\n", 2)[2]
        held = path.read_text(encoding="utf-8").split("\n", 2)[2] if path.exists() else None
        if options.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        elif held != body:
            stale.append(path.relative_to(ROOT).as_posix())
    if options.check:
        if stale:
            print("car-adv: generated files differ from %s: %s" % (options.ref, ", ".join(stale)))
            return 1
        print("car-adv: generated files (schema, words, registry) match %s" % options.ref)
    else:
        print("car-adv: wrote %s from %s" % (", ".join(path.name for path in files), options.ref))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
