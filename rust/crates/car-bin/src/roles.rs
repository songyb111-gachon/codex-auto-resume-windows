//! `codex-auto-resume.exe`'s first word: which program of the reference it stands in for.
//!
//! | first word | the reference | here |
//! |---|---|---|
//! | a role of the edition's own (the advanced build's, P7) | its entry point | [`Role`] in the table the edition's `main` hands [`dispatch`] |
//! | `bridge` | `controlcli.main(argv)` (the window's bridges, PLAN 6.9) | [`bridge`] |
//! | `mcp` | `mcpserver.main(argv)` (the MCP launcher, D18) | [`mcp`] |
//! | a `plugin_setup.py` command | `plugin_setup.main(argv)` | [`crate::setup`] |
//! | anything else | `cli.main(argv)` (`auto_resume.py`) | [`crate::cli`] |
//!
//! The role registry is the seam the other edition fills (P7-DESIGN): that edition's binary passes its own roles,
//! and they are looked at first; the standard build passes none, so no advanced role's name is in its binary.

use std::io::Read;
use std::path::Path;
use std::sync::Arc;

use car_control::host::Host;
use car_machine::json::Value;

use crate::argparse::{self, Exit};
use crate::cli::{Io, Machine};
use crate::parsers_gen::{BRIDGE, CLI, MCP, PARSERS, SETUP};

/// What a role is handed: the machine, the words after its own, the streams.
pub type RoleFn = fn(&Machine, &[String], &mut Io, &mut dyn Read) -> i32;

/// One entry of the role registry: the first word, and what runs it.
#[derive(Clone, Copy)]
pub struct Role {
    pub word: &'static str,
    pub run: RoleFn,
}

/// The standard edition's own roles.
pub const STANDARD: &[Role] = &[
    Role {
        word: "bridge",
        run: bridge,
    },
    Role {
        word: "mcp",
        run: mcp,
    },
    Role {
        word: "engine-trusted",
        run: engine_trusted,
    },
];

/// `engine-trusted <path>` (S8.2's install.ps1, the Store engine's signature): 0 only where `codex.pairing`'s
/// `official_engine(path)` is `(True, "openai_signature")`, 1 otherwise, 2 for a command line without one path.
pub fn engine_trusted(
    machine: &Machine,
    argv: &[String],
    io: &mut Io,
    _stdin: &mut dyn Read,
) -> i32 {
    let [path] = argv else {
        io.warn("usage: codex-auto-resume engine-trusted PATH");
        return 2;
    };
    match machine.outside.official_engine(Path::new(path)) {
        Some((true, reason)) if reason == "openai_signature" => 0,
        _ => 1,
    }
}

/// The commands `plugin_setup.py` has (its parser's choices): a first word that is one of these is `plugin_setup`'s.
pub fn setup_commands() -> Vec<&'static str> {
    PARSERS[SETUP]
        .actions
        .iter()
        .flat_map(|action| action.commands.iter().map(|(word, _)| *word))
        .collect()
}

/// An ended parse, written as argparse writes it: the help on stdout, or the usage and the error on stderr.
pub fn shown(exit: Exit, io: &mut Io) -> i32 {
    let code = exit.code();
    match exit {
        Exit::Help(text) => {
            let _ = io.out.write_all(text.replace('\n', "\r\n").as_bytes());
            let _ = io.out.flush();
        }
        Exit::Error(text) => {
            let _ = io.err.write_all(text.replace('\n', "\r\n").as_bytes());
            let _ = io.err.flush();
        }
    }
    code
}

/// `codex-auto-resume.exe <argv>`: the edition's roles first, then the standard ones, then plugin_setup's commands,
/// then the command line.
pub fn dispatch(
    machine: &Machine,
    extra: &[Role],
    argv: &[String],
    io: &mut Io,
    stdin: &mut dyn Read,
) -> i32 {
    if let Some(first) = argv.first() {
        if let Some(role) = extra.iter().chain(STANDARD).find(|role| role.word == first) {
            return (role.run)(machine, &argv[1..], io, stdin);
        }
        if setup_commands().contains(&first.as_str()) {
            return match argparse::parse_args(PARSERS, SETUP, argv) {
                Ok(args) => crate::setup::run(machine, &args, io),
                Err(exit) => shown(exit, io),
            };
        }
    }
    match argparse::parse_args(PARSERS, CLI, argv) {
        Ok(args) => crate::cli::run(machine, &args, io),
        Err(exit) => shown(exit, io),
    }
}

/// `config.installed_home()` of this program: the folder above `app`, or None for a program run from elsewhere.
fn installed_home(machine: &Machine) -> Option<String> {
    car_config::paths::installed_home(&machine.project_root)
}

/// The argparse lines of the bridge and the MCP server end with `\n`, not `\r\n`: their streams say UTF-8 and LF
/// (`controlcli.use_utf8`), and argparse's own messages go through the same streams.
fn shown_lf(exit: Exit, io: &mut Io) -> i32 {
    let code = exit.code();
    match exit {
        Exit::Help(text) => {
            let _ = io.out.write_all(text.as_bytes());
        }
        Exit::Error(text) => {
            let _ = io.err.write_all(text.replace('\n', "\r\n").as_bytes());
        }
    }
    code
}

