//! The claim's ledger (P11): the edition's plug asked inside a claim, and what it may do there (`store/ledger.py`
//! `_ledger_holds`, `_ledger_authorizer`, `_attachable`, `_same_file`, `_LedgerConnection`; seat S7.2a2).
//!
//! A claim asks the plug's ledger last, once every check of core's has granted it, on the claim's own connection and
//! inside its transaction - so what the ledger counts is counted under the same lock as core's rows. It is asked under
//! a savepoint that takes back whatever it wrote if it holds the claim (or its hook raised), through a handle that can
//! `execute` and nothing else (and, for a plug built over the same SQLite, the raw `sqlite3*`, under the same
//! authorizer), and under an authorizer that keeps core's schemas and the claim's transaction out of its reach. The
//! standard edition's plug is never asked, so none of this runs there.

use std::ffi::{CStr, c_char, c_int, c_void};
use std::path::Path;

use car_machine::json::Value;
use car_machine::winpath;
use car_policy::plug::{Alternative, Answer, Guarded, Ledger, Point, ReadFailed};
use rusqlite::{Connection, ffi};

use crate::errors::Result;
use crate::session::Links;
use crate::value::{execute, tuples};

/// The tables a ledger may not read in core's schemas (`columns._UNREAD_BY_DISPATCH`): a needs-you notice decides no
/// claim.
const UNREAD_BY_DISPATCH: &[&str] = &["notices"];
/// Read with no argument, which would set them.
const LEDGER_PRAGMAS: &[&str] = &[
    "database_list",
    "user_version",
    "schema_version",
    "data_version",
    "application_id",
];
/// Read with one argument naming the table or index they read.
const LEDGER_NAMED_PRAGMAS: &[&str] = &[
    "table_info",
    "table_xinfo",
    "index_list",
    "index_info",
    "index_xinfo",
    "foreign_key_list",
];

/// What the authorizer is handed: every file the claim's connection has attached (main's first, one an ATTACH lets on
/// added) and the store's probe of a file's identity.
struct Judge<'a> {
    attached: Vec<String>,
    links: &'a dyn Links,
}

fn text<'a>(found: *const c_char) -> Option<&'a str> {
    if found.is_null() {
        return None;
    }
    // SAFETY: SQLite hands NUL-terminated UTF-8 that lives for the callback.
    unsafe { CStr::from_ptr(found) }.to_str().ok()
}

/// `_ledger_authorizer(attached)(action, first, second, schema, trigger)`.
fn authorize(
    judge: &mut Judge<'_>,
    action: c_int,
    first: Option<&str>,
    second: Option<&str>,
    schema: Option<&str>,
) -> c_int {
    let core = matches!(schema, None | Some("main") | Some("temp"));
    if action == ffi::SQLITE_READ
        && core
        && first.is_some_and(|table| UNREAD_BY_DISPATCH.contains(&table))
    {
        return ffi::SQLITE_DENY;
    }
    if matches!(
        action,
        ffi::SQLITE_SELECT | ffi::SQLITE_READ | ffi::SQLITE_FUNCTION | ffi::SQLITE_RECURSIVE
    ) {
        return ffi::SQLITE_OK;
    }
    if action == ffi::SQLITE_ATTACH {
        let Some(name) = first.filter(|name| attachable(name, &judge.attached, judge.links)) else {
            return ffi::SQLITE_DENY;
        };
        judge.attached.push(name.to_owned());
        return ffi::SQLITE_OK;
    }
    if action == ffi::SQLITE_PRAGMA {
        let read = first.is_some_and(|name| {
            LEDGER_NAMED_PRAGMAS.contains(&name)
                || (LEDGER_PRAGMAS.contains(&name) && second.is_none())
        });
        return if read {
            ffi::SQLITE_OK
        } else {
            ffi::SQLITE_DENY
        };
    }
    if matches!(
        action,
        ffi::SQLITE_TRANSACTION | ffi::SQLITE_SAVEPOINT | ffi::SQLITE_DETACH
    ) {
        return ffi::SQLITE_DENY;
    }
    if core {
        ffi::SQLITE_DENY
    } else {
        ffi::SQLITE_OK
    }
}

unsafe extern "C" fn authorizer(
    data: *mut c_void,
    action: c_int,
    first: *const c_char,
    second: *const c_char,
    schema: *const c_char,
    _trigger: *const c_char,
) -> c_int {
    // A panic must not cross into SQLite: one is a refusal (D15).
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        // SAFETY: `data` is the `Judge` `ledger_holds` keeps alive while the authorizer is set.
        let judge = unsafe { &mut *data.cast::<Judge<'_>>() };
        authorize(judge, action, text(first), text(second), text(schema))
    }))
    .unwrap_or(ffi::SQLITE_DENY)
}

