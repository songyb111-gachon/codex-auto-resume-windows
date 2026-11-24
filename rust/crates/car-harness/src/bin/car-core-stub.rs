//! The stand-in for codex-auto-resume.exe that the CODEX_AR_CORE=rust shim starts (tests/rustdiff/shim.py).
//!
//! Its command line is the entry point's name and then the Python entry point's own argv:
//! `bridge <controlcli argv>`, `mcp <mcpserver argv>`, `cli <cli argv>`. Ported: `bridge --home H defaults`.
//! Everything else is refused with error_code "not_ported" and exit code 3, so a shim-lane test that
//! reaches an unported command fails saying so instead of passing on Python.
//!
//! TO BE REPLACED by car-bin (S5.1/S5.2), the real codex-auto-resume.exe.

use std::io::Write;
use std::path::PathBuf;

use car_harness::{NOT_PORTED, defaults, object, rejected};
use car_machine::json::{Options, Str, Value, to_string};

const NOT_PORTED_EXIT: i32 = 3;

/// Write one reply line the way `controlcli._emit` does; exit 0 when the reply is ok, 1 otherwise.
fn emit(reply: &Value) -> i32 {
    let ok = matches!(reply, Value::Object(pairs) if pairs.get(&Str::new("ok")) == Some(&Value::Bool(true)));
    let line = to_string(reply, &Options::wire()).unwrap_or_else(|_| "{\"ok\": false}".into());
    let mut stdout = std::io::stdout().lock();
    if writeln!(stdout, "{line}")
        .and_then(|_| stdout.flush())
        .is_err()
    {
        return 1;
    }
    if ok { 0 } else { 1 }
}

fn not_ported(what: &str) -> i32 {
    eprintln!("car-core-stub: {what} is not ported");
    emit(&rejected("this command is not ported", NOT_PORTED));
    NOT_PORTED_EXIT
}

fn bridge(arguments: &[String]) -> i32 {
    let mut home: Option<PathBuf> = None;
    let mut rest = Vec::new();
    let mut index = 0;
    while index < arguments.len() {
        match arguments[index].as_str() {
            "--home" if index + 1 < arguments.len() => {
                home = Some(PathBuf::from(&arguments[index + 1]));
                index += 2;
            }
            other => {
                rest.push(other.to_string());
                index += 1;
            }
        }
    }
    match (rest.as_slice(), home) {
        ([command], Some(home)) if command == "defaults" => match defaults::restore(&home) {
            Ok(values) => emit(&object([
                ("ok", Value::Bool(true)),
                ("settings", Value::Object(values)),
            ])),
            // controlcli answers a save it cannot make with the generic request_failed refusal.
            Err(_) => emit(&rejected("cannot save settings", "request_failed")),
        },
        ([command], None) if command == "defaults" => not_ported("bridge defaults without --home"),
        _ => not_ported(&format!("bridge {}", rest.join(" "))),
    }
}

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let code = match arguments.split_first() {
        Some((entry, rest)) if entry == "bridge" => bridge(rest),
        Some((entry, _)) => not_ported(entry),
        None => not_ported("no entry point"),
    };
    std::process::exit(code);
}
