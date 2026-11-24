//! The mark: its own colours, its geometry, and the rasteriser everything is drawn from (brand/mark.py).
//!
//! Deterministic: a pixel is ICON_SUPERSAMPLE squared samples, each the head, the ring or the badge's vertical
//! gradient, and the pixel their integer average - the same arithmetic as the tag's, so the .ico, the icon's
//! frames and gui/Brand.cs's frames are the same pixels.

use std::f64::consts::PI;

use crate::Py;
use crate::colour::rgb;
use crate::pyfmt;

pub use crate::tables_gen::{
    ICON_ACCENT, ICON_BOTTOM, ICON_MARK, ICON_SHAPE, ICON_SUPERSAMPLE, ICON_TOP,
};

/// `math.atan2(y, x)`: CPython's wrapper (its own answers for infinities and zeros), then the C library's.
pub fn atan2(y: f64, x: f64) -> f64 {
    if x.is_nan() || y.is_nan() {
        return f64::NAN;
    }
    if y.is_infinite() {
        if x.is_infinite() {
            return if 1.0f64.copysign(x) == 1.0 {
                (0.25 * PI).copysign(y)
            } else {
                (0.75 * PI).copysign(y)
            };
        }
        return (0.5 * PI).copysign(y);
    }
    if x.is_infinite() || y == 0.0 {
        return if 1.0f64.copysign(x) == 1.0 {
            0.0f64.copysign(y)
        } else {
            PI.copysign(y)
        };
    }
    y.atan2(x)
}

/// `icon_rounded_square(x, y, radius)`: signed distance to a rounded square of half-size 1; negative inside.
pub fn icon_rounded_square(x: f64, y: f64, radius: f64) -> f64 {
    let half = 1.0 - radius;
    let dx = pyfmt::max(x.abs() - half, 0.0);
    let dy = pyfmt::max(y.abs() - half, 0.0);
    if x.abs() > 1.0 || y.abs() > 1.0 {
        return 1.0;
    }
    pyfmt::hypot(dx, dy) - radius
}

/// `icon_ring_arc(x, y, inner, outer, start, end)`: inside an annulus sector, angles in radians counter-clockwise.
pub fn icon_ring_arc(x: f64, y: f64, inner: f64, outer: f64, start: f64, end: f64) -> bool {
    let distance = pyfmt::hypot(x, y);
    if !(inner <= distance && distance <= outer) {
        return false;
    }
    let turn = 2.0 * PI;
    let angle = pyfmt::rem(atan2(y, x), turn);
    let start = pyfmt::rem(start, turn);
    let end = pyfmt::rem(end, turn);
    if start <= end {
        return start <= angle && angle <= end;
    }
    angle >= start || angle <= end
}

fn shape(key: &str) -> f64 {
    ICON_SHAPE.at(key).f()
}

/// `icon_head_centre(angle)`: the head's centre on the stroke's centre line, at `angle` degrees.
pub fn icon_head_centre(angle: Option<f64>) -> (f64, f64) {
    let middle = (shape("ring_inner") + shape("ring_outer")) / 2.0;
    let radians = angle.unwrap_or_else(|| shape("arc_end")).to_radians();
    (middle * radians.cos(), middle * radians.sin())
}

/// `icon_head_box(size, angle)`: the pixels (left, top, right, bottom) a head at `angle` can touch.
pub fn icon_head_box(size: i64, angle: Option<f64>) -> [i64; 4] {
    let (x, y) = icon_head_centre(angle);
    let reach = shape("head_radius");
    let size_f = size as f64;
    [
        0.max(pyfmt::floor((x - reach + 1.0) / 2.0 * size_f)),
        0.max(pyfmt::floor((1.0 - (y + reach)) / 2.0 * size_f)),
        size.min(pyfmt::ceil((x + reach + 1.0) / 2.0 * size_f)),
        size.min(pyfmt::ceil((1.0 - (y - reach)) / 2.0 * size_f)),
    ]
}

/// One pixel's samples: (covered, heads, red, green, blue).
pub type Sample = [i64; 5];

/// What `icon_samples` is asked for besides the size.
#[derive(Clone, Debug, Default)]
pub struct Samples<'a> {
    pub rim: f64,
    pub head_angle: Option<f64>,
    pub no_head: bool,
    pub bounds: Option<[i64; 4]>,
    pub body: Option<(&'a str, &'a str)>,
}

