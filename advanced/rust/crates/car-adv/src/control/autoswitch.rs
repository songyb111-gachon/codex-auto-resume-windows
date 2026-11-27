//! `control/autoswitch.py` (seat S7.3a2): the Dashboard's saved accounts (account_auto_switch, v0.6.22) - the bridge's
//! six commands, the Dashboard's alone: the card read in every state, Add an account, Save the account in use, Read
//! usage, Switch to this account, and delete one or all.
//!
//! What reaches Codex or Windows (the add's `codex login`, a saved account's usage read on a scratch home, the account
//! read on the real home, the switch itself, the busy rule and the engines listing) is the surfaces' World's
//! (`surfaces::World`): the bare world reaches nothing real, the entry points hand the live one (S7.3d). The add, the
//! read and the switch run on a thread of this process's own (the World's `spawn`); what each is doing is kept per
//! installation home, as the module's `_ADDING`, `_READING` and `_SWITCHING`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;

use super::resets::{Result, field, int, is, object, refusal, standing, state, text};
use crate::codex::authfile::{self, Fault};
use crate::engine::autoswitch::{self as engine, best, seen};
use crate::profiles::{self, DAMAGED, KEEP_SECONDS, LOCK_SECONDS, NEEDS_SIGN_IN, Profiles, READY};
use crate::runtime::Runtime;
use crate::state::Error;
use crate::vocabulary::{ArmingState, OptionKey, Refusal};

pub const CAPABILITY: &str = "account_auto_switch";
/// The capabilities whose cards show the saved accounts: either on or watched lets a person add, save and read them.
pub const STANDING: [&str; 2] = [CAPABILITY, "account_switch"];
pub const WAITING: &str = "waiting";
pub const ADDED: &str = "added";
pub const NOT_ADDED: &str = "not_added";
pub const READING: &str = "reading";
pub const READ: &str = "read";
pub const HELD: &str = "held";
pub const UNKNOWN: &str = "unknown";
pub const READ_EVERY: i64 = 600;
pub const SWITCHING: &str = "switching";

/// `_READING[home]`: Read usage's state, how many it read of how many, and the ones whose read broke.
#[derive(Clone, Debug, Default)]
pub struct Reading {
    pub state: Option<String>,
    pub done: i64,
    pub of: Option<i64>,
    pub failed: Vec<String>,
}

#[derive(Default)]
struct Held {
    adding: BTreeMap<PathBuf, String>,
    reading: BTreeMap<PathBuf, Reading>,
    switching: BTreeMap<PathBuf, (String, Value)>,
}

static HOLD: LazyLock<Mutex<Held>> = LazyLock::new(|| Mutex::new(Held::default()));

fn hold() -> std::sync::MutexGuard<'static, Held> {
    HOLD.lock().unwrap_or_else(PoisonError::into_inner)
}

fn home_of(runtime: &Runtime) -> PathBuf {
    PathBuf::from(&runtime.paths.home)
}

/// `_saved(runtime)`: the saved accounts of this installation.
pub fn saved(paths: &Paths) -> Profiles {
    crate::state::seam::accounts::live_profiles(Path::new(&paths.home))
}

fn wall() -> f64 {
    crate::state::session::wall_clock()
}

fn fault(error: Fault) -> Error {
    Error::python(super::resets::class_of(&error.class), error.message)
}

fn profile_error(error: profiles::ProfileError) -> Error {
    Error::python(super::resets::class_of(error.class), error.message)
}

/// `_kept_standing(runtime)`.
pub fn kept_standing(runtime: &Runtime) -> bool {
    STANDING
        .iter()
        .any(|capability| standing(runtime, capability))
}

/// `_codex_home(runtime)`.
fn codex_home(runtime: &Runtime) -> Result<PathBuf> {
    super::resets::codex_home(runtime).map(PathBuf::from)
}

