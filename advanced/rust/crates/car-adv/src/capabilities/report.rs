//! Seat S7.2a: the code of `compat_report` (`report/__init__.py`'s `make`: `report::flow::Flow::new`), filled after the skeleton.

use car_config::Paths;

use super::Code;

/// The capability's code; None until S7.2a fills it.
pub fn make(_paths: &Paths) -> Option<Box<dyn Code>> {
    None
}
