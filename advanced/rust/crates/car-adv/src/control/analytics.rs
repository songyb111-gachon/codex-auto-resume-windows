//! `control/analytics.py` (seat S7.3a2): the Dashboard's usage and token analytics (v0.6.20, usage_analytics) - its
//! card read (`advanced-analytics {days}`) and its CSV saved where the person chose (`advanced-analytics-csv {days,
//! path, replace}`). Each the long-lived bridge's, the Dashboard's alone; neither writes anything of the edition's
//! state. Labels are resolved now by core's own reader of each watched Codex home, never stored (B8).

use std::collections::BTreeSet;

use car_machine::json::{Int, Map, Str, Value};
use car_machine::localclock::LocalClock;
use car_machine::pyval;

use super::resets::{Result, codex_os, field, get, int, object, refusal, standing, state, text};
use crate::codex::tokens;
use crate::codex::turns::Turns;
use crate::engine::analytics::{CAPABILITY, DAYS, DEFAULT_DAYS, MTOK, pace, route};
use crate::engine::usage::WINDOWS;
use crate::runtime::Runtime;
use crate::state::Error;
use crate::vocabulary::{OptionKey, Refusal, ReportRefusal};

pub const PROJECTS_LIMIT: usize = 50;
pub const CONVERSATIONS_LIMIT: usize = 50;
pub const COLUMNS: [&str; 8] = [
    "day",
    "project",
    "input",
    "cached",
    "output",
    "reasoning",
    "turns",
    "lifetime",
];
pub const FORMULA: [char; 6] = ['=', '+', '-', '@', '\t', '\r'];
pub const NUMBERS: [&str; 5] = ["input", "cached", "output", "reasoning", "turns"];

/// `_days(runtime, value)`: the days asked for, or the capability's own choice where none was asked; None for a wrong
/// one.
pub fn days_of(runtime: &Runtime, value: &Value) -> Option<i64> {
    let value = if matches!(value, Value::Null) {
        state(runtime, "options")
            .and_then(|state| state.options(&text(CAPABILITY)))
            .map(|options| {
                options
                    .get(OptionKey::AnalyticsDays.as_str())
                    .cloned()
                    .unwrap_or(int(DEFAULT_DAYS))
            })
            .unwrap_or(int(DEFAULT_DAYS))
    } else {
        value.clone()
    };
    match value {
        Value::Int(days) => days.as_i64().filter(|days| DAYS.contains(days)),
        _ => None,
    }
}

/// `_verdict(runtime)`.
fn verdict(runtime: &Runtime) -> Value {
    match runtime.arming().verdict(MTOK) {
        Ok(Some(word)) => text(word),
        _ => Value::Null,
    }
}

/// `first_day(now, days)`: the first local day of the last `days` days up to `now`'s.
pub fn first_day(local: &dyn LocalClock, now: f64, days: i64) -> Result<String> {
    let tm = local
        .localtime(now - ((days - 1) * 86400) as f64)
        .map_err(|_| Error::python("OSError", "localtime"))?;
    Ok(format!("{:04}-{:02}-{:02}", tm.year, tm.mon, tm.mday))
}

/// `_Labels(homes)`: labels resolved at display time, never stored.
struct Labels {
    homes: Vec<String>,
    sources: Vec<(String, Option<car_codex::source::LocalSource>)>,
    seen: Vec<(String, Map)>,
}

impl Labels {
    fn new(homes: &[String]) -> Labels {
        Labels {
            homes: homes.to_vec(),
            sources: Vec::new(),
            seen: Vec::new(),
        }
    }

    fn source(&mut self, home: &str) -> Option<&car_codex::source::LocalSource> {
        if !self.sources.iter().any(|(each, _)| each == home) {
            let made = car_codex::source::LocalSource::new(
                std::sync::Arc::new(car_codex::system::PolicyOs),
                home,
                None,
            )
            .ok();
            self.sources.push((home.to_owned(), made));
        }
        self.sources
            .iter()
            .find(|(each, _)| each == home)
            .and_then(|(_, source)| source.as_ref())
    }

