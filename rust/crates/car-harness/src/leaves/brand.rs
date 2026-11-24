//! car-brand's calls: the palette and its arithmetic, the scale and the designs, the motion curve, the shadows, the
//! check box, the status light, the mark's rasteriser, the corner's shape, the special days, the icon's motion, the
//! panel's CSS and gui/Brand.cs.
//!
//! A theme, a design or a state the Python compares with `==` and finds nothing for may be any value; one it looks
//! up in a dict raises TypeError when it cannot be hashed. Both are read here as Python reads them.

use car_brand::data::{D, Num};
use car_brand::days::{self, Element};
use car_brand::elevation::Shadow;
use car_brand::mark::Samples;
use car_brand::shape::{self, Profile, Segment};
use car_brand::{
    checkbox, colour, css, design, elevation, light, make_brand, mark, motion, pyfmt, scale,
    tokens, tray_motion,
};
use car_machine::hash;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{Py, truthy};

use super::Args;

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

fn num(value: Num) -> Value {
    match value {
        Num::I(int) => Value::from(int),
        Num::F(x) => Value::Float(x),
    }
}

fn float(x: f64) -> Value {
    Value::Float(x)
}

fn pair(x: f64, y: f64) -> Value {
    Value::Array(vec![float(x), float(y)])
}

fn ints(values: &[i64]) -> Value {
    Value::Array(values.iter().map(|each| Value::from(*each)).collect())
}

fn floats(values: &[f64]) -> Value {
    Value::Array(values.iter().map(|each| float(*each)).collect())
}

fn nums(values: &[Num]) -> Value {
    Value::Array(values.iter().map(|each| num(*each)).collect())
}

fn points(values: &[(f64, f64)]) -> Value {
    Value::Array(values.iter().map(|(x, y)| pair(*x, *y)).collect())
}

/// A table's value as the Python holds it (a dict in its order, a tuple as a list).
fn data(value: &'static D) -> Value {
    match value {
        D::Null => Value::Null,
        D::B(flag) => Value::Bool(*flag),
        D::N(number) => num(*number),
        D::S(text) => Value::from(*text),
        D::L(items) => Value::Array(items.iter().map(data).collect()),
        D::M(items) => {
            let mut map = Map::new();
            for (key, each) in items.iter() {
                map.insert(Str::from(*key), data(each));
            }
            Value::Object(map)
        }
    }
}

fn number(value: &Value) -> Py<Num> {
    match value {
        Value::Int(int) => int.as_i64().map(Num::I).ok_or("OverflowError"),
        Value::Float(x) => Ok(Num::F(*x)),
        Value::Bool(flag) => Ok(Num::I(i64::from(*flag))),
        _ => Err("TypeError"),
    }
}

fn real(value: &Value) -> Py<f64> {
    number(value).map(Num::f)
}

/// A value compared with `==` against names: its text, or None for anything that is not a str.
fn compared(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

/// A value looked up as a dict's key: its text, None for a hashable non-str, TypeError for a list or a dict.
fn looked_up(value: &Value) -> Py<Option<&str>> {
    match value {
        Value::Array(_) | Value::Object(_) => Err("TypeError"),
        other => Ok(compared(other)),
    }
}

/// A theme or a design argument, its default when absent.
fn named<'a>(args: &'a Args, at: usize, default: &'a str) -> Option<&'a str> {
    if at >= args.0.len() {
        Some(default)
    } else {
        compared(args.get(at))
    }
}

fn text_of(value: &Value) -> Py<&str> {
    match value {
        Value::Str(text) => text.as_str().ok_or("ValueError"),
        _ => Err("TypeError"),
    }
}

fn shadow_of(value: &Value) -> Py<Shadow> {
    let Value::Array(parts) = value else {
        return Err("TypeError");
    };
    if parts.len() != 6 {
        return Err("TypeError");
    }
    let token: &'static str = match compared(&parts[3]) {
        Some("shadow_dark") => "shadow_dark",
        Some("shadow_light") => "shadow_light",
        _ => "shadow_dark",
    };
    Ok(Shadow {
        dx: number(&parts[0])?,
        dy: number(&parts[1])?,
        blur: number(&parts[2])?,
        token,
        alpha: number(&parts[4])?,
        inset: truthy(&parts[5]),
    })
}

