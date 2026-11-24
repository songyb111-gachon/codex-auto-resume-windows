//! The parts of `ui/tray/motion.py` that gui/Brand.cs is made from: the icon's states and rhythms (ICON_*), the head's
//! colours, a frame as (position, level), when the next is due, and `IconFrames` - the icon's pixels for one size.
//!
//! The notification-area icon itself is the C# host's (PLAN 1.5); build/make_brand.py writes its motion and frames
//! into gui/Brand.cs (`Brand.Mark`), so the generator's port needs exactly these, and they live here with it.
//! `icon_state` (which asks the popup) is the host's and is not here.

use crate::Py;
use crate::colour::rgb;
use crate::data::Num;
use crate::days::{DAY_LOOKS, MOTIF_LEAST, MarkShape, mark_colour_of, marks};
use crate::light::{GLOW, breath, status_fill};
use crate::mark::{
    ICON_ACCENT, ICON_BOTTOM, ICON_SHAPE, ICON_SUPERSAMPLE, Sample, Samples, icon_head_box,
    icon_pixel, icon_samples,
};
use crate::pyfmt;
use crate::tokens::palette;

pub use crate::tables_gen::{
    ICON_BRAND_STATE, ICON_BREATHS, ICON_FOR_LIGHT, ICON_HEAD_PALETTE, ICON_MOTION, ICON_STATES,
    ICON_SWEEPS, ICON_TRAVEL_BREATHS,
};

/// `ICON_SWEEP`: the stroke, in degrees.
pub fn icon_sweep() -> f64 {
    pyfmt::rem(
        ICON_SHAPE.at("arc_end").f() - ICON_SHAPE.at("arc_start").f(),
        360.0,
    )
}

/// `ICON_DIM_TOWARD`: the badge's own deep blue the breath dims the head toward.
pub fn icon_dim_toward() -> &'static str {
    ICON_BOTTOM.s()
}

fn motion(key: &str) -> Num {
    ICON_MOTION.at(key).n()
}

/// `icon_brand_state(state)`: the brand status-light state an icon state is drawn as; anything unknown is idle.
pub fn icon_brand_state(state: Option<&str>) -> &'static str {
    state
        .and_then(|state| ICON_BRAND_STATE.find(state))
        .map_or("idle", |each| each.s())
}

/// `icon_head_colour(state)`: the head's full colour in a state.
pub fn icon_head_colour(state: Option<&str>) -> Py<[i64; 3]> {
    let token = status_fill(Some(icon_brand_state(state)));
    if token == "active" {
        return rgb(ICON_ACCENT.s());
    }
    let theme = ICON_HEAD_PALETTE
        .find(token)
        .map_or("light", |each| each.s());
    rgb(palette(Some(theme), Some("soft"))?.at(token).s())
}

/// `icon_level_colour(colour, level)`: the head's colour at breathing `level`.
pub fn icon_level_colour(colour: [i64; 3], level: f64) -> Py<[i64; 3]> {
    let top = motion("levels").f() as i64 - 1;
    if level.is_nan() {
        return Err("ValueError");
    }
    if level.is_infinite() {
        return Err("OverflowError");
    }
    let level = 0.max(top.min(level.trunc() as i64));
    let amount = motion("dim").f() * (top - level) as f64 / top as f64;
    let target = rgb(icon_dim_toward())?;
    let mut out = [0i64; 3];
    for index in 0..3 {
        out[index] = (colour[index] as f64 + (target[index] - colour[index]) as f64 * amount + 0.5)
            .floor() as i64;
    }
    Ok(out)
}

/// `_breath_level(elapsed_ms, cycle_ms)`: full brightness at the start of a cycle, dimmest halfway, full again.
pub fn breath_level(elapsed_ms: f64, cycle_ms: f64) -> Py<i64> {
    let top = motion("levels").f() - 1.0;
    Ok(pyfmt::round_int(
        top * (1.0 - breath(elapsed_ms, cycle_ms)?),
    ))
}

/// `icon_turn(state, elapsed_ms)`: how far along the stroke the head has swept, in degrees, or None.
pub fn icon_turn(state: Option<&str>, elapsed_ms: f64) -> Py<Option<f64>> {
    let Some(state) = state.filter(|name| ICON_SWEEPS.has(name)) else {
        return Ok(None);
    };
    let mut beat = GLOW.at("monitoring_ms").f();
    if state == "failed" {
        beat *= motion("failed_slot").f();
    }
    let watching = state == "watching";
    let sweeps = if watching {
        motion("sweep_breaths").f()
    } else {
        1.0
    };
    let out = beat * sweeps * motion("sweep_out").f();
    let hold = beat * sweeps * motion("sweep_hold").f();
    let start = if watching {
        beat * motion("breaths").f()
    } else {
        0.0
    };
    let cycle = if watching {
        start + beat * sweeps
    } else {
        2.0 * out + hold + beat * motion("recover_rest").f()
    };
    let into = pyfmt::rem(elapsed_ms, cycle) - start;
    if into < 0.0 || into >= 2.0 * out + hold {
        return Ok(if into < 0.0 { None } else { Some(0.0) });
    }
    Ok(Some(
        icon_sweep() * breath(pyfmt::min(into, pyfmt::max(out, into - hold)), 2.0 * out)?,
    ))
}

