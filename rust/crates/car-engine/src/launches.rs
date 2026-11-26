//! Up to eight sends waiting for their receipts at once, one in each conversation (v0.6.15-beta, P12)
//! (`engine/launches.py`; seat S7.2a2).
//!
//! Everything a send decides stays on the tick thread: the gates, the words, the sender, the one claim, the pre-send
//! look - and so does what came of it, settled in claim order. What a worker does is the long, stateless part between:
//! the bound send it was handed, called with a launch guard on a store of its own (SQLite's write lock serialises
//! that guard with every other connection, so a Pause, a Cancel or a conversation switched off that commits first
//! refuses the launch, I6) and the wait for its receipt. One worker per launch, started at the launch and joined, with
//! its store closed, before the pool is closed: no thread outlives a tick.
//!
//! This module calls only the call it is handed and opens only the store it is handed the opener of; of that store it
//! uses the launch guard and `close` alone.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

use car_machine::json::{Map, Value};
use car_machine::pyval::Py;

use crate::py::row;
use crate::seam::LaunchGuard;

/// One launch begun at least this long after the one before it.
pub const LAUNCH_SPACING: f64 = 1.0;
/// How long one look waits for a worker to finish while every worker is busy.
pub const POLL_SECONDS: f64 = 0.05;

/// The store a worker opens of its own (`open_store()`): its launch guard and `close`, nothing else.
pub trait WorkerStore: Send {
    /// `with store.submission_guard(key) as permitted:`.
    fn submission_guard(&self, key: &str, body: &mut dyn FnMut(bool) -> Value) -> Py<Value>;
    fn close(&self) -> Py<()>;
}

/// `open_store`: a store for one worker, or the exception opening it raised.
pub type Opener = Arc<dyn Fn() -> Py<Box<dyn WorkerStore>> + Send + Sync>;

/// The bound send handed to a worker: called once with the worker's launch guard.
pub type Call = Box<dyn FnOnce(&dyn LaunchGuard) -> Py<Value> + Send>;

/// The worker's own store's guard for one key.
struct WorkerGuard<'a> {
    store: &'a dyn WorkerStore,
    key: Option<String>,
}

impl LaunchGuard for WorkerGuard<'_> {
    fn enter(&self, body: &mut dyn FnMut(bool) -> Value) -> Py<Value> {
        self.store
            .submission_guard(self.key.as_deref().unwrap_or_default(), body)
    }
    fn key(&self) -> Option<&str> {
        self.key.as_deref()
    }
}

/// One send handed to a worker, and what it answered.
struct Launch<C> {
    thread: JoinHandle<()>,
    context: C,
    response: Arc<Mutex<Option<Map>>>,
}

/// A worker kept for one send, taken before its claim; freed (dropped) if the send does not go to it.
#[derive(Debug)]
pub struct Slot(());

/// At most `workers` sends waiting for their receipts at once, on the tick thread: `take` a slot before a claim,
/// `launch` the send through it, and every launch is joined and settled - in claim order - by `close`.
pub struct LaunchPool<C> {
    pub workers: usize,
    open_store: Opener,
    launches: VecDeque<Launch<C>>,
    last_start: Option<f64>,
    clock: Box<dyn Fn() -> f64>,
    sleep: Box<dyn Fn(f64)>,
}

impl<C> LaunchPool<C> {
    /// `LaunchPool(workers, open_store, settle, clock=time.monotonic, sleep=time.sleep)`.
    pub fn new(
        workers: usize,
        open_store: Opener,
        clock: Box<dyn Fn() -> f64>,
        sleep: Box<dyn Fn(f64)>,
    ) -> LaunchPool<C> {
        LaunchPool {
            workers,
            open_store,
            launches: VecDeque::new(),
            last_start: None,
            clock,
            sleep,
        }
    }

    /// `take()`: a free worker for the next send - every finished launch settled first, then, while every worker is
    /// busy, a wait outside any transaction until one is free.
    pub fn take(&mut self, settle: &mut dyn FnMut(C, Map)) -> Slot {
        self.settle_finished(settle);
        while self.running() >= self.workers {
            (self.sleep)(POLL_SECONDS);
            self.settle_finished(settle);
        }
        Slot(())
    }

    fn running(&self) -> usize {
        self.launches
            .iter()
            .filter(|launch| !launch.thread.is_finished())
            .count()
    }

    /// `_settle_finished()`: settle, in claim order, every launch from the front that has finished.
    fn settle_finished(&mut self, settle: &mut dyn FnMut(C, Map)) {
        while self
            .launches
            .front()
            .is_some_and(|launch| launch.thread.is_finished())
        {
            let Some(launch) = self.launches.pop_front() else {
                break;
            };
            settle_one(launch, settle);
        }
    }

