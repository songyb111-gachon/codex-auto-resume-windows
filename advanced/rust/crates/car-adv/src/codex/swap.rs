//! `codex/swap.py` (seat S7.2b): account_auto_switch's two acts on Codex - read a saved account's usage, and switch the
//! Codex app to it.
//!
//! [`read_profile`] reads one saved account on a scratch Codex home made from its sealed copy (`authfile::Scratch`):
//! one finite session of this capability's own asks account/read and account/rateLimits/read there - never on the real
//! home. A copy Codex refreshed there is sealed back into the profile; one Codex answers as signed out is marked as
//! needing a sign-in. What comes back is closed: present, whether it is the profile's own account, the plan word,
//! whether usage is available, the most used window and the latest reset of a full window - never an address. Every
//! read is kept in the profile for the card's meters, and the whole read holds the saved accounts' lock.
//!
//! [`switch`] puts a profile's account in: the switch written down (the intent); the Codex app closed as the account
//! switch's Restart closes it; with nothing of the app left to write it, the sign-in file in use sealed back into its
//! own profile and the target's copy put in its place in one rename - only while no other Codex engine may use this
//! home ([`other_engines`]) and only where the file is still the one read at the start (or the same account's); the app
//! started again and the account read afresh; a definite other answer puts the previous file back (NOT_SIGNED_IN, or
//! NOT_PUT_BACK where it could not yet), an answer that does not come is UNVERIFIED. [`recover`] settles what a switch
//! left at the next look; [`unwind`] before Delete all.
//!
//! Each hand is a seam ([`World`], the restart and the account read on the real home); a test fills them all.

use std::path::Path;

use car_codex::system::System;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;

use super::account::{self, Opener, Runner};
use super::authfile::{self, Fault, Scratch};
use super::restart as restarts;
use crate::profiles::{self, Profiles, bytes_value, value_bytes};
use crate::state::seam::Tokens;

pub const CAPABILITY: &str = "account_auto_switch";
pub const ACCOUNT_READ: &str = "account/read";
pub const USAGE_READ: &str = "account/rateLimits/read";
pub const ROOM_BELOW: i64 = 95;
pub const SWITCHED: &str = "switched";
pub const NOT_SIGNED_IN: &str = "not_signed_in";
pub const NOT_USABLE: &str = "not_usable";
pub const NOT_CLOSED: &str = "not_closed";
pub const FAILED: &str = "failed";
pub const LEFT: &str = "left";
pub const NOT_PUT_BACK: &str = "not_put_back";
pub const CHANGED: &str = "changed_under";
pub const LOCKED: &str = "locked";
pub const HELD: &str = "held";
pub const NOT_STARTED: &str = "not_started";
pub const ENGINE_ALIVE: &str = "engine_alive";
pub const UNVERIFIED: &str = "unverified";
pub const OUTCOMES: [&str; 13] = [
    SWITCHED,
    NOT_SIGNED_IN,
    NOT_USABLE,
    NOT_CLOSED,
    FAILED,
    LEFT,
    NOT_PUT_BACK,
    CHANGED,
    LOCKED,
    NOT_STARTED,
    ENGINE_ALIVE,
    HELD,
    UNVERIFIED,
];
pub const SWAP: &str = "swap";
pub const BACK: &str = "back";
pub const VERIFY: &str = "verify";
pub const AFTER_TRIES: usize = 3;
pub const AFTER_PAUSE: f64 = 10.0;
pub const BACK_TRIES: i64 = 3;
pub const ENGINES_SETTLE: f64 = 15.0;
pub const ENGINES_LOOK: f64 = 0.5;
pub const DAY_MINUTES: i64 = 1440;

/// What the reference's module reads of the world and a test replaces: the random names, the private access list and
/// the pause of `authfile`, the process list (`_inventory`: None where it cannot be read), the app servers this process
/// holds (`pairing._OWN`'s pids), core's pairing rules, whether the app runs now (`pairing.app_running_now`), and the
/// clock and the sleep of the waits (`_clock`, `_sleep`).
pub struct World<'a> {
    pub tokens: &'a dyn Tokens,
    pub private: &'a dyn Fn(&Path) -> bool,
    pub pause: &'a dyn Fn(f64),
    pub inventory: &'a dyn Fn() -> Option<Vec<Value>>,
    pub own: &'a dyn Fn() -> Vec<Value>,
    pub system: &'a dyn System,
    pub app_running: &'a dyn Fn() -> Option<bool>,
    pub clock: &'a dyn Fn() -> f64,
    pub sleep: &'a dyn Fn(f64),
}

/// `restart(between)`: codex/restart.restart's shape, given what to do once the app is gone - (outcome, how), or None
/// where its hands said no right before the close. Whatever `between` raises, the restart swallows.
pub type Restart<'a> = dyn FnMut(&mut dyn FnMut() -> Result<(), Fault>) -> Result<Option<(Value, Value)>, Fault> + 'a;

fn text(value: &str) -> Value {
    Value::Str(Str::new(value))
}

fn get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

fn field(map: &Map, key: &str) -> Value {
    map.get(key).cloned().unwrap_or(Value::Null)
}

fn is_true(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Bool(true)))
}

fn is_false(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Bool(false)))
}

fn truthy(value: Option<&Value>) -> bool {
    value.is_some_and(pyval::truthy)
}

fn word(value: &Value, wanted: &str) -> bool {
    pyval::is(value, wanted)
}

/// `with store.locked(seconds): body()` - a Locked (or anything the lock raised) as the reference's Locked; what the
/// body raised goes on as it was.
pub fn locked<T>(
    store: &Profiles,
    seconds: f64,
    body: impl FnOnce() -> Result<T, Fault>,
) -> Result<T, Fault> {
    let mut answer: Option<Result<T, Fault>> = None;
    store
        .locked(seconds, || {
            answer = Some(body());
            Ok(())
        })
        .map_err(Fault::from)?;
    answer.unwrap_or_else(|| Err(Fault::new("Locked", "the saved accounts are held")))
}

