//! A stack for the threads that hold a parsed document.
//!
//! Python's `json.loads` takes a document nested nearly 17,000 levels deep (`json::depth`), and the decoder here reads
//! it with a list of its own, so reading costs no stack. Dropping, comparing or copying the value it returns does:
//! the compiler's drop glue spends about 150 bytes per level, and a value of 17,000 levels needs about 3 MB where a
//! thread has 2 MB (Windows gives a program's first thread 1 MB). A thread that reads files, Codex's lines or a
//! caller's text therefore runs on [`DEEP_STACK_BYTES`]: Windows reserves the address space and commits a page only
//! when it is touched, so the size costs nothing a shallow document would use.

use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

/// The stack of a thread that holds parsed documents: 64 MiB, twenty times the deepest value's drop.
pub const DEEP_STACK_BYTES: usize = 64 * 1024 * 1024;

/// `body` on a thread of [`DEEP_STACK_BYTES`], waited for; its result, or its panic raised again here. Where the thread
/// cannot be made, `body` runs on this one.
pub fn run_deep<R: Send>(body: impl FnOnce() -> R + Send) -> R {
    let cell = Mutex::new(Some(body));
    let run = || {
        let body = cell.lock().ok().and_then(|mut held| held.take());
        body.map(|body| body())
    };
    let outcome = std::thread::scope(|scope| {
        match std::thread::Builder::new()
            .name("deep-stack".into())
            .stack_size(DEEP_STACK_BYTES)
            .spawn_scoped(scope, run)
        {
            Ok(handle) => handle.join(),
            Err(_) => Ok(None),
        }
    });
    match outcome {
        Ok(Some(answer)) => answer,
        Ok(None) => {
            let body = cell
                .lock()
                .ok()
                .and_then(|mut held| held.take())
                .expect("the body was not run, so it is still held");
            body()
        }
        Err(panic) => std::panic::resume_unwind(panic),
    }
}

/// `std::thread::spawn` with [`DEEP_STACK_BYTES`]; where that thread cannot be made, one of the ordinary size.
pub fn spawn_deep<T: Send + 'static>(body: impl FnOnce() -> T + Send + 'static) -> JoinHandle<T> {
    let cell = Arc::new(Mutex::new(Some(body)));
    let held = Arc::clone(&cell);
    let run = move || {
        let body = held.lock().ok().and_then(|mut found| found.take());
        body.expect("the body runs once")()
    };
    match std::thread::Builder::new()
        .name("deep-stack".into())
        .stack_size(DEEP_STACK_BYTES)
        .spawn(run)
    {
        Ok(handle) => handle,
        Err(_) => std::thread::spawn(move || {
            let body = cell.lock().ok().and_then(|mut found| found.take());
            body.expect("the body was not run, so it is still held")()
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compat::{LOADS_LIST_LEVELS, LOADS_OBJECT_LEVELS, loads};

    #[test]
    fn a_value_as_deep_as_python_takes_is_read_and_dropped() {
        let answer = run_deep(|| {
            let lists =
                "[".repeat(LOADS_LIST_LEVELS as usize) + &"]".repeat(LOADS_LIST_LEVELS as usize);
            let objects = "{\"a\":".repeat(LOADS_OBJECT_LEVELS as usize)
                + "0"
                + &"}".repeat(LOADS_OBJECT_LEVELS as usize);
            (loads(&lists).is_ok(), loads(&objects).is_ok())
        });
        assert_eq!(answer, (true, true));
    }

    #[test]
    fn a_panic_comes_out_of_the_thread() {
        let caught = std::panic::catch_unwind(|| run_deep(|| -> u8 { panic!("inside") }));
        assert!(caught.is_err());
        assert_eq!(spawn_deep(|| 7).join().ok(), Some(7));
    }
}
