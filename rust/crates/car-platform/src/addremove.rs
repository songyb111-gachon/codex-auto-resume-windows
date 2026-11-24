//! The entry in Windows' list of installed programs ("Add or remove programs"), and nothing else (`addremove.py`).
//!
//! One key per edition under the current user's Uninstall key, by a fixed name (`CodexAutoResume`, and another
//! edition's with its word added), only one of them at a time. What is removed is what can be proved ours: a key is
//! this installation's only when its `InstallLocation` is this home and its uninstall command runs this home's
//! kept uninstaller. Every registry call is `startup`'s, through a [`Registry`].

use std::path::{Path, PathBuf};

use crate::cmdline::{parse_command, quote_all};
use crate::registry::{Registry, Value};
use crate::startup::{self, StartupError};

pub const UNINSTALL_ROOT: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall";
pub const BASE_NAME: &str = "CodexAutoResume";
pub const PUBLISHER: &str = "songyb111-gachon";
pub const DEFAULT_DISPLAY_NAME: &str = "Codex Auto Resume";
pub const FIRST_VERSION: &str = "0.6.16";
pub const KEEP_ENTRY_ENV: &str = "CODEX_AUTO_RESUME_KEEP_ENTRY";
pub const KEPT_FOLDER: &str = "uninstall";
pub const KEPT_SCRIPT: &str = "install.ps1";
pub const WINDOW: &str = "CodexAutoResumeSettings.exe";
pub const WINDOW_SWITCH: &str = "--uninstall";
pub const ICON: &str = "codex-auto-resume.ico";
pub const VALUE_NAMES: [&str; 9] = [
    "DisplayName",
    "DisplayVersion",
    "Publisher",
    "InstallLocation",
    "UninstallString",
    "QuietUninstallString",
    "NoModify",
    "NoRepair",
    "DisplayIcon",
];

/// The standard edition's key is `CodexAutoResume`; another edition adds its word, capitalised.
pub fn key_name(edition: &str) -> String {
    if edition == "standard" {
        return BASE_NAME.to_string();
    }
    let mut letters = edition.chars();
    let word: String = match letters.next() {
        Some(first) => first
            .to_uppercase()
            .chain(letters.flat_map(|c| c.to_lowercase()))
            .collect(),
        None => String::new(),
    };
    format!("{BASE_NAME}{word}")
}

pub fn key_path(edition: &str) -> String {
    format!("{UNINSTALL_ROOT}\\{}", key_name(edition))
}

pub fn kept_script(home: &Path) -> PathBuf {
    home.join(KEPT_FOLDER).join(KEPT_SCRIPT)
}

/// An ordinary folder or file: not a symbolic link, not a junction or any other reparse point.
fn plain(path: &Path, directory: bool) -> bool {
    use std::os::windows::fs::MetadataExt;
    let Ok(info) = std::fs::symlink_metadata(path) else {
        return false;
    };
    if info.file_type().is_symlink() || info.file_attributes() & 0x400 != 0 {
        return false;
    }
    if directory {
        info.is_dir()
    } else {
        info.is_file()
    }
}

/// The kept uninstaller is there, and so is the folder it is in, as plain files and not links.
pub fn kept_uninstaller_present(home: &Path) -> bool {
    plain(&home.join(KEPT_FOLDER), true) && plain(&kept_script(home), false)
}

/// Delete the kept uninstaller, and its folder once empty. Only plain ones; true when the script is gone.
pub fn remove_kept(home: &Path) -> bool {
    if !kept_uninstaller_present(home) {
        return false;
    }
    let _ = std::fs::remove_file(kept_script(home))
        .and_then(|()| std::fs::remove_dir(home.join(KEPT_FOLDER)));
    !kept_script(home).exists()
}

pub fn powershell() -> PathBuf {
    let root = std::env::var("SystemRoot")
        .ok()
        .filter(|value| !value.is_empty())
        .or_else(|| {
            std::env::var("windir")
                .ok()
                .filter(|value| !value.is_empty())
        })
        .unwrap_or_else(|| "C:\\Windows".to_string());
    PathBuf::from(root)
        .join("System32")
        .join("WindowsPowerShell")
        .join("v1.0")
        .join("powershell.exe")
}

