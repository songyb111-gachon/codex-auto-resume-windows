//! Fix 7 (REVIEW-int5b.md, S2's other reads): `codex --version` and `codex queue --help` whose engine exits while a
//! process it started keeps the output pipe open.
//!
//! The reference (`codex/transport.py` `engine_checks`, `_queue_interface_ok`) runs each with
//! `subprocess.run(timeout=10)` / `timeout=20`: the time covers the output's end as well as the exit, so where a
//! grandchild holds the pipe past it the run is `TimeoutExpired` (after the kill, Windows' `run` reads to the pipe's
//! end, so it returns when the grandchild ends) and the check is UNAVAILABLE. car-codex read PASS once the pipe
//! closed. And the App Server helper's close (note 3): the reference's `__exit__` joins the reader 1 s and then
//! `process.stdout.close()`, which waits for the reader's read in progress - as long as the grandchild holds the
//! pipe; car-codex returned after 1 s and left the reader thread running.
//!
//! Its own harness (`harness = false`), as review7_send_receipt is: run with no arguments it is the test; started as
//! `codex.exe` (a copy in a scratch bin folder) it answers `--version`, `queue --help` and `app-server --stdio`'s initialize, starting one copy of itself
//! (`--fix7-linger N`, CREATE_NO_WINDOW) that sleeps N seconds holding the pipe, where the scratch folder's name says
//! so. Run: `cargo test --locked -p car-codex --test fix7_engine_checks` (in rust/; about 45 s).

use std::os::windows::process::CommandExt;
use std::sync::Arc;
use std::time::{Duration, Instant};

use car_codex::errors::{Error, Result};
use car_codex::system::System;
use car_codex::transport::Backend;
use car_machine::json::Value;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
/// Past `codex --version`'s 10 s, and past `codex queue --help`'s 20 s.
const VERSION_LINGER: u64 = 12;
const HELP_LINGER: u64 = 22;
/// Past the App Server helper's close (4 s for the exit, then 1 s for the reader).
const APPSERVER_LINGER: u64 = 8;

struct Stand;

impl System for Stand {
    fn env(&self, _name: &str) -> Option<String> {
        None
    }
    fn processes_named(&self, _names: &[&str], _families: &[&str]) -> Result<Vec<Value>> {
        Ok(Vec::new())
    }
    fn resource_users(&self, _paths: &[String]) -> Result<Vec<Value>> {
        Ok(Vec::new())
    }
    fn process_identity(&self, _pid: &Value) -> Result<Value> {
        Err(Error::Os)
    }
    fn signer(&self, _path: &str) -> std::result::Result<String, Option<&'static str>> {
        Ok("OpenAI OpCo, LLC".to_owned())
    }
    fn own_pid(&self) -> i64 {
        i64::from(std::process::id())
    }
    fn monotonic(&self) -> f64 {
        static START: std::sync::OnceLock<Instant> = std::sync::OnceLock::new();
        START.get_or_init(Instant::now).elapsed().as_secs_f64()
    }
    fn resolve(&self, text: &str) -> Option<String> {
        Some(text.to_owned())
    }
    fn restart_manager_available(&self) -> bool {
        false
    }

    fn package_roots(&self, _family: &str) -> Result<Vec<String>> {
        Ok(Vec::new())
    }
}

/// Which of the two answers lingers: the scratch folder's name says (`linger-version` or `linger-help`).
fn lingering(which: &str) -> bool {
    std::env::current_exe()
        .ok()
        .and_then(|exe| {
            exe.parent()?
                .parent()?
                .file_name()
                .map(|name| name.to_string_lossy().into_owned())
        })
        .is_some_and(|name| name.ends_with(which))
}

fn linger(seconds: u64) {
    if let Ok(me) = std::env::current_exe() {
        let _ = std::process::Command::new(me)
            .args(["--fix7-linger", &seconds.to_string()])
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn();
    }
}

