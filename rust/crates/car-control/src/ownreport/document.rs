//! `ownreport/document.py`: the report's body held to the project's rules, and this PC's own report as a file.
//!
//! `assemble` writes the envelope that names nobody; `check` is the self-check every report passes before it is
//! shown or exported - exactly the format's keys at every level, every string a time or a closed word, every count
//! a count. A record set larger than the project takes is a refusal with a closed code; anything else that breaks
//! the format would be a fault of this code (`DocumentError`).
//!
//! The other edition's in-app report (rust/GROUNDWORK.md, Integration 8) imports the body's self-check [`check_parts`], the bytes
//! a report is ([`encode`]), the closed refusals and the shapes of a time, a version and a Windows build from here
//! (Integration 8 folded S7.3c's copy in), so those helpers are public.

use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;

use super::evidence;

pub const FORMAT: &str = "codex-auto-resume-own-report/1";
pub const RULE: &str = "a record counts for this version only when the product's engine reports before and after it - or the version installed now - name this version and no other";
pub const COUNTING: &str = "a version is worked when at least one delivered record ended recovered, failed when at least one ended in a failed recovery, neither when no delivered record ended either way, and both when it is worked and failed at once";
pub const NOTE: &str = "Written on this PC from its own records and sent nowhere: counts, states and times, with no conversation text, identifiers, paths or names. progress_items are null: the Dashboard does not read Codex's history.";
/// `MAX_BYTES`: the receiving side's limit.
pub const MAX_BYTES: usize = 1_000_000;
pub const TOO_MANY_RECORDS: &str = "too_many_records";
pub const TOO_LARGE: &str = "too_large";

pub const LOCAL_KEYS: &[&str] = &["reports", "first", "last", "covers"];
pub const RECORD_KEYS: &[&str] = &[
    "detected_at",
    "delivered_at",
    "outcome_at",
    "category",
    "state",
    "reason",
    "turn_status",
    "gates_passed",
    "progress_items",
];
pub const CAPABILITY_KEYS: &[&str] = &["confirmed", "missed", "last_confirmed", "level"];
const BODY_KEYS: &[&str] = &[
    "codex_version",
    "verdict",
    "local_checks",
    "records",
    "capabilities",
];
pub const VERDICTS: &[&str] = &["PASS", "CHECKED", "NONE"];
pub const COUNTED: &[&str] = &["worked", "failed", "neither", "both"];
const TOP_KEYS: &[&str] = &[
    "format",
    "recorded_at",
    "product_version",
    "windows",
    "engine",
    "rule",
    "counting",
    "left_out",
    "versions",
    "note",
];
const ENGINE_KEYS: &[&str] = &["current", "from"];
const LEFT_OUT_KEYS: &[&str] = &["hidden", "another_route", "beyond_reach", "unplaced"];
const VERSION_KEYS: &[&str] = &["codex_version", "counted", "refusal", "body"];

/// What leaves a check: a refusal the project's rules make (`DocumentRefused`), or a fault (`DocumentError`, or the
/// class of another exception).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Fault {
    Refused(&'static str),
    Error(&'static str),
}

pub type Checked<T> = Result<T, Fault>;

pub fn error<T>() -> Checked<T> {
    Err(Fault::Error("DocumentError"))
}

pub fn map(value: &Value) -> Option<&Map> {
    match value {
        Value::Object(map) => Some(map),
        _ => None,
    }
}

pub fn at<'a>(value: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map(value).and_then(|map| map.get(name)).unwrap_or(&NULL)
}

/// `keys(value, wanted, where)`.
pub fn keys(value: &Value, wanted: &[&str]) -> Checked<()> {
    let Some(map) = map(value) else {
        return error();
    };
    if map.len() != wanted.len()
        || !map
            .keys()
            .zip(wanted)
            .all(|(key, want)| key.as_str() == Some(*want))
    {
        return error();
    }
    Ok(())
}

/// `word(value, words, where)`.
pub fn word(value: &Value, words: &[&str]) -> Checked<()> {
    match value {
        Value::Null => Ok(()),
        Value::Str(text) if text.as_str().is_some_and(|each| words.contains(&each)) => Ok(()),
        _ => error(),
    }
}

/// `ISO.match`: `\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z`, `\d` being any Unicode decimal digit.
pub fn iso_shape(text: &str) -> bool {
    let shape = "dddd-dd-ddTdd:dd:ddZ";
    let chars: Vec<char> = text.chars().collect();
    chars.len() == shape.len()
        && chars.iter().zip(shape.chars()).all(|(c, want)| {
            if want == 'd' {
                car_machine::pytext::decimal_value(*c).is_some()
            } else {
                *c == want
            }
        })
}

