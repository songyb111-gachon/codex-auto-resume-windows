//! The code of `stop_hook_continuation` (seat S7.2a; `engine/hookclaims.py`'s `StopHook`): P3's hold on a record the
//! hook blocked (`hookclaims::blocked_at`, S7.3c), and P8's upkeep of the declaration (`hookplugin::follow_real`, S7.3c).

use std::path::PathBuf;
use std::sync::Arc;

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Alternative, View};

use super::{Binding, Code, Raised, Said, Spoke};
use crate::engine::hookclaims::{HOLD_SECONDS, blocked_at};

/// Where the Codex home this installation looks at is read (`codex/inuse.home(paths)`), as the entry point gives it.
pub type HomeOf = Arc<dyn Fn(&Paths) -> Option<PathBuf> + Send + Sync>;

/// `StopHook(paths)`.
pub struct StopHook {
    paths: Paths,
    binding: Option<Binding>,
    home_of: HomeOf,
}

impl StopHook {
    /// `StopHook(paths)`, with the Codex home this installation looks at read through `home_of`.
    pub fn new(paths: Paths, home_of: HomeOf) -> StopHook {
        StopHook {
            paths,
            binding: None,
            home_of,
        }
    }

    /// `_now()`: the runtime's clock once bound, else the wall clock.
    fn now(&self) -> f64 {
        self.binding
            .as_ref()
            .and_then(|binding| binding.with(|scoped| scoped.now()))
            .unwrap_or_else(crate::state::session::wall_clock)
    }
}

impl Code for StopHook {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P3: HOLD for a core record whose turn the hook blocked within HOLD_SECONDS; DEFER for every other record and
    /// gate.
    fn gate(&mut self, _name: &Value, record: &Value, _facts: &Value) -> Spoke {
        let key = match record {
            Value::Object(map) => map.get("interruption_id").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let Some(at) = blocked_at(&self.paths, &key) else {
            return Ok(Said::Defer);
        };
        let since = self.now() - at;
        if !(0.0..HOLD_SECONDS).contains(&since) {
            return Ok(Said::Defer);
        }
        Ok(Said::Word(Alternative::Hold))
    }

    /// P8, asked only while the capability is on: its declaration stands in our plugin copies. Nothing to run.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let home = (self.home_of)(&self.paths);
        crate::control::hookplugin::follow_real(&self.paths, home.as_deref(), true);
        Ok(Said::Defer)
    }
}

/// `make(paths)`: the capability's code for one installation, its Codex home read by `inuse.home` over `home_of`.
pub fn make_with(paths: &Paths, home_of: HomeOf) -> Option<Box<dyn Code>> {
    Some(Box::new(StopHook::new(paths.clone(), home_of)))
}

/// `make(paths)` as the skeleton's table names it: the Codex home the watcher told (`inuse.told`), else none - the
/// entry points hand the full `inuse.home` through [`make_with`] (`capabilities::World`).
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(
        paths,
        Arc::new(|paths: &Paths| {
            crate::codex::inuse::told(Some(&paths.home)).map(|(_, home)| PathBuf::from(home))
        }),
    )
}
