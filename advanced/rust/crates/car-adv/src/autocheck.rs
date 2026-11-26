//! `autocheck.py`: the automatic compatibility check - what a machine can tell of a new Codex with no measurement and no
//! sitting (seat S7.2c; it replaces S7.1b's `seam_autocheck`).
//!
//! When the Codex in force changes, the watcher asks it - once, on a thread of its own - for its version, its own list of
//! calls (`app-server generate-json-schema`) and its feature list (`features list`), every child on a scratch Codex home
//! removed after it, with `CREATE_NO_WINDOW`; and this module records what that showed (`config/advanced/autocheck.json`),
//! as a grade of its own: WHOLE, PART, FAILS_ONLY or NONE per measurement ([`CHECKS`]). An automatic grade is not a
//! measurement: neither `arming`'s verdict nor `registry.offered` reads it.
//!
//! * judging a schema (pure): [`judge_row`], [`judge`], [`feature_words`];
//! * the grade (pure): [`settled`], [`grade`];
//! * the record, one writer, read whole: [`read_record`], [`results_for`] (what every reader reads: `seam::Edges::
//!   checked_for`), [`diagnostics`];
//! * the one run: [`due`], [`ask_engine`], [`run_engine`], [`probe_engine`] (MAUTO's), [`run_once`], and [`tend`], from
//!   the watcher's tick alone, for the engine the watcher told the plug (`codex::inuse`).
//!
//! What raises in the reference and is not caught there (an int too large for a float in the record, a nesting past the
//! interpreter's reach) is an `Err` carrying the class name, as car-machine's `pyval::Py` does.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

use car_codex::system::System;
use car_codex::transport::Backend;
use car_machine::compat::model::{parse_version, safe_version};
use car_machine::compat::{LoadsError, loads};
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::is_space;
use car_machine::pyval::{self, Py};
use car_platform::spawn::{Spawn, Stream, SystemStarter};

use crate::measured::Table;
use crate::vocabulary::{AutoResult, CheckGrade, CheckReach, Measurement, Verdict, parse};

pub const FORMAT: &str = "codex-auto-resume-autocheck/1";
pub const FILE: &str = "autocheck.json";
pub const REVISION: i64 = 1;
pub const LOOK_EVERY: f64 = 60.0;
pub const AT_MOST_EVERY: f64 = 600.0;
pub const RETRY_AFTER: f64 = 6.0 * 3600.0;
pub const TRIES: i64 = 3;
pub const CHILD_SECONDS: f64 = 60.0;
pub const MAX_BYTES: u64 = 64 * 1024;
pub const SCHEMA_FILE: &str = "codex_app_server_protocol.schemas.json";
pub const SCHEMA_ARGUMENTS: [&str; 4] = [
    "app-server",
    "generate-json-schema",
    "--experimental",
    "--out",
];
pub const SCHEMA_BYTES: u64 = 16 * 1024 * 1024;
pub const FEATURE_ARGUMENTS: [&str; 2] = ["features", "list"];
pub const SANE_METHODS: [&str; 3] = ["initialize", "thread/resume", "turn/start"];
pub const SANE_COUNT: usize = 50;
pub const RECORD_KEYS: [&str; 9] = [
    "format",
    "revision",
    "key",
    "tries",
    "tried_at",
    "engine",
    "checked_at",
    "results",
    "gone",
];
/// codex/authfile.py's `NAME`: the sign-in file a Codex home keeps (MAUTO asks whether the scratch home holds one).
pub const AUTH_FILE: &str = "auth.json";

/// What one measurement's automatic check asks.
#[derive(Clone, Copy, Debug)]
pub struct Row {
    pub reach: CheckReach,
    /// Methods ClientRequest offers.
    pub methods: &'static [&'static str],
    /// (method, a field of that method's own params).
    pub params: &'static [(&'static str, &'static str)],
    /// Methods ServerRequest may ask of a client.
    pub requests: &'static [&'static str],
    /// (a named type, one of its fields).
    pub fields: &'static [(&'static str, &'static str)],
    /// (a named type, a word it may be).
    pub words: &'static [(&'static str, &'static str)],
    /// A name `features list` lists.
    pub feature: Option<&'static str>,
}

const NONE: Row = Row {
    reach: CheckReach::None,
    methods: &[],
    params: &[],
    requests: &[],
    fields: &[],
    words: &[],
    feature: None,
};

const fn fails_only(methods: &'static [&'static str]) -> Row {
    Row {
        reach: CheckReach::FailsOnly,
        methods,
        ..NONE
    }
}

const QUEUE_ADD: Row = Row {
    reach: CheckReach::FailsOnly,
    methods: &["thread/queue/add"],
    params: &[
        ("thread/queue/add", "threadId"),
        ("thread/queue/add", "input"),
        ("thread/queue/add", "clientUserMessageId"),
    ],
    ..NONE
};
const USAGE: &str = "account/rateLimits/read";
const CONSUME: &str = "account/rateLimitResetCredit/consume";
const OUTCOME: &str = "ConsumeAccountRateLimitResetCreditOutcome";
const TURN_CALLS: &[&str] = &[
    "thread/resume",
    "turn/start",
    "turn/interrupt",
    "thread/unsubscribe",
];
const STOP_WORD: &[(&str, &str)] = &[("HookEventName", "stop")];
/// `tuple(DECLINE_ANSWERS)`: codex/protocol.py's refused requests.
const REQUESTS: &[&str] = &crate::codex::protocol::DECLINED_REQUESTS;

