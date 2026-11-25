//! car-legacy: `runtime\python.exe` and `runtime\pythonw.exe` of a Rust installation (D9, PLAN 6.1 and 6.4).
//!
//! Every Python version published before the port started its installation through those two names, and some of what
//! it left behind still does after the installation is Rust: a bootstrap Codex keeps in its plugin copy (its repair
//! branch and `Invoke-InstalledSetup` run the INSTALLED `runtime\python.exe app\scripts\plugin_setup.py <command>`),
//! a sign-in Run value or a notification-button handler an earlier version wrote, the MCP launcher a Codex plugin
//! copy holds, the skill a Codex plugin copy holds (and the Rust archive ships again: `runtime\python.exe
//! app\scripts\plugin_setup.py <command>` for `status`, `enable`, `cancel <thread-uuid>`, `uninstall --purge`, ...), the
//! Start-menu shortcut `install` made where the home had no settings window, and a settings window of an earlier
//! version still open across the update (its Repair and its Desktop-shortcut box). This program answers to those names, and to nothing else: it accepts only the exact command lines in
//! [`ACCEPTED`], which `rust/tools/legacy_lines.py` collects from every tag (`tests/data/published.txt`; the test
//! `published` holds the two to each other both ways). Any other command line is refused with nothing run.
//!
//! An accepted line is handed to the Rust program that replaces the script it names, with the same words after it:
//!
//! | the line names | the Rust program (`<home>\app\bin\`) | how |
//! |---|---|---|
//! | `app\scripts\plugin_setup.py <command> ...` | `codex-auto-resume.exe <command> ...` | waited for; its streams and exit code are this one's |
//! | the MCP launcher's `-c <code> <home>\app\src --home <home>` | `codex-auto-resume.exe mcp --home <home>` (D18) | the same |
//! | `watcher-launcher.py activate <uri>`, `app\src\auto_resume.py ... activate <uri>` | `codex-auto-resume.exe` with the same words | waited for, no streams |
//! | `watcher-launcher.py run`, `app\src\auto_resume.py --home <home> run` | the watcher host, `CodexAutoResume.exe` with the same words | started, not waited for |
//!
//! The child's environment is this process's with `CODEX_AUTO_RESUME_LEGACY_ENTRY` set to the line's [`Shape`] word, so
//! the Rust side knows it was reached through a registration or an updater of a Python version, and re-registers the
//! sign-in value and the protocol handler onto its own programs (PLAN 6.4) - `setup` does that in any case. Every child
//! is started through car-platform's one starter, with `CREATE_NO_WINDOW` (brief rule 12).
//!
//! Exit codes of this program itself: [`REFUSED`] (2, argparse's: an updater reads it as "this version has no such
//! command", which is what it is) and [`MISSING`] (1: the Rust program is not there or could not be started, or this
//! program failed). A message it cannot write (no stderr, a closed pipe) changes neither: the code is the answer, as
//! argparse's own `_print_message` drops a message it cannot write and still ends with 2.

use std::ffi::OsString;
use std::io::Write;
use std::path::{Path, PathBuf};

use car_platform::startup::{PROTOCOL_SCHEME, same_path};

/// A command line no published version used: nothing was run.
pub const REFUSED: i32 = 2;
/// The Rust program the line maps to is missing, or could not be started.
pub const MISSING: i32 = 1;
/// The variable the child is told its way in by.
pub const ENTRY_VARIABLE: &str = "CODEX_AUTO_RESUME_LEGACY_ENTRY";
/// The Rust core's console program and the watcher host, inside `<home>\app\bin` (PLAN 1.7, 6.1).
pub const CORE: &str = "codex-auto-resume.exe";
pub const HOST: &str = "CodexAutoResume.exe";

/// Which of the two stand-ins is running.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Program {
    /// `python.exe`: console subsystem; what bootstraps and the MCP launcher start.
    Console,
    /// `pythonw.exe`: GUI subsystem; what Windows starts from a Run value or a protocol handler.
    Windowless,
}

impl Program {
    pub fn file_name(self) -> &'static str {
        match self {
            Program::Console => "python.exe",
            Program::Windowless => "pythonw.exe",
        }
    }
}

