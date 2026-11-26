//! `scripts/plugin_setup.py`'s commands: the thin layer the skill, the installer and every published updater run
//! (`setup`, `watcher-running`, `downgrade-state`, `remove-entry`, `status`, `pending`, `enable`, `disable`, `cancel`,
//! `stop`, `doctor`, `logs`, `uninstall [--purge]`, `desktop-shortcut`, `verify-home`, `claim-home`), each on the
//! runtime home (`CODEX_AUTO_RESUME_PLUGIN_HOME`, else `%USERPROFILE%\.codex-auto-resume`), each answering the codes
//! old updaters read.
//!
//! What is Rust's own, by PLAN 6.4 and S8.2: the sign-in value starts the watcher host (`app\bin\CodexAutoResume.exe
//! --home <home> run`), the link handler is the core's (`codex-auto-resume.exe --home <home> activate "%1"`), and the
//! watcher `setup` starts is the host. There is no Python launcher to copy: `setup` writes `runtime.json` and the icon
//! and claims the home, as the reference does around its copy.

use std::path::{Path, PathBuf};

use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;

use crate::argparse::Namespace;
use crate::cli::{self, App, CliError, Io, Machine, progress};

pub const PLUGIN_NAME: &str = "codex-auto-resume";
pub const LAUNCHER_NAME: &str = "watcher-launcher.py";
pub const RUNTIME_CONFIG: &str = "runtime.json";
pub const ICON_NAME: &str = "codex-auto-resume.ico";
pub const ENV_RUNTIME_HOME: &str = "CODEX_AUTO_RESUME_PLUGIN_HOME";
pub const ENV_WILL_LOOK_AGAIN: &str = "CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN";
pub const ENV_SAYS_LEFT_STOPPED: &str = "CODEX_AUTO_RESUME_SETUP_SAYS_LEFT_STOPPED";
pub const ENV_SAYS_STARTED_AGAIN: &str = "CODEX_AUTO_RESUME_SETUP_SAYS_STARTED_AGAIN";
pub const ENV_ENGLISH: &str = "CODEX_AUTO_RESUME_SETUP_ENGLISH";
pub const RUNTIME_DIR_NAME: &str = ".codex-auto-resume";
pub const OCCUPIED_NAMES: &[&str] = &["app", "runtime", "config", "logs"];
pub const CHECK: &str = "\u{2713}";
pub const EXIT_OK: i32 = 0;
pub const EXIT_ERROR: i32 = 1;
pub const EXIT_UNCONFIRMED: i32 = 2;
pub const EXIT_DESKTOP_TAKEN: i32 = 3;
pub const EXIT_LEFT_STOPPED: i32 = 4;
pub const EXIT_STARTED_AGAIN: i32 = 5;
pub const SETUP_STEPS: i64 = 7;
/// `WATCHER_WAIT` (`control.WATCHER_START_TIMEOUT`).
pub const WATCHER_WAIT: f64 = car_control::lifecycle::WATCHER_START_TIMEOUT;
/// The watcher host, beside this program (PLAN 1.7).
pub const HOST: &str = "CodexAutoResume.exe";

/// `words(key)`: English where the caller's log is, else the language this process speaks.
fn words(machine: &Machine, key: &str) -> String {
    let full = format!("msg.{key}");
    if machine.env(ENV_ENGLISH).as_deref() == Some("1") {
        return car_words::l10n::text(&full, "en", &[]).unwrap_or(full);
    }
    let host = &machine.host;
    let environ = |name: &str| host.environ(name);
    let windows = || host.windows_languages();
    car_words::l10n::message(key, &environ, &windows).unwrap_or(full)
}

fn say(machine: &Machine, io: &mut Io, key: &str) {
    let text = words(machine, key);
    io.say(&text);
}

