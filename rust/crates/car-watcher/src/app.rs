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

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::path::Path;
use std::rc::Rc;
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
    /// Told once, as App is made: what the engine and its backend are built from.
    fn bind(&mut self, _bound: crate::join::Bound) {}
    /// `self._codex_exe_override = self._codex_exe_arg or self.settings.get("codex_exe")`, as `engine()` sets it
    /// again once the settings were read, while no backend is held.
    fn refresh_codex_exe(&mut self, _codex_exe: Option<String>) {}
    /// `Engine(store, source, self.backend(), plug=self.plug, ...)` with `apply_policy(values, managed)`.
    fn engine(
        &mut self,
        store: &Rc<Store>,
        values: &Map,
        managed: &Managed,
        plug: Arc<car_policy::plug::Guarded>,
    ) -> Res<Box<dyn TickEngine>>;
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
    ) -> Res<crate::watchloop::RecoveryFacts> {
        Ok((None, BTreeMap::new()))
    }
    fn home_backend(&mut self, _path: &str, _exe: &str) -> Res<Box<dyn HomeBackend>> {
        Err(Failed::new("EngineNotJoined", ""))
    }
    #[allow(clippy::too_many_arguments)]
    fn home_engine(
        &mut self,
        _store: &Rc<Store>,
        _path: &str,
        _exe: &str,
        _key: &str,
        _held: Rc<std::cell::RefCell<Box<dyn HeldLock>>>,
        _values: &Map,
        _managed: &Managed,
    ) -> Res<Box<dyn TickEngine>> {
        Err(Failed::new("EngineNotJoined", ""))
    }
}

/// The standard maker before the integration joins car-engine here: every build refused, typed.
pub struct NotJoined;

