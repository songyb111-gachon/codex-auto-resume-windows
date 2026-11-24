//! The watcher's heartbeat, and what it says about itself (store/watcher.py); the needs-you notices
//! (store/notices.py); counts and the last seven days (store/reporting.py).

use car_machine::json::{Map, Options, Str, Value, from_str, to_string};

use crate::errors::{Error, Result};
use crate::journal::finite_value;
use crate::machine::vocab::{ENGINE_STATES, HOME_STATES, STATES, TERMINAL, WATCHER_ENDS};
use crate::machine::{epoch_store, has, usage};
use crate::seam::KEEP_SECONDS;
use crate::session::Store;
use crate::validate::{is_home_key, now as check_now, short_text, validated_notice};
use crate::value::{
    Row, execute, float_or_null, get, int, is_in, key, number, rows, string, text, truthy, tuples,
};

/// v0.6.15-beta: the Codex homes a watcher is set to watch - the default and up to three more.
pub const MAX_HOMES: usize = 4;

/// The heartbeat's fields (`heartbeat`'s keywords).
#[derive(Clone, Debug)]
pub struct Beat {
    pub pid: i64,
    pub session_id: String,
    pub started_at: Value,
    pub ok: bool,
    pub engine_state: String,
    pub code_version: String,
    /// (time, windows) of the last usage reading, or None.
    pub usage: Option<(Value, Value)>,
    pub awake_since: Value,
    pub memory_peak: Value,
    pub sign_in: Value,
    pub booted_at: Value,
    pub homes: Value,
}

fn bytes(value: &Value) -> Value {
    match value {
        Value::Int(number) if number.as_i64().is_some_and(|n| (0..1 << 53).contains(&n)) => {
            value.clone()
        }
        _ => Value::Null,
    }
}

fn sign_in(value: &Value) -> Value {
    match text(value) {
        Some(found)
            if found.len() == 16
                && found
                    .bytes()
                    .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')) =>
        {
            value.clone()
        }
        _ => Value::Null,
    }
}

/// `homes_text(homes)`: compact JSON of 2 to 4 {key, state}, or None.
pub fn homes_text(homes: &Value) -> Option<String> {
    let Value::Array(homes) = homes else {
        return None;
    };
    if !(2..=MAX_HOMES).contains(&homes.len()) {
        return None;
    }
    let mut kept = Vec::new();
    let mut keys = Vec::new();
    for home in homes {
        let Value::Object(home) = home else {
            return None;
        };
        if home.len() != 2 || !home.contains_key("key") || !home.contains_key("state") {
            return None;
        }
        let (found, state) = (&home["key"], &home["state"]);
        if !is_home_key(found) || !is_in(state, HOME_STATES) {
            return None;
        }
        let mut entry = Map::new();
        entry.insert(Str::new("key"), found.clone());
        entry.insert(Str::new("state"), state.clone());
        keys.push(text(found).unwrap_or_default().to_string());
        kept.push(Value::Object(entry));
    }
    let mut unique = keys.clone();
    unique.sort();
    unique.dedup();
    if unique.len() != keys.len() {
        return None;
    }
    to_string(&Value::Array(kept), &Options::new().separators(",", ":")).ok()
}

/// `homes_read(text)`.
pub fn homes_read(stored: &Value) -> Value {
    let Some(stored) = text(stored).filter(|stored| stored.chars().count() <= 2000) else {
        return Value::Null;
    };
    let Ok(value) = crate::seam::python::loads(stored) else {
        return Value::Null;
    };
    match homes_text(&value) {
        Some(again) => from_str(&again).unwrap_or(Value::Null),
        None => Value::Null,
    }
}

/// `_reading(usage)`: (time, stored text) for a reading worth keeping.
fn reading(found: &Option<(Value, Value)>) -> Result<Option<(f64, String)>> {
    let Some((at, windows)) = found else {
        return Ok(None);
    };
    let Some(stored) = usage::encode(windows)? else {
        return Ok(None);
    };
    if !epoch_store(at)? {
        return Ok(None);
    }
    Ok(Some((number(at).expect("a time"), stored)))
}

