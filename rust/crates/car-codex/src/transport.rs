//! `codex/transport.py`: everything this product asks of the Codex CLI, and the checks it asks it first.
//!
//! A Codex update bumps the version string, which alone must not disable auto-resume - so every build has to prove it
//! still offers the exact interface this tool drives. A failed local check always wins over what the registry says.
//! Every process started here is a console program started with `CREATE_NO_WINDOW` (car-platform's `Spawn`).

use std::ffi::OsString;
use std::io::Read;
use std::os::windows::fs::MetadataExt;
use std::process::Child;
use std::sync::mpsc::{Receiver, RecvTimeoutError, channel};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use car_config::winpath;
use car_machine::domain::ids::is_uuid;
use car_machine::json::{Map, Value};
use car_machine::pytext::strip;
use car_machine::pyval;
use car_platform::spawn::{Spawn, Stream, SystemStarter};
use car_policy::classify::continuation::{
    COMMAND_LINE_UNITS, PROMPT_SEND_LIMIT, command_line_units,
};
use car_policy::classify::text::is_word;

use crate::appserver::{Protocol, Results};
use crate::errors::{Error, Result};
use crate::layout;
use crate::pairing;
use crate::refold::{self, points};
use crate::system::{System, object};
use crate::usage::parse_usage;

/// The flags `codex queue` must still take.
pub const REQUIRED_QUEUE_FLAGS: [&str; 2] = ["--thread", "--message"];
/// Why a record waits where a process of the app runs and no server of its was matched.
pub const UNMATCHED: &str = "app_server_unmatched";
pub const UNMATCHED_NAMED_ENGINE: &str = "app_server_unmatched:named_engine";
pub const PASS: &str = "PASS";
pub const FAIL: &str = "FAIL";
pub const UNAVAILABLE: &str = "UNAVAILABLE";
/// `codex --version`'s time, `codex queue --help`'s, a send's, and a killed send's last wait (seconds).
pub const VERSION_SECONDS: f64 = 10.0;
pub const HELP_SECONDS: f64 = 20.0;
pub const SEND_SECONDS: f64 = 45.0;
pub const KILLED_SECONDS: f64 = 5.0;

/// `offers(help_text, flag)`: whether a `--help` text lists `flag` as an option of its own.
pub fn offers(help_text: &str, flag: &str) -> bool {
    let text = points(help_text);
    let wanted = points(flag);
    let fence = |c: Option<&u32>| c.is_some_and(|c| is_word(*c) || *c == u32::from(b'-'));
    (0..text.len()).any(|at| {
        text[at..].starts_with(&wanted)
            && !fence(at.checked_sub(1).and_then(|before| text.get(before)))
            && !fence(text.get(at + wanted.len()))
    })
}

/// `canonical_uuid(value)`: the value, where it is a canonical UUID; a ValueError otherwise.
pub fn canonical_uuid(value: &str) -> Result<()> {
    if is_uuid(&Value::from(value)) {
        Ok(())
    } else {
        Err(Error::Python("ValueError"))
    }
}

static VERIFIED: Mutex<Option<Vec<String>>> = Mutex::new(None);

/// `verified_versions()`: the engine versions the bundled registry marks VERIFIED for sending, read once.
/// `version` is this product's own (`config.version()`).
pub fn verified_versions(bundled: Option<&str>, version: &str) -> Vec<String> {
    let mut held = VERIFIED
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if held.is_none() {
        let product = crate::compat::files::product_version(version);
        *held = Some(
            bundled
                .map(|path| crate::compat::files::bundled_verified_versions(path, &product))
                .unwrap_or_default(),
        );
    }
    held.clone().unwrap_or_default()
}

/// A fresh process's `_VERIFIED`.
pub fn reset() {
    *VERIFIED
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner()) = None;
}

/// What a process run to its end left: its exit code (as Windows gives it, unsigned) and its output, decoded.
struct Ran {
    code: i64,
    stdout: String,
}

/// Why a run gave nothing.
pub(crate) enum RunError {
    /// `OSError`: it could not be started or read.
    Os,
    /// `subprocess.TimeoutExpired`: it was killed when its time ran out.
    Timeout,
}

/// Bytes as a text-mode pipe decodes them: UTF-8 with replacement, universal newlines.
pub(crate) fn decode(bytes: &[u8]) -> String {
    let mut text = String::new();
    let mut whole = crate::appserver::TextReader::new(bytes);
    while let Ok(line) = whole.readline(1 << 20) {
        if line.is_empty() {
            break;
        }
        text.extend(line);
    }
    text
}

pub(crate) fn exit_code(status: std::process::ExitStatus) -> i64 {
    status.code().map_or(-1, |code| i64::from(code as u32))
}

