//! What the settings read of the classifier's and the policy rules' modules (S2.1's seat): a minimal local seam.
//!
//! TO BE REPLACED by car-policy's `classify` (S2.1) once it holds `continuation`, `ladder`, `quiet`, `guards`,
//! `power`, `needsyou`, `projects`, `failures` and `reasons`: each item below names the Python it stands for, and
//! nothing here is read by anything but `settings` and its own modules. Only the values and the checks the settings
//! layer itself takes are here (the coercers, the choice lists, the defaults, a Custom message's check), each as
//! the reference v0.6.26-beta.2 has it; `tests/rustdiff/diffs_settings_*.py` holds them to it through the settings.
//! `homefind.coerce_dismissed` is here too: homefind is in neither seat's list.

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pytext;

use super::ownvalues::{Own, OwnKind};

// ------------------------------------------------------------------------------------- failures, reasons
/// `failures.USAGE_LIMIT`.
pub const USAGE_LIMIT: &str = "usage_limit";
/// `reasons.RECOVERABLE`, in its order (the Custom message per category follows it).
pub const RECOVERABLE: &[&str] = &[
    "usage_limit",
    "rate_limit_transient",
    "network_transient",
    "timeout",
    "server_5xx",
    "stream_interrupted",
];
/// `failures.TAG_SHAPE.fullmatch(code)`: `[A-Za-z][A-Za-z0-9]{0,63}`.
pub fn tag_shape(code: &str) -> bool {
    let mut chars = code.chars();
    chars
        .next()
        .is_some_and(|first| first.is_ascii_alphabetic())
        && code.chars().count() <= 64
        && chars.all(|each| each.is_ascii_alphanumeric())
}

// ------------------------------------------------------------------------------------- continuation
/// `continuation.STYLES` (ContinuationStyle).
pub const STYLES: &[&str] = &["minimal", "standard", "detailed", "custom"];
pub const DEFAULT_STYLE: &str = "standard";
/// `continuation.FOLDED_STYLES`.
pub const FOLDED_STYLES: &[(&str, &str)] = &[("careful", "detailed")];
pub const BY_THREAD_FIELD: &str = "custom_message_by_thread";
pub const MAX_CONVERSATIONS: usize = 50;
/// `continuation.CUSTOM_MODES` (CustomMode).
pub const CUSTOM_MODES: &[&str] = &["global", "per_reason"];
pub const DEFAULT_CUSTOM_MODE: &str = "global";
pub const MAX_CUSTOM_LENGTH: usize = 2000;
pub const ALLOWED_PLACEHOLDERS: &[&str] = &[
    "reason",
    "category",
    "attempt",
    "max_attempts",
    "reset_time",
];
pub const FORBIDDEN_PLACEHOLDERS: &[(&str, &str)] = &[
    ("prompt", "the text you sent"),
    ("reply", "the assistant's answer"),
    ("conversation_title", "the conversation's title"),
    ("project_path", "a path on this machine"),
    ("path", "a path on this machine"),
    ("cwd", "a path on this machine"),
    ("username", "your Windows account name"),
    ("user", "your Windows account name"),
    ("raw_error", "the unredacted error"),
    ("error", "the unredacted error"),
    ("account", "your account"),
    ("email", "your e-mail address"),
    ("credential", "a credential"),
    ("token", "a token"),
];

/// `continuation.CustomMessageError`: the sentence, its code and the one fact it needs.
#[derive(Clone, Debug, PartialEq)]
pub struct CustomMessageError {
    pub message: String,
    pub code: &'static str,
    pub detail: Option<String>,
}

/// Whether every code point of `text` is white space (`not text.strip()`); a surrogate is not.
pub fn blank(text: &Str) -> bool {
    text.code_points()
        .all(|point| char::from_u32(point).is_some_and(pytext::is_space))
}

