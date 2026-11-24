//! The shadow model: the recipes as data, and what a shadow does to a pixel (brand/elevation.py).

use crate::Py;
use crate::colour::{mix, rgb};
use crate::data::{D, Num};
use crate::design::design_depth;
use crate::pyfmt;
use crate::tokens::{palette, theme_name};

pub use crate::tables_gen::{CARD_LIFT, SHADOWS};

/// One shadow (`Shadow`): (dx, dy, blur, token, alpha, inset) in CSS px.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Shadow {
    pub dx: Num,
    pub dy: Num,
    pub blur: Num,
    pub token: &'static str,
    pub alpha: Num,
    pub inset: bool,
}

impl Shadow {
    fn of(value: &'static D) -> Shadow {
        let parts = value.list();
        Shadow {
            dx: parts[0].n(),
            dy: parts[1].n(),
            blur: parts[2].n(),
            token: parts[3].s(),
            alpha: parts[4].n(),
            inset: parts[5].b(),
        }
    }
}

/// A theme's recipes as the tag lists them, without the design's say: `SHADOWS[theme][recipe]`.
pub fn listed(theme: &str, recipe: &str) -> Py<Vec<Shadow>> {
    let recipes = SHADOWS.at(theme);
    Ok(recipes
        .find(recipe)
        .ok_or("KeyError")?
        .list()
        .iter()
        .map(Shadow::of)
        .collect())
}

/// The recipe names of a theme, in order (`SHADOWS[theme]`'s keys).
pub fn recipes(theme: &str) -> Vec<&'static str> {
    SHADOWS.at(theme).keys().collect()
}

/// `shadows(recipe, theme, design)`: a theme's elevation recipe front to back; none in a design without depth.
pub fn shadows(recipe: &str, theme: Option<&str>, design: Option<&str>) -> Py<Vec<Shadow>> {
    let found = listed(theme_name(theme)?, recipe)?;
    Ok(if design_depth(design)? {
        found
    } else {
        Vec::new()
    })
}

/// `_CARD_GROUND[theme]`: the card's ground as the panel's stylesheet writes it.
pub fn css_card_ground(theme: &str) -> String {
    let lift = CARD_LIFT.at(theme).f();
    if lift == 0.0 {
        "var(--surface)".to_owned()
    } else {
        format!(
            "color-mix(in srgb, var(--raised) {}%, var(--surface))",
            pyfmt::d(pyfmt::round_int(lift * 100.0) as f64)
        )
    }
}

/// `card_ground(theme, design)`: a card's own fill in a theme.
pub fn card_ground(theme: Option<&str>, design: Option<&str>) -> Py<String> {
    let tokens = palette(theme, design)?;
    let lift = if design_depth(design)? {
        CARD_LIFT.at(theme_name(theme)?).f()
    } else {
        0.0
    };
    mix(tokens.at("surface").s(), tokens.at("raised").s(), lift)
}

const SIDES: [&str; 4] = ["left", "top", "right", "bottom"];

fn negate(value: Num) -> Num {
    match value {
        Num::I(int) => Num::I(-int),
        Num::F(x) => Num::F(-x),
    }
}

/// `shadow_offset(shadow, side)`: how far a shadow is moved toward one side of its box, in CSS px.
pub fn shadow_offset(shadow: &Shadow, side: &str) -> Py<Num> {
    let toward = match side {
        "left" => negate(shadow.dx),
        "top" => negate(shadow.dy),
        "right" => shadow.dx,
        "bottom" => shadow.dy,
        _ => return Err("ValueError"),
    };
    Ok(if shadow.inset { negate(toward) } else { toward })
}

/// `shadow_alpha(shadow, d, side, scale)`: one shadow's alpha `d` device px from a straight edge of its box.
pub fn shadow_alpha(shadow: &Shadow, d: Num, side: &str, scale: Num) -> Py<f64> {
    let offset = shadow_offset(shadow, side)?.times(scale);
    let sigma = shadow.blur.times(scale).f() / 2.0;
    if sigma <= 0.0 {
        let step = if offset.gt(d) {
            1.0
        } else if offset.compare(d) == Some(std::cmp::Ordering::Equal) {
            0.5
        } else {
            0.0
        };
        return Ok(shadow.alpha.f() * step);
    }
    Ok(shadow.alpha.f() * 0.5 * pyfmt::erfc(-(offset.minus(d).f() / sigma) / 2.0f64.sqrt()))
}

/// `elevation_colour(recipe, side, d, ground, theme, scale, inside, design)`: the colour `d` device px from one edge
/// of a box with `recipe`, as unrounded (r, g, b).
#[allow(clippy::too_many_arguments)]
pub fn elevation_colour(
    recipe: &str,
    side: &str,
    d: Num,
    ground: &str,
    theme: Option<&str>,
    scale: Num,
    inside: Option<bool>,
    design: Option<&str>,
) -> Py<[f64; 3]> {
    let tokens = palette(theme, design)?;
    let recipe_shadows = shadows(recipe, theme, design)?;
    let inside = inside.unwrap_or_else(|| {
        !recipe_shadows.is_empty() && recipe_shadows.iter().all(|shadow| shadow.inset)
    });
    let ground: &str = match tokens.find(ground) {
        Some(token) => token.s(),
        None => ground,
    };
    let start = rgb(ground)?;
    let mut colour = [start[0] as f64, start[1] as f64, start[2] as f64];
    for shadow in recipe_shadows.iter().rev() {
        if shadow.inset != inside {
            continue;
        }
        let alpha = shadow_alpha(shadow, d, side, scale)?;
        let tone = rgb(tokens.at(shadow.token).s())?;
        for index in 0..3 {
            colour[index] += (tone[index] as f64 - colour[index]) * alpha;
        }
    }
    Ok(colour)
}

/// `reach(recipe, theme, scale)`: how far a recipe's outer shadows reach past its box, (left, top, right, bottom).
pub fn reach(recipe: &str, theme: Option<&str>, scale: f64) -> Py<[i64; 4]> {
    let theme = theme_name(theme)?;
    let mut sides = [0i64; 4];
    for (index, side) in SIDES.iter().enumerate() {
        let mut far = 0.0f64;
        for shadow in listed(theme, recipe)? {
            if !shadow.inset {
                far = pyfmt::max(
                    far,
                    shadow_offset(&shadow, side)?.f() + 1.5 * shadow.blur.f(),
                );
            }
        }
        sides[index] = (far * scale - 1e-9).ceil() as i64;
    }
    Ok(sides)
}
