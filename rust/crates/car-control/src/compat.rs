//! `controlcli.py`'s Compatibility Registry commands: the report as the window shows it (or checked live), a
//! document imported, and the Diagnostics refresh. The registry itself - its validator, its live check and the
//! bootstrap's refresh - is S3.3's (`car-codex` `compat/*`) and comes in through [`Host`](crate::host::Host).

use std::path::PathBuf;

use car_machine::json::{Map, Str, Value};

use crate::bridge::boolean;
use crate::error::{Failure, Res, refuse};
use crate::host::{Event, Raised};
use crate::layer::Control;

fn raised(error: Raised) -> Failure {
    match error.as_control() {
        Some(refused) => Failure::Control(refused),
        None => Failure::Other(error.class),
    }
}

impl Control {
    /// `_compatibility(control, payload)`: the watcher's report, validated - or, with `live`, a fresh check made
    /// here and returned, never written.
    pub fn compatibility(&self, payload: &Map) -> Res<Value> {
        let settings = self.get_settings()?;
        if boolean(payload, "live")? {
            let explicit = match settings.get("codex_exe") {
                Some(value) if car_machine::pyval::truthy(value) => value.clone(),
                _ => Value::Null,
            };
            return self
                .host
                .compat_live_view(&self.state_dir(), &self.host.codex_home(), &explicit)
                .map_err(raised);
        }
        Ok(self.host.compat_view(&self.state_dir(), &settings))
    }

    /// `_compat_import(control, payload)`: one registry document validated and, only if it passes, made the cache;
    /// a running watcher asked to look now.
    pub fn compat_import(&self, payload: &Map) -> Res<Value> {
        let target = match payload.get("path") {
            Some(Value::Str(text)) if !text.is_empty() => text.clone(),
            _ => return refuse("choose a .json file to import", crate::error::FALLBACK_CODE),
        };
        let origin = payload
            .get("origin")
            .cloned()
            .unwrap_or(Value::from("file"));
        let known = ["main", "file"]
            .iter()
            .any(|word| car_machine::pyval::is(&origin, word));
        if !known {
            return refuse("origin must be main or file", crate::error::FALLBACK_CODE);
        }
        let result = self
            .host
            .compat_import(&self.state_dir(), &target, &origin)
            .map_err(raised)?;
        let imported = match &result {
            Value::Object(map) => map.get("imported").is_some_and(car_machine::pyval::truthy),
            _ => return Err(Failure::Other("AttributeError".into())),
        };
        let woke = imported
            && self
                .host
                .signal(Event::Wake, &self.state_dir())
                .unwrap_or(false);
        let mut map = match result {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        map.insert(Str::from("woke_watcher"), Value::Bool(woke));
        Ok(Value::Object(map))
    }

    /// `_compat_refresh(control)`: this installation's own bootstrap asked to fetch the registry data, and the
    /// fresh view checked live (or, where that fails, the report as it is).
    pub fn compat_refresh(&self) -> Res<Value> {
        let outcome = self
            .host
            .compat_refresh(&PathBuf::from(&self.paths.home))
            .map_err(raised)?;
        let mut live = Map::new();
        live.insert(Str::from("live"), Value::Bool(true));
        let view = match self.compatibility(&live) {
            Ok(view) => view,
            Err(_) => self.host.compat_view(&self.state_dir(), &Map::new()),
        };
        let mut map = match outcome {
            Value::Object(map) => map,
            _ => return Err(Failure::Other("TypeError".into())),
        };
        map.insert(Str::from("compatibility"), view);
        Ok(Value::Object(map))
    }

    /// `checkup.run(control)`: Diagnostics' check of why a failure was not taken up (the watcher's own rules).
    pub fn detection_check(&self) -> Res<Value> {
        self.host
            .checkup(&PathBuf::from(&self.paths.home))
            .map_err(raised)
    }
}
