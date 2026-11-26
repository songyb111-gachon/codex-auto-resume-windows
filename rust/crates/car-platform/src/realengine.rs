//! The real-engine guard: no test reaches this PC's installed Codex.
//!
//! Twice (2026-11-27) a test reached real engine discovery and started the codex.exe of the owner's running Codex
//! app. As `ipc_pipe` refuses the Desktop's real pipe, this module names what is this PC's real engine, and the places
//! that find, list or start an engine refuse it where the guard is on: in a crate's own tests (`cfg!(test)`, each
//! caller's), and in every process where [`SWITCH`] (`CAR_NO_REAL_ENGINE`) is set (car-harness, every rustdiff run and
//! the host's tests set it). Refused means "as if no engine were installed": discovery skips the build, the process list
//! leaves the app's processes out, and a start of the engine or of the app is refused as Windows refuses a program that
//! is not there.
//!
//! "Real" is decided by the folders Windows itself names (`SHGetKnownFolderPath`), never by the environment, which a
//! test points at its scratch folders: the account's `LocalAppData\OpenAI` (the official engine's builds) and
//! `LocalAppData\Microsoft\WindowsApps` (the app's aliases), `ProgramFiles\WindowsApps` (the Store app and the engine
//! it runs), the profile's `.vscode\extensions` (the extension's engine) and `RoamingAppData\npm` (the CLI). A scratch
//! folder under `%TEMP%` is none of these, so a diff's planted codex.exe is still found and run.

use std::ffi::OsString;
use std::os::windows::ffi::OsStringExt;
use std::sync::OnceLock;

use windows::Win32::System::Com::CoTaskMemFree;
use windows::Win32::UI::Shell::{
    FOLDERID_LocalAppData, FOLDERID_Profile, FOLDERID_ProgramFiles, FOLDERID_RoamingAppData,
    KNOWN_FOLDER_FLAG, SHGetKnownFolderPath,
};
use windows::core::GUID;

/// The switch: set (to anything) in a process, no engine of this PC is found, listed or started there.
pub const SWITCH: &str = "CAR_NO_REAL_ENGINE";

/// Whether [`SWITCH`] is set in this process. A crate's own tests add `cfg!(test)` themselves.
pub fn switched() -> bool {
    std::env::var_os(SWITCH).is_some()
}

fn known(folder: &GUID) -> Option<String> {
    // SAFETY: the folder id is a constant; the string Windows returns is ours to free with CoTaskMemFree.
    let path = unsafe { SHGetKnownFolderPath(folder, KNOWN_FOLDER_FLAG(0), None) }.ok()?;
    // SAFETY: a NUL-terminated string from the call above.
    let text = unsafe {
        let length = (0..).take_while(|&offset| *path.0.add(offset) != 0).count();
        OsString::from_wide(std::slice::from_raw_parts(path.0, length))
    };
    // SAFETY: allocated by the shell for us.
    unsafe { CoTaskMemFree(Some(path.0 as *const _)) };
    let text = text.to_string_lossy().into_owned();
    (!text.is_empty()).then_some(text)
}

/// What a path is compared as: `\\?\` dropped, `/` as `\`, lower case, no trailing separator.
fn folded(path: &str) -> String {
    let mut text = path.replace('/', "\\");
    if let Some(rest) = text.strip_prefix("\\\\?\\UNC\\") {
        text = format!("\\\\{rest}");
    } else if let Some(rest) = text.strip_prefix("\\\\?\\") {
        text = rest.to_owned();
    }
    let mut text = text.to_lowercase();
    while text.ends_with('\\') {
        text.pop();
    }
    text
}

/// The folders of this PC's real Codex: each folded, read once.
pub fn real_roots() -> &'static [String] {
    static ROOTS: OnceLock<Vec<String>> = OnceLock::new();
    ROOTS.get_or_init(|| {
        let mut roots = Vec::new();
        let mut add = |folder: &GUID, tail: &str| {
            if let Some(base) = known(folder) {
                roots.push(folded(&format!("{base}\\{tail}")));
            }
        };
        add(&FOLDERID_LocalAppData, "OpenAI");
        add(&FOLDERID_LocalAppData, "Microsoft\\WindowsApps");
        add(&FOLDERID_ProgramFiles, "WindowsApps");
        add(&FOLDERID_Profile, ".vscode\\extensions");
        add(&FOLDERID_RoamingAppData, "npm");
        roots
    })
}

