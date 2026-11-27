//! What the pairing, the transport and the registry's checks ask of Windows, as one trait.
//!
//! The reference reads the process list (`win/kernel.processes_named`), who holds a file open
//! (`win/inventory.resource_users`), a live process's identity (`win/kernel.process_identity`), a file's Authenticode
//! signer (`win/authenticode.signer`), its own environment, its own pid and the monotonic clock. [`Platform`] answers
//! them from car-platform (D3: every Windows call is made there); a test or the differential harness answers them
//! from a stand-in, so a diff never reads this machine's processes or signatures.
//!
//! Rows, holders and identities are the dicts the reference passes around (`{"pid", "parent", "path", "created",
//! "family"}`, `{"pid", "created"}`, `{"pid", "path", "created"}`): the pairing reads them as Python reads a dict,
//! type checks and all, so a stand-in may hand it anything the reference would meet.

use std::sync::{Arc, OnceLock};
use std::time::Instant;

use car_machine::json::{Map, Str, Value};

use crate::errors::{Error, Result};

/// The outside world of `codex/pairing.py`, `codex/transport.py` and `compat/probes.py`.
pub trait System: Send + Sync {
    /// `os.environ.get(name)` (Windows names are not case-sensitive).
    fn env(&self, name: &str) -> Option<String>;
    /// `processes_named(names, families)`: every process of a file called one of `names`, and every one of a package
    /// family in `families`. An `AdapterError`, `OSError` or `ValueError` where the list cannot be made.
    fn processes_named(&self, names: &[&str], families: &[&str]) -> Result<Vec<Value>>;
    /// `resource_users(*paths)`: who holds any of `paths` open, `{"pid", "created"}` each.
    fn resource_users(&self, paths: &[String]) -> Result<Vec<Value>>;
    /// `process_identity(pid)`: `{"pid", "path" (lower case), "created"}` of a live process.
    fn process_identity(&self, pid: &Value) -> Result<Value>;
    /// `authenticode.signer(path)`: the subject common name, `Err(Some(code))` an AdapterError, `Err(None)` any other
    /// exception.
    fn signer(&self, path: &str) -> std::result::Result<String, Option<&'static str>>;
    /// `os.getpid()`.
    fn own_pid(&self) -> i64;
    /// `time.monotonic()`.
    fn monotonic(&self) -> f64;
    /// `str(Path(text).resolve())`, or None where it raises (OSError, ValueError, RuntimeError).
    fn resolve(&self, text: &str) -> Option<String>;
    /// `win/inventory.restart_manager_available()`.
    fn restart_manager_available(&self) -> bool;
    /// `package_roots(family)` (`win/kernel.py`, v0.6.26 final): the folder of every package of the family installed
    /// for this account; an `AdapterError` or `OSError` where the package manager cannot answer. A stand-in names the
    /// folders of its own world, never this PC's (`tests/no_real_codex.py` `_guard_packages`).
    fn package_roots(&self, family: &str) -> Result<Vec<String>>;
}

/// A dict of the given pairs, in order.
pub fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

fn text_or_null(value: Option<&str>) -> Value {
    value.map_or(Value::Null, Value::from)
}

/// Windows itself, through car-platform.
#[derive(Debug)]
pub struct Platform {
    pub config: car_config::Os,
}

impl Platform {
    /// This process's working directory and the link probe; long paths as Windows' own setting says nothing of
    /// (the reference's `realpath` takes the folder as it is).
    pub fn new() -> Platform {
        Platform {
            config: car_config::Os::here(false, Arc::new(Links)),
        }
    }
}

impl Default for Platform {
    fn default() -> Platform {
        Platform::new()
    }
}

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &std::path::Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

fn started() -> &'static Instant {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now)
}

impl System for Platform {
    fn env(&self, name: &str) -> Option<String> {
        std::env::var_os(name).map(|value| value.to_string_lossy().into_owned())
    }

