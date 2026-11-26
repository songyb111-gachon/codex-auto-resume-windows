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

// ---------------------------------------------------------------------------------------------- config.toml
/// `tomllib.loads` (tomli, TOML 1.0, as the reference interpreter ships it): every acceptance and refusal of the
/// reference's parser, keeping of a document only what `declared_servers` reads - each table's keys in their first
/// order, and whether a value is a table, an array, or anything else. No dependency: nothing in the locks reads TOML.
pub mod toml {
    /// A TOML value as far as the anchor reads it.
    #[derive(Debug, Clone)]
    pub enum Item {
        Table(Vec<(String, Item)>),
        Array(Vec<Item>),
        Other,
    }

    impl Item {
        pub fn get(&self, key: &str) -> Option<&Item> {
            match self {
                Item::Table(pairs) => pairs.iter().find(|(name, _)| name == key).map(|(_, item)| item),
                _ => None,
            }
        }
        fn get_mut(&mut self, key: &str) -> Option<&mut Item> {
            match self {
                Item::Table(pairs) => pairs.iter_mut().find(|(name, _)| name == key).map(|(_, item)| item),
                _ => None,
            }
        }
        fn insert(&mut self, key: &str, item: Item) {
            if let Item::Table(pairs) = self {
                pairs.push((key.to_owned(), item));
            }
        }
    }

    /// TOML's refusal (`TOMLDecodeError`).
    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub struct Refused;

    type Parsed<T> = Result<T, Refused>;

    fn ctrl(c: char) -> bool {
        (c as u32) < 32 || c as u32 == 127
    }
    fn bare(c: char) -> bool {
        c.is_ascii_alphanumeric() || c == '-' || c == '_'
    }

    #[derive(Default)]
    struct FlagNode {
        flags: [bool; 2],
        recursive: [bool; 2],
        nested: Vec<(String, FlagNode)>,
    }

