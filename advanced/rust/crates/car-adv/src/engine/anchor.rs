//! Start the 5-hour window early (`window_anchor`, v0.6.20), at P8 (seat S7.2e2, `engine/anchor.py`).
//!
//! Codex's 5-hour usage window starts at the first use, so a late first use gives a late reset. With this on, when the
//! 5-hour window is idle, the watcher sends one near-free request (MANCHOR's `codex exec ... "Reply with OK"`) so the
//! window starts now and its reset is fixed five hours on - at the times of day a person picked, right after a reset
//! it has seen, or both. This part holds the module's pure functions; the capability's code follows below them.

use car_machine::json::Value;
use car_machine::localclock::LocalClock;
use car_machine::pyval::Py;

use super::supervise::{field, word};
use crate::state::sql;
use crate::vocabulary::OptionKey;

pub const CAPABILITY: &str = "window_anchor";
pub const FIVE_HOUR: i64 = 300;
pub const WEEKLY: i64 = 10080;
pub const WINDOW_SECONDS: i64 = FIVE_HOUR * 60;
pub const DAY: i64 = 86400;
pub const STEADY_GAP: f64 = 20.0;
pub const OFFSET_TOLERANCE: f64 = 120.0;
pub const DRIFT_TOLERANCE: f64 = 5.0;
pub const SLOT_GRACE: i64 = 1800;
pub const AFTER_RESET: i64 = 60;
pub const LEARN_EVERY: f64 = 1800.0;
pub const LOOK_EVERY: f64 = 15.0;
pub const RETRY_EVERY: f64 = 300.0;
pub const TIMEOUT: f64 = 120.0;
pub const KILL_WAIT: f64 = 10.0;
pub const TIME_OFF: i64 = 1;
pub const TIME_SHIFT: i64 = 2;
pub const TIME_RANGE: (i64, i64) = (TIME_OFF, 1439 + TIME_SHIFT);
pub const TIME_OPTIONS: [OptionKey; 3] = [OptionKey::AnchorAt1, OptionKey::AnchorAt2, OptionKey::AnchorAt3];
/// wrapwords' ON: Start right after a reset, on.
pub const ON: i64 = 1;
pub const PROMPT: &str = "Reply with OK";
pub const EXEC_ARGUMENTS: [&str; 9] = [
    "exec",
    "--skip-git-repo-check",
    "--ephemeral",
    "--json",
    "-s",
    "read-only",
    "-c",
    "model_reasoning_effort=\"low\"",
    PROMPT,
];
pub const QUIET_ARGUMENTS: [&str; 8] = [
    "-c",
    "notify=[]",
    "--disable",
    "hooks",
    "--disable",
    "plugins",
    "--disable",
    "apps",
];
pub const REFUSALS: [&str; 2] = [
    "Error loading config.toml: invalid transport",
    "Error: Unknown feature flag",
];
pub const FOLDER: &str = "anchor-cwd";
pub const IDLE: &str = "idle";
pub const RUNNING: &str = "running";
pub const WEEKLY_FULL: &str = "weekly";
pub const UNREADABLE: &str = "unreadable";
pub const LOG_PREFIX: &str = "window anchor: ";

/// `TIME_CHOICES`: off, then every half hour of the day.
pub fn time_choices() -> Vec<i64> {
    std::iter::once(TIME_OFF)
        .chain((0..1440).step_by(30).map(|minute| minute + TIME_SHIFT))
        .collect()
}

// ---------------------------------------------------------------------------------------------- pure
fn int(value: &Value) -> Option<i64> {
    match value {
        Value::Int(number) => number.as_i64(),
        _ => None,
    }
}

/// `encode_time(hour, minute)`.
pub fn encode_time(hour: &Value, minute: &Value) -> Option<i64> {
    let (hour, minute) = (int(hour)?, int(minute)?);
    ((0..24).contains(&hour) && (0..60).contains(&minute)).then_some(hour * 60 + minute + TIME_SHIFT)
}

/// `decode_time(value)`: the minute of the day a time option holds, or None.
pub fn decode_time(value: &Value) -> Option<i64> {
    let value = int(value)?;
    (TIME_SHIFT..=TIME_RANGE.1).contains(&value).then_some(value - TIME_SHIFT)
}

/// `clock_text(value)`: HH:MM, "" for off.
pub fn clock_text(value: &Value) -> String {
    decode_time(value).map_or(String::new(), |minute| format!("{:02}:{:02}", minute / 60, minute % 60))
}