/// A child's output, read to its end on a thread of its own: `Popen.communicate`'s reader thread on Windows.
///
/// Its end comes when every handle on the pipe is closed, so a process the child started that inherited the pipe
/// holds it open after the child exits. `finish` waits for that end however long it takes, as the reference's
/// `stdout.close()` waits for its reader thread, and dropping the reader finishes it: no reader thread is left
/// behind.
pub(crate) struct Output {
    ended: Receiver<Vec<u8>>,
    thread: Option<JoinHandle<()>>,
    bytes: Option<Vec<u8>>,
}

impl Output {
    pub(crate) fn start(mut stdout: impl Read + Send + 'static) -> Output {
        let (send, ended) = channel();
        let thread = std::thread::spawn(move || {
            let mut bytes = Vec::new();
            let _ = stdout.read_to_end(&mut bytes);
            let _ = send.send(bytes);
        });
        Output {
            ended,
            thread: Some(thread),
            bytes: None,
        }
    }

    /// `stdout_thread.join(remaining)` and `is_alive()`: whether the output's end was read by `until`.
    fn ended_by(&mut self, until: Instant) -> bool {
        if self.bytes.is_some() {
            return true;
        }
        match self
            .ended
            .recv_timeout(until.saturating_duration_since(Instant::now()))
        {
            Ok(bytes) => self.bytes = Some(bytes),
            Err(RecvTimeoutError::Timeout) => return false,
            Err(RecvTimeoutError::Disconnected) => self.bytes = Some(Vec::new()),
        }
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
        true
    }

    /// The output whole, once the pipe's every handle is closed (however long that takes).
    pub(crate) fn finish(&mut self) -> Vec<u8> {
        if self.bytes.is_none() {
            self.bytes = Some(self.ended.recv().unwrap_or_default());
        }
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
        self.bytes.take().unwrap_or_default()
    }
}

impl Drop for Output {
    fn drop(&mut self) {
        if self.thread.is_some() {
            self.finish();
        }
    }
}

/// How `communicate(timeout=)` ended.
pub(crate) enum Communicated {
    /// The output's end read and the exit seen, both within the time.
    Done(std::process::ExitStatus, Vec<u8>),
    /// `subprocess.TimeoutExpired`: the output's end or the exit did not come in time.
    Timeout,
    /// `OSError`: the process could not be waited for.
    Os,
}

/// `process.communicate(timeout=seconds)` on Windows: the reader thread joined with the time, then the process
/// waited for with what is left of it - one bound for the output's end AND the exit.
pub(crate) fn communicate(child: &mut Child, output: &mut Output, until: Instant) -> Communicated {
    if !output.ended_by(until) {
        return Communicated::Timeout;
    }
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Communicated::Done(status, output.finish()),
            Ok(None) => {}
            Err(_) => return Communicated::Os,
        }
        if Instant::now() >= until {
            return Communicated::Timeout;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

pub(crate) fn deadline(seconds: f64) -> Instant {
    Instant::now() + Duration::from_secs_f64(seconds)
}

/// `subprocess.run(argv, stdout=PIPE, ..., timeout=...)` of a spawn whose streams are set: its exit code and its
/// output bytes. On the time's end it is killed and then read to its end (Windows' `run` calls `communicate()`
/// after `kill()`, with no time), and the answer is `TimeoutExpired`; on any other error killed, read and waited
/// for (`run`'s bare `except: kill(); raise`, then `Popen.__exit__`).
pub(crate) fn run_to_end(
    spawn: &Spawn,
    seconds: f64,
) -> std::result::Result<(i64, Vec<u8>), RunError> {
    let mut child = SystemStarter
        .start_guarded(spawn, cfg!(test))
        .map_err(|_| RunError::Os)?;
    let Some(stdout) = child.stdout.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err(RunError::Os);
    };
    let mut output = Output::start(stdout);
    let ended = communicate(&mut child, &mut output, deadline(seconds));
    let error = match ended {
        Communicated::Done(status, bytes) => return Ok((exit_code(status), bytes)),
        Communicated::Timeout => RunError::Timeout,
        Communicated::Os => RunError::Os,
    };
    let _ = child.kill();
    output.finish();
    let _ = child.wait();
    Err(error)
}

/// `subprocess.run(argv, stdout=PIPE, stderr=DEVNULL, text=True, timeout=...)`.
fn run(spawn: Spawn, seconds: f64) -> std::result::Result<Ran, RunError> {
    let spawn = spawn.with_streams(Stream::Inherit, Stream::Piped, Stream::Null);
    let (code, bytes) = run_to_end(&spawn, seconds)?;
    Ok(Ran {
        code,
        stdout: decode(&bytes),
    })
}

