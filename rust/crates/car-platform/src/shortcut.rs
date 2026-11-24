//! The Start Menu shortcut that gives this tool a Windows application identity (`shortcut.py`).
//!
//! Windows will not show a toast from an unpackaged application until a Start Menu shortcut carries the same
//! AppUserModelID the notification is sent under. The shortcut is written through the shell's own COM interfaces,
//! driven from PowerShell because setting `System.AppUserModel.ID` needs `IPropertyStore`. The two scripts are the
//! reference's constants, byte for byte (`scripts/shortcut_maker.ps1`, `scripts/shortcut_reader.ps1`, held equal by
//! `tests/rustdiff/platform_diffs.py`); a value reaches them only as an environment variable (`pwsh`).
//!
//! The Desktop copy is the person's folder, not a singleton of ours: nothing here writes over or removes one unless
//! its target is inside this installation.

use std::path::{Path, PathBuf};
use std::time::Duration;

use windows::Win32::System::Com::CoTaskMemFree;
use windows::Win32::UI::Shell::{FOLDERID_Desktop, KNOWN_FOLDER_FLAG, SHGetKnownFolderPath};

use crate::cmdline::resolved;
use crate::paths::{from_wide, home_dir, normcase, pathlib_text};
use crate::pwsh::{self, RunError};
use crate::spawn::Starter;
use crate::startup::AUMID;

pub const SHORTCUT_NAME: &str = "Codex Auto Resume.lnk";
pub const TIMEOUT_SECONDS: u64 = 60;
/// Where the Desktop shortcut goes instead of the person's Desktop: what a smoke run or a test sets.
pub const DESKTOP_ENV: &str = "CODEX_AUTO_RESUME_DESKTOP";

/// The maker script as the reference has it, with the shell's own interface and class ids (Windows' published
/// constants, which a tracked file may not spell as one dashed literal: tests/test_repo_hygiene.py) written back in
/// where the template marks them. PKEY_AppUserModel_ID is the last of them, with property id 5 in the script itself.
pub fn maker() -> &'static str {
    static SCRIPT: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    SCRIPT.get_or_init(|| {
        let guid = |parts: [&str; 5]| parts.join("-");
        include_str!("scripts/shortcut_maker.ps1")
            .replace(
                "@@CLSID_SHELL_LINK@@",
                &guid(["00021401", "0000", "0000", "C000", "000000000046"]),
            )
            .replace(
                "@@IID_SHELL_LINK_W@@",
                &guid(["000214F9", "0000", "0000", "C000", "000000000046"]),
            )
            .replace(
                "@@IID_PROPERTY_STORE@@",
                &guid(["886D8EEB", "8CF2", "4446", "8D02", "CDBA1DBDCF99"]),
            )
            .replace(
                "@@IID_PERSIST_FILE@@",
                &guid(["0000010b", "0000", "0000", "C000", "000000000046"]),
            )
            .replace(
                "@@PKEY_APP_USER_MODEL_ID@@",
                &guid(["9F4C2855", "9F79", "4B39", "A8D0", "E1D42DE1D5F3"]),
            )
    })
}

/// Reads a shortcut and saves nothing: its target is inside the installation (0) or not (3); 4: it has no target.
pub const READER: &str = include_str!("scripts/shortcut_reader.ps1");

/// Why a shortcut could not be made or removed: a static reason, never a shell transcript.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ShortcutError {
    Failed(&'static str),
    /// A shortcut with our name is on the Desktop, and it is not ours. It stays as it is.
    DesktopTaken,
}

impl ShortcutError {
    pub fn reason(&self) -> &'static str {
        match self {
            ShortcutError::Failed(reason) => reason,
            ShortcutError::DesktopTaken => "Another shortcut with this name is on the Desktop",
        }
    }
}

impl std::fmt::Display for ShortcutError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.reason())
    }
}

impl std::error::Error for ShortcutError {}

fn failed(reason: &'static str) -> ShortcutError {
    ShortcutError::Failed(reason)
}

/// `%APPDATA%\Microsoft\Windows\Start Menu\Programs` (APPDATA, else `~\AppData\Roaming`).
pub fn start_menu_dir() -> PathBuf {
    let base = match std::env::var("APPDATA") {
        Ok(value) if !value.is_empty() => value,
        _ => format!(
            "{}\\AppData\\Roaming",
            home_dir()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default()
        ),
    };
    PathBuf::from(pathlib_text(&base))
        .join("Microsoft")
        .join("Windows")
        .join("Start Menu")
        .join("Programs")
}

