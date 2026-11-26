//! The S7.2e2 probe (`tests/rustdiff/advtime.py`): one request of cases, each a capability scenario or a pure call of
//! `engine::{supervise, powertasks, wake, analytics, updatecheck, fleet, anchor}`, answered as the reference's script
//! answers it. Every home is the scratch folder the case names; every stand-in is scripted and logs its calls; nothing
//! real is asked of Windows (no stop event, no wake timer, no PowerShell, no Codex) and nothing of a network.

mod anchor_ops;
mod common;
mod fleet_ops;
mod power_ops;
mod supervise_ops;
mod update_ops;
mod wake_ops;

use car_machine::json::{Map, Value};

use common::{get, object, text};

fn main() {
    // Values nest as deep as Python's json.loads takes them: the work runs on a stack of its own.
    let worker = std::thread::Builder::new()
        .stack_size(256 * 1024 * 1024)
        .spawn(run)
        .expect("the harness thread");
    if worker.join().is_err() {
        std::process::exit(101);
    }
}

fn run() {
    let path = std::env::args().nth(1).expect("a request file");
    let request = std::fs::read_to_string(path).expect("the request");
    let Value::Object(request) = car_machine::compat::loads(&request).expect("a JSON request")
    else {
        panic!("the request is an object");
    };
    let cases = match get(&request, "cases") {
        Value::Array(cases) => cases.clone(),
        _ => Vec::new(),
    };
    let mut results = Vec::new();
    for case in cases {
        let Value::Object(case) = case else {
            results.push(object(vec![("error", Value::Str("TypeError".into()))]));
            continue;
        };
        let found = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| answer(&case)));
        results.push(match found {
            Ok(Ok(value)) => object(vec![("ok", value)]),
            Ok(Err(class)) => object(vec![("error", Value::Str(class.as_str().into()))]),
            Err(_) => object(vec![("error", Value::Str("panic".into()))]),
        });
    }
    let out = object(vec![("results", Value::Array(results))]);
    let text =
        car_machine::json::to_string(&out, &car_machine::json::Options::new().ensure_ascii(false))
            .expect("the answer");
    print!("{text}");
}

fn answer(case: &Map) -> Result<Value, String> {
    let op = text(get(case, "op"));
    if let Some(found) = supervise_ops::answer(&op, case) {
        return found;
    }
    if let Some(found) = power_ops::answer(&op, case) {
        return found;
    }
    if let Some(found) = wake_ops::answer(&op, case) {
        return found;
    }
    if let Some(found) = update_ops::answer(&op, case) {
        return found;
    }
    if let Some(found) = fleet_ops::answer(&op, case) {
        return found;
    }
    if let Some(found) = anchor_ops::answer(&op, case) {
        return found;
    }
    Err(format!("unknown op {op}"))
}
