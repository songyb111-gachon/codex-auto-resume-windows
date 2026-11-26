//! `engine/wrapwords.py` (seat S7.2d): the wrap-up's words - what usage_wrap_up sends, exactly.
//!
//! A person picks the wording (`wrap_style`): 1 short, 2 standard, 3 detailed, 4 with the numbers, or 5 Custom - the
//! person's own text for each window, checked as the custom continuation text is ([`check_custom`]), which gets the
//! numbers and the reset only where it writes `{percent}`, `{window}`, `{stop_at}` or `{reset}`. Every wording is in the
//! continuation language. [`render`] is the one place the words are made, so what the page shows under the choice is what
//! is sent.
//!
//! What the reference lets out of `render` is kept: a catalog that is not UTF-8 (`UnicodeDecodeError`), `int(used)` of an
//! infinity (`OverflowError`) and a missing reset sentence (`TypeError`, `str + None`) are raised, not answered None.

use car_machine::json::Value;
use car_machine::localclock::LocalClock;

use crate::statement::Catalogs;

pub const FIVE_HOUR: i64 = 300;
pub const WEEKLY: i64 = 10080;
/// `STYLE_KEYS`, by style.
pub const STYLE_KEYS: [(i64, &str); 4] = [
    (1, "continue.wrap_up.short"),
    (2, "continue.wrap_up.standard"),
    (3, "continue.wrap_up.detailed"),
    (4, "continue.wrap_up.numbers"),
];
pub const CUSTOM_STYLE: i64 = 5;
pub const STYLES: [i64; 5] = [1, 2, 3, 4, 5];
pub const DEFAULT_STYLE: i64 = 2;
/// The placeholders Custom text may write - and nothing else in braces.
pub const PLACEHOLDERS: [&str; 4] = ["percent", "window", "stop_at", "reset"];
pub const WINDOW_KEYS: [(i64, &str); 2] = [
    (FIVE_HOUR, "continue.wrap_up.window.five_hour"),
    (WEEKLY, "continue.wrap_up.window.weekly"),
];
pub const RESET_KEYS: [(i64, &str); 2] = [
    (FIVE_HOUR, "continue.wrap_up.resets_at"),
    (WEEKLY, "continue.wrap_up.resets_on"),
];
pub const DATE_KEY: &str = "continue.wrap_up.date";
/// A switch's two values, as every on/off choice of these capabilities stores it.
pub const ON: i64 = 1;
pub const OFF: i64 = 2;
pub const SWITCH: [i64; 2] = [ON, OFF];

/// What [`render`] reads beside its arguments: the edition's catalogs and the local clock (`time.localtime`).
pub struct Words<'a> {
    pub catalogs: &'a Catalogs,
    pub clock: &'a dyn LocalClock,
}

/// What the reference raises out of `render` (the exception's class).
pub type Raise = &'static str;

/// `value == number` as Python compares a JSON value with an int (`True == 1`, `300.0 == 300`).
pub fn num_eq(value: &Value, number: i64) -> bool {
    match value {
        Value::Bool(flag) => i64::from(*flag) == number,
        Value::Int(int) => int.as_i64() == Some(number),
        Value::Float(x) => *x == number as f64,
        _ => false,
    }
}

/// A dict keyed by ints, looked up as Python looks up `value` (by equal hash: `1`, `1.0` and `True` are one key).
pub fn lookup(table: &[(i64, &'static str)], value: &Value) -> Option<&'static str> {
    table
        .iter()
        .find(|(number, _)| num_eq(value, *number))
        .map(|(_, found)| *found)
}

/// `type(value) is int`: an int, never a bool.
pub fn is_int(value: &Value) -> bool {
    matches!(value, Value::Int(_))
}

/// Why a Custom wording is refused: one closed word.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WordingError {
    Empty,
    TooLong,
    Control,
    Marker,
    Placeholder,
}

impl WordingError {
    pub const fn code(self) -> &'static str {
        match self {
            WordingError::Empty => "empty",
            WordingError::TooLong => "too_long",
            WordingError::Control => "control",
            WordingError::Marker => "marker",
            WordingError::Placeholder => "placeholder",
        }
    }
}

/// `_PLACEHOLDER.sub(replace, text)` for `\{([^{}]*)\}`: every brace pair with no brace inside, replaced by what
/// `replace` makes of its inside, left to right.
fn substitute(text: &str, mut replace: impl FnMut(&str) -> String) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len());
    let mut at = 0;
    while at < chars.len() {
        if chars[at] == '{' {
            let mut end = at + 1;
            while end < chars.len() && chars[end] != '{' && chars[end] != '}' {
                end += 1;
            }
            if end < chars.len() && chars[end] == '}' {
                let inside: String = chars[at + 1..end].iter().collect();
                out.push_str(&replace(&inside));
                at = end + 1;
                continue;
            }
        }
        out.push(chars[at]);
        at += 1;
    }
    out
}