/// A launch guard (`with launch_guard as permitted`): `enter` answers what the `with` binds, `exit` may fail.
pub trait LaunchGuard {
    fn enter(&mut self) -> std::result::Result<Value, Raised>;
    fn exit(&mut self) -> std::result::Result<(), Raised>;
}

/// A launch guard of the engine's shape (`send_within`): it enters the guard, runs the body with whether it permits,
/// and leaves it; an `Err` is an exception it raised entering or leaving.
pub type LaunchScope<'a> = dyn FnMut(&mut dyn FnMut(bool)) -> std::result::Result<(), Raised> + 'a;

/// An exception a launch guard raised.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Raised;

/// Every Backend's own number, from 1: `id(backend)` as the compatibility evaluator keys an engine by it.
static IDENTITIES: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);

/// The engine this product drives, and everything it asks of it.
pub struct Backend {
    /// `id(self)`: this Backend's own number, the same wherever the value is moved and never another Backend's
    /// (Python's `id` is the object's while it lives; a Rust value's address changes when it moves).
    identity: u64,
    pub system: Arc<dyn System>,
    /// `Path(codex_home).resolve()`, as text.
    pub codex_home: String,
    /// `Path(codex_exe).resolve()`, as text.
    pub codex_exe: String,
    pub require_holder: bool,
    /// This product's version, as `config.version()` reads it (the App Server is told it).
    pub product_version: String,
    /// The bundled registry file, read once for `verified_versions`.
    pub bundled: Option<String>,
    pub session_holder: Option<(Value, Value)>,
    version_signature: Option<(u64, u64)>,
    last_checks: Option<Map>,
    pub engine_version: Option<String>,
    pub engine_verified: bool,
    pub queue_remote_supported: bool,
    pub served_elsewhere: Vec<String>,
    pub app_look: Option<&'static str>,
    pub app_looked_at: Option<f64>,
    rows: Option<Vec<Value>>,
    pub server_holds: Option<bool>,
    pub named_engine: bool,
    pub app_look_why: Option<&'static str>,
    pub layout: Option<Arc<Value>>,
    /// What the helper last met on this backend (`protocol_results`).
    pub protocol_results: Results,
}

impl Backend {
    pub fn new(
        system: Arc<dyn System>,
        codex_home: &str,
        codex_exe: &str,
        require_holder: bool,
        product_version: &str,
    ) -> Backend {
        let resolve = |text: &str| {
            system
                .resolve(&winpath::path_str(text))
                .unwrap_or_else(|| winpath::path_str(text))
        };
        let (codex_home, codex_exe) = (resolve(codex_home), resolve(codex_exe));
        Backend {
            identity: IDENTITIES.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            system,
            codex_home,
            codex_exe,
            require_holder,
            product_version: product_version.to_owned(),
            bundled: None,
            session_holder: None,
            version_signature: None,
            last_checks: None,
            engine_version: None,
            engine_verified: false,
            queue_remote_supported: false,
            served_elsewhere: Vec::new(),
            app_look: None,
            app_looked_at: None,
            rows: None,
            server_holds: None,
            named_engine: false,
            app_look_why: None,
            layout: None,
            protocol_results: Vec::new(),
        }
    }

    /// `_environment()`: this process's environment as `os.environ.copy()` gives it (names upper-cased), with Codex's
    /// home and telemetry off.
    pub fn environment(&self) -> Vec<(OsString, OsString)> {
        let mut env: Vec<(OsString, OsString)> = Vec::new();
        let mut put = |name: String, value: OsString| {
            let key = OsString::from(name.to_uppercase());
            match env.iter_mut().find(|(each, _)| *each == key) {
                Some(slot) => slot.1 = value,
                None => env.push((key, value)),
            }
        };
        for (name, value) in std::env::vars_os() {
            put(name.to_string_lossy().into_owned(), value);
        }
        put("CODEX_HOME".into(), OsString::from(&self.codex_home));
        put("OTEL_SDK_DISABLED".into(), OsString::from("true"));
        env
    }

    /// `_argv()`: the engine with telemetry off.
    pub fn argv(&self) -> Vec<String> {
        [
            self.codex_exe.as_str(),
            "-c",
            "analytics.enabled=false",
            "-c",
            "otel.exporter=\"none\"",
            "-c",
            "otel.trace_exporter=\"none\"",
            "-c",
            "otel.metrics_exporter=\"none\"",
            "-c",
            "otel.log_user_prompt=false",
            "-c",
            "chatgpt_base_url=\"https://chatgpt.com/backend-api/\"",
        ]
        .iter()
        .map(|each| (*each).to_owned())
        .collect()
    }

