//! `notice_card.py`: the notification card, the pure half - what it says, where it goes and how it moves.
//!
//! It is the popup's card: the same width, radius, shadow family, padding, type roles, chip and status light, laid out
//! like one of the popup's task cards. Its words (`view`), every rectangle it draws (`layout`, measured by the C#
//! renderer through [`CardHost::measure`](crate::seam::CardHost::measure)), its life on a clock (`CardMotion`), the
//! stack beside the notification area (`stack_positions`), the shadow it floats on over a wallpaper (`float_shadows`)
//! and its rounded edge (`corner_coverage`, `premultiply`) are here; the window that shows them is the C# host's (D1).

use std::sync::Mutex;

use car_brand::data::Num;
use car_brand::pyfmt::{self, round_int, round_to};
use car_brand::shape::{self, Profile};
use car_brand::tables_gen::{LAYOUT, RADII, SPACING, STATUS_DOT};
use car_brand::{days, ease, glow_extent, luminance, palette, shadows};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_words::l10n;

use crate::notifier::Notice;
use crate::popup::placement::{self, Rect};
use crate::popup::words::one_line;
use crate::popup::{FRAME_MS as POPUP_FRAME_MS, MARK, WIDTH as POPUP_WIDTH};
use crate::py::{self, object, str_of};

fn space(key: &str) -> i64 {
    SPACING.at(key).i()
}

pub const WIDTH: i64 = POPUP_WIDTH;
pub const MAX_CARDS: i64 = 3;
pub const FRAME_MS: i64 = 16;
pub const BREATH_FRAME_MS: i64 = POPUP_FRAME_MS;
pub const ENTRANCE_MS: f64 = 340.0;
pub const EXIT_MS: f64 = 220.0;
pub const SLIDE_MS: f64 = 280.0;
pub const SWAP_MS: f64 = 130.0;
pub const STACK_DELAY_MS: i64 = 120;
pub const HOLD_MS: f64 = 6000.0;
pub const HOVER_GRACE_MS: f64 = 1500.0;
pub const RISE: f64 = 20.0;
pub const SCALE_FROM: f64 = 0.98;
pub const ALPHA_SHARE: f64 = 0.35;
/// `DEPTH_START`: the shadow at the start of the entrance, as a fraction of the settled one.
pub const DEPTH_START: [(&str, f64); 3] = [("offset", 0.35), ("blur", 0.55), ("alpha", 0.30)];
pub const DEPTH_LEVELS: i64 = 6;
pub const FLOAT_SHADOW_INK: &str = "shadow_dark";
pub const FLOAT_SHADOW_THEME: &str = "dark";
pub const DARK_ENOUGH: f64 = 0.05;
pub const HEADER_KEY: &str = "tray.title";
/// v0.6.11: about the tallest a card is at the usual text size, in logical pixels.
pub const USUAL_HEIGHT: i64 = 240;
/// v0.6.16: the hold of a card that stays until it is clicked.
pub const UNTIL_CLICKED: f64 = f64::INFINITY;

/// `CARD_WIDTH`: the card itself, exactly the popup's card.
pub fn card_width() -> i64 {
    WIDTH - 2 * space("m")
}

// -------------------------------------------------------------------------------- words
/// `view(notice)`: what one card says, as plain values.
pub fn view(notice: &Notice) -> Map {
    let locale = if l10n::LOCALES.contains(&notice.locale.as_str()) {
        notice.locale.as_str()
    } else {
        l10n::DEFAULT
    };
    let product = l10n::text(HEADER_KEY, locale, &[])
        .filter(|text| !text.is_empty())
        .or_else(|| l10n::text(HEADER_KEY, l10n::DEFAULT, &[]))
        .unwrap_or_default();
    let actions: Vec<Value> = notice
        .actions
        .iter()
        .enumerate()
        .map(|(index, (label, uri))| {
            let text = str_of(uri);
            let head = text.split_once('?').map_or(text.as_str(), |(head, _)| head);
            object([
                ("label", label.clone()),
                ("uri", uri.clone()),
                ("primary", Value::Bool(head.ends_with(":open"))),
                (
                    "target",
                    Value::Array(vec![Value::from("action"), Value::from(index as i64)]),
                ),
            ])
        })
        .collect();
    let text = |value: &Option<String>| value.as_deref().map_or(Value::Null, Value::from);
    let mut vm = Map::new();
    let mut put = |key: &str, value: Value| {
        vm.insert(Str::from(key), value);
    };
    put("product", Value::from(product));
    put("status", Value::from(notice.status.as_str()));
    put("chip", text(&notice.chip));
    put(
        "chip_tone",
        Value::from(
            notice
                .chip_tone
                .as_deref()
                .filter(|tone| !tone.is_empty())
                .unwrap_or("waiting"),
        ),
    );
    put("title", Value::from(one_line(&notice.title, 120)));
    put("line", notice.line.clone());
    put("origin", Value::from(one_line(&notice.origin, 200)));
    put("actions", Value::Array(actions));
    put("click", Value::from(notice.click.as_str()));
    put("locale", Value::from(locale));
    put("scene", Value::Null);
    vm
}

fn at<'a>(vm: &'a Map, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    vm.get(key).unwrap_or(&NULL)
}

