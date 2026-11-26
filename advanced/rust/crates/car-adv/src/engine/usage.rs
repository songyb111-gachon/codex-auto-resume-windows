//! `engine/usage.py` as the **v0.6.26 final** has it (seat S7.2d): the usage meter, and the wrap-up and the pause that
//! need it (issue #29).
//!
//! * usage_meter (P8): while the Codex app runs, reads usage on its own every `poll_minutes` through one finite session
//!   of its own, keeps the windows (`state/meter`), and marks a warning once for each window's reset. The final added
//!   [`SKIP_WAIT`] (after a look that did not read, the next waits a minute, never every core tick), the backend kept for
//!   the told engine (`_held`, its checks run again each look) and `inuse::saw` after each pairing look.
//! * usage_wrap_up (P8, P2): at the wrap-up percentage, each running conversation switched on is sent one message of the
//!   edition's own (a WRAP_UP record core queues), once for that window; Continue after the reset sends one continuation
//!   once the window resets, where the wrap-up's turn ended well.
//! * usage_pause (P8, P3): from v0.6.16-beta.4 the forced stop ([`super::usagestop`]) holds as the pause held: the
//!   window marked, core's records HOLD, the edition's own continuations not handed to core, let go at the reset.
//!
//! This file also holds what S7.2d's codes share: [`Bound`] (a code's handle on its own `Scoped`), [`World`] (what the
//! reference reads of the outside: catalogs, the local clock, the continuation language, Codex's files, the backend, the
//! capability's own session, the saved accounts) and the small Python readings of values.

use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock, PoisonError};

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_machine::localclock::LocalClock;
use car_policy::plug::{Alternative, Errand, Guards, HookFailed, View};

use super::continued::{answer_key, handed};
use super::credits::Opener;
use super::resetwatch::{Family, Row, num};
use super::wrapwords::{self, Ask, Words, num_eq};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::inuse::{self, Looked};
use crate::codex::session::Channel;
use crate::state::scoped::Scoped;
use crate::statement::Catalogs;

// ------------------------------------------------------------------ what S7.2d's codes share

/// What a code is given to reach its own view of the state, whenever it needs it.
pub type ScopeFn = dyn Fn(&mut dyn FnMut(&Scoped<'_>)) -> bool + Send + Sync;

/// `self._scoped` once bound: the runtime's [`Binding`], or what a probe hands (its own state and switches).
#[derive(Clone)]
pub struct Bound(Arc<ScopeFn>);

impl Bound {
    /// The runtime's binding.
    pub fn of(binding: Binding) -> Bound {
        Bound(Arc::new(move |act: &mut dyn FnMut(&Scoped<'_>)| {
            binding.with(|scoped| act(scoped)).is_some()
        }))
    }

    /// A scope a probe makes.
    pub fn new(scope: Arc<ScopeFn>) -> Bound {
        Bound(scope)
    }

    /// `f(scoped)`, or None where the scope is gone.
    pub fn with<R>(&self, f: impl FnOnce(&Scoped<'_>) -> R) -> Option<R> {
        let mut f = Some(f);
        let mut out = None;
        (self.0)(&mut |scoped| {
            if let Some(f) = f.take() {
                out = Some(f(scoped));
            }
        });
        out
    }

    /// `f(scoped)` for a call that may raise; a scope that is gone raises too.
    pub fn call<R>(
        &self,
        f: impl FnOnce(&Scoped<'_>) -> crate::state::Result<R>,
    ) -> Result<R, Raised> {
        match self.with(f) {
            None => Err(Raised::new("ReferenceError")),
            Some(Ok(found)) => Ok(found),
            Some(Err(error)) => Err(raised(&error)),
        }
    }

    pub fn now(&self) -> f64 {
        self.with(|scoped| scoped.now())
            .unwrap_or_else(crate::state::session::wall_clock)
    }

    /// `scoped.count(code)`, nothing raised.
    pub fn count(&self, code: &str) {
        self.with(|scoped| {
            let _ = scoped.count(&Value::from(code));
        });
    }

    /// `scoped.armed(other) is True`.
    pub fn armed(&self, other: &str) -> bool {
        self.with(|scoped| scoped.armed(&Value::from(other)))
            .unwrap_or(false)
    }
}

/// What a state call's refusal is as a code sees it: the exception's class.
pub fn raised(error: &crate::state::Error) -> Raised {
    Raised::new(error.class())
}

/// `isinstance(value, (int, float)) and not isinstance(value, bool)`.
pub fn is_time(value: &Value) -> bool {
    matches!(value, Value::Int(_) | Value::Float(_))
}

/// A number as f64 (an int, a float or a bool), as arithmetic reads it.
pub fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Bool(flag) => Some(f64::from(u8::from(*flag))),
        _ => car_store::value::number(value),
    }
}

/// `dict.get(name)` of a JSON object, None for anything else.
pub fn field<'a>(value: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// `value.get(name)` where `value` must be a dict: AttributeError for anything else.
pub fn get_of<'a>(value: &'a Value, name: &str) -> Result<&'a Value, Raised> {
    match value {
        Value::Object(_) => Ok(field(value, name)),
        _ => Err(Raised::new("AttributeError")),
    }
}

/// `value == word`, as Python compares any value with a text.
pub fn is_word(value: &Value, word: &str) -> bool {
    matches!(value, Value::Str(text) if text.as_str() == Some(word))
}

/// `row[name]` of a row.
pub fn cell<'a>(row: &'a Row, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    row.get(&car_machine::json::Str::new(name)).unwrap_or(&NULL)
}

/// `row[name] or 0`, as a number.
fn or_zero(value: &Value) -> Result<f64, Raised> {
    if car_machine::pyval::truthy(value) {
        num(value)
    } else {
        Ok(0.0)
    }
}

fn eq(one: &Value, other: &Value) -> bool {
    car_machine::pyval::eq(one, other)
}

fn same_family(one: &Family, other: &Family) -> bool {
    eq(&one.0, &other.0) && eq(&one.1, &other.1)
}

fn family_of(row: &Row) -> Family {
    (cell(row, "bucket").clone(), cell(row, "minutes").clone())
}

/// One turn as the reference's `Turns.latest` gives it: its status, its place and its id.
#[derive(Clone, Debug, PartialEq)]
pub struct TurnSeen {
    pub status: String,
    pub ordinal: Value,
    pub turn_id: Value,
}

/// What the wrap-up and the stop read of Codex's own files: `Turns(home)` (`running(booted=booted_of(paths))`,
/// `latest`, `between`) and core's `LocalSource(home)` with P19's widening while Recover every conversation is on.
pub trait CodexReads: Send + Sync {
    fn running(&self, home: &str, paths: &Paths) -> Result<Vec<String>, Raised>;
    fn latest(&self, home: &str, thread: &str) -> Result<Option<TurnSeen>, Raised>;
    fn between(
        &self,
        home: &str,
        thread: &str,
        after: &Value,
        before: &Value,
    ) -> Result<i64, Raised>;
    /// `LocalSource(home)` made (an `Err` is the constructor's raise).
    fn source(&self, home: &str) -> Result<(), Raised>;
    fn source_latest(
        &self,
        home: &str,
        thread: &str,
        widened: bool,
    ) -> Result<Option<Value>, Raised>;
}

/// The product's reads: car-adv's `codex::turns` and car-codex's `LocalSource`, over car-codex's `PolicyOs`.
pub struct SystemCodex;

fn turns_of(home: &str) -> crate::codex::turns::Turns {
    crate::codex::turns::Turns::new(home, Arc::new(car_codex::system::PolicyOs))
}

fn turns_raise(_: crate::codex::turns::Failure) -> Raised {
    Raised::new("TurnsUnavailable")
}

