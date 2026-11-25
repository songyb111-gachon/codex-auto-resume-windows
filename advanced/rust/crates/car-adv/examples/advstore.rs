//! The advanced store's differential harness (seat S7.1a): never shipped, built on demand
//! (`cargo build --release -p car-adv --example advstore`, from `advanced/rust`).
//!
//! `advstore <request.json>` runs one request and writes one JSON line per operation: `{"ok": value}` or
//! `{"raised": class, "message": text, "word": refusal}` - what `tests/rustdiff/advstore.py`'s reference runner
//! writes for the same request. The request names a scratch home, a pinned clock, the registry ("shipped" or
//! "none"), a token counter (the stand-in for `secrets.token_hex` both sides use) and the operations: the state's
//! methods by name, a capability's view (`scoped`), the claim ledger on core's connection (`ledger`), the saved
//! accounts (`profiles`), a prompt's pictures (`images`) and the watch log (`watchlog`). `ready` and `go`, when
//! given, are paths: once the state is made the harness writes `ready` and waits for `go`, so two processes - either
//! implementation - can claim at the same moment.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use car_adv::images::{self, ImageError};
use car_adv::ledger::ClaimLedger;
use car_adv::profiles::{self, ProfileError, Profiles};
use car_adv::registry::{self, Registry};
use car_adv::state::calls::{self, Call};
use car_adv::state::scoped::Scoped;
use car_adv::state::seam::Tokens;
use car_adv::state::seam::accounts::{Failure, Host};
use car_adv::state::{AdvancedState, Error};
use car_adv::watchlog;
use car_machine::json::{Map, Str, Value};

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

/// `secrets.token_hex(n)` as both sides stand it in: a counter, as 2n lowercase hex digits.
struct Counter(Mutex<u64>);

impl Counter {
    fn next(&self, count: usize) -> String {
        let mut held = self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *held += 1;
        format!("{:0>width$x}", *held, width = count * 2)
    }
}

impl Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        self.next(count)
    }
}

/// The saved accounts' host in the harness: a seal both sides use (`SEALED:` and the bytes), a lock that is always
/// free, no access list, no sweep, and the put-back's answer as `swap.unwind` gives it with nothing to put back.
struct Scratch(Arc<Counter>);

impl Host for Scratch {
    fn seal(&self, data: &[u8]) -> Result<Vec<u8>, Failure> {
        let mut sealed = b"SEALED:".to_vec();
        sealed.extend_from_slice(data);
        Ok(sealed)
    }
    fn open(&self, blob: &[u8]) -> Result<Vec<u8>, Failure> {
        blob.strip_prefix(b"SEALED:")
            .map(<[u8]>::to_vec)
            .ok_or_else(|| Failure("not sealed".into()))
    }
    fn lock(&self, _directory: &Path, _seconds: f64) -> Result<Box<dyn std::any::Any>, Failure> {
        Ok(Box::new(()))
    }
    fn private(&self, _directory: &Path) {}
    fn sweep(&self, _directory: &Path, _codex_home: Option<&Path>) {}
    fn unwind(&self, _intent: &Value, _codex_home: Option<&Path>) -> bool {
        true
    }
    fn token(&self, count: usize) -> String {
        self.0.next(count)
    }
}

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::new(key), value);
    }
    Value::Object(map)
}

fn text(value: &str) -> Value {
    Value::Str(Str::new(value))
}

fn raised(class: &str, message: &str, word: Option<&str>) -> Value {
    object(vec![
        ("raised", text(class)),
        ("message", text(message)),
        ("word", word.map_or(Value::Null, text)),
    ])
}

fn answer(result: Result<Value, Error>) -> Value {
    match result {
        Ok(value) => object(vec![("ok", value)]),
        Err(error) => raised(error.class(), &error.message(), error.word()),
    }
}

fn get<'a>(map: &'a Map, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map.get(name).unwrap_or(&NULL)
}

fn words(value: &Value) -> Vec<String> {
    match value {
        Value::Array(items) => items
            .iter()
            .map(|item| match item {
                Value::Str(text) => text.as_str().unwrap_or_default().to_string(),
                other => car_machine::pytext::py_str(other),
            })
            .collect(),
        _ => Vec::new(),
    }
}

fn profile_answer(result: Result<Value, ProfileError>) -> Value {
    match result {
        Ok(value) => object(vec![("ok", value)]),
        Err(error) => raised(error.class, &error.message, None),
    }
}

