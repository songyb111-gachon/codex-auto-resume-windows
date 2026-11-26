//! The leaf crates' calls (S1.1: car-machine, car-config, car-words, car-brand), one batch at a time.
//!
//! `leaves.batch` takes `cases`, a list of `[name, arg, ...]`, and answers a list with one entry per case:
//! `{"ok": value}` or `{"error": "ExceptionName"}`, the shape `tests/rustdiff/leaves.py`'s reference side
//! writes with Python's own exceptions' names. The functions are the crates' own: nothing here decides anything.

use car_machine::json::{Map, Str, Value, from_str};
use car_machine::pyval::Py;

mod brand;
mod config;
mod machine;
mod nesting;
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

    /// A float sent as its bits, 16 hex digits (`struct.pack(">d", x).hex()`): every f64, NaN payloads included.
    pub fn bits(&self, at: usize) -> Py<f64> {
        let hex = self.text(at)?;
        u64::from_str_radix(hex, 16)
            .map(f64::from_bits)
            .map_err(|_| "ValueError")
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
    machine::case(name, args)
        .or_else(|| nesting::case(name, args))
        .or_else(|| words::case(name, args))
        .or_else(|| config::case(name, args))
        .or_else(|| brand::case(name, args))
        .or_else(|| crate::classify::case(name, args))
        .or_else(|| crate::codex::case(name, args))
}

/// The levels a reply keeps: the runner reading it may be a Python whose `json.loads` stops at 2,998 levels (3.13), and a
/// value past 64 is answered as `{"$nested": its depth}`, the same on the reference's side (`leaves.PRELUDE`'s `shallow`).
pub const KEEP_LEVELS: usize = 64;

/// How many arrays and objects `value` is nested, counted without recursion (it may be 17,000 deep).
pub fn nesting(value: &Value) -> usize {
    let (mut best, mut stack) = (0, vec![(value, 1usize)]);
    while let Some((node, level)) = stack.pop() {
        match node {
            Value::Array(items) => {
                best = best.max(level);
                stack.extend(items.iter().map(|each| (each, level + 1)));
            }
            Value::Object(map) => {
                best = best.max(level);
                stack.extend(map.values().map(|each| (each, level + 1)));
            }
            _ => {}
        }
    }
    best
}

/// `value`, or `{"$nested": depth}` where it nests deeper than [`KEEP_LEVELS`].
pub fn shallow(value: Value) -> Value {
    let depth = nesting(&value);
    if depth <= KEEP_LEVELS {
        return value;
    }
    let mut entry = Map::new();
    entry.insert(Str::from("$nested"), Value::from(depth as i64));
    Value::Object(entry)
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
            Some(Ok(value)) => ok(shallow(value)),
            Some(Err(name)) => error(name),
            None => error(&format!("NotPorted:{name}")),
        });
    }
    Value::Array(answers)
}

/// Reads the request line as the Python reads it (arbitrary-size ints, floats as floats), each `{"$float": ...}`
/// tag turned into its float (`untag`).
pub fn read(request: &serde_json::Value) -> Option<Value> {
    from_str(&serde_json::to_string(request).ok()?)
        .ok()
        .map(untag)
}

/// The key of the channel's float tag (`tests/rustdiff/diffs.py`, `FLOAT_TAG`): a NaN or an infinity, which JSON
/// written with `allow_nan=False` and serde cannot carry, crosses as `{"$float": "nan" | "inf" | "-inf"}`.
pub const FLOAT_TAG: &str = "$float";

/// `value` with every float tag turned into its float. A one-key object of any other value is left as it is.
pub fn untag(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            if map.len() == 1
                && let Some(Value::Str(word)) = map.get(FLOAT_TAG)
            {
                match word.as_str() {
                    Some("nan") => return Value::Float(f64::NAN),
                    Some("inf") => return Value::Float(f64::INFINITY),
                    Some("-inf") => return Value::Float(f64::NEG_INFINITY),
                    _ => {}
                }
            }
            Value::Object(
                map.into_iter()
                    .map(|(key, each)| (key, untag(each)))
                    .collect(),
            )
        }
        Value::Array(items) => Value::Array(items.into_iter().map(untag).collect()),
        other => other,
    }
}

/// `value` with every NaN and infinity written as its float tag, as the reference's family scripts write theirs.
pub fn tag(value: Value) -> Value {
    match value {
        Value::Float(x) if x.is_nan() => float_tag("nan"),
        Value::Float(x) if x.is_infinite() => float_tag(if x > 0.0 { "inf" } else { "-inf" }),
        Value::Object(map) => Value::Object(
            map.into_iter()
                .map(|(key, each)| (key, tag(each)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.into_iter().map(tag).collect()),
        other => other,
    }
}

fn float_tag(word: &str) -> Value {
    let mut map = Map::new();
    map.insert(Str::from(FLOAT_TAG), Value::from(word));
    Value::Object(map)
}

#[cfg(test)]
mod tests {
    use super::{tag, untag};
    use car_machine::json::{Options, from_str, to_string};

    #[test]
    fn a_tag_is_a_float_and_a_float_a_tag() {
        let sent = from_str(
            r#"[{"$float": "nan"}, {"$float": "inf"}, {"x": {"$float": "-inf"}}, {"$float": "other"}, {"$float": "nan", "y": 1}, 1.5]"#,
        )
        .unwrap();
        let read = untag(sent);
        let car_machine::json::Value::Array(items) = &read else {
            panic!("an array")
        };
        assert!(matches!(items[0], car_machine::json::Value::Float(x) if x.is_nan()));
        assert!(matches!(items[1], car_machine::json::Value::Float(x) if x == f64::INFINITY));
        let back = to_string(&tag(read), &Options::wire()).unwrap();
        assert_eq!(
            back,
            r#"[{"$float": "nan"}, {"$float": "inf"}, {"x": {"$float": "-inf"}}, {"$float": "other"}, {"$float": "nan", "y": 1}, 1.5]"#
        );
    }
}