/// What an accepted line is, as the child is told it (`CODEX_AUTO_RESUME_LEGACY_ENTRY`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Shape {
    Setup,
    WatcherRunning,
    DowngradeState,
    RemoveEntry,
    Mcp,
    Run,
    Activate,
    /// Any other `plugin_setup.py` command a published skill, document or settings window runs (`status`, `cancel`, ...).
    Command,
    /// The Start-menu or Desktop shortcut `install` made where the home had no settings window (`... status`).
    Shortcut,
}

impl Shape {
    pub fn word(self) -> &'static str {
        match self {
            Shape::Setup => "setup",
            Shape::WatcherRunning => "watcher-running",
            Shape::DowngradeState => "downgrade-state",
            Shape::RemoveEntry => "remove-entry",
            Shape::Mcp => "mcp",
            Shape::Run => "run",
            Shape::Activate => "activate",
            Shape::Command => "command",
            Shape::Shortcut => "shortcut",
        }
    }
}

/// Which Rust program a line goes to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Target {
    /// `codex-auto-resume.exe`, waited for.
    Core,
    /// `CodexAutoResume.exe`, the watcher host, started and left running.
    Host,
}

impl Target {
    pub fn file_name(self) -> &'static str {
        match self {
            Target::Core => CORE,
            Target::Host => HOST,
        }
    }
}

/// One accepted command line: its arguments after the program, with `{home}` for the installation (any spelling of
/// the same folder), `{uri}` for a `codex-auto-resume:` URI and `{value}` for one value the script's parser takes (a
/// thread id, a number of lines: [`value_word`]); every other word exactly as written.
#[derive(Debug, Clone, Copy)]
pub struct Line {
    pub program: Program,
    pub argv: &'static [&'static str],
    pub shape: Shape,
    pub target: Target,
    /// Words the Rust program is given first (`mcp` for the MCP launcher's line).
    pub lead: &'static [&'static str],
    /// The first argument of `argv` handed on after `lead`: what follows the script.
    pub tail_from: usize,
}

const SETUP: &str = "{home}\\app\\scripts\\plugin_setup.py";
const LAUNCHER: &str = "{home}\\watcher-launcher.py";
const ENTRY: &str = "{home}\\app\\src\\auto_resume.py";
/// The MCP launcher's code, as every `gui/McpLauncher.cs` from v0.5.0 joins it.
pub const MCP_CODE: &str = "import sys;sys.path.insert(0,sys.argv[1]);from codex_auto_resume.mcpserver import main;sys.exit(main(sys.argv[2:]))";

macro_rules! console {
    ($shape:ident, $tail:expr, [$($word:expr),*]) => {
        Line { program: Program::Console, argv: &[$($word),*], shape: Shape::$shape, target: Target::Core, lead: &[],
               tail_from: $tail }
    };
}

macro_rules! windowless {
    ($shape:ident, $target:ident, $tail:expr, [$($word:expr),*]) => {
        Line { program: Program::Windowless, argv: &[$($word),*], shape: Shape::$shape, target: Target::$target,
               lead: &[], tail_from: $tail }
    };
}

