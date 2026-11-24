//! The `python.exe` stand-in for old registrations and bootstraps (D9). Console subsystem; see the library.
fn main() {
    std::process::exit(car_legacy::main_for(car_legacy::Program::Console));
}
