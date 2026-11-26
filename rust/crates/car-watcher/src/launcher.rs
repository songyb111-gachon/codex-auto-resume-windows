//! The logic of `scripts/watcher_launcher.py` (P6-DESIGN 1.6): the stable entry point of the autostarted watcher,
//! however the product was installed - its phases, the relaunch mark's wait, AFTER_STOP, P13's questions to the plug
//! (SUPERVISE at the start, RESTART once a supervised child ended), relaunching once after `EXIT_SCHEMA_NEWER`, the
//! plugin root's order (F10, Q6 (a): kept), and `launcher.log` and `errors.log`, line for line.
//!
//! What D8 retired is not here: `_again_without_remote_debug` and `NO_REMOTE_DEBUG` (no interpreter remains, so the
//! host starts with nothing to turn off), `_on_chosen`, `_again_under_bundled`, `_came_up` and `_not_up` (the Python
//! choice). The host's `Main` (S6.2b) hands this its world: the folder the launcher runs from, the environment,
//! the clock, the edition's plug, the child process starter (car-platform's one starter, CREATE_NO_WINDOW) and the
//! watcher itself.

use std::path::{Path, PathBuf};

use car_machine::json::{Map, Value};

pub const CONFIG_NAME: &str = "runtime.json";
pub const EXIT_SCHEMA_NEWER: i32 = 4;
pub const EXIT_MEMORY_GUARD: i32 = 5;
pub const RELAUNCH_MARK: &str = "CODEX_AUTO_RESUME_RELAUNCHED";
pub const AFTER_STOP_MARK: &str = "CODEX_AUTO_RESUME_AFTER_STOP";
pub const AFTER_STOP_WAIT: f64 = 30.0;
pub const AFTER_STOP_POLL: f64 = 0.25;
pub const OUR_MARKETPLACES: &[&str] = &["codex-auto-resume-windows"];
pub const EXIT_ERROR: i32 = 1;
pub const PHASE_START: &str = "start";
pub const PHASE_ENDED: &str = "ended";
pub const SUPERVISE: &str = "supervise";
pub const RESTART: &str = "restart";
pub const CHILD_ARGUMENT: &str = "--supervised-child";
pub const ASK_AGAIN_SECONDS: f64 = 5.0;
pub const UNSUPERVISED_FILE: &str = "unsupervised.txt";
pub const LAUNCH_LOG: &str = "launcher.log";
/// v0.6.26: 200, not 50 - a supervised start writes about four lines.
pub const LAUNCH_LOG_LINES: usize = 200;

/// A supervised child, started.
pub trait Child {
    fn pid(&self) -> u32;
    /// `child.wait()`: its exit code.
    fn wait(&mut self) -> i32;
}

/// What the launcher asks of the machine and of the product.
pub trait LauncherWorld {
    /// `Path(__file__).resolve().parent`: the launcher's own folder.
    fn here(&self) -> PathBuf;
    fn pid(&self) -> u32;
    fn env(&self, name: &str) -> Option<String>;
    /// `os.environ.pop(name, None)`.
    fn take_env(&mut self, name: &str) -> Option<String>;
    fn sleep(&mut self, seconds: f64);
    fn monotonic(&mut self) -> f64;
    /// `time.strftime("[%Y-%m-%d %H:%M:%S] ")`.
    fn stamp(&self) -> String;
    /// `_usable(root)`: a candidate looks like this project, not merely like a directory.
    fn usable(&self, root: &Path) -> bool;
    /// `codex_home()`: CODEX_HOME expanded, else the profile's `.codex`.
    fn codex_home(&self) -> PathBuf;
    /// P13: `guard(edition.plug(Paths(home))).supervise(facts)`, the answer's word; None where nothing could be asked.
    fn supervise(&mut self, home: &Path, facts: &Value) -> Option<String>;
    /// Whether the installed edition's plug is the standard edition's (NULL), which is never told `clean`.
    fn plug_is_null(&mut self, home: &Path) -> bool;
    /// `plug.supervise_held()`.
    fn supervise_held(&mut self, home: &Path) -> Value;
    /// `_ended_cleanly(paths)`.
    fn ended_cleanly(&mut self, home: &Path) -> Option<bool>;
    /// Whether `App(Paths(home), enable_logging=False).watcher_running` can be had at all.
    fn probe_available(&mut self, home: &Path) -> bool;
    /// That probe: True, False, or None where it cannot tell (or raised).
    fn watcher_running(&mut self, home: &Path) -> Option<bool>;
    /// `cli_main(["--home", home, "--quiet"] + command)`: the watcher, in this process.
    fn run_watcher(&mut self, home: &Path, command: &[String]) -> i32;
    /// The program a supervised child or the relaunch runs (the host's own image), or None where there is none.
    fn child_program(&self) -> Option<PathBuf>;
    /// `subprocess.Popen(arguments, creationflags=CREATE_NO_WINDOW, every stream DEVNULL)`.
    fn start_child(&mut self, arguments: &[String]) -> Result<Box<dyn Child>, String>;
    /// The relaunch: detached, with RELAUNCH_MARK set in its environment.
    fn relaunch(&mut self, arguments: &[String]) -> Result<(), String>;
}

