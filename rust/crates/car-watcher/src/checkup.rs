//! `checkup.py`: the Diagnostics check (v0.6.16-beta.3) - why a failed turn is not taken up, answered by the
//! watcher's own rules.
//!
//! Here: every verdict and every word of it that does not read Codex - the usage reading (`_usage`), the summary
//! (`_summary`, its FIRST order), the times in words (`_ago`, `_within`), a reason's words (`_reason`) and the result
//! said line by line (`lines`), in every language the catalogs hold; and (S6.2b4) what reads Codex and the records -
//! `_conversations` (the failure scan's `passed_over`, the engine's `not_taken_up` and `detection_since`),
//! `_presence`, `_skip_lines`, `sources_for` and `run` gathering it, which car-control's `Host::checkup` answers
//! through [`crate::checkhost::WatcherHost`].

use car_machine::json::{Map, Value};
use car_machine::pyval;

/// How far back conversations are looked at, and how many at most.
pub const HOURS: i64 = 72;
pub const NEWEST: i64 = 200;
pub const SECONDS: f64 = 10.0;
pub const SKIP_LINES: usize = 20;
pub const FIVE_HOURS: i64 = 300;
pub const WEEK: i64 = 10_080;
/// The summary's reasons, most likely first.
pub const FIRST: &[&str] = &[
    "recovery_off",
    "watcher_stopped",
    "conversation_off",
    "category_off",
    "before_window",
    "other_kind",
    "continued_elsewhere",
    "unknown_conversation",
    "not_recovered",
    "newer_turn",
];

fn t(key: &str, locale: &str, fields: &[(&str, String)]) -> String {
    car_words::l10n::text(key, locale, fields).unwrap_or_else(|| key.to_owned())
}

fn get<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn text(value: &Value) -> Option<String> {
    match value {
        Value::Str(found) => Some(crate::fail::lossy(found)),
        _ => None,
    }
}

fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Int(_) | Value::Float(_) => car_machine::pytext::to_float(value).ok(),
        _ => None,
    }
}

/// `_ago(seconds, locale)`.
pub fn ago(seconds: Option<f64>, locale: &str) -> String {
    let Some(seconds) = seconds else {
        return t("check.never", locale, &[]);
    };
    let seconds = (seconds.trunc() as i64).max(0);
    if seconds < 3600 {
        return t(
            "check.ago_minutes",
            locale,
            &[("n", (seconds / 60).to_string())],
        );
    }
    if seconds < 2 * 86_400 {
        return t(
            "check.ago_hours",
            locale,
            &[("n", (seconds / 3600).to_string())],
        );
    }
    t(
        "check.ago_days",
        locale,
        &[("n", (seconds / 86_400).to_string())],
    )
}

/// `_within(seconds, locale)`.
pub fn within(seconds: f64, locale: &str) -> String {
    let seconds = (seconds.trunc() as i64).max(0);
    if seconds < 3600 {
        return t(
            "check.in_minutes",
            locale,
            &[("n", (seconds / 60).to_string())],
        );
    }
    t(
        "check.in_hours",
        locale,
        &[("n", (seconds / 3600).to_string())],
    )
}

/// `_reason(code, kind, locale)`: a reason's words; its kind word, where it has one, after them.
pub fn reason(code: &str, kind: Option<&str>, locale: &str) -> String {
    let key = format!("check.reason.{code}");
    let Some(words) = car_words::l10n::text(&key, locale, &[]) else {
        return code.to_owned();
    };
    match kind.filter(|kind| !kind.is_empty()) {
        Some(kind) => format!("{words} ({kind})"),
        None => words,
    }
}

