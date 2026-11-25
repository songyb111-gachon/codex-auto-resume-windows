//! The codex readers' ops (`rd.*`).

use car_machine::json::Value;

use crate::{Context, Failure, Out};

pub fn run(_context: &Context, _op: &str, _args: &[Value]) -> Out {
    Err(Failure::new("UnknownOp"))
}
