//! The Stop hook launcher's work (`gui/HookLauncher.cs` of v0.6.26, retargeted by P6 Q4): find the installation, start
//! its core's Stop hook handler, hand it Codex's one JSON object, and relay its one answer - whole, and only from a
//! handler that ended 0 within the bound.
//!
//! What the C# launcher did, kept: the installation is `CODEX_AUTO_RESUME_PLUGIN_HOME`, else `CODEX_AUTO_RESUME_HOME`,
//! else `%USERPROFILE%\.codex-auto-resume`; nothing installed is nothing to say (exit 0, nothing written); the child's
//! three streams are piped (a child started with `CREATE_NO_WINDOW` and no explicit handles has no usable ones), its
//! standard error read and dropped, its input handed over on a thread of its own so an input that never ends cannot keep
//! the launcher past its bound; past [`BOUND`] the child is ended and the launcher passes; an exit other than 0 passes;
//! the launcher never writes to standard error and every way out is 0.
//!
//! What changed with the interpreter: the child is `app\bin\codex-auto-resume.exe hook --home <home>` - the core's `hook`
//! role, whose body is car-adv's `hook::handler::main` (`--home <home>` is the argument list `hook.main(sys.argv[2:])` was
//! handed) - started through car-platform's one starter, which ORs in `CREATE_NO_WINDOW`, from the installation's folder.

use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use car_platform::spawn::{Spawn, Stream, SystemStarter};

/// The outer bound (`BoundMilliseconds`): the handler answers within its own two seconds or passes
/// (`car_adv::hook::handler::BUDGET_SECONDS`); this is for a core that never got that far.
pub const BOUND: Duration = Duration::from_millis(8000);
/// How long the relays are given to finish once the child has ended (`output.Join(2000)`).
pub const JOIN: Duration = Duration::from_millis(2000);
/// The core's role this launcher starts.
pub const ROLE: &str = "hook";

/// `InstallHome()`: the configured installation, else the account's default.
pub fn install_home(env: &dyn Fn(&str) -> Option<String>) -> String {
    car_bin::launcher::install_home(env)
}

/// The command line the core is started with: `<core> hook --home <home>`.
pub fn arguments(home: &str) -> Vec<String> {
    vec![
        car_bin::launcher::core_of(home)
            .to_string_lossy()
            .into_owned(),
        ROLE.to_owned(),
        "--home".to_owned(),
        home.to_owned(),
    ]
}

/// Whether there is an installation to ask: its core, and the folder of its data, as the MCP launcher asks.
pub fn installed(home: &str) -> bool {
    car_bin::launcher::core_of(home).is_file() && Path::new(home).join("app").join("src").is_dir()
}

/// The child as it is started: three piped streams, no window, the installation's folder.
pub fn spawn_for(argv: Vec<String>, cwd: &str) -> Spawn {
    Spawn::new(argv)
        .with_streams(Stream::Piped, Stream::Piped, Stream::Piped)
        .with_cwd(PathBuf::from(cwd))
}

fn pump(from: &mut dyn Read, to: &mut dyn Write) {
    let mut buffer = [0u8; 8192];
    loop {
        match from.read(&mut buffer) {
            Ok(0) | Err(_) => return,
            Ok(read) => {
                if to
                    .write_all(&buffer[..read])
                    .and_then(|_| to.flush())
                    .is_err()
                {
                    return;
                }
            }
        }
    }
}

fn join_within(handle: JoinHandle<Vec<u8>>, wait: Duration) -> Option<Vec<u8>> {
    let deadline = Instant::now() + wait;
    while !handle.is_finished() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(10));
    }
    if handle.is_finished() {
        handle.join().ok()
    } else {
        None
    }
}

/// One run of `spawn`: `input` handed to its standard input, then closed; its standard output kept, its standard
/// error dropped. The answer to relay: `Some(bytes)` only for a child that ended 0 within `bound` and whose output
/// was read to its end; `None` for every doubt (it could not start, it was ended at the bound, it ended otherwise).
pub fn answer(spawn: &Spawn, input: Box<dyn Read + Send>, bound: Duration) -> Option<Vec<u8>> {
    let mut child = SystemStarter.start(spawn).ok()?;
    let output = child.stdout.take().map(|mut from| {
        std::thread::spawn(move || {
            let mut kept = Vec::new();
            pump(&mut from, &mut kept);
            kept
        })
    });
    let errors = child.stderr.take().map(|mut from| {
        std::thread::spawn(move || {
            pump(&mut from, &mut std::io::sink());
            Vec::new()
        })
    });
    if let Some(mut to) = child.stdin.take() {
        let mut input = input;
        // A thread of its own, never joined: an input that never ends must not keep the launcher past its bound.
        std::thread::spawn(move || {
            pump(&mut input, &mut to);
            drop(to);
        });
    }
    let deadline = Instant::now() + bound;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    };
    let kept = output.and_then(|handle| join_within(handle, JOIN));
    if let Some(handle) = errors {
        let _ = join_within(handle, JOIN);
    }
    // Only a handler that finished is relayed, and only whole: a decision cut short is no decision, and an exit other
    // than 0 is a doubt, which passes.
    if status.code() != Some(0) {
        return None;
    }
    kept
}

