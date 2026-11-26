//! `runtime/toasts.py`: notifications raised from the watcher's own thread, one at a time.
//!
//! Showing one runs PowerShell and can take many seconds. The engine only ever puts an event on this queue; a
//! thread of its own shows them one at a time and ends after `IDLE_SECONDS` with nothing to show. A full queue drops
//! the event and says so: a notification must never delay or decide a recovery.

use std::collections::VecDeque;
use std::sync::{Arc, Condvar, Mutex, PoisonError};
use std::time::{Duration, Instant};

use car_machine::json::Map;

use crate::fail::{Res, guarded, quietly};

/// `queue.Queue(maxsize=64)`.
pub const QUEUE_SIZE: usize = 64;
/// `self._queue.get(timeout=30)`: how long the thread waits for the next one before it ends.
pub const IDLE_SECONDS: f64 = 30.0;

/// What shows one notification: the event and its detail; whether it was shown, or what it raised.
pub type Show = Arc<dyn Fn(&str, &Map) -> Res<bool> + Send + Sync>;
/// A line for the watcher's log.
pub type Log = Arc<dyn Fn(&str) + Send + Sync>;

struct Queue {
    waiting: VecDeque<(String, Map)>,
    alive: bool,
}

struct Shared {
    queue: Mutex<Queue>,
    ready: Condvar,
    show: Show,
    log: Log,
    idle: Duration,
}

/// `Toasts(show, logger)`: notifications off the tick path.
#[derive(Clone)]
pub struct Toasts {
    shared: Arc<Shared>,
}

impl Toasts {
    pub fn new(show: Show, log: Log) -> Toasts {
        Toasts::with_idle(show, log, IDLE_SECONDS)
    }

    /// The same, with the thread's idle wait of a test's own.
    pub fn with_idle(show: Show, log: Log, idle_seconds: f64) -> Toasts {
        Toasts {
            shared: Arc::new(Shared {
                queue: Mutex::new(Queue {
                    waiting: VecDeque::new(),
                    alive: false,
                }),
                ready: Condvar::new(),
                show,
                log,
                idle: Duration::from_secs_f64(idle_seconds.max(0.0)),
            }),
        }
    }

    /// `toasts(event, detail)`: queued, or dropped when the queue is full - said in the log, and False.
    pub fn call(&self, event: &str, detail: &Map) -> bool {
        let mut queue = self
            .shared
            .queue
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if queue.waiting.len() >= QUEUE_SIZE {
            drop(queue);
            (self.shared.log)(&format!("notification queue full; {event} dropped"));
            return false;
        }
        queue.waiting.push_back((event.to_owned(), detail.clone()));
        self.shared.ready.notify_one();
        if !queue.alive {
            queue.alive = true;
            let shared = Arc::clone(&self.shared);
            // A notice's detail is a document the engine made: the thread holds it on a deep stack (car-machine `stack`).
            let started = car_machine::stack::try_spawn_deep("toasts", move || run(&shared));
            if started.is_err() {
                // No thread could be had: the next notice tries again (Python's start() raising propagates to the
                // engine's notify call, which counts a failed notifier).
                queue.alive = false;
            }
        }
        true
    }

    /// How many wait to be shown now (for tests).
    pub fn waiting(&self) -> usize {
        self.shared
            .queue
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .waiting
            .len()
    }
}

