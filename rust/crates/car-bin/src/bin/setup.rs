//! `codex-auto-resume-setup.exe`, the standard edition's setup program (BRIDGE.md, D9 means 2): Windows GUI subsystem,
//! an `asInvoker` manifest (build.rs). It runs the archive's own install\install.ps1 (car_bin::setup_main).
#![windows_subsystem = "windows"]

fn main() {
    std::process::exit(car_bin::setup_main("standard", &car_bin::arguments()));
}
