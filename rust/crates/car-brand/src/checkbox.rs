//! The check box and its tick: the state table, its High Contrast twin, and the geometry (brand/checkbox.py).

use crate::Py;
use crate::design::design_depth;
use crate::tokens::palette;

pub use crate::tables_gen::{CHECK_MARK, CHECKBOX, CHECKBOX_SYSTEM, LAYOUT, SYSTEM_CSS};

/// `check_box_state(checked, enabled)`: 'off', 'on', 'off_disabled' or 'on_disabled'.
pub fn check_box_state(checked: bool, enabled: bool) -> &'static str {
    match (checked, enabled) {
        (true, true) => "on",
        (false, true) => "off",
        (true, false) => "on_disabled",
        (false, false) => "off_disabled",
    }
}

/// A check box's colours (`check_box`): fill, edge and mark as `#RRGGBB` (mark None when there is none) and `well`.
#[derive(Clone, Debug, PartialEq)]
pub struct CheckBox {
    pub fill: &'static str,
    pub edge: &'static str,
    pub mark: Option<&'static str>,
    pub well: bool,
}

/// `check_box(checked, enabled, theme, design)`.
pub fn check_box(
    checked: bool,
    enabled: bool,
    theme: Option<&str>,
    design: Option<&str>,
) -> Py<CheckBox> {
    let entry = CHECKBOX.at(check_box_state(checked, enabled));
    let tokens = palette(theme, design)?;
    let mark = entry.at("mark").opt_s();
    Ok(CheckBox {
        fill: tokens.at(entry.at("fill").s()).s(),
        edge: tokens.at(entry.at("edge").s()).s(),
        mark: mark.map(|name| tokens.at(name).s()),
        well: entry.at("well").b() && design_depth(design)?,
    })
}

/// `check_box_system(checked, enabled)`: the same box in High Contrast, as (fill, edge, mark) system colour names.
pub fn check_box_system(
    checked: bool,
    enabled: bool,
) -> (&'static str, &'static str, Option<&'static str>) {
    let entry = CHECKBOX_SYSTEM.at(check_box_state(checked, enabled));
    (
        entry.at("fill").s(),
        entry.at("edge").s(),
        entry.at("mark").opt_s(),
    )
}

/// `css_system(name)`: a Windows system colour name as CSS's forced-colors keyword.
pub fn css_system(name: &str) -> Py<&'static str> {
    Ok(SYSTEM_CSS.find(name).ok_or("KeyError")?.s())
}

fn points() -> [(f64, f64); 3] {
    let mark = CHECK_MARK.list();
    let at = |index: usize| (mark[index].list()[0].f(), mark[index].list()[1].f());
    [at(0), at(1), at(2)]
}

/// `check_mark(scale, left, top)`: the mark's centre line - start, corner, end - in device px.
pub fn check_mark(scale: f64, left: f64, top: f64) -> Vec<(f64, f64)> {
    points()
        .iter()
        .map(|(x, y)| (left + x * scale, top + y * scale))
        .collect()
}

/// `check_mark_outline(scale, left, top)`: the stroked mark as a filled polygon, six points.
pub fn check_mark_outline(scale: f64, left: f64, top: f64) -> Vec<(f64, f64)> {
    let [(x0, y0), (x1, y1), (x2, y2)] = points();
    let half = LAYOUT.at("check_stroke").f() / 2.0;
    let normal = |ax: f64, ay: f64, bx: f64, by: f64| {
        let length = crate::pyfmt::hypot(bx - ax, by - ay);
        (-(by - ay) / length, (bx - ax) / length)
    };
    let (n1, n2) = (normal(x0, y0, x1, y1), normal(x1, y1, x2, y2));
    let joint = 1.0 + n1.0 * n2.0 + n1.1 * n2.1;
    let mitre = (half * (n1.0 + n2.0) / joint, half * (n1.1 + n2.1) / joint);
    let outline = [
        (x0 + half * n1.0, y0 + half * n1.1),
        (x1 + mitre.0, y1 + mitre.1),
        (x2 + half * n2.0, y2 + half * n2.1),
        (x2 - half * n2.0, y2 - half * n2.1),
        (x1 - mitre.0, y1 - mitre.1),
        (x0 - half * n1.0, y0 - half * n1.1),
    ];
    outline
        .iter()
        .map(|(x, y)| (left + x * scale, top + y * scale))
        .collect()
}
