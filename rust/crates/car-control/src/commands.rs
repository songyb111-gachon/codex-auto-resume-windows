//! `controlcli.dispatch`'s commands, each answered as the reference answers it.
//!
//! `run` holds the quiet ones (S5.1a): read from the state, the settings, the store, Codex's files and the
//! vocabulary (or, for the few that write, written to the settings and the files beside the state). `acting` holds
//! the rest (S5.1b): the ones that change a recovery (`control.actions`), start or stop the watcher, write the
//! sign-in entry or the power action, signal the icon (`demo`), or ask what the watcher's rules (`rescan`,
//! `detection-check`), the registry (`compat*`) or this PC's records (`own-report`, `diagnostics`) answer. What acts
//! on the machine goes through [`Host`](crate::host::Host).

use car_machine::json::{Map, Str, Value};

use crate::bridge::{GENERIC_ERROR, flag, ok_with, statistics_days};
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
            // Without `text`, the words are read; with it, set - or, for null, taken away.
            if payload.contains_key("text") {
                ok_with(
                    "result",
                    control.set_once_words(
                        field(payload, "interruption_id"),
                        field(payload, "thread_id"),
                        field(payload, "text"),
                    )?,
                )
            } else {
                ok_with(
                    "result",
                    control.once_words(field(payload, "interruption_id"))?,
                )
            }
        }
        _ => return acting(control, command, payload),
    };
    Ok(Some(reply))
}

/// The commands that change a recovery, start or stop the watcher, write the sign-in entry or the power action,
/// signal the icon, or ask what only the watcher's rules and the registry answer (S5.1b).
fn acting(control: &Control, command: &str, payload: &Map) -> Res<Option<Value>> {
    let reply = match command {
        "start-watcher" => ok_with("result", control.start_watcher()?),
        // It asks; it never kills, and it reports what the single-instance mutex said.
        "stop-watcher" => ok_with("result", control.stop_watcher()?),
        "clear-history" => ok_with("result", control.clear_history("gui")?),
        "cancel-all" => ok_with("result", control.cancel_all_pending("gui")?),
        "rescan" => ok_with("result", control.rescan("gui", true)?),
        "demo" => ok_with("result", control.show_demo()?),
        "power-action" => ok_with("result", control.power_options()?),
        "detection-check" => ok_with("result", control.detection_check()?),
        "own-report" => ok_with("result", control.own_report()?),
        "power-arm" => ok_with(
            "result",
            control.arm_power_action(&Value::Object(payload.clone()), "dashboard", false)?,
        ),
        "power-disarm" => {
            if !payload.is_empty() {
                return Err(Failure::Control(ControlError::plain(
                    "power-disarm takes no argument",
                )));
            }
            ok_with("result", control.disarm_power_action("dashboard")?)
        }
        "enabled" => ok_with("result", control.set_enabled(flag(payload)?)?),
        "startup" => {
            let on = flag(payload)?;
            ok_with(
                "startup_enabled",
                Value::Bool(control.set_startup_enabled(on)?),
            )
        }
        "cancel" => ok_with(
            "result",
            control.cancel_interruption(field(payload, "interruption_id"), "gui")?,
        ),
        "reset-budget" => ok_with(
            "result",
            control.reset_recovery_budget(field(payload, "interruption_id"), "gui")?,
        ),
        "retry-now" => ok_with(
            "result",
            control.request_retry_now(field(payload, "interruption_id"), "gui")?,
        ),
        "thread-enabled" => {
            let thread = field(payload, "thread_id");
            let on = flag(payload)?;
            ok_with("result", control.set_thread_enabled(thread, on, "gui")?)
        }
        "cancel-thread" => ok_with(
            "result",
            control.cancel_thread(field(payload, "thread_id"), "gui")?,
        ),
        "interruption-recovery" => {
            let on = flag(payload)?;
            ok_with(
                "result",
                control.set_interruption_recovery(
                    field(payload, "interruption_id"),
                    field(payload, "thread_id"),
                    on,
                    "gui",
                )?,
            )
        }
        "postpone" => ok_with(
            "result",
            control.postpone(
                field(payload, "interruption_id"),
                field(payload, "thread_id"),
                field(payload, "until"),
                field(payload, "preset"),
                field(payload, "minutes"),
                "gui",
            )?,
        ),
        "unpostpone" => ok_with(
            "result",
            control.unpostpone(
                field(payload, "interruption_id"),
                field(payload, "thread_id"),
                "gui",
            )?,
        ),
        "release-hold" => ok_with(
            "result",
            control.release_hold(
                field(payload, "interruption_id"),
                field(payload, "thread_id"),
                "gui",
            )?,
        ),
        "thread-tier" => {
            // The tier is named even to take it away - null - so a request that forgot it is refused.
            if !payload.contains_key("tier") {
                return Err(Failure::Control(ControlError::new(
                    "invalid tier",
                    "invalid_tier",
                )));
            }
            ok_with(
                "result",
                control.set_thread_tier(
                    field(payload, "thread_id"),
                    field(payload, "tier"),
                    field(payload, "interruption_id"),
                    "gui",
                )?,
            )
        }
        "project-rule" => {
            let Some(Value::Bool(always)) = payload.get("always") else {
                return Err(Failure::Control(ControlError::new(
                    "always must be true or false",
                    "invalid_enabled",
                )));
            };
            let labels = control.labels();
            ok_with(
                "result",
                control.set_project_rule(
                    field(payload, "interruption_id"),
                    field(payload, "thread_id"),
                    *always,
                    labels.as_ref(),
                    "gui",
                )?,
            )
        }
        "compatibility" => ok_with("compatibility", control.compatibility(payload)?),
        "compat-import" => ok_with("result", control.compat_import(payload)?),
        "compat-refresh" => ok_with("result", control.compat_refresh()?),
        "diagnostics" => ok_with("result", control.diagnostics(field(payload, "path"))?),
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
