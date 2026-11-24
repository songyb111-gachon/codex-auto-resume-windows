//! Per-user Windows registration: login autostart, and the toast button's URL protocol (`startup.py`).
//!
//! Both are optional, both are HKCU only, and both need no administrator rights. The only things ever written are
//! the single `CodexAutoResume` value under the current user's Run key and the `codex-auto-resume:` protocol keys
//! under the user's own class registrations - and, through `read_key`/`write_key`/`delete_key` at the foot of this
//! module, the one key of `addremove` under the user's Uninstall key. Every call goes through a [`Registry`], so a
//! test gives it a stand-in and nothing real is touched.
//!
//! Not ported, because they are about the Python interpreter that ran the reference: `python_launcher` and
//! `remote_debug_on`/`again_without_remote_debug` (PEP 768). The Rust core has no interpreter to find or to protect;
//! the launcher a value names is a parameter, and the options the reference puts after it (`NO_REMOTE_DEBUG`) are
//! one too, so a value written for an old install (D9's stand-ins) can still be made the same.

use std::path::{Path, PathBuf};

use crate::cmdline::{parse_command, quote_all, resolved, script_index};
use crate::paths::{identity_text, pathlib_text};
use crate::registry::{KEY_READ, KEY_SET_VALUE, Open, RegError, Registry, Root, TYPE_SZ, Value};

pub const RUN_KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
pub const VALUE_NAME: &str = "CodexAutoResume";
pub const PROTOCOL_SCHEME: &str = "codex-auto-resume";
pub const PROTOCOL_KEY: &str = "Software\\Classes\\codex-auto-resume";
pub const PROTOCOL_COMMAND_KEY: &str = "Software\\Classes\\codex-auto-resume\\shell\\open\\command";
pub const AUMID: &str = "CodexAutoResume.Watcher";
pub const AUMID_KEY: &str = "Software\\Classes\\AppUserModelId\\CodexAutoResume.Watcher";
pub const AUMID_DISPLAY_NAME: &str = "Codex Auto Resume";
/// The installation's own interpreter, relative to its home (`scripts/plugin_setup.bundled_python`).
pub const BUNDLED_PYTHONW: [&str; 2] = ["runtime", "pythonw.exe"];
/// `-X disable-remote-debug`: what the reference puts right after an interpreter (PEP 768), hyphens and all.
pub const NO_REMOTE_DEBUG: [&str; 2] = ["-X", "disable-remote-debug"];

/// A static reason only.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StartupError(pub &'static str);

impl std::fmt::Display for StartupError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for StartupError {}

/// The pythonw.exe a value Windows starts later names, where the installation at `home` has its bundled one.
pub fn bundled_pythonw(home: &Path) -> Option<PathBuf> {
    let bundled = BUNDLED_PYTHONW
        .iter()
        .fold(home.to_path_buf(), |path, part| path.join(part));
    bundled.is_file().then_some(bundled)
}

fn resolved_path(path: &Path) -> String {
    resolved(&path.to_string_lossy())
}

/// The sign-in (Run) value's command line - or, with `options`, one the product starts itself: every argument
/// quoted, always. `launcher` is what the reference found beside its interpreter; here the caller says.
pub fn command_line(
    entry_script: &Path,
    home: Option<&Path>,
    launcher: &str,
    options: &[&str],
) -> String {
    let mut argv: Vec<String> = vec![launcher.to_string()];
    argv.extend(options.iter().map(|option| option.to_string()));
    argv.push(resolved_path(entry_script));
    if let Some(home) = home {
        argv.push("--home".into());
        argv.push(resolved_path(home));
    }
    argv.push("run".into());
    quote_all(&argv)
}

/// The command Windows runs when a toast button activates our URI.
pub fn protocol_command_line(
    entry_script: &Path,
    home: &Path,
    launcher: &str,
    options: &[&str],
) -> String {
    let mut argv: Vec<String> = vec![launcher.to_string()];
    argv.extend(options.iter().map(|option| option.to_string()));
    argv.push(resolved_path(entry_script));
    argv.push("--home".into());
    argv.push(resolved_path(home));
    argv.push("--quiet".into());
    argv.push("activate".into());
    format!("{} \"%1\"", quote_all(&argv))
}

/// `startup._canonical`: one spelling for one location, so two can be compared.
pub fn canonical(value: &str) -> String {
    identity_text(value)
}

pub fn same_path(left: &str, right: &str) -> bool {
    canonical(left) == canonical(right)
}

/// True when `child` is `parent` or lives under it, both canonicalised.
pub fn inside(child: &str, parent: &str) -> bool {
    let (child_text, parent_text) = (canonical(child), canonical(parent));
    if child_text == parent_text {
        return true;
    }
    child_text.starts_with(&format!("{}\\", parent_text.trim_end_matches(['\\', '/'])))
}

/// True when this Run value starts the installation rooted at `home`.
pub fn belongs_to(command: &str, home: &str) -> bool {
    let argv = parse_command(command);
    for (index, argument) in argv.iter().enumerate() {
        if argument == "--home" && index + 1 < argv.len() && same_path(&argv[index + 1], home) {
            return true;
        }
    }
    let script = script_index(&argv);
    if argv.len() > script {
        return inside(&argv[script], home);
    }
    false
}

