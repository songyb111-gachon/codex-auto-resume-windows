//! Run a fixed Windows PowerShell script, with values passed beside it rather than in it (`pwsh.py`).
//!
//! The reasons are the reference's, and they stand: a value never becomes script text (PowerShell's tokenizer treats
//! four more characters as single quotes, which made a project folder's name a code injection); each travels as an
//! environment variable of the child, the script reads it with `$env:NAME`; and the script itself is the one
//! argument after `-Command`, quoted by `list2cmdline` - never as base64 behind an encoded-command switch (issue
//! #65). The child always has `CREATE_NO_WINDOW` (`spawn`).

use std::ffi::OsString;
use std::path::PathBuf;
use std::time::Duration;

use crate::spawn::{Spawn, SpawnError, Starter, Stream};

/// Namespaced so a value can never collide with, or be mistaken for, a real setting.
pub const PREFIX: &str = "CODEX_AUTO_RESUME_ARG_";
/// Windows limits an environment variable to 32,767 characters; a value near it is a bug, refused rather than cut.
pub const MAX_VALUE: usize = 16000;

/// A static reason only - never a transcript, never a value.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PowerShellError(pub &'static str);

impl std::fmt::Display for PowerShellError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for PowerShellError {}

/// `[A-Z][A-Z0-9_]{0,40}\Z`.
fn valid_name(name: &str) -> bool {
    let mut characters = name.chars();
    match characters.next() {
        Some(first) if first.is_ascii_uppercase() => {}
        _ => return false,
    }
    let rest: Vec<char> = characters.collect();
    rest.len() <= 40
        && rest
            .iter()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || *c == '_')
}

/// The in-box Windows PowerShell, by absolute path, never whatever is on PATH.
pub fn executable() -> Option<PathBuf> {
    let root = std::env::var("SystemRoot")
        .ok()
        .filter(|value| !value.is_empty())?;
    let path = PathBuf::from(root)
        .join("System32")
        .join("WindowsPowerShell")
        .join("v1.0")
        .join("powershell.exe");
    path.is_file().then_some(path)
}

/// The child's environment: ours, minus every argument variable a parent set, plus one variable per value.
pub fn environment(
    values: &[(&str, Option<&str>)],
) -> Result<Vec<(OsString, OsString)>, PowerShellError> {
    let mut child: Vec<(OsString, OsString)> = std::env::vars_os()
        .filter(|(name, _)| !name.to_string_lossy().to_uppercase().starts_with(PREFIX))
        .collect();
    for (name, value) in values {
        if !valid_name(name) {
            return Err(PowerShellError("invalid argument name"));
        }
        let text = value.unwrap_or("");
        if text.contains('\0') {
            return Err(PowerShellError("an argument contains a NUL character"));
        }
        if text.chars().count() > MAX_VALUE {
            return Err(PowerShellError("an argument is too long"));
        }
        child.push((
            OsString::from(format!("{PREFIX}{name}")),
            OsString::from(text),
        ));
    }
    Ok(child)
}

/// How a fixed script refers to a value: `$env:CODEX_AUTO_RESUME_ARG_NAME`.
pub fn reference(name: &str) -> Result<String, PowerShellError> {
    if !valid_name(name) {
        return Err(PowerShellError("invalid argument name"));
    }
    Ok(format!("$env:{PREFIX}{name}"))
}

/// The argv that runs the constant `script`: the script whole, as the one argument after `-Command`.
pub fn script_argv(shell: &str, script: &str) -> Vec<String> {
    vec![
        shell.to_string(),
        "-NoProfile".into(),
        "-NonInteractive".into(),
        "-Command".into(),
        script.to_string(),
    ]
}

/// What `run` can fail with.
#[derive(Debug)]
pub enum RunError {
    PowerShell(PowerShellError),
    Spawn(SpawnError),
}

impl From<PowerShellError> for RunError {
    fn from(error: PowerShellError) -> Self {
        RunError::PowerShell(error)
    }
}

impl From<SpawnError> for RunError {
    fn from(error: SpawnError) -> Self {
        RunError::Spawn(error)
    }
}

/// Run `script` with `values` available as environment variables; its exit code. `script` must be a constant: it is
/// the caller's code, not data.
pub fn run(
    starter: &dyn Starter,
    script: &str,
    values: &[(&str, Option<&str>)],
    timeout: Duration,
) -> Result<i32, RunError> {
    let shell = executable().ok_or(PowerShellError("PowerShell is unavailable"))?;
    let spawn = Spawn::new(script_argv(&shell.to_string_lossy(), script))
        .with_env(environment(values)?)
        .with_streams(Stream::Null, Stream::Null, Stream::Null);
    Ok(starter.run(&spawn, timeout)?)
}