/// `HookLauncher.Main`: always 0; the handler's answer on standard output where there is one.
pub fn run() -> i32 {
    let env = |name: &str| std::env::var(name).ok();
    let home = install_home(&env);
    if !installed(&home) {
        return 0;
    }
    let spawn = spawn_for(arguments(&home), &home);
    if let Some(bytes) = answer(&spawn, Box::new(std::io::stdin()), BOUND) {
        if !bytes.is_empty() {
            let mut stdout = std::io::stdout();
            let _ = stdout.write_all(&bytes).and_then(|_| stdout.flush());
        }
    }
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_platform::spawn::CREATE_NO_WINDOW;

    fn cmd(script: &[&str]) -> Spawn {
        let mut argv = vec!["cmd.exe".to_owned(), "/d".to_owned(), "/c".to_owned()];
        argv.extend(script.iter().map(|each| (*each).to_owned()));
        spawn_for(argv, &std::env::temp_dir().to_string_lossy())
    }

    fn given(bytes: &'static [u8]) -> Box<dyn Read + Send> {
        Box::new(bytes)
    }

    #[test]
    fn the_installation_is_found_as_the_c_sharp_launcher_found_it() {
        let env = |name: &str| match name {
            "CODEX_AUTO_RESUME_PLUGIN_HOME" => Some(String::new()),
            "CODEX_AUTO_RESUME_HOME" => Some(r"D:\Home".to_owned()),
            "USERPROFILE" => Some(r"C:\Users\ExampleUser".to_owned()),
            _ => None,
        };
        assert_eq!(install_home(&env), r"D:\Home");
        let env = |name: &str| (name == "USERPROFILE").then(|| r"C:\Users\ExampleUser".to_owned());
        assert_eq!(install_home(&env), r"C:\Users\ExampleUser\.codex-auto-resume");
        let env = |name: &str| (name == "CODEX_AUTO_RESUME_PLUGIN_HOME").then(|| r"E:\Plugin".to_owned());
        assert_eq!(install_home(&env), r"E:\Plugin");
    }

    #[test]
    fn the_child_is_the_core_s_hook_role_with_its_home_and_no_window() {
        let home = r"C:\Users\ExampleUser\.codex-auto-resume";
        assert_eq!(
            arguments(home),
            [
                r"C:\Users\ExampleUser\.codex-auto-resume\app\bin\codex-auto-resume.exe",
                "hook",
                "--home",
                home
            ]
        );
        let spawn = spawn_for(arguments(home), home);
        assert_eq!(
            (spawn.stdin, spawn.stdout, spawn.stderr),
            (Stream::Piped, Stream::Piped, Stream::Piped)
        );
        assert_eq!(spawn.flags() & CREATE_NO_WINDOW, CREATE_NO_WINDOW);
    }

    #[test]
    fn nothing_installed_is_nothing_to_ask() {
        let folder = std::env::temp_dir().join(format!("car-hook-launcher-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        std::fs::create_dir_all(folder.join("app").join("bin")).unwrap();
        let home = folder.to_string_lossy().into_owned();
        assert!(!installed(&home), "no core");
        std::fs::write(car_bin::launcher::core_of(&home), b"MZ").unwrap();
        assert!(!installed(&home), "a core but no app\\src");
        std::fs::create_dir_all(folder.join("app").join("src")).unwrap();
        assert!(installed(&home));
        let _ = std::fs::remove_dir_all(&folder);
    }

    #[test]
    fn the_answer_of_a_child_that_ended_0_is_relayed_whole_with_its_input_handed_over() {
        // `more` writes what it reads to its standard output: the input reached the child, and came back whole.
        let got = answer(&cmd(&["more"]), given(b"{\"decision\":\"block\"}"), BOUND);
        let text = String::from_utf8(got.expect("relayed")).unwrap();
        assert_eq!(text.trim_end(), "{\"decision\":\"block\"}");
    }

    #[test]
    fn standard_error_is_dropped() {
        let got = answer(&cmd(&["echo", "said", "1>&2"]), given(b""), BOUND);
        assert_eq!(got, Some(Vec::new()));
    }

    #[test]
    fn a_child_that_failed_passes() {
        let got = answer(&cmd(&["echo", "block", "&", "exit", "/b", "1"]), given(b""), BOUND);
        assert_eq!(got, None);
    }

    #[test]
    fn a_child_past_the_bound_is_ended_and_passes() {
        let started = Instant::now();
        let got = answer(
            &cmd(&["ping", "-n", "6", "127.0.0.1", ">nul"]),
            given(b""),
            Duration::from_millis(500),
        );
        assert_eq!(got, None);
        assert!(started.elapsed() < Duration::from_secs(4), "{:?}", started.elapsed());
    }

    #[test]
    fn an_input_that_never_ends_does_not_hold_the_launcher() {
        struct Endless;
        impl Read for Endless {
            fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
                std::thread::sleep(Duration::from_secs(60));
                Ok(0)
            }
        }
        let started = Instant::now();
        let got = answer(&cmd(&["echo", "go", "on"]), Box::new(Endless), BOUND);
        assert_eq!(
            String::from_utf8(got.expect("relayed")).unwrap().trim_end(),
            "go on"
        );
        assert!(started.elapsed() < Duration::from_secs(5), "{:?}", started.elapsed());
    }

    #[test]
    fn a_program_that_cannot_start_passes() {
        let spawn = spawn_for(
            vec![r"C:\nowhere\codex-auto-resume.exe".to_owned()],
            &std::env::temp_dir().to_string_lossy(),
        );
        assert_eq!(answer(&spawn, given(b""), BOUND), None);
    }
}
