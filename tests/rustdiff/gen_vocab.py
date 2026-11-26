"""Generate the Rust side of vocab.json: the closed vocabularies of the leaf crates, held to the tag's.

    python -X utf8 tests/rustdiff/gen_vocab.py --write      # write the three generated files
    python -X utf8 tests/rustdiff/gen_vocab.py --check      # fail when a file differs from what the tag's vocabulary gives

`build/vocab_export.py --ref TAG` reads every closed vocabulary out of a tag (D17: v0.6.26, until it exists
v0.6.26-beta.2, `reference.STAND_IN`). The modules whose Python is ported by S1.1 land in three crates:

    car-machine  domain.*, compat.model        rust/crates/car-machine/src/vocab_gen.rs
    car-config   config, logbook               rust/crates/car-config/src/vocab_gen.rs
    car-words    l10n                          rust/crates/car-words/src/vocab_gen.rs

Each generated file holds, per Python module, the enums (members in definition order, a typed Rust enum with
`as_str`, `parse` and `ALL`) and the constants (a `&str`, a `&[&str]` or a `Const::Node` tree) and a
`MODULES` table from which `export()` writes the same JSON structure the exporter does. The diff
(tests/rustdiff/diffs_leaves_machine.py) compares that export with the tag's, byte for byte, and this
script's --check compares the committed files with a fresh generation: a word that changes in Python
fails one of the two.

The modules of the other crates (failures, reasons, settings, engine, ...) are not here: their seats hold
them (S2.x onward). `MINE` is the whole list.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUST = ROOT / "rust" / "crates"

MACHINE = ("domain.compat_vocabulary", "domain.ids", "domain.power_vocabulary", "domain.public",
           "domain.reason_vocabulary", "domain.skips", "domain.states", "domain.usage", "domain.vocabulary",
           "compat.model")
CONFIG = ("config", "logbook")
WORDS = ("l10n",)
TARGETS = {"car-machine": MACHINE, "car-config": CONFIG, "car-words": WORDS}
MINE = MACHINE + CONFIG + WORDS

KEYWORDS = {"Self", "self", "crate", "super", "type", "match", "loop", "move", "ref", "mod", "fn", "as", "use"}


def camel(name: str) -> str:
    text = "".join(part.capitalize() for part in name.lower().split("_"))
    if text[:1].isdigit():
        text = "V" + text
    return text + "_" if text in KEYWORDS else text


def literal(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def node(value, depth=0) -> str:
    if isinstance(value, str):
        return "Node::Str(%s)" % literal(value)
    if isinstance(value, list):
        return "Node::List(&[%s])" % ", ".join(node(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return "Node::Map(&[%s])" % ", ".join("(%s, %s)" % (literal(key), node(item, depth + 1))
                                              for key, item in value.items())
    raise TypeError("a vocabulary holds text, lists and dicts only: %r" % (value,))


def module_source(name: str, body: dict) -> tuple[str, str]:
    """(the Rust `pub mod`, the ModuleDef expression) of one Python module."""
    ident = name.replace(".", "_")
    out = ["pub mod %s {" % ident, "    use super::*;"]
    enums, constants = body.get("enums", {}), body.get("constants", {})
    defs = []
    for enum, found in enums.items():
        members = found["members"]
        names = [camel(member) for member, _value in members]
        assert len(set(names)) == len(names), (name, enum)
        values = [value for _member, value in members]
        assert len(set(values)) == len(values), (name, enum, "an alias")
        out.append("    #[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]")
        out.append("    pub enum %s { %s }" % (enum, ", ".join(names)))
        out.append("    impl %s {" % enum)
        out.append("        pub const ALL: &[%s] = &[%s];" % (enum, ", ".join("%s::%s" % (enum, each) for each in names)))
        out.append("        pub const fn as_str(self) -> &'static str {")
        out.append("            match self { %s }" % ", ".join("%s::%s => %s" % (enum, each, literal(value))
                                                               for each, value in zip(names, values)))
        out.append("        }")
        out.append("        pub fn parse(text: &str) -> Option<%s> {" % enum)
        out.append("            match text { %s, _ => None }" % ", ".join("%s => Some(%s::%s)" % (literal(value), enum, each)
                                                                          for each, value in zip(names, values)))
        out.append("        }")
        out.append("    }")
        defs.append("EnumDef { name: %s, base: %s, members: &[%s] }" % (
            literal(enum), literal(found["base"]),
            ", ".join("(%s, %s)" % (literal(member), literal(value)) for member, value in members)))
    consts = []
    for constant, value in constants.items():
        if isinstance(value, str):
            out.append("    pub const %s: &str = %s;" % (constant, literal(value)))
            consts.append("(%s, Const::Str(%s::%s))" % (literal(constant), ident, constant))
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            out.append("    pub const %s: &[&str] = &[%s];" % (constant, ", ".join(literal(item) for item in value)))
            consts.append("(%s, Const::Strs(%s::%s))" % (literal(constant), ident, constant))
        else:
            out.append("    pub static %s: Node = %s;" % (constant, node(value)))
            consts.append("(%s, Const::Node(&%s::%s))" % (literal(constant), ident, constant))
    out.append("}")
    definition = "ModuleDef { name: %s, enums: &[%s], constants: &[%s] }" % (literal(name), ", ".join(defs),
                                                                              ", ".join(consts))
    return "\n".join(out), definition


def generate(vocab: dict) -> dict:
    """{crate: the text of its vocab_gen.rs}."""
    files = {}
    for crate, names in TARGETS.items():
        parts = [
            "// Generated by tests/rustdiff/gen_vocab.py from `build/vocab_export.py --ref <tag>`'s vocab.json. Do not edit:",
            "// `gen_vocab.py --check` regenerates it and compares, and the diff compares `export()` with the tag's.",
            "#![allow(dead_code, unused_imports, clippy::all)]",
            "use car_machine::vocab::{Const, EnumDef, ModuleDef, Node};" if crate != "car-machine"
            else "use crate::vocab::{Const, EnumDef, ModuleDef, Node};",
            "",
        ]
        defs = []
        for name in names:
            body = vocab["modules"][name]
            source, definition = module_source(name, body)
            parts.append(source)
            parts.append("")
            defs.append("    %s," % definition)
        parts.append("/// Every module of this crate's Python, as the exporter writes it.")
        parts.append("pub static MODULES: &[ModuleDef] = &[")
        parts.extend(defs)
        parts.append("];")
        parts.append("")
        files[crate] = "\n".join(parts)
    return files


def vocabulary(ref: str) -> dict:
    scratch = ROOT / "rust" / "target" / ("vocab-%s.json" % ref.replace("/", "_"))
    scratch.parent.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    from rustdiff import reference  # the reference's Python (`--reference-python`), not sys.executable
    done = subprocess.run(reference.script_command(ROOT / "build" / "vocab_export.py", "--ref", ref, "--out", scratch, paths=[]),
                          capture_output=True, text=True, encoding="utf-8",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=600)
    if done.returncode != 0:
        raise SystemExit("vocab_export failed:\n" + done.stderr[-3000:])
    return json.loads(scratch.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ref", default=None, help="the tag (default: rustdiff.reference.TAG)")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    ref = args.ref
    if ref is None:
        sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != Path(__file__).resolve().parent]
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
        from rustdiff import reference
        ref = reference.TAG
    files = generate(vocabulary(ref))
    status = 0
    for crate, text in files.items():
        path = RUST / crate / "src" / "vocab_gen.rs"
        if args.write:
            path.write_bytes(text.encode("utf-8"))
        elif path.read_bytes().decode("utf-8") != text:
            print("%s differs from the vocabulary of %s: run gen_vocab.py --write" % (path.relative_to(ROOT), ref))
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
