//! `runtime/app.py`: the composition root - the log, the settings, the state, the named objects, the health,
//! waking and power-action parts, and the icon's events - built once and handed to the loop as its [`World`].
//!
//! The engine and what it is built from (discovery of codex.exe, the backend, the Compatibility Registry's
//! evaluator, the layout watch, the notifier) come in through [`EngineMaker`], one seam: car-engine, car-codex's
//! transport and evaluator are each ported and diffed on their own (S3.3, S4.1), and the integration that joins them
//! to this world is the host's (S6.2b with the integration seat). Until it is joined the standard maker refuses with
//! a typed failure (`EngineNotJoined`), which the loop logs as the reference logs an engine that will not start:
//! "initialising Codex adapter failed (...)"; nothing is sent.
//!
//! The icon is the host's to draw (P6-DESIGN 1.4, 1.5): `start_tray` queues the `surfaces` event and waits up to 5 s
//! for `tray_started`; `update_tray` queues a `snapshot`; `stop_tray` queues `close` and waits up to 5 s for `closed`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_policy::settings::managed::{self, Managed};
use car_policy::settings::os::Os;
use car_store::Store;

use crate::afterwork::AfterWork;
use crate::events::Events;
use crate::fail::{Failed, Res};
use crate::health::Health;
use crate::homes::{HeldLock, HomeBackend, HomesApp};
use crate::waking::Waking;
use crate::watchloop::{Adapter, Fired, TickEngine, World};

/// The engine and everything it is built from, as App builds it (`backend`, `engine`, `engine_moved`,
/// `_compatibility_tick`, `engine_state`, `home_backend`, `home_engine`).
pub trait EngineMaker {
    fn engine(&mut self, store: &Store, values: &Map, managed: &Managed) -> Res<Box<dyn TickEngine>>;
    fn engine_moved(&mut self) -> bool {
        false
    }
    fn compatibility_tick(&mut self) {}
    fn engine_state(&self) -> String {
        "unknown".into()
    }
    fn codex_exe(&mut self) -> Option<String> {
        None
    }
    fn app_identity(&mut self) -> Res<Value> {
        Err(Failed::new("EngineNotJoined", ""))
    }
    /// `_recovery_facts(store, engine)`.
    fn recovery_facts(
        &mut self,
        _store: &Store,
        _engine: &mut dyn TickEngine,
    ) -> Res<(Option<bool>, BTreeMap<&'static str, Option<bool>>)> {
        Ok((None, BTreeMap::new()))
    }
    fn home_backend(&mut self, _path: &str, _exe: &str) -> Res<Box<dyn HomeBackend>> {
        Err(Failed::new("EngineNotJoined", ""))
    }
    fn home_engine(
        &mut self,
        _store: &Store,
        _path: &str,
        _exe: &str,
        _key: &str,
        _held: std::rc::Rc<std::cell::RefCell<Box<dyn HeldLock>>>,
    ) -> Res<Box<dyn TickEngine>> {
        Err(Failed::new("EngineNotJoined", ""))
    }
}

/// The standard maker before the integration joins car-engine here: every build refused, typed.
pub struct NotJoined;

impl EngineMaker for NotJoined {
    fn engine(&mut self, _store: &Store, _values: &Map, _managed: &Managed) -> Res<Box<dyn TickEngine>> {
        Err(Failed::new("EngineNotJoined", "car-engine is joined to the watcher by the integration"))
    }
}

/// The links probe for the store and the paths.
#[derive(Clone, Copy, Debug)]
pub struct Probe;

impl car_store::session::Links for Probe {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

impl car_config::Links for Probe {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
    fn find_first_file(&self, path: &str) -> Result<String, i32> {
        car_platform::paths::find_first_file(path)
    }
}

/// `config.Paths(home)` on this machine.
pub fn paths(home: Option<&str>, project_root: &str) -> Result<Paths, &'static str> {
    let env = |name: &str| std::env::var(name).ok();
    Paths::new(
        home,
        project_root,
        &env,
        car_config::Os::here(false, Arc::new(Probe)),
    )
}

struct PathLock(car_platform::homelock::HomeLock);

impl HeldLock for PathLock {
    fn identity(&self) -> Option<String> {
        self.0.identity.clone()
    }
    fn held(&self) -> bool {
        self.0.held()
    }
    fn exit(&mut self) {
        self.0.exit();
    }
}

