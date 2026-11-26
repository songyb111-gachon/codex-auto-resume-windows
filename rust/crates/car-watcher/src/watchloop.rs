//! `runtime/loop.py`: what the watcher does every few seconds, and how long it waits before doing it again.
//!
//! One tick reads what Codex recorded, registers what is new, sends what is due and reconciles what was sent. The
//! interval moves between `MIN_POLL` and `MAX_POLL` with how much there is to do, and the wake event cuts the wait
//! short when somebody presses Retry now.
//!
//! The reference is a mixin of `App`; here the loop is written once over [`World`], which is everything `App` hands
//! it (its named objects, its store, its engine, its icon, its log, its clocks). `app.rs` is the real world; a test's
//! world answers each call from a script, so no named object, timer or window of the product's is touched.
//!
//! D15: the span each `try:` of the reference covers is also where a panic is caught (`fail::guarded`), so a panic
//! in one tick costs that tick and nothing more; the newer-version errors stay typed (`Failed::newer`).

use std::collections::BTreeMap;

use car_engine::impossible;
use car_machine::json::{Map, Value};
use car_store::Store;

use crate::afterwork::AfterWork;
use crate::fail::{Failed, Res, guarded};
use crate::health::Health;
use crate::homes::Homes;
use crate::waking::Waking;

pub const EXIT_OK: i32 = 0;
pub const EXIT_ERROR: i32 = 1;
pub const EXIT_BUSY: i32 = 3;
/// The state was written by a newer version of this tool; the launcher re-reads the installation once.
pub const EXIT_SCHEMA_NEWER: i32 = 4;
/// v0.6.11: the memory guard stopped the watcher, between two ticks.
pub const EXIT_MEMORY_GUARD: i32 = 5;

/// Long enough that a status probe, which holds the single-instance mutex for microseconds, has let go.
pub const MUTEX_RETRY_SECONDS: f64 = 0.25;
pub const MIN_POLL: i64 = 5;
pub const MAX_POLL: i64 = 3600;
pub const DEFAULT_POLL: i64 = 30;
/// While anything of ours may be sitting in Codex's queue, look this often.
pub const WATCH_SECONDS: f64 = 1.0;
/// However often Retry Now is pressed, at most one extra tick per this many seconds.
pub const WAKE_COALESCE_SECONDS: f64 = 5.0;
/// A store that cannot be opened is retried with a growing wait, up to this.
pub const OPEN_RETRY_MAX_SECONDS: f64 = 60.0;

/// What `_wait_for` saw.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fired {
    Stop,
    Wake,
    Timeout,
}

/// `AdapterError(word)`: a named object that could not be had, by its word (`mutex_busy`, `home_lock_busy`, ...).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Adapter(pub String);

/// The engine as the loop drives it (car-engine's `Engine` in the product, a script in a test).
pub trait TickEngine: crate::waking::Sleeper + crate::afterwork::Activity {
    fn tick(&mut self) -> Res<()>;
    fn watch_needed(&mut self) -> Res<bool>;
    fn watch(&mut self) -> Res<()>;
    /// `engine.last_usage()`: (when, windows) of the last reading, or None.
    fn last_usage(&mut self) -> Res<Option<(Value, Value)>>;
    /// `engine.detection_failed`.
    fn detection_failed(&self) -> Option<bool>;
    /// `engine.handed_waits`.
    fn handed_waits(&self) -> Map;
    /// `engine.apply_policy(values, managed)`.
    fn apply_policy(&mut self, values: &Value, managed: &car_policy::settings::managed::Managed);
    /// `engine.retiring = value`.
    fn set_retiring(&mut self, retiring: bool);
    /// `engine.source.latest_failures(since, admissible=True, shapes=True)`.
    fn latest_failures(&mut self, since: f64) -> Res<Vec<Value>>;
}

/// What `App` hands the loop: every call it makes of `self`.
pub trait World: crate::homes::HomesApp {
    // ---------------------------------------------------------------- the named objects (win/sync.py, HomeLock)
    /// `self.mutex(timeout=0.0).__enter__()`: whether the mutex was abandoned by the watcher before, or why not.
    fn enter_mutex(&mut self) -> Result<bool, Adapter>;
    fn exit_mutex(&mut self);
    fn enter_stop(&mut self) -> Result<(), Adapter>;
    fn exit_stop(&mut self);
    fn enter_wake(&mut self) -> Result<(), Adapter>;
    fn exit_wake(&mut self);
    fn enter_home_lock(&mut self) -> Result<(), Adapter>;
    fn exit_home_lock(&mut self);
    /// `_wait_for(stop, wake, seconds)`, with or without the wake event.
    fn wait_for(&mut self, wake: bool, seconds: f64) -> Fired;
    /// `time.sleep(seconds)`.
    fn sleep(&mut self, seconds: f64);

