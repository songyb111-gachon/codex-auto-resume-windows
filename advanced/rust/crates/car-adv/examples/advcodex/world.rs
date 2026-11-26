//! The stand-in Windows the S7.2c diffs give both sides (`tests/rustdiff/advcodex.py`'s `WORLD`): the files' signers,
//! the process list, this process's pid and the monotonic clock are the case's; paths resolve on the scratch disk.
//! Nothing of this machine's processes or signatures is read.

use std::sync::{Arc, Mutex, PoisonError};

use car_codex::errors::{Error, Result};
use car_codex::system::System;
use car_machine::json::Value;

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &std::path::Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

/// The world a case runs in.
#[derive(Debug)]
pub struct World {
    pub spec: Mutex<Value>,
    pub os: car_config::Os,
}

impl World {
    pub fn new(spec: Value) -> Arc<World> {
        Arc::new(World {
            spec: Mutex::new(spec),
            os: car_config::Os::here(false, Arc::new(Links)),
        })
    }

    fn field(&self, name: &str) -> Value {
        match &*self.spec.lock().unwrap_or_else(PoisonError::into_inner) {
            Value::Object(map) => map.get(name).cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        }
    }
}

impl System for World {
    fn env(&self, name: &str) -> Option<String> {
        std::env::var_os(name).map(|value| value.to_string_lossy().into_owned())
    }

    fn processes_named(&self, _names: &[&str], _families: &[&str]) -> Result<Vec<Value>> {
        match self.field("processes") {
            Value::Array(rows) => Ok(rows),
            Value::Object(_) => Err(Error::Adapter("process_inventory_unavailable")),
            _ => Ok(Vec::new()),
        }
    }

    fn resource_users(&self, _paths: &[String]) -> Result<Vec<Value>> {
        Ok(Vec::new())
    }

    fn process_identity(&self, _pid: &Value) -> Result<Value> {
        Err(Error::Adapter("process_exited"))
    }

    fn signer(&self, path: &str) -> std::result::Result<String, Option<&'static str>> {
        if let Value::Object(signers) = self.field("signers") {
            for (name, value) in signers.iter() {
                let name = String::from_utf8_lossy(name.as_bytes()).to_lowercase();
                if name == path.to_lowercase() {
                    return match value {
                        Value::Str(text) => {
                            Ok(String::from_utf8_lossy(text.as_bytes()).into_owned())
                        }
                        _ => Err(None),
                    };
                }
            }
        }
        Err(Some("unsigned"))
    }

    fn own_pid(&self) -> i64 {
        match self.field("pid") {
            Value::Int(pid) => pid.as_i64().unwrap_or(999_999),
            _ => 999_999,
        }
    }

    fn monotonic(&self) -> f64 {
        match self.field("clock") {
            Value::Float(at) => at,
            Value::Int(at) => at.as_i64().unwrap_or(1000) as f64,
            _ => 1000.0,
        }
    }

    fn resolve(&self, text: &str) -> Option<String> {
        self.os
            .resolve(text)
            .ok()
            .map(|found| car_config::winpath::path_str(&found))
    }

    fn restart_manager_available(&self) -> bool {
        false
    }

    /// The case's package folders (`packages`, as advcodex.py's `fake_packages` reads it): none unless it names some,
    /// never this PC's.
    fn package_roots(&self, _family: &str) -> Result<Vec<String>> {
        match self.field("packages") {
            Value::Array(items) => Ok(items
                .iter()
                .filter_map(|each| match each {
                    Value::Str(text) => text.as_str().map(str::to_owned),
                    _ => None,
                })
                .collect()),
            Value::Object(_) => Err(Error::Adapter("package_roots_unavailable")),
            _ => Ok(Vec::new()),
        }
    }
}