/// Every command line a published version starts `runtime\python.exe` or `runtime\pythonw.exe` with, and nothing more.
/// `tests/published.rs` holds this to `tests/data/published.txt` (`rust/tools/legacy_lines.py`) both ways.
pub const ACCEPTED: &[Line] = &[
    // The bootstraps' repair branch (v0.5.2-v0.5.7 without --keep-state) and Invoke-InstalledSetup (v0.6.12 on);
    // `-X disable-remote-debug` from v0.6.19-beta.3.
    console!(Setup, 1, [SETUP, "setup"]),
    console!(Setup, 1, [SETUP, "setup", "--no-startup"]),
    console!(Setup, 1, [SETUP, "setup", "--keep-state"]),
    console!(Setup, 1, [SETUP, "setup", "--keep-state", "--no-startup"]),
    console!(
        Setup,
        1,
        [SETUP, "setup", "--keep-state", "--watcher-was-stopped"]
    ),
    console!(
        Setup,
        1,
        [
            SETUP,
            "setup",
            "--keep-state",
            "--no-startup",
            "--watcher-was-stopped"
        ]
    ),
    console!(WatcherRunning, 1, [SETUP, "watcher-running"]),
    console!(
        DowngradeState,
        1,
        [SETUP, "downgrade-state", "--to", "3", "--stop-watcher"]
    ),
    console!(
        DowngradeState,
        1,
        [SETUP, "downgrade-state", "--to", "4", "--stop-watcher"]
    ),
    console!(RemoveEntry, 1, [SETUP, "remove-entry"]),
    console!(
        Setup,
        3,
        ["-X", "disable-remote-debug", SETUP, "setup", "--keep-state"]
    ),
    console!(
        Setup,
        3,
        [
            "-X",
            "disable-remote-debug",
            SETUP,
            "setup",
            "--keep-state",
            "--no-startup"
        ]
    ),
    console!(
        Setup,
        3,
        [
            "-X",
            "disable-remote-debug",
            SETUP,
            "setup",
            "--keep-state",
            "--watcher-was-stopped"
        ]
    ),
    console!(
        Setup,
        3,
        [
            "-X",
            "disable-remote-debug",
            SETUP,
            "setup",
            "--keep-state",
            "--no-startup",
            "--watcher-was-stopped"
        ]
    ),
    console!(
        WatcherRunning,
        3,
        ["-X", "disable-remote-debug", SETUP, "watcher-running"]
    ),
    console!(
        DowngradeState,
        3,
        [
            "-X",
            "disable-remote-debug",
            SETUP,
            "downgrade-state",
            "--to",
            "3",
            "--stop-watcher"
        ]
    ),
    console!(
        DowngradeState,
        3,
        [
            "-X",
            "disable-remote-debug",
            SETUP,
            "downgrade-state",
            "--to",
            "4",
            "--stop-watcher"
        ]
    ),
    console!(
        RemoveEntry,
        3,
        ["-X", "disable-remote-debug", SETUP, "remove-entry"]
    ),
    // The skill's Commands table (every tag's skills/codex-auto-resume/SKILL.md, which the Rust archive ships too), in
    // the shapes each tag's own build_parser takes those commands: positionals, and each option alone.
    console!(Command, 1, [SETUP, "enable"]),
    console!(Command, 1, [SETUP, "disable"]),
    console!(Command, 1, [SETUP, "status"]),
    console!(Command, 1, [SETUP, "pending"]),
    console!(Command, 1, [SETUP, "cancel", "{value}"]),
    console!(Command, 1, [SETUP, "stop"]),
    console!(Command, 1, [SETUP, "doctor"]),
    console!(Command, 1, [SETUP, "logs"]),
    console!(Command, 1, [SETUP, "logs", "-n", "{value}"]),
    console!(Command, 1, [SETUP, "logs", "--lines", "{value}"]),
    console!(Command, 1, [SETUP, "uninstall"]),
    console!(Command, 1, [SETUP, "uninstall", "--purge"]),
    // A settings window of v0.6.19-beta.3 on, open across the update: its Desktop-shortcut box (gui/InstallerFlow.cs).
    console!(
        Command,
        3,
        [
            "-X",
            "disable-remote-debug",
            SETUP,
            "desktop-shortcut",
            "make"
        ]
    ),
    console!(
        Command,
        3,
        [
            "-X",
            "disable-remote-debug",
            SETUP,
            "desktop-shortcut",
            "remove"
        ]
    ),
    // The MCP launcher a Codex plugin copy keeps (gui/McpLauncher.cs): `-X disable-remote-debug` from v0.6.19-beta.3.
    Line {
        program: Program::Console,
        argv: &["-I", "-c", MCP_CODE, "{home}\\app\\src", "--home", "{home}"],
        shape: Shape::Mcp,
        target: Target::Core,
        lead: &["mcp"],
        tail_from: 4,
    },
    Line {
        program: Program::Console,
        argv: &[
            "-I",
            "-X",
            "disable-remote-debug",
            "-c",
            MCP_CODE,
            "{home}\\app\\src",
            "--home",
            "{home}",
        ],
        shape: Shape::Mcp,
        target: Target::Core,
        lead: &["mcp"],
        tail_from: 6,
    },
    // The sign-in Run value: setup's (watcher-launcher.py, every version) and `install --startup`'s (auto_resume.py).
    windowless!(Run, Host, 1, [LAUNCHER, "run"]),
    windowless!(Run, Host, 1, [ENTRY, "--home", "{home}", "run"]),
    // The Start-menu (and Desktop) shortcut `install` made with no settings window in the home: `-X ...` from
    // v0.6.19-beta.3.
    windowless!(Shortcut, Core, 1, [LAUNCHER, "--home", "{home}", "status"]),
    windowless!(Shortcut, Core, 1, [ENTRY, "--home", "{home}", "status"]),
    windowless!(
        Shortcut,
        Core,
        3,
        [
            "-X",
            "disable-remote-debug",
            LAUNCHER,
            "--home",
            "{home}",
            "status"
        ]
    ),
    windowless!(
        Shortcut,
        Core,
        3,
        [
            "-X",
            "disable-remote-debug",
            ENTRY,
            "--home",
            "{home}",
            "status"
        ]
    ),
    // The notification button's protocol handler, setup's and `install`'s: `-X ...` from v0.6.19-beta.3.
    windowless!(Activate, Core, 1, [LAUNCHER, "activate", "{uri}"]),
    windowless!(
        Activate,
        Core,
        3,
        ["-X", "disable-remote-debug", LAUNCHER, "activate", "{uri}"]
    ),
    windowless!(
        Activate,
        Core,
        1,
        [ENTRY, "--home", "{home}", "--quiet", "activate", "{uri}"]
    ),
    windowless!(
        Activate,
        Core,
        3,
        [
            "-X",
            "disable-remote-debug",
            ENTRY,
            "--home",
            "{home}",
            "--quiet",
            "activate",
            "{uri}"
        ]
    ),
];