/// `_usage(status, now)`: the last usage reading the watcher's heartbeat kept.
pub fn usage(status: &Value, now: f64) -> Value {
    let reading = get(get(status, "watcher"), "usage");
    let mut found = Map::new();
    let windows = match (reading, get(reading, "windows")) {
        (Value::Object(_), Value::Array(windows)) => windows.clone(),
        _ => {
            for (key, value) in [
                ("read", Value::Bool(false)),
                ("read_at", Value::Null),
                ("five_hour", Value::Null),
                ("weekly", Value::Null),
                ("reset_at", Value::Null),
            ] {
                found.insert(key.into(), value);
            }
            return Value::Object(found);
        }
    };
    found.insert("read".into(), Value::Bool(true));
    found.insert("read_at".into(), get(reading, "read_at").clone());
    found.insert("five_hour".into(), Value::Null);
    found.insert("weekly".into(), Value::Null);
    found.insert("reset_at".into(), Value::Null);
    let mut resets: Vec<Value> = Vec::new();
    for window in &windows {
        if !matches!(window, Value::Object(_)) {
            continue;
        }
        let minutes = get(window, "window_minutes");
        let used = get(window, "used_percent");
        let name = if pyval::eq(minutes, &Value::from(FIVE_HOURS)) {
            Some("five_hour")
        } else if pyval::eq(minutes, &Value::from(WEEK)) {
            Some("weekly")
        } else {
            None
        };
        if let Some(name) = name
            && matches!(found.get(name), Some(Value::Null))
            && matches!(used, Value::Int(_) | Value::Float(_))
        {
            found.insert(name.into(), used.clone());
        }
        let reset = get(window, "reset_at");
        if matches!(reset, Value::Int(_) | Value::Float(_))
            && pyval::greater(reset, &Value::Float(now)).unwrap_or(false)
        {
            resets.push(reset.clone());
        }
    }
    if let Some(first) = resets.first() {
        let mut least = first.clone();
        for each in &resets[1..] {
            if pyval::less(each, &least).unwrap_or(false) {
                least = each.clone();
            }
        }
        found.insert("reset_at".into(), least);
    }
    Value::Object(found)
}

fn rows(result: &Value, key: &str) -> Vec<Value> {
    match get(result, key) {
        Value::Array(items) => items.clone(),
        _ => Vec::new(),
    }
}

fn truthy(value: &Value) -> bool {
    pyval::truthy(value)
}

/// `_summary(rows, watcher_running, cloud)`: the most likely reason, as a code.
pub fn summary(rows: &[Value], watcher_running: bool, cloud: &Value) -> String {
    let failed: Vec<&Value> = rows
        .iter()
        .filter(|row| text(get(row, "status")).as_deref() == Some("failed"))
        .collect();
    let Some(latest) = failed.last() else {
        return if truthy(cloud) { "cloud" } else { "nothing" }.to_owned();
    };
    if truthy(get(latest, "records")) {
        return "taken".to_owned();
    }
    let mut reasons: Vec<String> = Vec::new();
    if truthy(get(latest, "reason"))
        && let Some(found) = text(get(latest, "reason"))
    {
        reasons.push(found);
    }
    if let Value::Array(remaining) = get(latest, "remaining") {
        reasons.extend(remaining.iter().filter_map(text));
    }
    if truthy(get(latest, "brought")) && !watcher_running {
        reasons.push("watcher_stopped".to_owned());
    }
    if reasons.is_empty() {
        return "ready".to_owned();
    }
    let rank = |code: &str| {
        FIRST
            .iter()
            .position(|each| *each == code)
            .unwrap_or(FIRST.len())
    };
    let mut best = reasons[0].clone();
    for each in &reasons[1..] {
        if rank(each) < rank(&best) {
            best = each.clone();
        }
    }
    best
}

/// `"%g" % x`: six significant digits, trailing zeros dropped, an exponent below 1e-4 and from 1e6.
pub fn percent_g(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_owned();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf" } else { "-inf" }.to_owned();
    }
    let text = format!("{x:.5e}");
    let (negative, rest) = match text.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, text.as_str()),
    };
    let (mantissa, exponent) = rest.split_once('e').unwrap_or((rest, "0"));
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let exponent: i32 = exponent.parse().unwrap_or(0);
    let point = exponent + 1;
    let mut out = String::new();
    if negative {
        out.push('-');
    }
    if point <= -4 || point > 6 {
        let kept = digits.trim_end_matches('0');
        let kept = if kept.is_empty() { "0" } else { kept };
        out.push_str(&kept[..1]);
        if kept.len() > 1 {
            out.push('.');
            out.push_str(&kept[1..]);
        }
        let sign = if exponent < 0 { '-' } else { '+' };
        out.push_str(&format!("e{sign}{:02}", exponent.unsigned_abs()));
    } else {
        let mut fixed = String::new();
        if point <= 0 {
            fixed.push_str("0.");
            fixed.extend(std::iter::repeat_n('0', point.unsigned_abs() as usize));
            fixed.push_str(&digits);
        } else {
            let point = point as usize;
            fixed.push_str(&digits[..point]);
            fixed.push('.');
            fixed.push_str(&digits[point..]);
        }
        out.push_str(fixed.trim_end_matches('0').trim_end_matches('.'));
    }
    out
}

