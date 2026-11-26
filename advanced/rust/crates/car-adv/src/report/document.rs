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
//! SEAT S7.3c. The core half is car-control's `ownreport::document`, imported (Integration 8 folded the two copies):
//! `check_parts`, the shapes, `encode`, `Fault`; what only the Dashboard's own report uses (`assemble` of every
//! version, `written`) stays there, and what only the advanced one uses (the envelope) is here. The product's
//! version and the Windows build this process runs on are the [`Facts`] seam (`config.version()`,
//! `sys.getwindowsversion()`).

use car_machine::json::{Map, Str, Value};
use car_machine::pyval;

use super::evidence;
pub use car_control::ownreport::document::{Checked, Fault, encode};
use car_control::ownreport::document::{
    VERDICTS, at, check_parts, error, keys, moment, product_version, windows_shape,
};

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

/// What the report asks of the process it runs in: the product's version (`config.version()`) and the Windows build
/// (`document.windows_version()`: `sys.getwindowsversion()`, never `platform`).
pub trait Facts {
    fn product_version(&self) -> String;
    fn windows_version(&self) -> Option<String>;
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
