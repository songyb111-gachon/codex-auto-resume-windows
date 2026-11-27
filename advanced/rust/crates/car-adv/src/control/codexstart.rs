//! `control/codexstart.py` (seat S7.3a2): Start-with-Codex through WMI, the advanced edition's route at P9.
//!
//! Codex runs each plugin's MCP server inside a job object with KILL_ON_JOB_CLOSE and no breakaway (measured, MW), so
//! a watcher the server starts plainly dies with it. This capability's route asks WMI's Win32_Process.Create to start
//! the watcher, whose parent becomes WmiPrvSE - outside the job. Core builds the command line and calls [`Route::start`]
//! once; this runs one constant PowerShell script through car-platform's `pwsh` (values in environment variables,
//! PowerShell by its System32 path, CREATE_NO_WINDOW) and reads back the created watcher's pid. Nothing here builds a
//! command line, sends, claims or touches a setting. What core made of the route is `told` (car-policy's
//! `StartRoute::told`, which car-control's start for Codex calls), written to the journal as the capability's own code.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

use car_config::Paths;
use car_machine::json::{Int, Map, Str, Value};
use car_policy::plug::StartRoute;

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};

/// The WMI create, as a constant `pwsh.run` script (the tag's `_WMI_CREATE`, byte for byte).
pub const WMI_CREATE: &str = r"
$cmd = $env:CODEX_AUTO_RESUME_ARG_WMI_COMMAND
$pidfile = $env:CODEX_AUTO_RESUME_ARG_WMI_PIDFILE
$startup = New-CimInstance -Namespace root/cimv2 -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
$r = Invoke-CimMethod -Namespace root/cimv2 -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; ProcessStartupInformation = $startup }
if ($null -eq $r) { exit 4 }
if ($r.ReturnValue -ne 0) { exit (100 + [int]$r.ReturnValue) }
[System.IO.File]::WriteAllText($pidfile, [string]$r.ProcessId)
exit 0
";
pub const TIMEOUT_SECONDS: f64 = 30.0;

#[derive(Default)]
struct Inner {
    binding: Option<Binding>,
    acted: Option<Box<dyn FnOnce() + Send>>,
}

/// How the route runs PowerShell (`pwsh.run`'s shape): the exit code, or why there was none.
pub type Runner = Arc<
    dyn Fn(&str, &[(&str, Option<&str>)], Duration) -> Result<i32, car_platform::pwsh::RunError>
        + Send
        + Sync,
>;

/// `StartWithCodex(paths)`: the capability's code.
pub struct StartWithCodex {
    pub paths: Paths,
    inner: Arc<Mutex<Inner>>,
    runner: Runner,
    available: Arc<dyn Fn() -> bool + Send + Sync>,
}

/// The route core carries out at P9: this capability's object, as the reference hands back `self`.
pub struct Route {
    inner: Arc<Mutex<Inner>>,
    runner: Runner,
    available: Arc<dyn Fn() -> bool + Send + Sync>,
}

fn lock(inner: &Mutex<Inner>) -> std::sync::MutexGuard<'_, Inner> {
    inner.lock().unwrap_or_else(PoisonError::into_inner)
}

fn code(value: Value) -> Value {
    let mut map = Map::new();
    map.insert(Str::new("code"), value);
    Value::Object(map)
}

fn word(text: &str) -> Value {
    Value::Str(Str::new(text))
}

/// An OSError's class as Python names it.
fn os_class(error: &std::io::Error) -> &'static str {
    match error.kind() {
        std::io::ErrorKind::NotFound => "FileNotFoundError",
        std::io::ErrorKind::PermissionDenied => "PermissionError",
        std::io::ErrorKind::AlreadyExists => "FileExistsError",
        std::io::ErrorKind::IsADirectory => "IsADirectoryError",
        _ => "OSError",
    }
}

/// `tempfile.mkstemp(prefix="car-swc-")`: a new empty file in the temporary folder.
fn mkstemp() -> Result<PathBuf, std::io::Error> {
    let folder = std::env::temp_dir();
    let mut last = None;
    for _ in 0..100 {
        let name = format!(
            "car-swc-{}",
            car_platform::random::token_hex(4).map_err(|_| std::io::Error::other("no random"))?
        );
        let path = folder.join(name);
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(_) => return Ok(path),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => last = Some(error),
            Err(error) => return Err(error),
        }
    }
    Err(last.unwrap_or_else(|| std::io::Error::from(std::io::ErrorKind::AlreadyExists)))
}

