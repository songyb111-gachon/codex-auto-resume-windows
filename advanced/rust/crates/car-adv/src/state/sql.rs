//! SQLite as the reference's `sqlite3` uses it: statements stepped to the end, rows as `dict(row)` in column
//! order, values as Python reads and binds them.
//!
//! Reading is car-store's (`car_store::value`): INTEGER an `int`, REAL a `float`, TEXT a `str`, NULL `None`, a BLOB
//! a value no check accepts. Binding is too, after the one check Python makes before SQLite sees a value: an `int`
//! too large for 64 bits is Python's `OverflowError` and a `str` with half a surrogate pair its
//! `UnicodeEncodeError` - neither is an `sqlite3.Error`, so neither becomes the transaction's sentence - while a
//! list or a dict is sqlite3's `ProgrammingError`, which is.

use car_machine::json::Value;
use rusqlite::Connection;

use super::errors::{Error, Result};

pub use car_store::value::{Row, get, int, key, py_eq, string, truthy};

/// The checks Python's sqlite3 makes on a parameter before binding it, in order.
fn checked(parameters: &[Value]) -> Result<()> {
    for value in parameters {
        match value {
            Value::Int(number) if number.as_i64().is_none() => {
                return Err(Error::python(
                    "OverflowError",
                    "Python int too large to convert to SQLite INTEGER",
                ));
            }
            Value::Str(text) if text.has_surrogate() => {
                return Err(Error::python(
                    "UnicodeEncodeError",
                    "'utf-8' codec can't encode character: surrogates not allowed",
                ));
            }
            _ => {}
        }
    }
    Ok(())
}

/// `connection.execute(sql, parameters).rowcount`.
pub fn exec(connection: &Connection, sql: &str, parameters: &[Value]) -> Result<u64> {
    checked(parameters)?;
    Ok(car_store::value::execute(connection, sql, parameters)?)
}

/// `connection.execute(sql, parameters).lastrowid` of an INSERT.
pub fn insert(connection: &Connection, sql: &str, parameters: &[Value]) -> Result<i64> {
    exec(connection, sql, parameters)?;
    Ok(connection.last_insert_rowid())
}

/// `[dict(row) for row in connection.execute(sql, parameters)]`.
pub fn all(connection: &Connection, sql: &str, parameters: &[Value]) -> Result<Vec<Row>> {
    checked(parameters)?;
    Ok(car_store::value::rows(connection, sql, parameters)?)
}

/// `connection.execute(sql, parameters).fetchone()` as a dict, or None.
pub fn one(connection: &Connection, sql: &str, parameters: &[Value]) -> Result<Option<Row>> {
    Ok(all(connection, sql, parameters)?.into_iter().next())
}

/// Every row as its values in column order (a tuple row).
pub fn tuples(connection: &Connection, sql: &str, parameters: &[Value]) -> Result<Vec<Vec<Value>>> {
    checked(parameters)?;
    Ok(car_store::value::tuples(connection, sql, parameters)?)
}

/// `fetchone()` as a tuple, or None.
pub fn first(
    connection: &Connection,
    sql: &str,
    parameters: &[Value],
) -> Result<Option<Vec<Value>>> {
    Ok(tuples(connection, sql, parameters)?.into_iter().next())
}

/// `fetchone()[0]`, `None` where there is no row.
pub fn scalar(connection: &Connection, sql: &str, parameters: &[Value]) -> Result<Value> {
    Ok(first(connection, sql, parameters)?
        .and_then(|row| row.into_iter().next())
        .unwrap_or(Value::Null))
}

/// `fetchone()[0]` of a count or a PRAGMA: a whole number.
pub fn number(connection: &Connection, sql: &str, parameters: &[Value]) -> Result<i64> {
    Ok(match scalar(connection, sql, parameters)? {
        Value::Int(number) => number.as_i64().unwrap_or(0),
        Value::Float(number) => number as i64,
        _ => 0,
    })
}

/// Whether the query gives a row (`fetchone() is not None`).
pub fn exists(connection: &Connection, sql: &str, parameters: &[Value]) -> Result<bool> {
    Ok(first(connection, sql, parameters)?.is_some())
}

/// "?, ?, ?" for `count` parameters (`", ".join("?" for _ in ...)`).
pub fn marks(count: usize) -> String {
    vec!["?"; count].join(", ")
}

/// "?,?,?" (`",".join("?" ...)`).
pub fn tight_marks(count: usize) -> String {
    vec!["?"; count].join(",")
}

/// Words as parameters.
pub fn words(list: &[&str]) -> Vec<Value> {
    list.iter().map(|word| string(word)).collect()
}

/// A float parameter.
pub fn float(number: f64) -> Value {
    Value::Float(number)
}

/// A row read as the store returns it, by its column `name` (`row[name]`); a missing column is Python's KeyError.
pub fn column<'a>(row: &'a Row, name: &str) -> Result<&'a Value> {
    row.get(name)
        .ok_or_else(|| Error::python("IndexError", "No item with that key"))
}