fn clock(store: &Profiles) -> f64 {
    (store.clock)()
}

/// `int(now or store._clock())`.
fn stamp_of(store: &Profiles, now: Option<f64>) -> Value {
    let at = match now {
        Some(at) if at != 0.0 => at,
        _ => clock(store),
    };
    Value::from(at.trunc() as i64)
}

fn auth_of(profile: &Map) -> Vec<u8> {
    value_bytes(&field(profile, "auth")).unwrap_or_default()
}

fn pairs(fields: Vec<(&str, Value)>) -> Vec<(String, Value)> {
    fields
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value))
        .collect()
}

// ------------------------------------------------------------------------------------------------ engines
/// `_born(row)`.
enum Born<'a> {
    Untimed,
    Unread,
    At(&'a Value),
}

fn born(row: &Value) -> Born<'_> {
    let Value::Object(map) = row else {
        return Born::Untimed;
    };
    match map.get("created") {
        None => Born::Untimed,
        Some(value @ Value::Int(_)) if pyval::greater(value, &Value::from(0)).unwrap_or(false) => {
            Born::At(value)
        }
        Some(_) => Born::Unread,
    }
}

/// Whether `parent` cannot have started `child`: created after it, or a time that could not be read.
fn younger(parent: &Value, child: &Value) -> bool {
    match (born(parent), born(child)) {
        (Born::Untimed, _) | (_, Born::Untimed) => false,
        (Born::At(up), Born::At(down)) => pyval::greater(up, down).unwrap_or(false),
        _ => true,
    }
}

fn unhashable() -> Fault {
    Fault::new("TypeError", "unhashable type")
}

fn hashed(value: &Value) -> Result<(), Fault> {
    pyval::hashable(value).map_err(|_| unhashable())
}

/// `other_engines(rows, app_open=)`: whether a Codex engine runs that may use this Codex home and is not the app's own
/// - every codex.exe counts but the app main's descendants while the app is open (by parents through the rows, a
/// parent created after its child not being its parent) and the app servers this process holds; rows that cannot be
/// read count as one. It ends no process. An unhashable pid or parent raises TypeError, as the reference's dict does.
pub fn other_engines(
    rows: Option<&[Value]>,
    app_open: bool,
    own: &[Value],
    system: &dyn System,
) -> Result<bool, Fault> {
    let Some(rows) = rows else {
        return Ok(true);
    };
    let mut main = Value::Null;
    if app_open
        && let Ok(found) = car_codex::pairing::app_main(system, rows)
        && let Some(pid) = get(found, "pid")
    {
        main = pid.clone();
    }
    let mut listed: Vec<(Value, Option<&Value>)> = Vec::new();
    for each in rows.iter().filter(|each| matches!(each, Value::Object(_))) {
        let pid = get(each, "pid").cloned().unwrap_or(Value::Null);
        hashed(&pid)?;
        match listed.iter_mut().find(|(key, _)| pyval::eq(key, &pid)) {
            Some(slot) => slot.1 = None,
            None => listed.push((pid, Some(each))),
        }
    }
    let under_main = |row: &Value| -> Result<bool, Fault> {
        let mut seen: Vec<Value> = Vec::new();
        let mut child = row;
        let mut at = get(row, "parent").cloned().unwrap_or(Value::Null);
        loop {
            if matches!(at, Value::Null) {
                return Ok(false);
            }
            hashed(&at)?;
            if seen.iter().any(|each| pyval::eq(each, &at)) || seen.len() > rows.len() {
                return Ok(false);
            }
            let up = listed
                .iter()
                .find(|(key, _)| pyval::eq(key, &at))
                .and_then(|(_, row)| *row);
            let Some(up) = up else {
                return Ok(false);
            };
            if younger(up, child) {
                return Ok(false);
            }
            if pyval::eq(&at, &main) {
                return Ok(true);
            }
            seen.push(at.clone());
            child = up;
            at = get(up, "parent").cloned().unwrap_or(Value::Null);
        }
    };
    for row in rows {
        if !matches!(row, Value::Object(_)) || !matches!(get(row, "path"), Some(Value::Str(_))) {
            return Ok(true);
        }
        let pid = get(row, "pid").cloned().unwrap_or(Value::Null);
        if !car_codex::pairing::engine_row(system, row) || own.iter().any(|each| pyval::eq(each, &pid)) {
            continue;
        }
        if !matches!(main, Value::Null) && !pyval::eq(&pid, &main) && under_main(row)? {
            continue;
        }
        return Ok(true);
    }
    Ok(false)
}

/// `engines_gone(seconds)`: whether no other engine runs (the app closed), looking again every ENGINES_LOOK seconds
/// for at most `seconds`. It ends no process.
pub fn engines_gone(world: &World, seconds: f64) -> Result<bool, Fault> {
    let deadline = (world.clock)() + seconds;
    loop {
        let rows = (world.inventory)();
        if !other_engines(rows.as_deref(), false, &(world.own)(), world.system)? {
            return Ok(true);
        }
        if (world.clock)() >= deadline {
            return Ok(false);
        }
        (world.sleep)(ENGINES_LOOK);
    }
}

// ------------------------------------------------------------------------------------------------ usage
/// Python's `round(x, 1)` of a float: the correctly rounded one-decimal text read back.
pub fn round1(x: f64) -> f64 {
    format!("{x:.1}").parse().unwrap_or(x)
}

fn is_number(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Int(_) | Value::Float(_)))
}