    /// `Slot.launch(call, thread, words, key, carrying, settle=context)`: hand `call` to a worker, a launch begun at
    /// least LAUNCH_SPACING after the one before it.
    pub fn launch(&mut self, slot: Slot, call: Call, key: Option<String>, context: C) {
        let Slot(()) = slot;
        if let Some(last) = self.last_start {
            let wait = last + LAUNCH_SPACING - (self.clock)();
            if wait > 0.0 {
                (self.sleep)(wait);
            }
        }
        self.last_start = Some((self.clock)());
        let response = Arc::new(Mutex::new(None));
        let answered = Arc::clone(&response);
        let open_store = Arc::clone(&self.open_store);
        let thread = std::thread::Builder::new()
            .name("launch".into())
            .spawn(move || {
                let found = work(&open_store, call, key);
                if let Ok(mut slot) = answered.lock() {
                    *slot = Some(found);
                }
            });
        match thread {
            Ok(thread) => self.launches.push_back(Launch {
                thread,
                context,
                response,
            }),
            // `Thread.start()` raising: the send may not have gone; settled as an unknown one would be, at once.
            Err(_) => {
                let thread = std::thread::spawn(|| {});
                if let Ok(mut slot) = response.lock() {
                    *slot = Some(row(vec![("outcome", Value::from("unknown"))]));
                }
                self.launches.push_back(Launch {
                    thread,
                    context,
                    response,
                });
            }
        }
    }

    /// `__exit__`: every launch joined, then settled in claim order.
    pub fn close(mut self, settle: &mut dyn FnMut(C, Map)) {
        while let Some(launch) = self.launches.pop_front() {
            settle_one(launch, settle);
        }
    }
}

fn settle_one<C>(launch: Launch<C>, settle: &mut dyn FnMut(C, Map)) {
    let Launch {
        thread,
        context,
        response,
    } = launch;
    let _ = thread.join();
    let found = response
        .lock()
        .ok()
        .and_then(|mut slot| slot.take())
        .unwrap_or_else(|| row(vec![("outcome", Value::from("unknown"))]));
    settle(context, found);
}

/// `_work(...)`: the worker - its own store, its launch guard, the send and its receipt. A store that cannot be opened
/// launched nothing (not started); a send that raised, or answered nothing a send answers, may have gone (unknown).
fn work(open_store: &Opener, call: Call, key: Option<String>) -> Map {
    let Ok(Ok(store)) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| open_store()))
    else {
        return row(vec![
            ("outcome", Value::from("not_started")),
            ("error_code", Value::from("worker_store_unavailable")),
        ]);
    };
    let response = {
        let guard = WorkerGuard {
            store: store.as_ref(),
            key,
        };
        match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| call(&guard))) {
            Ok(Ok(Value::Object(response))) => response,
            _ => row(vec![("outcome", Value::from("unknown"))]),
        }
    };
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| store.close()));
    response
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct Fake(Arc<AtomicUsize>, bool);

    impl WorkerStore for Fake {
        fn submission_guard(&self, _key: &str, body: &mut dyn FnMut(bool) -> Value) -> Py<Value> {
            Ok(body(self.1))
        }
        fn close(&self) -> Py<()> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

    fn pool(closed: &Arc<AtomicUsize>, permitted: bool, fail: bool) -> LaunchPool<usize> {
        let closed = Arc::clone(closed);
        let opener: Opener = Arc::new(move || {
            if fail {
                Err("OSError")
            } else {
                Ok(Box::new(Fake(Arc::clone(&closed), permitted)) as Box<dyn WorkerStore>)
            }
        });
        let now = Arc::new(Mutex::new(0.0_f64));
        let read = Arc::clone(&now);
        LaunchPool::new(
            2,
            opener,
            Box::new(move || *read.lock().unwrap()),
            Box::new(move |seconds| *now.lock().unwrap() += seconds),
        )
    }

    #[test]
    fn launches_settle_in_claim_order_and_every_store_is_closed() {
        let closed = Arc::new(AtomicUsize::new(0));
        let mut pool = pool(&closed, true, false);
        let mut settled = Vec::new();
        for index in 0..4 {
            let slot = pool.take(&mut |context, response| settled.push((context, response)));
            let call: Call = Box::new(move |guard| {
                let permitted = guard.enter(&mut Value::Bool)?;
                Ok(Value::Object(row(vec![
                    ("outcome", Value::from("accepted")),
                    ("permitted", permitted),
                    ("index", Value::from(index as i64)),
                ])))
            });
            pool.launch(slot, call, Some(format!("key{index}")), index);
        }
        pool.close(&mut |context, response| settled.push((context, response)));
        let order: Vec<usize> = settled.iter().map(|(context, _)| *context).collect();
        assert_eq!(order, vec![0, 1, 2, 3]);
        assert!(
            settled
                .iter()
                .all(|(_, response)| response.get("permitted") == Some(&Value::Bool(true)))
        );
        assert_eq!(closed.load(Ordering::SeqCst), 4);
    }

    #[test]
    fn a_store_that_cannot_open_launches_nothing_and_a_raise_may_have_gone() {
        let closed = Arc::new(AtomicUsize::new(0));
        let mut pool = pool(&closed, true, true);
        let slot = pool.take(&mut |_, _| {});
        pool.launch(slot, Box::new(|_| Ok(Value::Null)), None, 0);
        let mut found = Vec::new();
        pool.close(&mut |_, response| found.push(response));
        assert_eq!(
            found[0].get("error_code"),
            Some(&Value::from("worker_store_unavailable"))
        );
        let mut pool = self::pool(&closed, false, false);
        let slot = pool.take(&mut |_, _| {});
        pool.launch(slot, Box::new(|_| Err("RuntimeError")), None, 1);
        let slot = pool.take(&mut |_, _| {});
        pool.launch(slot, Box::new(|_| Ok(Value::from("not a dict"))), None, 2);
        let mut found = Vec::new();
        pool.close(&mut |_, response| found.push(response));
        assert!(
            found
                .iter()
                .all(|response| response.get("outcome") == Some(&Value::from("unknown")))
        );
    }
}