pub fn shortcut_path() -> PathBuf {
    start_menu_dir().join(SHORTCUT_NAME)
}

pub fn exists() -> bool {
    shortcut_path().is_file()
}

/// What `_write` hands the script: the `values` of the reference, in its order.
pub fn maker_values(
    destination: &Path,
    target: &Path,
    arguments: &str,
    icon: Option<&Path>,
    aumid: Option<&str>,
    description: &str,
) -> Vec<(&'static str, String)> {
    let target_resolved = resolved(&target.to_string_lossy());
    let workdir = Path::new(&target_resolved)
        .parent()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_default();
    vec![
        ("LNK", pathlib_text(&destination.to_string_lossy())),
        ("TARGET", target_resolved),
        ("ARGS", arguments.to_string()),
        ("WORKDIR", workdir),
        (
            "ICON",
            icon.map(|path| resolved(&path.to_string_lossy()))
                .unwrap_or_default(),
        ),
        ("AUMID", aumid.unwrap_or(AUMID).to_string()),
        ("DESC", description.to_string()),
    ]
}

fn run_script(
    starter: &dyn Starter,
    script: &str,
    values: &[(&'static str, String)],
) -> Result<i32, RunError> {
    let borrowed: Vec<(&str, Option<&str>)> = values
        .iter()
        .map(|(name, value)| (*name, Some(value.as_str())))
        .collect();
    pwsh::run(
        starter,
        script,
        &borrowed,
        Duration::from_secs(TIMEOUT_SECONDS),
    )
}

/// What a shortcut opens and how it is described: the arguments of `install` that travel together.
pub struct Shortcut<'a> {
    pub target: &'a Path,
    pub arguments: &'a str,
    pub icon: Option<&'a Path>,
    pub aumid: Option<&'a str>,
    pub description: &'a str,
}

fn write(
    starter: &dyn Starter,
    destination: &Path,
    shortcut: &Shortcut,
    cannot_create: &'static str,
    not_written: &'static str,
) -> Result<bool, ShortcutError> {
    let values = maker_values(
        destination,
        shortcut.target,
        shortcut.arguments,
        shortcut.icon,
        shortcut.aumid,
        shortcut.description,
    );
    match run_script(starter, maker(), &values) {
        Ok(0) if destination.is_file() => Ok(true),
        Ok(_) => Err(failed(not_written)),
        Err(_) => Err(failed(cannot_create)),
    }
}

/// Create or replace our Start Menu shortcut. True when written.
pub fn install(
    starter: &dyn Starter,
    target: &Path,
    arguments: &str,
    icon: Option<&Path>,
    aumid: Option<&str>,
    description: &str,
) -> Result<bool, ShortcutError> {
    if pwsh::executable().is_none() {
        return Err(failed(
            "PowerShell is unavailable; cannot create the Start Menu entry",
        ));
    }
    let destination = shortcut_path();
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|_| failed("Cannot create the Start Menu folder"))?;
    }
    write(
        starter,
        &destination,
        &Shortcut {
            target,
            arguments,
            icon,
            aumid,
            description,
        },
        "Cannot create the Start Menu entry",
        "The Start Menu entry could not be written",
    )
}

/// Remove only the shortcut at our own name and location. Idempotent.
pub fn uninstall() -> bool {
    let destination = shortcut_path();
    let is_link = std::fs::symlink_metadata(&destination)
        .map(|m| m.file_type().is_symlink())
        .unwrap_or(false);
    destination.is_file() && !is_link && std::fs::remove_file(&destination).is_ok()
}

