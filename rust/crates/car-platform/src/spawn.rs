//! The one place the Rust core starts a process (PLAN 6.7).
//!
//! Every console program our code starts gets `CREATE_NO_WINDOW` (brief rule 12), so no window of any kind
//! can show: a child started from a GUI-subsystem host or a watcher with no console must not open one. A
//! `Spawn` is the whole request - argument list, environment, standard streams, creation flags - and
//! `SystemStarter` is the only code with a `Command::new`; `tests` (and `tests/rustdiff/platform_diffs.py`) read
//! the source for any other. The flags are always ORed with `CREATE_NO_WINDOW`: a caller can add one
//! (`CREATE_BREAKAWAY_FROM_JOB`, `DETACHED_PROCESS`) but never take it away.
//!
//! The command line a child sees is the argument tail `list2cmdline` writes (`crate::cmdline`), as Python's
//! `subprocess` writes it; the program itself is quoted by std (always), which no program of ours parses.

use std::ffi::OsString;
use std::os::windows::process::CommandExt;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{Duration, Instant};

use crate::cmdline::list2cmdline;

/// `CREATE_NO_WINDOW` (`subprocess.CREATE_NO_WINDOW`, `win/kernel.NO_WINDOW`).
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;
/// `CREATE_BREAKAWAY_FROM_JOB` (`win/kernel.CREATE_BREAKAWAY_FROM_JOB`).
pub const CREATE_BREAKAWAY_FROM_JOB: u32 = 0x0100_0000;
pub const DETACHED_PROCESS: u32 = 0x0000_0008;
pub const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;

/// Where a child's standard stream goes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stream {
    /// NUL (`subprocess.DEVNULL`).
    Null,
    /// This process's own.
    Inherit,
    /// A pipe the caller reads or writes.
    Piped,
}

impl Stream {
    fn stdio(self) -> Stdio {
        match self {
            Stream::Null => Stdio::null(),
            Stream::Inherit => Stdio::inherit(),
            Stream::Piped => Stdio::piped(),
        }
    }
}

/// What can go wrong starting a program and waiting for it.
#[derive(Debug)]
pub enum SpawnError {
    /// Windows refused (the program is not there, access denied, ...).
    Os(std::io::Error),
    /// The program ran longer than it was given and was killed (`subprocess.TimeoutExpired`).
    Timeout,
}

impl std::fmt::Display for SpawnError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SpawnError::Os(error) => write!(f, "the program could not be started: {error}"),
            SpawnError::Timeout => f.write_str("the program ran out of time"),
        }
    }
}

impl std::error::Error for SpawnError {}

/// A process to start: the whole of the request, and nothing started yet.
#[derive(Debug, Clone)]
pub struct Spawn {
    argv: Vec<String>,
    env: Option<Vec<(OsString, OsString)>>,
    extra_flags: u32,
    pub stdin: Stream,
    pub stdout: Stream,
    pub stderr: Stream,
    cwd: Option<std::path::PathBuf>,
}

impl Spawn {
    /// A program and its arguments (`argv[0]` is the program), standard streams to NUL, this process's environment.
    pub fn new<S: Into<String>>(argv: impl IntoIterator<Item = S>) -> Self {
        Spawn {
            argv: argv.into_iter().map(Into::into).collect(),
            env: None,
            extra_flags: 0,
            stdin: Stream::Null,
            stdout: Stream::Null,
            stderr: Stream::Null,
            cwd: None,
        }
    }

    /// Replace the child's whole environment (`env=` of `subprocess.run`).
    pub fn with_env(mut self, env: Vec<(OsString, OsString)>) -> Self {
        self.env = Some(env);
        self
    }

    /// Add a creation flag. `CREATE_NO_WINDOW` stays whatever is added.
    pub fn with_flags(mut self, flags: u32) -> Self {
        self.extra_flags |= flags;
        self
    }

    pub fn with_streams(mut self, stdin: Stream, stdout: Stream, stderr: Stream) -> Self {
        self.stdin = stdin;
        self.stdout = stdout;
        self.stderr = stderr;
        self
    }

