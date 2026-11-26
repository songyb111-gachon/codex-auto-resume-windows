//! car-bin: the shared half of the binaries, so the other edition's build can reuse it (seat S5.2).
//!
//! The core's library: [`roles::main_with`] is `codex-auto-resume.exe`'s dispatcher once it is the core - the bridge
//! (`bridge`), the MCP server (`mcp`), `plugin_setup.py`'s commands ([`setup`]) and the command line ([`cli`]), every
//! word parsed as the reference's argparse parses it ([`argparse`] over the tag's own tables, `parsers_gen.rs`). The
//! advanced edition's binary passes its own [`Role`]s to [`main_with`]: the role registry seam (P7-DESIGN). car-harness's
//! `car-core-stub` (the CODEX_AR_CORE=rust shim) and `car-core-world` (the legacy shapes' diff) run it today.
//!
//! `codex-auto-resume.exe` itself is still the **stub core** the packaging skeleton (S8.1) ships ([`core_main`]): every
//! command is refused with [`NOT_PORTED`], so an old updater that reaches it through car-legacy (D9) ends on a code it
//! already reads as "did not finish" and changes nothing. The stub never answers success for work it did not do. One
//! exception, for the installer's proofs only (S8.2): where [`TEST_CORE`] names a program, the stub hands every command to
//! that program - the test double of `tests/install_double.py` - and ends with its code. It stays the stub until the
//! release's own proofs (`rust_legacy_bootstraps.check_entry`, the installer proofs) can run the real core on a scratch
//! home without its registrations reaching HKCU (Integration 8: [`main_with`]'s `setup` writes the Run value, the AUMID
//! and the link handler through car-platform, which no scratch home redirects).
//!
//! `codex-auto-resume-setup.exe` is the setup program v0.6.26's bootstrap hands a Rust archive over to (BRIDGE.md
//! section 4, [`setup_main`]): it runs the archive's own `install\install.ps1` - the installer every route ends in -
//! with no window of any kind, waits for it, keeps what it printed in a log, and ends with its code.

use std::ffi::OsString;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use car_platform::spawn::{Spawn, Stream, SystemStarter};

pub mod argparse;
pub mod cli;
pub mod launcher;
#[rustfmt::skip]
pub mod parsers_gen;
pub mod roles;
pub mod seam;
pub mod setup;
pub mod uris;

pub use roles::{Role, main_with};

/// The code a command that is not ported yet ends with (as `car-core-stub` and the shim lane answer it).
pub const NOT_PORTED: i32 = 3;

/// The program the stub core hands every command to, where it is set: the installer proofs' test double (S8.2).
pub const TEST_CORE: &str = "CODEX_AUTO_RESUME_TEST_CORE";
/// An argument put before the command's words (the double's script, when [`TEST_CORE`] is an interpreter).
pub const TEST_CORE_SCRIPT: &str = "CODEX_AUTO_RESUME_TEST_CORE_SCRIPT";
/// Set for the double: the stub core that handed the command on (the payload's copy, or the installation's).
pub const TEST_CORE_EXE: &str = "CODEX_AUTO_RESUME_TEST_CORE_EXE";

/// `codex-auto-resume.exe <words>`: the test double's answer where [`TEST_CORE`] names one; otherwise one line on
/// standard error naming the words, then [`NOT_PORTED`].
pub fn core_stub(words: &[String]) -> i32 {
    if let Some(code) = test_double(words) {
        return code;
    }
    say(&format!(
        "codex-auto-resume: `{}` is not ported yet (stub core); nothing was done",
        words.join(" ")
    ));
    NOT_PORTED
}

/// The whole of `codex-auto-resume.exe`'s `main`: a panic is caught (D15) and ends with 1.
pub fn core_main() -> i32 {
    std::panic::set_hook(Box::new(|_| {}));
    // A thread with the stack for a deeply nested document (car_machine::stack): the panic it ends with is caught here.
    std::panic::catch_unwind(|| car_machine::stack::run_deep(|| core_stub(&arguments())))
        .unwrap_or(1)
}

