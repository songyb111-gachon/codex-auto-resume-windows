//! `managed.py`: what an administrator has set - the standard edition's seven policy keys (v0.6.11).
//!
//! `Software\Policies\CodexAutoResume`, in HKEY_LOCAL_MACHINE and HKEY_CURRENT_USER. Read (car-platform's
//! `registry_reads::read_policies`, never written) and handed here as they came, data and type together; each can only
//! hold recovery back, and a value that is there and could not be read holds the most it could. Applied after the
//! settings are read (`clamp`), never to the file; a write that would loosen what a key holds is refused (`admit`).
//! Nothing here reads the registry, the clock or a file.

use car_machine::json::{Map, Str, Value};
use car_machine::pytext;
use car_machine::pyval::{self, Num};

use super::seam;
use super::vocab_gen::managed as words;

pub const KEY: &str = words::KEY;
pub const DISABLE_AUTO_RESUME: &str = words::DISABLE_AUTO_RESUME;
pub const FORCE_OBSERVE_ONLY: &str = words::FORCE_OBSERVE_ONLY;
pub const DISABLE_UPDATE_CHECK: &str = words::DISABLE_UPDATE_CHECK;
pub const DISABLE_STATUS_FILE: &str = words::DISABLE_STATUS_FILE;
pub const MAX_RECOVERY_ATTEMPTS: &str = words::MAX_RECOVERY_ATTEMPTS;
pub const QUIET_HOURS: &str = words::QUIET_HOURS;
pub const DISABLE_POWER_ACTION: &str = words::DISABLE_POWER_ACTION;
pub const VALUES: &[&str] = words::VALUES;
pub const STATUS_FILE_FIELDS: &[&str] = words::STATUS_FILE_FIELDS;
const SWITCHES: &[&str] = &[
    DISABLE_AUTO_RESUME,
    FORCE_OBSERVE_ONLY,
    DISABLE_UPDATE_CHECK,
    DISABLE_STATUS_FILE,
    DISABLE_POWER_ACTION,
];
/// The registry's own type numbers, and the reader's word for a value there and unreadable.
pub const REG_SZ: i64 = 1;
pub const REG_EXPAND_SZ: i64 = 2;
pub const REG_DWORD: i64 = 4;
pub const REG_QWORD: i64 = 11;
pub const REG_UNREADABLE: i64 = -1;
/// `settings.RANGES["max_recovery_attempts"]`.
const ATTEMPTS: (i64, i64) = (1, 20);

/// What the keys hold, once both places are read: each restriction, and nothing else.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Managed {
    pub disable_auto_resume: bool,
    pub force_observe_only: bool,
    pub disable_update_check: bool,
    pub disable_status_file: bool,
    pub max_recovery_attempts: Option<i64>,
    /// Each place's quiet hours, as the three settings that name a window, HKEY_LOCAL_MACHINE's first.
    pub quiet_hours: Vec<Map>,
    pub disable_power_action: bool,
}

impl Managed {
    /// `codes()`: the values in force, by their registry names, in VALUES order.
    pub fn codes(&self) -> Vec<&'static str> {
        let held = [
            self.disable_auto_resume,
            self.force_observe_only,
            self.disable_update_check,
            self.disable_status_file,
            self.max_recovery_attempts.is_some(),
            !self.quiet_hours.is_empty(),
            self.disable_power_action,
        ];
        VALUES
            .iter()
            .zip(held)
            .filter(|(_, on)| *on)
            .map(|(name, _)| *name)
            .collect()
    }

    pub fn active(&self) -> bool {
        !self.codes().is_empty()
    }
}

/// An entry as the reader hands it: `(data, type)`, a two-item list here.
fn pair(entry: Option<&Value>) -> Option<(&Value, &Value)> {
    match entry {
        Some(Value::Array(items)) if items.len() == 2 => Some((&items[0], &items[1])),
        _ => None,
    }
}

fn kind_is(kind: &Value, kinds: &[i64]) -> bool {
    kinds
        .iter()
        .any(|each| pyval::eq(kind, &Value::from(*each)))
}

fn switch((value, kind): (&Value, &Value)) -> bool {
    kind_is(kind, &[REG_DWORD, REG_QWORD])
        && matches!(value, Value::Int(int) if int.as_i64() != Some(0))
}

