//! `ui/popup/model.py` (the v0.6.26 final's): what the popup is showing, worked out from what the watcher said.
//!
//! The rows, their order, the word for what is happening, and what a click on each does - a pure function of the
//! snapshot. The header's word (`activity`), its light, the icon's attention and the icon's own word from its tick
//! snapshot are the rules every surface keeps (tests/data/light_states.json). Rows and statuses are the control
//! layer's dicts, read as the reference reads them: a value of the wrong kind raises what Python raises.

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_public::IMPORTANCE_TIERS;
use car_machine::vocab_gen::domain_states::WAITING;
use car_policy::classify::clock::LocalClock;
use car_policy::classify::reasons;
use car_words::words::{countdown, usage_line};

use super::words::{kept, one_line, say};
use crate::py::{self, object, str_of};
use crate::seam::{PopupControl, Raised};
use crate::usage;

pub const MAX_TASKS: usize = 3;
pub const NOTICE_SECONDS: f64 = 4.0;
pub const CLICK_AWAY_SECONDS: f64 = 0.5;
pub const DOUBLE_CLICK_SECONDS: f64 = 0.6;
pub const KEY_REPEAT_SECONDS: f64 = 0.3;
pub const CONTROL_CALLS: [&str; 10] = [
    "list_pending",
    "get_status",
    "set_enabled",
    "set_interruption_recovery",
    "postpone",
    "unpostpone",
    "release_hold",
    "set_thread_tier",
    "set_project_rule",
    "set_once_words",
];
pub const POSTPONE_PRESETS: [&str; 4] = ["30_minutes", "1_hour", "3_hours", "tomorrow_morning"];
pub const ROW_DIALOGS: [&str; 2] = ["message", "once_words"];
pub const STALE_CODES: [&str; 3] = [
    "no_such_interruption",
    "thread_mismatch",
    "already_finished",
];
pub const STATES: [&str; 6] = [
    "monitoring",
    "waiting",
    "checking",
    "recovering",
    "paused",
    "attention",
];
pub const ATTENTION_OVERLAYS: [&str; 6] = [
    "compatibility_blocked",
    "compatibility_failed_here",
    "engine_unavailable",
    "watcher_not_ticking",
    "app_server_unmatched",
    "codex_changed",
];
pub const HELD_OVERLAY: &str = "held";
pub const MOVING_CODES: [&str; 5] = [
    "submission_claimed",
    "submitted",
    "withdrawing",
    "turn_running",
    "turn_finishing",
];
pub const EXTRA: &str = "advanced";
pub const ROW_ACTIONS: [&str; 6] = [
    "postpone",
    "unpostpone",
    "release",
    "tier",
    "project",
    "unsay",
];

/// What the model's words need beside the catalog: the language this process speaks (`l10n.current()`, which
/// `kept` asks first) and the local clock the usage line's reset times are read on.
#[derive(Clone, Copy)]
pub struct Ctx<'a> {
    pub current: &'a str,
    pub clock: &'a dyn LocalClock,
}

static NULL: Value = Value::Null;

fn empty() -> Value {
    Value::Object(Map::new())
}

/// `value or {}` then `.get(key)`.
fn get_or<'a>(value: &'a Value, key: &str) -> Py<&'a Value> {
    py::get_or_empty(value, key)
}

/// `(row.get("overlays") or ())`.
fn overlays_of(row: &Value) -> Py<Value> {
    let found = pyval::get(row, "overlays")?;
    Ok(if pyval::truthy(found) {
        found.clone()
    } else {
        Value::Array(Vec::new())
    })
}

/// `_blocked(watcher)` (v0.6.26).
pub fn blocked(watcher: &Value) -> bool {
    let check = match watcher {
        Value::Object(map) => map.get("self_check").unwrap_or(&NULL),
        _ => &NULL,
    };
    matches!(check, Value::Object(map) if !matches!(map.get("blocked"), None | Some(Value::Null)))
}

/// `is_waiting(row)`: `row.get("state") in machine.WAITING`, a frozenset.
pub fn is_waiting(row: &Value) -> Py<bool> {
    let state = pyval::get(row, "state")?;
    pyval::in_set(state, WAITING)
}

/// `urgency(row)`: most urgent first - work already in Codex, then the soonest check, then the oldest.
pub fn urgency(row: &Value) -> Py<Vec<Value>> {
    let at = pyval::get(row, "eligible_at")?;
    let zero = Value::from(0);
    Ok(vec![
        Value::from(if is_waiting(row)? { 1 } else { 0 }),
        if matches!(at, Value::Null) {
            Value::Float(f64::INFINITY)
        } else {
            at.clone()
        },
        py::or(pyval::get(row, "detected_at")?, &zero).clone(),
        Value::from(str_of(py::or(
            pyval::get(row, "interruption_id")?,
            &Value::from(""),
        ))),
    ])
}

fn any_rows(rows: &[Value], test: &dyn Fn(&Value) -> Py<bool>) -> Py<bool> {
    for row in rows {
        if test(row)? {
            return Ok(true);
        }
    }
    Ok(false)
}

