//! The bridge's `defaults` command, and nothing else of the settings: S0.4's end-to-end proof.
//!
//! The table is `settings.defaults()` as tests/golden/bridge/defaults.json pins it, in the order the
//! Python builds it. TO BE REPLACED by car-policy's settings and schema (S2.2), which owns the defaults,
//! `coerce`, `kept` (the Codex homes Restore defaults keeps) and the managed clamp; this stub keeps
//! nothing, clamps nothing, and writes no Observe-only flag into the state.

use std::path::Path;

use car_machine::json::{Error, Map, Options, Value, to_string};

/// settings.py's CONFIG_VERSION, written beside the values in settings.json.
pub const CONFIG_VERSION: i64 = 2;

enum V {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(&'static str),
    EmptyList,
}

const DEFAULTS: &[(&str, V)] = &[
    ("max_recovery_attempts", V::Int(4)),
    ("max_no_progress", V::Int(3)),
    ("max_chain_continuations", V::Int(6)),
    ("retry_timing", V::Str("normal")),
    ("detection_lookback_hours", V::Float(6.0)),
    ("notifications", V::Bool(true)),
    ("show_tray", V::Bool(true)),
    ("notification_card", V::Bool(true)),
    ("start_with_codex", V::Bool(false)),
    ("theme", V::Str("system")),
    ("panel_theme", V::Str("same")),
    ("design", V::Str("soft")),
    ("reduce_motion", V::Bool(false)),
    ("codex_exe", V::Null),
    ("recover_usage_limit", V::Bool(true)),
    ("recover_network_transient", V::Bool(true)),
    ("recover_timeout", V::Bool(true)),
    ("recover_rate_limit_transient", V::Bool(true)),
    ("recover_server_5xx", V::Bool(true)),
    ("recover_stream_interrupted", V::Bool(true)),
    ("notify_interruption", V::Bool(true)),
    ("notify_starting", V::Bool(true)),
    ("notify_result", V::Bool(true)),
    ("notify_stopped", V::Bool(true)),
    ("notify_needs_you", V::Bool(false)),
    ("notify_needs_you_invalid", V::Bool(true)),
    ("notify_needs_you_policy", V::Bool(true)),
    ("notify_needs_you_auth", V::Bool(true)),
    ("notify_needs_you_failure", V::Bool(true)),
    ("stall_after", V::Str("off")),
    ("needs_you_sound", V::Bool(false)),
    ("interface_language", V::Str("system")),
    ("continuation_language", V::Str("follow")),
    ("continuation_style", V::Str("standard")),
    ("custom_message_mode", V::Str("global")),
    ("custom_message", V::Null),
    ("custom_message_usage_limit", V::Null),
    ("custom_message_rate_limit_transient", V::Null),
    ("custom_message_network_transient", V::Null),
    ("custom_message_timeout", V::Null),
    ("custom_message_server_5xx", V::Null),
    ("custom_message_stream_interrupted", V::Null),
    ("custom_message_by_thread", V::Null),
    ("quiet_hours_start", V::Str("off")),
    ("quiet_hours_end", V::Str("07:00")),
    ("quiet_hours_days", V::Str("every_day")),
    ("default_tier", V::Str("automatic")),
    ("objection_minutes", V::Int(5)),
    ("observe_only", V::Bool(false)),
    ("new_conversation_policy", V::Str("resume")),
    ("project_policy", V::Str("every")),
    ("project_keys_always", V::Str("")),
    ("project_keys_never", V::Str("")),
    ("retry_wait_1", V::Str("s5")),
    ("retry_wait_2", V::Str("m15")),
    ("retry_wait_3", V::Str("m15")),
    ("retry_wait_4", V::Str("m15")),
    ("retry_wait_5", V::Str("m15")),
    ("retry_jitter", V::Bool(false)),
    ("chain_time_ceiling", V::Str("off")),
    ("task_changed_guard", V::Str("off")),
    ("context_guard", V::Str("off")),
    ("ask_after_sleep_minutes", V::Str("off")),
    ("wait_for_network", V::Bool(false)),
    ("keep_awake", V::Str("off")),
    ("keep_awake_hours", V::Str("h6")),
    ("memory_guard", V::Str("off")),
    ("memory_guard_limit", V::Str("mb1024")),
    ("status_file", V::Bool(false)),
    ("codex_homes", V::EmptyList),
    ("home_suggestions", V::Bool(true)),
    ("home_suggestions_dismissed", V::EmptyList),
    ("notice_click", V::Str("page")),
    ("notices_stay", V::EmptyList),
];

/// Every setting at its default, in the Python's order.
pub fn defaults() -> Map {
    DEFAULTS
        .iter()
        .map(|(name, value)| {
            let value = match value {
                V::Null => Value::Null,
                V::Bool(flag) => Value::Bool(*flag),
                V::Int(number) => Value::from(*number),
                V::Float(number) => Value::Float(*number),
                V::Str(text) => Value::from(*text),
                V::EmptyList => Value::Array(Vec::new()),
            };
            ((*name).into(), value)
        })
        .collect()
}

/// settings.save's bytes: the values with config_version, indent 2, keys sorted, UTF-8.
pub fn settings_file_bytes(values: &Map) -> Result<Vec<u8>, Error> {
    let mut payload = values.clone();
    payload.insert("config_version".into(), Value::from(CONFIG_VERSION));
    let options = Options::wire().indent(2).sort_keys(true);
    Ok(to_string(&Value::Object(payload), &options)?.into_bytes())
}

/// What `defaults` does to a fresh home: settings.json written, and the reply's settings returned.
pub fn restore(home: &Path) -> std::io::Result<Map> {
    let values = defaults();
    let data =
        settings_file_bytes(&values).map_err(|_| std::io::Error::other("unwritable settings"))?;
    let folder = home.join("config");
    std::fs::create_dir_all(&folder)?;
    // settings.save writes a temporary file and replaces; the same here, so a reader never sees half a file.
    let temporary = folder.join("settings.harness.json.tmp");
    std::fs::write(&temporary, &data)?;
    std::fs::rename(&temporary, folder.join("settings.json"))?;
    Ok(values)
}