fn ceiling((value, kind): (&Value, &Value)) -> Option<i64> {
    if !kind_is(kind, &[REG_DWORD, REG_QWORD]) {
        return None;
    }
    match value {
        Value::Int(int) => int
            .as_i64()
            .filter(|number| ATTEMPTS.0 <= *number && *number <= ATTEMPTS.1),
        _ => None,
    }
}

fn unreadable(entry: Option<&Value>) -> bool {
    pair(entry).is_some_and(|(_, kind)| pyval::eq(kind, &Value::from(REG_UNREADABLE)))
}

/// `quiet_window(text)`: a QuietHours value as the three settings that name the same window, or None.
pub fn quiet_window(text: &Value) -> Option<Map> {
    let Value::Str(text) = text else { return None };
    let chars: Vec<char> = text
        .code_points()
        .map(|point| char::from_u32(point).unwrap_or('\u{fffd}'))
        .collect();
    let space = |at: usize| chars.get(at).is_some_and(|each| pytext::is_space(*each));
    let skip = |mut at: usize| {
        while space(at) {
            at += 1;
        }
        at
    };
    let digit = |at: usize| {
        chars
            .get(at)
            .is_some_and(|each| pytext::decimal_value(*each).is_some())
    };
    // (\d{2}:\d{2})
    let clock = |at: usize| -> Option<(String, usize)> {
        (digit(at)
            && digit(at + 1)
            && chars.get(at + 2) == Some(&':')
            && digit(at + 3)
            && digit(at + 4))
        .then(|| (chars[at..at + 5].iter().collect(), at + 5))
    };
    let (start, at) = clock(skip(0))?;
    let at = skip(at);
    if chars.get(at) != Some(&'-') {
        return None;
    }
    let (end, at) = clock(skip(at + 1))?;
    let word_at = skip(at);
    let mut days: Option<String> = None;
    if word_at > at
        && chars
            .get(word_at)
            .is_some_and(|each| each.is_ascii_lowercase() || *each == '_')
    {
        let mut after = word_at;
        while chars
            .get(after)
            .is_some_and(|each| each.is_ascii_lowercase() || *each == '_')
        {
            after += 1;
        }
        if skip(after) != chars.len() {
            return None;
        }
        days = Some(chars[word_at..after].iter().collect());
    } else if word_at != chars.len() {
        return None;
    }
    let days = days.unwrap_or_else(|| seam::QUIET_DEFAULT_DAYS.to_owned());
    if !seam::QUIET_TIMES.contains(&start.as_str())
        || !seam::QUIET_TIMES.contains(&end.as_str())
        || start == end
        || !seam::QUIET_DAYS.contains(&days.as_str())
    {
        return None;
    }
    let mut window = Map::new();
    window.insert(Str::from("quiet_hours_start"), Value::from(start));
    window.insert(Str::from("quiet_hours_end"), Value::from(end));
    window.insert(Str::from("quiet_hours_days"), Value::from(days));
    Some(window)
}

/// `parse(places)`: what the places hold - one object per place read, HKEY_LOCAL_MACHINE's first, of a value's name to
/// its `[data, type]` - with every restriction of either kept, and the most a value could hold kept for one that could
/// not be read.
pub fn parse(places: &Value) -> Managed {
    let mut switches: Vec<&str> = Vec::new();
    let mut ceilings: Vec<i64> = Vec::new();
    let mut windows: Vec<Map> = Vec::new();
    let places: &[Value] = match places {
        Value::Array(items) => items,
        _ => &[],
    };
    for place in places {
        let Value::Object(place) = place else {
            continue;
        };
        for name in SWITCHES {
            let entry = place.get(*name);
            if unreadable(entry) || pair(entry).is_some_and(switch) {
                switches.push(*name);
            }
        }
        let entry = place.get(MAX_RECOVERY_ATTEMPTS);
        if unreadable(entry) {
            ceilings.push(ATTEMPTS.0);
        } else if let Some(found) = pair(entry).and_then(ceiling) {
            ceilings.push(found);
        }
        let entry = place.get(QUIET_HOURS);
        if unreadable(entry) {
            switches.push(FORCE_OBSERVE_ONLY);
        } else if let Some((data, kind)) = pair(entry)
            && kind_is(kind, &[REG_SZ, REG_EXPAND_SZ])
            && let Some(window) = quiet_window(data)
            && !windows.contains(&window)
        {
            windows.push(window);
        }
    }
    let on = |name: &str| switches.contains(&name);
    Managed {
        disable_auto_resume: on(DISABLE_AUTO_RESUME),
        force_observe_only: on(FORCE_OBSERVE_ONLY),
        disable_update_check: on(DISABLE_UPDATE_CHECK),
        disable_status_file: on(DISABLE_STATUS_FILE),
        max_recovery_attempts: ceilings.iter().min().copied(),
        quiet_hours: windows,
        disable_power_action: on(DISABLE_POWER_ACTION),
    }
}

