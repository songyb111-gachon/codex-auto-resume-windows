//! `codex/errors.py`: the one refusal the reader makes, and the other things that can leave one of its calls.
//!
//! A Python call of the reference either answers, or raises `SourceError` (a safe sentence, never a database's
//! contents), or lets another exception through - an `OSError` of a file nobody caught, an `OverflowError` of a
//! number too large for a float, a `TypeError` of a value of the wrong kind. [`Error`] is those three, so a caller
//! (and the differential harness, which compares the exception's class) sees what Python would have raised.

use std::fmt;

/// Safe diagnostic: never includes database contents or an underlying error.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceError(pub String);

impl SourceError {
    pub fn new(message: &str) -> SourceError {
        SourceError(message.to_owned())
    }

    /// The refusal a failed read of Codex's own files gives.
    pub fn unavailable() -> SourceError {
        SourceError::new("Codex local state unavailable or unsupported")
    }
}

impl fmt::Display for SourceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for SourceError {}

/// What leaves a call of the reader.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    /// `SourceError`.
    Source(SourceError),
    /// An `OSError` (any of its subclasses) that nothing in the reference caught.
    Os,
    /// Another Python exception, by class name (`OverflowError`, `TypeError`, `IndexError`, ...).
    Python(&'static str),
    /// An `sqlite3.Error` (any of its subclasses). Inside a statement's scope it is turned into [`SourceError`] as
    /// the reference's `_db` does; where a call catches it itself, it never leaves.
    Sqlite,
}

impl Error {
    pub fn source(message: &str) -> Error {
        Error::Source(SourceError::new(message))
    }

    pub fn unavailable() -> Error {
        Error::Source(SourceError::unavailable())
    }

    /// The exception's class name, as the reference's `type(error).__name__` (an OSError subclass is `OSError`).
    pub fn class(&self) -> &'static str {
        match self {
            Error::Source(_) => "SourceError",
            Error::Os => "OSError",
            Error::Python(class) => class,
            Error::Sqlite => "Error",
        }
    }

    /// The sentence a `SourceError` carries; the others carry none that matters.
    pub fn message(&self) -> String {
        match self {
            Error::Source(refused) => refused.0.clone(),
            other => other.class().to_owned(),
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message())
    }
}

impl std::error::Error for Error {}

impl From<SourceError> for Error {
    fn from(refused: SourceError) -> Error {
        Error::Source(refused)
    }
}

impl From<rusqlite::Error> for Error {
    fn from(_error: rusqlite::Error) -> Error {
        Error::Sqlite
    }
}

impl From<std::io::Error> for Error {
    fn from(_error: std::io::Error) -> Error {
        Error::Os
    }
}

impl From<&'static str> for Error {
    fn from(class: &'static str) -> Error {
        Error::Python(class)
    }
}

pub type Result<T> = std::result::Result<T, Error>;
