//! Sizes, type and the panel's layout: everything that is not a colour and does not move (brand/scale.py).

use crate::Py;
use crate::data::{D, Num};

pub use crate::tables_gen::{
    CAPTION_STROKE, CORNER_SMOOTHING, LAYOUT, LINE_HEIGHT, RADII, SPACING, TYPE, TYPE_ROLES,
    TYPE_SCALE, WINDOW_SQUIRCLE,
};

/// A LAYOUT value's parts: a tuple's members, or the one number.
pub fn parts(value: &'static D) -> Vec<Num> {
    match value {
        D::L(items) => items.iter().map(D::n).collect(),
        other => vec![other.n()],
    }
}

/// `padding(key)`: a LAYOUT padding as (top, right, bottom, left), expanded the way CSS expands it.
pub fn padding(key: &str) -> Py<Vec<Num>> {
    let value = parts(LAYOUT.find(key).ok_or("KeyError")?);
    Ok(match value.len() {
        1 => vec![value[0]; 4],
        2 => vec![value[0], value[1], value[0], value[1]],
        3 => vec![value[0], value[1], value[2], value[1]],
        _ => value,
    })
}