/// `continuation.PLACEHOLDER.findall(text)`: `\{([A-Za-z_][A-Za-z0-9_]*)\}`, leftmost, not overlapping.
fn placeholders(text: &Str) -> Vec<String> {
    let points: Vec<u32> = text.code_points().collect();
    let ascii = |at: usize| points.get(at).and_then(|point| char::from_u32(*point));
    let mut found = Vec::new();
    let mut at = 0;
    while at < points.len() {
        if ascii(at) == Some('{')
            && let Some(first) = ascii(at + 1)
            && (first.is_ascii_alphabetic() || first == '_')
        {
            let mut end = at + 2;
            while ascii(end).is_some_and(|each| each.is_ascii_alphanumeric() || each == '_') {
                end += 1;
            }
            if ascii(end) == Some('}') {
                found.push((at + 1..end).filter_map(ascii).collect());
                at = end + 1;
                continue;
            }
        }
        at += 1;
    }
    found
}

/// `continuation.validate_custom(text)`: the text unchanged, or the refusal.
pub fn validate_custom(value: &Value) -> Result<Str, CustomMessageError> {
    let refuse = |message: String, code, detail| {
        Err(CustomMessageError {
            message,
            code,
            detail,
        })
    };
    let Value::Str(text) = value else {
        return refuse("A custom message has to be text.".into(), "not_text", None);
    };
    if blank(text) {
        return refuse("A custom message cannot be empty.".into(), "empty", None);
    }
    let length = text.len();
    if length > MAX_CUSTOM_LENGTH {
        return refuse(
            format!(
                "A custom message can be at most {MAX_CUSTOM_LENGTH} characters; this one is {length}."
            ),
            "too_long",
            Some(length.to_string()),
        );
    }
    for name in placeholders(text) {
        let lowered = name.to_ascii_lowercase();
        if let Some((_, what)) = FORBIDDEN_PLACEHOLDERS
            .iter()
            .find(|(forbidden, _)| *forbidden == lowered)
        {
            return refuse(
                format!("{{{name}}} is not available: it would put {what} into the message."),
                "forbidden_placeholder",
                Some(format!("{{{name}}}")),
            );
        }
        if !ALLOWED_PLACEHOLDERS.contains(&name.as_str()) {
            let available: Vec<String> = ALLOWED_PLACEHOLDERS
                .iter()
                .map(|each| format!("{{{each}}}"))
                .collect();
            return refuse(
                format!(
                    "{{{name}}} is not a placeholder this product knows. Available: {}.",
                    available.join(", ")
                ),
                "unknown_placeholder",
                Some(format!("{{{name}}}")),
            );
        }
    }
    Ok(text.clone())
}

/// `continuation.fold_style(style)`: a folded style as the one it became, anything else as it is.
pub fn fold_style(style: &Value) -> Value {
    if let Value::Str(text) = style
        && let Some((_, became)) = FOLDED_STYLES
            .iter()
            .find(|(folded, _)| text.as_str() == Some(folded))
    {
        return Value::from(*became);
    }
    style.clone()
}

/// `continuation.coerce_by_thread(value, default)`: the entries that are a canonical conversation id and a Custom
/// message, or `default` for anything else, for more than MAX_CONVERSATIONS entries and for none at all.
pub fn coerce_by_thread(value: &Value, default: &Value) -> Value {
    let Value::Object(entries) = value else {
        return default.clone();
    };
    if entries.is_empty() || entries.len() > MAX_CONVERSATIONS {
        return default.clone();
    }
    let mut kept = Map::new();
    for (thread, text) in entries {
        if !ids::is_uuid(&Value::Str(thread.clone())) {
            continue;
        }
        if let Ok(valid) = validate_custom(text) {
            kept.insert(thread.clone(), Value::Str(valid));
        }
    }
    if kept.is_empty() {
        default.clone()
    } else {
        Value::Object(kept)
    }
}

// ------------------------------------------------------------------------------------- projects
pub const PROJECT_ALWAYS: &str = "project_keys_always";
pub const PROJECT_NEVER: &str = "project_keys_never";
pub const PROJECT_DEFAULT_POLICY: &str = "every";
pub const MAX_KEYS: usize = 50;