/// The engine's part: what `codex.exe` answers.
fn engine(args: &[String]) {
    if let Some(at) = args.iter().position(|each| each == "--fix7-linger") {
        let seconds = args
            .get(at + 1)
            .and_then(|text| text.parse().ok())
            .unwrap_or(0);
        std::thread::sleep(Duration::from_secs(seconds));
        return;
    }
    if args.iter().any(|each| each == "app-server") {
        if lingering("linger-appserver") {
            linger(APPSERVER_LINGER);
        }
        let home = std::env::current_dir().unwrap_or_default();
        let home = home.to_string_lossy().replace('\\', "\\\\");
        for line in std::io::stdin().lines() {
            let Ok(line) = line else { break };
            if line.contains("\"initialize\"") {
                println!(
                    "{{\"id\": 1, \"result\": {{\"codexHome\": \"{home}\", \"platformOs\": \"windows\"}}}}"
                );
            }
        }
        return;
    }
    if args.iter().any(|each| each == "--version") {
        if lingering("linger-version") {
            linger(VERSION_LINGER);
        }
        println!("codex-cli 0.0.0-fix7");
        return;
    }
    if args.iter().any(|each| each == "--help") {
        if lingering("linger-help") {
            linger(HELP_LINGER);
        }
        println!("Usage: codex queue --thread <THREAD> --message <MESSAGE>");
    }
}

/// The engine copied into `<scratch>-<which>/bin`, and a Backend on it.
fn backend(which: &str) -> (std::path::PathBuf, Backend) {
    let scratch = std::env::temp_dir().join(format!(
        "car-v0627-fix7-checks-{}-{which}",
        std::process::id()
    ));
    let bin = scratch.join("bin");
    let home = scratch.join("home");
    std::fs::create_dir_all(&bin).expect("a scratch bin");
    std::fs::create_dir_all(&home).expect("a scratch home");
    let exe = bin.join("codex.exe");
    std::fs::copy(std::env::current_exe().expect("this test"), &exe).expect("the engine copy");
    let backend = Backend::new(
        Arc::new(Stand),
        &home.to_string_lossy(),
        &exe.to_string_lossy(),
        false,
        "0.6.27-alpha",
    );
    (scratch, backend)
}

/// The App Server helper opened and closed: whether it opened, and how long open and close took together.
fn helper(which: &str) -> (bool, Duration) {
    let (scratch, mut backend) = backend(which);
    let started = Instant::now();
    let opened = match car_codex::appserver::Protocol::open(&mut backend) {
        Ok(mut client) => {
            client.close();
            true
        }
        Err(_) => false,
    };
    let took = started.elapsed();
    let _ = std::fs::remove_dir_all(&scratch);
    (opened, took)
}

/// `engine_checks()` with the engine copied into `<scratch>-<which>/bin`: the checks and how long they took.
fn checks(which: &str) -> (Value, Value, Duration) {
    let (scratch, mut backend) = backend(which);
    let started = Instant::now();
    let found = backend.engine_checks();
    let took = started.elapsed();
    let _ = std::fs::remove_dir_all(&scratch);
    let get = |key: &str| found.get(key).cloned().unwrap_or(Value::Null);
    (get("version_runs"), get("queue_flags"), took)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args
        .iter()
        .any(|each| ["--version", "--help", "--fix7-linger", "app-server"].contains(&each.as_str()))
    {
        engine(&args);
        return;
    }
    let mut failed = Vec::new();
    let (runs, flags, took) = checks("linger-none");
    println!("no grandchild: version_runs {runs:?}, queue_flags {flags:?} in {took:?}");
    if runs != Value::from("PASS") || flags != Value::from("PASS") {
        failed.push("with no grandchild both checks PASS");
    }
    let (runs, flags, took) = checks("linger-version");
    println!("--version's grandchild: version_runs {runs:?}, queue_flags {flags:?} in {took:?}");
    if runs != Value::from("UNAVAILABLE") || flags != Value::from("UNAVAILABLE") {
        failed.push("--version past its 10 s is UNAVAILABLE, as subprocess.run(timeout=10) is");
    }
    if took < Duration::from_secs(VERSION_LINGER - 1) {
        failed
            .push("the timed-out run reads the pipe to its end, as Windows' run does after kill()");
    }
    let (runs, flags, _) = checks("linger-help");
    println!("--help's grandchild: version_runs {runs:?}, queue_flags {flags:?}");
    if runs != Value::from("PASS") || flags != Value::from("UNAVAILABLE") {
        failed.push("queue --help past its 20 s is UNAVAILABLE, as subprocess.run(timeout=20) is");
    }
    let (opened, took) = helper("linger-appserver");
    println!("the helper's grandchild: opened {opened}, open and close in {took:?}");
    if !opened {
        failed.push("the App Server helper opens on the stand-in");
    }
    if took < Duration::from_secs(APPSERVER_LINGER - 1) {
        failed.push(
            "the helper's close waits for the read in progress, as the reference's stdout.close() does",
        );
    }
    if !failed.is_empty() {
        for each in &failed {
            eprintln!("FAILED: {each}");
        }
        std::process::exit(1);
    }
    println!("ok");
}