/// `authfile.usable(home)`, UNREADABLE where it raised.
fn usable(home: Result<PathBuf>) -> &'static str {
    match home {
        Ok(home) => authfile::usable(&home).unwrap_or(authfile::UNREADABLE),
        Err(_) => authfile::UNREADABLE,
    }
}

/// `_sweep(store)`: what a kill left in the saved accounts folder swept, only while nothing holds them.
fn sweep(store: &Profiles) {
    let _ = store.locked(0.0, || {
        authfile::sweep(&store.directory, None, wall(), authfile::SCRATCH_STALE);
        Ok(())
    });
}

/// `view(runtime, store=, codex_home=, usage=, now=)`: advanced-accounts, in every state.
pub fn view(
    runtime: &Runtime,
    store: Option<&Profiles>,
    usage: Option<Value>,
    now: Option<f64>,
) -> Result<Value> {
    let made;
    let store = match store {
        Some(store) => store,
        None => {
            made = saved(&runtime.paths);
            &made
        }
    };
    let standing = kept_standing(runtime);
    let word = if standing {
        text(usable(codex_home(runtime)))
    } else {
        Value::Null
    };
    sweep(store);
    let switched = state(runtime, "stamped")
        .and_then(|state| {
            state.stamped(&text(CAPABILITY), &text(OptionKey::AutoSwitchedAt.as_str()))
        })
        .unwrap_or(Value::Null);
    let home = home_of(runtime);
    let (add_state, reading, switching) = {
        let mut held = hold();
        let add_state = held.adding.get(&home).cloned();
        if add_state
            .as_deref()
            .is_some_and(|word| word == ADDED || word == NOT_ADDED)
        {
            held.adding.remove(&home);
        }
        let reading = held.reading.get(&home).cloned().unwrap_or_default();
        let switching = held.switching.get(&home).cloned();
        if switching
            .as_ref()
            .is_some_and(|(word, _)| word != SWITCHING)
        {
            held.switching.remove(&home);
        }
        (add_state, reading, switching)
    };
    let offered = runtime.registry.get(CAPABILITY).is_some();
    let (switch_state, switch_mask) = match switching {
        Some((word, mask)) => (text(&word), mask),
        None => (Value::Null, Value::Null),
    };
    let mut answer = match object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("store", word),
        (
            "add_state",
            add_state.map_or(Value::Null, |word| text(&word)),
        ),
        ("switched_at", switched),
        ("offered", Value::Bool(offered)),
        ("standing", Value::Bool(standing)),
        ("switch_state", switch_state),
        ("switch_mask", switch_mask),
    ]) {
        Value::Object(map) => map,
        _ => Map::new(),
    };
    let now = now.unwrap_or_else(wall);
    for (key, value) in meters(runtime, store, &reading, now, usage)? {
        answer.insert(key, value);
    }
    Ok(Value::Object(answer))
}

/// `_watcher_usage(runtime)`: the watcher's own last usage reading of the account signed in, or None.
fn watcher_usage(runtime: &Runtime) -> Value {
    match super::resets::core(runtime).map(|store| store.watcher_status()) {
        Ok(Ok(Some(status))) => status.get("usage").cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    }
}

/// `swap.meters(windows)` of a value as the reference iterates it (`windows or ()`).
fn windows_of(windows: &Value) -> Result<Map> {
    let listed: Vec<Value> = match windows {
        Value::Array(items) => items.clone(),
        Value::Object(_) | Value::Str(_) => Vec::new(),
        other if !pyval::truthy(other) => Vec::new(),
        _ => return Err(Error::type_error("object is not iterable")),
    };
    crate::codex::swap::meters(&listed).map_err(fault)
}