/// `CHECKS`: every measurement, once, in the tag's order.
pub const CHECKS: &[(Measurement, Row)] = &[
    (Measurement::M1, NONE),
    (Measurement::M2b, NONE),
    (Measurement::M3, NONE),
    (Measurement::M5, NONE),
    (Measurement::Mh, NONE),
    (Measurement::Mw, NONE),
    (Measurement::Mp1, NONE),
    (Measurement::Mp2, NONE),
    (Measurement::Mp3, NONE),
    (Measurement::Mq, NONE),
    (Measurement::Me, NONE),
    (Measurement::Ms, NONE),
    (Measurement::Mk, NONE),
    (Measurement::Mt, NONE),
    (Measurement::Mipc, NONE),
    (Measurement::Mo, NONE),
    (Measurement::Mxa, NONE),
    (Measurement::Mb, NONE),
    (Measurement::Mc2, NONE),
    (Measurement::Mqo, NONE),
    (Measurement::Mqp, NONE),
    (Measurement::Mqg, NONE),
    (Measurement::Mtok, NONE),
    (Measurement::Mopen, NONE),
    (Measurement::Mal, NONE),
    (Measurement::Mwake, NONE),
    (Measurement::Mimg, NONE),
    (Measurement::Msteer, NONE),
    (Measurement::Msteer2, NONE),
    (Measurement::Mgave, NONE),
    (Measurement::Mauto, NONE),
    (Measurement::Maws, NONE),
    (Measurement::Mcloud, NONE),
    (
        Measurement::Mhk,
        Row {
            reach: CheckReach::Whole,
            words: STOP_WORD,
            feature: Some("plugin_hooks"),
            ..NONE
        },
    ),
    (
        Measurement::M6,
        Row {
            reach: CheckReach::Part,
            methods: TURN_CALLS,
            params: &[
                ("thread/resume", "threadId"),
                ("turn/start", "threadId"),
                ("turn/start", "input"),
                ("turn/start", "clientUserMessageId"),
                ("turn/interrupt", "threadId"),
                ("turn/interrupt", "turnId"),
                ("thread/unsubscribe", "threadId"),
                ("turn/start", "approvalPolicy"),
                ("turn/start", "sandboxPolicy"),
            ],
            requests: REQUESTS,
            words: &[
                ("CommandExecutionApprovalDecision", "decline"),
                ("FileChangeApprovalDecision", "decline"),
                ("ReviewDecision", "denied"),
                ("McpServerElicitationAction", "decline"),
                ("TurnStatus", "completed"),
                ("TurnStatus", "interrupted"),
                ("TurnStatus", "failed"),
            ],
            ..NONE
        },
    ),
    (
        Measurement::M6b,
        Row {
            reach: CheckReach::Part,
            methods: TURN_CALLS,
            params: &[
                ("thread/resume", "threadId"),
                ("turn/start", "threadId"),
                ("turn/start", "input"),
                ("turn/start", "clientUserMessageId"),
                ("turn/interrupt", "threadId"),
                ("turn/interrupt", "turnId"),
                ("thread/unsubscribe", "threadId"),
            ],
            requests: REQUESTS,
            fields: &[
                ("ThreadResumeResponse", "sandbox"),
                ("ThreadResumeResponse", "approvalPolicy"),
                ("ThreadResumeResponse", "approvalsReviewer"),
            ],
            words: &[
                ("CommandExecutionApprovalDecision", "decline"),
                ("FileChangeApprovalDecision", "decline"),
                ("ReviewDecision", "denied"),
                ("McpServerElicitationAction", "decline"),
                ("TurnStatus", "completed"),
                ("TurnStatus", "interrupted"),
                ("TurnStatus", "failed"),
                ("SandboxPolicy", "readOnly"),
                ("SandboxPolicy", "workspaceWrite"),
            ],
            feature: None,
        },
    ),
    (
        Measurement::Mu,
        Row {
            reach: CheckReach::Part,
            methods: &[USAGE],
            params: &[(USAGE, "excludeResetCreditDetails")],
            fields: &[
                ("GetAccountRateLimitsResponse", "rateLimits"),
                ("GetAccountRateLimitsResponse", "rateLimitResetCredits"),
                ("RateLimitResetCreditsSummary", "availableCount"),
                ("RateLimitSnapshot", "primary"),
                ("RateLimitSnapshot", "secondary"),
                ("RateLimitWindow", "usedPercent"),
                ("RateLimitWindow", "resetsAt"),
                ("RateLimitWindow", "windowDurationMins"),
            ],
            ..NONE
        },
    ),
    (
        Measurement::Mn,
        Row {
            reach: CheckReach::Part,
            methods: &[CONSUME],
            params: &[(CONSUME, "idempotencyKey")],
            words: &[(OUTCOME, "noCredit"), (OUTCOME, "nothingToReset")],
            ..NONE
        },
    ),
    (
        Measurement::Mr,
        Row {
            reach: CheckReach::Part,
            methods: &[CONSUME],
            params: &[(CONSUME, "idempotencyKey")],
            words: &[
                (OUTCOME, "reset"),
                (OUTCOME, "nothingToReset"),
                (OUTCOME, "noCredit"),
                (OUTCOME, "alreadyRedeemed"),
            ],
            ..NONE
        },
    ),
    (
        Measurement::Mx,
        Row {
            reach: CheckReach::Part,
            methods: &[
                "thread/resume",
                "thread/compact/start",
                "thread/unsubscribe",
            ],
            params: &[("thread/compact/start", "threadId")],
            words: &[("ThreadItem", "contextCompaction")],
            ..NONE
        },
    ),
    (
        Measurement::Mf,
        Row {
            reach: CheckReach::Part,
            methods: &[
                "thread/resume",
                "model/list",
                "turn/start",
                "turn/interrupt",
                "thread/settings/update",
                "thread/unsubscribe",
            ],
            params: &[
                ("thread/resume", "threadId"),
                ("turn/start", "model"),
                ("thread/settings/update", "threadId"),
                ("thread/settings/update", "model"),
            ],
            fields: &[
                ("ModelListResponse", "data"),
                ("Model", "isDefault"),
                ("Model", "model"),
                ("ThreadResumeResponse", "model"),
            ],
            ..NONE
        },
    ),
    (
        Measurement::M2,
        Row {
            reach: CheckReach::FailsOnly,
            methods: &["thread/goal/set"],
            params: &[
                ("thread/goal/set", "threadId"),
                ("thread/goal/set", "status"),
            ],
            ..NONE
        },
    ),
    (Measurement::M7, QUEUE_ADD),
    (Measurement::Mc1, QUEUE_ADD),
    (
        Measurement::M3b,
        Row {
            reach: CheckReach::FailsOnly,
            methods: &["turn/start"],
            params: &[("turn/start", "input")],
            ..NONE
        },
    ),
    (
        Measurement::M4,
        Row {
            reach: CheckReach::FailsOnly,
            words: STOP_WORD,
            feature: Some("plugin_hooks"),
            ..NONE
        },
    ),
    (
        Measurement::M4b,
        Row {
            reach: CheckReach::FailsOnly,
            words: STOP_WORD,
            feature: Some("plugin_hooks"),
            ..NONE
        },
    ),
    (Measurement::Ma, fails_only(&["account/read"])),
    (Measurement::Malr, fails_only(&["account/read"])),
    (Measurement::Manchor, fails_only(&[USAGE])),
    (
        Measurement::Mb2,
        fails_only(&["config/read", "account/read"]),
    ),
    (Measurement::Mprofile, fails_only(&["account/read", USAGE])),
    (Measurement::Mswap, fails_only(&["account/read", USAGE])),
];

/// `CHECKS.get(measurement, Row())`.
pub fn row(measurement: Measurement) -> Row {
    CHECKS
        .iter()
        .find(|(each, _)| *each == measurement)
        .map_or(NONE, |(_, row)| *row)
}

