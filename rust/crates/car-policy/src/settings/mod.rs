//! `settings.py`: the one authoritative definition of configurable policy (S2.2 seat).
//!
//! Every front end reads and writes through this module: one schema, one set of defaults, one validator, one
//! persistence path and one migration. Only *policy* is configurable, and an invalid or unknown value is never fatal
//! and never widens behaviour: it falls back to its default, the conservative choice. A write ([`validate_update`])
//! refuses instead, in the field's own words where it has any.
//!
//! Beside it, the modules the seat ports with it (each says which Python it replaces): `ownvalues`, `homes`,
//! `notice_kinds`, `memguard`, `schema` (`settings_schema.py`), `config` (`config.py`'s three settings functions, cut
//! C2), `managed`, `statusfile`, `poweraction`, `demo` and `selfcheck` (`domain/public.self_check`, cut C1). What the
//! settings read of S2.1's modules (`continuation`, `ladder`, `quiet`, `guards`, `power`, `needsyou`, `projects`, `failures`) is theirs, in `crate::classify`; `homefind` holds the one function of `homefind.py` they read. Paths are asked of [`os::Os`], handed in.
//! Held to the reference by `tests/rustdiff/diffs_settings_*.py`.

pub mod config;
pub mod demo;
pub mod homefind;
pub mod homes;
pub mod managed;
pub mod memguard;
pub mod notice_kinds;
pub mod os;
pub mod ownvalues;
pub mod poweraction;
pub mod schema;
pub mod selfcheck;
pub mod statusfile;
#[rustfmt::skip]
pub mod unicode_gen;
#[rustfmt::skip]
pub mod vocab_gen;

use std::io::Write;
use std::path::Path;

use car_machine::json::{self, Map, Options, Str, Value};
use car_machine::pyval::{self, Num, Py};
use car_words::l10n;

use crate::classify::text::has_non_space;
use crate::classify::{continuation, guards, ladder, needsyou, power, projects, quiet};
use os::Os;
use ownvalues::Own;
use vocab_gen::settings as words;

pub const CONFIG_VERSION: i64 = 2;
/// The most a settings file may hold (v0.6.23): 4 MiB.
pub const MAX_SETTINGS_BYTES: u64 = 4 * 1024 * 1024;
/// The longest Codex path Windows takes.
pub const CODEX_EXE_MAX: usize = 32767;
pub const CONFIGURABLE_CATEGORIES: &[&str] = words::CONFIGURABLE_CATEGORIES;
pub const NOTIFICATION_EVENTS: &[&str] = words::NOTIFICATION_EVENTS;
pub const FOLDED_DESIGN: &str = words::FOLDED_DESIGN;
pub const NOT_YET_OFFERED: &[&str] = words::NOT_YET_OFFERED;
pub const ROW_ACTION_FIELDS: &[&str] = words::ROW_ACTION_FIELDS;
pub const DASHBOARD_ONLY: &[&str] = words::DASHBOARD_ONLY;
pub const NEEDS_YOU_FIELDS: &[&str] = words::NEEDS_YOU_FIELDS;
/// A limit above its "high" is warned of on every surface that edits it.
pub const HIGH_LIMITS: &[(&str, i64)] = &[
    ("max_recovery_attempts", 8),
    ("max_no_progress", 5),
    ("max_chain_continuations", 8),
];
/// A notice told under another's switch (`GOVERNED_BY`).
pub const GOVERNED_BY: &[(&str, &str)] =
    &[("objection", "starting"), ("after_sleep", "interruption")];

/// What a field's raw value is coerced by (each coercer always answers a valid value).
#[derive(Clone, Copy, Debug)]
pub enum Coerce {
    Boolean,
    Int(i64, i64),
    Number(f64, f64),
    Choice(&'static [&'static str]),
    /// `continuation_style`: a folded style as the one it became, then a choice.
    Style,
    OptionalText,
    Custom,
    ByThread,
    Own(&'static [&'static str], &'static Own),
    Keys,
    Homes,
    Dismissed,
    NoticeKinds,
}

