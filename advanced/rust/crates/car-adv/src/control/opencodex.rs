//! `control/opencodex.py` (seat S7.3a): Open Codex on a notice (v0.6.18; v0.6.20: the notice itself, no button) - a
//! click on a notice about one conversation shows it in the Codex app. An action: core never asks it anything. While
//! it stands on and Windows has a handler for `codex:` - read, never written, from Software\Classes\codex under
//! HKEY_CURRENT_USER, then HKEY_LOCAL_MACHINE, a key marked "URL Protocol" - the icon's surface says so
//! (`surfaces::notice_view`). `handler_registered` is also what `engine/opentarget`'s world asks (seam_p7's
//! `OpenCodex`, which this replaces).

use std::sync::{Arc, OnceLock};
use std::time::Instant;

use car_config::Paths;

use crate::capabilities::Code;

pub const CAPABILITY: &str = "open_codex_button";
pub const PROTOCOL_KEY: &str = r"Software\Classes\codex";
pub const PROTOCOL_VALUE: &str = "URL Protocol";
/// How long one answer of the registry is reused, in seconds.
pub const REUSE: f64 = 60.0;
/// `winreg.KEY_READ`.
const KEY_READ: u32 = 0x20019;

/// `read(root, path, value)`: Ok(true) where the key holds the value; Err where the read raised.
pub type ReadFn = Arc<dyn Fn(&str, &str, &str) -> Result<bool, ()> + Send + Sync>;
/// `clock()`: a monotonic second count.
pub type ClockFn = Arc<dyn Fn() -> f64 + Send + Sync>;

/// `_registered(read)`.
fn registered(read: &dyn Fn(&str, &str, &str) -> Result<bool, ()>) -> bool {
    ["HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"]
        .into_iter()
        .any(|root| matches!(read(root, PROTOCOL_KEY, PROTOCOL_VALUE), Ok(true)))
}

/// `_read_registry(root, path, value)`: the key opened for KEY_READ alone, the value queried, the key closed.
#[allow(clippy::result_unit_err)] // the reference raises; what it raises is not read
pub fn read_registry(root: &str, path: &str, value: &str) -> Result<bool, ()> {
    use car_platform::registry::{Open, Root, WinRegistry};
    let root = match root {
        "HKEY_CURRENT_USER" => Root::CurrentUser,
        "HKEY_LOCAL_MACHINE" => Root::LocalMachine,
        _ => return Err(()),
    };
    let registry = WinRegistry::current_user();
    let key = Open::read(&registry, root, path, KEY_READ).map_err(|_| ())?;
    key.query(value).map_err(|_| ())?;
    Ok(true)
}

/// `handler_registered(read=None)`: whether Windows has a handler for `codex:` links; False where nothing can be read.
pub fn handler_registered(read: Option<&ReadFn>) -> bool {
    match read {
        Some(read) => registered(read.as_ref()),
        None => registered(&read_registry),
    }
}

fn monotonic() -> f64 {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_secs_f64()
}

/// `OpenCodexButton(paths, read=None, clock=None)`: open_codex_button's code.
pub struct OpenCodexButton {
    pub paths: Paths,
    read: Option<ReadFn>,
    clock: Option<ClockFn>,
    known: Option<(f64, bool)>,
}

impl OpenCodexButton {
    pub fn new(paths: &Paths, read: Option<ReadFn>, clock: Option<ClockFn>) -> OpenCodexButton {
        OpenCodexButton {
            paths: paths.clone(),
            read,
            clock,
            known: None,
        }
    }

    /// `available()`: whether Windows can open a `codex:` link here now, reused for REUSE seconds.
    pub fn available(&mut self) -> bool {
        let now = self.clock.as_ref().map_or_else(monotonic, |clock| clock());
        if let Some((at, answer)) = self.known
            && 0.0 <= now - at
            && now - at < REUSE
        {
            return answer;
        }
        let answer = handler_registered(self.read.as_ref());
        self.known = Some((now, answer));
        answer
    }
}

impl Code for OpenCodexButton {
    fn as_any(&mut self) -> Option<&mut dyn std::any::Any> {
        Some(self)
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(OpenCodexButton::new(paths, None, None)))
}
