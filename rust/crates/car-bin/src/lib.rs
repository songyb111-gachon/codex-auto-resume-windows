//! car-bin: the shared half of the binaries, so the other edition's build can reuse it (seat S5.2).
//!
//! `codex-auto-resume.exe` is [`roles::main_with`]: the bridge (`bridge`), the MCP server (`mcp`), `plugin_setup.py`'s
//! commands ([`setup`]) and the command line ([`cli`]), every word parsed as the reference's argparse parses it
//! ([`argparse`] over the tag's own tables, `parsers_gen.rs`). The advanced edition's binary passes its own [`Role`]s
//! to [`main_with`]: the role registry seam (P7-DESIGN).
//!
//! `codex-auto-resume-setup.exe` is still the stub S8.1 made ([`setup_stub`], [`NOT_PORTED`]): the setup program is
//! S8.2's (branch car-v0627-package2/fix9), and its integration replaces it. [`core_stub`] stays for that branch's test
//! double.

pub mod argparse;
pub mod cli;
pub mod launcher;
#[rustfmt::skip]
pub mod parsers_gen;
pub mod roles;
pub mod seam;
pub mod setup;
pub mod uris;

pub use roles::{Role, main_with};

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
