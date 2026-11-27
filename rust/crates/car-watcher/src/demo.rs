//! Show me what happens (v0.6.11, `App._demo`, `runtime/app.py:537-547`) through the event table (S6.2b4).
//!
//! The reference's icon makes the demo event (`DemoEvent(str(paths.state_dir))`, `ui/tray/icon.py:270-286`) when it
//! comes up and looks at it on its one-second timer; Diagnostics signals it. Here the core does the look while the
//! host's surfaces are up (the host only draws): a signal starts one worker that builds the made-up card
//! (`notifier.build_demo(time.time())`) and hands it to the host as the `demo` event - only where a card may be shown
//! now (`notifier.show_demo`: the card setting, the host's card stack attached, this PC's presence answers), never a
//! toast. The state, the engine and Codex are not touched.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread::JoinHandle;
use std::time::Duration;

use car_machine::json::{Map, Value};

use crate::events::Events;
use crate::fail::{Failed, Res};

/// How often the look is made (the icon's `TIMER_TICK`, one second).
const LOOK: Duration = Duration::from_secs(1);
/// How often the look's thread asks whether it should end.
const STEP: Duration = Duration::from_millis(100);

/// A log line, as the icon's `log` writes it (the watcher's main log).
pub type Log = Arc<dyn Fn(&str) + Send + Sync>;
/// `notice_presence.snapshot(notify.aumid())`'s answers, or what it raised.
pub type Probe = Arc<dyn Fn() -> Result<Value, Failed> + Send + Sync>;

/// `notifier.show_demo(notifier.build_demo(now), inbox=App._inbox, setting=...)`: whether the demo card went to the
/// host. `values` are the settings in force.
pub fn show(
    events: &Events,
    values: &Value,
    now: f64,
    probe: &dyn Fn() -> Result<Value, Failed>,
) -> Res<bool> {
    let environ = |name: &str| std::env::var(name).ok();
    let locale = car_words::interface::language(&environ, &Vec::new);
    let clock = car_platform::localclock::Crt;
    let speech = car_surface::speech::Speech::new(locale, &clock);
    let notice = car_surface::notifier::build_demo(&speech, &Value::Float(now))
        .map_err(|class| Failed::new(class, ""))?;
    if !matches!(crate::notices::card_setting(values), Value::Bool(true))
        || !events.cards_attached()
    {
        return Ok(false);
    }
    let answers = match probe() {
        Ok(Value::Object(found)) => found,
        _ => Map::new(),
    };
    if !car_surface::notice_presence::card_allowed(
        &car_surface::notice_presence::Answers::from_probes(&answers),
    ) {
        return Ok(false);
    }
    Ok(events.post_demo(&notice))
}

/// The look at the demo event while the surfaces are up.
pub struct DemoLook {
    stop: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}

impl DemoLook {
    /// `_open_demo` and the timer's `_look_for_demo`: the event made under `name` (`str(paths.state_dir)`); each
    /// signal one worker thread, `settings` read when it runs.
    pub fn start(
        name: &str,
        events: Arc<Events>,
        settings: Arc<std::sync::Mutex<Map>>,
        log: Log,
        probe: Probe,
    ) -> DemoLook {
        let stop = Arc::new(AtomicBool::new(false));
        let ended = Arc::clone(&stop);
        let name = name.to_owned();
        let thread = std::thread::Builder::new()
            .name("demo-look".into())
            .spawn(move || {
                crate::fail::quietly(|| look(&name, &ended, &events, &settings, &log, &probe));
            })
            .ok();
        DemoLook { stop, thread }
    }