/// `int(value)` of a number.
fn whole(value: &Value) -> Result<Value> {
    match value {
        Value::Int(_) => Ok(value.clone()),
        Value::Float(number) if number.is_finite() => {
            let truncated = number.trunc();
            if truncated.abs() < 9.0e15 {
                Ok(int(truncated as i64))
            } else {
                Ok(Value::Float(truncated))
            }
        }
        Value::Float(_) => Err(Error::python(
            "ValueError",
            "cannot convert float to integer",
        )),
        _ => Err(Error::type_error("int() argument must be a number")),
    }
}

/// `_in_use(rows)`: the row last found signed in (the greatest int `seen_at`, the first of equals), or None.
pub fn in_use(rows: &[Map]) -> Value {
    let mut picked: Option<(&Value, Value)> = None;
    for row in rows {
        let seen_at = field(&Value::Object(row.clone()), "seen_at");
        if !matches!(seen_at, Value::Int(_)) {
            continue;
        }
        let greater = match &picked {
            None => true,
            Some((best, _)) => !pyval::less_or_equal(&seen_at, best).unwrap_or(true),
        };
        if greater {
            let id = row.get("id").cloned().unwrap_or(Value::Null);
            picked = Some((row.get("seen_at").unwrap_or(&Value::Null), id));
        }
    }
    picked.map_or(Value::Null, |(_, id)| id)
}