impl CodexReads for SystemCodex {
    fn running(&self, home: &str, paths: &Paths) -> Result<Vec<String>, Raised> {
        let booted = crate::codex::turns::booted_of(std::path::Path::new(&paths.state_dir));
        turns_of(home).running(&booted).map_err(turns_raise)
    }
    fn latest(&self, home: &str, thread: &str) -> Result<Option<TurnSeen>, Raised> {
        let found = turns_of(home)
            .latest(&Value::from(thread))
            .map_err(turns_raise)?;
        Ok(found.map(|turn| TurnSeen {
            status: turn.status,
            ordinal: car_machine::json::Int::parse(&turn.ordinal.to_string())
                .map_or(Value::Null, Value::Int),
            turn_id: Value::from(turn.turn_id),
        }))
    }
    fn between(
        &self,
        home: &str,
        thread: &str,
        after: &Value,
        before: &Value,
    ) -> Result<i64, Raised> {
        turns_of(home)
            .between(&Value::from(thread), after, before)
            .map_err(turns_raise)
    }
    fn source(&self, home: &str) -> Result<(), Raised> {
        car_codex::source::LocalSource::new(Arc::new(car_codex::system::PolicyOs), home, None)
            .map(|_| ())
            .map_err(|_| Raised::new("SourceError"))
    }
    fn source_latest(
        &self,
        home: &str,
        thread: &str,
        widened: bool,
    ) -> Result<Option<Value>, Raised> {
        let mut source =
            car_codex::source::LocalSource::new(Arc::new(car_codex::system::PolicyOs), home, None)
                .map_err(|_| Raised::new("SourceError"))?;
        if widened {
            source.widened.insert("every_desktop".to_owned());
        }
        source
            .latest(thread)
            .map(|found| found.map(Value::Object))
            .map_err(|_| Raised::new("SourceError"))
    }
}

/// What the meter asks of the backend it looks through: the app's pairing look and the engine's checks again.
pub trait MeterBackend: Looked + Send {
    fn app_identity(&mut self) -> Result<Option<Value>, Raised>;
    fn app_look(&self) -> Option<String>;
    fn compatible(&mut self) -> Result<(), Raised>;
}

impl MeterBackend for car_codex::transport::Backend {
    fn app_identity(&mut self) -> Result<Option<Value>, Raised> {
        car_codex::transport::Backend::app_identity(self).map_err(|_| Raised::new("AdapterError"))
    }
    fn app_look(&self) -> Option<String> {
        self.app_look.map(str::to_owned)
    }
    fn compatible(&mut self) -> Result<(), Raised> {
        car_codex::transport::Backend::compatible(self).map_err(|_| Raised::new("AdapterError"))
    }
}

/// `inuse.backend(paths)`: the backend of the Codex the installation drives, checked.
pub type BackendOf = Arc<dyn Fn(&Paths) -> Result<Box<dyn MeterBackend>, Raised> + Send + Sync>;
/// `continuation.resolve_locale(settings.load(paths.settings_file))`; an `Err` is any raise.
pub type LocaleOf = Arc<dyn Fn(&Paths) -> Result<String, ()> + Send + Sync>;
/// `inuse.home(paths)`; an `Err` is its raise.
pub type HomeOf = Arc<dyn Fn(&Paths) -> Result<String, Raised> + Send + Sync>;
/// `_switched_at(paths)`: when account_auto_switch last put another account in, or a switch under way began.
pub type SwitchedOf = Arc<dyn Fn(&Paths) -> Option<f64> + Send + Sync>;

/// What the reference reads of the outside world. The entry points hand the live one ([`install_world`]); a probe
/// hands its own.
#[derive(Clone)]
pub struct World {
    pub catalogs: Arc<Catalogs>,
    pub clock: Arc<dyn LocalClock + Send + Sync>,
    pub locale: LocaleOf,
    pub codex: Arc<dyn CodexReads>,
    pub home: HomeOf,
    pub backend: BackendOf,
    pub open: Opener,
    pub keys: super::credits::Keys,
    pub switched: SwitchedOf,
    pub ipc: Arc<dyn super::usagestop::Ipc>,
}

static WORLD: OnceLock<World> = OnceLock::new();

/// The entry point's world, given once (S7.3d's `car-adv-bin`/`car-adv-host`).
pub fn install_world(world: World) {
    let _ = WORLD.set(world);
}

/// `inuse.backend(paths)` with the live discovery: the told engine, else the one the watcher would find.
pub fn system_backend(paths: &Paths) -> Result<car_codex::transport::Backend, inuse::BackendError> {
    #[derive(Debug)]
    struct Links;
    impl car_config::Links for Links {
        fn is_symlink(&self, path: &std::path::Path) -> bool {
            car_platform::links::is_symlink(path)
        }
    }
    let os = car_config::Os::here(false, Arc::new(Links));
    let env = |name: &str| std::env::var(name).ok();
    let root = std::env::current_exe()
        .ok()
        .and_then(|exe| {
            exe.parent()
                .map(|folder| folder.to_string_lossy().into_owned())
        })
        .unwrap_or_default();
    let discovery = inuse::Discovery {
        system: Arc::new(car_codex::system::Platform::new()),
        env: &env,
        os: &os,
        product_version: car_config::codex::version(&root, &mut |_| {}),
    };
    inuse::backend(
        Some(&paths.home),
        Some(std::path::Path::new(&paths.settings_file)),
        &discovery,
    )
}

impl World {
    /// The installed world, or the product's defaults: the catalogs beside the executable, the C runtime's local
    /// clock, the process's environment, car-codex's reads, the live backend and sessions. The saved accounts' switch
    /// is read only where the entry point installed a world (S7.2b's host).
    pub fn installed() -> World {
        if let Some(world) = WORLD.get() {
            return world.clone();
        }
        let locales = std::env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(|folder| folder.join("locales")))
            .unwrap_or_else(|| PathBuf::from("locales"));
        World {
            catalogs: Arc::new(Catalogs::new(locales, Box::new(|| "en".to_owned()))),
            clock: Arc::new(car_platform::localclock::Crt),
            locale: Arc::new(|paths: &Paths| {
                let loaded = car_policy::settings::load(
                    &car_codex::system::PolicyOs,
                    std::path::Path::new(&paths.settings_file),
                )
                .map_err(|_| ())?;
                let variable = |name: &str| std::env::var(name).ok();
                let windows = Vec::new;
                let environ = car_policy::classify::continuation::Environ {
                    variable: &variable,
                    windows: &windows,
                };
                car_policy::classify::continuation::resolve_locale(&Value::Object(loaded), &environ)
                    .map(str::to_owned)
                    .map_err(|_| ())
            }),
            codex: Arc::new(SystemCodex),
            home: Arc::new(|paths: &Paths| {
                let env = |name: &str| std::env::var(name).ok();
                #[derive(Debug)]
                struct Links;
                impl car_config::Links for Links {
                    fn is_symlink(&self, path: &std::path::Path) -> bool {
                        car_platform::links::is_symlink(path)
                    }
                }
                let os = car_config::Os::here(false, Arc::new(Links));
                inuse::home(Some(&paths.home), &env, &os).map_err(Raised::new)
            }),
            backend: Arc::new(|paths: &Paths| {
                system_backend(paths)
                    .map(|made| Box::new(made) as Box<dyn MeterBackend>)
                    .map_err(|_| Raised::new("AdapterError"))
            }),
            open: super::credits::system_opener(),
            keys: Arc::new(car_platform::ipc_pipe::uuid4),
            switched: Arc::new(|_: &Paths| None),
            ipc: Arc::new(super::usagestop::SystemIpc),
        }
    }

    /// The catalogs and the clock, as `wrapwords.render` reads them.
    pub fn words(&self) -> Words<'_> {
        Words {
            catalogs: &self.catalogs,
            clock: self.clock.as_ref(),
        }
    }

    /// `statement.CATALOGS.text(key, locale)`; a catalog that is not UTF-8 raises.
    pub fn text(&self, key: &str, locale: Option<&str>) -> Result<Option<String>, Raised> {
        self.catalogs
            .text(key, locale, &[])
            .map_err(|_| Raised::new(crate::statement::Undecodable::CLASS))
    }
}