/// `picked(options)`: the minutes of the day of the times picked, each once, in order.
pub fn picked(options: &Value) -> Vec<i64> {
    let mut found: Vec<i64> = TIME_OPTIONS
        .iter()
        .filter_map(|key| decode_time(field(options, key.as_str())))
        .collect();
    found.sort_unstable();
    found.dedup();
    found
}

/// `after_reset_on(options)`: on unless a person turned it off (a missing value is on).
pub fn after_reset_on(options: &Value) -> bool {
    let found = match options {
        Value::Object(map) => map.get(OptionKey::AnchorAfterReset.as_str()).cloned(),
        _ => None,
    };
    sql::py_eq(&found.unwrap_or(Value::Int(ON.into())), &Value::Int(ON.into()))
}

/// `int(now)`: a float truncated toward zero; a NaN is a ValueError, an infinity an OverflowError.
pub fn whole(now: f64) -> Py<i64> {
    if now.is_nan() {
        return Err("ValueError");
    }
    if now.is_infinite() {
        return Err("OverflowError");
    }
    Ok(now.trunc() as i64)
}

/// `midnight(now, local)`.
pub fn midnight(now: f64, local: &dyn LocalClock) -> Py<i64> {
    let moment = local.localtime(whole(now)? as f64)?;
    Ok(whole(now)? - (moment.hour * 3600 + moment.min * 60 + moment.sec))
}

/// `occurrence(now, days, minute, local, mktime)`: by the calendar, so across a daylight-saving change it is still that
/// time on the clock.
pub fn occurrence(now: f64, days: i64, minute: i64, local: &dyn LocalClock) -> Py<i64> {
    let moment = local.localtime(whole(now)? as f64)?;
    let made = local.mktime(
        moment.year,
        moment.mon,
        moment.mday + days,
        minute.div_euclid(60),
        minute.rem_euclid(60),
        0,
    )?;
    whole(made)
}

/// `found > done` for a stamp that is an int or None (anything else: the reference's TypeError).
fn after(found: i64, done: &Value) -> Py<bool> {
    match done {
        Value::Null => Ok(true),
        Value::Int(number) => Ok(number.as_i64().is_some_and(|done| found > done)),
        Value::Float(number) => Ok((found as f64) > *number),
        Value::Bool(flag) => Ok(found > i64::from(*flag)),
        _ => Err("TypeError"),
    }
}

/// `slot_due(options, now, done)`: the latest occurrence of a time picked that is due now, or None.
pub fn slot_due(options: &Value, now: f64, done: &Value, local: &dyn LocalClock) -> Py<Option<i64>> {
    let mut due: Option<i64> = None;
    for minute in picked(options) {
        for days in [0, -1] {
            let found = occurrence(now, days, minute, local)?;
            if (found as f64) <= now && now < (found + SLOT_GRACE) as f64 && after(found, done)? {
                due = Some(due.map_or(found, |due| due.max(found)));
            }
        }
    }
    Ok(due)
}

/// `reset_due(options, now, seen, done)`: the reset seen that is due now, or None.
pub fn reset_due(options: &Value, now: f64, seen: &Value, done: &Value) -> Py<Option<i64>> {
    let Some(seen) = int(seen) else {
        return Ok(None);
    };
    if !after_reset_on(options) || now < (seen + AFTER_RESET) as f64 {
        return Ok(None);
    }
    if !matches!(done, Value::Null) && !after(seen, done)? {
        return Ok(None);
    }
    Ok(Some(seen))
}

/// `next_due(options, now, slot_done, seen, reset_done)`: the earliest occasion still to come, or None.
pub fn next_due(
    options: &Value,
    now: f64,
    slot_done: &Value,
    seen: &Value,
    reset_done: &Value,
    local: &dyn LocalClock,
) -> Py<Option<i64>> {
    let mut found: Vec<i64> = Vec::new();
    for minute in picked(options) {
        for days in [0, 1] {
            let at = occurrence(now, days, minute, local)?;
            if (at as f64) > now && int(slot_done).is_none_or(|done| at > done) {
                found.push(at);
            }
        }
    }
    if after_reset_on(options)
        && let Some(seen) = int(seen)
        && int(reset_done).is_none_or(|done| seen > done)
        && ((seen + AFTER_RESET) as f64) > now
    {
        found.push(seen + AFTER_RESET);
    }
    Ok(found.into_iter().min())
}