/// `CHECKS.get(measurement, Row()).reach`.
pub fn reach(measurement: Measurement) -> CheckReach {
    row(measurement).reach
}

// ------------------------------------------------------------------------------------------- judging a schema (pure)

/// `for item in value or ()`: the items Python iterates - a list's items, a str's characters, a dict's keys - or the
/// TypeError a truthy number raises.
fn items(value: Option<&Value>) -> Py<Vec<Value>> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    if !pyval::truthy(value) {
        return Ok(Vec::new());
    }
    match value {
        Value::Array(items) => Ok(items.clone()),
        Value::Str(text) => Ok(text
            .code_points()
            .map(|point| Value::Str(Str::from_code_points([point]).unwrap_or_default()))
            .collect()),
        Value::Object(map) => Ok(map.keys().map(|key| Value::Str(key.clone())).collect()),
        _ => Err("TypeError"),
    }
}

fn get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

fn is_dict(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Object(_)))
}

/// `_definition(document, name)`.
fn definition<'a>(document: &'a Value, name: &[u8]) -> Option<&'a Value> {
    let table = get(document, "definitions")?;
    let Value::Object(map) = table else {
        return None;
    };
    let lookup = |map: &'a Map| {
        map.iter()
            .find(|(key, _)| key.as_bytes() == name)
            .map(|(_, value)| value)
    };
    let mut found = lookup(map);
    if !is_dict(found) {
        found = match map.get("v2") {
            Some(Value::Object(nested)) => lookup(nested),
            _ => None,
        };
    }
    found.filter(|value| matches!(value, Value::Object(_)))
}

/// `_reference(document, schema)`: `schema` followed through a `$ref` to what it names.
fn reference<'a>(document: &'a Value, schema: Option<&'a Value>) -> Option<&'a Value> {
    let target = schema.and_then(|schema| get(schema, "$ref"));
    match target {
        Some(Value::Str(target)) => {
            let bytes = target.as_bytes();
            let tail = match bytes.iter().rposition(|b| *b == b'/') {
                Some(at) => &bytes[at + 1..],
                None => bytes,
            };
            definition(document, tail)
        }
        _ => schema.filter(|schema| matches!(schema, Value::Object(_))),
    }
}

/// `_properties(document, schema, depth)`: the field names `schema` has, through `$ref` and its alternatives; none where
/// it describes no object at all.
fn properties(document: &Value, schema: Option<&Value>, depth: usize) -> Py<Option<Vec<Vec<u8>>>> {
    let Some(schema) = reference(document, schema) else {
        return Ok(None);
    };
    if depth > 6 {
        return Ok(None);
    }
    let mut found: Option<Vec<Vec<u8>>> = match get(schema, "properties") {
        Some(Value::Object(map)) => Some(map.keys().map(|key| key.as_bytes().to_vec()).collect()),
        _ => None,
    };
    for keyword in ["anyOf", "oneOf", "allOf"] {
        for item in items(get(schema, keyword))? {
            if let Some(inner) = properties(document, Some(&item), depth + 1)? {
                let held = found.get_or_insert_with(Vec::new);
                for name in inner {
                    if !held.contains(&name) {
                        held.push(name);
                    }
                }
            }
        }
    }
    Ok(found)
}

/// `_variants(schema, depth)`: the words `schema`'s value may be.
fn variants(schema: Option<&Value>, depth: usize, words: &mut Vec<Vec<u8>>) -> Py<()> {
    let Some(schema @ Value::Object(_)) = schema else {
        return Ok(());
    };
    if depth > 6 {
        return Ok(());
    }
    let add = |word: &Value, words: &mut Vec<Vec<u8>>| {
        if let Value::Str(word) = word
            && !words.iter().any(|seen| seen == word.as_bytes())
        {
            words.push(word.as_bytes().to_vec());
        }
    };
    for word in items(get(schema, "enum"))? {
        add(&word, words);
    }
    if let Some(constant @ Value::Str(_)) = get(schema, "const") {
        add(constant, words);
    }
    for keyword in ["oneOf", "anyOf"] {
        for item in items(get(schema, keyword))? {
            variants(Some(&item), depth + 1, words)?;
            if let Some(properties @ Value::Object(_)) = get(&item, "properties") {
                variants(get(properties, "type"), depth + 1, words)?;
                if let Some(Value::Array(required)) = get(&item, "required")
                    && let [one @ Value::Str(_)] = required.as_slice()
                {
                    add(one, words);
                }
            }
        }
    }
    Ok(())
}

/// `_offered(document, name)`: `{method: its params' schema, or None}` of the union `name`, in the order first named.
fn offered(document: &Value, name: &str) -> Py<Vec<(Vec<u8>, Value)>> {
    let union = definition(document, name.as_bytes());
    let mut found: Vec<(Vec<u8>, Value)> = Vec::new();
    for item in items(union.and_then(|union| get(union, "oneOf")))? {
        let Some(properties @ Value::Object(_)) = get(&item, "properties") else {
            continue;
        };
        let Some(Value::Object(method)) = get(properties, "method") else {
            continue;
        };
        if let Some(Value::Array(words)) = method.get("enum") {
            for word in words {
                if let Value::Str(word) = word {
                    let params = get(properties, "params").cloned().unwrap_or(Value::Null);
                    match found.iter_mut().find(|(seen, _)| seen == word.as_bytes()) {
                        Some(slot) => slot.1 = params,
                        None => found.push((word.as_bytes().to_vec(), params)),
                    }
                }
            }
        }
    }
    Ok(found)
}

