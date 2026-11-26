//! What the watcher says to its host (P6-DESIGN 1.5, the event table car-host's `abi.rs` holds): one queue the host
//! pulls with `next_event`, and the two waits the reference's icon thread makes - up to 5 s for the icon to come up
//! (`Tray.start`, answered by the `tray_started` action) and up to 5 s for it to go (`Tray.stop`'s join, answered by
//! `closed`).
//!
//! Each event is `{"kind": ..., <its fields in the table's order>}`; `ended` is always the last.

use std::collections::VecDeque;
use std::sync::{Condvar, Mutex, PoisonError};
use std::time::{Duration, Instant};

use car_machine::json::{Map, Value};

use crate::surface::Catalog;

/// `Tray.start` waits this long for the icon's thread; `Tray.stop` joins it this long.
pub const SURFACE_WAIT_SECONDS: f64 = 5.0;

#[derive(Default)]
struct Queue {
    events: VecDeque<Value>,
    /// The host said the icon came up (`tray_started`) or went (`closed`).
    started: Option<bool>,
    closed: bool,
    ended: bool,
    /// The card stack is attached (`cards_attached`): notices may go to it.
    cards: bool,
}

/// The queue and the waits.
#[derive(Default)]
pub struct Events {
    queue: Mutex<Queue>,
    ready: Condvar,
}

fn event<const N: usize>(kind: &str, fields: [(&str, Value); N]) -> Value {
    let mut map = Map::new();
    map.insert("kind".into(), Value::from(kind));
    for (name, value) in fields {
        map.insert(name.into(), value);
    }
    Value::Object(map)
}

impl Events {
    pub fn new() -> Events {
        Events::default()
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Queue> {
        self.queue.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn push(&self, value: Value) {
        let mut queue = self.lock();
        if queue.ended {
            return;
        }
        queue.events.push_back(value);
        self.ready.notify_all();
    }

    /// `car_next_event(timeout)`: the next event, or None once the time ran out.
    pub fn next(&self, timeout: Duration) -> Option<Value> {
        let until = Instant::now() + timeout;
        let mut queue = self.lock();
        loop {
            if let Some(found) = queue.events.pop_front() {
                return Some(found);
            }
            let now = Instant::now();
            if now >= until {
                return None;
            }
            queue = self
                .ready
                .wait_timeout(queue, until - now)
                .map(|(guard, _)| guard)
                .unwrap_or_else(|poisoned| poisoned.into_inner().0);
        }
    }

    /// The `surfaces` event, and the wait for `tray_started` (`Tray.start`): whether the icon came up. The catalog's
    /// locale and letters go with it, so the first frame is drawn in that language (DECISIONS.md's addendum).
    pub fn start_surfaces(
        &self,
        icon: &str,
        catalog: &Catalog,
        settings: &Value,
        edition: &str,
        demo: &str,
    ) -> bool {
        self.push(event(
            "surfaces",
            [
                ("icon", Value::from(icon)),
                ("strings", Value::Object(catalog.strings.clone())),
                ("settings", settings.clone()),
                ("edition", Value::from(edition)),
                ("demo", Value::from(demo)),
                ("locale", Value::from(catalog.locale.as_str())),
                ("letters", Value::from(catalog.letters.as_str())),
            ],
        ));
        self.wait(SURFACE_WAIT_SECONDS, |queue| queue.started.is_some())
            .is_some_and(|queue_started| queue_started)
    }

    fn wait(&self, seconds: f64, done: impl Fn(&Queue) -> bool) -> Option<bool> {
        let until = Instant::now() + Duration::from_secs_f64(seconds);
        let mut queue = self.lock();
        loop {
            if done(&queue) {
                return Some(queue.started.unwrap_or(false));
            }
            let now = Instant::now();
            if now >= until {
                return None;
            }
            queue = self
                .ready
                .wait_timeout(queue, until - now)
                .map(|(guard, _)| guard)
                .unwrap_or_else(|poisoned| poisoned.into_inner().0);
        }
    }

    /// The `close` event, and the wait for `closed` (`Tray.stop`'s join).
    pub fn close_surfaces(&self) {
        self.push(event("close", []));
        let _ = self.wait(SURFACE_WAIT_SECONDS, |queue| queue.closed);
    }

    /// The tray's snapshot and the popup's ready view (`surface::Shared::field`).
    pub fn queue_snapshot(&self, snapshot: Value, popup: Value) {
        self.push(event(
            "snapshot",
            [("snapshot", snapshot), ("popup", popup)],
        ));
    }

    pub fn queue_settings(&self, settings: &Value) {
        self.push(event("settings", [("settings", settings.clone())]));
    }

    /// A new catalog with its locale and letters. The caller sends a snapshot right after it, drawn in those words.
    pub fn queue_strings(&self, catalog: &Catalog) {
        self.push(event(
            "strings",
            [
                ("strings", Value::Object(catalog.strings.clone())),
                ("locale", Value::from(catalog.locale.as_str())),
                ("letters", Value::from(catalog.letters.as_str())),
            ],
        ));
    }

    /// A watcher notice (`_watcher_notice`): the card where the host attached it and the notice is not the last one,
    /// else - the notifier's toast is car-surface's, raised by the host's notifier seam (S6.2b) - the same event.
    pub fn queue_watcher_notice(&self, event_name: &str, detail: Map, last: bool) {
        let mut notice = Map::new();
        notice.insert("event".into(), Value::from(event_name));
        notice.insert("detail".into(), Value::Object(detail));
        notice.insert("final".into(), Value::Bool(last));
        self.push(event("notice", [("notice", Value::Object(notice))]));
    }

    /// `ended {exit_code}`: always the last event.
    pub fn end(&self, code: i32) {
        let mut queue = self.lock();
        if queue.ended {
            return;
        }
        queue.events.push_back(event(
            "ended",
            [("exit_code", Value::from(i64::from(code)))],
        ));
        queue.ended = true;
        self.ready.notify_all();
    }

    /// The host's answers to the two waits and the card stack's attachment.
    pub fn tray_started(&self, started: bool) {
        self.lock().started = Some(started);
        self.ready.notify_all();
    }

    pub fn closed(&self) {
        self.lock().closed = true;
        self.ready.notify_all();
    }

    pub fn cards(&self, attached: bool) {
        self.lock().cards = attached;
        self.ready.notify_all();
    }

    pub fn cards_attached(&self) -> bool {
        self.lock().cards
    }

    pub fn is_ended(&self) -> bool {
        self.lock().ended
    }
}
