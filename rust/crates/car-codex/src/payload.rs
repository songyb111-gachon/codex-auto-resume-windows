//! `codex/payload.py`: reading one interruption out of what Codex recorded.
//!
//! `detect` turns a failed turn into the record the engine keeps, and the two checks after it answer whether a
//! message in Codex's history or queue is a continuation of ours: by its marker, or - for one sent with none - by the
//! client id it was queued under.

use std::collections::BTreeSet;

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_policy::classify::failures;

use crate::values::{epoch, error_shape, json_of, normalize, row_status};

static NULL: Value = Value::Null;

fn field<'a>(map: &'a Map, key: &str) -> &'a Value {
    map.get(key).unwrap_or(&NULL)
}

fn dict_field<'a>(value: &'a Value, key: &str) -> &'a Value {
    match value {
        Value::Object(map) => field(map, key),
        _ => &NULL,
    }
}

/// `ids.interruption_id(thread_id, turn_id, completed_at, ordinal)` of a normalized turn.
fn interruption_of(normalized: &Map) -> Py<String> {
    ids::interruption_id(
        field(normalized, "thread_id"),
        field(normalized, "turn_id"),
        field(normalized, "completed_at"),
        field(normalized, "ordinal"),
        &Value::from(""),
    )
}

/// `detect(row)`: a failed turn this tool is willing to recover, or None.
///
/// `unknown` and every terminal category stop here: they are never registered, so they can never be retried by a
/// later change somewhere else in the pipeline.
pub fn detect(row: &Value) -> Py<Option<Map>> {
    let Some(mut normalized) = normalize(row)? else {
        return Ok(None);
    };
    let category = match field(&normalized, "category") {
        Value::Str(text) => text.as_str().unwrap_or("").to_owned(),
        _ => String::new(),
    };
    if !pyval::is(field(&normalized, "status"), "failed")
        || !failures::is_recoverable(&category)
        || matches!(field(&normalized, "completed_at"), Value::Null)
    {
        return Ok(None);
    }
    let found = interruption_of(&normalized)?;
    normalized.insert(Str::from("interruption_id"), Value::from(found));
    Ok(Some(normalized))
}

/// `_needing(row, kinds)`: a failed turn whose category is one of `kinds`, normalized as `detect` normalizes one and
/// with the id it would have - or None. Never passed to `detect`, and never registered.
pub fn needing(row: &Value, kinds: &[&str]) -> Py<Option<Map>> {
    let Some(mut normalized) = normalize(row)? else {
        return Ok(None);
    };
    let category = field(&normalized, "category");
    pyval::hashable(category)?;
    if !pyval::is(field(&normalized, "status"), "failed")
        || !pyval::in_tuple(category, kinds)
        || matches!(field(&normalized, "completed_at"), Value::Null)
    {
        return Ok(None);
    }
    let found = interruption_of(&normalized)?;
    normalized.insert(Str::from("interruption_id"), Value::from(found));
    Ok(Some(normalized))
}

/// `judge(row, needs_you, admissible, shapes)`: one failed latest turn as `latest_failures` brings it, or None:
/// `detect`'s, else - from the same read - one of the `needs_you` kinds, else one the plug may take up
/// (`admissible`), marked so; and with `shapes`, its error's shape, never a word of a message.
pub fn judge(
    row: &Map,
    needs_you: &BTreeSet<String>,
    admissible: bool,
    shapes: bool,
) -> Py<Option<Map>> {
    let whole = Value::Object(row.clone());
    let mut eligible = detect(&whole)?;
    if eligible.is_none() && !needs_you.is_empty() {
        let kinds: Vec<&str> = needs_you.iter().map(String::as_str).collect();
        eligible = needing(&whole, &kinds)?;
    }
    if eligible.is_none() && admissible {
        eligible = needing(&whole, failures::ADMISSIBLE)?;
    }
    if let Some(found) = eligible.as_mut() {
        if admissible && pyval::in_tuple(field(found, "category"), failures::ADMISSIBLE) {
            found.insert(Str::from("admissible"), Value::Bool(true));
        }
        if shapes {
            found.insert(Str::from("shape"), error_shape(row));
        }
    }
    Ok(eligible)
}