/// `str.splitlines()`: Python's line boundaries.
fn split_lines(text: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = text.char_indices().peekable();
    while let Some((at, c)) = chars.next() {
        let boundary = matches!(
            c,
            '\n' | '\r'
                | '\u{0b}'
                | '\u{0c}'
                | '\u{1c}'
                | '\u{1d}'
                | '\u{1e}'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        );
        if boundary {
            lines.push(&text[start..at]);
            let mut end = at + c.len_utf8();
            if c == '\r'
                && let Some((_, '\n')) = chars.peek()
            {
                chars.next();
                end += 1;
            }
            start = end;
        }
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}

/// `feature_words(text, name)`: the words after `name` on the line of `codex features list` that begins with it, or none.
pub fn feature_words(text: &str, name: &str) -> Option<Vec<String>> {
    for line in split_lines(text) {
        let replaced = line.replace('|', " ");
        let words: Vec<&str> = replaced
            .split(is_space)
            .filter(|word| !word.is_empty())
            .collect();
        if words.first() == Some(&name) {
            return Some(words[1..].iter().map(|word| (*word).to_owned()).collect());
        }
    }
    None
}

/// `judge_row(row, document, client, server, features)`: (AutoResult, the names of this row that are gone).
fn judge_row(
    row: &Row,
    document: &Value,
    client: &[(Vec<u8>, Value)],
    server: &[(Vec<u8>, Value)],
    features: Option<&str>,
) -> Py<(AutoResult, Vec<String>)> {
    let lookup = |table: &'_ [(Vec<u8>, Value)], name: &str| {
        table
            .iter()
            .find(|(seen, _)| seen == name.as_bytes())
            .map(|(_, params)| params.clone())
    };
    let mut gone: Vec<String> = Vec::new();
    let mut unknown = false;
    gone.extend(
        row.methods
            .iter()
            .filter(|method| lookup(client, method).is_none())
            .map(|method| (*method).to_owned()),
    );
    for (method, field) in row.params {
        let Some(params) = lookup(client, method) else {
            continue;
        };
        match properties(document, Some(&params), 0)? {
            None => unknown = true,
            Some(fields) if !fields.iter().any(|name| name == field.as_bytes()) => {
                gone.push(format!("{method}.{field}"));
            }
            Some(_) => {}
        }
    }
    gone.extend(
        row.requests
            .iter()
            .filter(|method| lookup(server, method).is_none())
            .map(|method| (*method).to_owned()),
    );
    for (name, field) in row.fields {
        match properties(document, definition(document, name.as_bytes()), 0)? {
            None => unknown = true,
            Some(fields) if !fields.iter().any(|each| each == field.as_bytes()) => {
                gone.push(format!("{name}.{field}"));
            }
            Some(_) => {}
        }
    }
    for (name, word) in row.words {
        match definition(document, name.as_bytes()) {
            None => unknown = true,
            Some(schema) => {
                let mut words = Vec::new();
                variants(Some(schema), 0, &mut words)?;
                if !words.iter().any(|each| each == word.as_bytes()) {
                    gone.push(format!("{name}.{word}"));
                }
            }
        }
    }
    if let Some(feature) = row.feature {
        match features {
            None => unknown = true,
            Some(text) if feature_words(text, feature).is_none() => gone.push(feature.to_owned()),
            Some(_) => {}
        }
    }
    Ok(if !gone.is_empty() {
        (AutoResult::Fail, gone)
    } else if unknown {
        (AutoResult::Unknown, Vec::new())
    } else {
        (AutoResult::Pass, Vec::new())
    })
}

/// `judge(document, features)`'s answer: `{Measurement: (AutoResult, gone)}` in CHECKS' order.
pub type Answer = Vec<(Measurement, (AutoResult, Vec<String>))>;

/// `judge(document, features)`: every row that asks something, or nothing for a document that is not Codex's whole
/// schema. Pure.
pub fn judge(document: &Value, features: Option<&str>) -> Py<Answer> {
    let client = offered(document, "ClientRequest")?;
    let named = |method: &str| client.iter().any(|(seen, _)| seen == method.as_bytes());
    if client.len() < SANE_COUNT || !SANE_METHODS.iter().all(|method| named(method)) {
        return Ok(Vec::new());
    }
    let server = offered(document, "ServerRequest")?;
    let mut answer = Vec::new();
    for (measurement, row) in CHECKS {
        if row.reach != CheckReach::None {
            answer.push((
                *measurement,
                judge_row(row, document, &client, &server, features)?,
            ));
        }
    }
    Ok(answer)
}

// ------------------------------------------------------------------------------------------------- the grade (pure)

/// `HERE, FAILED, GONE, STANDS_IN, UNSETTLED`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Settled {
    Here,
    Failed,
    Gone,
    StandsIn,
    Unsettled,
}

impl Settled {
    pub fn word(self) -> &'static str {
        match self {
            Settled::Here => "here",
            Settled::Failed => "failed",
            Settled::Gone => "gone",
            Settled::StandsIn => "stands_in",
            Settled::Unsettled => "unsettled",
        }
    }
}

/// What `results_for` gives: `{Measurement: AutoResult}`.
pub type Results = BTreeMap<Measurement, AutoResult>;

/// `settled(measurement, version, table, results)`: how one measurement stands for the Codex `version`.
pub fn settled(
    measurement: Measurement,
    version: Option<&str>,
    table: &Table,
    results: &Results,
) -> Settled {
    let (verdict, measured_on) = match table.get(&measurement) {
        Some((verdict, engine)) => (Some(*verdict), Some(engine.as_str())),
        None => (None, None),
    };
    if verdict == Some(Verdict::Fail) {
        return Settled::Failed;
    }
    if verdict == Some(Verdict::Pass) && version.is_some() && measured_on == version {
        return Settled::Here;
    }
    match results.get(&measurement) {
        Some(AutoResult::Fail) => return Settled::Gone,
        Some(AutoResult::Pass) => {
            let reach = reach(measurement);
            if reach == CheckReach::Whole
                || (reach == CheckReach::Part && verdict == Some(Verdict::Pass))
            {
                return Settled::StandsIn;
            }
        }
        _ => {}
    }
    Settled::Unsettled
}

/// `_order(version)`: `(tuple(parse_version(version) or ()), version)`.
fn order(version: &str) -> (Vec<i64>, String) {
    let key = parse_version(&Value::from(version))
        .map(|parts| parts.to_vec())
        .unwrap_or_default();
    (key, version.to_owned())
}

/// `grade(measurements, version, table, results)`: (CheckGrade, the oldest earlier Codex a person measured it on).
pub fn grade(
    measurements: &[Measurement],
    version: Option<&str>,
    table: &Table,
    results: &Results,
) -> (CheckGrade, Option<String>) {
    if measurements.is_empty() {
        return (CheckGrade::None, None);
    }
    // `{measurement: word}` keeps the first place of a measurement named twice.
    let mut each: Vec<(Measurement, Settled)> = Vec::new();
    for measurement in measurements {
        let word = settled(*measurement, version, table, results);
        match each.iter_mut().find(|(seen, _)| seen == measurement) {
            Some(held) => held.1 = word,
            None => each.push((*measurement, word)),
        }
    }
    let has = |wanted: Settled| each.iter().any(|(_, word)| *word == wanted);
    if has(Settled::Failed) {
        if measurements
            .iter()
            .any(|m| results.get(m) == Some(&AutoResult::Fail))
        {
            return (CheckGrade::Failed, None);
        }
        let offered = each
            .iter()
            .any(|(m, word)| *word == Settled::Failed && results.get(m) == Some(&AutoResult::Pass));
        let grade = if offered {
            CheckGrade::FailedStillOffered
        } else {
            CheckGrade::Failed
        };
        return (grade, None);
    }
    if has(Settled::Gone) {
        return (CheckGrade::CheckFailed, None);
    }
    if has(Settled::Unsettled) {
        let offered = each.iter().all(|(m, word)| {
            *word != Settled::Unsettled || results.get(m) == Some(&AutoResult::Pass)
        });
        let grade = if offered {
            CheckGrade::OfferedOnly
        } else {
            CheckGrade::Unmeasured
        };
        return (grade, None);
    }
    if !has(Settled::StandsIn) {
        return (CheckGrade::Measured, None);
    }
    let earlier: Vec<&str> = each
        .iter()
        .filter(|(_, word)| *word == Settled::StandsIn)
        .filter_map(|(m, _)| table.get(m).map(|(_, engine)| engine.as_str()))
        .collect();
    let oldest = earlier
        .into_iter()
        .min_by_key(|version| order(version))
        .map(str::to_owned);
    (CheckGrade::AutoChecked, oldest)
}

