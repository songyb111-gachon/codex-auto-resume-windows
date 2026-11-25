//! car-policy's classifier half (S2.1), one case at a time through `leaves.batch`.
//!
//! Each case is `[name, arg, ...]` as `tests/rustdiff/diffs_classify_*.py` writes it, and the answer is what the
//! family script's reference side writes for the same case: a set as a sorted list, a tuple as a list, a refusal
//! (`CustomMessageError`, `PromptError`) as `["refused", ...]`. Nothing here decides anything: every answer is
//! car-policy's own function's. The clock is a test zone ([`Zone`]) that the reference side defines alike, or `"local"`,
//! the product's own ([`Clock`], car-policy's `Crt`), which the reference answers with its own `time` module.

use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_machine::vocab;
use car_policy::classify::clock::{Crt, LocalClock, Tm};
use car_policy::classify::continuation::{self, Environ, Settings};
use car_policy::classify::gates::{self, Limits, Vector};
use car_policy::classify::{
    failures, guards, ladder, needsyou, permits, power, projects, quiet, reasons, selfcheck, text,
    vocab_gen,
};
use car_policy::plug::vocab_gen::domain_plug::{PACED_AS, TAKE_UP};
use car_policy::settings::ownvalues::{self, Measured, Own, OwnKind};

use crate::leaves::Args;

/// A test's zone: a fixed offset, and summer time of `dst` seconds between two days of the UTC year.
pub struct Zone {
    offset: i64,
    dst: i64,
    start: i64,
    end: i64,
}

const LAST_SECOND: f64 = 32_503_680_000.0;

fn civil(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (y + i64::from(m <= 2), m, d)
}

