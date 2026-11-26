//! `runtime.py` (seat S7.2a): the registry's capabilities, asked at the plug's points, each in the state a person put
//! it in. Written in the commits after the skeleton; the files are:
//!
//! | here | `runtime.py` |
//! |---|---|
//! | this module | `Runtime.__init__`, `states`, `_code_of`, `action`, `_tripped`, `wants`, `_once`, `_paired`, the module's helpers |
//! | [`ask`] | `ask` and what it calls (`_takes`, `_ceiling`, `_conflict`, `_send_again`, `_alone`, `_remember`, `_first`, ...) |
//! | [`claim`] | `claim` (P11) and `partition` (P12) |
//! | [`records`] | `records` (P2), `_holders`, `_watched_records`, `conversation_off`, `_own_record_answer` |
//! | [`tick`] | `tick` (P8), `resident` (P22), `_auto_check`, `_Errands` |
//! | [`moved`] | `moved` (P14) and its tripwires |
//! | [`start`] | `start_route` (P9), `supervise` (P13), `_held_start` |
//! | [`lists`] | `eligibility` (P19), `sessions` (P18) |
//! | [`measurement`] | `run_measurement`, `complete_measurement` (seat S7.4) |

pub mod ask;
pub mod claim;
pub mod lists;
pub mod measurement;
pub mod moved;
pub mod records;
pub mod start;
pub mod tick;

use crate::state::AdvancedState;
use crate::state::scoped::Scoped;

/// What a runtime shares with the codes it bound (`crate::capabilities::Binding`).
pub struct Shared {
    pub state: AdvancedState,
}

/// `f(state.scoped(capability, ...))` for a binding.
pub(crate) fn scoped_for<R>(
    shared: &Shared,
    capability: &str,
    f: impl FnOnce(&Scoped<'_>) -> R,
) -> R {
    let scoped = Scoped {
        state: &shared.state,
        capability: car_machine::json::Value::Str(capability.into()),
        on: None,
        verdict: None,
        armed: None,
    };
    f(&scoped)
}