fn shadow_value(shadow: &Shadow) -> Value {
    Value::Array(vec![
        num(shadow.dx),
        num(shadow.dy),
        num(shadow.blur),
        Value::from(shadow.token),
        num(shadow.alpha),
        Value::Bool(shadow.inset),
    ])
}

fn optional_real(value: &Value) -> Py<Option<f64>> {
    match value {
        Value::Null => Ok(None),
        other => real(other).map(Some),
    }
}

fn int_list<const N: usize>(value: &Value) -> Py<[i64; N]> {
    let Value::Array(parts) = value else {
        return Err("TypeError");
    };
    let mut out = [0i64; N];
    if parts.len() != N {
        return Err("ValueError");
    }
    for (index, part) in parts.iter().enumerate() {
        out[index] = match number(part)? {
            Num::I(int) => int,
            Num::F(_) => return Err("TypeError"),
        };
    }
    Ok(out)
}

fn real_list<const N: usize>(value: &Value) -> Py<[f64; N]> {
    let Value::Array(parts) = value else {
        return Err("TypeError");
    };
    if parts.len() != N {
        return Err("ValueError");
    }
    let mut out = [0.0; N];
    for (index, part) in parts.iter().enumerate() {
        out[index] = real(part)?;
    }
    Ok(out)
}

fn segment_value(segment: &Segment) -> Value {
    match segment {
        Segment::Point((x, y)) => Value::Array(vec![Value::from("point"), pair(*x, *y)]),
        Segment::Bezier(control) => {
            let mut parts = vec![Value::from("bezier")];
            parts.extend(control.iter().map(|(x, y)| pair(*x, *y)));
            Value::Array(parts)
        }
        Segment::Arc((cx, cy), radius, start, sweep) => Value::Array(vec![
            Value::from("arc"),
            pair(*cx, *cy),
            float(*radius),
            float(*start),
            float(*sweep),
        ]),
    }
}

fn segment_of(value: &Value) -> Py<Segment> {
    let Value::Array(parts) = value else {
        return Err("TypeError");
    };
    let at = |index: usize| -> Py<(f64, f64)> {
        let [x, y] = real_list::<2>(parts.get(index).ok_or("IndexError")?)?;
        Ok((x, y))
    };
    Ok(match compared(parts.first().ok_or("IndexError")?) {
        Some("point") => Segment::Point(at(1)?),
        Some("bezier") => Segment::Bezier([at(1)?, at(2)?, at(3)?, at(4)?]),
        _ => Segment::Arc(
            at(1)?,
            real(parts.get(2).ok_or("IndexError")?)?,
            real(parts.get(3).ok_or("IndexError")?)?,
            real(parts.get(4).ok_or("IndexError")?)?,
        ),
    })
}

fn corner_value(found: &shape::Corner) -> Value {
    floats(&[
        found.radius,
        found.smoothing,
        found.p,
        found.a,
        found.b,
        found.c,
        found.d,
        found.chord,
    ])
}

fn profile_value(made: &Profile) -> Value {
    Value::Array(vec![
        corner_value(&made.corner),
        float(made.p),
        float(made.middle),
        float(made.joint),
        floats(&made.bezier_u),
        floats(&made.bezier_v),
        floats(&made.rho),
        floats(&made.lean),
    ])
}

fn element_value(element: &Element) -> Value {
    Value::Array(vec![
        Value::from(element.kind.as_str()),
        nums(&element.numbers),
        Value::from(element.colour.as_str()),
        num(element.opacity),
        Value::from(element.motion.as_str()),
        nums(&element.values),
    ])
}

fn element_of(value: &Value) -> Py<Element> {
    let Value::Array(parts) = value else {
        return Err("TypeError");
    };
    if parts.len() != 6 {
        return Err("ValueError");
    }
    let numbers = |value: &Value| -> Py<Vec<Num>> {
        match value {
            Value::Array(items) => items.iter().map(number).collect(),
            _ => Err("TypeError"),
        }
    };
    Ok(Element {
        kind: text_of(&parts[0])?.to_owned(),
        numbers: numbers(&parts[1])?,
        colour: text_of(&parts[2])?.to_owned(),
        opacity: number(&parts[3])?,
        motion: text_of(&parts[4])?.to_owned(),
        values: numbers(&parts[5])?,
    })
}

