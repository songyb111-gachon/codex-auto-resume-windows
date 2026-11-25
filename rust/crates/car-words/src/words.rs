//! `ui/words.py`: words every surface writes the same way: a remaining time, and the usage reading's sentences.
//!
//! Locale-neutral where it can be: digits and a colon read the same in every language. The sentences that are
//! not (the usage line) are said through `say`, the catalog lookup the caller holds (`l10n::text` in a locale), so
//! the popup, the window and the panel say one example one way (`tests/test_usage_reading.py`).

use std::cmp::Ordering;

use car_machine::json::{Int, Value};
use car_machine::pytext::{self, py_str};
use car_machine::pyval::{self, Num, Py};

/// `say(key, **fields)`: one sentence of the catalog, formatted. Fields keep the order the sentence is filled in.
pub type Say<'a> = &'a dyn Fn(&str, &[(&str, String)]) -> String;

/// A moment as the clock shows it where the person is: year, month, day, hour, minute.
pub type Tm = (i64, i64, i64, i64, i64);

pub const WEEK_MINUTES: i64 = 7 * 24 * 60;
/// At or under this much left a window reads as a warning.
pub const LOW_LEFT: i64 = 10;

/// A non-negative Python int, `max(0, int(x))`, as its decimal digits (`"0"` for zero): Python's int has no
/// bound, so `countdown(1e300)` writes every one of its 301 digits of hours.
struct Whole(String);

impl Whole {
    /// `max(0, int(value))`: a bool or an int as it is, a float truncated toward zero (a NaN is a ValueError, an
    /// infinity an OverflowError), a text as `int(text)` reads it (white space, a sign, underscores between digits
    /// and any script's decimal digits; past 4,300 digits a ValueError); anything else a TypeError.
    fn of(value: &Value) -> Py<Whole> {
        let (negative, digits) = match value {
            Value::Bool(on) => (false, u8::from(*on).to_string()),
            Value::Int(int) => {
                let text = int.to_string();
                match text.strip_prefix('-') {
                    Some(rest) => (true, rest.to_owned()),
                    None => (false, text),
                }
            }
            Value::Float(x) => {
                if x.is_nan() {
                    return Err("ValueError");
                }
                if x.is_infinite() {
                    return Err("OverflowError");
                }
                // `{:.0}` of a whole f64 writes its exact digits.
                let text = format!("{:.0}", x.trunc().abs());
                (x.is_sign_negative(), text)
            }
            Value::Str(text) => {
                let text = text.as_str().ok_or("ValueError")?;
                pytext::parse_int(text, 10).ok_or("ValueError")?;
                let digits: String = text
                    .chars()
                    .filter_map(|c| pytext::decimal_value(c).and_then(|d| char::from_digit(d, 10)))
                    .collect();
                if digits.len() > 4300 {
                    return Err("ValueError");
                }
                let negative = pytext::strip(text).starts_with('-');
                (negative, digits)
            }
            _ => return Err("TypeError"),
        };
        let digits = digits.trim_start_matches('0');
        Ok(Whole(if negative || digits.is_empty() {
            "0".to_owned()
        } else {
            digits.to_owned()
        }))
    }

    /// The value, where it fits a u64.
    fn small(&self) -> Option<u64> {
        self.0.parse().ok()
    }

    /// `divmod(self, by)`.
    fn divmod(&self, by: u64) -> (Whole, u64) {
        let mut quotient = String::with_capacity(self.0.len());
        let mut rest: u128 = 0;
        for digit in self.0.bytes() {
            rest = rest * 10 + u128::from(digit - b'0');
            let place = rest / u128::from(by);
            rest %= u128::from(by);
            if !(quotient.is_empty() && place == 0) {
                quotient.push(char::from(b'0' + place as u8));
            }
        }
        if quotient.is_empty() {
            quotient.push('0');
        }
        (Whole(quotient), rest as u64)
    }
}

