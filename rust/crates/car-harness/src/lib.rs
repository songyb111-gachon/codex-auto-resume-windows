//! car-harness: the Rust side of the differential harness (PLAN.md section 4). Dev only, never shipped.
//!
//! Today it holds S0.4's skeleton and proof only: the inline JSON writer, the bridge's `defaults`, and one
//! state read. Every later port seat adds its calls to `serve` and moves the real code into its own crate.

pub mod defaults;
pub mod pyjson;
pub mod state;

use pyjson::Value;

/// The refusal shape the bridge uses (`controlcli._rejected`).
pub fn rejected(message: &str, code: &str) -> Value {
    Value::Object(vec![
        ("ok".into(), Value::Bool(false)),
        ("error".into(), Value::Str(message.into())),
        ("error_code".into(), Value::Str(code.into())),
    ])
}

/// What anything not yet ported answers, so a shim-lane failure says why.
pub const NOT_PORTED: &str = "not_ported";
