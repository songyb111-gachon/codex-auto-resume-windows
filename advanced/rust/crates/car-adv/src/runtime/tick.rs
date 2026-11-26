//! `Runtime.tick` (P8), `Runtime.resident` (P22), `_auto_check` and `_Errands` (`runtime.py`).

use std::sync::Weak;

use car_machine::json::Value;
use car_policy::plug::{Errand, Guards, HookFailed, Point, View};

use super::ask::class_of;
use super::{Py, Raise, Runtime, Shared, Swept, tended};
use crate::capabilities::{Raised, Said};
use crate::vocabulary::{ArmingState, JournalCode, OffReason, TRIPWIRES};

/// `_Errands`: the errands of every capability on at P8 (or P22), joined; core runs this once, last in the tick, and
/// each errand runs in the registry's order. One that raises (or panics, D15) trips its own capability alone; one that
/// asks for a tripwire has its capability turned off, or, kept on, noted (K7, K8).
pub struct Errands {
    runtime: Weak<Shared>,
    errands: Vec<(String, Box<dyn Errand>)>,
}

impl Errand for Errands {
    fn run(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        for (capability, errand) in &self.errands {
            // Run outside the runtime's lock: an errand waits on Codex, and the runtime's other callers need not wait.
            let asked =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| errand.run(view, guards)));
            let Some(shared) = self.runtime.upgrade() else {
                continue;
            };
            shared.enter(|runtime| {
                let Some(definition) = runtime.registry.get(capability) else {
                    return;
                };
                let asked = match asked {
                    Ok(Ok(asked)) => asked,
                    _ => {
                        runtime.tripped(definition, None, &Raised::new("Exception"));
                        return;
                    }
                };
                let reason = match &asked {
                    Value::Object(map) => map.get("trip").and_then(|reason| match reason {
                        Value::Str(text) => text.as_str().and_then(OffReason::parse),
                        _ => None,
                    }),
                    _ => None,
                };
                if let Some(reason) = reason.filter(|reason| TRIPWIRES.contains(reason)) {
                    let _ = runtime.arming.trip(&definition.id, reason);
                    runtime.states(true, &[]);
                }
            });
        }
        Ok(Value::Null)
    }
}

impl Runtime {
    /// `tick(view)`: P8 - every trip and reset there is to find, what every capability stands at read afresh, then the
    /// capabilities that answer once a tick, joined into the one errand core runs last (`_Errands`); a watched one's
    /// is only journalled, never run. What a run kind turned off or watched still owes is tended (`TENDED`).
    pub fn tick(&self, view: &dyn View) -> Py<Option<Errands>> {
        self.acted.borrow_mut().clear();
        self.pooled.borrow_mut().clear();
        self.texted.borrow_mut().clear();
        if self.registry.is_empty() {
            return Ok(None);
        }
        self.auto_check();
        self.arming.sweep(&Swept(view));
        let states = self.states(true, &[]);
        let mut errands = Vec::new();
        for definition in self.registry.at(Point::Tick) {
            let state = states.state_of(&definition.id);
            if state != ArmingState::Armed && tended(&definition.id) {
                // `_own(self._code_of(definition), "tend")`, outside the reference's try.
                let tend = self.call_own(definition, |code| code.tend(view).map(Ok));
                match tend {
                    Err(raised) => return Err(Raise(class_of(&raised))),
                    Ok(Some(Ok(Ok(Said::Errand(errand))))) => {
                        errands.push((definition.id.clone(), errand));
                        continue;
                    }
                    // Already off or watched: the next tick tends it again.
                    Ok(Some(_)) => continue,
                    Ok(None) => {}
                }
            }
            if state == ArmingState::Off {
                continue;
            }
            let answer = match self.call(definition, |code| code.tick(view)) {
                Ok(answer) => answer,
                Err(raised) => {
                    self.tripped(definition, None, &raised);
                    continue;
                }
            };
            let Said::Errand(errand) = answer else {
                continue;
            };
            if state == ArmingState::Shadow {
                self.once(
                    JournalCode::WouldHave,
                    definition,
                    Point::Tick,
                    Point::Tick.as_str(),
                    None,
                )?;
                continue;
            }
            self.once(
                JournalCode::Acted,
                definition,
                Point::Tick,
                Point::Tick.as_str(),
                None,
            )?;
            errands.push((definition.id.clone(), errand));
        }
        Ok(self.joined(errands))
    }

    fn joined(&self, errands: Vec<(String, Box<dyn Errand>)>) -> Option<Errands> {
        if errands.is_empty() {
            return None;
        }
        Some(Errands {
            runtime: self.me.borrow().clone(),
            errands,
        })
    }

    /// `_auto_check()`: the automatic compatibility check, where one is due (`autocheck.tend`); it costs the tick
    /// nothing, whatever it does.
    fn auto_check(&self) {
        if let Some(check) = &self.auto_check {
            let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| check()));
        }
    }

    /// `resident(view)`: P22 - asked only while recovery is paused: the errands of the capabilities that declare they
    /// send nothing, joined as P8's are; a watched one's journalled, never run.
    pub fn resident(&self, view: &dyn View) -> Py<Option<Errands>> {
        if self.registry.is_empty() {
            return Ok(None);
        }
        let states = self.states(true, &[]);
        let mut errands = Vec::new();
        for definition in self.registry.at(Point::Resident) {
            let state = states.state_of(&definition.id);
            if state == ArmingState::Off {
                continue;
            }
            let answer = match self.call(definition, |code| code.resident(view)) {
                Ok(answer) => answer,
                Err(raised) => {
                    self.tripped(definition, None, &raised);
                    continue;
                }
            };
            let Said::Errand(errand) = answer else {
                continue;
            };
            if state == ArmingState::Shadow {
                self.once(
                    JournalCode::WouldHave,
                    definition,
                    Point::Resident,
                    Point::Tick.as_str(),
                    None,
                )?;
                continue;
            }
            self.once(
                JournalCode::Acted,
                definition,
                Point::Resident,
                Point::Tick.as_str(),
                None,
            )?;
            errands.push((definition.id.clone(), errand));
        }
        Ok(self.joined(errands))
    }
}
