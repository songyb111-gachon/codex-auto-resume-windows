//! What core takes of a plug's answers (`domain/plughands.py`'s checks): the records of the plug's own core carries
//! out (P2), how many sends may wait at once (P12), a surface's fields (P10), the session kinds and the widening
//! (P18, P19), and how the tasks a person armed the power action for stand (P21, `Guarded.power`).
//!
//! Each takes an answer as a plug could give it - any value - and keeps only what core can carry out; anything else
//! is the standard edition's answer. A question Python answers with an exception answers with that exception's class.

use car_machine::domain::{ids, states};
use car_machine::json::{self, Map, Options, Str, Value};
use car_machine::pyval::{self, Num, Py};

use super::vocab_gen::domain_plughands as words;

/// How many records of the plug's own core takes in one tick (P2), at most.
pub const RECORDS_LIMIT: usize = 8;
/// P12: at most this many sends wait for their receipts at once.
pub const MAX_WORKERS: i64 = 8;
/// How long the words of a record may be, at most.
pub const WORDS_LIMIT: usize = 30000;
/// How many guards one errand may ask for in one tick.
pub const ERRAND_GUARDS: usize = 8;
/// P21: how many conversations its answer may name at most.
pub const POWER_THREADS: usize = 64;
pub const BASE_RECORD_KEYS: &[&str] = words::BASE_RECORD_KEYS;
pub const RECORD_KEYS: &[&str] = words::RECORD_KEYS;

/// `workers(answer)`: a whole number 2 to MAX_WORKERS as it is, and 1 for anything else.
pub fn workers(answer: Option<&Value>) -> i64 {
    match answer {
        Some(Value::Int(int)) => int
            .as_i64()
            .filter(|count| (2..=MAX_WORKERS).contains(count))
            .unwrap_or(1),
        _ => 1,
    }
}

/// `kinds_of` and `widening_of`: the closed words in a set or a tuple of them (`None` is any other answer), sorted;
/// the empty set for anything else.
pub fn words_of(answer: Option<&[Value]>, closed: &[&str]) -> Vec<String> {
    let Some(found) = answer else {
        return Vec::new();
    };
    if found.iter().any(|word| pyval::hashable(word).is_err()) {
        return Vec::new();
    }
    let mut kept: Vec<String> = Vec::new();
    for word in found {
        match pyval::text(word) {
            Some(text) if closed.contains(&text) => kept.push(text.to_owned()),
            _ => return Vec::new(),
        }
    }
    kept.sort();
    kept.dedup();
    kept
}

/// P18's words (`kinds_of`).
pub fn kinds_of(answer: Option<&[Value]>) -> Vec<String> {
    words_of(answer, words::SESSION_KINDS)
}

/// P19's words (`widening_of`).
pub fn widening_of(answer: Option<&[Value]>) -> Vec<String> {
    words_of(answer, words::WIDENINGS)
}