/// `runtime_home()`.
pub fn runtime_home(machine: &Machine) -> String {
    let os = machine.host.os();
    let resolve = |text: &str| -> String {
        let wide: Vec<u16> = text.encode_utf16().collect();
        os.resolve(&wide)
            .map(|resolved| String::from_utf16_lossy(&resolved))
            .unwrap_or_else(|_| text.to_owned())
    };
    if let Some(given) = machine
        .env(ENV_RUNTIME_HOME)
        .filter(|each| !each.is_empty())
    {
        let env = |name: &str| machine.env(name);
        let expanded = car_config::winpath::expanduser(&given, &env).unwrap_or(given);
        return resolve(&expanded);
    }
    let profile = machine
        .env("USERPROFILE")
        .filter(|each| !each.is_empty())
        .unwrap_or_default();
    resolve(&Path::new(&profile).join(RUNTIME_DIR_NAME).to_string_lossy())
}

/// `installed(home)`: both interpreters' names and the package's folder, as every published updater lays them.
pub fn installed(home: &str) -> bool {
    let runtime = Path::new(home).join("runtime");
    runtime.join("python.exe").is_file()
        && runtime.join("pythonw.exe").is_file()
        && Path::new(home)
            .join("app")
            .join("src")
            .join("codex_auto_resume")
            .is_dir()
}

/// `bootstrap_command()`.
fn bootstrap_command(machine: &Machine) -> String {
    let script = Path::new(&machine.project_root)
        .join("scripts")
        .join("bootstrap.ps1");
    format!(
        "powershell -NoProfile -ExecutionPolicy Bypass -File \"{}\"",
        script.display()
    )
}

/// `installed_as_plugin()`.
fn installed_as_plugin(machine: &Machine) -> bool {
    let parts: Vec<String> = Path::new(&machine.project_root)
        .components()
        .map(|part| part.as_os_str().to_string_lossy().into_owned())
        .collect();
    parts.iter().any(|each| each == "plugins") && parts.iter().any(|each| each == "cache")
}

/// `install_launcher(home, mode)`, without the Python launcher a Rust installation does not have.
fn install_launcher(machine: &Machine, home: &str, mode: &str) -> Result<(), CliError> {
    std::fs::create_dir_all(home).map_err(|error| CliError(error.to_string()))?;
    let icon = Path::new(&machine.project_root)
        .join("assets")
        .join(ICON_NAME);
    if icon.is_file() {
        std::fs::copy(&icon, Path::new(home).join(ICON_NAME))
            .map_err(|error| CliError(error.to_string()))?;
    }
    let mut payload = Map::new();
    payload.insert(Str::from("mode"), Value::from(mode));
    payload.insert(Str::from("plugin_name"), Value::from(PLUGIN_NAME));
    payload.insert(
        Str::from("plugin_root"),
        Value::from(machine.project_root.as_str()),
    );
    payload.insert(Str::from("home"), Value::from(home));
    let text = to_string(&Value::Object(payload), &Options::new().indent(2))
        .map_err(|_| CliError("ValueError".to_owned()))?;
    // `write_text` in text mode: each line ends CRLF on disk.
    std::fs::write(
        Path::new(home).join(RUNTIME_CONFIG),
        text.replace('\n', "\r\n").as_bytes(),
    )
    .map_err(|error| CliError(error.to_string()))?;
    let paths = machine.paths(Some(home)).map_err(CliError)?;
    paths.claim_home();
    Ok(())
}

fn quiet_app(machine: &Machine, home: &str) -> Result<App, CliError> {
    let paths = machine.paths(Some(home)).map_err(CliError)?;
    App::new(machine, paths, None, None, false, false, "")
}

/// `start_watcher(home)`: "running", "already-running", "exited", "unconfirmed" or "not-started".
pub fn start_watcher(machine: &Machine, home: &str) -> Result<String, CliError> {
    let app = quiet_app(machine, home)?;
    if app.watcher_running() == Some(true) {
        return Ok("already-running".to_owned());
    }
    let host = Path::new(home).join("app").join("bin").join(HOST);
    if !host.is_file() {
        return Ok("not-started".to_owned());
    }
    let argv = vec![
        host.to_string_lossy().into_owned(),
        "--home".to_owned(),
        home.to_owned(),
        "run".to_owned(),
    ];
    let mut process =
        match app
            .host()
            .launch(&argv, Path::new(home), car_control::lifecycle::DETACHED)
        {
            Ok(process) => process,
            Err(raised) => return Err(CliError(raised.message)),
        };
    let timeout = car_control::lifecycle::start_timeout(Path::new(home), Some(WATCHER_WAIT));
    let done = car_control::lifecycle::await_watcher(
        &app.control,
        Some(&mut *process),
        timeout,
        car_control::lifecycle::WATCHER_START_INTERVAL,
    );
    Ok(match done.get("state") {
        Some(Value::Str(state)) => state.as_str().unwrap_or("unconfirmed").to_owned(),
        _ => "unconfirmed".to_owned(),
    })
}

