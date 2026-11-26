//! How deep `json.loads` and `json.dumps` let a document nest, asked of car-machine (follow 3.14,
//! `tests/rustdiff/diffs_nesting_314.py`).
//!
//! A case names a pattern of container kinds (`L` a list, `O` an object, cycled), a count `n` of containers and a
//! leaf; both sides build the same document from it, so a case is a few bytes however deep it goes:
//!
//! * `json.loads` `[pattern, n, leaf]`: `json.loads(text)`; `"ok"`, or the exception's class name.
//! * `json.decode` `[pattern, n, leaf]`: `compat.model.decode(text)` (its hooks); `"ok"` or the refusal's code.
//! * `json.raw_decode` `[pattern, n, leaf]`: `JSONDecoder().raw_decode(text, 0)`; `["ok", end]` or the class name.
//! * `json.dumps` `[pattern, n, leaf, options]`: `json.dumps` of the document; `["ok", length, sha256]` or the class.
//! * `json.bisect` `[what]`: the largest `n` this side takes, for `loads:L`, `loads:O`, `loads:LO`, `loads:OL`,
//!   `dumps:L`, `dumps:O`, `dumps:LO`, `hook:O`, `hook:float`, `hook:nan`.
//! * `json.limits` `[]`: the four constants car-machine keeps.
//!
//! Leaves: `"0"`, `"1.5"`, `"NaN"`, `"1e999"` (loads) or `"0"` (dumps), and `"empty"`: the n-th container is empty.

use car_machine::compat::{self, LoadsError};
use car_machine::hash;
use car_machine::json::{
    DUMPS_LIST_LEVELS, DUMPS_OBJECT_LEVELS, Error, Map, Options, Str, Value, to_string,
};
use car_machine::pyval::Py;

use super::Args;

fn kinds(pattern: &str, n: usize) -> Py<Vec<bool>> {
    if pattern.is_empty() || !pattern.chars().all(|each| each == 'L' || each == 'O') {
        return Err("ValueError");
    }
    let cycle: Vec<bool> = pattern.chars().map(|each| each == 'L').collect();
    Ok((0..n).map(|index| cycle[index % cycle.len()]).collect())
}

/// The text: `n` containers round the leaf, the n-th empty when the leaf is `empty`.
fn text_of(kinds: &[bool], leaf: &str) -> String {
    let mut text = String::new();
    let last = kinds.len().saturating_sub(1);
    for (index, list) in kinds.iter().enumerate() {
        if leaf == "empty" && index == last {
            text.push_str(if *list { "[]" } else { "{}" });
            break;
        }
        text.push_str(if *list { "[" } else { "{\"a\":" });
    }
    if leaf != "empty" {
        text.push_str(leaf);
    }
    let closed = if leaf == "empty" {
        kinds.len().saturating_sub(1)
    } else {
        kinds.len()
    };
    for list in kinds[..closed].iter().rev() {
        text.push(if *list { ']' } else { '}' });
    }
    text
}

fn loads_answer(text: &str) -> Py<Value> {
    match compat::loads(text) {
        Ok(_) => Ok(Value::from("ok")),
        Err(LoadsError::Recursion) => Err("RecursionError"),
        Err(LoadsError::Value) => Err("JSONDecodeError"),
        Err(LoadsError::IntTooLong) => Err("ValueError"),
    }
}

fn decode_answer(text: &str) -> Value {
    match compat::decode(text.as_bytes(), usize::MAX) {
        Ok(_) => Value::from("ok"),
        Err(refused) => Value::from(refused.code),
    }
}

fn raw_answer(text: &str) -> Py<Value> {
    let chars: Vec<char> = text.chars().collect();
    match compat::raw_decode(&chars, 0) {
        Ok((_, end)) => Ok(Value::Array(vec![
            Value::from("ok"),
            Value::from(end as i64),
        ])),
        Err(LoadsError::Recursion) => Err("RecursionError"),
        Err(LoadsError::Value) => Err("JSONDecodeError"),
        Err(LoadsError::IntTooLong) => Err("ValueError"),
    }
}

