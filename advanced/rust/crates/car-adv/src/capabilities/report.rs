//! The code of `compat_report` (seat S7.2a; `report/__init__.py`'s `make`, which is `report.flow.Flow(paths)`), and the
//! runtime as the report's flow reaches it (`report::seam::Runtime`, S7.3c's seam, filled here over the real `Arming`
//! and `AdvancedState`).
//!
//! The capability is an action: core never asks it, and the surface a person starts a report from takes its code
//! through `Runtime::action` (S7.3a) and reaches the flow with [`ReportCode::flow`]. `Flow::new(paths, Config)` needs the
//! world its jobs act in - gh's runner, the home's mutex, the watcher's report - which the entry points hand
//! (S7.3d); [`make_with`] is that call, and [`make`] (the table's, with no world) has none to make.

use std::sync::Arc;

use car_config::Paths;
use car_machine::json::Value;

use super::Code;
use crate::policy::Policy;
use crate::registry::CapabilityDef;
use crate::report::flow::{Config, Flow};
use crate::report::seam::{Class, Runtime};
use crate::runtime::Shared;
use crate::vocabulary::{ArmingState, OffReason};

/// The report's code: its flow, for the surface that starts a job.
pub struct ReportCode {
    pub flow: Arc<Flow>,
}

impl ReportCode {
    pub fn flow(&self) -> &Arc<Flow> {
        &self.flow
    }
}

impl Code for ReportCode {
    fn as_any(&mut self) -> Option<&mut dyn std::any::Any> {
        Some(self)
    }
}

/// `report.make(paths)` with the world the flow acts in.
pub fn make_with(paths: &Paths, config: Config) -> Option<Box<dyn Code>> {
    Some(Box::new(ReportCode {
        flow: Flow::new(paths.clone(), config),
    }))
}

/// `report.make(paths)` as the skeleton's table names it: no world handed, so no flow (the entry points use
/// [`make_with`]).
pub fn make(_paths: &Paths) -> Option<Box<dyn Code>> {
    None
}

impl Runtime for Shared {
    fn policy(&self) -> Result<Policy, Class> {
        Ok(self.enter(|runtime| runtime.arming().policy()))
    }

    fn state_of(&self, id: &str) -> Result<Option<ArmingState>, Class> {
        Ok(self.enter(|runtime| runtime.states(true, &[]).get(id)))
    }

    fn stored_state(&self, id: &str) -> Result<Option<ArmingState>, Class> {
        self.enter(|runtime| match runtime.state.arming() {
            Ok(rows) => Ok(match rows.get(id) {
                Some(Value::Object(row)) => match row.get("state") {
                    Some(Value::Str(word)) => word.as_str().and_then(ArmingState::parse),
                    _ => None,
                },
                _ => None,
            }),
            Err(error) => Err(error.class().to_owned()),
        })
    }

    fn trip(&self, id: &str, reason: OffReason) {
        self.enter(|runtime| {
            let _ = runtime.arming().trip(id, reason);
        });
    }

    fn note(&self, definition: &CapabilityDef, code: &str, at: f64) -> Result<(), Class> {
        self.enter(|runtime| {
            let code = definition
                .code(code)
                .map_or(Value::Null, |code| Value::Str(code.into()));
            runtime
                .state
                .note(
                    &code,
                    &Value::Str(definition.id.as_str().into()),
                    &Value::Null,
                    &Value::Null,
                    &Value::Null,
                    &Value::Null,
                    &Value::Float(at),
                )
                .map(|_| ())
                .map_err(|error| error.class().to_owned())
        })
    }
}