    fn child<'a>(nodes: &'a mut Vec<(String, FlagNode)>, key: &str) -> &'a mut FlagNode {
        if let Some(index) = nodes.iter().position(|(name, _)| name == key) {
            return &mut nodes[index].1;
        }
        nodes.push((key.to_owned(), FlagNode::default()));
        &mut nodes.last_mut().expect("pushed").1
    }

    const FROZEN: usize = 0;
    const EXPLICIT_NEST: usize = 1;

    #[derive(Default)]
    struct Flags {
        root: Vec<(String, FlagNode)>,
        pending: Vec<(Vec<String>, usize)>,
    }

    impl Flags {
        fn finalize_pending(&mut self) {
            for (key, flag) in std::mem::take(&mut self.pending) {
                self.set(&key, flag, false);
            }
        }
        fn unset_all(&mut self, key: &[String]) {
            let mut nodes = &mut self.root;
            for part in &key[..key.len() - 1] {
                let Some(index) = nodes.iter().position(|(name, _)| name == part) else {
                    return;
                };
                nodes = &mut nodes[index].1.nested;
            }
            nodes.retain(|(name, _)| name != &key[key.len() - 1]);
        }
        fn set(&mut self, key: &[String], flag: usize, recursive: bool) {
            let mut nodes = &mut self.root;
            for part in &key[..key.len() - 1] {
                nodes = &mut child(nodes, part).nested;
            }
            let node = child(nodes, &key[key.len() - 1]);
            if recursive {
                node.recursive[flag] = true;
            } else {
                node.flags[flag] = true;
            }
        }
        fn is(&self, key: &[String], flag: usize) -> bool {
            if key.is_empty() {
                return false;
            }
            let mut nodes = &self.root;
            for part in &key[..key.len() - 1] {
                let Some((_, node)) = nodes.iter().find(|(name, _)| name == part) else {
                    return false;
                };
                if node.recursive[flag] {
                    return true;
                }
                nodes = &node.nested;
            }
            nodes
                .iter()
                .find(|(name, _)| name == &key[key.len() - 1])
                .is_some_and(|(_, node)| node.flags[flag] || node.recursive[flag])
        }
    }

    /// `NestedDict.get_or_create_nest(key, access_lists=...)`.
    fn nest<'a>(root: &'a mut Item, key: &[String], access_lists: bool) -> Parsed<&'a mut Item> {
        let mut cont = root;
        for part in key {
            if cont.get(part).is_none() {
                cont.insert(part, Item::Table(Vec::new()));
            }
            cont = cont.get_mut(part).ok_or(Refused)?;
            if access_lists && let Item::Array(items) = cont {
                cont = items.last_mut().ok_or(Refused)?;
            }
            if !matches!(cont, Item::Table(_)) {
                return Err(Refused);
            }
        }
        Ok(cont)
    }

    struct Parser {
        src: Vec<char>,
        pos: usize,
    }

    impl Parser {
        fn at(&self, pos: usize) -> Option<char> {
            self.src.get(pos).copied()
        }
        fn starts(&self, text: &str) -> bool {
            text.chars().enumerate().all(|(i, c)| self.at(self.pos + i) == Some(c))
        }
        fn skip_ws(&mut self) {
            while matches!(self.at(self.pos), Some(' ' | '\t')) {
                self.pos += 1;
            }
        }
        fn skip_ws_newline(&mut self) {
            while matches!(self.at(self.pos), Some(' ' | '\t' | '\n')) {
                self.pos += 1;
            }
        }
        /// `skip_until(src, pos, expect, error_on=..., error_on_eof=...)`.
        fn skip_until(&mut self, expect: &str, error_on: impl Fn(char) -> bool, error_on_eof: bool) -> Parsed<usize> {
            let wanted: Vec<char> = expect.chars().collect();
            let mut end = None;
            let mut index = self.pos;
            while index + wanted.len() <= self.src.len() {
                if self.src[index..index + wanted.len()] == wanted[..] {
                    end = Some(index);
                    break;
                }
                index += 1;
            }
            let end = match end {
                Some(end) => end,
                None if error_on_eof => return Err(Refused),
                None => self.src.len(),
            };
            if self.src[self.pos..end].iter().any(|c| error_on(*c)) {
                return Err(Refused);
            }
            Ok(end)
        }
        fn skip_comment(&mut self) -> Parsed<()> {
            if self.at(self.pos) == Some('#') {
                self.pos += 1;
                self.pos = self.skip_until("\n", |c| ctrl(c) && c != '\t', false)?;
            }
            Ok(())
        }
        fn skip_comments_and_array_ws(&mut self) -> Parsed<()> {
            loop {
                let before = self.pos;
                self.skip_ws_newline();
                self.skip_comment()?;
                if self.pos == before {
                    return Ok(());
                }
            }
        }

        fn key_part(&mut self) -> Parsed<String> {
            match self.at(self.pos) {
                Some(c) if bare(c) => {
                    let start = self.pos;
                    while self.at(self.pos).is_some_and(bare) {
                        self.pos += 1;
                    }
                    Ok(self.src[start..self.pos].iter().collect())
                }
                Some('\'') => self.literal_str(),
                Some('"') => {
                    self.pos += 1;
                    self.basic_str(false)
                }
                _ => Err(Refused),
            }
        }
        fn key(&mut self) -> Parsed<Vec<String>> {
            let mut key = vec![self.key_part()?];
            self.skip_ws();
            while self.at(self.pos) == Some('.') {
                self.pos += 1;
                self.skip_ws();
                key.push(self.key_part()?);
                self.skip_ws();
            }
            Ok(key)
        }
        fn literal_str(&mut self) -> Parsed<String> {
            self.pos += 1;
            let start = self.pos;
            let end = self.skip_until("'", |c| ctrl(c) && c != '\t', true)?;
            self.pos = end + 1;
            Ok(self.src[start..end].iter().collect())
        }
        fn hex_char(&mut self, length: usize) -> Parsed<char> {
            if self.pos + length > self.src.len() {
                return Err(Refused);
            }
            let text: String = self.src[self.pos..self.pos + length].iter().collect();
            if !text.chars().all(|c| c.is_ascii_hexdigit()) {
                return Err(Refused);
            }
            self.pos += length;
            let value = u32::from_str_radix(&text, 16).map_err(|_| Refused)?;
            char::from_u32(value).ok_or(Refused)
        }
        fn escape(&mut self, multiline: bool) -> Parsed<String> {
            let id: String = self.src[self.pos..(self.pos + 2).min(self.src.len())].iter().collect();
            self.pos += 2;
            if multiline && (id == "\\ " || id == "\\\t" || id == "\\\n") {
                if id != "\\\n" {
                    self.skip_ws();
                    match self.at(self.pos) {
                        None => return Ok(String::new()),
                        Some('\n') => self.pos += 1,
                        Some(_) => return Err(Refused),
                    }
                }
                self.skip_ws_newline();
                return Ok(String::new());
            }
            match id.as_str() {
                "\\u" => Ok(self.hex_char(4)?.to_string()),
                "\\U" => Ok(self.hex_char(8)?.to_string()),
                "\\b" => Ok("\u{8}".into()),
                "\\t" => Ok("\t".into()),
                "\\n" => Ok("\n".into()),
                "\\f" => Ok("\u{c}".into()),
                "\\r" => Ok("\r".into()),
                "\\\"" => Ok("\"".into()),
                "\\\\" => Ok("\\".into()),
                _ => Err(Refused),
            }
        }
        fn basic_str(&mut self, multiline: bool) -> Parsed<String> {
            let illegal = |c: char| ctrl(c) && c != '\t' && !(multiline && c == '\n');
            let mut result = String::new();
            let mut start = self.pos;
            loop {
                let Some(c) = self.at(self.pos) else {
                    return Err(Refused);
                };
                if c == '"' {
                    if !multiline {
                        result.extend(&self.src[start..self.pos]);
                        self.pos += 1;
                        return Ok(result);
                    }
                    if self.starts("\"\"\"") {
                        result.extend(&self.src[start..self.pos]);
                        self.pos += 3;
                        return Ok(result);
                    }
                    self.pos += 1;
                    continue;
                }
                if c == '\\' {
                    result.extend(&self.src[start..self.pos]);
                    let escaped = self.escape(multiline)?;
                    result.push_str(&escaped);
                    start = self.pos;
                    continue;
                }
                if illegal(c) {
                    return Err(Refused);
                }
                self.pos += 1;
            }
        }
        fn multiline_str(&mut self, literal: bool) -> Parsed<String> {
            self.pos += 3;
            if self.at(self.pos) == Some('\n') {
                self.pos += 1;
            }
            let delim = if literal { '\'' } else { '"' };
            let mut result = if literal {
                let end = self.skip_until("'''", |c| ctrl(c) && c != '\t' && c != '\n', true)?;
                let found: String = self.src[self.pos..end].iter().collect();
                self.pos = end + 3;
                found
            } else {
                self.basic_str(true)?
            };
            for _ in 0..2 {
                if self.at(self.pos) != Some(delim) {
                    return Ok(result);
                }
                self.pos += 1;
                result.push(delim);
            }
            Ok(result)
        }

        /// `d(?:_?d)*` at the position: whether it matched (the position after it).
        fn digits(&mut self, ok: impl Fn(char) -> bool) -> bool {
            if !self.at(self.pos).is_some_and(&ok) {
                return false;
            }
            self.pos += 1;
            loop {
                if self.at(self.pos).is_some_and(&ok) {
                    self.pos += 1;
                } else if self.at(self.pos) == Some('_') && self.at(self.pos + 1).is_some_and(&ok) {
                    self.pos += 2;
                } else {
                    return true;
                }
            }
        }
        fn fixed(&mut self, count: usize) -> Option<u32> {
            let mut value = 0u32;
            for _ in 0..count {
                value = value * 10 + self.at(self.pos)?.to_digit(10)?;
                self.pos += 1;
            }
            Some(value)
        }
        /// `_TIME_RE_STR` at the position: Some where it matched (the position after it), else the position kept.
        fn time(&mut self) -> Option<()> {
            let start = self.pos;
            let ok = (|| {
                let hour = self.fixed(2)?;
                (self.at(self.pos)? == ':').then_some(())?;
                self.pos += 1;
                let minute = self.fixed(2)?;
                (self.at(self.pos)? == ':').then_some(())?;
                self.pos += 1;
                let second = self.fixed(2)?;
                (hour <= 23 && minute <= 59 && second <= 59).then_some(())?;
                if self.at(self.pos) == Some('.') && self.at(self.pos + 1).is_some_and(|c| c.is_ascii_digit()) {
                    self.pos += 1;
                    while self.at(self.pos).is_some_and(|c| c.is_ascii_digit()) {
                        self.pos += 1;
                    }
                }
                Some(())
            })();
            if ok.is_none() {
                self.pos = start;
            }
            ok
        }
        /// RE_DATETIME at the position: Some(valid) where it matched (the position after it), None where not.
        fn datetime(&mut self) -> Option<bool> {
            let start = self.pos;
            let date = (|| {
                let year = self.fixed(4)?;
                (self.at(self.pos)? == '-').then_some(())?;
                self.pos += 1;
                let month = self.fixed(2)?;
                (self.at(self.pos)? == '-').then_some(())?;
                self.pos += 1;
                let day = self.fixed(2)?;
                ((1..=12).contains(&month) && (1..=31).contains(&day)).then_some((year, month, day))
            })();
            let Some((year, month, day)) = date else {
                self.pos = start;
                return None;
            };
            let after_date = self.pos;
            if matches!(self.at(self.pos), Some('T' | 't' | ' ')) {
                self.pos += 1;
                if self.time().is_some() {
                    match self.at(self.pos) {
                        Some('Z' | 'z') => self.pos += 1,
                        Some('+' | '-') => {
                            let mark = self.pos;
                            self.pos += 1;
                            let offset = (|| {
                                let hour = self.fixed(2)?;
                                (self.at(self.pos)? == ':').then_some(())?;
                                self.pos += 1;
                                let minute = self.fixed(2)?;
                                (hour <= 23 && minute <= 59).then_some(())
                            })();
                            if offset.is_none() {
                                self.pos = mark;
                            }
                        }
                        _ => {}
                    }
                } else {
                    self.pos = after_date;
                }
            }
            let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
            let days = [31, if leap { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month as usize - 1];
            // `datetime(year, ...)`: year 0 is no year.
            Some(year >= 1 && day <= days)
        }
        fn number(&mut self) -> bool {
            let start = self.pos;
            if self.at(self.pos) == Some('0') {
                let radix: Option<fn(char) -> bool> = match self.at(self.pos + 1) {
                    Some('x') => Some(|c: char| c.is_ascii_hexdigit()),
                    Some('b') => Some(|c: char| c == '0' || c == '1'),
                    Some('o') => Some(|c: char| ('0'..='7').contains(&c)),
                    _ => None,
                };
                if let Some(radix) = radix {
                    self.pos += 2;
                    if self.digits(radix) {
                        return true;
                    }
                    self.pos = start;
                }
            }
            if matches!(self.at(self.pos), Some('+' | '-')) {
                self.pos += 1;
            }
            match self.at(self.pos) {
                Some('0') => self.pos += 1,
                Some('1'..='9') => {
                    self.digits(|c| c.is_ascii_digit());
                }
                _ => {
                    self.pos = start;
                    return false;
                }
            }
            if self.at(self.pos) == Some('.') {
                let mark = self.pos;
                self.pos += 1;
                if !self.digits(|c| c.is_ascii_digit()) {
                    self.pos = mark;
                }
            }
            if matches!(self.at(self.pos), Some('e' | 'E')) {
                let mark = self.pos;
                self.pos += 1;
                if matches!(self.at(self.pos), Some('+' | '-')) {
                    self.pos += 1;
                }
                if !self.digits(|c| c.is_ascii_digit()) {
                    self.pos = mark;
                }
            }
            true
        }

        fn value(&mut self, depth: usize) -> Parsed<Item> {
            // CPython's recursion limit stops a nesting deeper than about a thousand levels.
            if depth > 900 {
                return Err(Refused);
            }
            match self.at(self.pos) {
                Some('"') => {
                    if self.starts("\"\"\"") {
                        self.multiline_str(false)?;
                    } else {
                        self.pos += 1;
                        self.basic_str(false)?;
                    }
                    return Ok(Item::Other);
                }
                Some('\'') => {
                    if self.starts("'''") {
                        self.multiline_str(true)?;
                    } else {
                        self.literal_str()?;
                    }
                    return Ok(Item::Other);
                }
                Some('t') if self.starts("true") => {
                    self.pos += 4;
                    return Ok(Item::Other);
                }
                Some('f') if self.starts("false") => {
                    self.pos += 5;
                    return Ok(Item::Other);
                }
                Some('[') => return self.array(depth),
                Some('{') => return self.inline_table(depth),
                _ => {}
            }
            if let Some(valid) = self.datetime() {
                return if valid { Ok(Item::Other) } else { Err(Refused) };
            }
            if self.time().is_some() || self.number() {
                return Ok(Item::Other);
            }
            for special in ["inf", "nan", "-inf", "+inf", "-nan", "+nan"] {
                if self.starts(special) {
                    self.pos += special.chars().count();
                    return Ok(Item::Other);
                }
            }
            Err(Refused)
        }
        fn array(&mut self, depth: usize) -> Parsed<Item> {
            self.pos += 1;
            let mut items = Vec::new();
            self.skip_comments_and_array_ws()?;
            if self.at(self.pos) == Some(']') {
                self.pos += 1;
                return Ok(Item::Array(items));
            }
            loop {
                items.push(self.value(depth + 1)?);
                self.skip_comments_and_array_ws()?;
                match self.at(self.pos) {
                    Some(']') => {
                        self.pos += 1;
                        return Ok(Item::Array(items));
                    }
                    Some(',') => self.pos += 1,
                    _ => return Err(Refused),
                }
                self.skip_comments_and_array_ws()?;
                if self.at(self.pos) == Some(']') {
                    self.pos += 1;
                    return Ok(Item::Array(items));
                }
            }
        }
        fn key_value(&mut self, depth: usize) -> Parsed<(Vec<String>, Item)> {
            let key = self.key()?;
            if self.at(self.pos) != Some('=') {
                return Err(Refused);
            }
            self.pos += 1;
            self.skip_ws();
            let value = self.value(depth + 1)?;
            Ok((key, value))
        }
        fn inline_table(&mut self, depth: usize) -> Parsed<Item> {
            self.pos += 1;
            let mut table = Item::Table(Vec::new());
            let mut flags = Flags::default();
            self.skip_ws();
            if self.at(self.pos) == Some('}') {
                self.pos += 1;
                return Ok(table);
            }
            loop {
                let (key, value) = self.key_value(depth)?;
                if flags.is(&key, FROZEN) {
                    return Err(Refused);
                }
                let container = matches!(value, Item::Table(_) | Item::Array(_));
                let place = nest(&mut table, &key[..key.len() - 1], false)?;
                if place.get(&key[key.len() - 1]).is_some() {
                    return Err(Refused);
                }
                place.insert(&key[key.len() - 1], value);
                self.skip_ws();
                match self.at(self.pos) {
                    Some('}') => {
                        self.pos += 1;
                        return Ok(table);
                    }
                    Some(',') => {}
                    _ => return Err(Refused),
                }
                if container {
                    flags.set(&key, FROZEN, true);
                }
                self.pos += 1;
                self.skip_ws();
            }
        }
    }

    /// `tomllib.loads(text)`: the document, or TOML's refusal.
    pub fn loads(text: &str) -> Result<Item, Refused> {
        let src: Vec<char> = text.replace("\r\n", "\n").chars().collect();
        let mut parser = Parser { src, pos: 0 };
        let mut data = Item::Table(Vec::new());
        let mut flags = Flags::default();
        let mut header: Vec<String> = Vec::new();
        loop {
            parser.skip_ws();
            let Some(c) = parser.at(parser.pos) else {
                break;
            };
            if c == '\n' {
                parser.pos += 1;
                continue;
            }
            if bare(c) || c == '"' || c == '\'' {
                let (key, value) = parser.key_value(0)?;
                let stem = key[key.len() - 1].clone();
                for i in 1..key.len() {
                    let mut cont: Vec<String> = header.clone();
                    cont.extend_from_slice(&key[..i]);
                    if flags.is(&cont, EXPLICIT_NEST) {
                        return Err(Refused);
                    }
                    flags.pending.push((cont, EXPLICIT_NEST));
                }
                let mut parent = header.clone();
                parent.extend_from_slice(&key[..key.len() - 1]);
                if flags.is(&parent, FROZEN) {
                    return Err(Refused);
                }
                let container = matches!(value, Item::Table(_) | Item::Array(_));
                let place = nest(&mut data, &parent, true)?;
                if place.get(&stem).is_some() {
                    return Err(Refused);
                }
                place.insert(&stem, value);
                if container {
                    let mut whole = header.clone();
                    whole.extend_from_slice(&key);
                    flags.set(&whole, FROZEN, true);
                }
                parser.skip_ws();
            } else if c == '[' {
                let list = parser.at(parser.pos + 1) == Some('[');
                flags.finalize_pending();
                parser.pos += if list { 2 } else { 1 };
                parser.skip_ws();
                let key = parser.key()?;
                if list {
                    if flags.is(&key, FROZEN) {
                        return Err(Refused);
                    }
                    flags.unset_all(&key);
                    flags.set(&key, EXPLICIT_NEST, false);
                    let place = nest(&mut data, &key[..key.len() - 1], true)?;
                    let last = &key[key.len() - 1];
                    match place.get_mut(last) {
                        Some(Item::Array(items)) => items.push(Item::Table(Vec::new())),
                        Some(_) => return Err(Refused),
                        None => place.insert(last, Item::Array(vec![Item::Table(Vec::new())])),
                    }
                    if !parser.starts("]]") {
                        return Err(Refused);
                    }
                    parser.pos += 2;
                } else {
                    if flags.is(&key, EXPLICIT_NEST) || flags.is(&key, FROZEN) {
                        return Err(Refused);
                    }
                    flags.set(&key, EXPLICIT_NEST, false);
                    nest(&mut data, &key, true)?;
                    if parser.at(parser.pos) != Some(']') {
                        return Err(Refused);
                    }
                    parser.pos += 1;
                }
                header = key;
                parser.skip_ws();
            } else if c != '#' {
                return Err(Refused);
            }
            parser.skip_comment()?;
            match parser.at(parser.pos) {
                None => break,
                Some('\n') => parser.pos += 1,
                Some(_) => return Err(Refused),
            }
        }
        Ok(data)
    }
}