/// `watcher_seen(home)`.
pub fn watcher_seen(machine: &Machine, home: &str) -> Result<Option<bool>, CliError> {
    Ok(quiet_app(machine, home)?.watcher_running())
}

/// `ended_by_itself(home)`.
fn ended_by_itself(machine: &Machine, home: &str) -> bool {
    let Ok(paths) = machine.paths(Some(home)) else {
        return false;
    };
    let state = Path::new(&paths.state_dir).join("state.sqlite");
    if !state.is_file() {
        return false;
    }
    let host = &machine.host;
    let Ok(store) = car_store::Store::open_with(
        Path::new(&paths.state_dir),
        car_store::Options {
            migrate: false,
            check: false,
            clock: Box::new(car_store::session::wall_clock),
            links: host.links(),
        },
    ) else {
        return false;
    };
    let Ok(Some(status)) = store.watcher_status() else {
        return false;
    };
    let mark = match status.get("end_mark") {
        Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
        _ => return false,
    };
    if mark != "running" && mark != "memory_guard" {
        return false;
    }
    let mut status = status.clone();
    status.insert(Str::from("end_mark"), Value::from("running"));
    let boot = host.boot();
    let (ended, _at) = car_control::status::how_it_ended(
        Some(&status),
        Some(false),
        boot.sign_in.as_deref(),
        boot.booted_at,
    );
    ended == Value::from("unexpected")
}

/// `looked_again(home, started)`.
fn looked_again(machine: &Machine, home: &str, started: String) -> String {
    if started == "unconfirmed" && watcher_seen(machine, home).ok().flatten() == Some(true) {
        return "running".to_owned();
    }
    started
}

/// `conflicting_autostart(home)`.
fn conflicting_autostart(machine: &Machine, home: &str) -> Option<String> {
    let current = machine.host.startup_read().ok()??;
    if current.is_empty() || car_platform::startup::belongs_to(&current, home) {
        return None;
    }
    Some(current)
}

/// `_cli(home, argv)`: the command line on the runtime home, its prints shown or dropped.
fn run_cli(machine: &Machine, home: &str, argv: &[&str], io: &mut Io, silent: bool) -> i32 {
    let mut words: Vec<String> = vec!["--home".to_owned(), home.to_owned()];
    words.extend(argv.iter().map(|each| (*each).to_owned()));
    let parsed =
        crate::argparse::parse_args(crate::parsers_gen::PARSERS, crate::parsers_gen::CLI, &words);
    let was = io.silent;
    io.silent = silent || was;
    let code = match parsed {
        Ok(args) => cli::run(machine, &args, io),
        Err(exit) => crate::roles::shown(exit, io),
    };
    io.silent = was;
    code
}

fn startup_enabled(machine: &Machine, home: &str) -> bool {
    machine
        .paths(Some(home))
        .map(|paths| machine.control(paths).startup_enabled())
        .unwrap_or(false)
}

