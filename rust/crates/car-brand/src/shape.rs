//! The corner every rounded thing is drawn with: Figma's corner smoothing (brand/shape.py).
//!
//! The geometry only: one corner (`corner`), the outline as segments (`outline`, `flatten`), and a corner's profile
//! for masks and shadows (`profile`, `inside`, `distance`). The profiles are kept per corner as the tag keeps them -
//! two tables of at most 64, each cleared when full - because a key is a rounded radius, and which profile a nearby
//! radius is answered with depends on what was asked before it, in the tag as here.

use std::cell::RefCell;
use std::collections::HashMap;

use crate::Py;
use crate::pyfmt;
use crate::tokens::design_name;

pub use crate::tables_gen::{CSS_CORNER, DESIGN_SMOOTHING, HALF_STEPS, PROFILE_LIMIT, RHO_STEPS};

/// `design_smoothing(design)`: how much a design smooths its corners.
pub fn design_smoothing(design: Option<&str>) -> Py<f64> {
    Ok(DESIGN_SMOOTHING.at(design_name(design)?).f())
}

/// One corner (`Corner`): radius and smoothing as drawn, p its length along each side, a b c d the Bezier's
/// spacings and `chord` the arc's run along each axis.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Corner {
    pub radius: f64,
    pub smoothing: f64,
    pub p: f64,
    pub a: f64,
    pub b: f64,
    pub c: f64,
    pub d: f64,
    pub chord: f64,
}

/// `corner(radius, smoothing, budget)`: one corner in a box whose shorter side is `2 * budget`.
pub fn corner(radius: f64, smoothing: f64, budget: f64) -> Corner {
    let budget = pyfmt::max(0.0, budget);
    let radius = pyfmt::max(0.0, pyfmt::min(radius, budget));
    if radius <= 0.0 {
        return Corner {
            radius: 0.0,
            smoothing: 0.0,
            p: 0.0,
            a: 0.0,
            b: 0.0,
            c: 0.0,
            d: 0.0,
            chord: 0.0,
        };
    }
    let smoothing = pyfmt::max(0.0, pyfmt::min(smoothing, budget / radius - 1.0));
    let p = pyfmt::min((1.0 + smoothing) * radius, budget);
    let arc = 90.0 * (1.0 - smoothing);
    let chord = (arc / 2.0).to_radians().sin() * radius * 2.0f64.sqrt();
    let alpha = (90.0 - arc) / 2.0;
    let p3_to_p4 = radius * (alpha / 2.0).to_radians().tan();
    let beta = 45.0 * smoothing;
    let c = p3_to_p4 * beta.to_radians().cos();
    let d = c * beta.to_radians().tan();
    let b = (p - chord - c - d) / 3.0;
    Corner {
        radius,
        smoothing,
        p,
        a: 2.0 * b,
        b,
        c,
        d,
        chord,
    }
}

/// `smoothed(found)`: whether a corner is drawn smoothed.
pub fn smoothed(found: &Corner) -> bool {
    found.smoothing > 1e-9
}

/// One piece of an outline (`outline`'s segments).
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Segment {
    Point((f64, f64)),
    Bezier([(f64, f64); 4]),
    /// centre, radius, start and sweep in GDI+'s degrees.
    Arc((f64, f64), f64, f64, f64),
}

pub const ORDER: [&str; 4] = ["top_left", "top_right", "bottom_right", "bottom_left"];

fn turn(name: &str, x: f64, y: f64) -> (f64, f64) {
    match name {
        "top_right" => (x, y),
        "bottom_right" => (-y, x),
        "bottom_left" => (-x, -y),
        _ => (y, -x),
    }
}

fn quadrant(name: &str) -> f64 {
    match name {
        "top_right" => 270.0,
        "bottom_right" => 0.0,
        "bottom_left" => 90.0,
        _ => 180.0,
    }
}

fn vertex(rect: [f64; 4], name: &str) -> (f64, f64) {
    let [left, top, right, bottom] = rect;
    match name {
        "top_left" => (left, top),
        "top_right" => (right, top),
        "bottom_right" => (right, bottom),
        _ => (left, bottom),
    }
}