    // ---------------------------------------------------------------- the clocks and the process
    fn pid(&self) -> u32;
    /// `uuid.uuid4().hex[:12]`.
    fn session_id(&mut self) -> String;
    /// `time.strftime("%H:%M:%S", time.localtime(seconds))`.
    fn clock_text(&self, seconds: f64) -> String;
    /// `config.version()`.
    fn version(&self) -> String;

    // ---------------------------------------------------------------- the log
    fn state_dir(&self) -> String;
    /// The edition's badge, for a plug that is not NULL (None for the standard edition, which writes no line).
    fn edition_badge(&self) -> Option<String>;

    // ---------------------------------------------------------------- what App builds
    /// `Store(state_dir, migrate=True, check=True)`, and the schema it was upgraded from.
    fn open_store(&mut self) -> Res<(Store, Option<i64>)>;
    fn engine_moved(&mut self) -> bool;
    /// `self.engine(store)`: raises `Unreadable` while the settings file cannot be read.
    fn engine(&mut self, store: &Store) -> Res<Box<dyn TickEngine>>;
    fn compatibility_tick(&mut self);
    fn refresh_settings(&mut self, engine: Option<&mut Box<dyn TickEngine>>);
    fn engine_state(&self) -> String;
    fn managed(&self) -> car_policy::settings::managed::Managed;
    /// `getattr(self, "_settings_good", True) is not False`.
    fn settings_good(&self) -> bool;
    fn failure_baseline(&mut self);
    fn sweep_set_aside(&mut self);
    /// `_new_health()`, `Waking(...)`, `_new_afterwork()`.
    fn new_health(&mut self) -> Res<Health>;
    fn new_waking(&mut self) -> Option<Waking>;
    fn new_afterwork(&mut self) -> Res<AfterWork>;
    /// The raise of a watcher notice (`_watcher_notice`).
    fn watcher_notice(&self, event: &str, detail: Map, last: bool) -> Res<()>;
    /// `_start_tray(stop)`: whether an icon was started.
    fn start_tray(&mut self) -> bool;
    fn update_tray(&mut self, store: &Store, blocked: bool);
    fn edition_surface(&mut self, store: &Store);
    fn stop_tray(&mut self);
    /// The Os the status file is written through.
    fn os(&self) -> std::sync::Arc<dyn car_policy::settings::os::Os + Send + Sync>;
    /// The logbook's clock (the power action's lines).
    fn log_clock(&self) -> &dyn car_config::logbook::Clock;

    // ---------------------------------------------------------------- the self-check's looks
    /// `_app_runs()`: whether a process of the Codex app's package runs, or None.
    fn app_runs(&mut self) -> Option<bool>;
    /// `_recovery_facts(store, engine)`: (app runs, {rule: held}), from the backend and the Restart Manager.
    fn recovery_facts(
        &mut self,
        store: &Store,
        engine: &mut dyn TickEngine,
    ) -> Res<(Option<bool>, BTreeMap<&'static str, Option<bool>>)>;
    /// `codex_layout.read(paths.codex_layout_file)`.
    fn layout(&mut self) -> Res<Value>;
    /// `compatio.write_json_atomic(paths.self_check_file, written, "selfcheck.")`: an OSError is said, anything
    /// else raises.
    fn write_self_check(&mut self, written: &Value) -> Res<()>;
    /// `control.watcher.how_it_ended(status, False, sign_in, booted_at)`.
    fn how_it_ended(&self, status: Option<&Map>, sign_in: Option<&str>, booted_at: Option<f64>) -> (Value, Value) {
        car_control::status::how_it_ended(status, Some(false), sign_in, booted_at)
    }
}

/// What the loop keeps between ticks (`_reading_kept`, `_judge`, `_judged_at`, `_unknown_error`,
/// `_self_check_written`, `_homes`).
pub struct Loop {
    reading_kept: Option<Value>,
    judge: Option<impossible::Judge>,
    judged_at: f64,
    unknown_error: Value,
    pub self_check_written: Option<Value>,
    pub homes: Homes,
}

impl Default for Loop {
    fn default() -> Loop {
        Loop::new()
    }
}

impl Loop {
    pub fn new() -> Loop {
        Loop {
            reading_kept: None,
            judge: None,
            judged_at: 0.0,
            unknown_error: Value::Null,
            self_check_written: None,
            homes: Homes::new(),
        }
    }

