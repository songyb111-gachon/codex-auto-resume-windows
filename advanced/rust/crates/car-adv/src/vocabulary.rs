//! `vocabulary.py`: the advanced edition's closed words - every word its state holds, its journal writes and its
//! surfaces answer with.
//!
//! One typed enum per Python `StrEnum`, with `as_str`, `parse` and `ALL` in the order the tag defines them. The enums and
//! the four lists beside them (`TRIPWIRES`, `KEPT_NOTICES`, `NOTE_FOR_PASS`, `NOTE_FOR_FAIL`) are written by
//! `tests/rustdiff/gen_advpolicy.py` from the reference tag's own module (`vocabulary_gen.rs`); `gen_advpolicy.py --check`
//! says when they are stale and `diffs_advpolicy_words.py` holds them equal to the tag's, both ways.

pub use crate::vocabulary_gen::*;

/// What every closed word of this edition can do: say its word, and list all of its kind.
pub trait ClosedWord: Copy + 'static {
    fn word(self) -> &'static str;
    fn all() -> &'static [Self];
}

/// `Enum(text)` for a closed word: the member whose value is `text`, or `None` where the tag raises `ValueError`.
pub fn parse<W: ClosedWord>(text: &str) -> Option<W> {
    W::all().iter().copied().find(|each| each.word() == text)
}

/// `NOTE_FOR_PASS` and `NOTE_FOR_FAIL`'s tests, as the tag's frozensets answer `in`.
pub fn is_tripwire(reason: OffReason) -> bool {
    TRIPWIRES.contains(&reason)
}

impl Measurement {
    /// `str(measurement)`.
    pub fn as_text(self) -> String {
        self.as_str().to_owned()
    }
}
