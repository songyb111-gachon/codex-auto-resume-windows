//! `every_conversation`'s code (seat S7.2e1; `engine/everyconversation.py`): every desktop conversation but Codex's
//! own kinds taken up (P19). It answers one closed word, EVERY_DESKTOP (`Widening`), and decides nothing else.

use car_config::Paths;
use car_machine::json::Value;

use crate::capabilities::{Code, Said, Spoke};

pub const CAPABILITY: &str = "every_conversation";
/// `Widening.EVERY_DESKTOP`.
pub const EVERY_DESKTOP: &str = "every_desktop";

/// `EveryConversation(paths)`: its answer at P19.
pub struct EveryConversation {
    pub paths: Paths,
}

impl Code for EveryConversation {
    /// P19: `frozenset({Widening.EVERY_DESKTOP})`.
    fn eligibility(&mut self) -> Spoke {
        Ok(Said::Set(vec![Value::Str(EVERY_DESKTOP.into())]))
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(EveryConversation {
        paths: paths.clone(),
    }))
}