    /// Whether the watcher's own judge found that recovery cannot work here (the snapshot's `blocked`).
    pub fn blocked(&self) -> bool {
        self.self_check_written
            .as_ref()
            .and_then(|note| match note {
                Value::Object(map) => map.get("blocked"),
                _ => None,
            })
            .is_some_and(|word| !matches!(word, Value::Null))
    }
}

/// `run(once=, poll=)`: busy is checked twice, a moment apart, before it is believed.
pub fn run(world: &mut dyn World, state: &mut Loop, once: bool, poll: Option<i64>) -> i32 {
    let pid = world.pid();
    let mut abandoned = false;
    for attempt in 0..2 {
        match world.enter_mutex() {
            Ok(was) => {
                abandoned = was;
                break;
            }
            Err(Adapter(word)) => {
                if word != "mutex_busy" {
                    world.info(&format!(
                        "single-instance mutex unavailable ({word}); refusing to run (pid {pid})"
                    ));
                    return EXIT_ERROR;
                }
                if attempt == 0 {
                    world.sleep(MUTEX_RETRY_SECONDS);
                    continue;
                }
                world.info(&format!(
                    "another watcher already holds the single-instance mutex; exiting (pid {pid})"
                ));
                return EXIT_BUSY;
            }
        }
    }
    let code = (|| {
        if let Err(Adapter(word)) = world.enter_stop() {
            world.info(&format!(
                "stop event unavailable ({word}); refusing to run (pid {pid})"
            ));
            return EXIT_ERROR;
        }
        let code = (|| {
            let wake = match world.enter_wake() {
                Ok(()) => true,
                Err(Adapter(word)) => {
                    world.info(&format!(
                        "wake event unavailable ({word}); Retry Now waits for the next poll"
                    ));
                    false
                }
            };
            let code = match world.enter_home_lock() {
                Err(Adapter(word)) => {
                    world.info(&format!(
                        "another engine or process holds this Codex home ({word}); refusing to run (pid {pid})"
                    ));
                    EXIT_BUSY
                }
                Ok(()) => {
                    let code = run_loop(world, state, abandoned, wake, once, poll);
                    world.exit_home_lock();
                    code
                }
            };
            if wake {
                world.exit_wake();
            }
            code
        })();
        world.exit_stop();
        code
    })();
    world.exit_mutex();
    code
}

/// `_poll_interval(store, poll)`: a transient store read here must NOT end the watcher.
fn poll_interval(world: &mut dyn World, store: &Store, poll: Option<i64>) -> i64 {
    let interval = match poll.filter(|poll| *poll != 0) {
        Some(poll) => Ok(poll),
        None => guarded(|| {
            let settings = store.settings()?;
            poll_seconds(settings.get("poll_seconds"))
        }),
    };
    let interval = interval.unwrap_or_else(|failed| {
        world.record_failure("poll interval read", &failed);
        poll.filter(|poll| *poll != 0).unwrap_or(DEFAULT_POLL)
    });
    interval.clamp(MIN_POLL, MAX_POLL)
}

/// `int(store.settings()["poll_seconds"])`.
fn poll_seconds(found: Option<&Value>) -> Res<i64> {
    match found {
        None => Err(Failed::new("KeyError", "poll_seconds")),
        Some(Value::Bool(flag)) => Ok(i64::from(*flag)),
        Some(Value::Int(number)) => number
            .as_i64()
            .ok_or_else(|| Failed::new("OverflowError", "")),
        Some(Value::Float(number)) if number.is_finite() => Ok(number.trunc() as i64),
        Some(Value::Float(_)) => Err(Failed::new("ValueError", "")),
        Some(Value::Str(text)) => car_machine::pytext::parse_int(&crate::fail::lossy(text), 10)
            .and_then(|parsed| {
                parsed.magnitude.and_then(|magnitude| {
                    i64::try_from(magnitude)
                        .ok()
                        .map(|n| if parsed.negative { -n } else { n })
                })
            })
            .ok_or_else(|| Failed::new("ValueError", "")),
        Some(_) => Err(Failed::new("TypeError", "")),
    }
}

/// `_open_for_watcher(stop)`: the watcher's store, upgraded under the mutex it holds, retried with backoff. A Store,
/// or an exit code.
fn open_for_watcher(world: &mut dyn World) -> Result<Store, i32> {
    let mut delay: f64 = 1.0;
    loop {
        match guarded(|| world.open_store()) {
            Ok((store, migrated_from)) => {
                if let Some(from) = migrated_from {
                    world.info(&format!(
                        "state upgraded from schema {from} to {}",
                        car_store::SCHEMA_VERSION
                    ));
                }
                return Ok(store);
            }
            Err(failed) if failed.class == "StateFromNewerVersion" => {
                world.info("schema_newer_than_watcher; exiting so the installed version can start");
                return Err(EXIT_SCHEMA_NEWER);
            }
            Err(failed) => world.record_failure("opening state", &failed),
        }
        if world.wait_for(false, delay) == Fired::Stop {
            return Err(EXIT_OK);
        }
        delay = (delay * 2.0).min(OPEN_RETRY_MAX_SECONDS);
    }
}

/// `_heartbeat(...)`: the heartbeat reports health; it must never be the thing that fails.
#[allow(clippy::too_many_arguments)]
fn heartbeat(
    world: &mut dyn World,
    state: &mut Loop,
    store: &Store,
    session: &str,
    started: f64,
    ok: bool,
    engine: Option<&mut Box<dyn TickEngine>>,
    awake: Option<f64>,
    health: Option<&Health>,
) {
    let usage = new_reading(state, engine);
    let now = world.now();
    let beat = car_store::watcher::Beat {
        pid: i64::from(world.pid()),
        session_id: session.to_owned(),
        started_at: Value::Float(started),
        ok,
        engine_state: world.engine_state(),
        code_version: world.version(),
        usage,
        awake_since: awake.map_or(Value::Null, Value::Float),
        memory_peak: health
            .and_then(|health| health.peak)
            .map_or(Value::Null, |peak| Value::from(peak)),
        sign_in: health
            .and_then(|health| health.sign_in.clone())
            .map_or(Value::Null, Value::from),
        booted_at: health
            .and_then(|health| health.booted_at)
            .map_or(Value::Null, Value::Float),
        homes: state.homes.heartbeat(world),
    };
    let _ = guarded(|| Ok(store.heartbeat(now, &beat)?));
}

/// `_predecessor(store, health)`: one line for the watcher before this one where it ended without stopping, in this
/// sign-in of this start of Windows. A reading that fails costs the line.
fn predecessor(world: &mut dyn World, store: &Store, health: Option<&Health>) {
    let _ = guarded(|| {
        let status = store.watcher_status()?;
        let (ended, seen) = world.how_it_ended(
            status.as_ref(),
            health.and_then(|health| health.sign_in.as_deref()),
            health.and_then(|health| health.booted_at),
        );
        if car_machine::pyval::is(&ended, "unexpected") {
            let pid = status
                .as_ref()
                .and_then(|status| status.get("pid"))
                .map_or("None".to_owned(), car_machine::pytext::py_str);
            let seen = car_machine::pytext::to_float(&seen)
                .map_err(|class| Failed::new(class, ""))?;
            world.info(&format!(
                "the watcher before this one (pid {pid}, last seen {}) ended without stopping, in this start of Windows",
                world.clock_text(seen)
            ));
        }
        Ok(())
    });
}

/// `_memory(health, guard=)`: True when the memory guard stops the watcher now - never for a single tick. A failure
/// here costs the look, never the watcher.
fn memory(world: &mut dyn World, health: Option<&mut Health>, guard: bool) -> bool {
    let Some(health) = health else {
        return false;
    };
    let values = world.values();
    let seen: &dyn World = world;
    let result = guarded(|| {
        health.look();
        if !guard {
            return Ok(false);
        }
        let log = |line: &str| seen.info(line);
        let notice = |event: &str, detail: Map, last: bool| seen.watcher_notice(event, detail, last);
        health.over(&values, &log, &notice)
    });
    match result {
        Ok(stop) => stop,
        Err(failed) => {
            seen.record_failure("memory guard", &failed);
            false
        }
    }
}

/// `_status(health, store, running=)`: the status file for other tools, while its setting is on.
fn status(world: &mut dyn World, health: Option<&mut Health>, store: &Store, running: bool) {
    let Some(health) = health else {
        return;
    };
    let values = world.values();
    let engine = world.engine_state();
    let os = world.os();
    let seen: &dyn World = world;
    let log = |line: &str| seen.info(line);
    let result = guarded(|| health.status(store, &values, running, &engine, &*os, &log));
    if let Err(failed) = result {
        seen.record_failure("status file", &failed);
    }
}

/// `_ended(health, store, end)`: that the watcher stops on purpose, and how, and the status file's last word.
fn ended(world: &mut dyn World, health: Option<&mut Health>, store: &Store, end: Option<&str>) {
    let (Some(health), Some(end)) = (health, end) else {
        return;
    };
    if let Err(failed) = guarded(|| health.ended(store, end)) {
        world.record_failure("recording how the watcher stopped", &failed);
    }
    status(world, Some(health), store, false);
}

/// `_keep_awake(waking, store, ok)`: since when this PC is kept awake, or None. A failure lets go.
fn keep_awake(
    world: &mut dyn World,
    waking: Option<&mut Waking>,
    store: &Store,
    ok: bool,
) -> Option<f64> {
    let waking = waking?;
    let values = world.values();
    let managed = world.managed();
    let seen: &dyn World = world;
    let log = |line: &str| seen.info(line);
    let result = guarded(|| {
        // Off (the default): `after` only lets go, so no settings row is read for it.
        let paused = car_policy::classify::power::keep_awake(&values) != "off"
            && (!car_machine::pyval::truthy(
                store
                    .settings()?
                    .get("enabled")
                    .ok_or_else(|| Failed::new("KeyError", "enabled"))?,
            ) || managed.disable_auto_resume);
        waking.after(store, &values, ok, paused, &log)
    });
    match result {
        Ok(since) => since,
        Err(failed) => {
            seen.record_failure("keeping this PC awake", &failed);
            guarded(|| Ok(waking.let_go(&log))).unwrap_or(None)
        }
    }
}

/// `_after_work(afterwork, store, engine, ok, waking)`: one look of the power action, on the same thread. A failure
/// here ends any countdown and costs nothing else.
fn after_work(
    world: &mut dyn World,
    afterwork: Option<&mut AfterWork>,
    store: &Store,
    engine: Option<&mut Box<dyn TickEngine>>,
    ok: bool,
    waking: Option<&mut Waking>,
) {
    let Some(afterwork) = afterwork else {
        return;
    };
    let values = world.values();
    let managed = world.managed();
    let seen: &dyn World = world;
    let log = |line: &str| seen.info(line);
    let notice = |event: &str, detail: Map, last: bool| seen.watcher_notice(event, detail, last);
    let clock = LinesClock(seen.log_clock());
    let engine: Option<&mut dyn crate::afterwork::Activity> = match engine {
        Some(engine) => Some(&mut **engine),
        None => None,
    };
    let result = guarded(|| {
        afterwork.look(crate::afterwork::Look {
            store,
            engine,
            ok,
            waking,
            settings: &values,
            managed: &managed,
            log: &log,
            notice: &notice,
            clock: &clock,
        })
    });
    if let Err(failed) = result {
        seen.record_failure("the power action", &failed);
        crate::fail::quietly(|| afterwork.halt(&log, &clock));
    }
}

/// The world's logbook clock, borrowed for one look.
struct LinesClock<'a>(&'a dyn car_config::logbook::Clock);

