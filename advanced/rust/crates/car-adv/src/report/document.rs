//! The compatibility report as a file (`report/document.py`): `records.py`'s body, in the envelope codex-compat-reporter
//! writes around it, held to the project's rules before anyone reads it - and, beside it, the part of core's
//! `ownreport/document.py` the advanced report imports (the body's self-check `check_parts`, the bytes a report is,
//! the closed refusals, the shapes of a time, a version and a Windows build).
//!
//! The format is the maintainer's own (`codex-auto-resume-compat-evidence/1`), and the keys come in the order the
//! reporter writes them (its `build`), so the two programs write the same file of the same records but for who wrote
//! it: `recorded_by` and `reporter` name this product, its version as the tool's. `check` is the self-check every
//! document passes before it is shown, saved or sent: exactly the format's keys at every level, every string a time,
//! a version, one of the product's closed words or one of the envelope's own fixed values, at most 500 records and at
//! most 1 MB as written. What a person can change - the login, or a report too big to send - is a refusal with a
//! closed code; anything else would be a fault of this code, and is an error.
//!
//! SEAT S7.3c. The core half is car-control's `ownreport::document` at bridge6 (`acea87eb0`) as far as the
//! Dashboard's report shares it (`check_parts` and the shapes); what only the Dashboard's own report uses (`assemble`
//! of every version, `written`) is not here, and what only the advanced one uses (the envelope) is. The product's
//! version and the Windows build this process runs on are the [`Facts`] seam (`config.version()`,
//! `sys.getwindowsversion()`).

use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;

use super::evidence;

pub const FORMAT: &str = "codex-auto-resume-compat-evidence/1";
pub const TOOL: &str = "codex-auto-resume";
pub const EDITION: &str = "advanced";
/// The repository a report is sent to.
pub const REPOSITORY: &str = "songyb111-gachon/codex-auto-resume-windows";
pub const RECORDED_BY: &str =
    "Codex Auto Resume %s (advanced edition), on a contributor's Windows machine";
pub const NOTE: &str = "Content-free: counts, states and times from this machine's own records, with no conversation text, identifiers or paths, counted only towards the Reported grade beside the version and never towards a version's tier.";
/// The reporter's own sentence (`ownreport.document.RULE`), word for word.
pub const RULE: &str = "a record counts for this version only when the product's engine reports before and after it - or the version installed now - name this version and no other";
/// The receiving side's limit (`build/community_report.py`).
pub const MAX_BYTES: usize = 1_000_000;
pub const TOO_MANY_RECORDS: &str = "too_many_records";
pub const TOO_LARGE: &str = "too_large";
pub const LOGIN_INVALID: &str = "login_invalid";
pub const LOGIN_RESERVED: &str = "login_reserved";
pub const LOGIN_OWNER: &str = "login_owner";

