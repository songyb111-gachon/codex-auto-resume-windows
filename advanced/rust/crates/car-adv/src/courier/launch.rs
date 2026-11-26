//! `courier/launch.py` (seat S7.3b): starting the courier - from the watcher at P8 (`engine::push`, `engine::feed`,
//! `engine::remote`) and from the Dashboard's service for a test notice, a pairing or a feed read now
//! (`control::courier`). No network here.
//!
//! The alpha's courier is `<home>\app\bin\codex-auto-resume.exe courier --home <home> [extra]` (PLAN 1.7; the tag's
//! `pythonw.exe -c <BOOTSTRAP> <roots> --home <home>`), with no console (CREATE_NO_WINDOW) and suspended
//! (CREATE_SUSPENDED) until it is in this process's one job object, made KILL_ON_JOB_CLOSE (car-platform `job`): it
//! ends with the process that started it, however that ends. One that cannot be put in the job is ended before it runs.
//! [`start`] never waits; from the watcher it starts at most once in [`EVERY`] seconds for one home ([`start_due`]);
//! [`run`] waits, for the Dashboard's test notice, at most a given time.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Child;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use car_config::Paths;
use car_platform::spawn::{Spawn, Stream, SystemStarter};

/// Seconds between two starts from the watcher, for one home.
pub const EVERY: f64 = 60.0;
pub const CREATE_SUSPENDED: u32 = car_platform::job::CREATE_SUSPENDED;

static STARTED: Mutex<Option<HashMap<String, f64>>> = Mutex::new(None);
static CHILDREN: Mutex<Vec<Child>> = Mutex::new(Vec::new());

/// The program the courier runs as: this installation's console program.
pub fn program(paths: &Paths) -> PathBuf {
    Path::new(&paths.home)
        .join("app")
        .join("bin")
        .join("codex-auto-resume.exe")
}

/// `argv(paths, *extra)`: the courier's command line.
pub fn argv(paths: &Paths, extra: &[&str]) -> Vec<String> {
    let mut found = vec![
        program(paths).to_string_lossy().into_owned(),
        "courier".to_owned(),
        "--home".to_owned(),
        Path::new(&paths.home).to_string_lossy().into_owned(),
    ];
    found.extend(extra.iter().map(|each| (*each).to_owned()));
    found
}

/// How a child is started and adopted: the seams a test fills (`popen`, `adopt_it`).
pub struct Seams<'a> {
    pub start: &'a dyn Fn(&Spawn) -> std::io::Result<Child>,
    pub adopt: &'a dyn Fn(&mut Child) -> std::io::Result<()>,
}

fn system_start(spawn: &Spawn) -> std::io::Result<Child> {
    SystemStarter.start(spawn).map_err(|error| match error {
        car_platform::spawn::SpawnError::Os(error) => error,
        car_platform::spawn::SpawnError::Timeout => {
            std::io::Error::from(std::io::ErrorKind::TimedOut)
        }
    })
}

/// The product's seams: car-platform's starter and its job.
pub fn system() -> Seams<'static> {
    Seams {
        start: &system_start,
        adopt: &car_platform::job::adopt,
    }
}

/// The request the courier is started with: the command line, the environment less PYTHONPATH, the three streams on
/// NUL, CREATE_NO_WINDOW and CREATE_SUSPENDED.
pub fn request(paths: &Paths, extra: &[&str]) -> Spawn {
    let environment: Vec<(std::ffi::OsString, std::ffi::OsString)> = std::env::vars_os()
        .filter(|(name, _)| !name.to_string_lossy().eq_ignore_ascii_case("PYTHONPATH"))
        .collect();
    Spawn::new(argv(paths, extra))
        .with_env(environment)
        .with_flags(CREATE_SUSPENDED)
        .with_streams(Stream::Null, Stream::Null, Stream::Null)
}

/// The courier started, in the job and running - or None where it could not be (then it was ended before it ran).
fn spawn_child(paths: &Paths, extra: &[&str], seams: &Seams<'_>) -> Option<Child> {
    let mut child = (seams.start)(&request(paths, extra)).ok()?;
    if (seams.adopt)(&mut child).is_err() {
        let until = Instant::now() + Duration::from_secs(5);
        while Instant::now() < until && matches!(child.try_wait(), Ok(None)) {
            std::thread::sleep(Duration::from_millis(20));
        }
        return None;
    }
    let mut children = CHILDREN
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    children.retain_mut(|each| matches!(each.try_wait(), Ok(None)));
    Some(child)
}

/// `spawn(paths, *extra)`: the courier started and kept to be reaped; its process id, or None.
pub fn spawn_with(paths: &Paths, extra: &[&str], seams: &Seams<'_>) -> Option<u32> {
    let child = spawn_child(paths, extra, seams)?;
    let pid = child.id();
    CHILDREN
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .push(child);
    Some(pid)
}

/// `start(paths, *extra)`: start the courier and return at once; whether it started.
pub fn start(paths: &Paths, extra: &[&str]) -> bool {
    spawn_with(paths, extra, &system()).is_some()
}

/// `start_due(paths, now, *extra)`: from the watcher - unless one was started for this home in the last EVERY seconds.
pub fn start_due_with(paths: &Paths, now: Option<f64>, extra: &[&str], seams: &Seams<'_>) -> bool {
    let now = now.unwrap_or_else(crate::state::session::wall_clock);
    let home = Path::new(&paths.home).to_string_lossy().into_owned();
    {
        let mut started = STARTED
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let started = started.get_or_insert_with(HashMap::new);
        if let Some(last) = started.get(&home)
            && 0.0 <= now - last
            && now - last < EVERY
        {
            return false;
        }
        started.insert(home, now);
    }
    spawn_with(paths, extra, seams).is_some()
}

/// `start_due(paths, now, *extra)` with the product's seams.
pub fn start_due(paths: &Paths, now: Option<f64>, extra: &[&str]) -> bool {
    start_due_with(paths, now, extra, &system())
}

/// `run(paths, *extra, timeout=)`: start the courier and wait for it at most `timeout` seconds - its exit code, or None
/// where it did not start or has not finished (it is then left to finish, in the job).
pub fn run_with(paths: &Paths, extra: &[&str], timeout: i64, seams: &Seams<'_>) -> Option<i32> {
    let mut child = spawn_child(paths, extra, seams)?;
    let until = Instant::now() + Duration::from_secs(timeout.max(0) as u64);
    loop {
        if let Ok(Some(status)) = child.try_wait() {
            return status.code();
        }
        if Instant::now() >= until {
            CHILDREN
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(child);
            return None;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// `run(paths, *extra, timeout=)` with the product's seams.
pub fn run(paths: &Paths, extra: &[&str], timeout: i64) -> Option<i32> {
    run_with(paths, extra, timeout, &system())
}