fn read_error(error: RegError, what: &'static str) -> Result<Option<()>, StartupError> {
    match error {
        RegError::NotFound => Ok(None),
        RegError::Other(_) => Err(StartupError(what)),
    }
}

/// A value read as a string only where it is one (`REG_SZ`); other types are no answer.
fn string_of(typed: crate::registry::Typed) -> Option<String> {
    match typed {
        (Value::Str(text), kind) if kind == TYPE_SZ => Some(text),
        _ => None,
    }
}

/// The current display name and icon for our AUMID, or None if unregistered.
pub fn aumid_registration(
    registry: &dyn Registry,
) -> Result<Option<Vec<(String, String)>>, StartupError> {
    let key = match Open::read(registry, Root::CurrentUser, AUMID_KEY, KEY_READ) {
        Ok(key) => key,
        Err(error) => {
            return read_error(error, "Cannot read the notification identity registration")
                .map(|_| None);
        }
    };
    let mut values = Vec::new();
    for name in ["DisplayName", "IconUri"] {
        match key.query(name) {
            Ok(typed) => {
                if let Some(text) = string_of(typed) {
                    values.push((name.to_string(), text));
                }
            }
            Err(RegError::NotFound) => {}
            Err(RegError::Other(_)) => {
                return Err(StartupError(
                    "Cannot read the notification identity registration",
                ));
            }
        }
    }
    Ok(if values.is_empty() {
        None
    } else {
        Some(values)
    })
}

fn lookup<'a>(values: &'a [(String, String)], name: &str) -> Option<&'a str> {
    values
        .iter()
        .find(|(key, _)| key == name)
        .map(|(_, value)| value.as_str())
}

/// Claim our AUMID for the current user. Idempotent; true when something was written.
pub fn register_aumid(
    registry: &dyn Registry,
    icon_path: Option<&Path>,
) -> Result<bool, StartupError> {
    let icon = icon_path.map(resolved_path);
    let current = aumid_registration(registry)?.unwrap_or_default();
    if lookup(&current, "DisplayName") == Some(AUMID_DISPLAY_NAME)
        && lookup(&current, "IconUri") == icon.as_deref()
    {
        return Ok(false);
    }
    let error = StartupError("Cannot register the notification identity");
    let key = Open::create(registry, Root::CurrentUser, AUMID_KEY, KEY_SET_VALUE)
        .map_err(|_| error.clone())?;
    key.set("DisplayName", &Value::Str(AUMID_DISPLAY_NAME.into()))
        .map_err(|_| error.clone())?;
    if let Some(icon) = icon.as_deref().filter(|icon| !icon.is_empty()) {
        key.set("IconUri", &Value::Str(icon.into()))
            .map_err(|_| error)?;
    }
    Ok(true)
}

/// Whether the registered notification identity belongs to `home`; None when nothing is registered.
pub fn notification_identity_owner(
    registry: &dyn Registry,
    home: &str,
) -> Result<Option<bool>, StartupError> {
    let Some(registration) = aumid_registration(registry)? else {
        return Ok(None);
    };
    match lookup(&registration, "IconUri") {
        Some(icon) if !icon.is_empty() => Ok(Some(inside(icon, home))),
        _ => Ok(Some(false)),
    }
}

/// Remove only our own AUMID key. Idempotent.
pub fn unregister_aumid(registry: &dyn Registry) -> bool {
    registry.delete_key(Root::CurrentUser, AUMID_KEY).is_ok()
}

pub fn protocol_value(registry: &dyn Registry) -> Result<Option<String>, StartupError> {
    let key = match Open::read(registry, Root::CurrentUser, PROTOCOL_COMMAND_KEY, KEY_READ) {
        Ok(key) => key,
        Err(error) => {
            return read_error(
                error,
                "Cannot read the current user's URL protocol registration",
            )
            .map(|_| None);
        }
    };
    match key.query("") {
        Ok(typed) => Ok(string_of(typed)),
        Err(RegError::NotFound) => Ok(None),
        Err(RegError::Other(_)) => Err(StartupError(
            "Cannot read the current user's URL protocol registration",
        )),
    }
}

/// Register the per-user URL protocol. Idempotent; true when something was written.
pub fn install_protocol(registry: &dyn Registry, command: &str) -> Result<bool, StartupError> {
    if protocol_value(registry)?.as_deref() == Some(command) {
        return Ok(false);
    }
    let error = StartupError("Cannot register the URL protocol for the current user");
    {
        let key = Open::create(registry, Root::CurrentUser, PROTOCOL_KEY, KEY_SET_VALUE)
            .map_err(|_| error.clone())?;
        key.set("", &Value::Str("URL:Codex Auto Resume".into()))
            .map_err(|_| error.clone())?;
        key.set("URL Protocol", &Value::Str(String::new()))
            .map_err(|_| error.clone())?;
    }
    let key = Open::create(
        registry,
        Root::CurrentUser,
        PROTOCOL_COMMAND_KEY,
        KEY_SET_VALUE,
    )
    .map_err(|_| error.clone())?;
    key.set("", &Value::Str(command.into()))
        .map_err(|_| error)?;
    Ok(true)
}