/// `meters(windows)`: {five_hour, weekly} of a reading's windows for the card - each {used, resets_at}, or None. Codex's
/// own bucket first; another only where it has none.
pub fn meters(windows: &[Value]) -> Result<Map, Fault> {
    let rows: Vec<&Value> = windows
        .iter()
        .filter(|window| matches!(window, Value::Object(_)) && is_number(get(window, "used_percent")))
        .collect();
    let codex: Vec<&Value> = rows
        .iter()
        .copied()
        .filter(|window| get(window, "bucket").is_some_and(|bucket| word(bucket, "codex")))
        .collect();
    let rows = if codex.is_empty() { rows } else { codex };
    let mut found = Map::new();
    found.insert(Str::new("five_hour"), Value::Null);
    found.insert(Str::new("weekly"), Value::Null);
    for window in rows {
        let name = match get(window, "window_minutes") {
            Some(minutes @ Value::Int(_)) => Some(
                if pyval::less(minutes, &Value::from(DAY_MINUTES)).unwrap_or(false) {
                    "five_hour"
                } else {
                    "weekly"
                },
            ),
            _ => {
                let which = get(window, "window").cloned().unwrap_or(Value::Null);
                hashed(&which)?;
                if word(&which, "primary") {
                    Some("five_hour")
                } else if word(&which, "secondary") {
                    Some("weekly")
                } else {
                    None
                }
            }
        };
        let Some(name) = name else {
            continue;
        };
        if !matches!(found.get(name), Some(Value::Null)) {
            continue;
        }
        let used = car_machine::pytext::to_float(get(window, "used_percent").unwrap_or(&Value::Null))
            .map_err(|class| Fault::new(class, "float()"))?;
        let reset = match get(window, "reset_at") {
            Some(reset @ Value::Int(_)) => reset.clone(),
            _ => Value::Null,
        };
        let mut meter = Map::new();
        meter.insert(Str::new("used"), Value::Float(round1(used)));
        meter.insert(Str::new("resets_at"), reset);
        found.insert(Str::new(name), Value::Object(meter));
    }
    Ok(found)
}

fn core(class: &'static str) -> Fault {
    Fault::new(class, "raised by core's usage reading")
}

/// `usage_of(reply)`: {available, most_used, full_until, five_hour, weekly} of one account/rateLimits/read answer
/// (core's allowlist).
pub fn usage_of(reply: &Value) -> Result<Map, Fault> {
    let parsed = Value::Object(car_codex::usage::parse_usage(reply).map_err(core)?);
    let windows = car_machine::domain::usage::windows_of(&parsed)
        .map_err(core)?
        .unwrap_or_default();
    let item = |window: &Value, key: &str| -> Result<Value, Fault> {
        get(window, key)
            .cloned()
            .ok_or_else(|| Fault::new("KeyError", key))
    };
    let mut used = Vec::new();
    let mut full = Vec::new();
    for window in &windows {
        used.push(item(window, "used_percent")?);
    }
    for window in &windows {
        let percent = item(window, "used_percent")?;
        if pyval::order(&percent, &Value::from(100))
            .map_err(core)?
            .is_some_and(|order| order != std::cmp::Ordering::Less)
            && !matches!(get(window, "reset_at"), None | Some(Value::Null))
        {
            full.push(item(window, "reset_at")?);
        }
    }
    let resets = if !full.is_empty() {
        full
    } else if is_false(get(&parsed, "available")) && truthy(get(&parsed, "reset_at")) {
        vec![item(&parsed, "reset_at")?]
    } else {
        Vec::new()
    };
    let maximum = |values: &[Value]| -> Result<Value, Fault> {
        if values.is_empty() {
            return Ok(Value::Null);
        }
        let all: Vec<&Value> = values.iter().collect();
        pyval::max(&all).cloned().map_err(core)
    };
    let mut found = Map::new();
    found.insert(
        Str::new("available"),
        match get(&parsed, "available") {
            Some(Value::Bool(on)) => Value::Bool(*on),
            _ => Value::Null,
        },
    );
    found.insert(Str::new("most_used"), maximum(&used)?);
    found.insert(Str::new("full_until"), maximum(&resets)?);
    for (key, value) in meters(&windows)? {
        found.insert(key, value);
    }
    Ok(found)
}

/// `has_room(found)`: its own account, usage available, every window below ROOM_BELOW.
pub fn has_room(found: &Value) -> bool {
    is_true(get(found, "present"))
        && is_true(get(found, "own"))
        && is_true(get(found, "available"))
        && matches!(
            get(found, "most_used"),
            Some(most @ (Value::Int(_) | Value::Float(_) | Value::Bool(_)))
                if pyval::less(most, &Value::from(ROOM_BELOW)).unwrap_or(false)
        )
}

// ------------------------------------------------------------------------------------------------ adding and saving
/// `default_backend_for(paths)`'s and `session_for`'s hands: a backend on a Codex home, or why it could not be made.
pub trait BackendFor {
    fn backend(&self, home: &Path) -> Result<Box<dyn account::Backend + '_>, Fault>;
}