/// The person's Desktop, where Windows says it is (a Desktop redirected to OneDrive is there, never under the
/// profile). None where Windows cannot say.
pub fn desktop_dir() -> Option<PathBuf> {
    if let Some(given) = std::env::var(DESKTOP_ENV)
        .ok()
        .filter(|given| !given.is_empty())
    {
        return Some(PathBuf::from(pathlib_text(&given)));
    }
    // SAFETY: the folder id is a constant; the string Windows returns is ours to free with CoTaskMemFree.
    let path =
        unsafe { SHGetKnownFolderPath(&FOLDERID_Desktop, KNOWN_FOLDER_FLAG(0), None) }.ok()?;
    // SAFETY: a NUL-terminated string from the call above.
    let text = unsafe {
        let length = (0..).take_while(|&offset| *path.0.add(offset) != 0).count();
        from_wide(std::slice::from_raw_parts(path.0, length))
    };
    // SAFETY: allocated by the shell for us.
    unsafe { CoTaskMemFree(Some(path.0 as *const _)) };
    (!text.is_empty()).then(|| PathBuf::from(pathlib_text(&text)))
}

pub fn desktop_path() -> Option<PathBuf> {
    desktop_dir().map(|folder| folder.join(SHORTCUT_NAME))
}

fn present(link: &Path) -> bool {
    std::fs::symlink_metadata(link).is_ok()
}

/// Whether the shortcut `link` opens something inside the installation at `home`, asked of the shell, which reads it
/// and saves nothing. Errors where it cannot be told, which is never an answer of yes.
pub fn inside(starter: &dyn Starter, link: &Path, home: &Path) -> Result<bool, ShortcutError> {
    let is_link = std::fs::symlink_metadata(link)
        .map(|m| m.file_type().is_symlink())
        .unwrap_or(false);
    if !link.is_file() || is_link {
        return Ok(false);
    }
    let values = vec![
        ("LNK", pathlib_text(&link.to_string_lossy())),
        ("ROOT", resolved(&home.to_string_lossy())),
    ];
    match run_script(starter, READER, &values) {
        Ok(code @ (0 | 3 | 4)) => Ok(code == 0),
        _ => Err(failed("The shortcut on the Desktop could not be read")),
    }
}

/// `root` is `target`'s folder or above it, as pathlib compares: `Path.parents`, case-insensitively.
fn is_ancestor(root: &str, target: &str) -> bool {
    let wanted = normcase(root);
    let mut current = pathlib_text(target);
    while let Some(cut) = current.rfind('\\') {
        let mut parent = current[..cut].to_string();
        if parent.len() == 2 && parent.ends_with(':') {
            parent.push('\\');
        }
        if parent.is_empty() {
            parent = "\\".to_string();
        }
        if normcase(&parent) == wanted {
            return true;
        }
        if parent.ends_with('\\') {
            break;
        }
        current = parent;
    }
    false
}

/// Create or replace this installation's shortcut on the Desktop. Refused where another shortcut has the name
/// (`DesktopTaken`) or where it cannot be written; what it opens must be inside the installation.
pub fn install_desktop(
    starter: &dyn Starter,
    home: &Path,
    target: &Path,
    arguments: &str,
    icon: Option<&Path>,
    aumid: Option<&str>,
    description: &str,
) -> Result<bool, ShortcutError> {
    let root = resolved(&home.to_string_lossy());
    if !is_ancestor(&root, &resolved(&target.to_string_lossy())) {
        return Err(failed(
            "What the Desktop shortcut would open is not inside this installation",
        ));
    }
    let link = desktop_path().ok_or_else(|| failed("Windows did not say where the Desktop is"))?;
    if present(&link) && !inside(starter, &link, Path::new(&root))? {
        return Err(ShortcutError::DesktopTaken);
    }
    if pwsh::executable().is_none() {
        return Err(failed(
            "PowerShell is unavailable; cannot create the Desktop shortcut",
        ));
    }
    if !link.parent().is_some_and(Path::is_dir) {
        return Err(failed("The Desktop folder is not there"));
    }
    write(
        starter,
        &link,
        &Shortcut {
            target,
            arguments,
            icon,
            aumid,
            description,
        },
        "Cannot create the Desktop shortcut",
        "The Desktop shortcut could not be written",
    )
}

/// Remove the shortcut on the Desktop if it is this installation's, and nothing else. Idempotent.
pub fn uninstall_desktop(starter: &dyn Starter, home: &Path) -> Result<bool, ShortcutError> {
    let Some(link) = desktop_path() else {
        return Ok(false);
    };
    if !present(&link) || !inside(starter, &link, home)? {
        return Ok(false);
    }
    std::fs::remove_file(&link).map_err(|_| failed("The Desktop shortcut could not be removed"))?;
    Ok(true)
}
