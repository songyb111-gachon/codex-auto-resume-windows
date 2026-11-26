//! The `Watcher` API car-host's exports drive (S6.2b; P6-DESIGN 1.2, 1.5): start, stop, next_event, post_action,
//! bridge. Nothing here is an export: car-host's `abi.rs` holds the six and their wire (the contracts), and maps each
//! of these calls onto them.
//!
//! * `start(request, factory)`: `{"argv": [...], "home": ..., "image": ...}`. The launcher's logic
//!   (`launcher::guarded`) runs on a thread of its own, every panic caught (D15); its watcher is the watch loop over
//!   [`App`](crate::app::App), in this process; `ended {exit_code}` is queued last, always.
//! * `stop()`: the in-process stop - `StopEvent(state_dir).signal()`, what the icon's Stop item does.
//! * `next_event(timeout)`: the next of the event table's events (`events::Events`).
//! * `post_action(action)`: the closed action table; the actors are the reference's (`toast`, `tray`).
//! * `bridge(line)`: one `bridge serve` request answered in process by car-control, the same bytes.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};
use std::time::Duration;

use car_machine::json::{Map, Value};
use car_policy::plug::Guarded;

use crate::app::{App, EngineMaker, NotJoined, Start};
use crate::events::Events;
use crate::launcher::{Child, LauncherWorld};

/// How an edition's plug is made (the standard edition's: `Guarded::null`).
pub type Factory = fn() -> Guarded;

/// `edition.plug(paths)`: this process's plug, made the first time a part of the watcher asks for it and the same
/// object every time after - the launcher's P13 questions, App (the engine's, the icon's and the cards' control
/// layer), the icon's actions and the bridge all hold this one, so what a plug keeps is seen by every part.
pub struct SharedPlug {
    factory: Factory,
    made: OnceLock<Arc<Guarded>>,
}

impl SharedPlug {
    pub fn new(factory: Factory) -> SharedPlug {
        SharedPlug {
            factory,
            made: OnceLock::new(),
        }
    }

    /// The one plug, made now if no part asked before.
    pub fn get(&self) -> Arc<Guarded> {
        Arc::clone(self.made.get_or_init(|| Arc::new((self.factory)())))
    }
}

/// What a request could not be started with (car-host answers it in its own words).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Refused {
    BadRequest,
    AlreadyStarted,
}

/// One watcher process's core.
pub struct Watcher {
    events: Arc<Events>,
    state: Arc<Mutex<Option<String>>>,
    home: Option<String>,
    project_root: String,
    plug: Arc<SharedPlug>,
    thread: Mutex<Option<std::thread::JoinHandle<()>>>,
}

fn texts(value: &Value) -> Option<Vec<String>> {
    match value {
        Value::Array(items) => items
            .iter()
            .map(|each| match each {
                Value::Str(text) => text.as_str().map(str::to_owned),
                _ => None,
            })
            .collect(),
        _ => None,
    }
}

/// The real launcher world: this process, its folder, the edition's plug, car-platform's one starter.
struct SystemLauncher {
    here: PathBuf,
    image: PathBuf,
    project_root: String,
    plug: Arc<SharedPlug>,
    events: Arc<Events>,
    state: Arc<Mutex<Option<String>>>,
    maker: Option<Box<dyn FnOnce() -> Box<dyn EngineMaker> + Send>>,
}

struct Process(std::process::Child);

impl Child for Process {
    fn pid(&self) -> u32 {
        self.0.id()
    }
    fn wait(&mut self) -> i32 {
        self.0
            .wait()
            .ok()
            .and_then(|status| status.code())
            .unwrap_or(crate::watchloop::EXIT_ERROR)
    }
}

fn home_paths(home: &Path, project_root: &str) -> Option<car_config::Paths> {
    crate::app::paths(Some(&home.to_string_lossy()), project_root).ok()
}

