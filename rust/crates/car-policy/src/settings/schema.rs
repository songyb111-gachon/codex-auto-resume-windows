//! `settings_schema.py`: the settings' schema, as every surface draws it (`settings.describe()`).
//!
//! The user interfaces render themselves from this, so a field added to FIELDS appears in every front end at once. A
//! field no surface offers (NOT_YET_OFFERED, ROW_ACTION_FIELDS, DASHBOARD_ONLY) is not described.

use car_machine::json::{Map, Str, Value};

use crate::classify::{continuation, power};

use super::{
    DASHBOARD_ONLY, FIELDS, NEEDS_YOU_FIELDS, NOT_YET_OFFERED, ROW_ACTION_FIELDS, field_type,
    is_custom_text, memguard, notice_kinds, own, ownvalues, ranges, statusfile,
};

const APPEARANCE: &[&str] = &["theme", "panel_theme", "design", "reduce_motion"];
const WINDOWS: &[&str] = &[
    "show_tray",
    "notification_card",
    "start_with_codex",
    power::KEEP_AWAKE_FIELD,
    power::AWAKE_CAP_FIELD,
    memguard::GUARD_FIELD,
    memguard::LIMIT_FIELD,
    statusfile::FIELD,
];
const LIMITS: &[&str] = &[
    "max_recovery_attempts",
    "max_no_progress",
    "max_chain_continuations",
    "retry_timing",
    "quiet_hours_start",
    "quiet_hours_end",
    "quiet_hours_days",
    "default_tier",
    "objection_minutes",
    "new_conversation_policy",
    "project_policy",
    "retry_wait_1",
    "retry_wait_2",
    "retry_wait_3",
    "retry_wait_4",
    "retry_wait_5",
    "retry_jitter",
    "chain_time_ceiling",
    "task_changed_guard",
    "context_guard",
    power::SLEEP_FIELD,
    power::NETWORK_FIELD,
];
const CONTINUATION: &[&str] = &[
    "continuation_language",
    "continuation_style",
    "custom_message_mode",
];

/// `describe()`: the machine-readable schema for the settings interfaces. `current` is the language this process
/// speaks (`l10n.current()`), asked only when an edition registered a kind of notice whose words are needed.
pub fn describe(current: &dyn Fn() -> String) -> Vec<Value> {
    let mut described = Vec::new();
    for field in FIELDS {
        let name = field.name;
        if NOT_YET_OFFERED.contains(&name)
            || ROW_ACTION_FIELDS.contains(&name)
            || DASHBOARD_ONLY.contains(&name)
        {
            continue;
        }
        let mut entry = Map::new();
        let mut put = |key: &str, value: Value| {
            entry.insert(Str::from(key), value);
        };
        put("name", Value::from(name));
        put("default", field.default.value());
        put("type", Value::from(field_type(name)));
        if let Some(range) = ranges(name) {
            for (key, value) in range {
                entry.insert(key, value);
            }
        }
        let mut put = |key: &str, value: Value| {
            entry.insert(Str::from(key), value);
        };
        if let Some(spec) = own(name) {
            put("custom", ownvalues::published(spec));
        }
        if let Some(category) = name.strip_prefix("recover_") {
            put("group", Value::from("recovery"));
            put("category", Value::from(category));
        } else if name.starts_with("notify_")
            || name == "notifications"
            || NEEDS_YOU_FIELDS.contains(&name)
        {
            put("group", Value::from("notifications"));
            put("master", Value::Bool(name == "notifications"));
        } else if APPEARANCE.contains(&name) {
            put("group", Value::from("appearance"));
        } else if name == notice_kinds::FIELD {
            put("group", Value::from("windows"));
            let every = notice_kinds::kinds();
            put(
                "kinds",
                Value::Array(
                    every
                        .iter()
                        .map(|kind| Value::from(kind.id.as_str()))
                        .collect(),
                ),
            );
            let mut keys = Map::new();
            for kind in &every {
                if let Some(key) = kind.key {
                    keys.insert(Str::from(kind.id.as_str()), Value::from(key));
                }
            }
            put("keys", Value::Object(keys));
            let labels = if notice_kinds::any_registered() {
                notice_kinds::edition_labels(&current())
            } else {
                Value::Object(Map::new())
            };
            put("labels", labels);
        } else if WINDOWS.contains(&name) {
            put("group", Value::from("windows"));
        } else if LIMITS.contains(&name) {
            put("group", Value::from("limits"));
        } else if name == "observe_only" {
            put("group", Value::from("recovery"));
        } else if name == "interface_language" {
            put("group", Value::from("general"));
        } else if CONTINUATION.contains(&name) {
            put("group", Value::from("continuation"));
        } else if is_custom_text(name) {
            put("group", Value::from("continuation"));
            put("multiline", Value::Bool(true));
            put(
                "max_length",
                Value::from(continuation::MAX_CUSTOM_LENGTH as i64),
            );
            if name != "custom_message" {
                put("category", Value::from(&name["custom_message_".len()..]));
            }
        } else {
            put("group", Value::from("advanced"));
        }
        described.push(Value::Object(entry));
    }
    described
}