/// `_attachable(name, attached)`: a file not attached already under any spelling, a link or another path to it
/// included, or a database of its own with no file. A bound or computed name reaches this as None (refused upstream).
fn attachable(name: &str, attached: &[String], links: &dyn Links) -> bool {
    let head: String = name.chars().take(5).collect();
    if head.to_lowercase() == "file:" {
        return false;
    }
    if name.is_empty() || name == ":memory:" {
        return true;
    }
    !attached.iter().any(|other| same_file(name, other, links))
}

/// `_same_file(first, second)`: `os.path.samefile`, or where either cannot be stat'ed the paths compared as
/// `normcase(abspath(...))`.
fn same_file(first: &str, second: &str, links: &dyn Links) -> bool {
    match (
        links.file_identity(Path::new(first)),
        links.file_identity(Path::new(second)),
    ) {
        (Some(one), Some(other)) => one == other,
        _ => normcase(&abspath(first)) == normcase(&abspath(second)),
    }
}

/// `os.path.abspath(path)` on Windows.
fn abspath(path: &str) -> String {
    if winpath::isabs(path) {
        return winpath::normpath(path);
    }
    let cwd = std::env::current_dir()
        .map(|found| found.to_string_lossy().into_owned())
        .unwrap_or_default();
    winpath::normpath(&winpath::join(&cwd, path))
}

/// `os.path.normcase(path)` on Windows: `/` as `\`, lower case.
fn normcase(path: &str) -> String {
    path.replace('/', "\\").to_lowercase()
}

/// `_LedgerConnection`: the claim's connection as a ledger is handed it - `execute`, rows read out whole, and nothing
/// once the ledger has answered (`ProgrammingError`, "the claim this connection was handed for is over").
struct Handle<'a> {
    live: Option<&'a Connection>,
}

impl Ledger for Handle<'_> {
    fn execute(
        &mut self,
        statement: &str,
        parameters: &[Value],
    ) -> std::result::Result<Vec<Vec<Value>>, ReadFailed> {
        let Some(connection) = self.live else {
            return Err(ReadFailed("ProgrammingError"));
        };
        tuples(connection, statement, parameters).map_err(|error| ReadFailed(sqlite_class(&error)))
    }

    fn sqlite(&mut self) -> Option<*mut c_void> {
        // SAFETY: the handle is the claim's own connection, valid for this call, under the authorizer.
        self.live
            .map(|connection| unsafe { connection.handle() }.cast::<c_void>())
    }
}

/// The class of the `sqlite3` exception a failed statement raises.
fn sqlite_class(error: &rusqlite::Error) -> &'static str {
    match error {
        rusqlite::Error::SqliteFailure(failure, _)
            if failure.code == rusqlite::ErrorCode::ConstraintViolation =>
        {
            "IntegrityError"
        }
        rusqlite::Error::SqliteFailure(failure, _)
            if failure.code == rusqlite::ErrorCode::TooBig =>
        {
            "DataError"
        }
        rusqlite::Error::InvalidParameterCount(..) | rusqlite::Error::MultipleStatement => {
            "ProgrammingError"
        }
        _ => "OperationalError",
    }
}

/// `_ledger_holds(connection, ledger, row, now, carried)`: whether the plug's ledger holds a claim every check of
/// core's has granted. HOLD, or a hook that raised on a claim that carried an answer of the plug's, holds it; a hold
/// or a raise takes back what the ledger wrote.
pub(crate) fn ledger_holds(
    connection: &Connection,
    ledger: &Guarded,
    links: &dyn Links,
    row: &Value,
    now: f64,
    carried: &[Point],
) -> Result<bool> {
    execute(connection, "SAVEPOINT claim_ledger", &[])?;
    let attached: Vec<String> = tuples(connection, "PRAGMA database_list", &[])?
        .into_iter()
        .filter_map(|listed| match listed.get(2) {
            Some(Value::Str(file)) if !file.is_empty() => file.as_str().map(str::to_owned),
            _ => None,
        })
        .collect();
    let mut judge = Judge { attached, links };
    // SAFETY: the connection is open; `judge` outlives the authorizer, which is taken off below before it is dropped.
    unsafe {
        ffi::sqlite3_set_authorizer(
            connection.handle(),
            Some(authorizer),
            (&raw mut judge).cast::<c_void>(),
        );
    }
    let (answer, broke) = {
        let mut handle = Handle {
            live: Some(connection),
        };
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            ledger.claim_ledger_checked(&mut handle, row, now, carried)
        }))
    }
    .unwrap_or((Answer::Defer, true));
    // SAFETY: as above; no authorizer from here.
    unsafe {
        ffi::sqlite3_set_authorizer(connection.handle(), None, std::ptr::null_mut());
    }
    drop(judge);
    let held = matches!(answer, Answer::Is(Alternative::Hold)) || (broke && !carried.is_empty());
    if held || broke {
        execute(connection, "ROLLBACK TO claim_ledger", &[])?;
    }
    execute(connection, "RELEASE claim_ledger", &[])?;
    Ok(held)
}