impl LauncherWorld for SystemLauncher {
    fn here(&self) -> PathBuf {
        self.here.clone()
    }
    fn pid(&self) -> u32 {
        std::process::id()
    }
    fn env(&self, name: &str) -> Option<String> {
        std::env::var(name).ok()
    }
    fn take_env(&mut self, name: &str) -> Option<String> {
        let found = std::env::var(name).ok();
        // SAFETY of the call: the launcher's own thread reads and writes the environment before any watcher runs.
        unsafe { std::env::remove_var(name) };
        found
    }
    fn sleep(&mut self, seconds: f64) {
        std::thread::sleep(Duration::from_secs_f64(seconds.max(0.0)));
    }
    fn monotonic(&mut self) -> f64 {
        crate::clock::monotonic()
    }
    fn stamp(&self) -> String {
        use car_machine::localclock::LocalClock;
        match car_platform::localclock::Crt.localtime(crate::clock::wall().floor()) {
            Ok(tm) => format!(
                "[{:04}-{:02}-{:02} {:02}:{:02}:{:02}] ",
                tm.year, tm.mon, tm.mday, tm.hour, tm.min, tm.sec
            ),
            Err(_) => "[0000-00-00 00:00:00] ".into(),
        }
    }
    /// The alpha's reading of `_usable`: a copy that carries the host (`app\bin\CodexAutoResume.exe`).
    fn usable(&self, root: &Path) -> bool {
        root.join("bin").join("CodexAutoResume.exe").is_file()
    }
    fn codex_home(&self) -> PathBuf {
        match std::env::var("CODEX_HOME")
            .ok()
            .filter(|found| !found.is_empty())
        {
            Some(found) => PathBuf::from(
                car_machine::winpath::expanduser(&found, &|name: &str| std::env::var(name).ok())
                    .unwrap_or(found),
            ),
            None => PathBuf::from(std::env::var("USERPROFILE").unwrap_or_default()).join(".codex"),
        }
    }
    fn supervise(&mut self, _home: &Path, facts: &Value) -> Option<String> {
        match self.plug.get().supervise(facts) {
            car_policy::plug::Answer::Is(word) => Some(word.as_str().to_owned()),
            car_policy::plug::Answer::Defer => None,
        }
    }
    fn plug_is_null(&mut self, _home: &Path) -> bool {
        self.plug.get().is_null()
    }
    fn supervise_held(&mut self, _home: &Path) -> Value {
        self.plug.get().supervise_held()
    }
    fn ended_cleanly(&mut self, home: &Path) -> Option<bool> {
        let paths = home_paths(home, &self.project_root)?;
        let state = Path::new(&paths.state_dir);
        if !state.join("state.sqlite").is_file() {
            return None;
        }
        let mut options = car_store::Options::new(Arc::new(crate::app::Probe));
        options.check = false;
        let mut store = car_store::Store::open_with(state, options).ok()?;
        let status = store.watcher_status().ok().flatten();
        store.close();
        match status.and_then(|row| row.get("end_mark").cloned()) {
            Some(Value::Str(mark)) if matches!(mark.as_str(), Some("clean" | "memory_guard")) => {
                Some(true)
            }
            Some(Value::Str(mark)) if mark.as_str() == Some("running") => Some(false),
            _ => None,
        }
    }
    fn probe_available(&mut self, home: &Path) -> bool {
        home_paths(home, &self.project_root).is_some()
    }
    fn watcher_running(&mut self, home: &Path) -> Option<bool> {
        App::watcher_running(&home_paths(home, &self.project_root)?.state_dir)
    }
    fn run_watcher(&mut self, home: &Path, command: &[String]) -> i32 {
        if command != ["run"] {
            // The host runs the watcher; every other command is the console core's (`codex-auto-resume.exe`).
            return crate::watchloop::EXIT_ERROR;
        }
        let Some(paths) = home_paths(home, &self.project_root) else {
            return crate::watchloop::EXIT_ERROR;
        };
        *self.state.lock().unwrap_or_else(PoisonError::into_inner) = Some(paths.state_dir.clone());
        let host = Arc::new(car_control::host::SystemHost::new(&self.project_root));
        let codex_home = car_control::host::Host::codex_home(&*host);
        let maker = self.maker.take().map_or_else(
            || Box::new(NotJoined) as Box<dyn EngineMaker>,
            |make| make(),
        );
        let mut app = App::new(Start {
            paths,
            project_root: self.project_root.clone(),
            codex_home,
            plug: self.plug.get(),
            host,
            events: Arc::clone(&self.events),
            maker,
        });
        let mut state = crate::watchloop::Loop::new();
        crate::watchloop::run(&mut app, &mut state, false, None)
    }
    fn child_program(&self) -> Option<PathBuf> {
        self.image.is_file().then(|| self.image.clone())
    }
    fn start_child(&mut self, arguments: &[String]) -> Result<Box<dyn Child>, String> {
        let spawn = car_platform::spawn::Spawn::new(arguments.iter().cloned()).with_streams(
            car_platform::spawn::Stream::Null,
            car_platform::spawn::Stream::Null,
            car_platform::spawn::Stream::Null,
        );
        car_platform::spawn::SystemStarter
            .start(&spawn)
            .map(|child| Box::new(Process(child)) as Box<dyn Child>)
            .map_err(|error| error.to_string())
    }
    fn relaunch(&mut self, arguments: &[String]) -> Result<(), String> {
        let mut env: Vec<(std::ffi::OsString, std::ffi::OsString)> = std::env::vars_os().collect();
        env.push((crate::launcher::RELAUNCH_MARK.into(), "1".into()));
        let spawn = car_platform::spawn::Spawn::new(arguments.iter().cloned())
            .with_env(env)
            .with_flags(
                car_platform::spawn::DETACHED_PROCESS
                    | car_platform::spawn::CREATE_NEW_PROCESS_GROUP,
            )
            .with_streams(
                car_platform::spawn::Stream::Null,
                car_platform::spawn::Stream::Null,
                car_platform::spawn::Stream::Null,
            );
        car_platform::spawn::SystemStarter
            .start(&spawn)
            .map(|_| ())
            .map_err(|error| error.to_string())
    }
}

