//! advfake: a stand-in for `codex.exe` that S7.2c's diffs (`tests/rustdiff/advcodex.py`) copy into a scratch folder and
//! that both the reference and car-adv start (always with `CREATE_NO_WINDOW`). Dev only, never shipped; it starts
//! nothing and reads nothing but `advfake.json` beside itself, and appends what it was asked to `advfake.log.jsonl`
//! there: its arguments, its working folder and `CODEX_HOME`.
//!
//! Its script: `version` and `help` answer `--version` and `queue --help` (`{"stdout", "code"}`); `schema` answers
//! `app-server generate-json-schema [--experimental] --out DIR`: with core's `-c` options and `--experimental` it copies
//! the file named by `file` (beside the script) into DIR as `codex_app_server_protocol.schemas.json` and exits with
//! `code`; `bare_code` is the exit without `--experimental`, `plain_code` the exit without the `-c` options, and `home` a
//! file name written into `CODEX_HOME`. `features` answers `features list` (`{"stdout", "code"}`). Anything else exits 2.

use std::io::Write;
use std::path::{Path, PathBuf};

use car_machine::json::{Options, Value, from_str, to_string};

fn beside() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(Path::to_path_buf))
        .unwrap_or_default()
}

fn field<'a>(value: &'a Value, name: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(name),
        _ => None,
    }
}

fn text(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::Str(text)) => text.as_str().map(str::to_owned),
        _ => None,
    }
}

fn code(value: Option<&Value>, default: i32) -> i32 {
    match value {
        Some(Value::Int(n)) => n.as_i64().map_or(default, |n| n as i32),
        _ => default,
    }
}

fn simple(entry: Option<&Value>) -> i32 {
    let entry = entry.cloned().unwrap_or(Value::Null);
    if let Some(out) = text(field(&entry, "stdout")) {
        let mut stdout = std::io::stdout().lock();
        let _ = stdout.write_all(out.as_bytes());
        let _ = stdout.flush();
    }
    code(field(&entry, "code"), 0)
}

fn quote(text: &str) -> String {
    to_string(&Value::from(text), &Options::new()).unwrap_or_default()
}

fn main() {
    let folder = beside();
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let cwd = std::env::current_dir()
        .map(|found| found.to_string_lossy().into_owned())
        .unwrap_or_default();
    let line = format!(
        "{{\"args\": [{}], \"cwd\": {}, \"codex_home\": {}}}\n",
        arguments.iter().map(|each| quote(each)).collect::<Vec<_>>().join(", "),
        quote(&cwd),
        quote(&std::env::var("CODEX_HOME").unwrap_or_default()),
    );
    if let Ok(mut log) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(folder.join("advfake.log.jsonl"))
    {
        let _ = log.write_all(line.as_bytes());
    }
    let script = std::fs::read_to_string(folder.join("advfake.json"))
        .ok()
        .and_then(|raw| from_str(&raw).ok())
        .unwrap_or(Value::Null);
    let options = arguments.iter().any(|each| each == "-c");
    let mut rest = arguments.iter();
    let mut positional: Vec<&str> = Vec::new();
    while let Some(argument) = rest.next() {
        if argument == "-c" {
            rest.next();
            continue;
        }
        positional.push(argument);
    }
    let exit = match positional.as_slice() {
        ["--version", ..] => simple(field(&script, "version")),
        ["queue", "--help", ..] => simple(field(&script, "help")),
        ["features", "list", ..] => simple(field(&script, "features")),
        ["app-server", "generate-json-schema", tail @ ..] => {
            let entry = field(&script, "schema").cloned().unwrap_or(Value::Null);
            let experimental = tail.contains(&"--experimental");
            let out = tail
                .iter()
                .position(|each| *each == "--out")
                .and_then(|at| tail.get(at + 1));
            if let Some(name) = text(field(&entry, "home")) {
                let home = std::env::var("CODEX_HOME").unwrap_or_default();
                let _ = std::fs::write(Path::new(&home).join(name), b"{}");
            }
            if !experimental {
                code(field(&entry, "bare_code"), 2)
            } else if !options {
                code(field(&entry, "plain_code"), 0)
            } else {
                if let (Some(out), Some(file)) = (out, text(field(&entry, "file"))) {
                    let _ = std::fs::copy(
                        folder.join(file),
                        Path::new(out).join("codex_app_server_protocol.schemas.json"),
                    );
                }
                code(field(&entry, "code"), 0)
            }
        }
        _ => 2,
    };
    std::process::exit(exit);
}
