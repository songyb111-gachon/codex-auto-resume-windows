//! The command line (`cli.py` and `commands/*`): the parser's table and the command bodies, run as the reference runs
//! them - prints on stdout, errors as `error: <message>` on stderr with exit 1, the watcher's log written through the
//! same logbook, every machine question through car-control's Host and this crate's [`Outside`].
//!
//! Lines are written as Python's text streams on Windows write them: `\r\n` at each line's end (no `--json` or line is
//! ever written without one). Text is UTF-8 (the reference writes the console's code page where nothing reconfigured
//! it; AUDIT-v0628 records the difference).

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use car_config::Paths;
use car_control::host::{Event, Host};
use car_control::{Control, Failure};
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;
use car_policy::plug::Guarded;
use car_store::open::{OpenState, Opened};

use crate::argparse::Namespace;
use crate::seam::{Backend, History, Outside, Raised, ShortcutFailure};

/// `EXIT_OK`, `EXIT_ERROR`.
pub const EXIT_OK: i32 = 0;
pub const EXIT_ERROR: i32 = 1;
/// `downgrade-state --stop-watcher`'s code for a watcher that would not let go.
pub const EXIT_WATCHER_RUNNING: i32 = 3;
/// `STOP_WAIT_SECONDS`.
pub const STOP_WAIT_SECONDS: f64 = 60.0;
/// `PROG`.
pub const PROG: &str = "auto_resume";
/// `HEALTH_CHECKS`: the commands whose log lines carry the process's mark.
pub const HEALTH_CHECKS: &[&str] = &["doctor", "status"];
/// `PROGRESS_LINES`.
pub const PROGRESS_LINES: &str = "CODEX_AUTO_RESUME_PROGRESS_LINES";
/// `DOCTOR_CHECKS`.
pub const DOCTOR_CHECKS: i64 = 8;
/// `CANCEL_RETRY_SECONDS` (control/actions.py), the activation's wait for a busy state.
pub const CANCEL_RETRY_SECONDS: f64 = 10.0;

pub const UNMATCHED_APP: &str = "running, but its Codex server could not be matched";
pub const ELSEWHERE_SHORT: &str =
    "its server runs from another official Codex engine, which the watcher takes up";
pub const CLOSED_APP: &str = "not running (not a problem: recoveries wait until it opens)";
pub const CLOSED_ENGINE: &str = "not found while the ChatGPT app is closed (not a problem: it is looked for again when the app opens)";
pub const HISTORY_NOT_YET: &str =
    "not created yet (Codex makes it with the first saved conversation)";
pub const PROBLEM: &str = "health check     : problem - ";

/// Where the command line writes: the two streams (a test's buffers, or the process's own).
pub struct Io<'a> {
    pub out: &'a mut dyn Write,
    pub err: &'a mut dyn Write,
    /// `contextlib.redirect_stdout(io.StringIO())`: what is printed is dropped (`_cli_silent`).
    pub silent: bool,
}

impl Io<'_> {
    /// `print(text)`.
    pub fn say(&mut self, text: &str) {
        if !self.silent {
            let _ = self.out.write_all(format!("{text}\r\n").as_bytes());
            let _ = self.out.flush();
        }
    }

    /// `print(text, file=sys.stderr)`.
    pub fn warn(&mut self, text: &str) {
        let _ = self.err.write_all(format!("{text}\r\n").as_bytes());
        let _ = self.err.flush();
    }
}

/// `os.environ.get`, as a machine answers it.
pub type Environ = Arc<dyn Fn(&str) -> Option<String> + Send + Sync>;

/// The machine a command runs on: car-control's Host, this crate's Outside, and where the program is.
#[derive(Clone)]
pub struct Machine {
    pub host: Arc<dyn Host>,
    pub outside: Arc<dyn Outside>,
    /// `config.PROJECT_ROOT`: the folder above `src` (an installation's `app`).
    pub project_root: String,
    /// The environment (`os.environ.get`).
    pub env: Environ,
}

impl Machine {
    pub fn env(&self, name: &str) -> Option<String> {
        (self.env)(name)
    }

    /// `config.Paths(home)`.
    pub fn paths(&self, home: Option<&str>) -> Result<Paths, String> {
        let env = |name: &str| self.env(name);
        let os = car_config::Os::here(false, Arc::new(car_control::host::Probe));
        Paths::new(home, &self.project_root, &env, os).map_err(|class| match class {
            "OSError" => "the home could not be resolved".to_owned(),
            other => other.to_owned(),
        })
    }

    pub fn control(&self, paths: Paths) -> Control {
        Control::new(paths, Arc::clone(&self.host), Arc::new(Guarded::null()))
    }
}

/// `time.time()` and the local zone, for the log's stamps and `format_local`.
pub struct HostClock<'a>(pub &'a dyn Host);

impl car_config::logbook::Clock for HostClock<'_> {
    fn now(&self) -> f64 {
        self.0.now()
    }
    fn utc_offset(&self, seconds: i64) -> Option<i32> {
        let local = self.0.local_clock().localtime(seconds as f64).ok()?;
        let civil = days_from(local.year, local.mon, local.mday) * 86_400
            + local.hour * 3600
            + local.min * 60
            + local.sec;
        i32::try_from(civil - seconds).ok()
    }
}

/// `time.strftime(format, time.localtime(time.time()))` for the two formats used here.
pub fn stamp(host: &dyn Host, format: &str) -> String {
    let now = host.now();
    match host.local_clock().localtime(now.floor()) {
        Ok(t) => format
            .replace("%Y", &format!("{:04}", t.year))
            .replace("%m", &format!("{:02}", t.mon))
            .replace("%d", &format!("{:02}", t.mday))
            .replace("%H", &format!("{:02}", t.hour))
            .replace("%M", &format!("{:02}", t.min))
            .replace("%S", &format!("{:02}", t.sec)),
        Err(_) => String::new(),
    }
}

