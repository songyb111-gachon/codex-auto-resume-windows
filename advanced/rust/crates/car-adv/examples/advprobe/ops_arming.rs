//! `arming.*`: filled in with the arming port.

use car_machine::json::Value;

use crate::util::{Failure, Out};

pub fn run(_op: &str, _args: &[Value]) -> Out {
    Err(Failure::new("UnknownOp"))
}