/// `icon_samples(size, rim, head_angle=, head=, box=, body=)`: the mark's samples, pixel by pixel.
pub fn icon_samples(size: i64, asked: &Samples) -> Py<Vec<Vec<Sample>>> {
    let steps = ICON_SUPERSAMPLE.i();
    let scale = (size * steps) as f64;
    let radius = if size >= ICON_SHAPE.at("corner_threshold").i() {
        shape("corner_large")
    } else {
        shape("corner_small")
    };
    let (mut top_colour, mut bottom_colour, mark) = (
        rgb(ICON_TOP.s())?,
        rgb(ICON_BOTTOM.s())?,
        rgb(ICON_MARK.s())?,
    );
    if let Some((first, last)) = asked.body {
        top_colour = rgb(first)?;
        bottom_colour = rgb(last)?;
    }
    let (inner, outer) = (shape("ring_inner"), shape("ring_outer"));
    let (start, end) = (
        shape("arc_start").to_radians(),
        shape("arc_end").to_radians(),
    );
    let (head_x, head_y) = icon_head_centre(asked.head_angle);
    let head_radius = shape("head_radius");
    let [left, top, right, bottom] = asked.bounds.unwrap_or([0, 0, size, size]);
    let mut rows = Vec::new();
    for py in top..bottom {
        let mut row = Vec::new();
        for px in left..right {
            let (mut covered, mut heads, mut red, mut green, mut blue) = (0, 0, 0, 0, 0);
            for sy in 0..steps {
                let fy = ((py * steps + sy) as f64 + 0.5) / scale * 2.0 - 1.0;
                for sx in 0..steps {
                    let fx = ((px * steps + sx) as f64 + 0.5) / scale * 2.0 - 1.0;
                    let distance = icon_rounded_square(fx, fy, radius);
                    if distance > 0.0 {
                        continue;
                    }
                    covered += 1;
                    if !asked.no_head && pyfmt::hypot(fx - head_x, -fy - head_y) <= head_radius {
                        heads += 1;
                        continue;
                    }
                    let colour = if icon_ring_arc(fx, -fy, inner, outer, start, end) {
                        mark
                    } else if asked.rim != 0.0 && distance >= -asked.rim {
                        top_colour
                    } else {
                        let position = (fy + 1.0) / 2.0;
                        let mut tone = [0i64; 3];
                        for index in 0..3 {
                            let (x, y) = (top_colour[index] as f64, bottom_colour[index] as f64);
                            tone[index] = pyfmt::round_int(x + (y - x) * position);
                        }
                        tone
                    };
                    red += colour[0];
                    green += colour[1];
                    blue += colour[2];
                }
            }
            row.push([covered, heads, red, green, blue]);
        }
        rows.push(row);
    }
    Ok(rows)
}

fn floor_div(a: i64, b: i64) -> i64 {
    a.div_euclid(b) - if b < 0 && a.rem_euclid(b) != 0 { 1 } else { 0 }
}

/// `icon_pixel(sample, head_colour)`: one (red, green, blue, alpha) pixel, with the head in `head_colour`.
pub fn icon_pixel(sample: &Sample, head: [i64; 3]) -> [i64; 4] {
    let [covered, heads, red, green, blue] = *sample;
    if covered == 0 {
        return [0, 0, 0, 0];
    }
    let whole = ICON_SUPERSAMPLE.i() * ICON_SUPERSAMPLE.i();
    [
        floor_div(red + heads * head[0], covered),
        floor_div(green + heads * head[1], covered),
        floor_div(blue + heads * head[2], covered),
        floor_div(covered * 255, whole),
    ]
}

/// `icon_render(size, rim)`: raw RGBA bytes for one square icon, the mark as the .ico and the logos carry it.
pub fn icon_render(size: i64, rim: f64) -> Py<Vec<u8>> {
    let head = rgb(ICON_ACCENT.s())?;
    let mut out = Vec::new();
    for row in icon_samples(
        size,
        &Samples {
            rim,
            ..Samples::default()
        },
    )? {
        for sample in &row {
            for part in icon_pixel(sample, head) {
                out.push(u8::try_from(part).map_err(|_| "ValueError")?);
            }
        }
    }
    Ok(out)
}
