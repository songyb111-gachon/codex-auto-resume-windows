//! car-legacy: `runtime\python.exe` and `runtime\pythonw.exe` of a Rust installation (D9, PLAN 6.1 and 6.4).
//!
//! Every Python version published before the port started its installation through those two names, and some of what
//! it left behind still does after the installation is Rust: a bootstrap Codex keeps in its plugin copy (its repair
//! branch and `Invoke-InstalledSetup` run the INSTALLED `runtime\python.exe app\scripts\plugin_setup.py <command>`),
//! a sign-in Run value or a notification-button handler an earlier version wrote, and the MCP launcher a Codex plugin
//! copy holds. This program answers to those names, and to nothing else: it accepts only the exact command lines in
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
//! command", which is what it is) and [`MISSING`] (1: the Rust program is not there or could not be started).

use std::ffi::OsString;
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
/// the same folder) and `{uri}` for a `codex-auto-resume:` URI; every other word exactly as written.
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

/// Whether `argument` is the template `word` at `home`.
fn matches(word: &str, argument: &str, home: &Path) -> bool {
    if word == "{uri}" {
        let scheme = format!("{PROTOCOL_SCHEME}:");
        return argument.len() > scheme.len()
            && argument.is_char_boundary(scheme.len())
            && argument[..scheme.len()].eq_ignore_ascii_case(&scheme)
            && argument.len() <= 32_768;
    }
    if let Some(rest) = word.strip_prefix("{home}") {
        if argument.is_empty() {
            return false;
        }
        let wanted = format!("{}{}", home_text(home).trim_end_matches(['\\', '/']), rest);
        return same_path(argument, &wanted);
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
            eprintln!(
                "codex-auto-resume: {} is not in this installation, so `{}` could not be run",
                plan.program.display(),
                plan.args.join(" ")
            );
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
                eprintln!(
                    "codex-auto-resume: {} could not be started: {error}",
                    plan.program.display()
                );
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

/// The whole of either stand-in's `main`: its exit code.
pub fn main_for(program: Program) -> i32 {
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
                eprintln!(
                    "codex-auto-resume: this {} is the compatibility entry of a Codex Auto Resume installation; it runs only \
                     the command lines earlier versions used, and `{}` is not one ({refusal:?}). Nothing was run.",
                    program.file_name(),
                    shown.join(" ")
                );
            }
            REFUSED
        }
    }
}