/// `later_turn(row)`: one turn after the failed one, as `later_turns` classifies it: ours, someone else's, or not yet
/// knowable - booleans and ids only. `row` holds `status`, `first_is_ours`, `has_first`, `turn_id`, `rollout_ordinal`.
pub fn later_turn(row: &Map) -> Py<Map> {
    let status = row_status(field(row, "status"))?;
    let (kind, reason) = if pyval::truthy(field(row, "first_is_ours")) {
        ("ours", None)
    } else if !pyval::truthy(field(row, "has_first")) && status == Some("inProgress") {
        ("undetermined", None)
    } else if !pyval::truthy(field(row, "has_first")) {
        ("foreign", Some("turn_without_user_item"))
    } else {
        ("foreign", Some("later_turn_exists"))
    };
    let turn = field(row, "turn_id");
    let mut found = Map::new();
    found.insert(
        Str::from("turn_id"),
        if ids::is_uuid(turn) {
            turn.clone()
        } else {
            Value::Null
        },
    );
    found.insert(Str::from("ordinal"), field(row, "rollout_ordinal").clone());
    found.insert(Str::from("status"), status.map_or(Value::Null, Value::from));
    found.insert(Str::from("kind"), Value::from(kind));
    found.insert(Str::from("reason"), reason.map_or(Value::Null, Value::from));
    Ok(found)
}

/// `marker_row(row, marker)`: one history row holding our marker, as `marker_rows` gives it - None where its message
/// is not ours after all.
pub fn marker_row(row: &Map, marker: &str) -> Py<Option<Map>> {
    let payload = json_of(field(row, "item_json")).unwrap_or(Value::Null);
    if !item_is_ours(&payload, marker) {
        return Ok(None);
    }
    let client = dict_field(&payload, "clientId");
    let ordinal = field(row, "rollout_ordinal");
    let turn = field(row, "turn_id");
    let mut found = Map::new();
    found.insert(
        Str::from("turn_id"),
        if ids::is_uuid(turn) {
            turn.clone()
        } else {
            Value::Null
        },
    );
    found.insert(
        Str::from("ordinal"),
        if pyval::is_int(ordinal) {
            ordinal.clone()
        } else {
            Value::Null
        },
    );
    found.insert(
        Str::from("status"),
        row_status(field(row, "status"))?.map_or(Value::Null, Value::from),
    );
    // A row whose turn is not projected yet cannot say who started it.
    found.insert(
        Str::from("first_unset"),
        Value::Bool(pyval::truthy(field(row, "first_unset")) || !pyval::is_int(ordinal)),
    );
    found.insert(
        Str::from("starts_turn"),
        Value::Bool(pyval::truthy(field(row, "starts_turn"))),
    );
    found.insert(
        Str::from("client_id"),
        if ids::is_client_id(client) {
            client.clone()
        } else {
            Value::Null
        },
    );
    Ok(Some(found))
}

/// `admissible(row)`: a failed turn of a kind the standard edition never recovers alone and the edition's plug may
/// take up, as `detect` has a failure, or None.
pub fn admissible(row: &Value) -> Py<Option<Map>> {
    needing(row, failures::ADMISSIBLE)
}

/// `marker in text` of a Python `str`: its code points are contiguous exactly where its UTF-8 bytes are.
fn contains(text: &Str, needle: &str) -> bool {
    let bytes = text.as_bytes();
    let wanted = needle.as_bytes();
    wanted.is_empty() || bytes.windows(wanted.len()).any(|window| window == wanted)
}

/// `_content_has_marker(content, marker)`.
pub fn content_has_marker(content: &Value, marker: &str) -> bool {
    let Value::Array(items) = content else {
        return false;
    };
    items.iter().any(|item| {
        let Value::Object(map) = item else {
            return false;
        };
        pyval::is(field(map, "type"), "text")
            && match field(map, "text") {
                Value::Str(text) => contains(text, marker),
                _ => false,
            }
    })
}

/// `_queue_has_marker(payload, marker)`.
pub fn queue_has_marker(payload: &Value, marker: &str) -> bool {
    let Value::Object(map) = payload else {
        return false;
    };
    // TurnInput's serde shape is version-pinned; unknown shapes fail closed.
    // {"UserInput": {"content": [...], "client_id": ...}}.
    let Some(content) = map.get("UserInput") else {
        return false;
    };
    if map.len() != 1 || !matches!(content, Value::Object(_)) {
        return false;
    }
    if ids::is_marker(&Value::from(marker)) {
        return content_has_marker(dict_field(content, "content"), marker);
    }
    // A marker-free continuation is ours by the client id it was queued under, and by nothing in its words.
    pyval::is(dict_field(content, "client_id"), marker)
}