impl car_config::logbook::Clock for LinesClock<'_> {
    fn now(&self) -> f64 {
        self.0.now()
    }
    fn utc_offset(&self, seconds: i64) -> Option<i32> {
        self.0.utc_offset(seconds)
    }
}

/// `_new_reading(engine)`: the engine's last usage reading, the first time the heartbeat is handed it.
fn new_reading(state: &mut Loop, engine: Option<&mut Box<dyn TickEngine>>) -> Option<(Value, Value)> {
    let reading = match engine {
        Some(engine) => guarded(|| engine.last_usage()).ok().flatten(),
        None => None,
    }?;
    if state
        .reading_kept
        .as_ref()
        .is_some_and(|kept| car_machine::pyval::eq(kept, &reading.0))
    {
        return None;
    }
    state.reading_kept = Some(reading.0.clone());
    Some(reading)
}

/// `_between_ticks(stop, wake, engine, interval, last_tick)`: 'stop', 'wake' or None.
fn between_ticks(
    world: &mut dyn World,
    state: &mut Loop,
    wake: bool,
    mut engine: Option<&mut Box<dyn TickEngine>>,
    interval: f64,
    last_tick: f64,
) -> Fired {
    let deadline = world.monotonic() + interval;
    loop {
        let remaining = deadline - world.monotonic();
        if remaining <= 0.0 {
            return Fired::Timeout;
        }
        let watching = guarded(|| {
            let mut watching = match engine.as_deref_mut() {
                Some(engine) => engine.watch_needed()?,
                None => false,
            };
            watching = watching || state.homes.watch_needed()?;
            Ok(watching)
        })
        .unwrap_or(false);
        let fired = world.wait_for(
            wake,
            if watching {
                remaining.min(WATCH_SECONDS)
            } else {
                remaining
            },
        );
        if fired == Fired::Stop {
            return Fired::Stop;
        }
        if fired == Fired::Wake {
            let gap = WAKE_COALESCE_SECONDS - (world.monotonic() - last_tick);
            if gap > 0.0 && world.wait_for(false, gap) == Fired::Stop {
                return Fired::Stop;
            }
            return Fired::Wake;
        }
        if !watching {
            return Fired::Timeout;
        }
        if let Some(engine) = engine.as_deref_mut()
            && let Err(failed) = guarded(|| engine.watch())
        {
            world.record_failure("watch", &failed);
        }
        state.homes.watch(world);
    }
}

