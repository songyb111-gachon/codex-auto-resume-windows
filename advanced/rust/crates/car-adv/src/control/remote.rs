//! `control/remote.py` (seat S7.3b): what the loopback API and Telegram may read and do, through core's control layer -
//! and their Dashboard cards' bridge commands. No network here.
//!
//! What it reads is the status file's document (core's `statusfile.content`) and the waiting recoveries as `task N`
//! (each one's 1-based place in Pending, its public state code and when it is next looked at). A listing carries a
//! `snapshot`: a digest of the ids it listed, so a later `task N` is resolved against exactly that list or refused
//! ([`Stale`]). What it may do is the reduce-actions alone: pause, cancel one waiting recovery - and, under
//! telegram_continue, release one held recovery and lift the pause.
//!
//! [`Layer`] is core's `Control` as these functions use it; the cards' functions take the courier's [`Runtime`] and the
//! seams the tag's take (`secrets`, `running`, `watcher`, `addresses`).

use car_machine::json::{Map, Str, Value};

use crate::courier::address::{self, web_view};
use crate::courier::keep;
use crate::courier::main::Runtime;
use crate::courier::resident::{BOUND, LAN_KEYS, TAKEN};
use crate::credentials::Secrets;
use crate::engine::remote as resident_code;
use crate::jsonx::object;
use crate::state::sql::{self, string};
use crate::vocabulary::{ArmingState, Refusal};

pub const API: &str = "local_api";
pub const API_ACTIONS: &str = "local_api_actions";
pub const API_LAN: &str = "local_api_lan";
pub const TELEGRAM: &str = "telegram_remote";
pub const TELEGRAM_CONTINUE: &str = "telegram_continue";
/// local_api's one secret.
pub const TOKEN: &str = "token";
/// Core's journal actor for these acts.
pub const ACTOR: &str = "cli";

/// What a layer's call raised: the exception's class.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Failed {
    /// `Stale`: the list changed since it was read, or never had that place.
    Stale,
    /// Any other exception, by class.
    Raised(String),
}

/// `Stale`.
pub fn stale() -> Failed {
    Failed::Stale
}

/// Core's control layer as these functions use it (`Control(paths)`).
pub trait Layer {
    /// `store.pending()` under `_open(legacy_ok=True)`: the waiting recoveries, oldest first.
    fn pending_rows(&self) -> Result<Vec<Value>, Failed>;
    /// `status_document(layer, now)`: core's `statusfile.content` over the settings, the store and the heartbeat.
    fn status_document(&self, now: f64) -> Result<Value, Failed>;
    /// `set_enabled(enabled)`: its answer (`{"enabled": ...}`).
    fn set_enabled(&self, enabled: bool) -> Result<Value, Failed>;
    /// `cancel_interruption(id, actor=)`.
    fn cancel_interruption(&self, id: &Value, actor: &str) -> Result<Value, Failed>;
    /// `release_hold(id, thread, actor=)`.
    fn release_hold(&self, id: &Value, thread: &Value, actor: &str) -> Result<Value, Failed>;
    /// `watcher_running()`.
    fn watcher_running(&self) -> Option<bool>;
}

fn field<'a>(row: &'a Value, key: &str) -> &'a Value {
    match row {
        Value::Object(map) => map.get(key).unwrap_or(&Value::Null),
        _ => &Value::Null,
    }
}

// ------------------------------------------------------------------------------------------ what is read
/// `snapshot(rows)`: a digest of the ids `rows` holds, in their order.
pub fn snapshot(rows: &[Value]) -> String {
    let joined: Vec<String> = rows
        .iter()
        .map(|row| car_machine::pytext::py_str(field(row, "interruption_id")))
        .collect();
    let digest = car_machine::hash::sha256(joined.join("\n").as_bytes());
    car_machine::hash::hex(&digest)[..16].to_owned()
}

/// `listing(rows)`: `task N`, the public state code and the next check - nothing else.
pub fn listing(rows: &[Value]) -> Result<Vec<Value>, Failed> {
    let mut listed = Vec::new();
    for (place, row) in rows.iter().enumerate() {
        let raised = |class: &str| Failed::Raised(class.to_owned());
        let due = car_machine::domain::public::eligible_at(row).map_err(raised)?;
        let code = car_machine::domain::public::public_code(row).map_err(raised)?;
        let next = match due {
            Value::Int(_) | Value::Float(_) => {
                Value::Float(crate::state::py::as_f64(&due).unwrap_or(f64::NAN))
            }
            _ => Value::Null,
        };
        listed.push(object([
            ("task", Value::from(format!("task {}", place + 1))),
            ("state", Value::from(code)),
            ("next_check_at", next),
        ]));
    }
    Ok(listed)
}

