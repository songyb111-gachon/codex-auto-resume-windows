//! The days of the year with a look of their own: one table, the icon's mark and the popup's scene, as plain shapes
//! (brand/days.py).
//!
//! `day_look_at(moment)` is the tag's `day_look` of the local date at a moment; the local date is the platform's
//! (car-platform hands it in), so this crate has `day_look` of the date alone.

use std::f64::consts::PI;
use std::sync::OnceLock;

use crate::Py;
use crate::colour::rgb;
use crate::data::Num;
use crate::pyfmt;

pub use crate::tables_gen::{
    CONFETTI_COLOURS, DAY_EGG_COLOURS, DAY_LOOKS, DAY_RINGS, FIXED_DAYS, LUNAR_DAYS, MOTIF_LEAST,
    PRESSES, SCENE_FOCUS, SCENE_FROM_TOP, SCENE_HEIGHT, SCENE_WIDTH, SPECK_BAND, SWEEP, WIDE,
};

/// The five looks, in DAY_LOOKS' order.
pub fn looks() -> Vec<&'static str> {
    DAY_LOOKS.keys().collect()
}

/// `day_look(year, month, day)`: the look of that date, or None for an ordinary day.
pub fn day_look(year: i64, month: i64, day: i64) -> Option<&'static str> {
    for fixed in FIXED_DAYS.list() {
        let parts = fixed.list();
        if (month, day) == (parts[0].i(), parts[1].i()) {
            return Some(parts[2].s());
        }
    }
    for entry in LUNAR_DAYS.list() {
        let parts = entry.list();
        for date in parts[1].list() {
            let ymd = date.list();
            if (year, month, day) == (ymd[0].i(), ymd[1].i(), ymd[2].i()) {
                return Some(parts[0].s());
            }
        }
    }
    None
}

// ------------------------------------------------------------------ a path, as points

/// `_TOKEN.findall(path)`: `[MmLlHhVvQqTtZz]|-?(?:\d+\.?\d*|\.\d+)`, ASCII digits (Python's `\d` also takes other
/// scripts' digits, which no path in the product has).
fn tokens(path: &str) -> Vec<&str> {
    let bytes = path.as_bytes();
    let digit = |at: usize| at < bytes.len() && bytes[at].is_ascii_digit();
    let mut found = Vec::new();
    let mut at = 0;
    while at < bytes.len() {
        if b"MmLlHhVvQqTtZz".contains(&bytes[at]) {
            found.push(&path[at..at + 1]);
            at += 1;
            continue;
        }
        let mut end = at;
        if bytes[end] == b'-' {
            end += 1;
        }
        if digit(end) {
            while digit(end) {
                end += 1;
            }
            if end < bytes.len() && bytes[end] == b'.' {
                end += 1;
            }
            while digit(end) {
                end += 1;
            }
            found.push(&path[at..end]);
            at = end;
        } else if end < bytes.len() && bytes[end] == b'.' && digit(end + 1) {
            end += 1;
            while digit(end) {
                end += 1;
            }
            found.push(&path[at..end]);
            at = end;
        } else {
            // no match here: findall moves on one character (a whole one, for text past ASCII)
            at += path[at..].chars().next().map_or(1, char::len_utf8);
        }
    }
    found
}

fn arguments(upper: char) -> usize {
    match upper {
        'M' | 'L' | 'T' => 2,
        'H' | 'V' => 1,
        'Q' => 4,
        _ => 0,
    }
}

/// One subpath's points.
pub type Points = Vec<(f64, f64)>;

/// `path_points(path, steps)`: an SVG path of M, L, H, V, Q, T and Z, flattened into subpaths of points.
pub fn path_points(path: &str, steps: i64) -> Py<Vec<Points>> {
    let tokens = tokens(path);
    let mut subpaths = Vec::new();
    let mut points: Points = Vec::new();
    let (mut x, mut y, mut start_x, mut start_y) = (0.0f64, 0.0f64, 0.0f64, 0.0f64);
    let mut control: Option<(f64, f64)> = None;
    let mut at = 0;
    let mut command: Option<char> = None;
    while at < tokens.len() {
        let first = tokens[at].chars().next().unwrap_or('0');
        if first.is_ascii_alphabetic() {
            command = Some(first);
            at += 1;
            if first == 'Z' || first == 'z' {
                points.push((start_x, start_y));
                (x, y) = (start_x, start_y);
                control = None;
                continue;
            }
        }
        let now = command.ok_or("AttributeError")?;
        let (upper, relative) = (now.to_ascii_uppercase(), now.is_ascii_lowercase());
        let count = arguments(upper);
        let mut values = Vec::new();
        for token in tokens.iter().skip(at).take(count) {
            values.push(token.parse::<f64>().map_err(|_| "ValueError")?);
        }
        at += count;
        let value = |index: usize| values.get(index).copied().ok_or("IndexError");
        let (base_x, base_y) = if relative { (x, y) } else { (0.0, 0.0) };
        match upper {
            'M' => {
                if !points.is_empty() {
                    subpaths.push(std::mem::take(&mut points));
                }
                (x, y) = (base_x + value(0)?, base_y + value(1)?);
                (start_x, start_y) = (x, y);
                points = vec![(x, y)];
                command = Some(if relative { 'l' } else { 'L' });
                control = None;
            }
            'L' | 'H' | 'V' => {
                if upper == 'H' {
                    x = base_x + value(0)?;
                } else if upper == 'V' {
                    y = base_y + value(0)?;
                } else {
                    (x, y) = (base_x + value(0)?, base_y + value(1)?);
                }
                points.push((x, y));
                control = None;
            }
            _ => {
                let (cx, cy, end_x, end_y) = if upper == 'Q' {
                    (
                        base_x + value(0)?,
                        base_y + value(1)?,
                        base_x + value(2)?,
                        base_y + value(3)?,
                    )
                } else {
                    let (cx, cy) = match control {
                        Some((px, py)) => (2.0 * x - px, 2.0 * y - py),
                        None => (x, y),
                    };
                    (cx, cy, base_x + value(0)?, base_y + value(1)?)
                };
                for step in 1..=steps {
                    let t = step as f64 / steps as f64;
                    let s = 1.0 - t;
                    points.push((
                        s.powf(2.0) * x + 2.0 * s * t * cx + t * t * end_x,
                        s.powf(2.0) * y + 2.0 * s * t * cy + t * t * end_y,
                    ));
                }
                (x, y, control) = (end_x, end_y, Some((cx, cy)));
            }
        }
    }
    if !points.is_empty() {
        subpaths.push(points);
    }
    Ok(subpaths)
}

