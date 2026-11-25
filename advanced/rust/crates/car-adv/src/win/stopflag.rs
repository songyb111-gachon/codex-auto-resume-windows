//! `win/stopflag.py`: whether the watcher's stop event was signalled, seen from the launcher that supervises it
//! (crash_restart, v0.6.19).
//!
//! The supervisor holds one handle of its own to the watcher's named, manual-reset stop event from the start
//! ([`StopFlag::hold`]) and after the watcher ends looks at it without waiting ([`StopFlag::signalled`]), or waits on
//! it instead of sleeping ([`StopFlag::wait`]). Nothing is signalled or reset here: the event is only held and looked
//! at. The Windows calls are car-platform's `wake::EventKernel` (D3); a test hands in a stand-in.

use car_machine::domain::errors::AdapterError;
use car_platform::paths::pathlib_text;
use car_platform::sync::StopEvent;
use car_platform::wake::{EventKernel, Handle, Raised};

pub const WAIT_OBJECT_0: u32 = 0;
pub const SYNCHRONIZE: u32 = 0x0010_0000;

/// `event_name(paths)`: the watcher's stop event's name for this installation, as core names it
/// (`StopEvent(str(paths.state_dir))`: the folder as pathlib writes it).
pub fn event_name(state_dir: &str) -> Result<String, AdapterError> {
    StopEvent::new(&pathlib_text(state_dir)).map(|event| event.name.clone())
}

/// Python's `min(a, b)`: the first unless the second is smaller (a NaN first stays).
fn py_min(a: f64, b: f64) -> f64 {
    if b < a { b } else { a }
}

/// Python's `max(a, b)`: the first unless the second is larger.
fn py_max(a: f64, b: f64) -> f64 {
    if b > a { b } else { a }
}

fn bounded(seconds: f64) -> f64 {
    py_max(0.0, py_min(seconds, 60.0))
}

/// The stop event of one installation, held and looked at.
pub struct StopFlag {
    name: String,
    kernel: Box<dyn EventKernel>,
    handle: Option<Handle>,
}

impl StopFlag {
    /// `StopFlag(paths, kernel=...)`, the event named for `state_dir`.
    pub fn new(state_dir: &str, kernel: Box<dyn EventKernel>) -> Result<StopFlag, AdapterError> {
        Ok(StopFlag::named(event_name(state_dir)?, kernel))
    }

    /// A flag on an event of the given name (the harness's stand-in names it).
    pub fn named(name: String, kernel: Box<dyn EventKernel>) -> StopFlag {
        StopFlag {
            name,
            kernel,
            handle: None,
        }
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    /// Hold a handle to the event from now on, made where none exists yet. Whether one is held.
    pub fn hold(&mut self) -> bool {
        if self.handle.is_some() {
            return true;
        }
        self.handle = self
            .kernel
            .create_event(true, false, &self.name)
            .ok()
            .filter(|handle| *handle != 0);
        self.handle.is_some()
    }

    /// Whether a stop was asked: the held handle looked at without waiting - or, where none is held, the event
    /// opened by name, looked at and closed again.
    pub fn signalled(&mut self) -> bool {
        self.look().unwrap_or(false)
    }

    fn look(&mut self) -> Result<bool, Raised> {
        if let Some(handle) = self.handle {
            return Ok(self.kernel.wait_for_single_object(handle, 0)? == WAIT_OBJECT_0);
        }
        let handle = self.kernel.open_event(SYNCHRONIZE, false, &self.name)?;
        if handle == 0 {
            return Ok(false);
        }
        let seen = self.kernel.wait_for_single_object(handle, 0);
        self.kernel.close_handle(handle)?;
        Ok(seen? == WAIT_OBJECT_0)
    }

    /// Wait up to `seconds` for a stop: True where one was asked by then. With no handle held, the seconds pass and
    /// what is open by name is looked at once.
    pub fn wait(&mut self, seconds: f64) -> bool {
        if let Some(handle) = self.handle {
            let millis = (bounded(seconds) * 1000.0) as u32;
            if let Ok(answer) = self.kernel.wait_for_single_object(handle, millis) {
                return answer == WAIT_OBJECT_0;
            }
        }
        std::thread::sleep(std::time::Duration::from_secs_f64(bounded(seconds)));
        self.signalled()
    }

    pub fn release(&mut self) {
        if let Some(handle) = self.handle {
            let _ = self.kernel.close_handle(handle);
        }
        self.handle = None;
    }
}

#[cfg(test)]
mod tests {
    use super::{bounded, py_max, py_min};

    #[test]
    fn the_bounds_are_python_s_min_and_max() {
        assert!(py_min(f64::NAN, 60.0).is_nan());
        assert_eq!(py_max(0.0, f64::NAN), 0.0);
        assert_eq!(bounded(f64::NAN), 0.0);
        assert_eq!(bounded(90.0), 60.0);
        assert_eq!(bounded(-1.0), 0.0);
    }
}