/// Remove only the keys this tool creates, deepest first. Idempotent.
pub fn uninstall_protocol(registry: &dyn Registry) -> bool {
    let mut removed = false;
    let open = format!("{PROTOCOL_KEY}\\shell\\open");
    let shell = format!("{PROTOCOL_KEY}\\shell");
    for path in [
        PROTOCOL_COMMAND_KEY,
        open.as_str(),
        shell.as_str(),
        PROTOCOL_KEY,
    ] {
        match registry.delete_key(Root::CurrentUser, path) {
            Ok(()) => removed = true,
            Err(RegError::NotFound) => continue,
            // A subkey added by something else must not be force-deleted.
            Err(RegError::Other(_)) => break,
        }
    }
    removed
}

/// The Run value, or None.
pub fn current_value(registry: &dyn Registry) -> Result<Option<String>, StartupError> {
    let key = match Open::read(registry, Root::CurrentUser, RUN_KEY, KEY_READ) {
        Ok(key) => key,
        Err(error) => {
            return read_error(error, "Cannot read the current user's Run key").map(|_| None);
        }
    };
    match key.query(VALUE_NAME) {
        Ok(typed) => Ok(string_of(typed)),
        Err(RegError::NotFound) => Ok(None),
        Err(RegError::Other(_)) => Err(StartupError("Cannot read the current user's Run key")),
    }
}

/// Idempotent: true when the value was created or changed.
pub fn install(registry: &dyn Registry, command: &str) -> Result<bool, StartupError> {
    if current_value(registry)?.as_deref() == Some(command) {
        return Ok(false);
    }
    let error = StartupError("Cannot write the current user's Run key");
    let key = Open::create(registry, Root::CurrentUser, RUN_KEY, KEY_SET_VALUE)
        .map_err(|_| error.clone())?;
    key.set(VALUE_NAME, &Value::Str(command.into()))
        .map_err(|_| error)?;
    Ok(true)
}

/// Idempotent: true when a value was removed.
pub fn uninstall(registry: &dyn Registry) -> Result<bool, StartupError> {
    let key = match Open::read(registry, Root::CurrentUser, RUN_KEY, KEY_SET_VALUE) {
        Ok(key) => key,
        Err(RegError::NotFound) => return Ok(false),
        Err(RegError::Other(_)) => {
            return Err(StartupError("Cannot remove the current user's Run value"));
        }
    };
    match key.delete_value(VALUE_NAME) {
        Ok(()) => Ok(true),
        Err(RegError::NotFound) => Ok(false),
        Err(RegError::Other(_)) => Err(StartupError("Cannot remove the current user's Run value")),
    }
}

// ------------------------------------------------------------------------------------------ a key's own values

/// The values of `names` under the HKCU key `path` that exist, or None when the key does not.
pub fn read_key(
    registry: &dyn Registry,
    path: &str,
    names: &[&str],
) -> Result<Option<Vec<(String, Value)>>, StartupError> {
    let key = match Open::read(registry, Root::CurrentUser, path, KEY_READ) {
        Ok(key) => key,
        Err(RegError::NotFound) => return Ok(None),
        Err(RegError::Other(_)) => {
            return Err(StartupError("Cannot read the current user's registry key"));
        }
    };
    let mut found = Vec::new();
    for name in names {
        match key.query(name) {
            Ok((value, _)) => found.push(((*name).to_string(), value)),
            Err(RegError::NotFound) => {}
            Err(RegError::Other(_)) => {
                return Err(StartupError("Cannot read the current user's registry key"));
            }
        }
    }
    Ok(Some(found))
}

/// Create the HKCU key `path` and set each value: a string as REG_SZ, a number as REG_DWORD.
pub fn write_key(
    registry: &dyn Registry,
    path: &str,
    values: &[(String, Value)],
) -> Result<(), StartupError> {
    let error = StartupError("Cannot write the current user's registry key");
    let key = Open::create(registry, Root::CurrentUser, path, KEY_SET_VALUE)
        .map_err(|_| error.clone())?;
    for (name, value) in values {
        key.set(name, value).map_err(|_| error.clone())?;
    }
    Ok(())
}

/// Idempotent: true when the HKCU key `path` was removed. A key with subkeys is refused by Windows, as it should be.
pub fn delete_key(registry: &dyn Registry, path: &str) -> Result<bool, StartupError> {
    match registry.delete_key(Root::CurrentUser, path) {
        Ok(()) => Ok(true),
        Err(RegError::NotFound) => Ok(false),
        Err(RegError::Other(_)) => Err(StartupError(
            "Cannot remove the current user's registry key",
        )),
    }
}

/// `str(Path(text))`, for callers that compare what they read to what they wrote.
pub fn path_text(text: &str) -> String {
    pathlib_text(text)
}