/// `watcher_known_running(status, rows)`.
pub fn watcher_known_running(status: &Value, rows: Option<&[Value]>) -> Py<bool> {
    if !matches!(get_or(status, "watcher_running")?, Value::Bool(true)) {
        return Ok(false);
    }
    let unavailable = any_rows(rows.unwrap_or(&[]), &|row| {
        py::contains(&overlays_of(row)?, "engine_unavailable")
    })?;
    Ok(!unavailable)
}

/// `light_for(status, word, rows)`: the word's light, or "idle" for a watcher not known to be running.
pub fn light_for(status: &Value, word: &str, rows: Option<&[Value]>) -> Py<String> {
    Ok(if watcher_known_running(status, rows)? {
        word.to_owned()
    } else {
        "idle".to_owned()
    })
}

/// The watcher of a status (`status.get("watcher") or {}`).
fn watcher_of(status: &Value) -> Py<Value> {
    let found = get_or(status, "watcher")?;
    Ok(if pyval::truthy(found) {
        found.clone()
    } else {
        empty()
    })
}

fn engine_trouble(watcher: &Value) -> Py<bool> {
    let state = pyval::get(watcher, "engine_state")?;
    Ok(pyval::is(state, "incompatible") || pyval::is(state, "failed_here"))
}

/// `activity(status, rows, now)`: the one word the header says.
pub fn activity(status: &Value, rows: Option<&[Value]>, now: &Value) -> Py<&'static str> {
    let status = if pyval::truthy(status) {
        status.clone()
    } else {
        empty()
    };
    let known: &[Value] = rows.unwrap_or(&[]);
    let watcher = watcher_of(&status)?;
    if !watcher_known_running(&status, Some(known))? {
        return Ok("attention");
    }
    let unwell = matches!(pyval::get(&status, "upgrade_pending")?, Value::Bool(true))
        || matches!(pyval::get(&watcher, "ticking")?, Value::Bool(false))
        || engine_trouble(&watcher)?
        || blocked(&watcher)
        || any_rows(known, &|row| {
            py::meets(&overlays_of(row)?, &ATTENTION_OVERLAYS)
        })?;
    if unwell {
        return Ok("attention");
    }
    if any_rows(known, &|row| py::contains(&overlays_of(row)?, HELD_OVERLAY))? {
        return Ok("attention");
    }
    if !matches!(pyval::get(&status, "enabled")?, Value::Bool(true)) {
        return Ok("paused");
    }
    let codes = py::or(pyval::get(&status, "codes")?, &empty()).clone();
    let moving = any_rows(known, &|row| Ok(!is_waiting(row)?))? || {
        let mut found = false;
        for code in MOVING_CODES {
            let count = py::or(pyval::get(&codes, code)?, &Value::from(0)).clone();
            if pyval::greater(&count, &Value::from(0))? {
                found = true;
                break;
            }
        }
        found
    };
    if moving {
        return Ok("recovering");
    }
    let due = any_rows(known, &|row| {
        let at = pyval::get(row, "eligible_at")?;
        Ok(!matches!(at, Value::Null) && pyval::less_or_equal(at, now)?)
    })?;
    if due {
        return Ok("checking");
    }
    if !known.is_empty() {
        return Ok("waiting");
    }
    let pending = py::or(pyval::get(&status, "pending")?, &Value::from(0)).clone();
    Ok(if pyval::greater(&pending, &Value::from(0))? {
        "waiting"
    } else {
        "monitoring"
    })
}

/// `icon_attention(status, rows)`: whether the open popup tells the icon that a person must act.
pub fn icon_attention(status: &Value, rows: Option<&[Value]>) -> Py<bool> {
    let status = if pyval::truthy(status) {
        status.clone()
    } else {
        empty()
    };
    let watcher = watcher_of(&status)?;
    Ok(
        matches!(pyval::get(&status, "watcher_running")?, Value::Bool(false))
            || matches!(pyval::get(&watcher, "ticking")?, Value::Bool(false))
            || engine_trouble(&watcher)?
            || blocked(&watcher)
            || any_rows(rows.unwrap_or(&[]), &|row| {
                py::meets(&overlays_of(row)?, &ATTENTION_OVERLAYS)
            })?,
    )
}

/// `snapshot_activity(snapshot, now, attention)`: the same word from the icon's own tick snapshot.
pub fn snapshot_activity(snapshot: &Value, now: &Value, attention: bool) -> Py<&'static str> {
    let snapshot = if pyval::truthy(snapshot) {
        snapshot.clone()
    } else {
        empty()
    };
    if attention {
        return Ok("attention");
    }
    let get = |key: &str| pyval::get(&snapshot, key);
    if pyval::truthy(get("held")?) || pyval::truthy(get("unconfirmed")?) {
        return Ok("attention");
    }
    let enabled = match &snapshot {
        Value::Object(map) => map.get("enabled").cloned().unwrap_or(Value::Bool(true)),
        _ => Value::Bool(true),
    };
    if pyval::truthy(&snapshot) && !pyval::truthy(&enabled) {
        return Ok("paused");
    }
    if pyval::truthy(get("unmatched")?) || pyval::truthy(get("blocked")?) {
        return Ok("attention");
    }
    if pyval::truthy(get("running")?) {
        return Ok("recovering");
    }
    if pyval::truthy(get("waiting")?) {
        let due = get("next_at")?;
        return Ok(
            if !matches!(due, Value::Null) && pyval::less_or_equal(due, now)? {
                "checking"
            } else {
                "waiting"
            },
        );
    }
    Ok("monitoring")
}