/// `texts(vm)`: every string a card with this view draws, for the privacy test.
pub fn texts(vm: &Map) -> Py<Vec<Value>> {
    let mut found = vec![
        at(vm, "product").clone(),
        at(vm, "title").clone(),
        at(vm, "line").clone(),
        at(vm, "origin").clone(),
    ];
    if pyval::truthy(at(vm, "chip")) {
        found.push(at(vm, "chip").clone());
    }
    for action in py::items(at(vm, "actions"))? {
        found.push(pyval::get(&action, "label")?.clone());
    }
    Ok(found.into_iter().filter(pyval::truthy).collect())
}

// ------------------------------------------------------------------------------- layout
/// The renderer's measure: (role, text, width, wrap) -> (width, height), device pixels.
pub type Measure<'a> = &'a dyn Fn(&str, &str, i64, bool) -> (i64, i64);

fn rect(values: [i64; 4]) -> Value {
    Value::Array(values.iter().map(|each| Value::from(*each)).collect())
}

/// `layout(vm, scale, measure)`: every rectangle the card draws, in device pixels, with the card at (0, 0); mirrored
/// right to left for a right-to-left locale.
pub fn layout(vm: &Map, scale: &Value, measure: Measure) -> Py<Value> {
    let factor = pyval::Num::of(scale).ok_or("TypeError")?.as_f64();
    let px = |value: f64| round_int(value * factor);
    let width = px(card_width() as f64);
    let pad = px(space("l") as f64);
    let (left, right) = (pad, width - pad);
    let inner = right - left;
    let mut items: Vec<Value> = Vec::new();
    let mut targets: Vec<Value> = Vec::new();
    let mut y = pad;
    let text_of = |value: &Value| str_of(value);
    let text = |items: &mut Vec<Value>,
                bounds: [i64; 4],
                role: &str,
                value: &Value,
                colour: &Value,
                wrap: bool,
                align: &str,
                target: &Value| {
        items.push(object([
            ("kind", Value::from("text")),
            ("rect", rect(bounds)),
            ("role", Value::from(role)),
            ("text", value.clone()),
            ("colour", colour.clone()),
            ("wrap", Value::Bool(wrap)),
            ("align", Value::from(align)),
            ("target", target.clone()),
        ]));
    };
    let product = at(vm, "product");
    let chip = at(vm, "chip");
    let mark = px(MARK as f64);
    let text_left = left + mark + px(space("s") as f64);
    let (_, product_h) = measure("label", &text_of(product), inner, false);
    let (mut chip_w, mut chip_h) = (0i64, 0i64);
    let chip_pad = px(LAYOUT.at("chip_pad_x").f());
    if pyval::truthy(chip) {
        let (chip_text_w, chip_text_h) = measure("chip", &text_of(chip), inner, false);
        let (product_w, _) = measure("label", &text_of(product), inner, false);
        let room = right - (text_left + product_w + px(space("m") as f64));
        chip_w = (chip_text_w + 2 * chip_pad)
            .min(room)
            .max((chip_text_w + 2 * chip_pad).min(inner.div_euclid(3)));
        chip_h = px(LAYOUT.at("chip_height").f()).max(chip_text_h);
    }
    let header_h = mark.max(product_h).max(chip_h);
    let dot = STATUS_DOT.at("popup").f();
    items.push(object([
        ("kind", Value::from("halo")),
        ("cx", Value::Float(left as f64 + mark as f64 / 2.0)),
        ("cy", Value::Float(y as f64 + header_h as f64 / 2.0)),
        ("state", at(vm, "status").clone()),
        ("radius", Value::Float(glow_extent(dot) * factor)),
    ]));
    let product_right = right
        - if chip_w != 0 {
            chip_w + px(space("s") as f64)
        } else {
            0
        };
    let top = y + (header_h - product_h).div_euclid(2);
    let none = Value::Null;
    text(
        &mut items,
        [text_left, top, product_right, top + product_h],
        "label",
        product,
        &Value::from("muted"),
        false,
        "left",
        &none,
    );
    if pyval::truthy(chip) {
        let chip_top = y + (header_h - chip_h).div_euclid(2);
        let bounds = [right - chip_w, chip_top, right, chip_top + chip_h];
        items.push(object([
            ("kind", Value::from("chip")),
            ("rect", rect(bounds)),
            ("tone", at(vm, "chip_tone").clone()),
        ]));
        text(
            &mut items,
            [
                bounds[0] + chip_pad,
                bounds[1],
                bounds[2] - chip_pad,
                bounds[3],
            ],
            "chip",
            chip,
            at(vm, "chip_tone"),
            false,
            "center",
            &none,
        );
    }
    y += header_h + px(space("s") as f64);
    let scene = at(vm, "scene");
    if pyval::truthy(scene) {
        let edge = 1.max(px(1.0));
        let (product_w, _) = measure("label", &text_of(product), inner, false);
        let look = pyval::text(scene).ok_or("KeyError")?;
        let px_num = |value: Num| Num::I(px(value.f()));
        let band = days::day_band(
            look,
            &px_num,
            [
                Num::I(edge),
                Num::I(edge),
                Num::I(width - edge),
                Num::I(y - px(2.0)),
            ],
            Num::I(text_left + product_w),
        )?;
        if let Some(band) = band {
            let num = |value: Num| match value {
                Num::I(int) => Value::from(int),
                Num::F(x) => Value::Float(x),
            };
            items.push(object([
                ("kind", Value::from("scene")),
                ("scene", Value::from(band.scene)),
                (
                    "rect",
                    Value::Array(band.rect.iter().map(|each| num(*each)).collect()),
                ),
                ("unit", Value::Float(band.unit)),
                ("scene_shown", Value::Bool(band.scene_shown)),
                (
                    "fade",
                    Value::Array(vec![num(band.fade.0), num(band.fade.1)]),
                ),
            ]));
        }
    }
    let tile_pad = px(space("m") as f64);
    let tile_top = y;
    let (x0, x1) = (left + tile_pad, right - tile_pad);
    let content = x1 - x0;
    let mut line_y = tile_top + tile_pad;
    let title = at(vm, "title");
    let (_, title_h) = measure("name", &text_of(title), content, false);
    text(
        &mut items,
        [x0, line_y, x1, line_y + title_h],
        "name",
        title,
        &Value::from("ink"),
        false,
        "left",
        &none,
    );
    line_y += title_h + px(space("xs") as f64);
    let line = at(vm, "line");
    if pyval::truthy(line) {
        let (_, line_h) = measure("body", &text_of(line), content, true);
        text(
            &mut items,
            [x0, line_y, x1, line_y + line_h],
            "body",
            line,
            &Value::from("ink"),
            true,
            "left",
            &none,
        );
        line_y += line_h + px(space("xs") as f64);
    }
    let origin = at(vm, "origin");
    if pyval::truthy(origin) {
        let (_, origin_h) = measure("small", &text_of(origin), content, true);
        text(
            &mut items,
            [x0, line_y, x1, line_y + origin_h],
            "small",
            origin,
            &Value::from("muted"),
            true,
            "left",
            &none,
        );
        line_y += origin_h;
    }
    let tile_bottom = line_y + tile_pad;
    items.push(object([
        ("kind", Value::from("panel")),
        ("rect", rect([left, tile_top, right, tile_bottom])),
    ]));
    y = tile_bottom;
    let actions = py::items(at(vm, "actions"))?;
    if !actions.is_empty() {
        y += px(space("m") as f64);
        let button_h = px(LAYOUT.at("button_height").f());
        let button_pad = px(space("m") as f64);
        let half = (inner - px(space("s") as f64)).div_euclid(2);
        let label_of = |action: &Value| -> Py<Value> { Ok(pyval::get(action, "label")?.clone()) };
        let mut widths = Vec::new();
        for action in &actions {
            widths.push(measure("button", &text_of(&label_of(action)?), inner, false).0);
        }
        let mut placed: Vec<([i64; 4], bool)> = Vec::new();
        let widest = widths.iter().copied().max().unwrap_or(0);
        if actions.len() == 1 {
            placed.push(([right - half, y, right, y + button_h], false));
            y += button_h;
        } else if actions.len() == 2 && widest + 2 * button_pad <= half {
            placed.push(([left, y, left + half, y + button_h], false));
            placed.push(([right - half, y, right, y + button_h], false));
            y += button_h;
        } else {
            for (index, action) in actions.iter().enumerate() {
                let label = text_of(&label_of(action)?);
                let (_, label_h) = measure("button", &label, inner - 2 * button_pad, true);
                let height = button_h.max(label_h + 2 * px(space("s") as f64));
                placed.push(([left, y, right, y + height], true));
                y += height
                    + if index < actions.len() - 1 {
                        px(space("s") as f64)
                    } else {
                        0
                    };
            }
        }
        for (action, (bounds, wrapped)) in actions.iter().zip(placed) {
            let target = pyval::get(action, "target")?.clone();
            let primary = pyval::get(action, "primary")?.clone();
            items.push(object([
                ("kind", Value::from("button")),
                ("rect", rect(bounds)),
                ("primary", primary.clone()),
                ("busy", Value::Bool(false)),
                ("target", target.clone()),
            ]));
            let label = label_of(action)?;
            let label_rect = if wrapped {
                let (_, label_h) = measure(
                    "button",
                    &text_of(&label),
                    bounds[2] - bounds[0] - 2 * button_pad,
                    true,
                );
                let top = bounds[1] + (bounds[3] - bounds[1] - label_h).div_euclid(2);
                [
                    bounds[0] + button_pad,
                    top,
                    bounds[2] - button_pad,
                    top + label_h,
                ]
            } else {
                [
                    bounds[0] + button_pad,
                    bounds[1],
                    bounds[2] - button_pad,
                    bounds[3],
                ]
            };
            let colour = if pyval::truthy(&primary) {
                "on_accent"
            } else {
                "ink"
            };
            text(
                &mut items,
                label_rect,
                "button",
                &label,
                &Value::from(colour),
                wrapped,
                "center",
                &target,
            );
            targets.push(Value::Array(vec![target, rect(bounds)]));
        }
    }
    y += pad;
    let card = [0, 0, width, y];
    items.insert(
        0,
        object([
            ("kind", Value::from("card")),
            ("rect", rect(card)),
            ("radius", Value::from(px(RADII.at("card").f()))),
            ("corner", Value::from("card")),
        ]),
    );
    let laid = object([
        (
            "size",
            Value::Array(vec![Value::from(width), Value::from(y)]),
        ),
        ("card", rect(card)),
        ("items", Value::Array(items)),
        ("targets", Value::Array(targets)),
        ("scale", scale.clone()),
    ]);
    let locale = pyval::text(at(vm, "locale")).unwrap_or("");
    if l10n::right_to_left(locale) {
        return mirror(&laid);
    }
    Ok(laid)
}