/// `controlcli.main(argv)`: `serve`, or one command per process.
pub fn bridge(machine: &Machine, argv: &[String], io: &mut Io, stdin: &mut dyn Read) -> i32 {
    let args = match argparse::parse_args(PARSERS, BRIDGE, argv) {
        Ok(args) => args,
        Err(exit) => return shown_lf(exit, io),
    };
    let home = args
        .get("home")
        .text()
        .filter(|each| !each.is_empty())
        .map(str::to_owned)
        .or_else(|| installed_home(machine));
    let paths = match machine.paths(home.as_deref()) {
        Ok(paths) => paths,
        Err(message) => {
            let _ = io.err.write_all(format!("{message}\r\n").as_bytes());
            return 1;
        }
    };
    let control = machine.control(paths);
    let command = args.get("command").text().unwrap_or_default().to_owned();
    if command == "serve" {
        // The set-aside sweep of the long-lived bridge (`sweep_soon`) is the watcher's (setaside.py, P6).
        return car_control::bridge::serve(&control, stdin, io.out);
    }
    let mut words = vec![command];
    if let Some(json) = args.get("json").text().filter(|each| !each.is_empty()) {
        words.push(json.to_owned());
    }
    if let Some(file) = args.get("file").text() {
        words.push("--file".into());
        words.push(file.to_owned());
    }
    if let Some(origin) = args.get("origin").text() {
        words.push("--origin".into());
        words.push(origin.to_owned());
    }
    car_control::bridge::one_shot(&control, &words, stdin, io.out)
}

/// `mcpserver.main(argv)`: the server over this process's streams, and the start with Codex beside the handshake.
pub fn mcp(machine: &Machine, argv: &[String], io: &mut Io, stdin: &mut dyn Read) -> i32 {
    // `mcpserver.main` parses before it says UTF-8 and LF on its streams: argparse's own lines end CRLF.
    let args = match argparse::parse_args(PARSERS, MCP, argv) {
        Ok(args) => args,
        Err(exit) => return shown(exit, io),
    };
    let home = args
        .get("home")
        .text()
        .filter(|each| !each.is_empty())
        .map(str::to_owned)
        .or_else(|| installed_home(machine));
    let paths = match machine.paths(home.as_deref()) {
        Ok(paths) => paths,
        Err(message) => {
            let _ = io.err.write_all(format!("{message}\r\n").as_bytes());
            return 1;
        }
    };
    let control = machine.control(paths.clone());
    // v0.6.9's start with Codex: only for an installation (a home), at once, beside the handshake, and given
    // STARTER_GRACE_SECONDS once the server is done - never more (the reference's daemon thread).
    let finished = home.is_some().then(|| {
        let (told, heard) = std::sync::mpsc::channel::<()>();
        let starter = machine.control(paths);
        std::thread::spawn(move || {
            let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                starter.start_for_codex(car_control::codexstart::CONFIRM_SECONDS);
            }));
            let _ = told.send(());
        });
        heard
    });
    let code = car_control::mcp::Server::new(&control).serve(stdin, io.out);
    if let Some(heard) = finished {
        let _ = heard.recv_timeout(std::time::Duration::from_secs_f64(
            car_control::mcp::server::STARTER_GRACE_SECONDS,
        ));
    }
    code
}

/// The real machine this program runs on: car-control's SystemHost and this crate's SystemOutside, with the
/// installation found from where this program is.
pub fn system_machine() -> Machine {
    let exe = std::env::current_exe().unwrap_or_default();
    let project_root = crate::setup::project_root_of(&exe)
        .to_string_lossy()
        .into_owned();
    let host: Arc<dyn Host> = Arc::new(car_control::host::SystemHost::new(&project_root));
    Machine {
        host,
        outside: Arc::new(crate::seam::SystemOutside),
        project_root,
        env: Arc::new(|name: &str| std::env::var(name).ok()),
    }
}

/// `main()`: this process's arguments and streams; the exit code. Panics end as an uncaught exception does (D15).
pub fn main_with(extra: &[Role]) -> i32 {
    // A thread with the stack for a deeply nested document (car_machine::stack); a panic ends as it did on this one.
    let extra = extra.to_vec();
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        car_machine::stack::run_deep(move || main_on_this_thread(&extra))
    }))
    .unwrap_or(1)
}

fn main_on_this_thread(extra: &[Role]) -> i32 {
    let argv: Vec<String> = std::env::args_os()
        .skip(1)
        .map(|each| each.to_string_lossy().into_owned())
        .collect();
    let machine = system_machine();
    let stdout = std::io::stdout();
    let stderr = std::io::stderr();
    let mut out = stdout.lock();
    let mut err = stderr.lock();
    let mut io = Io {
        out: &mut out,
        err: &mut err,
        silent: false,
    };
    let stdin = std::io::stdin();
    let mut input = stdin.lock();
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        dispatch(&machine, extra, &argv, &mut io, &mut input)
    }))
    .unwrap_or(1)
}

/// The value a role's answer says nothing with (for tests of the table).
pub fn none() -> Value {
    Value::Null
}

/// Whether a path is this program's own installation's (for tests).
pub fn under(path: &Path, home: &Path) -> bool {
    path.starts_with(home)
}