/// `_complain(home, reason)`: a failure leaves a trace on disk (`errors.log`).
pub fn complain(world: &dyn LauncherWorld, home: &Path, reason: &str) {
    let logs = home.join("logs");
    let _ = (|| -> std::io::Result<()> {
        std::fs::create_dir_all(&logs)?;
        use std::io::Write;
        let mut stream = car_machine::pyfile::options()
            .create(true)
            .append(true)
            .open(logs.join("errors.log"))?;
        let line = format!("{}watcher launcher: {reason}\n", world.stamp());
        stream.write_all(line.replace('\n', "\r\n").as_bytes())
    })();
}

/// `_note(home, text)`: one line per launch, before anything else can fail; trimmed to the last LAUNCH_LOG_LINES.
pub fn note(world: &dyn LauncherWorld, home: &Path, text: &str) {
    let logs = home.join("logs");
    let _ = (|| -> std::io::Result<()> {
        std::fs::create_dir_all(&logs)?;
        let path = logs.join(LAUNCH_LOG);
        let mut lines: Vec<String> = Vec::new();
        if path.is_file() {
            let raw = car_machine::pyfile::read(&path)?;
            // read_text(errors="replace") reads "\r\n" as "\n"; splitlines() then splits on every line break.
            let text = String::from_utf8_lossy(&raw).replace("\r\n", "\n").replace('\r', "\n");
            let all: Vec<String> = splitlines(&text);
            let skip = all.len().saturating_sub(LAUNCH_LOG_LINES);
            lines = all.into_iter().skip(skip).collect();
        }
        lines.push(format!("{}{text}", world.stamp()));
        let body = format!("{}\n", lines.join("\n")).replace('\n', "\r\n");
        car_machine::pyfile::write(&path, body.as_bytes())
    })();
}

/// `str.splitlines()`: every line break Python knows.
fn splitlines(text: &str) -> Vec<String> {
    let mut lines = Vec::new();
    let mut current = String::new();
    for c in text.chars() {
        if matches!(
            c,
            '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
        ) {
            lines.push(std::mem::take(&mut current));
        } else {
            current.push(c);
        }
    }
    if !current.is_empty() {
        lines.push(current);
    }
    lines
}

fn text<'a>(map: &'a Map, key: &str) -> Option<&'a str> {
    match map.get(key) {
        Some(Value::Str(found)) => found.as_str(),
        _ => None,
    }
}