/// `popup.mirror(plan)`: the plan right to left - every rectangle across the canvas, every left-aligned line right.
pub fn mirror(plan: &Value) -> Py<Value> {
    let Value::Object(plan) = plan else {
        return Err("TypeError");
    };
    let size = py::items(plan.get("size").ok_or("KeyError")?)?;
    let width = size.first().cloned().ok_or("IndexError")?;
    let across = |bounds: &Value| -> Py<Value> {
        let parts = py::items(bounds)?;
        if parts.len() != 4 {
            return Err("ValueError");
        }
        let minus = |value: &Value| -> Py<Value> { subtract(&width, value) };
        Ok(Value::Array(vec![
            minus(&parts[2])?,
            parts[1].clone(),
            minus(&parts[0])?,
            parts[3].clone(),
        ]))
    };
    let mut items = Vec::new();
    for item in py::items(plan.get("items").ok_or("KeyError")?)? {
        let mut item = py::dict(&item)?;
        item.insert(Str::from("mirrored"), Value::Bool(true));
        if let Some(bounds) = item.get("rect").cloned() {
            item.insert(Str::from("rect"), across(&bounds)?);
        }
        if let Some(cx) = item.get("cx").cloned() {
            item.insert(Str::from("cx"), subtract(&width, &cx)?);
        }
        if pyval::is(item.get("kind").ok_or("KeyError")?, "text") {
            let align = item.get("align").ok_or("KeyError")?.clone();
            pyval::hashable(&align)?;
            let swapped = if pyval::is(&align, "left") {
                Value::from("right")
            } else if pyval::is(&align, "right") {
                Value::from("left")
            } else {
                align
            };
            item.insert(Str::from("align"), swapped);
        }
        items.push(Value::Object(item));
    }
    let mut mirrored = plan.clone();
    mirrored.insert(Str::from("items"), Value::Array(items));
    let card = across(plan.get("card").ok_or("KeyError")?)?;
    mirrored.insert(Str::from("card"), card);
    mirrored.insert(Str::from("rtl"), Value::Bool(true));
    let mut targets = Vec::new();
    for pair in py::items(plan.get("targets").ok_or("KeyError")?)? {
        let (target, bounds) = py::pair(&pair)?;
        targets.push(Value::Array(vec![target, across(&bounds)?]));
    }
    mirrored.insert(Str::from("targets"), Value::Array(targets));
    if let Some(rows) = plan.get("rows") {
        let mut found = Vec::new();
        for pair in py::items(rows)? {
            let (key, bounds) = py::pair(&pair)?;
            found.push(Value::Array(vec![key, across(&bounds)?]));
        }
        mirrored.insert(Str::from("rows"), Value::Array(found));
    }
    Ok(Value::Object(mirrored))
}

