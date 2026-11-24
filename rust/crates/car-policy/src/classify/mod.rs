//! The classifier and the policy that reads it (S2.1): what a failed turn was, what each kind is called and sent,
//! and the rules a waiting recovery is held, paced, postponed or let go by.
//!
//! | here | Python (v0.6.26-beta.2, `src/codex_auto_resume/`) |
//! |---|---|
//! | [`failures`] | `failures.py` |
//! | [`reasons`] | `reasons.py` |
//! | [`gates`] | `domain/gates.py` |
//! | [`guards`] | `guards.py` |
//! | [`ladder`] | `ladder.py` |
//! | [`quiet`] | `quiet.py` |
//! | [`projects`] | `projects.py` |
//! | [`needsyou`] | `needsyou.py` |
//! | [`power`] | `power.py` |
//! | [`continuation`] | `continuation.py` |
//! | [`permits`] | `compat/permits.py` |
//! | [`selfcheck`] | `domain/public.py`'s `self_check` (cut C1: it reads `failures.TAG_SHAPE`) |
//! | [`vocab_gen`] | every word list of the modules above, generated (`tests/rustdiff/gen_policy.py`) |
//! | [`text`] | Python's `str.lower()` and `re`'s `\w`, over tables the same generator makes |
//! | [`pyjson`] | `json.loads` where Python reads what serde refuses (NaN, a lone surrogate) |
//! | `crate::settings::ownvalues`, `crate::plug` | what these modules read of `ownvalues.py` and `domain/plug.py` (S2.2's) |
//!
//! The rule of the port: the Python's answer, never stricter and never looser. Each function takes the values the
//! Python takes - a record, a settings dict, a structured error, as car-machine's Python-model [`Value`] - and
//! answers what Python answers, including the class of the exception it would raise ([`Py`]).
//! `tests/rustdiff/diffs_classify_*.py` hold every function here to the reference tag's own answers.
//!
//! [`Value`]: car_machine::json::Value
//! [`Py`]: car_machine::pyval::Py

pub mod clock;
pub mod continuation;
pub mod failures;
pub mod gates;
pub mod guards;
pub mod ladder;
pub mod needsyou;
pub mod permits;
pub mod power;
pub mod projects;
pub mod pyjson;
pub mod quiet;
pub mod reasons;
pub mod selfcheck;
pub mod text;
#[rustfmt::skip]
mod text_tables;
pub mod value;
#[rustfmt::skip]
pub mod vocab_gen;

/// `word in words`.
pub fn has(words: &[&str], word: &str) -> bool {
    words.contains(&word)
}