/// `projects.parse_keys(text)`: the keys one list holds, or None when `text` is not such a list.
fn parse_keys(text: &Value) -> Option<Vec<Str>> {
    let Value::Str(text) = text else { return None };
    if text.is_empty() {
        return Some(Vec::new());
    }
    let points: Vec<u32> = text.code_points().collect();
    let keys: Vec<Str> = points
        .split(|point| *point == u32::from(','))
        .map(|part| Str::from_code_points(part.iter().copied()).expect("taken from a Str"))
        .collect();
    let mut sorted = keys.clone();
    sorted.sort();
    sorted.dedup();
    if keys.len() > MAX_KEYS || sorted.len() != keys.len() {
        return None;
    }
    if !keys
        .iter()
        .all(|key| ids::is_digest(&Value::Str(key.clone())))
    {
        return None;
    }
    Some(keys)
}

/// `projects.coerce_keys(value, default)`: the list as written, when it is one in its one written form.
pub fn coerce_keys(value: &Value, default: &Value) -> Value {
    match parse_keys(value) {
        Some(mut keys) => {
            keys.sort();
            keys.dedup();
            let joined: Vec<u8> =
                keys.iter()
                    .enumerate()
                    .fold(Vec::new(), |mut out, (index, key)| {
                        if index > 0 {
                            out.push(b',');
                        }
                        out.extend_from_slice(key.as_bytes());
                        out
                    });
            match value {
                Value::Str(text) if text.as_bytes() == joined.as_slice() => value.clone(),
                _ => default.clone(),
            }
        }
        None => default.clone(),
    }
}

// ------------------------------------------------------------------------------------- quiet
/// `quiet.TIMES`: every half hour of the day.
pub const QUIET_TIMES: &[&str] = &[
    "00:00", "00:30", "01:00", "01:30", "02:00", "02:30", "03:00", "03:30", "04:00", "04:30",
    "05:00", "05:30", "06:00", "06:30", "07:00", "07:30", "08:00", "08:30", "09:00", "09:30",
    "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30",
    "15:00", "15:30", "16:00", "16:30", "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
    "20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00", "23:30",
];
/// `quiet.STARTS`: off, then the times.
pub const QUIET_STARTS: &[&str] = &[
    "off", "00:00", "00:30", "01:00", "01:30", "02:00", "02:30", "03:00", "03:30", "04:00",
    "04:30", "05:00", "05:30", "06:00", "06:30", "07:00", "07:30", "08:00", "08:30", "09:00",
    "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00",
    "14:30", "15:00", "15:30", "16:00", "16:30", "17:00", "17:30", "18:00", "18:30", "19:00",
    "19:30", "20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00", "23:30",
];
/// `quiet.DAYS` (QuietDays).
pub const QUIET_DAYS: &[&str] = &["every_day", "weekdays", "weekends"];
pub const QUIET_DEFAULT_START: &str = "off";
pub const QUIET_DEFAULT_END: &str = "07:00";
pub const QUIET_DEFAULT_DAYS: &str = "every_day";
pub static QUIET_CLOCK: Own = Own::new(OwnKind::Clock, 0, 0, &[]);
pub static QUIET_DAYS_OWN: Own = Own::new(OwnKind::Days, 0, 0, &[]);

