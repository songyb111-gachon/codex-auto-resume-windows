//! `bridge.run`: car-control's bridge, driven as `controlcli` is - `serve` over request lines, or one command
//! per process - over a scratch home and a "world" the request names (S5.1a, `tests/rustdiff/diffs_bridge*.py`).
//!
//! The world is what the reference's golden installation stands in for: the clock, the watcher's mutex, the Run
//! key, the policy keys, the install lock, the Codex home, the compatibility view, the languages. The Python side
//! (`tests/rustdiff/bridgeworld.py`) patches the same answers into the tag's modules; `WorldHost` answers them
//! here and asks the real machine for nothing else a quiet command could not do without.
//!
//! Request: `{"call": "bridge.run", "home": H, "world": {...}, "mode": "serve"|"main", "input": <hex>,
//! "argv": [...]}`. Reply value: `{"output": <text>, "code": n}`.

use std::path::Path;
use std::sync::Arc;

use std::path::PathBuf;

use car_control::host::{Boot, Event, Host, Judge, Launched, PlatformOs, Raised, SystemHost};
use car_machine::json::{Map, Str, Value};
use car_policy::plug::Guarded;
use car_policy::settings::managed::Managed;
use car_policy::settings::os::Os;
use car_store::open::{AdapterError, Windows};

use crate::{object, rejected};

/// The answers a request pins.
pub struct WorldHost {
    inner: SystemHost,
    now: f64,
    codex_home: String,
    version: String,
    watcher_running: Option<bool>,
    startup_value: Option<String>,
    install_in_progress: Option<bool>,
    superseded: bool,
    managed: Managed,
    languages: Vec<String>,
    environ: Vec<(String, String)>,
    state_access: String,
    host_app_default: Value,
    host_app_pids: Map,
    compat_view: Value,
    installed: bool,
    account_codex_home: Option<String>,
    app_homes: Vec<String>,
    boot: Boot,
    /// S5.1b: the acting calls' answers, and the record of the calls made.
    pub acts: Arc<crate::acting::Acts>,
    /// S5.2: what the panel asks of Windows - the text size, the UI font, and which letters each face lacks.
    text_size: Value,
    ui_face: Option<String>,
    lacks: Map,
}

fn text_of(map: &Map, name: &str) -> Option<String> {
    match map.get(name) {
        Some(Value::Str(text)) => text.as_str().map(str::to_owned),
        _ => None,
    }
}

fn number_of(value: Option<&Value>) -> Option<f64> {
    match value {
        Some(Value::Float(x)) => Some(*x),
        Some(Value::Int(int)) => int.as_i64().map(|each| each as f64),
        _ => None,
    }
}

fn tri(map: &Map, name: &str) -> Option<bool> {
    match map.get(name) {
        Some(Value::Bool(on)) => Some(*on),
        _ => None,
    }
}

