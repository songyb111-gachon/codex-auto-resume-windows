//! The palette: the identity ramp, the one brand colour, the two themes and each design's colours (brand/tokens.py).
//!
//! The tables are the tag's (tables_gen.rs); a palette is a dict of token to `#RRGGBB` in its declaration order.

use crate::Py;
use crate::data::D;
use crate::tables_gen as t;

pub use t::{
    BRAND, CLASSIC_DARK, CLASSIC_LIGHT, DARK, DESIGNS, EDITION_INK, LIGHT, PLAIN_DARK, PLAIN_LIGHT,
    RAMP, THEMES,
};

/// A palette by the name tables_gen gives it (DESIGN_TOKENS names them).
fn named(name: &str) -> &'static D {
    match name {
        "LIGHT" => &t::LIGHT,
        "DARK" => &t::DARK,
        "CLASSIC_LIGHT" => &t::CLASSIC_LIGHT,
        "CLASSIC_DARK" => &t::CLASSIC_DARK,
        "PLAIN_LIGHT" => &t::PLAIN_LIGHT,
        "PLAIN_DARK" => &t::PLAIN_DARK,
        _ => panic!("DESIGN_TOKENS names no palette {name:?}"),
    }
}

/// `DESIGN_TOKENS[design]`: the design's (light, dark) palettes, for a design that is one.
pub fn design_tokens(design: &str) -> Option<(&'static D, &'static D)> {
    let pair = t::DESIGN_TOKENS.find(design)?.list();
    Some((named(pair[0].s()), named(pair[1].s())))
}

/// `theme_name(theme)`: 'light' or 'dark'; anything else is a ValueError. A theme that is not a str is `None`.
pub fn theme_name(theme: Option<&str>) -> Py<&'static str> {
    match theme {
        Some("light") => Ok("light"),
        Some("dark") => Ok("dark"),
        _ => Err("ValueError"),
    }
}

/// `design_name(design)`: one of DESIGNS, as given; anything else (a design that is not a str is `None`) a ValueError.
pub fn design_name(design: Option<&str>) -> Py<&'static str> {
    let name = design.ok_or("ValueError")?;
    t::DESIGNS
        .strs()
        .find(|each| *each == name)
        .ok_or("ValueError")
}

/// `palette(theme, design)`: a design's colours in a theme.
pub fn palette(theme: Option<&str>, design: Option<&str>) -> Py<&'static D> {
    let (light, dark) = design_tokens(design_name(design)?).ok_or("KeyError")?;
    Ok(if theme_name(theme)? == "dark" {
        dark
    } else {
        light
    })
}

/// `palette(theme)[token]`, for a token every palette has.
pub fn token(palette: &'static D, token: &str) -> &'static str {
    palette.at(token).s()
}