/// `moment(value, where, required=...)`.
pub fn moment(value: &Value, required: bool) -> Checked<()> {
    match value {
        Value::Null if required => error(),
        Value::Null => Ok(()),
        Value::Str(text) if text.as_str().is_some_and(iso_shape) => Ok(()),
        _ => error(),
    }
}

/// `count(value, where, limit=10 ** 6)`.
pub fn count(value: &Value, limit: i64) -> Checked<()> {
    match value {
        Value::Int(int) if int.as_i64().is_some_and(|n| (0..=limit).contains(&n)) => Ok(()),
        _ => error(),
    }
}

/// `check_parts(part, where)`: a body's local_checks, records and capabilities held to the format.
pub fn check_parts(part: &Value) -> Checked<()> {
    let checks = at(part, "local_checks");
    keys(checks, LOCAL_KEYS)?;
    count(at(checks, "reports"), 1_000_000)?;
    moment(at(checks, "first"), false)?;
    moment(at(checks, "last"), false)?;
    let reportable = evidence::reportable();
    let Value::Array(covers) = at(checks, "covers") else {
        return error();
    };
    let mut seen: Vec<&Value> = Vec::new();
    for each in covers {
        if seen.iter().any(|other| pyval::eq(other, each)) {
            return error();
        }
        seen.push(each);
        if !pyval::text(each).is_some_and(|name| reportable.contains(&name)) {
            return error();
        }
    }
    let Value::Array(records) = at(part, "records") else {
        return error();
    };
    if records.len() > evidence::MAX_RECORDS {
        return Err(Fault::Refused(TOO_MANY_RECORDS));
    }
    let with_other = |words: Vec<&'static str>| {
        let mut words = words;
        words.push(evidence::OTHER);
        words
    };
    let (categories, states, reasons, turns) = (
        with_other(evidence::categories()),
        with_other(evidence::states()),
        with_other(evidence::reasons()),
        with_other(evidence::turn_statuses()),
    );
    for record in records {
        keys(record, RECORD_KEYS)?;
        moment(at(record, "detected_at"), true)?;
        moment(at(record, "delivered_at"), false)?;
        moment(at(record, "outcome_at"), false)?;
        word(at(record, "category"), &categories)?;
        word(at(record, "state"), &states)?;
        word(at(record, "reason"), &reasons)?;
        word(at(record, "turn_status"), &turns)?;
        count(at(record, "gates_passed"), 64)?;
        let items = at(record, "progress_items");
        if !matches!(items, Value::Null) {
            keys(items, evidence::PROGRESS)?;
            for many in map(items)
                .map(|map| map.values().collect::<Vec<_>>())
                .unwrap_or_default()
            {
                count(many, 1_000_000)?;
            }
        }
    }
    let capabilities = at(part, "capabilities");
    keys(capabilities, &reportable)?;
    for entry in map(capabilities)
        .map(|map| map.values().collect::<Vec<_>>())
        .unwrap_or_default()
    {
        keys(entry, CAPABILITY_KEYS)?;
        count(at(entry, "confirmed"), evidence::MAX_RECORDS as i64)?;
        count(at(entry, "missed"), evidence::MAX_RECORDS as i64)?;
        moment(at(entry, "last_confirmed"), false)?;
        match at(entry, "level") {
            Value::Null => {}
            Value::Str(text)
                if text.as_str().is_some_and(|level| {
                    [evidence::VERIFIED, evidence::CHECKED].contains(&level)
                }) => {}
            _ => return error(),
        }
    }
    Ok(())
}

/// `PRODUCT_VERSION.match`: `\A\d{1,4}\.\d{1,4}\.\d{1,4}(?:-(?:alpha|beta)(?:\.\d{1,3})?)?\Z`.
pub fn product_version(text: &str) -> bool {
    let chars: Vec<char> = text.chars().collect();
    let run = |from: usize| {
        chars[from..]
            .iter()
            .take_while(|c| car_machine::pytext::decimal_value(**c).is_some())
            .count()
    };
    let mut at = 0;
    for index in 0..3 {
        let n = run(at);
        if !(1..=4).contains(&n) {
            return false;
        }
        at += n;
        if index < 2 {
            if chars.get(at) != Some(&'.') {
                return false;
            }
            at += 1;
        }
    }
    let tail: String = chars[at..].iter().collect();
    if tail.is_empty() {
        return true;
    }
    let Some(rest) = tail
        .strip_prefix("-alpha")
        .or_else(|| tail.strip_prefix("-beta"))
    else {
        return false;
    };
    if rest.is_empty() {
        return true;
    }
    let Some(number) = rest.strip_prefix('.') else {
        return false;
    };
    let digits: Vec<char> = number.chars().collect();
    (1..=3).contains(&digits.len())
        && digits
            .iter()
            .all(|c| car_machine::pytext::decimal_value(*c).is_some())
}