/// `_run`: one at a time until none came for the idle wait; a notice that raised (or panicked, D15) is one line.
fn run(shared: &Shared) {
    loop {
        let next = {
            let mut queue = shared.queue.lock().unwrap_or_else(PoisonError::into_inner);
            let until = Instant::now() + shared.idle;
            loop {
                if let Some(next) = queue.waiting.pop_front() {
                    break Some(next);
                }
                let now = Instant::now();
                if now >= until {
                    queue.alive = false;
                    break None;
                }
                queue = shared
                    .ready
                    .wait_timeout(queue, until - now)
                    .map(|(guard, _)| guard)
                    .unwrap_or_else(|poisoned| poisoned.into_inner().0);
            }
        };
        let Some((event, detail)) = next else {
            return;
        };
        if guarded(|| {
            crate::trip::wire("worker");
            (shared.show)(&event, &detail)
        })
        .is_err()
        {
            quietly(|| (shared.log)(&format!("notification failed ({event})")));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The panic test's variable is process-wide: the toasts tests run one at a time.
    static SERIAL: Mutex<()> = Mutex::new(());

    /// P6-DESIGN 1.3: a panic inside the worker (the panic test's wire, `CAR_CORE_PANIC=worker`) costs that notice and
    /// nothing more - it is said as a failed notification and the next notice is shown by the same worker.
    #[cfg(feature = "panic-test")]
    #[test]
    fn a_panic_in_the_worker_costs_one_notice() {
        let _serial = SERIAL.lock().unwrap_or_else(PoisonError::into_inner);
        // SAFETY: this test alone reads the variable in this binary.
        unsafe { std::env::set_var("CAR_CORE_PANIC", "worker") };
        let lines: Arc<Mutex<Vec<String>>> = Arc::default();
        let shown: Arc<Mutex<Vec<String>>> = Arc::default();
        let seen = Arc::clone(&shown);
        let show: Show = Arc::new(move |event, _| {
            seen.lock().unwrap().push(event.to_owned());
            Ok(true)
        });
        let log_lines = Arc::clone(&lines);
        let log: Log = Arc::new(move |line| log_lines.lock().unwrap().push(line.to_owned()));
        let toasts = Toasts::with_idle(show, log, 1.0);
        assert!(toasts.call("first", &Map::new()));
        assert!(toasts.call("second", &Map::new()));
        let until = Instant::now() + Duration::from_secs(10);
        while shown.lock().unwrap().is_empty() && Instant::now() < until {
            std::thread::yield_now();
        }
        assert_eq!(*shown.lock().unwrap(), ["second"]);
        assert_eq!(*lines.lock().unwrap(), ["notification failed (first)"]);
        // SAFETY: as above.
        unsafe { std::env::remove_var("CAR_CORE_PANIC") };
    }

    #[test]
    fn a_full_queue_drops_and_says_so_and_a_failure_is_one_line() {
        let _serial = SERIAL.lock().unwrap_or_else(PoisonError::into_inner);
        let lines: Arc<Mutex<Vec<String>>> = Arc::default();
        let gate: Arc<(Mutex<bool>, Condvar)> = Arc::default();
        let held = Arc::clone(&gate);
        let shown: Arc<Mutex<Vec<String>>> = Arc::default();
        let seen = Arc::clone(&shown);
        let show: Show = Arc::new(move |event, _| {
            let (open, turn) = &*held;
            let mut open = open.lock().unwrap();
            while !*open {
                open = turn.wait(open).unwrap();
            }
            drop(open);
            seen.lock().unwrap().push(event.to_owned());
            if event == "boom" {
                panic!("OSError: no");
            }
            Ok(true)
        });
        let log_lines = Arc::clone(&lines);
        let log: Log = Arc::new(move |line| log_lines.lock().unwrap().push(line.to_owned()));
        let toasts = Toasts::with_idle(show, log, 0.2);
        assert!(toasts.call("boom", &Map::new()));
        // The thread takes "boom" and waits at the gate; 64 more fill the queue, the next is dropped.
        while toasts.waiting() > 0 {
            std::thread::yield_now();
        }
        for _ in 0..QUEUE_SIZE {
            assert!(toasts.call("x", &Map::new()));
        }
        assert!(!toasts.call("dropped", &Map::new()));
        *gate.0.lock().unwrap() = true;
        gate.1.notify_all();
        while shown.lock().unwrap().len() < QUEUE_SIZE + 1 {
            std::thread::yield_now();
        }
        std::thread::sleep(Duration::from_millis(400));
        let lines = lines.lock().unwrap().clone();
        assert_eq!(
            lines,
            vec![
                "notification queue full; dropped dropped".to_owned(),
                "notification failed (boom)".to_owned()
            ]
        );
        // The thread ended once idle; a new notice starts another.
        assert!(toasts.call("again", &Map::new()));
        while shown.lock().unwrap().len() < QUEUE_SIZE + 2 {
            std::thread::yield_now();
        }
    }
}