/// The command handed to the test double, waited for, its code answered; `None` where no double is named.
fn test_double(words: &[String]) -> Option<i32> {
    let program = std::env::var_os(TEST_CORE).filter(|value| !value.is_empty())?;
    let program = PathBuf::from(program);
    if !program.is_file() {
        say(&format!(
            "codex-auto-resume: {TEST_CORE} names {}, which is not a file; nothing was done",
            program.display()
        ));
        return Some(1);
    }
    let mut argv = vec![program.to_string_lossy().into_owned()];
    if let Some(script) = std::env::var_os(TEST_CORE_SCRIPT).filter(|value| !value.is_empty()) {
        argv.push(script.to_string_lossy().into_owned());
    }
    argv.extend(words.iter().cloned());
    let mut env: Vec<(OsString, OsString)> = std::env::vars_os()
        .filter(|(name, _)| !name.to_string_lossy().eq_ignore_ascii_case(TEST_CORE_EXE))
        .collect();
    if let Ok(me) = std::env::current_exe() {
        env.push((TEST_CORE_EXE.into(), me.into_os_string()));
    }
    let spawn = Spawn::new(argv).with_env(env).with_streams(
        Stream::Inherit,
        Stream::Inherit,
        Stream::Inherit,
    );
    match SystemStarter.start(&spawn) {
        Ok(mut child) => Some(
            child
                .wait()
                .ok()
                .and_then(|status| status.code())
                .unwrap_or(1),
        ),
        Err(error) => {
            say(&format!(
                "codex-auto-resume: the test double could not be started: {error}"
            ));
            Some(1)
        }
    }
}

/// install.ps1's code for an edition change nobody asked for (`$EDITION_CHANGE_REFUSED`), which the setup program
/// also ends with when it is handed an edition other than its own (BRIDGE.md section 4).
pub const EDITION_REFUSED: i32 = 14;
/// Words the setup program does not take (argparse's code: "no such command" to whoever reads it).
pub const USAGE: i32 = 2;
/// Nothing could be run: no installer beside the program, no Windows PowerShell, a start Windows refused.
pub const FAILED: i32 = 1;
/// The log the setup program keeps of what the installer printed, in the user's temporary folder: the folder it runs
/// from is deleted by the bootstrap once it ends (BRIDGE.md section 4).
pub const SETUP_LOG: &str = "CodexAutoResume-Setup.log";

/// What the setup program was handed (BRIDGE.md section 3), in install.ps1's own words.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Handover {
    /// `update`, `another` or `install`; `None` where no `-Handover` was given.
    pub mode: Option<String>,
    /// `standard` or `advanced`, where `-Edition` was given.
    pub edition: Option<String>,
    pub skip_startup: bool,
    pub allow_edition_change: bool,
    pub delete_saved_accounts: bool,
    /// The setup program's own: no Dashboard opened at the end (a caller with no person in front of it).
    pub silent: bool,
}

/// The words as BRIDGE.md section 3 gives them: `-Handover update|another|install -Edition standard|advanced
/// [-SkipStartup] [-AllowEditionChange] [-DeleteSavedAccounts]`, and `-Silent`. Names and values are read without
/// regard to case, as PowerShell reads a script's parameters; anything else is refused.
pub fn parse_setup(words: &[String]) -> Result<Handover, String> {
    let mut handover = Handover::default();
    let mut index = 0;
    while index < words.len() {
        let word = words[index].to_ascii_lowercase();
        match word.as_str() {
            "-handover" | "-edition" => {
                let Some(value) = words.get(index + 1) else {
                    return Err(format!("{} needs a value", words[index]));
                };
                let value = value.to_ascii_lowercase();
                if word == "-handover" {
                    if !matches!(value.as_str(), "update" | "another" | "install") {
                        return Err(format!(
                            "-Handover takes update, another or install, not {value}"
                        ));
                    }
                    handover.mode = Some(value);
                } else {
                    if !matches!(value.as_str(), "standard" | "advanced") {
                        return Err(format!("-Edition takes standard or advanced, not {value}"));
                    }
                    handover.edition = Some(value);
                }
                index += 2;
                continue;
            }
            "-skipstartup" => handover.skip_startup = true,
            "-alloweditionchange" => handover.allow_edition_change = true,
            "-deletesavedaccounts" => handover.delete_saved_accounts = true,
            "-silent" => handover.silent = true,
            _ => {
                return Err(format!("{} is not a word this program takes", words[index]));
            }
        }
        index += 1;
    }
    Ok(handover)
}

/// install.ps1's arguments for `handover`, after `-File <install.ps1>`: install.ps1's own switches, as today's setup
/// program passes them to Install.cmd, and `-Silent`, since nothing here can answer a question.
pub fn installer_switches(handover: &Handover) -> Vec<String> {
    let mut switches = vec!["-Silent".to_string()];
    if handover.skip_startup {
        switches.push("-SkipStartup".into());
    }
    if handover.allow_edition_change {
        switches.push("-AllowEditionChange".into());
    }
    if handover.delete_saved_accounts {
        switches.push("-DeleteSavedAccounts".into());
    }
    switches
}

/// The archive this setup program came in: `<root>\payload\app\bin\codex-auto-resume-setup.exe`, so four folders up,
/// where `install\install.ps1` must be.
pub fn archive_root(program: &Path) -> Option<PathBuf> {
    let root = program.parent()?.parent()?.parent()?.parent()?;
    root.join("install")
        .join("install.ps1")
        .is_file()
        .then(|| root.to_path_buf())
}