/// `meters(runtime, store, reading, now, usage=)`: the card's rows with their meters, the next candidate and Read
/// usage's state.
pub fn meters(
    runtime: &Runtime,
    store: &Profiles,
    reading: &Reading,
    now: f64,
    usage: Option<Value>,
) -> Result<Map> {
    let rows = store.view().map_err(profile_error)?;
    let in_use = in_use(&rows);
    let live = usage.unwrap_or_else(|| watcher_usage(runtime));
    let mut shown = Vec::new();
    let mut candidates = Vec::new();
    let mut read_at: Vec<Value> = Vec::new();
    for row in &rows {
        let get = |name: &str| row.get(name).cloned().unwrap_or(Value::Null);
        let id = get("id");
        let kept = get("usage");
        let mine = pyval::eq(&id, &in_use) && !matches!(in_use, Value::Null);
        let failed = matches!(&id, Value::Str(text) if reading.failed.iter().any(|one| text.as_str() == Some(one)));
        let mut entry = match object(vec![
            ("id", id.clone()),
            ("mask", get("mask")),
            ("plan", get("plan")),
            ("state", get("state")),
            ("in_use", Value::Bool(mine)),
            ("five_hour", Value::Null),
            ("weekly", Value::Null),
            ("read_at", Value::Null),
            (
                "unread",
                Value::Bool(pyval::truthy(&get("unread")) || failed),
            ),
        ]) {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        if mine {
            entry.insert(Str::new("unread"), Value::Bool(false));
            let at = field(&live, "read_at");
            if matches!(live, Value::Object(_)) && matches!(at, Value::Int(_) | Value::Float(_)) {
                for (key, value) in windows_of(&field(&live, "windows"))? {
                    entry.insert(key, value);
                }
                entry.insert(Str::new("read_at"), whole(&at)?);
            }
        } else if !matches!(kept, Value::Null) {
            entry.insert(Str::new("five_hour"), field(&kept, "five_hour"));
            entry.insert(Str::new("weekly"), field(&kept, "weekly"));
            entry.insert(Str::new("read_at"), field(&kept, "read_at"));
            read_at.push(field(&kept, "read_at"));
            if is(&get("state"), READY) {
                let found = object(vec![
                    ("present", Value::Bool(true)),
                    ("own", Value::Bool(true)),
                    ("available", field(&kept, "available")),
                    ("most_used", field(&kept, "most_used")),
                ]);
                candidates.push((id.clone(), found, get("used_at")));
            }
        }
        shown.push(Value::Object(entry));
    }
    let picked = best(&candidates).map_err(fault)?;
    let mask_of = |picked: &Value| {
        rows.iter()
            .rev()
            .find(|row| row.get("id").is_some_and(|id| pyval::eq(id, picked)))
            .and_then(|row| row.get("mask").cloned())
            .unwrap_or(Value::Null)
    };
    let last = store.read_now_at().map_err(profile_error)?;
    let following = match &last {
        Value::Int(at) => at.as_i64().and_then(|at| {
            let since = now - at as f64;
            (0.0 <= since && since < READ_EVERY as f64).then(|| int(at + READ_EVERY))
        }),
        _ => None,
    }
    .unwrap_or(Value::Null);
    let mut most: Option<Value> = None;
    for at in &read_at {
        let greater = match &most {
            None => true,
            Some(best) => !pyval::less_or_equal(at, best)
                .map_err(|_| Error::type_error("'>' not supported"))?,
        };
        if greater {
            most = Some(at.clone());
        }
    }
    let picked_truthy = picked.as_ref().is_some_and(pyval::truthy);
    let state_word = if picked_truthy {
        text("found")
    } else if !read_at.is_empty() {
        text("none_has_room")
    } else {
        Value::Null
    };
    let mut found = Map::new();
    found.insert(Str::new("profiles"), Value::Array(shown));
    found.insert(Str::new("read_at"), most.unwrap_or(Value::Null));
    found.insert(
        Str::new("candidate"),
        match &picked {
            Some(picked) if picked_truthy => mask_of(picked),
            _ => Value::Null,
        },
    );
    found.insert(Str::new("candidate_id"), picked.unwrap_or(Value::Null));
    found.insert(Str::new("candidate_state"), state_word);
    found.insert(
        Str::new("read_state"),
        reading.state.as_deref().map_or(Value::Null, text),
    );
    found.insert(
        Str::new("read_done"),
        if reading.state.is_some() {
            int(reading.done)
        } else {
            Value::Null
        },
    );
    found.insert(Str::new("read_of"), reading.of.map_or(Value::Null, int));
    found.insert(Str::new("read_next_at"), following);
    Ok(found)
}

/// `read(runtime, ...)`: advanced-accounts-read, Read usage.
pub fn read(runtime: &Runtime, now: Option<f64>) -> Result<Value> {
    if !kept_standing(runtime) {
        return Ok(refusal(Refusal::NotOn));
    }
    let store = saved(&runtime.paths);
    let home = home_of(runtime);
    let now = now.unwrap_or_else(wall).trunc() as i64;
    {
        let mut held = hold();
        if held
            .reading
            .get(&home)
            .is_some_and(|reading| reading.state.as_deref() == Some(READING))
        {
            return Ok(object(vec![
                ("done", Value::Bool(true)),
                ("refusal", Value::Null),
                ("started", Value::Bool(false)),
                ("read_state", text(READING)),
            ]));
        }
        let last = store.read_now_at().map_err(profile_error)?;
        if let Value::Int(at) = &last
            && let Some(at) = at.as_i64()
            && 0 <= now - at
            && now - at < READ_EVERY
        {
            return Ok(object(vec![
                ("done", Value::Bool(true)),
                ("refusal", Value::Null),
                ("started", Value::Bool(false)),
                ("read_next_at", int(at + READ_EVERY)),
            ]));
        }
        match store.note_read_now(now as f64) {
            Ok(()) => {}
            Err(error) if error.class == "OSError" => {
                return Ok(refusal(Refusal::StateUnavailable));
            }
            Err(error) => return Err(profile_error(error)),
        }
        held.reading.insert(
            home.clone(),
            Reading {
                state: Some(READING.to_owned()),
                ..Reading::default()
            },
        );
    }
    let paths = runtime.paths.clone();
    let world = crate::surfaces::world();
    let reading_home = home.clone();
    let job = Box::new(move || {
        let store = saved(&paths);
        let read_real = || (world.account_read)(&paths);
        let run = |store: &Profiles, profile_id: &str, now: i64| {
            (world.accounts_read_one)(&paths, store, profile_id, now)
        };
        let ended = read_all(&store, &reading_home, &run, &read_real, &wall).unwrap_or(UNKNOWN);
        if let Some(reading) = hold().reading.get_mut(&reading_home) {
            reading.state = Some(ended.to_owned());
        }
    });
    if !(crate::surfaces::world().spawn)(job) {
        if let Some(reading) = hold().reading.get_mut(&home) {
            reading.state = Some(UNKNOWN.to_owned());
        }
        return Ok(refusal(Refusal::StateUnavailable));
    }
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("started", Value::Bool(true)),
        ("read_state", text(READING)),
        ("read_next_at", int(now + READ_EVERY)),
    ]))
}

