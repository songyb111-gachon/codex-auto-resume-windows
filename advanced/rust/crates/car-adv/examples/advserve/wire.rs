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
            return from_str(line.trim_end()).ok().map(floats_in);
        }
    }
}

/// JSON has no NaN or infinity: the pipe carries one as `{"__float__": "nan" | "inf" | "-inf"}` (pipe.py's rule).
fn floats_in(value: Value) -> Value {
    match value {
        Value::Object(map) if map.len() == 1 && map.contains_key("__float__") => {
            match word(field(&Value::Object(map.clone()), "__float__")) {
                Some("nan") => Value::Float(f64::NAN),
                Some("inf") => Value::Float(f64::INFINITY),
                Some("-inf") => Value::Float(f64::NEG_INFINITY),
                _ => Value::Object(map),
            }
        }
        Value::Object(map) => Value::Object(
            map.into_iter()
                .map(|(key, item)| (key, floats_in(item)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.into_iter().map(floats_in).collect()),
        other => other,
    }
}

fn floats_out(value: &Value) -> Value {
    match value {
        Value::Float(number) if !number.is_finite() => {
            let said = if number.is_nan() {
                "nan"
            } else if *number > 0.0 {
                "inf"
            } else {
                "-inf"
            };
            let mut map = Map::new();
            map.insert(Str::new("__float__"), text(said));
            Value::Object(map)
        }
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(key, item)| (key.clone(), floats_out(item)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(floats_out).collect()),
        other => other.clone(),
    }
}

/// One line to the test.
pub fn write(value: &Value) {
    let text = to_string(value, &Options::new())
        .or_else(|_| to_string(&floats_out(value), &Options::new()))
        .unwrap_or_else(|_| "{}".to_owned());
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