// ------------------------------------------------------------------ the module's words and numbers

pub const METER: &str = "usage_meter";
pub const WRAP_UP: &str = "usage_wrap_up";
pub const PAUSE: &str = "usage_pause";
pub const ANALYTICS: &str = "usage_analytics";
pub const EVERY_CONVERSATION: &str = "every_conversation";
pub const FIVE_HOUR: i64 = 300;
pub const WEEKLY: i64 = 10080;
pub const WINDOWS: [i64; 2] = [FIVE_HOUR, WEEKLY];
pub const POLL_CHOICES: [i64; 7] = [5, 10, 15, 20, 30, 45, 60];
pub const DEFAULT_POLL: i64 = 15;
pub const PERCENTS: [i64; 14] = [50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 96, 97, 98, 99];
pub const PERCENT_RANGE: (i64, i64) = (1, 100);
pub const POLL_RANGE: (i64, i64) = (5, 60);
pub const DEFAULT_WARN: i64 = 85;
pub const DEFAULT_WRAP: i64 = 90;
pub const DEFAULT_PAUSE: i64 = 97;
pub const DEFAULT_STOP_WORDS: i64 = 95;
pub const STOP_WORDS_OPTIONS: [(i64, &str); 2] = [
    (FIVE_HOUR, "stop_words_five_hour"),
    (WEEKLY, "stop_words_weekly"),
];
pub const AFTER_RESET_KEY: &str = "continue.after_reset";
pub const WINDOW_OPTIONS: [(i64, &str); 2] =
    [(FIVE_HOUR, "window_five_hour"), (WEEKLY, "window_weekly")];
pub const CUSTOM_WORDINGS: [(i64, &str); 2] = [
    (FIVE_HOUR, "wrap_custom_five_hour"),
    (WEEKLY, "wrap_custom_weekly"),
];
pub const STAGE_OPTIONS: [(&str, [(i64, &str); 2]); 3] = [
    (
        METER,
        [(FIVE_HOUR, "warn_five_hour"), (WEEKLY, "warn_weekly")],
    ),
    (
        WRAP_UP,
        [(FIVE_HOUR, "wrap_five_hour"), (WEEKLY, "wrap_weekly")],
    ),
    (
        PAUSE,
        [(FIVE_HOUR, "pause_five_hour"), (WEEKLY, "pause_weekly")],
    ),
];
/// A reading older than this is not acted on by the wrap-up: two of the longest spacings.
pub const FRESH: f64 = 2.0 * 60.0 * 60.0;
pub const CLOSE_AFTER: f64 = 60.0;
pub const NOTICE_FOR: f64 = 900.0;
pub const LOOK_EVERY: f64 = 60.0;
pub const CREDIT_RESET: [&str; 2] = ["reset", "already_redeemed"];
pub const ON: i64 = wrapwords::ON;
pub const AUTO_SWITCH: &str = "account_auto_switch";
pub const ACCOUNT_SWITCH: &str = "account_switch";
pub const CHANGE_STAMPS: [(&str, &str, i64); 2] = [
    (AUTO_SWITCH, "auto_switched_at", 0),
    (ACCOUNT_SWITCH, "account_changed_at", 1),
];
pub const SKIP_CLOSED: &str = "app_closed";
pub const SKIP_UNMATCHED: &str = "unmatched";
pub const SKIP_NO_ENGINE: &str = "no_engine";
pub const SKIPS: [&str; 3] = [SKIP_CLOSED, SKIP_UNMATCHED, SKIP_NO_ENGINE];
/// v0.6.26 final: after a look that did not read, the next look waits this long.
pub const SKIP_WAIT: f64 = 60.0;

fn stage_key(capability: &str, minutes: &Value) -> Option<&'static str> {
    STAGE_OPTIONS
        .iter()
        .find(|(name, _)| *name == capability)
        .and_then(|(_, keys)| wrapwords::lookup(keys, minutes))
}

fn option<'a>(options: &'a Map, key: &str) -> Option<&'a Value> {
    options.get(key)
}

fn option_or(options: &Map, key: &str, default: i64) -> Value {
    option(options, key)
        .cloned()
        .unwrap_or_else(|| Value::from(default))
}

/// `percent(options, capability, minutes)`: the percentage a capability's stage acts at for a window, or None.
pub fn percent(options: &Map, capability: &str, minutes: &Value) -> Option<Value> {
    let value = option(options, stage_key(capability, minutes)?)?;
    wrapwords::is_int(value).then(|| value.clone())
}

/// `reached(row, threshold, now)`: at or over `threshold` with its reset still ahead (and known).
pub fn reached(row: &Row, threshold: Option<&Value>, now: f64) -> Result<bool, Raised> {
    let Some(threshold) = threshold else {
        return Ok(false);
    };
    if !car_machine::pyval::less_or_equal(threshold, cell(row, "used_percent"))
        .map_err(|_| Raised::new("TypeError"))?
    {
        return Ok(false);
    }
    let reset = cell(row, "reset_at");
    Ok(wrapwords::is_int(reset) && now < num(reset)? + CLOSE_AFTER)
}

/// `minutes in WINDOWS`.
pub fn in_windows(minutes: &Value) -> bool {
    WINDOWS.iter().any(|window| num_eq(minutes, *window))
}

/// `windows(rows)`: the rows of the five-hour and the weekly windows, any bucket's.
pub fn windows(rows: &[(Family, Row)]) -> Vec<Row> {
    rows.iter()
        .filter(|(_, row)| in_windows(cell(row, "minutes")))
        .map(|(_, row)| row.clone())
        .collect()
}

/// The meter's rows (`scoped.meter.rows()`).
pub fn meter_rows(scoped: &Scoped<'_>) -> crate::state::Result<Vec<(Family, Row)>> {
    scoped.state.meter()
}

/// `credit_resets(scoped, rows)`: `{(bucket, minutes): when the newest reset credit of that window was answered}`;
/// empty where none can be read.
pub fn credit_resets(bound: &Bound, rows: &[Row]) -> Vec<(Family, Value)> {
    if rows.is_empty() {
        return Vec::new();
    }
    let Ok(spends) = bound.call(|scoped| scoped.state.credit_spends(&Value::Null)) else {
        return Vec::new();
    };
    let mut found: Vec<(Family, Value)> = Vec::new();
    for spend in &spends {
        let at = cell(spend, "finished_at");
        let outcome = cell(spend, "outcome");
        if !CREDIT_RESET.iter().any(|word| is_word(outcome, word))
            || !matches!(at, Value::Int(_) | Value::Float(_) | Value::Bool(_))
        {
            continue;
        }
        let family = family_of_spend(spend);
        let held = found.iter().position(|(key, _)| same_family(key, &family));
        let before = held.map_or(Value::from(0), |index| found[index].1.clone());
        if car_machine::pyval::greater(at, &before).unwrap_or(false) {
            match held {
                Some(index) => found[index].1 = at.clone(),
                None => found.push((family, at.clone())),
            }
        }
    }
    found
}

fn family_of_spend(spend: &Row) -> Family {
    (
        cell(spend, "bucket").clone(),
        cell(spend, "minutes").clone(),
    )
}

/// `changed_at(paths, stamped_of, profiles=True)`: when the Codex account in use last changed, as far as this edition
/// can tell, or None. What cannot be read counts as no change.
pub fn changed_at(
    world: &World,
    paths: &Paths,
    bound: Option<&Bound>,
    profiles: bool,
) -> Option<f64> {
    let mut found: Vec<f64> = Vec::new();
    if profiles && let Some(at) = (world.switched)(paths) {
        found.push(at);
    }
    if let Some(bound) = bound {
        for (capability, key, before) in CHANGE_STAMPS {
            let Ok(at) =
                bound.call(|scoped| scoped.stamped_of(&Value::from(capability), &Value::from(key)))
            else {
                continue;
            };
            if is_time(&at) {
                found.push(number(&at).unwrap_or(0.0) - before as f64);
            }
        }
    }
    found.into_iter().reduce(f64::max)
}

