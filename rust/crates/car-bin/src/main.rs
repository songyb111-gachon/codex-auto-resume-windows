//! `codex-auto-resume.exe`, the standard edition's console program (PLAN 1.7): the core - its command line, bridge, MCP
//! server and setup commands, `car_bin::main_with(&[])` (S6.2b: the window now starts it for every bridge call, S6.2a).
//! The installer and bootstrap proofs never run it: they run the stub core, `car-core-proof.exe` (src/bin/proof.rs),
//! so no proof's `setup` reaches the real per-user registry (car-bin's lib.rs says how).
fn main() {
    std::process::exit(car_bin::main_with(&[]));
}