fn shape_value(shape: &days::Shape) -> Value {
    Value::Array(vec![
        Value::from(shape.kind.as_str()),
        nums(&shape.numbers),
        Value::from(shape.colour.as_str()),
        num(shape.opacity),
    ])
}

fn elements(list: &[Element]) -> Value {
    Value::Array(list.iter().map(element_value).collect())
}

fn sha(bytes: &[u8]) -> Value {
    Value::from(hash::hex(&hash::sha256(bytes)))
}

/// `px` as the diff hands it: ("round", scale) is `int(round(v * scale))`, ("float", scale) is `v * scale`.
fn px_of(mode: &str, factor: Num) -> impl Fn(Num) -> Num + '_ {
    move |value: Num| {
        let product = value.times(factor);
        match (mode, product) {
            ("round", Num::F(x)) => Num::I(pyfmt::round_int(x)),
            _ => product,
        }
    }
}

fn samples_value(rows: &[Vec<mark::Sample>]) -> Value {
    Value::Array(
        rows.iter()
            .map(|row| Value::Array(row.iter().map(|sample| ints(sample)).collect()))
            .collect(),
    )
}

fn glow_value(found: Option<light::Glow>) -> Value {
    match found {
        None => Value::Null,
        Some(glow) => object(vec![
            ("dim", float(glow.dim)),
            ("opacity", float(glow.opacity)),
            ("spread", float(glow.spread)),
            ("arc", glow.arc.map_or(Value::Null, num)),
        ]),
    }
}

