//! The engine's [`Backend`] over S3.3's `codex/transport.py` `Backend` (car-codex `transport::Backend`), Integration 6.
//!
//! The engine reads its backend as the reference does: a method for each call, and `getattr(backend, name, default)`
//! for the attributes a later version added. car-codex's `Backend` has every one, so each answer is its own: a value
//! where Python reads a value, `None` where its attribute is still unset. Its calls take `&mut self` (they keep what
//! they last saw: the rows, the app's look, the session holder), the engine's `&self`; the backend is held behind a
//! lock, which the engine's one thread never contends.
//!
//! The launch guard: the reference's `send(..., launch_guard=store.submission_guard(key))` enters the guard around the
//! one `Popen` (`with launch_guard as permitted:`). The engine's [`LaunchGuard`] runs a body inside the store's write
//! lock, so the send is car-codex's `send_within`, whose scope is that guard: the process is started inside the body.

use std::sync::{Mutex, MutexGuard};

use car_codex::transport::{Backend as Codex, Raised};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;

use crate::seam::{Backend, LaunchGuard};

/// car-codex's backend as the engine holds it.
pub struct Transport(pub Mutex<Codex>);

impl Transport {
    pub fn new(backend: Codex) -> Transport {
        Transport(Mutex::new(backend))
    }