impl Store {
    /// `heartbeat(now, ...)`: the watcher's proof of life, written every tick.
    pub fn heartbeat(&self, now: f64, beat: &Beat) -> Result<()> {
        check_now(now)?;
        let state = if has(ENGINE_STATES, &beat.engine_state) {
            beat.engine_state.as_str()
        } else {
            "unknown"
        };
        let read = reading(&beat.usage)?;
        let awake = if epoch_store(&beat.awake_since)? {
            float_or_null(number(&beat.awake_since))
        } else {
            Value::Null
        };
        let booted = if epoch_store(&beat.booted_at)? {
            float_or_null(number(&beat.booted_at))
        } else {
            Value::Null
        };
        let session: String = beat.session_id.chars().take(64).collect();
        let session = string(&session);
        short_text(&session, "session_id", 64, false)?;
        let version: String = beat.code_version.chars().take(32).collect();
        let version = string(&version);
        short_text(&version, "code_version", 32, false)?;
        self.transaction(|connection| {
            execute(
                connection,
                "INSERT INTO watcher_status (singleton, pid, session_id, started_at, last_tick_at, last_tick_ok, engine_state, code_version, awake_since, memory_peak, end_mark, ended_at, sign_in, booted_at, homes) VALUES (1,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?) ON CONFLICT(singleton) DO UPDATE SET pid=excluded.pid, session_id=excluded.session_id, started_at=excluded.started_at, last_tick_at=excluded.last_tick_at, last_tick_ok=excluded.last_tick_ok, engine_state=excluded.engine_state, code_version=excluded.code_version, awake_since=excluded.awake_since, memory_peak=excluded.memory_peak, end_mark=excluded.end_mark, ended_at=NULL, sign_in=excluded.sign_in, booted_at=excluded.booted_at, homes=excluded.homes",
                &[
                    int(beat.pid),
                    session.clone(),
                    float_or_null(finite_value(&beat.started_at, None)),
                    Value::Float(now),
                    int(i64::from(beat.ok)),
                    string(state),
                    version.clone(),
                    awake.clone(),
                    bytes(&beat.memory_peak),
                    string("running"),
                    sign_in(&beat.sign_in),
                    booted.clone(),
                    crate::value::optional(homes_text(&beat.homes).as_deref()),
                ],
            )?;
            if let Some((at, stored)) = &read {
                execute(
                    connection,
                    "UPDATE watcher_status SET usage_at=?, usage=? WHERE singleton=1",
                    &[Value::Float(*at), string(stored)],
                )?;
            }
            Ok(())
        })
    }

    /// `watcher_ended(now, end)`: CLEAN or MEMORY_GUARD written over the heartbeat; whether it was.
    pub fn watcher_ended(&self, now: f64, end: &str) -> Result<bool> {
        check_now(now)?;
        if !matches!(end, "clean" | "memory_guard") {
            return Err(Error::Python(
                "ValueError",
                "not how a watcher ends on purpose".into(),
            ));
        }
        self.transaction(|connection| {
            let changed = execute(
                connection,
                "UPDATE watcher_status SET end_mark=?, ended_at=? WHERE singleton=1",
                &[string(end), Value::Float(now)],
            )?;
            Ok(changed == 1)
        })
    }

