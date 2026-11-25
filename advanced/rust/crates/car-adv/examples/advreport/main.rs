//! advreport: the Rust side of S7.3c's differential tests of the compatibility report (tests/rustdiff/diffs_advreport_*.py).
//! Dev only, never shipped, built on demand (`cargo build --release -p car-adv --example advreport` in advanced/rust).
//!
//! One request on stdin: `{"cases": [[op, arg, ...], ...]}`; one answer on stdout: `{"results": [{"ok": v} | {"error":
//! "Class", "code": word?}]}`, written by car-machine's writer. Every home a case names is a scratch folder the reference
//! made; nothing here reads a real one, the registry, a process list or the network. No window is ever shown.

mod ops_document;
mod ops_github;
mod ops_records;
mod util;

use std::io::{Read, Write};

use car_adv::jsonx::object;
use car_machine::json::{Options, Value, from_str, to_string};

use util::Failure;

fn dispatch(op: &str, args: &[Value]) -> Result<Value, Failure> {
    let family = op.split('.').next().unwrap_or("");
    match family {
        "records" | "evidence" | "reading" => ops_records::run(op, args),
        "document" => ops_document::run(op, args),
        "github" => ops_github::run(op, args),
        _ => Err(Failure::new("UnknownOp")),
    }
}

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
        // D15: a panic is caught at the boundary; a case that panics is an error of its own class, never a dead probe.
        let done = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| dispatch(op, args)));
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
    let mut out = std::io::stdout().lock();
    out.write_all(text.as_bytes()).expect("stdout");
}