/// `before_change(row, changed)`: the meter read `row` at or before the change of account: it is the old account's.
pub fn before_change(row: &Row, changed: Option<f64>) -> Result<bool, Raised> {
    match changed {
        None => Ok(false),
        Some(changed) => Ok(changed >= or_zero(cell(row, "read_at"))?),
    }
}

/// `of_account(rows, paths, stamped_of)`: the five-hour and weekly windows read after the account in use last changed.
pub fn of_account(
    world: &World,
    rows: &[(Family, Row)],
    paths: &Paths,
    bound: Option<&Bound>,
) -> Result<Vec<Row>, Raised> {
    let changed = changed_at(world, paths, bound, true);
    let mut kept = Vec::new();
    for row in windows(rows) {
        if !before_change(&row, changed)? {
            kept.push(row);
        }
    }
    Ok(kept)
}

/// `stale(row, resets)`: read before a reset credit of that very window was answered.
pub fn stale(row: &Row, resets: &[(Family, Value)]) -> Result<bool, Raised> {
    let family = family_of(row);
    let Some((_, at)) = resets.iter().find(|(key, _)| same_family(key, &family)) else {
        return Ok(false);
    };
    Ok(num(at)? >= or_zero(cell(row, "read_at"))?)
}

/// `_reset_since(rows, minutes, created_at, now)`: whether the window of `minutes` has reset since `created_at`.
pub fn reset_since(
    rows: &[(Family, Row)],
    minutes: &Value,
    created_at: &Value,
    now: f64,
) -> Result<bool, Raised> {
    let found: Vec<Row> = windows(rows)
        .into_iter()
        .filter(|row| eq(cell(row, "minutes"), minutes))
        .collect();
    let length = num(minutes)? * 60.0;
    let Some(first) = found.first() else {
        return Ok(now - num(created_at)? >= length);
    };
    let reset = cell(first, "reset_at");
    if !wrapwords::is_int(reset) {
        return Ok(false);
    }
    let reset = num(reset)?;
    Ok(now >= reset + CLOSE_AFTER || reset - length > num(created_at)?)
}

/// `acting(options)`: the windows a person lets a capability act on, from its own options - both by default.
pub fn acting(options: &Map) -> Vec<i64> {
    WINDOW_OPTIONS
        .iter()
        .filter(|(_, key)| option(options, key).is_none_or(|value| num_eq(value, ON)))
        .map(|(minutes, _)| *minutes)
        .collect()
}

/// `_acting(scoped)`: every window where its choices cannot be read.
pub fn acting_of(bound: &Bound) -> Vec<i64> {
    match bound.call(|scoped| scoped.options()) {
        Ok(options) => acting(&options),
        Err(_) => WINDOWS.to_vec(),
    }
}

fn acts_on(on: &[i64], minutes: &Value) -> bool {
    on.iter().any(|window| num_eq(minutes, *window))
}

/// `touched(key)`: the windows whose order an option bears on.
pub fn touched(key: &str) -> Vec<i64> {
    WINDOWS
        .iter()
        .copied()
        .filter(|minutes| {
            let by = |table: &[(i64, &str)]| {
                table.iter().any(|(at, name)| at == minutes && *name == key)
            };
            by(&STOP_WORDS_OPTIONS) || STAGE_OPTIONS.iter().any(|(_, stages)| by(stages))
        })
        .collect()
}

fn of<'a>(values: &'a Map, capability: &str, key: &str) -> Option<&'a Value> {
    match values.get(capability) {
        Some(Value::Object(options)) => options.get(key),
        _ => None,
    }
}

/// `order_problem(values, windows_=WINDOWS)`: (refusal word or None, warning word or None) - item (j): the warning at
/// or below the wrap-up, the wrap-up below the words' stop, else "order"; a forced stop below the words' stop only warns.
pub fn order_problem(
    values: &Map,
    windows_: &[i64],
) -> Result<(Option<&'static str>, Option<&'static str>), Raised> {
    let mut warning = None;
    let type_error = |_| Raised::new("TypeError");
    for minutes in windows_ {
        let at = Value::from(*minutes);
        let key = |capability: &str| stage_key(capability, &at).unwrap_or_default();
        let words_key = wrapwords::lookup(&STOP_WORDS_OPTIONS, &at).unwrap_or_default();
        let warn = of(values, METER, key(METER))
            .cloned()
            .unwrap_or_else(|| Value::from(DEFAULT_WARN));
        let wrap = of(values, WRAP_UP, key(WRAP_UP))
            .cloned()
            .unwrap_or_else(|| Value::from(DEFAULT_WRAP));
        let words = of(values, WRAP_UP, words_key)
            .cloned()
            .unwrap_or_else(|| Value::from(DEFAULT_STOP_WORDS));
        let forced = of(values, PAUSE, key(PAUSE))
            .cloned()
            .unwrap_or_else(|| Value::from(DEFAULT_PAUSE));
        let ordered = car_machine::pyval::less_or_equal(&warn, &wrap).map_err(type_error)?
            && car_machine::pyval::less(&wrap, &words).map_err(type_error)?;
        if !ordered {
            return Ok((Some("order"), None));
        }
        if car_machine::pyval::less(&forced, &words).map_err(type_error)? {
            warning = Some("stop_before_words");
        }
    }
    Ok((None, warning))
}

/// `previews(state, now)`: what the wrap-up would send for each window now, exactly - `{minutes: words or None}`; empty
/// where the state cannot be read.
pub fn previews(
    world: &World,
    state: &crate::state::AdvancedState,
    now: f64,
) -> Result<Vec<(i64, Option<String>)>, Raised> {
    let wrap = Value::from(WRAP_UP);
    let read = (|| -> crate::state::Result<(Map, Map, super::resetwatch::Rows)> {
        Ok((
            state.options(&wrap)?,
            state.wordings(&wrap)?,
            state.meter()?,
        ))
    })();
    let Ok((options, custom, meter)) = read else {
        return Ok(Vec::new());
    };
    let mut rows: Vec<(Value, Row)> = Vec::new();
    for row in windows(&meter) {
        let minutes = cell(&row, "minutes").clone();
        if !rows.iter().any(|(held, _)| eq(held, &minutes)) {
            rows.push((minutes, row));
        }
    }
    let locale = (world.locale)(&state.paths).ok();
    let mut found = Vec::new();
    for minutes in WINDOWS {
        let at = Value::from(minutes);
        let row = rows
            .iter()
            .find(|(held, _)| eq(held, &at))
            .map(|(_, row)| row);
        let live = match row {
            Some(row) => {
                let reset = cell(row, "reset_at");
                wrapwords::is_int(reset) && num(reset)? > now
            }
            None => false,
        };
        let used = match (live, row) {
            (true, Some(row)) => cell(row, "used_percent").clone(),
            _ => option_or(
                &options,
                stage_key(WRAP_UP, &at).unwrap_or_default(),
                DEFAULT_WRAP,
            ),
        };
        let reset_at = match (live, row) {
            (true, Some(row)) => cell(row, "reset_at").clone(),
            _ => Value::from(now.trunc() as i64 + minutes * 60),
        };
        let style = option_or(&options, "wrap_style", wrapwords::DEFAULT_STYLE);
        let stop_at = option_or(
            &options,
            wrapwords::lookup(&STOP_WORDS_OPTIONS, &at).unwrap_or_default(),
            DEFAULT_STOP_WORDS,
        );
        let include_reset = num_eq(&option_or(&options, "wrap_reset_time", ON), ON);
        let custom_words = custom
            .get(wrapwords::lookup(&CUSTOM_WORDINGS, &at).unwrap_or_default())
            .cloned()
            .unwrap_or(Value::Null);
        let words = wrapwords::render(
            &world.words(),
            &Ask {
                style: &style,
                minutes: &at,
                used: &used,
                stop_at: &stop_at,
                locale: locale.as_deref(),
                reset_at: &reset_at,
                include_reset,
                custom: &custom_words,
            },
        )
        .map_err(Raised::new)?;
        found.push((minutes, words));
    }
    Ok(found)
}

