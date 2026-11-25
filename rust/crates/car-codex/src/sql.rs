//! Codex's databases, opened and read as the reference's `sqlite3` reads them: read-only (`mode=ro` in a file URI,
//! `query_only`), `trusted_schema` off, a 3-second busy timeout, and every cell the Python type SQLite gives it -
//! INTEGER an `int`, REAL a `float`, TEXT a `str` (a text that is not UTF-8 fails the read, as Python's decode does),
//! NULL `None`, a BLOB `bytes`.
//!
//! Nothing here writes. Every statement the reader sends is in `history.rs` and `schema.rs`.

use std::path::Path;
use std::rc::Rc;
use std::time::Duration;

use car_machine::json::{Int, Map, Str, Value};
use rusqlite::types::{ToSqlOutput, ValueRef};
use rusqlite::{Connection, OpenFlags, ToSql};

/// What a column holds, as Python's `sqlite3` gives it.
#[derive(Clone, Debug, PartialEq)]
pub enum Cell {
    Null,
    Int(i64),
    Real(f64),
    Text(String),
    Blob(Vec<u8>),
}

static NULL_CELL: Cell = Cell::Null;

impl Cell {
    /// The cell as a JSON-shaped value. A BLOB is Python's `bytes`, carried as car-store carries it (car-machine's
    /// `pybytes::blob`: a one-key object of its hex, equal only to the same bytes), which no check of the reader ever
    /// accepts as a number, a text, a list or a time. (`skips.kind` and truth read the cell itself: [`Cell::kind`],
    /// [`Cell::truthy`].)
    pub fn value(&self) -> Value {
        match self {
            Cell::Null => Value::Null,
            Cell::Int(number) => Value::Int(Int::from(*number)),
            Cell::Real(number) => Value::Float(*number),
            Cell::Text(text) => Value::from(text.as_str()),
            Cell::Blob(bytes) => car_machine::pybytes::blob(bytes),
        }
    }

    pub fn text(&self) -> Option<&str> {
        match self {
            Cell::Text(text) => Some(text),
            _ => None,
        }
    }

    /// `bool(value)`: a BLOB is `bytes`, true when it holds a byte.
    pub fn truthy(&self) -> bool {
        match self {
            Cell::Blob(bytes) => !bytes.is_empty(),
            other => car_machine::pyval::truthy(&other.value()),
        }
    }

    /// The parameter that binds this cell as Python binds a value read from a column.
    pub fn param(&self) -> Param<'_> {
        match self {
            Cell::Null => Param::Null,
            Cell::Int(number) => Param::Int(*number),
            Cell::Real(number) => Param::Real(*number),
            Cell::Text(text) => Param::Text(text),
            Cell::Blob(bytes) => Param::Blob(bytes),
        }
    }

    /// `skips.kind(value)` of the cell: a kind word safe to print. A BLOB is `bytes`, whose `str()` holds a quote and
    /// so is never a plain word; only a `subagent` in it is told apart.
    pub fn kind(&self) -> String {
        match self {
            Cell::Blob(bytes) => {
                let lowered: Vec<u8> = bytes.iter().map(u8::to_ascii_lowercase).collect();
                if lowered.windows(8).any(|window| window == b"subagent") {
                    "subagent".to_owned()
                } else {
                    "other".to_owned()
                }
            }
            other => car_machine::domain::skips::kind(&other.value()),
        }
    }
}

/// A parameter, bound as Python binds it: `str` as TEXT, `int` as INTEGER, `float` as REAL.
#[derive(Clone, Copy, Debug)]
pub enum Param<'a> {
    Text(&'a str),
    Int(i64),
    Real(f64),
    Blob(&'a [u8]),
    Null,
}

impl ToSql for Param<'_> {
    fn to_sql(&self) -> rusqlite::Result<ToSqlOutput<'_>> {
        Ok(match self {
            Param::Text(text) => ToSqlOutput::from(*text),
            Param::Int(number) => ToSqlOutput::from(*number),
            Param::Real(number) => ToSqlOutput::from(*number),
            Param::Blob(bytes) => ToSqlOutput::from(*bytes),
            Param::Null => ToSqlOutput::from(rusqlite::types::Null),
        })
    }
}

/// One row, `sqlite3.Row`: its columns in order, by name or by position.
#[derive(Clone, Debug)]
pub struct Row {
    names: Rc<Vec<String>>,
    cells: Vec<Cell>,
}

impl Row {
    /// `row[name]` (a name is found whatever its case, as `sqlite3.Row` finds it).
    pub fn get(&self, name: &str) -> &Cell {
        self.names
            .iter()
            .position(|each| each.eq_ignore_ascii_case(name))
            .and_then(|at| self.cells.get(at))
            .unwrap_or(&NULL_CELL)
    }

    /// `row[name]` as a value.
    pub fn value(&self, name: &str) -> Value {
        self.get(name).value()
    }

    /// `row[index]`.
    pub fn at(&self, index: usize) -> &Cell {
        self.cells.get(index).unwrap_or(&NULL_CELL)
    }

    /// `name in row.keys()`.
    pub fn has(&self, name: &str) -> bool {
        self.names
            .iter()
            .any(|each| each.eq_ignore_ascii_case(name))
    }

