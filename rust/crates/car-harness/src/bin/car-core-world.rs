//! A test core for the legacy shapes' end-to-end diff (S5.2, `tests/rustdiff/diffs_legacy.py`): car-bin's dispatcher,
//! exactly as `codex-auto-resume.exe` runs it, but over car-harness's world - the Host and the Outside answered from the
//! JSON file `CAR_CORE_WORLD` names, every call appended to `<that file>.calls` - so car-legacy can hand it every
//! published line in a scratch installation and nothing writes the registry, makes a shortcut or starts a process.
//! Dev only: it is copied into the scratch installation as `app\bin\codex-auto-resume.exe` by the diff, never shipped.

use std::io::Write;

use car_bin::cli::Io;
use car_machine::json::{Map, Options, Value, from_str, to_string};

fn main() {
    // A thread with the stack for a deeply nested document (car_machine::stack).
    car_machine::stack::run_deep(run);
}

fn run() {
    let named = std::env::var("CAR_CORE_WORLD").unwrap_or_default();
    let world: Map = match std::fs::read_to_string(&named)
        .ok()
        .and_then(|text| from_str(&text).ok())
    {
        Some(Value::Object(map)) => map,
        _ => {
            eprintln!("car-core-world: CAR_CORE_WORLD names no world");
            std::process::exit(97);
        }
    };
    let exe = std::env::current_exe().unwrap_or_default();
    let project_root = car_bin::setup::project_root_of(&exe)
        .to_string_lossy()
        .into_owned();
    let (machine, acts) = car_harness::cli::machine_for(&world, &project_root);
    let argv: Vec<String> = std::env::args_os()
        .skip(1)
        .map(|each| each.to_string_lossy().into_owned())
        .collect();
    let stdout = std::io::stdout();
    let stderr = std::io::stderr();
    let (mut out, mut err) = (stdout.lock(), stderr.lock());
    let mut io = Io {
        out: &mut out,
        err: &mut err,
        silent: false,
    };
    let stdin = std::io::stdin();
    let mut input = stdin.lock();
    let code = car_bin::roles::dispatch(&machine, &[], &argv, &mut io, &mut input);
    let mut entry = Map::new();
    entry.insert(
        "argv".into(),
        Value::Array(argv.iter().map(|each| Value::from(each.as_str())).collect()),
    );
    entry.insert(
        "entry".into(),
        std::env::var("CODEX_AUTO_RESUME_LEGACY_ENTRY").map_or(Value::Null, Value::from),
    );
    entry.insert("calls".into(), acts.calls());
    if let (Ok(line), Ok(mut file)) = (
        to_string(&Value::Object(entry), &Options::wire()),
        std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(format!("{named}.calls")),
    ) {
        let _ = writeln!(file, "{line}");
    }
    std::process::exit(code);
}
