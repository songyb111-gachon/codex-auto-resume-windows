//! The three designs: what each draws, as data (brand/design.py).

use crate::Py;
use crate::data::D;
use crate::tokens::design_name;

pub use crate::tables_gen::{ACCENT_BAR, DEFAULT_DESIGN, DESIGN, DESIGN_RADII};

fn rule(design: Option<&str>, axis: &str) -> Py<bool> {
    Ok(DESIGN.at(design_name(design)?).at(axis).b())
}

/// `design_depth(design)`: whether a design draws shadows, wells and a lifted card.
pub fn design_depth(design: Option<&str>) -> Py<bool> {
    rule(design, "depth")
}

/// `design_glow(design)`: whether a design draws the glow round the status light while it moves.
pub fn design_glow(design: Option<&str>) -> Py<bool> {
    rule(design, "glow")
}

/// `design_accent_bar(design)`: whether a design draws v0.6.2's accent bar and underlines the current tab.
pub fn design_accent_bar(design: Option<&str>) -> Py<bool> {
    rule(design, "accent_bar")
}

/// `design_radii(design)`: a design's corner radii by RADII's roles, in CSS px.
pub fn design_radii(design: Option<&str>) -> Py<&'static D> {
    Ok(DESIGN_RADII.at(design_name(design)?))
}