fn put(map: &mut Map, key: &str, value: Value) {
    map.insert(Str::from(key), value);
}

/// `task_item(row, strings, now, keep)`: one pending recovery as the window shows it.
pub fn task_item(
    row: &Value,
    strings: &Map,
    now: &Value,
    keep: &dyn Fn(&str) -> String,
) -> Py<Map> {
    let unknown = Value::from("unknown");
    let category = py::or(pyval::get(row, "category")?, &unknown).clone();
    let usage = reasons::has_reset_time(&category)?;
    let at = pyval::get(row, "eligible_at")?.clone();
    let mut seconds: Option<f64> = None;
    let mut status = if !is_waiting(row)? {
        say(strings, "activity.recovering", &[])
    } else if matches!(at, Value::Null) {
        say(strings, "activity.waiting", &[])
    } else {
        let left = pyval::minus(&at, now)?;
        let left = if left > 0.0 { left } else { 0.0 };
        seconds = Some(left);
        let mut key = if usage && pyval::truthy(pyval::get(row, "reset_at")?) {
            "popup.until_reset"
        } else {
            "popup.until_retry"
        };
        if pyval::is(pyval::get(row, "reason")?, "offline") {
            key = "popup.offline";
        }
        say(
            strings,
            key,
            &[("time", keep(&countdown(&Value::Float(left))?))],
        )
    };
    let overlays = py::text_set(&overlays_of(row)?)?;
    let has = |name: &str| overlays.iter().any(|each| pyval::is(each, name));
    let enabled = match row {
        Value::Object(map) => {
            pyval::truthy(map.get("thread_enabled").unwrap_or(&Value::Bool(true)))
        }
        _ => return Err("AttributeError"),
    };
    let waiting = is_waiting(row)?;
    if has("held") && waiting {
        status = say(strings, "popup.held", &[]);
        seconds = None;
    } else if has("app_server_unmatched") && waiting {
        status = say(strings, "overlay.app_server_unmatched", &[]);
        seconds = None;
    } else if has("codex_changed") && waiting {
        status = say(strings, "overlay.codex_changed", &[]);
        seconds = None;
    }
    let attention = ATTENTION_OVERLAYS.iter().any(|name| has(name));
    let tone = if attention || !reasons::is_recoverable(&category)? {
        "warning"
    } else if !enabled || has("paused") || has("thread_disabled") || has("held") {
        "paused"
    } else {
        "waiting"
    };
    let name = pyval::get(row, "name")?;
    let shown_name = match name {
        Value::Str(text) if !car_machine::pytext::strip(&py::text_of(text)).is_empty() => {
            one_line(name, 120)
        }
        _ => say(strings, "msg.toast_unnamed", &[]),
    };
    let cancel_requested = pyval::truthy(pyval::get(row, "cancel_requested")?);
    let held = !matches!(pyval::get(row, "hold")?, Value::Null)
        && !pyval::truthy(pyval::get(row, "terminal")?)
        && !cancel_requested;
    let postponed = py::or(pyval::get(row, "postponed_until")?, &Value::from(0)).clone();
    let mut item = Map::new();
    put(
        &mut item,
        "interruption_id",
        pyval::get(row, "interruption_id")?.clone(),
    );
    put(
        &mut item,
        "thread_id",
        pyval::get(row, "thread_id")?.clone(),
    );
    put(&mut item, "name", Value::from(shown_name));
    put(
        &mut item,
        "reason",
        Value::from(say(strings, &reasons::label_key(&category)?, &[])),
    );
    put(&mut item, "tone", Value::from(tone));
    put(&mut item, "status", Value::from(status));
    put(
        &mut item,
        "at_zero",
        Value::Bool(seconds.is_some_and(|left| left <= 0.0)),
    );
    put(
        &mut item,
        "check_label",
        Value::from(say(strings, "pending.col_resume", &[])),
    );
    put(&mut item, "checked", Value::Bool(enabled));
    put(&mut item, "busy", Value::Bool(false));
    put(
        &mut item,
        "waiting",
        Value::Bool(waiting && !cancel_requested),
    );
    put(&mut item, "held", Value::Bool(held));
    put(&mut item, "tier", pyval::get(row, "tier")?.clone());
    put(
        &mut item,
        "postponed",
        Value::Bool(pyval::greater(&postponed, now)?),
    );
    put(
        &mut item,
        "once_words",
        Value::Bool(matches!(pyval::get(row, "once_words")?, Value::Bool(true))),
    );
    Ok(item)
}

fn entry(text: String, action: Value, enabled: bool, checked: bool, items: Value) -> Value {
    object([
        ("text", Value::from(text)),
        ("action", action),
        ("enabled", Value::Bool(enabled)),
        ("checked", Value::Bool(checked)),
        ("items", items),
    ])
}

