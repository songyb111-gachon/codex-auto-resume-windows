//! `control/records.py`: one record as every interface shows it, and the three listings built from it - Pending,
//! History, the timeline and the statistics. `describe_record` is the wire shape the window, the panel and the
//! command line all read, held to the byte by `tests/golden/`.

use std::collections::BTreeSet;

use car_codex::LocalSource;
use car_machine::domain::public;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_policy::classify::gates::{GATES, decode_gates, would_send_at};
use car_policy::settings::homes;
use car_store::Store;
use car_store::value::{Row, get, number, text_of};

use crate::error::{MAX_BUDGET_RESETS, Res, interruption_id, refuse};
use crate::layer::{Control, from_store};
use crate::oncewords::OnceWords;
use crate::status::other_class;

/// `_REASON_UNCHANGED`: the journal entries that change a schedule or a flag and never the record's stored reason.
const REASON_UNCHANGED: &[&str] = &[
    "retry_now",
    "cancel_requested",
    "would_send",
    "rescan_rechecked",
    "rescan_unresolved",
    "rescan_changed",
];

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

fn held(row: &Row, name: &str) -> Value {
    get(row, name).clone()
}

/// `receipts(rows)`: what delivery showed of each continuation of one chain, oldest first.
pub fn receipts(rows: &[Row]) -> Vec<Value> {
    let mut sorted: Vec<&Row> = rows.iter().collect();
    sorted.sort_by(|a, b| {
        let at = |row: &Row| number(get(row, "detected_at")).unwrap_or(0.0);
        at(a)
            .partial_cmp(&at(b))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                text_of(a, "interruption_id")
                    .unwrap_or_default()
                    .cmp(text_of(b, "interruption_id").unwrap_or_default())
            })
    });
    let mut found = Vec::new();
    for row in sorted {
        let id = held(row, "interruption_id");
        let with = |kind: &str, at: Value| {
            object(vec![
                ("interruption_id", id.clone()),
                ("kind", Value::from(kind)),
                ("at", at),
            ])
        };
        if pyval::truthy(get(row, "recovery_turn_id")) && pyval::truthy(get(row, "turn_started_at"))
        {
            found.push(with("seen", held(row, "turn_started_at")));
        } else if text_of(row, "state") == Some("submission_unknown") {
            let at = if pyval::truthy(get(row, "submitted_at")) {
                held(row, "submitted_at")
            } else {
                held(row, "last_claim_at")
            };
            found.push(with("uncertain", at));
        } else if pyval::truthy(get(row, "first_queued_at")) {
            found.push(with("queued", held(row, "first_queued_at")));
        }
    }
    found
}

