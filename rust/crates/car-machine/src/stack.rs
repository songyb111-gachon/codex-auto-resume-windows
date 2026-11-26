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

/// `body` on a thread of [`DEEP_STACK_BYTES`], waited for; its result, or its panic raised again here. Where that thread
/// cannot be made, one of the ordinary size runs it (see [`spawn_deep`]).
///
/// `body` is `'static` and so is its answer: `std::thread::scope` would take a borrowing body, but it is `#[track_caller]`,
/// and a panic location is an absolute source path that the advanced workspace's build does not remap for a crate outside
/// its folder (the edition rebuild check scans the standard binaries for the builder's profile path).
pub fn run_deep<R: Send + 'static>(body: impl FnOnce() -> R + Send + 'static) -> R {
    match spawn_deep(body).join() {
        Ok(answer) => answer,
        Err(panic) => std::panic::resume_unwind(panic),
    }
}

/// `std::thread::spawn` with [`DEEP_STACK_BYTES`]; where that thread cannot be made, one of the ordinary size.
pub fn spawn_deep<T: Send + 'static>(body: impl FnOnce() -> T + Send + 'static) -> JoinHandle<T> {
    let cell = Arc::new(Mutex::new(Some(body)));
    let held = Arc::clone(&cell);
    let run = move || {
        let Some(body) = held.lock().ok().and_then(|mut found| found.take()) else {
            std::process::abort()
        };
        body()
    };
    match std::thread::Builder::new()
        .name("deep-stack".into())
        .stack_size(DEEP_STACK_BYTES)
        .spawn(run)
    {
        Ok(handle) => handle,
        Err(_) => std::thread::spawn(move || {
            let Some(body) = cell.lock().ok().and_then(|mut found| found.take()) else {
                std::process::abort()
            };
            body()
        }),
    }
}

/// [`spawn_deep`] for a thread with a name of its own that answers itself when no thread can be had: the deep one, else
/// one of the ordinary size, else the error of that last try (car-watcher's launcher and notification threads).
pub fn try_spawn_deep<T: Send + 'static>(
    name: &str,
    body: impl FnOnce() -> T + Send + 'static,
) -> std::io::Result<JoinHandle<T>> {
    let cell = Arc::new(Mutex::new(Some(body)));
    let held = Arc::clone(&cell);
    let run = move || {
        let Some(body) = held.lock().ok().and_then(|mut found| found.take()) else {
            std::process::abort()
        };
        body()
    };
    match std::thread::Builder::new()
        .name(name.into())
        .stack_size(DEEP_STACK_BYTES)
        .spawn(run)
    {
        Ok(handle) => Ok(handle),
        Err(_) => std::thread::Builder::new()
            .name(name.into())
            .spawn(move || {
                let Some(body) = cell.lock().ok().and_then(|mut found| found.take()) else {
                    std::process::abort()
                };
                body()
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

    #[test]
    fn a_named_deep_thread_holds_the_deepest_value_and_keeps_its_name() {
        let handle = try_spawn_deep("named", || {
            let lists =
                "[".repeat(LOADS_LIST_LEVELS as usize) + &"]".repeat(LOADS_LIST_LEVELS as usize);
            (
                std::thread::current().name().map(str::to_owned),
                loads(&lists).is_ok(),
            )
        });
        let answer = handle.ok().and_then(|handle| handle.join().ok());
        assert_eq!(answer, Some((Some("named".to_owned()), true)));
    }
}
