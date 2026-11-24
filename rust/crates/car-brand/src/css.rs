//! Everything that writes CSS, and nothing that decides a value (brand/css.py): the panel's stylesheet properties,
//! byte for byte as the tag writes them.

use crate::Py;
use crate::checkbox::{CHECKBOX, check_mark_outline};
use crate::data::D;
use crate::design::{DESIGN_RADII, design_depth};
use crate::elevation::{self, SHADOWS};
use crate::light::{
    GLOW, GLOW_BREATHES, STATUS_DOT, glow_extent, glow_phase, glow_radius, glow_reach,
};
use crate::motion::MOTION;
use crate::pyfmt;
use crate::scale::{LAYOUT, LINE_HEIGHT, RADII, SPACING, TYPE_SCALE, parts as layout_parts};
use crate::shape::{CSS_CORNER, design_smoothing};
use crate::tokens::{DESIGNS, THEMES, design_tokens, palette, theme_name};

pub use crate::tables_gen::{CORNER_ROLES, GLOW_STOPS};

/// `_number(value)`: a number as a stylesheet or a C# literal writes it: 14, 12.5, 0.3.
pub fn number(value: f64) -> String {
    let value = pyfmt::round_to(value, 4);
    if value.fract() == 0.0 && value.is_finite() {
        pyfmt::d(value)
    } else {
        pyfmt::repr(value)
    }
}

/// `_css_length(value)`: "0", or the number in px.
pub fn css_length(value: f64) -> String {
    if value == 0.0 {
        "0".to_owned()
    } else {
        format!("{}px", number(value))
    }
}

fn hyphens(name: &str) -> String {
    name.replace('_', "-")
}

/// `css_scale()`: the scale as CSS custom properties, for the panel's stylesheet.
pub fn css_scale() -> Py<String> {
    let mut parts = Vec::new();
    for (prefix, table) in [
        ("radius", &RADII),
        ("space", &SPACING),
        ("type", &TYPE_SCALE),
    ] {
        for (name, value) in table.items() {
            parts.push(format!(
                "--{prefix}-{}: {}px;",
                hyphens(name),
                number(value.f())
            ));
        }
    }
    for (name, value) in LINE_HEIGHT.items() {
        parts.push(format!("--lh-{}: {};", hyphens(name), number(value.f())));
    }
    for (name, value) in LAYOUT.items() {
        let lengths: Vec<String> = layout_parts(value)
            .iter()
            .map(|part| css_length(part.f()))
            .collect();
        parts.push(format!("--size-{}: {};", hyphens(name), lengths.join(" ")));
    }
    parts.push(format!(
        "--transition: {}ms;",
        pyfmt::d(MOTION.at("transition_ms").f())
    ));
    parts.push(format!(
        "--transition-press: {}ms;",
        pyfmt::d(MOTION.at("press_ms").f())
    ));
    parts.push(format!("--transition-ease: {};", css_ease()));
    let dot = STATUS_DOT.at("panel").f();
    parts.push(css_glow_geometry(dot));
    for name in ["edge", "near", "far"] {
        parts.push(format!(
            "--glow-{name}-mix: {}%;",
            number(GLOW.at(&format!("{name}_alpha")).f() * 100.0)
        ));
    }
    parts.push(format!("--glow-from: {};", number(dot / glow_extent(dot))));
    for state in GLOW_BREATHES.strs() {
        parts.push(format!(
            "--glow-{state}-ms: {}ms;",
            pyfmt::d(GLOW.at(&format!("{state}_ms")).f())
        ));
    }
    parts.push(format!(
        "--glow-arc-ms: {}ms;",
        pyfmt::d(GLOW.at("arc_ms").f())
    ));
    parts.push(format!(
        "--glow-arc-mix: {}%;",
        number(GLOW.at("arc_alpha").f() * 100.0)
    ));
    parts.push(format!(
        "--glow-arc-gap: {};",
        css_length(GLOW.at("arc_gap").f())
    ));
    parts.push(format!(
        "--glow-arc-width: {};",
        css_length(GLOW.at("arc_width").f())
    ));
    parts.push(format!(
        "--glow-arc-sweep: {}deg;",
        number(GLOW.at("arc_sweep").f())
    ));
    parts.push(format!(
        "--glow-arc-still: {}deg;",
        number(GLOW.at("arc_still_at").f())
    ));
    parts.push(css_check_box());
    parts.push(css_corner()?);
    Ok(parts.join(" "))
}