fn managed_of(map: Option<&Value>) -> Managed {
    let Some(Value::Object(map)) = map else {
        return Managed::default();
    };
    let on = |name: &str| matches!(map.get(name), Some(Value::Bool(true)));
    let quiet_hours = match map.get("quiet_hours") {
        Some(Value::Array(windows)) => windows
            .iter()
            .filter_map(|window| match window {
                Value::Object(each) => Some(each.clone()),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };
    Managed {
        disable_auto_resume: on("disable_auto_resume"),
        force_observe_only: on("force_observe_only"),
        disable_update_check: on("disable_update_check"),
        disable_status_file: on("disable_status_file"),
        max_recovery_attempts: match map.get("max_recovery_attempts") {
            Some(Value::Int(int)) => int.as_i64(),
            _ => None,
        },
        quiet_hours,
        disable_power_action: on("disable_power_action"),
    }
}

impl WorldHost {
    pub fn from_world(world: &Map, project_root: &str) -> WorldHost {
        let strings = |name: &str| match world.get(name) {
            Some(Value::Array(items)) => items
                .iter()
                .filter_map(|each| match each {
                    Value::Str(text) => text.as_str().map(str::to_owned),
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        };
        let environ = match world.get("environ") {
            Some(Value::Object(map)) => map
                .iter()
                .filter_map(|(name, value)| match value {
                    Value::Str(text) => {
                        Some((name.as_str()?.to_owned(), text.as_str()?.to_owned()))
                    }
                    _ => None,
                })
                .collect(),
            _ => Vec::new(),
        };
        let boot = match world.get("boot") {
            Some(Value::Object(map)) => Boot {
                sign_in: text_of(map, "sign_in"),
                booted_at: number_of(map.get("booted_at")),
            },
            _ => Boot::default(),
        };
        let (host_app_default, host_app_pids) = match world.get("host_app") {
            Some(Value::Object(map)) => (
                map.get("default").cloned().unwrap_or(Value::Null),
                match map.get("pids") {
                    Some(Value::Object(pids)) => pids.clone(),
                    _ => Map::new(),
                },
            ),
            _ => (Value::Null, Map::new()),
        };
        WorldHost {
            inner: SystemHost::new(project_root),
            now: number_of(world.get("now")).unwrap_or(0.0),
            codex_home: text_of(world, "codex_home").unwrap_or_default(),
            version: text_of(world, "version").unwrap_or_default(),
            watcher_running: tri(world, "watcher_running"),
            startup_value: text_of(world, "startup_value"),
            install_in_progress: tri(world, "install_in_progress"),
            superseded: matches!(world.get("superseded"), Some(Value::Bool(true))),
            managed: managed_of(world.get("managed")),
            languages: strings("languages"),
            environ,
            state_access: text_of(world, "state_access").unwrap_or_else(|| "unknown".into()),
            host_app_default,
            host_app_pids,
            compat_view: world.get("compat_view").cloned().unwrap_or(Value::Null),
            installed: matches!(world.get("installed"), Some(Value::Bool(true))),
            account_codex_home: text_of(world, "account_codex_home"),
            app_homes: strings("app_homes"),
            boot,
            acts: Arc::new(crate::acting::Acts::from_world(world)),
            text_size: world.get("text_size").cloned().unwrap_or(Value::Float(1.0)),
            ui_face: text_of(world, "ui_face"),
            lacks: match world.get("lacks") {
                Some(Value::Object(map)) => map.clone(),
                _ => Map::new(),
            },
        }
    }
}

impl Windows for WorldHost {
    fn install_in_progress(&self) -> Option<bool> {
        self.install_in_progress
    }

    fn watcher_mutex(&self, state_dir: &Path) -> Result<Box<dyn std::any::Any>, AdapterError> {
        self.inner.watcher_mutex(state_dir)
    }

    fn links(&self) -> Arc<dyn car_store::session::Links> {
        self.inner.links()
    }
}

impl Host for WorldHost {
    fn now(&self) -> f64 {
        self.now
    }

    fn store_clock(&self) -> Option<f64> {
        Some(self.now)
    }

    fn os(&self) -> Arc<dyn Os + Send + Sync> {
        Arc::new(PlatformOs)
    }

    fn version(&self) -> String {
        self.version.clone()
    }

    fn codex_home(&self) -> String {
        self.codex_home.clone()
    }

    fn managed(&self) -> Managed {
        self.managed.clone()
    }

    fn environ(&self, name: &str) -> Option<String> {
        self.environ
            .iter()
            .find(|(each, _)| each == name)
            .map(|(_, value)| value.clone())
    }

    fn windows_languages(&self) -> Vec<String> {
        self.languages.clone()
    }

    fn watcher_running(&self, _state_dir: &Path) -> Option<bool> {
        self.acts.watcher_running(self.watcher_running)
    }

    fn startup_value(&self) -> Option<String> {
        self.startup_value.clone()
    }

    fn boot(&self) -> Boot {
        self.boot.clone()
    }

    fn compat_view(&self, _state_dir: &Path, settings: &Map) -> Value {
        let _ = &self.compat_view;
        self.acts.compat_view(settings)
    }

    fn state_access(&self, _path: &Path) -> String {
        self.state_access.clone()
    }

    fn host_app(&self, pid: Option<u32>, _started_by: Option<f64>) -> Value {
        pid.and_then(|pid| self.host_app_pids.get(pid.to_string().as_str()))
            .cloned()
            .unwrap_or_else(|| self.host_app_default.clone())
    }

    fn installed(&self) -> bool {
        self.installed
    }

    fn account_codex_home(&self) -> Option<String> {
        self.account_codex_home.clone()
    }

    fn app_homes(&self) -> Vec<String> {
        self.app_homes.clone()
    }

    fn edition_name(&self) -> String {
        "standard".to_owned()
    }

    fn superseded(&self) -> bool {
        self.superseded
    }

    fn local_clock(&self) -> Box<dyn car_policy::classify::clock::LocalClock> {
        // The zone the reference's side pins (bridgeworld.py: `time.localtime` is `gmtime`).
        Box::new(car_control::localclock::UtcClock)
    }

    fn is_symlink(&self, path: &Path) -> bool {
        self.inner.is_symlink(path)
    }

    fn file_id(&self, path: &Path) -> Option<u128> {
        self.inner.file_id(path)
    }
    fn read_file(&self, path: &Path) -> std::io::Result<Vec<u8>> {
        self.inner.read_file(path)
    }
    fn open_file(&self, path: &Path) -> std::io::Result<std::fs::File> {
        self.inner.open_file(path)
    }
    fn create_file(&self, path: &Path) -> std::io::Result<std::fs::File> {
        self.inner.create_file(path)
    }
    fn replace(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        self.inner.replace(from, to)
    }
    fn rename(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        self.inner.rename(from, to)
    }
    fn lock(&self, name: &str, timeout: f64) -> Result<Box<dyn std::any::Any>, AdapterError> {
        self.inner.lock(name, timeout)
    }
    fn monotonic(&self) -> f64 {
        self.acts.monotonic()
    }
    fn sleep(&self, seconds: f64) {
        self.acts.sleep(seconds)
    }
    fn signal(&self, event: Event, _state_dir: &Path) -> Result<bool, Raised> {
        self.acts.signal(event)
    }
    fn startup_read(&self) -> Result<Option<String>, Raised> {
        self.acts.startup_read()
    }
    fn startup_install(&self, command: &str) -> Result<bool, Raised> {
        self.acts.startup_install(command)
    }
    fn startup_uninstall(&self) -> Result<bool, Raised> {
        self.acts.startup_uninstall()
    }
    fn protocol_value(&self) -> Result<Option<String>, Raised> {
        self.acts.protocol_value()
    }
    fn notification_identity_owner(&self, home: &str) -> Result<Option<bool>, Raised> {
        self.acts.notification_identity_owner(home)
    }
    fn python_launcher(&self) -> Result<PathBuf, Raised> {
        self.acts.python_launcher()
    }
    fn launch(&self, argv: &[String], cwd: &Path, flags: u32) -> Result<Box<dyn Launched>, Raised> {
        self.acts.launch(argv, cwd, flags)
    }
    fn power_available(&self, action: &str) -> Result<(bool, Option<String>), Raised> {
        self.acts.power_available(action)
    }
    fn internet(&self) -> Result<Option<bool>, Raised> {
        self.acts.internet()
    }
    fn token_hex(&self, count: usize) -> String {
        self.acts.token_hex(count)
    }
    fn token_bytes(&self, count: usize) -> Vec<u8> {
        self.acts.token_bytes(count)
    }
    fn process_context(&self) -> Result<Value, Raised> {
        self.acts.process_context()
    }
    fn pid(&self) -> u32 {
        self.acts.pid()
    }
    fn process_there(&self, pid: u32) -> bool {
        self.acts.process_there(pid)
    }
    fn windows_version(&self) -> Option<String> {
        self.acts.windows_version()
    }
    fn system(&self) -> Value {
        self.acts.system()
    }
    fn compat_live_view(
        &self,
        _state_dir: &Path,
        codex_home: &str,
        explicit: &Value,
    ) -> Result<Value, Raised> {
        self.acts.compat_live_view(codex_home, explicit)
    }
    fn compat_import(
        &self,
        _state_dir: &Path,
        target: &Str,
        origin: &Value,
    ) -> Result<Value, Raised> {
        self.acts.compat_import(target, origin)
    }
    fn compat_refresh(&self, home: &Path) -> Result<Value, Raised> {
        self.acts.compat_refresh(home)
    }
    fn checkup(&self, _home: &Path) -> Result<Value, Raised> {
        self.acts.checkup()
    }
    fn checkup_for_bundle(&self, _home: &Path, key: &[u8]) -> Result<Value, Raised> {
        self.acts.checkup_for_bundle(key)
    }
    fn rescan_judge(&self, _home: &Path) -> Result<Box<dyn Judge>, Raised> {
        self.acts.rescan_judge()
    }
    fn note_turn(&self, _file: &std::fs::File) -> bool {
        self.acts.note_turn()
    }
    fn text_size(&self) -> Value {
        self.text_size.clone()
    }
    fn ui_face(&self) -> Option<String> {
        self.ui_face.clone()
    }
    fn face_lacks(&self, face: &str, text: &str) -> String {
        let lacking = match self.lacks.get(face) {
            Some(Value::Str(letters)) => letters.as_str().unwrap_or_default().to_owned(),
            _ => String::new(),
        };
        text.chars().filter(|c| lacking.contains(*c)).collect()
    }
}

fn unhex(text: &str) -> Vec<u8> {
    (0..text.len() / 2)
        .filter_map(|at| u8::from_str_radix(text.get(at * 2..at * 2 + 2)?, 16).ok())
        .collect()
}

/// `bridge.run`.
pub fn run(home: &Path, request: &Map) -> Value {
    let world = match request.get("world") {
        Some(Value::Object(map)) => map.clone(),
        _ => return rejected("a world is required", "request_failed"),
    };
    // The reference starts a fresh interpreter for every stream, whose Interface-language preference is "system";
    // this process answers every stream, and car-words keeps the preference in a process global a `strings` sets.
    car_words::l10n::set_preference(None, &|_: &str| None, &Vec::new);
    // The reference starts a fresh interpreter for every stream, whose Interface-language preference is "system";
    // this process answers every stream, and car-words keeps the preference in a process global a `strings` sets.
    car_words::l10n::set_preference(None, &|_: &str| None, &Vec::new);
    let host = Arc::new(WorldHost::from_world(&world, &home.to_string_lossy()));
    let links = car_config::Os::here(false, crate::links::for_config());
    let no_env = |_: &str| None;
    let paths = match car_config::Paths::new(
        Some(&home.to_string_lossy()),
        &home.to_string_lossy(),
        &no_env,
        links,
    ) {
        Ok(paths) => paths,
        Err(class) => return rejected(class, "request_failed"),
    };
    let acts = Arc::clone(&host.acts);
    let control = car_control::Control::new(paths, host, Arc::new(Guarded::null()));
    let input = match request.get("input") {
        Some(Value::Str(text)) => unhex(text.as_str().unwrap_or_default()),
        _ => Vec::new(),
    };
    let mut output: Vec<u8> = Vec::new();
    let code = match request.get("mode") {
        Some(Value::Str(mode)) if mode.as_str() == Some("serve") => {
            car_control::bridge::serve(&control, &mut input.as_slice(), &mut output)
        }
        // S5.2: the MCP server's loop over the same control, as `mcpserver.Server(control).serve()`.
        Some(Value::Str(mode)) if mode.as_str() == Some("mcp") => {
            car_control::mcp::Server::new(&control).serve(&mut input.as_slice(), &mut output)
        }
        _ => {
            let argv: Vec<String> = match request.get("argv") {
                Some(Value::Array(items)) => items
                    .iter()
                    .filter_map(|each| match each {
                        Value::Str(text) => text.as_str().map(str::to_owned),
                        _ => None,
                    })
                    .collect(),
                _ => Vec::new(),
            };
            car_control::bridge::one_shot(&control, &argv, &mut input.as_slice(), &mut output)
        }
    };
    object([
        (
            "output",
            Value::Str(Str::from(String::from_utf8_lossy(&output).into_owned())),
        ),
        ("code", Value::from(i64::from(code))),
        ("calls", acts.calls()),
        (
            "power_guard",
            Value::Bool(std::env::var_os("CAR_NO_POWER_ACTION").is_some()),
        ),
    ])
}

/// What a Control method answered, as `control.call` replies it: `{"value": v}`, `{"refusal": [sentence, code]}`
/// for a ControlError, or `{"raised": class}` for any other exception.
fn answered(result: Result<Value, car_control::Failure>) -> Value {
    match result {
        Ok(value) => object([("value", value)]),
        Err(car_control::Failure::Control(error)) => object([(
            "refusal",
            Value::Array(vec![Value::Str(error.message), Value::from(error.code)]),
        )]),
        Err(car_control::Failure::Other(class)) => object([("raised", Value::from(class))]),
    }
}

fn optional_text(value: Option<&str>) -> Value {
    value.map_or(Value::Null, Value::from)
}

/// `control.call`: one Control method no bridge command reaches - the MCP server's start with Codex, the watcher's
/// and a notice's power-action writers, Retry now and Rescan as another actor - over the same world as `bridge.run`.
///
/// Request: `{"call": "control.call", "home": H, "world": {...}, "method": name, "args": [...]}`. Reply value:
/// `{"result": answered, "calls": [...]}`.
pub fn call(home: &Path, request: &Map) -> Value {
    let world = match request.get("world") {
        Some(Value::Object(map)) => map.clone(),
        _ => return rejected("a world is required", "request_failed"),
    };
    let host = Arc::new(WorldHost::from_world(&world, &home.to_string_lossy()));
    let links = car_config::Os::here(false, crate::links::for_config());
    let no_env = |_: &str| None;
    let paths = match car_config::Paths::new(
        Some(&home.to_string_lossy()),
        &home.to_string_lossy(),
        &no_env,
        links,
    ) {
        Ok(paths) => paths,
        Err(class) => return rejected(class, "request_failed"),
    };
    let acts = Arc::clone(&host.acts);
    let control = car_control::Control::new(paths, host, Arc::new(Guarded::null()));
    let args: Vec<Value> = match request.get("args") {
        Some(Value::Array(items)) => items.clone(),
        _ => Vec::new(),
    };
    let arg = |index: usize| args.get(index).cloned().unwrap_or(Value::Null);
    let word = |index: usize| match args.get(index) {
        Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    };
    let number = |index: usize| number_of(args.get(index));
    let method = match request.get("method") {
        Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    };
    let result: Result<Value, car_control::Failure> = match method.as_str() {
        "start_for_codex" => Ok(Value::from(
            control.start_for_codex(number(0).unwrap_or(0.0)),
        )),
        "launch_ends_with_job" => Ok(control
            .launch_ends_with_job()
            .map_or(Value::Null, Value::Bool)),
        "stop_power_countdown" => control
            .stop_power_countdown(&arg(0), &word(1))
            .map(Value::from),
        "power_batch_end" => Ok(Value::Bool(control.power_batch_end(
            &arg(0),
            &arg(1),
            number(2),
        ))),
        "power_batch_finish" => Ok(optional_text(
            control.power_batch_finish(&arg(0), number(1)),
        )),
        "power_refused" => Ok(Value::Bool(control.power_refused(number(0)))),
        "power_show" => Ok(Value::Bool(control.power_show(&arg(0), &arg(1), number(2)))),
        "disarm_power_action" => control.disarm_power_action(&word(0)),
        "arm_power_action" => {
            control.arm_power_action(&arg(0), &word(1), matches!(arg(2), Value::Bool(true)))
        }
        "request_retry_now" => control.request_retry_now(&arg(0), &word(1)),
        "rescan" => control.rescan(&word(0), matches!(arg(1), Value::Bool(true))),
        "cancel_interruption" => control.cancel_interruption(&arg(0), &word(1)),
        "cancel_all_pending" => control.cancel_all_pending(&word(0)),
        "clear_history" => control.clear_history(&word(0)),
        "own_report" => control.own_report(),
        _ => return rejected("no such method", "request_failed"),
    };
    object([("result", answered(result)), ("calls", acts.calls())])
}
