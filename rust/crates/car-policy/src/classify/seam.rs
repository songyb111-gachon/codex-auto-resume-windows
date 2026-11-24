//! SEAM, TO BE REPLACED by S2.2's `ownvalues` and plug (`domain/plug.py`) in this crate: the little of them the
//! classifier half reads, copied to the Python's rules exactly, so S2.1 does not wait for S2.2.
//!
//! | here | Python | owner |
//! |---|---|---|
//! | [`Own`], [`amount`], [`canonical`], [`coerce`], [`spell`] | `ownvalues.py` | S2.2 (settings) |
//! | [`TAKE_UP`], [`PACED_AS`], the [`Alternative`] and [`FailureForm`] words | `domain/plug.py`, `domain/vocabulary.py` | S2.2 (plug) |
//!
//! `tests/rustdiff/diffs_classify_policy.py` (`OwnValuesDiff`) holds the copy here to the reference; when S2.2's
//! modules land, these items become `pub use` lines of theirs and the diff keeps holding them.

use std::collections::BTreeSet;

use car_machine::json::Value;

// ------------------------------------------------------------------------------------------------- ownvalues.py

pub const DURATION: &str = "duration";
pub const CLOCK: &str = "clock";
pub const DAYS: &str = "days";
pub const COUNT: &str = "count";
pub const MINUTE: i64 = 60;
pub const HOUR: i64 = 3600;
pub const DAY: i64 = 86400;
pub const WEEK: i64 = 7 * DAY;
const DURATION_UNITS: &[(&str, i64)] = &[("s", 1), ("m", MINUTE), ("h", HOUR)];
const COUNT_UNITS: &[(&str, i64)] = &[("", 1), ("k", 1000), ("m", 1000 * 1000)];
pub const DAY_NAMES: &[&str] = &["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
/// `NAMED_DAYS`, in the dict's order: every day, weekdays, weekends.
const NAMED_DAYS: &[(&[i64], &str)] = &[
    (&[0, 1, 2, 3, 4, 5, 6], "every_day"),
    (&[0, 1, 2, 3, 4], "weekdays"),
    (&[5, 6], "weekends"),
];

/// `ownvalues.Own`: what a field takes of a person's own.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Own {
    pub kind: &'static str,
    pub low: i64,
    pub high: i64,
    pub units: &'static [&'static str],
    pub prefix: &'static str,
}

impl Own {
    pub const fn of(kind: &'static str) -> Own {
        Own {
            kind,
            low: 0,
            high: 0,
            units: &[],
            prefix: "",
        }
    }

    pub const fn bounded(
        kind: &'static str,
        low: i64,
        high: i64,
        units: &'static [&'static str],
    ) -> Own {
        Own {
            kind,
            low,
            high,
            units,
            prefix: "",
        }
    }
}

/// What `amount` measures: seconds, a minute of the day or a count; or a set of weekdays.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Measured {
    Number(i64),
    Days(BTreeSet<i64>),
}

impl Measured {
    pub fn number(&self) -> Option<i64> {
        match self {
            Measured::Number(n) => Some(*n),
            Measured::Days(_) => None,
        }
    }
}

/// `_whole(digits)`: digits as a number from 1 up; None for one written with a leading zero.
fn whole(digits: &str) -> Option<i64> {
    if digits.starts_with('0') {
        return None;
    }
    digits.parse().ok()
}

fn unit(table: &[(&str, i64)], name: &str) -> Option<i64> {
    table
        .iter()
        .find(|(each, _)| *each == name)
        .map(|(_, size)| *size)
}

/// `([0-9]{min,max})` at the start of `text`: the digits and the rest.
fn digits(text: &str, min: usize, max: usize) -> Option<(&str, &str)> {
    let count = text.bytes().take_while(u8::is_ascii_digit).count();
    (count >= min && count <= max).then(|| text.split_at(count))
}

/// `amount(spec, value)`: what `value` measures under `spec`, or None.
pub fn amount(spec: &Own, value: &Value) -> Option<Measured> {
    let Value::Str(raw) = value else {
        return None;
    };
    let value = raw.as_str()?;
    match spec.kind {
        DAYS => {
            if let Some((days, _)) = NAMED_DAYS.iter().find(|(_, name)| *name == value) {
                return Some(Measured::Days(days.iter().copied().collect()));
            }
            let mut found = BTreeSet::new();
            for name in value.split(',') {
                found.insert(DAY_NAMES.iter().position(|each| *each == name)? as i64);
            }
            Some(Measured::Days(found))
        }
        CLOCK => {
            // `([0-9]{1,2}):([0-9]{2})\Z`
            let (hours, rest) = digits(value, 1, 2)?;
            let rest = rest.strip_prefix(':')?;
            let (minutes, rest) = digits(rest, 2, 2)?;
            if !rest.is_empty() {
                return None;
            }
            let (hours, minutes): (i64, i64) = (hours.parse().ok()?, minutes.parse().ok()?);
            (hours <= 23 && minutes <= 59).then_some(Measured::Number(hours * 60 + minutes))
        }
        DURATION => {
            // `([smh])([0-9]{1,7})\Z`
            let mut chars = value.chars();
            let letter = chars.next()?;
            let size = unit(DURATION_UNITS, &letter.to_string())?;
            let (number, rest) = digits(chars.as_str(), 1, 7)?;
            if !rest.is_empty() {
                return None;
            }
            let seconds = whole(number)? * size;
            let finest = spec
                .units
                .first()
                .and_then(|name| unit(DURATION_UNITS, name))
                .unwrap_or(1);
            (spec.low <= seconds && seconds <= spec.high && seconds % finest == 0)
                .then_some(Measured::Number(seconds))
        }
        COUNT => {
            // `([0-9]{1,9})([km]?)\Z` after the prefix
            let body = value.strip_prefix(spec.prefix)?;
            let (number, rest) = digits(body, 1, 9)?;
            let suffix = match rest {
                "" => "",
                "k" => "k",
                "m" => "m",
                _ => return None,
            };
            let number = whole(number)?;
            if !suffix.is_empty() && !spec.units.contains(&suffix) {
                return None;
            }
            let count = number * unit(COUNT_UNITS, suffix)?;
            let finest = spec
                .units
                .first()
                .and_then(|name| unit(COUNT_UNITS, name))
                .unwrap_or(1);
            (spec.low <= count && count <= spec.high && count % finest == 0)
                .then_some(Measured::Number(count))
        }
        _ => None,
    }
}