/// What to run for an accepted line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Plan {
    pub shape: Shape,
    pub target: Target,
    /// The Rust program's full path, inside the installation.
    pub program: PathBuf,
    /// Its arguments.
    pub args: Vec<String>,
}

/// Why a line was refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Refusal {
    /// An argument that is not Unicode: no published version wrote one.
    NotText,
    /// This program does not sit in `<home>\runtime`.
    NotInstalled,
    /// No published version used this command line.
    Unknown,
}

/// The installation this stand-in belongs to: the folder above its own `runtime` folder.
pub fn home_of(executable: &Path) -> Result<PathBuf, Refusal> {
    let folder = executable.parent().ok_or(Refusal::NotInstalled)?;
    let named = folder
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("");
    if !named.eq_ignore_ascii_case("runtime") {
        return Err(Refusal::NotInstalled);
    }
    folder
        .parent()
        .map(Path::to_path_buf)
        .ok_or(Refusal::NotInstalled)
}

fn home_text(home: &Path) -> String {
    home.to_string_lossy().into_owned()
}

/// A path as written, without the `\\?\` (or `\\?\UNC\`) prefix Windows and Python take it with: the script it names is
/// the same file either way, and an earlier version's Python ran it in both spellings.
fn unprefixed(argument: &str) -> String {
    if let Some(rest) = argument.strip_prefix("\\\\?\\UNC\\") {
        return format!("\\\\{rest}");
    }
    argument
        .strip_prefix("\\\\?\\")
        .unwrap_or(argument)
        .to_string()
}

/// Whether argparse would take `argument` as a value (a positional or an option's value) rather than as an option: it
/// does not start with `-`, or is `-` alone, or looks like a negative number (`_negative_number_matcher`, none of these
/// parsers having an option that looks like one), or holds a space. Anything else would be an option the parser does not
/// have, which it refuses.
pub fn value_word(argument: &str) -> bool {
    if argument.len() > 32_768 {
        return false;
    }
    let Some(rest) = argument.strip_prefix('-') else {
        return true;
    };
    if rest.is_empty() || argument.contains(' ') {
        return true;
    }
    let digits = |text: &str| !text.is_empty() && text.chars().all(|c| c.is_ascii_digit());
    match rest.split_once('.') {
        None => digits(rest),
        Some((whole, fraction)) => whole.chars().all(|c| c.is_ascii_digit()) && digits(fraction),
    }
}

/// Whether `argument` is the template `word` at `home`.
fn matches(word: &str, argument: &str, home: &Path) -> bool {
    if word == "{uri}" {
        let scheme = format!("{PROTOCOL_SCHEME}:");
        // `codex-auto-resume:` alone too: the old handler handed any URI of the scheme to its parser.
        return argument.len() >= scheme.len()
            && argument.is_char_boundary(scheme.len())
            && argument[..scheme.len()].eq_ignore_ascii_case(&scheme)
            && argument.len() <= 32_768;
    }
    if word == "{value}" {
        return value_word(argument);
    }
    if let Some(rest) = word.strip_prefix("{home}") {
        if argument.is_empty() {
            return false;
        }
        let wanted = format!("{}{}", home_text(home).trim_end_matches(['\\', '/']), rest);
        return same_path(&unprefixed(argument), &unprefixed(&wanted));
    }
    word == argument
}

