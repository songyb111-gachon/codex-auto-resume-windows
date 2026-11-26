//! `car-harness serve`: JSON-lines requests on stdin, one reply line each on stdout, the framing
//! `controlcli serve` uses: `{"id": n, "call": "...", ...}` in, `{"id": n, "reply": {...}}` out.
//!
//! Calls: `store.record_state` {home, interruption_id}, `store.schema_version` {home}, `sqlite.version`
//! (S0.4's, now through car-store), and car-store's own (S1.2): `store.script`, `store.legacy`,
//! `store.downgrade`, `store.open_state` (src/store.rs says what each takes). Anything else is answered
//! `not_ported`. Later seats add their calls here, and the calls that need the outside world (the backend,
//! the registry) are asked back over the same pipe.

use std::io::Write;
use std::path::Path;

use car_harness::{NOT_PORTED, leaves, object, rejected, store};
use car_machine::json::{Map, Options, Value, from_str, to_string};

fn answer(request: &serde_json::Value, line: &str) -> Value {
    let text = |name: &str| request.get(name).and_then(|value| value.as_str());
    let ok = |name: &str, value: Value| object([("ok", Value::Bool(true)), (name, value)]);
    // The store's calls read the whole line, each `{"$float": ...}` tag as its float (leaves::untag).
    let whole = || match from_str(line).map(leaves::untag) {
        Ok(Value::Object(map)) => map,
        _ => Map::new(),
    };
    let home = text("home").map(Path::new);
    match (text("call"), home) {
        (Some("store.record_state"), Some(home)) => match text("interruption_id") {
            Some(key) => match store::record_state(home, key) {
                Ok(found) => ok("value", found),
                Err(error) => rejected(
                    &format!("{}: {}", error.class(), error.message()),
                    "request_failed",
                ),
            },
            None => rejected("home and interruption_id are required", "request_failed"),
        },
        (Some("store.schema_version"), Some(home)) => match store::schema_version(home) {
            Ok(version) => ok("value", version),
            Err(error) => rejected(
                &format!("{}: {}", error.class(), error.message()),
                "request_failed",
            ),
        },
        (Some("store.script"), Some(home)) => ok("value", store::script(home, &whole())),
        (Some("store.legacy"), Some(home)) => ok("value", store::legacy(home, &whole())),
        (Some("store.downgrade"), Some(home)) => ok("value", store::downgrade(home, &whole())),
        (Some("store.open_state"), Some(home)) => ok("value", store::open(home, &whole())),
        (Some(call), None) if call.starts_with("store.") => {
            rejected("home is required", "request_failed")
        }
        (Some("bridge.run"), Some(home)) => ok("value", car_harness::bridge::run(home, &whole())),
        (Some("control.call"), Some(home)) => {
            ok("value", car_harness::bridge::call(home, &whole()))
        }
        (Some("sqlite.version"), _) => ok("value", Value::from(car_store::sqlite_version())),
        (Some("leaves.batch"), _) => match request.get("cases").and_then(|_| leaves::read(request))
        {
            Some(Value::Object(parsed)) => {
                ok("value", leaves::tag(leaves::batch(&parsed["cases"])))
            }
            _ => rejected("cases are required", "request_failed"),
        },
        (Some("codexapp.script"), _) => {
            match request.get("cases").and_then(|_| leaves::read(request)) {
                Some(Value::Object(parsed)) => {
                    ok("value", car_harness::appserver::script(&parsed["cases"]))
                }
                _ => rejected("cases are required", "request_failed"),
            }
        }
        // S4.1: car-engine's sessions (src/engine.rs), whose backend is asked back over this pipe.
        (Some(call), _) if call.starts_with("engine.") => {
            ok("value", car_harness::engine::answer(call, &whole()))
        }
        (Some("surface.batch"), _) => {
            match request.get("cases").and_then(|_| leaves::read(request)) {
                Some(Value::Object(parsed)) => ok(
                    "value",
                    leaves::tag(car_harness::surface::batch(&parsed["cases"])),
                ),
                _ => rejected("cases are required", "request_failed"),
            }
        }
        // S6.1: car-watcher's loop over a scripted world (src/watcher.rs).
        (Some("watcher.loop"), _) => ok("value", car_harness::watcher::run_loop(&whole())),
        (Some("watcher.batch"), _) => match request.get("cases").and_then(|_| leaves::read(request)) {
            Some(Value::Object(parsed)) => ok(
                "value",
                leaves::tag(car_harness::watcher::batch(&parsed["cases"])),
            ),
            _ => rejected("cases are required", "request_failed"),
        },
        (Some("codex.script"), _) => match request.get("cases").and_then(|_| leaves::read(request))
        {
            Some(Value::Object(parsed)) => ok(
                "value",
                leaves::tag(car_harness::codex::script(&parsed["cases"])),
            ),
            _ => rejected("cases are required", "request_failed"),
        },
        _ => rejected("this call is not ported", NOT_PORTED),
    }
}

fn serve() -> i32 {
    let mut stdout = std::io::stdout().lock();
    // One line at a time, stdin locked only while a line is read: an engine step asks back on the same pipe.
    while let Some(line) = car_harness::engine::read_line() {
        let line = line.trim_start_matches('\u{feff}').trim();
        if line.is_empty() {
            continue;
        }
        // S2.2's calls read the line as Python's json.loads does (NaN, lone surrogates), which serde refuses.
        let loose = if line.contains("\"policy.batch\"") {
            car_harness::policy::answer(line)
        } else if line.contains("\"proxy.") {
            car_harness::proxy::line(line)
        } else {
            None
        };
        let (id, reply) = match serde_json::from_str::<serde_json::Value>(line) {
            _ if loose.is_some() => loose.unwrap_or((Value::Null, Value::Null)),
            Ok(request) if request.is_object() => {
                let id = request
                    .get("id")
                    .and_then(|value| value.as_i64())
                    .map_or(Value::Null, Value::from);
                (id, answer(&request, line))
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
        let envelope = object([("id", id), ("reply", reply)]);
        // A text holding half of a pair cannot be written as itself: it goes as its escape, as ensure_ascii writes it.
        let text = to_string(&envelope, &Options::wire())
            .or_else(|_| to_string(&envelope, &Options::new()))
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