    fn processes_named(&self, names: &[&str], families: &[&str]) -> Result<Vec<Value>> {
        let rows = car_platform::kernel::processes_named(names, families)?;
        Ok(rows
            .into_iter()
            .map(|row| {
                object(vec![
                    ("pid", Value::from(i64::from(row.pid))),
                    ("parent", Value::from(i64::from(row.parent))),
                    ("path", text_or_null(row.path.as_deref())),
                    (
                        "created",
                        row.created.map_or(Value::Null, |at| Value::from(at as i64)),
                    ),
                    ("family", text_or_null(row.family.as_deref())),
                ])
            })
            .collect())
    }

    fn resource_users(&self, paths: &[String]) -> Result<Vec<Value>> {
        let names: Vec<&str> = paths.iter().map(String::as_str).collect();
        let holders = car_platform::inventory::resource_users(&names)?;
        Ok(holders
            .into_iter()
            .map(|holder| {
                object(vec![
                    ("pid", Value::from(i64::from(holder.pid))),
                    ("created", Value::from(holder.created as i64)),
                ])
            })
            .collect())
    }

    fn process_identity(&self, pid: &Value) -> Result<Value> {
        let Value::Int(number) = pid else {
            // ctypes refuses anything but an int for a DWORD.
            return Err(Error::Python("ArgumentError"));
        };
        let Some(pid) = number.as_i64().and_then(|n| u32::try_from(n).ok()) else {
            return Err(Error::Adapter("process_identity_unavailable"));
        };
        let held = car_platform::kernel::process_identity(pid)?;
        Ok(object(vec![
            ("pid", Value::from(i64::from(held.pid))),
            ("path", Value::from(held.path.as_str())),
            ("created", Value::from(held.created as i64)),
        ]))
    }

    fn signer(&self, path: &str) -> std::result::Result<String, Option<&'static str>> {
        car_platform::authenticode::signer(std::path::Path::new(path))
            .map_err(|refused| Some(refused.0))
    }

    fn own_pid(&self) -> i64 {
        i64::from(std::process::id())
    }

    fn monotonic(&self) -> f64 {
        started().elapsed().as_secs_f64() + 1.0
    }

    fn resolve(&self, text: &str) -> Option<String> {
        if text.contains('\0') {
            // gh-106242: a path Windows cannot be asked about is made absolute and normal, never resolved, and never
            // raises (3.13.15's `realpath`).
            let normal = car_config::winpath::normpath(text);
            let absolute = if car_config::winpath::isabs(&normal) {
                normal
            } else {
                car_config::winpath::join(&self.config.cwd, &normal)
            };
            return Some(car_config::winpath::path_str(&absolute));
        }
        self.config
            .resolve(text)
            .ok()
            .map(|found| car_config::winpath::path_str(&found))
    }

    fn restart_manager_available(&self) -> bool {
        car_platform::inventory::restart_manager_available()
    }

    fn package_roots(&self, family: &str) -> Result<Vec<String>> {
        Ok(car_platform::kernel::package_roots(family))
    }
}

/// car-policy's `Os` over car-platform, for the readers this half shares with S3.2 (`paths::newest_generation`).
#[derive(Clone, Copy, Debug, Default)]
pub struct PolicyOs;

impl car_policy::settings::os::Os for PolicyOs {
    fn is_symlink(&self, path: &std::path::Path) -> bool {
        car_platform::links::is_symlink(path)
    }

    fn is_junction(&self, path: &std::path::Path) -> bool {
        car_platform::links::reparse_tag(path) == Some(car_platform::links::MOUNT_POINT_TAG)
    }

    fn normcase(&self, text: &[u16]) -> Vec<u16> {
        car_platform::widepath::normcase(text)
    }

    fn abspath(&self, text: &[u16]) -> Vec<u16> {
        let normal = car_policy::settings::os::normpath(text);
        car_platform::widepath::full_path(&normal).unwrap_or(normal)
    }

    fn resolve(&self, text: &[u16]) -> std::result::Result<Vec<u16>, &'static str> {
        match String::from_utf16(text) {
            Ok(plain) => Ok(car_platform::paths::realpath(&plain)
                .encode_utf16()
                .collect()),
            Err(_) => Ok(text.to_vec()),
        }
    }

    fn replace(&self, from: &std::path::Path, to: &std::path::Path) -> std::io::Result<()> {
        car_platform::files::replace(from, to)
    }
}
