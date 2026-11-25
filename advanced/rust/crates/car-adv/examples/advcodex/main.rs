//! advcodex: the Rust side of S7.2c's differential tests (`tests/rustdiff/diffs_advcodex_*.py`). Dev only, never shipped.
//!
//! One request on stdin: `{"world": {...}, "product_version": "0.6.26", "cases": [[op, arg, ...], ...]}`; one answer on
//! stdout: `{"results": [{"ok": v} | {"error": "Class"[, "code": c]}]}`, written by car-machine's writer. Every home, Codex
//! home and engine a case names is a scratch folder the diff made; the only processes started are the diff's own fake
//! engine (`advfake`), through car-platform's starter with `CREATE_NO_WINDOW`; signers and process lists come from the
//! world (`world.rs`), never from this machine.

mod ops_check;
mod ops_compat;
mod ops_inuse;
mod ops_protocol;
mod ops_read;
mod ops_win;
mod world;

use std::io::{Read, Write};
use std::sync::Arc;

use car_adv::jsonx::object;
use car_machine::json::{Options, Value, to_string};

/// An op's refusal: the class name of the reference's exception, and the code an AdapterError carries.
#[derive(Debug)]
pub struct Failure {
    pub class: String,
    pub code: Option<String>,
}

impl Failure {
    pub fn new(class: &str) -> Failure {
        Failure {
            class: class.to_owned(),
            code: None,
        }
    }
    pub fn coded(class: &str, code: &str) -> Failure {
        Failure {
            class: class.to_owned(),
            code: Some(code.to_owned()),
        }
    }
}

pub type Out = Result<Value, Failure>;

pub fn bad() -> Failure {
    Failure::new("BadArgument")
}

pub fn arg(args: &[Value], at: usize) -> &Value {
    static NULL: Value = Value::Null;
    args.get(at).unwrap_or(&NULL)
}

pub fn text(value: &Value) -> Result<String, Failure> {
    match value {
        Value::Str(each) => each.as_str().map(str::to_owned).ok_or_else(bad),
        _ => Err(bad()),
    }
}

pub fn maybe_text(value: &Value) -> Result<Option<String>, Failure> {
    match value {
        Value::Null => Ok(None),
        other => text(other).map(Some),
    }
}

pub fn float(value: &Value) -> Result<f64, Failure> {
    match value {
        Value::Float(each) => Ok(*each),
        Value::Int(each) => each.as_i64().map(|n| n as f64).ok_or_else(bad),
        _ => Err(bad()),
    }
}

/// What every op family is handed.
pub struct Context {
    pub world: Arc<world::World>,
    pub product_version: String,
}

fn dispatch(context: &Context, op: &str, args: &[Value]) -> Out {
    match op.split('.').next().unwrap_or("") {
        "cd" => ops_compat::run(context, op, args),
        "ac" => ops_check::run(context, op, args),
        "iu" => ops_inuse::run(context, op, args),
        "pr" => ops_protocol::run(context, op, args),
        "rd" => ops_read::run(context, op, args),
        "wn" => ops_win::run(context, op, args),
        "world" => {
            *context
                .world
                .spec
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) = arg(args, 0).clone();
            Ok(Value::Null)
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}

fn main() {
    let mut raw = String::new();
    std::io::stdin().read_to_string(&mut raw).expect("stdin");
    let Ok(Value::Object(request)) = car_machine::compat::loads(&raw) else {
        eprintln!("the request is not a JSON object");
        std::process::exit(2);
    };
    let context = Context {
        world: world::World::new(request.get("world").cloned().unwrap_or(Value::Null)),
        product_version: match request.get("product_version") {
            Some(Value::Str(version)) => version.as_str().unwrap_or("").to_owned(),
            _ => String::new(),
        },
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
        // D15: a panic is caught at the boundary; a case that panics is an error of its own class.
        let done = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            dispatch(&context, op, args)
        }));
        results.push(match done {
            Ok(Ok(value)) => object([("ok", value)]),
            Ok(Err(Failure { class, code: None })) => object([("error", class.into())]),
            Ok(Err(Failure {
                class,
                code: Some(code),
            })) => object([("error", class.into()), ("code", code.into())]),
            Err(_) => object([("error", "Panic".into())]),
        });
    }
    let answer = object([("results", Value::Array(results))]);
    let text = to_string(&answer, &Options::new()).expect("the answer is JSON");
    let mut out = std::io::stdout().lock();
    out.write_all(text.as_bytes()).expect("stdout");
}
