//! Small builders for the JSON values this crate's answers are made of (car-machine's `Value`: keys keep the order they
//! were inserted in, as a Python `dict` keeps them; `to_string` writes them as `json.dumps(ensure_ascii=False)`).

use car_machine::json::{Int, Map, Str, Value};

/// An object whose keys keep the order given.
pub fn object<I: IntoIterator<Item = (&'static str, Value)>>(pairs: I) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

/// A text.
pub fn text(value: &str) -> Value {
    Value::from(value)
}

/// A list of texts.
pub fn texts<S: AsRef<str>>(values: &[S]) -> Value {
    Value::Array(values.iter().map(|each| text(each.as_ref())).collect())
}

/// An integer.
pub fn int(value: i64) -> Value {
    Value::Int(Int::from(value))
}

/// `None` as null, or the text.
pub fn maybe_text(value: Option<&str>) -> Value {
    value.map_or(Value::Null, text)
}

/// `None` as null, or the integer.
pub fn maybe_int(value: Option<i64>) -> Value {
    value.map_or(Value::Null, int)
}