// ------------------------------------------------------------------ the meter

/// What the meter keeps between looks.
pub struct MeterInner {
    pub paths: Paths,
    pub world: World,
    bound: Option<Bound>,
    pub looked: Option<f64>,
    pub why: Option<&'static str>,
    pub said: Option<&'static str>,
    pub skipped_at: Option<f64>,
    held: Option<((String, String), Box<dyn MeterBackend>)>,
}

/// `UsageMeter(paths)`: usage_meter's code, its P8 errand.
pub struct UsageMeter {
    inner: Arc<Mutex<MeterInner>>,
}

struct MeterErrand {
    inner: Arc<Mutex<MeterInner>>,
}

impl Errand for MeterErrand {
    fn run(&self, _view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let mut inner = self.inner.lock().unwrap_or_else(PoisonError::into_inner);
        inner.look().map_err(|_| HookFailed)
    }
}

/// What the meter keeps, as a probe reads it.
pub struct Kept {
    pub looked: Option<f64>,
    pub why: Option<&'static str>,
    pub said: Option<&'static str>,
    pub skipped_at: Option<f64>,
    pub held: Option<(String, String)>,
}

impl UsageMeter {
    pub fn new(paths: Paths, world: World) -> UsageMeter {
        UsageMeter {
            inner: Arc::new(Mutex::new(MeterInner {
                paths,
                world,
                bound: None,
                looked: None,
                why: None,
                said: None,
                skipped_at: None,
                held: None,
            })),
        }
    }

    pub fn bind_to(&mut self, bound: Bound) {
        self.lock().bound = Some(bound);
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, MeterInner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The errand's look, as a probe runs it.
    pub fn look(&self) -> Result<Value, Raised> {
        self.lock().look()
    }

    pub fn kept(&self) -> Kept {
        let inner = self.lock();
        Kept {
            looked: inner.looked,
            why: inner.why,
            said: inner.said,
            skipped_at: inner.skipped_at,
            held: inner.held.as_ref().map(|(told, _)| told.clone()),
        }
    }
}

impl MeterInner {
    fn count(&self, code: &str) {
        if let Some(bound) = &self.bound {
            bound.count(code);
        }
    }

    fn changed_since(&self, last: f64) -> bool {
        changed_at(&self.world, &self.paths, self.bound.as_ref(), false)
            .is_some_and(|changed| changed > last)
    }

    /// `_running()` with `_backend()`: whether the Codex app runs now - the backend kept for the told engine (its
    /// checks run again), else made afresh; the pairing look's elsewhere kept (`inuse.saw`); where it does not run,
    /// `why` says which of SKIPS stood in the way.
    fn running(&mut self) -> bool {
        let told = inuse::told(Some(&self.paths.home));
        let reuse = matches!((&told, &self.held), (Some(told), Some((held, _))) if held == told);
        let mut fresh: Option<Box<dyn MeterBackend>> = None;
        if reuse {
            let checked = self.held.as_mut().map(|(_, backend)| backend.compatible());
            if !matches!(checked, Some(Ok(()))) {
                self.held = None;
                self.why = Some(SKIP_NO_ENGINE);
                return false;
            }
        } else {
            match (self.world.backend)(&self.paths) {
                Err(_) => {
                    self.held = None;
                    self.why = Some(SKIP_NO_ENGINE);
                    return false;
                }
                Ok(made) => match told {
                    Some(told) => self.held = Some((told, made)),
                    None => {
                        self.held = None;
                        fresh = Some(made);
                    }
                },
            }
        }
        let backend: &mut dyn MeterBackend = match fresh.as_mut() {
            Some(made) => made.as_mut(),
            None => match self.held.as_mut() {
                Some((_, held)) => held.as_mut(),
                None => return false,
            },
        };
        let paired = backend.app_identity().unwrap_or(None);
        let looked: &dyn Looked = &*backend;
        inuse::saw(Some(&self.paths.home), looked);
        let look = backend.app_look();
        if paired.is_none() {
            self.why = Some(if look.as_deref() == Some("unmatched") {
                SKIP_UNMATCHED
            } else {
                SKIP_CLOSED
            });
            return false;
        }
        true
    }

    /// `_skipped()`: a look that did not read, journalled once for each change of why.
    fn skipped(&mut self) {
        let why = self.why.take();
        if let Some(why) = why
            && self.said != Some(why)
        {
            self.said = Some(why);
            self.count(why);
        }
    }

    /// `_read()`: one usage read through a finite session of the meter's own - the windows core keeps, or a raise.
    fn read(&self) -> Result<Value, Raised> {
        let mut session: Box<dyn Channel> =
            (self.world.open)(&self.paths, METER).map_err(|error| Raised::new(error.class()))?;
        session
            .enter()
            .map_err(|error| Raised::new(error.class()))?;
        let reply = session.call(crate::codex::credits::READ, Some(Value::Object(Map::new())));
        session.exit();
        let reply = reply.map_err(|error| Raised::new(error.class()))?;
        let parsed = crate::codex::credits::parse(&reply).map_err(|_| Raised::new("TypeError"))?;
        Ok(field(&parsed, "windows").clone())
    }

    /// `look()`: the errand.
    fn look(&mut self) -> Result<Value, Raised> {
        let Some(bound) = self.bound.clone() else {
            return Err(Raised::new("AttributeError"));
        };
        if !bound
            .with(|scoped| scoped.handle().is_on())
            .unwrap_or(false)
        {
            return Ok(Value::Null);
        }
        let now = bound.now();
        if !self.running() {
            self.skipped_at = Some(now);
            self.skipped();
            return Ok(Value::Null);
        }
        self.skipped_at = None;
        self.said = None;
        self.looked = Some(now);
        let found = self.read().unwrap_or(Value::Null);
        if matches!(found, Value::Null) {
            self.count("unreadable");
            return Ok(Value::Null);
        }
        bound.call(|scoped| scoped.handle().meter_save(&found))?;
        self.count("read");
        bound.with(|scoped| {
            if scoped.armed(&Value::from(ANALYTICS)) {
                let _ = scoped
                    .handle()
                    .analytics_sample(&found, &Value::from(scoped.now()));
            }
        });
        let options = bound.call(|scoped| scoped.options())?;
        let on = acting(&options);
        let rows = bound.call(meter_rows)?;
        for row in of_account(&self.world, &rows, &self.paths, Some(&bound))? {
            let minutes = cell(&row, "minutes");
            if !acts_on(&on, minutes) {
                continue;
            }
            let threshold = percent(&options, METER, minutes);
            if reached(&row, threshold.as_ref(), now)?
                && !eq(cell(&row, "warned_reset_at"), cell(&row, "reset_at"))
            {
                let marked = bound.call(|scoped| {
                    scoped.handle().meter_writer()?;
                    scoped.state.mark_meter(
                        cell(&row, "bucket"),
                        minutes,
                        cell(&row, "reset_at"),
                        &Value::Null,
                        &Value::Bool(false),
                        &Value::Null,
                    )
                })?;
                if marked {
                    self.count("warned");
                }
            }
        }
        Ok(Value::Null)
    }
}

impl Code for UsageMeter {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.lock().bound = Some(Bound::of(binding));
        Some(Ok(()))
    }

