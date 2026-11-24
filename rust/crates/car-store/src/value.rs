//! Rows as the Python store sees them: a `dict` of column name to `int`, `float`, `str`, `None` (and
//! `bool` for the flags a validated record carries), in the order `SELECT *` gives the columns.
//!
//! The store's rules are written against Python's dynamic values - a REAL column that holds text fails its
//! check, `1 == 1.0`, `x or y` - so a row is car-machine's Python value model, not a typed struct, and the
//! helpers here are Python's own operators on it.

use car_machine::json::{Int, Map, Str, Value};
use rusqlite::types::{ToSqlOutput, ValueRef};
use rusqlite::{Connection, ToSql};

/// One row, or one record: a `dict` in column order.
pub type Row = Map;

/// The key `name` as a row holds it.
pub fn key(name: &str) -> Str {
    Str::new(name)
}

/// `row[name]`, or `None` where the row has no such key (`row.get(name)`).
pub fn get<'a>(row: &'a Row, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    row.get(name).unwrap_or(&NULL)
}

/// `row[name] = value`.
pub fn set(row: &mut Row, name: &str, value: Value) {
    row.insert(key(name), value);
}

/// A `str`'s text, when the value is one (and has no lone surrogate).
pub fn text(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

/// `row[name]` as text, when it is a `str`.
pub fn text_of<'a>(row: &'a Row, name: &str) -> Option<&'a str> {
    text(get(row, name))
}

/// An `int` value.
pub fn int(number: i64) -> Value {
    Value::Int(Int::from(number))
}

/// A `str` value.
pub fn string(text: &str) -> Value {
    Value::Str(Str::new(text))
}

/// `None`, or the text.
pub fn optional(text: Option<&str>) -> Value {
    text.map_or(Value::Null, string)
}

/// `None`, or the float.
pub fn float_or_null(number: Option<f64>) -> Value {
    number.map_or(Value::Null, Value::Float)
}

/// The number a value is, for arithmetic and comparison: an `int` or a `float`, never a `bool` (as
/// `isinstance(v, (int, float)) and not isinstance(v, bool)`). An `int` beyond f64 comes back infinite.
pub fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Int(number) => Some(int_as_f64(number)),
        Value::Float(number) => Some(*number),
        _ => None,
    }
}

/// An `int`'s value as an f64, as Python's `float(n)` - infinite where that would overflow.
pub fn int_as_f64(number: &Int) -> f64 {
    number
        .as_i64()
        .map(|n| n as f64)
        .or_else(|| number.as_u64().map(|n| n as f64))
        .unwrap_or_else(|| number.to_string().parse::<f64>().unwrap_or(f64::INFINITY))
}

/// The number a value is in Python arithmetic, a `bool` counting as 0 or 1 (`True + 1 == 2`).
pub fn arithmetic(value: &Value) -> Option<f64> {
    match value {
        Value::Bool(on) => Some(f64::from(u8::from(*on))),
        other => number(other),
    }
}

/// `value or 0`, as a number (None, 0 and False all give 0).
pub fn or_zero(value: &Value) -> f64 {
    if truthy(value) {
        arithmetic(value).unwrap_or(0.0)
    } else {
        0.0
    }
}

/// Python's truthiness.
pub fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(on) => *on,
        Value::Int(number) => number.as_i64() != Some(0),
        Value::Float(number) => *number != 0.0,
        Value::Str(text) => !text.is_empty(),
        Value::Array(items) => !items.is_empty(),
        Value::Object(map) => !map.is_empty(),
    }
}

/// `a or b`.
pub fn or(first: &Value, second: &Value) -> Value {
    if truthy(first) {
        first.clone()
    } else {
        second.clone()
    }
}

/// Python's `==`: numbers by value whatever their type (`1 == 1.0 == True`), text by its code points,
/// containers member by member.
pub fn py_eq(first: &Value, second: &Value) -> bool {
    match (first, second) {
        (Value::Null, Value::Null) => true,
        (Value::Str(a), Value::Str(b)) => a == b,
        (Value::Int(a), Value::Int(b)) => a == b,
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(x, y)| py_eq(x, y))
        }
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(name, x)| b.get(name).is_some_and(|y| py_eq(x, y)))
        }
        (a, b) => match (arithmetic(a), arithmetic(b)) {
            (Some(x), Some(y)) => x == y,
            _ => false,
        },
    }
}

/// `value in allowed` for a set of words: only a `str` can be in one.
pub fn is_in(value: &Value, allowed: &[&str]) -> bool {
    text(value).is_some_and(|word| allowed.contains(&word))
}

/// A row's value read from SQLite the way Python's sqlite3 reads it: INTEGER `int`, REAL `float`,
/// TEXT `str` (a text that is not UTF-8 fails the read, as Python's decode does), NULL `None`. A BLOB
/// is Python's `bytes`, which no check of the store ever accepts; it is kept as an empty list, which no
/// check accepts either.
pub fn from_sql(value: ValueRef<'_>) -> rusqlite::Result<Value> {
    Ok(match value {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(number) => int(number),
        ValueRef::Real(number) => Value::Float(number),
        ValueRef::Text(bytes) => match std::str::from_utf8(bytes) {
            Ok(text) => string(text),
            Err(error) => {
                return Err(rusqlite::Error::FromSqlConversionFailure(
                    0,
                    rusqlite::types::Type::Text,
                    Box::new(error),
                ));
            }
        },
        ValueRef::Blob(_) => Value::Array(Vec::new()),
    })
}