/// `add_by_login(paths, store, ...)`: Codex's own `codex login` on a scratch home, then that home's sign-in file sealed
/// as a profile with the address and plan account/read answers there; the scratch home removed whatever happened. The
/// profile's id, or None.
pub fn add_by_login(
    world: &World,
    store: &Profiles,
    backend_for: &dyn BackendFor,
    session_for: &dyn Opener,
    runner: &dyn Runner,
    seconds: Option<f64>,
) -> Result<Option<String>, Fault> {
    let mut scratch = Scratch::new(&store.directory, None);
    let read = scratch.with(world.tokens, world.private, world.pause, |home| {
        let backend = backend_for.backend(home)?;
        let mut argv = backend.argv()?;
        argv.push("login".to_owned());
        let seconds = seconds.filter(|seconds| *seconds != 0.0).unwrap_or(account::LOGIN_SECONDS);
        let code = account::run_codex(runner, &argv, backend.as_ref(), seconds)?;
        if !matches!(&code, account::Exit::Code(code) if pyval::eq(code, &Value::from(0))) {
            return Ok(None);
        }
        let mut session = session_for.open(Some(home))?;
        let found = account::parse(&session.call(ACCOUNT_READ, Value::Object(Map::new()))?);
        drop(session);
        let data = authfile::read(home)?;
        Ok(Some((found, data)))
    });
    let Ok(Some((found, data))) = read else {
        return Ok(None);
    };
    if !is_true(get(&found, "present")) || !truthy(get(&found, "email")) {
        return Ok(None);
    }
    let email = get(&found, "email").cloned().unwrap_or(Value::Null);
    let plan = get(&found, "plan_word").cloned().unwrap_or(Value::Null);
    match locked(store, profiles::LOCK_SECONDS, || Ok(store.save(&data, &email, &plan)?)) {
        Ok(saved) => Ok(Some(saved)),
        Err(fault) if fault.is_os() => Ok(None),
        Err(fault) => Err(fault),
    }
}

/// `save_current(paths, store, codex_home, read_real=)`: the account in use saved - the real sign-in file sealed as
/// its profile. Its id, or None where the sign-in is not a file or the account cannot be told apart.
pub fn save_current(
    store: &Profiles,
    codex_home: &Path,
    read_real: &dyn Fn() -> Value,
) -> Result<Option<String>, Fault> {
    if authfile::usable(codex_home)? != authfile::USABLE {
        return Ok(None);
    }
    let found = read_real();
    let Value::Object(_) = &found else {
        return Err(Fault::new("AttributeError", "object has no attribute 'get'"));
    };
    if !is_true(get(&found, "present")) || !truthy(get(&found, "email")) {
        return Ok(None);
    }
    let email = get(&found, "email").cloned().unwrap_or(Value::Null);
    let plan = get(&found, "plan_word").cloned().unwrap_or(Value::Null);
    let saved = locked(store, profiles::LOCK_SECONDS, || {
        let data = authfile::read(codex_home)?;
        let saved = store.save(&data, &email, &plan)?;
        let seen = Value::from(clock(store).trunc() as i64);
        store.update(&text(&saved), &pairs(vec![("seen_at", seen)]))?;
        Ok(saved)
    });
    match saved {
        Ok(saved) => Ok(Some(saved)),
        Err(fault) if fault.is_os() => Ok(None),
        Err(fault) => Err(fault),
    }
}

// ------------------------------------------------------------------------------------------------ reading
fn unread() -> Map {
    let mut found = Map::new();
    for key in [
        "present",
        "own",
        "plan",
        "available",
        "most_used",
        "full_until",
        "five_hour",
        "weekly",
    ] {
        found.insert(Str::new(key), Value::Null);
    }
    found
}

/// `read_profile(paths, store, profile_id, session_for=, now=)`: one read of a saved account on a scratch home - or
/// {present: None, ...} where it could not be read or another read, switch or save held the saved accounts.
pub fn read_profile(
    world: &World,
    store: &Profiles,
    profile_id: &Value,
    session_for: &dyn Opener,
    now: Option<f64>,
) -> Result<Map, Fault> {
    let found = unread();
    match locked(store, profiles::KEEP_SECONDS, || {
        read_one(world, store, profile_id, found.clone(), session_for, now)
    }) {
        Err(fault) if fault.class == "Locked" => Ok(found),
        other => other,
    }
}

fn read_one(
    world: &World,
    store: &Profiles,
    profile_id: &Value,
    mut found: Map,
    session_for: &dyn Opener,
    now: Option<f64>,
) -> Result<Map, Fault> {
    let profile = match store.get(profile_id) {
        Ok(profile) => profile,
        Err(error) => {
            let fault = Fault::from(error);
            return if fault.is_profile() { Ok(found) } else { Err(fault) };
        }
    };
    let auth = auth_of(&profile);
    let mut scratch = Scratch::new(&store.directory, Some(auth.clone()));
    let read = scratch.with(world.tokens, world.private, world.pause, |home| {
        let mut session = session_for.open(Some(home))?;
        let account = account::parse(&session.call(ACCOUNT_READ, Value::Object(Map::new()))?);
        let usage = if is_true(get(&account, "present")) {
            Some(session.call(USAGE_READ, Value::Object(Map::new()))?)
        } else {
            None
        };
        Ok((account, usage))
    });
    let (account, usage) = match read {
        Ok(read) => read,
        Err(_) => {
            // A read that broke after Codex refreshed the tokens there: the newer copy is kept all the same.
            let mut changes = vec![("unread_at", stamp_of(store, now))];
            if let Some(after) = scratch.after.as_ref().filter(|after| **after != auth) {
                changes.push(("auth", bytes_value(after)));
            }
            let changes = pairs(changes);
            let kept = locked(store, profiles::KEEP_SECONDS, || {
                Ok(store.update(profile_id, &changes)?)
            });
            if let Err(fault) = kept
                && !fault.is_os()
            {
                return Err(fault);
            }
            return Ok(found);
        }
    };
    let present = get(&account, "present").cloned().unwrap_or(Value::Null);
    found.insert(Str::new("present"), present.clone());
    let own = match profile.get("email") {
        Some(Value::Str(saved)) if pyval::truthy(&present) => {
            let lowered = car_policy::classify::text::lower(saved);
            let saved = Str::from_code_points(lowered).map_or(Value::Null, Value::Str);
            Value::Bool(account::identity(&account)?.is_some_and(|text| pyval::eq(&text, &saved)))
        }
        _ => Value::Null,
    };
    found.insert(Str::new("own"), own);
    found.insert(
        Str::new("plan"),
        get(&account, "plan_word").cloned().unwrap_or(Value::Null),
    );
    if let Some(usage) = &usage {
        for (key, value) in usage_of(usage)? {
            found.insert(key, value);
        }
    }
    let noted = locked(store, profiles::KEEP_SECONDS, || {
        note_read(store, profile_id, &auth, scratch.after.as_deref(), &found, now)
    });
    if let Err(fault) = noted
        && !fault.is_os()
    {
        return Err(fault);
    }
    Ok(found)
}

