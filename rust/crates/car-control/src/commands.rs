//! `controlcli.dispatch`'s commands: the quiet ones, each answered as the reference answers it.
//!
//! Quiet means the answer is read from the state, the settings, the store, Codex's files and the vocabulary
//! (or, for the few that write, written to the settings and the files beside the state), without the engine
//! acting, the watcher running or a process starting. The rest of the bridge's commands - the ones that change a
//! recovery (`control.actions`), start or stop the watcher, Codex or the power action, run the registry
//! (`compat*`), the engine's own rules (`rescan`, `detection-check`) or the icon (`demo`) - are S5.1b's and
//! answer `unknown command` here until that seat ports them.

use car_machine::json::{Map, Str, Value};

use crate::bridge::{GENERIC_ERROR, ok_with, statistics_days};
use crate::error::{ControlError, Failure, Res};
use crate::layer::Control;

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

fn field<'a>(payload: &'a Map, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    payload.get(name).unwrap_or(&NULL)
}

/// One command: its reply, or None for a command this module has none of (the bridge says `unknown command`).
pub fn run(control: &Control, command: &str, payload: &Map) -> Res<Option<Value>> {
    let reply = match command {
        "status" => ok_with("status", control.get_status()?),
        "settings" => ok_with("settings", Value::Object(control.get_settings()?)),
        "describe" => ok_with("schema", Value::Array(control.describe_settings())),
        "defaults" => ok_with("settings", Value::Object(control.restore_defaults()?)),
        "strings" => ok_with_pairs(strings(control)?),
        "pending" => {
            let labels = control.labels();
            ok_with(
                "pending",
                Value::Array(control.list_pending(false, labels.as_ref())?),
            )
        }
        "pending-all" => ok_with("pending", Value::Array(control.list_pending(true, None)?)),
        "history" => {
            let labels = control.labels();
            ok_with("history", Value::Array(control.history(labels.as_ref())?))
        }
        "failure-seen" => ok_with("result", control.acknowledge_failure(None, false)?),
        "plugin-copy" => ok_with("result", control.plugin_copy()),
        "state-access" => ok_with("result", control.state_access()),
        "host-app" => ok_with("result", control.host_app()?),
        "dashboard" => dashboard(control)?,
        "update" => ok_with(
            "settings",
            Value::Object(control.update_settings(&Value::Object(payload.clone()))?),
        ),
        "timeline" => ok_with(
            "result",
            control.timeline(field(payload, "interruption_id"))?,
        ),
        "statistics" => {
            let days = statistics_days(payload)?;
            ok_with("result", control.statistics(days.as_ref())?)
        }
        "check-setting" => ok_with(
            "result",
            control.check_setting(field(payload, "name"), field(payload, "value"))?,
        ),
        "conversation-message" => {
            // The text is named even to take it away - null - so a request that forgot it is refused.
            if !payload.contains_key("text") {
                return Err(Failure::Control(ControlError::plain(
                    "a custom message has to be text",
                )));
            }
            ok_with(
                "result",
                control.set_conversation_message(
                    field(payload, "thread_id"),
                    field(payload, "text"),
                )?,
            )
        }
        "preview-continuation" => ok_with(
            "result",
            control.preview_continuation(
                field(payload, "category"),
                field(payload, "changes"),
                field(payload, "thread_id"),
                field(payload, "once_words"),
            )?,
        ),
        "home-suggestion" => ok_with("result", control.home_suggestion()?),
        "home-dismiss" => ok_with(
            "result",
            control.dismiss_home_suggestion(field(payload, "path"))?,
        ),
        "logs" => {
            let limit = payload.get("limit").cloned().unwrap_or(Value::from(500));
            ok_with(
                "result",
                control.search_logs(field(payload, "query"), &limit)?,
            )
        }
        "once-words" => {
            // Without `text`, the words are read; with it, set - or, for null, taken away (S5.1b's).
            if payload.contains_key("text") {
                return Ok(None);
            }
            ok_with(
                "result",
                control.once_words(field(payload, "interruption_id"))?,
            )
        }
        _ => return Ok(None),
    };
    Ok(Some(reply))
}

fn ok_with_pairs(mut pairs: Vec<(&str, Value)>) -> Value {
    pairs.insert(0, ("ok", Value::Bool(true)));
    object(pairs)
}

/// `dashboard`: what the Overview needs, in one round trip. Each part fails on its own.
fn dashboard(control: &Control) -> Res<Value> {
    let mut reply = Map::new();
    reply.insert(Str::from("ok"), Value::Bool(true));
    reply.insert(Str::from("status"), control.get_status()?);
    let labels = control.labels();
    let parts: [(&str, Res<Value>); 3] = [
        (
            "pending",
            control
                .list_pending(false, labels.as_ref())
                .map(Value::Array),
        ),
        (
            "history",
            control.history(labels.as_ref()).map(Value::Array),
        ),
        ("week", control.statistics(Some(&Value::from(7)))),
    ];
    for (key, read) in parts {
        match read {
            Ok(value) => {
                reply.insert(Str::from(key), value);
            }
            Err(Failure::Control(error)) => {
                reply.insert(Str::from(format!("{key}_error")), Value::Str(error.message));
            }
            Err(Failure::Other(_)) => {
                reply.insert(
                    Str::from(format!("{key}_error")),
                    Value::from(GENERIC_ERROR),
                );
            }
        }
    }
    Ok(Value::Object(reply))
}

/// `strings`: the interface vocabulary for the resolved language, handed over whole.
fn strings(control: &Control) -> Res<Vec<(&'static str, Value)>> {
    let host = &*control.host;
    let environ = |name: &str| host.environ(name);
    let windows = || host.windows_languages();
    let values = control.get_settings()?;
    let chosen = match values.get("interface_language") {
        Some(Value::Str(text)) => text.as_str().map(str::to_owned),
        _ => None,
    };
    car_words::l10n::set_preference(chosen.as_deref(), &environ, &windows);
    let language = car_words::interface::language(&environ, &windows);
    let catalog = car_words::interface::catalog(&environ, &windows);
    let mut strings = Map::new();
    for (key, text) in catalog {
        strings.insert(Str::from(key), Value::from(text));
    }
    let mut endonyms = Map::new();
    for (locale, name) in car_words::l10n::offered_endonyms() {
        endonyms.insert(Str::from(locale), Value::from(name));
    }
    Ok(vec![
        ("language", Value::from(language)),
        ("strings", Value::Object(strings)),
        ("preference", Value::from(car_words::l10n::preference())),
        (
            "system_language",
            Value::from(car_words::l10n::from_system(&environ, &windows)),
        ),
        ("endonyms", Value::Object(endonyms)),
    ])
}