/// `countdown(seconds)`: a short, locale-neutral duration: `45s`, `12:04`, `3:05:00`.
pub fn countdown(seconds: &Value) -> Py<String> {
    let seconds = Whole::of(seconds)?;
    let (hours, rest) = seconds.divmod(3600);
    let (minutes, secs) = (rest / 60, rest % 60);
    Ok(if hours.0 != "0" {
        format!("{}:{minutes:02}:{secs:02}", hours.0)
    } else if minutes > 0 {
        format!("{minutes}:{secs:02}")
    } else {
        format!("{secs}s")
    })
}

/// `age(seconds, say)`: how long ago, in the largest unit that is not zero.
pub fn age(seconds: &Value, say: Say) -> Py<String> {
    let total = Whole::of(seconds)?;
    let Some(small) = total.small() else {
        // Past a u64 only the days are named.
        let count = say("time.days", &[("n", total.divmod(86400).0.0)]);
        return Ok(say("time.ago", &[("time", count)]));
    };
    if small < 5 {
        return Ok(say("time.just_now", &[]));
    }
    for (limit, key, unit) in [
        (Some(60), "time.seconds", 1),
        (Some(3600), "time.minutes", 60),
        (Some(86400), "time.hours", 3600),
        (None, "time.days", 86400),
    ] {
        if limit.is_none_or(|limit| small < limit) {
            let count = say(key, &[("n", (small / unit).to_string())]);
            return Ok(say("time.ago", &[("time", count)]));
        }
    }
    Ok(say("time.just_now", &[]))
}

/// `clock_time(at, now)`: a moment later today as the clock shows it, and any other with its date. The broken-down
/// local times are the caller's (`time.localtime`, which is the platform's clock and time zone).
pub fn clock_time(moment: Tm, today: Tm) -> String {
    if (moment.0, moment.1, moment.2) == (today.0, today.1, today.2) {
        format!("{:02}:{:02}", moment.3, moment.4)
    } else {
        format!(
            "{:04}-{:02}-{:02} {:02}:{:02}",
            moment.0, moment.1, moment.2, moment.3, moment.4
        )
    }
}

/// `window_name(minutes, say)`: how a usage window's length is named: weekly, or in days, hours or minutes - "limit"
/// when Codex gave no length.
pub fn window_name(minutes: &Value, say: Say) -> String {
    let Value::Int(int) = minutes else {
        return say("usage.limit", &[]);
    };
    let Some(minutes) = int.as_i64().filter(|each| *each > 0) else {
        return say("usage.limit", &[]);
    };
    if minutes == WEEK_MINUTES {
        return say("usage.weekly", &[]);
    }
    for (size, key) in [(1440, "usage.days"), (60, "usage.hours")] {
        if minutes % size == 0 {
            return say(key, &[("n", (minutes / size).to_string())]);
        }
    }
    say("usage.minutes", &[("n", minutes.to_string())])
}

/// `share(window)`: the share used as a whole number, never rounded up to 100: 99.6% is not used up.
///
/// `100 if used >= 100 else int(used // 1)`: a NaN is not >= 100 and `int(nan)` is a ValueError; `-inf // 1` is a
/// NaN, so a ValueError too; an int is itself, of any size, and a float its exact floor.
pub fn share(window: &Value) -> Py<Int> {
    let used = pyval::get(window, "used_percent")?;
    let used = if pyval::truthy(used) {
        used.clone()
    } else {
        Value::from(0)
    };
    if matches!(
        pyval::order(&used, &Value::from(100))?,
        Some(Ordering::Greater | Ordering::Equal)
    ) {
        return Ok(Int::from(100));
    }
    match used {
        Value::Bool(on) => Ok(Int::from(i64::from(on))),
        Value::Int(int) => Ok(int),
        Value::Float(x) if x.is_finite() => {
            Int::parse(&format!("{:.0}", x.floor())).ok_or("ValueError")
        }
        Value::Float(_) => Err("ValueError"),
        _ => Err("TypeError"),
    }
}