/// A field's default.
#[derive(Clone, Copy, Debug)]
pub enum FieldDefault {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(&'static str),
    EmptyList,
}

impl FieldDefault {
    pub fn value(self) -> Value {
        match self {
            FieldDefault::Null => Value::Null,
            FieldDefault::Bool(on) => Value::Bool(on),
            FieldDefault::Int(number) => Value::from(number),
            FieldDefault::Float(number) => Value::Float(number),
            FieldDefault::Str(text) => Value::from(text),
            FieldDefault::EmptyList => Value::Array(Vec::new()),
        }
    }
}

/// One setting: its name, its default and its coercer (`FIELDS[name]`).
#[derive(Clone, Copy, Debug)]
pub struct Field {
    pub name: &'static str,
    pub default: FieldDefault,
    pub coerce: Coerce,
}

const fn field(name: &'static str, default: FieldDefault, coerce: Coerce) -> Field {
    Field {
        name,
        default,
        coerce,
    }
}

use Coerce as C;
use FieldDefault as D;

/// `FIELDS`, in the order the Python builds it.
pub static FIELDS: &[Field] = &[
    field("max_recovery_attempts", D::Int(4), C::Int(1, 20)),
    field("max_no_progress", D::Int(3), C::Int(1, 10)),
    field("max_chain_continuations", D::Int(6), C::Int(1, 10)),
    field(
        "retry_timing",
        D::Str(ladder::DEFAULT_TIMING),
        C::Choice(words::RETRY_TIMINGS),
    ),
    field(
        "detection_lookback_hours",
        D::Float(6.0),
        C::Number(0.0, 168.0),
    ),
    field("notifications", D::Bool(true), C::Boolean),
    field("show_tray", D::Bool(true), C::Boolean),
    field("notification_card", D::Bool(true), C::Boolean),
    field("start_with_codex", D::Bool(false), C::Boolean),
    field(
        "theme",
        D::Str(words::DEFAULT_THEME),
        C::Choice(words::THEMES),
    ),
    field(
        "panel_theme",
        D::Str(words::DEFAULT_PANEL_THEME),
        C::Choice(words::PANEL_THEMES),
    ),
    field(
        "design",
        D::Str(words::DEFAULT_DESIGN),
        C::Choice(words::DESIGNS),
    ),
    field("reduce_motion", D::Bool(false), C::Boolean),
    field("codex_exe", D::Null, C::OptionalText),
    field("recover_usage_limit", D::Bool(true), C::Boolean),
    field("recover_network_transient", D::Bool(true), C::Boolean),
    field("recover_timeout", D::Bool(true), C::Boolean),
    field("recover_rate_limit_transient", D::Bool(true), C::Boolean),
    field("recover_server_5xx", D::Bool(true), C::Boolean),
    field("recover_stream_interrupted", D::Bool(true), C::Boolean),
    field("notify_interruption", D::Bool(true), C::Boolean),
    field("notify_starting", D::Bool(true), C::Boolean),
    field("notify_result", D::Bool(true), C::Boolean),
    field("notify_stopped", D::Bool(true), C::Boolean),
    field("notify_needs_you", D::Bool(false), C::Boolean),
    field("notify_needs_you_invalid", D::Bool(true), C::Boolean),
    field("notify_needs_you_policy", D::Bool(true), C::Boolean),
    field("notify_needs_you_auth", D::Bool(true), C::Boolean),
    field("notify_needs_you_failure", D::Bool(true), C::Boolean),
    field(
        needsyou::STALL_FIELD,
        D::Str(needsyou::DEFAULT_STALL),
        C::Own(needsyou::STALL_WAITS, &needsyou::OWN_STALL),
    ),
    field(needsyou::SOUND_FIELD, D::Bool(false), C::Boolean),
    field(
        "interface_language",
        D::Str(l10n::SYSTEM),
        C::Choice(l10n::CHOICES),
    ),
    field(
        "continuation_language",
        D::Str(words::FOLLOW_INTERFACE),
        C::Choice(words::CONTINUATION_LANGUAGES),
    ),
    field(
        "continuation_style",
        D::Str(continuation::DEFAULT_STYLE),
        C::Style,
    ),
    field(
        "custom_message_mode",
        D::Str(continuation::DEFAULT_CUSTOM_MODE),
        C::Choice(continuation::CUSTOM_MODES),
    ),
    field("custom_message", D::Null, C::Custom),
    field("custom_message_usage_limit", D::Null, C::Custom),
    field("custom_message_rate_limit_transient", D::Null, C::Custom),
    field("custom_message_network_transient", D::Null, C::Custom),
    field("custom_message_timeout", D::Null, C::Custom),
    field("custom_message_server_5xx", D::Null, C::Custom),
    field("custom_message_stream_interrupted", D::Null, C::Custom),
    field(continuation::BY_THREAD_FIELD, D::Null, C::ByThread),
    field(
        "quiet_hours_start",
        D::Str(quiet::DEFAULT_START),
        C::Own(quiet::STARTS, &quiet::OWN_CLOCK),
    ),
    field(
        "quiet_hours_end",
        D::Str(quiet::DEFAULT_END),
        C::Own(quiet::TIMES, &quiet::OWN_CLOCK),
    ),
    field(
        "quiet_hours_days",
        D::Str(quiet::DEFAULT_DAYS),
        C::Own(quiet::DAY_CHOICES, &quiet::OWN_DAYS),
    ),
    field(
        "default_tier",
        D::Str(words::DEFAULT_TIER),
        C::Choice(words::TIERS),
    ),
    field("objection_minutes", D::Int(5), C::Int(1, 60)),
    field("observe_only", D::Bool(false), C::Boolean),
    field(
        "new_conversation_policy",
        D::Str("resume"),
        C::Choice(words::NEW_CONVERSATION_POLICIES),
    ),
    field(
        "project_policy",
        D::Str(projects::DEFAULT_POLICY),
        C::Choice(words::PROJECT_POLICIES),
    ),
    field(projects::ALWAYS, D::Str(""), C::Keys),
    field(projects::NEVER, D::Str(""), C::Keys),
    field(
        "retry_wait_1",
        D::Str("s5"),
        C::Own(ladder::FIRST_WAITS, &ladder::OWN_FIRST),
    ),
    field(
        "retry_wait_2",
        D::Str("m15"),
        C::Own(ladder::LATER_WAITS, &ladder::OWN_LATER),
    ),
    field(
        "retry_wait_3",
        D::Str("m15"),
        C::Own(ladder::LATER_WAITS, &ladder::OWN_LATER),
    ),
    field(
        "retry_wait_4",
        D::Str("m15"),
        C::Own(ladder::LATER_WAITS, &ladder::OWN_LATER),
    ),
    field(
        "retry_wait_5",
        D::Str("m15"),
        C::Own(ladder::LATER_WAITS, &ladder::OWN_LATER),
    ),
    field("retry_jitter", D::Bool(false), C::Boolean),
    field(
        "chain_time_ceiling",
        D::Str(ladder::DEFAULT_CEILING),
        C::Own(ladder::CEILINGS, &ladder::OWN_CEILING),
    ),
    field(
        "task_changed_guard",
        D::Str(guards::DEFAULT_TASK_GUARD),
        C::Choice(guards::TASK_GUARDS),
    ),
    field(
        "context_guard",
        D::Str(guards::DEFAULT_CONTEXT_GUARD),
        C::Own(guards::CONTEXT_GUARDS, &guards::OWN_CONTEXT),
    ),
    field(
        power::SLEEP_FIELD,
        D::Str(power::DEFAULT_SLEEP),
        C::Own(power::SLEEP_WAITS, &power::OWN_SLEEP),
    ),
    field(power::NETWORK_FIELD, D::Bool(false), C::Boolean),
    field(
        power::KEEP_AWAKE_FIELD,
        D::Str(power::DEFAULT_KEEP_AWAKE),
        C::Choice(power::KEEP_AWAKE_MODES),
    ),
    field(
        power::AWAKE_CAP_FIELD,
        D::Str(power::DEFAULT_AWAKE_CAP),
        C::Own(power::AWAKE_CAPS, &power::OWN_AWAKE_CAP),
    ),
    field(
        memguard::GUARD_FIELD,
        D::Str(memguard::DEFAULT_MODE),
        C::Choice(memguard::MODES),
    ),
    field(
        memguard::LIMIT_FIELD,
        D::Str(memguard::DEFAULT_LIMIT),
        C::Own(memguard::LIMITS, &memguard::LIMIT_OWN),
    ),
    field(statusfile::FIELD, D::Bool(false), C::Boolean),
    field(homes::FIELD, D::EmptyList, C::Homes),
    field(homefind::SWITCH, D::Bool(true), C::Boolean),
    field(homefind::DISMISSED, D::EmptyList, C::Dismissed),
    field(
        "notice_click",
        D::Str("page"),
        C::Choice(words::NOTICE_CLICKS),
    ),
    field(notice_kinds::FIELD, D::EmptyList, C::NoticeKinds),
];

/// `FIELDS[name]`.
pub fn field_named(name: &str) -> Option<&'static Field> {
    FIELDS.iter().find(|field| field.name == name)
}

