"""Generate car-brand's data tables from the reference tag's `codex_auto_resume.brand` and `ui.tray.motion`.

    python -X utf8 tests/rustdiff/gen_brand.py --write | --check

The palettes, the scale, the shadow recipes, the light's numbers, the mark's shape, the day tables (LUNAR_DAYS
among them) and the icon's motion are data in Python, and car-brand reads the same data from
`rust/crates/car-brand/src/tables_gen.rs`, written here from the tag's own modules (run in the tag's package by
`reference.run`). Each value keeps its Python type - an int stays `Num::I`, a float `Num::F` written as its repr -
because the answers the diffs compare carry it (`16` is not `16.0`). What the brand computes (the scenes, the marks,
the CSS, gui/Brand.cs) is hand-written Rust; only the tables are made here. diffs_leaves_brand compares what Rust
answers with the tag's, so a table that goes stale fails it until this is run again.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "rust" / "crates" / "car-brand" / "src" / "tables_gen.rs"

# Runs under the reference tag: every table by its Rust name, as JSON that keeps ints, floats and key order.
DUMP = r'''
import json, sys
from codex_auto_resume import brand
from codex_auto_resume.brand import checkbox, css, days, design, elevation, light, mark, scale, shape, tokens
from codex_auto_resume.ui.tray import motion

def plain(value):
    if isinstance(value, dict):
        return {"dict": [[key, plain(each)] for key, each in value.items()]}
    if isinstance(value, (tuple, list)):
        return {"list": [plain(each) for each in value]}
    return value

named = {id(value): name for name, value in (("LIGHT", tokens.LIGHT), ("DARK", tokens.DARK),
         ("CLASSIC_LIGHT", tokens.CLASSIC_LIGHT), ("CLASSIC_DARK", tokens.CLASSIC_DARK),
         ("PLAIN_LIGHT", tokens.PLAIN_LIGHT), ("PLAIN_DARK", tokens.PLAIN_DARK))}
tables = [
    ("RAMP", tokens.RAMP), ("BRAND", tokens.BRAND), ("LIGHT", tokens.LIGHT), ("DARK", tokens.DARK),
    ("CLASSIC_LIGHT", tokens.CLASSIC_LIGHT), ("CLASSIC_DARK", tokens.CLASSIC_DARK),
    ("PLAIN_LIGHT", tokens.PLAIN_LIGHT), ("PLAIN_DARK", tokens.PLAIN_DARK),
    ("DESIGN_TOKENS", {name: [named[id(pair[0])], named[id(pair[1])]] for name, pair in tokens.DESIGN_TOKENS.items()}),
    ("DESIGNS", tokens.DESIGNS), ("THEMES", tokens.THEMES), ("EDITION_INK", tokens.EDITION_INK),
    ("RADII", scale.RADII), ("CORNER_SMOOTHING", scale.CORNER_SMOOTHING), ("WINDOW_SQUIRCLE", scale.WINDOW_SQUIRCLE),
    ("SPACING", scale.SPACING), ("TYPE", scale.TYPE), ("TYPE_SCALE", scale.TYPE_SCALE), ("LINE_HEIGHT", scale.LINE_HEIGHT),
    ("TYPE_ROLES", scale.TYPE_ROLES), ("LAYOUT", scale.LAYOUT), ("CAPTION_STROKE", scale.CAPTION_STROKE),
    ("DESIGN", design.DESIGN), ("DESIGN_RADII", design.DESIGN_RADII), ("ACCENT_BAR", design.ACCENT_BAR),
    ("DEFAULT_DESIGN", design.DEFAULT_DESIGN),
    ("MOTION", brand.MOTION),
    ("SHADOWS", elevation.SHADOWS), ("CARD_LIFT", elevation.CARD_LIFT),
    ("CHECKBOX", checkbox.CHECKBOX), ("CHECKBOX_SYSTEM", checkbox.CHECKBOX_SYSTEM), ("SYSTEM_CSS", checkbox.SYSTEM_CSS),
    ("CHECK_MARK", checkbox.CHECK_MARK),
    ("STATUS_DOT", light.STATUS_DOT), ("STATUS_FILL", light.STATUS_FILL), ("STATUS_SYSTEM", light.STATUS_SYSTEM),
    ("GLOW", light.GLOW), ("GLOW_BREATHES", light.GLOW_BREATHES),
    ("ICON_TOP", mark.ICON_TOP), ("ICON_BOTTOM", mark.ICON_BOTTOM), ("ICON_MARK", mark.ICON_MARK),
    ("ICON_ACCENT", mark.ICON_ACCENT), ("ICON_SHAPE", mark.ICON_SHAPE), ("ICON_SUPERSAMPLE", mark.ICON_SUPERSAMPLE),
    ("GLOW_STOPS", css.GLOW_STOPS), ("CORNER_ROLES", css.CORNER_ROLES),
    ("DESIGN_SMOOTHING", shape.DESIGN_SMOOTHING), ("CSS_CORNER", shape.CSS_CORNER), ("RHO_STEPS", shape.RHO_STEPS),
    ("HALF_STEPS", shape._HALF_STEPS), ("PROFILE_LIMIT", shape._PROFILE_LIMIT),
    ("DAY_LOOKS", days.DAY_LOOKS), ("FIXED_DAYS", days.FIXED_DAYS), ("LUNAR_DAYS", days.LUNAR_DAYS),
    ("MOTIF_LEAST", days.MOTIF_LEAST), ("SCENE_WIDTH", days.SCENE_WIDTH), ("SCENE_HEIGHT", days.SCENE_HEIGHT),
    ("SCENE_FOCUS", days.SCENE_FOCUS), ("SCENE_FROM_TOP", days.SCENE_FROM_TOP), ("CONFETTI_COLOURS", days._CONFETTI_COLOURS),
    ("SPECK_BAND", days.SPECK_BAND), ("WIDE", days.WIDE), ("PRESSES", days.PRESSES), ("SWEEP", days.SWEEP),
    ("DAY_RINGS", days.DAY_RINGS), ("DAY_EGG_COLOURS", days.DAY_EGG_COLOURS),
    ("ICON_STATES", motion.ICON_STATES), ("ICON_BRAND_STATE", motion.ICON_BRAND_STATE), ("ICON_FOR_LIGHT", motion.ICON_FOR_LIGHT),
    ("ICON_BREATHS", motion.ICON_BREATHS), ("ICON_SWEEPS", motion.ICON_SWEEPS), ("ICON_TRAVEL_BREATHS", motion.ICON_TRAVEL_BREATHS),
    ("ICON_MOTION", motion.ICON_MOTION), ("ICON_HEAD_PALETTE", motion.ICON_HEAD_PALETTE),
]
sys.stdout.write(json.dumps([[name, plain(value)] for name, value in tables]))
'''


def literal(value) -> str:
    """One Python value as a car-brand `D`."""
    if value is None:
        return "D::Null"
    if isinstance(value, bool):
        return "D::B(%s)" % ("true" if value else "false")
    if isinstance(value, int):
        return "D::N(Num::I(%d))" % value
    if isinstance(value, float):
        text = repr(value)
        return "D::N(Num::F(%s))" % (text if any(mark in text for mark in ".en") else text + ".0")
    if isinstance(value, str):
        return "D::S(%s)" % json.dumps(value, ensure_ascii=False)
    if "dict" in value:
        return "D::M(&[%s])" % ", ".join("(%s, %s)" % (json.dumps(key, ensure_ascii=False), literal(each))
                                        for key, each in value["dict"])
    return "D::L(&[%s])" % ", ".join(literal(each) for each in value["list"])


def render(tables) -> str:
    lines = ["// Generated by tests/rustdiff/gen_brand.py from the reference tag's brand and ui/tray/motion. Do not edit:",
             "// `gen_brand.py --check` regenerates it and compares, and diffs_leaves_brand holds every answer to the tag's.",
             "#![allow(dead_code, clippy::all)]",
             "use crate::data::{Num, D};",
             ""]
    for name, value in tables:
        lines.append("pub static %s: D = %s;" % (name, literal(value)))
    return "\n".join(lines) + "\n"


def made() -> str:
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != Path(__file__).resolve().parent]
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    from rustdiff import reference
    done = reference.run(DUMP)
    if done.returncode != 0:
        raise SystemExit(done.stderr.decode("utf-8", "replace")[-3000:])
    return render(json.loads(done.stdout.decode("utf-8")))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = made()
    if args.write:
        TARGET.write_bytes(text.encode("utf-8"))
        return 0
    if not TARGET.is_file() or TARGET.read_bytes().decode("utf-8") != text:
        print("%s is not what %s's brand makes: run gen_brand.py --write" % (TARGET.relative_to(ROOT).as_posix(), "the reference tag"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