fn days_from(y: i64, m: i64, d: i64) -> i64 {
    let y = y - i64::from(m <= 2);
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (m + if m > 2 { -3 } else { 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// `App(paths, codex_exe=..., codex_home=..., console=..., enable_logging=..., log_mark=...)`, the parts a command uses.
pub struct App {
    pub machine: Machine,
    pub paths: Paths,
    pub control: Control,
    log: Option<car_config::logbook::Logbook>,
    mark: String,
    console: bool,
    pub settings: Map,
    pub codex_exe_override: Option<String>,
    pub codex_home: String,
}

/// Why a command ended with `error: <message>` (CliError, ConfigError, StoreError, StartupError).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CliError(pub String);

type Done = Result<i32, CliError>;

impl App {
    pub fn new(
        machine: &Machine,
        paths: Paths,
        codex_exe: Option<&str>,
        codex_home: Option<&str>,
        console: bool,
        enable_logging: bool,
        mark: &str,
    ) -> Result<App, CliError> {
        let log = if enable_logging {
            paths
                .ensure()
                .map_err(|raised| CliError(raised.message()))?;
            Some(car_config::logbook::Logbook::open(
                &paths.log_file,
                mark,
                &[],
            ))
        } else {
            None
        };
        let control = machine.control(paths.clone());
        let managed = machine.host.managed();
        let os = machine.host.os();
        let stored = car_policy::settings::load(&*os, Path::new(&paths.settings_file))
            .unwrap_or_else(|_| car_policy::settings::defaults());
        let settings = car_policy::settings::managed::clamp(&stored, &managed);
        let host = Arc::clone(&machine.host);
        let environ = |name: &str| host.environ(name);
        let windows = || host.windows_languages();
        let language = match settings.get("interface_language") {
            Some(Value::Str(text)) => text.as_str().map(str::to_owned),
            _ => None,
        };
        car_words::l10n::set_preference(language.as_deref(), &environ, &windows);
        let codex_exe_override =
            codex_exe
                .map(str::to_owned)
                .or_else(|| match settings.get("codex_exe") {
                    Some(value @ Value::Str(text)) if pyval::truthy(value) => {
                        text.as_str().map(str::to_owned)
                    }
                    _ => None,
                });
        let codex_home = match codex_home {
            Some(given) => os
                .resolve(&given.encode_utf16().collect::<Vec<u16>>())
                .map(|wide| String::from_utf16_lossy(&wide))
                .unwrap_or_else(|_| given.to_owned()),
            None => machine.host.codex_home(),
        };
        Ok(App {
            machine: machine.clone(),
            paths,
            control,
            log,
            mark: mark.to_owned(),
            console,
            settings,
            codex_exe_override,
            codex_home,
        })
    }

    /// `app.logger.info(line)`: the log file, and stderr where the console mirrors it.
    pub fn info(&self, io: &mut Io, line: &str) {
        let clock = HostClock(&*self.machine.host);
        if let Some(log) = &self.log {
            log.info(line, &clock);
            if self.console {
                let stamp = stamp(&*self.machine.host, "%Y-%m-%d %H:%M:%S");
                io.warn(&format!("[{stamp}] {}{line}", self.mark));
            }
        }
    }

    pub fn host(&self) -> &dyn Host {
        &*self.machine.host
    }

    pub fn state_dir(&self) -> PathBuf {
        PathBuf::from(&self.paths.state_dir)
    }

    /// `app.watcher_running()`.
    pub fn watcher_running(&self) -> Option<bool> {
        self.host().watcher_running(&self.state_dir())
    }

    /// `app.stop_event().signal()`: False where nothing could be signalled.
    pub fn signal_stop(&self) -> bool {
        self.host()
            .signal(Event::Stop, &self.state_dir())
            .unwrap_or(false)
    }

    fn open_with(&self, legacy: &str, hold: bool) -> Result<Opened, CliError> {
        let host = self.host();
        car_store::open::open_state(
            &self.state_dir(),
            host,
            &OpenState {
                legacy,
                hold_while_installing: hold,
                clock: host.store_clock(),
                ..Default::default()
            },
        )
        .map_err(store_error)
    }

    /// `_open_state(app)`: legacy "always", held while an installation runs.
    pub fn open_state(&self) -> Result<Opened, CliError> {
        self.open_with("always", true)
    }

    /// `app.open_store()`: legacy "never", held while an installation runs.
    pub fn open_store(&self) -> Result<car_store::Store, CliError> {
        match self.open_with("never", true)? {
            Opened::Store(store) => Ok(store),
            Opened::Legacy(_) => Err(CliError("unexpected legacy store".to_owned())),
        }
    }

    pub fn format_local(&self, value: &Value) -> String {
        car_config::logbook::format_local(value, &HostClock(&*self.machine.host))
    }

    pub fn setting_f64(&self, name: &str) -> f64 {
        self.settings.get(name).and_then(pyval_float).unwrap_or(0.0)
    }
}

fn pyval_float(value: &Value) -> Option<f64> {
    car_machine::pytext::to_float(value).ok()
}

/// `str(StoreError)`, as `main` prints it.
pub fn store_error(error: car_store::Error) -> CliError {
    CliError(error.message())
}

fn failure(error: Failure) -> CliError {
    match error {
        Failure::Control(error) => {
            CliError(String::from_utf8_lossy(error.message.as_bytes()).into_owned())
        }
        Failure::Other(class) => CliError(class),
    }
}

/// `canonical_thread_id(value)`.
pub fn canonical_thread_id(value: &str) -> Result<String, CliError> {
    match car_machine::domain::ids::uuid_problem(&Value::from(value), true) {
        Some(problem) if problem == car_machine::vocab_gen::domain_ids::MALFORMED => Err(CliError(
            "thread id must be a canonical UUID (never --last or a name)".to_owned(),
        )),
        Some(_) => Err(CliError(
            "thread id must be lowercase canonical UUID text".to_owned(),
        )),
        None => Ok(value.to_owned()),
    }
}

/// `progress(step, done, total)`: the setup window's bar.
pub fn progress(machine: &Machine, io: &mut Io, step: &str, done: i64, total: i64) {
    if machine.env(PROGRESS_LINES).as_deref() != Some("1") || total <= 0 {
        return;
    }
    let _ = io
        .out
        .write_all(format!("progress: {step} {}/{total}\r\n", done.clamp(0, total)).as_bytes());
    let _ = io.out.flush();
}

fn text_of(value: Option<&Value>) -> String {
    match value {
        Some(Value::Str(text)) => String::from_utf8_lossy(text.as_bytes()).into_owned(),
        Some(Value::Null) | None => "None".to_owned(),
        Some(other) => car_machine::pytext::py_str(other),
    }
}

fn get<'a>(row: &'a Map, name: &str) -> &'a Value {
    row.get(name).unwrap_or(&Value::Null)
}

fn int_of(value: &Value) -> i64 {
    match value {
        Value::Int(int) => int.as_i64().unwrap_or(0),
        Value::Bool(on) => i64::from(*on),
        Value::Float(x) => *x as i64,
        _ => 0,
    }
}

// ------------------------------------------------------------------------------------------------ the table
/// What `main` was given: the global options.
pub struct Global<'a> {
    pub home: Option<&'a str>,
    pub codex_exe: Option<&'a str>,
    pub codex_home: Option<&'a str>,
    pub quiet: bool,
    pub command: &'a str,
}

/// `log_mark(args)`.
pub fn log_mark(host: &dyn Host, command: &str) -> String {
    if HEALTH_CHECKS.contains(&command) {
        format!("({command}, pid {}) ", host.pid())
    } else {
        String::new()
    }
}

/// `_app(args)`.
pub fn app_of(machine: &Machine, global: &Global) -> Result<App, CliError> {
    let paths = machine.paths(global.home).map_err(CliError)?;
    App::new(
        machine,
        paths,
        global.codex_exe,
        global.codex_home,
        !global.quiet,
        true,
        &log_mark(&*machine.host, global.command),
    )
}

/// `cli.main(argv)` over parsed arguments.
pub fn run(machine: &Machine, args: &Namespace, io: &mut Io) -> i32 {
    let text = |name: &str| args.get(name).text().map(str::to_owned);
    let home = text("home");
    let codex_exe = text("codex_exe");
    let codex_home = text("codex_home");
    let command = text("command").unwrap_or_default();
    let global = Global {
        home: home.as_deref(),
        codex_exe: codex_exe.as_deref(),
        codex_home: codex_home.as_deref(),
        quiet: args.get("quiet").on(),
        command: &command,
    };
    let done = match command.as_str() {
        "enable" => cmd_enable(machine, &global, args, io),
        "disable" => cmd_disable(machine, &global, args, io),
        "status" => cmd_status(machine, &global, io),
        "pending" => cmd_pending(machine, &global, args, io),
        "cancel" => cmd_cancel(machine, &global, args, io),
        "logs" => cmd_logs(machine, &global, args, io),
        "run" => cmd_run(machine, &global, args),
        "stop" => cmd_stop(machine, &global, io),
        "install" => cmd_install(machine, &global, args, io),
        "uninstall" => cmd_uninstall(machine, &global, args, io),
        "doctor" => cmd_doctor(machine, &global, io),
        "compat" => cmd_compat(machine, &global, args, io),
        "activate" => cmd_activate(machine, &global, args, io),
        "diagnostics" => cmd_diagnostics(machine, &global, args, io),
        "downgrade-state" => cmd_downgrade_state(machine, &global, args, io),
        _ => Err(CliError(format!("unknown command {command}"))),
    };
    match done {
        Ok(code) => code,
        Err(CliError(message)) => {
            io.warn(&format!("error: {message}"));
            EXIT_ERROR
        }
    }
}

// ------------------------------------------------------------------------------------------------ records.py
fn cmd_enable(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let mut app = app_of(machine, global)?;
    let thread = args.get("thread_id").text().map(str::to_owned);
    if thread.is_none() && app.host().managed().disable_auto_resume {
        return Err(CliError(
            "recovery is paused by your administrator (DisableAutoResume)".to_owned(),
        ));
    }
    if let crate::argparse::Got::Float(hours) = args.get("lookback_hours") {
        let mut changes = Map::new();
        changes.insert(Str::from("detection_lookback_hours"), Value::Float(*hours));
        let os = app.host().os();
        app.paths
            .ensure()
            .map_err(|raised| CliError(raised.message()))?;
        app.settings = car_policy::settings::update(
            &*os,
            Path::new(&app.paths.settings_file),
            &Value::Object(changes),
        )
        .map_err(|error| {
            CliError(String::from_utf8_lossy(error.message().as_bytes()).into_owned())
        })?;
    }
    let now = app.host().now();
    let opened = app.open_state()?;
    if let Some(thread) = thread {
        let thread = canonical_thread_id(&thread)?;
        match &opened {
            Opened::Store(store) => store
                .set_thread_enabled(&thread, true, "cli", None)
                .map_err(store_error)?,
            Opened::Legacy(store) => store
                .set_thread_enabled(&thread, true)
                .map_err(store_error)?,
        }
        drop(opened);
        app.info(io, &format!("thread {thread}: enabled by user"));
        io.say(&format!("thread {thread} enabled"));
    } else {
        match &opened {
            Opened::Store(store) => store.set_enabled(true, now).map_err(store_error)?,
            Opened::Legacy(store) => store.set_enabled(true, now).map_err(store_error)?,
        }
        drop(opened);
        let hours = app.setting_f64("detection_lookback_hours");
        app.info(
            io,
            &format!("auto-resume enabled by user (lookback {hours:.1}h)"),
        );
        io.say(&format!(
            "auto-resume enabled (lookback {hours:.1} h). Start the watcher with: run"
        ));
        if app.watcher_running() == Some(false) {
            io.say("note: no watcher is running; nothing will be resumed until `run` is started");
        }
    }
    Ok(EXIT_OK)
}

