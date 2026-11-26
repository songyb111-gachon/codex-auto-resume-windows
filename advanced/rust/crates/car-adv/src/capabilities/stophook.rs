//! Seat S7.2a: the code of `stop_hook_continuation` (`engine/hookclaims.py`'s `StopHook`: `hookclaims::blocked_at` at P3, `hookplugin::follow_real` at P8), filled after the skeleton.

use car_config::Paths;

use super::Code;

/// The capability's code; None until S7.2a fills it.
pub fn make(_paths: &Paths) -> Option<Box<dyn Code>> {
    None
}