    /// P8: an errand where a look is due - its spacing passed since the last read or look (or the account changed
    /// since), and never within SKIP_WAIT of a look that did not read.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let inner = self.lock();
        let Some(bound) = inner.bound.clone() else {
            return Ok(Said::Defer);
        };
        let read = bound.call(|scoped| {
            let options = scoped.options()?;
            let rows = meter_rows(scoped)?;
            Ok((options, scoped.now(), rows))
        });
        let Ok((options, now, rows)) = read else {
            return Ok(Said::Defer);
        };
        // `options.get(POLL_MINUTES, DEFAULT_POLL) * 60` inside the reference's try: None or a dict raise there.
        let spacing = option_or(&options, "poll_minutes", DEFAULT_POLL);
        if matches!(spacing, Value::Null | Value::Object(_)) {
            return Ok(Said::Defer);
        }
        if let Some(skipped) = inner.skipped_at
            && (0.0..SKIP_WAIT).contains(&(now - skipped))
        {
            return Ok(Said::Defer);
        }
        let looked = inner.looked.filter(|looked| *looked != 0.0);
        let mut read: Vec<Value> = rows
            .iter()
            .map(|(_, row)| cell(row, "read_at").clone())
            .collect();
        let last = if !read.is_empty() || looked.is_some() {
            read.push(looked.map_or(Value::from(0), Value::from));
            let refs: Vec<&Value> = read.iter().collect();
            Some(num(
                car_machine::pyval::max(&refs).map_err(|_| Raised::new("TypeError"))?
            )?)
        } else {
            None
        };
        if let Some(last) = last
            && now - last >= 0.0
            && now - last < num(&spacing)? * 60.0
            && !inner.changed_since(last)
        {
            return Ok(Said::Defer);
        }
        drop(inner);
        Ok(Said::Errand(Box::new(MeterErrand {
            inner: self.inner.clone(),
        })))
    }
}

// ------------------------------------------------------------------ the wrap-up

/// Core's reader of the Codex home, as the wrap-up and the stop make it (`_source()`).
pub struct Source {
    pub home: String,
    pub widened: bool,
}

/// `_codex_home()`: the home a test gave, else `inuse.home(paths)`.
pub fn codex_home(world: &World, paths: &Paths, home: Option<&str>) -> Result<String, Raised> {
    match home {
        Some(home) => Ok(home.to_owned()),
        None => (world.home)(paths),
    }
}

/// `_source()`: core's `LocalSource(home)`, P19's widening taken up while Recover every conversation is on.
pub fn source_of(
    world: &World,
    paths: &Paths,
    home: Option<&str>,
    bound: Option<&Bound>,
) -> Result<Source, Raised> {
    let home = codex_home(world, paths, home)?;
    world.codex.source(&home)?;
    let widened = bound.is_some_and(|bound| bound.armed(EVERY_CONVERSATION));
    Ok(Source { home, widened })
}

impl Source {
    pub fn latest(&self, world: &World, thread: &str) -> Result<Option<Value>, Raised> {
        world.codex.source_latest(&self.home, thread, self.widened)
    }
}

/// `view.thread_enabled(thread) is not True or source.latest(thread) is None`, then `turns.latest(thread)`: None where
/// the conversation is off or not one core would take up, else its latest turn; an `Err` where a read raised.
pub fn enabled_latest(
    world: &World,
    view: &dyn View,
    source: &Source,
    thread: &str,
) -> Result<Option<Option<TurnSeen>>, Raised> {
    let enabled = view
        .thread_enabled(thread)
        .map_err(|failed| Raised::new(failed.0))?;
    if !enabled || source.latest(world, thread)?.is_none() {
        return Ok(None);
    }
    Ok(Some(world.codex.latest(&source.home, thread)?))
}

fn thread_text(value: &Value) -> String {
    car_machine::pytext::py_str(value)
}

/// `UsageWrapUp(paths, home=None)`: usage_wrap_up's code - at P8 the conversations to ask, at P2 the messages waiting.
pub struct UsageWrapUp {
    pub paths: Paths,
    pub world: World,
    pub home: Option<String>,
    bound: Option<Bound>,
    pub looked: Option<f64>,
    pub turn: usize,
}

impl UsageWrapUp {
    pub fn new(paths: Paths, world: World) -> UsageWrapUp {
        UsageWrapUp {
            paths,
            world,
            home: None,
            bound: None,
            looked: None,
            turn: 0,
        }
    }

    pub fn bind_to(&mut self, bound: Bound) {
        self.bound = Some(bound);
    }

    fn count(&self, code: &str) {
        if let Some(bound) = &self.bound {
            bound.count(code);
        }
    }

    fn source(&self) -> Result<Source, Raised> {
        source_of(
            &self.world,
            &self.paths,
            self.home.as_deref(),
            self.bound.as_ref(),
        )
    }

    /// `_look(view, now)`: the conversations to send a wrap-up to, each once for its window.
    fn look_due(&self, bound: &Bound, view: &dyn View, now: f64) -> Result<(), Raised> {
        if !bound
            .with(|scoped| scoped.handle().is_on())
            .unwrap_or(false)
        {
            return Ok(());
        }
        let options = bound.call(|scoped| scoped.options())?;
        let on = acting_of(bound);
        let rows = bound.call(meter_rows)?;
        let mut due = Vec::new();
        for row in of_account(&self.world, &rows, &self.paths, Some(bound))? {
            let minutes = cell(&row, "minutes");
            if !acts_on(&on, minutes) || now - num(cell(&row, "read_at"))? > FRESH {
                continue;
            }
            if reached(&row, percent(&options, WRAP_UP, minutes).as_ref(), now)? {
                due.push(row);
            }
        }
        if due.is_empty() {
            return Ok(());
        }
        let locale = (self.world.locale)(&self.paths).ok();
        let custom = bound.call(|scoped| scoped.wordings()).unwrap_or_default();
        let mut worded = Vec::new();
        for row in due {
            let minutes = cell(&row, "minutes").clone();
            let style = option_or(&options, "wrap_style", wrapwords::DEFAULT_STYLE);
            let stop_key = wrapwords::lookup(&STOP_WORDS_OPTIONS, &minutes).unwrap_or_default();
            let stop_at = option_or(&options, stop_key, DEFAULT_STOP_WORDS);
            let include_reset = num_eq(&option_or(&options, "wrap_reset_time", ON), ON);
            let custom_words = wrapwords::lookup(&CUSTOM_WORDINGS, &minutes)
                .and_then(|key| custom.get(key).cloned())
                .unwrap_or(Value::Null);
            let words = wrapwords::render(
                &self.world.words(),
                &Ask {
                    style: &style,
                    minutes: &minutes,
                    used: cell(&row, "used_percent"),
                    stop_at: &stop_at,
                    locale: locale.as_deref(),
                    reset_at: cell(&row, "reset_at"),
                    include_reset,
                    custom: &custom_words,
                },
            )
            .map_err(Raised::new)?;
            if let Some(words) = words {
                worded.push((row, words));
            }
        }
        if worded.is_empty() {
            return Ok(());
        }
        let home = codex_home(&self.world, &self.paths, self.home.as_deref())?;
        let source = self.source()?;
        for thread in self.world.codex.running(&home, &self.paths)? {
            let Ok(Some(Some(turn))) = enabled_latest(&self.world, view, &source, &thread) else {
                continue;
            };
            if turn.status != "inProgress" {
                continue;
            }
            let thread_value = Value::from(thread.as_str());
            for (row, words) in &worded {
                let key = Value::from(answer_key(&[
                    Value::from(WRAP_UP),
                    thread_value.clone(),
                    cell(row, "bucket").clone(),
                    cell(row, "minutes").clone(),
                    cell(row, "reset_at").clone(),
                ]));
                if bound
                    .call(|scoped| scoped.handle().continuation(&key))?
                    .is_some()
                {
                    continue;
                }
                let added = bound.call(|scoped| {
                    scoped.handle().continuations_writing()?;
                    scoped.state.add_continuation(
                        &key,
                        &scoped.capability,
                        &Value::from("wrap_up"),
                        &thread_value,
                        &Value::from(words.as_str()),
                        &turn.ordinal,
                        cell(row, "minutes"),
                        &Value::Null,
                    )
                })?;
                if added {
                    self.count("found");
                }
            }
        }
        Ok(())
    }