fn rows(found: Vec<car_adv::state::sql::Row>) -> Value {
    calls::rows(found)
}

fn profiles_call(store: &Profiles, name: &str, call: Call<'_>) -> Value {
    let arg = |index: usize, key: &str| call.opt(Some(index), key);
    let bytes = |value: Value| profiles::value_bytes(&value).unwrap_or_default();
    let result: Result<Value, ProfileError> = (|| {
        Ok(match name {
            "ids" => Value::Array(store.ids().iter().map(|id| text(id)).collect()),
            "get" => Value::Object(store.get(&arg(0, "profile_id"))?),
            "find" => store
                .find(&arg(0, "email"))?
                .map_or(Value::Null, |id| text(&id)),
            "save" => {
                text(&store.save(&bytes(arg(0, "data")), &arg(1, "email"), &arg(2, "plan"))?)
            }
            "update" => {
                store.update(&arg(0, "profile_id"), &call.rest(&["profile_id"]))?;
                Value::Null
            }
            "delete" => Value::Bool(store.delete(&arg(0, "profile_id"))),
            "delete_all" => car_adv::state::py::int(store.delete_all(None)?),
            "view" => rows(store.view()?),
            "read_now_at" => store.read_now_at()?,
            "note_read_now" => {
                store.note_read_now(car_adv::state::py::as_f64(&arg(0, "at")).unwrap_or(0.0))?;
                Value::Null
            }
            "intent" => store.intent()?,
            "begin" => {
                store.begin(
                    &arg(0, "source"),
                    &arg(1, "target"),
                    &call.or(Some(2), "step", text("swap")),
                    &call.or(Some(3), "tries", car_adv::state::py::int(0)),
                    &call.opt(None, "put_in"),
                    &call.opt(None, "previous"),
                    &call.opt(None, "to_email"),
                )?;
                Value::Null
            }
            "end" => {
                store.end();
                Value::Null
            }
            "last_switch_at" => store.last_switch_at()?,
            "attempts" => store.attempts()?,
            "note_attempts" => {
                let times: Vec<i64> = match arg(0, "times") {
                    Value::Array(items) => {
                        items.iter().filter_map(car_adv::state::py::small).collect()
                    }
                    _ => Vec::new(),
                };
                store.note_attempts(&times)?;
                Value::Null
            }
            "mark_switched" => {
                store.mark_switched(
                    car_adv::state::py::text(&arg(0, "email")).unwrap_or_default(),
                )?;
                Value::Null
            }
            "switched_to" => Value::Bool(store.switched_to(&arg(0, "identity"), &arg(1, "after"))?),
            "state" => match arg(0, "found") {
                Value::Object(found) => text(store.state(
                    &found,
                    car_adv::state::py::as_f64(&call.opt(Some(1), "now")),
                )),
                _ => Value::Null,
            },
            "fn.reading" => profiles::reading(&arg(0, "value")),
            "fn.mask" => car_adv::state::seam::accounts::mask(&arg(0, "email"))
                .map_or(Value::Null, Value::Str),
            "fn.is_id" => {
                Value::Bool(car_adv::state::py::text(&arg(0, "text")).is_some_and(profiles::is_id))
            }
            _ => {
                return Err(ProfileError {
                    class: "AttributeError",
                    message: name.into(),
                });
            }
        })
    })();
    profile_answer(result)
}