fn record(found: &Value) -> Py<Option<Value>> {
    let Value::Object(map) = found else {
        return Ok(None);
    };
    let keys_fit = BASE_RECORD_KEYS.iter().all(|key| map.contains_key(*key))
        && map
            .keys()
            .all(|key| key.as_str().is_some_and(|key| RECORD_KEYS.contains(&key)));
    if !keys_fit {
        return Ok(None);
    }
    let (key, thread, state, words, sent) = (
        &map["record_id"],
        &map["thread_id"],
        &map["state"],
        &map["words"],
        &map["sent_at"],
    );
    let purpose = map
        .get("purpose")
        .cloned()
        .unwrap_or_else(|| Value::from("message"));
    let ordinal = map.get("ordinal").cloned().unwrap_or(Value::Null);
    let queue_id = map.get("queue_id").cloned().unwrap_or(Value::Null);
    let withdraw = map.get("withdraw").cloned().unwrap_or(Value::Bool(false));
    let keeps = map
        .get("pause_keeps")
        .cloned()
        .unwrap_or(Value::Bool(false));
    if !matches!(keeps, Value::Bool(_)) {
        return Ok(None);
    }
    let Value::Str(key_text) = key else {
        return Ok(None);
    };
    if !ids::is_interruption_id(key, false) || ids::uuid_problem(thread, false).is_some() {
        return Ok(None);
    }
    let marker = ids::short_marker(key_text.as_str().unwrap_or_default());
    if !pyval::is(&map["marker"], &marker)
        || !pyval::in_tuple(&purpose, super::vocab_gen::domain_plug::RECORD_PURPOSES)
    {
        return Ok(None);
    }
    if pyval::in_tuple(&purpose, &["continuation", "wrap_up"]) {
        let whole = matches!(&ordinal, Value::Int(int) if !int.to_string().starts_with('-'));
        if !whole {
            return Ok(None);
        }
    } else if !matches!(ordinal, Value::Null) {
        return Ok(None);
    }
    if pyval::is(state, "waiting") {
        let words_ok =
            matches!(words, Value::Str(text) if !text.is_empty() && text.len() <= WORDS_LIMIT);
        if !words_ok
            || !matches!(sent, Value::Null)
            || !matches!(queue_id, Value::Null)
            || withdraw != Value::Bool(false)
        {
            return Ok(None);
        }
    } else if pyval::is(state, "in_flight") {
        let (low, high) = states::EPOCH_STORE;
        let sent_ok = matches!(sent, Value::Null) || states::epoch(sent, low, high, false, true)?;
        let queue_ok =
            matches!(queue_id, Value::Null) || ids::uuid_problem(&queue_id, false).is_none();
        if !matches!(words, Value::Null)
            || !sent_ok
            || !queue_ok
            || !matches!(withdraw, Value::Bool(_))
        {
            return Ok(None);
        }
    } else {
        return Ok(None);
    }
    let mut out = Map::new();
    let mut put = |name: &str, value: Value| {
        out.insert(Str::from(name), value);
    };
    put("record_id", key.clone());
    put("thread_id", thread.clone());
    put("marker", map["marker"].clone());
    put("state", state.clone());
    put("words", words.clone());
    put(
        "sent_at",
        if matches!(sent, Value::Null) {
            Value::Null
        } else {
            Value::Float(Num::of(sent).ok_or("TypeError")?.as_f64())
        },
    );
    put("purpose", purpose);
    put("ordinal", ordinal);
    put("queue_id", queue_id);
    put("withdraw", withdraw);
    put("pause_keeps", keeps);
    Ok(Some(Value::Object(out)))
}

/// `records_of(answer)`: the records of the plug's own core takes from P2's answer - a list or a tuple of records,
/// each checked, the first RECORDS_LIMIT looked at, a second record of one id dropped. `None` is any other answer.
pub fn records_of(answer: Option<&[Value]>) -> Py<Vec<Value>> {
    let Some(found) = answer else {
        return Ok(Vec::new());
    };
    let mut taken: Vec<Value> = Vec::new();
    let mut seen: Vec<Value> = Vec::new();
    for each in found.iter().take(RECORDS_LIMIT) {
        if let Some(made) = record(each)? {
            let id = match &made {
                Value::Object(map) => map["record_id"].clone(),
                _ => Value::Null,
            };
            if !seen.contains(&id) {
                seen.push(id);
                taken.push(made);
            }
        }
    }
    Ok(taken)
}

/// `fields(answer)`: what a surface takes from a plug (P10) - a JSON object with text keys, copied through the writer's
/// own form - or None (DEFER there).
pub fn fields(answer: &Value) -> Option<Value> {
    let Value::Object(_) = answer else {
        return None;
    };
    let text = json::to_string(answer, &Options::new()).ok()?;
    json::from_str(&text)
        .ok()
        .or_else(|| car_machine::compat::loads(&text).ok())
}

/// `Guarded.power`'s check of P21's answer: `{"tasks": a PowerTasks word, "threads": [ids]}` - exactly those two keys,
/// at most POWER_THREADS canonical ids, kept once each in their order - or None. `threads_tuple` says the answer's
/// threads were a list or a tuple (`None` for any other kind of value in that place).
pub fn power_of(answer: &Value) -> Option<Value> {
    let Value::Object(map) = answer else {
        return None;
    };
    if map.len() != 2 || !map.contains_key("tasks") || !map.contains_key("threads") {
        return None;
    }
    let word = pyval::text(&map["tasks"])?;
    if !super::POWER_TASKS.contains(&word) {
        return None;
    }
    let Value::Array(threads) = &map["threads"] else {
        return None;
    };
    if threads.len() > POWER_THREADS
        || !threads
            .iter()
            .all(|thread| matches!(thread, Value::Str(_)) && ids::is_uuid(thread))
    {
        return None;
    }
    let mut kept: Vec<Value> = Vec::new();
    for thread in threads {
        if !kept.contains(thread) {
            kept.push(thread.clone());
        }
    }
    let mut out = Map::new();
    out.insert(Str::from("tasks"), Value::from(word));
    out.insert(Str::from("threads"), Value::Array(kept));
    Some(Value::Object(out))
}