    /// `_after_reset(view, now)`: Continue after the reset - one continuation once the wrap-up's window resets, where
    /// the wrap-up's turn ended well; noted and left where newer work came or the turn did not complete.
    fn after_reset(&self, bound: &Bound, view: &dyn View, now: f64) -> Result<(), Raised> {
        if !bound
            .with(|scoped| scoped.handle().is_on())
            .unwrap_or(false)
        {
            return Ok(());
        }
        let options = bound.call(|scoped| scoped.options())?;
        if !num_eq(&option_or(&options, "wrap_after_reset", ON), ON) {
            return Ok(());
        }
        let mine = bound.call(|scoped| {
            scoped
                .state
                .continuations(&scoped.capability, &Value::Null, &Value::Null)
        })?;
        let sent: Vec<Row> = mine
            .into_iter()
            .filter(|row| {
                is_word(cell(row, "kind"), "wrap_up")
                    && (is_word(cell(row, "reason"), "delivered")
                        || is_word(cell(row, "reason"), "sent"))
                    && in_windows(cell(row, "chain"))
            })
            .collect();
        if sent.is_empty() {
            return Ok(());
        }
        let rows = bound.call(meter_rows)?;
        let home = codex_home(&self.world, &self.paths, self.home.as_deref())?;
        let source = self.source()?;
        let mut words: Option<Option<String>> = None;
        for wrap in sent {
            let thread_value = cell(&wrap, "thread_id").clone();
            let created = cell(&wrap, "created_at");
            let created_int = match created {
                Value::Float(x) if x.is_finite() => Value::from(x.trunc() as i64),
                Value::Int(_) => created.clone(),
                Value::Bool(flag) => Value::from(i64::from(*flag)),
                _ => return Err(Raised::new("TypeError")),
            };
            let key = Value::from(answer_key(&[
                Value::from("after_reset"),
                thread_value.clone(),
                Value::from("wrap"),
                cell(&wrap, "chain").clone(),
                created_int,
            ]));
            if bound
                .call(|scoped| scoped.handle().continuation(&key))?
                .is_some()
                || !reset_since(&rows, cell(&wrap, "chain"), created, now)?
            {
                continue;
            }
            let thread = thread_text(&thread_value);
            let Ok(Some(Some(latest))) = enabled_latest(&self.world, view, &source, &thread) else {
                continue;
            };
            if latest.status == "inProgress" {
                continue;
            }
            let Some(newer) = after_wrap_up(
                &self.world,
                &home,
                &thread,
                cell(&wrap, "ordinal"),
                &latest.ordinal,
            ) else {
                continue;
            };
            let note = |reason: &str| {
                bound.call(|scoped| {
                    scoped.handle().continuations_writing()?;
                    scoped.state.note_continuation(
                        &key,
                        &scoped.capability,
                        &Value::from("after_reset"),
                        &thread_value,
                        &Value::from(reason),
                        &Value::Null,
                        &Value::from(0),
                        &Value::Null,
                    )
                })
            };
            if newer {
                note("superseded")?;
                continue;
            }
            if latest.status != "completed" {
                note("handed_over")?;
                continue;
            }
            if words.is_none() {
                words = Some(match (self.world.locale)(&self.paths) {
                    Ok(locale) => match self.world.text(AFTER_RESET_KEY, Some(&locale)) {
                        Ok(found) => found,
                        Err(_) => self.world.text(AFTER_RESET_KEY, None)?,
                    },
                    Err(()) => self.world.text(AFTER_RESET_KEY, None)?,
                });
            }
            let said = words.clone().flatten().map_or(Value::Null, Value::from);
            let added = bound.call(|scoped| {
                scoped.handle().continuations_writing()?;
                scoped.state.add_continuation(
                    &key,
                    &scoped.capability,
                    &Value::from("after_reset"),
                    &thread_value,
                    &said,
                    &latest.ordinal,
                    cell(&wrap, "chain"),
                    &Value::Null,
                )
            })?;
            if added {
                self.count("continued");
            }
        }
        Ok(())
    }

    /// `_still_due(waiting, spared)`: the waiting wrap-ups whose turn is still the latest and still running; every
    /// other one ends superseded (its conversation's, unless a continuation after the reset waits there).
    fn still_due(&self, bound: &Bound, waiting: Vec<Row>, spared: &[Value]) -> Vec<Row> {
        let Ok(source) = self.source() else {
            return waiting;
        };
        let mut kept = Vec::new();
        let mut ended: Vec<Value> = Vec::new();
        for row in waiting {
            let thread = cell(&row, "thread_id").clone();
            let latest = match source.latest(&self.world, &thread_text(&thread)) {
                Ok(latest) => latest,
                Err(_) => {
                    kept.push(row);
                    continue;
                }
            };
            let running = latest.as_ref().is_some_and(|latest| {
                eq(field(latest, "ordinal"), cell(&row, "ordinal"))
                    && is_word(field(latest, "status"), "inProgress")
            });
            if running {
                kept.push(row);
            } else if !ended.iter().any(|held| eq(held, &thread)) {
                ended.push(thread.clone());
                if spared.iter().any(|held| eq(held, &thread)) {
                    continue;
                }
                let _ = bound.call(|scoped| {
                    scoped.handle().continuations_writing()?;
                    scoped.state.end_continuations(
                        &Value::from("superseded"),
                        &scoped.capability,
                        &thread,
                        &Value::Null,
                    )
                });
            }
        }
        kept.into_iter()
            .filter(|row| !ended.iter().any(|held| eq(held, cell(row, "thread_id"))))
            .collect()
    }
}

/// `_after_wrap_up(turns, thread, made_for, latest)`: whether a turn came after the wrap-up's own; None where that
/// cannot be read.
pub fn after_wrap_up(
    world: &World,
    home: &str,
    thread: &str,
    made_for: &Value,
    latest: &Value,
) -> Option<bool> {
    if !wrapwords::is_int(made_for) || !wrapwords::is_int(latest) {
        return None;
    }
    match car_machine::pyval::order(latest, made_for).ok().flatten()? {
        std::cmp::Ordering::Equal => Some(false),
        std::cmp::Ordering::Less => Some(true),
        std::cmp::Ordering::Greater => world
            .codex
            .between(home, thread, made_for, latest)
            .ok()
            .map(|between| between != 0),
    }
}