/// `corner_segments(found, vertex, name)`: one corner's segments; a circular corner is its arc alone.
pub fn corner_segments(found: &Corner, at_vertex: (f64, f64), name: &str) -> Vec<Segment> {
    let (vx, vy) = at_vertex;
    let at = |x: f64, y: f64| {
        let (tx, ty) = turn(name, x, y);
        (vx + tx, vy + ty)
    };
    let (radius, p, a, b, c, d) = (found.radius, found.p, found.a, found.b, found.c, found.d);
    let start = quadrant(name);
    let centre = at(-radius, radius);
    if !smoothed(found) {
        return vec![Segment::Arc(centre, radius, start, 90.0)];
    }
    let beta = 45.0 * found.smoothing;
    vec![
        Segment::Bezier([
            at(-p, 0.0),
            at(-p + a, 0.0),
            at(-p + a + b, 0.0),
            at(-p + a + b + c, d),
        ]),
        Segment::Arc(centre, radius, start + beta, 90.0 - 2.0 * beta),
        Segment::Bezier([
            at(-d, p - a - b - c),
            at(0.0, p - a - b),
            at(0.0, p - a),
            at(0.0, p),
        ]),
    ]
}

/// `outline(rect, radius, smoothing, corners)`: the outline as segments in drawing order; empty for a box too small
/// to round.
pub fn outline(rect: [f64; 4], radius: f64, smoothing: f64, corners: &[&str]) -> Vec<Segment> {
    let [left, top, right, bottom] = rect;
    let budget = pyfmt::min(right - left, bottom - top) / 2.0;
    let found = corner(radius, smoothing, budget);
    if found.radius * 2.0 <= 1.0 {
        return Vec::new();
    }
    let mut segments = Vec::new();
    for name in ORDER {
        let at = vertex(rect, name);
        if corners.contains(&name) {
            segments.extend(corner_segments(&found, at, name));
        } else {
            segments.push(Segment::Point(at));
        }
    }
    segments
}

fn bezier_at(points: &[(f64, f64); 4], t: f64) -> (f64, f64) {
    let [p0, p1, p2, p3] = *points;
    let s = 1.0 - t;
    (
        s * s * s * p0.0 + 3.0 * s * s * t * p1.0 + 3.0 * s * t * t * p2.0 + t * t * t * p3.0,
        s * s * s * p0.1 + 3.0 * s * s * t * p1.1 + 3.0 * s * t * t * p2.1 + t * t * t * p3.1,
    )
}

/// `flatten(segments, steps)`: the outline's points, each Bezier and arc cut into `steps` straight pieces.
pub fn flatten(segments: &[Segment], steps: i64) -> Vec<(f64, f64)> {
    let mut points = Vec::new();
    let count = steps as f64;
    for segment in segments {
        match segment {
            Segment::Point(at) => points.push(*at),
            Segment::Bezier(control) => {
                for k in 0..=steps {
                    points.push(bezier_at(control, k as f64 / count));
                }
            }
            Segment::Arc((cx, cy), radius, start, sweep) => {
                for k in 0..=steps {
                    let angle = (start + sweep * k as f64 / count).to_radians();
                    points.push((cx + radius * angle.cos(), cy + radius * angle.sin()));
                }
            }
        }
    }
    points
}

/// A corner's profile (`Profile`): what a mask asks of a corner, worked out once per radius and smoothing.
#[derive(Clone, Debug, PartialEq)]
pub struct Profile {
    pub corner: Corner,
    pub p: f64,
    pub middle: f64,
    pub joint: f64,
    pub bezier_u: Vec<f64>,
    pub bezier_v: Vec<f64>,
    pub rho: Vec<f64>,
    pub lean: Vec<f64>,
}

fn arc_v(radius: f64, u: f64) -> f64 {
    let rest = radius * radius - (radius - u) * (radius - u);
    if rest > 0.0 {
        radius - rest.sqrt()
    } else {
        radius
    }
}

