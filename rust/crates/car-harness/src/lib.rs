//! car-harness: the Rust side of the differential harness (PLAN.md section 4). Dev only, never shipped.
//!
//! It holds S0.4's skeleton (the bridge's `defaults`) and car-store's calls (S1.2, `store`), writing JSON
//! through car-machine's Python-compatible writer. Every later port seat adds its calls to `serve` and moves the real code into its own crate.

pub mod acting;
pub mod appserver;
pub mod bridge;
pub mod classify;
pub mod cli;
pub mod codex;
pub mod defaults;
pub mod engine;
pub mod judge;
pub mod leaves;
pub mod links;
pub mod mcp;
pub mod plugscript;
pub mod policy;
pub mod proxy;
pub mod registry;
pub mod store;
pub mod surface;
pub mod watcher;

use car_machine::json::{Map, Value};

/// The refusal shape the bridge uses (`controlcli._rejected`).
pub fn rejected(message: &str, code: &str) -> Value {
    object([
        ("ok", Value::Bool(false)),
        ("error", message.into()),
        ("error_code", code.into()),
    ])
}

/// An object whose keys keep the order given, as the Python builds its dicts.
pub fn object<const N: usize>(pairs: [(&str, Value); N]) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(key.into(), value);
    }
    Value::Object(map)
}

/// What anything not yet ported answers, so a shim-lane failure says why.
pub const NOT_PORTED: &str = "not_ported";
