//! `config.py`'s three settings functions - `load_settings`, `save_settings`, `update_settings` (cut C2 puts them here,
//! so car-config never loads settings).
//!
//! Each is a thin adapter over the settings module: one reader and one writer. A save and an update first make sure
//! the home's own folders are there (`Paths.ensure()`, car-config's, handed in as [`Home`]), and turn a settings
//! refusal into the ConfigError the callers catch, with its sentence.

use std::path::PathBuf;

use car_machine::json::{Map, Str, Value};

use super::os::Os;
use super::{SettingsError, load, save, update};

/// What the three functions need of car-config's `Paths`: where the settings file is, and `ensure()`.
pub trait Home {
    /// `paths.settings_file`.
    fn settings_file(&self) -> PathBuf;
    /// `paths.ensure()`: Ok, or the exception it raised.
    fn ensure(&self) -> Result<(), ConfigFailure>;
}

/// What one of the three raises.
#[derive(Clone, Debug, PartialEq)]
pub enum ConfigFailure {
    /// `ConfigError(str(exc))`: a settings refusal, or `ensure()`'s own.
    ConfigError(Str),
    /// Any other exception, by class (`RecursionError` from a file nested too deep, an OSError of a folder).
    Raised(&'static str),
}

impl ConfigFailure {
    pub fn class(&self) -> &'static str {
        match self {
            ConfigFailure::ConfigError(_) => "ConfigError",
            ConfigFailure::Raised(class) => class,
        }
    }

    pub fn message(&self) -> Str {
        match self {
            ConfigFailure::ConfigError(text) => text.clone(),
            ConfigFailure::Raised(_) => Str::default(),
        }
    }
}

fn wrapped(error: SettingsError) -> ConfigFailure {
    if error.is_settings_error() {
        ConfigFailure::ConfigError(error.message())
    } else {
        ConfigFailure::Raised(error.class())
    }
}

/// `load_settings(paths)`: the user's settings, the defaults for anything missing or malformed.
pub fn load_settings(os: &dyn Os, home: &dyn Home) -> Result<Map, ConfigFailure> {
    load(os, &home.settings_file()).map_err(|error| ConfigFailure::Raised(error.class()))
}

/// `save_settings(paths, values)`: persist a complete settings mapping through the shared validator.
pub fn save_settings(os: &dyn Os, home: &dyn Home, values: &Value) -> Result<Map, ConfigFailure> {
    home.ensure()?;
    save(os, &home.settings_file(), values).map_err(wrapped)
}

/// `update_settings(paths, changes)`: merge an explicit edit, leaving every field the caller did not name alone.
pub fn update_settings(
    os: &dyn Os,
    home: &dyn Home,
    changes: &Value,
) -> Result<Map, ConfigFailure> {
    home.ensure()?;
    update(os, &home.settings_file(), changes).map_err(wrapped)
}