    fn command(&self, tail: &[&str]) -> Spawn {
        let mut argv = vec![self.codex_exe.clone()];
        argv.extend(tail.iter().map(|each| (*each).to_owned()));
        Spawn::new(argv).with_env(self.environment())
    }

    /// `_queue_interface_ok()`: prove `codex queue` still takes the exact flags we drive it with.
    fn queue_interface_ok(&mut self) -> std::result::Result<bool, RunError> {
        let result = run(self.command(&["queue", "--help"]), HELP_SECONDS)?;
        if result.code != 0 {
            return Ok(false);
        }
        self.queue_remote_supported = offers(&result.stdout, "--remote");
        Ok(REQUIRED_QUEUE_FLAGS
            .iter()
            .all(|flag| offers(&result.stdout, flag)))
    }

    /// `_queue_daemon_remote()`: whether a managed daemon of this home runs, so a send names it with `--remote`.
    pub fn queue_daemon_remote(&self) -> Result<bool> {
        if !self.queue_remote_supported {
            return Ok(false);
        }
        let folder = winpath::path_str(&winpath::join(
            &winpath::join(
                &winpath::join(&self.codex_home, "packages"),
                "app-server-daemon",
            ),
            "releases",
        ));
        let mut prefix = refold::casefold_points(&points(&folder));
        prefix.push(u32::from(b'\\'));
        pairing::forget_inventory();
        let rows = match pairing::inventory(self.system.as_ref()) {
            Ok(rows) => rows,
            Err(Error::Adapter(_) | Error::Os | Error::Python("ValueError")) => {
                return Err(Error::Adapter("process_inventory_unavailable"));
            }
            Err(other) => return Err(other),
        };
        Ok(rows.iter().any(|row| {
            let Value::Object(map) = row else {
                return false;
            };
            let pid_ok = matches!(map.get("pid"), Some(pid @ Value::Int(_))
                if pyval::greater(pid, &Value::from(0)).unwrap_or(false));
            let Some(Value::Str(path)) = map.get("path") else {
                return false;
            };
            let path: Vec<u32> = path.code_points().collect();
            if !pid_ok || !refold::casefold_points(&path).starts_with(&prefix) {
                return false;
            }
            // `row["path"][len(prefix):]`: the original text cut at the folded prefix's length.
            let rest = path.get(prefix.len()..).unwrap_or(&[]);
            let Some(end) = rest.iter().position(|c| *c == u32::from(b'\\')) else {
                return false;
            };
            end > 0 && refold::exactly(rest, end, "\\bin\\codex.exe")
        }))
    }

    fn keep(&mut self, checks: &Map) -> Map {
        self.last_checks = Some(checks.clone());
        checks.clone()
    }

    /// `engine_checks()`: the engine's three structural checks, with the version and the signature they were made on.
    pub fn engine_checks(&mut self) -> Map {
        let mut checks = Map::new();
        for (key, value) in [
            ("official_location", Value::from(FAIL)),
            ("version_runs", Value::from(UNAVAILABLE)),
            ("queue_flags", Value::from(UNAVAILABLE)),
            ("version", Value::Null),
            ("signature", Value::Null),
        ] {
            checks.insert(key.into(), value);
        }
        if !pairing::official_engine(self.system.as_ref(), &self.codex_exe).0 {
            return self.keep(&checks);
        }
        checks.insert("official_location".into(), Value::from(PASS));
        let Ok(found) = std::fs::metadata(&self.codex_exe) else {
            return self.keep(&checks);
        };
        let signature = (found.len(), mtime_ns(found.last_write_time()));
        checks.insert(
            "signature".into(),
            Value::Array(vec![
                Value::from(signature.0 as i64),
                Value::from(signature.1 as i64),
            ]),
        );
        if Some(signature) == self.version_signature {
            checks.insert("version_runs".into(), Value::from(PASS));
            checks.insert("queue_flags".into(), Value::from(PASS));
            checks.insert(
                "version".into(),
                self.engine_version
                    .as_deref()
                    .map_or(Value::Null, Value::from),
            );
            return self.keep(&checks);
        }
        let Ok(result) = run(self.command(&["--version"]), VERSION_SECONDS) else {
            return self.keep(&checks);
        };
        if result.code != 0 {
            return self.keep(&checks);
        }
        let version = strip(&result.stdout).to_owned();
        checks.insert("version_runs".into(), Value::from(PASS));
        checks.insert("version".into(), Value::from(version.as_str()));
        let Ok(flags) = self.queue_interface_ok() else {
            return self.keep(&checks);
        };
        if !flags {
            checks.insert("queue_flags".into(), Value::from(FAIL));
            return self.keep(&checks);
        }
        checks.insert("queue_flags".into(), Value::from(PASS));
        self.engine_version = Some(version.clone());
        self.engine_verified =
            verified_versions(self.bundled.as_deref(), &self.product_version).contains(&version);
        self.version_signature = Some(signature);
        self.keep(&checks)
    }

