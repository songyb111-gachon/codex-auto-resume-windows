//! The document's ops (`document.*`).

use car_adv::jsonx::object;
use car_adv::report::document::{self, Facts, Fault};
use car_machine::json::Value;

use crate::ops_records;
use crate::util::{Failure, Out, arg, maybe_text, tagged_float, text};

/// A report is never asked for the process's own facts here: every case names them.
struct Named;

impl Facts for Named {
    fn product_version(&self) -> String {
        "unasked".to_owned()
    }
    fn windows_version(&self) -> Option<String> {
        None
    }
}

pub fn fault(error: Fault) -> Failure {
    match error {
        Fault::Refused(code) => Failure::coded("DocumentRefused", code),
        Fault::Error(class) => Failure::new(class),
    }
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "document.check_login" => document::check_login(arg(args, 0)?)
            .map(Value::from)
            .map_err(fault),
        "document.assemble" => {
            let made = document::assemble(
                arg(args, 0)?,
                arg(args, 1)?,
                maybe_text(arg(args, 2)?)?,
                maybe_text(arg(args, 3)?)?,
                tagged_float(arg(args, 4)?)?,
                &Named,
            )
            .map_err(fault)?;
            Ok(made)
        }
        "document.check" => document::check(arg(args, 0)?)
            .map(Value::from)
            .map_err(fault),
        "document.encode" => document::encode(arg(args, 0)?)
            .map(Value::from)
            .map_err(fault),
        // The reader, then the envelope, then the self-check, over one scratch home: what the Dashboard's Write does.
        "document.assemble_of" => {
            let found = ops_records::read(&args[..5])?;
            let made = document::assemble(
                &found.body,
                arg(args, 5)?,
                maybe_text(arg(args, 6)?)?,
                maybe_text(arg(args, 7)?)?,
                tagged_float(arg(args, 3)?)?,
                &Named,
            )
            .map_err(fault)?;
            let bytes = document::check(&made).map_err(fault)?;
            let Value::Object(top) = &made else {
                return Err(Failure::new("TypeError"));
            };
            let keys = Value::Array(top.keys().map(|key| Value::from(text_of(key))).collect());
            let get = |name: &str| top.get(name).cloned().unwrap_or(Value::Null);
            Ok(object([
                ("keys", keys),
                (
                    "envelope",
                    object([
                        ("format", get("format")),
                        ("attribution", get("attribution")),
                        ("note", get("note")),
                    ]),
                ),
                ("bytes", Value::from(bytes)),
            ]))
        }
        _ => {
            let _ = text;
            Err(Failure::new("UnknownOp"))
        }
    }
}

fn text_of(key: &car_machine::json::Str) -> String {
    key.as_str().unwrap_or_default().to_owned()
}