/// `OWN[name]`: the drop-downs that also take a value of the person's own.
pub fn own(name: &str) -> Option<&'static Own> {
    match field_named(name)?.coerce {
        C::Own(_, spec) => Some(spec),
        _ => None,
    }
}

/// `is_custom_text(name)`: whether a field holds Custom continuation text (not `custom_message_mode`).
pub fn is_custom_text(name: &str) -> bool {
    name.starts_with("custom_message") && name != "custom_message_mode"
}

/// `defaults()`: every setting at its default, in FIELDS' order.
pub fn defaults() -> Map {
    FIELDS
        .iter()
        .map(|field| (Str::from(field.name), field.default.value()))
        .collect()
}

/// `field_type(name)`: the JSON type a field's values have.
pub fn field_type(name: &str) -> &'static str {
    if name == continuation::BY_THREAD_FIELD {
        return "object";
    }
    match field_named(name).map(|field| field.default) {
        Some(D::EmptyList) => "array",
        Some(D::Bool(_)) => "boolean",
        Some(D::Int(_)) => "integer",
        Some(D::Float(_)) => "number",
        _ => "string",
    }
}

/// `ladder.previews()` as a surface is told it: each preset's waits, in the presets' order.
fn previews() -> Value {
    Value::Object(
        ladder::previews()
            .into_iter()
            .map(|(name, waits)| {
                (
                    Str::from(name),
                    Value::Array(waits.into_iter().map(Value::from).collect()),
                )
            })
            .collect(),
    )
}

