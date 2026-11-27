//! car-adv-host: the advanced edition's `car_core.dll` (P6-DESIGN 1, the owner's Q3: one host exe for both editions,
//! the edition differences in each edition's core DLL).
//!
//! car-host's six exports (`car_host_lib::export_core!`) over the advanced edition's [`Factory`]: the same bodies as
//! the standard DLL, the plug the only difference. car-host's own exports are off here (`default-features = false`), so
//! the two editions' six never meet in one DLL.
//!
//! The plug is `plug.py`'s `AdvancedPlug` as far as the core sees it with no capability on: its edition and badge,
//! and every decision answering as NULL does ("an advanced installation with nothing on is the standard one",
//! `AdvancedPlug`'s own docstring, held by advanced/tests/test_advanced_package.py). The capabilities' hooks are S7.3d's
//! to put behind this same factory (P7-DESIGN S7.3d); the factory is the one seam they change.
//!
//! [`Factory`]: car_host_lib::abi::Factory

use car_policy::plug::{Edition, Guarded, Plug};

/// `AdvancedPlug` with no capability on.
struct AdvancedPlug;

impl Plug for AdvancedPlug {
    fn edition(&self) -> Edition {
        Edition::Advanced
    }

    fn badge(&self) -> &'static str {
        "Advanced"
    }
}

/// The advanced edition's plug, made once per watcher start (`plug.load()` in an advanced installation).
pub fn advanced_plug() -> Guarded {
    Guarded::new(Box::new(AdvancedPlug))
}

car_host_lib::export_core!(advanced_plug);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_factory_is_the_advanced_edition() {
        let plug = advanced_plug();
        assert_eq!(plug.edition(), Edition::Advanced);
        assert_eq!(plug.badge(), "Advanced");
        assert!(!plug.is_null());
    }

    #[test]
    fn the_six_answer_before_a_start() {
        assert_eq!(car_stop(), 0);
        let request = br#"{"argv": "run"}"#;
        let mut length = 0usize;
        // SAFETY: `request` lives for the call; `length` is the test's.
        let reply = unsafe { car_start(request.as_ptr(), request.len(), &mut length) };
        // SAFETY: `length` bytes the core handed out.
        let text = unsafe { std::slice::from_raw_parts(reply, length) }.to_vec();
        assert_eq!(text, br#"{"abi": 1, "ok": false, "error": "bad_request"}"#);
        // SAFETY: handed back once with its own length.
        unsafe { car_free(reply, length) };
    }
}