fn percent(value: &Value) -> String {
    match value {
        Value::Null => "?".to_owned(),
        Value::Bool(flag) => percent_g(f64::from(u8::from(*flag))),
        other => number(other).map_or_else(|| "?".to_owned(), percent_g),
    }
}

/// `lines(result, now, locale)`: the result in words, a line each, the summary first.
pub fn lines(result: &Value, now: f64, locale: &str) -> Vec<String> {
    let hours = HOURS.to_string();
    let mut said = Vec::new();
    let summary = text(get(result, "summary")).unwrap_or_default();
    if matches!(summary.as_str(), "nothing" | "cloud" | "ready" | "taken") {
        said.push(t(
            &format!("check.summary.{summary}"),
            locale,
            &[("hours", hours.clone())],
        ));
    } else {
        said.push(t(
            "check.summary",
            locale,
            &[("reason", reason(&summary, None, locale))],
        ));
    }
    said.push(String::new());
    said.push(t("check.part1", locale, &[("hours", hours.clone())]));
    let conversations = rows(result, "conversations");
    if conversations.is_empty() {
        said.push(format!(
            "  {}",
            t("check.none_recent", locale, &[("hours", hours.clone())])
        ));
    }
    let left = get(result, "left_out");
    if truthy(get(left, "conversations")) {
        said.push(format!(
            "  {}",
            t(
                "check.left_out",
                locale,
                &[
                    ("n", car_machine::pytext::py_str(get(left, "conversations"))),
                    ("newest", NEWEST.to_string()),
                ],
            )
        ));
    }
    if truthy(get(left, "unchecked")) {
        said.push(format!(
            "  {}",
            t(
                "check.unchecked",
                locale,
                &[("n", car_machine::pytext::py_str(get(left, "unchecked")))]
            )
        ));
    }
    for row in &conversations {
        let status = text(get(row, "status"));
        let row_reason = text(get(row, "reason"));
        let verdict = if truthy(get(row, "brought")) {
            t("check.yes", locale, &[])
        } else if status.as_deref() != Some("failed") && matches!(get(row, "reason"), Value::Null) {
            t(
                "check.no",
                locale,
                &[("reason", reason("not_failed", None, locale))],
            )
        } else {
            let code = row_reason
                .filter(|code| !code.is_empty())
                .unwrap_or_else(|| "not_failed".into());
            t(
                "check.no",
                locale,
                &[(
                    "reason",
                    reason(&code, text(get(row, "kind")).as_deref(), locale),
                )],
            )
        };
        let when = if truthy(get(row, "completed_at")) {
            ago(number(get(row, "completed_at")).map(|at| now - at), locale)
        } else {
            t("check.never", locale, &[])
        };
        let category = match text(get(row, "category")).filter(|found| !found.is_empty()) {
            Some(found) => format!(" ({found})"),
            None => String::new(),
        };
        said.push(format!(
            "  {}",
            t(
                "check.row",
                locale,
                &[
                    ("when", when),
                    ("thread", car_machine::pytext::py_str(get(row, "thread"))),
                    (
                        "status",
                        status
                            .filter(|found| !found.is_empty())
                            .unwrap_or_else(|| "?".into()),
                    ),
                    ("category", category),
                    ("verdict", verdict),
                ],
            )
        ));
    }
    said.push(String::new());
    said.push(t("check.part2", locale, &[]));
    let brought: Vec<&Value> = conversations
        .iter()
        .filter(|row| truthy(get(row, "brought")))
        .collect();
    if brought.is_empty() {
        said.push(format!("  {}", t("check.part2_none", locale, &[])));
    }
    let running = truthy(get(result, "watcher_running"));
    for row in brought {
        let thread = car_machine::pytext::py_str(get(row, "thread"));
        if truthy(get(row, "records")) {
            let states: Vec<String> = match get(row, "records") {
                Value::Array(items) => items.iter().map(car_machine::pytext::py_str).collect(),
                _ => Vec::new(),
            };
            said.push(format!(
                "  {}",
                t(
                    "check.recorded",
                    locale,
                    &[("thread", thread), ("state", states.join(", "))]
                )
            ));
            continue;
        }
        let mut held: Vec<String> = match get(row, "remaining") {
            Value::Array(items) => items.iter().map(car_machine::pytext::py_str).collect(),
            _ => Vec::new(),
        };
        if !running {
            held.push("watcher_stopped".to_owned());
        }
        if held.is_empty() {
            said.push(format!(
                "  {}",
                t("check.held_none", locale, &[("thread", thread.clone())])
            ));
        }
        for code in held {
            said.push(format!(
                "  {}",
                t(
                    "check.held",
                    locale,
                    &[
                        ("thread", thread.clone()),
                        ("reason", reason(&code, None, locale))
                    ],
                )
            ));
        }
    }
    said.push(String::new());
    said.push(t("check.split_title", locale, &[]));
    let split = rows(result, "split");
    if split.is_empty() {
        said.push(format!("  {}", t("check.split_none", locale, &[])));
    }
    for pair in &split {
        said.push(format!(
            "  {}",
            t(
                "check.split_row",
                locale,
                &[
                    ("thread", car_machine::pytext::py_str(get(pair, "thread"))),
                    (
                        "other",
                        car_machine::pytext::py_str(get(pair, "turns_under"))
                    ),
                ],
            )
        ));
    }
    said.push(String::new());
    said.push(t("check.homes_title", locale, &[]));
    for home in rows(result, "homes") {
        let name = if matches!(get(&home, "home"), Value::Null) {
            t("check.home_default", locale, &[])
        } else {
            t(
                "check.home_other",
                locale,
                &[("n", car_machine::pytext::py_str(get(&home, "home")))],
            )
        };
        if !truthy(get(&home, "readable")) {
            said.push(format!(
                "  {}",
                t("check.home_unreadable", locale, &[("home", name)])
            ));
            continue;
        }
        let state = ago(
            number(get(&home, "state_written")).map(|at| now - at),
            locale,
        );
        let history = ago(
            number(get(&home, "history_written")).map(|at| now - at),
            locale,
        );
        let current = if truthy(get(&home, "current")) {
            t("check.home_current", locale, &[])
        } else {
            String::new()
        };
        said.push(format!(
            "  {}",
            t(
                "check.home_row",
                locale,
                &[
                    ("home", name),
                    ("state", state),
                    ("history", history),
                    ("current", current)
                ],
            )
        ));
    }
    said.push(String::new());
    let count = get(result, "cloud_tasks");
    said.push(if truthy(count) {
        t(
            "check.cloud",
            locale,
            &[("count", car_machine::pytext::py_str(count))],
        )
    } else {
        t("check.cloud_none", locale, &[])
    });
    let reading = get(result, "usage");
    if truthy(get(reading, "read")) {
        let when = if truthy(get(reading, "read_at")) {
            ago(number(get(reading, "read_at")).map(|at| now - at), locale)
        } else {
            "?".to_owned()
        };
        let reset = if truthy(get(reading, "reset_at")) {
            number(get(reading, "reset_at"))
                .map_or_else(|| "?".into(), |at| within(at - now, locale))
        } else {
            "?".to_owned()
        };
        said.push(t(
            "check.usage",
            locale,
            &[
                ("when", when),
                ("five", percent(get(reading, "five_hour"))),
                ("weekly", percent(get(reading, "weekly"))),
                ("reset", reset),
            ],
        ));
    } else {
        said.push(t("check.usage_none", locale, &[]));
    }
    let notices = get(result, "notices");
    let word = |value: &Value, yes: &str, no: &str| match value {
        Value::Null => t("check.unknown", locale, &[]),
        found if truthy(found) => t(yes, locale, &[]),
        _ => t(no, locale, &[]),
    };
    let route = match text(get(notices, "route")).filter(|found| !found.is_empty()) {
        Some(route) => t(&format!("check.route.{route}"), locale, &[]),
        None => t("check.unknown", locale, &[]),
    };
    said.push(t(
        "check.notices",
        locale,
        &[
            ("route", route),
            (
                "dnd",
                word(get(notices, "do_not_disturb"), "check.on", "check.off"),
            ),
            (
                "allowed",
                word(
                    get(notices, "app_allowed"),
                    "check.allowed",
                    "check.blocked",
                ),
            ),
        ],
    ));
    let codex = get(result, "codex");
    let or_unknown = |value: &Value| {
        if truthy(value) {
            car_machine::pytext::py_str(value)
        } else {
            t("check.unknown", locale, &[])
        }
    };
    said.push(t(
        "check.codex",
        locale,
        &[
            ("version", or_unknown(get(codex, "version"))),
            ("tier", or_unknown(get(codex, "tier"))),
            (
                "found",
                if truthy(get(codex, "engine_found")) {
                    t("check.found", locale, &[])
                } else {
                    t("check.not_found", locale, &[])
                },
            ),
        ],
    ));
    said.push(String::new());
    said.push(t("check.skips_title", locale, &[]));
    let skips = rows(result, "skips");
    if skips.is_empty() {
        said.push(format!("  {}", t("check.skips_none", locale, &[])));
    }
    for line in skips {
        said.push(format!("  {}", car_machine::pytext::py_str(&line)));
    }
    said
}