/// The tick's own body: what the reference's one `try:` covers.
fn tick_body(
    world: &mut dyn World,
    state: &mut Loop,
    store: &Store,
    engine: &mut Option<Box<dyn TickEngine>>,
    last_enabled: &mut Option<bool>,
    waking: Option<&mut Waking>,
) -> Res<()> {
    if store.schema_version()? > car_store::SCHEMA_VERSION
        && store.readable_from()? > car_store::SCHEMA_VERSION
    {
        return Err(Failed::new("StateFromNewerVersion", "newer schema"));
    }
    if engine.is_some() && world.engine_moved() {
        *engine = None;
    }
    if engine.is_none() {
        let built = guarded(|| world.engine(store));
        world.compatibility_tick();
        *engine = Some(built?);
    } else {
        world.refresh_settings(engine.as_mut());
        world.compatibility_tick();
    }
    let settings = store.settings()?;
    let enabled = car_machine::pyval::truthy(
        settings
            .get("enabled")
            .ok_or_else(|| Failed::new("KeyError", "enabled"))?,
    );
    if Some(enabled) != *last_enabled {
        world.info(&format!(
            "auto-resume is {}",
            if enabled {
                "enabled"
            } else {
                "disabled (kill switch active; no submissions)"
            }
        ));
        *last_enabled = Some(enabled);
    }
    let engine = engine.as_mut().expect("built above");
    // Before any gate runs: what fell due during a long sleep waits for a person first.
    if let Some(waking) = waking {
        let values = world.values();
        let seen: &dyn World = world;
        let log = |line: &str| seen.info(line);
        let sleeper: &mut dyn crate::waking::Sleeper = &mut **engine;
        waking.before(Some(sleeper), &values, &log)?;
    }
    engine.tick()?;
    // ok = True is the caller's, once this returns.
    other_homes(world, state, store)
}