impl Watcher {
    /// `car_start`'s request read: `argv` a list of texts (required), `home` a text or absent, `image` the host's own
    /// path. The launcher runs on its own thread; this returns once it is started.
    pub fn start(
        request: &Value,
        factory: Factory,
        project_root: &str,
    ) -> Result<Watcher, Refused> {
        Watcher::start_with(request, factory, project_root, None)
    }

    /// The same, with the engine maker the integration joins (S6.2b).
    pub fn start_with(
        request: &Value,
        factory: Factory,
        project_root: &str,
        maker: Option<Box<dyn FnOnce() -> Box<dyn EngineMaker> + Send>>,
    ) -> Result<Watcher, Refused> {
        let Value::Object(map) = request else {
            return Err(Refused::BadRequest);
        };
        let argv = map.get("argv").and_then(texts).ok_or(Refused::BadRequest)?;
        let image = match map.get("image") {
            Some(Value::Str(text)) => PathBuf::from(text.as_str().unwrap_or_default()),
            _ => std::env::current_exe().unwrap_or_default(),
        };
        let home = match map.get("home") {
            Some(Value::Str(text)) => text.as_str().map(str::to_owned),
            _ => None,
        };
        // `--home <home> run` (car-legacy's form) names the home; the launcher's folder is that home, as the Python
        // launcher's folder is the installation root it was copied to.
        let (argv, home) = match argv.as_slice() {
            [flag, named, rest @ ..] if flag == "--home" => (rest.to_vec(), Some(named.clone())),
            _ => (argv, home),
        };
        let here = match &home {
            Some(home) => PathBuf::from(home),
            None => image
                .parent()
                .and_then(Path::parent)
                .and_then(Path::parent)
                .map(Path::to_path_buf)
                .unwrap_or_default(),
        };
        let events = Arc::new(Events::new());
        let state = Arc::new(Mutex::new(None));
        let plug = Arc::new(SharedPlug::new(factory));
        let mut world = SystemLauncher {
            here,
            image,
            project_root: project_root.to_owned(),
            plug: Arc::clone(&plug),
            events: Arc::clone(&events),
            state: Arc::clone(&state),
            maker,
        };
        let ended = Arc::clone(&events);
        // The watcher reads the state, the settings and Codex's lines: a deep stack (car-machine `stack`).
        let thread = car_machine::stack::try_spawn_deep("watcher", move || {
            let code = car_machine::caught::catch(std::panic::AssertUnwindSafe(|| {
                crate::launcher::guarded(&mut world, &argv)
            }))
            .unwrap_or(crate::watchloop::EXIT_ERROR);
            ended.end(code);
        })
        .map_err(|_| Refused::BadRequest)?;
        Ok(Watcher {
            events,
            state,
            home,
            project_root: project_root.to_owned(),
            plug,
            thread: Mutex::new(Some(thread)),
        })
    }