/// `describe_record(row, enabled=, thread_enabled=, watcher=)`: one record as every interface shows it.
pub fn describe_record(
    row: &Row,
    enabled: &Value,
    thread_enabled: bool,
    watcher: &Value,
) -> Res<Map> {
    let record = Value::Object(row.clone());
    let described = public::describe(&record, enabled, &Value::Bool(thread_enabled), watcher)
        .map_err(other_class)?;
    let Value::Object(described) = described else {
        unreachable!("describe answers an object")
    };
    let part = |name: &str| described.get(name).cloned().unwrap_or(Value::Null);
    let gates = if pyval::truthy(get(row, "gate_eval")) {
        let vector = decode_gates(get(row, "gate_eval"));
        let mut map = Map::new();
        for name in GATES {
            let (result, reason) = vector.or_unknown(name);
            map.insert(
                Str::from(*name),
                Value::Array(vec![Value::from(result), Value::from(reason)]),
            );
        }
        Value::Object(map)
    } else {
        Value::Null
    };
    let resets = match get(row, "budget_resets") {
        Value::Int(int) => int.as_i64().unwrap_or(0),
        _ => 0,
    };
    let postponed = car_store::machine::own_postponement(row, None)
        .map_err(from_store)?
        .map_or(Value::Null, Value::Float);
    let mut out = Map::new();
    let mut put = |name: &str, value: Value| {
        out.insert(Str::from(name), value);
    };
    put("interruption_id", held(row, "interruption_id"));
    put("thread_id", held(row, "thread_id"));
    put("state", held(row, "state"));
    put("code", part("code"));
    put("reason", part("reason"));
    put("overlays", part("overlays"));
    put("eligible_at", part("eligible_at"));
    put("terminal", part("terminal"));
    put("category", held(row, "category"));
    put("detected_at", held(row, "detected_at"));
    put("reset_at", held(row, "reset_at"));
    put("next_retry_at", held(row, "next_retry_at"));
    put("recovery_attempts", held(row, "recovery_attempts"));
    put("no_progress_count", held(row, "no_progress_count"));
    put("chain_continuations", held(row, "chain_continuations"));
    put("chain_origin_id", held(row, "chain_origin_id"));
    put(
        "parent_interruption_id",
        held(row, "parent_interruption_id"),
    );
    put("budget_resets", held(row, "budget_resets"));
    put(
        "budget_resets_left",
        Value::from((MAX_BUDGET_RESETS - resets).max(0)),
    );
    put(
        "cancel_requested",
        Value::Bool(pyval::truthy(get(row, "cancel_requested"))),
    );
    put("recovery_turn_status", held(row, "recovery_turn_status"));
    put(
        "user_joined",
        Value::Bool(pyval::truthy(get(row, "user_joined"))),
    );
    put(
        "after_user_work",
        Value::Bool(pyval::truthy(get(row, "after_user_work"))),
    );
    put("outcome_at", held(row, "outcome_at"));
    put("first_queued_at", held(row, "first_queued_at"));
    put("gates", gates);
    put("gates_at", held(row, "gate_eval_at"));
    put("not_before", held(row, "not_before"));
    put("postponed_until", postponed);
    put("hold", held(row, "hold"));
    put("would_send_at", would_send_at(row));
    put("context_tokens", held(row, "context_tokens"));
    Ok(out)
}

/// `_other_homes(configured)`: home_key -> (alias, folder) for each Codex home Settings add.
fn other_homes(control: &Control, configured: &Value) -> Vec<(String, (Value, Str))> {
    let os = control.host.os();
    let configured = if pyval::truthy(configured) {
        configured.clone()
    } else {
        Value::Array(Vec::new())
    };
    let Value::Array(entries) = homes::coerce(&*os, &configured, &Value::Array(Vec::new())) else {
        return Vec::new();
    };
    let mut found: Vec<(String, (Value, Str))> = Vec::new();
    for entry in entries {
        let Value::Object(map) = &entry else { continue };
        let (Some(Value::Str(path)), Some(alias)) = (map.get("path"), map.get("alias")) else {
            continue;
        };
        let Ok(key) = homes::key(&*os, path) else {
            continue;
        };
        found.retain(|(each, _)| *each != key);
        found.push((key, (alias.clone(), path.clone())));
    }
    found
}

/// `_usage_check(check, row)`: a row's usage check, with whether the recovery has been continued since it lifted the
/// reset.
fn usage_check(check: Option<&Value>, row: &Row) -> Value {
    let Some(Value::Object(check)) = check else {
        return Value::Null;
    };
    if check.is_empty() {
        return Value::Null;
    }
    let sent = match get(row, "submitted_at") {
        Value::Float(x) => Some(*x),
        Value::Int(int) => int.as_i64().map(|each| each as f64),
        _ => None,
    };
    let at = match check.get("at") {
        Some(Value::Float(x)) => *x,
        Some(Value::Int(int)) => int.as_i64().unwrap_or(0) as f64,
        _ => 0.0,
    };
    let lifted = check.get("lifted").is_some_and(pyval::truthy);
    let continued = lifted && sent.is_some_and(|sent| sent >= at);
    let mut merged = check.clone();
    merged.insert(Str::from("continued"), Value::Bool(continued));
    Value::Object(merged)
}