/// `a - b` of two numbers, an int where both are ints.
fn subtract(a: &Value, b: &Value) -> Py<Value> {
    match (a, b) {
        (Value::Int(x), Value::Int(y)) => match (x.as_i64(), y.as_i64()) {
            (Some(x), Some(y)) => x.checked_sub(y).map(Value::from).ok_or("OverflowError"),
            _ => Err("OverflowError"),
        },
        _ => Ok(Value::Float(pyval::minus(a, b)?)),
    }
}

// ------------------------------------------------------------------------------- motion
/// `ease_in(progress)`: easeInQuad, for leaving.
pub fn ease_in(progress: f64) -> f64 {
    let t = pyfmt::min(1.0, pyfmt::max(0.0, progress));
    t * t
}

/// `Frame(alpha, offset, scale, depth)`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Frame {
    pub alpha: f64,
    pub offset: f64,
    pub scale: f64,
    pub depth: f64,
}

pub const SETTLED: Frame = Frame {
    alpha: 1.0,
    offset: 0.0,
    scale: 1.0,
    depth: 1.0,
};

/// `entrance(elapsed_ms, reduced)`.
pub fn entrance(elapsed_ms: f64, reduced: bool) -> Frame {
    if reduced || elapsed_ms >= ENTRANCE_MS {
        return SETTLED;
    }
    let t = pyfmt::max(0.0, elapsed_ms) / ENTRANCE_MS;
    let settle = ease(t);
    Frame {
        alpha: ease(t / ALPHA_SHARE),
        offset: RISE * (1.0 - settle),
        scale: SCALE_FROM + (1.0 - SCALE_FROM) * settle,
        depth: settle,
    }
}

/// `leaving(elapsed_ms, start_alpha, reduced, duration)`: the card's alpha into its exit.
pub fn leaving(elapsed_ms: f64, start_alpha: f64, reduced: bool, duration: f64) -> Py<f64> {
    if reduced || elapsed_ms >= duration {
        return Ok(0.0);
    }
    if duration == 0.0 {
        return Err("ZeroDivisionError");
    }
    Ok(start_alpha * (1.0 - ease_in(pyfmt::max(0.0, elapsed_ms) / duration)))
}

/// `rise_vector(edge)`: toward the taskbar, so the card rises out of it.
pub fn rise_vector(edge: &Value) -> Py<(i64, i64)> {
    pyval::hashable(edge)?;
    Ok(match pyval::text(edge) {
        Some("top") => (0, -1),
        Some("left") => (-1, 0),
        Some("right") => (1, 0),
        _ => (0, 1),
    })
}

/// `CardMotion`: one card's life on a clock it is given - enter, hold, exit, gone.
#[derive(Clone, Debug, PartialEq)]
pub struct CardMotion {
    pub reduced: bool,
    pub phase: &'static str,
    pub since: f64,
    pub hold_ms: f64,
    pub hold_left: f64,
    pub paused: bool,
    pub from_alpha: f64,
    pub exit_ms: f64,
    pub is_final: bool,
    pub position: Option<Vec<i64>>,
    slide: Option<(Vec<i64>, Vec<i64>, f64)>,
}