/// `WINDOWS.match`: `\A10\.0\.\d{5}\Z`.
pub fn windows_shape(text: &str) -> bool {
    let Some(build) = text.strip_prefix("10.0.") else {
        return false;
    };
    let chars: Vec<char> = build.chars().collect();
    chars.len() == 5
        && chars
            .iter()
            .all(|c| car_machine::pytext::decimal_value(*c).is_some())
}

/// `encode(document)`: two-space JSON, ASCII, one newline at the end.
pub fn encode(document: &Value) -> Checked<String> {
    match to_string(document, &Options::new().indent(2)) {
        Ok(text) => Ok(text + "\n"),
        Err(_) => Err(Fault::Error("ValueError")),
    }
}

/// `check(document)`: the report's bytes, once it is the format exactly.
pub fn check(document: &Value) -> Checked<String> {
    keys(document, TOP_KEYS)?;
    if !pyval::is(at(document, "format"), FORMAT)
        || !pyval::is(at(document, "rule"), RULE)
        || !pyval::is(at(document, "counting"), COUNTING)
        || !pyval::is(at(document, "note"), NOTE)
    {
        return error();
    }
    moment(at(document, "recorded_at"), true)?;
    match at(document, "product_version") {
        Value::Str(text)
            if text
                .as_str()
                .is_some_and(|version| version == "unknown" || product_version(version)) => {}
        _ => return error(),
    }
    match at(document, "windows") {
        Value::Null => {}
        Value::Str(text) if text.as_str().is_some_and(windows_shape) => {}
        _ => return error(),
    }
    let engine = at(document, "engine");
    keys(engine, ENGINE_KEYS)?;
    if !pyval::text(at(engine, "current")).is_some_and(evidence::version_matches) {
        return error();
    }
    word(at(engine, "from"), &["watcher_report", "log"])?;
    let left = at(document, "left_out");
    keys(left, LEFT_OUT_KEYS)?;
    for name in ["hidden", "another_route", "beyond_reach"] {
        count(at(left, name), 1_000_000)?;
    }
    keys(at(left, "unplaced"), evidence::UNPLACED)?;
    for many in map(at(left, "unplaced"))
        .map(|map| map.values().collect::<Vec<_>>())
        .unwrap_or_default()
    {
        count(many, 1_000_000)?;
    }
    let Value::Array(versions) = at(document, "versions") else {
        return error();
    };
    if versions.len() > 64 {
        return error();
    }
    let mut seen: Vec<String> = Vec::new();
    for entry in versions {
        keys(entry, VERSION_KEYS)?;
        let version = at(entry, "codex_version");
        let canonical = evidence::canonical_version(version);
        let text = pyval::text(version).map(str::to_owned);
        if canonical.is_none()
            || canonical != text
            || text.as_ref().is_some_and(|each| seen.contains(each))
        {
            return error();
        }
        seen.push(text.unwrap_or_default());
        let body = at(entry, "body");
        if matches!(body, Value::Null) {
            word(at(entry, "refusal"), &[TOO_MANY_RECORDS])?;
            if matches!(at(entry, "refusal"), Value::Null)
                || !matches!(at(entry, "counted"), Value::Null)
            {
                return error();
            }
            continue;
        }
        if !matches!(at(entry, "refusal"), Value::Null) {
            return error();
        }
        keys(body, BODY_KEYS)?;
        if !pyval::eq(at(body, "codex_version"), version)
            || !pyval::text(at(body, "verdict")).is_some_and(|verdict| VERDICTS.contains(&verdict))
        {
            return error();
        }
        check_parts(body)?;
        let records = match at(body, "records") {
            Value::Array(records) => records.clone(),
            _ => Vec::new(),
        };
        if !pyval::eq(at(entry, "counted"), &evidence::graded(&records)) {
            return error();
        }
    }
    let raw = encode(document)?;
    if raw.len() > MAX_BYTES {
        return Err(Fault::Refused(TOO_LARGE));
    }
    Ok(raw)
}