/// What the watcher is started with.
pub struct Start {
    pub paths: Paths,
    pub project_root: String,
    /// `codex_home`: the argument, else `config.codex_home()`.
    pub codex_home: String,
    pub plug: car_policy::plug::Guarded,
    pub host: Arc<dyn car_control::host::Host>,
    pub events: Arc<Events>,
    pub maker: Box<dyn EngineMaker>,
}

/// App: the real world of the loop.
pub struct App {
    pub paths: Paths,
    project_root: String,
    codex_home: String,
    plug: car_policy::plug::Guarded,
    host: Arc<dyn car_control::host::Host>,
    events: Arc<Events>,
    maker: Box<dyn EngineMaker>,
    log: car_config::logbook::Logbook,
    clock: crate::clock::LogClock,
    os: Arc<dyn Os + Send + Sync>,
    managed: Managed,
    stored: Map,
    settings: Map,
    settings_good: bool,
    settings_unread: bool,
    settings_stamp: Option<(u128, u64)>,
    mutex: Option<car_platform::sync::Mutex>,
    stop: Option<car_platform::sync::StopEvent>,
    wake: Option<car_platform::sync::WakeEvent>,
    home_lock: Option<car_platform::homelock::HomeLock>,
    lock_dir: String,
    tray: bool,
    notices: crate::plugnotices::PlugNotices,
}

fn stamp(path: &str) -> Option<(u128, u64)> {
    let meta = std::fs::metadata(path).ok()?;
    let modified = meta
        .modified()
        .ok()?
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_nanos();
    Some((modified, meta.len()))
}

impl App {
    pub fn new(start: Start) -> App {
        let _ = start.paths.ensure();
        let log = car_config::logbook::Logbook::open(&start.paths.log_file, "", &[])
            .with_rename(|from, to| car_platform::files::rename(from, to));
        let os: Arc<dyn Os + Send + Sync> = Arc::new(car_control::host::PlatformOs);
        let managed = start.host.managed();
        let lock_dir = std::env::var("LOCALAPPDATA")
            .ok()
            .filter(|found| !found.is_empty())
            .unwrap_or_else(|| std::env::var("USERPROFILE").unwrap_or_default());
        let mut app = App {
            paths: start.paths,
            project_root: start.project_root,
            codex_home: start.codex_home,
            plug: start.plug,
            host: start.host,
            events: start.events,
            maker: start.maker,
            log,
            clock: crate::clock::LogClock::here(),
            os,
            managed,
            stored: car_policy::settings::defaults(),
            settings: Map::new(),
            settings_good: false,
            settings_unread: false,
            settings_stamp: None,
            mutex: None,
            stop: None,
            wake: None,
            home_lock: None,
            lock_dir: Path::new(&lock_dir)
                .join("codex-auto-resume")
                .join("homes")
                .to_string_lossy()
                .into_owned(),
            tray: false,
            notices: crate::plugnotices::PlugNotices::new(),
        };
        let stored = app.read_settings();
        app.settings_good = stored.is_some();
        if let Some(stored) = stored {
            app.stored = stored;
        }
        app.settings = managed::clamp(&app.stored, &app.managed);
        if app.settings_good {
            app.settings_stamp = stamp(&app.paths.settings_file);
        }
        app
    }

    /// `_read_settings()`: the stored settings, or None while the file is there and cannot be read (said once).
    fn read_settings(&mut self) -> Option<Map> {
        match car_policy::settings::read(&*self.os, Path::new(&self.paths.settings_file)) {
            Err(car_policy::settings::SettingsError::Unreadable { reason, .. }) => {
                if !self.settings_unread {
                    self.settings_unread = true;
                    self.info(&format!("the settings file could not be read ({reason}); the settings in force are kept, nothing is done on the defaults, and it is read again at the next tick"));
                }
                None
            }
            Err(_) => None,
            Ok(stored) => {
                if self.settings_unread {
                    self.settings_unread = false;
                    self.info("the settings file was read again");
                }
                Some(stored)
            }
        }
    }

    fn control(&self) -> car_control::Control {
        car_control::Control::new(
            self.paths.clone(),
            Arc::clone(&self.host),
            car_policy::plug::Guarded::null(),
        )
    }

