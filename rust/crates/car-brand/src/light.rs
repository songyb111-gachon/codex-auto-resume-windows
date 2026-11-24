//! The status light: which colour a state is drawn in, and how it breathes (brand/light.py).

use std::f64::consts::PI;

use crate::Py;
use crate::data::Num;
use crate::design::design_glow;
use crate::pyfmt;
use crate::tokens::palette;

pub use crate::tables_gen::{GLOW, GLOW_BREATHES, STATUS_DOT, STATUS_FILL, STATUS_SYSTEM};

/// `status_fill(state)`: the colour token a state's dot is filled with; anything unknown is idle grey.
pub fn status_fill(state: Option<&str>) -> &'static str {
    state
        .and_then(|state| STATUS_FILL.find(state))
        .map_or("idle", |token| token.s())
}

/// `status_system(state)`: the High Contrast system colour a state's dot is filled with.
pub fn status_system(state: Option<&str>) -> &'static str {
    state
        .and_then(|state| STATUS_SYSTEM.find(state))
        .map_or("GrayText", |name| name.s())
}

/// `status_colour(state, theme, design)`: the `#RRGGBB` a state's dot and glow are drawn in.
pub fn status_colour(
    state: Option<&str>,
    theme: Option<&str>,
    design: Option<&str>,
) -> Py<&'static str> {
    Ok(palette(theme, design)?.at(status_fill(state)).s())
}

/// `_breath(elapsed_ms, cycle_ms)`: 0 at the start of a cycle, 1 halfway, 0 again: a raised cosine.
pub fn breath(elapsed_ms: f64, cycle_ms: f64) -> Py<f64> {
    if cycle_ms == 0.0 {
        return Err("ZeroDivisionError");
    }
    Ok(0.5 - 0.5 * (2.0 * PI * pyfmt::rem(elapsed_ms, cycle_ms) / cycle_ms).cos())
}

/// `glow_floor()`: what the dot is drawn at when the breath is at its lowest.
pub fn glow_floor() -> f64 {
    GLOW.at("low").f().powf(1.0 / GLOW.at("gamma").f())
}

/// `glow_phase(fraction)`: the light at `fraction` of one breath, as (dim, spread).
pub fn glow_phase(fraction: f64) -> (f64, f64) {
    let breath = 0.5 + 0.5 * (2.0 * PI * pyfmt::rem(fraction, 1.0)).cos();
    let low = GLOW.at("low").f();
    let lit = (low + (1.0 - low) * breath).powf(1.0 / GLOW.at("gamma").f());
    let floor = glow_floor();
    let risen = (lit - floor) / (1.0 - floor);
    (1.0 - lit, risen * risen)
}

/// One frame of the status light (`glow`): dim, opacity, spread, and the checking arc's angle or None.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Glow {
    pub dim: f64,
    pub opacity: f64,
    pub spread: f64,
    pub arc: Option<Num>,
}

/// `glow(state, elapsed_ms, since_entered_ms, reduced=, design=)`; None when the light is off.
pub fn glow(
    state: Option<&str>,
    elapsed_ms: f64,
    reduced: bool,
    design: Option<&str>,
) -> Py<Option<Glow>> {
    let mut fraction = None;
    let mut arc = None;
    match state {
        Some(name) if GLOW_BREATHES.has(name) => {
            if !reduced {
                let cycle = GLOW.at(&format!("{name}_ms")).f();
                if cycle == 0.0 {
                    return Err("ZeroDivisionError");
                }
                fraction = Some(pyfmt::rem(elapsed_ms, cycle) / cycle);
            }
        }
        Some("checking") => {
            arc = Some(if reduced {
                GLOW.at("arc_still_at").n()
            } else {
                let cycle = GLOW.at("arc_ms").f();
                Num::F(pyfmt::rem(elapsed_ms, cycle) / cycle * 360.0)
            });
        }
        _ => return Ok(None),
    }
    let (dim, mut spread) = fraction.map_or((0.0, 0.0), glow_phase);
    if !design_glow(design)? {
        spread = 0.0;
    }
    Ok(Some(Glow {
        dim,
        opacity: GLOW.at("peak").f() * spread,
        spread,
        arc,
    }))
}

/// `glow_moves(state, since_entered_ms, reduced=)`: whether a frame timer has anything to draw for this state.
pub fn glow_moves(state: Option<&str>, reduced: bool) -> bool {
    !reduced && state.is_some_and(|name| GLOW_BREATHES.has(name) || name == "checking")
}

/// `glow_reach(dot_radius)`: how far past the dot's edge the glow gets at the top of the breath.
pub fn glow_reach(dot_radius: f64) -> f64 {
    GLOW.at("reach_of_radius").f() * dot_radius
}

/// `glow_radius(dot_radius, spread)`: the glow's outer radius in CSS px for a frame's `spread`.
pub fn glow_radius(dot_radius: f64, spread: f64) -> f64 {
    dot_radius + glow_reach(dot_radius) * spread
}

/// `glow_extent(dot_radius)`: the largest outer radius any frame draws.
pub fn glow_extent(dot_radius: f64) -> f64 {
    glow_radius(dot_radius, 1.0)
}

/// `glow_stops(dot_radius)`: the falloff as (fraction of the outer radius, alpha factor) stops.
pub fn glow_stops(dot_radius: f64) -> Vec<(f64, Num)> {
    let (outer, reach) = (glow_extent(dot_radius), glow_reach(dot_radius));
    let alpha = |name: &str| GLOW.at(name).n();
    vec![
        (0.0, alpha("edge_alpha")),
        (dot_radius / outer, alpha("edge_alpha")),
        (
            (dot_radius + reach * GLOW.at("near_at").f()) / outer,
            alpha("near_alpha"),
        ),
        (
            (dot_radius + reach * GLOW.at("far_at").f()) / outer,
            alpha("far_alpha"),
        ),
        (1.0, Num::F(0.0)),
    ]
}