// ---------------------------------------------------------------------------------- the record: one writer, read whole

/// `_path(paths)`: the record in the advanced state folder.
pub fn record_path(advanced_dir: &Path) -> PathBuf {
    advanced_dir.join(FILE)
}

/// `_number(value)`: an int or a float, not a bool, finite (an int past a float's reach raises OverflowError).
fn number(value: &Value) -> Py<bool> {
    if !pyval::is_number(value) {
        return Ok(false);
    }
    pyval::is_finite(value)
}

fn is_word<W: crate::vocabulary::ClosedWord>(value: &Value) -> bool {
    matches!(value, Value::Str(word) if word.as_str().and_then(parse::<W>).is_some())
}

/// `_shaped(value)`: the record, or none for one wrong in any part.
fn shaped(value: Value) -> Py<Option<Value>> {
    let Value::Object(record) = &value else {
        return Ok(None);
    };
    if record.len() != RECORD_KEYS.len() || !RECORD_KEYS.iter().all(|key| record.contains_key(*key))
    {
        return Ok(None);
    }
    if !matches!(&record["format"], Value::Str(format) if format.as_bytes() == FORMAT.as_bytes()) {
        return Ok(None);
    }
    if !pyval::is_int(&record["revision"])
        || !pyval::is_int(&record["tries"])
        || !number(&record["tried_at"])?
    {
        return Ok(None);
    }
    if !matches!(record["engine"], Value::Null)
        && (safe_version(&record["engine"]).is_none() || !number(&record["checked_at"])?)
    {
        return Ok(None);
    }
    let (Value::Object(results), Value::Object(gone)) = (&record["results"], &record["gone"])
    else {
        return Ok(None);
    };
    let known = |name: &Str| {
        name.as_str()
            .and_then(parse::<Measurement>)
            .is_some_and(|m| CHECKS.iter().any(|(each, _)| *each == m))
    };
    if !results
        .iter()
        .all(|(name, word)| known(name) && is_word::<AutoResult>(word))
    {
        return Ok(None);
    }
    let listed = |names: &Value| matches!(names, Value::Array(items) if items.iter().all(|each| matches!(each, Value::Str(_))));
    if !gone
        .iter()
        .all(|(name, names)| known(name) && listed(names))
    {
        return Ok(None);
    }
    Ok(Some(value))
}

/// `read_record(paths)`: the record as the watcher last wrote it, or none. Starts nothing.
pub fn read_record(advanced_dir: &Path) -> Py<Option<Value>> {
    let path = record_path(advanced_dir);
    let Ok(found) = std::fs::metadata(&path) else {
        return Ok(None);
    };
    if found.len() > MAX_BYTES {
        return Ok(None);
    }
    let Ok(raw) = car_machine::pyfile::read(&path) else {
        return Ok(None);
    };
    let Ok(text) = std::str::from_utf8(&raw) else {
        return Ok(None);
    };
    match loads(text) {
        Ok(value) => shaped(value),
        Err(LoadsError::Recursion) => Err("RecursionError"),
        Err(_) => Ok(None),
    }
}

/// `results_for(paths, engine)`: what the check found of exactly the Codex `engine` and this REVISION, or nothing.
pub fn results_for(advanced_dir: &Path, engine: Option<&str>) -> Py<Results> {
    let Some(engine) = engine else {
        return Ok(Results::new());
    };
    let Some(Value::Object(record)) = read_record(advanced_dir)? else {
        return Ok(Results::new());
    };
    let same_engine =
        matches!(&record["engine"], Value::Str(found) if found.as_bytes() == engine.as_bytes());
    if !same_engine || record["revision"] != Value::from(REVISION) {
        return Ok(Results::new());
    }
    let mut found = Results::new();
    if let Value::Object(results) = &record["results"] {
        for (name, word) in results {
            let measurement = name.as_str().and_then(parse::<Measurement>);
            let word = match word {
                Value::Str(word) => word.as_str().and_then(parse::<AutoResult>),
                _ => None,
            };
            if let (Some(measurement), Some(word)) = (measurement, word) {
                found.insert(measurement, word);
            }
        }
    }
    Ok(found)
}

/// `diagnostics(paths)`: what Diagnostics' export says of the last check, or none where no check ever wrote.
pub fn diagnostics(advanced_dir: &Path) -> Py<Option<Value>> {
    let Some(Value::Object(record)) = read_record(advanced_dir)? else {
        return Ok(None);
    };
    let mut out = Map::new();
    for key in ["engine", "checked_at", "tries", "results", "gone"] {
        out.insert(key.into(), record[key].clone());
    }
    Ok(Some(Value::Object(out)))
}

/// Why a write did not happen: the OSError `_write` raises, or the ConfigError of the home's own folders.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WriteError {
    Os,
    Config(String),
}

/// `_write(paths, record)`: the record, whole, in config/advanced/, made and marked as ours first.
pub fn write(paths: &car_config::Paths, record: &Value) -> Result<(), WriteError> {
    // `_write`'s `except OSError`: a mkdir of ensure() that fails (config a file) is the write's OSError.
    paths.ensure().map_err(|raised| match raised {
        car_config::paths::EnsureError::Config(refused) => WriteError::Config(refused.0),
        car_config::paths::EnsureError::Os { .. } => WriteError::Os,
    })?;
    let folder = PathBuf::from(&paths.advanced_dir);
    let text = folder.to_string_lossy().into_owned();
    if car_config::paths::is_link(&text) || (folder.exists() && !paths.confined(&text)) {
        return Err(WriteError::Os);
    }
    match std::fs::create_dir(&folder) {
        Ok(()) => {}
        Err(_) if folder.is_dir() => {}
        Err(_) => return Err(WriteError::Os),
    }
    let marker = folder.join(car_config::paths::OWNER_MARKER);
    if !marker.exists() {
        std::fs::write(&marker, crate::state::session::owner_text().as_bytes())
            .map_err(|_| WriteError::Os)?;
    }
    car_codex::compat::files::write_json_atomic(
        &record_path(&folder).to_string_lossy(),
        record,
        "autocheck",
    )
    .map_err(|_| WriteError::Os)
}