fn rotated(points: &[(f64, f64)], degrees: f64, px: f64, py: f64) -> Points {
    let radians = degrees.to_radians();
    let (c, s) = (radians.cos(), radians.sin());
    points
        .iter()
        .map(|(x, y)| {
            (
                px + (x - px) * c - (y - py) * s,
                py + (x - px) * s + (y - py) * c,
            )
        })
        .collect()
}

/// `_box(x, y, w, h)`: four corners, kept as the numbers they are (an int and an int is an int).
fn boxed(x: Num, y: Num, w: Num, h: Num) -> Vec<(Num, Num)> {
    vec![
        (x, y),
        (x.plus(w), y),
        (x.plus(w), y.plus(h)),
        (x, y.plus(h)),
    ]
}

fn floats(points: &[(Num, Num)]) -> Points {
    points.iter().map(|(x, y)| (x.f(), y.f())).collect()
}

fn nums(points: &[(f64, f64)]) -> Vec<(Num, Num)> {
    points
        .iter()
        .map(|(x, y)| (Num::F(*x), Num::F(*y)))
        .collect()
}

// ------------------------------------------------------------------ the icon's mark, in the icon's 32 by 32

/// One shape of a look's mark (`MARKS`).
#[derive(Clone, Debug, PartialEq)]
pub enum MarkShape {
    Poly(Vec<(Num, Num)>, &'static str),
    Circle(f64, f64, f64, &'static str),
    Line(f64, f64, f64, f64, f64, &'static str),
}

fn i(value: i64) -> Num {
    Num::I(value)
}

fn f(value: f64) -> Num {
    Num::F(value)
}

/// `MARKS[look]`.
pub fn marks(look: &str) -> Py<Vec<MarkShape>> {
    Ok(match look {
        "birthday" => vec![
            MarkShape::Poly(
                nums(&rotated(
                    &floats(&boxed(i(21), i(3), f(3.4), i(6))),
                    25.0,
                    22.0,
                    6.0,
                )),
                "#FFD76A",
            ),
            MarkShape::Circle(27.0, 9.5, 1.7, "#FFFFFF"),
            MarkShape::Poly(
                nums(&rotated(
                    &floats(&boxed(i(25), f(2.5), i(3), i(5))),
                    -30.0,
                    26.0,
                    5.0,
                )),
                "#FFB3C0",
            ),
        ],
        "new_year" => {
            let star = path_points("M25.5 2l1 3.5 3.5 1-3.5 1-1 3.5-1-3.5-3.5-1 3.5-1z", 1)?;
            vec![MarkShape::Poly(nums(&star[0]), "#FFE9A8")]
        }
        "christmas" => vec![
            MarkShape::Line(25.5, 2.5, 25.5, 10.5, 1.1, "#FFFFFF"),
            MarkShape::Line(21.8, 4.5, 29.2, 8.5, 1.1, "#FFFFFF"),
            MarkShape::Line(21.8, 8.5, 29.2, 4.5, 1.1, "#FFFFFF"),
        ],
        "seollal" => ["#F2C230", "#3FA86B", "#3B6FC9", "#E88BB0"]
            .iter()
            .enumerate()
            .map(|(index, colour)| {
                MarkShape::Poly(
                    boxed(i(2), f(23.5 + index as f64 * 1.5), i(28), f(1.5)),
                    colour,
                )
            })
            .collect(),
        "chuseok" => vec![
            MarkShape::Circle(25.5, 6.5, 4.0, "#F6E7B4"),
            MarkShape::Circle(24.2, 5.6, 0.8, "#E2CF96"),
        ],
        _ => return Err("KeyError"),
    })
}

fn inside_polygon(points: &[(Num, Num)], x: f64, y: f64) -> bool {
    let mut inside = false;
    let count = points.len();
    for index in 0..count {
        let (x1, y1) = (points[index].0.f(), points[index].1.f());
        let previous = points[(index + count - 1) % count];
        let (x2, y2) = (previous.0.f(), previous.1.f());
        if (y1 > y) != (y2 > y) && x < x1 + (y - y1) * (x2 - x1) / (y2 - y1) {
            inside = !inside;
        }
    }
    inside
}

fn on_line(x: f64, y: f64, line: (f64, f64, f64, f64), width: f64) -> bool {
    let (x1, y1, x2, y2) = line;
    let (dx, dy) = (x2 - x1, y2 - y1);
    let t = pyfmt::max(
        0.0,
        pyfmt::min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)),
    );
    (x - x1 - t * dx).powf(2.0) + (y - y1 - t * dy).powf(2.0) <= width * width / 4.0
}

/// `mark_colour(look, x, y)`: the (red, green, blue) of `look`'s mark at (x, y) in the icon's 32 by 32, or None.
pub fn mark_colour(look: &str, x: f64, y: f64) -> Py<Option<[i64; 3]>> {
    mark_colour_of(&marks(look)?, x, y)
}

/// `mark_colour` over a look's shapes already made.
pub fn mark_colour_of(shapes: &[MarkShape], x: f64, y: f64) -> Py<Option<[i64; 3]>> {
    let mut found = None;
    for shape in shapes {
        let (hit, colour) = match shape {
            MarkShape::Poly(points, colour) => (inside_polygon(points, x, y), colour),
            MarkShape::Circle(cx, cy, radius, colour) => (
                (x - cx).powf(2.0) + (y - cy).powf(2.0) <= radius.powf(2.0),
                colour,
            ),
            MarkShape::Line(x1, y1, x2, y2, width, colour) => {
                (on_line(x, y, (*x1, *y1, *x2, *y2), *width), colour)
            }
        };
        if hit {
            found = Some(*colour);
        }
    }
    found.map(rgb).transpose()
}

// ------------------------------------------------------------------ the scene, in its 190 by 66

/// One element of a scene (`[kind, numbers, colour, opacity, motion, motion's numbers]`).
#[derive(Clone, Debug, PartialEq)]
pub struct Element {
    pub kind: String,
    pub numbers: Vec<Num>,
    pub colour: String,
    pub opacity: Num,
    pub motion: String,
    pub values: Vec<Num>,
}

fn element(
    kind: &str,
    numbers: Vec<Num>,
    colour: &str,
    opacity: Num,
    motion: &str,
    values: Vec<Num>,
) -> Element {
    Element {
        kind: kind.to_owned(),
        numbers,
        colour: colour.to_owned(),
        opacity,
        motion: motion.to_owned(),
        values,
    }
}

/// `_Seeded`: the same numbers every time.
struct Seeded(u64);

impl Seeded {
    fn next(&mut self, low: f64, high: f64) -> f64 {
        self.0 = (self.0 * 1103515245 + 12345) & 0x7FFF_FFFF;
        low + (high - low) * self.0 as f64 / 2147483647.0
    }
}

fn flat(points: &[(Num, Num)]) -> Vec<Num> {
    points
        .iter()
        .flat_map(|(x, y)| [x.round_to(3), y.round_to(3)])
        .collect()
}

fn flat_f(points: &[(f64, f64)]) -> Vec<Num> {
    flat(&nums(points))
}

fn round3(x: f64) -> Num {
    Num::F(pyfmt::round_to(x, 3))
}

fn star(x: f64, y: f64, size: f64, colour: &str, duration: f64, delay: f64) -> Element {
    let w = size * 0.24;
    let points = [
        (x, y - size),
        (x + w, y - w),
        (x + size, y),
        (x + w, y + w),
        (x, y + size),
        (x - w, y + w),
        (x - size, y),
        (x - w, y - w),
    ];
    element(
        "poly",
        flat_f(&points),
        colour,
        f(1.0),
        "twinkle",
        vec![round3(duration), round3(delay)],
    )
}

type Range = (f64, f64);

fn stars(
    seeded: &mut Seeded,
    count: usize,
    xs: Range,
    ys: Range,
    sizes: Range,
    colour: &str,
) -> Vec<Element> {
    let mut made = Vec::new();
    for _ in 0..count {
        let x = seeded.next(xs.0, xs.1);
        let y = seeded.next(ys.0, ys.1);
        let size = seeded.next(sizes.0, sizes.1);
        let duration = seeded.next(2.0, 4.0);
        let delay = seeded.next(0.0, 2.0);
        made.push(star(x, y, size, colour, duration, delay));
    }
    made
}

fn first_subpath(path: &str) -> Points {
    path_points(path, 8)
        .expect("the scenes' own paths read")
        .remove(0)
}

fn still(path: &str, colour: &str) -> Element {
    element(
        "poly",
        flat_f(&first_subpath(path)),
        colour,
        f(1.0),
        "",
        Vec::new(),
    )
}

fn circle(cx: Num, cy: Num, radius: Num, colour: &str) -> Element {
    element(
        "circle",
        vec![cx, cy, radius],
        colour,
        f(1.0),
        "",
        Vec::new(),
    )
}

fn rounded(numbers: [Num; 5], colour: &str) -> Element {
    element("round", numbers.to_vec(), colour, f(1.0), "", Vec::new())
}

fn tree(x: i64, height: i64, colour: &str) -> Element {
    let (x, h) = (x as f64, height as f64);
    let points = [
        (i(x as i64), f(66.0 - h)),
        (f(x + h * 0.42), f(66.0)),
        (f(x - h * 0.42), f(66.0)),
    ];
    element("poly", flat(&points), colour, f(1.0), "", Vec::new())
}

fn colours(table: &'static crate::data::D) -> Vec<&'static str> {
    table.strs().collect()
}

fn birthday() -> Vec<Element> {
    let mut seeded = Seeded(906);
    let confetti = colours(&CONFETTI_COLOURS);
    let mut parts = Vec::new();
    for index in 0..16 {
        let x = seeded.next(50.0, 186.0);
        let width = seeded.next(3.0, 5.0);
        let height = seeded.next(5.0, 8.0);
        let duration = seeded.next(3.2, 6.0);
        let delay = seeded.next(-6.0, 0.0);
        let corners = boxed(f(x), f(-4.0), f(width), f(height));
        parts.push(element(
            "poly",
            flat(&corners),
            confetti[index % 5],
            f(1.0),
            "fall",
            vec![round3(duration), round3(delay), f(320.0)],
        ));
    }
    parts.push(rounded([i(142), i(42), i(38), i(20), i(4)], "#FFFFFF"));
    parts.push(still(
        "M142 48q4.7 7 9.5 0t9.5 0 9.5 0 9.5 0v-3q0-3-3-3h-32q-3 0-3 3z",
        "#F4A7B5",
    ));
    parts.push(rounded([f(159.5), i(30), i(3), i(12), i(1)], "#5BB8C4"));
    parts.push(element(
        "ellipse",
        vec![f(161.0), f(26.0), f(2.6), f(4.4)],
        "#F6B73C",
        f(1.0),
        "flame",
        vec![f(1.1), f(30.4)],
    ));
    parts
}

fn new_year() -> Vec<Element> {
    let mut parts = vec![
        element(
            "glow",
            vec![i(150), i(72), i(62), f(0.45)],
            "#FFC766",
            f(1.0),
            "breathe",
            vec![f(4.0), f(0.34), f(0.3)],
        ),
        circle(i(150), i(72), i(28), "#FAC65A"),
        still("M60 66q24-14 48-5t44-5 44 4v8z", "#141B45"),
    ];
    parts.extend(stars(
        &mut Seeded(101),
        9,
        (58.0, 186.0),
        (7.0, 36.0),
        (2.5, 5.2),
        "#FFE9A8",
    ));
    parts
}

fn christmas() -> Vec<Element> {
    let mut seeded = Seeded(1225);
    let mut parts = vec![
        tree(132, 34, "#1F6B4A"),
        tree(172, 28, "#1F6B4A"),
        tree(152, 48, "#2B8660"),
        star(152.0, 16.0, 4.6, "#FFD76A", 3.0, 0.5),
    ];
    for _ in 0..22 {
        let x = seeded.next(50.0, 190.0);
        let radius = seeded.next(0.9, 2.0);
        let duration = seeded.next(4.0, 8.0);
        let delay = seeded.next(-8.0, 0.0);
        parts.push(element(
            "circle",
            vec![round3(x), f(-4.0), round3(radius)],
            "#FFFFFF",
            f(1.0),
            "fall",
            vec![round3(duration), round3(delay), f(0.0)],
        ));
    }
    parts
}

const STRIPES: [&str; 5] = ["#D9463E", "#F2C230", "#3FA86B", "#3B6FC9", "#E88BB0"];

fn seollal() -> Vec<Element> {
    let sway = vec![f(3.4), f(149.0), f(21.0)];
    let mut parts: Vec<Element> = STRIPES
        .iter()
        .enumerate()
        .map(|(index, colour)| rounded([i(0), f(index as f64 * 3.4), i(190), f(3.4), i(0)], colour))
        .collect();
    let stroke = |width: f64, path: &str| {
        let mut numbers = vec![f(width)];
        numbers.extend(flat_f(&first_subpath(path)));
        numbers
    };
    parts.push(element(
        "stroke",
        stroke(1.4, "M60 42q4-6 11-3 5-6 12-1 6-2 8 4z"),
        "#E2C9A0",
        f(1.0),
        "drift",
        vec![f(7.0)],
    ));
    parts.push(element(
        "poly",
        flat_f(&first_subpath(
            "M138 26q-13 12-11 24 2 12 22 12t22-12q2-12-11-24z",
        )),
        "#C93B3B",
        f(1.0),
        "sway",
        sway.clone(),
    ));
    parts.push(element(
        "poly",
        flat_f(&first_subpath("M139 26q10 5 20 0l2-5q-12-4-24 0z")),
        "#E25B4F",
        f(1.0),
        "sway",
        sway.clone(),
    ));
    parts.push(element(
        "poly",
        flat(&boxed(i(138), f(24.5), i(22), f(3.6))),
        "#F2C230",
        f(1.0),
        "sway",
        sway.clone(),
    ));
    parts.push(element(
        "circle",
        vec![f(149.0), f(26.0), f(3.2)],
        "#F6D76B",
        f(1.0),
        "sway",
        sway.clone(),
    ));
    parts.push(element(
        "ring",
        vec![f(149.0), f(45.0), f(8.5), f(1.5)],
        "#F2C230",
        f(1.0),
        "sway",
        sway.clone(),
    ));
    parts.push(element(
        "stroke",
        stroke(1.3, "M149 39v12"),
        "#F2C230",
        f(1.0),
        "sway",
        sway.clone(),
    ));
    parts.push(element(
        "stroke",
        stroke(1.3, "M143 45h12"),
        "#F2C230",
        f(1.0),
        "sway",
        sway,
    ));
    parts
}

fn chuseok() -> Vec<Element> {
    let cloud = |x: i64, y: i64, duration: f64| {
        vec![
            element(
                "round",
                vec![i(x), i(y), i(46), i(7), f(3.5)],
                "#3A3F86",
                f(1.0),
                "drift",
                vec![f(duration)],
            ),
            element(
                "round",
                vec![i(x + 10), i(y - 5), i(24), i(8), i(4)],
                "#3A3F86",
                f(1.0),
                "drift",
                vec![f(duration)],
            ),
        ]
    };
    let mut parts = vec![
        element(
            "glow",
            vec![i(146), i(30), i(43), f(0.47)],
            "#FFEBB8",
            f(1.0),
            "breathe",
            vec![f(4.5), f(0.3), f(0.3)],
        ),
        circle(i(146), i(30), i(20), "#F6E7B4"),
        circle(i(139), i(25), f(3.6), "#E6D39B"),
        circle(i(152), i(35), f(4.6), "#E6D39B"),
        circle(i(151), i(22), i(2), "#E6D39B"),
    ];
    parts.extend(cloud(100, 50, 8.0));
    parts.extend(cloud(146, 56, 6.0));
    parts.extend(stars(
        &mut Seeded(815),
        7,
        (60.0, 120.0),
        (8.0, 38.0),
        (1.8, 3.2),
        "#FFF4D0",
    ));
    parts
}

fn kept(
    look: &str,
    cells: &'static [OnceLock<Vec<Element>>; 5],
    make: fn(&str) -> Vec<Element>,
) -> Py<&'static [Element]> {
    let index = looks()
        .iter()
        .position(|each| *each == look)
        .ok_or("KeyError")?;
    Ok(cells[index].get_or_init(|| make(look)))
}

static SCENES: [OnceLock<Vec<Element>>; 5] = [const { OnceLock::new() }; 5];
static SPECKS: [OnceLock<Vec<Element>>; 5] = [const { OnceLock::new() }; 5];

fn make_scene(look: &str) -> Vec<Element> {
    match look {
        "birthday" => birthday(),
        "new_year" => new_year(),
        "christmas" => christmas(),
        "seollal" => seollal(),
        _ => chuseok(),
    }
}

/// `scene_elements(look)`: `look`'s scene as the list every surface draws from.
pub fn scene_elements(look: &str) -> Py<&'static [Element]> {
    kept(look, &SCENES, make_scene)
}

