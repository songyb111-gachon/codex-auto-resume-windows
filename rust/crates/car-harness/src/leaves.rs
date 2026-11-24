//! The leaf crates' calls (S1.1: car-machine, car-config, car-words, car-brand), one batch at a time.
//!
//! `leaves.batch` takes `cases`, a list of `[name, arg, ...]`, and answers a list with one entry per case:
//! `{"ok": value}` or `{"error": "ExceptionName"}`, the shape `tests/rustdiff/leaves.py`'s reference side
//! writes with Python's own exceptions' names. The functions are the crates' own: nothing here decides anything.

use car_machine::json::{Map, Str, Value, from_str};
use car_machine::pyval::Py;

mod machine;
mod words;

fn ok(value: Value) -> Value {
    let mut entry = Map::new();
    entry.insert(Str::from("ok"), value);
    Value::Object(entry)
}

fn error(name: &str) -> Value {
    let mut entry = Map::new();
    entry.insert(Str::from("error"), Value::from(name));
    Value::Object(entry)
}

/// The arguments of one case, read as the Python's `json.loads` reads them.
pub struct Args<'a>(pub &'a [Value]);

impl<'a> Args<'a> {
    pub fn get(&self, at: usize) -> &'a Value {
        static NULL: Value = Value::Null;
        self.0.get(at).unwrap_or(&NULL)
    }

    pub fn text(&self, at: usize) -> Py<&'a str> {
        match self.get(at) {
            Value::Str(text) => text.as_str().ok_or("ValueError"),
            _ => Err("TypeError"),
        }
    }

    pub fn flag(&self, at: usize) -> bool {
        matches!(self.get(at), Value::Bool(true))
    }

    pub fn int(&self, at: usize) -> Py<i64> {
        match self.get(at) {
            Value::Int(int) => int.as_i64().ok_or("OverflowError"),
            _ => Err("TypeError"),
        }
    }

    pub fn float(&self, at: usize) -> Py<f64> {
        car_machine::pytext::to_float(self.get(at))
    }

    /// A `bytes` argument, sent as hex.
    pub fn bytes(&self, at: usize) -> Py<Vec<u8>> {
        let hex = self.text(at)?;
        (0..hex.len() / 2)
            .map(|i| u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).map_err(|_| "ValueError"))
            .collect()
    }
}

/// One case: `Some(result)` where this harness knows the name, `None` where not.
fn case(name: &str, args: &Args) -> Option<Py<Value>> {
    machine::case(name, args).or_else(|| words::case(name, args))
}

/// `leaves.batch`: every case of `cases`, in order.
pub fn batch(cases: &Value) -> Value {
    let Value::Array(cases) = cases else {
        return Value::Null;
    };
    let mut answers = Vec::with_capacity(cases.len());
    for each in cases {
        let Value::Array(parts) = each else {
            answers.push(error("TypeError"));
            continue;
        };
        let name = match parts.first() {
            Some(Value::Str(name)) => name.as_str().unwrap_or_default().to_owned(),
            _ => {
                answers.push(error("TypeError"));
                continue;
            }
        };
        let args = Args(&parts[1..]);
        answers.push(match case(&name, &args) {
            Some(Ok(value)) => ok(value),
            Some(Err(name)) => error(name),
            None => error(&format!("NotPorted:{name}")),
        });
    }
    Value::Array(answers)
}

/// Reads the request line as the Python reads it (arbitrary-size ints, floats as floats).
pub fn read(request: &serde_json::Value) -> Option<Value> {
    from_str(&serde_json::to_string(request).ok()?).ok()
}
