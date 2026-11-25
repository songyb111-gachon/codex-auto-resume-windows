//! `control/watcher.py`'s acting half: starting the watcher, asking it to stop, and its sign-in entry.
//!
//! A stop is a request and never a kill: the watcher finishes the tick it is in. A start launches what the
//! installer and sign-in launch, through [`Host::launch`](crate::host::Host), and then waits, by the clock, for the
//! single-instance mutex to say whether it came up. Nothing here kills, sends or decides about an interruption.

use std::path::{Path, PathBuf};

use car_machine::json::{Map, Str, Value};

use crate::error::{Failure, Res, refuse};
use crate::host::{Event, Launched, Raised};
use crate::layer::Control;

/// `WATCHER_START_TIMEOUT`: how long a launched watcher is waited for.
pub const WATCHER_START_TIMEOUT: f64 = 45.0;
/// `WATCHER_START_INTERVAL`.
pub const WATCHER_START_INTERVAL: f64 = 0.1;
/// `CHOSEN_ASK_SECONDS`.
pub const CHOSEN_ASK_SECONDS: f64 = 48.0;
/// `INTERPRETER_STARTS_SECONDS`.
pub const INTERPRETER_STARTS_SECONDS: f64 = 15.0;
/// `CHOSEN_START_TIMEOUT`.
pub const CHOSEN_START_TIMEOUT: f64 =
    WATCHER_START_TIMEOUT + CHOSEN_ASK_SECONDS + INTERPRETER_STARTS_SECONDS;
/// `WATCHER_STOP_TIMEOUT`.
pub const WATCHER_STOP_TIMEOUT: f64 = 10.0;
/// `WATCHER_STOP_INTERVAL`.
pub const WATCHER_STOP_INTERVAL: f64 = 0.25;
/// `INSTALLING`: the start's refusal while an installation holds its lock.
pub const INSTALLING: &str =
    "could not start the watcher: an installation is in progress; start it once it has finished";
/// `chosen_runtime.FOLDER` and `RECORD`: where a choice of Python is recorded.
pub const CHOSEN_FOLDER: &str = "runtimes";
pub const CHOSEN_RECORD: &str = "chosen.json";
/// `subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP`.
pub const DETACHED: u32 =
    car_platform::spawn::DETACHED_PROCESS | car_platform::spawn::CREATE_NEW_PROCESS_GROUP;
/// The stable launcher's file name in the installation's home.
pub const LAUNCHER: &str = "watcher-launcher.py";

/// The classes an `except OSError` catches.
pub const OS_ERRORS: &[&str] = &[
    "OSError",
    "FileNotFoundError",
    "FileExistsError",
    "PermissionError",
    "NotADirectoryError",
    "IsADirectoryError",
    "BlockingIOError",
    "ChildProcessError",
    "ConnectionError",
    "InterruptedError",
    "ProcessLookupError",
    "TimeoutError",
];

fn object(pairs: Vec<(&str, Value)>) -> Map {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(Str::from(name), value);
    }
    map
}

/// `start_timeout(home, wait=None)`: how long a start of the watcher of the installation at `home` is waited for.
pub fn start_timeout(home: &Path, wait: Option<f64>) -> f64 {
    let wait = wait.unwrap_or(WATCHER_START_TIMEOUT);
    if home.join(CHOSEN_FOLDER).join(CHOSEN_RECORD).is_file() {
        wait + CHOSEN_ASK_SECONDS + INTERPRETER_STARTS_SECONDS
    } else {
        wait
    }
}

/// `await_watcher(probe, process, timeout=..., interval=...)`: wait, by the clock, for a launched watcher to be real.
pub fn await_watcher(
    control: &Control,
    process: Option<&mut dyn Launched>,
    timeout: f64,
    interval: f64,
) -> Map {
    let host = &*control.host;
    let deadline = host.monotonic() + timeout;
    let mut process = process;
    loop {
        if control.watcher_running() == Some(true) {
            return object(vec![
                ("confirmed", Value::Bool(true)),
                ("state", Value::from("running")),
                ("reason", Value::Null),
            ]);
        }
        if let Some(child) = process.as_deref_mut()
            && child.poll().is_some()
        {
            return object(vec![
                ("confirmed", Value::Bool(false)),
                ("state", Value::from("exited")),
                ("reason", Value::from("exited")),
            ]);
        }
        if host.monotonic() >= deadline {
            return object(vec![
                ("confirmed", Value::Bool(false)),
                ("state", Value::from("unconfirmed")),
                ("reason", Value::from("unconfirmed")),
            ]);
        }
        host.sleep(interval);
    }
}

/// `await_stopped(probe, timeout=..., interval=...)`: wait, by the clock, for a signalled watcher to let go.
pub fn await_stopped(control: &Control, timeout: f64, interval: f64) -> Map {
    let host = &*control.host;
    let deadline = host.monotonic() + timeout;
    loop {
        let answer = control.watcher_running();
        if answer == Some(false) {
            return object(vec![
                ("stopped", Value::Bool(true)),
                ("state", Value::from("stopped")),
                ("reason", Value::Null),
            ]);
        }
        if host.monotonic() >= deadline {
            let state = if answer == Some(true) {
                "still-finishing"
            } else {
                "unknown"
            };
            return object(vec![
                ("stopped", Value::Bool(false)),
                ("state", Value::from(state)),
                ("reason", Value::from(state)),
            ]);
        }
        host.sleep(interval);
    }
}

