//! `projects.py`: which projects may resume without a person, by a key that is only ever a digest. A decision here
//! can only hold a record back (`notify_only`); it never names a conversation.

use car_machine::domain::ids;
use car_machine::hash;
use car_machine::json::{Map, Value};
use car_machine::pyval::Py;

use super::text::{casefold, strip};
use super::value::{dict_or_empty, get, in_tuple, text};
pub use super::vocab_gen::projects::{DEFAULT_POLICY, POLICIES};

/// The settings that hold the two lists, each a comma-separated run of keys in order.
pub const ALWAYS: &str = "project_keys_always";
pub const NEVER: &str = "project_keys_never";
pub const MAX_KEYS: usize = 50;

/// `normal_folder(cwd)`: a folder as one project, or None.
pub fn normal_folder(cwd: &Value) -> Option<String> {
    let cwd = text(cwd)?;
    if cwd.contains(['\r', '\n', '\0']) {
        return None;
    }
    let mut plain = strip(cwd);
    if let Some(rest) = plain.strip_prefix("\\\\?\\") {
        plain = rest;
    }
    let plain = plain.replace('/', "\\");
    let folded = casefold(plain.trim_end_matches('\\'));
    (!folded.is_empty()).then_some(folded)
}

/// `key_for(project_id, cwd)`: the digest of Codex's project id when there is one, else of its folder.
pub fn key_for(project_id: &Value, cwd: &Value) -> Option<String> {
    if let Some(id) = text(project_id)
        && !strip(id).is_empty()
        && !id.contains('\0')
    {
        return Some(digest(&format!("project_id:{}", strip(id))));
    }
    normal_folder(cwd).map(|folder| digest(&format!("cwd:{folder}")))
}

fn digest(said: &str) -> String {
    hash::hex(&hash::sha256(said.as_bytes()))
}

/// `is_key(value)`.
pub fn is_key(value: &Value) -> bool {
    ids::is_digest(value)
}

/// `parse_keys(text)`: the keys one list holds, in order, or None when `text` is not such a list.
pub fn parse_keys(value: &Value) -> Option<Vec<String>> {
    let said = text(value)?;
    if said.is_empty() {
        return Some(Vec::new());
    }
    let keys: Vec<String> = said.split(',').map(str::to_owned).collect();
    let mut seen = keys.clone();
    seen.sort();
    seen.dedup();
    if keys.len() > MAX_KEYS
        || seen.len() != keys.len()
        || !keys.iter().all(|key| is_key(&Value::from(key.as_str())))
    {
        return None;
    }
    Some(keys)
}

/// `format_keys(keys)`: sorted, each once.
pub fn format_keys(keys: &[String]) -> String {
    let mut sorted = keys.to_vec();
    sorted.sort();
    sorted.dedup();
    sorted.join(",")
}

/// `coerce_keys(value, default)`: the list as written, when it is one in its one written form.
pub fn coerce_keys(value: &Value, default: &Value) -> Value {
    match parse_keys(value) {
        Some(keys) if Some(format_keys(&keys).as_str()) == text(value) => value.clone(),
        _ => default.clone(),
    }
}

fn policy(values: &Value) -> &'static str {
    let raw = match values {
        Value::Object(map) => get(map, "project_policy"),
        _ => &Value::Null,
    };
    POLICIES
        .iter()
        .copied()
        .find(|each| in_tuple(raw, &[each]))
        .unwrap_or(DEFAULT_POLICY)
}

/// `asks(values)`: whether the policy asks anything at all.
pub fn asks(values: &Value) -> bool {
    policy(values) != DEFAULT_POLICY
}

fn keys(values: &Value, name: &str) -> Vec<String> {
    parse_keys(get(dict_or_empty(values), name)).unwrap_or_default()
}

/// `allows(values, key)`: whether a project, by its key (None: it could not be read), may resume without a person.
pub fn allows(values: &Value, key: &Value) -> bool {
    let chosen = policy(values);
    if chosen == "every" {
        return true;
    }
    if matches!(key, Value::Null) {
        return false;
    }
    let listed =
        |name: &str| text(key).is_some_and(|key| keys(values, name).iter().any(|each| each == key));
    if chosen == "only_listed" {
        return listed(ALWAYS);
    }
    !listed(NEVER)
}

/// `hold_for(values, key)`: none, or a person's (`notify_only`).
pub fn hold_for(values: &Value, key: &Value) -> Option<&'static str> {
    (!allows(values, key)).then_some("notify_only")
}

/// `rule(values, key, always)`: the settings a task row's Always (or Never) for this project writes. ValueError for a
/// key that is not one, and for a list already at MAX_KEYS.
pub fn rule(values: &Value, key: &Value, always: bool) -> Py<Value> {
    if !is_key(key) {
        return Err("ValueError");
    }
    let key = text(key).expect("a key is text").to_owned();
    let mut always_keys = keys(values, ALWAYS);
    let mut never_keys = keys(values, NEVER);
    let (into, out) = if always {
        (&mut always_keys, &mut never_keys)
    } else {
        (&mut never_keys, &mut always_keys)
    };
    if !into.contains(&key) {
        into.push(key.clone());
    }
    out.retain(|each| *each != key);
    always_keys.sort();
    always_keys.dedup();
    never_keys.sort();
    never_keys.dedup();
    if always_keys.len() > MAX_KEYS || never_keys.len() > MAX_KEYS {
        return Err("ValueError");
    }
    let mut changes = Map::new();
    changes.insert(ALWAYS.into(), Value::from(format_keys(&always_keys)));
    changes.insert(NEVER.into(), Value::from(format_keys(&never_keys)));
    if !always && policy(values) == "every" {
        changes.insert("project_policy".into(), Value::from("except_listed"));
    }
    Ok(Value::Object(changes))
}
