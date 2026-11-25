//! What every op reads its arguments with.

use car_machine::json::{Map, Value};

/// An op's refusal: the class name the reference's exception has.
#[derive(Debug)]
pub struct Failure {
    pub class: String,
}

impl Failure {
    pub fn new(class: &str) -> Failure {
        Failure {
            class: class.to_owned(),
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

#[allow(dead_code)]
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
