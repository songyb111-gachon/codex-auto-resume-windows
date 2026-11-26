//! What the report's flow reaches the rest of the advanced edition through (seat S7.3c), each a seam another seat fills.
//!
//! | here | stands in for | filled by |
//! |---|---|---|
//! | [`Runtime`] | `runtime.arming.policy()`, `runtime.states(fresh=True)`, `runtime.state.arming()`, `runtime.arming.trip`, `runtime.state.note` | S7.2a's runtime (`car-adv/src/runtime`), over the real `Arming` and `AdvancedState` |
//! | [`HomeMutex`], [`MakeMutex`] | `report/flow.ReportMutex`: the home's named mutex, its handle kept for the life of the process, abandonment told | car-platform's `sync` (S3.1) once it keeps the handle and tells `WAIT_ABANDONED` apart (it closes it on exit and holds `abandoned` only after `enter`); the name is [`mutex_name`] |
//! | [`CodexHome`] | `codex/inuse.home(paths)`: the Codex home this installation looks at | S7.2c's `codex/inuse` |
//! | [`super::reading::WatcherView`] | `compatio.reader_view` | S3.3 (`car-codex::compatio`, `compat::views`) |
//! | [`super::github::Runner`], [`super::github::Jobs`] | gh started in the job object | S7.3b's car-platform `job.rs` |
//!
//! Nothing here starts a process, opens a window or reaches the network.

use std::path::PathBuf;

use car_config::Paths;

use crate::policy::Policy;
use crate::registry::CapabilityDef;
use crate::vocabulary::{ArmingState, OffReason};

/// Another exception than the closed ones: its class, as the reference's `type(error).__name__`.
pub type Class = String;

/// The runtime a capability's code is handed (`Runtime` in `runtime.py`), as far as the report's flow asks it.
pub trait Runtime: Send + Sync {
    /// `runtime.arming.policy()`: what the administrator allows.
    fn policy(&self) -> Result<Policy, Class>;
    /// `runtime.states(fresh=True).get(id)`: where the capability stands now, or `None` where the map does not hold it
    /// (the flow reads that as off).
    fn state_of(&self, id: &str) -> Result<Option<ArmingState>, Class>;
    /// `(runtime.state.arming().get(id) or {}).get("state")`: what the state stores for it; `Err` where it cannot be read
    /// (the flow reads that as nothing stored).
    fn stored_state(&self, id: &str) -> Result<Option<ArmingState>, Class>;
    /// `runtime.arming.trip(id, reason)`: the capability turns itself off.
    fn trip(&self, id: &str, reason: OffReason);
    /// `runtime.state.note(definition.code(code), capability=definition.id, at=at)`: one line of the journal. The flow
    /// ignores a failure, as the reference does.
    fn note(&self, definition: &CapabilityDef, code: &str, at: f64) -> Result<(), Class>;
}

/// The home's report mutex held by one check or send (`ReportMutex.take`/`give`).
pub trait HomeMutex: Send + Sync {
    /// Takes it on the calling thread without waiting; whether the holder before let it go by dying (abandoned).
    /// `Err(Busy)` where another holds it now.
    fn take(&self) -> Result<bool, Busy>;
    /// Lets it go, on the thread that took it; the handle stays open.
    fn give(&self);
}

/// Another check or send of this home holds the report mutex.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Busy;

/// Makes the mutex of one home (`mutex=ReportMutex`).
pub type MakeMutex = Box<dyn Fn(&Paths) -> Box<dyn HomeMutex> + Send + Sync>;

/// `codex/inuse.home(paths)`.
pub trait CodexHome: Send + Sync {
    fn home(&self, paths: &Paths) -> PathBuf;
}

/// The mutex's name (`Mutex(str(paths.advanced_dir / MUTEX_NAME)).name`): per user and per path, in the session's
/// namespace. `home` is the user's home as car-platform spells it (`paths::home_identity`).
pub fn mutex_name(paths: &Paths, home: &str) -> String {
    let path = std::path::Path::new(&paths.advanced_dir).join(super::flow::MUTEX_NAME);
    car_platform::names::mutex_name_for(
        home,
        &car_config::winpath::path_str(&path.to_string_lossy()),
    )
}