/// `spell(spec, measured)`: `measured` in its one spelling.
pub fn spell(spec: &Own, measured: &Measured) -> String {
    match (spec.kind, measured) {
        (DAYS, Measured::Days(days)) => NAMED_DAYS
            .iter()
            .find(|(set, _)| set.len() == days.len() && set.iter().all(|day| days.contains(day)))
            .map(|(_, name)| (*name).to_owned())
            .unwrap_or_else(|| {
                days.iter()
                    .map(|day| DAY_NAMES[*day as usize])
                    .collect::<Vec<_>>()
                    .join(",")
            }),
        (CLOCK, Measured::Number(minute)) => format!("{:02}:{:02}", minute / 60, minute % 60),
        (kind, Measured::Number(measured)) => {
            let table = if kind == DURATION {
                DURATION_UNITS
            } else {
                COUNT_UNITS
            };
            let names: Vec<&str> = if spec.units.is_empty() {
                table.iter().map(|(name, _)| *name).collect()
            } else {
                spec.units.to_vec()
            };
            // `max(..., key=table.get)`: the first of the largest.
            let mut best: Option<(&str, i64)> = None;
            for name in names {
                let size = unit(table, name).unwrap_or(1);
                if measured % size == 0 && best.is_none_or(|(_, top)| size > top) {
                    best = Some((name, size));
                }
            }
            let (name, size) = best.unwrap_or(("", 1));
            let number = measured / size;
            if kind == DURATION {
                format!("{name}{number}")
            } else {
                format!("{}{number}{name}", spec.prefix)
            }
        }
        _ => String::new(),
    }
}

/// `canonical(spec, value, choices)`: `value` as it is stored, or None.
pub fn canonical(spec: &Own, value: &Value, choices: &[&str]) -> Option<String> {
    if let Some(word) = super::value::text(value)
        && choices.contains(&word)
    {
        return Some(word.to_owned());
    }
    let measured = amount(spec, value)?;
    if measured == Measured::Days(BTreeSet::new()) {
        return None;
    }
    Some(spell(spec, &measured))
}

/// `coerce(value, default, choices, spec)`: what is stored, or `default`.
pub fn coerce(value: &Value, default: &str, choices: &[&str], spec: &Own) -> String {
    canonical(spec, value, choices).unwrap_or_else(|| default.to_owned())
}

// ------------------------------------------------------------------------------------------- domain/plug.py

/// `domain/vocabulary.py` `Alternative`: the words the classifier half compares with.
pub mod alternative {
    pub const ADMIT: &str = "admit";
    pub const CAPACITY: &str = "capacity";
    pub const AS_NETWORK_TRANSIENT: &str = "as_network_transient";
    pub const AS_TIMEOUT: &str = "as_timeout";
    pub const AS_RATE_LIMIT_TRANSIENT: &str = "as_rate_limit_transient";
    pub const AS_SERVER_5XX: &str = "as_server_5xx";
    pub const AS_STREAM_INTERRUPTED: &str = "as_stream_interrupted";
}
pub use alternative as Alternative;

/// `domain/vocabulary.py` `FailureForm`.
pub mod failure_form {
    pub const TAGGED: &str = "tagged";
    pub const STATUS_ONLY: &str = "status_only";
    pub const UNRECOGNISED: &str = "unrecognised";
    pub const MESSAGE_ONLY: &str = "message_only";
    pub const ABSENT: &str = "absent";
}
pub use failure_form as FailureForm;

/// `domain/plug.py` `TAKE_UP` (a frozenset; sorted).
pub const TAKE_UP: &[&str] = &[
    "admit",
    "as_network_transient",
    "as_rate_limit_transient",
    "as_server_5xx",
    "as_stream_interrupted",
    "as_timeout",
    "capacity",
];

/// `domain/plug.py` `PACED_AS`, in the dict's order: the temporary kind each AS_ word is paced as.
pub const PACED_AS: &[(&str, &str)] = &[
    ("as_network_transient", "network_transient"),
    ("as_timeout", "timeout"),
    ("as_rate_limit_transient", "rate_limit_transient"),
    ("as_server_5xx", "server_5xx"),
    ("as_stream_interrupted", "stream_interrupted"),
];