// ------------------------------------------------------------------------------------------- run (S6.2b4)

use std::collections::BTreeSet;
use std::rc::Rc;

use car_codex::source::LocalSource;
use car_control::Control;
use car_control::diagnostics::Redactor;
use car_control::error::Failure;
use car_control::host::Raised;

/// What `run` lets out, as the reference raises it: a ControlError whole, anything else by its class.
fn failure(failed: Failure) -> Raised {
    match failed {
        Failure::Control(refused) => Raised::control(&refused),
        Failure::Other(class) => Raised::new(&class, ""),
    }
}

fn store_failed(error: car_store::errors::Error) -> Raised {
    Raised::new(error.class(), error.message())
}

fn reader_failed(failed: crate::fail::Failed) -> Raised {
    Raised::new(&failed.class, failed.message)
}

/// `except HistoryNotYet:` (v0.6.26 final): a fresh home whose history Codex has not made yet - read, and holding
/// nothing - is passed by, not unreadable. car-codex's `Error::is_history_not_yet()` (the final port's HistoryNotYet,
/// a SourceError that says so; joined by Integration 11).
pub fn history_not_yet(error: &car_codex::errors::Error) -> bool {
    error.is_history_not_yet()
}

/// `sources_for(control)`: (label, reader) for each Codex home the watcher knows - the default (label None) first,
/// then each one Settings add, by its number (2, 3, ...).
pub fn sources_for(control: &Control) -> Result<Vec<(Value, LocalSource)>, Raised> {
    let chains = control.paths.split_chains_file.clone();
    let host = &control.host;
    let mut found = vec![(
        Value::Null,
        crate::reading::source(host, &chains, &host.codex_home()).map_err(reader_failed)?,
    )];
    let named = control
        .get_settings()
        .ok()
        .and_then(|values| values.get(car_policy::settings::homes::FIELD).cloned())
        .unwrap_or(Value::Null);
    if let Value::Array(entries) = named {
        for (number, entry) in (2i64..).zip(&entries) {
            if let Value::Object(entry) = entry
                && let Some(Value::Str(path)) = entry.get("path")
            {
                let path = crate::fail::lossy(path);
                found.push((
                    Value::from(number),
                    crate::reading::source(host, &chains, &path).map_err(reader_failed)?,
                ));
            }
        }
    }
    Ok(found)
}

