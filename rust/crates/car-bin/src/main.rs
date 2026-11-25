//! `codex-auto-resume.exe`, the standard edition's console program (PLAN 1.7): the core's command line, bridge, MCP
//! server and setup commands. The standard edition has no roles of its own beyond car-bin's.
fn main() {
    std::process::exit(car_bin::main_with(&[]));
}
