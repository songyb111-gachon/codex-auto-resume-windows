//! The panic test (P6-DESIGN 1.3, D15) over a core built with the feature `panic-test`: `CAR_CORE_PANIC` makes the
//! first tick and the first `car_bridge` panic on purpose. The tick's panic costs that tick - it is recorded as an
//! exception is, and the next tick runs; the export answers `panic`, the panic is recorded in the watcher's log and
//! `errors.log`, and the next call is answered. (The worker thread's case is car-watcher's `toasts` test under the
//! same feature; the release DLL's lack of the wire is `abi_exports`' `the_release_dll_has_no_panic_wire`.)
//!
//! `cargo test -p car-host --features panic-test --test panic_feature`

#![cfg(feature = "panic-test")]

mod common;

use std::time::{Duration, Instant};

use common::*;

/// The joined engine's discovery, refusing the named codex.exe that is not there (tests/common): every tick after the
/// panicked one says it.
const NOT_BUILT: &str = "initialising Codex adapter failed (ConfigError)";

#[test]
fn a_panic_costs_one_tick_and_one_call() {
    let scratch = scratch("panic", None);
    let home = scratch.home.clone();
    // SAFETY: this binary's one test sets it before the watcher starts.
    unsafe { std::env::set_var("CAR_CORE_PANIC", "tick,car_bridge") };
    assert_eq!(start(&start_request(&home)), r#"{"abi": 1, "ok": true}"#);
    // The first tick panics; the toggle wakes the loop for the next one (set_enabled signals the wake event).
    let until = Instant::now() + Duration::from_secs(120);
    let mut woken = Instant::now();
    loop {
        pump(|_| false, 1);
        let log = log(&home);
        let panicked = log.lines().position(|line| {
            line.contains("initialising Codex adapter failed (")
                && !line.contains(NOT_BUILT)
        });
        if let Some(at) = panicked
            && log
                .lines()
                .skip(at + 1)
                .any(|line| line.contains(NOT_BUILT))
        {
            break;
        }
        assert!(
            Instant::now() < until,
            "no tick after the panicked one:\n{log}"
        );
        if woken.elapsed() > Duration::from_secs(3) {
            post(r#"{"action": "toggle", "paused": true}"#);
            woken = Instant::now();
        }
    }
    // The export: answered `panic`, recorded, and the next call answered as ever.
    assert_eq!(
        bridge(r#"{"id": 1, "command": "get_status"}"#),
        r#"{"ok": false, "error": "panic"}"#
    );
    let reply = bridge(r#"{"id": 2, "command": "get_status"}"#);
    assert!(reply.starts_with(r#"{"id": 2, "reply": "#), "{reply}");
    assert!(car_core::abi::panics() >= 1);
    let log = log(&home);
    assert!(
        log.contains("car_bridge failed (panic); no submission was made"),
        "{log}"
    );
    let errors = std::fs::read_to_string(home.join("logs").join("errors.log")).expect("errors.log");
    assert!(
        errors.contains("the panic test tripped in car_bridge"),
        "{errors}"
    );
    assert!(
        errors.contains("the panic test tripped in tick"),
        "{errors}"
    );
    assert_eq!(car_core::car_stop(), 0);
    let end = pump(|seen| seen.iter().any(|event| kind(event) == "ended"), 60);
    assert_eq!(end.last().map(kind).as_deref(), Some("ended"));
}