fn images_call(folder: &Path, tokens: &Counter, name: &str, call: Call<'_>) -> Value {
    let arg = |index: usize, key: &str| call.opt(Some(index), key);
    let prompt = |value: Value| car_machine::pytext::py_str(&value);
    let refusal = |error: ImageError| match error {
        ImageError::Refused(word) => raised("ImageRefused", word, Some(word)),
        ImageError::Os(message) => raised("OSError", &message, None),
    };
    let ok = |value: Value| object(vec![("ok", value)]);
    match name {
        "read" => match car_adv::state::py::text(&arg(0, "source")) {
            None => refusal(ImageError::Refused("image_refused")),
            Some(source) => match images::read(source) {
                Ok((data, ext)) => ok(Value::Array(vec![profiles::bytes_value(&data), text(ext)])),
                Err(error) => refusal(error),
            },
        },
        "kind" => ok(profiles::value_bytes(&arg(0, "data"))
            .and_then(|data| images::kind(&data))
            .map_or(Value::Null, text)),
        "stage" => {
            let data = profiles::value_bytes(&arg(0, "data")).unwrap_or_default();
            let ext = car_machine::pytext::py_str(&arg(1, "ext"));
            match images::stage(folder, tokens, &data, &ext) {
                Ok(id) => ok(text(&id)),
                Err(error) => refusal(error),
            }
        }
        "of" => ok(Value::Array(
            images::of(folder, &prompt(arg(0, "prompt_id")))
                .into_iter()
                .map(|(id, path)| object(vec![("id", text(&id)), ("path", text(&path))]))
                .collect(),
        )),
        "count" => ok(car_adv::state::py::int(
            images::count(folder, &prompt(arg(0, "prompt_id"))) as i64,
        )),
        "kept" => {
            let (found, size) = images::kept(folder, &words(&arg(0, "pending")));
            ok(Value::Array(vec![
                car_adv::state::py::int(found),
                car_adv::state::py::int(size as i64),
            ]))
        }
        "place" => match images::place(
            folder,
            &prompt(arg(0, "prompt_id")),
            &words(&arg(1, "images")),
        ) {
            Ok(()) => ok(Value::Null),
            Err(error) => refusal(error),
        },
        "drop" => {
            images::drop_staged(folder, &words(&arg(0, "images")));
            ok(Value::Null)
        }
        "problem" => ok(Value::Bool(images::problem(
            folder,
            &prompt(arg(0, "prompt_id")),
        ))),
        "sweep" => ok(car_adv::state::py::int(images::sweep(
            folder,
            &words(&arg(0, "pending")),
        ))),
        _ => raised("AttributeError", name, None),
    }
}

fn ledger_call(state: &AdvancedState, home: &Path, op: &Map) -> Value {
    let path = home.join("config").join("state.sqlite");
    let connection = match car_store::session::connect(&path) {
        Ok(connection) => connection,
        Err(error) => return raised("OperationalError", &error.to_string(), None),
    };
    let ledger = ClaimLedger { state };
    let now = car_adv::state::py::as_f64(get(op, "now")).unwrap_or(0.0);
    let run = || -> Result<Value, Error> {
        connection.execute_batch("BEGIN IMMEDIATE")?;
        let found = match get(op, "ledger") {
            Value::Str(kind) if kind.as_str() == Some("record") => {
                ledger.record(&connection, get(op, "record"), now)
            }
            _ => ledger.claim(
                &connection,
                get(op, "record"),
                now,
                get(op, "acted"),
                get(op, "verified"),
                matches!(get(op, "unvouched"), Value::Bool(true)),
            ),
        };
        let end = if matches!(get(op, "end"), Value::Str(word) if word.as_str() == Some("rollback"))
        {
            "ROLLBACK"
        } else {
            "COMMIT"
        };
        match found {
            Ok(word) => {
                connection.execute_batch(end)?;
                Ok(text(word.word()))
            }
            Err(error) => {
                let _ = connection.execute_batch("ROLLBACK");
                Err(error)
            }
        }
    };
    answer(run())
}

fn main() {
    // Values nest as deep as Python's json.loads takes them (about 3,000 levels): the work runs on a stack of its own
    // with room for that, as a watcher thread of the product would be given.
    let worker = std::thread::Builder::new()
        .stack_size(256 * 1024 * 1024)
        .spawn(run)
        .expect("the harness thread");
    if worker.join().is_err() {
        std::process::exit(101);
    }
}