/// `css_corner()`: Soft's corner where the panel's engine draws `corner-shape`.
pub fn css_corner() -> Py<String> {
    if design_smoothing(Some("soft"))? == 0.0 {
        return Ok("--corner-shape: round;".to_owned());
    }
    let mut parts = vec![format!(
        "--corner-shape: superellipse({});",
        number(CSS_CORNER.at("superellipse").f())
    )];
    for role in CORNER_ROLES.strs() {
        parts.push(format!(
            "--squircle-{role}: {};",
            css_length(RADII.at(role).f() * CSS_CORNER.at("reach").f())
        ));
    }
    Ok(parts.join(" "))
}

/// `css_glow_geometry(dot)`: where the glow of a light `dot` px in radius reaches, and where its stops lie.
pub fn css_glow_geometry(dot: f64) -> String {
    let mut parts = vec![format!("--glow-reach: {};", css_length(glow_reach(dot)))];
    for (name, fraction) in [
        ("edge", 0.0),
        ("near", GLOW.at("near_at").f()),
        ("far", GLOW.at("far_at").f()),
        ("outer", 1.0),
    ] {
        parts.push(format!(
            "--glow-{name}: {};",
            css_length(dot + glow_reach(dot) * fraction)
        ));
    }
    parts.join(" ")
}

/// `css_glow_keyframes()`: GLOW's breath as the panel's keyframes, sampled from glow_phase.
pub fn css_glow_keyframes() -> String {
    let panel = STATUS_DOT.at("panel").f();
    let extent = glow_extent(panel);
    let stops = GLOW_STOPS.i();
    let (mut dot, mut spread) = (Vec::new(), Vec::new());
    for step in 0..=stops {
        let fraction = step as f64 / stops as f64;
        let (dim, out) = glow_phase(fraction);
        let at = format!("{}%", number(fraction * 100.0));
        dot.push(format!(
            "{at} {{ background-color: color-mix(in srgb, var(--halo-color) {}%, var(--halo-ground)); }}",
            number((1.0 - dim) * 100.0)
        ));
        let scale = glow_radius(panel, out) / extent;
        spread.push(format!(
            "{at} {{ opacity: {}; transform: scale({}); }}",
            number(GLOW.at("peak").f() * out),
            number(scale)
        ));
    }
    format!(
        "@keyframes glow-dot {{ {} }}\n@keyframes glow-spread {{ {} }}\n@keyframes glow-arc {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}",
        dot.join(" "),
        spread.join(" ")
    )
}

/// `css_ease()`: MOTION's curve as CSS writes it.
pub fn css_ease() -> String {
    let values: Vec<String> = MOTION
        .at("ease")
        .list()
        .iter()
        .map(|value| number(value.f()))
        .collect();
    format!("cubic-bezier({})", values.join(", "))
}

/// `css_check_box()`: the check box's custom properties, part of css_scale().
pub fn css_check_box() -> String {
    let mut parts = Vec::new();
    for (state, entry) in CHECKBOX.items() {
        let name = hyphens(state);
        for part in ["fill", "edge", "mark"] {
            if let Some(token) = entry.at(part).opt_s() {
                parts.push(format!("--check-{name}-{part}: var(--{});", hyphens(token)));
            }
        }
        let elev = if entry.at("well").b() {
            "var(--elev-inset)"
        } else {
            "none"
        };
        parts.push(format!("--check-{name}-elev: {elev};"));
    }
    let points: Vec<String> = check_mark_outline(1.0, 0.0, 0.0)
        .iter()
        .map(|(x, y)| format!("{}px {}px", number(*x), number(*y)))
        .collect();
    parts.push(format!(
        "--check-mark-shape: polygon({});",
        points.join(", ")
    ));
    parts.join(" ")
}