/// `_note_read(...)`: what one read found, kept in the profile.
fn note_read(
    store: &Profiles,
    profile_id: &Value,
    auth: &[u8],
    after: Option<&[u8]>,
    found: &Map,
    now: Option<f64>,
) -> Result<(), Fault> {
    if is_false(found.get("present")) || is_false(found.get("own")) {
        store.update(profile_id, &pairs(vec![("failed_at", stamp_of(store, now))]))?;
        return Ok(());
    }
    let mut changes = Vec::new();
    if let Some(after) = after.filter(|after| *after != auth) {
        changes.push(("auth", bytes_value(after)));
    }
    if truthy(found.get("full_until")) {
        let until = field(found, "full_until");
        let until = match &until {
            Value::Float(x) if x.is_finite() => Value::from(x.trunc() as i64),
            Value::Float(_) => return Err(Fault::new("ValueError", "cannot convert float")),
            Value::Bool(on) => Value::from(i64::from(*on)),
            other => other.clone(),
        };
        changes.push(("exhausted_until", until));
    }
    if is_true(found.get("present")) && !matches!(found.get("available"), None | Some(Value::Null)) {
        let mut usage = Map::new();
        usage.insert(Str::new("read_at"), stamp_of(store, now));
        for key in ["available", "most_used", "five_hour", "weekly"] {
            usage.insert(Str::new(key), field(found, key));
        }
        changes.push(("usage", Value::Object(usage)));
        changes.push(("unread_at", Value::Null));
    }
    if !changes.is_empty() {
        store.update(profile_id, &pairs(changes))?;
    }
    Ok(())
}

// ------------------------------------------------------------------------------------------------ switching
/// `known(found)`: whether an account read is a definite answer - signed out, or an account told apart.
pub fn known(found: &Value) -> Result<bool, Fault> {
    if !matches!(found, Value::Object(_)) {
        return Ok(false);
    }
    Ok(is_false(get(found, "present")) || account::identity(found)?.is_some())
}

/// `read_answer(read_real, tries=)`: the account read until it gives a definite answer, `tries` reads at most,
/// AFTER_PAUSE seconds apart: the last read.
pub fn read_answer(
    world: &World,
    read_real: &dyn Fn() -> Value,
    tries: usize,
) -> Result<Value, Fault> {
    let mut found = read_real();
    for _ in 0..tries.saturating_sub(1) {
        if known(&found)? {
            break;
        }
        (world.sleep)(AFTER_PAUSE);
        found = read_real();
    }
    Ok(found)
}

/// What a put-in is known by: the bytes a switch put there, the intent's digest of them, or anything else an intent
/// file held (which no file in place ever is).
#[derive(Clone, Debug, PartialEq)]
pub enum Copy {
    Bytes(Vec<u8>),
    Digest(Value),
    Other(Value),
}

impl Copy {
    /// A profile's `auth` (bytes, carried as a list of numbers).
    fn auth(value: &Value) -> Copy {
        Copy::Bytes(value_bytes(value).unwrap_or_default())
    }

    /// The intent's `put_in`: None where it has none.
    fn kept(value: &Value) -> Option<Copy> {
        match value {
            Value::Null => None,
            Value::Str(_) => Some(Copy::Digest(value.clone())),
            other => Some(Copy::Other(other.clone())),
        }
    }

    fn value(&self) -> Value {
        match self {
            Copy::Bytes(data) => bytes_value(data),
            Copy::Digest(found) | Copy::Other(found) => found.clone(),
        }
    }
}

/// `_is_in_place(codex_home, data)`: whether the sign-in file at `codex_home` is, byte for byte, the copy (or a file of
/// that digest).
pub fn is_in_place(codex_home: &Path, data: &Copy) -> Result<bool, Fault> {
    let found = match authfile::read(codex_home) {
        Ok(found) => found,
        Err(fault) if fault.class == "AuthFileError" => return Ok(false),
        Err(fault) => return Err(fault),
    };
    Ok(match data {
        Copy::Bytes(data) => found == *data,
        Copy::Digest(digest) => pyval::eq(&text(&profiles::digest(&found)), digest),
        Copy::Other(_) => false,
    })
}

/// `_put_back(codex_home, put_in, previous, restart)`: the previous sign-in file back in place of `put_in` (only over
/// it), through `restart` or directly where Codex does not run. Whether the file in place is the previous one now.
pub fn put_back(
    world: &World,
    codex_home: &Path,
    put_in: &Copy,
    previous: &[u8],
    restart: Option<&mut Restart>,
) -> Result<bool, Fault> {
    let back = || -> Result<(), Fault> {
        if is_in_place(codex_home, put_in)? {
            authfile::replace(codex_home, previous, world.tokens)?;
        }
        Ok(())
    };
    let outcome = match restart {
        Some(restart) => {
            let mut hand = back;
            restart(&mut hand)?
        }
        None => {
            if (world.app_running)() != Some(false) {
                None
            } else {
                Some((text(restarts::NOT_RUNNING), Value::Null))
            }
        }
    };
    if let Some((outcome, _)) = &outcome
        && word(outcome, restarts::NOT_RUNNING)
    {
        match back() {
            Ok(()) => {}
            Err(fault) if fault.is_os() => {}
            Err(fault) => return Err(fault),
        }
    }
    is_in_place(codex_home, &Copy::Bytes(previous.to_vec()))
}