fn days_from(y: i64, m: i64, d: i64) -> i64 {
    let y = y - i64::from(m <= 2);
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (m + if m > 2 { -3 } else { 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

fn yday(y: i64, m: i64, d: i64) -> i64 {
    days_from(y, m, d) - days_from(y, 1, 1) + 1
}

impl Zone {
    pub fn of(value: &Value) -> Zone {
        let at = |index: usize| match value {
            Value::Array(items) => items.get(index).and_then(|each| match each {
                Value::Int(n) => n.as_i64(),
                _ => None,
            }),
            _ => None,
        };
        Zone {
            offset: at(0).unwrap_or(0),
            dst: at(1).unwrap_or(0),
            start: at(2).unwrap_or(0),
            end: at(3).unwrap_or(0),
        }
    }

    fn in_dst(&self, t: i64) -> bool {
        if self.dst == 0 {
            return false;
        }
        let (y, m, d) = civil(t.div_euclid(86400));
        (self.start..self.end).contains(&yday(y, m, d))
    }
}

impl LocalClock for Zone {
    /// The test zone's `localtime(None)` is a TypeError, as its Python twin's is (it takes numbers only).
    fn localtime_now(&self) -> Py<Tm> {
        Err("TypeError")
    }

    fn localtime(&self, t: f64) -> Py<Tm> {
        if t.is_nan() {
            return Err("ValueError");
        }
        if t.is_infinite() {
            return Err("OverflowError");
        }
        if !(0.0..=LAST_SECOND).contains(&t) {
            return Err("OSError");
        }
        let t = t.floor() as i64;
        let local = t + self.offset + if self.in_dst(t) { self.dst } else { 0 };
        let (days, rest) = (local.div_euclid(86400), local.rem_euclid(86400));
        let (year, mon, mday) = civil(days);
        Ok(Tm {
            year,
            mon,
            mday,
            hour: rest / 3600,
            min: rest % 3600 / 60,
            sec: rest % 60,
            wday: (days + 3).rem_euclid(7),
        })
    }

    fn mktime(&self, year: i64, mon: i64, mday: i64, hour: i64, min: i64, sec: i64) -> Py<f64> {
        let year = year + (mon - 1).div_euclid(12);
        let mon = (mon - 1).rem_euclid(12) + 1;
        let local = (days_from(year, mon, 1) + mday - 1) * 86400 + hour * 3600 + min * 60 + sec;
        let standard = local - self.offset;
        let summer = standard - self.dst;
        let t = if self.dst != 0 && self.in_dst(summer) {
            summer
        } else {
            standard
        };
        if !(0.0..=LAST_SECOND).contains(&(t as f64)) {
            return Err("OverflowError");
        }
        Ok(t as f64)
    }
}

/// The clock a case names: a test zone, or `"local"`, the product's own (car-policy's `Crt`, the C runtime's
/// `localtime` and `mktime`), which the reference side answers with its interpreter's own `time` module.
pub enum Clock {
    Zone(Zone),
    Local(Crt),
}

impl Clock {
    fn of(value: &Value) -> Clock {
        match value {
            Value::Str(name) if name.as_str() == Some("local") => Clock::Local(Crt),
            other => Clock::Zone(Zone::of(other)),
        }
    }
}

impl LocalClock for Clock {
    fn localtime_now(&self) -> Py<Tm> {
        match self {
            Clock::Zone(zone) => zone.localtime_now(),
            Clock::Local(crt) => crt.localtime_now(),
        }
    }

    fn localtime(&self, seconds: f64) -> Py<Tm> {
        match self {
            Clock::Zone(zone) => zone.localtime(seconds),
            Clock::Local(crt) => crt.localtime(seconds),
        }
    }

    fn mktime(&self, year: i64, mon: i64, mday: i64, hour: i64, min: i64, sec: i64) -> Py<f64> {
        match self {
            Clock::Zone(zone) => zone.mktime(year, mon, mday, hour, min, sec),
            Clock::Local(crt) => crt.mktime(year, mon, mday, hour, min, sec),
        }
    }
}

fn row(value: &Value) -> Map {
    match value {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    }
}

fn float(value: &Value) -> f64 {
    car_policy::classify::value::number(value).unwrap_or(0.0)
}

fn limits(value: &Value) -> Option<Limits> {
    let Value::Object(map) = value else {
        return None;
    };
    let number = |name: &str| map.get(name).and_then(car_policy::classify::value::number);
    Some(Limits {
        max_no_progress: number("max_no_progress").unwrap_or(0.0),
        max_chain_continuations: number("max_chain_continuations").unwrap_or(0.0),
        max_recovery_attempts: number("max_recovery_attempts").unwrap_or(0.0),
        max_chain_seconds: number("max_chain_seconds"),
        managed_max_recovery_attempts: None,
    })
}

fn vector(value: &Value) -> Vector {
    let mut found = Vector::default();
    if let Value::Object(map) = value {
        for (name, pair) in map {
            if let (Some(name), Value::Array(pair)) = (name.as_str(), pair)
                && let [Value::Str(result), Value::Str(reason)] = pair.as_slice()
            {
                found.set(
                    name,
                    (
                        result.as_str().unwrap_or_default().to_owned(),
                        reason.as_str().unwrap_or_default().to_owned(),
                    ),
                );
            }
        }
    }
    found
}

fn pair(gate: (String, String)) -> Value {
    Value::Array(vec![Value::from(gate.0), Value::from(gate.1)])
}

fn words(items: &[&str]) -> Value {
    Value::Array(items.iter().map(|each| Value::from(*each)).collect())
}

fn option<T: Into<Value>>(found: Option<T>) -> Value {
    found.map_or(Value::Null, Into::into)
}

fn spec(value: &Value) -> Own {
    let items = match value {
        Value::Array(items) => items.clone(),
        _ => Vec::new(),
    };
    let text = |at: usize| -> &'static str {
        let said = items
            .get(at)
            .and_then(|each| car_policy::classify::value::text(each))
            .unwrap_or("");
        Box::leak(said.to_owned().into_boxed_str())
    };
    let number = |at: usize| match items.get(at) {
        Some(Value::Int(n)) => n.as_i64().unwrap_or(0),
        _ => 0,
    };
    let units: Vec<&'static str> = match items.get(3) {
        Some(Value::Array(units)) => units
            .iter()
            .map(|each| -> &'static str {
                Box::leak(
                    car_policy::classify::value::text(each)
                        .unwrap_or("")
                        .to_owned()
                        .into_boxed_str(),
                )
            })
            .collect(),
        _ => Vec::new(),
    };
    let kind = match text(0) {
        "duration" => OwnKind::Duration,
        "clock" => OwnKind::Clock,
        "days" => OwnKind::Days,
        _ => OwnKind::Count,
    };
    Own::new(
        kind,
        number(1),
        number(2),
        Box::leak(units.into_boxed_slice()),
    )
    .prefix(text(4))
}