impl CardMotion {
    pub fn new(now_ms: f64, hold_ms: f64, reduced: bool, position: Option<Vec<i64>>) -> CardMotion {
        CardMotion {
            reduced,
            phase: if reduced { "hold" } else { "enter" },
            since: now_ms,
            hold_ms: pyfmt::max(0.0, hold_ms),
            hold_left: pyfmt::max(0.0, hold_ms),
            paused: false,
            from_alpha: 1.0,
            exit_ms: EXIT_MS,
            is_final: false,
            position,
            slide: None,
        }
    }

    /// `restart(now_ms)`.
    pub fn restart(&mut self, now_ms: f64) {
        if (self.phase == "enter" || self.phase == "hold") && !self.is_final {
            self.phase = if self.reduced { "hold" } else { "enter" };
            self.since = now_ms;
            self.hold_left = self.hold_ms;
        }
    }

    /// `delay(ms)`.
    pub fn delay(&mut self, ms: f64) {
        if self.phase == "enter" && ms > 0.0 {
            self.since += ms;
        }
    }

    fn advance(&mut self, now_ms: f64) {
        if self.phase == "enter" && now_ms - self.since >= ENTRANCE_MS {
            self.phase = "hold";
            self.since += ENTRANCE_MS;
        }
        if self.phase == "return" && now_ms - self.since >= EXIT_MS {
            self.phase = "hold";
            self.since += EXIT_MS;
        }
        if self.phase == "hold" && !self.paused && now_ms - self.since >= self.hold_left {
            self.phase = "exit";
            self.since += self.hold_left;
            self.from_alpha = 1.0;
            self.hold_left = 0.0;
        }
        if self.phase == "exit" && (self.reduced || now_ms - self.since >= self.exit_ms) {
            self.phase = "gone";
        }
    }

    /// `frame(now_ms)`.
    pub fn frame(&mut self, now_ms: f64) -> Py<Frame> {
        self.advance(now_ms);
        let elapsed = now_ms - self.since;
        Ok(match self.phase {
            "enter" => entrance(elapsed, self.reduced),
            "return" => {
                let t = ease(elapsed / EXIT_MS);
                Frame {
                    alpha: self.from_alpha + (1.0 - self.from_alpha) * t,
                    ..SETTLED
                }
            }
            "exit" => Frame {
                alpha: leaving(elapsed, self.from_alpha, self.reduced, self.exit_ms)?,
                ..SETTLED
            },
            "gone" => Frame {
                alpha: 0.0,
                ..SETTLED
            },
            _ => SETTLED,
        })
    }

    /// `_slide`: (from, to, when it began), while the card glides.
    pub fn slide(&self) -> Option<(Vec<i64>, Vec<i64>, f64)> {
        self.slide.clone()
    }

    /// `gone`.
    pub fn gone(&self) -> bool {
        self.phase == "gone"
    }

    /// `pause(now_ms, paused)`: hold still while somebody points at the stack.
    pub fn pause(&mut self, now_ms: f64, paused: bool) -> Py<()> {
        self.advance(now_ms);
        if paused == self.paused {
            return Ok(());
        }
        if paused {
            if self.phase == "hold" {
                self.hold_left = pyfmt::max(0.0, self.hold_left - (now_ms - self.since));
                self.since = now_ms;
            } else if self.phase == "exit" && !self.reduced && !self.is_final {
                self.from_alpha = self.frame(now_ms)?.alpha;
                self.phase = "return";
                self.since = now_ms;
                self.hold_left = 0.0;
            }
        } else if self.phase == "hold" || self.phase == "return" {
            if self.phase == "hold" {
                self.since = now_ms;
            }
            self.hold_left = pyfmt::max(self.hold_left, HOVER_GRACE_MS);
        }
        self.paused = paused;
        Ok(())
    }

    /// `retire(now_ms, quick)`: leave now and for good.
    pub fn retire(&mut self, now_ms: f64, quick: bool) -> Py<()> {
        self.advance(now_ms);
        self.is_final = true;
        if self.phase == "gone" {
            return Ok(());
        }
        if self.phase == "exit" {
            if quick && self.exit_ms > SWAP_MS {
                self.from_alpha = self.frame(now_ms)?.alpha;
                self.since = now_ms;
                self.exit_ms = SWAP_MS;
            }
            return Ok(());
        }
        self.from_alpha = if self.phase == "enter" && now_ms < self.since {
            0.0
        } else {
            self.frame(now_ms)?.alpha
        };
        self.phase = "exit";
        self.since = now_ms;
        self.paused = false;
        self.exit_ms = if quick { SWAP_MS } else { EXIT_MS };
        if self.reduced {
            self.phase = "gone";
        }
        Ok(())
    }

    /// `move_to(now_ms, target, delay)`: glide to a new place in the stack.
    pub fn move_to(&mut self, now_ms: f64, target: Vec<i64>, delay: f64) {
        if self.position.is_none() || self.reduced {
            self.position = Some(target);
            self.slide = None;
            return;
        }
        let current = self.place(now_ms);
        if current.as_ref() == Some(&target) {
            self.slide = None;
            self.position = Some(target);
            return;
        }
        self.slide = Some((
            current.unwrap_or_default(),
            target.clone(),
            now_ms + pyfmt::max(0.0, delay),
        ));
        self.position = Some(target);
    }