/// `for window in windows or ()`, the dicts among them; a truthy value that cannot be iterated is a TypeError.
fn rows(windows: &Value) -> Py<Vec<&Value>> {
    match windows {
        Value::Array(items) => Ok(items.iter().filter(|each| matches!(each, Value::Object(_))).collect()),
        Value::Object(_) | Value::Str(_) => Ok(Vec::new()),
        other if !sql::truthy(other) => Ok(Vec::new()),
        _ => Err("TypeError"),
    }
}

/// `windows_of(windows)`: (the 5-hour window, the weekly window) of one reading, the `codex` bucket's else `legacy`.
pub fn windows_of(windows: &Value) -> Py<(Option<Value>, Option<Value>)> {
    let rows = rows(windows)?;
    for bucket in ["codex", "legacy"] {
        let mine: Vec<&Value> = rows
            .iter()
            .copied()
            .filter(|window| *field(window, "bucket") == word(bucket))
            .collect();
        let minutes = |window: &&Value, wanted: i64| sql::py_eq(field(window, "window_minutes"), &Value::Int(wanted.into()));
        if let Some(five) = mine.iter().find(|window| minutes(window, FIVE_HOUR)) {
            let weekly = mine.iter().find(|window| minutes(window, WEEKLY));
            return Ok((Some((*five).clone()), weekly.map(|each| (*each).clone())));
        }
    }
    Ok((None, None))
}

/// `(reading or {}).get(name)`: a falsy reading is `{}`; a truthy one that is not a dict raises AttributeError.
fn reading_get<'a>(reading: &'a Value, name: &str) -> Py<&'a Value> {
    match reading {
        Value::Object(_) => Ok(field(reading, name)),
        other if !sql::truthy(other) => Ok(field(&Value::Null, name)),
        _ => Err("AttributeError"),
    }
}

/// `dictionary[key]`: KeyError where it is missing.
fn item<'a>(value: &'a Value, key: &str) -> Py<&'a Value> {
    match value {
        Value::Object(map) => map.get(key).ok_or("KeyError"),
        _ => Err("TypeError"),
    }
}

/// A number as Python compares it (`bool` is one); anything else cannot be ordered against a number.
fn numeric(value: &Value) -> Py<f64> {
    match value {
        Value::Bool(flag) => Ok(f64::from(u8::from(*flag))),
        Value::Int(number) => Ok(number.as_i64().map_or(f64::INFINITY, |n| n as f64)),
        Value::Float(number) => Ok(*number),
        _ => Err("TypeError"),
    }
}

/// `running_reset(reading, now)`: the reset ahead of a 5-hour window this reading shows running, or None.
pub fn running_reset(reading: &Value, now: f64) -> Py<Option<i64>> {
    let (five, _weekly) = windows_of(reading_get(reading, "windows")?)?;
    let Some(five) = five else {
        return Ok(None);
    };
    let Some(reset) = int(field(&five, "reset_at")) else {
        return Ok(None);
    };
    if !(numeric(item(&five, "used_percent")?)? > 0.0) {
        return Ok(None);
    }
    Ok(((reset as f64) > now).then_some(reset))
}

/// `judge(first, second)`: what two readings at least STEADY_GAP apart say of the 5-hour window.
pub fn judge(first: &Value, second: &Value) -> Py<&'static str> {
    let mut found: Vec<(f64, Value)> = Vec::new();
    for reading in [first, second] {
        let (five, weekly) = windows_of(reading_get(reading, "windows")?)?;
        let at = reading_get(reading, "at")?;
        let (Some(five), Some(at)) = (five, super::supervise::number(at)) else {
            return Ok(UNREADABLE);
        };
        if let Some(weekly) = weekly
            && numeric(item(&weekly, "used_percent")?)? >= 100.0
        {
            return Ok(WEEKLY_FULL);
        }
        found.push((at, five));
    }
    let (at1, five1) = &found[0];
    let (at2, five2) = &found[1];
    if numeric(item(five1, "used_percent")?)? > 0.0 || numeric(item(five2, "used_percent")?)? > 0.0 {
        return Ok(RUNNING);
    }
    let (reset1, reset2) = (item(five1, "reset_at")?, item(five2, "reset_at")?);
    let (Some(reset1), Some(reset2)) = (int(reset1), int(reset2)) else {
        return Ok(UNREADABLE);
    };
    if at2 - at1 < STEADY_GAP {
        return Ok(UNREADABLE);
    }
    let window = WINDOW_SECONDS as f64;
    let steady = [(*at1, reset1), (*at2, reset2)]
        .iter()
        .all(|(at, reset)| (((*reset as f64) - at) - window).abs() <= OFFSET_TOLERANCE);
    let moving = ((reset2 - reset1) as f64) >= (at2 - at1) - DRIFT_TOLERANCE;
    Ok(if steady && moving { IDLE } else { RUNNING })
}

