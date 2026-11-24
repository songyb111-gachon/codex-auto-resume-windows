//! `ownvalues.py`: a person's own value beside a drop-down's choices (v0.6.11) - Custom..., and Unlimited.
//!
//! One rule. Whether a value is taken, and how it is written down, is answered here and nowhere else: the settings
//! coerce every such field with [`coerce`] and take a write that [`canonical`] spells as what they store; the modules
//! that read one ask [`amount`]; `describe()` publishes [`published`]. One value, one spelling: a value is kept in its
//! shortest exact form (60 minutes is `h1`, 90 is `m90`), and a set of days a choice names is that choice.
//!
//! Pure: words in, words and numbers out.

use car_machine::json::{Map, Str, Value};

use super::vocab_gen::ownvalues as words;

pub const UNLIMITED: &str = words::UNLIMITED;
pub const MINUTE: i64 = 60;
pub const HOUR: i64 = 3600;
pub const DAY: i64 = 86400;
pub const WEEK: i64 = 7 * DAY;
/// A duration's units, as its words start (`s5`, `m45`, `h3`), finest first.
pub const DURATION_UNITS: &[(&str, i64)] = &[("s", 1), ("m", MINUTE), ("h", HOUR)];
/// A count's units, as its words end.
pub const COUNT_UNITS: &[(&str, i64)] = &[("", 1), ("k", 1000), ("m", 1_000_000)];
/// The days, Monday first (`time.struct_time.tm_wday`).
pub const DAY_NAMES: &[&str] = words::DAY_NAMES;
/// The sets a choice names, as bit masks of DAY_NAMES' places, in `NAMED_DAYS`' order.
pub const NAMED_DAYS: &[(u8, &str)] = &[
    (0b111_1111, "every_day"),
    (0b001_1111, "weekdays"),
    (0b110_0000, "weekends"),
];

/// The kinds of a person's own value (`DURATION`, `CLOCK`, `DAYS`, `COUNT`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OwnKind {
    Duration,
    Clock,
    Days,
    Count,
}

impl OwnKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            OwnKind::Duration => "duration",
            OwnKind::Clock => "clock",
            OwnKind::Days => "days",
            OwnKind::Count => "count",
        }
    }
}

/// `Own`: what a field takes of a person's own - its kind, its bounds in the kind's own measure (seconds, or a
/// count), its units (the first the finest a value may be), and a count's prefix and catalog words.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Own {
    pub kind: OwnKind,
    pub low: i64,
    pub high: i64,
    pub units: &'static [&'static str],
    pub prefix: &'static str,
    pub amount: &'static str,
    pub label: &'static str,
}

impl Own {
    pub const fn new(kind: OwnKind, low: i64, high: i64, units: &'static [&'static str]) -> Own {
        Own {
            kind,
            low,
            high,
            units,
            prefix: "",
            amount: "",
            label: "",
        }
    }

    pub const fn prefix(mut self, prefix: &'static str) -> Own {
        self.prefix = prefix;
        self
    }

    pub const fn amount(mut self, amount: &'static str) -> Own {
        self.amount = amount;
        self
    }

    pub const fn label(mut self, label: &'static str) -> Own {
        self.label = label;
        self
    }
}

/// What a value measures: seconds or a count, a minute of the day, or a set of weekdays (bit `n` for DAY_NAMES[n]).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Measured {
    Number(i64),
    Minute(i64),
    Days(u8),
}

impl Measured {
    /// The number a duration, a count or a clock measures; None for a set of days.
    pub fn number(self) -> Option<i64> {
        match self {
            Measured::Number(number) | Measured::Minute(number) => Some(number),
            Measured::Days(_) => None,
        }
    }

    /// The weekdays a set holds, as the numbers `time.struct_time.tm_wday` gives, Monday first.
    pub fn days(self) -> std::collections::BTreeSet<i64> {
        match self {
            Measured::Days(mask) => (0..7).filter(|day| mask & (1 << day) != 0).collect(),
            _ => std::collections::BTreeSet::new(),
        }
    }
}

fn unit_value(table: &[(&str, i64)], name: &str) -> Option<i64> {
    table
        .iter()
        .find(|(unit, _)| *unit == name)
        .map(|(_, value)| *value)
}

