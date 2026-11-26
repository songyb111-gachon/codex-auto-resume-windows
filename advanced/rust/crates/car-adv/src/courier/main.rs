//! `courier/__main__.py` (seat S7.3b): the courier process - `codex-auto-resume.exe courier --home <home> [--feed |
//! --test <channel> | --pair | --serve | --check]` (the alpha's start, PLAN 1.7, in place of `pythonw.exe -c
//! <BOOTSTRAP> ...`).
//!
//! It takes this home's courier mutex first - a second courier for the same home exits at once with [`EXIT_BUSY`] -
//! then does one round and exits: the outbox drained while push_notices stands on and recovery is not paused; with
//! `--feed`, OpenAI's status page read once too; `--test <channel>`, the fixed test notice; `--pair`, Telegram's
//! pairing; `--serve`, the resident roles under the resident's own mutex; `--check`, every part a round needs linked,
//! then 0, nothing read or written. Nothing is printed.
//!
//! [`Runtime`] is what the courier's parts ask of the advanced runtime (`runtime.state`, `.clock()`, `.registry`,
//! `.states(fresh=True)`, `._unreadable`, `.arming.trip`, `.paths`): the real one is `crate::runtime::Runtime`; a diff
//! hands its own over the same state.

use car_config::Paths;

use crate::arming::States;
use crate::registry::Registry;
use crate::state::AdvancedState;
use crate::vocabulary::OffReason;

pub const EXIT_DONE: i32 = 0;
pub const EXIT_BUSY: i32 = 3;
pub const EXIT_REFUSED: i32 = 4;
pub const EXIT_NOT_PAIRED: i32 = 9;
pub const PUSH: &str = "push_notices";
pub const FEED: &str = "status_feed";

/// `EXIT_TEST[word]`: a test notice's outcome as its exit code.
pub fn exit_test(word: &str) -> Option<i32> {
    match word {
        "2xx" => Some(0),
        "4xx" => Some(5),
        "5xx" => Some(6),
        "timeout" => Some(7),
        "tls" => Some(8),
        _ => None,
    }
}

/// What the courier's parts ask of the runtime.
pub trait Runtime {
    fn state(&self) -> &AdvancedState;
    fn registry(&self) -> &Registry;
    fn paths(&self) -> &Paths;
    /// `runtime.clock()`.
    fn clock(&self) -> f64;
    /// `runtime.states(fresh=True)`; `Err` where it raised.
    fn states(&self) -> Result<States, ()>;
    /// `runtime._unreadable`: the last read of the states failed.
    fn unreadable(&self) -> bool;
    /// `runtime.arming.trip(capability, reason)`; `Err` where it raised.
    fn trip(&self, capability: &str, reason: OffReason) -> Result<bool, ()>;
}

impl Runtime for crate::runtime::Runtime {
    fn state(&self) -> &AdvancedState {
        &self.state
    }

    fn registry(&self) -> &Registry {
        &self.registry
    }

    fn paths(&self) -> &Paths {
        &self.paths
    }

    fn clock(&self) -> f64 {
        self.now()
    }

    fn states(&self) -> Result<States, ()> {
        Ok(crate::runtime::Runtime::states(self, true, &[]))
    }

    fn unreadable(&self) -> bool {
        self.unreadable.get()
    }

    fn trip(&self, capability: &str, reason: OffReason) -> Result<bool, ()> {
        self.arming().trip(capability, reason).map_err(|_| ())
    }
}