// --------------------------------------------------------------------------------------------------------- the one run

/// `_engine_key(exe)`: `[the path's digest, size, mtime_ns]`, or none.
pub fn engine_key(system: &dyn System, exe: &str) -> Py<Option<Value>> {
    let signature = car_codex::compat::files::signature(exe)?;
    let digest = car_codex::compat::files::path_digest(system, exe);
    Ok(match (signature, digest) {
        (Value::Array(parts), Some(digest)) if !parts.is_empty() => {
            let mut key = vec![Value::from(digest)];
            key.extend(parts);
            Some(Value::Array(key))
        }
        _ => None,
    })
}

/// `due(record, key, now)`: whether a run is due for the engine file `key` at `now`. Pure.
pub fn due(record: Option<&Value>, key: Option<&Value>, now: f64) -> Py<bool> {
    let Some(key) = key else {
        return Ok(false);
    };
    let Some(record) = record else {
        return Ok(true);
    };
    let field = |name: &str| get(record, name).cloned().unwrap_or(Value::Null);
    let mut since = pyval::minus(&Value::Float(now), &field("tried_at"))?;
    if since < 0.0 {
        since = f64::INFINITY;
    }
    if pyval::eq(&field("key"), key) && field("revision") == Value::from(REVISION) {
        let fewer = pyval::less(&field("tries"), &Value::from(TRIES))?;
        return Ok(matches!(field("engine"), Value::Null) && fewer && since >= RETRY_AFTER);
    }
    Ok(since >= AT_MOST_EVERY)
}

/// `_schema_of(folder)`: the schema file the engine wrote, as a dict, or none. A nesting past the interpreter's reach
/// raises (RecursionError), as the reference's `json.loads` does.
fn schema_of(folder: &Path) -> Py<Option<Value>> {
    let path = folder.join(SCHEMA_FILE);
    let Ok(found) = std::fs::symlink_metadata(&path) else {
        return Ok(None);
    };
    if !found.file_type().is_file() || found.len() > SCHEMA_BYTES {
        return Ok(None);
    }
    let Ok(raw) = car_machine::pyfile::read(&path) else {
        return Ok(None);
    };
    let Ok(text) = std::str::from_utf8(&raw) else {
        return Ok(None);
    };
    match loads(text) {
        Ok(value @ Value::Object(_)) => Ok(Some(value)),
        Ok(_) => Ok(None),
        Err(LoadsError::Recursion) => Err("RecursionError"),
        Err(_) => Ok(None),
    }
}

/// Bytes as a text-mode pipe decodes them: UTF-8 with replacement, universal newlines.
fn decode_text(bytes: &[u8]) -> String {
    let mut text = String::new();
    let mut whole = car_codex::appserver::TextReader::new(bytes);
    while let Ok(line) = whole.readline(1 << 20) {
        if line.is_empty() {
            break;
        }
        text.extend(line);
    }
    text
}

/// `subprocess.run(argv, stdin=DEVNULL, stdout=PIPE or DEVNULL, stderr=DEVNULL, cwd=..., env=..., timeout=60,
/// creationflags=NO_WINDOW)`: the exit code and what it printed, or none where it could not start or ran out of time.
fn run_child(
    argv: Vec<String>,
    cwd: &Path,
    env: Vec<(std::ffi::OsString, std::ffi::OsString)>,
    keep: bool,
) -> Option<(i64, Vec<u8>)> {
    let spawn = Spawn::new(argv).with_env(env).with_cwd(cwd).with_streams(
        Stream::Null,
        if keep { Stream::Piped } else { Stream::Null },
        Stream::Null,
    );
    let mut child = SystemStarter.start(&spawn).ok()?;
    let reading = child.stdout.take().map(|mut stdout| {
        std::thread::spawn(move || {
            let mut bytes = Vec::new();
            let _ = std::io::Read::read_to_end(&mut stdout, &mut bytes);
            bytes
        })
    });
    let until = Instant::now() + Duration::from_secs_f64(CHILD_SECONDS);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {}
            Err(_) => return None,
        }
        if Instant::now() >= until {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
        std::thread::sleep(Duration::from_millis(5));
    };
    let bytes = reading
        .and_then(|thread| thread.join().ok())
        .unwrap_or_default();
    Some((
        status.code().map_or(-1, |code| i64::from(code as u32)),
        bytes,
    ))
}

/// `_child(backend, arguments, scratch)`: what the engine printed to one set of arguments, or none.
fn child(backend: &Backend, arguments: &[String], scratch: &Path) -> Option<String> {
    let mut argv = backend.argv();
    argv.extend(arguments.iter().cloned());
    let (code, bytes) = run_child(argv, scratch, backend.environment(), true)?;
    (code == 0).then(|| decode_text(&bytes))
}

/// What the check asks of the outside world: Windows' answers (car-codex's `System`) and the product's own version.
#[derive(Clone)]
pub struct World {
    pub system: Arc<dyn System>,
    /// `config.version()`: what the backend tells the engine it is.
    pub product_version: String,
}

/// `ask_engine(exe, scratch)`'s answer.
pub struct Asked {
    pub backend: Backend,
    pub home: PathBuf,
    pub out: PathBuf,
    pub version: Option<String>,
    pub schema_answered: bool,
    pub schema_written: bool,
    pub features_answered: bool,
    pub answer: Answer,
}

/// Why `ask_engine` raised: the engine check's refusal (core's AdapterError code), a folder that could not be made, or
/// a class the reference does not catch there.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AskError {
    Adapter(String),
    Os,
    Raised(&'static str),
}