/// `check_custom(text)`: a person's Custom wording, unchanged, or why it is refused - text of 1 to
/// `MAX_CUSTOM_LENGTH` characters, not blank, no control character but a tab and the ends of a line, no marker of this
/// product's - and braces only around the four placeholders.
pub fn check_custom(text: &Value) -> Result<String, WordingError> {
    let Value::Str(held) = text else {
        return Err(WordingError::Empty);
    };
    let text = String::from_utf8_lossy(held.as_bytes()).into_owned();
    if car_machine::pytext::strip(&text).is_empty() {
        return Err(WordingError::Empty);
    }
    if text.chars().count() > car_policy::classify::continuation::MAX_CUSTOM_LENGTH {
        return Err(WordingError::TooLong);
    }
    if text
        .chars()
        .any(|c| ((c as u32) < 32 && !matches!(c, '\t' | '\n' | '\r')) || c == '\x7f')
    {
        return Err(WordingError::Control);
    }
    if text.contains(car_machine::vocab_gen::domain_ids::MARKER_PREFIX) {
        return Err(WordingError::Marker);
    }
    let rest = substitute(&text, |inside| {
        if PLACEHOLDERS.contains(&inside) {
            String::new()
        } else {
            "{".to_owned()
        }
    });
    if rest.contains('{') || rest.contains('}') {
        return Err(WordingError::Placeholder);
    }
    Ok(text)
}

fn catalog_text(
    words: &Words<'_>,
    key: &str,
    locale: Option<&str>,
    fields: &[(&str, String)],
) -> Result<Option<String>, Raise> {
    words
        .catalogs
        .text(key, locale, fields)
        .map_err(|_| crate::statement::Undecodable::CLASS)
}

/// `window_words(minutes, locale)`: how the words name the window of `minutes`.
pub fn window_words(
    words: &Words<'_>,
    minutes: &Value,
    locale: Option<&str>,
) -> Result<Option<String>, Raise> {
    match lookup(&WINDOW_KEYS, minutes) {
        None => Ok(None),
        Some(key) => catalog_text(words, key, locale, &[]),
    }
}

/// `reset_words(reset_at, minutes, locale)`: core's local hour and minute for the five-hour window, the date before it
/// for the weekly one - or None where the reset is not known.
pub fn reset_words(
    words: &Words<'_>,
    reset_at: &Value,
    minutes: &Value,
    locale: Option<&str>,
) -> Result<Option<String>, Raise> {
    if !is_int(reset_at) {
        return Ok(None);
    }
    let hour = car_policy::classify::continuation::format_reset_time(reset_at, words.clock);
    let Value::Str(hour) = hour else {
        return Ok(None);
    };
    let hour = String::from_utf8_lossy(hour.as_bytes()).into_owned();
    if !num_eq(minutes, WEEKLY) {
        return Ok(Some(hour));
    }
    let seconds = car_store::value::number(reset_at).unwrap_or(0.0);
    let moment = words.clock.localtime(seconds)?;
    catalog_text(
        words,
        DATE_KEY,
        locale,
        &[
            ("time", hour),
            ("month", moment.mon.to_string()),
            ("day", moment.mday.to_string()),
        ],
    )
}

