//! `car-core-proof.exe`: the stub core, for the release's own proofs only (the installer proofs, `tests/install_double.py`
//! through CODEX_AUTO_RESUME_TEST_CORE, and `build/rust_legacy_bootstraps.py`'s entry check). Every command is refused
//! with NOT_PORTED (3) unless the test double is named, so a proof that reaches it writes nothing at all - no Run value,
//! no AUMID, no link handler in the real HKCU, which a scratch home does not redirect. Never shipped: rust_release.py
//! copies only codex-auto-resume.exe, and refuses any core that carries the test forward and is not this stub.
fn main() {
    std::process::exit(car_bin::core_main());
}
