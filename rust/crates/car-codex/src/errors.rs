//! `codex/errors.py`: the one refusal the reader makes, the one case of it that is no failure yet (`HistoryNotYet`,
//! v0.6.26 final), and the other things that can leave one of its calls.
//!
//! A Python call of the reference either answers, or raises `SourceError` (a safe sentence, never a database's
//! contents), or lets another exception through - an `OSError` of a file nobody caught, an `OverflowError` of a
//! number too large for a float, a `TypeError` of a value of the wrong kind. [`Error`] is those three, so a caller
//! (and the differential harness, which compares the exception's class) sees what Python would have raised.

use std::fmt;

/// Safe diagnostic: never includes database contents or an underlying error.
///
/// `.1` is true for its one subclass, `HistoryNotYet` (v0.6.26 final): no history database yet in a home whose newest
/// state database holds no conversation - Codex makes it with the first conversation it saves, so a fresh home has
/// nothing to read yet, not a history that cannot be read. It is still a `SourceError`: everything that catches the
/// refusal (`Error::Source`) catches it too, as `except SourceError` does in the reference; only its class name, and the
/// callers that ask [`SourceError::is_history_not_yet`], tell it apart.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceError(pub String, pub bool);

impl SourceError {
    pub fn new(message: &str) -> SourceError {
        SourceError(message.to_owned(), false)
    }

    /// `HistoryNotYet("No Codex history database yet")`, the one place the reference raises it (`schema.py` `resolve`).
    pub fn history_not_yet() -> SourceError {
        SourceError("No Codex history database yet".to_owned(), true)
    }

    /// Whether this is `HistoryNotYet` (`except HistoryNotYet:`).
    pub fn is_history_not_yet(&self) -> bool {
        self.1
    }

    /// The exception's class name: `HistoryNotYet` for the subclass, `SourceError` otherwise.
    pub fn class(&self) -> &'static str {
        if self.1 {
            "HistoryNotYet"
        } else {
            "SourceError"
        }
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
    /// `AdapterError(code)` (`domain/errors.py`): the platform's and the app server's refusals, a reason code only.
    Adapter(&'static str),
}

impl Error {
    pub fn source(message: &str) -> Error {
        Error::Source(SourceError::new(message))
    }

    pub fn unavailable() -> Error {
        Error::Source(SourceError::unavailable())
    }

    /// `HistoryNotYet` (a `SourceError`).
    pub fn history_not_yet() -> Error {
        Error::Source(SourceError::history_not_yet())
    }

    /// Whether this is `HistoryNotYet` (`except HistoryNotYet:`): every other refusal, and every other error, is not.
    pub fn is_history_not_yet(&self) -> bool {
        matches!(self, Error::Source(refused) if refused.is_history_not_yet())
    }

    /// The exception's class name, as the reference's `type(error).__name__` (an OSError subclass is `OSError`;
    /// `HistoryNotYet` is its own name).
    pub fn class(&self) -> &'static str {
        match self {
            Error::Source(refused) => refused.class(),
            Error::Os => "OSError",
            Error::Python(class) => class,
            Error::Sqlite => "Error",
            Error::Adapter(_) => "AdapterError",
        }
    }

    /// The sentence a `SourceError` carries; the others carry none that matters.
    pub fn message(&self) -> String {
        match self {
            Error::Source(refused) => refused.0.clone(),
            Error::Adapter(code) => (*code).to_owned(),
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

impl From<car_machine::domain::errors::AdapterError> for Error {
    fn from(refused: car_machine::domain::errors::AdapterError) -> Error {
        Error::Adapter(refused.0)
    }
}

impl From<&'static str> for Error {
    fn from(class: &'static str) -> Error {
        Error::Python(class)
    }
}

pub type Result<T> = std::result::Result<T, Error>;
