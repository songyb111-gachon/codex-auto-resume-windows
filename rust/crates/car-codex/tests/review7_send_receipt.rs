//! Review 7 (REVIEW-int5b.md, finding S2): a send whose `codex queue` exits while a process it started keeps its
//! output pipe open.
//!
//! The reference (`codex/transport.py` `send`) reads the receipt with `process.communicate(timeout=45)`: the 45 s
//! cover the output's end as well as the exit, so where a grandchild inherited the pipe (Codex is a Rust program, and
//! std's CreateProcess passes every inheritable handle on) it times out, kills, waits 5 s more and answers
//! `{"outcome": "unknown", "error_code": "queue_timeout"}` - whatever the receipt said (its `finally`'s
//! `stdout.close()` then waits for the pipe too, so it returns when the grandchild ends). car-codex's
//! `Backend::send` waits only for the exit, then joins its reader thread with no time limit and reads the receipt:
//! `{"outcome": "accepted", "queue_id": ...}`. Both wait as long as the grandchild lives (forever for a daemon).
//! Measured on the reference with this very binary as the engine (2026-11-26):
//! `{'outcome': 'unknown', 'error_code': 'queue_timeout'} in 77.9 s`; car-codex: accepted in 76.4 s.
//!
//! This file is its own harness (`harness = false`): run with no arguments it is the test; started as `codex.exe`
//! (a copy in a scratch bin folder) it answers `--version`, `queue --help` and a send, the send starting one copy of
//! itself (`--review7-linger`, CREATE_NO_WINDOW) that sleeps LINGER seconds and holds the pipe. Fails today.
//! Run: `cargo test --locked -p car-codex --test review7_send_receipt` (in rust/; about 75 s).

use std::os::windows::process::CommandExt;
use std::sync::Arc;
use std::time::{Duration, Instant};

use car_codex::errors::{Error, Result};
use car_codex::system::System;
use car_codex::transport::Backend;
use car_machine::json::Value;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const THREAD: &str = "11111111-2222-4333-8444-555555555555";
const QUEUED: &str = "66666666-7777-4888-8999-aaaaaaaaaaaa";
const LINGER: u64 = 75;

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

/// The engine's part: what `codex.exe` answers.
fn engine(args: &[String]) {
    if args.iter().any(|each| each == "--review7-linger") {
        std::thread::sleep(Duration::from_secs(LINGER));
        return;
    }
    if args.iter().any(|each| each == "--version") {
        println!("codex-cli 0.0.0-review7");
        return;
    }
    if args.iter().any(|each| each == "--help") {
        println!("Usage: codex queue --thread <THREAD> --message <MESSAGE>");
        return;
    }
    if let Some(at) = args.iter().position(|each| each == "--thread") {
        let thread = args.get(at + 1).cloned().unwrap_or_default();
        if let Ok(me) = std::env::current_exe() {
            let _ = std::process::Command::new(me)
                .arg("--review7-linger")
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .creation_flags(CREATE_NO_WINDOW)
                .spawn();
        }
        println!("Queued message {QUEUED} for thread {thread}.");
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|each| {
        ["--version", "--help", "--thread", "--review7-linger"].contains(&each.as_str())
    }) {
        engine(&args);
        return;
    }
    let scratch =
        std::env::temp_dir().join(format!("car-v0627-review7-send-{}", std::process::id()));
    let bin = scratch.join("bin");
    let home = scratch.join("home");
    std::fs::create_dir_all(&bin).expect("a scratch bin");
    std::fs::create_dir_all(&home).expect("a scratch home");
    let exe = bin.join("codex.exe");
    std::fs::copy(std::env::current_exe().expect("this test"), &exe).expect("the engine copy");
    let mut backend = Backend::new(
        Arc::new(Stand),
        &home.to_string_lossy(),
        &exe.to_string_lossy(),
        false,
        "0.6.27-alpha",
    );
    let started = Instant::now();
    let answer = backend.send(THREAD, &Value::from("keep going"), None);
    let took = started.elapsed();
    println!("send answered {answer:?} in {took:?}");
    let outcome = answer.get("outcome").cloned().unwrap_or(Value::Null);
    let code = answer.get("error_code").cloned().unwrap_or(Value::Null);
    let ok = outcome == Value::from("unknown") && code == Value::from("queue_timeout");
    if !ok {
        eprintln!(
            "FAILED: the reference answers {{'outcome': 'unknown', 'error_code': 'queue_timeout'}} (communicate's \
             45 s ran out on the pipe a grandchild held); car-codex answered {answer:?} after {took:?}"
        );
        std::process::exit(1);
    }
    println!("ok");
}