// ------------------------------------------------------------------------------------- ladder
/// `ladder.TIMINGS` (RetryTiming).
pub const RETRY_TIMINGS: &[&str] = &["conservative", "normal", "aggressive", "custom"];
pub const DEFAULT_TIMING: &str = "normal";
/// `ladder.PRESETS`, in order.
pub const PRESETS: &[(&str, [i64; 5])] = &[
    ("conservative", [15, 45, 120, 300, 600]),
    ("normal", [5, 15, 30, 60, 120]),
    ("aggressive", [3, 8, 20, 45, 90]),
];
/// `ladder.SPACING`.
pub const SPACING: i64 = 900;
/// `ladder.WAIT_SECONDS` (RetryWait), in order.
pub const WAIT_SECONDS: &[(&str, i64)] = &[
    ("s5", 5),
    ("s15", 15),
    ("s30", 30),
    ("m1", 60),
    ("m2", 120),
    ("m5", 300),
    ("m10", 600),
    ("m15", 900),
    ("m30", 1800),
    ("h1", 3600),
    ("h2", 7200),
    ("h3", 10800),
    ("h6", 21600),
];
/// `ladder.FIRST_WAITS` and `LATER_WAITS`.
pub const FIRST_WAITS: &[&str] = &[
    "s5", "s15", "s30", "m1", "m2", "m5", "m10", "m15", "m30", "h1", "h2",
];
pub const LATER_WAITS: &[&str] = &["m15", "m30", "h1", "h2", "h3", "h6"];
pub const STEP_FIELDS: &[&str] = &[
    "retry_wait_1",
    "retry_wait_2",
    "retry_wait_3",
    "retry_wait_4",
    "retry_wait_5",
];
pub const DEFAULT_STEPS: &[&str] = &["s5", "m15", "m15", "m15", "m15"];
/// `ladder.CEILINGS` (ChainCeiling).
pub const CEILINGS: &[&str] = &["off", "h1", "h3", "h6", "h12", "h24"];
pub const DEFAULT_CEILING: &str = "off";
pub static FIRST_STEP: Own = Own::new(OwnKind::Duration, 5, 2 * 3600, &["s", "m", "h"]);
pub static LATER_STEP: Own = Own::new(OwnKind::Duration, SPACING, 6 * 3600, &["m", "h"]);
pub static CEILING_OWN: Own = Own::new(
    OwnKind::Duration,
    SPACING,
    super::ownvalues::WEEK,
    &["m", "h"],
);

/// `ladder.choices_for(field)`.
pub fn choices_for(field: &str) -> &'static [&'static str] {
    if field == STEP_FIELDS[0] {
        FIRST_WAITS
    } else {
        LATER_WAITS
    }
}

/// `ladder.previews()`: each preset's waits as a person is shown them - its first, then the first plus SPACING.
pub fn previews() -> Value {
    let mut map = Map::new();
    for (name, steps) in PRESETS {
        let mut shown = vec![Value::from(steps[0])];
        shown.extend((1..steps.len()).map(|_| Value::from(steps[0] + SPACING)));
        map.insert(Str::from(*name), Value::Array(shown));
    }
    Value::Object(map)
}

// ------------------------------------------------------------------------------------- guards
/// `guards.TASK_GUARDS` (TaskGuard) and `CONTEXT_GUARDS` (ContextGuard).
pub const TASK_GUARDS: &[&str] = &["off", "hold", "tell"];
pub const CONTEXT_GUARDS: &[&str] = &[
    "off",
    "show",
    "above_100k",
    "above_250k",
    "above_500k",
    "above_1m",
];
pub const DEFAULT_TASK_GUARD: &str = "off";
pub const DEFAULT_CONTEXT_GUARD: &str = "off";
pub static CONTEXT_OWN: Own = Own::new(OwnKind::Count, 10_000, 10_000_000, &["k", "m"])
    .prefix("above_")
    .label("own.hold_above");