/// `RANGES[name]`: what a surface is told of a field's range or choices.
pub fn ranges(name: &str) -> Option<Map> {
    let mut range = Map::new();
    let mut put = |key: &str, value: Value| {
        range.insert(Str::from(key), value);
    };
    let list = |items: &[&str]| Value::Array(items.iter().map(|each| Value::from(*each)).collect());
    let field = field_named(name)?;
    match (name, field.coerce) {
        (_, C::Int(low, high)) => {
            put("min", Value::from(low));
            put("max", Value::from(high));
            if let Some((_, high)) = HIGH_LIMITS.iter().find(|(limit, _)| *limit == name) {
                put("high", Value::from(*high));
            }
        }
        (_, C::Number(low, high)) => {
            put("min", Value::Float(low));
            put("max", Value::Float(high));
        }
        ("retry_timing", C::Choice(choices)) => {
            put("choices", list(choices));
            put("waits", previews());
        }
        ("notice_click", _) => return None,
        (_, C::Choice(choices)) => put("choices", list(choices)),
        (_, C::Style) => put("choices", list(continuation::STYLES)),
        (_, C::Own(choices, _)) => {
            put("choices", list(choices));
            if ladder::STEP_FIELDS.contains(&name) {
                let mut seconds = Map::new();
                for choice in choices {
                    let wait = ladder::WAIT_SECONDS
                        .iter()
                        .find(|(each, _)| each == choice)
                        .map_or(0, |(_, s)| *s);
                    seconds.insert(Str::from(*choice), Value::from(wait));
                }
                put("seconds", Value::Object(seconds));
            }
        }
        _ => return None,
    }
    Some(range)
}

// ------------------------------------------------------------------------------------------ errors

/// What a settings call refuses with, as the Python raises it.
#[derive(Clone, Debug, PartialEq)]
pub enum SettingsError {
    /// `SettingsError(message)`: a rejected write.
    Refused(Str),
    /// `Unreadable(reason, transient)`: a file that is there and cannot be read now, holds no JSON, or is too large.
    Unreadable { reason: String, transient: bool },
    /// Another Python exception that leaves the call as it is (its class): `RecursionError` from a file nested past
    /// the reader's depth, an `OSError` of the folder or the temporary file a save makes outside its own guard.
    Raised(&'static str),
}

impl SettingsError {
    fn refused(text: impl Into<String>) -> SettingsError {
        SettingsError::Refused(Str::from(text.into()))
    }

    /// The exception's class name.
    pub fn class(&self) -> &'static str {
        match self {
            SettingsError::Refused(_) => "SettingsError",
            SettingsError::Unreadable { .. } => "Unreadable",
            SettingsError::Raised(class) => class,
        }
    }

    /// Whether `except SettingsError` catches it (`Unreadable` is one).
    pub fn is_settings_error(&self) -> bool {
        !matches!(self, SettingsError::Raised(_))
    }

    /// `str(exc)`.
    pub fn message(&self) -> Str {
        match self {
            SettingsError::Refused(text) => text.clone(),
            SettingsError::Unreadable {
                reason,
                transient: true,
            } => Str::from(format!(
                "the settings file could not be read just now ({reason}); try again"
            )),
            SettingsError::Unreadable {
                reason,
                transient: false,
            } => Str::from(format!(
                "the settings file cannot be read ({reason}): it is kept as it is and nothing was saved; fix it, or \
                 Restore defaults sets it aside and starts again"
            )),
            SettingsError::Raised(_) => Str::default(),
        }
    }
}

/// The Python class of an OSError raised for `error`: car-machine's (car-config's `Paths::ensure` answers it too).
pub use car_machine::pyfile::os_error_class;

// ------------------------------------------------------------------------------------------ coercion

