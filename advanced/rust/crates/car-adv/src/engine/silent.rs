//! `silent_continuation`'s code (seat S7.2e1; `engine/silent.py`): continue with no words (P15, headless only).
//!
//! P15 answers SILENT, unless a route met Codex refusing a turn with no input in this process
//! (`codex::headless::EMPTY_REFUSED`): then DEFER, so the next attempt carries words.

use std::sync::atomic::Ordering;

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::Alternative;

use crate::capabilities::{Code, Said, Spoke};
use crate::codex::headless;

pub const CAPABILITY: &str = "silent_continuation";

/// `SilentContinuation(paths)`: its hook at P15, reading the process's one flag.
pub struct SilentContinuation {
    pub paths: Paths,
}

impl Code for SilentContinuation {
    /// P15: SILENT, unless Codex has refused a turn with no input in this process.
    fn delivery(&mut self, _record: &Value) -> Spoke {
        if headless::EMPTY_REFUSED.load(Ordering::SeqCst) {
            Ok(Said::Defer)
        } else {
            Ok(Said::Word(Alternative::Silent))
        }
    }
}

/// `make(paths)`: the capability's code for one installation.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(SilentContinuation {
        paths: paths.clone(),
    }))
}