    fn identity(&mut self, thread: &str) -> Map {
        if let Some((_, found)) = self.seen.iter().find(|(each, _)| each == thread) {
            return found.clone();
        }
        let mut found = match object(vec![
            ("name", Value::Null),
            ("project", Value::Null),
            ("cwd_basename", Value::Null),
        ]) {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        for home in self.homes.clone() {
            let seen = self
                .source(&home)
                .and_then(|source| source.identity(thread).ok());
            if let Some(seen) = seen
                && !seen.is_empty()
                && ["name", "project", "cwd_basename"]
                    .iter()
                    .any(|name| seen.get(*name).is_some_and(pyval::truthy))
            {
                found = seen;
                found.insert(Str::new("home"), text(&home));
                break;
            }
        }
        self.seen.push((thread.to_owned(), found.clone()));
        found
    }

    fn project(&mut self, thread: &str) -> Value {
        let seen = self.identity(thread);
        let project = seen.get("project").cloned().unwrap_or(Value::Null);
        if pyval::truthy(&project) {
            project
        } else {
            seen.get("cwd_basename").cloned().unwrap_or(Value::Null)
        }
    }
}

fn thread_text(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    }
}

/// `_lifetime(...)`: (thread, project key, lifetime tokens) of each conversation that finished a turn in the last
/// `days` and is not one of `known`.
fn lifetime(
    homes: &[String],
    labels: &mut Labels,
    now: f64,
    days: i64,
    known: &[String],
) -> Vec<(String, Value, Value)> {
    let mut found = Vec::new();
    let mut seen: BTreeSet<String> = known.iter().cloned().collect();
    for home in homes {
        let since = (now - (days * 86400) as f64).trunc() as i64;
        let threads = Turns::new(home, codex_os())
            .recent(since)
            .unwrap_or_default();
        let has_source = labels.source(home).is_some();
        for thread in threads {
            if seen.contains(&thread) || !has_source {
                continue;
            }
            seen.insert(thread.clone());
            let Some(source) = labels.source(home) else {
                continue;
            };
            let read = (|| {
                let count = source
                    .task_facts(&thread, false, true)
                    .ok()?
                    .get("tokens")
                    .cloned()
                    .unwrap_or(Value::Null);
                let key = source.project_key(&thread).ok()?;
                Some((count, key))
            })();
            let Some((count, key)) = read else {
                continue;
            };
            if matches!(count, Value::Null) {
                continue;
            }
            let key = match key {
                Some(key) if key.chars().count() >= 16 => {
                    text(&key.chars().take(16).collect::<String>())
                }
                _ => Value::Null,
            };
            found.push((thread, key, count));
        }
    }
    found
}

fn numbers() -> Vec<(&'static str, Value)> {
    NUMBERS.iter().map(|name| (*name, int(0))).collect()
}

fn add(a: &Value, b: &Value) -> Result<Value> {
    match super::resets::plus(a, b) {
        Value::Null => Err(Error::type_error("unsupported operand type(s) for +=")),
        sum => Ok(sum),
    }
}

fn number(map: &Map, name: &str) -> f64 {
    super::resets::number_of(map.get(name).unwrap_or(&Value::Null)).unwrap_or(0.0)
}

/// `(x or 0)` as a number.
fn or_zero(value: &Value) -> f64 {
    super::resets::or_zero(value).unwrap_or(0.0)
}

/// A project as the card shows it, while it is built.
struct Project {
    key: Value,
    fields: Map,
    conversations: Vec<(String, Map)>,
}

fn blank(pairs: Vec<(&str, Value)>) -> Map {
    match object(pairs) {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

fn project_of<'a>(projects: &'a mut Vec<Project>, key: &Value) -> &'a mut Project {
    let at = match projects
        .iter()
        .position(|project| pyval::eq(&project.key, key) && same_kind(&project.key, key))
    {
        Some(at) => at,
        None => {
            let mut pairs = vec![("key", key.clone()), ("label", Value::Null)];
            pairs.extend(numbers());
            pairs.push(("lifetime", Value::Null));
            projects.push(Project {
                key: key.clone(),
                fields: blank(pairs),
                conversations: Vec::new(),
            });
            projects.len() - 1
        }
    };
    &mut projects[at]
}