impl Route {
    /// `start(command)`: the WMI create for `command`, and the created pid or why it failed. Never raises.
    pub fn run(&self, command: &str) -> Value {
        if !(self.available)() {
            return code(word("no_powershell"));
        }
        let pidfile = match mkstemp() {
            Ok(path) => path,
            Err(error) => return code(word(os_class(&error))),
        };
        let found = self.create(command, &pidfile);
        let _ = std::fs::remove_file(&pidfile);
        found
    }

    fn create(&self, command: &str, pidfile: &Path) -> Value {
        use car_platform::pwsh::RunError;
        use car_platform::spawn::SpawnError;
        let file = pidfile.to_string_lossy().into_owned();
        let ran = (self.runner)(
            WMI_CREATE,
            &[("WMI_COMMAND", Some(command)), ("WMI_PIDFILE", Some(&file))],
            Duration::from_secs_f64(TIMEOUT_SECONDS),
        );
        let exit = match ran {
            Ok(exit) => exit,
            Err(RunError::Spawn(SpawnError::Timeout)) => {
                let mut map = Map::new();
                map.insert(Str::new("uncertain"), word("timeout"));
                return Value::Object(map);
            }
            Err(RunError::Spawn(SpawnError::Os(error))) => return code(word(os_class(&error))),
            Err(RunError::PowerShell(_)) => return code(word("PowerShellError")),
        };
        if exit != 0 {
            return code(Value::Int(Int::from(i64::from(exit))));
        }
        let pid = std::fs::read(pidfile)
            .ok()
            .and_then(|bytes| String::from_utf8(bytes).ok())
            .and_then(|text| python_int(&text));
        match pid {
            Some(pid) => {
                let mut map = Map::new();
                map.insert(Str::new("pid"), Value::Int(Int::from(pid)));
                Value::Object(map)
            }
            None => code(word("no_pid")),
        }
    }

    /// `told(word)`: what core made of the route, written to the journal as the capability's own code - `running`
    /// sampled by the day with no line; a word it has no code for is not written. Never raises.
    pub fn told(&self, said: &Value) {
        let acted = lock(&self.inner).acted.take();
        let Value::Str(text) = said else {
            return;
        };
        {
            let inner = lock(&self.inner);
            let Some(binding) = inner.binding.as_ref() else {
                return;
            };
            if text.as_str() == Some("running") {
                let _ = binding.with(|scoped| scoped.sample(said));
                return;
            }
        }
        if let Some(acted) = acted {
            acted();
        }
        let inner = lock(&self.inner);
        if let Some(binding) = inner.binding.as_ref() {
            let _ = binding.with(|scoped| scoped.count(said));
        }
    }
}

/// `int(text.strip())` of a pid file: an optional sign, digits (underscores between them), whitespace around.
fn python_int(text: &str) -> Option<i64> {
    let trimmed = text.trim();
    let (sign, digits) = match trimmed.strip_prefix('-') {
        Some(rest) => (-1, rest),
        None => (1, trimmed.strip_prefix('+').unwrap_or(trimmed)),
    };
    if digits.is_empty()
        || digits.starts_with('_')
        || digits.ends_with('_')
        || digits.contains("__")
        || !digits.chars().all(|c| c.is_ascii_digit() || c == '_')
    {
        return None;
    }
    digits
        .replace('_', "")
        .parse::<i64>()
        .ok()
        .map(|n| sign * n)
}

impl StartRoute for Route {
    fn start(&self, command: &[String]) -> Value {
        self.run(&command.join(" "))
    }

    /// Core's `_tell` (car-control `codexstart::tell`, Integration 12): the word core made of this route.
    fn told(&self, word: &str) {
        Route::told(self, &Value::Str(Str::new(word)));
    }
}

impl StartWithCodex {
    /// `StartWithCodex(paths)` with car-platform's PowerShell.
    pub fn new(paths: Paths) -> StartWithCodex {
        StartWithCodex::with(
            paths,
            Arc::new(|script, values, timeout| {
                car_platform::pwsh::run(
                    &car_platform::spawn::SystemStarter,
                    script,
                    values,
                    timeout,
                )
            }),
            Arc::new(|| car_platform::pwsh::executable().is_some()),
        )
    }