    /// `place(now_ms)`.
    pub fn place(&mut self, now_ms: f64) -> Option<Vec<i64>> {
        let Some((start, target, began)) = self.slide.clone() else {
            return self.position.clone();
        };
        let t = (now_ms - began) / SLIDE_MS;
        if t >= 1.0 {
            self.slide = None;
            return Some(target);
        }
        let settle = ease(t);
        Some(
            start
                .iter()
                .zip(&target)
                .map(|(a, b)| round_int(*a as f64 + (*b - *a) as f64 * settle))
                .collect(),
        )
    }

    /// `moving(now_ms)`: whether a frame timer has anything to draw for this card now.
    pub fn moving(&mut self, now_ms: f64) -> bool {
        self.advance(now_ms);
        if let Some((_, _, began)) = &self.slide
            && now_ms - began < SLIDE_MS
        {
            return true;
        }
        matches!(self.phase, "enter" | "exit" | "return") && !self.reduced
    }

    /// `wait_ms(now_ms)`: how long nothing will change, when nothing is moving - or None.
    pub fn wait_ms(&mut self, now_ms: f64) -> Option<f64> {
        self.advance(now_ms);
        if self.phase == "hold" && !self.paused && !self.hold_left.is_infinite() {
            return Some(pyfmt::max(0.0, self.hold_left - (now_ms - self.since)));
        }
        None
    }
}

/// `hold_ms(message_duration_ms)`: HOLD_MS, or Windows' own "dismiss notifications after" time when longer.
pub fn hold_ms(message_duration_ms: &Value) -> Py<f64> {
    match message_duration_ms {
        Value::Int(_) | Value::Float(_) => {
            if !pyval::greater(message_duration_ms, &Value::from(6000))? {
                return Ok(HOLD_MS);
            }
            // `float(max(HOLD_MS, x))`: an int past a float's reach is an OverflowError.
            let given = pyval::Num::of(message_duration_ms).map_or(HOLD_MS, |n| n.as_f64());
            if given.is_infinite() && matches!(message_duration_ms, Value::Int(_)) {
                return Err("OverflowError");
            }
            Ok(given)
        }
        _ => Ok(HOLD_MS),
    }
}

// -------------------------------------------------------------------------- the stack
/// `stack_direction(edge, y, height, work)`: -1 when older cards stand above the newest one, +1 when below.
pub fn stack_direction(edge: &str, y: i64, height: i64, work: Rect) -> i64 {
    if edge == "top" {
        return 1;
    }
    if (edge == "left" || edge == "right")
        && (y as f64 + height as f64 / 2.0) < (work[1] + work[3]) as f64 / 2.0
    {
        return 1;
    }
    -1
}

/// `stack_positions(sizes, work, monitor, anchor, gap, spacing)`: where the cards go, newest first, and the edge.
pub fn stack_positions(
    sizes: &[(i64, i64)],
    work: Rect,
    monitor: Rect,
    anchor: Option<Rect>,
    gap: i64,
    spacing: i64,
) -> (Vec<(i64, i64)>, &'static str) {
    let Some(&(first_w, first_h)) = sizes.first() else {
        return (Vec::new(), placement::taskbar_edge(work, monitor, anchor));
    };
    let (x0, y0, edge) = placement::place((first_w, first_h), work, monitor, anchor, None, gap);
    let upward = stack_direction(edge, y0, first_h, work) < 0;
    let mut positions = vec![(x0, y0)];
    let edge_x = x0 + first_w;
    let mut y = y0;
    let mut previous_h = first_h;
    for &(width, height) in &sizes[1..] {
        let x = if edge == "left" { x0 } else { edge_x - width };
        y = if upward {
            y - spacing - height
        } else {
            y + previous_h + spacing
        };
        if y < work[1] + gap || y + height > work[3] - gap {
            break;
        }
        let x = placement::clamp(x, work[0] + gap, work[2] - gap - width);
        positions.push((x, y));
        previous_h = height;
    }
    (positions, edge)
}

// --------------------------------------------------------------------- the floating shadow
/// `FloatShadow(dx, dy, blur, colour, alpha)`.
#[derive(Clone, Debug, PartialEq)]
pub struct FloatShadow {
    pub dx: Num,
    pub dy: Num,
    pub blur: Num,
    pub colour: String,
    pub alpha: Num,
}

/// `float_shadows(theme, design)`: the card recipe's outer shadows as they may be drawn over a wallpaper. A theme or a
/// design that is not a text is `None` (the reference's default design is "soft", which its callers pass).
pub fn float_shadows(theme: Option<&str>, design: Option<&str>) -> Py<Vec<FloatShadow>> {
    let tokens = palette(theme, design)?;
    let ink = palette(Some(FLOAT_SHADOW_THEME), Some("soft"))?
        .at(FLOAT_SHADOW_INK)
        .s();
    let ground = tokens.at("canvas").s();
    let mut found = Vec::new();
    for shadow in shadows("card", theme, design)? {
        if shadow.inset {
            continue;
        }
        let colour = tokens.find(shadow.token).ok_or("KeyError")?.s();
        if luminance(colour)? >= luminance(ground)? {
            continue;
        }
        if luminance(colour)? <= DARK_ENOUGH {
            found.push(FloatShadow {
                dx: shadow.dx,
                dy: shadow.dy,
                blur: shadow.blur,
                colour: colour.to_owned(),
                alpha: shadow.alpha,
            });
            continue;
        }
        let darkening = shadow.alpha.f() * (1.0 - luminance(colour)?) / (1.0 - luminance(ink)?);
        found.push(FloatShadow {
            dx: shadow.dx,
            dy: shadow.dy,
            blur: shadow.blur,
            colour: ink.to_owned(),
            alpha: Num::F(round_to(darkening, 4)),
        });
    }
    Ok(found)
}