/// `_previous(store, intent)`: the copy a put-back puts in - the intent's own, else the previous profile's.
pub fn previous_of(store: &Profiles, intent: &Value) -> Result<Vec<u8>, Fault> {
    if let Some(Value::Str(kept)) = get(intent, "previous") {
        let opened = kept
            .as_str()
            .and_then(profiles::base64_decode)
            .ok_or_else(|| Fault::new("ProfileError", "the intent's copy cannot be opened"))?;
        return match authfile::check(&opened) {
            Ok(data) => Ok(data),
            Err(fault) if fault.is_os() => {
                Err(Fault::new("ProfileError", "the intent's copy cannot be opened"))
            }
            Err(fault) => Err(fault),
        };
    }
    let from = get(intent, "from")
        .cloned()
        .ok_or_else(|| Fault::new("KeyError", "from"))?;
    Ok(auth_of(&store.get(&from)?))
}

/// What one switch knew as it went (`done`).
#[derive(Default)]
struct Done {
    swapped: bool,
    changed: bool,
    engines: bool,
    kept: bool,
}

/// `switch(paths, store, codex_home, target_id, restart=, read_real=, now=)`: the saved account `target_id` put in as
/// Codex's sign-in at `codex_home`. One of OUTCOMES - LOCKED, and nothing done, where another switch, put-back, save or
/// delete holds the saved accounts.
pub fn switch(
    world: &World,
    store: &Profiles,
    codex_home: &Path,
    target_id: &Value,
    restart: &mut Restart,
    read_real: &dyn Fn() -> Value,
    now: Option<f64>,
) -> Result<&'static str, Fault> {
    match locked(store, 0.0, || {
        switch_held(world, store, codex_home, target_id, restart, read_real, now)
    }) {
        Err(fault) if fault.class == "Locked" => Ok(LOCKED),
        other => other,
    }
}

fn switch_held(
    world: &World,
    store: &Profiles,
    codex_home: &Path,
    target_id: &Value,
    restart: &mut Restart,
    read_real: &dyn Fn() -> Value,
    now: Option<f64>,
) -> Result<&'static str, Fault> {
    if authfile::usable(codex_home)? != authfile::USABLE {
        return Ok(NOT_USABLE);
    }
    let (target, current) = match (|| -> Result<(Map, Vec<u8>), Fault> {
        let target = store.get(target_id)?;
        Ok((target, authfile::read(codex_home)?))
    })() {
        Ok(found) => found,
        Err(fault) if fault.is_os() => return Ok(FAILED),
        Err(fault) => return Err(fault),
    };
    let stamp = stamp_of(store, now);
    let before = read_real();
    if !matches!(before, Value::Object(_)) {
        return Err(Fault::new("AttributeError", "object has no attribute 'get'"));
    }
    if !is_true(get(&before, "present")) || !truthy(get(&before, "email")) {
        return Ok(NOT_USABLE); // an account that cannot be told apart is never swapped out
    }
    let email = get(&before, "email").cloned().unwrap_or(Value::Null);
    let source_id = match (|| -> Result<String, Fault> {
        // The account in use is kept first - saved now if it never was - so its sign-in is never lost by the swap.
        match store.find(&email)? {
            Some(found) => Ok(found),
            None => Ok(store.save(
                &current,
                &email,
                &get(&before, "plan_word").cloned().unwrap_or(Value::Null),
            )?),
        }
    })() {
        Ok(found) => found,
        Err(fault) if fault.is_os() => return Ok(FAILED),
        Err(fault) => return Err(fault),
    };
    let source = text(&source_id);
    if pyval::eq(&source, target_id) {
        return Ok(FAILED);
    }
    let target_auth = auth_of(&target);
    let mut done = Done::default();
    let between = |done: &mut Done| -> Result<(), Fault> {
        // The app is gone: the file in use goes back into its own profile, then the target's copy takes its place -
        // unless another engine that may use this home still runs (or that cannot be told): then nothing is written.
        if !engines_gone(world, ENGINES_SETTLE)? {
            done.engines = true;
            return Ok(());
        }
        let mut latest = authfile::read(codex_home)?;
        if latest != current {
            if account::identity(&read_real())? != account::identity(&before)? {
                done.changed = true; // not the account being saved back: nothing is written
                return Ok(());
            }
            // That read may have refreshed the tokens and written the file: what is sealed is what is there now.
            latest = authfile::read(codex_home)?;
        }
        store.update(
            &source,
            &pairs(vec![("auth", bytes_value(&latest)), ("used_at", stamp.clone())]),
        )?;
        authfile::replace(codex_home, &target_auth, world.tokens)?;
        done.swapped = true;
        Ok(())
    };
    store.begin(
        &source,
        target_id,
        &text(SWAP),
        &Value::from(0),
        &Value::Null,
        &Value::Null,
        &Value::Null,
    )?;
    let outcome = (|| -> Result<&'static str, Fault> {
        let found = {
            let mut hand = || between(&mut done);
            restart(&mut hand)?
        };
        let Some((outcome, _how)) = found else {
            return Ok(HELD); // its hands said no at the last look: nothing was closed
        };
        if word(&outcome, restarts::NOT_RUNNING) {
            between(&mut done)?; // Codex is closed: the next start reads the new file
        } else if (word(&outcome, restarts::NOT_ENDED) || word(&outcome, restarts::FAILED))
            && !done.swapped
        {
            return Ok(NOT_CLOSED);
        }
        if done.changed {
            return Ok(CHANGED);
        }
        if done.engines {
            return Ok(ENGINE_ALIVE);
        }
        if !done.swapped {
            return Ok(FAILED);
        }
        let after = read_answer(world, read_real, AFTER_TRIES)?;
        let wanted = match target.get("email") {
            Some(found) if pyval::truthy(found) => match found {
                Value::Str(email) => Str::from_code_points(car_policy::classify::text::lower(email))
                    .map_or(Value::Null, Value::Str),
                _ => return Err(Fault::new("AttributeError", "object has no attribute 'lower'")),
            },
            _ => text(""),
        };
        let identity = account::identity(&after)?;
        if identity.as_ref().is_some_and(|found| pyval::eq(found, &wanted)) {
            store.update(
                target_id,
                &pairs(vec![("used_at", stamp.clone()), ("seen_at", stamp.clone())]),
            )?;
            let email = pyval::text(&field(&target, "email")).unwrap_or_default().to_owned();
            store.mark_switched(&email)?;
            // The app that did not come back is said as such: nothing is released early into a closed app.
            return Ok(if word(&outcome, restarts::NOT_STARTED) {
                NOT_STARTED
            } else {
                SWITCHED
            });
        }
        let to_email = field(&target, "email");
        if !known(&after)? {
            // R1: no answer is not "not signed in": the intent keeps what a put-back needs; the next look reads again.
            let previous = auth_of(&store.get(&source)?);
            store.begin(
                &source,
                target_id,
                &text(VERIFY),
                &Value::from(0),
                &bytes_value(&target_auth),
                &bytes_value(&previous),
                &to_email,
            )?;
            done.kept = true;
            return Ok(UNVERIFIED);
        }
        // Not the target: the previous file back, Codex started on it once more, and the target set aside.
        store.update(target_id, &pairs(vec![("failed_at", stamp.clone())]))?;
        let previous = auth_of(&store.get(&source)?);
        if put_back(
            world,
            codex_home,
            &Copy::Bytes(target_auth.clone()),
            &previous,
            Some(&mut *restart),
        )? {
            return Ok(NOT_SIGNED_IN);
        }
        let previous = auth_of(&store.get(&source)?);
        store.begin(
            &source,
            target_id,
            &text(BACK),
            &Value::from(0),
            &bytes_value(&target_auth),
            &bytes_value(&previous),
            &to_email,
        )?;
        done.kept = true;
        Ok(NOT_PUT_BACK)
    })();
    let answer = match outcome {
        Err(fault) if fault.is_os() => Ok(FAILED),
        other => other,
    };
    if !done.kept {
        store.end();
    }
    answer
}