fn tuple(items: Vec<Value>) -> Value {
    Value::Array(items)
}

/// `row_menu(task, strings, default_tier)`: a task row's own menu, as data (v0.6.11, v0.6.23).
pub fn row_menu(task: &Value, strings: &Map, default_tier: &Value) -> Py<Value> {
    let key = pyval::get(task, "interruption_id")?.clone();
    let thread = pyval::get(task, "thread_id")?.clone();
    if !pyval::truthy(&key) || !pyval::truthy(&thread) {
        return Ok(Value::Array(Vec::new()));
    }
    let waiting = pyval::truthy(pyval::get(task, "waiting")?);
    let mut postpone: Vec<Value> = POSTPONE_PRESETS
        .iter()
        .map(|preset| {
            entry(
                say(strings, &format!("postpone.{preset}"), &[]),
                tuple(vec![
                    Value::from("postpone"),
                    key.clone(),
                    thread.clone(),
                    Value::from(*preset),
                ]),
                waiting,
                false,
                Value::Null,
            )
        })
        .collect();
    postpone.push(Value::Null);
    postpone.push(entry(
        say(strings, "menu.unpostpone", &[]),
        tuple(vec![Value::from("unpostpone"), key.clone(), thread.clone()]),
        waiting && pyval::truthy(pyval::get(task, "postponed")?),
        false,
        Value::Null,
    ));
    let default = IMPORTANCE_TIERS
        .iter()
        .copied()
        .find(|tier| pyval::is(default_tier, tier))
        .unwrap_or(IMPORTANCE_TIERS[0]);
    let own = pyval::get(task, "tier")?.clone();
    let worded = matches!(pyval::get(task, "once_words")?, Value::Bool(true));
    let mut writing = vec![
        Value::Null,
        entry(
            say(strings, "menu.conversation_message", &[]),
            tuple(vec![
                Value::from("dashboard_row"),
                Value::from("message"),
                key.clone(),
                thread.clone(),
            ]),
            true,
            false,
            Value::Null,
        ),
        entry(
            say(
                strings,
                if worded {
                    "menu.once_words_change"
                } else {
                    "menu.once_words_add"
                },
                &[],
            ),
            tuple(vec![
                Value::from("dashboard_row"),
                Value::from("once_words"),
                key.clone(),
                thread.clone(),
            ]),
            waiting,
            false,
            Value::Null,
        ),
    ];
    if worded {
        writing.push(entry(
            say(strings, "menu.once_words_remove", &[]),
            tuple(vec![Value::from("unsay"), key.clone(), thread.clone()]),
            true,
            false,
            Value::Null,
        ));
    }
    let mut tiers = vec![entry(
        say(
            strings,
            "choice.tier_default",
            &[("tier", say(strings, &format!("choice.{default}"), &[]))],
        ),
        tuple(vec![
            Value::from("tier"),
            key.clone(),
            thread.clone(),
            Value::Null,
        ]),
        true,
        matches!(own, Value::Null),
        Value::Null,
    )];
    for tier in IMPORTANCE_TIERS {
        tiers.push(entry(
            say(strings, &format!("choice.{tier}"), &[]),
            tuple(vec![
                Value::from("tier"),
                key.clone(),
                thread.clone(),
                Value::from(*tier),
            ]),
            true,
            pyval::eq(&own, &Value::from(*tier)),
            Value::Null,
        ));
    }
    let mut menu = vec![
        entry(
            say(strings, "menu.postpone", &[]),
            Value::Null,
            waiting,
            false,
            Value::Array(postpone),
        ),
        entry(
            say(strings, "action.continue", &[]),
            tuple(vec![Value::from("release"), key.clone(), thread.clone()]),
            pyval::truthy(pyval::get(task, "held")?),
            false,
            Value::Null,
        ),
        Value::Null,
        entry(
            say(strings, "menu.tier", &[]),
            Value::Null,
            true,
            false,
            Value::Array(tiers),
        ),
        entry(
            say(strings, "menu.project_always", &[]),
            tuple(vec![
                Value::from("project"),
                key.clone(),
                thread.clone(),
                Value::Bool(true),
            ]),
            true,
            false,
            Value::Null,
        ),
        entry(
            say(strings, "menu.project_never", &[]),
            tuple(vec![
                Value::from("project"),
                key.clone(),
                thread.clone(),
                Value::Bool(false),
            ]),
            true,
            false,
            Value::Null,
        ),
    ];
    menu.extend(writing);
    Ok(Value::Array(menu))
}

/// `newest_reading(status)`: the usage reading the popup shows (the v0.6.26 final's `domain/usage.newest`).
pub fn newest_reading(status: &Value) -> Py<Value> {
    let status = if pyval::truthy(status) {
        status.clone()
    } else {
        empty()
    };
    let watcher = watcher_of(&status)?;
    let reading = pyval::get(&watcher, "usage")?.clone();
    let added = pyval::get(&status, EXTRA)?.clone();
    usage::newest(&reading, &added)
}