fn depth_start(name: &str) -> f64 {
    DEPTH_START
        .iter()
        .find(|(each, _)| *each == name)
        .map_or(0.0, |(_, value)| *value)
}

/// `shadow_at(shadows, depth)`: the floating shadows at `depth` (0 the start of the entrance, 1 settled).
pub fn shadow_at(found: &[FloatShadow], depth: f64) -> Vec<FloatShadow> {
    let depth = pyfmt::min(1.0, pyfmt::max(0.0, depth));
    let toward = |start: f64| start + (1.0 - start) * depth;
    let (offset, blur, alpha) = (
        toward(depth_start("offset")),
        toward(depth_start("blur")),
        toward(depth_start("alpha")),
    );
    found
        .iter()
        .map(|shadow| FloatShadow {
            dx: Num::F(shadow.dx.f() * offset),
            dy: Num::F(shadow.dy.f() * offset),
            blur: Num::F(shadow.blur.f() * blur),
            colour: shadow.colour.clone(),
            alpha: Num::F(shadow.alpha.f() * alpha),
        })
        .collect()
}

/// `depth_level(depth)`: which of DEPTH_LEVELS pre-drawn shadow images stands for `depth`.
pub fn depth_level(depth: f64) -> i64 {
    round_int(pyfmt::min(1.0, pyfmt::max(0.0, depth)) * (DEPTH_LEVELS - 1) as f64)
}

/// `shadow_margin(shadows, scale)`: how far the settled shadows reach past the card, in device pixels.
pub fn shadow_margin(found: &[FloatShadow], scale: f64) -> i64 {
    let mut reach = 0.0;
    for shadow in found {
        let far = pyfmt::max(shadow.dx.f().abs(), shadow.dy.f().abs()) + 1.5 * shadow.blur.f();
        reach = pyfmt::max(reach, far);
    }
    (reach * scale).ceil() as i64 + 2
}

// ---------------------------------------------------------------------- the card's edge
type Rows = Vec<Vec<u8>>;

/// `_CORNERS`: a corner per scale, a few at most.
static CORNERS: Mutex<Vec<((u64, u64), Rows)>> = Mutex::new(Vec::new());

/// `corner_coverage(radius, smoothing)`: how much of each pixel of a card's top-left corner square the card covers,
/// 0-255, rows of bytes; the squircle at `smoothing` (Soft's unless said), the circle without smoothing.
pub fn corner_coverage(radius: f64, smoothing: Option<f64>) -> Py<Rows> {
    let smoothing = match smoothing {
        Some(value) => value,
        None => shape::design_smoothing(Some("soft"))?,
    };
    let key = (radius.to_bits(), smoothing.to_bits());
    let mut kept = CORNERS
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if let Some((_, rows)) = kept.iter().find(|(each, _)| *each == key) {
        return Ok(rows.clone());
    }
    let made = shape::profile(radius, smoothing, 1e9);
    let rows = if shape::smoothed(&made.corner) {
        squircle_corner(&made)
    } else {
        round_corner(radius)
    };
    if kept.len() >= 8 {
        kept.clear();
    }
    kept.push((key, rows.clone()));
    Ok(rows)
}

fn round_corner(radius: f64) -> Rows {
    let size = radius.ceil().max(0.0) as usize;
    let mut rows = Vec::with_capacity(size);
    for j in 0..size {
        let mut row = vec![0u8; size];
        for (i, cell) in row.iter_mut().enumerate() {
            let mut distance =
                pyfmt::hypot(radius - (i as f64 + 0.5), radius - (j as f64 + 0.5)) - radius;
            if i as f64 + 0.5 >= radius || j as f64 + 0.5 >= radius {
                distance = -1.0;
            }
            *cell = round_int(pyfmt::min(1.0, pyfmt::max(0.0, 0.5 - distance)) * 255.0) as u8;
        }
        rows.push(row);
    }
    rows
}