    /// `watcher_status()`: what the heartbeat says, or None.
    pub fn watcher_status(&self) -> Result<Option<Row>> {
        let found = self.read(|connection| {
            Ok(rows(
                connection,
                "SELECT * FROM watcher_status WHERE singleton=1",
                &[],
            )?)
        })?;
        let Some(row) = found.into_iter().next() else {
            return Ok(None);
        };
        let windows = usage::decode(get(&row, "usage"))?;
        let at = finite_value(get(&row, "usage_at"), None);
        let end = get(&row, "end_mark");
        let mut status = Row::new();
        let mut put = |name: &str, value: Value| {
            status.insert(key(name), value);
        };
        put(
            "pid",
            if matches!(get(&row, "pid"), Value::Int(_)) {
                get(&row, "pid").clone()
            } else {
                Value::Null
            },
        );
        put(
            "started_at",
            float_or_null(finite_value(get(&row, "started_at"), None)),
        );
        put(
            "last_tick_at",
            float_or_null(finite_value(get(&row, "last_tick_at"), None)),
        );
        put(
            "last_tick_ok",
            Value::Bool(truthy(get(&row, "last_tick_ok"))),
        );
        put(
            "engine_state",
            if is_in(get(&row, "engine_state"), ENGINE_STATES) {
                get(&row, "engine_state").clone()
            } else {
                string("unknown")
            },
        );
        put(
            "code_version",
            if matches!(get(&row, "code_version"), Value::Str(_)) {
                get(&row, "code_version").clone()
            } else {
                Value::Null
            },
        );
        put(
            "usage",
            match (windows, at) {
                (Some(windows), Some(at)) => {
                    let mut reading = Map::new();
                    reading.insert(Str::new("read_at"), Value::Float(at));
                    reading.insert(Str::new("windows"), Value::Array(windows));
                    Value::Object(reading)
                }
                _ => Value::Null,
            },
        );
        put(
            "awake_since",
            float_or_null(finite_value(get(&row, "awake_since"), None)),
        );
        put("memory_peak", bytes(get(&row, "memory_peak")));
        put(
            "end_mark",
            if is_in(end, WATCHER_ENDS) && text(end) != Some("unexpected") {
                end.clone()
            } else {
                Value::Null
            },
        );
        put(
            "ended_at",
            float_or_null(finite_value(get(&row, "ended_at"), None)),
        );
        put("sign_in", sign_in(get(&row, "sign_in")));
        put(
            "booted_at",
            float_or_null(finite_value(get(&row, "booted_at"), None)),
        );
        put("homes", homes_read(get(&row, "homes")));
        Ok(Some(status))
    }

    /// `raise_notice(key, thread_id, kind, now)`: True the first time, False after.
    pub fn raise_notice(
        &self,
        notice_key: &str,
        thread_id: &str,
        kind: &str,
        now: f64,
    ) -> Result<bool> {
        let mut row = Row::new();
        row.insert(key("interruption_id"), string(notice_key));
        row.insert(key("thread_id"), string(thread_id));
        row.insert(key("category"), string(kind));
        row.insert(key("raised_at"), Value::Float(now));
        row.insert(key("seen_at"), Value::Null);
        let row = validated_notice(row)?;
        self.transaction(|connection| {
            execute(connection, "DELETE FROM notices WHERE raised_at<?", &[Value::Float(now - KEEP_SECONDS)])?;
            let inserted = execute(
                connection,
                "INSERT OR IGNORE INTO notices (interruption_id, thread_id, category, raised_at, seen_at) VALUES (?,?,?,?,NULL)",
                &[get(&row, "interruption_id").clone(), get(&row, "thread_id").clone(), get(&row, "category").clone(), get(&row, "raised_at").clone()],
            )?;
            Ok(inserted == 1)
        })
    }

    /// `status_counts()`: records by state.
    pub fn status_counts(&self) -> Result<Row> {
        let found = self.read(|connection| {
            Ok(tuples(
                connection,
                "SELECT state, count(*) FROM interruptions GROUP BY state",
                &[],
            )?)
        })?;
        let mut counts = Row::new();
        for row in found {
            if let Value::Str(state) = &row[0]
                && is_in(&row[0], STATES)
            {
                counts.insert(state.clone(), row[1].clone());
            }
        }
        Ok(counts)
    }

