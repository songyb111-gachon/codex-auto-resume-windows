//! `ownreport/`: this PC's own compatibility report (v0.6.19, both editions) - written on request from the
//! product's own records, shown whole with its SHA-256 in the Dashboard's Diagnostics page and put in the
//! diagnostics export, and sent nowhere.
//!
//! | Python | here |
//! |---|---|
//! | `ownreport/reading.py` | [`reading`]: the state (read-only), the logs and the watcher's own report |
//! | `ownreport/evidence.py` | [`evidence`]: what those records say, counted as codex-compat-reporter counts them |
//! | `ownreport/document.py` | [`document`]: the envelope that names nobody, and the self-check |

pub mod document;
pub mod evidence;
pub mod reading;

use car_machine::json::{Map, Str, Value};

use crate::error::{Failure, Res};
use crate::layer::Control;

fn refusal(code: &str) -> Value {
    let mut map = Map::new();
    map.insert(Str::from("refusal"), Value::from(code));
    Value::Object(map)
}

impl Control {
    /// `ownreport.write(paths)`: the report as the Dashboard is given it, or `{"refusal": code}` when the records
    /// cannot be read or the report would be more than a report holds.
    pub fn own_report(&self) -> Res<Value> {
        self.own_report_with(None)
    }

    /// `ownreport.write(paths, view=...)`: `view` stands in for the watcher's report (the tests' seam).
    pub fn own_report_with(&self, view: Option<Option<Value>>) -> Res<Value> {
        let found = match reading::read_all(self, view) {
            Ok(found) => found,
            Err(reading::Refused::Code(code)) => return Ok(refusal(code)),
            Err(reading::Refused::Raised(class)) => return Err(Failure::Other(class.to_owned())),
        };
        let version = self.host.version();
        let windows = self.host.windows_version();
        let made = match document::assemble(&found, &version, windows.as_deref(), self.host.now()) {
            Ok(made) => made,
            Err(document::Fault::Refused(code)) => return Ok(refusal(code)),
            Err(document::Fault::Error(class)) => return Err(Failure::Other(class.to_owned())),
        };
        document::written(&made).map_err(|fault| match fault {
            document::Fault::Refused(_) => Failure::Other("DocumentRefused".to_owned()),
            document::Fault::Error(class) => Failure::Other(class.to_owned()),
        })
    }

    /// `ownreport.for_bundle(paths)()`: the report written for the diagnostics export - its SHA-256, its size and
    /// the report itself - or the refusal. `Err` is the class of what it raised.
    pub fn own_report_for_bundle(&self) -> Result<Value, String> {
        let found = self.own_report().map_err(|failure| match failure {
            Failure::Other(class) => class,
            Failure::Control(_) => "ControlError".to_owned(),
        })?;
        let Value::Object(found) = found else {
            return Err("TypeError".to_owned());
        };
        if let Some(code) = found.get("refusal") {
            let mut map = Map::new();
            map.insert(Str::from("refusal"), code.clone());
            return Ok(Value::Object(map));
        }
        let text = match found.get("text") {
            Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
            _ => String::new(),
        };
        let report = car_machine::compat::loads(&text).map_err(|_| "JSONDecodeError".to_owned())?;
        let mut map = Map::new();
        map.insert(
            Str::from("sha256"),
            found.get("sha256").cloned().unwrap_or(Value::Null),
        );
        map.insert(
            Str::from("bytes"),
            found.get("bytes").cloned().unwrap_or(Value::Null),
        );
        map.insert(Str::from("report"), report);
        Ok(Value::Object(map))
    }
}