/// Windows PowerShell 5.1, by the system folder: never a `powershell` found on PATH.
fn powershell() -> Option<PathBuf> {
    let system = std::env::var_os("SystemRoot")
        .or_else(|| std::env::var_os("windir"))
        .filter(|value| !value.is_empty())?;
    let path = PathBuf::from(system)
        .join("System32")
        .join("WindowsPowerShell")
        .join("v1.0")
        .join("powershell.exe");
    path.is_file().then_some(path)
}

/// The installation home, as install.ps1 reads it: CODEX_AUTO_RESUME_PLUGIN_HOME where it is set, else
/// `.codex-auto-resume` in the profile.
fn install_home() -> Option<PathBuf> {
    if let Some(home) = std::env::var_os("CODEX_AUTO_RESUME_PLUGIN_HOME")
        && !home.to_string_lossy().trim().is_empty()
    {
        return Some(PathBuf::from(home));
    }
    std::env::var_os("USERPROFILE")
        .filter(|value| !value.is_empty())
        .map(|profile| PathBuf::from(profile).join(".codex-auto-resume"))
}

/// `codex-auto-resume-setup.exe <words>` (BRIDGE.md section 4), for `edition`, the edition this program was built for.
///
/// Handed over (`-Handover`), it takes the person's yes as given and runs the archive's own installer,
/// `install\install.ps1`, with install.ps1's switches: the installer takes the install lock
/// (`Local\CodexAutoResume.Install`) itself, stops the watcher, closes this installation's Dashboards but the one
/// CODEX_AUTO_RESUME_UPDATING_DASHBOARD names, keeps the state, refuses an edition change without -AllowEditionChange
/// (14), and ends with 0 only when it installed. This program waits for it - so nothing it leaves running runs from
/// the folder the bootstrap deletes - and ends with its code; at the end of an install that succeeded it opens the
/// new Dashboard, as today's setup window does. An `-Edition` other than its own ends with 14 before anything is run.
/// Without `-Handover` nothing is run (the window that would ask first is P6's).
pub fn setup_main(edition: &str, words: &[String]) -> i32 {
    std::panic::set_hook(Box::new(|_| {}));
    let (edition, words) = (edition.to_owned(), words.to_vec());
    std::panic::catch_unwind(|| car_machine::stack::run_deep(move || setup(&edition, &words)))
        .unwrap_or(FAILED)
}

fn setup(edition: &str, words: &[String]) -> i32 {
    let handover = match parse_setup(words) {
        Ok(handover) => handover,
        Err(_) => return USAGE,
    };
    if handover.mode.is_none() {
        return USAGE;
    }
    if handover
        .edition
        .as_deref()
        .is_some_and(|asked| asked != edition)
    {
        return EDITION_REFUSED;
    }
    let Some(root) = std::env::current_exe()
        .ok()
        .and_then(|program| archive_root(&program))
    else {
        return FAILED;
    };
    let Some(powershell) = powershell() else {
        return FAILED;
    };
    let installer = root.join("install").join("install.ps1");
    let mut argv = vec![
        powershell.to_string_lossy().into_owned(),
        "-NoLogo".into(),
        "-NoProfile".into(),
        "-NonInteractive".into(),
        "-ExecutionPolicy".into(),
        "Bypass".into(),
        "-File".into(),
        installer.to_string_lossy().into_owned(),
    ];
    argv.extend(installer_switches(&handover));
    let code = run_logged(argv, &root);
    if code == 0 && !handover.silent {
        open_dashboard();
    }
    code
}

type Sink = Arc<Mutex<Option<std::fs::File>>>;

/// Runs the installer with its two streams kept, line by line, in [`SETUP_LOG`]; its exit code, or [`FAILED`].
fn run_logged(argv: Vec<String>, folder: &Path) -> i32 {
    let log = std::env::temp_dir().join(SETUP_LOG);
    let sink: Sink = Arc::new(Mutex::new(std::fs::File::create(log).ok()));
    let spawn =
        Spawn::new(argv)
            .with_cwd(folder)
            .with_streams(Stream::Null, Stream::Piped, Stream::Piped);
    let mut child = match SystemStarter.start(&spawn) {
        Ok(child) => child,
        Err(error) => {
            keep(
                &sink,
                &format!("The installer could not be started: {error}"),
            );
            return FAILED;
        }
    };
    let streams: Vec<Box<dyn Read + Send>> = [
        child
            .stdout
            .take()
            .map(|out| Box::new(out) as Box<dyn Read + Send>),
        child
            .stderr
            .take()
            .map(|err| Box::new(err) as Box<dyn Read + Send>),
    ]
    .into_iter()
    .flatten()
    .collect();
    let readers: Vec<_> = streams
        .into_iter()
        .map(|stream| {
            let sink = Arc::clone(&sink);
            std::thread::spawn(move || {
                for line in BufReader::new(stream).split(b'\n').map_while(Result::ok) {
                    keep(&sink, String::from_utf8_lossy(&line).trim_end_matches('\r'));
                }
            })
        })
        .collect();
    let code = child
        .wait()
        .ok()
        .and_then(|status| status.code())
        .unwrap_or(FAILED);
    for reader in readers {
        let _ = reader.join();
    }
    keep(&sink, &format!("The installer ended with code {code}."));
    code
}