/// `recover(paths, store, codex_home, read_real=, restart=)`: a switch the watcher did not see finish, settled once,
/// holding the saved accounts - LOCKED where another process's switch is under way; None where none was.
pub fn recover(
    world: &World,
    store: &Profiles,
    codex_home: &Path,
    read_real: &dyn Fn() -> Value,
    restart: Option<&mut Restart>,
) -> Result<Option<&'static str>, Fault> {
    if matches!(store.intent()?, Value::Null) {
        return Ok(None);
    }
    match locked(store, 0.0, || recover_held(world, store, codex_home, read_real, restart)) {
        Err(fault) if fault.class == "Locked" => Ok(Some(LOCKED)),
        other => other,
    }
}

fn recover_held(
    world: &World,
    store: &Profiles,
    codex_home: &Path,
    read_real: &dyn Fn() -> Value,
    restart: Option<&mut Restart>,
) -> Result<Option<&'static str>, Fault> {
    let intent = store.intent()?;
    if matches!(intent, Value::Null) {
        return Ok(None);
    }
    let mut kept = false;
    let outcome = (|| -> Result<&'static str, Fault> {
        let to = get(&intent, "to").cloned().unwrap_or(Value::Null);
        let target = if matches!(to, Value::Str(_)) {
            match store.get(&to) {
                Ok(target) => Some(target),
                Err(error) => {
                    let fault = Fault::from(error);
                    if !fault.is_profile() {
                        return Err(fault);
                    }
                    None // deleted since: the intent's own record serves
                }
            }
        } else {
            None
        };
        let to_email = match &target {
            Some(target) => field(target, "email"),
            None => get(&intent, "to_email").cloned().unwrap_or(Value::Null),
        };
        let put_in = match &target {
            Some(target) => Some(Copy::auth(&field(target, "auth"))),
            None => Copy::kept(get(&intent, "put_in").unwrap_or(&Value::Null)),
        };
        let step = get(&intent, "step").cloned().unwrap_or(Value::Null);
        let from = get(&intent, "from").cloned().unwrap_or(Value::Null);
        let found = read_real();
        let now = account::identity(&found)?;
        if let (Value::Str(email), Some(now)) = (&to_email, &now) {
            let lowered = Str::from_code_points(car_policy::classify::text::lower(email))
                .map_or(Value::Null, Value::Str);
            if pyval::eq(now, &lowered) {
                if target.is_some() {
                    let stamp = Value::from(clock(store).trunc() as i64);
                    store.update(&to, &pairs(vec![("used_at", stamp.clone()), ("seen_at", stamp)]))?;
                }
                store.mark_switched(email.as_str().unwrap_or_default())?;
                return Ok(SWITCHED);
            }
        }
        if !word(&step, BACK) && !known(&found)? && put_in.is_some() && matches!(from, Value::Str(_)) {
            kept = true; // R1: no answer, nothing undone - read again next look
            return Ok(UNVERIFIED);
        }
        let Some(put_in) = put_in else {
            return Ok(LEFT);
        };
        if !matches!(from, Value::Str(_)) || !is_in_place(codex_home, &put_in)? {
            return Ok(LEFT);
        }
        if word(&step, VERIFY) && target.is_some() {
            let stamp = Value::from(clock(store).trunc() as i64);
            store.update(&to, &pairs(vec![("failed_at", stamp)]))?;
        }
        let previous = previous_of(store, &intent)?;
        let tries = match get(&intent, "tries") {
            Some(Value::Int(_)) => get(&intent, "tries").cloned().unwrap_or(Value::from(0)),
            Some(Value::Bool(on)) => Value::from(i64::from(*on)),
            _ => Value::from(0),
        };
        let mut made = 0i64;
        let put = match restart {
            Some(restart) if pyval::less(&tries, &Value::from(BACK_TRIES)).unwrap_or(false) => {
                let mut counted = |between: &mut dyn FnMut() -> Result<(), Fault>| {
                    let found = restart(between)?;
                    if found.is_some() {
                        made += 1;
                    }
                    Ok(found)
                };
                put_back(
                    world,
                    codex_home,
                    &put_in,
                    &previous,
                    Some(&mut counted as &mut Restart),
                )?
            }
            _ => put_back(world, codex_home, &put_in, &previous, None)?,
        };
        if put {
            return Ok(NOT_SIGNED_IN);
        }
        let tries = if made == 0 {
            tries
        } else {
            tries_plus(&tries, made).unwrap_or(tries)
        };
        store.begin(
            &from,
            &to,
            &text(BACK),
            &tries,
            &put_in.value(),
            &bytes_value(&previous),
            &to_email,
        )?;
        kept = true;
        Ok(NOT_PUT_BACK)
    })();
    let answer = match outcome {
        Ok(word) => Ok(Some(word)),
        Err(fault) if fault.is_os() => Ok(Some(FAILED)),
        Err(fault) => Err(fault),
    };
    if !kept {
        store.end();
    }
    answer
}

