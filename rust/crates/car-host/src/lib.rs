//! car-host: `car_core.dll`, the core the C# watcher host `CodexAutoResume.exe` loads (D1 = U2).
//!
//! P6 step 0 (seat S6.2): the contracts only. [`abi`] holds the six exports, the closed event and action tables and
//! the panic rule, answering on an empty core; S6.2b fills the bodies over car-watcher (S6.1).

pub mod abi;

// The standard edition's six exports (feature `exports`, on by default). car-adv-host turns the feature off and makes
// the same six with the advanced plug, so the two never meet in one DLL.
#[cfg(feature = "exports")]
export_core!(car_policy::plug::Guarded::null);
