//! The program the CODEX_AR_CORE=rust shim starts (tests/rustdiff/shim.py): the Python entry point's name, then its own
//! argv - `bridge <controlcli argv>`, `mcp <mcpserver argv>`, `cli <cli argv>` - run by car-bin exactly as
//! `codex-auto-resume.exe` runs them (S5.2). `cli` is the command line itself, never `plugin_setup.py`'s commands of
//! the same names (`codex-auto-resume.exe status` is plugin_setup's; `cli.main(["status"])` is the CLI's).
//!
//! The installation it answers for is the repository the shim runs from: `CODEX_AR_PROJECT_ROOT`, else the folder
//! three above this program (`rust/target/release/car-core-stub.exe`), where `.codex-plugin/plugin.json` gives the
//! version and `src/` the package.

use std::path::PathBuf;
use std::sync::Arc;

use car_bin::cli::{Io, Machine};
use car_control::host::Host;

fn project_root() -> String {
    if let Ok(named) = std::env::var("CODEX_AR_PROJECT_ROOT")
        && !named.is_empty()
    {
        return named;
    }
    let exe = std::env::current_exe().unwrap_or_default();
    exe.ancestors()
        .nth(4)
        .map(PathBuf::from)
        .unwrap_or_default()
        .to_string_lossy()
        .into_owned()
}

fn main() {
    // The real-engine guard (car-platform `realengine`): a test-only binary never finds, lists or starts this PC's
    // installed Codex engine or app. SAFETY: the first statement of main, before any thread exists.
    unsafe { std::env::set_var("CAR_NO_REAL_ENGINE", "1") };
    // A thread with the stack for a deeply nested document (car_machine::stack).
    car_machine::stack::run_deep(run);
}

fn run() {
    let arguments: Vec<String> = std::env::args_os()
        .skip(1)
        .map(|each| each.to_string_lossy().into_owned())
        .collect();
    let root = project_root();
    let host: Arc<dyn Host> = Arc::new(car_control::host::SystemHost::new(&root));
    let machine = Machine {
        host,
        outside: Arc::new(car_bin::seam::SystemOutside),
        project_root: root,
        env: Arc::new(|name: &str| std::env::var(name).ok()),
    };
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
    let code = match arguments.split_first() {
        Some((entry, rest)) if entry == "bridge" => {
            car_bin::roles::bridge(&machine, rest, &mut io, &mut input)
        }
        Some((entry, rest)) if entry == "mcp" => {
            car_bin::roles::mcp(&machine, rest, &mut io, &mut input)
        }
        Some((entry, rest)) if entry == "cli" => {
            match car_bin::argparse::parse_args(
                car_bin::parsers_gen::PARSERS,
                car_bin::parsers_gen::CLI,
                rest,
            ) {
                Ok(args) => car_bin::cli::run(&machine, &args, &mut io),
                Err(exit) => car_bin::roles::shown(exit, &mut io),
            }
        }
        _ => {
            eprintln!("car-core-stub: an entry point is bridge, mcp or cli");
            3
        }
    };
    std::process::exit(code);
}