impl Code for UsageWrapUp {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.bound = Some(Bound::of(binding));
        Some(Ok(()))
    }

    /// P8: at most once a minute, the wrap-ups due and the continuations after a reset; nothing to run.
    fn tick(&mut self, view: &dyn View) -> Spoke {
        let Some(bound) = self.bound.clone() else {
            return Ok(Said::Defer);
        };
        let now = bound.now();
        if let Some(looked) = self.looked
            && (0.0..LOOK_EVERY).contains(&(now - looked))
        {
            return Ok(Said::Defer);
        }
        self.looked = Some(now);
        let _ = self.look_due(&bound, view, now);
        let _ = self.after_reset(&bound, view, now);
        Ok(Said::Defer)
    }

    /// P2: every wrap-up waiting, with its words; past RECORDS_LIMIT, handed from a place that moves on each tick.
    fn records(&mut self, _view: &dyn View) -> Spoke {
        let Some(bound) = self.bound.clone() else {
            return Ok(Said::Defer);
        };
        let Ok(rows) = bound.call(|scoped| {
            scoped
                .state
                .continuations(&scoped.capability, &Value::Null, &Value::Bool(true))
        }) else {
            return Ok(Said::Defer);
        };
        let waiting: Vec<Row> = rows
            .into_iter()
            .filter(|row| is_word(cell(row, "record_state"), "waiting"))
            .collect();
        let later: Vec<Row> = waiting
            .iter()
            .filter(|row| is_word(cell(row, "kind"), "after_reset"))
            .cloned()
            .collect();
        let mut waiting: Vec<Row> = waiting
            .into_iter()
            .filter(|row| !is_word(cell(row, "kind"), "after_reset"))
            .collect();
        if !waiting.is_empty() {
            let spared: Vec<Value> = later
                .iter()
                .map(|row| cell(row, "thread_id").clone())
                .collect();
            waiting = self.still_due(&bound, waiting, &spared);
        }
        waiting.extend(later);
        let mut found: Vec<Value> = waiting
            .into_iter()
            .filter_map(|row| handed(&Value::Object(row)))
            .collect();
        let limit = car_policy::plug::hands::RECORDS_LIMIT;
        if found.len() > limit {
            let start = (self.turn * limit) % found.len();
            found.rotate_left(start);
            self.turn += 1;
        }
        if found.is_empty() {
            return Ok(Said::Defer);
        }
        Ok(Said::Value(Value::Array(found)))
    }
}

// ------------------------------------------------------------------ the pause

/// The pause's holding, which the forced stop keeps (`UsagePause`).
pub struct PauseCore {
    pub paths: Paths,
    pub world: World,
    pub bound: Option<Bound>,
}

impl PauseCore {
    pub fn count(&self, code: &str) {
        if let Some(bound) = &self.bound {
            bound.count(code);
        }
    }

    /// `_mark()`: the windows held and let go at P8, as their readings stand; the rows newly held this tick. A raise
    /// ends the marking where it stands (the reference's one try).
    pub fn mark(&self) -> Vec<Row> {
        let mut newly = Vec::new();
        let _ = self.marking(&mut newly);
        newly
    }

    fn marking(&self, newly: &mut Vec<Row>) -> Result<(), Raised> {
        let Some(bound) = &self.bound else {
            return Ok(());
        };
        if !bound
            .with(|scoped| scoped.handle().is_on())
            .unwrap_or(false)
        {
            return Ok(());
        }
        let now = bound.now();
        let options = bound.call(|scoped| scoped.options())?;
        let on = acting_of(bound);
        let meter = bound.call(meter_rows)?;
        let rows = windows(&meter);
        let resets = credit_resets(bound, &rows);
        let mut current: Vec<Family> = Vec::new();
        let mut any = false;
        for row in &rows {
            if !matches!(cell(row, "paused_reset_at"), Value::Null)
                || reached(
                    row,
                    percent(&options, PAUSE, cell(row, "minutes")).as_ref(),
                    now,
                )?
            {
                any = true;
                break;
            }
        }
        if any {
            let again = bound.call(meter_rows)?;
            current = of_account(&self.world, &again, &self.paths, Some(bound))?
                .iter()
                .map(family_of)
                .collect();
        }
        for row in &rows {
            let minutes = cell(row, "minutes");
            let acted = acts_on(&on, minutes);
            let family = family_of(row);
            let fresh =
                !stale(row, &resets)? && current.iter().any(|held| same_family(held, &family));
            let over =
                acted && fresh && reached(row, percent(&options, PAUSE, minutes).as_ref(), now)?;
            let held = cell(row, "paused_reset_at");
            let reset = cell(row, "reset_at");
            if over && !eq(held, reset) {
                let marked = bound.call(|scoped| {
                    scoped.handle().meter_writer()?;
                    scoped.state.mark_meter(
                        &family.0,
                        &family.1,
                        &Value::Null,
                        reset,
                        &Value::Bool(false),
                        &Value::Null,
                    )
                })?;
                if marked {
                    self.count("paused");
                    newly.push(row.clone());
                }
            } else if !matches!(held, Value::Null)
                && !over
                && (!acted || !fresh || !eq(held, reset) || now >= num(held)? + CLOSE_AFTER)
            {
                let marked = bound.call(|scoped| {
                    scoped.handle().meter_writer()?;
                    scoped.state.mark_meter(
                        &family.0,
                        &family.1,
                        &Value::Null,
                        &Value::Null,
                        &Value::Bool(true),
                        &Value::Null,
                    )
                })?;
                if marked {
                    self.count("resumed");
                }
            }
        }
        Ok(())
    }

    /// `holding()`: whether a window the pause marked has not reset yet - its reset not passed, no reset credit of it
    /// spent since it was read, and read after the account last changed.
    pub fn holding(&self) -> Result<bool, Raised> {
        let Some(bound) = &self.bound else {
            return Ok(false);
        };
        let now = bound.now();
        let meter = bound.call(meter_rows)?;
        let mut held = Vec::new();
        for row in windows(&meter) {
            let paused = cell(&row, "paused_reset_at");
            if !matches!(paused, Value::Null) && now < num(paused)? + CLOSE_AFTER {
                held.push(row);
            }
        }
        if held.is_empty() {
            return Ok(false);
        }
        let resets = credit_resets(bound, &held);
        let mut keyed: Vec<(Family, Row)> = Vec::new();
        for row in held {
            let family = family_of(&row);
            match keyed.iter_mut().find(|(key, _)| same_family(key, &family)) {
                Some(slot) => slot.1 = row,
                None => keyed.push((family, row)),
            }
        }
        for row in of_account(&self.world, &keyed, &self.paths, Some(bound))? {
            if !stale(&row, &resets)? {
                return Ok(true);
            }
        }
        Ok(false)
    }

    /// P3: HOLD a record of core's while a window holds; nothing for anything else.
    pub fn gate(&self, record: &Value) -> Said {
        let Value::Object(map) = record else {
            return Said::Defer;
        };
        if !map.contains_key("interruption_id") {
            return Said::Defer;
        }
        match self.holding() {
            Ok(true) => Said::Word(Alternative::Hold),
            _ => Said::Defer,
        }
    }

    /// `holds(record)`: a continuation of the edition's own waiting is held back from core this tick.
    pub fn holds(&self, record: &Value) -> bool {
        if !(matches!(record, Value::Object(_))
            && is_word(field(record, "state"), "waiting")
            && is_word(field(record, "purpose"), "continuation"))
        {
            return false;
        }
        self.holding().unwrap_or(false)
    }
}

/// `UsagePause(paths)`: the plain pause's code (the registry makes the forced stop).
pub struct UsagePause {
    pub core: PauseCore,
}

impl UsagePause {
    pub fn new(paths: Paths, world: World) -> UsagePause {
        UsagePause {
            core: PauseCore {
                paths,
                world,
                bound: None,
            },
        }
    }
}

impl Code for UsagePause {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.core.bound = Some(Bound::of(binding));
        Some(Ok(()))
    }
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        if self.core.bound.is_some() {
            self.core.mark();
        }
        Ok(Said::Defer)
    }
    fn gate(&mut self, _name: &Value, record: &Value, _facts: &Value) -> Spoke {
        Ok(self.core.gate(record))
    }
    fn holds(&mut self, record: &Value) -> Option<Result<Value, Raised>> {
        Some(Ok(Value::Bool(self.core.holds(record))))
    }
}

/// `make_meter(paths)`.
pub fn make_meter(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(UsageMeter::new(paths.clone(), World::installed())))
}

/// `make_wrap_up(paths)`.
pub fn make_wrap_up(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(UsageWrapUp::new(
        paths.clone(),
        World::installed(),
    )))
}

/// `make_pause(paths)`: usage_pause's code - from v0.6.16-beta.4 the forced stop, which holds as the pause held.
pub fn make_pause(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(super::usagestop::UsageStop::new(
        paths.clone(),
        World::installed(),
    )))
}