/// Dict keys: None and a text are never equal.
fn same_kind(a: &Value, b: &Value) -> bool {
    matches!(
        (a, b),
        (Value::Null, Value::Null) | (Value::Str(_), Value::Str(_))
    ) || !matches!(a, Value::Null | Value::Str(_))
}

fn conversation(thread: &Value, lifetime: Value) -> Map {
    let mut pairs = vec![("thread_id", thread.clone()), ("label", Value::Null)];
    pairs.extend(numbers());
    pairs.push(("lifetime", lifetime));
    blank(pairs)
}

/// `aggregate(runtime, days, now=)`: the card's numbers, and the homes read.
pub fn aggregate(runtime: &Runtime, days: i64, now: f64) -> Result<(Map, Vec<String>)> {
    let measured = verdict(runtime);
    let way = route(&measured);
    let homes = crate::engine::analytics::watched(&runtime.paths);
    let mut labels = Labels::new(&homes);
    let rows = if way == "per_day" {
        let first = first_day(&car_platform::localclock::Crt, now, days)?;
        state(runtime, "token_days")?.token_days(&text(&first))?
    } else {
        Vec::new()
    };
    let mut projects: Vec<Project> = Vec::new();
    let mut known: Vec<String> = Vec::new();
    for row in &rows {
        let key = get(row, "project_digest");
        let thread = get(row, "thread_id");
        let project = project_of(&mut projects, &key);
        let at = match project
            .conversations
            .iter()
            .position(|(each, _)| *each == thread_text(&thread))
        {
            Some(at) => at,
            None => {
                project
                    .conversations
                    .push((thread_text(&thread), conversation(&thread, Value::Null)));
                project.conversations.len() - 1
            }
        };
        for name in NUMBERS {
            let value = get(row, name);
            let sum = add(project.fields.get(name).unwrap_or(&Value::Null), &value)?;
            project.fields.insert(Str::new(name), sum);
            let item = &mut project.conversations[at].1;
            let sum = add(item.get(name).unwrap_or(&Value::Null), &value)?;
            item.insert(Str::new(name), sum);
        }
        let id = thread_text(&thread);
        if !known.contains(&id) {
            known.push(id);
        }
    }
    for (thread, key, count) in lifetime(&homes, &mut labels, now, days, &known) {
        let project = project_of(&mut projects, &key);
        let had = project
            .fields
            .get("lifetime")
            .cloned()
            .unwrap_or(Value::Null);
        let base = if pyval::truthy(&had) { had } else { int(0) };
        let sum = add(&base, &count)?;
        project.fields.insert(Str::new("lifetime"), sum);
        let item = conversation(&text(&thread), count);
        match project
            .conversations
            .iter()
            .position(|(each, _)| *each == thread)
        {
            Some(at) => project.conversations[at].1 = item,
            None => project.conversations.push((thread, item)),
        }
    }
    let mut shown: Vec<Map> = Vec::new();
    for project in projects {
        let mut items: Vec<Map> = project
            .conversations
            .into_iter()
            .map(|(_, item)| item)
            .collect();
        items.sort_by(|a, b| {
            let left = (
                -(number(a, "input") + number(a, "output")),
                -or_zero(a.get("lifetime").unwrap_or(&Value::Null)),
            );
            let right = (
                -(number(b, "input") + number(b, "output")),
                -or_zero(b.get("lifetime").unwrap_or(&Value::Null)),
            );
            left.partial_cmp(&right)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut fields = project.fields;
        for item in items.iter_mut().take(CONVERSATIONS_LIMIT) {
            let thread = thread_text(item.get("thread_id").unwrap_or(&Value::Null));
            let name = labels
                .identity(&thread)
                .get("name")
                .cloned()
                .unwrap_or(Value::Null);
            item.insert(Str::new("label"), name);
        }
        for item in &items {
            if matches!(fields.get("label"), None | Some(Value::Null)) {
                let thread = thread_text(item.get("thread_id").unwrap_or(&Value::Null));
                fields.insert(Str::new("label"), labels.project(&thread));
            }
        }
        let more = items.len().saturating_sub(CONVERSATIONS_LIMIT);
        items.truncate(CONVERSATIONS_LIMIT);
        fields.insert(
            Str::new("conversations"),
            Value::Array(items.into_iter().map(Value::Object).collect()),
        );
        fields.insert(Str::new("more"), int(more as i64));
        shown.push(fields);
    }
    let order_key = |item: &Map| match item.get("key") {
        Some(Value::Str(key)) if !key.is_empty() => key.clone(),
        _ => Str::new("~"),
    };
    shown.sort_by(|a, b| {
        let left = (
            -(number(a, "input") + number(a, "output")),
            -or_zero(a.get("lifetime").unwrap_or(&Value::Null)),
        );
        let right = (
            -(number(b, "input") + number(b, "output")),
            -or_zero(b.get("lifetime").unwrap_or(&Value::Null)),
        );
        left.partial_cmp(&right)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| order_key(a).cmp(&order_key(b)))
    });
    let mut total = blank(numbers());
    let mut lifetime_total = Value::Null;
    for project in &shown {
        for name in NUMBERS {
            let sum = add(
                total.get(name).unwrap_or(&Value::Null),
                project.get(name).unwrap_or(&Value::Null),
            )?;
            total.insert(Str::new(name), sum);
        }
        let own = project.get("lifetime").cloned().unwrap_or(Value::Null);
        if !matches!(own, Value::Null) {
            let base = if pyval::truthy(&lifetime_total) {
                lifetime_total
            } else {
                int(0)
            };
            lifetime_total = add(&base, &own)?;
        }
    }
    total.insert(Str::new("lifetime"), lifetime_total);
    let more = shown.len().saturating_sub(PROJECTS_LIMIT);
    shown.truncate(PROJECTS_LIMIT);
    let found = blank(vec![
        ("route", text(way)),
        ("measured", measured),
        (
            "projects",
            Value::Array(shown.into_iter().map(Value::Object).collect()),
        ),
        ("more", int(more as i64)),
        ("total", Value::Object(total)),
    ]);
    Ok((found, homes))
}

/// `_paces(runtime, now)`: each five-hour and weekly window the meter last read, with its pace.
fn paces(runtime: &Runtime, now: f64) -> Result<Vec<Value>> {
    let read = (|| -> Result<_> {
        let rows = state(runtime, "meter")?.meter()?;
        let samples =
            state(runtime, "usage_samples")?.usage_samples(&Value::Float(now - 3600.0))?;
        Ok((rows, samples))
    })();
    let Ok((rows, samples)) = read else {
        return Ok(Vec::new());
    };
    let samples: Vec<Value> = samples.into_iter().map(Value::Object).collect();
    let mut found = Vec::new();
    for (_, row) in rows {
        let minutes = get(&row, "minutes");
        if !WINDOWS
            .iter()
            .any(|window| pyval::eq(&minutes, &int(*window)))
        {
            continue;
        }
        found.push(
            pace(&samples, &Value::Object(row), now)
                .map_err(|class| Error::python(class, "pace"))?,
        );
    }
    found.sort_by(|a, b| {
        let minutes =
            |item: &Value| super::resets::number_of(&field(item, "minutes")).unwrap_or(0.0);
        let bucket = |item: &Value| match field(item, "bucket") {
            Value::Str(text) => text,
            _ => Str::new(""),
        };
        minutes(a)
            .partial_cmp(&minutes(b))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| bucket(a).cmp(&bucket(b)))
    });
    Ok(found)
}