/// `_presence()` over the probes' answers: how a notice reaches the person now - card or toast, Do not disturb,
/// this app's notifications, each None where Windows cannot say.
pub fn presence(found: &Map) -> Value {
    let mode = found
        .get("notification_mode")
        .cloned()
        .unwrap_or(Value::Null);
    let allowed = found
        .get("app_notifications")
        .cloned()
        .unwrap_or(Value::Null);
    let card = car_surface::notice_presence::card_allowed(
        &car_surface::notice_presence::Answers::from_probes(found),
    );
    let int = |value: &Value| match value {
        Value::Int(int) => int.as_i64(),
        _ => None,
    };
    let mut out = Map::new();
    out.insert(
        "route".into(),
        Value::from(if card { "card" } else { "toast" }),
    );
    out.insert(
        "do_not_disturb".into(),
        int(&mode).map_or(Value::Null, |mode| {
            Value::Bool(mode != car_surface::notice_presence::MODE_UNRESTRICTED)
        }),
    );
    out.insert(
        "app_allowed".into(),
        int(&allowed).map_or(Value::Null, |allowed| {
            Value::Bool(allowed == car_surface::notice_presence::APP_ENABLED)
        }),
    );
    Value::Object(out)
}

/// This PC's `_presence()`: the probes read now under the product's AUMID.
pub fn system_presence() -> Result<Value, Raised> {
    match crate::notices::presence().map_err(|_| Raised::new("OSError", ""))? {
        Value::Object(found) => Ok(presence(&found)),
        _ => Err(Raised::new("TypeError", "")),
    }
}