/// `_other_homes(store)`: the other Codex homes' tick, after the default home's.
fn other_homes(world: &mut dyn World, state: &mut Loop, store: &Store) -> Res<()> {
    let result = guarded(|| {
        state.homes.sync(world, store)?;
        state.homes.tick(world);
        Ok(())
    });
    match result {
        Err(failed) if failed.newer() => Err(failed),
        Err(failed) => {
            world.record_failure("other Codex homes", &failed);
            Ok(())
        }
        Ok(()) => Ok(()),
    }
}

/// `_loop(mutex, stop, wake, once=, poll=)`.
fn run_loop(
    world: &mut dyn World,
    state: &mut Loop,
    abandoned: bool,
    wake: bool,
    once: bool,
    poll: Option<i64>,
) -> i32 {
    let pid = world.pid();
    let state_dir = world.state_dir();
    world.info(&format!("watcher started (pid {pid}, state {state_dir})"));
    if let Some(badge) = world.edition_badge() {
        world.info(&format!("edition {badge}"));
    }
    if abandoned {
        world.info(
            "previous watcher exited without releasing the mutex; reconciling before any send",
        );
    }
    let store = match open_for_watcher(world) {
        Ok(store) => store,
        Err(code) => return code,
    };
    let session = world.session_id();
    let started = world.now();
    let mut engine: Option<Box<dyn TickEngine>> = None;
    let mut last_enabled: Option<bool> = None;
    let mut exit_code = EXIT_OK;
    let mut end: Option<&'static str> = None;
    let mut health = match guarded(|| world.new_health()) {
        Ok(health) => Some(health),
        Err(failed) => {
            world.record_failure("the watcher's own health", &failed);
            None
        }
    };
    predecessor(world, &store, health.as_ref());
    if !once {
        world.failure_baseline();
        world.sweep_set_aside();
    }
    let icon = !once && world.start_tray();
    let mut waking = if once { None } else { world.new_waking() };
    let mut afterwork = if once {
        None
    } else {
        match guarded(|| world.new_afterwork()) {
            Ok(found) => Some(found),
            Err(failed) => {
                world.record_failure("the power action", &failed);
                None
            }
        }
    };
    state.homes = Homes::new();
    loop {
        let mut ok = false;
        let result = guarded(|| {
            tick_body(
                world,
                state,
                &store,
                &mut engine,
                &mut last_enabled,
                waking.as_mut(),
            )
        });
        match result {
            Ok(()) => ok = true,
            Err(failed) if failed.newer() => {
                world.info("schema_newer_than_watcher; exiting so the installed version can start");
                exit_code = EXIT_SCHEMA_NEWER;
                break;
            }
            Err(failed) if failed.class == "Unreadable" => {
                if engine.is_some() {
                    world.record_failure("tick", &failed);
                }
            }
            Err(failed) if store_error(&failed) => world.record_failure("tick", &failed),
            Err(failed) => world.record_failure(
                if engine.is_none() {
                    "initialising Codex adapter"
                } else {
                    "tick"
                },
                &failed,
            ),
        }
        let awake = keep_awake(world, waking.as_mut(), &store, ok);
        after_work(
            world,
            afterwork.as_mut(),
            &store,
            engine.as_mut(),
            ok,
            waking.as_mut(),
        );
        let stopping = memory(world, health.as_mut(), !once);
        heartbeat(
            world,
            state,
            &store,
            &session,
            started,
            ok,
            engine.as_mut(),
            awake,
            health.as_ref(),
        );
        if !once {
            self_check(world, state, &store, engine.as_mut(), started);
        }
        status(world, health.as_mut(), &store, true);
        if !once {
            world.failure_baseline();
        }
        if icon {
            let blocked = state.blocked();
            world.update_tray(&store, blocked);
        } else {
            world.edition_surface(&store);
        }
        let last_tick = world.monotonic();
        if once {
            if engine.is_none() {
                exit_code = EXIT_ERROR;
            }
            end = Some("clean");
            break;
        }
        if stopping {
            end = Some("memory_guard");
            exit_code = EXIT_MEMORY_GUARD;
            break;
        }
        let mut interval = poll_interval(world, &store, poll) as f64;
        if let Some(afterwork) = &afterwork {
            interval = afterwork.cap(interval);
        }
        if between_ticks(world, state, wake, engine.as_mut(), interval, last_tick) == Fired::Stop {
            world.info("stop requested; watcher exiting");
            end = Some("clean");
            break;
        }
    }
    {
        let seen: &dyn World = world;
        let log = |line: &str| seen.info(line);
        if let Some(afterwork) = afterwork.as_mut() {
            let clock = LinesClock(seen.log_clock());
            // A countdown simply ends: nothing is done.
            if let Err(failed) = guarded(|| {
                afterwork.stop(&log, &clock);
                Ok(())
            }) {
                seen.record_failure("the power action", &failed);
            }
        }
        if let Some(waking) = waking.as_mut() {
            // On the thread that made the request, which holds it.
            if let Err(failed) = guarded(|| {
                waking.stop(&log);
                Ok(())
            }) {
                seen.record_failure("letting this PC sleep", &failed);
            }
        }
    }
    if icon {
        world.stop_tray();
    }
    state.homes.close(world);
    ended(world, health.as_mut(), &store, end);
    let mut store = store;
    store.close();
    world.info("watcher stopped");
    exit_code
}