/// A saved account's usage read on a scratch home (`swap.read_profile`'s shape): its found, `present` None where it
/// could not be read.
pub type ReadOne<'a> = dyn Fn(&Profiles, &str, i64) -> std::result::Result<Map, Fault> + 'a;

/// One saved account's turn under the lock.
enum Step {
    Held,
    Found(bool),
    Raised(Fault),
}

/// `read_all(paths, store, home, run=, read_real=, clock=)`: Read usage's thread - READ, HELD or UNKNOWN; an `Err` is a
/// raise (the caller's UNKNOWN).
pub fn read_all(
    store: &Profiles,
    home: &Path,
    run: &ReadOne<'_>,
    read_real: &dyn Fn() -> Value,
    clock: &dyn Fn() -> f64,
) -> std::result::Result<&'static str, Fault> {
    let current = match crate::codex::account::identity(&read_real()) {
        Ok(Some(current)) => current,
        _ => return Ok(UNKNOWN),
    };
    let profile = |error: profiles::ProfileError| Fault::new(error.class, &error.message);
    let switched = store.last_switch_at().map_err(profile)?;
    let mut targets = Vec::new();
    for profile_id in store.ids() {
        let found = match store.get(&text(&profile_id)) {
            Ok(found) => found,
            Err(error) if !matches!(error.class, "RecursionError" | "TypeError") => continue,
            Err(error) => return Err(profile(error)),
        };
        let email = match found.get("email") {
            Some(Value::Str(email)) if !email.is_empty() => {
                Str::from_code_points(car_policy::classify::text::lower(email))
                    .map_or(Value::Null, Value::Str)
            }
            Some(other) if pyval::truthy(other) => {
                return Err(Fault::new(
                    "AttributeError",
                    "object has no attribute 'lower'",
                ));
            }
            _ => text(""),
        };
        if pyval::eq(&email, &current) && matches!(email, Value::Str(_)) {
            seen(store, &text(&profile_id), clock());
        } else if store.state(&found, None) != NEEDS_SIGN_IN {
            targets.push(profile_id);
        }
    }
    if let Some(reading) = hold().reading.get_mut(home) {
        reading.of = Some(targets.len() as i64);
    }
    for (done, profile_id) in targets.iter().enumerate() {
        let mut broke = true;
        let outcome = store.locked(KEEP_SECONDS, || {
            if !matches!(store.intent()?, Value::Null)
                || !pyval::eq(&store.last_switch_at()?, &switched)
            {
                return Ok(Step::Held);
            }
            Ok(match run(store, profile_id, clock().trunc() as i64) {
                Ok(found) => Step::Found(matches!(found.get("present"), None | Some(Value::Null))),
                Err(raised) => Step::Raised(raised),
            })
        });
        match outcome {
            Ok(Step::Held) => return Ok(HELD),
            Ok(Step::Found(unread)) => broke = unread,
            Ok(Step::Raised(raised)) => return Err(raised),
            Err(error) if error.class == "Locked" => {}
            Err(error) => return Err(profile(error)),
        }
        if let Some(reading) = hold().reading.get_mut(home) {
            reading.done = done as i64 + 1;
            if broke {
                reading.failed.push(profile_id.clone());
            }
        }
    }
    Ok(READ)
}

