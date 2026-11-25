//! What the advanced state refuses with (`state/session.py`'s `StateError`, `StaleGeneration`; `state/choices.py`'s
//! `Refused`; `state/steers.py`'s `SteerRefused`), and the Python exceptions it lets through unwrapped.
//!
//! Every refusal is a `StateError`: a static sentence, never a path or a value. The subclasses are kept as the
//! class name the reference raises, with the closed word a `Refused` carries (`refusal`) or a `SteerRefused` names
//! (`reason`). SQLite's own error is kept inside the state only: every way out of a transaction turns it into
//! `StateError("advanced state transaction failed")`, of an opening into `StateError("cannot open the advanced
//! state")`, as the reference does; on core's connection (the claim's) it goes out as the class Python's sqlite3
//! raises.

use std::fmt;

/// A refusal of the advanced state, a Python exception it does not wrap, or SQLite's error before a transaction
/// named it.
#[derive(Debug)]
pub enum Error {
    /// `StateError` or one of its subclasses: the class, the sentence, and the closed word a `Refused`
    /// (`refusal`) or `SteerRefused` (`reason`) carries.
    State {
        class: &'static str,
        message: String,
        word: Option<String>,
    },
    /// A Python exception the state does not wrap: its class and message (`TypeError`, `KeyError`,
    /// `OverflowError`, `UnicodeEncodeError`, core's `ConfigError` ...).
    Python(&'static str, String),
    /// SQLite's error, on its way to the sentence of the place that met it.
    Sqlite(rusqlite::Error),
}

impl Error {
    /// `StateError(message)`.
    pub fn state(message: impl Into<String>) -> Error {
        Error::State {
            class: "StateError",
            message: message.into(),
            word: None,
        }
    }

    /// `StaleGeneration("stale generation")`.
    pub fn stale() -> Error {
        Error::State {
            class: "StaleGeneration",
            message: "stale generation".into(),
            word: None,
        }
    }

    /// `Refused(refusal)`: its message is "refused", its word the refusal.
    pub fn refused(refusal: &str) -> Error {
        Error::State {
            class: "Refused",
            message: "refused".into(),
            word: Some(refusal.into()),
        }
    }

    /// `SteerRefused(reason)`.
    pub fn steer_refused(reason: &str) -> Error {
        Error::State {
            class: "SteerRefused",
            message: reason.into(),
            word: Some(reason.into()),
        }
    }

    /// A Python exception by class.
    pub fn python(class: &'static str, message: impl Into<String>) -> Error {
        Error::Python(class, message.into())
    }

    /// `TypeError(message)`.
    pub fn type_error(message: impl Into<String>) -> Error {
        Error::Python("TypeError", message.into())
    }

    /// The class name the reference raises.
    pub fn class(&self) -> &'static str {
        match self {
            Error::State { class, .. } => class,
            Error::Python(class, _) => class,
            Error::Sqlite(error) => sqlite_class(error),
        }
    }

    /// `str(exc)`.
    pub fn message(&self) -> String {
        match self {
            Error::State { message, .. } | Error::Python(_, message) => message.clone(),
            Error::Sqlite(error) => error.to_string(),
        }
    }

    /// A `Refused`'s refusal or a `SteerRefused`'s reason.
    pub fn word(&self) -> Option<&str> {
        match self {
            Error::State { word, .. } => word.as_deref(),
            _ => None,
        }
    }

    /// `isinstance(exc, StateError)`.
    pub fn is_state(&self) -> bool {
        matches!(self, Error::State { .. })
    }

    /// `isinstance(exc, sqlite3.Error)`.
    pub fn is_sqlite(&self) -> bool {
        matches!(self, Error::Sqlite(_))
    }
}

/// The class Python's sqlite3 raises for SQLite's error: a constraint is `IntegrityError`, a value it could not
/// bind `ProgrammingError`, everything else `OperationalError`.
pub fn sqlite_class(error: &rusqlite::Error) -> &'static str {
    match error {
        rusqlite::Error::SqliteFailure(failure, _)
            if failure.code == rusqlite::ErrorCode::ConstraintViolation =>
        {
            "IntegrityError"
        }
        rusqlite::Error::ToSqlConversionFailure(_) | rusqlite::Error::InvalidParameterCount(..) => {
            "ProgrammingError"
        }
        _ => "OperationalError",
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

impl From<car_store::Error> for Error {
    fn from(error: car_store::Error) -> Error {
        match error {
            car_store::Error::Sqlite(error) => Error::Sqlite(error),
            other => Error::Python(other.class(), other.message()),
        }
    }
}

/// The advanced state's result.
pub type Result<T> = std::result::Result<T, Error>;