/// `icon_frame(state, elapsed_ms, reduced=, fine=)`: (head position, breathing level) for one frame.
pub fn icon_frame(
    state: Option<&str>,
    elapsed_ms: f64,
    reduced: bool,
    fine: i64,
) -> Py<(i64, i64)> {
    let positions = motion("positions").f() as i64 * fine;
    let top = motion("levels").f() as i64 - 1;
    if reduced {
        return Ok((0, top));
    }
    if let Some(turn) = icon_turn(state, elapsed_ms)? {
        let name = state.unwrap_or_default();
        let level = match ICON_TRAVEL_BREATHS.find(name) {
            Some(rhythm) => breath_level(elapsed_ms, GLOW.at(rhythm.s()).f())?,
            None => top,
        };
        if positions == 0 {
            return Err("ZeroDivisionError");
        }
        let position = pyfmt::round_int(turn / (360.0 / positions as f64)).rem_euclid(positions);
        return Ok((position, level));
    }
    if let Some(rhythm) = state.and_then(|name| ICON_BREATHS.find(name)) {
        return Ok((0, breath_level(elapsed_ms, GLOW.at(rhythm.s()).f())?));
    }
    Ok((0, top))
}

/// `icon_frame_ms(state, elapsed_ms, reduced=, fine=)`: how soon the next frame is due, in ms, or None.
pub fn icon_frame_ms(
    state: Option<&str>,
    elapsed_ms: f64,
    reduced: bool,
    fine: i64,
) -> Py<Option<i64>> {
    if reduced {
        return Ok(None);
    }
    if icon_turn(state, elapsed_ms)?.is_some() {
        if fine > 1 && state == Some("watching") {
            let glide = motion("glide_frame_ms").f() as i64;
            let (beat, sweeps) = (GLOW.at("monitoring_ms").f(), motion("sweep_breaths").f());
            let out = beat * sweeps * motion("sweep_out").f();
            let hold = beat * sweeps * motion("sweep_hold").f();
            let cycle = beat * (motion("breaths").f() + sweeps);
            let into = pyfmt::rem(elapsed_ms, cycle);
            if into - beat * motion("breaths").f() >= 2.0 * out + hold {
                let each = (glide as f64 / (1000.0 / 64.0)).ceil() * (1000.0 / 64.0);
                return Ok(Some(
                    glide * 1.max(((cycle - into) / each - 1e-9).ceil() as i64),
                ));
            }
            return Ok(Some(glide));
        }
        return Ok(Some(motion("turn_frame_ms").f() as i64));
    }
    if state.is_some_and(|name| ICON_BREATHS.find(name).is_some()) {
        return Ok(Some(motion("breathe_frame_ms").f() as i64));
    }
    Ok(None)
}

/// `icon_motion_allowed(...)`: whether the icon may move at all.
pub fn icon_motion_allowed(
    reduced: bool,
    contrast: bool,
    battery_saver: bool,
    locked: bool,
    hidden: bool,
    frames: bool,
) -> bool {
    frames && !(reduced || contrast || battery_saver || locked || hidden)
}

/// `_mark_cover(size, look)`: for each pixel the look's mark falls on, (hits, red, green, blue); row by row.
fn mark_cover(size: i64, shapes: &[MarkShape]) -> Py<Vec<Option<[i64; 4]>>> {
    let steps = 4i64;
    let unit = 32.0 / size as f64;
    let mut cover = vec![None; (size * size) as usize];
    for py in 0..size {
        for px in 0..size {
            let mut hits = Vec::new();
            for sy in 0..steps {
                for sx in 0..steps {
                    let x = (px as f64 + (sx as f64 + 0.5) / steps as f64) * unit;
                    let y = (py as f64 + (sy as f64 + 0.5) / steps as f64) * unit;
                    if let Some(hit) = mark_colour_of(shapes, x, y)? {
                        hits.push(hit);
                    }
                }
            }
            if !hits.is_empty() {
                let sum = |index: usize| hits.iter().map(|hit| hit[index]).sum::<i64>();
                cover[(py * size + px) as usize] =
                    Some([hits.len() as i64, sum(0), sum(1), sum(2)]);
            }
        }
    }
    Ok(cover)
}

fn floor_div(a: i64, b: i64) -> i64 {
    a.div_euclid(b) - if b < 0 && a.rem_euclid(b) != 0 { 1 } else { 0 }
}