fn run() {
    let request_path = std::env::args().nth(1).expect("a request file");
    let request = std::fs::read_to_string(&request_path).expect("the request");
    let Value::Object(request) = car_machine::compat::loads(&request).expect("a JSON request")
    else {
        panic!("the request is a JSON object");
    };
    let home = PathBuf::from(car_machine::pytext::py_str(get(&request, "home")));
    let clock = Arc::new(Mutex::new(
        car_adv::state::py::as_f64(get(&request, "clock")).unwrap_or(0.0),
    ));
    let seed = car_adv::state::py::small(get(&request, "tokens")).unwrap_or(0) as u64;
    let counter = Arc::new(Counter(Mutex::new(seed)));
    let registry: Arc<Registry> = match get(&request, "registry") {
        Value::Str(word) if word.as_str() == Some("none") => {
            Arc::new(Registry::new(Vec::new()).expect("an empty registry"))
        }
        _ => Arc::new(registry::shipped(false).expect("the shipped registry")),
    };
    let no_env = |_: &str| None;
    let paths = car_config::Paths::new(
        Some(&home.to_string_lossy()),
        &home.to_string_lossy(),
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .expect("the home's paths");
    let reading = Arc::clone(&clock);
    let state = AdvancedState::new(
        paths.clone(),
        registry,
        Box::new(move || {
            *reading
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        }),
        counter.clone() as Arc<dyn Tokens>,
    );
    let reading = Arc::clone(&clock);
    let store = Profiles::new(
        Path::new(&paths.home),
        Arc::new(Scratch(counter.clone())),
        Box::new(move || {
            *reading
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        }),
    );
    if let (Value::Str(ready), Value::Str(go)) = (get(&request, "ready"), get(&request, "go")) {
        let _ = state.exists();
        std::fs::write(ready.as_str().unwrap_or_default(), b"ready").expect("ready");
        let go = PathBuf::from(go.as_str().unwrap_or_default());
        let started = std::time::Instant::now();
        while !go.exists() && started.elapsed().as_secs() < 60 {
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
    let empty = Map::new();
    let mut out = String::new();
    let ops = match get(&request, "ops") {
        Value::Array(ops) => ops.clone(),
        _ => Vec::new(),
    };
    for op in ops {
        let Value::Object(op) = op else { continue };
        let args = match get(&op, "args") {
            Value::Array(args) => args.clone(),
            _ => Vec::new(),
        };
        let kwargs = match get(&op, "kwargs") {
            Value::Object(kwargs) => kwargs.clone(),
            _ => empty.clone(),
        };
        let call = Call {
            args: &args,
            kwargs: &kwargs,
        };
        let name = car_machine::pytext::py_str(get(&op, "name"));
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            if let Some(at) = car_adv::state::py::as_f64(get(&op, "clock")) {
                *clock
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner) = at;
                return object(vec![("ok", Value::Null)]);
            }
            if let Value::Str(method) = get(&op, "method") {
                return answer(calls::call(
                    &state,
                    method.as_str().unwrap_or_default(),
                    call,
                ));
            }
            if let Value::Object(view) = get(&op, "scoped") {
                let on_value = get(view, "on").clone();
                let on = move || matches!(on_value, Value::Bool(true));
                let verdicts = get(view, "verdict").clone();
                let verdict = move |measurement: &Value| match (&verdicts, measurement) {
                    (Value::Object(map), Value::Str(key)) => map
                        .get(key.as_str().unwrap_or_default())
                        .cloned()
                        .unwrap_or(Value::Null),
                    _ => Value::Null,
                };
                let armed_map = get(view, "armed").clone();
                let armed = move |other: &Value| match (&armed_map, other) {
                    (Value::Object(map), Value::Str(key)) => {
                        matches!(
                            map.get(key.as_str().unwrap_or_default()),
                            Some(Value::Bool(true))
                        )
                    }
                    _ => false,
                };
                let has = |name: &str| !matches!(get(view, name), Value::Null);
                let scoped = Scoped {
                    state: &state,
                    capability: get(view, "capability").clone(),
                    on: if has("on") { Some(&on) } else { None },
                    verdict: if has("verdict") { Some(&verdict) } else { None },
                    armed: if has("armed") { Some(&armed) } else { None },
                };
                return answer(calls::scoped_call(&scoped, &name, call));
            }
            if !matches!(get(&op, "ledger"), Value::Null) {
                return ledger_call(&state, &home, &op);
            }
            if !matches!(get(&op, "profiles"), Value::Null) {
                return profiles_call(
                    &store,
                    &car_machine::pytext::py_str(get(&op, "profiles")),
                    call,
                );
            }
            if !matches!(get(&op, "images"), Value::Null) {
                return images_call(
                    &state.directory,
                    &counter,
                    &car_machine::pytext::py_str(get(&op, "images")),
                    call,
                );
            }
            if let Value::Str(which) = get(&op, "watchlog") {
                let now = *clock
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                return answer(match which.as_str() {
                    Some("view") => watchlog::view(&state, &call.opt(Some(0), "capability"), now)
                        .map(Value::Object),
                    _ => watchlog::exported(&state, now).map(rows),
                });
            }
            raised("AttributeError", "no such operation", None)
        }));
        let line = result.unwrap_or_else(|_| raised("Panic", "the harness panicked", None));
        out.push_str(&profiles::dumps(&line, false).unwrap_or_default());
        out.push('\n');
    }
    state.close();
    print!("{out}");
}