/// `fields(managed)`: the settings a key decides while it is set, sorted.
pub fn fields(managed: &Managed) -> Vec<&'static str> {
    let mut names = Vec::new();
    if managed.force_observe_only {
        names.push("observe_only");
    }
    if managed.max_recovery_attempts.is_some() {
        names.push("max_recovery_attempts");
    }
    if !managed.quiet_hours.is_empty() {
        names.extend(["quiet_hours_start", "quiet_hours_end", "quiet_hours_days"]);
    }
    if managed.disable_status_file {
        names.extend(
            STATUS_FILE_FIELDS
                .iter()
                .filter(|name| super::field_named(name).is_some()),
        );
    }
    names.sort_unstable();
    names.dedup();
    names
}

/// `ceilings(managed)`: the settings a key holds under a ceiling, with the most it lets them be.
pub fn ceilings(managed: &Managed) -> Map {
    let mut held = Map::new();
    if let Some(most) = managed.max_recovery_attempts {
        held.insert(Str::from("max_recovery_attempts"), Value::from(most));
    }
    held
}

/// `clamp(values, managed)`: the settings as the keys leave them; with no key set, `values` itself.
pub fn clamp(values: &Map, managed: &Managed) -> Map {
    if !managed.active() {
        return values.clone();
    }
    let mut held = values.clone();
    if managed.force_observe_only {
        held.insert(Str::from("observe_only"), Value::Bool(true));
    }
    if let (Some(most), Some(Value::Int(own))) = (
        managed.max_recovery_attempts,
        values.get("max_recovery_attempts"),
    ) {
        let own_value = Value::Int(own.clone());
        let lower = Num::of(&own_value)
            .and_then(|found| pyval::compare(found, Num::Whole(i128::from(most))))
            .is_some_and(|order| order.is_le());
        held.insert(
            Str::from("max_recovery_attempts"),
            if lower { own_value } else { Value::from(most) },
        );
    }
    if let Some(first) = managed.quiet_hours.first() {
        for (name, value) in first {
            held.insert(name.clone(), value.clone());
        }
    }
    if managed.disable_status_file {
        for name in STATUS_FILE_FIELDS {
            if let Some(field) = super::field_named(name) {
                held.insert(Str::from(*name), field.default.value());
            }
        }
    }
    held
}

fn same_type(a: &Value, b: &Value) -> bool {
    std::mem::discriminant(a) == std::mem::discriminant(b)
}

/// `admit(changes, effective, managed)`: an edit as the keys let it be stored - what to write, and the first setting
/// refused or None.
pub fn admit(changes: &Map, effective: &Map, managed: &Managed) -> (Map, Option<Str>) {
    let decided = fields(managed);
    let mut kept = Map::new();
    static NULL: Value = Value::Null;
    for (name, value) in changes {
        let text = name.as_str().unwrap_or_default();
        if !decided.contains(&text) {
            kept.insert(name.clone(), value.clone());
            continue;
        }
        let current = effective.get(name).unwrap_or(&NULL);
        if pyval::eq(value, current) && same_type(value, current) {
            continue;
        }
        if text == "max_recovery_attempts"
            && let (Value::Int(_), Some(most)) = (value, managed.max_recovery_attempts)
            && Num::of(value)
                .and_then(|found| pyval::compare(found, Num::Whole(i128::from(most))))
                .is_some_and(|order| order.is_le())
        {
            kept.insert(name.clone(), value.clone());
            continue;
        }
        return (kept, Some(name.clone()));
    }
    (kept, None)
}

/// `quiet_sources(own, managed)`: every window quiet hours are asked of - the settings' own, then each
/// administrator's.
pub fn quiet_sources(own: &Value, managed: &Managed) -> Vec<Value> {
    let mut sources = vec![own.clone()];
    sources.extend(
        managed
            .quiet_hours
            .iter()
            .map(|window| Value::Object(window.clone())),
    );
    sources
}
