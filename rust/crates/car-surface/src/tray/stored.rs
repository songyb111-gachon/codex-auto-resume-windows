//! `ui/tray/stored.py`: what was stored since - the settings the icon reads for itself, read again only when the
//! file's stamp changed, so a language or a theme chosen a moment ago is the popup's and the menu's at once, and a
//! Reduce motion chosen a moment ago stills the icon within a second.

use car_machine::json::{Map, Value};
use car_words::l10n::Environ;

use crate::popup::words::vocabulary;
use crate::py;
use crate::seam::{Raised, StoredSettings, TraySurface};

/// The classes Python's `except OSError` catches.
pub const OS_ERRORS: [&str; 17] = [
    "OSError",
    "FileNotFoundError",
    "FileExistsError",
    "PermissionError",
    "NotADirectoryError",
    "IsADirectoryError",
    "TimeoutError",
    "InterruptedError",
    "BlockingIOError",
    "ChildProcessError",
    "ProcessLookupError",
    "ConnectionError",
    "BrokenPipeError",
    "ConnectionAbortedError",
    "ConnectionRefusedError",
    "ConnectionResetError",
    "WindowsError",
];

/// Where the icon's languages come from: the process environment and the Windows preferred UI languages.
pub struct Languages<'a> {
    pub environ: Environ<'a>,
    pub windows: &'a dyn Fn() -> Vec<String>,
}

/// `StoredMixin`'s own state: the file's last stamp, what it held then, and whether a failed read was said.
#[derive(Clone, Debug, Default)]
pub struct Stored {
    pub stamp: Option<(i128, u64)>,
    pub values: Option<Map>,
    pub motion_read_failed: bool,
}

impl Stored {
    /// `_stored_settings()`: the stored settings through the control layer, read again only when the file changed;
    /// None when the control layer cannot say. Its errors are the reference's: the read's and `dict()`'s, and
    /// anything but an OSError from the path or the stamp.
    pub fn stored_settings(&mut self, control: &dyn StoredSettings) -> Result<Option<Map>, Raised> {
        if !control.has_get_settings() {
            return Ok(None);
        }
        let mut stamp = None;
        if let Some(path) = control.settings_path() {
            match path.and_then(|path| control.stat(&path)) {
                Ok(found) => stamp = Some(found),
                Err(raised) if OS_ERRORS.contains(&raised.class.as_str()) => stamp = None,
                Err(raised) => return Err(raised),
            }
        }
        if stamp.is_none() || stamp != self.stamp || self.values.is_none() {
            let read = control.get_settings()?;
            self.values = Some(py::dict(&read).map_err(Raised::new)?);
            self.stamp = stamp;
        }
        Ok(self.values.clone())
    }

    /// `_adopt_settings()`: speak the stored Interface language and draw in the stored Theme from this opening on.
    /// An unreadable file costs the new words, nothing else: one line in the log.
    pub fn adopt_settings(
        &mut self,
        control: &dyn StoredSettings,
        surface: &dyn TraySurface,
        languages: &Languages,
    ) {
        let outcome = (|| -> Result<(), Raised> {
            let Some(values) = self.stored_settings(control)? else {
                return Ok(());
            };
            surface.adopt_settings(&values)?;
            let language = values
                .get("interface_language")
                .cloned()
                .unwrap_or(Value::Null);
            let strings = vocabulary(&language, languages.environ, languages.windows);
            let changed = !car_machine::pyval::eq(
                &Value::Object(strings.clone()),
                &Value::Object(surface.strings()),
            );
            if changed {
                surface.set_strings(strings);
            }
            Ok(())
        })();
        if let Err(raised) = outcome {
            surface.log(&format!("tray settings read failed ({})", raised.class));
        }
    }

    /// `_adopt_reduce_motion(tray_popup)`: take up the stored Reduce motion on the tick that decides whether the icon
    /// may move; an unreadable file keeps the setting there is, and is said once until it reads again.
    pub fn adopt_reduce_motion(&mut self, control: &dyn StoredSettings, surface: &dyn TraySurface) {
        let values = match self.stored_settings(control) {
            Ok(values) => values,
            Err(raised) => {
                if !self.motion_read_failed {
                    self.motion_read_failed = true;
                    surface.log(&format!("tray settings read failed ({})", raised.class));
                }
                return;
            }
        };
        self.motion_read_failed = false;
        if let Some(values) = values {
            surface.set_reduce_motion(values.get("reduce_motion").unwrap_or(&Value::Null));
        }
    }
}