// ------------------------------------------------------------------------------------- power
pub const SLEEP_FIELD: &str = "ask_after_sleep_minutes";
pub const NETWORK_FIELD: &str = "wait_for_network";
pub const KEEP_AWAKE_FIELD: &str = "keep_awake";
pub const AWAKE_CAP_FIELD: &str = "keep_awake_hours";
/// `power.KEEP_AWAKE_MODES` (KeepAwake), `AWAKE_CAPS` (AwakeCap), `SLEEP_WAITS` (SleepWait).
pub const KEEP_AWAKE_MODES: &[&str] = &["off", "on_ac", "always"];
pub const AWAKE_CAPS: &[&str] = &["h1", "h2", "h3", "h6", "h12", "h24", "unlimited"];
pub const SLEEP_WAITS: &[&str] = &["off", "m30", "h1", "h2", "h3", "h6", "h12"];
pub const DEFAULT_SLEEP: &str = "off";
pub const DEFAULT_KEEP_AWAKE: &str = "off";
pub const DEFAULT_AWAKE_CAP: &str = "h6";
pub static SLEEP_OWN: Own = Own::new(OwnKind::Duration, 300, super::ownvalues::WEEK, &["m", "h"]);
pub static AWAKE_OWN: Own = Own::new(
    OwnKind::Duration,
    SPACING,
    super::ownvalues::WEEK,
    &["m", "h"],
);

// ------------------------------------------------------------------------------------- needsyou
/// `needsyou.KIND_FIELDS.values()`, in order.
pub const NEEDS_YOU_KIND_FIELDS: &[&str] = &[
    "notify_needs_you_invalid",
    "notify_needs_you_policy",
    "notify_needs_you_auth",
    "notify_needs_you_failure",
];
pub const STALL_FIELD: &str = "stall_after";
pub const SOUND_FIELD: &str = "needs_you_sound";
/// `needsyou.STALL_WAITS` (StallWait).
pub const STALL_WAITS: &[&str] = &["off", "m10", "m15", "m30", "h1", "h2"];
pub const DEFAULT_STALL: &str = "off";
pub static STALL_OWN: Own = Own::new(OwnKind::Duration, 300, super::ownvalues::WEEK, &["m", "h"]);

// ------------------------------------------------------------------------------------- homefind
pub const HOMEFIND_SWITCH: &str = "home_suggestions";
pub const HOMEFIND_DISMISSED: &str = "home_suggestions_dismissed";
pub const DISMISSED_MAX: usize = 16;

#[cfg(test)]
mod tests {
    use super::*;
    use car_machine::vocab_gen::domain_vocabulary as v;

    fn words<T: Copy>(all: &[T], as_str: fn(T) -> &'static str) -> Vec<&'static str> {
        all.iter().map(|each| as_str(*each)).collect()
    }

    #[test]
    fn the_seams_lists_are_the_vocabularys() {
        assert_eq!(
            STYLES,
            words(v::ContinuationStyle::ALL, v::ContinuationStyle::as_str)
        );
        assert_eq!(
            CUSTOM_MODES,
            words(v::CustomMode::ALL, v::CustomMode::as_str)
        );
        assert_eq!(QUIET_DAYS, words(v::QuietDays::ALL, v::QuietDays::as_str));
        assert_eq!(
            RETRY_TIMINGS,
            words(v::RetryTiming::ALL, v::RetryTiming::as_str)
        );
        assert_eq!(
            CEILINGS,
            words(v::ChainCeiling::ALL, v::ChainCeiling::as_str)
        );
        assert_eq!(TASK_GUARDS, words(v::TaskGuard::ALL, v::TaskGuard::as_str));
        assert_eq!(
            CONTEXT_GUARDS,
            words(v::ContextGuard::ALL, v::ContextGuard::as_str)
        );
        assert_eq!(
            KEEP_AWAKE_MODES,
            words(v::KeepAwake::ALL, v::KeepAwake::as_str)
        );
        assert_eq!(AWAKE_CAPS, words(v::AwakeCap::ALL, v::AwakeCap::as_str));
        assert_eq!(SLEEP_WAITS, words(v::SleepWait::ALL, v::SleepWait::as_str));
        assert_eq!(STALL_WAITS, words(v::StallWait::ALL, v::StallWait::as_str));
        let waits: Vec<&str> = WAIT_SECONDS.iter().map(|(name, _)| *name).collect();
        assert_eq!(waits, words(v::RetryWait::ALL, v::RetryWait::as_str));
        assert_eq!(&QUIET_STARTS[1..], QUIET_TIMES);
    }
}