fn squircle_corner(made: &Profile) -> Rows {
    let size = made.p.ceil().max(0.0) as usize;
    let middle = made.middle;
    let mut half: Vec<Vec<u8>> = Vec::with_capacity(size);
    for i in 0..size {
        let mut column = vec![0u8; size];
        if (i + 1) as f64 <= middle {
            half.push(column);
            continue;
        }
        let edges: Vec<f64> = (0..4)
            .map(|s| {
                let u = i as f64 + (s as f64 + 0.5) / 4.0;
                if u >= middle {
                    shape::edge_at(made, u)
                } else {
                    size as f64
                }
            })
            .collect();
        let low = edges.iter().copied().fold(f64::INFINITY, pyfmt::min);
        let high = edges.iter().copied().fold(f64::NEG_INFINITY, pyfmt::max);
        let first = 0i64.max((i as i64).min((low - 0.875).floor() as i64));
        let full = first.max((i as i64).min((high - 0.125).ceil() as i64));
        for j in first..full {
            let mut count: i64 = 16;
            for edge in &edges {
                let skipped = (4.0 * (edge - j as f64) - 0.5).ceil() as i64;
                count -= if skipped > 4 {
                    4
                } else if skipped > 0 {
                    skipped
                } else {
                    0
                };
            }
            column[j as usize] = ((count * 255 + 8).div_euclid(16)) as u8;
        }
        for cell in column.iter_mut().take(i).skip(full as usize) {
            *cell = 0xff;
        }
        half.push(column);
    }
    let mut rows = Vec::with_capacity(size);
    for r in 0..size {
        let mut row = vec![0u8; size];
        row[..r].copy_from_slice(&half[r][..r]);
        for (c, cell) in row.iter_mut().enumerate().skip(r + 1) {
            *cell = half[c][r];
        }
        row[r] = if (r + 1) as f64 <= middle {
            0
        } else if r as f64 >= middle + 1.0 {
            255
        } else {
            let mut count = 0i64;
            for sy in 0..4 {
                for sx in 0..4 {
                    let u = r as f64 + (sx as f64 + 0.5) / 4.0;
                    let v = r as f64 + (sy as f64 + 0.5) / 4.0;
                    if shape::inside_corner(made, u, v) {
                        count += 1;
                    }
                }
            }
            ((count * 255 + 8).div_euclid(16)) as u8
        };
        rows.push(row);
    }
    rows
}

/// Python's `a // b` of two ints.
fn floor_div(a: i64, b: i64) -> i64 {
    let quotient = a / b;
    if (a % b != 0) && ((a < 0) != (b < 0)) {
        quotient - 1
    } else {
        quotient
    }
}

/// `premultiply(pixels, width, height, radius, top, smoothing)`: a card's opaque BGRX pixels as premultiplied BGRA
/// with its rounded corners cut out; `pixels` may be a band of whole rows starting at row `top`.
pub fn premultiply(
    pixels: &[u8],
    width: i64,
    height: i64,
    radius: f64,
    top: i64,
    smoothing: Option<f64>,
) -> Py<Vec<u8>> {
    let mut data = pixels.to_vec();
    let band = if width != 0 {
        floor_div(data.len() as i64, 4 * width)
    } else {
        0
    };
    // `data[3::4] = b"\xff" * (width * band)`: an extended slice takes exactly as many bytes as it has places.
    let places = if data.len() > 3 {
        (data.len() - 3).div_ceil(4)
    } else {
        0
    };
    let filled = (width * band).max(0);
    if filled == 0 {
        // A bytearray given no bytes for an extended slice deletes the slice's places.
        let mut index = 0usize;
        data.retain(|_| {
            let keep = index < 3 || !(index - 3).is_multiple_of(4);
            index += 1;
            keep
        });
    } else if (places as i64) != filled {
        return Err("ValueError");
    } else {
        for index in (3..data.len()).step_by(4) {
            data[index] = 0xff;
        }
    }
    let rows = corner_coverage(radius, smoothing)?;
    let size = rows.len() as i64;
    for j in 0..size.min(height) {
        for i in 0..size.min(width) {
            let cover = rows[j as usize][i as usize];
            if cover == 255 {
                continue;
            }
            for (x, y) in [
                (i, j),
                (width - 1 - i, j),
                (i, height - 1 - j),
                (width - 1 - i, height - 1 - j),
            ] {
                let y = y - top;
                if !(0 <= y && y < band) {
                    continue;
                }
                let index = ((y * width + x) * 4) as usize;
                if cover == 0 {
                    data[index..index + 4].copy_from_slice(&[0, 0, 0, 0]);
                } else {
                    for channel in 0..3 {
                        data[index + channel] =
                            ((u32::from(data[index + channel]) * u32::from(cover) + 127) / 255)
                                as u8;
                    }
                    data[index + 3] = cover;
                }
            }
        }
    }
    Ok(data)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn motion() {
        assert_eq!(entrance(400.0, false), SETTLED);
        let mut card = CardMotion::new(0.0, HOLD_MS, false, None);
        assert_eq!(card.frame(0.0).unwrap().alpha, 0.0);
        card.frame(ENTRANCE_MS + HOLD_MS + 1.0).unwrap();
        assert_eq!(card.phase, "exit");
        card.frame(ENTRANCE_MS + HOLD_MS + EXIT_MS + 1.0).unwrap();
        assert!(card.gone());
        assert_eq!(hold_ms(&Value::from(9000)), Ok(9000.0));
        assert_eq!(hold_ms(&Value::Bool(true)), Ok(HOLD_MS));
    }

    #[test]
    fn corners() {
        let rows = corner_coverage(16.0, Some(0.0)).unwrap();
        assert_eq!(rows.len(), 16);
        assert_eq!(rows[0][0], 0);
        assert_eq!(rows[15][15], 255);
        let smooth = corner_coverage(16.0, None).unwrap();
        assert!(!smooth.is_empty());
        let pixels = vec![200u8; 4 * 40 * 40];
        let cut = premultiply(&pixels, 40, 40, 16.0, 0, None).unwrap();
        assert_eq!(&cut[0..4], &[0, 0, 0, 0]);
        assert_eq!(cut[4 * (20 * 40 + 20) + 3], 255);
        assert!(premultiply(&[1, 2, 3, 4, 5], 1, 1, 4.0, 0, None).is_ok());
        assert!(premultiply(&[0; 12], 2, 1, 4.0, 0, None).is_err());
        assert_eq!(premultiply(&[0; 8], 0, 2, 4.0, 0, None).unwrap().len(), 6);
    }
}