fn keep(sink: &Sink, line: &str) {
    if let Ok(mut guard) = sink.lock()
        && let Some(file) = guard.as_mut()
    {
        let _ = writeln!(file, "{line}");
    }
}

/// The Dashboard of the installation just made, opened as today's setup window opens it at its end: by its own file
/// in the installation, with no argument. A Dashboard that cannot be opened is no failure of the install.
fn open_dashboard() {
    let Some(home) = install_home() else {
        return;
    };
    let dashboard = home.join("CodexAutoResumeSettings.exe");
    if !dashboard.is_file() {
        return;
    }
    // The waiting Dashboard's process id is the bootstrap's word to the installer, not the new window's.
    let env: Vec<(OsString, OsString)> = std::env::vars_os()
        .filter(|(name, _)| {
            !name
                .to_string_lossy()
                .eq_ignore_ascii_case("CODEX_AUTO_RESUME_UPDATING_DASHBOARD")
        })
        .collect();
    let spawn = Spawn::new([dashboard.to_string_lossy().into_owned()])
        .with_env(env)
        .with_cwd(home);
    let _ = SystemStarter.start(&spawn);
}

/// One line to stderr, or nothing where it cannot be written: never a panic.
fn say(line: &str) {
    let mut stderr = std::io::stderr().lock();
    let _ = writeln!(stderr, "{line}");
    let _ = stderr.flush();
}

/// This process's arguments after the program, as text (lossy where one is not Unicode).
pub fn arguments() -> Vec<String> {
    std::env::args_os()
        .skip(1)
        .map(|argument| argument.to_string_lossy().into_owned())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn words(text: &str) -> Vec<String> {
        text.split_whitespace().map(str::to_string).collect()
    }

    #[test]
    fn the_bridge_words_are_read_as_install_ps1_reads_its_switches() {
        let handover = parse_setup(&words(
            "-Handover another -Edition advanced -SkipStartup -AllowEditionChange -DeleteSavedAccounts",
        ))
        .unwrap();
        assert_eq!(handover.mode.as_deref(), Some("another"));
        assert_eq!(handover.edition.as_deref(), Some("advanced"));
        assert!(
            handover.skip_startup
                && handover.allow_edition_change
                && handover.delete_saved_accounts
        );
        assert_eq!(
            installer_switches(&handover),
            words("-Silent -SkipStartup -AllowEditionChange -DeleteSavedAccounts")
        );
        let plain = parse_setup(&words("-handover UPDATE -edition Standard")).unwrap();
        assert_eq!(
            (plain.mode.as_deref(), plain.edition.as_deref()),
            (Some("update"), Some("standard"))
        );
        assert_eq!(installer_switches(&plain), words("-Silent"));
    }

    #[test]
    fn anything_else_is_refused() {
        for given in [
            "-Handover",
            "-Handover later",
            "-Edition other",
            "-Force",
            "update",
            "-Handover update -Edition",
        ] {
            assert!(parse_setup(&words(given)).is_err(), "{given}");
        }
    }

    #[test]
    fn another_edition_ends_with_fourteen_and_no_handover_with_two_before_anything_runs() {
        assert_eq!(
            setup("standard", &words("-Handover update -Edition advanced")),
            EDITION_REFUSED
        );
        assert_eq!(setup("advanced", &words("-Edition advanced")), USAGE);
        assert_eq!(setup("standard", &words("-Handover nope")), USAGE);
    }

    #[test]
    fn the_archive_root_is_four_folders_up_where_its_installer_is() {
        let base = std::env::temp_dir().join(format!("car-bin-root-{}", std::process::id()));
        let program = base
            .join("payload")
            .join("app")
            .join("bin")
            .join("codex-auto-resume-setup.exe");
        std::fs::create_dir_all(program.parent().unwrap()).unwrap();
        assert_eq!(archive_root(&program), None);
        std::fs::create_dir_all(base.join("install")).unwrap();
        std::fs::write(base.join("install").join("install.ps1"), b"#").unwrap();
        assert_eq!(archive_root(&program), Some(base.clone()));
        let _ = std::fs::remove_dir_all(&base);
    }
}