/// `assemble(found, product_version=..., windows=..., now=...)`: the Dashboard's own report, checked.
pub fn assemble(
    found: &Value,
    product_version: &str,
    windows: Option<&str>,
    now: f64,
) -> Checked<Value> {
    let mut versions = Vec::new();
    if let Value::Array(entries) = at(found, "versions") {
        for entry in entries {
            let body = at(entry, "body");
            let counted = if pyval::truthy(body) {
                match at(body, "records") {
                    Value::Array(records) => evidence::graded(records),
                    _ => Value::Null,
                }
            } else {
                Value::Null
            };
            let mut item = Map::new();
            item.insert(
                Str::from("codex_version"),
                at(entry, "codex_version").clone(),
            );
            item.insert(Str::from("counted"), counted);
            item.insert(Str::from("refusal"), at(entry, "refusal").clone());
            item.insert(Str::from("body"), body.clone());
            versions.push(Value::Object(item));
        }
    }
    let engine = at(found, "engine");
    let mut engine_out = Map::new();
    engine_out.insert(Str::from("current"), at(engine, "current").clone());
    engine_out.insert(Str::from("from"), at(engine, "from").clone());
    let left = at(found, "left_out");
    let mut left_out = Map::new();
    for name in LEFT_OUT_KEYS {
        left_out.insert(Str::from(*name), at(left, name).clone());
    }
    let recorded = evidence::iso(now).map_err(Fault::Error)?;
    let mut document = Map::new();
    let mut put = |name: &str, value: Value| {
        document.insert(Str::from(name), value);
    };
    put("format", Value::from(FORMAT));
    put("recorded_at", Value::from(recorded));
    put("product_version", Value::from(product_version));
    put("windows", windows.map_or(Value::Null, Value::from));
    put("engine", Value::Object(engine_out));
    put("rule", Value::from(RULE));
    put("counting", Value::from(COUNTING));
    put("left_out", Value::Object(left_out));
    put("versions", Value::Array(versions));
    put("note", Value::from(NOTE));
    let document = Value::Object(document);
    check(&document)?;
    Ok(document)
}

/// `written(document)`: what the Dashboard and the diagnostics export are given of one report.
pub fn written(document: &Value) -> Checked<Value> {
    let raw = check(document)?;
    let digest = car_machine::hash::hex(&car_machine::hash::sha256(raw.as_bytes()));
    let mut versions = Vec::new();
    if let Value::Array(entries) = at(document, "versions") {
        for entry in entries {
            let body = at(entry, "body");
            let records = match at(body, "records") {
                Value::Array(records) => Some(records),
                _ => None,
            };
            let has_body = pyval::truthy(body);
            let mut item = Map::new();
            item.insert(
                Str::from("codex_version"),
                at(entry, "codex_version").clone(),
            );
            item.insert(Str::from("refusal"), at(entry, "refusal").clone());
            item.insert(
                Str::from("verdict"),
                if has_body {
                    at(body, "verdict").clone()
                } else {
                    Value::Null
                },
            );
            item.insert(
                Str::from("records"),
                match (has_body, records) {
                    (true, Some(records)) => Value::from(records.len() as i64),
                    _ => Value::Null,
                },
            );
            item.insert(
                Str::from("delivered"),
                match (has_body, records) {
                    (true, Some(records)) => Value::from(
                        records
                            .iter()
                            .filter(|record| pyval::truthy(at(record, "delivered_at")))
                            .count() as i64,
                    ),
                    _ => Value::Null,
                },
            );
            let counted = at(entry, "counted");
            for name in COUNTED {
                item.insert(
                    Str::from(*name),
                    if pyval::truthy(counted) {
                        at(counted, name).clone()
                    } else {
                        Value::Null
                    },
                );
            }
            versions.push(Value::Object(item));
        }
    }
    let mut out = Map::new();
    out.insert(Str::from("sha256"), Value::from(digest));
    out.insert(Str::from("bytes"), Value::from(raw.len() as i64));
    out.insert(Str::from("text"), Value::from(raw));
    out.insert(Str::from("engine"), at(document, "engine").clone());
    out.insert(Str::from("versions"), Value::Array(versions));
    out.insert(Str::from("left_out"), at(document, "left_out").clone());
    Ok(Value::Object(out))
}
