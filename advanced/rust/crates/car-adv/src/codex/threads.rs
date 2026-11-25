//! `codex/threads.py`: a person's own conversations and their names, read-only, for the Dashboard's Find a conversation
//! alone (seat S7.2c). One statement per ordering; a conversation with no name is left out. Rows are read one at a time,
//! as the reference's cursor reads them, so a row past the limit is never read.

use std::collections::BTreeSet;

use car_codex::eligibility::{ThreadRow, row_problem};
use car_codex::sql::{self, Cell};
use car_machine::domain::ids;
use car_machine::json::Value;
use rusqlite::types::ValueRef;

use super::turns::{Failure, Read, SharedOs, connect, unavailable};

pub const THREAD_COLUMNS: &[&str] = &[
    "id",
    "name",
    "source",
    "thread_source",
    "archived",
    "history_mode",
];
const SELECT: &str = "SELECT id, name, source, thread_source, archived, history_mode FROM threads WHERE archived=0 ORDER BY ";
pub const SCAN: usize = 5000;

/// The five orderings, newest first by the column Codex keeps its last change in, else by the order written.
pub fn statements() -> [String; 5] {
    [
        format!("{SELECT}updated_at_ms DESC, rowid DESC"),
        format!("{SELECT}updated_at DESC, rowid DESC"),
        format!("{SELECT}created_at_ms DESC, rowid DESC"),
        format!("{SELECT}created_at DESC, rowid DESC"),
        format!("{SELECT}rowid DESC"),
    ]
}

/// A cell as Python's `sqlite3` gives it; a text that is not UTF-8 fails the fetch.
pub fn cell_of(value: ValueRef<'_>) -> rusqlite::Result<Cell> {
    Ok(match value {
        ValueRef::Null => Cell::Null,
        ValueRef::Integer(number) => Cell::Int(number),
        ValueRef::Real(number) => Cell::Real(number),
        ValueRef::Text(bytes) => Cell::Text(String::from_utf8(bytes.to_vec()).map_err(|_| {
            rusqlite::Error::InvalidColumnType(0, "text".into(), rusqlite::types::Type::Text)
        })?),
        ValueRef::Blob(bytes) => Cell::Blob(bytes.to_vec()),
    })
}

/// The conversations of the Codex home `home`, as Find a conversation reads them.
pub struct Threads {
    pub home: String,
    pub os: SharedOs,
}

impl Threads {
    /// `own(limit, skip)`: the person's own conversations, newest first, none in `skip` and at most `limit`.
    pub fn own(&self, limit: i64, skip: &BTreeSet<String>) -> Read<Vec<(String, String)>> {
        let connection = connect(
            self.os.as_ref(),
            &self.home,
            "state",
            &[("threads", THREAD_COLUMNS)],
        )?;
        let failed = |_| unavailable("the conversations cannot be read");
        let columns = sql::columns(&connection, "threads").map_err(failed)?;
        let has = |name: &str| columns.iter().any(|each| each == name);
        let statements = statements();
        let statement = if has("updated_at_ms") {
            &statements[0]
        } else if has("updated_at") {
            &statements[1]
        } else if has("created_at_ms") {
            &statements[2]
        } else if has("created_at") {
            &statements[3]
        } else {
            &statements[4]
        };
        let mut prepared = connection.prepare(statement).map_err(failed)?;
        let mut rows = prepared.query([]).map_err(failed)?;
        let mut found = Vec::new();
        let empty = BTreeSet::new();
        let mut number = 0usize;
        while let Some(row) = rows.next().map_err(failed)? {
            let cells: Vec<Cell> = (0..6)
                .map(|index| row.get_ref(index).and_then(cell_of))
                .collect::<rusqlite::Result<_>>()
                .map_err(failed)?;
            if number >= SCAN || found.len() as i64 >= limit {
                break;
            }
            number += 1;
            let thread = cells[0].value();
            let name = car_codex::labels::label(&cells[1].value());
            let Some(name) = name else { continue };
            if !ids::is_uuid(&thread) {
                continue;
            }
            let thread = match &thread {
                Value::Str(text) => text.as_str().unwrap_or("").to_owned(),
                _ => continue,
            };
            if skip.contains(&thread) {
                continue;
            }
            let shaped = ThreadRow {
                source: &cells[2],
                archived: &cells[4],
                thread_source: &cells[3],
                history_mode: &cells[5],
            };
            let problem =
                row_problem(&shaped, &empty, &empty, false).map_err(|class| match class {
                    "ValueError" => unavailable("the conversations cannot be read"),
                    other => Failure::Raised(other),
                })?;
            if problem.is_some() {
                continue;
            }
            found.push((thread, name));
        }
        Ok(found)
    }
}