/// `_behind(runtime, homes, now)`: whether more is left to read than one pass reads.
fn behind(runtime: &Runtime, homes: &[String], now: f64) -> bool {
    let read = || -> Option<bool> {
        let known = state(runtime, "token_files").ok()?.token_files().ok()?;
        let rollouts =
            tokens::rollouts(&car_codex::system::PolicyOs, homes, now, tokens::KEEP_DAYS).ok()?;
        let mut left: i64 = 0;
        for rollout in rollouts {
            let row = known
                .get(rollout.key.as_str())
                .cloned()
                .unwrap_or(Value::Null);
            let offset =
                if matches!(row, Value::Object(_)) && pyval::truthy(&field(&row, "thread_id")) {
                    match field(&row, "offset") {
                        Value::Int(offset) => offset.as_i64()?,
                        _ => return None,
                    }
                } else {
                    0
                };
            left += rollout.size - offset;
            if left > tokens::PASS_BYTES {
                return Some(true);
            }
        }
        Some(false)
    };
    read().unwrap_or(false)
}

/// `view(runtime, days=None)`: advanced-analytics.
pub fn view(runtime: &Runtime, days: &Value) -> Result<Value> {
    let Some(days) = days_of(runtime, days) else {
        return Ok(refusal(Refusal::InvalidRequest));
    };
    if !standing(runtime, CAPABILITY) {
        return Ok(refusal(Refusal::NotOn));
    }
    let now = runtime.now();
    let read = (|| -> Result<_> {
        let found = aggregate(runtime, days, now)?;
        let last = state(runtime, "stamped")?
            .stamped(&text(CAPABILITY), &text(OptionKey::LastIngest.as_str()))?;
        Ok((found, last))
    })();
    let Ok(((mut found, homes), last)) = read else {
        return Ok(refusal(Refusal::StateUnavailable));
    };
    let per_day =
        matches!(found.get("route"), Some(Value::Str(way)) if way.as_str() == Some("per_day"));
    found.insert(Str::new("done"), Value::Bool(true));
    found.insert(Str::new("refusal"), Value::Null);
    found.insert(Str::new("days"), int(days));
    found.insert(
        Str::new("choices"),
        Value::Array(DAYS.iter().map(|days| int(*days)).collect()),
    );
    found.insert(Str::new("paces"), Value::Array(paces(runtime, now)?));
    found.insert(Str::new("last_ingest"), last);
    found.insert(
        Str::new("behind"),
        Value::Bool(per_day && behind(runtime, &homes, now)),
    );
    Ok(Value::Object(found))
}

