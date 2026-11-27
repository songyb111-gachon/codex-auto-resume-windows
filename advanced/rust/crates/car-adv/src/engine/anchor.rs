//! Start the 5-hour window early (`window_anchor`, v0.6.20), at P8 (seat S7.2e2, `engine/anchor.py`).
//!
//! Codex's 5-hour usage window starts at the first use, so a late first use gives a late reset. With this on, when the
//! 5-hour window is idle, the watcher sends one near-free request (MANCHOR's `codex exec ... "Reply with OK"`) so the
//! window starts now and its reset is fixed five hours on - at the times of day a person picked, right after a reset
//! it has seen, or both. The module's pure functions come first, then config.toml's reader (`toml`), the request,
//! and the capability's code (`WindowAnchor`).

use car_machine::json::Value;
use car_machine::localclock::LocalClock;
use car_machine::pyval::Py;

use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::supervise::{Bound, field, lock, word};
use crate::capabilities::{Code, Raised, Said, Spoke};
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
pub const TIME_OPTIONS: [OptionKey; 3] = [
    OptionKey::AnchorAt1,
    OptionKey::AnchorAt2,
    OptionKey::AnchorAt3,
];
/// wrapwords' ON: Start right after a reset, on (`engine/wrapwords.ON`, as the tag imports it).
pub const ON: i64 = super::wrapwords::ON;
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
    ((0..24).contains(&hour) && (0..60).contains(&minute))
        .then_some(hour * 60 + minute + TIME_SHIFT)
}

/// `decode_time(value)`: the minute of the day a time option holds, or None.
pub fn decode_time(value: &Value) -> Option<i64> {
    let value = int(value)?;
    (TIME_SHIFT..=TIME_RANGE.1)
        .contains(&value)
        .then_some(value - TIME_SHIFT)
}

