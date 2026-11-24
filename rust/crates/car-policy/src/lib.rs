//! car-policy: the classifier and the policy (PLAN.md 1.2, row 6).
//!
//! Two seats fill it (PLAN 5.3, P2): S2.1 the classifier and the policy that reads it ([`classify`]); S2.2 the settings (`settings`: the
//! settings, their schema and persistence, the administrator's keys, the status file, the power action's rules, the memory guard, the
//! demo, the self-check and their kin) and the edition's plug (`plug`: the Plug trait P2-P22, PLUG_API, NULL and the edition).

pub mod classify;
pub mod plug;
pub mod settings;