fn measured(found: Option<Measured>) -> Value {
    match found {
        None => Value::Null,
        Some(Measured::Number(n) | Measured::Minute(n)) => Value::from(n),
        Some(days @ Measured::Days(_)) => {
            Value::Array(days.days().into_iter().map(Value::from).collect())
        }
    }
}

fn reason_entry(entry: &reasons::Reason) -> Value {
    car_policy::classify::value::object([
        ("category", Value::from(entry.category)),
        ("recoverable", Value::Bool(entry.recoverable)),
        ("order", Value::from(i64::from(entry.order))),
        ("has_reset_time", Value::Bool(entry.has_reset_time)),
        ("configurable", Value::Bool(entry.configurable)),
        ("label_key", Value::from(entry.label_key())),
        ("standard_key", option(entry.standard_key())),
        ("detailed_key", option(entry.detailed_key())),
    ])
}

/// The environment a continuation case names (a dict of variables), and Windows naming no language.
fn with_environ<T>(value: &Value, body: impl FnOnce(&Environ) -> T) -> T {
    let variables = row(value);
    let variable = move |name: &str| -> Option<String> {
        variables
            .get(name)
            .and_then(car_policy::classify::value::text)
            .map(str::to_owned)
    };
    let windows = || Vec::new();
    body(&Environ {
        variable: &variable,
        windows: &windows,
    })
}

fn refused(code: &str, rest: Vec<Value>) -> Value {
    let mut items = vec![Value::from("refused"), Value::from(code)];
    items.extend(rest);
    Value::Array(items)
}

fn accepted(said: String) -> Value {
    Value::Array(vec![Value::from("ok"), Value::from(said)])
}

fn continuation_case(name: &str, a: &Args) -> Option<Py<Value>> {
    let settings = |at: usize, body: &dyn Fn(&Settings) -> Py<Value>| -> Py<Value> {
        let zone = Clock::of(a.get(at + 4));
        with_environ(a.get(at + 3), |environ| {
            body(&Settings {
                values: a.get(at),
                row: a.get(at + 1),
                limits: a.get(at + 2),
                environ,
                clock: &zone,
            })
        })
    };
    Some(match name {
        "continuation.validate_custom" => Ok(match continuation::validate_custom(a.get(0)) {
            Ok(said) => accepted(said),
            Err(error) => refused(
                error.code,
                vec![option(error.detail), Value::from(error.message)],
            ),
        }),
        "continuation.validate_prompt" => Ok(match continuation::validate_prompt(a.get(0)) {
            Ok(said) => accepted(said),
            Err(code) => refused(code, Vec::new()),
        }),
        "continuation.validate_continuation" => {
            Ok(match continuation::validate_continuation(a.get(0)) {
                Ok(said) => accepted(said),
                Err(code) => refused(code, Vec::new()),
            })
        }
        "continuation.joined_command_line" | "continuation.command_line_units" => {
            let argv: Vec<String> = match a.get(0) {
                Value::Array(items) => items
                    .iter()
                    .map(|each| {
                        car_policy::classify::value::text(each)
                            .unwrap_or("")
                            .to_owned()
                    })
                    .collect(),
                _ => Vec::new(),
            };
            Ok(if name.ends_with("units") {
                Value::from(continuation::command_line_units(&argv) as i64)
            } else {
                Value::from(continuation::joined_command_line(&argv))
            })
        }
        "continuation.fits_command_line" => a
            .text(0)
            .map(|said| Value::Bool(continuation::fits_command_line(said))),
        "continuation.product_texts" => Ok(Value::Array(
            continuation::product_texts()
                .iter()
                .map(|each| Value::from(each.as_str()))
                .collect(),
        )),
        "continuation.prompt_limit" => Ok(Value::from(continuation::prompt_limit() as i64)),
        "continuation.coerce_by_thread" => Ok(continuation::coerce_by_thread(a.get(0), a.get(1))),
        "continuation.conversation_text" => continuation::conversation_text(a.get(0), a.get(1)),
        "continuation.fill" => a
            .text(0)
            .map(|template| Value::from(continuation::fill(template, &row(a.get(1))))),
        "continuation.metadata_for" => a
            .text(1)
            .and_then(|locale| continuation::metadata_for(a.get(0), locale, a.get(2), a.get(3)))
            .map(Value::Object),
        "continuation.build" => a
            .text(1)
            .and_then(|locale| continuation::build(a.get(0), locale, a.get(2), a.get(3), a.get(4)))
            .map(Value::from),
        "continuation.resolve_locale" => with_environ(a.get(1), |environ| {
            continuation::resolve_locale(a.get(0), environ)
        })
        .map(Value::from),
        "continuation.fold_style" => Ok(continuation::fold_style(a.get(0))),
        "continuation.style_from" => continuation::style_from(a.get(0)).map(Value::from),
        "continuation.custom_from" => continuation::custom_from(a.get(0), a.get(1)),
        "continuation.format_reset_time" => Ok(continuation::format_reset_time(
            a.get(0),
            &Clock::of(a.get(1)),
        )),
        "continuation.source_for" => {
            settings(1, &|at| continuation::source_for(a.get(0), at).map(option))
        }
        "continuation.for_settings" => settings(1, &|at| {
            continuation::for_settings(a.get(0), at).map(Value::from)
        }),
        "continuation.with_once_words" => settings(3, &|at| {
            continuation::with_once_words(a.get(0), a.get(1), a.get(2), at)
        }),
        _ => return None,
    })
}