/// `view_model(rows, status, strings, now, notice=..., error=...)`: everything the window says, as plain values.
/// `rows` is None until the first read; `status` is `Value::Null` where it could not be read.
pub fn view_model(
    ctx: &Ctx,
    rows: Option<&[Value]>,
    status: &Value,
    strings: &Map,
    now: &Value,
    notice: Value,
    error: Value,
) -> Py<Map> {
    let known = rows.is_some();
    // `sorted(rows or [], key=urgency)`: every key first, then the comparisons.
    let mut keyed = Vec::new();
    for row in rows.unwrap_or(&[]) {
        keyed.push((urgency(row)?, row.clone()));
    }
    let ordered: Vec<Value> = py::sorted_by(&keyed, &|a: &(Vec<Value>, Value), b| {
        py::tuple_less(&a.0, &b.0)
    })?
    .into_iter()
    .map(|(_, row)| row)
    .collect();
    let mut waiting = Vec::new();
    for row in &ordered {
        if is_waiting(row)? {
            waiting.push(row);
        }
    }
    let mut due = Vec::new();
    for row in &waiting {
        let at = pyval::get(row, "eligible_at")?;
        if !matches!(at, Value::Null) {
            due.push(at);
        }
    }
    let dash = "\u{2014}";
    let state = activity(status, known.then_some(ordered.as_slice()), now)?;
    let keep = kept(strings, ctx.current);
    let mut tasks = Vec::new();
    for row in ordered.iter().take(MAX_TASKS) {
        tasks.push(task_item(row, strings, now, &keep)?);
    }
    let more = ordered.len() - tasks.len();
    let paused = match status {
        Value::Null => Value::Null,
        _ => Value::Bool(!matches!(pyval::get(status, "enabled")?, Value::Bool(true))),
    };
    let next = if due.is_empty() {
        dash.to_owned()
    } else {
        let left = pyval::minus(py::min_of(&due)?, now)?;
        countdown(&Value::Float(if left > 0.0 { left } else { 0.0 }))?
    };
    let counts = Value::Array(vec![
        Value::Array(vec![
            Value::from(say(strings, "popup.count_waiting", &[])),
            Value::from(if known {
                waiting.len().to_string()
            } else {
                dash.to_owned()
            }),
        ]),
        Value::Array(vec![
            Value::from(say(strings, "popup.count_recovering", &[])),
            Value::from(if known {
                (ordered.len() - waiting.len()).to_string()
            } else {
                dash.to_owned()
            }),
        ]),
        Value::Array(vec![
            Value::from(say(strings, "popup.next_check", &[])),
            Value::from(next),
        ]),
    ]);
    let zero = tasks
        .iter()
        .any(|task| matches!(task.get("at_zero"), Some(Value::Bool(true))));
    let observe = !matches!(status, Value::Null)
        && matches!(pyval::get(status, "observe_only")?, Value::Bool(true))
        && !pyval::truthy(&paused);
    let reading = newest_reading(status)?;
    let say_line = |key: &str, fields: &[(&str, String)]| say(strings, key, fields);
    let clock = ctx.clock;
    let local = |at: f64| {
        clock
            .localtime(at)
            .map(|tm| (tm.year, tm.mon, tm.mday, tm.hour, tm.min))
            .unwrap_or((1970, 1, 1, 0, 0))
    };
    let usage_note = usage_line(&reading, &say_line, now, &local, &keep)?;
    let mut vm = Map::new();
    put(
        &mut vm,
        "title",
        Value::from(say(strings, "tray.title", &[])),
    );
    put(&mut vm, "state", Value::from(state));
    put(
        &mut vm,
        "light",
        Value::from(light_for(
            status,
            state,
            known.then_some(ordered.as_slice()),
        )?),
    );
    put(
        &mut vm,
        "state_text",
        Value::from(say(strings, &format!("activity.{state}"), &[])),
    );
    put(&mut vm, "counts", counts);
    put(
        &mut vm,
        "tasks",
        Value::Array(tasks.into_iter().map(Value::Object).collect()),
    );
    put(
        &mut vm,
        "more",
        if more > 0 {
            Value::from(say(strings, "popup.more", &[("n", more.to_string())]))
        } else {
            Value::Null
        },
    );
    put(
        &mut vm,
        "empty",
        if known && ordered.is_empty() {
            Value::from(say(strings, "popup.nothing", &[]))
        } else {
            Value::Null
        },
    );
    put(
        &mut vm,
        "zero_note",
        if zero {
            Value::from(say(strings, "popup.zero_note", &[]))
        } else {
            Value::Null
        },
    );
    put(&mut vm, "notice", notice);
    put(&mut vm, "error", error);
    put(&mut vm, "paused", paused.clone());
    put(
        &mut vm,
        "toggle_text",
        Value::from(say(
            strings,
            if pyval::truthy(&paused) {
                "action.resume"
            } else {
                "action.pause"
            },
            &[],
        )),
    );
    put(&mut vm, "toggle_busy", Value::Bool(false));
    put(
        &mut vm,
        "dashboard_text",
        Value::from(say(strings, "popup.open_dashboard", &[])),
    );
    put(
        &mut vm,
        "observe_note",
        if observe {
            Value::from(say(strings, "popup.observe_only", &[]))
        } else {
            Value::Null
        },
    );
    put(
        &mut vm,
        "usage_note",
        usage_note.map_or(Value::Null, Value::from),
    );
    Ok(vm)
}