/// `left(window)`: the share LEFT as a whole number, 0 to 100: `max(0, min(100, 100 - share(window)))`.
pub fn left(window: &Value) -> Py<i64> {
    let used = share(window)?;
    Ok(match used.as_i64() {
        Some(used) => (100 - i128::from(used)).clamp(0, 100) as i64,
        // Past an i64: a used share far below zero leaves 100, one far above leaves nothing.
        None if used.to_string().starts_with('-') => 100,
        None => 0,
    })
}

/// `usage_windows(windows, say, now, keep)`: each window of a reading: its length, the share left of it, and when it
/// resets where Codex said. `keep` is given each reset time before it goes into its sentence.
pub fn usage_windows(
    windows: &Value,
    say: Say,
    now: &Value,
    local: &dyn Fn(f64) -> Tm,
    keep: &dyn Fn(&str) -> String,
) -> Py<String> {
    let mut parts = Vec::new();
    let empty = Vec::new();
    let listed = match windows {
        Value::Array(items) => items,
        Value::Null => &empty,
        _ => return Err("TypeError"),
    };
    let today = Num::of(now).ok_or("TypeError")?.as_f64();
    for window in listed {
        let name = window_name(pyval::get(window, "window_minutes")?, say);
        let reset = pyval::get(window, "reset_at")?;
        let percent = left(window)?.to_string();
        if pyval::truthy(reset) {
            let at = Num::of(reset).ok_or("TypeError")?.as_f64();
            let time = keep(&clock_time(local(at), local(today)));
            parts.push(say(
                "usage.window_resets",
                &[("window", name), ("percent", percent), ("time", time)],
            ));
        } else {
            parts.push(say(
                "usage.window",
                &[("window", name), ("percent", percent)],
            ));
        }
    }
    Ok(parts.join(" \u{b7} "))
}

/// `usage_line(reading, say, now, keep)`: the last usage reading as one line, with its age - or `None` when there is none.
pub fn usage_line(
    reading: &Value,
    say: Say,
    now: &Value,
    local: &dyn Fn(f64) -> Tm,
    keep: &dyn Fn(&str) -> String,
) -> Py<Option<String>> {
    let Value::Object(map) = reading else {
        return Ok(None);
    };
    let windows = map.get("windows").unwrap_or(&Value::Null);
    let read_at = map.get("read_at").unwrap_or(&Value::Null);
    if !pyval::truthy(windows) || !pyval::truthy(read_at) {
        return Ok(None);
    }
    let how_long = Value::Float(pyval::minus(now, read_at)?);
    let ago = age(&how_long, say)?;
    let lines = usage_windows(windows, say, now, local, keep)?;
    Ok(Some(say("usage.line", &[("age", ago), ("windows", lines)])))
}

/// `str(value)` for the one place a window's number is shown: kept here so the harness and the callers agree.
pub fn shown(value: &Value) -> String {
    py_str(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_machine::json::from_str;

    fn v(text: &str) -> Value {
        from_str(text).unwrap()
    }

    #[test]
    fn countdowns() {
        assert_eq!(countdown(&v("45")).unwrap(), "45s");
        assert_eq!(countdown(&v("724.9")).unwrap(), "12:04");
        assert_eq!(countdown(&v("11100")).unwrap(), "3:05:00");
        assert_eq!(countdown(&v("-5")).unwrap(), "0s");
    }

    #[test]
    fn shares() {
        assert_eq!(
            share(&v("{\"used_percent\": 99.6}")).unwrap(),
            Int::from(99)
        );
        assert_eq!(left(&v("{\"used_percent\": 99.6}")).unwrap(), 1);
        assert_eq!(left(&v("{\"used_percent\": 250}")).unwrap(), 0);
        assert_eq!(left(&v("{}")).unwrap(), 100);
        assert_eq!(left(&v("{\"used_percent\": -0.5}")).unwrap(), 100);
    }

    #[test]
    fn clocks() {
        assert_eq!(
            clock_time((2026, 11, 25, 9, 5), (2026, 11, 25, 1, 1)),
            "09:05"
        );
        assert_eq!(
            clock_time((2026, 11, 26, 9, 5), (2026, 11, 25, 1, 1)),
            "2026-11-26 09:05"
        );
    }
}