// ------------------------------------------------------------------ the CSV

/// `_cell(label)`.
fn cell(label: &Value) -> String {
    let text = match label {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    };
    if text.starts_with(FORMULA) {
        format!("'{text}")
    } else {
        text
    }
}

/// One CSV field as it is written (a number's `str`, a text as it is).
enum Field {
    Text(String),
    Number(Value),
}

/// `rows_of(runtime, days, now=)`: the CSV's rows after its header.
fn rows_of(runtime: &Runtime, days: i64) -> Result<Vec<Vec<Field>>> {
    let now = runtime.now();
    let (found, _) = aggregate(runtime, days, now)?;
    let projects = match found.get("projects") {
        Some(Value::Array(items)) => items.clone(),
        _ => Vec::new(),
    };
    let label_of = |key: &Value| -> Value {
        projects
            .iter()
            .rev()
            .find(|project| {
                let own = field(project, "key");
                pyval::eq(&own, key) && same_kind(&own, key)
            })
            .map(|project| field(project, "label"))
            .unwrap_or(Value::Null)
    };
    let mut per_day: Vec<((Value, Value), Map)> = Vec::new();
    if matches!(found.get("route"), Some(Value::Str(way)) if way.as_str() == Some("per_day")) {
        let first = first_day(&car_platform::localclock::Crt, now, days)?;
        for row in state(runtime, "token_days")?.token_days(&text(&first))? {
            let key = (get(&row, "day"), get(&row, "project_digest"));
            let at = match per_day.iter().position(|((day, digest), _)| {
                pyval::eq(day, &key.0) && pyval::eq(digest, &key.1) && same_kind(digest, &key.1)
            }) {
                Some(at) => at,
                None => {
                    per_day.push((key.clone(), blank(numbers())));
                    per_day.len() - 1
                }
            };
            for name in NUMBERS {
                let numbers = &mut per_day[at].1;
                let sum = add(numbers.get(name).unwrap_or(&Value::Null), &get(&row, name))?;
                numbers.insert(Str::new(name), sum);
            }
        }
    }
    let text_key = |value: &Value| match value {
        Value::Str(text) if !text.is_empty() => text.clone(),
        Value::Str(text) => text.clone(),
        _ => Str::new("~"),
    };
    per_day.sort_by(|((day_a, key_a), _), ((day_b, key_b), _)| {
        text_key(day_a).cmp(&text_key(day_b)).then_with(|| {
            let a = if pyval::truthy(key_a) {
                text_key(key_a)
            } else {
                Str::new("~")
            };
            let b = if pyval::truthy(key_b) {
                text_key(key_b)
            } else {
                Str::new("~")
            };
            a.cmp(&b)
        })
    });
    let mut lines = Vec::new();
    for ((day, key), numbers) in &per_day {
        let mut line = vec![
            Field::Number(day.clone()),
            Field::Text(cell(&label_of(key))),
        ];
        for name in NUMBERS {
            line.push(Field::Number(
                numbers.get(name).cloned().unwrap_or(Value::Null),
            ));
        }
        line.push(Field::Text(String::new()));
        lines.push(line);
    }
    for project in &projects {
        let own = field(project, "lifetime");
        if !matches!(own, Value::Null) {
            let mut line = vec![
                Field::Text(String::new()),
                Field::Text(cell(&field(project, "label"))),
            ];
            for _ in NUMBERS {
                line.push(Field::Text(String::new()));
            }
            line.push(Field::Number(own));
            lines.push(line);
        }
    }
    Ok(lines)
}