/// `signed_in(reply)`: whether account/read names a signed-in account, or None where it did not answer as one.
pub fn signed_in(reply: &Value) -> Option<bool> {
    match reply {
        Value::Object(map) if map.contains_key("account") => {
            Some(matches!(field(reply, "account"), Value::Object(_)))
        }
        _ => None,
    }
}

/// `str.splitlines()`.
pub fn splitlines(text: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = text.char_indices().peekable();
    while let Some((index, c)) = chars.next() {
        let end = match c {
            '\r' => {
                if let Some((_, '\n')) = chars.peek() {
                    chars.next();
                    Some(index + 2)
                } else {
                    Some(index + 1)
                }
            }
            '\n' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}' => {
                Some(index + c.len_utf8())
            }
            _ => None,
        };
        if let Some(end) = end {
            lines.push(&text[start..index]);
            start = end;
        }
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}

/// The JSON events among what `codex exec --json` printed: each line stripped, those that start with "{" and parse.
fn events(printed: &str) -> Vec<Value> {
    splitlines(printed)
        .into_iter()
        .map(car_machine::pytext::strip)
        .filter(|line| line.starts_with('{'))
        .filter_map(|line| car_machine::compat::loads(line).ok())
        .collect()
}

/// `tokens_of(printed)`: the token counts of the request's `turn.completed` event.
pub fn tokens_of(printed: &str) -> [Option<i64>; 3] {
    let mut found = [None, None, None];
    for event in events(printed) {
        if *field(&event, "type") != word("turn.completed") {
            continue;
        }
        let usage = field(&event, "usage");
        if !matches!(usage, Value::Object(_)) {
            continue;
        }
        for (slot, name) in ["input_tokens", "cached_input_tokens", "output_tokens"].iter().enumerate() {
            found[slot] = int(field(usage, name)).filter(|value| (0..1_000_000_000).contains(value));
        }
    }
    found
}

/// `thread_started(printed)`: whether a `thread.started` event is there.
pub fn thread_started(printed: &str) -> bool {
    events(printed)
        .iter()
        .any(|event| *field(event, "type") == word("thread.started"))
}

/// `refused(errors)`: whether stderr carries one of REFUSALS.
pub fn refused(errors: &str) -> bool {
    REFUSALS.iter().any(|words| errors.contains(words))
}

/// `_toml_key(name)`: a name as a TOML basic string (json.dumps, ensure_ascii off; DEL escaped).
pub fn toml_key(name: &Value) -> String {
    car_machine::json::to_string(name, &car_machine::json::Options::new().ensure_ascii(false))
        .unwrap_or_default()
        .replace('\x7f', "\\u007f")
}

/// `servers_off(names)`: the one `-c` value that turns each named server off, or None for no names.
pub fn servers_off(names: &[Value]) -> Option<String> {
    if names.is_empty() {
        return None;
    }
    let parts: Vec<String> = names
        .iter()
        .map(|name| format!("{}={{enabled=false}}", toml_key(name)))
        .collect();
    Some(format!("mcp_servers={{{}}}", parts.join(",")))
}

/// `tokens_said(tokens)`: the request's token counts as the log line says them.
pub fn tokens_said(tokens: &Value) -> String {
    let said = |key: &str| match field(tokens, key) {
        Value::Int(number) => number.to_string(),
        _ => "?".to_owned(),
    };
    format!(
        "{} input tokens ({} cached), {} output",
        said("input"),
        said("cached"),
        said("output")
    )
}

/// `_hhmm(at, local)`.
pub fn hhmm(at: f64, local: &dyn LocalClock) -> Py<String> {
    let moment = local.localtime(whole(at)? as f64)?;
    Ok(format!("{:02}:{:02}", moment.hour, moment.min))
}

/// `make(paths)`: until the capability's code is ported below, none.
pub fn make(_paths: &car_config::Paths) -> Option<Box<dyn crate::capabilities::Code>> {
    None
}