/// `pending(layer)`: {"snapshot", "pending"} of the waiting recoveries.
pub fn pending(layer: &dyn Layer) -> Result<Value, Failed> {
    let rows = layer.pending_rows()?;
    Ok(object([
        ("snapshot", Value::from(snapshot(&rows))),
        ("pending", Value::Array(listing(&rows)?)),
    ]))
}

const METRICS: [(&str, &str); 6] = [
    (
        "codex_auto_resume_watcher_running",
        "Whether the watcher runs (1) or not (0).",
    ),
    (
        "codex_auto_resume_recovery_on",
        "Whether recovery is on (1), or paused or only watching (0).",
    ),
    (
        "codex_auto_resume_pending",
        "How many recoveries are pending.",
    ),
    (
        "codex_auto_resume_pending_state",
        "How many pending recoveries are at each public state code.",
    ),
    (
        "codex_auto_resume_next_check_seconds",
        "When a waiting recovery is next looked at, seconds since 1970.",
    ),
    (
        "codex_auto_resume_written_seconds",
        "When this was read, seconds since 1970.",
    ),
];

fn percent_d(value: &Value) -> Result<String, Failed> {
    match value {
        Value::Bool(flag) => Ok(i64::from(*flag).to_string()),
        Value::Int(_) => Ok(car_machine::pytext::py_str(value)),
        Value::Float(x) if x.is_finite() => Ok(format!("{}", x.trunc() as i64)),
        _ => Err(Failed::Raised("TypeError".into())),
    }
}

fn percent_3f(value: &Value) -> Result<String, Failed> {
    match value {
        Value::Int(_) | Value::Float(_) | Value::Bool(_) => {
            let x = match value {
                Value::Bool(flag) => f64::from(u8::from(*flag)),
                _ => crate::state::py::as_f64(value).unwrap_or(f64::NAN),
            };
            Ok(if x.is_nan() {
                "nan".into()
            } else if x.is_infinite() {
                if x > 0.0 { "inf".into() } else { "-inf".into() }
            } else {
                format!("{x:.3}")
            })
        }
        _ => Err(Failed::Raised("TypeError".into())),
    }
}

/// `metrics(document)`: the status document as Prometheus' text format.
pub fn metrics(document: &Value) -> Result<String, Failed> {
    let get = |key: &str| match document {
        Value::Object(map) => map
            .get(key)
            .cloned()
            .ok_or_else(|| Failed::Raised("KeyError".into())),
        _ => Err(Failed::Raised("TypeError".into())),
    };
    let mut lines = Vec::new();
    for (name, said) in METRICS {
        lines.push(format!("# HELP {name} {said}"));
        lines.push(format!("# TYPE {name} gauge"));
        if name.ends_with("watcher_running") {
            let running = sql::py_eq(&get("watcher")?, &string("running"));
            lines.push(format!("{name} {}", i64::from(running)));
        } else if name.ends_with("recovery_on") {
            let on = sql::py_eq(&get("recovery")?, &string("on"));
            lines.push(format!("{name} {}", i64::from(on)));
        } else if name.ends_with("_pending") {
            lines.push(format!("{name} {}", percent_d(&get("pending")?)?));
        } else if name.ends_with("pending_state") {
            let Value::Object(states) = get("states")? else {
                return Err(Failed::Raised("AttributeError".into()));
            };
            for (code, count) in states.iter() {
                lines.push(format!(
                    "{name}{{state=\"{}\"}} {}",
                    car_machine::pytext::py_str(&Value::Str(code.clone())),
                    percent_d(count)?
                ));
            }
        } else if name.ends_with("next_check_seconds") {
            let next = get("next_check_at")?;
            if !matches!(next, Value::Null) {
                lines.push(format!("{name} {}", percent_3f(&next)?));
            }
        } else {
            lines.push(format!("{name} {}", percent_3f(&get("written_at")?)?));
        }
    }
    Ok(lines.join("\n") + "\n")
}

// ------------------------------------------------------------------------------------------ what is done
/// `ALIAS`: `task ([1-9][0-9]{0,3})\Z`.
pub fn alias_place(alias: &str) -> Option<usize> {
    let digits = alias.strip_prefix("task ")?;
    let good = (1..=4).contains(&digits.len())
        && digits.bytes().all(|b| b.is_ascii_digit())
        && !digits.starts_with('0');
    if good { digits.parse().ok() } else { None }
}