const TOP_KEYS: &[&str] = &[
    "format",
    "codex_version",
    "verdict",
    "recorded_at",
    "recorded_by",
    "reporter",
    "attribution",
    "local_checks",
    "records",
    "capabilities",
    "note",
];
const REPORTER_KEYS: &[&str] = &[
    "github_login",
    "tool",
    "tool_version",
    "product_version",
    "windows",
];
const ATTRIBUTION_KEYS: &[&str] = &["rule", "window", "basis"];
const LOCAL_KEYS: &[&str] = &["reports", "first", "last", "covers"];
const RECORD_KEYS: &[&str] = &[
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
const CAPABILITY_KEYS: &[&str] = &["confirmed", "missed", "last_confirmed", "level"];
const VERDICTS: &[&str] = &["PASS", "CHECKED", "NONE"];

/// What the report asks of the process it runs in: the product's version (`config.version()`) and the Windows build
/// (`document.windows_version()`: `sys.getwindowsversion()`, never `platform`).
pub trait Facts {
    fn product_version(&self) -> String;
    fn windows_version(&self) -> Option<String>;
}

/// What leaves a check: a refusal the project's rules make (`DocumentRefused`), or a fault (`DocumentError`, or the
/// class of another exception).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Fault {
    Refused(&'static str),
    Error(&'static str),
}

type Checked<T> = Result<T, Fault>;

fn error<T>() -> Checked<T> {
    Err(Fault::Error("DocumentError"))
}

fn map(value: &Value) -> Option<&Map> {
    match value {
        Value::Object(map) => Some(map),
        _ => None,
    }
}

fn at<'a>(value: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map(value).and_then(|map| map.get(name)).unwrap_or(&NULL)
}

/// `keys(value, wanted, where)`.
fn keys(value: &Value, wanted: &[&str]) -> Checked<()> {
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
fn word(value: &Value, words: &[&str]) -> Checked<()> {
    match value {
        Value::Null => Ok(()),
        Value::Str(text) if text.as_str().is_some_and(|each| words.contains(&each)) => Ok(()),
        _ => error(),
    }
}

/// `ISO.match`: `\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z`, `\d` being any Unicode decimal digit.
fn iso_shape(text: &str) -> bool {
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
fn moment(value: &Value, required: bool) -> Checked<()> {
    match value {
        Value::Null if required => error(),
        Value::Null => Ok(()),
        Value::Str(text) if text.as_str().is_some_and(iso_shape) => Ok(()),
        _ => error(),
    }
}

/// `count(value, where, limit=10 ** 6)`.
fn count(value: &Value, limit: i64) -> Checked<()> {
    match value {
        Value::Int(int) if int.as_i64().is_some_and(|n| (0..=limit).contains(&n)) => Ok(()),
        _ => error(),
    }
}

/// `check_parts(part, where)`: a body's local_checks, records and capabilities held to the format.
fn check_parts(part: &Value) -> Checked<()> {
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
fn product_version(text: &str) -> bool {
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
fn windows_shape(text: &str) -> bool {
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

/// `RESERVED`: the names Windows keeps for devices, which no folder can have.
fn reserved(name: &str) -> bool {
    matches!(name, "con" | "prn" | "aux" | "nul")
        || (name.len() == 4
            && (name.starts_with("com") || name.starts_with("lpt"))
            && name.as_bytes()[3].is_ascii_digit())
}

/// `LOGIN`: `\A[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}\Z` - a GitHub login, by GitHub's own rule.
pub fn login_shape(text: &str) -> bool {
    let bytes = text.as_bytes();
    if !text.is_ascii() || bytes.is_empty() || bytes.len() > 39 {
        return false;
    }
    let alnum = |byte: u8| byte.is_ascii_alphanumeric();
    if !alnum(bytes[0]) {
        return false;
    }
    bytes.iter().enumerate().skip(1).all(|(at, byte)| {
        alnum(*byte) || (*byte == b'-' && bytes.get(at + 1).is_some_and(|next| alnum(*next)))
    })
}

/// `check_login(login)`: `login` as a report may be filed under, or the refusal's code.
pub fn check_login(login: &Value) -> Result<String, Fault> {
    let Some(text) = pyval::text(login).filter(|text| login_shape(text)) else {
        return Err(Fault::Refused(LOGIN_INVALID));
    };
    // `login.casefold()`: ASCII letters, digits and hyphens only here.
    let folded = text.to_ascii_lowercase();
    if reserved(&folded) {
        return Err(Fault::Refused(LOGIN_RESERVED));
    }
    if folded
        == REPOSITORY
            .split('/')
            .next()
            .unwrap_or_default()
            .to_ascii_lowercase()
    {
        return Err(Fault::Refused(LOGIN_OWNER));
    }
    Ok(text.to_owned())
}

/// `RECORDED_BY % version`.
pub fn recorded_by(version: &str) -> String {
    RECORDED_BY.replace("%s", version)
}

fn put(map: &mut Map, name: &str, value: Value) {
    map.insert(Str::from(name), value);
}

/// `assemble(body, login, product_version=..., windows=..., now=...)`: the whole report for `body` (`records.read`'s),
/// filed under `login`, checked (`check`). `product_version` and `windows` are `None` for "ask the process" (`facts`),
/// as the tag's `None` is.
pub fn assemble(
    body: &Value,
    login: &Value,
    product_version: Option<&str>,
    windows: Option<&str>,
    now: f64,
    facts: &dyn Facts,
) -> Checked<Value> {
    let login = check_login(login)?;
    let version = product_version.map_or_else(|| facts.product_version(), str::to_owned);
    let windows: Option<String> = match windows {
        Some(given) => Some(given.to_owned()),
        None => facts.windows_version(),
    };
    let recorded = evidence::iso(now).map_err(Fault::Error)?;
    let mut reporter = Map::new();
    put(&mut reporter, "github_login", Value::from(login.as_str()));
    put(&mut reporter, "tool", Value::from(TOOL));
    put(&mut reporter, "tool_version", Value::from(version.as_str()));
    put(
        &mut reporter,
        "product_version",
        Value::from(version.as_str()),
    );
    put(
        &mut reporter,
        "windows",
        windows.as_deref().map_or(Value::Null, Value::from),
    );
    let mut attribution = Map::new();
    put(&mut attribution, "rule", Value::from(RULE));
    put(&mut attribution, "window", Value::Null);
    put(&mut attribution, "basis", Value::Null);
    let mut document = Map::new();
    put(&mut document, "format", Value::from(FORMAT));
    put(
        &mut document,
        "codex_version",
        at(body, "codex_version").clone(),
    );
    put(&mut document, "verdict", at(body, "verdict").clone());
    put(&mut document, "recorded_at", Value::from(recorded));
    put(
        &mut document,
        "recorded_by",
        Value::from(recorded_by(&version)),
    );
    put(&mut document, "reporter", Value::Object(reporter));
    put(&mut document, "attribution", Value::Object(attribution));
    put(
        &mut document,
        "local_checks",
        at(body, "local_checks").clone(),
    );
    put(&mut document, "records", at(body, "records").clone());
    put(
        &mut document,
        "capabilities",
        at(body, "capabilities").clone(),
    );
    put(&mut document, "note", Value::from(NOTE));
    let document = Value::Object(document);
    check(&document)?;
    Ok(document)
}

/// `check(document)`: the document's bytes (ASCII text), once it is the format exactly and nothing in it can be
/// anything but a time, a version, a count or a closed word; the refusal when it is more than the project takes, the
/// error when it is anything else.
pub fn check(document: &Value) -> Checked<String> {
    keys(document, TOP_KEYS)?;
    if !pyval::is(at(document, "format"), FORMAT)
        || !pyval::text(at(document, "verdict")).is_some_and(|verdict| VERDICTS.contains(&verdict))
    {
        return error();
    }
    // `evidence.canonical_version(x) != x`: None for anything but a version, so a null passes it (the reference's own
    // answer, kept).
    let version = at(document, "codex_version");
    let same = match evidence::canonical_version(version) {
        Some(text) => pyval::is(version, &text),
        None => matches!(version, Value::Null),
    };
    if !same {
        return error();
    }
    moment(at(document, "recorded_at"), true)?;
    let reporter = at(document, "reporter");
    keys(reporter, REPORTER_KEYS)?;
    check_login(at(reporter, "github_login"))?;
    let product = at(reporter, "product_version");
    match pyval::text(product).filter(|text| product_version(text)) {
        Some(text)
            if pyval::is(at(reporter, "tool"), TOOL)
                && pyval::is(at(reporter, "tool_version"), text)
                && pyval::is(at(document, "recorded_by"), &recorded_by(text)) => {}
        _ => return error(),
    }
    if !pyval::text(at(reporter, "windows")).is_some_and(windows_shape) {
        return error();
    }
    let mut want = Map::new();
    put(&mut want, "rule", Value::from(RULE));
    put(&mut want, "window", Value::Null);
    put(&mut want, "basis", Value::Null);
    if !pyval::eq(at(document, "attribution"), &Value::Object(want))
        || !pyval::is(at(document, "note"), NOTE)
    {
        return error();
    }
    keys(at(document, "attribution"), ATTRIBUTION_KEYS)?;
    check_parts(document)?;
    let raw = encode(document)?;
    if raw.len() > MAX_BYTES {
        return Err(Fault::Refused(TOO_LARGE));
    }
    Ok(raw)
}