/// The store's own refusals (`except StoreError`), which say "tick" whether or not an engine was built.
fn store_error(failed: &Failed) -> bool {
    matches!(failed.class.as_str(), "StoreError" | "UpgradePending")
}

/// `_self_check(store, engine, started)`: one tick of the watcher's judge of its own looks, and what it says written
/// beside the heartbeat, only when that changed.
fn self_check(
    world: &mut dyn World,
    state: &mut Loop,
    store: &Store,
    mut engine: Option<&mut Box<dyn TickEngine>>,
    started: f64,
) {
    let mut judge = state.judge.take().unwrap_or_else(impossible::Judge::new);
    let now = world.now();
    let looked = guarded(|| {
        let missing = engine.is_none() && world.settings_good();
        let unreadable = engine
            .as_deref()
            .is_some_and(|engine| engine.detection_failed() == Some(true));
        let runs = if missing || unreadable {
            world.app_runs() == Some(true)
        } else {
            false
        };
        let mut facts = BTreeMap::new();
        facts.insert("engine_missing", missing);
        facts.insert("history_unreadable", unreadable);
        judge.tick(runs, &facts);
        match engine.as_deref_mut() {
            None => judge.look(now, false, &BTreeMap::new()),
            Some(engine) => {
                if now - state.judged_at >= impossible::LOOK_EVERY_SECONDS || now < state.judged_at {
                    state.judged_at = now;
                    let (runs, facts) = world.recovery_facts(store, &mut **engine)?;
                    judge.look(now, runs == Some(true), &facts);
                    state.unknown_error = unknown_errors(&mut **engine, now, &state.unknown_error);
                }
            }
        }
        Ok(())
    });
    if let Err(failed) = looked {
        world.record_failure("the self-check", &failed);
        judge.look(now, false, &BTreeMap::new());
    }
    let (untested, updated) = match guarded(|| layout_said(world)) {
        Ok(found) => found,
        Err(failed) => {
            world.record_failure("the self-check", &failed);
            (Value::Null, Value::Null)
        }
    };
    let word = judge.word(now).map_or(Value::Null, Value::from);
    state.judge = Some(judge);
    let Ok(written) = car_machine::domain::public::self_check_note(
        &Value::Float(started),
        &word,
        &state.unknown_error,
        &untested,
        &updated,
    ) else {
        return;
    };
    if state
        .self_check_written
        .as_ref()
        .is_some_and(|before| car_machine::pyval::eq(before, &written))
    {
        return;
    }
    match world.write_self_check(&written) {
        Ok(()) => {
            state.self_check_written = Some(written.clone());
            if let Value::Object(map) = &written
                && let Some(blocked) = map.get("blocked")
                && !matches!(blocked, Value::Null)
            {
                world.info(&format!(
                    "self-check: {}",
                    car_machine::pytext::py_str(blocked)
                ));
            }
        }
        Err(failed) => world.record_failure("writing the self-check", &failed),
    }
}

