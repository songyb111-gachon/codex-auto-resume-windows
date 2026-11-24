//! car-words: the 22 catalogs and the way they are read, formatted and chosen between (PLAN 1.2 row 2).
//!
//! Replaces `l10n.py`, `interface.py`, `messages.py` and `ui/words.py`. The Windows preferred UI languages, which
//! only car-platform can ask, and the broken-down local time, which is the platform's clock, are handed in by the
//! caller; everything else is here. Held to the reference tag by `tests/rustdiff/diffs_leaves_words.py`.

#[rustfmt::skip]
mod bidi_tables;
pub mod interface;
pub mod l10n;
#[rustfmt::skip]
pub mod vocab_gen;
pub mod words;
