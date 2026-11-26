//! Seat S7.2e1: `engine/markerfree.py` (P7-DESIGN 2.2). Empty until that seat ports it; the skeleton (S7.2a) made the file
//! so no seat edits a `mod.rs`, `lib.rs` or `Cargo.toml` (P7-DESIGN 2.1).

use car_config::Paths;

use crate::capabilities::Code;

/// `make(paths)`: the capability's code, as `registry.py` names it. None until S7.2e1 ports it: the
/// runtime then treats the capability as one whose code could not be made (it trips at its first hook).
pub fn make(_paths: &Paths) -> Option<Box<dyn Code>> {
    None
}