/// `_layout_said()`: (Codex's version where the app runs in a layout this version has not been tested on, the
/// version of this product it was updated from where no look since has paired a server), each None.
fn layout_said(world: &mut dyn World) -> Res<(Value, Value)> {
    let kept = world.layout()?;
    let Value::Object(kept) = kept else {
        return Ok((Value::Null, Value::Null));
    };
    let found = match kept.get("layout") {
        Some(Value::Object(found)) => found.clone(),
        _ => Map::new(),
    };
    // `type(found.get(name)) is int and found[name] > 0`: a bool is not an int here.
    let app_open = ["mains", "helpers"].iter().any(|name| match found.get(*name) {
        Some(count @ Value::Int(_)) => {
            car_machine::pyval::greater(count, &Value::from(0)).unwrap_or(false)
        }
        _ => false,
    });
    let untested = if app_open && matches!(kept.get("catalogued"), Some(Value::Bool(false))) {
        car_machine::domain::public::version_word(kept.get("app_version").unwrap_or(&Value::Null))
            .or_else(|| {
                car_machine::domain::public::version_word(
                    kept.get("engine_version").unwrap_or(&Value::Null),
                )
            })
            .map_or(Value::Null, Value::from)
    } else {
        Value::Null
    };
    let updated = if matches!(kept.get("unpaired_after_update"), Some(Value::Bool(true))) {
        kept.get("updated_from").cloned().unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let text = |value: Value| match value {
        Value::Str(_) => value,
        _ => Value::Null,
    };
    Ok((text(untested), text(updated)))
}

/// `_unknown_errors(engine, now)`: the newest error code Codex reported in the last day that this version does not
/// know, with how many of the latest turns failed with it, or None.
fn unknown_errors(engine: &mut dyn TickEngine, now: f64, kept: &Value) -> Value {
    let Ok(read) = guarded(|| engine.latest_failures((now - 86_400.0).max(0.0))) else {
        return kept.clone();
    };
    let mut found: Vec<(Value, Value)> = Vec::new();
    for entry in &read {
        let Ok(code) = car_policy::classify::failures::unknown_code(entry) else {
            continue;
        };
        if matches!(code, Value::Null) {
            continue;
        }
        let at = match entry {
            Value::Object(map) => map.get("completed_at").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let at = if car_machine::pyval::truthy(&at) {
            at
        } else {
            Value::from(0)
        };
        found.push((at, code));
    }
    if found.is_empty() {
        return Value::Null;
    }
    // max(found): by time, then by code.
    let mut newest = 0;
    for (index, each) in found.iter().enumerate().skip(1) {
        let best = &found[newest];
        let later = car_machine::pyval::greater(&each.0, &best.0).unwrap_or(false)
            || (car_machine::pyval::eq(&each.0, &best.0)
                && car_machine::pyval::greater(&each.1, &best.1).unwrap_or(false));
        if later {
            newest = index;
        }
    }
    let code = found[newest].1.clone();
    let count = found
        .iter()
        .filter(|(_, each)| car_machine::pyval::eq(each, &code))
        .count();
    let mut map = Map::new();
    map.insert("code".into(), code);
    map.insert("count".into(), Value::from(count as i64));
    Value::Object(map)
}