/// `busy_key(action)`.
pub fn busy_key(action: &[Value]) -> Py<Option<Vec<Value>>> {
    let Some(kind) = action.first() else {
        return Ok(None);
    };
    let at = |index: usize| action.get(index).cloned().ok_or("IndexError");
    if pyval::is(kind, "recovery") {
        return Ok(Some(vec![Value::from("recovery"), at(1)?]));
    }
    if pyval::is(kind, "enabled") {
        return Ok(Some(vec![Value::from("enabled")]));
    }
    if ROW_ACTIONS.iter().any(|name| pyval::is(kind, name)) {
        return Ok(Some(vec![Value::from("row"), at(1)?]));
    }
    Ok(None)
}

/// The Dashboard opener `perform` is given: no row (`dashboard()`), or one row and its dialog
/// (`dashboard(row=(dialog, interruption_id, thread_id))`).
pub type Dashboard<'a> = &'a dyn Fn(Option<(Value, Value, Value)>) -> Result<Value, Raised>;

/// `perform(action, control, source=..., dashboard=...)`: run one action against the control layer, called on a
/// worker thread. ("ok", payload), ("refused", code) for a coded refusal, or ("failed", name).
pub fn perform(
    action: &[Value],
    control: &dyn PopupControl,
    source: Option<&Value>,
    dashboard: Option<Dashboard>,
) -> (String, Value) {
    let raised = |class: &'static str| Raised::new(class);
    let run = || -> Result<Option<Value>, Raised> {
        let kind = action.first().cloned().unwrap_or(Value::Null);
        let unpack = |count: usize| -> Result<&[Value], Raised> {
            if action.len() == count {
                Ok(action)
            } else {
                Err(raised("ValueError"))
            }
        };
        let dict = |value: Value| -> Result<Value, Raised> {
            py::dict(&value).map(Value::Object).map_err(raised)
        };
        let is = |name: &str| pyval::is(&kind, name);
        if is("read") {
            let rows = control.list_pending(source)?;
            let mut listed = Vec::new();
            for row in py::items(&rows).map_err(raised)? {
                listed.push(dict(row)?);
            }
            let status = dict(control.get_status()?)?;
            return Ok(Some(object([
                ("rows", Value::Array(listed)),
                ("status", status),
            ])));
        }
        if is("recovery") {
            let parts = unpack(4)?;
            let answer = control.set_interruption_recovery(
                &parts[1],
                &parts[2],
                pyval::truthy(&parts[3]),
            )?;
            return dict(answer).map(Some);
        }
        if is("enabled") {
            let enabled = action.get(1).ok_or_else(|| raised("IndexError"))?;
            return dict(control.set_enabled(pyval::truthy(enabled))?).map(Some);
        }
        if is("postpone") {
            let parts = unpack(4)?;
            return dict(control.postpone(&parts[1], &parts[2], &parts[3])?).map(Some);
        }
        if is("unpostpone") {
            let parts = unpack(3)?;
            return dict(control.unpostpone(&parts[1], &parts[2])?).map(Some);
        }
        if is("release") {
            let parts = unpack(3)?;
            return dict(control.release_hold(&parts[1], &parts[2])?).map(Some);
        }
        if is("tier") {
            let parts = unpack(4)?;
            return dict(control.set_thread_tier(&parts[2], &parts[3], &parts[1])?).map(Some);
        }
        if is("project") {
            let parts = unpack(4)?;
            let answer =
                control.set_project_rule(&parts[1], &parts[2], pyval::truthy(&parts[3]), source)?;
            return dict(answer).map(Some);
        }
        if is("unsay") {
            let parts = unpack(3)?;
            return dict(control.set_once_words(&parts[1], &parts[2], &Value::Null)?).map(Some);
        }
        if is("dashboard") {
            let opened = match dashboard {
                Some(open) => pyval::truthy(&open(None)?),
                None => false,
            };
            return Ok(Some(object([("opened", Value::Bool(opened))])));
        }
        if is("dashboard_row") {
            let parts = unpack(4)?;
            if !ROW_DIALOGS.iter().any(|name| pyval::is(&parts[1], name)) {
                return Ok(None);
            }
            let opened = match dashboard {
                Some(open) => pyval::truthy(&open(Some((
                    parts[1].clone(),
                    parts[2].clone(),
                    parts[3].clone(),
                )))?),
                None => false,
            };
            return Ok(Some(object([("opened", Value::Bool(opened))])));
        }
        Ok(None)
    };
    match run() {
        Ok(Some(payload)) => ("ok".into(), payload),
        Ok(None) => ("failed".into(), Value::from("unknown_action")),
        Err(error) => match &error.code {
            Value::Str(code) if !code.is_empty() => ("refused".into(), Value::Str(code.clone())),
            _ => ("failed".into(), Value::from(error.class.as_str())),
        },
    }
}

