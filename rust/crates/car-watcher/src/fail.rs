//! What a call of the watcher raised, as Python names it: the exception's class and `str(exc)`. The watcher's
//! `_record_failure(label)` writes the class alone into the main log, so the class is what every port keeps; and
//! D15's one catcher (car-machine `caught`) turns a panic into the same thing at every boundary the reference
//! catches `Exception` at.

use car_machine::caught::{Payload, catch, class_of, raised};

/// An exception, by its class and text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Failed {
    pub class: String,
    pub message: String,
}

impl Failed {
    pub fn new(class: &str, message: impl Into<String>) -> Failed {
        Failed {
            class: class.to_owned(),
            message: message.into(),
        }
    }

    /// What a panic carried, read as the exception it stands for.
    pub fn of_panic(payload: &Payload) -> Failed {
        let message = raised(&**payload)
            .map(|found| found.message.clone())
            .or_else(|| {
                payload
                    .downcast_ref::<&str>()
                    .map(|text| (*text).to_owned())
            })
            .or_else(|| payload.downcast_ref::<String>().cloned())
            .unwrap_or_default();
        Failed {
            class: class_of(&**payload),
            message,
        }
    }

    /// Whether this is one of the store's two errors of a newer version (never retried, never a corruption).
    pub fn newer(&self) -> bool {
        matches!(
            self.class.as_str(),
            "StateFromNewerVersion" | "RecordSchemaMismatch"
        )
    }
}

impl std::fmt::Display for Failed {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.class, self.message)
    }
}

impl From<car_store::errors::Error> for Failed {
    fn from(error: car_store::errors::Error) -> Failed {
        Failed::new(error.class(), error.message())
    }
}

impl From<car_control::error::Failure> for Failed {
    fn from(error: car_control::error::Failure) -> Failed {
        match error {
            car_control::error::Failure::Control(refused) => {
                Failed::new("ControlError", lossy(&refused.message))
            }
            car_control::error::Failure::Other(class) => Failed::new(&class, ""),
        }
    }
}

impl From<car_control::host::Raised> for Failed {
    fn from(error: car_control::host::Raised) -> Failed {
        Failed::new(&error.class, error.message)
    }
}

/// A result of the watcher's own.
pub type Res<T> = Result<T, Failed>;

/// `try: body() except Exception`: the body's own error, or a panic read as the exception it stands for (D15).
pub fn guarded<T>(body: impl FnOnce() -> Res<T>) -> Res<T> {
    match catch(body) {
        Ok(result) => result,
        Err(payload) => Err(Failed::of_panic(&payload)),
    }
}

/// The body, any panic in it caught and dropped: a thread's or a callback's last word (D15).
pub fn quietly(body: impl FnOnce()) {
    let _ = catch(body);
}

/// A Python `str` as Rust text, a surrogate as U+FFFD.
pub fn lossy(text: &car_machine::json::Str) -> String {
    text.code_points()
        .map(|point| char::from_u32(point).unwrap_or('\u{fffd}'))
        .collect()
}
