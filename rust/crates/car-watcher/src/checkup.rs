//! `checkup.py`: the Diagnostics check (v0.6.16-beta.3) - why a failed turn is not taken up, answered by the
//! watcher's own rules.
//!
//! Here: every verdict and every word of it that does not read Codex - the usage reading (`_usage`), the summary
//! (`_summary`, its FIRST order), the times in words (`_ago`, `_within`), a reason's words (`_reason`) and the result
//! said line by line (`lines`), in every language the catalogs hold. What reads Codex and the records - `_conversations`
//! (the failure scan's `passed_over`, the engine's `not_taken_up` and `detection_since`) and `run` gathering it - is
//! joined with the engine by the integration, through car-control's `Host::checkup` (P6-DESIGN 4.1 row 1a's
//! `detection-check` golden then runs whole).

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