/// `clock_text(value)`: HH:MM, "" for off.
pub fn clock_text(value: &Value) -> String {
    decode_time(value).map_or(String::new(), |minute| {
        format!("{:02}:{:02}", minute / 60, minute % 60)
    })
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
    sql::py_eq(
        &found.unwrap_or(Value::Int(ON.into())),
        &Value::Int(ON.into()),
    )
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
pub fn slot_due(
    options: &Value,
    now: f64,
    done: &Value,
    local: &dyn LocalClock,
) -> Py<Option<i64>> {
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
        Value::Array(items) => Ok(items
            .iter()
            .filter(|each| matches!(each, Value::Object(_)))
            .collect()),
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
        let minutes = |window: &&Value, wanted: i64| {
            sql::py_eq(field(window, "window_minutes"), &Value::Int(wanted.into()))
        };
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
    // `not five["used_percent"] > 0`: a NaN is not above it either.
    if numeric(item(&five, "used_percent")?)?.partial_cmp(&0.0) != Some(std::cmp::Ordering::Greater)
    {
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
    if numeric(item(five1, "used_percent")?)? > 0.0 || numeric(item(five2, "used_percent")?)? > 0.0
    {
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
            '\n' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}'
            | '\u{2029}' => Some(index + c.len_utf8()),
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
        for (slot, name) in ["input_tokens", "cached_input_tokens", "output_tokens"]
            .iter()
            .enumerate()
        {
            found[slot] =
                int(field(usage, name)).filter(|value| (0..1_000_000_000).contains(value));
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
                Item::Table(pairs) => pairs
                    .iter()
                    .find(|(name, _)| name == key)
                    .map(|(_, item)| item),
                _ => None,
            }
        }
        fn get_mut(&mut self, key: &str) -> Option<&mut Item> {
            match self {
                Item::Table(pairs) => pairs
                    .iter_mut()
                    .find(|(name, _)| name == key)
                    .map(|(_, item)| item),
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
            text.chars()
                .enumerate()
                .all(|(i, c)| self.at(self.pos + i) == Some(c))
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
        fn skip_until(
            &mut self,
            expect: &str,
            error_on: impl Fn(char) -> bool,
            error_on_eof: bool,
        ) -> Parsed<usize> {
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
            let id: String = self.src[self.pos..(self.pos + 2).min(self.src.len())]
                .iter()
                .collect();
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
                if self.at(self.pos) == Some('.')
                    && self.at(self.pos + 1).is_some_and(|c| c.is_ascii_digit())
                {
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
            let days = [
                31,
                if leap { 29 } else { 28 },
                31,
                30,
                31,
                30,
                31,
                31,
                30,
                31,
                30,
                31,
            ][month as usize - 1];
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
    let Some(toml::Item::Table(servers)) = found
        .as_ref()
        .and_then(|found| found.get("mcp_servers"))
        .cloned()
    else {
        return Vec::new();
    };
    servers
        .into_iter()
        .filter(|(_, value)| {
            matches!(value, toml::Item::Table(_))
                && (value.get("command").is_some() || value.get("url").is_some())
        })
        .map(|(name, _)| name)
        .collect()
}

/// `config_unreadable(codex_home)`.
pub fn config_unreadable(codex_home: &str) -> bool {
    config(codex_home).1
}

// ---------------------------------------------------------------------------------------------- the request
/// What the request needs of core's Backend: the product's own `codex` prefix (`_argv`) and the environment
/// (`_environment`, its CODEX_HOME the home the request uses).
pub trait RequestBackend: Send {
    fn argv(&self) -> Vec<String>;
    fn environment(&self) -> Vec<(std::ffi::OsString, std::ffi::OsString)>;
    /// `_environment().get("CODEX_HOME") or ""`.
    fn codex_home(&self) -> String {
        self.environment()
            .into_iter()
            .find(|(name, _)| name.to_string_lossy() == "CODEX_HOME")
            .map(|(_, value)| value.to_string_lossy().into_owned())
            .unwrap_or_default()
    }
}

impl RequestBackend for car_codex::transport::Backend {
    fn argv(&self) -> Vec<String> {
        car_codex::transport::Backend::argv(self)
    }
    fn environment(&self) -> Vec<(std::ffi::OsString, std::ffi::OsString)> {
        car_codex::transport::Backend::environment(self)
    }
}

/// `argv_for(backend, plain)`: the prefix, `exec`, the switch that keeps the person's programs out (and `servers_off`
/// for the servers of the Codex home the request uses), then the rest of the measured arguments.
pub fn argv_for(backend: &dyn RequestBackend, plain: bool) -> Vec<String> {
    let mut argv = backend.argv();
    if plain {
        argv.extend(EXEC_ARGUMENTS.iter().map(|each| (*each).to_owned()));
        return argv;
    }
    let names: Vec<Value> = declared_servers(&backend.codex_home())
        .iter()
        .map(|name| word(name))
        .collect();
    argv.push(EXEC_ARGUMENTS[0].to_owned());
    argv.extend(QUIET_ARGUMENTS.iter().map(|each| (*each).to_owned()));
    if let Some(off) = servers_off(&names) {
        argv.push("-c".to_owned());
        argv.push(off);
    }
    argv.extend(EXEC_ARGUMENTS[1..].iter().map(|each| (*each).to_owned()));
    argv
}

/// `folder_of(paths)`.
pub fn folder_of(paths: &car_config::Paths) -> std::path::PathBuf {
    std::path::Path::new(&paths.advanced_dir).join(FOLDER)
}

/// `ready_folder(folder)`: made where it is not, and whether it is an empty folder of its own (never a link).
pub fn ready_folder(folder: &std::path::Path) -> bool {
    if std::fs::create_dir_all(folder).is_err() {
        return false;
    }
    let Ok(metadata) = std::fs::symlink_metadata(folder) else {
        return false;
    };
    if metadata.file_type().is_symlink() || !folder.is_dir() {
        return false;
    }
    std::fs::read_dir(folder).is_ok_and(|mut entries| entries.next().is_none())
}

/// `start_request(backend, folder, plain)`: the request started, windowless, no shell, no input.
pub fn start_request(
    backend: &dyn RequestBackend,
    folder: &std::path::Path,
    plain: bool,
) -> Result<std::process::Child, Raised> {
    use car_platform::spawn::{Spawn, Stream, SystemStarter};
    let spawn = Spawn::new(argv_for(backend, plain))
        .with_env(backend.environment())
        .with_cwd(folder)
        .with_streams(Stream::Null, Stream::Piped, Stream::Piped);
    SystemStarter
        .start(&spawn)
        .map_err(|_| Raised::new("OSError"))
}

/// What `finish_request` answered: `{"end", "code", "input", "cached", "output", "refused"}`.
#[derive(Debug, Clone, PartialEq)]
pub struct Finished {
    pub timed_out: bool,
    pub code: Option<i64>,
    pub tokens: [Option<i64>; 3],
    pub refused: bool,
}

/// `finish_request(process, timeout)`: waited for at most `timeout`, killed after it.
pub fn finish_request(child: std::process::Child, timeout: f64) -> Finished {
    match super::updatecheck::communicate(child, timeout) {
        Ok((code, printed, errors)) => {
            let printed = String::from_utf8_lossy(&printed).into_owned();
            let errors = String::from_utf8_lossy(&errors).into_owned();
            Finished {
                timed_out: false,
                code: Some(code),
                tokens: tokens_of(&printed),
                refused: code != 0 && !thread_started(&printed) && refused(&errors),
            }
        }
        Err(late) => {
            let super::updatecheck::Late { mut child, back } = *late;
            let _ = child.kill();
            let started = std::time::Instant::now();
            while started.elapsed().as_secs_f64() < KILL_WAIT {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(20));
            }
            std::thread::spawn(move || {
                let _ = child.wait();
                let _ = back.finish();
            });
            Finished {
                timed_out: true,
                code: None,
                tokens: [None, None, None],
                refused: false,
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------- the capability
pub const SLOT: &str = "slot";
pub const RESET: &str = "reset";
pub const VERIFY: &str = "verify";
pub const ACCOUNT_SWITCH: &str = "account_switch";
pub const WINDOW_STAMPS: [OptionKey; 3] = [
    OptionKey::AnchorStartedAt,
    OptionKey::AnchorFixedAt,
    OptionKey::AnchorSeenReset,
];
/// The reasons that say nothing lasting of the window: the occasion stays open (`_held`).
pub const PASSING: [&str; 7] = [
    "unreadable",
    "signed_out",
    "paused",
    "home",
    "folder",
    "state",
    "failed",
];

/// `_word(reason)`: the journal's word an occasion ends with.
pub fn skip_word(reason: &str) -> &str {
    match reason {
        "running" => "skip_running",
        "weekly" => "skip_weekly",
        "paused" => "skip_paused",
        "signed_out" => "skip_signed_out",
        "unreadable" => "skip_unreadable",
        "home" => "skip_home",
        "once" => "skip_once",
        "folder" => "skip_folder",
        "state" => "skip_state",
        "ceiling" => "skip_ceiling",
        other => other,
    }
}

/// The registry's ceiling of starts a day (`WINDOW_ANCHOR.ceilings.per_day`).
pub fn per_day() -> i64 {
    static FOUND: std::sync::OnceLock<i64> = std::sync::OnceLock::new();
    *FOUND.get_or_init(|| {
        crate::registry::shipped(false)
            .ok()
            .and_then(|registry| {
                registry
                    .get(CAPABILITY)
                    .and_then(|definition| definition.ceilings.as_ref().map(|c| c.per_day))
            })
            .unwrap_or(5)
    })
}

/// A usage session of its own (`Session(backend, capability=CAPABILITY)`, entered): `call(method, params)`.
pub trait UsageSession {
    fn call(&mut self, method: &str, params: &Value) -> Result<Value, Raised>;
}

/// `session()`: one opened and entered.
pub type OpenSession = Box<dyn Fn() -> Result<Box<dyn UsageSession>, Raised> + Send + Sync>;
/// `told()`: (codex.exe, Codex home) as the watcher told them, or None.
pub type Told = Box<dyn Fn() -> Option<(String, String)> + Send + Sync>;
/// `backend()`: core's Backend for that pair.
pub type MakeBackend = Box<dyn Fn() -> Result<Box<dyn RequestBackend>, Raised> + Send + Sync>;
/// `begin(target)`: the waiting thread started.
pub type Begin = Box<dyn Fn(Box<dyn FnOnce() + Send>) -> Result<(), Raised> + Send + Sync>;
/// One line in the watcher's log.
pub type Log = Box<dyn Fn(&str) -> Result<(), Raised> + Send + Sync>;
/// The local clock.
pub type Local = Box<dyn LocalClock + Send + Sync>;

#[derive(Clone, Copy, PartialEq, Debug)]
enum Told2 {
    NotTold,
    Told(Option<i64>),
}

#[derive(Clone, Debug)]
struct Held {
    next: f64,
    until: f64,
    reason: String,
    weekly: bool,
    /// `"wake" in held`, and what it holds.
    wake: Option<Option<i64>>,
    said_weekly: bool,
}

#[derive(Clone, Debug)]
struct Occasion {
    at: i64,
    plain: bool,
}

#[derive(Clone, Debug)]
struct Pending {
    why: &'static str,
    occurrence: i64,
    first: Value,
    tokens: Option<Value>,
}

struct Memory {
    pending: Option<Pending>,
    running: Option<Occasion>,
    ended: Option<(Occasion, Finished)>,
    looked: Option<f64>,
    learned: Option<f64>,
    held_open: Vec<((&'static str, i64), Held)>,
    shown: Told2,
    shown_next: Told2,
}

struct Inner {
    paths: car_config::Paths,
    bound: std::sync::Mutex<Option<Bound>>,
    session: Option<OpenSession>,
    told: Told,
    backend: MakeBackend,
    begin: Begin,
    log: Log,
    local: Local,
    memory: std::sync::Mutex<Memory>,
}

/// `WindowAnchor(paths, session=..., told=..., backend=..., begin=..., log=..., local=...)`.
#[derive(Clone)]
pub struct WindowAnchor {
    inner: std::sync::Arc<Inner>,
}

type Answer<T> = Result<T, Raised>;

fn key(option: OptionKey) -> Value {
    word(option.as_str())
}

fn int_value(value: &Value) -> Option<i64> {
    match value {
        Value::Int(number) => number.as_i64(),
        _ => None,
    }
}

fn number_value(value: &Value) -> Option<f64> {
    super::supervise::number(value)
}

impl WindowAnchor {
    pub fn new(
        paths: car_config::Paths,
        session: Option<OpenSession>,
        told: Told,
        backend: MakeBackend,
        begin: Begin,
        log: Log,
        local: Local,
    ) -> WindowAnchor {
        WindowAnchor {
            inner: std::sync::Arc::new(Inner {
                paths,
                bound: std::sync::Mutex::new(None),
                session,
                told,
                backend,
                begin,
                log,
                local,
                memory: std::sync::Mutex::new(Memory {
                    pending: None,
                    running: None,
                    ended: None,
                    looked: None,
                    learned: None,
                    held_open: Vec::new(),
                    shown: Told2::NotTold,
                    shown_next: Told2::NotTold,
                }),
            }),
        }
    }

    /// `bind(scoped)` with a harness's own state.
    pub fn bind_to(&self, bound: Bound) {
        *lock(&self.inner.bound) = Some(bound);
    }

    fn memory(&self) -> std::sync::MutexGuard<'_, Memory> {
        lock(&self.inner.memory)
    }

    fn bound(&self) -> Answer<Bound> {
        lock(&self.inner.bound)
            .clone()
            .ok_or_else(|| Raised::new("AttributeError"))
    }

    fn stamped(&self, option: OptionKey) -> Answer<Value> {
        self.bound()?.read(|scoped| scoped.stamped(&key(option)))
    }

    /// `_stamp(key, value)`: Some(true) kept, Some(false) not kept (not on), None where the state could not be written.
    fn stamp(&self, option: OptionKey, value: i64) -> Option<bool> {
        let bound = self.bound().ok()?;
        match bound.with(|scoped| scoped.stamp(&key(option), &Value::Int(value.into()))) {
            Some(Ok(kept)) => Some(kept),
            _ => None,
        }
    }

    fn unstamp(&self, option: OptionKey) {
        if let Ok(bound) = self.bound() {
            let _ = bound.with(|scoped| scoped.unstamp(&key(option)));
        }
    }

    fn count(&self, code: &str) {
        if let Ok(bound) = self.bound() {
            let _ = bound.with(|scoped| scoped.count(&word(code)));
        }
    }

    fn say(&self, line: &str) {
        let _ = (self.inner.log)(&format!("{LOG_PREFIX}{line}"));
    }

    fn now(&self) -> Answer<f64> {
        self.bound()?.now()
    }

    fn options(&self) -> Answer<Value> {
        Ok(Value::Object(
            self.bound()?.read(|scoped| scoped.options())?,
        ))
    }

    // ------------------------------------------------------------------ P8
    /// The tick: an errand where there is something to do; reads nothing but its own stamps.
    pub fn ticked(&self) -> Spoke {
        if lock(&self.inner.bound).is_none() {
            return Ok(Said::Defer);
        }
        let due = (|| -> Answer<bool> {
            let now = self.now()?;
            self.account_changed();
            let (ended, running, pending) = {
                let memory = self.memory();
                (
                    memory.ended.is_some(),
                    memory.running.is_some(),
                    memory.pending.clone(),
                )
            };
            if ended {
                return Ok(true);
            }
            if running {
                return Ok(false);
            }
            if let Some(pending) = pending {
                let at = number_value(field(&pending.first, "at")).unwrap_or(f64::NAN);
                return Ok(now - at >= STEADY_GAP);
            }
            let looked = self.memory().looked;
            if let Some(looked) = looked
                && 0.0 <= now - looked
                && now - looked < LOOK_EVERY
            {
                return Ok(false);
            }
            self.memory().looked = Some(now);
            Ok(!self.span_over(now).is_empty()
                || self.open(now)?.is_some()
                || self.learn_due(now)?)
        })();
        match due {
            Ok(true) => Ok(Said::Errand(Box::new(AnchorErrand(self.clone())))),
            _ => Ok(Said::Defer),
        }
    }

    /// `_account_changed()`: another account signed in since the last change taken in - its window stamps go, once.
    fn account_changed(&self) {
        let Ok(bound) = self.bound() else {
            return;
        };
        let _ = bound.with(|scoped| -> Result<(), crate::state::Error> {
            if !scoped.armed(&word(ACCOUNT_SWITCH)) {
                return Ok(());
            }
            let changed =
                scoped.stamped_of(&word(ACCOUNT_SWITCH), &key(OptionKey::AccountChangedAt))?;
            let taken = scoped.stamped(&key(OptionKey::AnchorAccountAt))?;
            let Some(changed_at) = int_value(&changed) else {
                return Ok(());
            };
            if int_value(&taken).is_some_and(|taken| taken >= changed_at) {
                return Ok(());
            }
            for option in WINDOW_STAMPS {
                scoped.unstamp(&key(option))?;
            }
            scoped.stamp(&key(OptionKey::AnchorAccountAt), &changed)?;
            Ok(())
        });
    }

    /// `_occasion(now)`: a time picked first, then a reset seen; or None.
    fn occasion(&self, now: f64) -> Answer<Option<(&'static str, i64)>> {
        let options = self.options()?;
        let done = self.stamped(OptionKey::AnchorSlotDone)?;
        if let Some(slot) =
            slot_due(&options, now, &done, self.inner.local.as_ref()).map_err(Raised::new)?
        {
            return Ok(Some((SLOT, slot)));
        }
        let seen = self.stamped(OptionKey::AnchorSeenReset)?;
        let reset_done = self.stamped(OptionKey::AnchorResetDone)?;
        Ok(reset_due(&options, now, &seen, &reset_done)
            .map_err(Raised::new)?
            .map(|seen| (RESET, seen)))
    }

    /// `_open(now)`: the occasion due now, unless a passing failure's retry is not due yet.
    fn open(&self, now: f64) -> Answer<Option<(&'static str, i64)>> {
        let occasion = self.occasion(now)?;
        let Some(occasion) = occasion else {
            return Ok(None);
        };
        let memory = self.memory();
        let held = memory
            .held_open
            .iter()
            .find(|(known, _)| *known == occasion);
        Ok(match held {
            Some((_, held)) if now < held.next => None,
            _ => Some(occasion),
        })
    }

    /// `_span_over(now)`: the occasions held open whose span is over.
    fn span_over(&self, now: f64) -> Vec<(&'static str, i64)> {
        self.memory()
            .held_open
            .iter()
            .filter(|(_, held)| now >= held.until)
            .map(|(occasion, _)| *occasion)
            .collect()
    }

    /// `_learn_due(now)`.
    fn learn_due(&self, now: f64) -> Answer<bool> {
        if !self.memory().held_open.is_empty() || !after_reset_on(&self.options()?) {
            return Ok(false);
        }
        if let Some(seen) = int_value(&self.stamped(OptionKey::AnchorSeenReset)?)
            && (seen as f64) > now
        {
            return Ok(false);
        }
        let learned = self.memory().learned;
        Ok(learned.is_none_or(|learned| !(0.0 <= now - learned && now - learned < LEARN_EVERY)))
    }

    // ------------------------------------------------------------------ the errand
    /// `look(view, guard)`.
    pub fn look(&self, view: &dyn View, guards: &mut Guards<'_>) -> Answer<()> {
        if self.settle(Some(guards))? {
            return Ok(());
        }
        let now = self.now()?;
        if self.memory().pending.is_some() {
            return self.second(view, guards, now);
        }
        let found = (|| -> Answer<(Option<(&'static str, i64)>, bool)> {
            for over in self.span_over(now) {
                self.span_ended(over, now)?;
            }
            let occasion = self.open(now)?;
            let learn = occasion.is_none() && self.learn_due(now)?;
            Ok((occasion, learn))
        })();
        let Ok((occasion, learn)) = found else {
            return Ok(());
        };
        if let Some(occasion) = occasion {
            self.first(view, occasion, now)?;
        } else if learn {
            self.memory().learned = Some(now);
            let reading = self.read(false);
            self.remember(&reading, now)?;
        }
        Ok(())
    }

    fn first(&self, view: &dyn View, occasion: (&'static str, i64), now: f64) -> Answer<()> {
        let (why, occurrence) = occasion;
        if let Some(reason) = self.before(view, now) {
            return self.skip(why, occurrence, reason, None);
        }
        let reading = self.read(true);
        self.remember(&reading, now)?;
        if matches!(reading, Value::Null) || matches!(field(&reading, "windows"), Value::Null) {
            return self.skip(why, occurrence, "unreadable", None);
        }
        match field(&reading, "signed_in") {
            Value::Bool(true) => {}
            Value::Bool(false) => return self.skip(why, occurrence, "signed_out", None),
            _ => return self.skip(why, occurrence, "unreadable", None),
        }
        let (five, weekly) = windows_of(field(&reading, "windows")).map_err(Raised::new)?;
        let Some(five) = five else {
            return self.skip(why, occurrence, "unreadable", None);
        };
        if let Some(weekly) = weekly
            && numeric_of(item_of(&weekly, "used_percent")?)? >= 100.0
        {
            let until = self.past_weekly(why, &reading, now)?;
            return self.skip(why, occurrence, "weekly", until);
        }
        if numeric_of(item_of(&five, "used_percent")?)? > 0.0 {
            return self.skip(why, occurrence, "running", None);
        }
        self.memory().pending = Some(Pending {
            why,
            occurrence,
            first: reading,
            tokens: None,
        });
        Ok(())
    }

    fn second(&self, view: &dyn View, guards: &mut Guards<'_>, now: f64) -> Answer<()> {
        let Some(pending) = self.memory().pending.take() else {
            return Ok(());
        };
        let (why, occurrence) = (pending.why, pending.occurrence);
        let reading = self.read(false);
        self.remember(&reading, now)?;
        let found = if matches!(reading, Value::Null) {
            UNREADABLE
        } else {
            judge(&pending.first, &reading).map_err(Raised::new)?
        };
        if why == VERIFY {
            return self.verified(found, &reading, &pending);
        }
        let first_at = number_value(field(&pending.first, "at")).unwrap_or(f64::NAN);
        if !(0.0 <= now - first_at && now - first_at <= SLOT_GRACE as f64) {
            return self.skip(why, occurrence, "unreadable", None);
        }
        if found == WEEKLY_FULL {
            let basis = if matches!(reading, Value::Null) {
                pending.first.clone()
            } else {
                reading.clone()
            };
            let until = self.past_weekly(why, &basis, now)?;
            return self.skip(why, occurrence, "weekly", until);
        }
        if found != IDLE {
            return self.skip(
                why,
                occurrence,
                if found == RUNNING {
                    "running"
                } else {
                    "unreadable"
                },
                None,
            );
        }
        if let Some(reason) = self.before(view, now) {
            return self.skip(why, occurrence, reason, None);
        }
        self.start(why, occurrence, guards, now)
    }

    /// `_before(view, now)`: why no window may be started now, or None.
    fn before(&self, view: &dyn View, now: f64) -> Option<&'static str> {
        let settings = view.settings().unwrap_or(Value::Null);
        if !matches!(settings, Value::Object(_))
            || !matches!(field(&settings, "enabled"), Value::Bool(true))
            || car_machine::pyval::truthy(field(&settings, "observe_only"))
        {
            return Some("paused");
        }
        if (self.inner.told)().is_none() {
            return Some("home");
        }
        let Ok(started) = self.stamped(OptionKey::AnchorStartedAt) else {
            return Some("state");
        };
        if let Some(started) = int_value(&started)
            && 0.0 <= now - started as f64
            && now - (started as f64) < WINDOW_SECONDS as f64
        {
            return Some("once");
        }
        let made = self.bound().and_then(|bound| {
            bound.read(|scoped| {
                scoped.counted_since(&word("started"), &Value::Float(now - DAY as f64))
            })
        });
        match made {
            Err(_) => Some("state"),
            Ok(made) if made >= per_day() => Some("ceiling"),
            Ok(_) => None,
        }
    }

    fn start(
        &self,
        why: &'static str,
        occurrence: i64,
        guards: &mut Guards<'_>,
        now: f64,
    ) -> Answer<()> {
        let folder = folder_of(&self.inner.paths);
        if !ready_folder(&folder) {
            return self.skip(why, occurrence, "folder", None);
        }
        let Ok(backend) = self.backend() else {
            return self.skip(why, occurrence, "home", None);
        };
        let mut process: Option<std::process::Child> = None;
        let mut refused: Option<&'static str> = None;
        let whole = super::anchor::whole(now).map_err(Raised::new)?;
        let guarded = guards(&mut |permitted| {
            if !permitted {
                refused = Some("paused");
                return Value::Null;
            }
            match self.stamp(OptionKey::AnchorStartedAt, whole.max(1)) {
                None => refused = Some("state"),
                Some(true) => match start_request(backend.as_ref(), &folder, false) {
                    Ok(child) => process = Some(child),
                    Err(_) => self.unstamp(OptionKey::AnchorStartedAt),
                },
                Some(false) => {}
            }
            Value::Null
        });
        if guarded.is_err() && process.is_none() {
            refused = Some("state");
        }
        if let Some(reason) = refused {
            return self.skip(why, occurrence, reason, None);
        }
        let Some(process) = process else {
            return self.skip(why, occurrence, "failed", None);
        };
        self.done(why, occurrence);
        self.unstamp(OptionKey::AnchorStoppedAt);
        self.count("started");
        if config_unreadable(&backend.codex_home()) {
            self.say(
                "warning: the Codex home's config.toml could not be read here, so the MCP servers it may declare were \
                 not kept out of the request and may run for it; hooks, plugins, apps and the notify program were kept out",
            );
        }
        self.wait(
            Occasion {
                at: whole,
                plain: false,
            },
            process,
        );
        Ok(())
    }

    /// `_wait(occasion, process)`: the request's waiting thread begun.
    fn wait(&self, occasion: Occasion, process: std::process::Child) {
        self.memory().running = Some(occasion.clone());
        let slot = std::sync::Arc::new(std::sync::Mutex::new(Some(process)));
        let waiting = {
            let code = self.clone();
            let slot = slot.clone();
            let occasion = occasion.clone();
            move || code.finish(&occasion, &slot)
        };
        if (self.inner.begin)(Box::new(waiting)).is_err() {
            self.finish(&occasion, &slot);
        }
    }

    fn finish(&self, occasion: &Occasion, slot: &std::sync::Mutex<Option<std::process::Child>>) {
        let Some(child) = lock(slot).take() else {
            return;
        };
        let answered = finish_request(child, TIMEOUT);
        let mut memory = self.memory();
        memory.ended = Some((occasion.clone(), answered));
        memory.running = None;
    }

    /// `_again(occasion, guard)`: the request sent once more as it was before v0.6.24.
    fn again(&self, occasion: &Occasion, guards: &mut Guards<'_>) -> bool {
        if occasion.plain {
            return false;
        }
        let folder = folder_of(&self.inner.paths);
        if !ready_folder(&folder) {
            return false;
        }
        let Ok(backend) = self.backend() else {
            return false;
        };
        let mut process = None;
        let _ = guards(&mut |permitted| {
            if permitted {
                process = start_request(backend.as_ref(), &folder, true).ok();
            }
            Value::Null
        });
        let Some(process) = process else {
            return false;
        };
        self.say(
            "warning: this Codex refused the switch that keeps your MCP servers, hooks, plugins, apps and notify program \
             out of the request, so it was sent once more without it - they ran for this request",
        );
        let mut plain = occasion.clone();
        plain.plain = true;
        self.wait(plain, process);
        true
    }

    /// `_settle(guard)`: a request that ended; whether there was one.
    fn settle(&self, guards: Option<&mut Guards<'_>>) -> Answer<bool> {
        let Some((occasion, answered)) = self.memory().ended.take() else {
            return Ok(false);
        };
        if answered.refused
            && let Some(guards) = guards
            && self.again(&occasion, guards)
        {
            return Ok(true);
        }
        for (option, slot) in [
            (OptionKey::AnchorInputTokens, 0usize),
            (OptionKey::AnchorOutputTokens, 2),
        ] {
            match answered.tokens[slot] {
                Some(value) if value >= 1 => {
                    self.stamp(option, value);
                }
                _ => self.unstamp(option),
            }
        }
        if answered.timed_out {
            self.count("timed_out");
            self.say(&format!(
                "the request did not finish within {} s and was ended",
                TIMEOUT as i64
            ));
            return Ok(true);
        }
        if answered.code != Some(0) {
            self.count("failed");
            let code = answered
                .code
                .map_or("unknown".to_owned(), |code| code.to_string());
            self.say(&format!("the request ended with exit code {code}"));
            return Ok(true);
        }
        let now = self.now()?;
        let reading = self.read(false);
        if matches!(reading, Value::Null) || matches!(field(&reading, "windows"), Value::Null) {
            self.count("unfixed");
            self.say("the request finished, but usage could not be read afterwards");
            return Ok(true);
        }
        let tokens = {
            let mut map = car_machine::json::Map::new();
            for (name, value) in ["input", "cached", "output"].iter().zip(answered.tokens) {
                map.insert(
                    (*name).into(),
                    value.map_or(Value::Null, |n| Value::Int(n.into())),
                );
            }
            Value::Object(map)
        };
        self.memory().pending = Some(Pending {
            why: VERIFY,
            occurrence: occasion.at,
            first: reading.clone(),
            tokens: Some(tokens),
        });
        self.remember(&reading, now)?;
        Ok(true)
    }

    fn verified(&self, found: &str, reading: &Value, pending: &Pending) -> Answer<()> {
        let started = pending.occurrence;
        if found == RUNNING && !matches!(reading, Value::Null) {
            let (five, _weekly) = windows_of(field(reading, "windows")).map_err(Raised::new)?;
            let reset = match &five {
                Some(five) => item_of(five, "reset_at")?.clone(),
                None => Value::Null,
            };
            if let Some(reset) = int_value(&reset)
                && (reset as f64) > self.now()?
            {
                self.stamp(OptionKey::AnchorFixedAt, reset);
                self.stamp(OptionKey::AnchorSeenReset, reset);
                self.count("fixed");
                let local = self.inner.local.as_ref();
                let line = format!(
                    "the 5-hour window started at {}; its next reset is fixed at {} ({})",
                    hhmm(started as f64, local).map_err(Raised::new)?,
                    hhmm(reset as f64, local).map_err(Raised::new)?,
                    tokens_said(pending.tokens.as_ref().unwrap_or(&Value::Null)),
                );
                self.say(&line);
                return Ok(());
            }
        }
        self.count("unfixed");
        self.say("the request finished, but the 5-hour window did not show as started");
        Ok(())
    }

    // ------------------------------------------------------------------ helpers
    /// `_remember(reading, now)`: a running window's reset ahead, kept as the reset seen.
    fn remember(&self, reading: &Value, now: f64) -> Answer<()> {
        let reset = running_reset(reading, now).map_err(Raised::new)?;
        let Some(reset) = reset else {
            return Ok(());
        };
        let Ok(seen) = self.stamped(OptionKey::AnchorSeenReset) else {
            return Ok(());
        };
        if int_value(&seen) == Some(reset) && matches!(seen, Value::Int(_)) {
            return Ok(());
        }
        if self
            .stamp_raising(OptionKey::AnchorSeenReset, reset)
            .is_err()
        {
            return Ok(());
        }
        self.memory()
            .held_open
            .retain(|((why, _), _)| *why != RESET);
        self.show_retry();
        self.unstamp(OptionKey::AnchorStoppedAt);
        Ok(())
    }

    fn stamp_raising(&self, option: OptionKey, value: i64) -> Answer<bool> {
        self.bound()?
            .read(|scoped| scoped.stamp(&key(option), &Value::Int(value.into())))
    }

    /// `_past_weekly(why, reading, now)`.
    fn past_weekly(&self, why: &str, reading: &Value, now: f64) -> Answer<Option<f64>> {
        let windows = match reading {
            Value::Object(_) => field(reading, "windows").clone(),
            other if !car_machine::pyval::truthy(other) => Value::Null,
            _ => return Err(Raised::new("AttributeError")),
        };
        let (_five, weekly) = windows_of(&windows).map_err(Raised::new)?;
        let reset = weekly
            .as_ref()
            .map_or(Value::Null, |weekly| field(weekly, "reset_at").clone());
        Ok(match int_value(&reset) {
            Some(reset) if why == RESET && (reset as f64) > now => {
                Some((reset + WINDOW_SECONDS) as f64)
            }
            _ => None,
        })
    }

    /// `_skip(why, occurrence, reason, until)`.
    fn skip(
        &self,
        why: &'static str,
        occurrence: i64,
        reason: &'static str,
        until: Option<f64>,
    ) -> Answer<()> {
        let until = if reason == "ceiling" && why == RESET {
            Some((occurrence + DAY) as f64)
        } else {
            until
        };
        if (why == SLOT || why == RESET) && (PASSING.contains(&reason) || until.is_some()) {
            return self.held(why, occurrence, reason, until);
        }
        self.done(why, occurrence);
        self.count(skip_word(reason));
        Ok(())
    }

    fn strftime(&self, at: f64) -> Answer<String> {
        let moment = self
            .inner
            .local
            .localtime(super::anchor::whole(at).map_err(Raised::new)? as f64)
            .map_err(Raised::new)?;
        Ok(format!(
            "{:04}-{:02}-{:02} {:02}:{:02}",
            moment.year, moment.mon, moment.mday, moment.hour, moment.min
        ))
    }

    /// `_held(why, occurrence, reason, longer)`: a passing failure, tried again in RETRY_EVERY while its span lasts.
    fn held(
        &self,
        why: &'static str,
        occurrence: i64,
        reason: &'static str,
        longer: Option<f64>,
    ) -> Answer<()> {
        let now = self.now()?;
        let occasion = (why, occurrence);
        let span = if why == SLOT {
            SLOT_GRACE
        } else {
            WINDOW_SECONDS
        };
        let ceiling_wake = if reason == "ceiling" {
            Some(self.ceiling_frees(now))
        } else {
            None
        };
        let (first, held) = {
            let mut memory = self.memory();
            let first = !memory.held_open.iter().any(|(known, _)| *known == occasion);
            if first {
                memory.held_open.push((
                    occasion,
                    Held {
                        next: 0.0,
                        until: (occurrence + span) as f64,
                        reason: String::new(),
                        weekly: false,
                        wake: None,
                        said_weekly: false,
                    },
                ));
            }
            let held = &mut memory
                .held_open
                .iter_mut()
                .find(|(known, _)| *known == occasion)
                .expect("held")
                .1;
            held.next = now + RETRY_EVERY;
            held.reason = reason.to_owned();
            if let Some(longer) = longer {
                held.until = longer;
            }
            let weekly = reason == "weekly" && longer.is_some();
            if weekly {
                let longer = longer.unwrap_or(0.0);
                held.next = held.next.max(longer - WINDOW_SECONDS as f64 + RETRY_EVERY);
            }
            held.weekly = weekly;
            if reason == "ceiling" {
                if held.wake.is_none() {
                    held.wake = ceiling_wake;
                }
            } else {
                held.wake = None;
            }
            (first, held.clone())
        };
        if now >= held.until {
            return self.span_ended(occasion, now);
        }
        self.show_next();
        if held.weekly && !held.said_weekly {
            if let Some((_, kept)) = self
                .memory()
                .held_open
                .iter_mut()
                .find(|(known, _)| *known == occasion)
            {
                kept.said_weekly = true;
            }
            let line = format!(
                "the weekly limit is reached; looking again once it resets, at {}",
                self.strftime(held.next)?
            );
            self.say(&line);
            self.unstamp(OptionKey::AnchorStoppedAt);
            self.show_retry();
        } else if first && !held.weekly {
            let line = format!(
                "could not start the window now ({reason}); trying again every {} minutes until {}",
                RETRY_EVERY as i64 / 60,
                self.strftime(held.until)?
            );
            self.say(&line);
            self.unstamp(OptionKey::AnchorStoppedAt);
            self.show_retry();
        }
        Ok(())
    }

    /// `_span_ended(occasion, now)`: done, and its one journal line.
    fn span_ended(&self, occasion: (&'static str, i64), now: f64) -> Answer<()> {
        let reason = self
            .memory()
            .held_open
            .iter()
            .find(|(known, _)| *known == occasion)
            .map(|(_, held)| held.reason.clone())
            .ok_or_else(|| Raised::new("KeyError"))?;
        let kept = self.done(occasion.0, occasion.1);
        self.count(skip_word(&reason));
        let whole = super::anchor::whole(now).map_err(Raised::new)?;
        self.stamp(OptionKey::AnchorStoppedAt, whole.max(1));
        if kept != Some(true) {
            self.memory().held_open.push((
                occasion,
                Held {
                    next: f64::INFINITY,
                    until: f64::INFINITY,
                    reason,
                    weekly: false,
                    wake: None,
                    said_weekly: false,
                },
            ));
        }
        Ok(())
    }

    /// `_done(why, occurrence)`: what `_stamp` answered, True where there was nothing to stamp.
    fn done(&self, why: &str, occurrence: i64) -> Option<bool> {
        self.memory()
            .held_open
            .retain(|((known, at), _)| !(*known == why && *at == occurrence));
        self.show_retry();
        let option = match why {
            SLOT => Some(OptionKey::AnchorSlotDone),
            RESET => Some(OptionKey::AnchorResetDone),
            _ => None,
        };
        match option {
            Some(option) if occurrence >= 1 => self.stamp(option, occurrence),
            _ => Some(true),
        }
    }

    /// `_show_retry()`: its card's "trying again until".
    fn show_retry(&self) {
        self.show_next();
        let until = {
            let memory = self.memory();
            memory
                .held_open
                .iter()
                .filter(|(_, held)| held.until != f64::INFINITY && !held.weekly)
                .map(|(_, held)| held.until)
                .fold(None, |most: Option<f64>, until| {
                    Some(most.map_or(until, |most| most.max(until)))
                })
                .map(|until| until.trunc() as i64)
        };
        if self.memory().shown == Told2::Told(until) {
            return;
        }
        self.memory().shown = Told2::Told(until);
        match until {
            None => self.unstamp(OptionKey::AnchorRetryUntil),
            Some(until) => {
                self.stamp(OptionKey::AnchorRetryUntil, until);
            }
        }
    }

    /// `_ceiling_frees(now)`: when its ceiling of starts a day lets a start go again, or None.
    fn ceiling_frees(&self, now: f64) -> Option<i64> {
        let most = per_day();
        let bound = self.bound().ok()?;
        let full = |at: i64| -> Option<bool> {
            let made = bound
                .with(|scoped| {
                    scoped.counted_since(&word("started"), &Value::Int((at - DAY).into()))
                })?
                .ok()?;
            Some(made >= most)
        };
        let whole = now.trunc() as i64;
        let (mut low, mut high) = (whole, whole + DAY);
        if full(high)? {
            return None;
        }
        while high - low > 60 {
            let middle = (low + high).div_euclid(2);
            if full(middle)? {
                low = middle;
            } else {
                high = middle;
            }
        }
        Some(high)
    }

    /// `_show_next()`: the next look of an occasion held open, stamped for wake_for_reset.
    fn show_next(&self) {
        let found = {
            let memory = self.memory();
            memory
                .held_open
                .iter()
                .filter_map(|(_, held)| {
                    if held.weekly {
                        Some(held.next)
                    } else {
                        held.wake.flatten().map(|at| at as f64)
                    }
                })
                .filter(|at| *at != f64::INFINITY && !at.is_nan())
                .fold(None, |least: Option<f64>, at| {
                    Some(least.map_or(at, |least| least.min(at)))
                })
                .map(|at| at.trunc() as i64)
        };
        if self.memory().shown_next == Told2::Told(found) {
            return;
        }
        self.memory().shown_next = Told2::Told(found);
        match found {
            None => self.unstamp(OptionKey::AnchorNextLook),
            Some(at) => {
                self.stamp(OptionKey::AnchorNextLook, at);
            }
        }
    }

    /// `_backend()`: core's Backend for the pair the watcher told - never another.
    fn backend(&self) -> Answer<Box<dyn RequestBackend>> {
        if (self.inner.told)().is_none() {
            return Err(Raised::new("LookupError"));
        }
        (self.inner.backend)()
    }

    /// `_read(account)`: one usage read through a session of its own, or None.
    fn read(&self, account: bool) -> Value {
        let found = (|| -> Answer<(Value, Option<bool>)> {
            if (self.inner.told)().is_none() {
                return Err(Raised::new("LookupError"));
            }
            let opener = self
                .inner
                .session
                .as_ref()
                .ok_or_else(|| Raised::new("LookupError"))?;
            let mut session = opener()?;
            let signed = if account {
                signed_in(&session.call(
                    "account/read",
                    &Value::Object(car_machine::json::Map::new()),
                )?)
            } else {
                None
            };
            let reply = session.call(
                crate::codex::credits::READ,
                &Value::Object(car_machine::json::Map::new()),
            )?;
            let parsed = crate::codex::credits::parse(&reply).map_err(Raised::new)?;
            Ok((field(&parsed, "windows").clone(), signed))
        })();
        let Ok((windows, signed)) = found else {
            return Value::Null;
        };
        let Ok(now) = self.now() else {
            return Value::Null;
        };
        let mut reading = car_machine::json::Map::new();
        reading.insert("at".into(), Value::Float(now));
        reading.insert("windows".into(), windows);
        reading.insert("signed_in".into(), signed.map_or(Value::Null, Value::Bool));
        Value::Object(reading)
    }
}

/// `dictionary[key]` in the capability: a KeyError where it is missing.
fn item_of<'a>(value: &'a Value, name: &str) -> Answer<&'a Value> {
    match value {
        Value::Object(map) => map.get(name).ok_or_else(|| Raised::new("KeyError")),
        _ => Err(Raised::new("TypeError")),
    }
}

/// A number as Python compares it against one (`bool` is one); anything else a TypeError.
fn numeric_of(value: &Value) -> Answer<f64> {
    match value {
        Value::Bool(flag) => Ok(f64::from(u8::from(*flag))),
        Value::Int(number) => Ok(number.as_i64().map_or(f64::INFINITY, |n| n as f64)),
        Value::Float(number) => Ok(*number),
        _ => Err(Raised::new("TypeError")),
    }
}

struct AnchorErrand(WindowAnchor);

impl Errand for AnchorErrand {
    fn run(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        self.0
            .look(view, guards)
            .map(|()| Value::Null)
            .map_err(|_| HookFailed)
    }
}

impl Code for WindowAnchor {
    fn bind(&mut self, binding: crate::capabilities::Binding) -> Option<Result<(), Raised>> {
        self.bind_to(Bound::of(binding));
        Some(Ok(()))
    }

    fn tick(&mut self, _view: &dyn View) -> Spoke {
        self.ticked()
    }
}

/// `view(runtime)`: `{"window_anchor": {"started_at", "fixed_at", "retry_until", "stopped_at"}}` while it stands on.
pub fn view(armed: bool, stamped: &dyn Fn(OptionKey) -> Option<Value>, now: f64) -> Value {
    let mut found = car_machine::json::Map::new();
    if !armed {
        return Value::Object(found);
    }
    let (Some(started), Some(fixed), Some(retry), Some(stopped)) = (
        stamped(OptionKey::AnchorStartedAt),
        stamped(OptionKey::AnchorFixedAt),
        stamped(OptionKey::AnchorRetryUntil),
        stamped(OptionKey::AnchorStoppedAt),
    ) else {
        return Value::Object(found);
    };
    let ahead = |value: &Value| match int_value(value) {
        Some(at) if (at as f64) > now => value.clone(),
        _ => Value::Null,
    };
    let whole = |value: &Value| {
        if int_value(value).is_some() {
            value.clone()
        } else {
            Value::Null
        }
    };
    let mut inner = car_machine::json::Map::new();
    inner.insert("started_at".into(), whole(&started));
    inner.insert("fixed_at".into(), ahead(&fixed));
    inner.insert("retry_until".into(), ahead(&retry));
    inner.insert("stopped_at".into(), whole(&stopped));
    found.insert(CAPABILITY.into(), Value::Object(inner));
    Value::Object(found)
}

/// The product's begin: a daemon thread.
pub fn thread_begin(target: Box<dyn FnOnce() + Send>) -> Result<(), Raised> {
    std::thread::Builder::new()
        .spawn(target)
        .map(|_| ())
        .map_err(|_| Raised::new("RuntimeError"))
}

/// `make(paths)`: the pair the watcher told (`inuse.told`); the session, core's Backend and the watcher's log are the
/// entry points' to hand (S7.3d: `inuse.backend` over the live `Discovery`, `protocol.Session`, core's logbook) -
/// until then no usage can be read and no request is started (every occasion is held `unreadable`).
pub fn make(paths: &car_config::Paths) -> Option<Box<dyn Code>> {
    let home = paths.home.clone();
    Some(Box::new(WindowAnchor::new(
        paths.clone(),
        None,
        Box::new(move || crate::codex::inuse::told(Some(&home))),
        Box::new(|| Err(Raised::new("LookupError"))),
        Box::new(thread_begin),
        Box::new(|_line: &str| Ok(())),
        Box::new(car_platform::localclock::Crt),
    )))
}
