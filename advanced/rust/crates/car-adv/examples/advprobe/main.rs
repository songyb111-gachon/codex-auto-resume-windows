//! advprobe: the Rust side of S7.1b's differential tests (tests/rustdiff/diffs_advpolicy_*.py). Dev only, never shipped.
//!
//! One request on stdin: `{"cases": [[op, arg, ...], ...]}`; one answer on stdout: `{"results": [{"ok": v} | {"error": "Class"}]}`,
//! written by car-machine's writer (the bytes `json.dumps(..., ensure_ascii=False, allow_nan=False)` writes). Nothing here reads
//! a home, the registry of this machine, or the network: every state, view and clock a case needs comes in the case.

mod defs;
mod ops_arming;
mod ops_pure;
mod ops_registry;
mod ops_statement;
mod ops_words;
mod util;

use std::io::{Read, Write};

use car_adv::jsonx::object;
use car_machine::json::{Options, Value, from_str, to_string};

use util::Failure;

fn dispatch(op: &str, args: &[Value]) -> Result<Value, Failure> {
    let family = op.split('.').next().unwrap_or("");
    match family {
        "vocab" | "standards" | "measured" | "policy" => ops_words::run(op, args),
        "registry" => ops_registry::run(op, args),
        "statement" => ops_statement::run(op, args),
        "arming" if op.starts_with("arming.pure.") => ops_pure::run(op, args),
        "arming" => ops_arming::run(op, args),
        _ => Err(Failure::new("UnknownOp")),
    }
}

fn main() {
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
            Ok(Err(failure)) => object([("error", failure.class.into())]),
            Err(payload) => object([(
                "error",
                car_adv::state::port::raised(&*payload)
                    .map_or("Panic", |raised| raised.class)
                    .into(),
            )]),
        });
    }
    let answer = object([("results", Value::Array(results))]);
    let text = to_string(&answer, &Options::new()).expect("the answer is JSON");
    let mut out = std::io::stdout().lock();
    out.write_all(text.as_bytes()).expect("stdout");
}