/// `_marked(pixel, cover)`: (red, green, blue) under the cover's share of the mark.
fn marked(pixel: [i64; 3], cover: [i64; 4]) -> [i64; 3] {
    let [hits, red, green, blue] = cover;
    let total = 16;
    [
        floor_div(pixel[0] * (total - hits) + red, total),
        floor_div(pixel[1] * (total - hits) + green, total),
        floor_div(pixel[2] * (total - hits) + blue, total),
    ]
}

fn byte(value: i64) -> Py<u8> {
    u8::try_from(value).map_err(|_| "ValueError")
}

/// The icon's frames for one size (`IconFrames`): the mark without its head as top-down BGRA, and for each head
/// position the box its head can touch and the samples there.
#[derive(Clone, Debug)]
pub struct IconFrames {
    pub size: i64,
    pub fine: i64,
    pub look: Option<String>,
    mark: Vec<Option<[i64; 4]>>,
    pub ground: Vec<u8>,
    pub heads: Vec<([i64; 4], Vec<Vec<Sample>>)>,
}

impl IconFrames {
    /// `IconFrames(size, fine, look)`.
    pub fn new(size: i64, fine: i64, look: Option<&str>) -> Py<IconFrames> {
        if size <= 0 || fine < 1 {
            return Err("ValueError");
        }
        let positions = motion("positions").f() as i64 * fine;
        let look = look.filter(|name| !name.is_empty());
        let body = match look {
            Some(name) => {
                let colours = DAY_LOOKS.find(name).ok_or("KeyError")?.list();
                Some((colours[0].s(), colours[1].s()))
            }
            None => None,
        };
        let mark = match look {
            Some(name) if size >= MOTIF_LEAST.i() => mark_cover(size, &marks(name)?)?,
            _ => vec![None; (size * size) as usize],
        };
        let mut ground = vec![0u8; (size * size * 4) as usize];
        let rows = icon_samples(
            size,
            &Samples {
                no_head: true,
                body,
                ..Samples::default()
            },
        )?;
        for (y, row) in rows.iter().enumerate() {
            for (x, sample) in row.iter().enumerate() {
                let [mut red, mut green, mut blue, alpha] = icon_pixel(sample, [0, 0, 0]);
                if let Some(cover) = mark[y * size as usize + x].filter(|_| alpha != 0) {
                    [red, green, blue] = marked([red, green, blue], cover);
                }
                let index = (y * size as usize + x) * 4;
                ground[index..index + 4].copy_from_slice(&[
                    byte(blue)?,
                    byte(green)?,
                    byte(red)?,
                    byte(alpha)?,
                ]);
            }
        }
        let mut heads = Vec::new();
        for position in 0..positions {
            let angle = ICON_SHAPE.at("arc_end").f() - 360.0 * position as f64 / positions as f64;
            let bounds = icon_head_box(size, Some(angle));
            let samples = icon_samples(
                size,
                &Samples {
                    head_angle: Some(angle),
                    bounds: Some(bounds),
                    body,
                    ..Samples::default()
                },
            )?;
            heads.push((bounds, samples));
        }
        Ok(IconFrames {
            size,
            fine,
            look: look.map(str::to_owned),
            mark,
            ground,
            heads,
        })
    }

    /// `compose(position, head)`: one frame, the head at `position` in `head` (red, green, blue).
    pub fn compose(&self, position: i64, head: [i64; 3]) -> Py<Vec<u8>> {
        let size = self.size;
        let mut pixels = self.ground.clone();
        let (bounds, rows) = &self.heads[position.rem_euclid(self.heads.len() as i64) as usize];
        let (left, top) = (bounds[0], bounds[1]);
        for (y, row) in rows.iter().enumerate() {
            for (x, sample) in row.iter().enumerate() {
                let [mut red, mut green, mut blue, alpha] = icon_pixel(sample, head);
                let (px, py) = (left + x as i64, top + y as i64);
                let inside = (0..size).contains(&px) && (0..size).contains(&py);
                let cover = if inside {
                    self.mark[(py * size + px) as usize]
                } else {
                    None
                };
                if let Some(cover) = cover.filter(|_| alpha != 0 && sample[1] == 0) {
                    [red, green, blue] = marked([red, green, blue], cover);
                }
                let index = ((py * size + px) * 4) as usize;
                pixels[index..index + 4].copy_from_slice(&[
                    byte(blue)?,
                    byte(green)?,
                    byte(red)?,
                    byte(alpha)?,
                ]);
            }
        }
        Ok(pixels)
    }
}

/// The supersample count a pixel's samples come in (ICON_SUPERSAMPLE squared).
pub fn whole() -> i64 {
    ICON_SUPERSAMPLE.i() * ICON_SUPERSAMPLE.i()
}