fn half_points(found: &Corner, steps: i64) -> Vec<(f64, f64)> {
    let (radius, p, a, b, c, d) = (found.radius, found.p, found.a, found.b, found.c, found.d);
    let mut points = Vec::new();
    let count = steps as f64;
    let start = if smoothed(found) {
        let control = [(p, 0.0), (p - a, 0.0), (p - a - b, 0.0), (p - a - b - c, d)];
        for k in 0..steps {
            points.push(bezier_at(&control, k as f64 / count));
        }
        (270.0 - 45.0 * found.smoothing).to_radians()
    } else {
        270.0f64.to_radians()
    };
    let end = 225.0f64.to_radians();
    for k in 0..=steps {
        let angle = start + (end - start) * k as f64 / count;
        points.push((radius + radius * angle.cos(), radius + radius * angle.sin()));
    }
    points
}

/// `bisect.bisect_left(items, x)`.
fn bisect_left(items: &[f64], x: f64) -> usize {
    let (mut low, mut high) = (0, items.len());
    while low < high {
        let middle = (low + high) / 2;
        if items[middle] < x {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    low
}

/// A float as a dict key: Python's `==` (0.0 is -0.0).
fn key(x: f64) -> u64 {
    (x + 0.0).to_bits()
}

thread_local! {
    static UNITS: RefCell<HashMap<u64, Profile>> = RefCell::new(HashMap::new());
    static PROFILES: RefCell<HashMap<(u64, u64), Profile>> = RefCell::new(HashMap::new());
}

fn unit(smoothing: f64) -> Profile {
    if let Some(known) = UNITS.with(|units| units.borrow().get(&key(smoothing)).cloned()) {
        return known;
    }
    let half_steps = HALF_STEPS.i();
    let rho_steps = RHO_STEPS.i();
    let found = corner(1.0, smoothing, 1e9);
    let (p, radius) = (found.p, found.radius);
    let half = half_points(&found, half_steps);
    let joint = if smoothed(&found) {
        p - found.a - found.b - found.c
    } else {
        radius
    };
    let mut bezier: Vec<(f64, f64)> = if smoothed(&found) {
        half[..(half_steps as usize + 1).min(half.len())]
            .iter()
            .copied()
            .filter(|point| point.0 >= joint)
            .collect()
    } else {
        Vec::new()
    };
    bezier.sort_by(|one, other| one.partial_cmp(other).unwrap_or(std::cmp::Ordering::Equal));
    let (mut ts, mut rs, mut leans) = (Vec::new(), Vec::new(), Vec::new());
    let last = half.len() - 1;
    for k in (0..=last).rev() {
        let (u, v) = half[k];
        let (qx, qy) = (p - u, p - v);
        if qx + qy <= 0.0 {
            continue;
        }
        let (u0, v0) = half[k.saturating_sub(1)];
        let (u1, v1) = half[(k + 1).min(last)];
        let tangent = pyfmt::hypot(u1 - u0, v1 - v0);
        let r = pyfmt::hypot(qx, qy);
        ts.push(qy / (qx + qy));
        rs.push(r);
        leans.push(if tangent > 0.0 && r > 0.0 {
            (qx * (v1 - v0) - qy * (u1 - u0)).abs() / (r * tangent)
        } else {
            1.0
        });
    }
    let size = rho_steps as usize;
    let mut rho = vec![0.0; size + 1];
    let mut lean = vec![1.0; size + 1];
    for k in size / 2..=size {
        let t = k as f64 / rho_steps as f64;
        let i = bisect_left(&ts, t).max(1).min(ts.len() - 1);
        let (t0, t1) = (ts[i - 1], ts[i]);
        let share = if t1 > t0 {
            pyfmt::min(1.0, pyfmt::max(0.0, (t - t0) / (t1 - t0)))
        } else {
            0.0
        };
        let value = rs[i - 1] + (rs[i] - rs[i - 1]) * share;
        rho[k] = value;
        rho[size - k] = value;
        let leant = leans[i - 1] + (leans[i] - leans[i - 1]) * share;
        lean[k] = leant;
        lean[size - k] = leant;
    }
    let made = Profile {
        corner: found,
        p,
        middle: radius * (1.0 - 0.5f64.sqrt()),
        joint,
        bezier_u: bezier.iter().map(|point| point.0).collect(),
        bezier_v: bezier.iter().map(|point| point.1).collect(),
        rho,
        lean,
    };
    UNITS.with(|units| {
        let mut units = units.borrow_mut();
        if units.len() >= PROFILE_LIMIT.i() as usize {
            units.clear();
        }
        units.insert(key(smoothing), made.clone());
    });
    made
}

/// `profile(radius, smoothing, budget)`: the corner's tables, kept per corner as drawn.
pub fn profile(radius: f64, smoothing: f64, budget: f64) -> Profile {
    let found = corner(radius, smoothing, budget);
    let kept = (
        key(pyfmt::round_to(found.radius, 6)),
        key(pyfmt::round_to(found.smoothing, 6)),
    );
    if let Some(known) = PROFILES.with(|profiles| profiles.borrow().get(&kept).cloned()) {
        return known;
    }
    let base = unit(pyfmt::round_to(found.smoothing, 9));
    let size = found.radius;
    let made = Profile {
        corner: found,
        p: found.p,
        middle: base.middle * size,
        joint: base.joint * size,
        bezier_u: base.bezier_u.iter().map(|value| size * value).collect(),
        bezier_v: base.bezier_v.iter().map(|value| size * value).collect(),
        rho: base.rho.iter().map(|value| size * value).collect(),
        lean: base.lean,
    };
    PROFILES.with(|profiles| {
        let mut profiles = profiles.borrow_mut();
        if profiles.len() >= PROFILE_LIMIT.i() as usize {
            profiles.clear();
        }
        profiles.insert(kept, made.clone());
    });
    made
}

/// `edge_at(made, u)`: the outline's v at u on its half nearer the horizontal side.
pub fn edge_at(made: &Profile, u: f64) -> f64 {
    if u >= made.p {
        return 0.0;
    }
    if u <= made.joint || made.bezier_u.len() < 2 {
        return arc_v(
            made.corner.radius,
            pyfmt::max(0.0, pyfmt::min(u, made.corner.radius)),
        );
    }
    let (us, vs) = (&made.bezier_u, &made.bezier_v);
    let i = bisect_left(us, u).max(1).min(us.len() - 1);
    let (u0, u1) = (us[i - 1], us[i]);
    vs[i - 1] + (vs[i] - vs[i - 1]) * if u1 > u0 { (u - u0) / (u1 - u0) } else { 0.0 }
}

/// `inside_corner(made, u, v)`: whether a point in a corner's local frame is inside the outline.
pub fn inside_corner(made: &Profile, u: f64, v: f64) -> bool {
    if u < 0.0 || v < 0.0 {
        return false;
    }
    if u >= made.p || v >= made.p {
        return true;
    }
    let (u, v) = if v > u { (v, u) } else { (u, v) };
    if u < made.middle {
        return false;
    }
    v >= edge_at(made, u)
}

/// `inside(x, y, rect, radius, smoothing)`: whether (x, y) is inside `rect` rounded as `outline` draws it.
pub fn inside(x: f64, y: f64, rect: [f64; 4], radius: f64, smoothing: f64) -> bool {
    let [left, top, right, bottom] = rect;
    if !(left <= x && x <= right && top <= y && y <= bottom) {
        return false;
    }
    let made = profile(
        radius,
        smoothing,
        pyfmt::min(right - left, bottom - top) / 2.0,
    );
    inside_corner(
        &made,
        pyfmt::min(x - left, right - x),
        pyfmt::min(y - top, bottom - y),
    )
}

/// `distance(x, y, half_width, half_height, radius, smoothing)`: signed distance to the rounded box centred on the
/// origin; inside is negative.
pub fn distance(
    x: f64,
    y: f64,
    half_width: f64,
    half_height: f64,
    radius: f64,
    smoothing: f64,
) -> Py<f64> {
    let made = profile(radius, smoothing, pyfmt::min(half_width, half_height));
    let p = made.p;
    let qx = x.abs() - (half_width - p);
    let qy = y.abs() - (half_height - p);
    if qx > 0.0 && qy > 0.0 {
        if !smoothed(&made.corner) {
            return Ok(pyfmt::hypot(qx, qy) - p);
        }
        let k = qy / (qx + qy) * RHO_STEPS.f() + 0.5;
        let k = k.trunc() as usize;
        let rho = made.rho.get(k).ok_or("IndexError")?;
        return Ok((pyfmt::hypot(qx, qy) - rho) * made.lean[k]);
    }
    Ok(pyfmt::max(qx, qy) - p)
}
