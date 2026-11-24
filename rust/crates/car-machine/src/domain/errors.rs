//! `domain/errors.py`: what this product refuses with, carrying only a reason.

/// Contains only a static reason code; never raw CLI or protocol output (`AdapterError`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdapterError(pub &'static str);

impl std::fmt::Display for AdapterError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.0)
    }
}

impl std::error::Error for AdapterError {}