    /// `watcher_running()`: True/False, or None when the probe itself is unavailable.
    pub fn watcher_running(state_dir: &str) -> Option<bool> {
        let mut mutex = car_platform::sync::Mutex::new(state_dir, 0.0).ok()?;
        match mutex.enter() {
            Ok(()) => {
                mutex.exit();
                Some(false)
            }
            Err(error) if error.0 == "mutex_busy" => Some(true),
            Err(_) => None,
        }
    }
}

impl HomesApp for App {
    fn values(&self) -> Value {
        Value::Object(self.settings.clone())
    }
    fn info(&self, line: &str) {
        self.log.info(line, &self.clock);
    }
    fn record_failure(&self, label: &str, failed: &Failed) {
        self.info(&format!(
            "{label} failed ({}); no submission was made",
            failed.class
        ));
        let path = PathBuf::from(&self.paths.error_log);
        let _ = (|| -> std::io::Result<()> {
            use std::io::Write;
            let mut stream = car_machine::pyfile::options()
                .create(true)
                .append(true)
                .open(&path)?;
            let when = car_watcher_stamp(&self.clock);
            let text = format!("{when}{label}\n{failed}\n");
            stream.write_all(text.replace('\n', "\r\n").as_bytes())?;
            drop(stream);
            if std::fs::metadata(&path)?.len() > 2_000_000 {
                car_platform::files::replace(&path, &path.with_extension("log.1"))?;
            }
            Ok(())
        })();
    }
    fn now(&mut self) -> f64 {
        crate::clock::wall()
    }
    fn monotonic(&mut self) -> f64 {
        crate::clock::monotonic()
    }
    fn path_os(&self) -> Arc<dyn Os + Send + Sync> {
        Arc::clone(&self.os)
    }
    fn default_codex_exe(&mut self) -> Option<String> {
        self.maker.codex_exe()
    }
    fn default_app_identity(&mut self) -> Res<Value> {
        self.maker.app_identity()
    }
    fn default_lock_identity(&self) -> Option<String> {
        self.home_lock.as_ref().and_then(|lock| lock.identity.clone())
    }
    fn codex_home(&self) -> String {
        self.codex_home.clone()
    }
    fn extra_home_lock(&mut self, path: &str) -> Result<Box<dyn HeldLock>, Adapter> {
        let mut lock = car_platform::homelock::HomeLock::new(path, Some(&self.lock_dir), true)
            .map_err(|error| Adapter(error.0.to_owned()))?;
        lock.enter().map_err(|error| Adapter(error.0.to_owned()))?;
        Ok(Box::new(PathLock(lock)))
    }
    fn home_backend(&mut self, path: &str, exe: &str) -> Res<Box<dyn HomeBackend>> {
        self.maker.home_backend(path, exe)
    }
    fn home_engine(
        &mut self,
        store: &Store,
        path: &str,
        exe: &str,
        key: &str,
        held: std::rc::Rc<std::cell::RefCell<Box<dyn HeldLock>>>,
    ) -> Res<Box<dyn TickEngine>> {
        self.maker.home_engine(store, path, exe, key, held)
    }
}

/// `time.strftime("[%Y-%m-%d %H:%M:%S] ")` in this PC's zone.
fn car_watcher_stamp(clock: &crate::clock::LogClock) -> String {
    use car_machine::localclock::LocalClock;
    let now = crate::clock::wall();
    match car_platform::localclock::Crt.localtime(now.floor()) {
        Ok(tm) => format!(
            "[{:04}-{:02}-{:02} {:02}:{:02}:{:02}] ",
            tm.year, tm.mon, tm.mday, tm.hour, tm.min, tm.sec
        ),
        Err(_) => {
            let _ = clock;
            "[0000-00-00 00:00:00] ".into()
        }
    }
}

fn adapter(error: car_machine::domain::errors::AdapterError) -> Adapter {
    Adapter(error.0.to_owned())
}