    /// The backend again, as it was left.
    pub fn into_inner(self) -> Codex {
        self.0
            .into_inner()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn held(&self) -> MutexGuard<'_, Codex> {
        self.0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

fn word(found: Option<&str>) -> Value {
    found.map_or(Value::Null, Value::from)
}

/// `{method: (code, sequence)}`, as `_note` keeps it on the backend; None before the helper met anything (the
/// attribute is set by the first note).
fn results(kept: &[(String, (String, u64))]) -> Value {
    if kept.is_empty() {
        return Value::Null;
    }
    let mut map = Map::with_capacity(kept.len());
    for (method, (code, sequence)) in kept {
        map.insert(
            Str::from(method.as_str()),
            Value::Array(vec![Value::from(code.as_str()), Value::from(*sequence)]),
        );
    }
    Value::Object(map)
}

impl Backend for Transport {
    fn app_identity(&self) -> Py<Value> {
        match self.held().app_identity() {
            Ok(found) => Ok(found.unwrap_or(Value::Null)),
            Err(error) => Err(error.class()),
        }
    }

    fn loaded(&self, thread_id: &str, app_identity: &Value) -> Py<Value> {
        self.held()
            .loaded(thread_id, app_identity)
            .map(Value::from)
            .map_err(|error| error.class())
    }

    fn usage(&self) -> Py<Value> {
        self.held()
            .usage()
            .map(Value::Object)
            .map_err(|error| error.class())
    }

    fn send(&self, thread_id: &str, prompt: &Str, launch_guard: &dyn LaunchGuard) -> Py<Value> {
        let mut scope = |body: &mut dyn FnMut(bool)| -> Result<(), Raised> {
            launch_guard
                .enter(&mut |permitted| {
                    body(permitted);
                    Value::Bool(permitted)
                })
                .map(|_| ())
                .map_err(|_| Raised)
        };
        let answer = self
            .held()
            .send_within(thread_id, &Value::Str(prompt.clone()), &mut scope);
        Ok(Value::Object(answer))
    }

    fn delete_queue(&self, thread_id: &str, queue_id: &str) -> Py<Value> {
        self.held()
            .delete_queue(thread_id, queue_id)
            .map(Value::Bool)
            .map_err(|error| error.class())
    }

    fn app_look(&self) -> Value {
        word(self.held().app_look)
    }

    fn app_unmatched_reason(&self) -> Value {
        Value::from(self.held().app_unmatched_reason())
    }

    fn protocol_results(&self) -> Value {
        results(&self.held().protocol_results)
    }

    fn session_holder(&self) -> Value {
        match &self.held().session_holder {
            Some((pid, created)) => Value::Array(vec![pid.clone(), created.clone()]),
            None => Value::Null,
        }
    }

    fn engine_version(&self) -> Value {
        word(self.held().engine_version.as_deref())
    }

    fn holder(&self, thread_id: &str) -> Option<Py<Value>> {
        Some(
            self.held()
                .holder(thread_id)
                .map(Value::from)
                .map_err(|error| error.class()),
        )
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use car_codex::errors::Result;
    use car_codex::system::System;

    use super::*;

    /// A machine with nothing on it: no process, no engine. Nothing here starts a process.
    #[derive(Debug)]
    struct Empty;

    impl System for Empty {
        fn env(&self, _name: &str) -> Option<String> {
            None
        }
        fn processes_named(&self, _names: &[&str], _families: &[&str]) -> Result<Vec<Value>> {
            Ok(Vec::new())
        }
        fn resource_users(&self, _paths: &[String]) -> Result<Vec<Value>> {
            Ok(Vec::new())
        }
        fn process_identity(&self, _pid: &Value) -> Result<Value> {
            Ok(Value::Null)
        }
        fn signer(&self, _path: &str) -> std::result::Result<String, Option<&'static str>> {
            Err(None)
        }
        fn own_pid(&self) -> i64 {
            1
        }
        fn monotonic(&self) -> f64 {
            0.0
        }
        fn resolve(&self, text: &str) -> Option<String> {
            Some(text.to_owned())
        }
        fn restart_manager_available(&self) -> bool {
            false
        }

        fn package_roots(&self, _family: &str) -> car_codex::errors::Result<Vec<String>> {
            Ok(Vec::new())
        }
    }

    struct Counted(std::cell::Cell<u32>);

    impl LaunchGuard for Counted {
        fn enter(&self, body: &mut dyn FnMut(bool) -> Value) -> Py<Value> {
            self.0.set(self.0.get() + 1);
            Ok(body(true))
        }
    }

    fn transport() -> Transport {
        Transport::new(Codex::new(
            Arc::new(Empty),
            r"C:\nowhere\codex-home",
            r"C:\nowhere\codex.exe",
            false,
            "0.0.0",
        ))
    }

    /// The attributes `getattr` reads are None before anything set them, and the reason word is the property's.
    #[test]
    fn the_attributes_read_as_getattr_reads_them() {
        let backend = transport();
        assert_eq!(backend.app_look(), Value::Null);
        assert_eq!(backend.session_holder(), Value::Null);
        assert_eq!(backend.protocol_results(), Value::Null);
        assert_eq!(backend.engine_version(), Value::Null);
        assert_eq!(
            backend.app_unmatched_reason(),
            Value::from("app_server_unmatched")
        );
        backend.held().app_look = Some("unmatched");
        backend.held().session_holder = Some((Value::from(7), Value::from(1.5)));
        backend.held().protocol_results = vec![("initialize".into(), ("ok".into(), 3))];
        assert_eq!(backend.app_look(), Value::from("unmatched"));
        assert_eq!(
            backend.session_holder(),
            Value::Array(vec![Value::from(7), Value::from(1.5)])
        );
        let Value::Object(kept) = backend.protocol_results() else {
            panic!("a dict of the helper's answers");
        };
        assert_eq!(
            kept.get("initialize"),
            Some(&Value::Array(vec![Value::from("ok"), Value::from(3)]))
        );
    }

    /// A send its checks refuse never enters the launch guard, as the reference's preflight returns before `with`.
    #[test]
    fn a_refused_send_never_enters_the_guard() {
        let backend = transport();
        let guard = Counted(std::cell::Cell::new(0));
        let answer = backend
            .send("not-a-uuid", &Str::from("go on"), &guard)
            .unwrap();
        let Value::Object(answer) = answer else {
            panic!("a dict");
        };
        assert_eq!(answer.get("outcome"), Some(&Value::from("not_started")));
        assert_eq!(
            answer.get("error_code"),
            Some(&Value::from("queue_preflight_failed"))
        );
        assert_eq!(guard.0.get(), 0);
    }
}