/// `resolve_plugin_root(config)`: the installed application wins, then this product's own marketplace copy (newest by
/// write time), then the recorded copy (F10).
pub fn resolve_plugin_root(world: &dyn LauncherWorld, config: &Map) -> Option<PathBuf> {
    let home = match config.get("home") {
        Some(Value::Str(found)) => found.as_str().map(PathBuf::from),
        None | Some(Value::Null) => Some(PathBuf::new()),
        _ => None,
    };
    if let Some(home) = home
        && home.file_name().is_some()
    {
        let candidate = home.join("app");
        if world.usable(&candidate) {
            return Some(candidate);
        }
    }
    if text(config, "mode") == Some("plugin") {
        let name = text(config, "plugin_name").unwrap_or_default().to_owned();
        let cache = world.codex_home().join("plugins").join("cache");
        let mut candidates: Vec<PathBuf> = Vec::new();
        let listed = (|| -> std::io::Result<()> {
            for marketplace in std::fs::read_dir(&cache)? {
                let marketplace = marketplace?.path();
                let Some(market) = marketplace.file_name().map(|n| n.to_string_lossy().into_owned()) else {
                    continue;
                };
                if !OUR_MARKETPLACES.contains(&market.as_str()) {
                    continue;
                }
                let versions = marketplace.join(&name);
                if !versions.is_dir() {
                    continue;
                }
                for version in std::fs::read_dir(&versions)? {
                    let version = version?.path();
                    if world.usable(&version) {
                        candidates.push(version);
                    }
                }
            }
            Ok(())
        })();
        if listed.is_err() {
            candidates.clear();
        }
        let mut newest: Option<(std::time::SystemTime, PathBuf)> = None;
        for candidate in candidates {
            let Ok(stamp) = std::fs::metadata(&candidate).and_then(|meta| meta.modified()) else {
                continue;
            };
            if newest.as_ref().is_none_or(|(best, _)| stamp > *best) {
                newest = Some((stamp, candidate));
            }
        }
        if let Some((_, found)) = newest {
            return Some(found);
        }
    }
    if let Some(recorded) = text(config, "plugin_root").filter(|found| !found.is_empty()) {
        let root = PathBuf::from(recorded);
        if world.usable(&root) {
            return Some(root);
        }
    }
    None
}

fn facts(phase: &str) -> Value {
    let mut map = Map::new();
    map.insert("phase".into(), Value::from(phase));
    Value::Object(map)
}

fn ended_facts(code: i32) -> Value {
    let mut map = Map::new();
    map.insert("phase".into(), Value::from(PHASE_ENDED));
    map.insert("exit_code".into(), Value::from(i64::from(code)));
    Value::Object(map)
}

/// `_supervise(home, facts)`: P13, with `clean` added for an end where the plug is not NULL.
pub fn supervise(world: &mut dyn LauncherWorld, home: &Path, facts: &Value) -> Option<String> {
    let mut facts = facts.clone();
    if let Value::Object(map) = &mut facts
        && text(map, "phase") == Some(PHASE_ENDED)
        && !world.plug_is_null(home)
    {
        let clean = world.ended_cleanly(home);
        map.insert("clean".into(), clean.map_or(Value::Null, Value::Bool));
    }
    world.supervise(home, &facts)
}

/// `_unsupervised(home, word)`: the file the Dashboard reads.
fn unsupervised(world: &dyn LauncherWorld, home: &Path, word: Option<&str>) {
    let path = home.join("logs").join(UNSUPERVISED_FILE);
    match word {
        None => {
            let _ = std::fs::remove_file(&path);
        }
        Some(word) => {
            let line = format!("{} {word}\r\n", world.pid());
            let _ = car_machine::pyfile::write(&path, line.as_bytes());
        }
    }
}

/// `_why_held(home)`: why the start question named no supervisor, a closed word, or None.
fn why_held(world: &mut dyn LauncherWorld, home: &Path) -> Option<String> {
    match world.supervise_held(home) {
        Value::Str(word) => word.as_str().and_then(|word| {
            let letters: String = word.chars().filter(|c| *c != '_').collect();
            (!letters.is_empty() && letters.chars().all(char::is_alphabetic)).then(|| word.to_owned())
        }),
        _ => None,
    }
}