/// `_config(codex_home)`: (config.toml as tomllib reads it, whether it is there and could not be read).
pub fn config(codex_home: &str) -> (Option<toml::Item>, bool) {
    let path = std::path::Path::new(codex_home).join("config.toml");
    let data = match std::fs::read(&path) {
        Ok(data) => data,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return (None, false),
        Err(_) => return (None, true),
    };
    let Ok(text) = String::from_utf8(data) else {
        return (None, true);
    };
    let text = text.strip_prefix('\u{feff}').unwrap_or(&text);
    match toml::loads(text) {
        Ok(found) => (Some(found), false),
        Err(_) => (None, true),
    }
}

/// `declared_servers(codex_home)`: the MCP servers config.toml declares (a table with `command` or `url`), in order.
pub fn declared_servers(codex_home: &str) -> Vec<String> {
    let (found, _unreadable) = config(codex_home);
    let Some(toml::Item::Table(servers)) = found.as_ref().and_then(|found| found.get("mcp_servers")).cloned() else {
        return Vec::new();
    };
    servers
        .into_iter()
        .filter(|(_, value)| {
            matches!(value, toml::Item::Table(_)) && (value.get("command").is_some() || value.get("url").is_some())
        })
        .map(|(name, _)| name)
        .collect()
}

/// `config_unreadable(codex_home)`.
pub fn config_unreadable(codex_home: &str) -> bool {
    config(codex_home).1
}