/// `ask_engine(exe, scratch)`: what the codex.exe `exe` answered, every child on a Codex home inside `scratch`.
pub fn ask_engine(world: &World, exe: &str, scratch: &Path) -> Result<Asked, AskError> {
    let home = scratch.join("codex-home");
    let out = scratch.join("schema");
    std::fs::create_dir(&home).map_err(|_| AskError::Os)?;
    std::fs::create_dir(&out).map_err(|_| AskError::Os)?;
    let mut backend = Backend::new(
        Arc::clone(&world.system),
        &home.to_string_lossy(),
        exe,
        false,
        &world.product_version,
    );
    backend.compatible().map_err(|error| match error {
        car_codex::errors::Error::Adapter(code) => AskError::Adapter(code.to_owned()),
        other => AskError::Adapter(format!("{other:?}")),
    })?;
    let version = backend
        .engine_version
        .as_ref()
        .and_then(|version| safe_version(&Value::from(version.as_str())).map(str::to_owned));
    let mut asked = Asked {
        backend,
        home,
        out,
        version,
        schema_answered: false,
        schema_written: false,
        features_answered: false,
        answer: Vec::new(),
    };
    if asked.version.is_none() {
        return Ok(asked);
    }
    let mut arguments: Vec<String> = SCHEMA_ARGUMENTS
        .iter()
        .map(|each| (*each).to_owned())
        .collect();
    arguments.push(asked.out.to_string_lossy().into_owned());
    asked.schema_answered = child(&asked.backend, &arguments, scratch).is_some();
    let document = if asked.schema_answered {
        schema_of(&asked.out).map_err(AskError::Raised)?
    } else {
        None
    };
    let Some(document) = document else {
        return Ok(asked);
    };
    asked.schema_written = true;
    let features_arguments: Vec<String> = FEATURE_ARGUMENTS
        .iter()
        .map(|each| (*each).to_owned())
        .collect();
    let features = child(&asked.backend, &features_arguments, scratch);
    asked.features_answered = features.is_some();
    asked.answer = judge(&document, features.as_deref()).map_err(AskError::Raised)?;
    Ok(asked)
}

/// `run_engine(exe, scratch)`: (the version the engine names, judge's answer), or none for no answer.
pub fn run_engine(
    world: &World,
    exe: &str,
    scratch: &Path,
) -> Result<Option<(String, Answer)>, AskError> {
    let asked = ask_engine(world, exe, scratch)?;
    Ok(match asked.version {
        Some(version) if !version.is_empty() && !asked.answer.is_empty() => {
            Some((version, asked.answer))
        }
        _ => None,
    })
}

/// `tempfile.mkdtemp(prefix=prefix)`: a new folder in the temporary folder Python's `gettempdir` names (TMPDIR, TEMP,
/// TMP, in that order).
pub fn mkdtemp(prefix: &str) -> std::io::Result<PathBuf> {
    let root = ["TMPDIR", "TEMP", "TMP"]
        .iter()
        .filter_map(std::env::var_os)
        .find(|value| !value.is_empty() && Path::new(value).is_dir())
        .map_or_else(std::env::temp_dir, PathBuf::from);
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    loop {
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |since| since.subsec_nanos());
        let count = NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let name = format!("{prefix}{:x}{:x}{count:x}", std::process::id(), stamp);
        let path = root.join(name);
        match std::fs::create_dir(&path) {
            Ok(()) => return Ok(path),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
}

/// `_bare_schema(backend, arguments, scratch)`: whether one form of the schema's command runs at all.
fn bare_schema(backend: &Backend, arguments: Vec<String>, scratch: &Path) -> bool {
    let out = scratch.join("schema-again");
    let _ = std::fs::remove_dir_all(&out);
    if std::fs::create_dir(&out).is_err() {
        return false;
    }
    let mut argv = arguments;
    argv.push(out.to_string_lossy().into_owned());
    run_child(argv, scratch, backend.environment(), false).is_some_and(|(code, _)| code == 0)
}

/// Every file under `folder`, as `Path.rglob("*")` and `is_file()` find them.
fn files_under(folder: &Path) -> usize {
    let mut count = 0;
    let mut stack = vec![folder.to_path_buf()];
    while let Some(next) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&next) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if !entry.file_type().is_ok_and(|kind| kind.is_symlink()) {
                    stack.push(path);
                }
            } else if path.is_file() {
                count += 1;
            }
        }
    }
    count
}

/// `probe_engine(exe)`: the check's own commands on the real engine, for MAUTO, on a scratch home removed after.
pub fn probe_engine(world: &World, exe: &str) -> Value {
    let official = car_codex::pairing::official_engine(world.system.as_ref(), exe).0;
    let mut found: Vec<(&str, Value)> = vec![
        ("official", Value::Bool(official)),
        ("engine_accepted", Value::Bool(false)),
        ("version", Value::Null),
        ("schema_answered", Value::Bool(false)),
        ("experimental_taken", Value::Bool(false)),
        ("schema_written", Value::Bool(false)),
        ("schema_whole", Value::Bool(false)),
        ("features_answered", Value::Bool(false)),
        ("options_without_flag", Value::Null),
        ("flag_without_options", Value::Null),
        ("scratch_home_files", Value::Null),
        ("scratch_home_signed_in", Value::Null),
        ("results", Value::Object(Map::new())),
    ];
    let set = |found: &mut Vec<(&str, Value)>, key: &str, value: Value| {
        if let Some(slot) = found.iter_mut().find(|(each, _)| *each == key) {
            slot.1 = value;
        }
    };
    if let Ok(scratch) = mkdtemp("car-mauto-") {
        if let Ok(asked) = ask_engine(world, exe, &scratch) {
            set(&mut found, "engine_accepted", Value::Bool(true));
            set(
                &mut found,
                "version",
                asked.version.clone().map_or(Value::Null, Value::from),
            );
            set(
                &mut found,
                "schema_answered",
                Value::Bool(asked.schema_answered),
            );
            set(
                &mut found,
                "experimental_taken",
                Value::Bool(asked.schema_answered),
            );
            set(
                &mut found,
                "schema_written",
                Value::Bool(asked.schema_written),
            );
            set(
                &mut found,
                "schema_whole",
                Value::Bool(!asked.answer.is_empty()),
            );
            set(
                &mut found,
                "features_answered",
                Value::Bool(asked.features_answered),
            );
            let results: Map = asked
                .answer
                .iter()
                .map(|(measurement, (word, _))| {
                    (measurement.as_str().into(), Value::from(word.as_str()))
                })
                .collect();
            set(&mut found, "results", Value::Object(results));
            if !asked.schema_answered {
                let options = asked.backend.argv();
                let mut without_flag = options.clone();
                without_flag.extend(
                    SCHEMA_ARGUMENTS
                        .iter()
                        .filter(|word| **word != "--experimental")
                        .map(|word| (*word).to_owned()),
                );
                set(
                    &mut found,
                    "options_without_flag",
                    Value::Bool(bare_schema(&asked.backend, without_flag, &scratch)),
                );
                let mut flag_only: Vec<String> = options.iter().take(1).cloned().collect();
                flag_only.extend(SCHEMA_ARGUMENTS.iter().map(|word| (*word).to_owned()));
                set(
                    &mut found,
                    "flag_without_options",
                    Value::Bool(bare_schema(&asked.backend, flag_only, &scratch)),
                );
            }
            set(
                &mut found,
                "scratch_home_files",
                Value::from(files_under(&asked.home) as i64),
            );
            set(
                &mut found,
                "scratch_home_signed_in",
                Value::Bool(asked.home.join(AUTH_FILE).exists()),
            );
        }
        let _ = std::fs::remove_dir_all(&scratch);
    }
    Value::Object(
        found
            .into_iter()
            .map(|(key, value)| (key.into(), value))
            .collect(),
    )
}

