//! `codex-auto-resume-setup.exe`, the advanced edition's setup program (BRIDGE.md, D9 means 2): Windows GUI subsystem,
//! an `asInvoker` manifest (build.rs). The stub until S8.2.
#![windows_subsystem = "windows"]

fn main() {
    std::process::exit(car_bin::setup_stub("advanced", &car_bin::arguments()));
}