fn is_str_in(value: &Value, allowed: &[&str]) -> bool {
    matches!(value, Value::Str(text) if text.as_str().is_some_and(|text| allowed.contains(&text)))
}

/// The field's coercer: `coercer(raw, default)`, which always answers a valid value.
pub fn coerce_field(os: &dyn Os, field: &Field, raw: &Value) -> Value {
    let default = field.default.value();
    match field.coerce {
        C::Boolean => match raw {
            Value::Bool(_) => raw.clone(),
            _ => default,
        },
        C::Int(low, high) => match raw {
            Value::Int(int)
                if int
                    .as_i64()
                    .is_some_and(|number| low <= number && number <= high) =>
            {
                raw.clone()
            }
            _ => default,
        },
        C::Number(low, high) => match (raw, Num::of(raw)) {
            (Value::Int(_) | Value::Float(_), Some(number)) => {
                let inside = pyval::compare(Num::Real(low), number)
                    .is_some_and(|order| order.is_le())
                    && pyval::compare(number, Num::Real(high)).is_some_and(|order| order.is_le());
                if inside {
                    Value::Float(number.as_f64())
                } else {
                    default
                }
            }
            _ => default,
        },
        C::Choice(allowed) => {
            if is_str_in(raw, allowed) {
                raw.clone()
            } else {
                default
            }
        }
        C::Style => {
            let folded = continuation::fold_style(raw);
            if is_str_in(&folded, continuation::STYLES) {
                folded
            } else {
                default
            }
        }
        C::OptionalText => match raw {
            Value::Str(text) if has_non_space(text) && text.len() <= CODEX_EXE_MAX => raw.clone(),
            _ => default,
        },
        C::Custom => match raw {
            Value::Null => Value::Null,
            _ => match continuation::validate_custom(raw) {
                Ok(_) => raw.clone(),
                Err(_) => default,
            },
        },
        C::ByThread => continuation::coerce_by_thread(raw, &default),
        C::Own(choices, spec) => ownvalues::coerce(raw, &default, choices, spec),
        C::Keys => projects::coerce_keys(raw, &default),
        C::Homes => homes::coerce(os, raw, &default),
        C::Dismissed => homefind::coerce_dismissed(os, raw, &default),
        C::NoticeKinds => notice_kinds::coerce(raw, &default),
    }
}

/// `whole_text(value)`: whether every text in `value` can be written as UTF-8 (and the value as strict JSON).
pub fn whole_text(value: &Value) -> bool {
    json::to_string(value, &Options::wire()).is_ok()
}

/// `_storable(value, default)`: a stored field as it can be saved - the whole entries of a list or an object.
fn storable(value: Value, default: Value) -> Value {
    if whole_text(&value) {
        return value;
    }
    match value {
        Value::Object(map) => Value::Object(
            map.into_iter()
                .filter(|(key, item)| {
                    whole_text(&Value::Array(vec![Value::Str(key.clone()), item.clone()]))
                })
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.into_iter().filter(whole_text).collect()),
        _ => default,
    }
}

/// `coerce(raw)`: a complete settings dict from a candidate mapping; unknown keys dropped, invalid values defaulted.
pub fn coerce(os: &dyn Os, raw: &Value) -> Map {
    let mut values = defaults();
    if let Value::Object(given) = raw {
        for field in FIELDS {
            if let Some(found) = given.get(field.name) {
                let coerced = coerce_field(os, field, found);
                values.insert(
                    Str::from(field.name),
                    storable(coerced, field.default.value()),
                );
            }
        }
    }
    values
}

/// `_right_type(name, value)`: whether `value` is of this field's type, asked before anything looks at the value.
fn right_type(field: &Field, value: &Value) -> bool {
    match value {
        Value::Null => matches!(field.default, D::Null),
        Value::Bool(_) => field_type(field.name) == "boolean",
        Value::Int(_) => matches!(field_type(field.name), "integer" | "number"),
        Value::Float(_) => field_type(field.name) == "number",
        Value::Str(_) => field_type(field.name) == "string",
        Value::Object(_) => field_type(field.name) == "object",
        Value::Array(_) => field_type(field.name) == "array",
    }
}

/// `_refuse(name, value)`: the refusal for one field, in that field's own words where it has any.
fn refuse(name: &str, value: &Value) -> SettingsError {
    if is_custom_text(name)
        && name != continuation::BY_THREAD_FIELD
        && !matches!(value, Value::Null)
        && let Err(error) = continuation::validate_custom(value)
    {
        return SettingsError::refused(error.message);
    }
    if name == "design" && pyval::is(value, FOLDED_DESIGN) {
        return SettingsError::refused(format!(
            "invalid value for design: expected one of {}",
            words::DESIGNS.join(", ")
        ));
    }
    if name == "continuation_style"
        && let Value::Str(text) = value
        && continuation::FOLDED_STYLES
            .iter()
            .any(|(folded, _)| text.as_str() == Some(folded))
    {
        return SettingsError::refused(format!(
            "invalid value for continuation_style: expected one of {}",
            continuation::STYLES.join(", ")
        ));
    }
    SettingsError::refused(format!("invalid value for {name}"))
}