    pub fn with_cwd(mut self, cwd: impl Into<std::path::PathBuf>) -> Self {
        self.cwd = Some(cwd.into());
        self
    }

    pub fn argv(&self) -> &[String] {
        &self.argv
    }

    pub fn env(&self) -> Option<&[(OsString, OsString)]> {
        self.env.as_deref()
    }

    /// The creation flags the process is started with: always including `CREATE_NO_WINDOW`.
    pub fn flags(&self) -> u32 {
        self.extra_flags | CREATE_NO_WINDOW
    }

    /// The command line as `subprocess.list2cmdline(argv)` writes it.
    pub fn command_line(&self) -> String {
        list2cmdline(&self.argv)
    }
}

/// The flags of the process most recently started by `SystemStarter`, for the test that reads them (0 before any).
static LAST_FLAGS: AtomicU32 = AtomicU32::new(0);

/// The creation flags `SystemStarter` applied to the last process it started.
pub fn last_started_flags() -> u32 {
    LAST_FLAGS.load(Ordering::SeqCst)
}

/// Something that starts a request and waits for it: the system, or a test's stand-in.
pub trait Starter {
    /// Start `spawn`, wait up to `timeout` for it and answer its exit code (`subprocess.run(...).returncode`).
    fn run(&self, spawn: &Spawn, timeout: Duration) -> Result<i32, SpawnError>;
}

/// Windows itself.
pub struct SystemStarter;

impl SystemStarter {
    /// Start without waiting: the child is the caller's (a watcher left running, a Codex server).
    pub fn start(&self, spawn: &Spawn) -> Result<Child, SpawnError> {
        self.start_guarded(spawn, false)
    }

    /// [`SystemStarter::start`] with the caller's own `cfg!(test)` given as `test`: where the real-engine guard is on
    /// (`test`, this crate's tests or `CAR_NO_REAL_ENGINE`), this PC's Codex engine or app is refused as a program
    /// that is not there (`realengine`).
    pub fn start_guarded(&self, spawn: &Spawn, test: bool) -> Result<Child, SpawnError> {
        let (program, rest) = spawn.argv.split_first().ok_or_else(|| {
            SpawnError::Os(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "no program",
            ))
        })?;
        // The real-engine guard: this PC's Codex is never started from a test (`realengine`).
        let on = test || cfg!(test) || crate::realengine::switched();
        if crate::realengine::start_refused(on, &spawn.argv) {
            return Err(SpawnError::Os(std::io::Error::from_raw_os_error(2)));
        }
        // The one `Command::new` of the core (PLAN 6.7).
        let mut command = Command::new(program);
        if !rest.is_empty() {
            command.raw_arg(list2cmdline(rest));
        }
        if let Some(env) = &spawn.env {
            command.env_clear();
            command.envs(env.iter().map(|(name, value)| (name, value)));
        }
        if let Some(cwd) = &spawn.cwd {
            command.current_dir(cwd);
        }
        command
            .stdin(spawn.stdin.stdio())
            .stdout(spawn.stdout.stdio())
            .stderr(spawn.stderr.stdio());
        let flags = spawn.flags();
        command.creation_flags(flags);
        LAST_FLAGS.store(flags, Ordering::SeqCst);
        command.spawn().map_err(SpawnError::Os)
    }
}

impl Starter for SystemStarter {
    fn run(&self, spawn: &Spawn, timeout: Duration) -> Result<i32, SpawnError> {
        let mut child = self.start(spawn)?;
        let started = Instant::now();
        loop {
            match child.try_wait() {
                Ok(Some(status)) => return Ok(status.code().unwrap_or(-1)),
                Ok(None) => {}
                Err(error) => return Err(SpawnError::Os(error)),
            }
            if started.elapsed() >= timeout {
                let _ = child.kill();
                let _ = child.wait();
                return Err(SpawnError::Timeout);
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}