/// `add(runtime, start=, run=)`: advanced-accounts-add, Add an account.
pub fn add(runtime: &Runtime) -> Result<Value> {
    if !kept_standing(runtime) {
        return Ok(refusal(Refusal::NotOn));
    }
    let home = home_of(runtime);
    {
        let mut held = hold();
        if held.adding.get(&home).is_some_and(|word| word == WAITING) {
            return Ok(refusal(Refusal::SwitchRunning));
        }
        held.adding.insert(home.clone(), WAITING.to_owned());
    }
    let paths = runtime.paths.clone();
    let world = crate::surfaces::world();
    let adding = home.clone();
    let job = Box::new(move || {
        let added = matches!((world.accounts_add)(&paths, &saved(&paths)), Ok(Some(_)));
        hold()
            .adding
            .insert(adding, (if added { ADDED } else { NOT_ADDED }).to_owned());
    });
    if !(crate::surfaces::world().spawn)(job) {
        hold().adding.insert(home, NOT_ADDED.to_owned());
        return Ok(refusal(Refusal::StateUnavailable));
    }
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("add_state", text(WAITING)),
    ]))
}

/// `save(runtime, store=, codex_home=, read_real=)`: advanced-accounts-save, Save the account in use.
pub fn save(runtime: &Runtime) -> Result<Value> {
    if !kept_standing(runtime) {
        return Ok(refusal(Refusal::NotOn));
    }
    let store = saved(&runtime.paths);
    let home = codex_home(runtime)?;
    let world = crate::surfaces::world();
    let paths = runtime.paths.clone();
    let read_real = move || (world.account_read)(&paths);
    let kept = crate::codex::swap::save_current(&store, &home, &read_real).map_err(fault)?;
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("saved", Value::Bool(kept.is_some())),
    ]))
}

/// `delete(runtime, argument, store=, codex_home=)`: advanced-accounts-delete, {"id": ...} or {"all": true}, in every
/// state.
pub fn delete(runtime: &Runtime, argument: &Value) -> Result<Value> {
    let store = saved(&runtime.paths);
    let all = matches!(field(argument, "all"), Value::Bool(true));
    let codex = if all { codex_home(runtime).ok() } else { None };
    let profile_id = field(argument, "id");
    let outcome = store.locked(LOCK_SECONDS, || {
        if all {
            let deleted = store.delete_all(codex.as_deref())?;
            return Ok(object(vec![
                ("done", Value::Bool(true)),
                ("refusal", Value::Null),
                ("deleted", int(deleted)),
            ]));
        }
        let known = match &profile_id {
            Value::Str(id) => store.ids().iter().any(|one| id.as_str() == Some(one)),
            _ => false,
        };
        if !known {
            return Ok(refusal(Refusal::OptionInvalid));
        }
        Ok(object(vec![
            ("done", Value::Bool(true)),
            ("refusal", Value::Null),
            ("deleted", int(i64::from(store.delete(&profile_id)))),
        ]))
    });
    match outcome {
        Ok(found) => Ok(found),
        Err(error) if error.class == "Locked" => Ok(refusal(Refusal::AccountsHeld)),
        Err(error) => Err(profile_error(error)),
    }
}

/// `_journal(runtime, word)`: one line of a person's switch, under the automatic switch - or under account_switch.
fn journal(runtime: &Runtime, word: &str) {
    for capability in STANDING {
        if runtime.registry.get(capability).is_none() {
            continue;
        }
        if let Ok(state) = state(runtime, "counted")
            && matches!(
                state.counted(&text(capability), &text(word), &Value::Null),
                Ok(true)
            )
        {
            return;
        }
    }
}