/// `mark_text(look)`: the icon's mark as scene_text's lines, for the window (Brand.DayMark).
pub fn mark_text(look: &str) -> Py<String> {
    let mut lines = Vec::new();
    for shape in marks(look)? {
        lines.push(match shape {
            MarkShape::Poly(points, colour) => {
                let numbers: Vec<String> = flat(&points)
                    .iter()
                    .map(|value| pyfmt::g(value.f()))
                    .collect();
                format!("poly;{};{colour};1;;", numbers.join(" "))
            }
            MarkShape::Circle(cx, cy, radius, colour) => {
                format!(
                    "circle;{} {} {};{colour};1;;",
                    pyfmt::g(cx),
                    pyfmt::g(cy),
                    pyfmt::g(radius)
                )
            }
            MarkShape::Line(x1, y1, x2, y2, width, colour) => format!(
                "stroke;{} {} {} {} {};{colour};1;;",
                pyfmt::g(width),
                pyfmt::g(x1),
                pyfmt::g(y1),
                pyfmt::g(x2),
                pyfmt::g(y2)
            ),
        });
    }
    Ok(lines.join("\n"))
}

fn joined(values: &[Num]) -> String {
    values
        .iter()
        .map(|value| pyfmt::g(value.f()))
        .collect::<Vec<_>>()
        .join(" ")
}