fn text(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

/// The kept uninstaller, as a command (see the reference's docstring: shown in the installer window by the
/// Dashboard program where it is there and not `silent`; by PowerShell otherwise, with `-Silent` when quiet).
pub fn uninstall_command(home: &Path, silent: bool) -> String {
    let window = home.join(WINDOW);
    if !silent && window.is_file() {
        return quote_all(&[
            text(&window),
            WINDOW_SWITCH.to_string(),
            text(&kept_script(home)),
        ]);
    }
    let mut argv: Vec<String> = vec![
        text(&powershell()),
        "-NoLogo".into(),
        "-NoProfile".into(),
        "-ExecutionPolicy".into(),
        "Bypass".into(),
        "-File".into(),
        text(&kept_script(home)),
        "-Uninstall".into(),
    ];
    if silent {
        argv.push("-Silent".into());
    }
    quote_all(&argv)
}

/// The name the installed manifest gives this edition (another edition's carries its word).
pub fn display_name(manifest_path: &Path) -> String {
    let read = || -> Option<String> {
        let bytes = std::fs::read(manifest_path).ok()?;
        let body = String::from_utf8(bytes).ok()?;
        let body = body.strip_prefix('\u{feff}').unwrap_or(&body);
        let manifest: serde_json::Value = serde_json::from_str(body).ok()?;
        let name = match manifest.get("interface")?.get("displayName")? {
            serde_json::Value::String(text) => text.clone(),
            serde_json::Value::Null => "None".to_string(),
            serde_json::Value::Bool(true) => "True".to_string(),
            serde_json::Value::Bool(false) => "False".to_string(),
            serde_json::Value::Number(number) => number.to_string(),
            _ => return None,
        };
        Some(name.trim().to_string())
    };
    match read() {
        Some(name) if !name.is_empty() => name,
        _ => DEFAULT_DISPLAY_NAME.to_string(),
    }
}

/// The installed program's icon, for Settings > Apps: the icon file the installer puts in the home, else the
/// Dashboard program's own (`,0`); None where neither is there.
pub fn display_icon(home: &Path) -> Option<String> {
    for (name, suffix) in [(ICON, ""), (WINDOW, ",0")] {
        if plain(&home.join(name), false) {
            return Some(format!("{}{suffix}", text(&home.join(name))));
        }
    }
    None
}

/// The values of one key, in the reference's order.
pub fn entry_values(home: &Path, name: &str, version: &str) -> Vec<(String, Value)> {
    let mut values = vec![
        ("DisplayName".to_string(), Value::Str(name.to_string())),
        (
            "DisplayVersion".to_string(),
            Value::Str(version.to_string()),
        ),
        ("Publisher".to_string(), Value::Str(PUBLISHER.to_string())),
        ("InstallLocation".to_string(), Value::Str(text(home))),
        (
            "UninstallString".to_string(),
            Value::Str(uninstall_command(home, false)),
        ),
        (
            "QuietUninstallString".to_string(),
            Value::Str(uninstall_command(home, true)),
        ),
        ("NoModify".to_string(), Value::Int(1)),
        ("NoRepair".to_string(), Value::Int(1)),
    ];
    if let Some(icon) = display_icon(home) {
        values.push(("DisplayIcon".to_string(), Value::Str(icon)));
    }
    values
}

/// The values of the key of this edition's name, or None when there is none.
pub fn read(
    registry: &dyn Registry,
    edition: &str,
) -> Result<Option<Vec<(String, Value)>>, StartupError> {
    startup::read_key(registry, &key_path(edition), &VALUE_NAMES)
}

fn get<'a>(values: &'a [(String, Value)], name: &str) -> Option<&'a Value> {
    values
        .iter()
        .find(|(key, _)| key == name)
        .map(|(_, value)| value)
}

fn same_values(left: &[(String, Value)], right: &[(String, Value)]) -> bool {
    left.len() == right.len()
        && left
            .iter()
            .all(|(name, value)| get(right, name) == Some(value))
}

/// True when this key describes the installation rooted at `home`: it is installed there, and what it runs to
/// uninstall is this home's kept uninstaller.
pub fn owned(values: Option<&[(String, Value)]>, home: &Path) -> bool {
    let Some(values) = values.filter(|values| !values.is_empty()) else {
        return false;
    };
    let (Some(Value::Str(location)), Some(Value::Str(command))) = (
        get(values, "InstallLocation"),
        get(values, "UninstallString"),
    ) else {
        return false;
    };
    if !startup::same_path(location, &text(home)) {
        return false;
    }
    let argv = parse_command(command);
    let script = text(&kept_script(home));
    argv.iter()
        .skip(1)
        .any(|argument| startup::same_path(argument, &script))
}

/// Write this edition's key for the installation at `home`, and take the other edition's away when it is this
/// installation's. Nothing is written unless the kept uninstaller is there, and nothing over a key that is not
/// this installation's. `editions` is every edition there is, the one registered among them (the editions are the
/// caller's to name: this crate belongs to every edition and names none). Returns what was done.
pub fn register(
    registry: &dyn Registry,
    home: &Path,
    edition: &str,
    editions: &[&str],
    version: &str,
    name: Option<&str>,
) -> Result<Vec<String>, StartupError> {
    let mut done = Vec::new();
    if !editions.contains(&edition)
        || !kept_uninstaller_present(home)
        || version.is_empty()
        || version == "unknown"
    {
        return Ok(done);
    }
    let existing = read(registry, edition)?;
    if existing.is_some() && !owned(existing.as_deref(), home) {
        return Ok(done);
    }
    let values = entry_values(
        home,
        name.filter(|n| !n.is_empty())
            .unwrap_or(DEFAULT_DISPLAY_NAME),
        version,
    );
    if existing
        .as_deref()
        .is_none_or(|existing| !same_values(existing, &values))
    {
        startup::write_key(registry, &key_path(edition), &values)?;
        done.push(format!("wrote {}", key_name(edition)));
    }
    for &other in editions {
        if other != edition && remove_edition(registry, other, home)? {
            done.push(format!("removed {}", key_name(other)));
        }
    }
    Ok(done)
}

/// Delete this edition's key if it is this installation's. True when it was deleted.
pub fn remove_edition(
    registry: &dyn Registry,
    edition: &str,
    home: &Path,
) -> Result<bool, StartupError> {
    let values = read(registry, edition)?;
    if !owned(values.as_deref(), home) {
        return Ok(false);
    }
    startup::delete_key(registry, &key_path(edition))
}

/// Delete whichever of `editions`' keys is this installation's. The names of the keys removed.
pub fn unregister(
    registry: &dyn Registry,
    home: &Path,
    editions: &[&str],
) -> Result<Vec<String>, StartupError> {
    let mut removed = Vec::new();
    for &edition in editions {
        if remove_edition(registry, edition, home)? {
            removed.push(key_name(edition));
        }
    }
    Ok(removed)
}