/// `_whole(digits)`: the number from 1 up; None for 0 or a leading zero. `digits` are 1 to 9 ASCII digits.
fn whole(digits: &str) -> Option<i64> {
    if digits.starts_with('0') {
        None
    } else {
        digits.parse().ok()
    }
}

/// The ASCII digits at the start of `text`, at most `most` of them, and what follows.
fn digits(text: &str, most: usize) -> (&str, &str) {
    let end = text.bytes().take_while(u8::is_ascii_digit).count();
    if end > most {
        (&text[..0], text)
    } else {
        text.split_at(end)
    }
}

/// `amount(spec, value)`: what `value` measures under `spec`, or None - not this kind's words, finer than its first
/// unit, or out of bounds. A named choice of days is its set.
pub fn amount(spec: &Own, value: &Value) -> Option<Measured> {
    let Value::Str(text) = value else { return None };
    // A text with a surrogate holds no word of any kind below.
    let text = text.as_str()?;
    match spec.kind {
        OwnKind::Days => {
            if let Some((mask, _)) = NAMED_DAYS.iter().find(|(_, name)| *name == text) {
                return Some(Measured::Days(*mask));
            }
            let mut mask = 0u8;
            for name in text.split(',') {
                let place = DAY_NAMES.iter().position(|day| *day == name)?;
                mask |= 1 << place;
            }
            Some(Measured::Days(mask))
        }
        OwnKind::Clock => {
            // ([0-9]{1,2}):([0-9]{2})\Z
            let (hours, rest) = digits(text, 2);
            let minutes = rest.strip_prefix(':')?;
            if hours.is_empty()
                || minutes.len() != 2
                || !minutes.bytes().all(|b| b.is_ascii_digit())
            {
                return None;
            }
            let (hours, minutes): (i64, i64) = (hours.parse().ok()?, minutes.parse().ok()?);
            if hours > 23 || minutes > 59 {
                return None;
            }
            Some(Measured::Minute(hours * 60 + minutes))
        }
        OwnKind::Duration => {
            // ([smh])([0-9]{1,7})\Z
            let mut chars = text.chars();
            let unit = chars.next()?;
            let unit = match unit {
                's' | 'm' | 'h' => unit,
                _ => return None,
            };
            let rest = chars.as_str();
            if rest.is_empty() || rest.len() > 7 || !rest.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            let number = whole(rest)?;
            let seconds = number * unit_value(DURATION_UNITS, &unit.to_string())?;
            let finest = spec
                .units
                .first()
                .and_then(|first| unit_value(DURATION_UNITS, first))
                .unwrap_or(1);
            (spec.low <= seconds && seconds <= spec.high && seconds % finest == 0)
                .then_some(Measured::Number(seconds))
        }
        OwnKind::Count => {
            // prefix, then ([0-9]{1,9})([km]?)\Z
            let rest = text.strip_prefix(spec.prefix)?;
            let (number, suffix) = digits(rest, 9);
            if number.is_empty() || !matches!(suffix, "" | "k" | "m") {
                return None;
            }
            let number = whole(number)?;
            if !suffix.is_empty() && !spec.units.contains(&suffix) {
                return None;
            }
            let count = number * unit_value(COUNT_UNITS, suffix)?;
            let finest = spec
                .units
                .first()
                .and_then(|first| unit_value(COUNT_UNITS, first))
                .unwrap_or(1);
            (spec.low <= count && count <= spec.high && count % finest == 0)
                .then_some(Measured::Number(count))
        }
    }
}

/// `spell(spec, measured)`: `measured` in its one spelling.
pub fn spell(spec: &Own, measured: Measured) -> String {
    match measured {
        Measured::Days(mask) => match NAMED_DAYS.iter().find(|(named, _)| *named == mask) {
            Some((_, name)) => (*name).to_owned(),
            None => (0..7)
                .filter(|day| mask & (1 << day) != 0)
                .map(|day| DAY_NAMES[day])
                .collect::<Vec<_>>()
                .join(","),
        },
        Measured::Minute(minute) => format!("{:02}:{:02}", minute / 60, minute % 60),
        Measured::Number(value) => {
            let table = if spec.kind == OwnKind::Duration {
                DURATION_UNITS
            } else {
                COUNT_UNITS
            };
            let names: Vec<&str> = if spec.units.is_empty() {
                table.iter().map(|(name, _)| *name).collect()
            } else {
                spec.units.to_vec()
            };
            // max(..., key=table.get): the largest unit that measures it exactly; the first of equals wins.
            let mut best: Option<(&str, i64)> = None;
            for name in names {
                let size = unit_value(table, name).unwrap_or(1);
                if value % size == 0 && best.is_none_or(|(_, held)| size > held) {
                    best = Some((name, size));
                }
            }
            let (unit, size) = best.unwrap_or(("", 1));
            let number = (value / size).to_string();
            if spec.kind == OwnKind::Duration {
                format!("{unit}{number}")
            } else {
                format!("{}{number}{unit}", spec.prefix)
            }
        }
    }
}