fn as_text(elements: &[Element]) -> String {
    elements
        .iter()
        .map(|each| {
            [
                each.kind.clone(),
                joined(&each.numbers),
                each.colour.clone(),
                pyfmt::g(each.opacity.f()),
                each.motion.clone(),
                joined(&each.values),
            ]
            .join(";")
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// `scene_text(look)`: the scene as one line per element, for the window (Brand.DayScene).
pub fn scene_text(look: &str) -> Py<String> {
    Ok(as_text(scene_elements(look)?))
}

// ------------------------------------------------------------------ the day spread wide

type Maker = fn(f64, f64, &str, Num, Vec<Num>) -> Element;

#[allow(clippy::too_many_arguments)]
fn specks_falling(
    seeded: &mut Seeded,
    count: usize,
    sizes: Range,
    durations: Range,
    colours: &[&str],
    opacity: f64,
    make: Maker,
) -> Vec<Element> {
    let band = SPECK_BAND.f();
    let mut made = Vec::new();
    for index in 0..count {
        let x = seeded.next(4.0, band - 4.0);
        let size = seeded.next(sizes.0, sizes.1);
        let duration = seeded.next(durations.0, durations.1);
        let delay = seeded.next(-duration, 0.0);
        made.push(make(
            pyfmt::round_to(x, 3),
            pyfmt::round_to(size, 3),
            colours[index % colours.len()],
            f(opacity),
            vec![round3(duration), round3(delay)],
        ));
    }
    made
}

fn confetti(x: f64, size: f64, colour: &str, opacity: Num, mut timing: Vec<Num>) -> Element {
    timing.push(f(320.0));
    element(
        "poly",
        flat(&boxed(f(x), f(-4.0), f(size * 0.62), f(size))),
        colour,
        opacity,
        "fall",
        timing,
    )
}

fn flake(x: f64, size: f64, colour: &str, opacity: Num, mut timing: Vec<Num>) -> Element {
    timing.push(f(0.0));
    element(
        "circle",
        vec![f(x), f(-4.0), f(size)],
        colour,
        opacity,
        "fall",
        timing,
    )
}

fn make_specks(look: &str) -> Vec<Element> {
    let band = SPECK_BAND.f();
    match look {
        "birthday" => specks_falling(
            &mut Seeded(9061),
            14,
            (4.2, 6.8),
            (4.0, 7.5),
            &colours(&CONFETTI_COLOURS),
            0.9,
            confetti,
        ),
        "new_year" => stars(
            &mut Seeded(1011),
            12,
            (4.0, band - 4.0),
            (6.0, 60.0),
            (1.8, 3.6),
            "#FFE9A8",
        ),
        "christmas" => specks_falling(
            &mut Seeded(12251),
            18,
            (0.8, 1.8),
            (5.0, 9.0),
            &["#FFFFFF"],
            0.9,
            flake,
        ),
        "seollal" => {
            let mut parts: Vec<Element> = STRIPES
                .iter()
                .enumerate()
                .map(|(index, colour)| {
                    rounded(
                        [i(0), f(index as f64 * 3.4), SPECK_BAND.n(), f(3.4), i(0)],
                        colour,
                    )
                })
                .collect();
            parts.extend(specks_falling(
                &mut Seeded(2027),
                10,
                (1.5, 2.4),
                (6.0, 10.0),
                &["#F2C230", "#E25B4F"],
                0.9,
                flake,
            ));
            parts
        }
        _ => stars(
            &mut Seeded(8151),
            10,
            (4.0, band - 4.0),
            (6.0, 60.0),
            (1.4, 2.8),
            "#FFF4D0",
        ),
    }
}

/// `speck_elements(look)`: `look`'s specks in one band SPECK_BAND by 66.
pub fn speck_elements(look: &str) -> Py<&'static [Element]> {
    kept(look, &SPECKS, make_specks)
}

fn centre(kind: &str, numbers: &[Num]) -> Py<(Num, Num)> {
    if kind == "poly" {
        let xs: Vec<Num> = numbers.iter().step_by(2).copied().collect();
        let ys: Vec<Num> = numbers.iter().skip(1).step_by(2).copied().collect();
        let low = |values: &[Num]| values.iter().copied().reduce(Num::min).ok_or("ValueError");
        let high = |values: &[Num]| values.iter().copied().reduce(Num::max).ok_or("ValueError");
        return Ok((
            Num::F(low(&xs)?.plus(high(&xs)?).f() / 2.0),
            Num::F(low(&ys)?.plus(high(&ys)?).f() / 2.0),
        ));
    }
    Ok((
        *numbers.first().ok_or("IndexError")?,
        *numbers.get(1).ok_or("IndexError")?,
    ))
}

/// How far along its band an element can ever reach, (from, to) (`_reach`).
fn reach(element: &Element) -> Py<(Num, Num)> {
    let numbers = &element.numbers;
    let at = |index: usize| numbers.get(index).copied().ok_or("IndexError");
    if element.kind == "round" {
        return Ok((at(0)?, at(0)?.plus(at(2)?)));
    }
    let (centre_x, far) = if element.kind == "poly" {
        let (centre_x, centre_y) = centre(&element.kind, numbers)?;
        let mut far: Option<f64> = None;
        for pair in numbers.as_chunks::<2>().0 {
            let distance = pyfmt::hypot(pair[0].f() - centre_x.f(), pair[1].f() - centre_y.f());
            far = Some(far.map_or(distance, |known| pyfmt::max(known, distance)));
        }
        (centre_x, Num::F(far.ok_or("ValueError")?))
    } else {
        (at(0)?, at(2)?)
    };
    let far = far.f() * 1.1;
    Ok((Num::F(centre_x.f() - far), Num::F(centre_x.f() + far)))
}

static REACHES: [OnceLock<Vec<(Num, Num)>>; 5] = [const { OnceLock::new() }; 5];

/// `speck_reach(look)`: for each of `look`'s specks, how far along the band it can ever reach.
pub fn speck_reach(look: &str) -> Py<&'static [(Num, Num)]> {
    let specks = speck_elements(look)?;
    let index = looks()
        .iter()
        .position(|each| *each == look)
        .ok_or("KeyError")?;
    if let Some(known) = REACHES[index].get() {
        return Ok(known);
    }
    let made = specks.iter().map(reach).collect::<Py<Vec<_>>>()?;
    Ok(REACHES[index].get_or_init(|| made))
}

/// One shape of a frame: (kind, numbers, colour, opacity).
#[derive(Clone, Debug, PartialEq)]
pub struct Shape {
    pub kind: String,
    pub numbers: Vec<Num>,
    pub colour: String,
    pub opacity: Num,
}

/// `speck_frame(look, milliseconds, within)`: `look`'s specks `milliseconds` in, in their band.
pub fn speck_frame(look: &str, milliseconds: f64, within: Option<(f64, f64)>) -> Py<Vec<Shape>> {
    let seconds = milliseconds / 1000.0;
    let specks = speck_elements(look)?;
    let Some((least, most)) = within else {
        return specks
            .iter()
            .map(|each| element_at(each, seconds))
            .collect();
    };
    let mut shown = Vec::new();
    for (each, (start, end)) in specks.iter().zip(speck_reach(look)?) {
        if end.f() < least || start.f() > most {
            continue;
        }
        let shape = element_at(each, seconds)?;
        let (top, bottom) = height(&shape)?;
        if bottom.f() >= 0.0 && top.f() <= SCENE_HEIGHT.f() {
            shown.push(shape);
        }
    }
    Ok(shown)
}

fn height(shape: &Shape) -> Py<(Num, Num)> {
    let numbers = &shape.numbers;
    let at = |index: usize| numbers.get(index).copied().ok_or("IndexError");
    if shape.kind == "poly" {
        let ys: Vec<Num> = numbers.iter().skip(1).step_by(2).copied().collect();
        let low = ys.iter().copied().reduce(Num::min).ok_or("ValueError")?;
        let high = ys.iter().copied().reduce(Num::max).ok_or("ValueError")?;
        return Ok((low, high));
    }
    if shape.kind == "round" {
        return Ok((at(1)?, at(1)?.plus(at(3)?)));
    }
    Ok((at(1)?.minus(at(2)?), at(1)?.plus(at(2)?)))
}

/// The day spread wide over a card's header (`day_band`).
#[derive(Clone, Debug, PartialEq)]
pub struct Band {
    pub scene: &'static str,
    pub rect: [Num; 4],
    pub unit: f64,
    pub scene_shown: bool,
    pub fade: (Num, Num),
}

fn floordiv(a: Num, b: Num) -> Py<Num> {
    match (a, b) {
        (_, Num::I(0)) => Err("ZeroDivisionError"),
        (Num::I(x), Num::I(y)) => Ok(Num::I(
            x.div_euclid(y) - if y < 0 && x.rem_euclid(y) != 0 { 1 } else { 0 },
        )),
        _ if b.f() == 0.0 => Err("ZeroDivisionError"),
        _ => Ok(Num::F(pyfmt::floordiv(a.f(), b.f()))),
    }
}

fn int_of(value: Num) -> Py<Num> {
    match value {
        Num::I(_) => Ok(value),
        Num::F(x) if x.is_nan() => Err("ValueError"),
        Num::F(x) if x.is_infinite() => Err("OverflowError"),
        Num::F(x) => Ok(Num::I(x.trunc() as i64)),
    }
}

/// `day_band(look, px, band, words_end)`: the day over a card's header, or None where there is no room for it.
pub fn day_band(
    look: &str,
    px: &dyn Fn(Num) -> Num,
    band: [Num; 4],
    words_end: Num,
) -> Py<Option<Band>> {
    let [left, top, right, bottom] = band;
    let left = left.max(words_end.plus(px(WIDE.at("gap").n())));
    let fade = px(WIDE.at("fade").n());
    if right
        .minus(left)
        .lt(floordiv(fade, Num::I(2))?.plus(px(Num::I(24))))
        || bottom.le(top)
    {
        return Ok(None);
    }
    let unit = bottom.minus(top).over(SCENE_HEIGHT.n());
    let focal = SCENE_WIDTH
        .n()
        .minus(SCENE_FOCUS.find(look).ok_or("KeyError")?.n());
    let solid = left.plus(px(Num::I(2)));
    let room = int_of(right.minus(solid).minus(focal.times(Num::F(unit))))?;
    let scene = room.ge(px(Num::I(28)));
    let other = if scene {
        room
    } else {
        right.minus(solid).minus(px(Num::I(24)))
    };
    let far = solid.plus(px(Num::I(2)).max(fade.min(other)));
    let name = DAY_LOOKS
        .keys()
        .find(|each| *each == look)
        .ok_or("KeyError")?;
    Ok(Some(Band {
        scene: name,
        rect: [left, top, right, bottom],
        unit,
        scene_shown: scene,
        fade: (solid, far),
    }))
}

/// `speck_text(look)`: the specks as scene_text's lines, for the window (Brand.DaySpecks).
pub fn speck_text(look: &str) -> Py<String> {
    Ok(as_text(speck_elements(look)?))
}

fn wave(seconds: f64, duration: f64, delay: f64) -> f64 {
    (1.0 - (2.0 * PI * pyfmt::rem((seconds - delay) / duration, 1.0)).cos()) / 2.0
}

fn drift(seconds: f64, duration: f64) -> f64 {
    let turn = seconds / duration;
    let mut part = pyfmt::rem(turn, 1.0);
    if turn.trunc() % 2.0 != 0.0 {
        part = 1.0 - part;
    }
    -10.0 + 24.0 * (1.0 - (PI * part).cos()) / 2.0
}

fn placed(kind: &str, numbers: &[Num], step: &dyn Fn(Num, Num) -> (Num, Num)) -> Py<Vec<Num>> {
    if kind == "poly" || kind == "stroke" {
        let start = usize::from(kind == "stroke");
        let mut out: Vec<Num> = numbers.iter().take(start).copied().collect();
        let mut at = start;
        while at < numbers.len() {
            let x = numbers[at];
            let y = *numbers.get(at + 1).ok_or("IndexError")?;
            let (nx, ny) = step(x, y);
            out.push(nx);
            out.push(ny);
            at += 2;
        }
        return Ok(out);
    }
    let (x, y) = (
        *numbers.first().ok_or("IndexError")?,
        *numbers.get(1).ok_or("IndexError")?,
    );
    let (nx, ny) = step(x, y);
    let mut out = vec![nx, ny];
    out.extend(numbers.iter().skip(2).copied());
    Ok(out)
}

/// `element_at(element, seconds)`: one element `seconds` in, as (kind, numbers, colour, opacity).
pub fn element_at(element: &Element, seconds: f64) -> Py<Shape> {
    let kind = element.kind.as_str();
    let mut numbers = element.numbers.clone();
    let mut opacity = element.opacity;
    let values = &element.values;
    let value = |index: usize| values.get(index).map(|each| each.f()).ok_or("IndexError");
    match element.motion.as_str() {
        "fall" => {
            let part = pyfmt::rem((seconds - value(1)?) / value(0)?, 1.0);
            let (centre_x, centre_y) = centre(kind, &numbers)?;
            let (cx, cy) = (centre_x.f(), centre_y.f());
            let dy = -14.0 + 96.0 * part;
            let radians = (value(2)? * part).to_radians();
            let (c, s) = (radians.cos(), radians.sin());
            numbers = placed(kind, &numbers, &|x, y| {
                let (x, y) = (x.f(), y.f());
                (
                    Num::F(cx + (x - cx) * c - (y - cy) * s),
                    Num::F(cy + dy + (x - cx) * s + (y - cy) * c),
                )
            })?;
        }
        "twinkle" => {
            let level = wave(seconds, value(0)?, value(1)?);
            let (centre_x, centre_y) = centre(kind, &numbers)?;
            let (cx, cy) = (centre_x.f(), centre_y.f());
            let size = 0.7 + 0.4 * level;
            numbers = placed(kind, &numbers, &|x, y| {
                (
                    Num::F(cx + (x.f() - cx) * size),
                    Num::F(cy + (y.f() - cy) * size),
                )
            })?;
            opacity = Num::F(0.25 + 0.75 * level);
        }
        "breathe" => {
            opacity = Num::F(value(1)? + value(2)? * wave(seconds, value(0)?, 0.0));
        }
        "drift" => {
            let dx = drift(seconds, value(0)?);
            // the point's y is kept as it is: an int stays an int
            numbers = placed(kind, &numbers, &|x, y| (Num::F(x.f() + dx), y))?;
        }
        "sway" => {
            let radians = (-5.0 + 10.0 * wave(seconds, value(0)?, 0.0)).to_radians();
            let (c, s) = (radians.cos(), radians.sin());
            let (px, py) = (value(1)?, value(2)?);
            numbers = placed(kind, &numbers, &|x, y| {
                let (x, y) = (x.f(), y.f());
                (
                    Num::F(px + (x - px) * c - (y - py) * s),
                    Num::F(py + (x - px) * s + (y - py) * c),
                )
            })?;
        }
        "flame" => {
            let tall = numbers.get(3).ok_or("IndexError")?.f()
                * (1.0 + 0.35 * wave(seconds, value(0)?, 0.0));
            numbers[1] = Num::F(value(1)? - tall);
            numbers[3] = Num::F(tall);
        }
        _ => {}
    }
    Ok(Shape {
        kind: element.kind.clone(),
        numbers,
        colour: element.colour.clone(),
        opacity,
    })
}

/// `scene_frame(look, milliseconds)`: `look`'s scene `milliseconds` in, as the shapes to draw in order.
pub fn scene_frame(look: &str, milliseconds: f64) -> Py<Vec<Shape>> {
    scene_elements(look)?
        .iter()
        .map(|each| element_at(each, milliseconds / 1000.0))
        .collect()
}

// ------------------------------------------------------------------ the seventh press

/// `PressRun`: presses one after another, `wanted` each within `gap_ms` of the last, say so once and start again.
#[derive(Clone, Debug, Default)]
pub struct PressRun {
    count: i64,
    last: Option<Num>,
}

impl PressRun {
    pub fn new() -> PressRun {
        PressRun::default()
    }

    pub fn press(&mut self, milliseconds: Num) -> bool {
        let gap = PRESSES.at("gap_ms").n();
        self.count = match self.last {
            Some(last) if milliseconds.minus(last).le(gap) => self.count + 1,
            _ => 1,
        };
        self.last = Some(milliseconds);
        if self.count < PRESSES.at("wanted").i() {
            return false;
        }
        self.count = 0;
        true
    }
}

/// One sweep frame (`sweep_at`): the arc covered, its opacity, and the two rings' (spread, opacity).
pub type Sweep = (f64, f64, [(f64, f64); 2]);

/// `sweep_at(milliseconds, ease)`.
pub fn sweep_at(milliseconds: Num, ease: &dyn Fn(f64) -> f64) -> Sweep {
    let number = |key: &str| SWEEP.at(key).n();
    let covered = ease(milliseconds.over(number("arc_ms")));
    let opacity = if milliseconds.le(number("arc_ms")) {
        1.0
    } else {
        1.0 - ease(
            milliseconds
                .minus(number("arc_ms"))
                .over(number("arc_fade_ms")),
        )
    };
    let mut rings = [(0.0, 0.0); 2];
    for (index, start) in ["first_ring_ms", "second_ring_ms"].iter().enumerate() {
        let since = milliseconds.minus(number(start));
        let spread = ease(since.over(number("ring_ms")));
        let shown = if since.lt(Num::I(0)) || since.ge(number("ring_ms")) {
            0.0
        } else {
            number("ring_opacity").f() * (1.0 - spread)
        };
        rings[index] = (spread, shown);
    }
    (covered, opacity, rings)
}