    /// `statistics(since=0.0, until=None)`: exact, content-free counts over records detected in a period.
    pub fn statistics(&self, since: f64, until: Option<f64>) -> Result<Row> {
        let until = until.unwrap_or(f64::INFINITY);
        let found: Vec<Row> = self
            .all_records()?
            .into_iter()
            .filter(|row| {
                number(get(row, "detected_at")).is_some_and(|at| since <= at && at < until)
            })
            .collect();
        const OUTCOME: &[(&str, &str)] = &[
            ("recovered", "recovered"),
            ("completed_no_progress", "no_progress"),
            ("recovery_turn_failed", "recovery_failed"),
            ("outcome_unverified", "outcome_unverified"),
            ("handed_over", "handed_over"),
            ("stopped_by_user", "stopped_by_user"),
            ("cancelled", "cancelled"),
            ("superseded", "superseded"),
            ("superseded_by_user", "superseded"),
            ("retry_budget_exhausted", "exhausted"),
            ("no_progress_exhausted", "exhausted"),
            ("failed", "failed_terminal"),
            ("terminal_failure", "failed_terminal"),
            ("submission_unknown", "submission_unknown"),
            ("resumed", "delivered_legacy"),
        ];
        let mut names: Vec<&str> = OUTCOME.iter().map(|(_, bucket)| *bucket).collect();
        names.sort_unstable();
        names.dedup();
        let mut buckets: Vec<(&str, i64)> = names.iter().map(|name| (*name, 0)).collect();
        let mut by_category = Row::new();
        for row in &found {
            let state = text(get(row, "state")).unwrap_or_default();
            if let Some((_, bucket)) = OUTCOME.iter().find(|(from, _)| *from == state) {
                buckets
                    .iter_mut()
                    .find(|(name, _)| name == bucket)
                    .expect("named")
                    .1 += 1;
            }
            if let Value::Str(category) = get(row, "category") {
                let count = by_category
                    .get(category)
                    .and_then(|v| match v {
                        Value::Int(n) => n.as_i64(),
                        _ => None,
                    })
                    .unwrap_or(0);
                by_category.insert(category.clone(), int(count + 1));
            }
        }
        let group = |name: &str| match name {
            "recovered" | "superseded" | "delivered_legacy" => "success",
            "handed_over" | "stopped_by_user" | "cancelled" => "other",
            _ => "failure",
        };
        let succeeded: i64 = buckets
            .iter()
            .filter(|(name, _)| group(name) == "success")
            .map(|(_, n)| n)
            .sum();
        let denominator: i64 = buckets
            .iter()
            .filter(|(name, _)| group(name) != "other")
            .map(|(_, n)| n)
            .sum();
        let at = |row: &Row, name: &str| number(get(row, name));
        let waits: Vec<f64> = found
            .iter()
            .filter_map(
                |row| match (at(row, "first_queued_at"), at(row, "detected_at")) {
                    (Some(queued), Some(detected)) if queued >= detected => Some(queued - detected),
                    _ => None,
                },
            )
            .collect();
        let latencies: Vec<f64> = found
            .iter()
            .filter(|row| text(get(row, "state")) == Some("recovered"))
            .filter_map(
                |row| match (at(row, "outcome_at"), at(row, "first_queued_at")) {
                    (Some(outcome), Some(queued)) if outcome >= queued => Some(outcome - queued),
                    _ => None,
                },
            )
            .collect();
        let mut answer = Row::new();
        let mut put = |name: &str, value: Value| {
            answer.insert(key(name), value);
        };
        put("interruptions_detected", int(found.len() as i64));
        put(
            "continuations_submitted",
            int(found
                .iter()
                .filter(|row| !matches!(get(row, "first_queued_at"), Value::Null))
                .count() as i64),
        );
        put(
            "pending",
            int(found
                .iter()
                .filter(|row| !is_in(get(row, "state"), TERMINAL))
                .count() as i64),
        );
        let mut outcomes = Row::new();
        let mut groups = Row::new();
        for (name, count) in &buckets {
            outcomes.insert(key(name), int(*count));
            groups.insert(key(name), string(group(name)));
        }
        put("outcomes", Value::Object(outcomes));
        put("outcome_groups", Value::Object(groups));
        put(
            "success_rate",
            if denominator >= 5 {
                Value::Float(succeeded as f64 / denominator as f64)
            } else {
                Value::Null
            },
        );
        put("success_denominator", int(denominator));
        put("median_wait_seconds", float_or_null(median(waits)));
        put("median_recovery_seconds", float_or_null(median(latencies)));
        put("by_category", Value::Object(by_category));
        let retries: i64 = found
            .iter()
            .map(|row| match get(row, "retry_now_count") {
                Value::Int(n) => n.as_i64().unwrap_or(0),
                _ => 0,
            })
            .sum();
        put("retry_now_requests", int(retries));
        Ok(answer)
    }
}

/// `statistics.median`: the middle value, or the mean of the two middle ones.
fn median(mut values: Vec<f64>) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(|a, b| a.total_cmp(b));
    let n = values.len();
    Some(if n % 2 == 1 {
        values[n / 2]
    } else {
        (values[n / 2 - 1] + values[n / 2]) / 2.0
    })
}