    /// `last_checks()`: the result of the most recent `engine_checks()`, or None before the first.
    pub fn last_checks(&self) -> Option<Map> {
        self.last_checks.clone()
    }

    /// `_compatible()`.
    pub fn compatible(&mut self) -> Result<()> {
        let checks = self.engine_checks();
        let is = |key: &str, word: &str| pyval::is(checks.get(key).unwrap_or(&Value::Null), word);
        if !is("official_location", PASS) {
            return Err(Error::Adapter("unsupported_codex_location"));
        }
        if !is("version_runs", PASS) || is("queue_flags", UNAVAILABLE) {
            return Err(Error::Adapter("codex_binary_unavailable"));
        }
        if !is("queue_flags", PASS) {
            return Err(Error::Adapter("unsupported_codex_version"));
        }
        Ok(())
    }

    /// `app_unmatched_reason`.
    pub fn app_unmatched_reason(&self) -> &'static str {
        if self.app_look_why == Some("named_engine") {
            UNMATCHED_NAMED_ENGINE
        } else {
            UNMATCHED
        }
    }

    /// `app_identity()`: the paired app and server, or None.
    pub fn app_identity(&mut self) -> Result<Option<Value>> {
        self.served_elsewhere = Vec::new();
        self.app_look = None;
        self.app_look_why = None;
        self.server_holds = None;
        self.layout = None;
        match self.identity() {
            Ok(found) => Ok(Some(found)),
            Err(Error::Adapter(_) | Error::Os | Error::Python("KeyError" | "TypeError")) => {
                Ok(None)
            }
            Err(other) => Err(other),
        }
    }

    fn identity(&mut self) -> Result<Value> {
        self.compatible()?;
        self.rows = None;
        let rows = pairing::inventory(self.system.as_ref())?;
        self.rows = Some(rows.clone());
        let system = Arc::clone(&self.system);
        let running = pairing::app_running(system.as_ref(), &rows)?;
        self.app_look = Some(if running { "unmatched" } else { "closed" });
        self.app_looked_at = Some(system.monotonic());
        let mut seen = Map::new();
        let paired = pairing::desktop_pair(
            system.as_ref(),
            &rows,
            &self.codex_exe,
            Some(&self.codex_home),
            self.require_holder,
            Some(&mut seen),
        );
        self.layout = Some(Arc::new(layout::snapshot(
            system.as_ref(),
            Some(&rows),
            Some(&self.codex_exe),
            Some(&seen),
        )));
        match paired {
            Ok(paired) => {
                self.app_look = Some("matched");
                self.server_holds =
                    Some(matches!(seen.get("server_holds"), Some(Value::Bool(true))));
                Ok(paired)
            }
            Err(Error::Adapter(code)) => {
                self.served_elsewhere =
                    pairing::engines_instead(system.as_ref(), &rows, &self.codex_exe)?;
                if self.named_engine
                    && self.app_look == Some("unmatched")
                    && self
                        .served_elsewhere
                        .iter()
                        .any(|path| pairing::official_engine(system.as_ref(), path).0)
                {
                    self.app_look_why = Some("named_engine");
                }
                Err(Error::Adapter(code))
            }
            Err(other) => Err(other),
        }
    }

    fn lock_path(&self, thread_id: &str) -> String {
        winpath::path_str(&winpath::join(
            &winpath::join(&self.codex_home, "thread-writer-locks"),
            &format!("{thread_id}.lock"),
        ))
    }

    fn users(&self, thread_id: &str) -> Result<Vec<Value>> {
        self.system.resource_users(&[self.lock_path(thread_id)])
    }

    /// `loaded(thread_id, app_identity)`: "loaded", "notLoaded", "elsewhere" or "unknown".
    pub fn loaded(&mut self, thread_id: &str, app_identity: &Value) -> Result<&'static str> {
        self.session_holder = None;
        match self.loaded_inner(thread_id, app_identity) {
            Ok(word) => Ok(word),
            Err(
                Error::Adapter(_)
                | Error::Os
                | Error::Python("ValueError" | "KeyError" | "TypeError"),
            ) => Ok("unknown"),
            Err(other) => Err(other),
        }
    }

    fn same_identity(&mut self, app_identity: &Value) -> Result<bool> {
        Ok(match self.app_identity()? {
            Some(found) => pyval::eq(&found, app_identity),
            None => matches!(app_identity, Value::Null),
        })
    }

    fn loaded_inner(&mut self, thread_id: &str, app_identity: &Value) -> Result<&'static str> {
        canonical_uuid(thread_id)?;
        self.compatible()?;
        if !pyval::truthy(app_identity) || !self.same_identity(app_identity)? {
            return Ok("unknown");
        }
        let folder = winpath::join(&self.codex_home, "thread-writer-locks");
        if !std::path::Path::new(&folder).is_dir() {
            return Ok("unknown");
        }
        let users = self.users(thread_id)?;
        if users.is_empty() {
            return Ok("notLoaded");
        }
        let server = index(app_identity, "server")?;
        let expected = object(vec![
            ("pid", index(server, "pid")?.clone()),
            ("created", index(server, "created")?.clone()),
        ]);
        let only = users.len() == 1 && pyval::eq(&users[0], &expected);
        if only && self.same_identity(app_identity)? {
            return Ok("loaded");
        }
        if users.len() == 1
            && !only
            && self.same_identity(app_identity)?
            && self.server_holds == Some(true)
            && pairing::session_kind(
                self.system.as_ref(),
                self.rows.as_deref(),
                &users[0],
                &self.codex_exe,
            )?
        {
            self.session_holder = Some((
                index(&users[0], "pid")?.clone(),
                index(&users[0], "created")?.clone(),
            ));
            return Ok("elsewhere");
        }
        Ok("unknown")
    }

    /// `holder(thread_id)`: "none", "session", "ours" or "unknown".
    pub fn holder(&mut self, thread_id: &str) -> Result<&'static str> {
        let found = (|| -> Result<&'static str> {
            canonical_uuid(thread_id)?;
            self.compatible()?;
            let Some(rows) = self.rows.clone() else {
                return Ok("unknown");
            };
            if pairing::app_running(self.system.as_ref(), &rows)? {
                return Ok("unknown");
            }
            let users = self.users(thread_id)?;
            if users.is_empty() {
                return Ok("none");
            }
            if users.len() == 1
                && pairing::session_kind(
                    self.system.as_ref(),
                    Some(&rows),
                    &users[0],
                    &self.codex_exe,
                )?
            {
                return Ok("session");
            }
            if users.len() == 1 && pairing::own_holder(&users[0])? {
                return Ok("ours");
            }
            Ok("unknown")
        })();
        match found {
            Ok(word) => Ok(word),
            Err(
                Error::Adapter(_)
                | Error::Os
                | Error::Python("ValueError" | "KeyError" | "TypeError"),
            ) => Ok("unknown"),
            Err(other) => Err(other),
        }
    }

    /// `usage()`: the usage the App Server reports, or the one answer that says it could not be read.
    pub fn usage(&mut self) -> Result<Map> {
        let read = (|| -> Result<Map> {
            let mut client = Protocol::open(self)?;
            let result = client.call("account/rateLimits/read", None)?;
            let parsed = parse_usage(&result).map_err(Error::Python)?;
            client.close();
            Ok(parsed)
        })();
        match read {
            Ok(found) => Ok(found),
            Err(Error::Adapter(_) | Error::Os | Error::Python("ValueError")) => {
                let mut answer = Map::new();
                answer.insert("available".into(), Value::Null);
                answer.insert("reset_at".into(), Value::Null);
                answer.insert("limit_type".into(), Value::from("unknown"));
                answer.insert("reason".into(), Value::from("usage_probe_unavailable"));
                Ok(answer)
            }
            Err(other) => Err(other),
        }
    }

    fn send_argv(&self, thread_id: &str, prompt: &str, remote: bool) -> Vec<String> {
        let mut argv = self.argv();
        argv.extend([
            "queue".to_owned(),
            "--thread".to_owned(),
            thread_id.to_owned(),
            format!("--message={prompt}"),
        ]);
        if remote {
            argv.extend(["--remote".to_owned(), "unix://".to_owned()]);
        }
        argv
    }

    /// `send(thread_id, prompt, launch_guard=)`: only a spawn failure permits a retry; every uncertainty after it is
    /// terminal.
    pub fn send(
        &mut self,
        thread_id: &str,
        prompt: &Value,
        launch_guard: Option<&mut dyn LaunchGuard>,
    ) -> Map {
        let (text, remote) = match self.send_preflight(thread_id, prompt) {
            Ok(found) => found,
            Err(refused) => return refused,
        };
        let mut guard = launch_guard;
        if let Some(guard) = guard.as_mut() {
            let permitted = match guard.enter() {
                Ok(permitted) => permitted,
                Err(Raised) => return not_started("queue_spawn_failed"),
            };
            if !matches!(permitted, Value::Bool(true)) {
                return match guard.exit() {
                    Ok(()) => not_started("queue_consent_refused"),
                    Err(Raised) => not_started("queue_spawn_failed"),
                };
            }
        }
        let started = self.send_start(thread_id, &text, remote);
        if let Some(guard) = guard.as_mut() {
            // A guard exit can fail after Popen; the process then already exists, and its receipt is read below.
            let _ = guard.exit();
            if started.is_err() {
                return not_started("queue_spawn_failed");
            }
        }
        let Ok(process) = started else {
            return not_started("queue_spawn_failed");
        };
        receipt(thread_id, process)
    }

    /// `send(...)` with a launch guard of the other shape (Integration 6, for car-engine's `store.submission_guard`):
    /// `scope(body)` enters the guard, runs `body(permitted)` inside it and leaves it - an `Err` is an exception the
    /// guard raised entering or leaving. The process is started inside `body`, where `with launch_guard as permitted:`
    /// starts it; every answer is `send`'s: refused before the guard is asked, `queue_consent_refused` where it did not
    /// permit, `queue_spawn_failed` where it raised before a process existed or the start failed, and a process that
    /// exists has its receipt read even where the guard raised leaving.
    pub fn send_within(
        &mut self,
        thread_id: &str,
        prompt: &Value,
        scope: &mut LaunchScope<'_>,
    ) -> Map {
        let (text, remote) = match self.send_preflight(thread_id, prompt) {
            Ok(found) => found,
            Err(refused) => return refused,
        };
        let mut started: Option<std::result::Result<std::process::Child, ()>> = None;
        let entered = scope(&mut |permitted: bool| {
            if permitted {
                started = Some(self.send_start(thread_id, &text, remote).map_err(|_| ()));
            }
        });
        match (entered, started) {
            (_, Some(Ok(process))) => receipt(thread_id, process),
            (Ok(()), None) => not_started("queue_consent_refused"),
            _ => not_started("queue_spawn_failed"),
        }
    }

    /// `send`'s checks before the guard: a canonical id, a prompt that fits, a compatible engine, a command line
    /// that fits; the prompt as text and whether the managed daemon is spoken to, or the answer that refuses.
    fn send_preflight(
        &mut self,
        thread_id: &str,
        prompt: &Value,
    ) -> std::result::Result<(String, bool), Map> {
        let preflight = (|| -> Result<(String, bool)> {
            canonical_uuid(thread_id)?;
            let text = match prompt {
                Value::Str(text) => text,
                _ => return Err(Error::Python("ValueError")),
            };
            let count = text.code_points().count();
            if count == 0 || count > PROMPT_SEND_LIMIT || text.code_points().any(|c| c == 0) {
                return Err(Error::Python("ValueError"));
            }
            let text = text
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| String::from_utf8_lossy(text.as_bytes()).into_owned());
            self.compatible()?;
            let remote = self.queue_daemon_remote()?;
            if command_line_units(&self.send_argv(thread_id, &text, remote)) > COMMAND_LINE_UNITS {
                return Err(Error::Python("ValueError"));
            }
            Ok((text, remote))
        })();
        preflight.map_err(|_| not_started("queue_preflight_failed"))
    }

    /// The one place that starts a send: `codex queue --thread <id> --message=<text>` (`--remote unix://` for the
    /// managed daemon), console-less, its output piped.
    fn send_start(
        &self,
        thread_id: &str,
        text: &str,
        remote: bool,
    ) -> std::result::Result<std::process::Child, car_platform::spawn::SpawnError> {
        let spawn = Spawn::new(self.send_argv(thread_id, text, remote))
            .with_env(self.environment())
            .with_cwd(&self.codex_home)
            .with_streams(Stream::Null, Stream::Piped, Stream::Null);
        SystemStarter.start_guarded(&spawn, cfg!(test))
    }

    /// `delete_queue(thread_id, queue_id)`: whether the App Server says it deleted our queued message.
    pub fn delete_queue(&mut self, thread_id: &str, queue_id: &str) -> Result<bool> {
        let done = (|| -> Result<bool> {
            canonical_uuid(thread_id)?;
            canonical_uuid(queue_id)?;
            let mut client = Protocol::open(self)?;
            let result = client.call(
                "thread/queue/delete",
                Some(object(vec![
                    ("threadId", Value::from(thread_id)),
                    ("queuedSubmissionId", Value::from(queue_id)),
                ])),
            )?;
            client.close();
            Ok(matches!(&result, Value::Object(map)
                if matches!(map.get("deleted"), Some(Value::Bool(true)))))
        })();
        match done {
            Ok(deleted) => Ok(deleted),
            Err(Error::Adapter(_) | Error::Os | Error::Python("ValueError")) => Ok(false),
            Err(other) => Err(other),
        }
    }

    /// `id(backend)`: this Backend's own number, kept wherever the value moves.
    pub fn object_id(&self) -> u64 {
        self.identity
    }

    /// The rows the last `app_identity()` read (in memory only).
    pub fn rows(&self) -> Option<&[Value]> {
        self.rows.as_deref()
    }
}