impl EngineMaker for NotJoined {
    fn engine(
        &mut self,
        _store: &Rc<Store>,
        _values: &Map,
        _managed: &Managed,
        _plug: Arc<car_policy::plug::Guarded>,
    ) -> Res<Box<dyn TickEngine>> {
        Err(Failed::new(
            "EngineNotJoined",
            "car-engine is joined to the watcher by the integration",
        ))
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
    fn engine_refused(&self, path: &str) -> bool {
        car_platform::realengine::refused(cfg!(test), path)
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
    /// The process's one plug (`api::SharedPlug`): App's Controls hand it on, as `Control(self.paths, plug=self.plug)`.
    pub plug: Arc<car_policy::plug::Guarded>,
    pub host: Arc<dyn car_control::host::Host>,
    pub events: Arc<Events>,
    pub maker: Box<dyn EngineMaker>,
    /// The popup's model, shared with the Watcher (a click, a `strings` event): `surface::new_popup()`.
    pub popup: crate::surface::Popup,
}

/// App: the real world of the loop.
pub struct App {
    pub paths: Paths,
    project_root: String,
    codex_home: String,
    plug: Arc<car_policy::plug::Guarded>,
    host: Arc<dyn car_control::host::Host>,
    events: Arc<Events>,
    maker: Box<dyn EngineMaker>,
    log: crate::join::SharedLog,
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
    /// The Codex home's lock, shared with the engines' `home_lock` question.
    home_lock: Rc<RefCell<Option<car_platform::homelock::HomeLock>>>,
    lock_dir: String,
    tray: bool,
    /// `self.settings`, as the notifier reads it on its own thread at every event.
    shared_settings: Arc<std::sync::Mutex<Map>>,
    notices: crate::plugnotices::PlugNotices,
    popup: crate::surface::Popup,
    /// `_watcher_toasts`, made at the first watcher notice that is not the last one.
    watcher_notices: std::sync::OnceLock<Arc<crate::notices::WatcherNotices>>,
    /// The icon's look at the demo event (`on_demo=self._demo`), while the surfaces are up.
    demo: Option<crate::demo::DemoLook>,
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
        // The engine's transitions are said by their state (logbook.STATE_CODES), in the one log of the watcher.
        let log = crate::join::SharedLog::new(
            car_config::logbook::Logbook::open(
                &start.paths.log_file,
                "",
                car_machine::vocab_gen::domain_states::STATES,
            )
            .with_rename(car_platform::files::rename),
            crate::clock::LogClock::here(),
        );
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
            home_lock: Rc::new(RefCell::new(None)),
            lock_dir: Path::new(&lock_dir)
                .join("codex-auto-resume")
                .join("homes")
                .to_string_lossy()
                .into_owned(),
            tray: false,
            demo: None,
            shared_settings: Arc::new(std::sync::Mutex::new(Map::new())),
            notices: crate::plugnotices::PlugNotices::new(),
            popup: start.popup,
            watcher_notices: std::sync::OnceLock::new(),
        };
        let stored = app.read_settings();
        app.settings_good = stored.is_some();
        if let Some(stored) = stored {
            app.stored = stored;
        }
        app.settings = managed::clamp(&app.stored, &app.managed);
        *app.shared_settings
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = app.settings.clone();
        if app.settings_good {
            app.settings_stamp = stamp(&app.paths.settings_file);
        }
        let held = Rc::clone(&app.home_lock);
        let bound = crate::join::Bound {
            paths: app.paths.clone(),
            project_root: app.project_root.clone(),
            codex_home: app.codex_home.clone(),
            codex_exe: codex_exe_setting(&app.settings),
            host: Arc::clone(&app.host),
            log: app.log.clone(),
            home_lock: Rc::new(move || held.borrow().as_ref().is_some_and(|lock| lock.held())),
            announce: app.announce(),
            plug: Arc::clone(&app.plug),
        };
        app.maker.bind(bound);
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

    pub(crate) fn control(&self) -> car_control::Control {
        car_control::Control::new(
            self.paths.clone(),
            Arc::clone(&self.host),
            Arc::clone(&self.plug),
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
        self.log.info(line);
    }
    fn record_failure(&self, label: &str, failed: &Failed) {
        crate::join::record_failure(&self.log, &self.paths.error_log, label, failed);
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
        self.home_lock
            .borrow()
            .as_ref()
            .and_then(|lock| lock.identity.clone())
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
        store: &Rc<Store>,
        path: &str,
        exe: &str,
        key: &str,
        held: Rc<RefCell<Box<dyn HeldLock>>>,
    ) -> Res<Box<dyn TickEngine>> {
        let (values, managed) = (self.stored.clone(), self.managed.clone());
        self.maker
            .home_engine(store, path, exe, key, held, &values, &managed)
    }
}

/// `time.strftime("[%Y-%m-%d %H:%M:%S] ")` now, in this PC's zone (the error log's stamp).
pub(crate) fn stamp_now() -> String {
    car_watcher_stamp(&crate::clock::LogClock::here())
}

/// `time.strftime("[%Y-%m-%d %H:%M:%S] ")` in this PC's zone.
fn car_watcher_stamp(_clock: &crate::clock::LogClock) -> String {
    use car_machine::localclock::LocalClock;
    let now = crate::clock::wall();
    match car_platform::localclock::Crt.localtime(now.floor()) {
        Ok(tm) => format!(
            "[{:04}-{:02}-{:02} {:02}:{:02}:{:02}] ",
            tm.year, tm.mon, tm.mday, tm.hour, tm.min, tm.sec
        ),
        Err(_) => "[0000-00-00 00:00:00] ".into(),
    }
}

/// `codex_exe or self.settings.get("codex_exe")`: the watcher has no argument; a setting that is text and not empty.
fn codex_exe_setting(settings: &Map) -> Option<String> {
    settings
        .get("codex_exe")
        .and_then(crate::join::text)
        .filter(|found| !found.is_empty())
        .map(str::to_owned)
}

fn adapter(error: car_machine::domain::errors::AdapterError) -> Adapter {
    Adapter(error.0.to_owned())
}

impl World for App {
    fn enter_mutex(&mut self) -> Result<bool, Adapter> {
        let mut mutex =
            car_platform::sync::Mutex::new(&self.paths.state_dir, 0.0).map_err(adapter)?;
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
        let mut stop =
            car_platform::sync::StopEvent::new(&self.paths.state_dir).map_err(adapter)?;
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
        let mut wake =
            car_platform::sync::WakeEvent::new(&self.paths.state_dir).map_err(adapter)?;
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
        let mut lock =
            car_platform::homelock::HomeLock::new(&self.codex_home, Some(&self.lock_dir), false)
                .map_err(adapter)?;
        lock.enter().map_err(adapter)?;
        *self.home_lock.borrow_mut() = Some(lock);
        Ok(())
    }
    fn exit_home_lock(&mut self) {
        let held = self.home_lock.borrow_mut().take();
        if let Some(mut lock) = held {
            lock.exit();
        }
    }
    fn wait_for(&mut self, wake: bool, seconds: f64) -> Fired {
        let Some(stop) = self.stop.as_ref() else {
            std::thread::sleep(std::time::Duration::from_secs_f64(
                seconds.clamp(0.0, 3600.0),
            ));
            return Fired::Timeout;
        };
        if !wake || self.wake.is_none() {
            return if stop.wait(seconds) {
                Fired::Stop
            } else {
                Fired::Timeout
            };
        }
        let handles = [
            stop.raw(),
            self.wake
                .as_ref()
                .and_then(car_platform::sync::WakeEvent::raw),
        ];
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
    fn open_store(&mut self) -> Res<(Rc<Store>, Option<i64>)> {
        let mut options = car_store::Options::new(Arc::new(Probe));
        options.migrate = true;
        options.check = true;
        let store = Store::open_with(Path::new(&self.paths.state_dir), options)?;
        let from = store.migrated_from;
        Ok((Rc::new(store), from))
    }
    fn engine_moved(&mut self) -> bool {
        self.maker.engine_moved()
    }
    fn engine(&mut self, store: &Rc<Store>) -> Res<Box<dyn TickEngine>> {
        if !self.settings_good {
            self.refresh_settings(None);
            if !self.settings_good {
                return Err(Failed::new("Unreadable", "not read yet"));
            }
            self.maker
                .refresh_codex_exe(codex_exe_setting(&self.settings));
        }
        let (values, managed) = (self.stored.clone(), self.managed.clone());
        let engine = self
            .maker
            .engine(store, &values, &managed, Arc::clone(&self.plug))?;
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
        *self
            .shared_settings
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = self.settings.clone();
        if let Some(engine) = engine {
            engine.apply_policy(&Value::Object(self.stored.clone()), &held);
        }
        let settings = Value::Object(self.settings.clone());
        self.events.queue_settings(&settings);
        if self.settings.get("interface_language") != previous.as_ref() && self.tray {
            // `refresh_settings` on a language change, and the snapshot right after it, in those words (DECISIONS.md:
            // the core sends a snapshot right after each `strings` event).
            let catalog = crate::surface::catalog();
            self.events.queue_strings(&catalog);
            let mut popup = crate::surface::held(&self.popup);
            popup.adopt(&catalog);
            if let Some(last) = popup.snapshot.clone() {
                let field = popup.field(crate::clock::wall());
                self.events.queue_snapshot(Value::Object(last), field);
            }
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
        self.watcher_notices()
            .notice(event, detail, last)
            .map(|_| ())
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
        let catalog = crate::surface::catalog();
        crate::surface::held(&self.popup).adopt(&catalog);
        self.tray = self.events.start_surfaces(
            &icon,
            &catalog,
            &Value::Object(self.settings.clone()),
            edition,
            &self.paths.state_dir,
        );
        if self.tray {
            let log = self.log.clone();
            self.demo = Some(crate::demo::DemoLook::start(
                &self.paths.state_dir,
                Arc::clone(&self.events),
                Arc::clone(&self.shared_settings),
                Arc::new(move |line: &str| log.info(line)),
                Arc::new(|| {
                    crate::notices::presence().map_err(|raised| Failed::new(&raised.class, ""))
                }),
            ));
        }
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
            // What the icon asked its control layer, and the popup's read and view (the host computes neither).
            let control = self.control();
            crate::surface::icon_answers(&control, &mut snapshot);
            let now = crate::clock::wall();
            let source = crate::surface::names(&*self.host, &self.paths.split_chains_file);
            let mut popup = crate::surface::held(&self.popup);
            popup.read(
                &crate::surface::ControlPopup {
                    control: &control,
                    source,
                },
                now,
            );
            let field = popup.field(now);
            popup.snapshot = Some(snapshot.clone());
            drop(popup);
            self.events.queue_snapshot(Value::Object(snapshot), field);
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
            let added = self
                .plug
                .surface(car_policy::plug::Surface::Tray, &snapshot);
            self.edition_notices(&added)
        });
    }
    fn stop_tray(&mut self) {
        if let Some(look) = self.demo.take() {
            look.stop();
        }
        if self.tray {
            self.events.close_surfaces();
            self.tray = false;
        }
    }
    fn os(&self) -> Arc<dyn Os + Send + Sync> {
        Arc::clone(&self.os)
    }
    fn log_clock(&self) -> &dyn car_config::logbook::Clock {
        &*self.log.clock
    }
    fn app_runs(&mut self) -> Option<bool> {
        car_codex::pairing::app_running_now(&car_codex::system::Platform::new())
    }
    fn recovery_facts(
        &mut self,
        store: &Store,
        engine: &mut dyn TickEngine,
    ) -> Res<crate::watchloop::RecoveryFacts> {
        self.maker.recovery_facts(store, engine)
    }
    fn layout(&mut self) -> Res<Value> {
        Ok(car_codex::layout::read(&self.paths.codex_layout_file).unwrap_or(Value::Null))
    }
    fn write_self_check(&mut self, written: &Value) -> Res<()> {
        car_codex::compat::files::write_json_atomic(
            &self.paths.self_check_file,
            written,
            "selfcheck.",
        )
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
        Ok(Value::Object(
            self.0.settings().map_err(|error| error.class())?,
        ))
    }
    fn failure_marks(&self) -> car_machine::pyval::Py<Value> {
        Ok(Value::Object(
            self.0.failure_marks().map_err(|error| error.class())?,
        ))
    }
}

impl App {
    /// `_edition_notices(added)`: the plug's notices, each shown once in this watcher's life.
    fn edition_notices(&mut self, added: &car_policy::plug::Answer<Value>) -> Res<()> {
        let notices = self.watcher_notices();
        let mut notice = |event: &str, detail: Map| -> Res<()> {
            notices.notice(event, detail, false).map(|_| ())
        };
        self.notices.edition_notices(added, &mut notice)
    }

    /// `_managed_pause(engine)`: an administrator's DisableAutoResume written into the state as a Pause.
    fn managed_pause(&mut self, store: &Store) {
        if !self.managed.disable_auto_resume {
            return;
        }
        let result = crate::fail::guarded(|| {
            let enabled = store
                .settings()?
                .get("enabled")
                .cloned()
                .unwrap_or(Value::Null);
            if car_machine::pyval::truthy(&enabled) {
                store.set_enabled(false, crate::clock::wall())?;
                self.info(
                    "auto-resume paused: an administrator's policy key says so (DisableAutoResume)",
                );
            }
            Ok(())
        });
        if let Err(failed) = result {
            self.record_failure("administrator's pause", &failed);
        }
    }
}

impl App {
    /// What a notice's route needs: the settings in force, the plug, the state folder and the card inbox.
    fn route(&self) -> crate::notices::Route {
        crate::notices::Route {
            settings: Arc::clone(&self.shared_settings),
            plug: Arc::clone(&self.plug),
            state_dir: self.paths.state_dir.clone(),
            events: Arc::clone(&self.events),
        }
    }

    /// `_watcher_notice`'s queue and route.
    fn watcher_notices(&self) -> Arc<crate::notices::WatcherNotices> {
        Arc::clone(self.watcher_notices.get_or_init(|| {
            let log = self.log.clone();
            Arc::new(crate::notices::WatcherNotices::new(
                self.route(),
                Arc::new(move |line: &str| log.info(line)),
            ))
        }))
    }

    /// `_notifier(source)`'s announce (`App._deliver` included): read from the settings in force on every event, built
    /// into one Notice and shown by exactly one route: the card where the host attached its stack and this PC's
    /// presence probes allow it (`notices::Route::deliver`), else the toast.
    fn announce(&self) -> crate::join::Announce {
        let route = self.route();
        Arc::new(
            move |event: &str, detail: &Map, identity: &dyn Fn() -> Value| {
                let values = route.values();
                let fail = |class: &'static str| Failed::new(class, "");
                if !car_policy::settings::notification_enabled(&values, event).map_err(fail)? {
                    return Ok(false);
                }
                let identity = identity();
                let field = |key: &str| match &values {
                    Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
                    _ => Value::Null,
                };
                let sound = event == car_policy::classify::vocab_gen::needsyou::EVENT
                    && matches!(
                        field(car_policy::classify::vocab_gen::needsyou::SOUND_FIELD),
                        Value::Bool(true)
                    );
                let environ = |name: &str| std::env::var(name).ok();
                let locale = car_words::interface::language(&environ, &Vec::new);
                let clock = car_platform::localclock::Crt;
                let speech = car_surface::speech::Speech::new(locale, &clock);
                let stay = Value::Array(
                    car_policy::settings::notice_kinds::chosen(&values)
                        .into_iter()
                        .map(Value::from)
                        .collect(),
                );
                let built = car_surface::notifier::build(
                    &speech,
                    &Value::from(event),
                    &Value::Object(detail.clone()),
                    &identity,
                    sound,
                    car_surface::notifier::click_destination(&values, false),
                    &stay,
                )
                .map_err(fail)?;
                let Some(built) = built else {
                    return Ok(false);
                };
                let notice = car_surface::notifier::with_open_codex(&built, false).map_err(fail)?;
                let setting = crate::notices::card_setting(&values);
                let shown = route.deliver(&notice, detail, true, &setting)?;
                Ok(shown)
            },
        )
    }
}
