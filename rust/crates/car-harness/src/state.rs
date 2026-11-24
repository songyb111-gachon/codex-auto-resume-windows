//! One read of a state.sqlite with rusqlite (bundled, D4): S0.4's state-fixture proof.
//!
//! TO BE REPLACED by car-store (S1.2). Opened read only, so the harness never changes a fixture the
//! reference wrote; no migration, no schema check, no mark - the reference's store does those.

use std::path::Path;

use rusqlite::{Connection, OpenFlags, OptionalExtension};

/// The `state` column of one interruption record, None when there is no such record.
pub fn record_state(home: &Path, interruption_id: &str) -> rusqlite::Result<Option<String>> {
    let connection =
        Connection::open_with_flags(home.join("state.sqlite"), OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    connection
        .query_row(
            "SELECT state FROM interruptions WHERE interruption_id = ?1",
            [interruption_id],
            |row| row.get(0),
        )
        .optional()
}

/// `PRAGMA user_version` of the state, the schema the reference's `Store.schema_version()` answers.
pub fn schema_version(home: &Path) -> rusqlite::Result<i64> {
    let connection =
        Connection::open_with_flags(home.join("state.sqlite"), OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    connection.query_row("PRAGMA user_version", [], |row| row.get(0))
}

/// The bundled SQLite's version, recorded with every run (D4 pins it at or above the bundled Python's).
pub fn sqlite_version() -> &'static str {
    rusqlite::version()
}
