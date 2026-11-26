//! What every op reads its arguments with.
#![allow(dead_code)]

use car_machine::json::{Map, Value};

/// An op's refusal: the class name the reference's exception has, and the closed code it carries where it has one.
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

pub fn text(value: &Value) -> Result<&str, Failure> {
    match value {
        Value::Str(each) => each.as_str().ok_or_else(bad),
        _ => Err(bad()),
    }
}

pub fn maybe_text(value: &Value) -> Result<Option<&str>, Failure> {
    match value {
        Value::Null => Ok(None),
        other => text(other).map(Some),
    }
}

pub fn number(value: &Value) -> Result<i64, Failure> {
    match value {
        Value::Int(each) => each.as_i64().ok_or_else(bad),
        _ => Err(bad()),
    }
}

pub fn float(value: &Value) -> Result<f64, Failure> {
    match value {
        Value::Float(each) => Ok(*each),
        Value::Int(each) => each.as_i64().map(|n| n as f64).ok_or_else(bad),
        _ => Err(bad()),
    }
}

pub fn flag(value: &Value) -> Result<bool, Failure> {
    match value {
        Value::Bool(each) => Ok(*each),
        _ => Err(bad()),
    }
}

pub fn list(value: &Value) -> Result<&Vec<Value>, Failure> {
    match value {
        Value::Array(each) => Ok(each),
        _ => Err(bad()),
    }
}

pub fn map(value: &Value) -> Result<&Map, Failure> {
    match value {
        Value::Object(each) => Ok(each),
        _ => Err(bad()),
    }
}

pub fn texts(value: &Value) -> Result<Vec<String>, Failure> {
    list(value)?
        .iter()
        .map(|each| text(each).map(str::to_owned))
        .collect()
}

pub fn arg(args: &[Value], at: usize) -> Result<&Value, Failure> {
    args.get(at).ok_or_else(bad)
}

/// A number as the channel carries it: a JSON number, or a one-key `{"$float": "nan" | "inf" | "-inf"}` object
/// (tests/rustdiff/diffs.py's tagging).
pub fn tagged_float(value: &Value) -> Result<f64, Failure> {
    match value {
        Value::Object(tag) if tag.len() == 1 => match tag.get("$float") {
            Some(Value::Str(word)) => match word.as_str() {
                Some("nan") => Ok(f64::NAN),
                Some("inf") => Ok(f64::INFINITY),
                Some("-inf") => Ok(f64::NEG_INFINITY),
                _ => Err(bad()),
            },
            _ => Err(bad()),
        },
        other => float(other),
    }
}

/// A float as the channel carries it.
pub fn untag(value: f64) -> Value {
    if value.is_nan() {
        car_adv::jsonx::object([("$float", "nan".into())])
    } else if value.is_infinite() {
        car_adv::jsonx::object([("$float", (if value > 0.0 { "inf" } else { "-inf" }).into())])
    } else {
        Value::Float(value)
    }
}