/// `css_elevation(theme)`: `--elev-card`, `--elev-control`, `--elev-inset` and `--card-ground` for one theme.
pub fn css_elevation(theme: Option<&str>) -> Py<String> {
    let name = theme_name(theme)?;
    let mut parts = Vec::new();
    for recipe in elevation::recipes(name) {
        let listed: Vec<String> = elevation::listed(name, recipe)?
            .iter()
            .map(|shadow| {
                format!(
                    "{}{} {} {} color-mix(in srgb, var(--{}) {}%, transparent)",
                    if shadow.inset { "inset " } else { "" },
                    css_length(shadow.dx.f()),
                    css_length(shadow.dy.f()),
                    css_length(shadow.blur.f()),
                    hyphens(shadow.token),
                    pyfmt::round_int(shadow.alpha.f() * 100.0)
                )
            })
            .collect();
        parts.push(format!("--elev-{recipe}: {};", listed.join(", ")));
    }
    parts.push(format!(
        "--card-ground: {};",
        elevation::css_card_ground(name)
    ));
    Ok(parts.join(" "))
}

/// `css_variables(theme)`: `--name: value;` pairs, in declaration order, for a stylesheet block.
pub fn css_variables(pairs: &[(&str, &str)]) -> String {
    pairs
        .iter()
        .map(|(name, value)| format!("--{}: {value};", hyphens(name)))
        .collect::<Vec<_>>()
        .join(" ")
}

/// A palette's (token, value) pairs, for `css_variables`.
pub fn pairs(palette: &'static D) -> Vec<(&'static str, &'static str)> {
    palette
        .items()
        .iter()
        .map(|(name, value)| (*name, value.s()))
        .collect()
}

/// What a design block adds for one (theme, design), as `css_design_blocks`' `extra` is called.
pub type Extra<'a> = &'a dyn Fn(&str, &str) -> String;

fn design_declarations(theme: &str, design: &str, extra: Option<Extra>) -> Py<String> {
    let mut parts = vec![css_variables(&pairs(palette(Some(theme), Some(design))?))];
    if !design_depth(Some(design))? {
        let name = theme_name(Some(theme))?;
        let none: Vec<String> = SHADOWS
            .at(name)
            .keys()
            .map(|recipe| format!("--elev-{recipe}: none;"))
            .collect();
        parts.push(none.join(" "));
        parts.push("--card-ground: var(--surface);".to_owned());
    }
    let radii: Vec<String> = DESIGN_RADII
        .at(design)
        .items()
        .iter()
        .map(|(name, value)| format!("--radius-{}: {}px;", hyphens(name), number(value.f())))
        .collect();
    parts.push(radii.join(" "));
    if design_smoothing(Some(design))? == 0.0 {
        parts.push("--corner-shape: round;".to_owned());
    }
    if let Some(extra) = extra {
        parts.push(extra(theme, design));
    }
    Ok(parts
        .into_iter()
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" "))
}

fn same_radii(one: &'static D, other: &'static D) -> bool {
    let (a, b) = (one.items(), other.items());
    a.len() == b.len()
        && a.iter().all(|(key, value)| {
            other
                .find(key)
                .is_some_and(|each| each.n().compare(value.n()) == Some(std::cmp::Ordering::Equal))
        })
}

fn soft_colours(design: &str) -> bool {
    let (ours, soft) = (design_tokens(design), design_tokens("soft"));
    match (ours, soft) {
        (Some((light, dark)), Some((soft_light, soft_dark))) => {
            std::ptr::eq(light, soft_light) && std::ptr::eq(dark, soft_dark)
        }
        _ => false,
    }
}

/// `css_design_blocks(extra)`: the designs as the panel's stylesheet writes them.
pub fn css_design_blocks(extra: Option<Extra>) -> Py<String> {
    let mut blocks = Vec::new();
    for design in DESIGNS.strs() {
        if soft_colours(design)
            && design_depth(Some(design))?
            && same_radii(DESIGN_RADII.at(design), DESIGN_RADII.at("soft"))
        {
            continue;
        }
        let root = format!(":root[data-design=\"{design}\"]");
        let themes: Vec<&str> = THEMES.strs().collect();
        let light = design_declarations(themes[0], design, extra)?;
        let dark = design_declarations(themes[1], design, extra)?;
        blocks.push(format!("{root} {{ {light} }}"));
        blocks.push(format!("@media (prefers-color-scheme: dark) {{\n  {root}:not([data-theme=\"light\"]) {{ {dark} }}\n}}"));
        blocks.push(format!("{root}[data-theme=\"dark\"] {{ {dark} }}"));
        blocks.push(format!("{root}[data-theme=\"light\"] {{ {light} }}"));
    }
    Ok(blocks.join("\n"))
}