fn cmd_disable(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    let now = app.host().now();
    let opened = app.open_state()?;
    if let Some(thread) = args.get("thread_id").text() {
        let thread = canonical_thread_id(thread)?;
        match &opened {
            Opened::Store(store) => store
                .set_thread_enabled(&thread, false, "cli", None)
                .map_err(store_error)?,
            Opened::Legacy(store) => store
                .set_thread_enabled(&thread, false)
                .map_err(store_error)?,
        }
        // `_told_off`: the standard edition's plug has nothing to end.
        drop(opened);
        app.info(io, &format!("thread {thread}: disabled by user"));
        io.say(&format!(
            "thread {thread} disabled (pending records kept, never submitted while disabled)"
        ));
    } else {
        match &opened {
            Opened::Store(store) => store.set_enabled(false, now).map_err(store_error)?,
            Opened::Legacy(store) => store.set_enabled(false, now).map_err(store_error)?,
        }
        drop(opened);
        app.info(io, "auto-resume DISABLED by user (kill switch)");
        io.say("auto-resume disabled: no continuation will be queued until `enable`");
    }
    Ok(EXIT_OK)
}

/// `_record_view(row)`.
fn record_view(app: &App, row: &Map) -> Result<Map, CliError> {
    let record = Value::Object(row.clone());
    let local = |name: &str| -> Value {
        let value = get(row, name);
        if pyval::truthy(value) {
            Value::from(app.format_local(value))
        } else {
            Value::Null
        }
    };
    let code = car_machine::domain::public::public_code(&record)
        .map_err(|class| CliError(class.to_owned()))?;
    let reason = car_machine::domain::public::public_reason(&record)
        .map_err(|class| CliError(class.to_owned()))?;
    let mut view = Map::new();
    let mut put = |key: &str, value: Value| {
        view.insert(Str::from(key), value);
    };
    put("thread_id", get(row, "thread_id").clone());
    put("interruption_id", get(row, "interruption_id").clone());
    put("state", get(row, "state").clone());
    put("code", Value::from(code));
    put("reason", reason);
    put(
        "detected_at",
        Value::from(app.format_local(get(row, "detected_at"))),
    );
    put("reset_at", local("reset_at"));
    put("limit_type", get(row, "limit_type").clone());
    put("uncertain", get(row, "uncertain").clone());
    put("next_retry_at", local("next_retry_at"));
    put("retry_count", get(row, "retry_count").clone());
    put("attempt_count", get(row, "attempt_count").clone());
    put("resumed_at", local("resumed_at"));
    put("last_error", get(row, "last_error").clone());
    put("queue_id", get(row, "queue_id").clone());
    put("cancel_requested", get(row, "cancel_requested").clone());
    Ok(view)
}

/// `"%d" % value`.
fn percent_d(value: &Value) -> String {
    match value {
        Value::Int(int) => int.to_string(),
        Value::Bool(on) => i64::from(*on).to_string(),
        Value::Float(x) => format!("{}", x.trunc() as i128),
        _ => "0".to_owned(),
    }
}

fn cmd_pending(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    let store = app.open_store()?;
    let rows = if args.get("all").on() {
        store.all_records()
    } else {
        store.pending()
    }
    .map_err(store_error)?;
    let mut views = Vec::new();
    for row in &rows {
        let thread = text_of(Some(get(row, "thread_id")));
        let enabled = store.thread_enabled(&thread).map_err(store_error)?;
        let mut view = record_view(&app, row)?;
        view.insert(Str::from("thread_enabled"), Value::Bool(enabled));
        views.push(view);
    }
    drop(store);
    if args.get("json").on() {
        let listed = Value::Array(views.into_iter().map(Value::Object).collect());
        let text = to_string(&listed, &Options::wire().indent(2))
            .map_err(|_| CliError("Out of range float values are not JSON compliant".to_owned()))?;
        for line in text.split('\n') {
            io.say(line);
        }
        return Ok(EXIT_OK);
    }
    if views.is_empty() {
        io.say("no pending interruptions");
        return Ok(EXIT_OK);
    }
    for view in &views {
        let field = |name: &str| view.get(name).cloned().unwrap_or(Value::Null);
        io.say(&format!("thread {}", text_of(Some(&field("thread_id")))));
        io.say(&format!(
            "  status       : {}{}",
            text_of(Some(&field("code"))),
            if pyval::truthy(&field("thread_enabled")) {
                ""
            } else {
                "  (thread disabled)"
            }
        ));
        io.say(&format!(
            "  state        : {}",
            text_of(Some(&field("state")))
        ));
        io.say(&format!(
            "  detected     : {}",
            text_of(Some(&field("detected_at")))
        ));
        let reset = field("reset_at");
        let limit = field("limit_type");
        io.say(&format!(
            "  reset        : {}  [{}{}]",
            if pyval::truthy(&reset) {
                text_of(Some(&reset))
            } else {
                "unknown".to_owned()
            },
            if pyval::truthy(&limit) {
                text_of(Some(&limit))
            } else {
                "unknown".to_owned()
            },
            if pyval::truthy(&field("uncertain")) {
                ", uncertain"
            } else {
                ""
            }
        ));
        let next = field("next_retry_at");
        io.say(&format!(
            "  next check   : {}",
            if pyval::truthy(&next) {
                text_of(Some(&next))
            } else {
                "-".to_owned()
            }
        ));
        io.say(&format!(
            "  retries      : {} launch retries, {} reservations",
            percent_d(&field("retry_count")),
            percent_d(&field("attempt_count"))
        ));
        if pyval::truthy(&field("resumed_at")) {
            io.say(&format!(
                "  resumed      : {}",
                text_of(Some(&field("resumed_at")))
            ));
        }
        if pyval::truthy(&field("last_error")) {
            io.say(&format!(
                "  last reason  : {}",
                text_of(Some(&field("last_error")))
            ));
        }
        let key = text_of(Some(&field("interruption_id")));
        io.say(&format!(
            "  interruption : {}",
            key.chars().take(16).collect::<String>()
        ));
    }
    Ok(EXIT_OK)
}

fn cmd_cancel(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    let thread = canonical_thread_id(args.get("thread_id").text().unwrap_or_default())?;
    let now = app.host().now();
    let opened = app.open_state()?;
    let rows = match &opened {
        Opened::Store(store) => {
            store
                .cancel_thread(&thread, now, "cli")
                .map_err(store_error)?;
            store
                .all_records()
                .map_err(store_error)?
                .into_iter()
                .filter(|row| text_of(Some(get(row, "thread_id"))) == thread)
                .collect()
        }
        Opened::Legacy(store) => {
            store.cancel_thread(&thread, now).map_err(store_error)?;
            Vec::new()
        }
    };
    drop(opened);
    app.info(io, &format!("thread {thread}: cancel requested by user"));
    let terminal = car_machine::vocab_gen::domain_states::TERMINAL;
    let in_flight = rows
        .iter()
        .filter(|row| !terminal.contains(&text_of(Some(get(row, "state"))).as_str()))
        .count();
    io.say(&format!("thread {thread} cancelled and disabled"));
    if in_flight > 0 {
        io.say(&format!(
            "note: {in_flight} submission(s) already in flight will be reconciled and not resent"
        ));
    }
    Ok(EXIT_OK)
}