/// `_attempt(paths, key, tries, now)`.
pub fn attempt(key: &Value, tries: i64, now: f64) -> Value {
    let pairs: [(&str, Value); 9] = [
        ("format", Value::from(FORMAT)),
        ("revision", Value::from(REVISION)),
        ("key", key.clone()),
        ("tries", Value::from(tries)),
        ("tried_at", Value::Float(now)),
        ("engine", Value::Null),
        ("checked_at", Value::Null),
        ("results", Value::Object(Map::new())),
        ("gone", Value::Object(Map::new())),
    ];
    Value::Object(
        pairs
            .into_iter()
            .map(|(key, value)| (key.into(), value))
            .collect(),
    )
}

/// A clock the run reads (`time.time`).
pub type Clock = Arc<dyn Fn() -> f64 + Send + Sync>;

/// `run_once(paths, exe, record, clock=clock)`: one run for `exe`, whose attempt `record` is already written: the answer
/// written over it, and the scratch folder gone. Nothing raises out of it but the ConfigError of the home's own folders.
pub fn run_once(
    world: &World,
    paths: &car_config::Paths,
    exe: &str,
    record: &Value,
    clock: &Clock,
) -> Result<(), String> {
    let mut found = None;
    if let Ok(scratch) = mkdtemp("car-autocheck-") {
        found = run_engine(world, exe, &scratch).ok().flatten();
        let _ = std::fs::remove_dir_all(&scratch);
    }
    let Some((version, answer)) = found else {
        return Ok(());
    };
    let Value::Object(mut done) = record.clone() else {
        return Ok(());
    };
    done.insert("engine".into(), Value::from(version));
    done.insert("checked_at".into(), Value::Float(clock()));
    let results: Map = answer
        .iter()
        .map(|(measurement, (word, _))| (measurement.as_str().into(), Value::from(word.as_str())))
        .collect();
    let gone: Map = answer
        .iter()
        .filter(|(_, (_, names))| !names.is_empty())
        .map(|(measurement, (_, names))| {
            (
                measurement.as_str().into(),
                Value::Array(
                    names
                        .iter()
                        .map(|name| Value::from(name.as_str()))
                        .collect(),
                ),
            )
        })
        .collect();
    done.insert("results".into(), Value::Object(results));
    done.insert("gone".into(), Value::Object(gone));
    match write(paths, &Value::Object(done)) {
        Ok(()) | Err(WriteError::Os) => Ok(()),
        Err(WriteError::Config(why)) => Err(why),
    }
}

/// `{an installation's home: its run's thread}`, and when its tick last looked.
struct Tended {
    running: HashMap<String, std::thread::JoinHandle<()>>,
    looked: HashMap<String, f64>,
}

static TENDED: Mutex<Option<Tended>> = Mutex::new(None);

/// `Path(paths.home)` as a dict key: pathlib's Windows flavour compares a path lower-cased.
fn home_key(home: &str) -> String {
    car_config::winpath::path_str(home).to_lowercase()
}

/// Why `tend` raised: the record's own read (an int past a float's reach, a nesting too deep) or its write.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TendError {
    Raised(&'static str),
    Write(WriteError),
}

/// `tend(paths, clock=clock)`: once a tick, from the watcher alone, start a run where one is due for the engine the
/// watcher told the plug. Whether one started; the run has a thread of its own.
pub fn tend(world: &World, paths: &car_config::Paths, clock: Clock) -> Result<bool, TendError> {
    let Some((exe, _home)) = crate::codex::inuse::told(Some(&paths.home)) else {
        return Ok(false);
    };
    let home = home_key(&paths.home);
    let now = clock();
    let mut held = TENDED.lock().unwrap_or_else(PoisonError::into_inner);
    let tended = held.get_or_insert_with(|| Tended {
        running: HashMap::new(),
        looked: HashMap::new(),
    });
    let since = now
        - tended
            .looked
            .get(&home)
            .copied()
            .unwrap_or(f64::NEG_INFINITY);
    if (0.0..LOOK_EVERY).contains(&since) {
        return Ok(false);
    }
    tended.looked.insert(home.clone(), now);
    if tended
        .running
        .get(&home)
        .is_some_and(|thread| !thread.is_finished())
    {
        return Ok(false);
    }
    let key = engine_key(world.system.as_ref(), &exe).map_err(TendError::Raised)?;
    let record = read_record(Path::new(&paths.advanced_dir)).map_err(TendError::Raised)?;
    if !due(record.as_ref(), key.as_ref(), now).map_err(TendError::Raised)? {
        return Ok(false);
    }
    let Some(key) = key else {
        return Ok(false);
    };
    let same = record.as_ref().is_some_and(|record| {
        get(record, "key").is_some_and(|held| pyval::eq(held, &key))
            && get(record, "revision") == Some(&Value::from(REVISION))
    });
    let tries = match (
        same,
        record.as_ref().and_then(|record| get(record, "tries")),
    ) {
        (true, Some(Value::Int(tries))) => tries.as_i64().unwrap_or(i64::MAX).saturating_add(1),
        _ => 1,
    };
    let attempt = attempt(&key, tries, now);
    write(paths, &attempt).map_err(TendError::Write)?;
    let (world, paths) = (world.clone(), paths.clone());
    let thread = std::thread::Builder::new()
        .name("codex-auto-resume-autocheck".into())
        .spawn(move || {
            let _ = run_once(&world, &paths, &exe, &attempt, &clock);
        })
        .map_err(|_| TendError::Write(WriteError::Os))?;
    tended.running.insert(home, thread);
    Ok(true)
}

/// Wait for the run `tend` started for the installation at `home`, if one is going: for tests and the harness, which
/// read the record the run writes.
pub fn join(home: &str) {
    let thread = TENDED
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .as_mut()
        .and_then(|tended| tended.running.remove(&home_key(home)));
    if let Some(thread) = thread {
        let _ = thread.join();
    }
}

/// Forget every installation's last look and run: a new process, for tests and the harness.
pub fn reset() {
    *TENDED.lock().unwrap_or_else(PoisonError::into_inner) = None;
}