/// `validate_update(changes)`: strictly validate an explicit edit - a bad value is refused, never replaced.
pub fn validate_update(os: &dyn Os, changes: &Value) -> Result<Map, SettingsError> {
    let Value::Object(changes) = changes else {
        return Err(SettingsError::refused("settings must be an object"));
    };
    let mut unknown: Vec<&Str> = changes
        .keys()
        .filter(|name| name.as_str().is_none_or(|n| field_named(n).is_none()))
        .collect();
    unknown.sort();
    unknown.dedup();
    if !unknown.is_empty() {
        let mut message: Vec<u8> = b"unknown setting: ".to_vec();
        for (index, name) in unknown.iter().enumerate() {
            if index > 0 {
                message.extend_from_slice(b", ");
            }
            message.extend_from_slice(name.as_bytes());
        }
        return Err(SettingsError::Refused(
            Str::from_surrogatepass(message).expect("whole names"),
        ));
    }
    let mut clean = Map::new();
    for (name, value) in changes {
        let field = field_named(name.as_str().unwrap_or_default()).expect("known names only");
        if !right_type(field, value) {
            return Err(refuse(field.name, value));
        }
        match json::to_string(value, &Options::wire()) {
            Ok(_) => {}
            Err(json::Error::TooDeep) => return Err(SettingsError::Raised("RecursionError")),
            Err(_) => {
                return Err(SettingsError::refused(format!(
                    "invalid value for {}: it holds half of a character pair, which cannot be stored",
                    field.name
                )));
            }
        }
        let coerced = coerce_field(os, field, value);
        let same = pyval::eq(&coerced, value)
            || (field.name == "codex_exe" && matches!(value, Value::Null))
            || own(field.name)
                .and_then(|spec| ownvalues::canonical(Some(spec), value, &[]))
                .is_some_and(|spelled| pyval::eq(&spelled, &coerced));
        if !same {
            return Err(refuse(field.name, value));
        }
        clean.insert(name.clone(), coerced);
    }
    Ok(clean)
}

// ------------------------------------------------------------------------------------------ readers of values

fn get<'a>(values: &'a Value, name: &str) -> Option<&'a Value> {
    match values {
        Value::Object(map) => map.get(name),
        _ => None,
    }
}

/// `high_limits(values)`: the limits set above their "high", in the order they are shown.
pub fn high_limits(values: &Value) -> Vec<&'static str> {
    HIGH_LIMITS
        .iter()
        .filter(|(name, high)| match get(values, name) {
            Some(Value::Int(int)) => pyval::compare(
                Num::of(&Value::Int(int.clone())).expect("an int"),
                Num::Whole(i128::from(*high)),
            )
            .is_some_and(|order| order.is_gt()),
            _ => false,
        })
        .map(|(name, _)| *name)
        .collect()
}

fn choice_of(values: &Value, name: &str, allowed: &[&str], default: &'static str) -> Value {
    match get(values, name) {
        Some(found) if is_str_in(found, allowed) => found.clone(),
        _ => Value::from(default),
    }
}

/// `theme_preference(values)`: system, light or dark - never anything else.
pub fn theme_preference(values: &Value) -> Value {
    choice_of(values, "theme", words::THEMES, words::DEFAULT_THEME)
}

/// `design_preference(values)`: soft, classic or plain - never anything else.
pub fn design_preference(values: &Value) -> Value {
    choice_of(values, "design", words::DESIGNS, words::DEFAULT_DESIGN)
}

/// `tier_of(values, own)`: the conversation's own tier, or else the default in `values`.
pub fn tier_of(values: &Value, own: &Value) -> Value {
    if pyval::in_tuple(own, words::TIERS) {
        return own.clone();
    }
    choice_of(values, "default_tier", words::TIERS, words::DEFAULT_TIER)
}

/// `values or {}`: a falsy value reads as the empty dict; a truthy one that is not a dict has no `.get`.
fn mapping(values: &Value) -> Py<Option<&Map>> {
    match values {
        Value::Object(map) => Ok(Some(map)),
        other if !pyval::truthy(other) => Ok(None),
        _ => Err("AttributeError"),
    }
}