/// Whether `path` is inside one of `roots` (each folded).
fn inside(path: &str, roots: &[String]) -> bool {
    let path = folded(path);
    roots.iter().any(|root| {
        path == *root
            || (path.len() > root.len()
                && path.starts_with(root.as_str())
                && path.as_bytes()[root.len()] == b'\\')
    })
}

/// Whether `path` is this PC's real Codex engine, app or CLI: inside one of [`real_roots`].
pub fn is_real_engine(path: &str) -> bool {
    inside(path, real_roots())
}

/// Whether discovery or a lookup leaves `path` out: the guard on (the switch, or `test`, the caller's own `cfg!(test)`)
/// and `path` this PC's real Codex.
pub fn refused(test: bool, path: &str) -> bool {
    (test || switched()) && is_real_engine(path)
}

/// Whether a process's package family is the Codex app's (OpenAI's).
pub fn is_real_family(family: &str) -> bool {
    family.to_lowercase().starts_with("openai.")
}

/// Whether an argument asks for the Codex app itself: a `codex:` link or the app by its Store id.
pub fn asks_for_the_app(argument: &str) -> bool {
    let text = argument.trim_start_matches('"').to_lowercase();
    text.starts_with("codex:") || text.contains("shell:appsfolder\\openai.")
}

/// Whether a start of `argv` is refused: the guard on (the switch, or `cfg!(test)` of the caller given as `on`) and
/// the program this PC's real engine, or an argument the app itself.
pub fn start_refused<S: AsRef<str>>(on: bool, argv: &[S]) -> bool {
    if !on {
        return false;
    }
    let Some((program, rest)) = argv.split_first() else {
        return false;
    };
    is_real_engine(program.as_ref())
        || rest
            .iter()
            .any(|argument| asks_for_the_app(argument.as_ref()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_roots_are_the_known_folders_not_the_environment() {
        let roots = real_roots();
        assert_eq!(roots.len(), 5, "{roots:?}");
        let local = folded(&known(&FOLDERID_LocalAppData).unwrap());
        assert!(roots.contains(&format!("{local}\\openai")));
        // A test's scratch folder (under %TEMP%, inside LocalAppData) is not real.
        let temp = std::env::temp_dir().join("x").join("codex.exe");
        assert!(!is_real_engine(&temp.to_string_lossy()));
    }

    #[test]
    fn inside_is_by_whole_components() {
        let roots = vec![folded("C:\\Users\\Example\\AppData\\Local\\OpenAI")];
        assert!(inside(
            "c:/users/example/appdata/local/openai/Codex/bin/ab/codex.exe",
            &roots
        ));
        assert!(inside(
            "\\\\?\\C:\\Users\\Example\\AppData\\Local\\OpenAI\\x",
            &roots
        ));
        assert!(!inside(
            "C:\\Users\\Example\\AppData\\Local\\OpenAIx\\codex.exe",
            &roots
        ));
        assert!(!inside("C:\\Users\\Example\\AppData\\Local", &roots));
    }

    #[test]
    fn the_real_engine_is_refused_and_a_scratch_one_is_not() {
        let local = known(&FOLDERID_LocalAppData).unwrap();
        let real = format!("{local}\\OpenAI\\Codex\\bin\\abc\\codex.exe");
        let scratch = std::env::temp_dir()
            .join("codex.exe")
            .to_string_lossy()
            .into_owned();
        assert!(start_refused(true, &[real.as_str(), "--version"]));
        assert!(!start_refused(false, &[real.as_str()]));
        assert!(!start_refused(true, &[scratch.as_str(), "--version"]));
        let explorer = "C:\\Windows\\explorer.exe";
        assert!(start_refused(true, &[explorer, "codex://threads/x"]));
        assert!(start_refused(
            true,
            &[explorer, "shell:AppsFolder\\OpenAI.Codex_x!App"]
        ));
        assert!(!start_refused(true, &[explorer, "C:\\x"]));
        assert!(is_real_family("OpenAI.Codex_2p2nqsd0c76g0"));
        assert!(!is_real_family("Microsoft.Something"));
    }
}