/// The value: `n` containers round the leaf, innermost first.
fn value_of(kinds: &[bool], leaf: &str) -> Value {
    let mut value = Value::Int(0.into());
    let empty = leaf == "empty";
    for (index, list) in kinds.iter().enumerate().rev() {
        let held = if empty && index + 1 == kinds.len() {
            None
        } else {
            Some(std::mem::replace(&mut value, Value::Null))
        };
        value = if *list {
            Value::Array(held.into_iter().collect())
        } else {
            let mut map = Map::new();
            if let Some(held) = held {
                // two keys, "b" first: sort_keys has an order to make
                map.insert(Str::new("b"), Value::Int(0.into()));
                map.insert(Str::new("a"), held);
            }
            Value::Object(map)
        };
    }
    value
}

fn options_of(name: &str) -> Py<Options> {
    Ok(match name {
        "plain" => Options::new(),
        "indent0" => Options::new().indent(0),
        "indent2" => Options::new().indent(2),
        "sort" => Options::new().sort_keys(true),
        "sep" => Options::new().separators(",", ":"),
        _ => return Err("ValueError"),
    })
}

fn dumps_answer(kinds: &[bool], leaf: &str, options: &Options) -> Py<Value> {
    let value = value_of(kinds, leaf);
    match to_string(&value, options) {
        Ok(text) => Ok(Value::Array(vec![
            Value::from("ok"),
            Value::from(text.chars().count() as i64),
            Value::from(hash::hex(&hash::sha256(text.as_bytes()))),
        ])),
        Err(Error::TooDeep) => Err("RecursionError"),
        Err(_) => Err("ValueError"),
    }
}

/// The largest `n` for which `accepts(n)`, found by doubling and then halving (the limits are monotone).
fn largest(accepts: impl Fn(usize) -> bool) -> usize {
    let (mut low, mut high) = (1, 1000);
    while accepts(high) {
        low = high;
        high *= 2;
    }
    while high - low > 1 {
        let middle = (low + high) / 2;
        if accepts(middle) {
            low = middle;
        } else {
            high = middle;
        }
    }
    low
}

fn bisect(what: &str) -> Py<Value> {
    let found = match what {
        "loads:L" | "loads:O" | "loads:LO" | "loads:OL" => {
            let pattern = what.trim_start_matches("loads:");
            largest(|n| {
                kinds(pattern, n).is_ok_and(|each| compat::loads(&text_of(&each, "0")).is_ok())
            })
        }
        "dumps:L" | "dumps:O" | "dumps:LO" => {
            let pattern = what.trim_start_matches("dumps:");
            largest(|n| {
                kinds(pattern, n)
                    .is_ok_and(|each| to_string(&value_of(&each, "empty"), &Options::new()).is_ok())
            })
        }
        "hook:O" => largest(|n| {
            kinds("O", n).is_ok_and(|each| decode_answer(&text_of(&each, "0")) == Value::from("ok"))
        }),
        "hook:float" | "hook:nan" => {
            let leaf = if what == "hook:float" { "1.5" } else { "NaN" };
            largest(|n| {
                kinds("L", n).is_ok_and(|each| {
                    decode_answer(&text_of(&each, leaf)) != Value::from("too_deep")
                })
            })
        }
        _ => return Err("ValueError"),
    };
    Ok(Value::from(found as i64))
}

pub fn case(name: &str, a: &Args) -> Option<Py<Value>> {
    Some(match name {
        "json.loads" | "json.decode" | "json.raw_decode" => (|| {
            let n = a.int(1)? as usize;
            let list = kinds(a.text(0)?, n)?;
            let text = text_of(&list, a.text(2)?);
            match name {
                "json.loads" => loads_answer(&text),
                "json.decode" => Ok(decode_answer(&text)),
                _ => raw_answer(&text),
            }
        })(),
        "json.dumps" => (|| {
            let n = a.int(1)? as usize;
            let list = kinds(a.text(0)?, n)?;
            dumps_answer(&list, a.text(2)?, &options_of(a.text(3)?)?)
        })(),
        "json.bisect" => a.text(0).and_then(bisect),
        "json.limits" => Ok(Value::Array(
            [
                compat::LOADS_LIST_LEVELS,
                compat::LOADS_OBJECT_LEVELS,
                DUMPS_LIST_LEVELS,
                DUMPS_OBJECT_LEVELS,
            ]
            .iter()
            .map(|each| Value::from(*each))
            .collect(),
        )),
        _ => return None,
    })
}