fn tries_plus(tries: &Value, made: i64) -> Option<Value> {
    match tries {
        Value::Int(number) => number
            .as_i64()
            .and_then(|tries| tries.checked_add(made))
            .map(Value::from),
        _ => None,
    }
}

/// `unwind(store, codex_home)`: before Delete all - whether nothing a switch left waits on the saved accounts any more.
pub fn unwind(world: &World, store: &Profiles, codex_home: Option<&Path>) -> Result<bool, Fault> {
    let intent = store.intent()?;
    let Some(codex_home) = codex_home else {
        return Ok(true);
    };
    if matches!(intent, Value::Null) || truthy(get(&intent, "damaged")) {
        return Ok(true);
    }
    let found = (|| -> Result<Option<(Copy, Vec<u8>)>, Fault> {
        let mut put_in = Copy::kept(get(&intent, "put_in").unwrap_or(&Value::Null));
        if put_in.is_none()
            && let Some(to @ Value::Str(_)) = get(&intent, "to")
        {
            put_in = Some(Copy::auth(&field(&store.get(to)?, "auth")));
        }
        let Some(put_in) = put_in else {
            return Ok(None);
        };
        Ok(Some((put_in, previous_of(store, &intent)?)))
    })();
    let (put_in, previous) = match found {
        Ok(Some(found)) => found,
        Ok(None) => return Ok(true),
        Err(fault) if fault.is_profile() || ["KeyError", "TypeError"].contains(&fault.class.as_str()) => {
            return Ok(true); // nothing kept to put back: deleting loses nothing more
        }
        Err(fault) => return Err(fault),
    };
    if !is_in_place(codex_home, &put_in)? {
        return Ok(true);
    }
    if put_back(world, codex_home, &put_in, &previous, None)? {
        store.end();
        return Ok(true);
    }
    Ok(false)
}

// ------------------------------------------------------------------------------------------------ the product's world
/// The product's own world for the switch: random names from the system, the private access list, real pauses, core's
/// process list read afresh, Windows through car-codex's Platform, the monotonic clock. `pairing._OWN` is not readable
/// from car-codex (no getter; seam left in rust/GROUNDWORK.md), so no app server is taken as this process's own.
pub struct Live {
    pub system: std::sync::Arc<car_codex::system::Platform>,
    inventory: Box<dyn Fn() -> Option<Vec<Value>> + Send + Sync>,
    app_running: Box<dyn Fn() -> Option<bool> + Send + Sync>,
    clock: Box<dyn Fn() -> f64 + Send + Sync>,
}

impl Default for Live {
    fn default() -> Live {
        Live::new()
    }
}

fn pause(seconds: f64) {
    std::thread::sleep(std::time::Duration::from_secs_f64(seconds.max(0.0)));
}

fn private(directory: &Path) -> bool {
    authfile::private_dacl(directory)
}

fn nobody() -> Vec<Value> {
    Vec::new()
}

impl Live {
    pub fn new() -> Live {
        let system = std::sync::Arc::new(car_codex::system::Platform::new());
        let (listing, asking) = (std::sync::Arc::clone(&system), std::sync::Arc::clone(&system));
        let started = std::time::Instant::now();
        Live {
            system,
            inventory: Box::new(move || {
                car_codex::pairing::forget_inventory();
                car_codex::pairing::inventory(listing.as_ref()).ok()
            }),
            app_running: Box::new(move || car_codex::pairing::app_running_now(asking.as_ref())),
            clock: Box::new(move || started.elapsed().as_secs_f64()),
        }
    }

    /// The world this live switch hands every function here.
    pub fn world(&self) -> World<'_> {
        World {
            tokens: &crate::credentials::SystemTokens,
            private: &private,
            pause: &pause,
            inventory: self.inventory.as_ref(),
            own: &nobody,
            system: self.system.as_ref(),
            app_running: self.app_running.as_ref(),
            clock: self.clock.as_ref(),
            sleep: &pause,
        }
    }
}
