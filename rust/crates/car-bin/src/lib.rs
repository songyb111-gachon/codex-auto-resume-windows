//! car-bin: the shared half of the binaries, so the other edition's build can reuse it.
//!
//! Until the core is ported (S5.1/S5.2) this is the **stub core** the packaging skeleton (S8.1) ships: every command
//! of `codex-auto-resume.exe` and every start of `codex-auto-resume-setup.exe` is refused with [`NOT_PORTED`], so an
//! old updater that reaches it through car-legacy (D9) ends on a code it already reads as "did not finish" and changes
//! nothing, and v0.6.26's setup handover reports "it ended with code 3" and keeps the installation it had. The stub
//! never answers success for work it did not do.

/// The code a command that is not ported yet ends with (as `car-core-stub` and the shim lane answer it).
pub const NOT_PORTED: i32 = 3;

/// `codex-auto-resume.exe <words>`: one line on standard error naming the words, then [`NOT_PORTED`].
pub fn core_stub(words: &[String]) -> i32 {
    eprintln!(
        "codex-auto-resume: `{}` is not ported yet (stub core); nothing was done",
        words.join(" ")
    );
    NOT_PORTED
}

/// `codex-auto-resume-setup.exe <words>` (BRIDGE.md section 4): a program of the Windows GUI subsystem, so it has no
/// stream to write to; it ends with [`NOT_PORTED`] and shows no window. The real one installs `edition`'s archive.
pub fn setup_stub(edition: &str, words: &[String]) -> i32 {
    let _ = (edition, words);
    NOT_PORTED
}

/// This process's arguments after the program, as text (lossy where one is not Unicode: the stub only names them).
pub fn arguments() -> Vec<String> {
    std::env::args_os()
        .skip(1)
        .map(|argument| argument.to_string_lossy().into_owned())
        .collect()
}