fn cmd_setup(machine: &Machine, args: &Namespace, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    if !installed(&home) {
        say(machine, io, "not_installed");
        io.say("");
        io.say(&format!("  {}", bootstrap_command(machine)));
        io.say("");
        say(machine, io, "not_installed_hint");
        return Ok(EXIT_ERROR);
    }
    if let Some(conflict) = conflicting_autostart(machine, &home)
        && !args.get("replace_existing").on()
    {
        say(machine, io, "conflict");
        io.say(&format!("  {conflict}"));
        return Ok(EXIT_ERROR);
    }
    install_launcher(
        machine,
        &home,
        if installed_as_plugin(machine) {
            "plugin"
        } else {
            "local"
        },
    )?;
    progress(machine, io, "setup", 1, SETUP_STEPS);
    let mut prepare = vec!["--quiet", "install"];
    let edition_from = args.get("edition_from").text().map(str::to_owned);
    if let Some(edition) = &edition_from {
        prepare.push("--edition-from");
        prepare.push(edition);
    }
    let mut incomplete = run_cli(machine, &home, &prepare, io, true) != cli::EXIT_OK;
    progress(machine, io, "setup", 2, SETUP_STEPS);
    let keep_state = args.get("keep_state").on();
    if !keep_state {
        incomplete |= run_cli(machine, &home, &["--quiet", "enable"], io, true) != cli::EXIT_OK;
    }
    progress(machine, io, "setup", 3, SETUP_STEPS);
    let register_startup =
        !args.get("no_startup").on() && (!keep_state || startup_enabled(machine, &home));
    if register_startup {
        machine
            .host
            .startup_install(&cli::watcher_command(&home))
            .map_err(|raised| CliError(raised.message))?;
    }
    progress(machine, io, "setup", 4, SETUP_STEPS);
    let _ = machine
        .outside
        .install_protocol(&cli::protocol_command(&home));
    progress(machine, io, "setup", 5, SETUP_STEPS);
    let manifest = Path::new(&machine.project_root)
        .join(".codex-plugin")
        .join("plugin.json");
    // `display_name` answers Python's str (fix4: a lone surrogate kept); the Outside's registry writer takes text, so
    // a name holding one - never in the product's own manifest - is written with U+FFFD in its place.
    let name = car_platform::addremove::display_name(&manifest);
    let name = name
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| String::from_utf8_lossy(name.as_bytes()).into_owned());
    let _ = machine.outside.addremove_register(
        &home,
        &machine.host.edition_name(),
        &machine.host.version(),
        &name,
    );
    progress(machine, io, "setup", 6, SETUP_STEPS);
    let was_stopped = keep_state && args.get("watcher_was_stopped").on();
    let started_again = was_stopped && ended_by_itself(machine, &home);
    let left_stopped = was_stopped && !started_again && !startup_enabled(machine, &home);
    let started = if left_stopped {
        "left-stopped".to_owned()
    } else {
        start_watcher(machine, &home)?
    };
    progress(machine, io, "setup", 7, SETUP_STEPS);
    say(machine, io, "ready_title");
    io.say("");
    say(machine, io, "ready_defaults");
    for key in ["ready_b1", "ready_b2", "ready_b3", "ready_b4"] {
        let text = words(machine, key);
        io.say(&format!("  {CHECK} {text}"));
    }
    io.say("");
    let started = looked_again(machine, &home, started);
    let confirmed = started == "running" || started == "already-running";
    let unconfirmed_word = if machine.env(ENV_WILL_LOOK_AGAIN).as_deref() == Some("1") {
        "setup_unconfirmed_yet"
    } else {
        "setup_unconfirmed"
    };
    if incomplete {
        say(machine, io, "setup_incomplete");
    } else {
        say(
            machine,
            io,
            if confirmed && started_again {
                "setup_started_again"
            } else if confirmed {
                "setup_done"
            } else if left_stopped {
                "setup_left_stopped"
            } else {
                unconfirmed_word
            },
        );
    }
    if register_startup {
        say(machine, io, "setup_autostart");
    }
    io.say("");
    io.say(&format!("state: {home}"));
    if incomplete {
        return Ok(EXIT_ERROR);
    }
    if confirmed {
        return Ok(
            if started_again && machine.env(ENV_SAYS_STARTED_AGAIN).as_deref() == Some("1") {
                EXIT_STARTED_AGAIN
            } else {
                EXIT_OK
            },
        );
    }
    if left_stopped {
        return Ok(
            if machine.env(ENV_SAYS_LEFT_STOPPED).as_deref() == Some("1") {
                EXIT_LEFT_STOPPED
            } else {
                EXIT_OK
            },
        );
    }
    Ok(EXIT_UNCONFIRMED)
}

fn running_word(running: Option<bool>) -> &'static str {
    match running {
        Some(true) => "watcher_running",
        Some(false) => "watcher_stopped",
        None => "watcher_unknown",
    }
}

