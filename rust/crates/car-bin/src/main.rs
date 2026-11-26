//! `codex-auto-resume.exe`, the standard edition's console program (PLAN 1.7): the stub core (car-bin's lib.rs says
//! why); the core's command line, bridge, MCP server and setup commands are `car_bin::main_with(&[])`.
fn main() {
    // The stub core until the release proofs can run the real one on a scratch home (lib.rs); `main_with(&[])` then.
    std::process::exit(car_bin::core_main());
}