/// The answer of a send no process was started for.
fn not_started(code: &str) -> Map {
    answer(vec![
        ("outcome", Value::from("not_started")),
        ("error_code", Value::from(code)),
    ])
}

fn answer(pairs: Vec<(&str, Value)>) -> Map {
    match object(pairs) {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

/// What a started send answers: its receipt, read within `SEND_SECONDS`, or why it is unknown.
fn receipt(thread_id: &str, mut process: std::process::Child) -> Map {
    let unknown = |code: &str| {
        answer(vec![
            ("outcome", Value::from("unknown")),
            ("error_code", Value::from(code)),
        ])
    };
    let Some(stdout) = process.stdout.take() else {
        return unknown("queue_result_unknown");
    };
    // `finally: process.stdout.close()`: every way out waits for the reader, as `output`'s drop does.
    let mut output = Output::start(stdout);
    let (status, stdout) = match communicate(&mut process, &mut output, deadline(SEND_SECONDS)) {
        Communicated::Done(status, bytes) => (status, decode(&bytes)),
        Communicated::Timeout => {
            let _ = process.kill(); // only this helper; accepted delivery is still possible
            // `process.communicate(timeout=5)`, its TimeoutExpired passed over.
            let _ = communicate(&mut process, &mut output, deadline(KILLED_SECONDS));
            output.finish();
            return unknown("queue_timeout");
        }
        Communicated::Os => {
            output.finish();
            return unknown("queue_result_unknown");
        }
    };
    let code = exit_code(status);
    let receipt = strip(&stdout);
    let queue_id = receipt
        .strip_prefix("Queued message ")
        .and_then(|rest| rest.strip_suffix(&format!(" for thread {thread_id}.")))
        .filter(|id| {
            id.chars().count() == 36
                && id
                    .chars()
                    .all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c) || c == '-')
        });
    if code == 0
        && let Some(queue_id) = queue_id
    {
        if canonical_uuid(queue_id).is_err() {
            return unknown("queue_result_unknown");
        }
        return answer(vec![
            ("outcome", Value::from("accepted")),
            ("queue_id", Value::from(queue_id)),
        ]);
    }
    let unconfirmed = |detail: &str, exit: Option<i64>| {
        let mut pairs = vec![
            ("outcome", Value::from("unknown")),
            ("error_code", Value::from("queue_response_unconfirmed")),
            ("receipt_detail", Value::from(detail)),
        ];
        if let Some(exit) = exit {
            pairs.push(("exit_code", Value::from(exit)));
        }
        answer(pairs)
    };
    if code != 0 {
        return unconfirmed("nonzero_exit", (0..=255).contains(&code).then_some(code));
    }
    if receipt.is_empty() {
        return unconfirmed("empty_stdout", None);
    }
    unconfirmed("unrecognized_stdout", None)
}

