//! The setup program carries a manifest that asks for no elevation (BRIDGE.md section 4): Windows' installer detection
//! would otherwise ask for administrator rights for a program whose name says setup.
fn main() {
    for argument in ["/MANIFEST:EMBED", "/MANIFESTUAC:level='asInvoker'"] {
        println!("cargo:rustc-link-arg-bin=codex-auto-resume-setup={argument}");
    }
    println!("cargo:rerun-if-changed=build.rs");
}