/// `category_enabled(values, category)`: whether automatic recovery is allowed for one failure category.
pub fn category_enabled(values: &Value, category: &str) -> Py<bool> {
    let key = format!("recover_{category}");
    let Some(field) = field_named(&key) else {
        return Ok(true);
    };
    let found = mapping(values)?.and_then(|map| map.get(key.as_str()).cloned());
    Ok(pyval::truthy(
        &found.unwrap_or_else(|| field.default.value()),
    ))
}

/// `notification_enabled(values, event)`.
pub fn notification_enabled(values: &Value, event: &str) -> Py<bool> {
    let map = mapping(values)?;
    let lookup = |key: &str, otherwise: Value| {
        map.and_then(|map| map.get(key).cloned())
            .unwrap_or(otherwise)
    };
    if !pyval::truthy(&lookup("notifications", Value::Bool(true))) {
        return Ok(false);
    }
    let governed = GOVERNED_BY
        .iter()
        .find(|(name, _)| *name == event)
        .map_or(event, |(_, by)| *by);
    let key = format!("notify_{governed}");
    let otherwise = field_named(&key).map_or(Value::Bool(true), |field| field.default.value());
    Ok(pyval::truthy(&lookup(&key, otherwise)))
}

// ------------------------------------------------------------------------------------------ persistence

/// `_fold_design(raw)` and `_fold_style(raw)`: a stored Still as Soft with Reduce motion on, a stored Careful as
/// Detailed.
fn fold(mut raw: Map) -> Map {
    if raw
        .get("design")
        .is_some_and(|design| pyval::is(design, FOLDED_DESIGN))
    {
        raw.insert(Str::from("design"), Value::from(words::DEFAULT_DESIGN));
        raw.insert(Str::from("reduce_motion"), Value::Bool(true));
    }
    if let Some(Value::Str(style)) = raw.get("continuation_style")
        && let Some((_, became)) = continuation::FOLDED_STYLES
            .iter()
            .find(|(folded, _)| style.as_str() == Some(folded))
    {
        raw.insert(Str::from("continuation_style"), Value::from(*became));
    }
    raw
}

/// `_migrate(raw)`: bring an older settings file forward without losing what the user chose.
pub fn migrate(raw: &Value) -> Map {
    let Value::Object(raw) = raw else {
        return Map::new();
    };
    let versioned = match raw.get("config_version") {
        Some(Value::Int(int)) => {
            int.as_i64().is_none_or(|version| version >= 1) && !int.to_string().starts_with('-')
        }
        Some(Value::Bool(on)) => *on,
        _ => false,
    };
    if !versioned {
        // v0.4.x wrote a flat file with no version marker: its fields that still exist keep their values.
        let kept: Map = FIELDS
            .iter()
            .filter_map(|field| {
                raw.get(field.name)
                    .map(|value| (Str::from(field.name), value.clone()))
            })
            .collect();
        return fold(kept);
    }
    fold(raw.clone())
}

/// `read(path)`: the settings, or Unreadable for a file that is there and cannot be read now, holds no JSON, or is
/// too large. No file (or a link) is the defaults.
pub fn read(os: &dyn Os, path: &Path) -> Result<Map, SettingsError> {
    if !std::fs::metadata(path).is_ok_and(|found| found.is_file()) || os.is_symlink(path) {
        return Ok(defaults());
    }
    let transient = |error: &std::io::Error| match os_error_class(error) {
        "FileNotFoundError" => Ok(defaults()),
        class => Err(SettingsError::Unreadable {
            reason: class.to_owned(),
            transient: true,
        }),
    };
    let size = match std::fs::metadata(path) {
        Ok(found) => found.len(),
        Err(error) => return transient(&error),
    };
    if size > MAX_SETTINGS_BYTES {
        return Err(SettingsError::Unreadable {
            reason: "too_large".into(),
            transient: false,
        });
    }
    let bytes = {
        use std::io::Read;
        // Python's open(): shared for reading and writing, not for deleting.
        let opened = car_machine::pyfile::open(path);
        let mut bytes = Vec::new();
        match opened.and_then(|mut file| file.read_to_end(&mut bytes)) {
            Ok(_) => bytes,
            Err(error) => return transient(&error),
        }
    };
    let Ok(text) = std::str::from_utf8(&bytes) else {
        return Err(SettingsError::Unreadable {
            reason: "UnicodeDecodeError".into(),
            transient: false,
        });
    };
    let raw = match car_machine::compat::loads(text) {
        Ok(raw) => raw,
        Err(car_machine::compat::LoadsError::Value) => {
            return Err(SettingsError::Unreadable {
                reason: "JSONDecodeError".into(),
                transient: false,
            });
        }
        Err(car_machine::compat::LoadsError::IntTooLong) => {
            return Err(SettingsError::Unreadable {
                reason: "ValueError".into(),
                transient: false,
            });
        }
        Err(car_machine::compat::LoadsError::Recursion) => {
            return Err(SettingsError::Raised("RecursionError"));
        }
    };
    Ok(coerce(os, &Value::Object(migrate(&raw))))
}