fn cmd_logs(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let paths = machine.paths(global.home).map_err(CliError)?;
    let count = args.get("lines").int().unwrap_or(0);
    let count = i64::try_from(count).unwrap_or(if count < 0 { i64::MIN } else { i64::MAX });
    for line in car_config::logbook::tail(Path::new(&paths.log_file), count) {
        io.say(&line);
    }
    Ok(EXIT_OK)
}

// ------------------------------------------------------------------------------------------------ watcher.py
fn cmd_run(machine: &Machine, global: &Global, args: &Namespace) -> Done {
    let app = app_of(machine, global)?;
    let poll = args.get("poll").int();
    Ok(machine
        .outside
        .run_watcher(&app.paths.home, args.get("once").on(), poll))
}

fn cmd_stop(machine: &Machine, global: &Global, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    if app.signal_stop() {
        for _ in 0..40 {
            if app.watcher_running() == Some(false) {
                break;
            }
            app.host().sleep(0.25);
        }
        io.say(&format!(
            "stop requested{}",
            if app.watcher_running() == Some(false) {
                "; watcher exited"
            } else {
                "; watcher still finishing"
            }
        ));
        return Ok(EXIT_OK);
    }
    io.say("no running watcher found");
    Ok(EXIT_OK)
}

fn cmd_activate(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    let uri = args.get("uri").text().unwrap_or_default().to_owned();
    match crate::uris::parse(&uri) {
        crate::uris::Activation::Chat(thread) => {
            let opened = machine.outside.open_chat(&app.paths.home, &thread);
            app.info(
                io,
                if opened {
                    "the chat opened from a notification"
                } else {
                    "activation: the Dashboard is not installed here"
                },
            );
            Ok(if opened { EXIT_OK } else { EXIT_ERROR })
        }
        crate::uris::Activation::Open(page) => {
            let opened = machine.outside.open_dashboard(&app.paths.home, &page);
            app.info(
                io,
                if opened {
                    "dashboard opened from a notification"
                } else {
                    "activation: the Dashboard is not installed here"
                },
            );
            Ok(if opened { EXIT_OK } else { EXIT_ERROR })
        }
        crate::uris::Activation::PowerStop => {
            let done = machine.outside.power_stop(&app.paths.home, &uri);
            Ok(if done == "stopped" {
                EXIT_OK
            } else {
                EXIT_ERROR
            })
        }
        crate::uris::Activation::Malformed => {
            app.info(io, "activation ignored: malformed or unsupported URI");
            Ok(EXIT_ERROR)
        }
        crate::uris::Activation::Cancel { id, open_codex } => {
            let deadline = app.host().monotonic() + CANCEL_RETRY_SECONDS;
            let thread = loop {
                match cancel_once(&app, &id, io) {
                    Ok(Ok(thread)) => break thread,
                    Ok(Err(code)) => return Ok(code),
                    Err(_) => {
                        if app.host().monotonic() >= deadline {
                            app.info(
                                io,
                                "activation: the state stayed busy; the cancel was not recorded",
                            );
                            return Ok(EXIT_ERROR);
                        }
                        app.host().sleep(0.5);
                    }
                }
            };
            app.info(
                io,
                &format!("thread {thread}: cancelled from the notification"),
            );
            // `_open_codex_on`: never in the standard edition.
            let _ = open_codex;
            machine.outside.announce_cancelled(&thread, false);
            io.say(&format!("thread {thread} cancelled"));
            Ok(EXIT_OK)
        }
    }
}

/// One try of the activation's cancel: the thread, an exit code already decided, or a busy store (retried).
fn cancel_once(app: &App, id: &str, io: &mut Io) -> Result<Result<String, i32>, ()> {
    let now = app.host().now();
    let opened = app.open_state().map_err(|_| ())?;
    match &opened {
        Opened::Legacy(store) => {
            let thread = store.thread_of(id).map_err(|_| ())?;
            let Value::Str(thread) = thread else {
                drop(opened);
                app.info(io, "activation ignored: no record for that interruption");
                return Ok(Err(EXIT_ERROR));
            };
            let thread = String::from_utf8_lossy(thread.as_bytes()).into_owned();
            store.cancel_thread(&thread, now).map_err(|_| ())?;
            Ok(Ok(thread))
        }
        Opened::Store(store) => {
            let Some(record) = store.get(id).map_err(|_| ())? else {
                drop(opened);
                app.info(io, "activation ignored: no record for that interruption");
                return Ok(Err(EXIT_ERROR));
            };
            let thread = text_of(Some(get(&record, "thread_id")));
            let result = store
                .cancel_interruption(id, now, "toast")
                .map_err(|_| ())?;
            if let Some(map) = &result
                && map.get("changed") == Some(&Value::Bool(false))
            {
                drop(opened);
                app.info(
                    io,
                    &format!(
                        "thread {thread}: the notification's cancel changed nothing; it had already finished"
                    ),
                );
                io.say(&format!(
                    "thread {thread} had already finished; nothing changed"
                ));
                return Ok(Err(EXIT_OK));
            }
            Ok(Ok(thread))
        }
    }
}