fn snapshot_shape(text: &str) -> bool {
    text.len() == 16
        && text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// `resolve(layer, alias, listed)`: the record `alias` names on the list `listed` - read again now - or Stale.
pub fn resolve(layer: &dyn Layer, alias: &Value, listed: &Value) -> Result<Value, Failed> {
    let place = crate::state::py::text(alias).and_then(alias_place);
    let listed = crate::state::py::text(listed).filter(|text| snapshot_shape(text));
    let (Some(place), Some(listed)) = (place, listed) else {
        return Err(Failed::Stale);
    };
    let rows = layer.pending_rows()?;
    if snapshot(&rows) != listed || place > rows.len() {
        return Err(Failed::Stale);
    }
    Ok(rows[place - 1].clone())
}

fn enabled_of(answer: &Value) -> Result<Value, Failed> {
    match answer {
        Value::Object(map) => map
            .get("enabled")
            .cloned()
            .ok_or_else(|| Failed::Raised("KeyError".into())),
        _ => Err(Failed::Raised("TypeError".into())),
    }
}

/// `pause(layer)`.
pub fn pause(layer: &dyn Layer) -> Result<Value, Failed> {
    let enabled = enabled_of(&layer.set_enabled(false)?)?;
    Ok(object([("done", Value::Bool(true)), ("enabled", enabled)]))
}

/// `cancel(layer, alias, listed)`.
pub fn cancel(layer: &dyn Layer, alias: &Value, listed: &Value) -> Result<Value, Failed> {
    let record = resolve(layer, alias, listed)?;
    let found = layer.cancel_interruption(field(&record, "interruption_id"), ACTOR)?;
    let changed = car_machine::pyval::truthy(field(&found, "changed"));
    Ok(object([
        ("done", Value::Bool(true)),
        ("task", alias.clone()),
        ("changed", Value::Bool(changed)),
    ]))
}

/// `release(layer, alias, listed)`.
pub fn release(layer: &dyn Layer, alias: &Value, listed: &Value) -> Result<Value, Failed> {
    let record = resolve(layer, alias, listed)?;
    layer.release_hold(
        field(&record, "interruption_id"),
        field(&record, "thread_id"),
        ACTOR,
    )?;
    Ok(object([
        ("done", Value::Bool(true)),
        ("task", alias.clone()),
    ]))
}

/// `lift_pause(layer)`.
pub fn lift_pause(layer: &dyn Layer) -> Result<Value, Failed> {
    let enabled = enabled_of(&layer.set_enabled(true)?)?;
    Ok(object([("done", Value::Bool(true)), ("enabled", enabled)]))
}

// ------------------------------------------------------------------------------------------ the Dashboard's card
/// What the cards ask beyond the runtime: whether a resident answers its mutex, whether the watcher runs, this PC's
/// own addresses, and a new token's random bytes (`secrets.token_urlsafe(32)`).
pub struct CardSeams<'a> {
    pub running: &'a dyn Fn() -> bool,
    pub watcher: &'a dyn Fn() -> bool,
    pub addresses: Option<&'a dyn Fn() -> Vec<String>>,
    pub token: &'a dyn Fn() -> String,
}

fn refusal(word: Refusal) -> Value {
    object([
        ("done", Value::Bool(false)),
        ("refusal", Value::from(word.as_str())),
    ])
}

fn state_of(runtime: &dyn Runtime, capability: &str) -> Result<ArmingState, ()> {
    runtime.states().map(|states| states.state_of(capability))
}

fn armed(runtime: &dyn Runtime, capability: &str) -> bool {
    state_of(runtime, capability) == Ok(ArmingState::Armed)
}

/// `_standing(runtime, capability)`: None where it is on or watched; the refusal otherwise.
fn standing(runtime: &dyn Runtime, capability: &str) -> Option<Refusal> {
    if runtime.registry().get(capability).is_none() {
        return Some(Refusal::UnknownCapability);
    }
    match state_of(runtime, capability) {
        Err(()) => Some(Refusal::StateUnavailable),
        Ok(ArmingState::Armed | ArmingState::Shadow) => None,
        Ok(_) => Some(Refusal::NotOn),
    }
}

/// `port(runtime)`: the port chosen, or the default.
pub fn port(runtime: &dyn Runtime) -> i64 {
    match runtime.state().options(&string(API)) {
        Ok(options) => match options.get("api_port") {
            Some(Value::Int(value)) => value.as_i64().unwrap_or(resident_code::DEFAULT_PORT),
            _ => resident_code::DEFAULT_PORT,
        },
        Err(_) => resident_code::DEFAULT_PORT,
    }
}