/// `_skip_lines(control, redact)`: the watcher's last skip lines (and the two lines beside them), redacted.
fn skip_lines(control: &Control, redact: &Redactor) -> Vec<Value> {
    let lines_of = |query: &str, limit: usize| -> Option<Vec<Value>> {
        let found = control
            .search_logs(&Value::from(query), &Value::from(limit as i64))
            .ok()?;
        match get(&found, "lines") {
            Value::Array(lines) => Some(lines.clone()),
            _ => None,
        }
    };
    let Some(mut found) = lines_of("not taken up", SKIP_LINES) else {
        return Vec::new();
    };
    let Some(more) = lines_of("automatic recovery is off", 3) else {
        return Vec::new();
    };
    found.extend(more);
    found.sort_by_key(|line| car_machine::pytext::py_str(get(line, "at")));
    let start = found.len().saturating_sub(SKIP_LINES);
    found[start..]
        .iter()
        .map(|line| {
            Value::from(redact.text(&format!(
                "{} {}",
                car_machine::pytext::py_str(get(line, "at")),
                car_machine::pytext::py_str(get(line, "text"))
            )))
        })
        .collect()
}

fn obj(pairs: Vec<(&str, Value)>) -> Map {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(key.into(), value);
    }
    map
}

/// What `_conversations` hands back: the rows, the homes, and how many were left out and unchecked.
struct Read {
    rows: Vec<Value>,
    homes: Vec<Map>,
    left: (i64, i64),
}