impl World for App {
    fn enter_mutex(&mut self) -> Result<bool, Adapter> {
        let mut mutex = car_platform::sync::Mutex::new(&self.paths.state_dir, 0.0).map_err(adapter)?;
        mutex.enter().map_err(adapter)?;
        let abandoned = mutex.abandoned;
        self.mutex = Some(mutex);
        Ok(abandoned)
    }
    fn exit_mutex(&mut self) {
        if let Some(mut mutex) = self.mutex.take() {
            mutex.exit();
        }
    }
    fn enter_stop(&mut self) -> Result<(), Adapter> {
        let mut stop = car_platform::sync::StopEvent::new(&self.paths.state_dir).map_err(adapter)?;
        stop.enter().map_err(adapter)?;
        self.stop = Some(stop);
        Ok(())
    }
    fn exit_stop(&mut self) {
        if let Some(mut stop) = self.stop.take() {
            stop.exit();
        }
    }
    fn enter_wake(&mut self) -> Result<(), Adapter> {
        let mut wake = car_platform::sync::WakeEvent::new(&self.paths.state_dir).map_err(adapter)?;
        wake.enter().map_err(adapter)?;
        self.wake = Some(wake);
        Ok(())
    }
    fn exit_wake(&mut self) {
        if let Some(mut wake) = self.wake.take() {
            wake.exit();
        }
    }
    fn enter_home_lock(&mut self) -> Result<(), Adapter> {
        let mut lock = car_platform::homelock::HomeLock::new(&self.codex_home, Some(&self.lock_dir), false)
            .map_err(adapter)?;
        lock.enter().map_err(adapter)?;
        self.home_lock = Some(lock);
        Ok(())
    }
    fn exit_home_lock(&mut self) {
        if let Some(mut lock) = self.home_lock.take() {
            lock.exit();
        }
    }
    fn wait_for(&mut self, wake: bool, seconds: f64) -> Fired {
        let Some(stop) = self.stop.as_ref() else {
            std::thread::sleep(std::time::Duration::from_secs_f64(seconds.clamp(0.0, 3600.0)));
            return Fired::Timeout;
        };
        if !wake || self.wake.is_none() {
            return if stop.wait(seconds) {
                Fired::Stop
            } else {
                Fired::Timeout
            };
        }
        let handles = [stop.raw(), self.wake.as_ref().and_then(car_platform::sync::WakeEvent::raw)];
        match car_platform::sync::wait_any(&handles, seconds) {
            Some(0) => Fired::Stop,
            Some(1) => Fired::Wake,
            _ => Fired::Timeout,
        }
    }
    fn sleep(&mut self, seconds: f64) {
        std::thread::sleep(std::time::Duration::from_secs_f64(seconds.max(0.0)));
    }
    fn pid(&self) -> u32 {
        std::process::id()
    }
    fn session_id(&mut self) -> String {
        car_machine::hash::hex(&car_control::host::std_random(6))
    }
    fn clock_text(&self, seconds: f64) -> String {
        use car_machine::localclock::LocalClock;
        match car_platform::localclock::Crt.localtime(seconds) {
            Ok(tm) => format!("{:02}:{:02}:{:02}", tm.hour, tm.min, tm.sec),
            Err(_) => "00:00:00".into(),
        }
    }
    fn version(&self) -> String {
        car_config::codex::version(&self.project_root, &mut |_| {})
    }
    fn state_dir(&self) -> String {
        self.paths.state_dir.clone()
    }
    fn edition_badge(&self) -> Option<String> {
        (!self.plug.is_null()).then(|| self.plug.badge().to_owned())
    }
    fn open_store(&mut self) -> Res<(Store, Option<i64>)> {
        let mut options = car_store::Options::new(Arc::new(Probe));
        options.migrate = true;
        options.check = true;
        let store = Store::open_with(Path::new(&self.paths.state_dir), options)?;
        let from = store.migrated_from;
        Ok((store, from))
    }
    fn engine_moved(&mut self) -> bool {
        self.maker.engine_moved()
    }
    fn engine(&mut self, store: &Store) -> Res<Box<dyn TickEngine>> {
        if !self.settings_good {
            self.refresh_settings(None);
            if !self.settings_good {
                return Err(Failed::new("Unreadable", "not read yet"));
            }
        }
        let (values, managed) = (self.stored.clone(), self.managed.clone());
        let engine = self.maker.engine(store, &values, &managed)?;
        // `_observe_only` and `_managed_pause`, as App.engine makes them good before the first tick.
        if let Err(failed) = crate::fail::guarded(|| {
            store.set_observe_only(matches!(
                self.settings.get("observe_only"),
                Some(Value::Bool(true))
            ))?;
            Ok(())
        }) {
            self.record_failure("observe-only switch", &failed);
        }
        self.managed_pause(store);
        Ok(engine)
    }
    fn compatibility_tick(&mut self) {
        self.maker.compatibility_tick();
    }
    fn refresh_settings(&mut self, engine: Option<&mut Box<dyn TickEngine>>) {
        let held = self.host.managed();
        let now = stamp(&self.paths.settings_file);
        if now == self.settings_stamp && held == self.managed {
            return;
        }
        let keys_changed = held != self.managed;
        if keys_changed {
            let codes = held.codes();
            self.info(&format!(
                "administrator's policy keys: {}",
                if codes.is_empty() {
                    "none".to_owned()
                } else {
                    codes.join(", ")
                }
            ));
            self.managed = held.clone();
        }
        if now != self.settings_stamp
            && let Some(stored) = self.read_settings()
        {
            self.settings_stamp = now;
            self.stored = stored;
            self.settings_good = true;
        }
        let values = managed::clamp(&self.stored, &held);
        if values == self.settings && !keys_changed {
            return;
        }
        let previous = self.settings.get("interface_language").cloned();
        self.settings = values;
        if let Some(engine) = engine {
            engine.apply_policy(&Value::Object(self.stored.clone()), &held);
        }
        let settings = Value::Object(self.settings.clone());
        self.events.queue_settings(&settings);
        if self.settings.get("interface_language") != previous.as_ref() && self.tray {
            self.events.queue_strings();
        }
        self.info("settings reloaded");
    }
    fn engine_state(&self) -> String {
        self.maker.engine_state()
    }
    fn managed(&self) -> Managed {
        self.managed.clone()
    }
    fn settings_good(&self) -> bool {
        self.settings_good
    }
    fn failure_baseline(&mut self) {
        if let Err(failure) = self.control().acknowledge_failure(None, true) {
            let failed = Failed::from(failure);
            self.info(&format!("failure baseline not written ({})", failed.class));
        }
    }
    fn sweep_set_aside(&mut self) {
        let lines = std::cell::RefCell::new(Vec::new());
        let log = |line: &str| lines.borrow_mut().push(line.to_owned());
        crate::setaside::sweep(&self.paths, Some(&log), &crate::setaside::ThisMachine);
        for line in lines.into_inner() {
            self.info(&line);
        }
    }
    fn new_health(&mut self) -> Res<Health> {
        Ok(Health::new(
            &self.paths.status_file,
            &self.version(),
            Box::new(crate::health::ThisProcess),
            Box::new(crate::clock::wall),
        ))
    }
    fn new_waking(&mut self) -> Option<Waking> {
        let state_dir = self.paths.state_dir.clone();
        Some(Waking::new(
            Box::new(crate::waking::ThisPower),
            Arc::new(move || {
                if let Ok(wake) = car_platform::sync::WakeEvent::new(&state_dir) {
                    wake.signal();
                }
                Ok(())
            }),
            Box::new(crate::clock::wall),
        ))
    }
    fn new_afterwork(&mut self) -> Res<AfterWork> {
        Ok(AfterWork::new(
            Box::new(self.control()),
            Box::new(crate::afterwork::ThisPowerdown),
            Box::new(crate::clock::wall),
        ))
    }
    fn watcher_notice(&self, event: &str, detail: Map, last: bool) -> Res<()> {
        self.events.queue_watcher_notice(event, detail, last);
        Ok(())
    }
    fn start_tray(&mut self) -> bool {
        if !self
            .settings
            .get("show_tray")
            .is_none_or(car_machine::pyval::truthy)
        {
            return false;
        }
        let icon = if Path::new(&self.paths.icon_file).is_file() {
            self.paths.icon_file.clone()
        } else {
            Path::new(&self.project_root)
                .join("assets")
                .join("codex-auto-resume.ico")
                .to_string_lossy()
                .into_owned()
        };
        let edition = car_policy::plug::edition::shown(&self.plug);
        self.tray = self.events.start_surfaces(
            &icon,
            &Value::Object(self.settings.clone()),
            edition,
            &self.paths.state_dir,
        );
        self.tray
    }
    fn update_tray(&mut self, store: &Store, blocked: bool) {
        let _ = crate::fail::guarded(|| {
            let snapshot = car_surface::tray::model::snapshot_from(&StoreTray(store))
                .map_err(|class| Failed::new(class, ""))?;
            let mut snapshot = match snapshot {
                Value::Object(map) => map,
                _ => Map::new(),
            };
            // P10: what the edition's plug adds to what the icon draws from, under its one key.
            let added = self.plug.surface(
                car_policy::plug::Surface::Tray,
                &Value::Object(snapshot.clone()),
            );
            if let car_policy::plug::Answer::Is(found) = &added {
                snapshot.insert(car_policy::plug::EXTRA.into(), found.clone());
            }
            self.edition_notices(&added)?;
            snapshot.insert("blocked".into(), Value::Bool(blocked));
            self.events.queue_snapshot(Value::Object(snapshot));
            Ok(())
        });
    }
    fn edition_surface(&mut self, store: &Store) {
        let _ = crate::fail::guarded(|| {
            if self.plug.is_null() {
                return Ok(());
            }
            let snapshot = car_surface::tray::model::snapshot_from(&StoreTray(store))
                .map_err(|class| Failed::new(class, ""))?;
            let added = self.plug.surface(car_policy::plug::Surface::Tray, &snapshot);
            self.edition_notices(&added)
        });
    }
    fn stop_tray(&mut self) {
        if self.tray {
            self.events.close_surfaces();
            self.tray = false;
        }
    }
    fn os(&self) -> Arc<dyn Os + Send + Sync> {
        Arc::clone(&self.os)
    }
    fn log_clock(&self) -> &dyn car_config::logbook::Clock {
        &self.clock
    }
    fn app_runs(&mut self) -> Option<bool> {
        None
    }
    fn recovery_facts(
        &mut self,
        store: &Store,
        engine: &mut dyn TickEngine,
    ) -> Res<(Option<bool>, BTreeMap<&'static str, Option<bool>>)> {
        self.maker.recovery_facts(store, engine)
    }
    fn layout(&mut self) -> Res<Value> {
        Ok(car_codex::layout::read(&self.paths.codex_layout_file).unwrap_or(Value::Null))
    }
    fn write_self_check(&mut self, written: &Value) -> Res<()> {
        car_codex::compat::files::write_json_atomic(&self.paths.self_check_file, written, "selfcheck.")
            .map_err(|_| Failed::new("OSError", ""))
    }
}