fn cmd_enable(machine: &Machine, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    let code = run_cli(machine, &home, &["--quiet", "enable"], io, true);
    let started = start_watcher(machine, &home)?;
    let started = looked_again(machine, &home, started);
    say(machine, io, "enabled");
    if started != "running" && started != "already-running" {
        say(machine, io, "setup_unconfirmed");
        return Ok(if code != 0 { code } else { EXIT_UNCONFIRMED });
    }
    Ok(code)
}

fn cmd_status(machine: &Machine, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    let running = watcher_seen(machine, &home)?;
    say(machine, io, running_word(running));
    if let Some(conflict) = conflicting_autostart(machine, &home) {
        say(machine, io, "conflict_other");
        io.say(&format!("  {conflict}"));
    }
    io.say("");
    Ok(run_cli(machine, &home, &["--quiet", "status"], io, false))
}

fn cmd_watcher_running(machine: &Machine, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    let running = watcher_seen(machine, &home)?;
    if machine.env(ENV_ENGLISH).as_deref() == Some("1") {
        let host = &machine.host;
        let environ = |name: &str| host.environ(name);
        let windows = || host.windows_languages();
        car_words::l10n::set_preference(Some("en"), &environ, &windows);
    }
    say(machine, io, running_word(running));
    Ok(if running == Some(true) {
        EXIT_OK
    } else {
        EXIT_UNCONFIRMED
    })
}

fn cmd_pending(machine: &Machine, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    let app = quiet_app(machine, &home)?;
    let store = app.open_store()?;
    let rows = store.pending().map_err(cli::store_error)?;
    drop(store);
    if rows.is_empty() {
        say(machine, io, "no_pending");
        return Ok(EXIT_OK);
    }
    Ok(run_cli(machine, &home, &["--quiet", "pending"], io, false))
}

fn cmd_verify_home(machine: &Machine, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    let paths = machine.paths(Some(&home)).map_err(CliError)?;
    if !paths.owns_home() {
        io.say("not-owned");
        io.say(&home);
        return Ok(EXIT_ERROR);
    }
    io.say("owned");
    io.say(&paths.home);
    Ok(EXIT_OK)
}

fn cmd_claim_home(machine: &Machine, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    let paths = machine.paths(Some(&home)).map_err(CliError)?;
    if paths.owns_home() {
        io.say("owned");
        io.say(&paths.home);
        return Ok(EXIT_OK);
    }
    let mut occupied: Vec<String> = match std::fs::read_dir(&home) {
        Ok(entries) => entries
            .filter_map(Result::ok)
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| OCCUPIED_NAMES.contains(&name.as_str()) || name.contains(".old-"))
            .collect(),
        Err(_) => Vec::new(),
    };
    occupied.sort();
    if !occupied.is_empty() || !paths.claim_home() {
        io.say("not-owned");
        io.say(&home);
        for name in occupied {
            io.say(&name);
        }
        return Ok(EXIT_ERROR);
    }
    io.say("claimed");
    io.say(&paths.home);
    Ok(EXIT_OK)
}

fn cmd_uninstall(machine: &Machine, args: &Namespace, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    let mut argv = vec!["--quiet", "uninstall"];
    if !args.get("purge").on() {
        argv.push("--keep-state");
        argv.push("--keep-logs");
    }
    let code = run_cli(machine, &home, &argv, io, false);
    if code != EXIT_OK {
        return Ok(code);
    }
    let paths = machine.paths(Some(&home)).map_err(CliError)?;
    for name in [LAUNCHER_NAME, RUNTIME_CONFIG] {
        let path = Path::new(&home).join(name);
        let text = path.to_string_lossy().into_owned();
        if path.is_file() && !car_config::paths::is_link(&text) && paths.confined(&text) {
            let _ = std::fs::remove_file(&path);
        }
    }
    let empty = std::fs::read_dir(&home).is_ok_and(|mut entries| entries.next().is_none());
    if Path::new(&home).is_dir() && empty {
        let _ = std::fs::remove_dir(&home);
    }
    say(machine, io, "uninstalled");
    Ok(EXIT_OK)
}