/// `_start_answer(here, home)`: (the answer, why no supervisor was named where one was asked for).
fn start_answer(
    world: &mut dyn LauncherWorld,
    here: &Path,
    home: &Path,
) -> (Option<String>, Option<String>) {
    let mut answer = supervise(world, home, &facts(PHASE_START));
    let mut held = if answer.as_deref() == Some(SUPERVISE) {
        None
    } else {
        why_held(world, home)
    };
    if let Some(word) = &held {
        note(
            world,
            here,
            &format!(
                "no crash restart yet ({word}); asking again in {} s",
                ASK_AGAIN_SECONDS as i64
            ),
        );
        world.sleep(ASK_AGAIN_SECONDS);
        answer = supervise(world, home, &facts(PHASE_START));
        held = if answer.as_deref() == Some(SUPERVISE) {
            None
        } else {
            why_held(world, home)
        };
    }
    unsupervised(world, home, held.as_deref());
    if let Some(word) = &held {
        note(
            world,
            here,
            &format!("running the watcher here, without crash restart ({word})"),
        );
        complain(
            world,
            home,
            &format!(
                "the watcher runs without crash restart for now ({word}); its next start takes it up again"
            ),
        );
    }
    (answer, held)
}

/// `_supervised(here, home, held=)`: run the watcher as a child and wait for it; once it ended, ask P13 again, and
/// start it once more only where the answer is RESTART. The child's last exit code, or None where no child could be
/// started at all (the watcher then runs in this process).
fn supervised(
    world: &mut dyn LauncherWorld,
    here: &Path,
    home: &Path,
    mut held: Option<String>,
) -> Option<i32> {
    let Some(program) = world.child_program() else {
        note(
            world,
            here,
            "no pythonw.exe to run a supervised watcher under; running it here",
        );
        return None;
    };
    let arguments = vec![
        program.to_string_lossy().into_owned(),
        "run".to_owned(),
        CHILD_ARGUMENT.to_owned(),
    ];
    let mut started = false;
    loop {
        let mut child = match world.start_child(&arguments) {
            Ok(child) => child,
            Err(error) => {
                complain(
                    world,
                    here,
                    &format!("could not start a supervised watcher: {error}"),
                );
                return if started { Some(EXIT_ERROR) } else { None };
            }
        };
        started = true;
        note(
            world,
            here,
            &format!("watcher started as a supervised child (pid {})", child.pid()),
        );
        let code = child.wait();
        if code == EXIT_SCHEMA_NEWER {
            note(world, here, &format!("the supervised watcher ended (exit {code}): the state is newer than its code, and it started the installed copy itself; not starting it again here"));
            return Some(code);
        }
        if held.is_some() && supervise(world, home, &facts(PHASE_START)).as_deref() == Some(SUPERVISE) {
            held = None;
            unsupervised(world, home, None);
        }
        if supervise(world, home, &ended_facts(code)).as_deref() != Some(RESTART) {
            note(
                world,
                here,
                &format!(
                    "the supervised watcher (pid {}) ended (exit {code}); not starting it again",
                    child.pid()
                ),
            );
            return Some(code);
        }
        note(
            world,
            here,
            &format!("the watcher stopped unexpectedly (exit {code}); starting it again"),
        );
    }
}

/// `_after_stop(here, home)`: whether to go on once the watcher this launcher was started to follow has let go of
/// its mutex.
fn after_stop(world: &mut dyn LauncherWorld, here: &Path, home: &Path) -> bool {
    note(
        world,
        here,
        &format!(
            "started to follow a stop of the watcher; waiting up to {} s for it to end",
            AFTER_STOP_WAIT as i64
        ),
    );
    if !world.probe_available(home) {
        return true;
    }
    let ends = world.monotonic() + AFTER_STOP_WAIT;
    loop {
        let running = world.watcher_running(home);
        if running == Some(false) {
            return true;
        }
        if world.monotonic() >= ends {
            if running == Some(true) {
                note(
                    world,
                    here,
                    &format!(
                        "the watcher it followed still runs after {} s; not starting another",
                        AFTER_STOP_WAIT as i64
                    ),
                );
                return false;
            }
            return true;
        }
        world.sleep(AFTER_STOP_POLL);
    }
}