/// The line `args` (after the program) is, for this program at `home`, or why it is none.
pub fn line_for(program: Program, home: &Path, args: &[String]) -> Result<&'static Line, Refusal> {
    ACCEPTED
        .iter()
        .find(|line| {
            line.program == program
                && line.argv.len() == args.len()
                && line
                    .argv
                    .iter()
                    .zip(args)
                    .all(|(word, argument)| matches(word, argument, home))
        })
        .ok_or(Refusal::Unknown)
}

/// The plan for `args` given to this program at `executable`.
pub fn plan(program: Program, executable: &Path, args: &[OsString]) -> Result<Plan, Refusal> {
    let home = home_of(executable)?;
    let args: Vec<String> = args
        .iter()
        .map(|argument| {
            argument
                .to_str()
                .map(str::to_string)
                .ok_or(Refusal::NotText)
        })
        .collect::<Result<_, _>>()?;
    let line = line_for(program, &home, &args)?;
    let mut handed: Vec<String> = line.lead.iter().map(|word| word.to_string()).collect();
    handed.extend(args[line.tail_from..].iter().cloned());
    Ok(Plan {
        shape: line.shape,
        target: line.target,
        program: home.join("app").join("bin").join(line.target.file_name()),
        args: handed,
    })
}

/// Run `plan`: the exit code this program ends with.
pub fn run(program: Program, plan: &Plan) -> i32 {
    use car_platform::spawn::{Spawn, Stream, SystemStarter};

    if !plan.program.is_file() {
        if program == Program::Console {
            say(&format!(
                "codex-auto-resume: {} is not in this installation, so `{}` could not be run",
                plan.program.display(),
                plan.args.join(" ")
            ));
        }
        return MISSING;
    }
    let mut argv = vec![plan.program.to_string_lossy().into_owned()];
    argv.extend(plan.args.iter().cloned());
    let mut env: Vec<(OsString, OsString)> = std::env::vars_os()
        .filter(|(name, _)| !name.to_string_lossy().eq_ignore_ascii_case(ENTRY_VARIABLE))
        .collect();
    env.push((ENTRY_VARIABLE.into(), plan.shape.word().into()));
    let streams = match program {
        Program::Console => Stream::Inherit,
        Program::Windowless => Stream::Null,
    };
    let mut spawn = Spawn::new(argv)
        .with_env(env)
        .with_streams(streams, streams, streams);
    if let Some(folder) = plan.program.parent() {
        spawn = spawn.with_cwd(folder);
    }
    let started = match SystemStarter.start(&spawn) {
        Ok(child) => child,
        Err(error) => {
            if program == Program::Console {
                say(&format!(
                    "codex-auto-resume: {} could not be started: {error}",
                    plan.program.display()
                ));
            }
            return MISSING;
        }
    };
    if plan.target == Target::Host {
        // The watcher outlives this process, as the Python one it replaces did.
        return 0;
    }
    let mut child = started;
    match child.wait() {
        Ok(status) => status.code().unwrap_or(MISSING),
        Err(_) => MISSING,
    }
}

/// One line to stderr, or nothing where it cannot be written: never a panic (exit 101), so the code stays the answer.
fn say(line: &str) {
    let mut stderr = std::io::stderr().lock();
    let _ = writeln!(stderr, "{line}");
    let _ = stderr.flush();
}

/// The whole of either stand-in's `main`: its exit code. A panic is caught here (D15) and ends with [`MISSING`], as an
/// uncaught Python exception ends with 1; the default hook's message is not written (it could panic in turn).
pub fn main_for(program: Program) -> i32 {
    std::panic::set_hook(Box::new(|_| {}));
    std::panic::catch_unwind(|| entry(program)).unwrap_or(MISSING)
}

fn entry(program: Program) -> i32 {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let executable = match std::env::current_exe() {
        Ok(path) => path,
        Err(_) => return MISSING,
    };
    match plan(program, &executable, &args) {
        Ok(plan) => run(program, &plan),
        Err(refusal) => {
            if program == Program::Console {
                let shown: Vec<String> = args
                    .iter()
                    .map(|argument| argument.to_string_lossy().into_owned())
                    .collect();
                say(&format!(
                    "codex-auto-resume: this {} is the compatibility entry of a Codex Auto Resume installation; it runs only \
                     the command lines earlier versions used, and `{}` is not one ({refusal:?}). Nothing was run.",
                    program.file_name(),
                    shown.join(" ")
                ));
            }
            REFUSED
        }
    }
}