    /// `car_stop`: the stop event signalled, as the icon's Stop item does; 0 when nothing ran to be stopped.
    pub fn stop(&self) -> i32 {
        let state = self
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone();
        match state {
            Some(state_dir) => match car_platform::sync::StopEvent::new(&state_dir) {
                Ok(stop) => i32::from(stop.signal()),
                Err(_) => 0,
            },
            None => 0,
        }
    }

    /// `car_next_event(timeout)`.
    pub fn next_event(&self, timeout: Duration) -> Option<Value> {
        self.events.next(timeout)
    }

    /// The host's answers to the two waits and the card stack's attachment (`tray_started`, `closed`,
    /// `cards_attached`, `cards_detached`); `toggle`, `stop` and `disarm_power` through the control layer with the
    /// reference's actors. Every other action of the table is the surfaces' (S6.2b, S6.3): `not_ported` until then.
    pub fn post_action(&self, action: &str, fields: &Map) -> Value {
        let answer = |ok: bool| {
            let mut map = Map::new();
            map.insert("ok".into(), Value::Bool(ok));
            Value::Object(map)
        };
        match action {
            "tray_started" => {
                self.events.tray_started(true);
                answer(true)
            }
            "closed" => {
                self.events.closed();
                answer(true)
            }
            "cards_attached" => {
                self.events.cards(true);
                answer(true)
            }
            "cards_detached" => {
                self.events.cards(false);
                answer(true)
            }
            "stop" => answer(
                self.stop() != 0
                    || self
                        .state
                        .lock()
                        .unwrap_or_else(PoisonError::into_inner)
                        .is_some(),
            ),
            "toggle" | "disarm_power" => match self.control() {
                Some(control) => {
                    let done = if action == "toggle" {
                        let paused = fields.get("paused").is_some_and(car_machine::pyval::truthy);
                        control.set_enabled(paused).is_ok()
                    } else {
                        control.disarm_power_action("tray").is_ok()
                    };
                    answer(done)
                }
                None => answer(false),
            },
            _ => {
                let mut map = Map::new();
                map.insert("ok".into(), Value::Bool(false));
                map.insert("error".into(), Value::from("not_ported"));
                Value::Object(map)
            }
        }
    }

    /// The control layer bound to the watcher's home, once the watcher runs.
    fn control(&self) -> Option<car_control::Control> {
        let state = self
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()?;
        let home = Path::new(&state).parent()?.to_string_lossy().into_owned();
        let paths = crate::app::paths(Some(&home), &self.project_root).ok()?;
        Some(car_control::Control::new(
            paths,
            Arc::new(car_control::host::SystemHost::new(&self.project_root)),
            self.plug.get(),
        ))
    }