/// `str(value)` of what a CSV row carries.
fn str_of(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        Value::Int(number) => number.to_string(),
        Value::Float(number) => car_machine::pytext::float_repr(*number),
        Value::Bool(true) => "True".to_owned(),
        Value::Bool(false) => "False".to_owned(),
        Value::Null => String::new(),
        _ => String::new(),
    }
}

/// `csv.writer(lineterminator="\r\n").writerow(row)`'s line, QUOTE_MINIMAL.
fn csv_line(fields: &[String]) -> String {
    let mut line = String::new();
    for (at, value) in fields.iter().enumerate() {
        if at > 0 {
            line.push(',');
        }
        let quote =
            value.contains([',', '"', '\r', '\n']) || (fields.len() == 1 && value.is_empty());
        if quote {
            line.push('"');
            line.push_str(&value.replace('"', "\"\""));
            line.push('"');
        } else {
            line.push_str(value);
        }
    }
    line.push_str("\r\n");
    line
}

/// `save_csv(runtime, argument)`: advanced-analytics-csv.
pub fn save_csv(runtime: &Runtime, argument: &Map) -> Result<Value> {
    let days = days_of(runtime, argument.get("days").unwrap_or(&Value::Null));
    let path = argument.get("path").cloned().unwrap_or(Value::Null);
    let replace = argument
        .get("replace")
        .cloned()
        .unwrap_or(Value::Bool(false));
    let (Some(days), Value::Bool(replace)) = (days, replace) else {
        return Ok(refusal(Refusal::InvalidRequest));
    };
    let save_failed = || {
        object(vec![
            ("done", Value::Bool(false)),
            ("refusal", text(ReportRefusal::SaveFailed.as_str())),
        ])
    };
    let path = match &path {
        Value::Str(text) => text.as_str().map(str::to_owned),
        _ => None,
    };
    let Some(path) = path.filter(|path| {
        !path.is_empty() && !path.contains('\0') && std::path::Path::new(path).is_absolute()
    }) else {
        return Ok(save_failed());
    };
    if !standing(runtime, CAPABILITY) {
        return Ok(refusal(Refusal::NotOn));
    }
    let Ok(lines) = rows_of(runtime, days) else {
        return Ok(refusal(Refusal::StateUnavailable));
    };
    let mut written = String::from("\u{feff}");
    written.push_str(&csv_line(
        &COLUMNS
            .iter()
            .map(|name| (*name).to_owned())
            .collect::<Vec<_>>(),
    ));
    for line in &lines {
        let fields: Vec<String> = line
            .iter()
            .map(|field| match field {
                Field::Text(text) => text.clone(),
                Field::Number(value) => str_of(value),
            })
            .collect();
        written.push_str(&csv_line(&fields));
    }
    let mut options = std::fs::OpenOptions::new();
    options.write(true);
    if replace {
        options.create(true).truncate(true);
    } else {
        options.create_new(true);
    }
    let outcome = options
        .open(&path)
        .and_then(|mut handle| std::io::Write::write_all(&mut handle, written.as_bytes()));
    match outcome {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            return Ok(object(vec![
                ("done", Value::Bool(false)),
                ("refusal", text(ReportRefusal::FileExists.as_str())),
            ]));
        }
        Err(_) => return Ok(save_failed()),
    }
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("rows", Value::Int(Int::from(lines.len() as i64))),
    ]))
}