fn journal_times(runtime: &dyn Runtime) -> impl Fn(&str, &str, f64) -> Vec<f64> + '_ {
    move |capability: &str, word: &str, since: f64| {
        runtime
            .state()
            .journal_times(&string(capability), &string(word), &Value::Float(since))
            .map(|times| times.iter().filter_map(crate::state::py::as_f64).collect())
            .unwrap_or_default()
    }
}

/// `_began(runtime)`: when the newest resident was started, in whole seconds; 0 where none is journalled.
fn began(runtime: &dyn Runtime) -> i64 {
    let mut found: Vec<f64> = Vec::new();
    for capability in resident_code::RESIDENT {
        match runtime.state().journal_times(
            &string(capability),
            &string(resident_code::START_WORD),
            &Value::from(0),
        ) {
            Ok(times) => found.extend(times.iter().filter_map(crate::state::py::as_f64)),
            Err(_) => return 0,
        }
    }
    found
        .into_iter()
        .reduce(f64::max)
        .map_or(0, |at| at.trunc() as i64)
}

/// `_down(runtime, alive, watcher)`.
fn down(runtime: &dyn Runtime, alive: bool, seams: &CardSeams<'_>) -> Option<&'static str> {
    if alive {
        return None;
    }
    let times = journal_times(runtime);
    if resident_code::stopped(
        &times,
        runtime.clock(),
        resident_code::setup_time(runtime.paths()),
    ) {
        return Some("stopped");
    }
    Some(if (seams.watcher)() {
        "starting"
    } else {
        "no_watcher"
    })
}

/// `_word(runtime, on, alive, watcher)`: how the server stands, for the card.
fn word(runtime: &dyn Runtime, on: bool, alive: bool, seams: &CardSeams<'_>) -> &'static str {
    if !on {
        return "off";
    }
    if let Some(down) = down(runtime, alive, seams) {
        return down;
    }
    let began = began(runtime);
    let api = string(API);
    let stamps = runtime
        .state()
        .stamped(&api, &string(BOUND))
        .and_then(|bound| Ok((bound, runtime.state().stamped(&api, &string(TAKEN))?)));
    let Ok((bound, taken)) = stamps else {
        return "starting";
    };
    let number = |value: &Value| crate::state::py::as_f64(value);
    let began = began as f64;
    if let Some(bound) = number(&bound)
        && bound >= began
        && number(&taken).is_none_or(|taken| bound >= taken)
    {
        return "running";
    }
    if number(&taken).is_some_and(|taken| taken >= began) {
        "port_taken"
    } else {
        "starting"
    }
}

/// `recorded_addresses(runtime)`: this PC's own network addresses the server answers on, as the resident recorded them.
pub fn recorded_addresses(runtime: &dyn Runtime) -> Vec<String> {
    let mut found = Vec::new();
    for key in LAN_KEYS {
        if let Ok(Value::Int(value)) = runtime.state().stamped(&string(API), &string(key))
            && let Some(value) = value.as_i64()
            && (0..=i64::from(u32::MAX)).contains(&value)
        {
            found.push(address::ipv4_text(value as u32));
        }
    }
    found
}

fn token_of(runtime: &dyn Runtime, secrets: &Secrets<'_>) -> Option<String> {
    let _ = runtime;
    secrets.read(API, &string(TOKEN)).ok().flatten()
}

/// `api_view(runtime, copy=, host=, copy_token=, ...)`: what the card shows.
pub fn api_view(
    runtime: &dyn Runtime,
    copy: &Value,
    host: &Value,
    copy_token: &Value,
    secrets: &Secrets<'_>,
    seams: &CardSeams<'_>,
) -> Value {
    if runtime.registry().get(API).is_none() {
        return refusal(Refusal::UnknownCapability);
    }
    let on = armed(runtime, API);
    let token = token_of(runtime, secrets);
    let alive = if on { (seams.running)() } else { false };
    let chosen = port(runtime);
    let lan = on && armed(runtime, API_LAN);
    let token_saved = token.as_deref().is_some_and(|token| !token.is_empty());
    let state = word(runtime, on, alive, seams);
    let mut found = Map::new();
    let mut put = |key: &str, value: Value| {
        found.insert(Str::from(key), value);
    };
    put("done", Value::Bool(true));
    put("refusal", Value::Null);
    put("port", Value::from(chosen));
    put("url", Value::from(web_view(chosen, None, None)));
    put("token_saved", Value::Bool(token_saved));
    put("state", Value::from(state));
    put("lan", Value::Bool(lan));
    put("actions", Value::Bool(on && armed(runtime, API_ACTIONS)));
    let own: Vec<String> = if lan {
        match seams.addresses {
            Some(addresses) => addresses(),
            None => recorded_addresses(runtime),
        }
    } else {
        Vec::new()
    };
    if lan {
        put(
            "lan_urls",
            Value::Array(
                own.iter()
                    .map(|address| Value::from(web_view(chosen, None, Some(address))))
                    .collect(),
            ),
        );
    }
    if token_saved && state == "running" && standing(runtime, API).is_none() {
        let token = token.unwrap_or_default();
        let host_text = crate::state::py::text(host);
        if matches!(copy, Value::Bool(true))
            && (matches!(host, Value::Null)
                || host_text.is_some_and(|h| own.iter().any(|a| a == h)))
        {
            put(
                "copy_url",
                Value::from(web_view(chosen, Some(&token), host_text)),
            );
        }
        if matches!(copy_token, Value::Bool(true)) {
            put("copy_token", Value::from(token.as_str()));
        }
    }
    Value::Object(found)
}

/// `api_token_new(runtime, ...)`: a new token kept, the old one gone; the address carrying it answered this once.
pub fn api_token_new(runtime: &dyn Runtime, secrets: &Secrets<'_>, seams: &CardSeams<'_>) -> Value {
    if let Some(refused) = standing(runtime, API) {
        return refusal(refused);
    }
    let token = (seams.token)();
    if secrets
        .write(API, &string(TOKEN), &Value::from(token.as_str()))
        .is_err()
    {
        return refusal(Refusal::SecretUnavailable);
    }
    let mut made = Map::new();
    made.insert(Str::from("done"), Value::Bool(true));
    made.insert(Str::from("refusal"), Value::Null);
    let on = armed(runtime, API);
    let alive = on && (seams.running)();
    if word(runtime, on, alive, seams) == "running" {
        made.insert(
            Str::from("copy_url"),
            Value::from(web_view(port(runtime), Some(&token), None)),
        );
    }
    Value::Object(made)
}

/// `pair_state(runtime, ...)`: the shared Telegram pairing, as the remote card shows it.
pub fn pair_state(runtime: &dyn Runtime, secrets: &Secrets<'_>, seams: &CardSeams<'_>) -> Value {
    if runtime.registry().get(TELEGRAM).is_none()
        || runtime.registry().get(keep::CAPABILITY).is_none()
    {
        return refusal(Refusal::UnknownCapability);
    }
    let row = match keep::pairing(runtime.state()) {
        Ok(row) => row.unwrap_or_default(),
        Err(_) => return refusal(Refusal::StateUnavailable),
    };
    let now = runtime.clock();
    let on = armed(runtime, TELEGRAM);
    let alive = if on { (seams.running)() } else { false };
    let paired = keep::saved(secrets, "telegram");
    let token_saved = matches!(keep::read(secrets, "telegram_token"), Ok(Some(_)));
    let pairing = car_machine::pyval::truthy(sql::get(&row, "code_digest"))
        && crate::state::py::as_f64(sql::get(&row, "code_expires_at")).unwrap_or(0.0) > now;
    let state = if !on {
        "off"
    } else {
        match down(runtime, alive, seams) {
            Some(down) => down,
            None if !token_saved => "no_token",
            None if pairing => "pairing",
            None if !paired => "no_chat",
            None => "running",
        }
    };
    let mut found = Map::new();
    for (key, value) in [
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("paired", Value::Bool(paired)),
        ("token_saved", Value::Bool(token_saved)),
        ("pairing", Value::Bool(pairing)),
        ("state", Value::from(state)),
        ("continue", Value::Bool(armed(runtime, TELEGRAM_CONTINUE))),
    ] {
        found.insert(Str::from(key), value);
    }
    if paired {
        let chat = keep::chat_name(secrets).ok().flatten();
        found.insert(Str::from("chat"), chat.map_or(Value::Null, Value::from));
    }
    Value::Object(found)
}

/// `pair_start(runtime, ...)`: the notices card's pairing begun from the remote card.
pub fn pair_start(
    runtime: &dyn Runtime,
    secrets: &Secrets<'_>,
    code: &dyn Fn() -> String,
    start: &dyn Fn(&[&str]) -> bool,
) -> Value {
    for capability in [TELEGRAM, keep::CAPABILITY] {
        if let Some(refused) = standing(runtime, capability) {
            return refusal(refused);
        }
    }
    crate::control::courier::begin_pair(runtime, secrets, code, start)
}