/// A `StartupError` met as the control layer meets it: the registry layer's own sentence.
fn startup_refused(raised: Raised, code: &str) -> Failure {
    if raised.class == "StartupError" {
        crate::error::ControlError::new(raised.message, code).into()
    } else {
        Failure::Other(raised.class)
    }
}

impl Control {
    pub fn home_dir(&self) -> PathBuf {
        PathBuf::from(&self.paths.home)
    }

    /// `startup.watcher_python(home)`: the installation's bundled windowless runtime, else the one beside this
    /// interpreter (`python_launcher`).
    pub fn watcher_python(&self) -> Result<PathBuf, Raised> {
        match car_platform::startup::bundled_pythonw(&self.home_dir()) {
            Some(bundled) => Ok(bundled),
            None => self.host.python_launcher(),
        }
    }

    /// `set_startup_enabled(enabled)`: the sign-in entry written or, when it is this installation's own, removed.
    pub fn set_startup_enabled(&self, enabled: bool) -> Res<bool> {
        let home = self.home_dir();
        if enabled {
            let launcher = home.join(LAUNCHER);
            let found = launcher.is_file();
            let entry = if found {
                launcher
            } else {
                PathBuf::from(&self.paths.entry_script)
            };
            let python = self
                .watcher_python()
                .map_err(|raised| startup_refused(raised, "request_failed"))?;
            let command = car_platform::startup::command_line(
                &entry,
                if found { None } else { Some(home.as_path()) },
                &python.to_string_lossy(),
                &[],
            );
            self.host
                .startup_install(&command)
                .map_err(|raised| startup_refused(raised, "request_failed"))?;
        } else {
            let value = self
                .host
                .startup_read()
                .map_err(|raised| startup_refused(raised, "request_failed"))?;
            if let Some(value) = value
                && !value.is_empty()
                && car_platform::startup::belongs_to(&value, &self.paths.home)
            {
                self.host
                    .startup_uninstall()
                    .map_err(|raised| startup_refused(raised, "request_failed"))?;
            }
        }
        Ok(self.startup_enabled())
    }

    /// `start_watcher()`: start the watcher if it is not already running, and report what the mutex says.
    pub fn start_watcher(&self) -> Res<Value> {
        if self.watcher_running() == Some(true) {
            return Ok(Value::Object(object(vec![
                ("started", Value::Bool(false)),
                ("confirmed", Value::Bool(true)),
                ("state", Value::from("already-running")),
                ("reason", Value::from("already running")),
            ])));
        }
        if self.host.install_in_progress() != Some(false) {
            return refuse(INSTALLING, "start_failed");
        }
        let mut process = match self.launch_watcher(0, false)? {
            Ok(process) => process,
            Err(raised) => {
                return refuse(
                    format!("could not start the watcher: {}", raised.message),
                    "start_failed",
                );
            }
        };
        let timeout = start_timeout(&self.home_dir(), None);
        let mut result = await_watcher(self, Some(&mut *process), timeout, WATCHER_START_INTERVAL);
        result.insert(Str::from("started"), Value::Bool(true));
        Ok(Value::Object(result))
    }

    /// `_launch_watcher(extra_flags=0, launcher_only=False)`: the watcher started the way the installer and sign-in
    /// start it. The outer `Err` is a refusal or another exception; the inner one the `OSError` Windows raised.
    pub fn launch_watcher(
        &self,
        extra_flags: u32,
        launcher_only: bool,
    ) -> Res<Result<Box<dyn Launched>, Raised>> {
        let home = self.home_dir();
        let launcher = home.join(LAUNCHER);
        let found = launcher.is_file();
        if launcher_only && !found {
            return refuse("the watcher is not installed here", "not_installed");
        }
        let entry = if found {
            launcher.clone()
        } else {
            PathBuf::from(&self.paths.entry_script)
        };
        if !entry.is_file() {
            return refuse("the watcher is not installed here", "not_installed");
        }
        let interpreter = match self.host.python_launcher() {
            Ok(found) => found,
            Err(raised) => return Err(startup_refused(raised, "not_installed")),
        };
        let flags = DETACHED | extra_flags;
        let mut arguments: Vec<String> = vec![interpreter.to_string_lossy().into_owned()];
        arguments.extend(
            car_platform::startup::NO_REMOTE_DEBUG
                .iter()
                .map(|each| (*each).to_owned()),
        );
        arguments.push(entry.to_string_lossy().into_owned());
        if !found {
            arguments.push("--home".into());
            arguments.push(self.paths.home.clone());
            arguments.push("--quiet".into());
        }
        arguments.push("run".into());
        match self.host.launch(&arguments, &home, flags) {
            Ok(process) => Ok(Ok(process)),
            Err(raised) if OS_ERRORS.contains(&raised.class.as_str()) => Ok(Err(raised)),
            Err(raised) => Err(Failure::Other(raised.class)),
        }
    }

    /// `stop_watcher()`: ask a running watcher to stop, and report only what the probe can prove.
    pub fn stop_watcher(&self) -> Res<Value> {
        if self.watcher_running() == Some(false) {
            return Ok(Value::Object(object(vec![
                ("stopped", Value::Bool(false)),
                ("signalled", Value::Bool(false)),
                ("state", Value::from("not-running")),
                ("reason", Value::from("not-running")),
            ])));
        }
        let signalled = self
            .host
            .signal(Event::Stop, &self.state_dir())
            .unwrap_or(false);
        let mut result = await_stopped(self, WATCHER_STOP_TIMEOUT, WATCHER_STOP_INTERVAL);
        result.insert(Str::from("signalled"), Value::Bool(signalled));
        Ok(Value::Object(result))
    }
}
