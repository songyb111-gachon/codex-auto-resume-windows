//! The pipe of `advserve`: one JSON line each way, and the questions car-adv asks the test back while a call waits.
//!
//! A line from the test with `"call"` is a request (answered with `{"id", "reply"}`); one with `"answer"` or `"raise"`
//! answers the question this process asked last. A request read while an answer is awaited is a call the test made
//! from inside its answer (a code that reads its `Scoped`, a channel's errand that asks again): it is handled there,
//! nested, before the wait goes on - the same rule as car-harness's `proxy.rs`.

use std::io::{BufRead, Write};

use car_adv::capabilities::Raised;
use car_machine::json::{Map, Options, Str, Value, from_str, to_string};

/// One line from the test, or None at the end of its input (the test process is gone: this one ends too).
pub fn read() -> Option<Value> {
    let mut line = String::new();
    loop {
        line.clear();
        let read = std::io::stdin().lock().read_line(&mut line).ok()?;
        if read == 0 {
            return None;
        }
        if !line.trim().is_empty() {
            return from_str(line.trim_end()).ok();
        }
    }
}

/// One line to the test.
pub fn write(value: &Value) {
    let text = to_string(value, &Options::new()).unwrap_or_else(|_| "{}".to_owned());
    let mut out = std::io::stdout().lock();
    let _ = out.write_all(text.as_bytes());
    let _ = out.write_all(b"\n");
    let _ = out.flush();
}

pub fn text(word: &str) -> Value {
    Value::Str(Str::new(word))
}

pub fn field<'a>(value: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

pub fn word(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

/// `{"ask": kind, ...fields}`, and the test's answer: its value, or what it raised.
pub fn ask(kind: &str, fields: Vec<(&str, Value)>) -> Result<Value, Raised> {
    let mut map = Map::new();
    map.insert(Str::new("ask"), text(kind));
    for (name, value) in fields {
        map.insert(Str::new(name), value);
    }
    write(&Value::Object(map));
    loop {
        let Some(line) = read() else {
            std::process::exit(0);
        };
        if !matches!(field(&line, "call"), Value::Null) {
            let reply = crate::handle(&line);
            write(&reply);
            continue;
        }
        if let Value::Object(map) = &line {
            if let Some(answer) = map.get("answer") {
                return Ok(answer.clone());
            }
            if let Some(class) = map.get("raise") {
                return Err(Raised {
                    class: word(class).unwrap_or("Exception").to_owned(),
                    cause: word(field(&line, "cause")).map(str::to_owned),
                    at: word(field(&line, "at")).map(str::to_owned),
                });
            }
        }
    }
}
