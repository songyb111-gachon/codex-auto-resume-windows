//! The fakes of an `advturns` trace (seat S7.2e1), the Rust half of `tests/rustdiff/advturnsworld.py`: how each
//! capability of the scenario is made (the ported code, with the scenario's fakes where it takes them) and the steps
//! that move a fake. Every fake notes each call it is asked in `asked`, in order, as `[fake, call, ...]`.

use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::capabilities::Code;
use car_adv::registry::CapabilityDef;
use car_config::Paths;
use car_machine::json::Value;

/// Every call asked of a fake (and the hooks), in order.
pub type Asked = Arc<Mutex<Vec<Value>>>;

/// The scenario's fakes, by capability.
#[derive(Clone)]
pub struct World {
    #[allow(dead_code)]
    seams: Value,
    #[allow(dead_code)]
    asked: Asked,
    #[allow(dead_code)]
    clock: Arc<Mutex<f64>>,
}

impl World {
    pub fn new(seams: Value, asked: Asked, clock: Arc<Mutex<f64>>) -> World {
        World {
            seams,
            asked,
            clock,
        }
    }

    #[allow(dead_code)]
    fn note(&self, entry: Vec<Value>) {
        self.asked
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .push(Value::Array(entry));
    }

    /// `definition.make(paths)`: the edition's own code, with the scenario's fakes where it takes them.
    pub fn make(&self, definition: &CapabilityDef, paths: &Paths) -> Option<Box<dyn Code>> {
        car_adv::capabilities::make(definition, paths)
    }

    /// A step that moves a fake: None for an op it does not know.
    pub fn step(&self, op: &str, args: &[Value]) -> Option<Result<Value, String>> {
        match op {
            "flag" => {
                let on = args.get(1).is_some_and(car_machine::pyval::truthy);
                if matches!(args.first(), Some(Value::Str(name)) if name.as_str() == Some("empty_refused"))
                {
                    car_adv::codex::headless::EMPTY_REFUSED.store(on, Ordering::SeqCst);
                }
                Some(Ok(Value::Null))
            }
            _ => None,
        }
    }
}