/// `load(path)`: read, falling back to the defaults for a file that cannot be read.
pub fn load(os: &dyn Os, path: &Path) -> Result<Map, SettingsError> {
    match read(os, path) {
        Err(SettingsError::Unreadable { .. }) => Ok(defaults()),
        other => other,
    }
}

/// `kept(path)`: what a save keeps - never the defaults for a file it cannot read.
pub fn kept(os: &dyn Os, path: &Path) -> Result<Map, SettingsError> {
    read(os, path)
}

/// The bytes `save` writes for a complete settings dict: with config_version, indent 2, keys sorted, UTF-8.
pub fn file_bytes(complete: &Map) -> Result<Vec<u8>, SettingsError> {
    let mut payload = complete.clone();
    payload.insert(Str::from("config_version"), Value::from(CONFIG_VERSION));
    match json::to_string(
        &Value::Object(payload),
        &Options::wire().indent(2).sort_keys(true),
    ) {
        Ok(text) => Ok(text.into_bytes()),
        Err(json::Error::Surrogate) => Err(SettingsError::Raised("UnicodeEncodeError")),
        Err(json::Error::TooDeep) => Err(SettingsError::Raised("RecursionError")),
        Err(_) => Err(SettingsError::Raised("ValueError")),
    }
}

/// A new file in `folder` named `<prefix><8 random characters>.json.tmp`, made exclusively (`tempfile.mkstemp`).
pub(crate) fn temporary_named(
    folder: &Path,
    prefix: &str,
) -> std::io::Result<(std::path::PathBuf, std::fs::File)> {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    const LETTERS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789_";
    let seed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |since| since.as_nanos() as u64)
        ^ u64::from(std::process::id()).rotate_left(32);
    let mut last = None;
    for attempt in 0..10_000u64 {
        let mut state = seed
            ^ COUNTER
                .fetch_add(1, Ordering::Relaxed)
                .wrapping_mul(0x9E37_79B9_7F4A_7C15)
            ^ attempt;
        let name: String = (0..8)
            .map(|_| {
                state = state
                    .wrapping_mul(6_364_136_223_846_793_005)
                    .wrapping_add(1_442_695_040_888_963_407);
                char::from(LETTERS[((state >> 33) % LETTERS.len() as u64) as usize])
            })
            .collect();
        let path = folder.join(format!("{prefix}{name}.json.tmp"));
        // tempfile.mkstemp's os.open(O_CREAT | O_EXCL): shared as the C runtime shares.
        match car_machine::pyfile::options()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(file) => return Ok((path, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => last = Some(error),
            Err(error) => return Err(error),
        }
    }
    Err(last.unwrap_or_else(|| std::io::Error::other("no temporary name")))
}

/// `save(path, values)`: persist a complete settings dict atomically; what was written.
pub fn save(os: &dyn Os, path: &Path, values: &Value) -> Result<Map, SettingsError> {
    let complete = coerce(os, values);
    let folder = path.parent().unwrap_or(Path::new("."));
    if let Err(error) = std::fs::create_dir_all(folder) {
        return Err(SettingsError::Raised(os_error_class(&error)));
    }
    let data = file_bytes(&complete)?;
    if data.len() as u64 > MAX_SETTINGS_BYTES {
        return Err(SettingsError::refused(format!(
            "the settings would be {} bytes, past the {MAX_SETTINGS_BYTES} allowed",
            data.len()
        )));
    }
    let (temporary, mut file) = temporary_named(folder, "settings.")
        .map_err(|error| SettingsError::Raised(os_error_class(&error)))?;
    let written = file
        .write_all(&data)
        .and_then(|_| file.flush())
        .and_then(|_| file.sync_all());
    drop(file);
    if written.and_then(|_| os.replace(&temporary, path)).is_err() {
        let _ = std::fs::remove_file(&temporary);
        return Err(SettingsError::refused("cannot save settings"));
    }
    Ok(complete)
}

/// `update(path, changes)`: validate and merge an edit into the stored settings.
pub fn update(os: &dyn Os, path: &Path, changes: &Value) -> Result<Map, SettingsError> {
    let clean = validate_update(os, changes)?;
    let mut merged = kept(os, path)?;
    for (name, value) in clean {
        merged.insert(name, value);
    }
    save(os, path, &Value::Object(merged))
}
