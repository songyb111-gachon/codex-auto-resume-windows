//! car-engine's `Engine` as the loop drives it ([`TickEngine`]), and car-control's words for this time as the engine
//! reads them ([`car_engine::OnceWords`]).

use std::sync::Arc;

use car_engine::Engine;
use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_policy::settings::managed::Managed;

use crate::fail::{Failed, Res};
use crate::watchloop::TickEngine;

/// An exception the engine let out, by its class.
pub fn raised(class: &'static str) -> Failed {
    Failed::new(class, "")
}

fn py<T>(found: Py<T>) -> Res<T> {
    found.map_err(raised)
}

/// The engine of one Codex home, driven by the loop.
pub struct Driven(pub Engine);

impl crate::waking::Sleeper for Driven {
    fn after_sleep(&mut self, since: f64, slept: f64) -> Res<()> {
        py(self.0.after_sleep(since, slept)).map(|_| ())
    }
}

impl crate::afterwork::Activity for Driven {
    fn activity(&mut self, threads: &[String]) -> Res<Value> {
        Ok(Value::Object(self.0.activity(threads)))
    }
    fn follow_option(&self) -> Option<Value> {
        Some(Value::Float(
            self.0.options.unknown_reconcile_window_seconds,
        ))
    }
}

impl TickEngine for Driven {
    fn tick(&mut self) -> Res<()> {
        py(self.0.tick())
    }
    fn watch_needed(&mut self) -> Res<bool> {
        py(self.0.watch_needed())
    }
    fn watch(&mut self) -> Res<()> {
        py(self.0.watch())
    }
    fn last_usage(&mut self) -> Res<Option<(Value, Value)>> {
        Ok(self
            .0
            .last_usage()
            .map(|(at, windows)| (Value::Float(at), Value::Array(windows))))
    }
    fn detection_failed(&self) -> Option<bool> {
        self.0.detection_failed
    }
    fn handed_waits(&self) -> Map {
        self.0.handed_waits.clone()
    }
    fn apply_policy(&mut self, values: &Value, managed: &Managed) {
        self.0.apply_policy(values, Some(managed.clone()));
    }
    fn set_retiring(&mut self, retiring: bool) {
        self.0.retiring = retiring;
    }
    fn latest_failures(&mut self, since: f64) -> Res<Vec<Value>> {
        Ok(py(self.0.source.latest_failures(since, &[], true, true))?
            .into_iter()
            .map(Value::Object)
            .collect())
    }
}

/// `oncewords.OnceWords.of(paths)`: car-control's file of words for this time, as the engine asks it.
pub struct Words {
    pub file: String,
    pub host: Arc<dyn car_control::host::Host>,
}

impl Words {
    fn held(&self) -> car_control::oncewords::OnceWords<'_> {
        car_control::oncewords::OnceWords::of(&self.file, &*self.host)
    }
}

impl car_engine::OnceWords for Words {
    fn words(&self, interruption_id: &str) -> Py<Value> {
        Ok(self
            .held()
            .words(interruption_id)?
            .map_or(Value::Null, Value::Str))
    }
    fn unchanged(&self, interruption_id: &str, seen: &Value) -> Py<Value> {
        let seen = match seen {
            Value::Str(text) => Some(text),
            _ => None,
        };
        Ok(self
            .held()
            .unchanged(interruption_id, seen)
            .map_or(Value::Null, Value::Bool))
    }
    fn remove(&self, interruption_id: &str) -> Py<Value> {
        Ok(Value::Bool(self.held().remove(interruption_id)))
    }
    fn restore(&self, interruption_id: &str, words: &Value) -> Py<()> {
        self.held().restore(interruption_id, words, None);
        Ok(())
    }
    fn prune(&self, keep: &mut dyn FnMut(&str) -> Py<bool>) -> Py<()> {
        // `keep` raising ends the prune with its exception; the entries it already answered for stay as they were
        // only where the file is not written (car-control's prune takes an infallible `keep`: after the first
        // exception every entry is kept, and the exception is raised once the prune is done).
        let keep = std::cell::RefCell::new(keep);
        let failed: std::cell::Cell<Option<&'static str>> = std::cell::Cell::new(None);
        self.held().prune(|key| {
            if failed.get().is_some() {
                return true;
            }
            match (keep.borrow_mut())(key) {
                Ok(kept) => kept,
                Err(class) => {
                    failed.set(Some(class));
                    true
                }
            }
        });
        failed.get().map_or(Ok(()), Err)
    }
}