/// One case: `Some(result)` where this module knows the name.
pub fn case(name: &str, a: &Args) -> Option<Py<Value>> {
    if name.starts_with("continuation.") {
        return continuation_case(name, a);
    }
    Some(match name {
        "classify.vocab" => Ok(vocab::export(&[vocab_gen::MODULES])),
        "classify.tables" => {
            let mut words = String::with_capacity(0x110000);
            for point in 0..0x110000u32 {
                words.push(if (0xD800..0xE000).contains(&point) {
                    '-'
                } else if text::is_word(point) {
                    'w'
                } else {
                    '.'
                });
            }
            let lowered: Vec<(u32, String)> = (0..0x110000u32)
                .filter(|point| !(0xD800..0xE000).contains(point))
                .filter_map(|point| {
                    let mut out = Vec::new();
                    text::lower_point(point, &mut out);
                    (out != [point]).then(|| {
                        (
                            point,
                            out.iter()
                                .filter_map(|each| char::from_u32(*each))
                                .collect(),
                        )
                    })
                })
                .collect();
            let folded: Vec<(u32, String)> = (0..0x110000u32)
                .filter(|point| !(0xD800..0xE000).contains(point))
                .filter_map(|point| {
                    let c = char::from_u32(point)?;
                    let said = text::casefold(&c.to_string());
                    (said != c.to_string()).then_some((point, said))
                })
                .collect();
            let pairs = |found: &[(u32, String)]| {
                Value::Array(
                    found
                        .iter()
                        .map(|(point, said)| {
                            Value::Array(vec![
                                Value::from(i64::from(*point)),
                                Value::from(said.as_str()),
                            ])
                        })
                        .collect(),
                )
            };
            Ok(Value::Array(vec![
                Value::from(words),
                pairs(&lowered),
                pairs(&folded),
            ]))
        }
        // failures
        "failures.classify" => Ok(Value::from(failures::classify(a.get(0), a.get(1)))),
        "failures.shape" => Ok(failures::shape(a.get(0), a.get(1))),
        "failures.retry_after" => Ok(option(failures::retry_after(a.get(0)))),
        "failures.wait_seconds" => Ok(option(failures::wait_seconds(a.get(0)))),
        "failures.is_recoverable" => failures::is_recoverable_value(a.get(0)).map(Value::Bool),
        "failures.tag_shape" => a.text(0).map(|code| Value::Bool(failures::tag_shape(code))),
        "failures.decision_tag" => Ok(Value::Bool(failures::decision_tag(a.get(0)))),
        "failures.unknown_code" => failures::unknown_code(a.get(0)),
        "failures.admits" => failures::admits(a.get(0), a.get(1)).map(Value::Bool),
        "failures.takes" => {
            let on: Vec<String> = match a.get(1) {
                Value::Array(items) => items
                    .iter()
                    .filter_map(car_policy::classify::value::text)
                    .map(str::to_owned)
                    .collect(),
                _ => Vec::new(),
            };
            failures::takes(a.get(0), &|kind| on.iter().any(|each| each == kind))
                .map(|found| words(&found))
        }
        "failures.readmits" => failures::readmits(a.get(0), a.get(1)).map(Value::Bool),
        "failures.reset_verified" => {
            failures::reset_verified_value(a.get(0), a.get(1)).map(Value::Bool)
        }
        "failures.reset_verified_row" => Ok(Value::Bool(failures::reset_verified(
            &row(a.get(0)),
            float(a.get(1)),
        ))),
        "failures.reset_carried" => Ok(failures::reset_carried(a.get(0), a.get(1))),
        "failures.recoverable_text" => a
            .text(0)
            .map(|category| Value::Bool(failures::is_recoverable(category))),
        // reasons
        "reasons.entry" => reasons::get_value(a.get(0)).map(reason_entry),
        "reasons.is_recoverable" => reasons::is_recoverable(a.get(0)).map(Value::Bool),
        "reasons.label_key" => reasons::label_key(a.get(0)).map(Value::from),
        "reasons.has_reset_time" => reasons::has_reset_time(a.get(0)).map(Value::Bool),
        "reasons.configurable" => Ok(words(&reasons::configurable())),
        // self-check
        "public.self_check" => selfcheck::self_check(a.get(0), a.get(1)),
        // gates
        "gates.gate" => Ok(pair(gates::gate(
            a.text(0).unwrap_or(""),
            a.text(1).unwrap_or(""),
        ))),
        "gates.consent" => Ok(pair(gates::gate_consent(
            a.flag(0),
            a.flag(1),
            a.flag(2),
            a.flag(3),
            a.get(4),
        ))),
        "gates.schedule" => Ok(pair(gates::gate_schedule(
            &row(a.get(0)),
            float(a.get(1)),
            car_policy::classify::value::number(a.get(2)),
            a.flag(3),
            a.flag(4),
        ))),
        "gates.usage_read_stopped" => Ok(option(gates::usage_read_stopped(
            a.flag(0),
            a.flag(1),
            a.flag(2),
            a.flag(3),
        ))),
        "gates.submission_safe" => Ok(pair(gates::gate_submission_safe(
            &row(a.get(0)),
            a.int(1).unwrap_or(0),
        ))),
        "gates.own_budget_only" => Ok(Value::Bool(gates::own_budget_only(
            &row(a.get(0)),
            car_policy::classify::value::number(a.get(1)),
        ))),
        "gates.was_resent" => Ok(Value::Bool(gates::was_resent(&row(a.get(0))))),
        "gates.resend_candidate" => {
            let window = match a.get(2) {
                Value::Array(items) if items.len() == 2 => (float(&items[0]), float(&items[1])),
                _ => (0.0, 0.0),
            };
            Ok(Value::Bool(gates::resend_candidate(
                &row(a.get(0)),
                float(a.get(1)),
                window,
            )))
        }
        "gates.chain_span" => Ok(Value::Float(gates::chain_span(&row(a.get(0))))),
        "gates.waited_aside" => Ok(Value::Bool(gates::waited_aside(&vector(a.get(0))))),
        "gates.counted_from" => Ok(gates::counted_from(&row(a.get(0)), float(a.get(1)))),
        "gates.over_ceiling" => Ok(Value::Bool(gates::over_ceiling(
            &row(a.get(0)),
            &limits(a.get(1)).expect("limits"),
            a.flag(2),
        ))),
        "gates.inherited" => {
            let parent = match a.get(0) {
                Value::Object(map) => Some(map.clone()),
                _ => None,
            };
            let mut found = Map::new();
            for (name, value) in gates::inherited(parent.as_ref(), a.get(1), a.get(2)) {
                found.insert(name.into(), value);
            }
            Ok(Value::Object(found))
        }
        "gates.birth_stop" => {
            let parent = match a.get(0) {
                Value::Object(map) => Some(map.clone()),
                _ => None,
            };
            let limits = limits(a.get(2));
            Ok(
                match gates::birth_stop(
                    parent.as_ref(),
                    a.get(1),
                    limits.as_ref(),
                    a.flag(3),
                    float(a.get(4)),
                    a.get(5),
                ) {
                    Some((state, reason)) => words(&[state, reason]),
                    None => Value::Null,
                },
            )
        }
        "gates.budgets" => {
            let mut found = Map::new();
            for (name, gate) in gates::gate_budgets(
                &row(a.get(0)),
                &limits(a.get(1)).expect("limits"),
                a.flag(2),
            ) {
                found.insert(name.into(), pair(gate));
            }
            Ok(Value::Object(found))
        }
        "gates.first_refusal" => Ok(match gates::first_refusal(&vector(a.get(0))) {
            Some((name, gate)) => Value::Array(vec![Value::from(name), pair(gate)]),
            None => Value::Null,
        }),
        "gates.would_send_at" => Ok(gates::would_send_at(&row(a.get(0)))),
        "gates.encode" => Ok(Value::from(gates::encode_gates(&vector(a.get(0))))),
        "gates.decode" => {
            let decoded = gates::decode_gates(a.get(0));
            let mut found = Map::new();
            for (name, gate) in decoded.0 {
                found.insert(name.as_str().into(), pair(gate));
            }
            Ok(Value::Object(found))
        }
        // guards
        "guards.task_mode" => Ok(Value::from(guards::task_mode(a.get(0)))),
        "guards.watches_task" => Ok(Value::Bool(guards::watches_task(a.get(0)))),
        "guards.context_mode" => Ok(Value::from(guards::context_mode(a.get(0)))),
        "guards.counts_tokens" => Ok(Value::Bool(guards::counts_tokens(a.get(0)))),
        "guards.context_limit" => Ok(option(guards::context_limit(a.get(0)))),
        "guards.fingerprint" => guards::fingerprint(a.get(0), a.get(1), a.get(2)).map(Value::from),
        "guards.is_print" => Ok(Value::Bool(guards::is_print(a.get(0)))),
        "guards.changed" => Ok(Value::Bool(guards::changed(a.get(0), a.get(1)))),
        "guards.tokens" => Ok(option(guards::tokens(a.get(0)))),
        "guards.over" => Ok(Value::Bool(guards::over(a.get(0), a.get(1)))),
        // ladder
        "ladder.choices_for" => a.text(0).map(|field| words(ladder::choices_for(field))),
        "ladder.timing" => Ok(Value::from(ladder::timing(a.get(0)))),
        "ladder.custom_steps" => Ok(Value::Array(
            ladder::custom_steps(a.get(0))
                .iter()
                .map(|n| Value::from(*n))
                .collect(),
        )),
        "ladder.ladder" => Ok(Value::Array(
            ladder::ladder(a.get(0))
                .iter()
                .map(|n| Value::from(*n))
                .collect(),
        )),
        "ladder.walks" => Ok(Value::Bool(ladder::walks(a.get(0)))),
        "ladder.wait_before" => ladder::wait_before(a.get(0), a.get(1), a.get(2)).map(Value::from),
        "ladder.preview" => Ok(Value::Array(
            ladder::preview(a.get(0))
                .into_iter()
                .map(Value::from)
                .collect(),
        )),
        "ladder.previews" => {
            let mut found = Map::new();
            for (name, preview) in ladder::previews() {
                found.insert(
                    name.into(),
                    Value::Array(preview.into_iter().map(Value::from).collect()),
                );
            }
            Ok(Value::Object(found))
        }
        "ladder.jittered" => ladder::jittered(a.get(0), a.get(1), a.get(2)),
        "ladder.ceiling" => Ok(option(ladder::ceiling(a.get(0)))),
        "ladder.constants" => Ok(Value::Array(
            [
                ladder::SPACING,
                ladder::PER_DAY,
                ladder::RATE_LIMIT_FIRST,
                ladder::ADMITTED_WAITS[0],
                ladder::ADMITTED_WAITS[1],
                ladder::ADMITTED_WAITS[2],
                ladder::ADMISSION_MAX_AGE,
                ladder::ADMITTED_MAX_SECONDS,
                ladder::CAPACITY_WAITS[0],
                ladder::CAPACITY_WAITS[1],
                ladder::CAPACITY_WAITS[2],
                ladder::CAPACITY_WAITS[3],
                ladder::CAPACITY_SPACING,
                ladder::CAPACITY_PER_DAY,
                ladder::CAPACITY_MAX_SECONDS,
                ladder::RESET_PER_DAY,
                ladder::EARLY_SPACING,
                ladder::EARLY_WINDOW,
                needsyou::WINDOW_SECONDS,
                needsyou::KEEP_SECONDS,
                quiet::MAX_POSTPONE_SECONDS,
                guards::MAX_TOKENS,
                failures::MAX_RETRY_AFTER,
                continuation::MAX_CUSTOM_LENGTH as i64,
                continuation::PROMPT_SEND_LIMIT as i64,
                continuation::COMMAND_LINE_UNITS as i64,
                continuation::SEND_ARGV_ROOM as i64,
                projects::MAX_KEYS as i64,
                continuation::MAX_CONVERSATIONS as i64,
            ]
            .into_iter()
            .map(Value::from)
            .chain([
                Value::Float(ladder::JITTER_SHARE),
                Value::Float(power::MIN_SLEEP_SECONDS),
            ])
            .collect(),
        )),
        // quiet
        "quiet.window" => Ok(match quiet::window(a.get(0)) {
            Some((start, end, days)) => Value::Array(vec![
                Value::from(start),
                Value::from(end),
                Value::Array(days.into_iter().map(Value::from).collect()),
            ]),
            None => Value::Null,
        }),
        "quiet.quiet_until" => {
            quiet::quiet_until(a.get(0), a.get(1), &Clock::of(a.get(2))).map(option)
        }
        "quiet.postpone_time" => {
            quiet::postpone_time(a.get(0), a.get(1), &Clock::of(a.get(2))).map(option)
        }
        "quiet.postponement_problem" => {
            quiet::postponement_problem(a.get(0), a.get(1), a.get(2)).map(option)
        }
        "quiet.zone" => {
            let zone = Clock::of(a.get(1));
            match a.get(0) {
                Value::Array(parts) if parts.len() == 6 => {
                    let n = |at: usize| match &parts[at] {
                        Value::Int(n) => n.as_i64().unwrap_or(0),
                        _ => 0,
                    };
                    zone.mktime(n(0), n(1), n(2), n(3), n(4), n(5))
                        .map(Value::Float)
                }
                // A bool is the number it is, as `time.localtime(True)` reads it.
                Value::Bool(on) => zone.localtime(f64::from(u8::from(*on))).map(|tm| {
                    Value::Array(
                        [tm.year, tm.mon, tm.mday, tm.hour, tm.min, tm.sec, tm.wday]
                            .into_iter()
                            .map(Value::from)
                            .collect(),
                    )
                }),
                other => zone.localtime(float(other)).map(|tm| {
                    Value::Array(
                        [tm.year, tm.mon, tm.mday, tm.hour, tm.min, tm.sec, tm.wday]
                            .into_iter()
                            .map(Value::from)
                            .collect(),
                    )
                }),
            }
        }
        // projects
        "projects.normal_folder" => Ok(option(projects::normal_folder(a.get(0)))),
        "projects.key_for" => Ok(option(projects::key_for(a.get(0), a.get(1)))),
        "projects.is_key" => Ok(Value::Bool(projects::is_key(a.get(0)))),
        "projects.parse_keys" => Ok(match projects::parse_keys(a.get(0)) {
            Some(keys) => Value::Array(keys.into_iter().map(Value::from).collect()),
            None => Value::Null,
        }),
        "projects.format_keys" => {
            let keys: Vec<String> = match a.get(0) {
                Value::Array(items) => items
                    .iter()
                    .filter_map(car_policy::classify::value::text)
                    .map(str::to_owned)
                    .collect(),
                _ => Vec::new(),
            };
            Ok(Value::from(projects::format_keys(&keys)))
        }
        "projects.coerce_keys" => Ok(projects::coerce_keys(a.get(0), a.get(1))),
        "projects.asks" => Ok(Value::Bool(projects::asks(a.get(0)))),
        "projects.allows" => Ok(Value::Bool(projects::allows(a.get(0), a.get(1)))),
        "projects.hold_for" => Ok(option(projects::hold_for(a.get(0), a.get(1)))),
        "projects.rule" => projects::rule(a.get(0), a.get(1), a.flag(2)),
        // needs you
        "needsyou.told" => Ok(Value::Bool(needsyou::told(a.get(0)))),
        "needsyou.kinds" => {
            let mut found = needsyou::kinds(a.get(0));
            found.sort_unstable();
            Ok(words(&found))
        }
        "needsyou.stall_seconds" => Ok(option(needsyou::stall_seconds(a.get(0)))),
        "needsyou.minutes" => needsyou::minutes(a.get(0)).map(|n| Value::from(n as i64)),
        "needsyou.tables" => {
            let fields: Vec<Value> = needsyou::KINDS
                .iter()
                .map(|kind| {
                    Value::Array(vec![
                        Value::from(*kind),
                        option(needsyou::kind_field(kind)),
                        option(needsyou::next_step(kind)),
                    ])
                })
                .collect();
            Ok(Value::Array(vec![
                Value::Array(fields),
                option(needsyou::next_step(needsyou::STALLED)),
            ]))
        }
        // power
        "power.keep_awake" => Ok(Value::from(power::keep_awake(a.get(0)))),
        "power.awake_cap" => Ok(option(power::awake_cap(a.get(0)))),
        "power.sleep_threshold" => Ok(option(power::sleep_threshold(a.get(0)))),
        "power.waits_for_network" => Ok(Value::Bool(power::waits_for_network(a.get(0)))),
        "power.listens" => Ok(Value::Bool(power::listens(a.get(0)))),
        "power.asleep" => power::asleep(a.get(0), a.get(1)).map(Value::Float),
        "power.fell_due" => power::fell_due(a.get(0), a.get(1), a.get(2)).map(Value::Bool),
        "power.waiting" => power::waiting(a.get(0)).map(Value::from),
        "power.wants_awake" => power::wants_awake(a.get(0), a.get(1), a.get(2)).map(Value::Bool),
        // permits
        "permits.permits" => {
            let (allowed, reason) =
                permits::permits(a.get(0), a.get(1), a.get(2), a.get(3), a.get(4), a.get(5));
            Ok(Value::Array(vec![
                Value::Bool(allowed),
                Value::from(reason),
            ]))
        }
        // ownvalues and the plug's words (S2.2's, which the classifier reads)
        "own.amount" => Ok(measured(ownvalues::amount(&spec(a.get(0)), a.get(1)))),
        "own.canonical" => {
            let choices: Vec<&str> = match a.get(2) {
                Value::Array(items) => items
                    .iter()
                    .filter_map(car_policy::classify::value::text)
                    .collect(),
                _ => Vec::new(),
            };
            Ok(option(ownvalues::canonical(
                Some(&spec(a.get(0))),
                a.get(1),
                &choices,
            )))
        }
        "own.plug" => Ok(Value::Array(vec![
            words(TAKE_UP),
            Value::Object(match &PACED_AS {
                vocab::Node::Map(pairs) => pairs
                    .iter()
                    .filter_map(|(word, kind)| Some(((*word).into(), Value::from(kind.as_str()?))))
                    .collect(),
                _ => Map::new(),
            }),
        ])),
        "text.tables_version" => Ok(Value::from(text::UNICODE)),
        _ => return None,
    })
}