/// car-store's `Store` as the icon's snapshot reads it (`ui/tray/model.py`'s `store`).
struct StoreTray<'a>(&'a Store);

impl car_surface::seam::TrayStore for StoreTray<'_> {
    fn pending(&self) -> car_machine::pyval::Py<Vec<Value>> {
        Ok(self
            .0
            .pending()
            .map_err(|error| error.class())?
            .into_iter()
            .map(Value::Object)
            .collect())
    }
    fn disabled_threads(&self) -> car_machine::pyval::Py<Vec<Value>> {
        self.0.disabled_threads().map_err(|error| error.class())
    }
    fn settings(&self) -> car_machine::pyval::Py<Value> {
        Ok(Value::Object(self.0.settings().map_err(|error| error.class())?))
    }
    fn failure_marks(&self) -> car_machine::pyval::Py<Value> {
        Ok(Value::Object(self.0.failure_marks().map_err(|error| error.class())?))
    }
}

impl App {
    /// `_edition_notices(added)`: the plug's notices, each shown once in this watcher's life.
    fn edition_notices(&mut self, added: &car_policy::plug::Answer<Value>) -> Res<()> {
        let events = std::sync::Arc::clone(&self.events);
        let mut notice = |event: &str, detail: Map| -> Res<()> {
            events.queue_watcher_notice(event, detail, false);
            Ok(())
        };
        self.notices.edition_notices(added, &mut notice)
    }

    /// `_managed_pause(engine)`: an administrator's DisableAutoResume written into the state as a Pause.
    fn managed_pause(&mut self, store: &Store) {
        if !self.managed.disable_auto_resume {
            return;
        }
        let result = crate::fail::guarded(|| {
            let enabled = store.settings()?.get("enabled").cloned().unwrap_or(Value::Null);
            if car_machine::pyval::truthy(&enabled) {
                store.set_enabled(false, crate::clock::wall())?;
                self.info("auto-resume paused: an administrator's policy key says so (DisableAutoResume)");
            }
            Ok(())
        });
        if let Err(failed) = result {
            self.record_failure("administrator's pause", &failed);
        }
    }
}