    /// `car_bridge`: one `bridge serve` request, its reply bytes as `bridge serve` writes them.
    pub fn bridge(&self, line: &[u8]) -> Vec<u8> {
        let home = self.home.clone().or_else(|| {
            let state = self
                .state
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .clone()?;
            Some(Path::new(&state).parent()?.to_string_lossy().into_owned())
        });
        let Ok(paths) = crate::app::paths(home.as_deref(), &self.project_root) else {
            return Vec::new();
        };
        let control = car_control::Control::new(
            paths,
            Arc::new(car_control::host::SystemHost::new(&self.project_root)),
            self.plug.get(),
        );
        let mut input: &[u8] = line;
        let mut output = Vec::new();
        car_control::bridge::serve(&control, &mut input, &mut output);
        output
    }

    /// Whether `ended` has been queued.
    pub fn ended(&self) -> bool {
        self.events.is_ended()
    }

    /// Wait for the launcher's thread (after `ended`).
    pub fn join(&self) {
        if let Some(thread) = self
            .thread
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take()
        {
            let _ = thread.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_policy::plug::{HookFailed, Plug};
    use std::sync::atomic::{AtomicI64, Ordering};

    /// A plug with state of its own: each `supervise_held` answers how many times this one plug object was asked.
    struct Counting(AtomicI64);

    impl Plug for Counting {
        fn supervise_held(&self) -> Result<Value, HookFailed> {
            Ok(Value::Int(
                (self.0.fetch_add(1, Ordering::SeqCst) + 1).into(),
            ))
        }
    }

    fn counting() -> Guarded {
        Guarded::new(Box::new(Counting(AtomicI64::new(0))))
    }

    fn count(asked: i64) -> Value {
        Value::Int(asked.into())
    }

    /// `edition.plug(paths)` is the same object every time after the first: the launcher's P13 question, each of
    /// App's Controls (`Control(self.paths, plug=self.plug)`) and the icon's control layer ask one plug, so a plug's
    /// state is seen by every Control. A fresh plug per Control would answer 1 each time.
    #[test]
    fn every_control_of_one_watcher_sees_the_one_plugs_state() {
        let base =
            std::env::temp_dir().join(format!("car-watcher-sharedplug-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        let home = base.join("home");
        std::fs::create_dir_all(&home).expect("scratch home");
        let home_text = home.to_string_lossy().into_owned();
        let project_root = base.join("app").to_string_lossy().into_owned();
        let paths = crate::app::paths(Some(&home_text), &project_root).expect("paths");
        let plug = Arc::new(SharedPlug::new(counting));
        let events = Arc::new(Events::new());
        let state = Arc::new(Mutex::new(Some(paths.state_dir.clone())));
        let mut launcher = SystemLauncher {
            here: home.clone(),
            image: PathBuf::new(),
            project_root: project_root.clone(),
            plug: Arc::clone(&plug),
            events: Arc::clone(&events),
            state: Arc::clone(&state),
            maker: None,
        };
        let watcher = Watcher {
            events: Arc::clone(&events),
            state,
            home: Some(home_text.clone()),
            project_root: project_root.clone(),
            plug: Arc::clone(&plug),
            thread: Mutex::new(None),
        };
        let app = App::new(Start {
            paths,
            project_root: project_root.clone(),
            codex_home: base.join("codex").to_string_lossy().into_owned(),
            plug: plug.get(),
            host: Arc::new(car_control::host::SystemHost::new(&project_root)),
            events,
            maker: Box::new(NotJoined),
        });
        assert_eq!(launcher.supervise_held(&home), count(1));
        assert_eq!(app.control().plug().supervise_held(), count(2));
        assert_eq!(app.control().plug().supervise_held(), count(3));
        let icon = watcher.control().expect("the watcher's home");
        assert_eq!(icon.plug().supervise_held(), count(4));
        assert_eq!(launcher.supervise_held(&home), count(5));
        drop(app);
        let _ = std::fs::remove_dir_all(&base);
    }
}