/// `select_action(visible, now, hidden_at=..., double_click_at=..., previous_key_at=..., keyboard=...)`: what a select
/// on the icon does - "show", "hide" or "none".
pub fn select_action(
    visible: bool,
    now: f64,
    hidden_at: Option<f64>,
    double_click_at: Option<f64>,
    previous_key_at: Option<f64>,
    keyboard: bool,
) -> &'static str {
    let within =
        |at: Option<f64>, span: f64| at.is_some_and(|at| 0.0 <= now - at && now - at < span);
    if keyboard && within(previous_key_at, KEY_REPEAT_SECONDS) {
        return "none";
    }
    if within(double_click_at, DOUBLE_CLICK_SECONDS) {
        return if visible { "none" } else { "show" };
    }
    if visible {
        return "hide";
    }
    if within(hidden_at, CLICK_AWAY_SECONDS) {
        return "none";
    }
    "show"
}

/// A dict keyed by values as Python keys one (`==` across bool, int and float), in insertion order.
#[derive(Clone, Debug)]
struct Keyed<T> {
    entries: Vec<(Value, T)>,
}

impl<T> Default for Keyed<T> {
    fn default() -> Self {
        Keyed {
            entries: Vec::new(),
        }
    }
}

impl<T: Clone> Keyed<T> {
    fn get(&self, key: &Value) -> Option<&T> {
        self.entries
            .iter()
            .find(|(each, _)| pyval::eq(each, key))
            .map(|(_, value)| value)
    }

    fn insert(&mut self, key: Value, value: T) {
        match self
            .entries
            .iter_mut()
            .find(|(each, _)| pyval::eq(each, &key))
        {
            Some(slot) => slot.1 = value,
            None => self.entries.push((key, value)),
        }
    }
}

/// `PopupModel`: what the window knows, and what a click on what it drew means. No Win32 here.
#[derive(Clone, Debug, Default)]
pub struct PopupModel {
    pub strings: Map,
    pub rows: Option<Vec<Value>>,
    pub status: Option<Value>,
    pub read_failed: bool,
    pub notice_key: Option<String>,
    pub notice_until: f64,
    busy: Vec<Vec<Value>>,
    drawn: Keyed<(Value, bool)>,
    drawn_tasks: Keyed<Map>,
    pub drawn_paused: Option<bool>,
    pub wants_read: bool,
}

fn same_key(a: &[Value], b: &[Value]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(p, q)| pyval::eq(p, q))
}

impl PopupModel {
    pub fn new(strings: Map) -> PopupModel {
        PopupModel {
            strings,
            ..PopupModel::default()
        }
    }

    fn is_busy(&self, key: &[Value]) -> bool {
        self.busy.iter().any(|each| same_key(each, key))
    }

    /// `view(now)`.
    pub fn view(&mut self, ctx: &Ctx, now: &Value) -> Py<Map> {
        let notice = match &self.notice_key {
            Some(key) if pyval::less(now, &Value::Float(self.notice_until))? => {
                Value::from(say(&self.strings, key, &[]))
            }
            _ => Value::Null,
        };
        let error = if self.read_failed && self.rows.is_none() {
            Value::from(say(&self.strings, "pending.unavailable", &[]))
        } else {
            Value::Null
        };
        let status = self.status.clone().unwrap_or(Value::Null);
        let mut vm = view_model(
            ctx,
            self.rows.as_deref(),
            &status,
            &self.strings,
            now,
            notice,
            error,
        )?;
        let mut tasks = match vm.get("tasks") {
            Some(Value::Array(tasks)) => tasks.clone(),
            _ => Vec::new(),
        };
        for task in &mut tasks {
            if let Value::Object(map) = task {
                let id = map.get("interruption_id").cloned().unwrap_or(Value::Null);
                // `("recovery", id) in self.busy`: the tuple is hashed, so an unhashable id raises.
                pyval::hashable(&id)?;
                let key = vec![Value::from("recovery"), id];
                map.insert(Str::from("busy"), Value::Bool(self.is_busy(&key)));
            }
        }
        let paused = vm.get("paused").cloned().unwrap_or(Value::Null);
        let toggle_busy = self.is_busy(&[Value::from("enabled")]) || matches!(paused, Value::Null);
        vm.insert(Str::from("tasks"), Value::Array(tasks.clone()));
        vm.insert(Str::from("toggle_busy"), Value::Bool(toggle_busy));
        self.drawn = Keyed::default();
        self.drawn_tasks = Keyed::default();
        for task in &tasks {
            if let Value::Object(map) = task {
                let id = map.get("interruption_id").cloned().unwrap_or(Value::Null);
                let thread = map.get("thread_id").cloned().unwrap_or(Value::Null);
                let checked = matches!(map.get("checked"), Some(Value::Bool(true)));
                self.drawn.insert(id.clone(), (thread, checked));
                self.drawn_tasks.insert(id, map.clone());
            }
        }
        self.drawn_paused = match paused {
            Value::Bool(on) => Some(on),
            _ => None,
        };
        Ok(vm)
    }