/// A parameter bound the way Python's sqlite3 binds it: `int` (and `bool`) as INTEGER, `float` as REAL,
/// `str` as TEXT, `None` as NULL. Anything else is refused, as Python refuses an unsupported type.
pub struct Sql<'a>(pub &'a Value);

impl ToSql for Sql<'_> {
    fn to_sql(&self) -> rusqlite::Result<ToSqlOutput<'_>> {
        let unsupported = |what: &str| {
            rusqlite::Error::ToSqlConversionFailure(Box::from(format!(
                "Error binding parameter: type '{what}' is not supported"
            )))
        };
        Ok(match self.0 {
            Value::Null => ToSqlOutput::from(rusqlite::types::Null),
            Value::Bool(on) => ToSqlOutput::from(i64::from(*on)),
            Value::Int(number) => match number.as_i64() {
                Some(number) => ToSqlOutput::from(number),
                None => return Err(unsupported("int too large")),
            },
            Value::Float(number) => ToSqlOutput::from(*number),
            Value::Str(text) => match text.as_str() {
                Some(text) => ToSqlOutput::from(text),
                None => return Err(unsupported("str with a surrogate")),
            },
            Value::Array(_) => return Err(unsupported("list")),
            Value::Object(_) => return Err(unsupported("dict")),
        })
    }
}

/// Run one statement as Python's `connection.execute` does - stepping through whatever rows it gives -
/// and answer how many rows it changed (`cursor.rowcount` of a DML statement).
pub fn execute(connection: &Connection, sql: &str, parameters: &[Value]) -> rusqlite::Result<u64> {
    let mut statement = connection.prepare(sql)?;
    let bound: Vec<Sql<'_>> = parameters.iter().map(Sql).collect();
    let mut rows = statement.query(rusqlite::params_from_iter(bound.iter()))?;
    while rows.next()?.is_some() {}
    Ok(connection.changes())
}

/// Every row of a query, each as a `dict` (`sqlite3.Row` read with `dict(row)`).
pub fn rows(
    connection: &Connection,
    sql: &str,
    parameters: &[Value],
) -> rusqlite::Result<Vec<Row>> {
    let mut statement = connection.prepare(sql)?;
    let names: Vec<String> = statement.column_names().map(str::to_string).collect();
    let bound: Vec<Sql<'_>> = parameters.iter().map(Sql).collect();
    let mut rows = statement.query(rusqlite::params_from_iter(bound.iter()))?;
    let mut found = Vec::new();
    while let Some(row) = rows.next()? {
        let mut map = Row::with_capacity(names.len());
        for (index, name) in names.iter().enumerate() {
            map.insert(key(name), from_sql(row.get_ref(index)?)?);
        }
        found.push(map);
    }
    Ok(found)
}

/// Every row of a query as its values in column order (a plain tuple row).
pub fn tuples(
    connection: &Connection,
    sql: &str,
    parameters: &[Value],
) -> rusqlite::Result<Vec<Vec<Value>>> {
    let mut statement = connection.prepare(sql)?;
    let count = statement.column_count();
    let bound: Vec<Sql<'_>> = parameters.iter().map(Sql).collect();
    let mut rows = statement.query(rusqlite::params_from_iter(bound.iter()))?;
    let mut found = Vec::new();
    while let Some(row) = rows.next()? {
        let mut values = Vec::with_capacity(count);
        for index in 0..count {
            values.push(from_sql(row.get_ref(index)?)?);
        }
        found.push(values);
    }
    Ok(found)
}

/// The first row's values, or None (`fetchone()`).
pub fn first(
    connection: &Connection,
    sql: &str,
    parameters: &[Value],
) -> rusqlite::Result<Option<Vec<Value>>> {
    Ok(tuples(connection, sql, parameters)?.into_iter().next())
}

/// The first column of the first row (`fetchone()[0]`); None where there is no row.
pub fn scalar(connection: &Connection, sql: &str, parameters: &[Value]) -> rusqlite::Result<Value> {
    Ok(first(connection, sql, parameters)?
        .and_then(|row| row.into_iter().next())
        .unwrap_or(Value::Null))
}

/// A whole number read back from SQLite (a PRAGMA's answer, a count).
pub fn integer(connection: &Connection, sql: &str, parameters: &[Value]) -> rusqlite::Result<i64> {
    Ok(match scalar(connection, sql, parameters)? {
        Value::Int(number) => number.as_i64().unwrap_or(0),
        Value::Float(number) => number as i64,
        _ => 0,
    })
}

/// "?,?,?" for `count` parameters.
pub fn marks(count: usize) -> String {
    vec!["?"; count].join(",")
}

/// A list of words as parameters, sorted as Python's `tuple(sorted(...))` gives them.
pub fn words(list: &[&str]) -> Vec<Value> {
    let mut sorted: Vec<&str> = list.to_vec();
    sorted.sort_unstable();
    sorted.into_iter().map(string).collect()
}

/// The words of `all` that are not in `but`, sorted (`sorted(A - B)`).
pub fn words_but(all: &[&str], but: &[&str]) -> Vec<Value> {
    let kept: Vec<&str> = all
        .iter()
        .copied()
        .filter(|word| !but.contains(word))
        .collect();
    words(&kept)
}