/// `_conversations(control, sources, engine_for, now, redact)`: each recent conversation's latest turn in every
/// home, and for one the failure scan brings, the engine's own remaining reasons and the records of that turn.
fn conversations(
    control: &Control,
    sources: &[(Value, LocalSource)],
    values: &Value,
    held: &car_policy::settings::managed::Managed,
    now: f64,
    redact: &Redactor,
) -> Result<Read, Raised> {
    let (mut found, mut homes, mut left) = (Vec::new(), Vec::new(), (0i64, 0i64));
    let deadline = car_codex::rollout::monotonic() + SECONDS;
    let store = Rc::new(control.open_current().map_err(failure)?);
    let stored = store.settings().map_err(store_failed)?;
    let records = store.all_records().map_err(store_failed)?;
    for (label, source) in sources {
        let mut home = obj(vec![
            ("home", label.clone()),
            ("state_written", Value::Null),
            ("history_written", Value::Null),
            ("current", Value::Bool(false)),
            ("readable", Value::Bool(true)),
            ("cloud_tasks", Value::Null),
        ]);
        match source.written() {
            Ok(written) => {
                let time = |at: Option<f64>| at.map_or(Value::Null, Value::Float);
                home.insert("state_written".into(), time(written.state_written));
                home.insert("history_written".into(), time(written.history_written));
                home.insert(
                    "cloud_tasks".into(),
                    source.cloud_tasks().map_or(Value::Null, Value::from),
                );
            }
            Err(_) => {
                home.insert("readable".into(), Value::Bool(false));
            }
        }
        homes.push(home);
        let at = homes.len() - 1;
        // `engine_for(store, source)`: the engine reads through a reader of its own over the same home.
        let reader = crate::reading::source(
            &control.host,
            &control.paths.split_chains_file,
            &source.home,
        )
        .map_err(reader_failed)?;
        let mut engine =
            crate::reading::engine(&control.host, Some(Rc::clone(&store)), reader, now, "");
        engine.apply_policy(values, Some(held.clone()));
        let since = engine
            .detection_since(&stored)
            .map_err(|class| Raised::new(class, ""))?;
        let read = match source.passed_over(
            &Value::Float(since),
            &Value::Float(now - (HOURS * 3600) as f64),
            true,
            &BTreeSet::new(),
            Some(NEWEST as usize),
            Some(deadline),
        ) {
            Ok(read) => read,
            Err(error) if history_not_yet(&error) => continue,
            Err(_) => {
                homes[at].insert("readable".into(), Value::Bool(false));
                continue;
            }
        };
        let count = |name: &str| match read.get(name) {
            Some(Value::Int(int)) => int.as_i64().unwrap_or(0),
            _ => 0,
        };
        left.0 += count("more");
        left.1 += count("unchecked");
        let passed = match read.get("passed") {
            Some(Value::Array(passed)) => passed.clone(),
            _ => Vec::new(),
        };
        for entry in &passed {
            let Value::Object(fields) = entry else {
                continue;
            };
            let field = |name: &str| fields.get(name).cloned().unwrap_or(Value::Null);
            let brought = text(&field("status")).as_deref() == Some("failed")
                && matches!(field("reason"), Value::Null);
            let turns = field("turns_id");
            let mut remaining = Vec::new();
            let mut taken = Vec::new();
            if brought {
                if !pyval::truthy(stored.get("enabled").unwrap_or(&Value::Null))
                    || engine.managed.disable_auto_resume
                {
                    remaining.push(Value::from(
                        car_machine::vocab_gen::domain_skips::RECOVERY_OFF,
                    ));
                }
                if let Some((why, _)) = engine
                    .not_taken_up(fields)
                    .map_err(|class| Raised::new(class, ""))?
                {
                    remaining.push(Value::from(why.as_str()));
                }
                for record in &records {
                    let of = |name: &str| record.get(name).unwrap_or(&Value::Null);
                    if pyval::eq(of("thread_id"), &field("thread_id"))
                        && pyval::eq(of("turn_id"), &field("turn_id"))
                    {
                        taken.push(of("state").clone());
                    }
                }
            }
            let under = if pyval::truthy(&turns) {
                Value::from(redact.alias(&turns, "thread"))
            } else {
                Value::Null
            };
            found.push(Value::Object(obj(vec![
                (
                    "thread",
                    Value::from(redact.alias(&field("thread_id"), "thread")),
                ),
                ("home", label.clone()),
                ("status", field("status")),
                ("category", field("category")),
                ("completed_at", field("completed_at")),
                ("reason", field("reason")),
                ("kind", field("kind")),
                ("turns_under", under),
                ("brought", Value::Bool(brought)),
                ("remaining", Value::Array(remaining)),
                ("records", Value::Array(taken)),
            ])));
        }
    }
    let newest = homes
        .iter()
        .filter_map(|home| match home.get("history_written") {
            Some(Value::Float(at)) => Some(*at),
            _ => None,
        })
        .reduce(f64::max);
    for home in &mut homes {
        let current = match (newest, home.get("history_written")) {
            (Some(newest), Some(Value::Float(at))) => *at == newest,
            _ => false,
        };
        home.insert("current".into(), Value::Bool(current));
    }
    let completed = |row: &Value| {
        let at = get(row, "completed_at");
        if pyval::truthy(at) {
            number(at).unwrap_or(0.0)
        } else {
            0.0
        }
    };
    found.sort_by(|a, b| {
        completed(a)
            .partial_cmp(&completed(b))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    Ok(Read {
        rows: found,
        homes,
        left,
    })
}

/// How `run` is asked: the clock, the aliases' key (a fresh one where None), the language (the Interface
/// language where None) and how a notice reaches the person now.
pub struct Asked<'a> {
    pub now: f64,
    pub key: Option<&'a [u8]>,
    pub locale: Option<&'a str>,
    pub presence: &'a dyn Fn() -> Result<Value, Raised>,
}

fn interface_locale(control: &Control) -> String {
    match control.get_settings() {
        Ok(values) => {
            let host = &control.host;
            let environ = |name: &str| host.environ(name);
            let windows = || host.windows_languages();
            let preference = match values.get("interface_language") {
                Some(Value::Str(text)) => Some(crate::fail::lossy(text)),
                _ => None,
            };
            car_words::l10n::resolve(preference.as_deref(), &environ, &windows).to_owned()
        }
        Err(_) => car_words::l10n::DEFAULT.to_owned(),
    }
}

/// `run(control, sources=None, *, now=None, redact=None, locale=None, presence=None)`: the check, run now - the
/// structured result and `lines`, the summary first.
pub fn run(control: &Control, asked: &Asked<'_>) -> Result<Value, Raised> {
    let now = asked.now;
    let sources = sources_for(control)?;
    let redact = match asked.key {
        Some(key) => Redactor::with_key(control, key),
        None => Redactor::new(control),
    };
    let locale = match asked.locale {
        Some(locale) => locale.to_owned(),
        None => interface_locale(control),
    };
    let os = control.host.os();
    let path = control.settings_path();
    let settings_failed = |error: car_policy::settings::SettingsError| {
        Raised::new(error.class(), lossy_text(&error.message()))
    };
    let values = car_policy::settings::load(&*os, &path).map_err(settings_failed)?;
    let unread = match car_policy::settings::read(&*os, &path) {
        Ok(_) => None,
        Err(car_policy::settings::SettingsError::Unreadable { reason, .. }) => Some(reason),
        Err(error) => return Err(settings_failed(error)),
    };
    let held = control.managed();
    let read = conversations(
        control,
        &sources,
        &Value::Object(values),
        &held,
        now,
        &redact,
    )?;
    let status = control
        .get_status()
        .unwrap_or_else(|_| Value::Object(Map::new()));
    let running = pyval::truthy(get(&status, "watcher_running"));
    let notices = (asked.presence)().unwrap_or_else(|_| {
        Value::Object(obj(vec![
            ("route", Value::Null),
            ("do_not_disturb", Value::Null),
            ("app_allowed", Value::Null),
        ]))
    });
    let codex = codex_of(&control.bundle_compatibility());
    let cloud: Vec<i64> = read
        .homes
        .iter()
        .filter_map(|home| match home.get("cloud_tasks") {
            Some(Value::Int(int)) => int.as_i64(),
            _ => None,
        })
        .collect();
    let total: i64 = cloud.iter().sum();
    let mut split: Vec<(String, String)> = read
        .rows
        .iter()
        .filter(|row| pyval::truthy(get(row, "turns_under")))
        .map(|row| {
            (
                text(get(row, "thread")).unwrap_or_default(),
                text(get(row, "turns_under")).unwrap_or_default(),
            )
        })
        .collect();
    split.sort();
    split.dedup();
    let split = split
        .iter()
        .map(|(thread, other)| {
            Value::Object(obj(vec![
                ("thread", Value::from(thread.as_str())),
                ("turns_under", Value::from(other.as_str())),
            ]))
        })
        .collect();
    let said = summary(&read.rows, running, &Value::from(total));
    let mut result = obj(vec![
        ("summary", Value::from(said.as_str())),
        ("watcher_running", Value::Bool(running)),
        ("conversations", Value::Array(read.rows)),
        (
            "left_out",
            Value::Object(obj(vec![
                ("conversations", Value::from(read.left.0)),
                ("unchecked", Value::from(read.left.1)),
            ])),
        ),
        ("split", Value::Array(split)),
        (
            "homes",
            Value::Array(read.homes.into_iter().map(Value::Object).collect()),
        ),
        (
            "cloud_tasks",
            if cloud.is_empty() {
                Value::Null
            } else {
                Value::from(total)
            },
        ),
        ("usage", usage(&status, now)),
        ("notices", notices),
        ("codex", codex),
        ("skips", Value::Array(skip_lines(control, &redact))),
    ]);
    let mut words: Vec<Value> = lines(&Value::Object(result.clone()), now, &locale)
        .into_iter()
        .map(Value::from)
        .collect();
    if let Some(reason) = unread {
        // The verdicts above are on the defaults, which the watcher does not act on while the file cannot be read.
        let line = t("check.settings_unreadable", &locale, &[("reason", reason)]);
        words.insert(1.min(words.len()), Value::from(line));
    }
    result.insert("lines".into(), Value::Array(words));
    Ok(Value::Object(result))
}

/// `{"version", "tier", "engine_found"}` of the registry's view (`_compatibility(control)`); the defaults for a view
/// that is not a dict, or whose engine is neither a dict nor empty (the reference's `AttributeError`, caught).
fn codex_of(compat: &Value) -> Value {
    let fallback = || {
        Value::Object(obj(vec![
            ("version", Value::Null),
            ("tier", Value::Null),
            ("engine_found", Value::Bool(false)),
        ]))
    };
    let Value::Object(compat) = compat else {
        return fallback();
    };
    let engine = compat.get("engine").cloned().unwrap_or(Value::Null);
    let engine = if pyval::truthy(&engine) {
        match engine {
            Value::Object(map) => map,
            _ => return fallback(),
        }
    } else {
        Map::new()
    };
    let found = pyval::truthy(engine.get("found").unwrap_or(&Value::Null));
    Value::Object(obj(vec![
        (
            "version",
            engine.get("version").cloned().unwrap_or(Value::Null),
        ),
        (
            "tier",
            compat.get("overall").cloned().unwrap_or(Value::Null),
        ),
        ("engine_found", Value::Bool(found)),
    ]))
}

fn lossy_text(text: &car_machine::json::Str) -> String {
    crate::fail::lossy(text)
}

/// `for_bundle(control)(redact)`: the check as the diagnostics bundle runs it - in English, under the bundle's key.
pub fn for_bundle(
    control: &Control,
    key: &[u8],
    now: f64,
    presence: &dyn Fn() -> Result<Value, Raised>,
) -> Result<Value, Raised> {
    run(
        control,
        &Asked {
            now,
            key: Some(key),
            locale: Some(car_words::l10n::DEFAULT),
            presence,
        },
    )
}
