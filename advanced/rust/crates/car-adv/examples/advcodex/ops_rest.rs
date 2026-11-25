//! The S7.2c remainder's other ops (seat adv72d): `bt.booted_of` (turns' read of core's store).

use std::path::Path;

use car_adv::codex::turns;
use car_machine::json::Value;

use crate::{Context, Failure, Out, arg, text};

pub fn run(_context: &Context, op: &str, args: &[Value]) -> Out {
    match op {
        "bt.booted_of" => Ok(turns::booted_of(Path::new(&text(arg(args, 0))?))),
        _ => Err(Failure::new("UnknownOp")),
    }
}