    /// The icon gone: no more looks.
    pub fn stop(mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

impl Drop for DemoLook {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

fn look(
    name: &str,
    stop: &AtomicBool,
    events: &Arc<Events>,
    settings: &Arc<std::sync::Mutex<Map>>,
    log: &Log,
    probe: &Probe,
) {
    let mut event = match car_platform::sync::DemoEvent::new(name) {
        Ok(event) => event,
        Err(error) => {
            log(&format!("demo unavailable ({})", class_of(error.0)));
            return;
        }
    };
    if let Err(error) = event.enter() {
        log(&format!("demo unavailable ({})", class_of(error.0)));
        return;
    }
    let mut waited = Duration::ZERO;
    while !stop.load(Ordering::SeqCst) {
        std::thread::sleep(STEP);
        waited += STEP;
        if waited < LOOK {
            continue;
        }
        waited = Duration::ZERO;
        if event.taken() {
            demo(events, settings, log, probe);
        }
    }
}

/// `AdapterError(code)` is the class the reference's log line names.
fn class_of(_code: &str) -> &'static str {
    "AdapterError"
}

/// `App._demo()`: one worker; what it raised is one line in the log.
fn demo(events: &Arc<Events>, settings: &Arc<std::sync::Mutex<Map>>, log: &Log, probe: &Probe) {
    let events = Arc::clone(events);
    let settings = Arc::clone(settings);
    let log = Arc::clone(log);
    let probe = Arc::clone(probe);
    let _ = std::thread::Builder::new()
        .name("demo".into())
        .spawn(move || {
            let values = Value::Object(
                settings
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .clone(),
            );
            if let Err(failed) =
                crate::fail::guarded(|| show(&events, &values, crate::clock::wall(), &*probe))
            {
                log(&format!("demo card not shown ({})", failed.class));
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn card_answers() -> Result<Value, Failed> {
        let mut found = Map::new();
        for (name, value) in [
            ("notification_state", Value::from(5)),
            ("notification_mode", Value::from(0)),
            ("app_notifications", Value::from(0)),
            ("screen_reader", Value::Bool(false)),
            ("remote_session", Value::Bool(false)),
            ("session_locked", Value::Bool(false)),
        ] {
            found.insert(name.into(), value);
        }
        Ok(Value::Object(found))
    }

    fn values(card: Value) -> Value {
        let mut map = Map::new();
        map.insert(car_surface::notifier::CARD_SETTING.into(), card);
        Value::Object(map)
    }

    #[test]
    fn the_demo_card_goes_to_the_host_only_where_a_card_may_be_shown_now() {
        let events = Arc::new(Events::new());
        // No card stack attached: nothing, and never a toast.
        assert!(!show(&events, &values(Value::Bool(true)), 1.8e9, &card_answers).unwrap());
        assert!(events.next(Duration::ZERO).is_none());
        events.attach_cards();
        // The card setting off, or not exactly True.
        assert!(!show(&events, &values(Value::Bool(false)), 1.8e9, &card_answers).unwrap());
        assert!(!show(&events, &values(Value::from(1)), 1.8e9, &card_answers).unwrap());
        // Presence that cannot tell, or a probe that raised.
        assert!(
            !show(&events, &values(Value::Bool(true)), 1.8e9, &|| Ok(
                Value::Null
            ))
            .unwrap()
        );
        assert!(
            !show(&events, &values(Value::Bool(true)), 1.8e9, &|| Err(
                Failed::new("OSError", "")
            ))
            .unwrap()
        );
        assert!(events.next(Duration::ZERO).is_none());
        // Every answer the card's: one `demo` event with the made-up card, ended once by notice_complete.
        assert!(show(&events, &values(Value::Bool(true)), 1.8e9, &card_answers).unwrap());
        let found = events.next(Duration::ZERO).expect("the demo event");
        let Value::Object(found) = found else {
            panic!("an object")
        };
        assert_eq!(found.get("kind"), Some(&Value::from("demo")));
        let Some(Value::Object(notice)) = found.get("notice") else {
            panic!("the card's view")
        };
        let id = notice.get("id").cloned().expect("an id");
        assert!(events.take_posted(&id).is_some());
        assert!(events.take_posted(&id).is_none());
        // The inbox itself got nothing: the demo is not a notice.
        assert!(events.inbox().take().is_empty());
        // Settings unset: the card setting's default, True.
        assert!(show(&events, &Value::Object(Map::new()), 1.8e9, &card_answers).unwrap());
    }

    #[test]
    fn the_look_ends_with_the_surfaces() {
        let events = Arc::new(Events::new());
        let look = DemoLook::start(
            "car-watcher-demo-test-not-a-state-dir",
            events,
            Arc::new(std::sync::Mutex::new(Map::new())),
            Arc::new(|_: &str| {}),
            Arc::new(card_answers),
        );
        look.stop();
    }
}