/// `_item_is_ours(payload, proof)`: whether a history row's user message is our continuation: it carries our marker
/// in its words, or - sent with none (P15) - Codex keeps our client id on it as `clientId`.
pub fn item_is_ours(payload: &Value, proof: &str) -> bool {
    if !matches!(payload, Value::Object(_))
        || !pyval::is(dict_field(payload, "type"), "userMessage")
    {
        return false;
    }
    if ids::is_marker(&Value::from(proof)) {
        return content_has_marker(dict_field(payload, "content"), proof);
    }
    pyval::is(dict_field(payload, "clientId"), proof)
}

/// `_choose_reset(buckets, completed_at)`: the reset hint of the rate-limit snapshots before a usage-limit failure.
pub fn choose_reset(buckets: &Value, completed_at: &Value) -> Py<Map> {
    let Value::Object(buckets) = buckets else {
        return Err("AttributeError");
    };
    // The largest (reset, "bucket:window") pair, as `max` of tuples orders them.
    let mut blocked: Vec<(Value, Str)> = Vec::new();
    let mut ambiguity = false;
    for (bucket, limits) in buckets {
        let mut has_window = false;
        for name in ["primary", "secondary"] {
            let Value::Object(limit_map) = limits else {
                return Err("AttributeError");
            };
            let window = field(limit_map, name);
            let Value::Object(window) = window else {
                continue;
            };
            let used = field(window, "used_percent");
            let reset = field(window, "resets_at");
            if !matches!(used, Value::Int(_) | Value::Float(_))
                || !pyval::is_finite(used)?
                || pyval::less(used, &Value::from(0))?
            {
                continue;
            }
            has_window = true;
            if !pyval::less(used, &Value::from(100))? {
                if epoch(reset)? && pyval::less_or_equal(completed_at, reset)? {
                    let mut joined = bucket.as_bytes().to_vec();
                    joined.extend_from_slice(format!(":{name}").as_bytes());
                    blocked.push((
                        reset.clone(),
                        Str::from_surrogatepass(joined).ok_or("ValueError")?,
                    ));
                } else {
                    ambiguity = true;
                }
            }
        }
        if !has_window {
            ambiguity = true;
        }
    }
    if !blocked.is_empty() {
        let mut best = 0;
        for at in 1..blocked.len() {
            let ahead = match pyval::order(&blocked[at].0, &blocked[best].0)? {
                Some(std::cmp::Ordering::Greater) => true,
                Some(std::cmp::Ordering::Equal) => blocked[at].1 > blocked[best].1,
                _ => false,
            };
            if ahead {
                best = at;
            }
        }
        let (reset, limit) = blocked[best].clone();
        let mut found = Map::new();
        found.insert(Str::from("reset_at"), reset);
        found.insert(Str::from("limit_type"), Value::Str(limit));
        found.insert(
            Str::from("uncertain"),
            Value::Bool(ambiguity || blocked.len() > 1),
        );
        return Ok(found);
    }
    // Actual sample is codex primary=98%, immediately followed by premium=null. Preserve its corroborating reset ONLY
    // when its own usage is high enough to plausibly be the block; a low-usage window's far-future reset must not
    // delay the first eligibility check. A fresh live availability check is still required.
    if let Some(Value::Object(codex)) = buckets.get("codex")
        && let Some(Value::Object(primary)) = codex.get("primary")
    {
        let used = field(primary, "used_percent");
        let reset = field(primary, "resets_at");
        if matches!(used, Value::Int(_) | Value::Float(_))
            && pyval::is_finite(used)?
            && !pyval::less(used, &Value::from(90))?
            && epoch(reset)?
            && pyval::less_or_equal(completed_at, reset)?
        {
            let mut found = Map::new();
            found.insert(Str::from("reset_at"), reset.clone());
            found.insert(Str::from("limit_type"), Value::from("codex:primary_hint"));
            found.insert(Str::from("uncertain"), Value::Bool(true));
            return Ok(found);
        }
    }
    let mut found = Map::new();
    found.insert(Str::from("reset_at"), Value::Null);
    found.insert(Str::from("limit_type"), Value::from("unknown"));
    found.insert(Str::from("uncertain"), Value::Bool(true));
    Ok(found)
}

/// `UNKNOWN_RESET`.
pub fn unknown_reset() -> Map {
    let mut found = Map::new();
    found.insert(Str::from("reset_at"), Value::Null);
    found.insert(Str::from("limit_type"), Value::from("unknown"));
    found.insert(Str::from("uncertain"), Value::Bool(true));
    found
}
