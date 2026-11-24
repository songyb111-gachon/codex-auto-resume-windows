//! `demo.py`: Show me what happens (v0.6.11) - a recovery played out with made-up words, and nothing sent.
//!
//! Everything here is made up and held in memory: an obviously fake conversation and interruption, a usage limit
//! that "resets" in a minute. It reads no state and knows no engine; a row it returns carries `demo: true`.

use car_machine::domain::public;
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::to_float;
use car_machine::pyval::Py;

use super::vocab_gen::demo as words;

pub const DEMO_SECONDS: i64 = 60;
pub const DEMO_THREAD: &str = words::DEMO_THREAD;
pub const DEMO_KEY: &str = words::DEMO_KEY;
pub const CATEGORY: &str = words::CATEGORY;

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

/// `detail(now)`: the made-up interruption a demo card is built from.
pub fn detail(now: &Value) -> Py<Value> {
    let now = to_float(now)?;
    Ok(object(vec![
        ("thread_id", Value::from(DEMO_THREAD)),
        ("interruption_id", Value::from(DEMO_KEY)),
        ("category", Value::from(CATEGORY)),
        ("reset_at", Value::Float(now + DEMO_SECONDS as f64)),
    ]))
}

/// `_row(record)`: one made-up record as a list row, in the keys a Pending or History row has.
fn row(record: &Value) -> Py<Value> {
    let on = Value::Bool(true);
    let described = public::describe(record, &on, &on, &Value::Null)?;
    let take = |key: &str| match record {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let said = |key: &str| match &described {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let none = || Value::Null;
    Ok(object(vec![
        ("interruption_id", Value::from(DEMO_KEY)),
        ("thread_id", Value::from(DEMO_THREAD)),
        ("state", take("state")),
        ("code", said("code")),
        ("reason", said("reason")),
        ("overlays", said("overlays")),
        ("eligible_at", said("eligible_at")),
        ("terminal", said("terminal")),
        ("category", Value::from(CATEGORY)),
        ("detected_at", take("detected_at")),
        ("reset_at", take("reset_at")),
        ("next_retry_at", take("next_retry_at")),
        ("recovery_attempts", Value::from(0)),
        ("no_progress_count", Value::from(0)),
        ("chain_continuations", Value::from(0)),
        ("chain_origin_id", Value::from(DEMO_KEY)),
        ("parent_interruption_id", none()),
        ("budget_resets", Value::from(0)),
        ("budget_resets_left", Value::from(0)),
        ("cancel_requested", Value::Bool(false)),
        ("recovery_turn_status", none()),
        ("user_joined", Value::Bool(false)),
        ("after_user_work", Value::Bool(false)),
        ("outcome_at", take("outcome_at")),
        ("first_queued_at", none()),
        ("gates", none()),
        ("gates_at", none()),
        ("not_before", none()),
        ("postponed_until", none()),
        ("hold", none()),
        ("would_send_at", none()),
        ("context_tokens", none()),
        ("thread_enabled", Value::Bool(true)),
        ("tier", none()),
        ("attempt_limit", none()),
        ("name", none()),
        ("project", none()),
        ("cwd_basename", none()),
        ("home", none()),
        ("once_words", Value::Bool(false)),
        ("usage_check", none()),
        ("demo", Value::Bool(true)),
    ]))
}

/// `rows(now)`: the demo as the Dashboard plays it - its countdown, the made-up task on Pending, and the entry History
/// shows once the countdown has run out. A pure function of `now`.
pub fn rows(now: &Value) -> Py<Value> {
    let now = to_float(now)?;
    let due = now + DEMO_SECONDS as f64;
    let mut waiting = Map::new();
    waiting.insert(Str::from("state"), Value::from("waiting_reset"));
    waiting.insert(Str::from("detected_at"), Value::Float(now));
    waiting.insert(Str::from("reset_at"), Value::Float(due));
    waiting.insert(Str::from("next_retry_at"), Value::Float(due));
    let mut finished = waiting.clone();
    finished.insert(Str::from("state"), Value::from("recovered"));
    finished.insert(Str::from("outcome_at"), Value::Float(due));
    Ok(object(vec![
        ("seconds", Value::from(DEMO_SECONDS)),
        ("pending", row(&Value::Object(waiting))?),
        ("history", row(&Value::Object(finished))?),
    ]))
}