// ------------------------------------------------------------------------------------------------ status.py
fn view_status(app: &App, view: &Value) -> String {
    let status = match view {
        Value::Object(map) => map.get("status").cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let word = status.clone();
    let text = match word.as_str_value() {
        Some("ok") => "report ok",
        Some("absent") => "no report yet - is the watcher running?",
        Some("invalid") => "report unreadable",
        Some("stale") => "report too old - is the watcher ticking?",
        Some("engine_changed") => "the engine changed since the last check",
        _ => "report unreadable",
    };
    let mut text = text.to_owned();
    let field = |name: &str| match view {
        Value::Object(map) => map.get(name).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    if status.as_str_value() == Some("ok") && pyval::truthy(&field("checked_at")) {
        text.push_str(&format!(
            ", checked {}",
            app.format_local(&field("checked_at"))
        ));
    }
    let acting = field("acting");
    if pyval::truthy(&acting) && acting != field("overall") {
        text.push_str(&format!(
            "; the watcher is still acting on {} - restart it to re-check",
            text_of(Some(&acting))
        ));
    }
    text
}

trait StrValue {
    fn as_str_value(&self) -> Option<&str>;
}

impl StrValue for Value {
    fn as_str_value(&self) -> Option<&str> {
        match self {
            Value::Str(text) => text.as_str(),
            _ => None,
        }
    }
}

/// `_ENGINE_WORDS[word]` (short, long), or `_ENGINE_CHECKS_ONLY`.
fn engine_words(word: Option<&str>) -> (&'static str, &'static str) {
    match word {
        Some("verified") => (
            "verified by the registry data in force: a real recovery on this build confirmed it",
            "verified: its local checks pass, and the registry data in force verifies this build",
        ),
        Some("checked") => (
            "checked: local checks pass, and the maintainer's checks passed on this build",
            "checked: its local checks pass, and the registry data in force records the maintainer's checks passing on this build; no real recovery has verified it yet",
        ),
        Some("structurally_compatible") => (
            "compatible: local checks pass; the registry data in force does not verify this build",
            "compatible: its local checks pass - `codex queue` still offers --thread/--message - and the registry data in force does not verify this build",
        ),
        Some("incompatible") => (
            "local checks pass, but the registry data in force marks this build incompatible",
            "its local checks pass, but the registry data in force marks this build incompatible; nothing is sent while that data is in force",
        ),
        Some("failed_here") => (
            "a local check failed here, on a build the registry data in force vouches for",
            "a local check failed here, on a build the registry data in force vouches for",
        ),
        _ => (
            "local checks pass",
            "its local checks pass - `codex queue` still offers --thread/--message",
        ),
    }
}

/// `_reported_words(view)`.
fn reported_words(view: &Value) -> String {
    let reported = match view {
        Value::Object(map) => match map.get("reported") {
            Some(Value::Object(reported)) => reported.clone(),
            _ => Map::new(),
        },
        _ => Map::new(),
    };
    let qualifier = " (others' reports; changes nothing)";
    match reported.get("state").and_then(StrValue::as_str_value) {
        Some("reported") => {
            let count = |name: &str| match reported.get(name) {
                Some(value @ Value::Int(_)) => percent_d(value),
                Some(Value::Bool(on)) => i64::from(*on).to_string(),
                _ => "0".to_owned(),
            };
            let mut text = format!(
                "worked {}, failed {}, neither {}",
                count("worked"),
                count("failed"),
                count("neither")
            );
            let both = count("both");
            if both.parse::<i128>().map(|each| each > 0).unwrap_or(true) {
                text.push_str(&format!(", counted in both {both}"));
            }
            text + qualifier
        }
        Some("none_yet") => format!("none yet{qualifier}"),
        Some("rejected") => format!("could not be read{qualifier}"),
        _ => "-".to_owned(),
    }
}

/// `_capability_lines(view, only_problems=...)`.
fn capability_lines(view: &Value, only_problems: bool) -> Result<Vec<String>, CliError> {
    let mut lines = Vec::new();
    let Value::Object(view) = view else {
        return Err(CliError("TypeError".to_owned()));
    };
    let Some(Value::Object(capabilities)) = view.get("capabilities") else {
        return Err(CliError("KeyError".to_owned()));
    };
    for (name, entry) in capabilities {
        let Value::Object(entry) = entry else {
            return Err(CliError(
                "TypeError: an entry is not subscriptable".to_owned(),
            ));
        };
        let reason = text_of(Some(&index(&Value::Object(entry.clone()), "reason")?));
        if reason == "not_implemented" {
            continue;
        }
        let state = text_of(Some(&index(&Value::Object(entry.clone()), "state")?));
        if only_problems && ["COMPATIBLE", "CHECKED", "VERIFIED"].contains(&state.as_str()) {
            continue;
        }
        let detail = match entry.get("registry_reason") {
            Some(value) if pyval::truthy(value) => format!("{reason} ({})", text_of(Some(value))),
            _ => reason,
        };
        lines.push(format!(
            "  {:<26} {:<12} {detail}",
            String::from_utf8_lossy(name.as_bytes()),
            state
        ));
    }
    Ok(lines)
}

fn compat_view(app: &App) -> Value {
    app.host().compat_view(&app.state_dir(), &app.settings)
}

/// `view[name]`: a TypeError for a view that is not a dict, a KeyError for a missing key (the reference's traceback).
fn index(view: &Value, name: &str) -> Result<Value, CliError> {
    match view {
        Value::Object(map) => map
            .get(name)
            .cloned()
            .ok_or_else(|| CliError(format!("KeyError: '{name}'"))),
        _ => Err(CliError(
            "TypeError: the view is not subscriptable".to_owned(),
        )),
    }
}

fn view_field(view: &Value, name: &str) -> Value {
    match view {
        Value::Object(map) => map.get(name).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    }
}

fn cmd_status(machine: &Machine, global: &Global, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    let store = app.open_store()?;
    let settings = store.settings().map_err(store_error)?;
    let counts = store.status_counts().map_err(store_error)?;
    let pending = store.pending().map_err(store_error)?;
    drop(store);
    let running = app.watcher_running();
    let enabled = pyval::truthy(get(&settings, "enabled"));
    io.say(&format!(
        "auto-resume      : {}",
        if enabled { "ENABLED" } else { "disabled" }
    ));
    if enabled {
        io.say(&format!(
            "enabled since    : {}",
            app.format_local(get(&settings, "armed_at"))
        ));
    }
    io.say(&format!(
        "watcher          : {}",
        match running {
            Some(true) => "running",
            Some(false) => "not running",
            None => "unknown",
        }
    ));
    match app.host().startup_read() {
        Ok(value) => io.say(&format!(
            "login autostart  : {}",
            if value.is_some_and(|each| !each.is_empty()) {
                "registered"
            } else {
                "not registered"
            }
        )),
        Err(_) => io.say("login autostart  : unavailable"),
    }
    match machine
        .outside
        .backend(app.codex_exe_override.as_deref(), &app.codex_home)
    {
        Ok(backend) => {
            io.say(&format!("codex engine     : {}", backend.codex_exe));
            let word = machine
                .outside
                .engine_word(&app.state_dir(), &backend.engine_version);
            io.say(&format!(
                "engine version   : {}  ({})",
                backend.engine_version,
                engine_words(word.as_deref()).0
            ));
            let paired = machine.outside.app_paired(&backend);
            let elsewhere =
                if paired.identity.is_some() && paired.looked.codex_exe != backend.codex_exe {
                    format!("; {ELSEWHERE_SHORT}")
                } else {
                    String::new()
                };
            io.say(&format!(
                "ChatGPT app      : {}",
                match paired.identity {
                    Some((pid, server)) =>
                        format!("running (pid {pid}, codex server pid {server}{elsewhere})"),
                    None if paired.app_look == "unmatched" => UNMATCHED_APP.to_owned(),
                    None => "not running / not paired".to_owned(),
                }
            ));
        }
        Err(raised) => io.say(&format!(
            "codex engine     : unavailable ({})",
            raised.message
        )),
    }
    let view = compat_view(&app);
    let overall = index(&view, "overall")?;
    io.say(&format!(
        "compatibility    : {} ({})",
        text_of(Some(&overall)),
        view_status(&app, &view)
    ));
    io.say(&format!("pending          : {}", pending.len()));
    let mut states: Vec<(&Str, &Value)> = counts.iter().collect();
    states.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
    for (state, count) in states {
        io.say(&format!(
            "  {:<22} {}",
            String::from_utf8_lossy(state.as_bytes()),
            percent_d(count)
        ));
    }
    io.say(&format!(
        "lookback         : {:.1} h",
        app.setting_f64("detection_lookback_hours")
    ));
    io.say(&format!(
        "state file       : {}",
        Path::new(&app.paths.state_dir)
            .join("state.sqlite")
            .display()
    ));
    io.say(&format!("log file         : {}", app.paths.log_file));
    Ok(EXIT_OK)
}

/// `_autostart_line()`: (ok, line).
fn autostart_line(app: &App) -> (bool, String) {
    match app.host().startup_read() {
        Ok(None) => (true, "autostart        : not registered".to_owned()),
        Ok(Some(value)) if value.is_empty() => {
            (true, "autostart        : not registered".to_owned())
        }
        Ok(Some(value)) => {
            let argv = car_platform::cmdline::parse_command(&value);
            let script = car_platform::cmdline::script_index(&argv);
            let mut parts: Vec<&String> = argv.iter().take(1).collect();
            if let Some(each) = argv.get(script) {
                parts.push(each);
            }
            let missing: Vec<&&String> = parts
                .iter()
                .filter(|part| !Path::new(part.as_str()).exists())
                .collect();
            if let Some(first) = missing.first() {
                let which = if argv.first() == Some(**first) {
                    "its interpreter"
                } else {
                    "its launcher"
                };
                return (
                    false,
                    format!(
                        "autostart        : registered, but {which} is missing (run install again)"
                    ),
                );
            }
            (true, "autostart        : registered".to_owned())
        }
        Err(raised) => (
            true,
            format!("autostart        : unavailable ({})", raised.class),
        ),
    }
}

fn cmd_doctor(machine: &Machine, global: &Global, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    let mut failed: Vec<String> = Vec::new();
    let fail = |failed: &mut Vec<String>, io: &mut Io, line: String| {
        io.say(&line);
        failed.push(line);
    };
    let outside = &machine.outside;
    let backend = match outside.backend(app.codex_exe_override.as_deref(), &app.codex_home) {
        Ok(backend) => {
            io.say(&format!("codex.exe        : {}", backend.codex_exe));
            let word = outside.engine_word(&app.state_dir(), &backend.engine_version);
            io.say(&format!(
                "engine version   : {} ({})",
                backend.engine_version,
                engine_words(word.as_deref()).1
            ));
            Some(backend)
        }
        Err(raised) => {
            if outside.app_running_now() != Some(false) {
                let line = format!("codex.exe        : FAIL ({})", raised.message);
                fail(&mut failed, io, line);
                io.say(&format!("{PROBLEM}{}", words_joined(&failed[0])));
                return Ok(EXIT_ERROR);
            }
            io.say(&format!("codex.exe        : {CLOSED_ENGINE}"));
            None
        }
    };
    if let Some(backend) = &backend {
        progress(machine, io, "check", 1, DOCTOR_CHECKS);
        let live = match outside.doctor_live_view(&app.state_dir(), &app.codex_home, backend) {
            Ok(Value::Null) => None,
            Ok(view) => Some(view),
            Err(raised) => {
                io.say(&format!(
                    "compatibility    : unavailable ({})",
                    raised.class
                ));
                None
            }
        };
        if let Some(live) = &live {
            let overall = text_of(Some(&index(live, "overall")?));
            io.say(&format!("compatibility    : {overall} (checked now)"));
            for line in capability_lines(live, true)? {
                io.say(&line);
            }
            if overall == "incompatible" || overall == "failed_here" {
                failed.push(format!("compatibility    : {overall} (checked now)"));
            }
        }
        progress(machine, io, "check", 2, DOCTOR_CHECKS);
        let report = compat_view(&app);
        io.say(&format!(
            "watcher's report : {} ({})",
            text_of(Some(&index(&report, "overall")?)),
            view_status(&app, &report)
        ));
        io.say(&format!(
            "reported         : {}",
            reported_words(live.as_ref().unwrap_or(&report))
        ));
        progress(machine, io, "check", 3, DOCTOR_CHECKS);
        io.say(&format!("codex home       : {}", app.codex_home));
        let paired = outside.app_paired(backend);
        match paired.identity {
            Some((pid, server)) => {
                io.say(&format!(
                    "ChatGPT app      : main pid {pid}, codex app-server pid {server}"
                ));
                if paired.looked.codex_exe != backend.codex_exe {
                    io.say(&format!(
                        "                   {ELSEWHERE_SHORT}: {} ({})",
                        paired.looked.codex_exe, paired.looked.engine_version
                    ));
                }
            }
            None if paired.app_look == "closed" => {
                io.say(&format!("ChatGPT app      : {CLOSED_APP}"))
            }
            None => {
                let line = format!(
                    "ChatGPT app      : {}",
                    if paired.app_look == "unmatched" {
                        UNMATCHED_APP
                    } else {
                        "not running or not paired with the configured engine"
                    }
                );
                fail(&mut failed, io, line);
            }
        }
        progress(machine, io, "check", 4, DOCTOR_CHECKS);
    }
    io.say(&format!(
        "watcher mutex    : {}",
        match app.watcher_running() {
            Some(true) => "held by a running watcher",
            Some(false) => "free",
            None => "unavailable",
        }
    ));
    progress(machine, io, "check", 5, DOCTOR_CHECKS);
    let probe = Path::new(&app.codex_home)
        .join("thread-writer-locks")
        .join(".coordination.lock");
    if probe.exists() {
        match outside.resource_users(&probe) {
            None => io.say("restart manager  : ok"),
            Some(message) => {
                let line = format!("restart manager  : FAIL ({message})");
                fail(&mut failed, io, line);
            }
        }
    } else {
        io.say("restart manager  : skipped (no coordination lock file)");
    }
    progress(machine, io, "check", 6, DOCTOR_CHECKS);
    match outside.history(&app.codex_home, app.host().now() - 60.0) {
        History::Readable => io.say("local history    : readable"),
        History::NotYet => io.say(&format!("local history    : {HISTORY_NOT_YET}")),
        History::Failed(class) => {
            let line = format!("local history    : FAIL ({class})");
            fail(&mut failed, io, line);
        }
    }
    progress(machine, io, "check", 7, DOCTOR_CHECKS);
    match app.host().protocol_value() {
        Ok(None) => io.say("notification action: not registered (the button would do nothing)"),
        Ok(Some(value)) if value.is_empty() => {
            io.say("notification action: not registered (the button would do nothing)")
        }
        Ok(Some(registered)) => {
            let argv = car_platform::cmdline::parse_command(&registered);
            let script = car_platform::cmdline::script_index(&argv);
            match argv.get(script) {
                Some(target) if !Path::new(target).exists() => {
                    fail(
                        &mut failed,
                        io,
                        "notification action: registered, but its target is missing".to_owned(),
                    );
                    io.say("                     re-run install to point it at this installation");
                }
                _ => io.say("notification action: registered"),
            }
        }
        Err(raised) => io.say(&format!(
            "notification action: unavailable ({})",
            raised.message
        )),
    }
    let (good, line) = autostart_line(&app);
    if good {
        io.say(&line);
    } else {
        fail(&mut failed, io, line);
    }
    progress(machine, io, "check", 8, DOCTOR_CHECKS);
    if let Some(first) = failed.first() {
        io.say(&format!("{PROBLEM}{}", words_joined(first)));
    }
    Ok(if failed.is_empty() {
        EXIT_OK
    } else {
        EXIT_ERROR
    })
}

/// `" ".join(text.split())`.
fn words_joined(text: &str) -> String {
    text.split(car_machine::pytext::is_space)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

fn cmd_compat(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    if let Some(file) = args.get("import_file").text() {
        let result = app
            .host()
            .compat_import(&app.state_dir(), &Str::from(file), &Value::from("file"))
            .map_err(|raised| CliError(raised.message))?;
        if pyval::truthy(&view_field(&result, "imported")) {
            let _ = app.host().signal(Event::Wake, &app.state_dir());
            io.say(&format!(
                "imported registry data #{} (cache {})",
                text_of(Some(&view_field(&result, "sequence"))),
                text_of(Some(&view_field(&result, "cache")))
            ));
            return Ok(EXIT_OK);
        }
        io.say(&format!(
            "refused: {}; the existing cache was left as it was",
            text_of(Some(&view_field(&result, "reason")))
        ));
        return Ok(EXIT_ERROR);
    }
    let view = if args.get("live").on() {
        let explicit = app.codex_exe_override.clone().or_else(|| {
            machine
                .env("CODEX_AUTO_RESUME_CODEX_EXE")
                .filter(|each| !each.is_empty())
        });
        app.host()
            .compat_live_view(
                &app.state_dir(),
                &app.codex_home,
                &explicit.map_or(Value::Null, Value::from),
            )
            .map_err(|raised| CliError(raised.message))?
    } else {
        compat_view(&app)
    };
    if args.get("json").on() {
        let text = to_string(&view, &Options::wire().indent(2))
            .map_err(|_| CliError("Out of range float values are not JSON compliant".to_owned()))?;
        for line in text.split('\n') {
            io.say(line);
        }
        return Ok(EXIT_OK);
    }
    let overall = index(&view, "overall")?;
    io.say(&format!(
        "compatibility    : {} ({})",
        text_of(Some(&overall)),
        if pyval::truthy(&view_field(&view, "live")) {
            "checked now".to_owned()
        } else {
            view_status(&app, &view)
        }
    ));
    let engine = index(&view, "engine")?;
    let version = index(&engine, "version")?;
    io.say(&format!(
        "engine version   : {}",
        if pyval::truthy(&version) {
            text_of(Some(&version))
        } else {
            "not found".to_owned()
        }
    ));
    io.say(&format!("reported         : {}", reported_words(&view)));
    let data = view_field(&view, "data");
    if pyval::truthy(&data) {
        let sequence = view_field(&data, "cache_sequence");
        io.say(&format!(
            "registry data    : {} (bundled {} #{}, cache {}{})",
            text_of(Some(&index(&data, "source")?)),
            text_of(Some(&index(&data, "bundled")?)),
            text_of(Some(&index(&data, "bundled_sequence")?)),
            text_of(Some(&index(&data, "cache")?)),
            if matches!(sequence, Value::Null) {
                String::new()
            } else {
                format!(" #{}", text_of(Some(&sequence)))
            }
        ));
    }
    for line in capability_lines(&view, false)? {
        io.say(&line);
    }
    Ok(EXIT_OK)
}

// ------------------------------------------------------------------------------------------------ install.py
/// The command line that starts this installation's watcher at sign-in: the Rust host, every word quoted, with the
/// home (S8.2's finding: v0.6.26's `setup --keep-state` re-registers only a value `startup.belongs_to` knows).
pub fn watcher_command(home: &str) -> String {
    let host = Path::new(home)
        .join("app")
        .join("bin")
        .join("CodexAutoResume.exe");
    quote_all(&[
        host.to_string_lossy().into_owned(),
        "--home".into(),
        home.to_owned(),
        "run".into(),
    ])
}

/// The link handler: `"<home>\app\bin\codex-auto-resume.exe" "--home" "<home>" "activate" "%1"` (PLAN 6.4).
pub fn protocol_command(home: &str) -> String {
    let core = Path::new(home)
        .join("app")
        .join("bin")
        .join("codex-auto-resume.exe");
    format!(
        "{} \"%1\"",
        quote_all(&[
            core.to_string_lossy().into_owned(),
            "--home".into(),
            home.to_owned(),
            "activate".into()
        ])
    )
}

fn quote_all(argv: &[String]) -> String {
    argv.iter()
        .map(|each| car_platform::cmdline::quote_argument(each))
        .collect::<Vec<_>>()
        .join(" ")
}

/// `_what_the_entry_opens(paths)`.
pub fn what_the_entry_opens(paths: &Paths) -> crate::seam::Opens {
    let icon = Path::new(&paths.icon_file)
        .is_file()
        .then(|| paths.icon_file.clone());
    let window = Path::new(&paths.home).join("CodexAutoResumeSettings.exe");
    if window.is_file() {
        return crate::seam::Opens {
            target: window.to_string_lossy().into_owned(),
            arguments: None,
            icon,
            description: "Codex Auto Resume Settings".to_owned(),
        };
    }
    // No settings window: the Start-menu entry runs `status`, as the reference's does, through the Rust core.
    let core = Path::new(&paths.home)
        .join("app")
        .join("bin")
        .join("codex-auto-resume.exe");
    crate::seam::Opens {
        target: core.to_string_lossy().into_owned(),
        arguments: Some(quote_all(&[
            "--home".into(),
            paths.home.clone(),
            "status".into(),
        ])),
        icon,
        description: "Codex Auto Resume".to_owned(),
    }
}

fn cmd_install(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    let opened = app.open_state()?;
    let enabled = match &opened {
        Opened::Store(store) => {
            pyval::truthy(get(&store.settings().map_err(store_error)?, "enabled"))
        }
        Opened::Legacy(store) => {
            pyval::truthy(get(&store.settings().map_err(store_error)?, "enabled"))
        }
    };
    drop(opened);
    io.say(&format!("owned state directory : {}", app.paths.state_dir));
    io.say(&format!("owned log directory   : {}", app.paths.logs_dir));
    if let Some(previous) = args.get("edition_from").text() {
        // `_edition_changed`: the standard edition's plug has nothing to do.
        if previous == "standard" {
            io.say("edition               : standard (unchanged)");
        } else {
            app.info(io, &format!("edition changed from {previous} to standard"));
            io.say(&format!(
                "edition               : standard (was {previous})"
            ));
        }
    }
    forget_edition_left(&app.paths);
    if args.get("startup").on() {
        let command = watcher_command(&app.paths.home);
        let changed = app
            .host()
            .startup_install(&command)
            .map_err(|raised| CliError(raised.message))?;
        app.info(
            io,
            &format!(
                "login autostart {}",
                if changed {
                    "registered"
                } else {
                    "already registered"
                }
            ),
        );
        io.say(&format!(
            "login autostart       : {}",
            if changed {
                "registered"
            } else {
                "already registered (unchanged)"
            }
        ));
        io.say(&format!("  {command}"));
    } else {
        io.say("login autostart       : not requested (use install --startup to opt in)");
    }
    let notifications = app.settings.get("notifications").is_none_or(pyval::truthy);
    if notifications {
        let icon = Path::new(&app.paths.icon_file)
            .is_file()
            .then(|| app.paths.icon_file.clone());
        let registered = machine
            .outside
            .register_aumid(icon.as_deref())
            .map_err(|raised| raised.message)
            .and_then(|_| {
                machine
                    .outside
                    .shortcut_install(&what_the_entry_opens(&app.paths))
                    .map_err(|failure| match failure {
                        ShortcutFailure::Taken(text) | ShortcutFailure::Failed(text) => text,
                    })
            });
        match registered {
            Ok(_) => {
                io.say(&format!(
                    "notification sender   : {}",
                    car_platform::startup::AUMID_DISPLAY_NAME
                ));
                io.say(&format!(
                    "start menu entry      : {}",
                    machine.outside.shortcut_name()
                ));
            }
            Err(message) => io.say(&format!("notification sender   : unavailable ({message})")),
        }
        match machine
            .outside
            .install_protocol(&protocol_command(&app.paths.home))
        {
            Ok(changed) => io.say(&format!(
                "notification action   : {}",
                if changed {
                    "registered"
                } else {
                    "already registered (unchanged)"
                }
            )),
            Err(raised) => io.say(&format!(
                "notification action   : unavailable ({})",
                raised.message
            )),
        }
    } else {
        io.say("notification action   : notifications are disabled in settings");
    }
    io.say(&format!(
        "auto-resume is {}; use `enable` then `run`.",
        if enabled { "enabled" } else { "disabled" }
    ));
    Ok(EXIT_OK)
}

/// `_note_edition_left(paths)`.
pub fn note_edition_left(paths: &Paths, io: &mut Io, pid: u32) {
    let target = &paths.edition_left_file;
    if !paths.owns(&paths.state_dir) || car_config::paths::is_link(target) {
        return;
    }
    let parent = Path::new(target)
        .parent()
        .map(|each| each.to_string_lossy().into_owned())
        .unwrap_or_default();
    if !paths.confined(&parent) {
        return;
    }
    let temporary = Path::new(&paths.state_dir).join(format!("edition-left.{pid}.tmp"));
    let written = std::fs::write(&temporary, b"standard\r\n")
        .and_then(|_| std::fs::rename(&temporary, Path::new(target)));
    if written.is_err() {
        io.say("warning: could not note which edition was uninstalled; reinstalling it starts its features off");
        let _ = std::fs::remove_file(&temporary);
    }
}

/// `_forget_edition_left(paths)`.
pub fn forget_edition_left(paths: &Paths) {
    let target = &paths.edition_left_file;
    if Path::new(target).is_file() && !car_config::paths::is_link(target) && paths.confined(target)
    {
        let _ = std::fs::remove_file(target);
    }
}

fn cmd_uninstall(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let paths = machine.paths(global.home).map_err(CliError)?;
    let app = App::new(machine, paths.clone(), None, None, false, false, "")?;
    let host = app.host();
    let mut removed: Vec<String> = Vec::new();
    let mut foreign = None;
    if app.signal_stop() {
        for _ in 0..60 {
            if app.watcher_running() == Some(false) {
                break;
            }
            host.sleep(0.25);
        }
    }
    let running = app.watcher_running();
    if running != Some(false) {
        io.say(if running == Some(true) {
            "a watcher is still running"
        } else {
            "watcher state could not be verified"
        });
        io.say("uninstall aborted before removing anything; stop the watcher and retry");
        return Ok(EXIT_ERROR);
    }
    match host.startup_read() {
        Ok(None) => {}
        Ok(Some(value)) => {
            if car_platform::startup::belongs_to(&value, &paths.home) {
                if host
                    .startup_uninstall()
                    .map_err(|raised| CliError(raised.message))?
                {
                    removed.push("login autostart value".to_owned());
                }
            } else {
                foreign = Some(value);
            }
        }
        Err(raised) => io.say(&format!("warning: {}", raised.message)),
    }
    let owner = match host.notification_identity_owner(&paths.home) {
        Ok(owner) => owner,
        Err(raised) => {
            io.say(&format!("warning: {}", raised.message));
            Some(false)
        }
    };
    if owner == Some(false) {
        io.say("kept the notification identity and Start Menu entry: they belong to a different installation");
    } else {
        match machine.outside.unregister_aumid() {
            Ok(true) => removed.push("notification sender identity".to_owned()),
            Ok(false) => {}
            Err(raised) => io.say(&format!("warning: {}", raised.message)),
        }
        if machine.outside.shortcut_uninstall() {
            removed.push("start menu entry".to_owned());
        }
    }
    match machine.outside.desktop_uninstall(&paths.home) {
        Ok(true) => removed.push("desktop shortcut".to_owned()),
        Ok(false) => {}
        Err(ShortcutFailure::Taken(text) | ShortcutFailure::Failed(text)) => {
            io.say(&format!("warning: {text}"))
        }
    }
    match host.protocol_value() {
        Ok(Some(registered)) if !registered.is_empty() => {
            if car_platform::startup::belongs_to(&registered, &paths.home) {
                match machine.outside.uninstall_protocol() {
                    Ok(true) => removed.push("notification action registration".to_owned()),
                    Ok(false) => {}
                    Err(raised) => io.say(&format!("warning: {}", raised.message)),
                }
            } else {
                io.say(
                    "kept the codex-auto-resume: protocol: it points at a different installation",
                );
            }
        }
        Ok(_) => {}
        Err(raised) => io.say(&format!("warning: {}", raised.message)),
    }
    if machine
        .env(car_platform::addremove::KEEP_ENTRY_ENV)
        .is_none_or(|each| each.is_empty())
    {
        match machine.outside.addremove_unregister(&paths.home) {
            Ok(true) => removed.push("entry in Add or remove programs".to_owned()),
            Ok(false) => {}
            Err(raised) => io.say(&format!("warning: {}", raised.message)),
        }
    }
    let keep_state = args.get("keep_state").on();
    let keep_logs = args.get("keep_logs").on();
    let edition_state: Vec<String> = if car_config::paths::is_link(&paths.advanced_dir) {
        Vec::new()
    } else {
        vec![paths.advanced_dir.clone()]
    };
    let mut considered: Vec<String> = Vec::new();
    if !keep_logs {
        considered.push(paths.logs_dir.clone());
    }
    if !keep_state {
        considered.extend(edition_state);
        considered.push(paths.state_dir.clone());
    }
    let mut owned_dirs: Vec<String> = considered
        .iter()
        .filter(|each| paths.owns(each))
        .cloned()
        .collect();
    let skipped: Vec<String> = considered
        .iter()
        .filter(|each| Path::new(each).is_dir() && !paths.owns(each))
        .cloned()
        .collect();
    let mut targets: Vec<String> = if keep_state {
        Vec::new()
    } else {
        let mut all = paths.owned_state_files();
        all.extend(paths.owned_account_files());
        all
    };
    if !keep_state {
        let mut first = paths.owned_account_dirs();
        first.extend(owned_dirs);
        owned_dirs = first;
    }
    if !keep_logs {
        targets.extend(paths.owned_log_files());
    }
    for path in &targets {
        if Path::new(path).is_file() && !car_config::paths::is_link(path) && paths.confined(path) {
            if std::fs::remove_file(path).is_ok() {
                removed.push(path.clone());
            } else {
                io.say(&format!("warning: could not delete {path}"));
            }
        }
    }
    for directory in &owned_dirs {
        let empty = std::fs::read_dir(directory).is_ok_and(|mut entries| entries.next().is_none());
        if Path::new(directory).is_dir() && empty {
            let _ = std::fs::remove_dir(directory);
        }
    }
    io.say(&format!(
        "removed: {}",
        if removed.is_empty() {
            "nothing (already clean)".to_owned()
        } else {
            removed.join(", ")
        }
    ));
    if keep_state {
        note_edition_left(&paths, io, host.pid());
        io.say(&format!(
            "kept your settings and pending recoveries in {}",
            paths.state_dir
        ));
    }
    for directory in skipped {
        io.say(&format!(
            "skipped {directory} (no provenance marker; not created by this tool, nothing deleted there)"
        ));
    }
    if let Some(value) = foreign {
        io.say("kept the login autostart value: it starts a different installation, not this one");
        io.say(&format!("  {value}"));
    }
    io.say("ChatGPT/Codex files and repositories were not touched");
    Ok(EXIT_OK)
}

fn cmd_diagnostics(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let paths = machine.paths(global.home).map_err(CliError)?;
    let control = machine.control(paths);
    let target = match args.get("out").text() {
        Some(out) => PathBuf::from(out),
        None => std::env::current_dir().unwrap_or_default().join(format!(
            "codex-auto-resume-diagnostics-{}.json",
            stamp(&*machine.host, "%Y%m%d-%H%M%S")
        )),
    };
    if target.exists() {
        let name = target
            .file_name()
            .map(|each| each.to_string_lossy().into_owned())
            .unwrap_or_default();
        return Err(CliError(format!("refusing to overwrite {name}")));
    }
    let written = control.write_bundle(&target).map_err(failure)?;
    io.say(&format!("diagnostics written to {}", written.display()));
    io.say("ids are aliases and paths are removed; read the file before sharing it");
    Ok(EXIT_OK)
}

/// `app.mutex(timeout)` held, or the AdapterError's text.
fn with_mutex<T>(app: &App, timeout: f64, work: impl FnOnce() -> T) -> Result<T, String> {
    let guard = app
        .machine
        .outside
        .watcher_mutex(&app.state_dir(), timeout)
        .map_err(|raised| raised.message)?;
    let done = work();
    drop(guard);
    Ok(done)
}

fn cmd_downgrade_state(machine: &Machine, global: &Global, args: &Namespace, io: &mut Io) -> Done {
    let app = app_of(machine, global)?;
    let target = i64::try_from(args.get("to").int().unwrap_or(0)).unwrap_or(0);
    let links = car_control::host::Probe;
    if args.get("stop_watcher").on() {
        if app.signal_stop() {
            app.info(io, "downgrade-state asked the watcher to stop");
        }
        let done = with_mutex(&app, STOP_WAIT_SECONDS, || {
            car_store::downgrade::downgrade_state(&app.state_dir(), target, &links)
        });
        let result = match done {
            Err(message) if message == "mutex_busy" => {
                io.say("downgrade: watcher-running");
                return Ok(EXIT_WATCHER_RUNNING);
            }
            Err(_) | Ok(Err(_)) => {
                io.say("downgrade: failed");
                return Ok(EXIT_ERROR);
            }
            Ok(Ok(result)) => result,
        };
        if !pyval::truthy(get(&result, "changed")) {
            io.say("downgrade: nothing");
            return Ok(EXIT_OK);
        }
        app.info(
            io,
            &format!(
                "state downgraded to schema {target} ({} records kept)",
                percent_d(get(&result, "rows"))
            ),
        );
        io.say(&format!(
            "downgrade: converted {} {} {} {} {}",
            percent_d(get(&result, "rows")),
            percent_d(result.get("made_final").unwrap_or(&Value::from(0))),
            percent_d(result.get("conversations_off").unwrap_or(&Value::from(0))),
            percent_d(result.get("unfollowed_off").unwrap_or(&Value::from(0))),
            i64::from(pyval::truthy(get(&result, "observe_only_paused")))
        ));
        return Ok(EXIT_OK);
    }
    let done = with_mutex(&app, 0.0, || {
        car_store::downgrade::downgrade_state(&app.state_dir(), target, &links)
    });
    let result = match done {
        Err(_) => {
            io.say("the watcher is running; stop it first (stop), then run this again");
            return Ok(EXIT_ERROR);
        }
        Ok(result) => result.map_err(store_error)?,
    };
    if !pyval::truthy(get(&result, "changed")) {
        io.say(&format!(
            "the state is already schema {target} or older; nothing to do"
        ));
        return Ok(EXIT_OK);
    }
    let rows = percent_d(get(&result, "rows"));
    app.info(
        io,
        &format!("state downgraded to schema {target} ({rows} records kept)"),
    );
    io.say(&format!(
        "state rewritten as schema {target}; {rows} records kept, and a copy of the previous state was saved beside it"
    ));
    let count = |name: &str| int_of(get(&result, name));
    if count("made_final") != 0 {
        io.say(&format!("{} continuation(s) already handed to Codex were marked final: the older release could not follow them, and never sends them again", percent_d(get(&result, "made_final"))));
    }
    if count("extra_home_rows") != 0 {
        io.say(&format!("{} record(s) of other Codex homes were kept, and none of them is waiting any more: the older release watches one home", percent_d(get(&result, "extra_home_rows"))));
    }
    if count("conversations_off") != 0 {
        io.say(&format!("{} conversation(s) were switched off because they waited for you to say so; switch them back on in the older release to let them resume", percent_d(get(&result, "conversations_off"))));
    }
    if count("unfollowed_off") != 0 {
        io.say(&format!("{} conversation(s) were switched off because Codex may still deliver a continuation the older release could not follow, and it would take a failure of that one for a new task; switch them back on in the older release when you want them to resume", percent_d(get(&result, "unfollowed_off"))));
    }
    if pyval::truthy(get(&result, "observe_only_paused")) {
        io.say("observe-only became a pause: resume recovery in the older release when you want it to send");
    }
    io.say("install the older release now; starting this version's watcher again upgrades the state again");
    Ok(EXIT_OK)
}

/// What the integration must hand in for `run`: the reference's `App.run` is the watcher host's (P6).
pub fn not_ported(what: &str) -> Raised {
    Raised::new("NotImplementedError", format!("{what} is not ported"))
}

/// `Backend` for a test of the table.
pub fn backend(codex_exe: &str, version: &str) -> Backend {
    Backend {
        codex_exe: codex_exe.to_owned(),
        engine_version: version.to_owned(),
    }
}