/// `int(value)` as `render` takes it: the error is `TypeError`/`ValueError` (answered None) or `OverflowError` (raised).
fn py_int(value: &Value) -> Result<String, Raise> {
    match value {
        Value::Bool(flag) => Ok(i64::from(*flag).to_string()),
        Value::Int(int) => Ok(int.to_string()),
        Value::Float(x) if x.is_nan() => Err("ValueError"),
        Value::Float(x) if x.is_infinite() => Err("OverflowError"),
        Value::Float(x) => {
            let whole = x.trunc();
            Ok(if whole == 0.0 {
                "0".to_owned()
            } else {
                format!("{whole:.0}")
            })
        }
        Value::Str(text) => {
            let text = String::from_utf8_lossy(text.as_bytes()).into_owned();
            match car_machine::pytext::parse_int(&text, 10) {
                Some(parsed) => match parsed.magnitude {
                    Some(magnitude) if parsed.negative && magnitude != 0 => {
                        Ok(format!("-{magnitude}"))
                    }
                    Some(magnitude) => Ok(magnitude.to_string()),
                    None => Err("ValueError"),
                },
                None => Err("ValueError"),
            }
        }
        _ => Err("TypeError"),
    }
}

/// The words a style other than Custom stands for (`STYLE_KEYS.get(style, STYLE_KEYS[DEFAULT_STYLE])`, Custom read as
/// the default).
fn style_key(style: &Value) -> &'static str {
    let style = if num_eq(style, CUSTOM_STYLE) {
        Value::from(DEFAULT_STYLE)
    } else {
        style.clone()
    };
    lookup(&STYLE_KEYS, &style).unwrap_or(STYLE_KEYS[1].1)
}

/// What `render` is asked to make.
pub struct Ask<'a> {
    pub style: &'a Value,
    pub minutes: &'a Value,
    pub used: &'a Value,
    pub stop_at: &'a Value,
    pub locale: Option<&'a str>,
    pub reset_at: &'a Value,
    pub include_reset: bool,
    pub custom: &'a Value,
}

/// `render(style=, minutes=, used=, stop_at=, locale=, reset_at=None, include_reset=False, custom=None)`: the words
/// sent for a window at `used` percent, asking Codex to stop at `stop_at` percent - and, with `include_reset`, when
/// that window resets - or None where they cannot be made (a window this does not know, or words core would refuse
/// as a continuation).
pub fn render(words: &Words<'_>, ask: &Ask<'_>) -> Result<Option<String>, Raise> {
    let Some(window) = window_words(words, ask.minutes, ask.locale)? else {
        return Ok(None);
    };
    if !is_int(ask.stop_at) {
        return Ok(None);
    }
    let percent = match py_int(ask.used) {
        Ok(percent) => percent,
        Err("OverflowError") => return Err("OverflowError"),
        Err(_) => return Ok(None),
    };
    let stop_at = car_machine::pytext::py_str(ask.stop_at);
    let made: Option<String> = if num_eq(ask.style, CUSTOM_STYLE)
        && matches!(ask.custom, Value::Str(_))
    {
        let Ok(custom) = check_custom(ask.custom) else {
            return Ok(None);
        };
        let reset = reset_words(words, ask.reset_at, ask.minutes, ask.locale)?.unwrap_or_default();
        Some(substitute(&custom, |name| match name {
            "percent" => percent.clone(),
            "window" => window.clone(),
            "stop_at" => stop_at.clone(),
            _ => reset.clone(),
        }))
    } else {
        let fields = [
            ("percent", percent.clone()),
            ("window", window.clone()),
            ("stop_at", stop_at.clone()),
        ];
        let mut made = catalog_text(words, style_key(ask.style), ask.locale, &fields)?;
        let reset = if ask.include_reset {
            reset_words(words, ask.reset_at, ask.minutes, ask.locale)?
        } else {
            None
        };
        if let (Some(text), Some(reset)) = (made.as_ref(), reset)
            && !text.is_empty()
            && !reset.is_empty()
        {
            let key = lookup(&RESET_KEYS, ask.minutes).unwrap_or(RESET_KEYS[0].1);
            match catalog_text(words, key, ask.locale, &[("reset", reset)])? {
                Some(sentence) => made = Some(format!("{text} {sentence}")),
                None => return Err("TypeError"),
            }
        }
        made
    };
    let value = made.map_or(Value::Null, Value::from);
    Ok(car_policy::classify::continuation::validate_continuation(&value).ok())
}
