//! review8 (REVIEW-surface.md S2), red on purpose until fixed: a seam that panics is not turned into the answer the
//! reference's `except Exception` gives.
//!
//! `ui/popup/model.perform` wraps every control call in `except Exception` ("a front end reports; it never raises into
//! the loop") and answers `("failed", type(exc).__name__)`; `notifier.activate` answers "failed" with one log line
//! (`notification card: the cancel failed (<class>)`). The port's convention for an exception a seam's `Result` cannot
//! carry is a panic (car-adv `port::Raised`, REVIEW-int5b N6), and D15 catches panics only at thread and DLL
//! boundaries: `perform` and `activate` here let the panic leave, so the popup's worker loses its outcome (its busy key
//! is never discarded by `apply_outcome`) and the card's press leaves no log line, where the reference reports and
//! goes on.

use std::cell::RefCell;
use std::panic::{AssertUnwindSafe, catch_unwind};

use car_machine::json::Value;
use car_policy::classify::clock::Crt;
use car_surface::notifier::{Activation, activate};
use car_surface::popup::model::perform;
use car_surface::seam::{CardControl, PopupControl, Raised};
use car_surface::speech::Speech;

/// A control layer whose reads break the way a ported seam carries a TypeError: by panicking.
struct Breaking;

fn broken() -> Result<Value, Raised> {
    std::panic::panic_any("TypeError: a value of the wrong type crossed the seam")
}

impl PopupControl for Breaking {
    fn list_pending(&self, _source: Option<&Value>) -> Result<Value, Raised> {
        broken()
    }
    fn get_status(&self) -> Result<Value, Raised> {
        broken()
    }
    fn set_enabled(&self, _enabled: bool) -> Result<Value, Raised> {
        broken()
    }
    fn set_interruption_recovery(
        &self,
        _i: &Value,
        _t: &Value,
        _enabled: bool,
    ) -> Result<Value, Raised> {
        broken()
    }
    fn postpone(&self, _i: &Value, _t: &Value, _preset: &Value) -> Result<Value, Raised> {
        broken()
    }
    fn unpostpone(&self, _i: &Value, _t: &Value) -> Result<Value, Raised> {
        broken()
    }
    fn release_hold(&self, _i: &Value, _t: &Value) -> Result<Value, Raised> {
        broken()
    }
    fn set_thread_tier(&self, _t: &Value, _tier: &Value, _i: &Value) -> Result<Value, Raised> {
        broken()
    }
    fn set_project_rule(
        &self,
        _i: &Value,
        _t: &Value,
        _always: bool,
        _source: Option<&Value>,
    ) -> Result<Value, Raised> {
        broken()
    }
    fn set_once_words(&self, _i: &Value, _t: &Value, _words: &Value) -> Result<Value, Raised> {
        broken()
    }
}

impl CardControl for Breaking {
    fn cancel_interruption(&self, _interruption_id: &str, _actor: &str) -> Result<Value, Raised> {
        broken()
    }
    fn stop_power_countdown(&self, _nonce: &str, _actor: &str) -> Result<Value, Raised> {
        broken()
    }
}

/// `f()`, with the default panic message held back while it runs: Ok its answer, Err where it unwound.
fn quietly<R>(f: impl FnOnce() -> R) -> Result<R, ()> {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let answer = catch_unwind(AssertUnwindSafe(f)).map_err(|_| ());
    std::panic::set_hook(previous);
    answer
}

#[test]
fn seams_that_break_are_reported() {
    let mut wrong = Vec::new();
    for action in [
        vec![Value::from("read")],
        vec![Value::from("enabled"), Value::Bool(true)],
        vec![
            Value::from("release"),
            Value::from("1".repeat(64)),
            Value::from("0a1b2c3d-3d4e-7f80-9a0b-1c2d3e4f5a6b"),
        ],
    ] {
        // The reference: ("failed", "TypeError") - an answer, never an exception into the popup's worker.
        match quietly(|| perform(&action, &Breaking, None, None)) {
            Ok((verdict, _)) if verdict == "failed" => {}
            Ok(other) => wrong.push(format!("perform({action:?}) answered {other:?}")),
            Err(()) => wrong.push(format!(
                "perform({action:?}) let the seam's panic leave; the reference answers (\"failed\", <class>)"
            )),
        }
    }
    let clock = Crt;
    let speech = Speech::new("en", &clock);
    let lines = RefCell::new(Vec::<String>::new());
    let log = |line: &str| -> Result<(), Raised> {
        lines.borrow_mut().push(line.to_owned());
        Ok(())
    };
    let with = Activation {
        control: Some(&Breaking),
        open_dashboard: None,
        announce: None,
        log: Some(&log),
        open_link: None,
        stay: Value::Array(Vec::new()),
        open_chat: None,
    };
    for uri in [
        format!("codex-auto-resume:cancel?i={}", "1".repeat(64)),
        "codex-auto-resume:power-stop?n=0123456789abcdef".to_owned(),
    ] {
        lines.borrow_mut().clear();
        // The reference: "failed", and one line naming the press that failed and the exception's class.
        match quietly(|| activate(&speech, &Value::from(uri.as_str()), &with)) {
            Ok(Ok(word)) if word == "failed" && lines.borrow().len() == 1 => {}
            Ok(other) => wrong.push(format!("activate({uri}) answered {other:?}, logged {:?}", lines.borrow())),
            Err(()) => wrong.push(format!(
                "activate({uri}) let the seam's panic leave (logged {:?}); the reference answers \"failed\" with one \
                 log line",
                lines.borrow()
            )),
        }
    }
    assert!(wrong.is_empty(), "{}", wrong.join("\n"));
}