/// `canonical(spec, value, choices)`: `value` as it is stored, or None when the field does not take it.
pub fn canonical(spec: Option<&Own>, value: &Value, choices: &[&str]) -> Option<Value> {
    if let Value::Str(text) = value
        && text.as_str().is_some_and(|text| choices.contains(&text))
    {
        return Some(value.clone());
    }
    let spec = spec?;
    match amount(spec, value)? {
        Measured::Days(0) => None,
        measured => Some(Value::from(spell(spec, measured))),
    }
}

/// `coerce(value, default, choices, spec)`: what is stored, or `default` for anything not taken.
pub fn coerce(value: &Value, default: &Value, choices: &[&str], spec: &Own) -> Value {
    canonical(Some(spec), value, choices).unwrap_or_else(|| default.clone())
}

/// `pattern(spec)`: the words `spec` takes, as a JSON Schema pattern (the form, never the bounds).
pub fn pattern(spec: &Own) -> String {
    match spec.kind {
        OwnKind::Days => {
            let names = DAY_NAMES.join("|");
            format!("^({names})(,({names}))*$")
        }
        OwnKind::Clock => "^[0-9]{1,2}:[0-9]{2}$".to_owned(),
        OwnKind::Duration => "^[smh][1-9][0-9]*$".to_owned(),
        OwnKind::Count => {
            let suffixes: Vec<&str> = spec
                .units
                .iter()
                .copied()
                .filter(|unit| !unit.is_empty())
                .collect();
            let tail = if suffixes.is_empty() {
                String::new()
            } else {
                format!("({})?", suffixes.join("|"))
            };
            format!("^{}[1-9][0-9]*{tail}$", escape(spec.prefix))
        }
    }
}

/// `re.escape(text)`: every character of Python's special set escaped with a backslash.
fn escape(text: &str) -> String {
    const SPECIAL: &str = "()[]{}?*+-|^$\\.&~# \t\n\r\u{b}\u{c}";
    text.chars().fold(String::new(), |mut out, each| {
        if SPECIAL.contains(each) {
            out.push('\\');
        }
        out.push(each);
        out
    })
}

/// `published(spec)`: what describe() says of a field's own values.
pub fn published(spec: &Own) -> Value {
    let mut said = Map::new();
    said.insert(Str::from("kind"), Value::from(spec.kind.as_str()));
    said.insert(Str::from("pattern"), Value::from(pattern(spec)));
    if matches!(spec.kind, OwnKind::Duration | OwnKind::Count) {
        said.insert(Str::from("min"), Value::from(spec.low));
        said.insert(Str::from("max"), Value::from(spec.high));
        said.insert(
            Str::from("units"),
            Value::Array(spec.units.iter().map(|unit| Value::from(*unit)).collect()),
        );
    }
    for (name, text) in [
        ("prefix", spec.prefix),
        ("amount", spec.amount),
        ("label", spec.label),
    ] {
        if !text.is_empty() {
            said.insert(Str::from(name), Value::from(text));
        }
    }
    if spec.kind == OwnKind::Days {
        said.insert(
            Str::from("days"),
            Value::Array(DAY_NAMES.iter().map(|day| Value::from(*day)).collect()),
        );
        let mut named = Map::new();
        for (mask, name) in NAMED_DAYS {
            let days = (0..7)
                .filter(|day| mask & (1 << day) != 0)
                .map(|day| Value::from(DAY_NAMES[day]))
                .collect();
            named.insert(Str::from(*name), Value::Array(days));
        }
        said.insert(Str::from("named"), Value::Object(named));
    }
    Value::Object(said)
}
