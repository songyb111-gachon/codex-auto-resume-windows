//! advcourier: the Rust side of S7.3b's differential tests of the courier (tests/rustdiff/diffs_advcourier_*.py).
//! Dev only, never shipped, built on demand (`cargo build --release -p car-adv --example advcourier` in advanced/rust).
//!
//! One request on stdin: `{"cases": [[op, arg, ...], ...]}`; one answer on stdout: `{"results": [{"ok": v} | {"error":
//! "Class", "code": word?}]}`. A case that needs a home names the reference's scratch home; this side makes its own beside
//! it (`<home>-rust`), so the harness compares the two state files. Every opener is a scripted fake, every secret a
//! memory backend, every server bound to 127.0.0.1 on a port of its own: nothing reaches a network, the registry or a
//! real home. No window is ever shown.

mod ops;
mod util;

use std::io::{Read, Write};

use car_adv::jsonx::object;
use car_machine::json::{Options, Value, from_str, to_string};

fn main() {
    let worker = std::thread::Builder::new()
        .stack_size(64 * 1024 * 1024)
        .spawn(run)
        .expect("the harness thread");
    if worker.join().is_err() {
        std::process::exit(101);
    }
}

fn run() {
    let mut raw = String::new();
    std::io::stdin().read_to_string(&mut raw).expect("stdin");
    let Ok(Value::Object(request)) = from_str(&raw) else {
        eprintln!("the request is not a JSON object");
        std::process::exit(2);
    };
    let Some(Value::Array(cases)) = request.get("cases") else {
        eprintln!("no cases");
        std::process::exit(2);
    };
    let mut results = Vec::with_capacity(cases.len());
    for case in cases {
        let Value::Array(parts) = case else {
            results.push(object([("error", "BadCase".into())]));
            continue;
        };
        let (Some(Value::Str(op)), args) = (parts.first(), &parts[parts.len().min(1)..]) else {
            results.push(object([("error", "BadCase".into())]));
            continue;
        };
        let op = op.as_str().unwrap_or("");
        let done = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| ops::run(op, args)));
        results.push(match done {
            Ok(Ok(value)) => object([("ok", value)]),
            Ok(Err(failure)) => match failure.code {
                Some(code) => object([("error", failure.class.into()), ("code", code.into())]),
                None => object([("error", failure.class.into())]),
            },
            Err(_) => object([("error", "Panic".into())]),
        });
    }
    let answer = object([("results", Value::Array(results))]);
    let text = to_string(&answer, &Options::new()).expect("the answer is JSON");
    std::io::stdout()
        .lock()
        .write_all(text.as_bytes())
        .expect("stdout");
}