fn cmd_remove_entry(machine: &Machine, io: &mut Io) -> Result<i32, CliError> {
    let home = runtime_home(machine);
    let removed = match machine.outside.addremove_unregister(&home) {
        Ok(removed) => removed,
        Err(raised) => {
            io.say(&format!("entry: failed {}", raised.message));
            return Ok(EXIT_ERROR);
        }
    };
    let kept = machine.outside.addremove_remove_kept(&home);
    io.say(if removed || kept {
        "entry: removed"
    } else {
        "entry: none"
    });
    Ok(EXIT_OK)
}

fn cmd_desktop_shortcut(machine: &Machine, args: &Namespace, io: &mut Io) -> Result<i32, CliError> {
    let paths = machine
        .paths(Some(&runtime_home(machine)))
        .map_err(CliError)?;
    let done = if args.get("action").text() == Some("make") {
        machine
            .outside
            .desktop_install(&paths.home, &cli::what_the_entry_opens(&paths))
            .map(|_| ())
    } else {
        machine.outside.desktop_uninstall(&paths.home).map(|_| ())
    };
    match done {
        Ok(()) => Ok(EXIT_OK),
        Err(crate::seam::ShortcutFailure::Taken(text)) => {
            io.say(&text);
            Ok(EXIT_DESKTOP_TAKEN)
        }
        Err(crate::seam::ShortcutFailure::Failed(text)) => {
            io.say(&text);
            Ok(EXIT_ERROR)
        }
    }
}

/// `plugin_setup.main(argv)` over parsed arguments.
pub fn run(machine: &Machine, args: &Namespace, io: &mut Io) -> i32 {
    let command = args.get("command").text().unwrap_or_default().to_owned();
    let home = || runtime_home(machine);
    let done = match command.as_str() {
        "setup" => cmd_setup(machine, args, io),
        "status" => cmd_status(machine, io),
        "pending" => cmd_pending(machine, io),
        "enable" => cmd_enable(machine, io),
        "disable" => {
            let code = run_cli(machine, &home(), &["--quiet", "disable"], io, true);
            say(machine, io, "disabled");
            Ok(code)
        }
        "cancel" => {
            let thread = args.get("thread_id").text().unwrap_or_default().to_owned();
            let code = run_cli(machine, &home(), &["--quiet", "cancel", &thread], io, false);
            if code == EXIT_OK {
                say(machine, io, "cancelled");
            }
            Ok(code)
        }
        "uninstall" => cmd_uninstall(machine, args, io),
        "verify-home" => cmd_verify_home(machine, io),
        "watcher-running" => cmd_watcher_running(machine, io),
        "claim-home" => cmd_claim_home(machine, io),
        "downgrade-state" => {
            let to = args.get("to").int().unwrap_or(0).to_string();
            let mut argv = vec!["--quiet", "downgrade-state", "--to", to.as_str()];
            if args.get("stop_watcher").on() {
                argv.push("--stop-watcher");
            }
            Ok(run_cli(machine, &home(), &argv, io, false))
        }
        "remove-entry" => cmd_remove_entry(machine, io),
        "desktop-shortcut" => cmd_desktop_shortcut(machine, args, io),
        "stop" | "doctor" => Ok(run_cli(machine, &home(), &["--quiet", &command], io, false)),
        "logs" => {
            let lines = args.get("lines").int().unwrap_or(0).to_string();
            Ok(run_cli(
                machine,
                &home(),
                &["--quiet", "logs", "-n", &lines],
                io,
                false,
            ))
        }
        _ => Err(CliError(format!("unknown command {command}"))),
    };
    match done {
        Ok(code) => code,
        Err(CliError(message)) => {
            // An exception the reference does not catch here ends the process with its traceback and code 1.
            io.warn(&format!("Traceback (most recent call last):\n{message}"));
            EXIT_ERROR
        }
    }
}

/// Where this program's own installation is: `<home>\app\bin\<exe>` gives `<home>\app`.
pub fn project_root_of(exe: &Path) -> PathBuf {
    exe.parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .unwrap_or_default()
}

/// What the store's settings say of one switch, for tests.
pub fn truthy(value: &Value) -> bool {
    pyval::truthy(value)
}