/// `switch(runtime, argument, ...)`: advanced-accounts-switch, Switch to this account.
pub fn switch(runtime: &Runtime, argument: &Value) -> Result<Value> {
    let profile_id = field(argument, "id");
    let Value::Str(profile_text) = &profile_id else {
        return Ok(refusal(Refusal::OptionInvalid));
    };
    let profile_text = profile_text.as_str().unwrap_or_default().to_owned();
    if runtime.registry.get(CAPABILITY).is_none() {
        return Ok(refusal(Refusal::SwitchUnmeasured));
    }
    let store = saved(&runtime.paths);
    let rows = store.view().map_err(profile_error)?;
    let Some(row) = rows
        .iter()
        .find(|row| row.get("id").is_some_and(|id| pyval::eq(id, &profile_id)))
    else {
        return Ok(refusal(Refusal::OptionInvalid));
    };
    if pyval::eq(&profile_id, &in_use(&rows)) {
        return Ok(refusal(Refusal::AccountInUse));
    }
    let row_state = row.get("state").cloned().unwrap_or(Value::Null);
    if is(&row_state, NEEDS_SIGN_IN) || is(&row_state, DAMAGED) {
        return Ok(refusal(Refusal::AccountNotReady));
    }
    let codex = codex_home(runtime)?;
    if usable(Ok(codex.clone())) != authfile::USABLE {
        return Ok(refusal(Refusal::SignInNotFile));
    }
    let world = crate::surfaces::world();
    if (world.accounts_busy)(&runtime.paths) {
        return Ok(refusal(Refusal::RestartBusy));
    }
    if (world.other_engine)() {
        return Ok(refusal(Refusal::OtherEngine));
    }
    let home = home_of(runtime);
    let mask = row.get("mask").cloned().unwrap_or(Value::Null);
    {
        let mut held = hold();
        let switching = held
            .switching
            .get(&home)
            .is_some_and(|(word, _)| word == SWITCHING);
        let reading = held
            .reading
            .get(&home)
            .is_some_and(|reading| reading.state.as_deref() == Some(READING));
        if switching || reading || !matches!(store.intent().map_err(profile_error)?, Value::Null) {
            return Ok(refusal(Refusal::AccountsHeld));
        }
        match store.locked(0.0, || Ok(())) {
            Ok(()) => {}
            Err(error) if error.class == "Locked" => return Ok(refusal(Refusal::AccountsHeld)),
            Err(error) => return Err(profile_error(error)),
        }
        held.switching
            .insert(home.clone(), (SWITCHING.to_owned(), mask.clone()));
    }
    let shared = runtime.me.borrow().clone();
    let paths = runtime.paths.clone();
    let switching_home = home.clone();
    let kept_mask = mask.clone();
    let job = Box::new(move || {
        let at = wall().trunc() as i64;
        let outcome = (world.accounts_put_in)(&paths, &codex, &profile_text, at)
            .unwrap_or(crate::codex::swap::FAILED);
        let word = if outcome == crate::codex::swap::SWITCHED {
            engine::MANUAL_SWITCHED
        } else if engine::MANUAL_NOTHING.contains(&outcome) {
            engine::MANUAL_NOT_DONE
        } else {
            engine::MANUAL_NOT_FINISHED
        };
        if let Some(shared) = shared.upgrade() {
            shared.enter(|runtime| {
                if outcome == crate::codex::swap::SWITCHED
                    && runtime.states(true, &[]).state_of(CAPABILITY) == ArmingState::Armed
                    && let Ok(state) = state(runtime, "stamp")
                {
                    let _ = state.stamp(
                        &text(CAPABILITY),
                        &text(OptionKey::AutoSwitchedAt.as_str()),
                        &int(at.max(1)),
                    );
                }
                journal(runtime, word);
            });
        }
        hold()
            .switching
            .insert(switching_home, (outcome.to_owned(), kept_mask));
    });
    if !(crate::surfaces::world().spawn)(job) {
        hold().switching.remove(&home);
        return Ok(refusal(Refusal::StateUnavailable));
    }
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("switch_state", text(SWITCHING)),
        ("switch_mask", mask),
    ]))
}