pub fn case(name: &str, a: &Args) -> Option<Py<Value>> {
    Some(match name {
        // ---------------------------------------------------------------- colour and tokens
        "brand.rgb" => text_of(a.get(0))
            .and_then(colour::rgb)
            .map(|triple| ints(&triple)),
        "brand.mix" => (|| {
            Ok(Value::from(colour::mix(
                text_of(a.get(0))?,
                text_of(a.get(1))?,
                real(a.get(2))?,
            )?))
        })(),
        "brand.brighten" => (|| {
            Ok(Value::from(colour::brighten(
                text_of(a.get(0))?,
                real(a.get(1))?,
            )?))
        })(),
        "brand.luminance" => text_of(a.get(0)).and_then(colour::luminance).map(float),
        "brand.contrast" => (|| {
            Ok(float(colour::contrast(
                text_of(a.get(0))?,
                text_of(a.get(1))?,
            )?))
        })(),
        "brand.theme_name" => tokens::theme_name(compared(a.get(0))).map(Value::from),
        "brand.design_name" => tokens::design_name(compared(a.get(0))).map(Value::from),
        "brand.palette" => tokens::palette(named(a, 0, "light"), named(a, 1, "soft")).map(data),
        "brand.tables" => Ok(object(vec![
            ("RAMP", data(&tokens::RAMP)),
            ("BRAND", data(&tokens::BRAND)),
            ("EDITION_INK", data(&tokens::EDITION_INK)),
            ("RADII", data(&scale::RADII)),
            ("SPACING", data(&scale::SPACING)),
            ("TYPE", data(&scale::TYPE)),
            ("TYPE_SCALE", data(&scale::TYPE_SCALE)),
            ("LINE_HEIGHT", data(&scale::LINE_HEIGHT)),
            ("TYPE_ROLES", data(&scale::TYPE_ROLES)),
            ("LAYOUT", data(&scale::LAYOUT)),
            ("DESIGN", data(&design::DESIGN)),
            ("DESIGN_RADII", data(&design::DESIGN_RADII)),
            ("MOTION", data(&motion::MOTION)),
            ("SHADOWS", data(&elevation::SHADOWS)),
            ("CHECKBOX", data(&checkbox::CHECKBOX)),
            ("GLOW", data(&light::GLOW)),
            ("ICON_SHAPE", data(&mark::ICON_SHAPE)),
            ("DAY_LOOKS", data(&days::DAY_LOOKS)),
            ("LUNAR_DAYS", data(&days::LUNAR_DAYS)),
            ("DAY_EGG_COLOURS", data(&days::DAY_EGG_COLOURS)),
            ("ICON_MOTION", data(&tray_motion::ICON_MOTION)),
        ])),
        // ---------------------------------------------------------------- scale, design, motion
        "brand.padding" => text_of(a.get(0))
            .and_then(scale::padding)
            .map(|values| nums(&values)),
        "brand.design_depth" => design::design_depth(named(a, 0, "soft")).map(Value::Bool),
        "brand.design_glow" => design::design_glow(named(a, 0, "soft")).map(Value::Bool),
        "brand.design_accent_bar" => {
            design::design_accent_bar(named(a, 0, "soft")).map(Value::Bool)
        }
        "brand.design_radii" => design::design_radii(named(a, 0, "soft")).map(data),
        "brand.ease" => real(a.get(0)).map(|progress| float(motion::ease(progress))),
        "brand._bezier" => (|| {
            Ok(float(motion::bezier(
                real(a.get(0))?,
                real(a.get(1))?,
                real(a.get(2))?,
            )))
        })(),
        // ---------------------------------------------------------------- elevation
        "brand.shadows" => (|| {
            let found = elevation::shadows(
                text_of(a.get(0))?,
                named(a, 1, "light"),
                named(a, 2, "soft"),
            )?;
            Ok(Value::Array(found.iter().map(shadow_value).collect()))
        })(),
        "brand.card_ground" => {
            elevation::card_ground(named(a, 0, "light"), named(a, 1, "soft")).map(Value::from)
        }
        "brand.shadow_offset" => (|| {
            Ok(num(elevation::shadow_offset(
                &shadow_of(a.get(0))?,
                text_of(a.get(1))?,
            )?))
        })(),
        "brand.shadow_alpha" => (|| {
            let shadow = shadow_of(a.get(0))?;
            let factor = if a.0.len() > 3 {
                number(a.get(3))?
            } else {
                Num::F(1.0)
            };
            Ok(float(elevation::shadow_alpha(
                &shadow,
                number(a.get(1))?,
                text_of(a.get(2))?,
                factor,
            )?))
        })(),
        "brand.elevation_colour" => (|| {
            let inside = match a.get(6) {
                Value::Null => None,
                other => Some(truthy(other)),
            };
            let found = elevation::elevation_colour(
                text_of(a.get(0))?,
                text_of(a.get(1))?,
                number(a.get(2))?,
                text_of(a.get(3))?,
                compared(a.get(4)),
                number(a.get(5))?,
                inside,
                compared(a.get(7)),
            )?;
            Ok(floats(&found))
        })(),
        "brand.reach" => (|| {
            let factor = if a.0.len() > 2 { real(a.get(2))? } else { 1.0 };
            Ok(ints(&elevation::reach(
                text_of(a.get(0))?,
                named(a, 1, "light"),
                factor,
            )?))
        })(),
        // ---------------------------------------------------------------- the check box
        "brand.check_box_state" => Ok(Value::from(checkbox::check_box_state(
            truthy(a.get(0)),
            a.0.len() < 2 || truthy(a.get(1)),
        ))),
        "brand.check_box" => (|| {
            let found = checkbox::check_box(
                truthy(a.get(0)),
                truthy(a.get(1)),
                compared(a.get(2)),
                compared(a.get(3)),
            )?;
            Ok(object(vec![
                ("fill", Value::from(found.fill)),
                ("edge", Value::from(found.edge)),
                ("mark", found.mark.map_or(Value::Null, Value::from)),
                ("well", Value::Bool(found.well)),
            ]))
        })(),
        "brand.check_box_system" => {
            let (fill, edge, mark) = checkbox::check_box_system(truthy(a.get(0)), truthy(a.get(1)));
            Ok(object(vec![
                ("fill", Value::from(fill)),
                ("edge", Value::from(edge)),
                ("mark", mark.map_or(Value::Null, Value::from)),
            ]))
        }
        "brand.css_system" => {
            (|| checkbox::css_system(looked_up(a.get(0))?.ok_or("KeyError")?).map(Value::from))()
        }
        "brand.check_mark" => (|| {
            Ok(points(&checkbox::check_mark(
                real(a.get(0))?,
                real(a.get(1))?,
                real(a.get(2))?,
            )))
        })(),
        "brand.check_mark_outline" => (|| {
            Ok(points(&checkbox::check_mark_outline(
                real(a.get(0))?,
                real(a.get(1))?,
                real(a.get(2))?,
            )))
        })(),
        // ---------------------------------------------------------------- the status light
        "brand.status_fill" => {
            looked_up(a.get(0)).map(|state| Value::from(light::status_fill(state)))
        }
        "brand.status_system" => {
            looked_up(a.get(0)).map(|state| Value::from(light::status_system(state)))
        }
        "brand.status_colour" => (|| {
            // palette(theme, design) is asked before the state is looked up
            tokens::palette(compared(a.get(1)), compared(a.get(2)))?;
            light::status_colour(looked_up(a.get(0))?, compared(a.get(1)), compared(a.get(2)))
                .map(Value::from)
        })(),
        "brand._breath" => (|| Ok(float(light::breath(real(a.get(0))?, real(a.get(1))?)?)))(),
        "brand.glow_floor" => Ok(float(light::glow_floor())),
        "brand.glow_phase" => real(a.get(0)).map(|fraction| {
            let (dim, spread) = light::glow_phase(fraction);
            pair(dim, spread)
        }),
        "brand.glow" => (|| {
            let found = light::glow(
                compared(a.get(0)),
                real(a.get(1))?,
                truthy(a.get(2)),
                compared(a.get(3)),
            )?;
            Ok(glow_value(found))
        })(),
        "brand.glow_moves" => Ok(Value::Bool(light::glow_moves(
            compared(a.get(0)),
            truthy(a.get(1)),
        ))),
        "brand.glow_reach" => real(a.get(0)).map(|radius| float(light::glow_reach(radius))),
        "brand.glow_radius" => {
            (|| Ok(float(light::glow_radius(real(a.get(0))?, real(a.get(1))?))))()
        }
        "brand.glow_extent" => real(a.get(0)).map(|radius| float(light::glow_extent(radius))),
        "brand.glow_stops" => real(a.get(0)).map(|radius| {
            Value::Array(
                light::glow_stops(radius)
                    .iter()
                    .map(|(at, alpha)| Value::Array(vec![float(*at), num(*alpha)]))
                    .collect(),
            )
        }),
        // ---------------------------------------------------------------- the mark
        "brand.icon_rounded_square" => (|| {
            Ok(float(mark::icon_rounded_square(
                real(a.get(0))?,
                real(a.get(1))?,
                real(a.get(2))?,
            )))
        })(),
        "brand.icon_ring_arc" => (|| {
            let [x, y, inner, outer, start, end] =
                [0, 1, 2, 3, 4, 5].map(|index| real(a.get(index)));
            Ok(Value::Bool(mark::icon_ring_arc(
                x?, y?, inner?, outer?, start?, end?,
            )))
        })(),
        "brand.icon_head_centre" => optional_real(a.get(0)).map(|angle| {
            let (x, y) = mark::icon_head_centre(angle);
            pair(x, y)
        }),
        "brand.icon_head_box" => (|| {
            let size = number(a.get(0))?;
            let Num::I(size) = size else {
                return Err("TypeError");
            };
            Ok(ints(&mark::icon_head_box(size, optional_real(a.get(1))?)))
        })(),
        "brand.icon_samples" => (|| {
            let Num::I(size) = number(a.get(0))? else {
                return Err("TypeError");
            };
            let bounds = match a.get(4) {
                Value::Null => None,
                other => Some(int_list::<4>(other)?),
            };
            let body = match a.get(5) {
                Value::Null => None,
                Value::Array(parts) if parts.len() == 2 => {
                    Some((text_of(&parts[0])?, text_of(&parts[1])?))
                }
                _ => return Err("TypeError"),
            };
            let asked = Samples {
                rim: real(a.get(1))?,
                head_angle: optional_real(a.get(2))?,
                no_head: !truthy(a.get(3)),
                bounds,
                body,
            };
            Ok(samples_value(&mark::icon_samples(size, &asked)?))
        })(),
        "brand.icon_pixel" => (|| {
            Ok(ints(&mark::icon_pixel(
                &int_list::<5>(a.get(0))?,
                int_list::<3>(a.get(1))?,
            )))
        })(),
        "brand.icon_render" => (|| {
            let Num::I(size) = number(a.get(0))? else {
                return Err("TypeError");
            };
            let bytes = mark::icon_render(size, real(a.get(1))?)?;
            Ok(Value::Array(vec![
                Value::from(bytes.len() as i64),
                sha(&bytes),
            ]))
        })(),
        // ---------------------------------------------------------------- the CSS
        "brand._number" => real(a.get(0)).map(|value| Value::from(css::number(value))),
        "brand._css_length" => real(a.get(0)).map(|value| Value::from(css::css_length(value))),
        "brand.css_scale" => css::css_scale().map(Value::from),
        "brand.css_corner" => css::css_corner().map(Value::from),
        "brand.css_ease" => Ok(Value::from(css::css_ease())),
        "brand.css_check_box" => Ok(Value::from(css::css_check_box())),
        "brand.css_glow_keyframes" => Ok(Value::from(css::css_glow_keyframes())),
        "brand.css_glow_geometry" => {
            real(a.get(0)).map(|dot| Value::from(css::css_glow_geometry(dot)))
        }
        "brand.css_elevation" => css::css_elevation(compared(a.get(0))).map(Value::from),
        "brand.css_variables" => (|| {
            let Value::Object(map) = a.get(0) else {
                return Err("TypeError");
            };
            let mut owned = Vec::new();
            for (key, value) in map.iter() {
                owned.push((key.as_str().ok_or("ValueError")?, text_of(value)?));
            }
            Ok(Value::from(css::css_variables(&owned)))
        })(),
        "brand.css_variables_of" => tokens::palette(compared(a.get(0)), compared(a.get(1)))
            .map(|palette| Value::from(css::css_variables(&css::pairs(palette)))),
        "brand.css_design_blocks" => (|| {
            let template = match a.get(0) {
                Value::Null => None,
                other => Some(text_of(other)?.to_owned()),
            };
            let extra = template.map(|template| {
                move |theme: &str, design: &str| {
                    template
                        .replace("{theme}", theme)
                        .replace("{design}", design)
                }
            });
            match &extra {
                Some(extra) => css::css_design_blocks(Some(extra)),
                None => css::css_design_blocks(None),
            }
            .map(Value::from)
        })(),
        // ---------------------------------------------------------------- the corner
        "shape.design_smoothing" => shape::design_smoothing(named(a, 0, "soft")).map(float),
        "shape.corner" => (|| {
            Ok(corner_value(&shape::corner(
                real(a.get(0))?,
                real(a.get(1))?,
                real(a.get(2))?,
            )))
        })(),
        "shape.outline" => (|| {
            let rect = real_list::<4>(a.get(0))?;
            let corners: Vec<&str> = match a.get(3) {
                Value::Null => shape::ORDER.to_vec(),
                Value::Array(names) => names.iter().filter_map(compared).collect(),
                _ => return Err("TypeError"),
            };
            let found = shape::outline(rect, real(a.get(1))?, real(a.get(2))?, &corners);
            Ok(Value::Array(found.iter().map(segment_value).collect()))
        })(),
        "shape.flatten" => (|| {
            let Value::Array(items) = a.get(0) else {
                return Err("TypeError");
            };
            let segments = items.iter().map(segment_of).collect::<Py<Vec<_>>>()?;
            let steps = if a.0.len() > 1 { a.int(1)? } else { 32 };
            Ok(points(&shape::flatten(&segments, steps)))
        })(),
        "shape.profile" => (|| {
            Ok(profile_value(&shape::profile(
                real(a.get(0))?,
                real(a.get(1))?,
                real(a.get(2))?,
            )))
        })(),
        "shape.edge_at" => (|| {
            let made = shape::profile(real(a.get(0))?, real(a.get(1))?, real(a.get(2))?);
            Ok(float(shape::edge_at(&made, real(a.get(3))?)))
        })(),
        "shape.inside_corner" => (|| {
            let made = shape::profile(real(a.get(0))?, real(a.get(1))?, real(a.get(2))?);
            Ok(Value::Bool(shape::inside_corner(
                &made,
                real(a.get(3))?,
                real(a.get(4))?,
            )))
        })(),
        "shape.inside" => (|| {
            let rect = real_list::<4>(a.get(2))?;
            Ok(Value::Bool(shape::inside(
                real(a.get(0))?,
                real(a.get(1))?,
                rect,
                real(a.get(3))?,
                real(a.get(4))?,
            )))
        })(),
        "shape.distance" => (|| {
            let [x, y, w, h, r, s] = [0, 1, 2, 3, 4, 5].map(|index| real(a.get(index)));
            Ok(float(shape::distance(x?, y?, w?, h?, r?, s?)?))
        })(),
        // ---------------------------------------------------------------- the days
        "days.day_look" => {
            (|| Ok(days::day_look(a.int(0)?, a.int(1)?, a.int(2)?).map_or(Value::Null, Value::from)))(
            )
        }
        "days.path_points" => (|| {
            let steps = if a.0.len() > 1 { a.int(1)? } else { 8 };
            let found = days::path_points(text_of(a.get(0))?, steps)?;
            Ok(Value::Array(
                found.iter().map(|each| points(each)).collect(),
            ))
        })(),
        "days.mark_colour" => (|| {
            let found = days::mark_colour(
                looked_up(a.get(0))?.ok_or("KeyError")?,
                real(a.get(1))?,
                real(a.get(2))?,
            )?;
            Ok(found.map_or(Value::Null, |triple| ints(&triple)))
        })(),
        "days.scene_elements" => {
            (|| days::scene_elements(looked_up(a.get(0))?.ok_or("KeyError")?).map(elements))()
        }
        "days.speck_elements" => {
            (|| days::speck_elements(looked_up(a.get(0))?.ok_or("KeyError")?).map(elements))()
        }
        "days.mark_text" => {
            (|| days::mark_text(looked_up(a.get(0))?.ok_or("KeyError")?).map(Value::from))()
        }
        "days.scene_text" => {
            (|| days::scene_text(looked_up(a.get(0))?.ok_or("KeyError")?).map(Value::from))()
        }
        "days.speck_text" => {
            (|| days::speck_text(looked_up(a.get(0))?.ok_or("KeyError")?).map(Value::from))()
        }
        "days.speck_reach" => (|| {
            let found = days::speck_reach(looked_up(a.get(0))?.ok_or("KeyError")?)?;
            Ok(Value::Array(
                found
                    .iter()
                    .map(|(start, end)| Value::Array(vec![num(*start), num(*end)]))
                    .collect(),
            ))
        })(),
        "days.speck_frame" => (|| {
            let within = match a.get(2) {
                Value::Null => None,
                other => {
                    let [least, most] = real_list::<2>(other)?;
                    Some((least, most))
                }
            };
            let found = days::speck_frame(
                looked_up(a.get(0))?.ok_or("KeyError")?,
                real(a.get(1))?,
                within,
            )?;
            Ok(Value::Array(found.iter().map(shape_value).collect()))
        })(),
        "days.scene_frame" => (|| {
            let found =
                days::scene_frame(looked_up(a.get(0))?.ok_or("KeyError")?, real(a.get(1))?)?;
            Ok(Value::Array(found.iter().map(shape_value).collect()))
        })(),
        "days.element_at" => (|| {
            Ok(shape_value(&days::element_at(
                &element_of(a.get(0))?,
                real(a.get(1))?,
            )?))
        })(),
        "days.day_band" => (|| {
            let look = looked_up(a.get(0))?.ok_or("KeyError")?;
            let px = px_of(text_of(a.get(1))?, number(a.get(2))?);
            let Value::Array(parts) = a.get(3) else {
                return Err("TypeError");
            };
            if parts.len() != 4 {
                return Err("ValueError");
            }
            let band = [
                number(&parts[0])?,
                number(&parts[1])?,
                number(&parts[2])?,
                number(&parts[3])?,
            ];
            let found = days::day_band(look, &px, band, number(a.get(4))?)?;
            Ok(found.map_or(Value::Null, |band| {
                object(vec![
                    ("kind", Value::from("scene")),
                    ("scene", Value::from(band.scene)),
                    ("rect", nums(&band.rect)),
                    ("unit", float(band.unit)),
                    ("scene_shown", Value::Bool(band.scene_shown)),
                    ("fade", nums(&[band.fade.0, band.fade.1])),
                ])
            }))
        })(),
        "days.PressRun" => (|| {
            let Value::Array(presses) = a.get(0) else {
                return Err("TypeError");
            };
            let mut run = days::PressRun::new();
            let mut said = Vec::new();
            for each in presses {
                said.push(Value::Bool(run.press(number(each)?)));
            }
            Ok(Value::Array(said))
        })(),
        "days.sweep_at" => number(a.get(0)).map(|milliseconds| {
            let (covered, opacity, rings) = days::sweep_at(milliseconds, &motion::ease);
            Value::Array(vec![
                float(covered),
                float(opacity),
                Value::Array(
                    rings
                        .iter()
                        .map(|(spread, shown)| pair(*spread, *shown))
                        .collect(),
                ),
            ])
        }),
        // ---------------------------------------------------------------- the icon's motion
        "tray.icon_brand_state" => {
            looked_up(a.get(0)).map(|state| Value::from(tray_motion::icon_brand_state(state)))
        }
        "tray.icon_head_colour" => {
            (|| tray_motion::icon_head_colour(looked_up(a.get(0))?).map(|triple| ints(&triple)))()
        }
        "tray.icon_level_colour" => (|| {
            Ok(ints(&tray_motion::icon_level_colour(
                int_list::<3>(a.get(0))?,
                real(a.get(1))?,
            )?))
        })(),
        "tray._breath_level" => (|| {
            Ok(Value::from(tray_motion::breath_level(
                real(a.get(0))?,
                real(a.get(1))?,
            )?))
        })(),
        "tray.icon_turn" => (|| {
            Ok(tray_motion::icon_turn(compared(a.get(0)), real(a.get(1))?)?
                .map_or(Value::Null, float))
        })(),
        "tray.icon_frame" => (|| {
            let (position, level) = tray_motion::icon_frame(
                compared(a.get(0)),
                real(a.get(1))?,
                truthy(a.get(2)),
                a.int(3)?,
            )?;
            Ok(ints(&[position, level]))
        })(),
        "tray.icon_frame_ms" => (|| {
            let found = tray_motion::icon_frame_ms(
                compared(a.get(0)),
                real(a.get(1))?,
                truthy(a.get(2)),
                a.int(3)?,
            )?;
            Ok(found.map_or(Value::Null, Value::from))
        })(),
        "tray.icon_motion_allowed" => {
            let flag = |index: usize| truthy(a.get(index));
            Ok(Value::Bool(tray_motion::icon_motion_allowed(
                flag(0),
                flag(1),
                flag(2),
                flag(3),
                flag(4),
                flag(5),
            )))
        }
        "tray.ICON_SWEEP" => Ok(float(tray_motion::icon_sweep())),
        "tray.IconFrames" => (|| {
            let look = match a.get(2) {
                Value::Null => None,
                other => Some(text_of(other)?),
            };
            let frames = tray_motion::IconFrames::new(a.int(0)?, a.int(1)?, look)?;
            let boxes = Value::Array(
                frames
                    .heads
                    .iter()
                    .map(|(bounds, _)| ints(bounds))
                    .collect(),
            );
            let heads = if a.0.len() > 4 && truthy(a.get(4)) {
                Value::Array(
                    frames
                        .heads
                        .iter()
                        .map(|(_, rows)| samples_value(rows))
                        .collect(),
                )
            } else {
                Value::Null
            };
            let Value::Array(asked) = a.get(3) else {
                return Err("TypeError");
            };
            let mut composed = Vec::new();
            for each in asked {
                let Value::Array(parts) = each else {
                    return Err("TypeError");
                };
                let position = number(parts.first().ok_or("IndexError")?)?;
                let Num::I(position) = position else {
                    return Err("TypeError");
                };
                let head = int_list::<3>(parts.get(1).ok_or("IndexError")?)?;
                composed.push(sha(&frames.compose(position, head)?));
            }
            Ok(object(vec![
                ("ground", sha(&frames.ground)),
                ("boxes", boxes),
                ("heads", heads),
                ("composed", Value::Array(composed)),
            ]))
        })(),
        // ---------------------------------------------------------------- gui/Brand.cs
        "make_brand.render" => make_brand::render().map(Value::from),
        "make_brand.mark_frames" => (|| {
            Ok(Value::from(make_brand::base64(&make_brand::mark_frames(
                a.int(0)?,
            )?)))
        })(),
        _ => return None,
    })
}