    /// The code with a runner of a test's own (no test starts a real process or reaches WMI).
    pub fn with(
        paths: Paths,
        runner: Runner,
        available: Arc<dyn Fn() -> bool + Send + Sync>,
    ) -> StartWithCodex {
        StartWithCodex {
            paths,
            inner: Arc::new(Mutex::new(Inner::default())),
            runner,
            available,
        }
    }

    /// The route this code names (`self`).
    pub fn route(&self) -> Route {
        Route {
            inner: Arc::clone(&self.inner),
            runner: Arc::clone(&self.runner),
            available: Arc::clone(&self.available),
        }
    }
}

impl Code for StartWithCodex {
    fn start_route(&mut self, _request: &Value) -> Spoke {
        Ok(Said::StartRoute(Box::new(self.route())))
    }

    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        lock(&self.inner).binding = Some(binding);
        Some(Ok(()))
    }

    fn acted_when_told(&mut self, told: Box<dyn FnOnce() + Send>) -> Option<Result<(), Raised>> {
        lock(&self.inner).acted = Some(told);
        Some(Ok(()))
    }

    fn as_any(&mut self) -> Option<&mut dyn std::any::Any> {
        Some(self)
    }
}

/// `make(paths)`: the capability's code, as `registry.py` names it.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(StartWithCodex::new(paths.clone())))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn route(exit: Result<i32, &'static str>, pid: Option<&'static str>, here: bool) -> Route {
        let runner: Runner = Arc::new(move |script, values, timeout| {
            assert_eq!(script, WMI_CREATE);
            assert_eq!(timeout, Duration::from_secs_f64(TIMEOUT_SECONDS));
            let file = values
                .iter()
                .find(|(name, _)| *name == "WMI_PIDFILE")
                .and_then(|(_, value)| *value)
                .map(PathBuf::from);
            if let (Some(file), Some(pid)) = (file, pid) {
                std::fs::write(file, pid).ok();
            }
            match exit {
                Ok(code) => Ok(code),
                Err("timeout") => Err(car_platform::pwsh::RunError::Spawn(
                    car_platform::spawn::SpawnError::Timeout,
                )),
                Err(_) => Err(car_platform::pwsh::RunError::PowerShell(
                    car_platform::pwsh::PowerShellError("refused"),
                )),
            }
        });
        Route {
            inner: Arc::new(Mutex::new(Inner::default())),
            runner,
            available: Arc::new(move || here),
        }
    }

    fn one(key: &str, value: Value) -> Value {
        let mut map = Map::new();
        map.insert(Str::new(key), value);
        Value::Object(map)
    }

    #[test]
    fn the_script_is_the_tags_byte_for_byte() {
        let source =
            include_str!("../../../../../src/codex_auto_resume_advanced/control/codexstart.py");
        let start = source.find("_WMI_CREATE = r\"\"\"").map(|at| at + 18);
        let script =
            start.and_then(|at| source[at..].find("\"\"\"").map(|end| &source[at..at + end]));
        assert_eq!(
            script.map(|text| text.replace("\r\n", "\n")),
            Some(WMI_CREATE.to_owned())
        );
    }

    #[test]
    fn each_outcome_is_the_tags_word() {
        assert_eq!(
            route(Ok(0), Some(" 7321\n"), true).run("cmd"),
            one("pid", Value::Int(Int::from(7321)))
        );
        assert_eq!(
            route(Ok(121), None, true).run("cmd"),
            one("code", Value::Int(Int::from(121)))
        );
        assert_eq!(
            route(Ok(0), Some("x"), true).run("cmd"),
            one("code", word("no_pid"))
        );
        assert_eq!(
            route(Ok(0), None, true).run("cmd"),
            one("code", word("no_pid"))
        );
        assert_eq!(
            route(Ok(0), Some("1"), false).run("cmd"),
            one("code", word("no_powershell"))
        );
        assert_eq!(
            route(Err("timeout"), None, true).run("cmd"),
            one("uncertain", word("timeout"))
        );
        assert_eq!(
            route(Err("refused"), None, true).run("cmd"),
            one("code", word("PowerShellError"))
        );
    }

    #[test]
    fn a_pid_reads_as_python_int_reads_it() {
        assert_eq!(python_int(" +12 "), Some(12));
        assert_eq!(python_int("1_000"), Some(1000));
        assert_eq!(python_int("_1"), None);
        assert_eq!(python_int(""), None);
        assert_eq!(python_int("1.0"), None);
    }
}
