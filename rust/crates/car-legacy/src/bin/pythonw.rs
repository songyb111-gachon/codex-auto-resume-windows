//! The `pythonw.exe` stand-in (D9): the old Run value and protocol handler started pythonw, so no console window.
#![windows_subsystem = "windows"]

fn main() {
    std::process::exit(car_legacy::main_for(car_legacy::Program::Windowless));
}
