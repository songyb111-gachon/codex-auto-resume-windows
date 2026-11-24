//! What the store refuses with (store/errors.py).
//!
//! Four, and each is a different answer: the state is unreadable, it belongs to a newer release, an
//! older one still owns it, or a row is not shaped the way this release writes rows. Python raises each
//! as its own class, all four `StoreError`s; the control layer maps them to its error codes, so the class
//! is kept here as a [`Kind`], with the message word for word.
//!
//! Beside them, the few Python exceptions the store lets through unwrapped - a `ValueError` for an
//! argument outside a closed list, an `OverflowError` for an `int` too large to be a time - as
//! [`Error::Python`], named by their class.

use std::fmt;

/// Which of the four `StoreError` classes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    /// `StoreError`: invalid or unavailable local state; automatic resumes must stop.
    Store,
    /// `UpgradePending`: the state is an older schema and this caller may not migrate it.
    UpgradePending,
    /// `StateFromNewerVersion`: written by a newer version. Never a corruption.
    StateFromNewerVersion,
    /// `RecordSchemaMismatch`: a row has columns this version never wrote.
    RecordSchemaMismatch,
}

impl Kind {
    /// The Python class name.
    pub fn class(self) -> &'static str {
        match self {
            Kind::Store => "StoreError",
            Kind::UpgradePending => "UpgradePending",
            Kind::StateFromNewerVersion => "StateFromNewerVersion",
            Kind::RecordSchemaMismatch => "RecordSchemaMismatch",
        }
    }
}

/// A refusal of the store, or SQLite's own error before the transaction that met it named it.
#[derive(Debug)]
pub enum Error {
    /// One of the four store errors, with its message.
    Store(Kind, String),
    /// A Python exception the store does not wrap: its class name and message.
    Python(&'static str, String),
    /// SQLite's error, inside the store only: every way out turns it into a `StoreError` with the
    /// sentence Python's store gives at that place.
    Sqlite(rusqlite::Error),
}

impl Error {
    /// `StoreError(message)`.
    pub fn store(message: impl Into<String>) -> Error {
        Error::Store(Kind::Store, message.into())
    }

    /// The Python class name the reference raises for this.
    pub fn class(&self) -> &'static str {
        match self {
            Error::Store(kind, _) => kind.class(),
            Error::Python(class, _) => class,
            Error::Sqlite(_) => "OperationalError",
        }
    }

    /// `str(exc)`.
    pub fn message(&self) -> String {
        match self {
            Error::Store(_, message) | Error::Python(_, message) => message.clone(),
            Error::Sqlite(error) => error.to_string(),
        }
    }

    /// Whether this is one of the store's own errors (`isinstance(exc, StoreError)`).
    pub fn is_store(&self) -> bool {
        matches!(self, Error::Store(..))
    }

    /// The kind, for a store error.
    pub fn kind(&self) -> Option<Kind> {
        match self {
            Error::Store(kind, _) => Some(*kind),
            _ => None,
        }
    }

    /// Whether SQLite refused it as a constraint (`sqlite3.IntegrityError`).
    pub fn is_integrity(&self) -> bool {
        matches!(self, Error::Sqlite(rusqlite::Error::SqliteFailure(failure, _))
            if failure.code == rusqlite::ErrorCode::ConstraintViolation)
    }
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.class(), self.message())
    }
}

impl std::error::Error for Error {}

impl From<rusqlite::Error> for Error {
    fn from(error: rusqlite::Error) -> Error {
        Error::Sqlite(error)
    }
}

/// The store's result.
pub type Result<T> = std::result::Result<T, Error>;