    /// `dict(row)`.
    pub fn dict(&self) -> Map {
        let mut map = Map::with_capacity(self.names.len());
        for (name, cell) in self.names.iter().zip(&self.cells) {
            map.insert(Str::from(name.as_str()), cell.value());
        }
        map
    }
}

fn cell(value: ValueRef<'_>) -> rusqlite::Result<Cell> {
    Ok(match value {
        ValueRef::Null => Cell::Null,
        ValueRef::Integer(number) => Cell::Int(number),
        ValueRef::Real(number) => Cell::Real(number),
        ValueRef::Text(bytes) => match std::str::from_utf8(bytes) {
            Ok(text) => Cell::Text(text.to_owned()),
            Err(error) => {
                return Err(rusqlite::Error::FromSqlConversionFailure(
                    0,
                    rusqlite::types::Type::Text,
                    Box::new(error),
                ));
            }
        },
        ValueRef::Blob(bytes) => Cell::Blob(bytes.to_vec()),
    })
}

/// `urllib.parse.quote_from_bytes(path)`, its `/` kept: what `Path.as_uri()` makes of the part after the drive.
fn quote(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for byte in text.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-' | b'~' | b'/') {
            out.push(char::from(byte));
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

/// `Path(text).as_uri()` for an absolute Windows path (3.13): `file:///C:/a/b` on a drive, `file://host/share/a` on a
/// share. None for a relative one (a ValueError in Python).
pub fn as_uri(text: &str) -> Option<String> {
    let (drive, root, tail) = car_config::winpath::parse(text);
    if root.is_empty() {
        return None;
    }
    let posix = format!("{}{}", root.replace('\\', "/"), tail.join("/"));
    if drive.len() == 2 && drive.as_bytes().get(1) == Some(&b':') {
        return Some(format!("file:///{drive}{}", quote(&posix)));
    }
    if !drive.is_empty() {
        let whole = format!("{}{}", drive.replace('\\', "/"), posix);
        return Some(format!("file:{}", quote(&whole)));
    }
    Some(format!("file://{}", quote(&posix)))
}

/// `SchemaMixin._connect(path)`: read-only by the URI, `query_only`, `trusted_schema=OFF`, a 3 s timeout.
pub fn connect(path: &Path) -> rusqlite::Result<Connection> {
    let text = path.to_string_lossy();
    let uri = as_uri(&text).ok_or_else(|| rusqlite::Error::InvalidPath(path.to_path_buf()))?;
    // `sqlite3.connect(uri, uri=True)` opens with READWRITE | CREATE; `mode=ro` in the URI is what makes it read-only.
    let connection = Connection::open_with_flags(
        format!("{uri}?mode=ro"),
        OpenFlags::SQLITE_OPEN_READ_WRITE
            | OpenFlags::SQLITE_OPEN_CREATE
            | OpenFlags::SQLITE_OPEN_URI
            | OpenFlags::SQLITE_OPEN_FULL_MUTEX,
    )?;
    connection.busy_timeout(Duration::from_secs(3))?;
    connection.execute_batch("PRAGMA query_only=ON")?;
    connection.execute_batch("PRAGMA trusted_schema=OFF")?;
    Ok(connection)
}

/// Every row of a statement, fetched whole (`fetchall()`).
pub fn query(
    connection: &Connection,
    sql: &str,
    parameters: &[Param<'_>],
) -> rusqlite::Result<Vec<Row>> {
    let mut statement = connection.prepare(sql)?;
    let names = Rc::new(
        statement
            .column_names()
            .map(str::to_owned)
            .collect::<Vec<_>>(),
    );
    let count = names.len();
    let mut rows = statement.query(rusqlite::params_from_iter(parameters.iter()))?;
    let mut found = Vec::new();
    while let Some(row) = rows.next()? {
        let mut cells = Vec::with_capacity(count);
        for index in 0..count {
            cells.push(cell(row.get_ref(index)?)?);
        }
        found.push(Row {
            names: Rc::clone(&names),
            cells,
        });
    }
    Ok(found)
}

/// The first row, `fetchone()`.
pub fn first(
    connection: &Connection,
    sql: &str,
    parameters: &[Param<'_>],
) -> rusqlite::Result<Option<Row>> {
    Ok(query(connection, sql, parameters)?.into_iter().next())
}

/// `{row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)}`: the column names a table has.
pub fn columns(connection: &Connection, table: &str) -> rusqlite::Result<Vec<String>> {
    Ok(
        query(connection, &format!("PRAGMA table_info({table})"), &[])?
            .iter()
            .filter_map(|row| row.at(1).text().map(str::to_owned))
            .collect(),
    )
}

/// `{row[1]: str(row[2] or "").upper()}`: the columns of a table with their declared type, upper-cased.
pub fn column_types(
    connection: &Connection,
    table: &str,
) -> rusqlite::Result<Vec<(String, String)>> {
    Ok(
        query(connection, &format!("PRAGMA table_info({table})"), &[])?
            .iter()
            .filter_map(|row| {
                let name = row.at(1).text()?.to_owned();
                let declared = match row.at(2) {
                    Cell::Text(text) => text.to_uppercase(),
                    _ => String::new(),
                };
                Some((name, declared))
            })
            .collect(),
    )
}
