//! `car-harness serve`: JSON-lines requests on stdin, one reply line each on stdout, the framing
//! `controlcli serve` uses: `{"id": n, "call": "...", ...}` in, `{"id": n, "reply": {...}}` out.
//!
//! Calls today (S0.4): `store.record_state` {home, interruption_id}, `store.schema_version` {home},
//! `sqlite.version`. Anything else is answered `not_ported`. Later seats add their calls here, and the
//! calls that need the outside world (the backend, the registry) are asked back over the same pipe.

use std::io::{BufRead, Write};
use std::path::Path;

use car_harness::pyjson::{Value, dumps};
use car_harness::{NOT_PORTED, rejected, state};

fn answer(request: &serde_json::Value) -> Value {
    let text = |name: &str| request.get(name).and_then(|value| value.as_str());
    let ok = |name: &str, value: Value| {
        Value::Object(vec![("ok".into(), Value::Bool(true)), (name.into(), value)])
    };
    match text("call") {
        Some("store.record_state") => match (text("home"), text("interruption_id")) {
            (Some(home), Some(key)) => match state::record_state(Path::new(home), key) {
                Ok(found) => ok("value", found.map_or(Value::Null, Value::Str)),
                Err(error) => rejected(&format!("sqlite: {error}"), "request_failed"),
            },
            _ => rejected("home and interruption_id are required", "request_failed"),
        },
        Some("store.schema_version") => match text("home") {
            Some(home) => match state::schema_version(Path::new(home)) {
                Ok(version) => ok("value", Value::Int(version)),
                Err(error) => rejected(&format!("sqlite: {error}"), "request_failed"),
            },
            None => rejected("home is required", "request_failed"),
        },
        Some("sqlite.version") => ok("value", Value::Str(state::sqlite_version().into())),
        _ => rejected("this call is not ported", NOT_PORTED),
    }
}

fn serve() -> i32 {
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout().lock();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let line = line.trim_start_matches('\u{feff}').trim();
        if line.is_empty() {
            continue;
        }
        let (id, reply) = match serde_json::from_str::<serde_json::Value>(line) {
            Ok(request) if request.is_object() => {
                let id = request
                    .get("id")
                    .and_then(|value| value.as_i64())
                    .map_or(Value::Null, Value::Int);
                (id, answer(&request))
            }
            Ok(_) => (
                Value::Null,
                rejected("request must be a JSON object", "request_failed"),
            ),
            Err(_) => (
                Value::Null,
                rejected("request must be JSON", "request_failed"),
            ),
        };
        let envelope = Value::Object(vec![("id".into(), id), ("reply".into(), reply)]);
        let text = dumps(&envelope)
            .unwrap_or_else(|_| "{\"id\": null, \"reply\": {\"ok\": false}}".into());
        if writeln!(stdout, "{text}")
            .and_then(|_| stdout.flush())
            .is_err()
        {
            return 1;
        }
    }
    0
}

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    match arguments.first().map(String::as_str) {
        Some("serve") => std::process::exit(serve()),
        _ => {
            eprintln!("usage: car-harness serve");
            std::process::exit(2);
        }
    }
}
