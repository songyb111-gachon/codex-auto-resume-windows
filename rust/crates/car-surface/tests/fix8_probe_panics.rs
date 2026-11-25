//! fix8 (REVIEW-surface.md S2): a presence probe that panics is `answers = {}` in `deliver` and `show_demo`, as the
//! reference's `except Exception` has it; the notice is not lost (the toast is still raised).

use car_machine::json::Value;
use car_policy::classify::clock::Crt;
use car_surface::notice_inbox::Inbox;
use car_surface::notifier::{Notice, build_power_stopped, deliver, show_demo};
use car_surface::seam::Raised;
use car_surface::speech::Speech;

fn panicking() -> Result<Value, Raised> {
    std::panic::panic_any("TypeError: the probe broke")
}

#[test]
fn a_probe_that_panics_costs_the_card_not_the_notice() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let clock = Crt;
    let speech = Speech::new("en", &clock);
    let found: Notice = build_power_stopped(&speech, &Value::Array(Vec::new())).expect("built");
    let inbox: Inbox<Notice> = Inbox::new();
    inbox.attach(std::sync::Arc::new(|| true));
    let shown = std::cell::Cell::new(0);
    let show = |_: &car_machine::json::Map, _: bool| {
        shown.set(shown.get() + 1);
        Ok(true)
    };
    let answer = deliver(&found, Some(&inbox), &Value::Bool(true), &panicking, &show);
    let demo = show_demo(&found, Some(&inbox), &Value::Bool(true), &panicking);
    std::panic::set_hook(previous);
    // Every probe answer unknown: no card is allowed, so the toast is raised, once.
    assert_eq!(answer, Ok(("toast", true)));
    assert_eq!(shown.get(), 1);
    assert!(!demo);
}