impl Control {
    /// `_described(store, rows, source)`.
    fn described(
        &self,
        store: &Store,
        state: &crate::layer::State,
        rows: Vec<Row>,
        source: Option<&LocalSource>,
    ) -> Res<Vec<Value>> {
        let settings_row = store.settings().map_err(from_store)?;
        let disabled: BTreeSet<String> = store
            .disabled_threads()
            .map_err(from_store)?
            .into_iter()
            .filter_map(|each| match each {
                Value::Str(text) => text.as_str().map(str::to_owned),
                _ => None,
            })
            .collect();
        let tiers = store.thread_tiers().map_err(from_store)?;
        let watcher = self.watcher(state)?;
        let values = self.get_settings()?;
        let attempts = values
            .get("max_recovery_attempts")
            .cloned()
            .unwrap_or(Value::Null);
        let others = other_homes(self, values.get(homes::FIELD).unwrap_or(&Value::Null));
        let mut readers: Vec<(Str, Option<LocalSource>)> = Vec::new();
        let worded: Vec<String> = OnceWords::of(&self.paths.once_words_file, &*self.host)
            .held()
            .map(|entries| entries.into_iter().map(|(key, _)| key).collect())
            .unwrap_or_default();
        let checked = store
            .usage_checks_shown(self.host.now() - 86400.0)
            .unwrap_or_default();
        let enabled = get(&settings_row, "enabled").clone();
        let mut listed = Vec::new();
        for row in rows {
            let thread = text_of(&row, "thread_id").unwrap_or_default().to_owned();
            let wanted = text_of(&row, "home_key").unwrap_or_default();
            let home = others
                .iter()
                .find(|(key, _)| key == wanted)
                .map(|(_, found)| found.clone());
            let mut identity = Map::new();
            let mut reader: Option<&LocalSource> = source;
            if let (Some((_, path)), Some(base)) = (&home, source) {
                let at = readers.iter().position(|(each, _)| each == path);
                let at = match at {
                    Some(at) => at,
                    None => {
                        let made = path.as_str().and_then(|text| base.elsewhere(text).ok());
                        readers.push((path.clone(), made));
                        readers.len() - 1
                    }
                };
                reader = readers[at].1.as_ref();
            }
            if let Some(reader) = reader
                && let Ok(found) = reader.identity(&thread)
            {
                identity = found;
            }
            let thread_enabled = !disabled.contains(&thread);
            let mut item = describe_record(&row, &enabled, thread_enabled, &watcher)?;
            let said = |name: &str| identity.get(name).cloned().unwrap_or(Value::Null);
            let key = text_of(&row, "interruption_id").unwrap_or_default();
            item.insert(Str::from("thread_enabled"), Value::Bool(thread_enabled));
            item.insert(
                Str::from("tier"),
                tiers.get(thread.as_str()).cloned().unwrap_or(Value::Null),
            );
            item.insert(
                Str::from("attempt_limit"),
                if text_of(&row, "category") == Some("usage_limit") {
                    Value::Null
                } else {
                    attempts.clone()
                },
            );
            item.insert(Str::from("name"), said("name"));
            item.insert(Str::from("project"), said("project"));
            item.insert(Str::from("cwd_basename"), said("cwd_basename"));
            item.insert(
                Str::from("home"),
                home.as_ref()
                    .map_or(Value::Null, |(alias, _)| alias.clone()),
            );
            item.insert(
                Str::from("once_words"),
                Value::Bool(worded.iter().any(|each| each == key)),
            );
            item.insert(
                Str::from("usage_check"),
                usage_check(checked.get(key), &row),
            );
            listed.push(Value::Object(item));
        }
        Ok(listed)
    }

    /// `_labels()`: display names for conversations, read-only from Codex's own state, or None.
    pub fn labels(&self) -> Option<LocalSource> {
        LocalSource::new(self.host.os(), &self.host.codex_home(), None).ok()
    }