    /// `action_for(target)`: the action a click on `target` asks for, from what was drawn - or None.
    pub fn action_for(&self, target: &[Value]) -> Py<Option<Vec<Value>>> {
        let Some(kind) = target.first() else {
            return Ok(None);
        };
        if pyval::is(kind, "check") && target.len() == 2 {
            pyval::hashable(&target[1])?;
            if let Some((thread, checked)) = self.drawn.get(&target[1]) {
                return Ok(Some(vec![
                    Value::from("recovery"),
                    target[1].clone(),
                    thread.clone(),
                    Value::Bool(!checked),
                ]));
            }
        }
        if pyval::is(kind, "toggle")
            && let Some(paused) = self.drawn_paused
        {
            return Ok(Some(vec![Value::from("enabled"), Value::Bool(paused)]));
        }
        if pyval::is(kind, "dashboard") {
            return Ok(Some(vec![Value::from("dashboard")]));
        }
        Ok(None)
    }

    /// `menu_for(interruption_id)`: the row menu of a task as it was last drawn, or [] for a row that was not.
    pub fn menu_for(&self, interruption_id: &Value) -> Py<Value> {
        pyval::hashable(interruption_id)?;
        let Some(task) = self.drawn_tasks.get(interruption_id) else {
            return Ok(Value::Array(Vec::new()));
        };
        let status = self.status.clone().unwrap_or(Value::Null);
        let settings = py::or(get_or(&status, "settings")?, &empty()).clone();
        let default_tier = pyval::get(&settings, "default_tier")?.clone();
        row_menu(&Value::Object(task.clone()), &self.strings, &default_tier)
    }

    /// `begin(action)`: mark an action as under way; false if the same one already is.
    pub fn begin(&mut self, action: &[Value]) -> Py<bool> {
        let Some(key) = busy_key(action)? else {
            return Ok(true);
        };
        for each in &key {
            pyval::hashable(each)?;
        }
        if self.is_busy(&key) {
            return Ok(false);
        }
        self.busy.push(key);
        Ok(true)
    }

    /// `apply_outcome(action, outcome, now)`.
    pub fn apply_outcome(&mut self, action: &[Value], outcome: &[Value], now: f64) -> Py<()> {
        let kind = action.first().ok_or("IndexError")?.clone();
        let verdict = outcome.first().ok_or("IndexError")?.clone();
        let payload = outcome.get(1).cloned().unwrap_or(Value::Null);
        if let Some(key) = busy_key(action)? {
            for each in &key {
                pyval::hashable(each)?;
            }
            self.busy.retain(|each| !same_key(each, &key));
        }
        let is = |name: &str| pyval::is(&kind, name);
        if is("read") {
            if pyval::is(&verdict, "ok") {
                let rows = match &payload {
                    Value::Object(map) => map.get("rows").ok_or("KeyError")?,
                    _ => return Err("TypeError"),
                };
                let mut copied = Vec::new();
                for row in py::items(rows)? {
                    copied.push(Value::Object(py::dict(&row)?));
                }
                // The rows are taken before the status is read, as the reference's two assignments are.
                self.rows = Some(copied);
                let status = match &payload {
                    Value::Object(map) => map.get("status").ok_or("KeyError")?,
                    _ => return Err("TypeError"),
                };
                self.status = Some(Value::Object(py::dict(status)?));
                self.read_failed = false;
            } else {
                self.read_failed = true;
            }
            return Ok(());
        }
        if is("dashboard") || is("dashboard_row") {
            return Ok(());
        }
        if pyval::is(&verdict, "ok") {
            if is("recovery")
                && let Some(rows) = &mut self.rows
            {
                for row in rows.iter_mut() {
                    let wanted = action.get(2).ok_or("IndexError")?;
                    if pyval::eq(pyval::get(row, "thread_id")?, wanted) {
                        let enabled = pyval::truthy(pyval::get(&payload, "enabled")?);
                        if let Value::Object(map) = row {
                            map.insert(Str::from("thread_enabled"), Value::Bool(enabled));
                        }
                    }
                }
            } else if is("enabled")
                && let Some(Value::Object(status)) = &mut self.status
            {
                let enabled = pyval::truthy(pyval::get(&payload, "enabled")?);
                status.insert(Str::from("enabled"), Value::Bool(enabled));
            }
        } else {
            let row_action = ROW_ACTIONS.iter().any(|name| is(name));
            let stale = pyval::is(&verdict, "refused")
                && (is("recovery") || (row_action && pyval::in_set(&payload, &STALE_CODES)?));
            self.notice_key = Some(
                if stale {
                    "popup.stale"
                } else {
                    "action.failed"
                }
                .into(),
            );
            self.notice_until = now + NOTICE_SECONDS;
        }
        self.wants_read = true;
        Ok(())
    }

    /// `attention()`: what the icon reads while this popup is open.
    pub fn attention(&self) -> Py<bool> {
        match &self.status {
            None => Ok(false),
            Some(status) => icon_attention(status, self.rows.as_deref()),
        }
    }
}