/// `st_mtime_ns` of a FILETIME, as Python's `os.stat` gives it.
pub fn mtime_ns(filetime: u64) -> u64 {
    let seconds = (filetime / 10_000_000).wrapping_sub(11_644_473_600);
    seconds
        .wrapping_mul(1_000_000_000)
        .wrapping_add((filetime % 10_000_000) * 100)
}

fn index<'a>(value: &'a Value, key: &str) -> Result<&'a Value> {
    match value {
        Value::Object(map) => map.get(key).ok_or(Error::Python("KeyError")),
        _ => Err(Error::Python("TypeError")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn backend() -> Backend {
        let home = std::env::temp_dir().join("car-v0627-fix7-identity");
        Backend::new(
            Arc::new(crate::system::Platform::new()),
            &home.to_string_lossy(),
            &home.join("codex.exe").to_string_lossy(),
            false,
            "0.6.27-alpha",
        )
    }

    /// `id(backend)`: the evaluator's engine key holds while the Backend is moved, and two Backends differ.
    #[test]
    fn a_backends_identity_survives_a_move() {
        let first = backend();
        let before = (first.object_id(), &first as *const Backend as usize);
        let moved = vec![first];
        let held = Box::new(moved);
        assert_eq!(held[0].object_id(), before.0);
        assert_ne!(backend().object_id(), before.0);
    }
}