    /// `list_pending(include_terminal=False, source=None)`.
    pub fn list_pending(
        &self,
        include_terminal: bool,
        source: Option<&LocalSource>,
    ) -> Res<Vec<Value>> {
        let state = self.open(false)?;
        let crate::layer::State::Current(store) = &state else {
            return refuse(car_store::open::UPGRADE_PENDING, "upgrade_pending");
        };
        let rows = if include_terminal {
            store.all_records()
        } else {
            store.pending()
        }
        .map_err(from_store)?;
        self.described(store, &state, rows, source)
    }

    /// `history(limit=200, include_hidden=False, source=None)`: recent recoveries, newest first.
    pub fn history(&self, source: Option<&LocalSource>) -> Res<Vec<Value>> {
        let state = self.open(false)?;
        let crate::layer::State::Current(store) = &state else {
            return refuse(car_store::open::UPGRADE_PENDING, "upgrade_pending");
        };
        let rows = store.history(false, 200).map_err(from_store)?;
        self.described(store, &state, rows, source)
    }

    /// `timeline(interruption_id)`: the content-free journal of one recovery's whole chain, oldest first.
    pub fn timeline(&self, id: &Value) -> Res<Value> {
        let key = interruption_id(id)?;
        let store = self.open_current()?;
        let Some(record) = store.get(&key).map_err(from_store)? else {
            return refuse("no such interruption", "no_such_interruption");
        };
        let origin = text_of(&record, "chain_origin_id")
            .unwrap_or_default()
            .to_owned();
        let mut events = store.events(None, Some(&origin), 500).map_err(from_store)?;
        let chain: Vec<Row> = store
            .all_records()
            .map_err(from_store)?
            .into_iter()
            .filter(|row| text_of(row, "chain_origin_id") == Some(origin.as_str()))
            .collect();
        drop(store);
        let mut previous: Vec<(Value, Value)> = Vec::new();
        for event in &mut events {
            let to_state = held(event, "to_state");
            let owner = held(event, "interruption_id");
            let code = if pyval::truthy(&to_state)
                && pyval::eq(&held(event, "from_state"), &to_state)
                && text_of(event, "code").is_some_and(|word| REASON_UNCHANGED.contains(&word))
                && previous.iter().any(|(each, _)| pyval::eq(each, &owner))
            {
                previous
                    .iter()
                    .find(|(each, _)| pyval::eq(each, &owner))
                    .map(|(_, code)| code.clone())
                    .unwrap_or(Value::Null)
            } else if pyval::truthy(&to_state) {
                let mut probe = Map::new();
                probe.insert(Str::from("state"), to_state.clone());
                probe.insert(Str::from("last_error"), held(event, "reason"));
                Value::from(public::public_code(&Value::Object(probe)).map_err(other_class)?)
            } else {
                Value::Null
            };
            event.insert(Str::from("to_code"), code.clone());
            if !matches!(code, Value::Null) {
                previous.retain(|(each, _)| !pyval::eq(each, &owner));
                previous.push((owner, code));
            }
        }
        Ok(object(vec![
            ("interruption_id", Value::from(key)),
            ("chain_origin_id", Value::from(origin)),
            (
                "events",
                Value::Array(events.into_iter().map(Value::Object).collect()),
            ),
            ("receipts", Value::Array(receipts(&chain))),
        ]))
    }

    /// `statistics(days=None)`.
    pub fn statistics(&self, days: Option<&Value>) -> Res<Value> {
        let seconds = match days {
            Some(Value::Float(x)) if *x != 0.0 => Some(*x),
            Some(Value::Int(int)) if int.as_i64() != Some(0) => Some(
                int.as_i64()
                    .map(|each| each as f64)
                    .unwrap_or_else(|| int.to_string().parse().unwrap_or(f64::INFINITY)),
            ),
            _ => None,
        };
        let since = match seconds {
            None => 0.0,
            Some(days) => (self.host.now() - days * 86400.0).max(0.0),
        };
        let store = self.open_current()?;
        let mut result = store.statistics(since, None).map_err(from_store)?;
        result.insert(
            Str::from("period_days"),
            days.cloned().unwrap_or(Value::Null),
        );
        Ok(Value::Object(result))
    }
}
