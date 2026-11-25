//! Review 7 (REVIEW-int5b.md, finding S1): `attach` waits for the state's own lock; the reference's does not.
//!
//! `state/session.py` `_open` reads the open connection WITHOUT the lock ("the claim attaches the file from core's
//! transaction, which must not wait for a transaction of this connection's on another thread"). car-adv's `attach`
//! takes the state's mutex every time. So while core's claim holds BEGIN IMMEDIATE on a connection the file is
//! attached to (which reserves advanced.sqlite too), a second thread's write on the state holds the mutex while it
//! waits SQLite's 10 s busy time for that very reservation, and the claim's `attach` waits behind it: the claim
//! stalls ~10 s and the other write fails. The reference (v0.6.26-beta.2, same steps, measured 2026-11-26):
//! `attach 2 True in 0.00 s`, the writer's `set_global_hourly` answers 2 once the claim commits.
//!
//! Fails today. Run: `cargo test --locked -p car-adv --test review7_attach` (in advanced/rust).

use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use car_adv::registry::{self, Registry};
use car_adv::state::AdvancedState;
use car_adv::state::seam::Tokens;
use car_machine::json::Value;

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

struct Counter(Mutex<u64>);

impl Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        let mut held = self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *held += 1;
        format!("{:0>width$x}", *held, width = count * 2)
    }
}

fn scratch() -> std::path::PathBuf {
    let home =
        std::env::temp_dir().join(format!("car-v0627-review7-attach-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(&home).expect("a scratch home");
    home
}

#[test]
fn attach_does_not_wait_for_another_threads_transaction() {
    let home = scratch();
    let text = home.to_string_lossy().into_owned();
    let no_env = |_: &str| None;
    let paths = car_config::Paths::new(
        Some(&text),
        &text,
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .expect("the home's paths");
    let registry: Arc<Registry> = Arc::new(registry::shipped(false).expect("the shipped registry"));
    let state = Arc::new(AdvancedState::new(
        paths,
        registry,
        Box::new(|| 1_800_000_000.0),
        Arc::new(Counter(Mutex::new(0))) as Arc<dyn Tokens>,
    ));
    let generation = car_adv::state::sql::get(&state.meta().expect("meta"), "generation").clone();
    state
        .set_global_hourly(
            &Value::from(5),
            &generation,
            &Value::from("dashboard"),
            &Value::Null,
        )
        .expect("the file made");
    let core = rusqlite::Connection::open(home.join("core.sqlite")).expect("core's connection");
    core.busy_timeout(Duration::from_secs(10))
        .expect("busy timeout");
    assert!(state.attach(&core).expect("attach"));
    core.execute_batch("BEGIN IMMEDIATE")
        .expect("core's claim begins");

    let writer = {
        let state = Arc::clone(&state);
        std::thread::spawn(move || {
            state
                .set_global_hourly(
                    &Value::from(4),
                    // The generation after the first move (meta 0, the first answers 1): the reference's steps
                    // pass 1 and answer 2; with 2 both sides answer StaleGeneration (fix7, measured 2026-11-26).
                    &Value::from(1),
                    &Value::from("dashboard"),
                    &Value::Null,
                )
                .map_err(|error| format!("{error:?}"))
        })
    };
    std::thread::sleep(Duration::from_millis(300));
    let started = Instant::now();
    let attached = state.attach(&core).expect("attach in the claim");
    let waited = started.elapsed();
    core.execute_batch("COMMIT").expect("core's claim commits");
    let written = writer.join().expect("the writer thread");
    let _ = std::fs::remove_dir_all(&home);

    assert!(attached);
    assert!(
        waited < Duration::from_secs(2),
        "attach waited {waited:?} for another thread's transaction (the reference: 0.00 s)"
    );
    assert_eq!(
        written,
        Ok(Value::from(2)),
        "the other thread's write (the reference: 2)"
    );
}