/// `_relaunch_once(here, command)`: start the launcher again, once, so it resolves the installation afresh.
fn relaunch_once(world: &mut dyn LauncherWorld, here: &Path, command: &[String]) {
    if world.env(RELAUNCH_MARK).is_some_and(|mark| !mark.is_empty()) {
        note(
            world,
            here,
            "the state is newer than the installed engine; not starting again",
        );
        return;
    }
    let Some(program) = world.child_program() else {
        note(world, here, "the state is newer than this engine, and there is no pythonw.exe to start the installed copy under; not starting again");
        return;
    };
    note(
        world,
        here,
        "the state is newer than this engine; starting the installed copy once",
    );
    let mut arguments = vec![program.to_string_lossy().into_owned()];
    arguments.extend(command.iter().cloned());
    if let Err(error) = world.relaunch(&arguments) {
        complain(
            world,
            here,
            &format!("could not start the installed copy: {error}"),
        );
    }
}

/// `main(argv)`.
pub fn main(world: &mut dyn LauncherWorld, argv: &[String]) -> i32 {
    let here = world.here();
    let child_argv = [String::from("run"), CHILD_ARGUMENT.to_owned()];
    if argv != child_argv {
        let pid = world.pid();
        note(world, &here, &format!("launcher started (pid {pid})"));
    }
    if world.env(RELAUNCH_MARK).is_some_and(|mark| !mark.is_empty()) {
        world.sleep(2.0);
    }
    let config = (|| -> Option<(Map, PathBuf)> {
        let raw = car_machine::pyfile::read(here.join(CONFIG_NAME)).ok()?;
        let text = std::str::from_utf8(&raw).ok()?;
        let Ok(Value::Object(config)) = car_machine::json::from_str(text) else {
            return None;
        };
        let home = match config.get("home") {
            Some(Value::Str(home)) => PathBuf::from(home.as_str()?),
            _ => return None,
        };
        Some((config, home))
    })();
    let Some((config, home)) = config else {
        complain(
            world,
            &here,
            &format!("cannot read {CONFIG_NAME}; not starting"),
        );
        return EXIT_ERROR;
    };
    if resolve_plugin_root(world, &config).is_none() {
        complain(
            world,
            &home,
            "no installed codex-auto-resume engine found; not starting",
        );
        return EXIT_ERROR;
    }
    if world.take_env(AFTER_STOP_MARK).is_some_and(|mark| !mark.is_empty())
        && !after_stop(world, &here, &home)
    {
        return 0;
    }
    let mut command: Vec<String> = if argv.is_empty() {
        vec!["run".to_owned()]
    } else {
        argv.to_vec()
    };
    let child = command == child_argv;
    if child {
        command = vec!["run".to_owned()];
    }
    let mut asks = command == ["run"] && !child;
    let mut held = None;
    if asks {
        let (answer, why) = start_answer(world, &here, &home);
        held = why;
        if answer.as_deref() == Some(SUPERVISE) {
            if let Some(code) = supervised(world, &here, &home, None) {
                return code;
            }
            asks = false;
        }
    }
    let code = world.run_watcher(&home, &command);
    if code == EXIT_SCHEMA_NEWER && command == ["run"] {
        relaunch_once(world, &here, &command);
    } else if held.is_some() {
        if supervise(world, &home, &facts(PHASE_START)).as_deref() == Some(SUPERVISE)
            && supervise(world, &home, &ended_facts(code)).as_deref() == Some(RESTART)
        {
            note(world, &here, &format!("the watcher that ran without crash restart stopped unexpectedly (exit {code}); starting it supervised"));
            unsupervised(world, &home, None);
            let restarted = supervised(world, &here, &home, None);
            return restarted.unwrap_or(code);
        }
    } else if asks {
        supervise(world, &home, &ended_facts(code));
    }
    code
}

/// `_guarded(argv)`: run, and make sure a crash says so somewhere (D15: a panic is the exception here).
pub fn guarded(world: &mut dyn LauncherWorld, argv: &[String]) -> i32 {
    let here = world.here();
    match car_machine::caught::catch(std::panic::AssertUnwindSafe(|| main(world, argv))) {
        Ok(code) => code,
        Err(payload) => {
            let failed = crate::fail::Failed::of_panic(&payload);
            note(
                world,
                &here,
                &format!("launcher failed: {}: {}", failed.class, failed.message),
            );
            complain(
                world,
                &here,
                &format!("unhandled {}: {}", failed.class, failed.message),
            );
            EXIT_ERROR
        }
    }
}
