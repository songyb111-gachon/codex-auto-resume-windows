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

use car_control::host::{Boot, Host, PlatformOs, SystemHost};
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
        self.watcher_running
    }

    fn startup_value(&self) -> Option<String> {
        self.startup_value.clone()
    }

    fn boot(&self) -> Boot {
        self.boot.clone()
    }

    fn compat_view(&self, _state_dir: &Path, _settings: &Map) -> Value {
        self.compat_view.clone()
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
    let control = car_control::Control::new(paths, host, Guarded::null());
    let input = match request.get("input") {
        Some(Value::Str(text)) => unhex(text.as_str().unwrap_or_default()),
        _ => Vec::new(),
    };
    let mut output: Vec<u8> = Vec::new();
    let code = match request.get("mode") {
        Some(Value::Str(mode)) if mode.as_str() == Some("serve") => {
            car_control::bridge::serve(&control, &mut input.as_slice(), &mut output)
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
    ])
}
