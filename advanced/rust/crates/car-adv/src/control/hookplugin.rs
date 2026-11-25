//! Continue inside the turn (`stop_hook_continuation`): the Stop hook's declaration, written into this product's own plugin
//! copies while the capability is on, and removed the moment it is not (`control/hookplugin.py`).
//!
//! Where: this plugin's roots and no other file - the installation's own (`<home>/app`, the marketplace Codex was given) and
//! each advanced copy Codex keeps of this plugin (`<CODEX_HOME>/plugins/cache/<marketplace>/<plugin>/<version>`), as the
//! format names them. Never Codex's `config.toml`, never another plugin's files, never a path that leaves its root or runs
//! through a link. Codex's own hook-trust prompt gates what is written; nothing here bypasses it.
//!
//! `follow` makes the files match the capability's stored state - written while it is on, removed when it is off. A
//! declaration file is removed only when every command in it is one of ours; one a person or another tool wrote is left as it
//! is. The one write is [`Files::write`] and the one removal [`Files::remove`] - the seam a test replaces (the tag's `WRITER`
//! and `REMOVER`).
//!
//! SEAT S7.3c. `Edges::hook_follow` (S7.1b's seam) is [`follow`] with the Codex home S7.2c's `inuse::home` names.

use std::path::{Path, PathBuf};

use car_config::Paths;
use car_machine::compat::loads;
use car_machine::json::{Options, Value, to_string};
use car_machine::pyval;

use crate::hook::format::{FORMAT, HookFormat, commands_in, declaration};

pub const CAPABILITY: &str = "stop_hook_continuation";
pub const HOOK_DIR: &str = "hook";
pub const HOOK_EXE: &str = "codex-auto-resume-hook.exe";
const MANIFEST: [&str; 2] = [".codex-plugin", "plugin.json"];
const ADVANCED_PACKAGE: [&str; 2] = ["src", "codex_auto_resume_advanced"];
/// `edition.MARKETPLACE, PLUGIN`.
pub const MARKETPLACE: &str = "codex-auto-resume-windows";
pub const PLUGIN: &str = "codex-auto-resume";

/// The one write and the one removal.
pub trait Files {
    fn write(&self, path: &Path, document: &Value) -> std::io::Result<()>;
    fn remove(&self, path: &Path) -> std::io::Result<()>;
}

/// `write_declaration` and `remove_declaration`: the real ones.
pub struct Real;

impl Files for Real {
    /// `document` as UTF-8 JSON at `path`, whole or not at all (a temporary file beside it, replaced).
    fn write(&self, path: &Path, document: &Value) -> std::io::Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut name = path.file_name().unwrap_or_default().to_os_string();
        name.push(".tmp");
        let temporary = path.with_file_name(name);
        let text = to_string(document, &Options::new().ensure_ascii(false).indent(2))
            .map_err(|_| std::io::Error::other("unwritable"))?;
        // `Path.write_text` is text mode: on Windows every "\n" is written "\r\n".
        std::fs::write(&temporary, format!("{text}\n").replace('\n', "\r\n"))?;
        car_platform::files::replace(&temporary, path)
    }

    /// The file at `path`, and its folder if that is left empty.
    fn remove(&self, path: &Path) -> std::io::Result<()> {
        std::fs::remove_file(path)?;
        if let Some(parent) = path.parent() {
            let _ = std::fs::remove_dir(parent);
        }
        Ok(())
    }
}

fn link(path: &Path) -> bool {
    car_config::paths::is_link(&path.to_string_lossy())
}

fn same(a: &Path, b: &Path) -> bool {
    car_config::winpath::same_path(&a.to_string_lossy(), &b.to_string_lossy())
}

/// `_linked(path, root)`: whether `path`, or any folder between it and `root`, is a link or a junction.
fn linked(path: &Path, root: &Path) -> bool {
    let mut current = path.to_path_buf();
    loop {
        if current.exists() && link(&current) {
            return true;
        }
        let parent = match current.parent() {
            Some(parent) => parent.to_path_buf(),
            None => return false,
        };
        if same(&current, root) || same(&parent, &current) {
            return false;
        }
        current = parent;
    }
}

fn plugin_root(folder: &Path) -> bool {
    folder.is_dir()
        && !link(folder)
        && MANIFEST
            .iter()
            .fold(folder.to_path_buf(), |path, part| path.join(part))
            .is_file()
        && ADVANCED_PACKAGE
            .iter()
            .fold(folder.to_path_buf(), |path, part| path.join(part))
            .is_dir()
}

/// `launcher(paths)`: the hook launcher in the installation's home: where the advanced archive puts it.
pub fn launcher(paths: &Paths) -> PathBuf {
    Path::new(&paths.home)
        .join("app")
        .join(HOOK_DIR)
        .join(HOOK_EXE)
}

/// `roots(paths, codex_home, found)`: this plugin's advanced roots that exist, as FORMAT.roots names them.
pub fn roots(paths: &Paths, codex_home: Option<&Path>, found: &HookFormat) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if found.roots.contains(&"installation") {
        let installation = Path::new(&paths.home).join("app");
        if plugin_root(&installation) {
            out.push(installation);
        }
    }
    if found.roots.contains(&"codex_copy")
        && let Some(home) = codex_home
    {
        let cache = home
            .join("plugins")
            .join("cache")
            .join(MARKETPLACE)
            .join(PLUGIN);
        let mut copies: Vec<PathBuf> = if cache.is_dir() && !linked(&cache, home) {
            match std::fs::read_dir(&cache) {
                Ok(entries) => entries
                    .filter_map(Result::ok)
                    .map(|entry| entry.path())
                    .filter(|entry| plugin_root(entry))
                    .collect(),
                Err(_) => Vec::new(),
            }
        } else {
            Vec::new()
        };
        // `sorted(Path)`: pathlib's Windows flavour compares case-folded parts.
        copies.sort_by_key(|path| path.to_string_lossy().to_lowercase());
        out.extend(copies);
    }
    out
}

/// `command(paths, found)`: the command the declaration runs.
pub fn command(paths: &Paths, found: &HookFormat) -> String {
    if found.command == "contained" {
        return format!("./{HOOK_DIR}/{HOOK_EXE}");
    }
    car_config::winpath::path_str(&launcher(paths).to_string_lossy())
}

/// `ours(paths, found)`: every command a declaration of ours may run: the launcher's absolute path, and its path inside the
/// plugin.
pub fn ours(paths: &Paths) -> Vec<String> {
    vec![
        car_config::winpath::path_str(&launcher(paths).to_string_lossy()),
        format!("./{HOOK_DIR}/{HOOK_EXE}"),
    ]
}

/// `target(root, found)`: the declaration file under `root`, or None where it would leave the root or run through a link.
pub fn target(root: &Path, found: &HookFormat) -> Option<PathBuf> {
    let path = found
        .file
        .iter()
        .fold(root.to_path_buf(), |path, part| path.join(part));
    let resolved_root = std::fs::canonicalize(root).ok()?;
    // `path.resolve()` of a path that is not there yet: its folder's real place and the name.
    let resolved = resolve_loose(&path)?;
    if !car_config::winpath::is_relative_to(
        &strip_verbatim(&resolved),
        &strip_verbatim(&resolved_root),
    ) || linked(&path, root)
    {
        return None;
    }
    Some(path)
}

fn strip_verbatim(path: &Path) -> String {
    let text = path.to_string_lossy();
    text.strip_prefix(r"\\?\").unwrap_or(&text).to_owned()
}

/// `Path.resolve()` where the last parts may not exist: the longest existing prefix resolved, the rest appended.
fn resolve_loose(path: &Path) -> Option<PathBuf> {
    let mut tail = Vec::new();
    let mut current = path.to_path_buf();
    loop {
        if let Ok(real) = std::fs::canonicalize(&current) {
            return Some(
                tail.iter()
                    .rev()
                    .fold(real, |base, part: &std::ffi::OsString| base.join(part)),
            );
        }
        let name = current.file_name()?.to_os_string();
        tail.push(name);
        current = current.parent()?.to_path_buf();
    }
}

fn read(path: &Path) -> Option<Value> {
    let bytes = std::fs::read(path).ok()?;
    let text = String::from_utf8(bytes).ok()?;
    loads(&text).ok()
}

/// `_manifest(root, found, present)`: the manifest's key for the declaration, where FORMAT names one: set while it is on,
/// taken out when it is off.
fn manifest(
    root: &Path,
    found: &HookFormat,
    present: bool,
    files: &dyn Files,
) -> std::io::Result<()> {
    let Some(key) = found.manifest_key else {
        return Ok(());
    };
    let path = MANIFEST
        .iter()
        .fold(root.to_path_buf(), |path, part| path.join(part));
    let Some(Value::Object(mut document)) = read(&path) else {
        return Ok(());
    };
    let wanted = Value::from(format!("./{}", found.file.join("/")));
    let held = document.get(key).cloned();
    if present && !held.as_ref().is_some_and(|each| pyval::eq(each, &wanted)) {
        document.insert(car_machine::json::Str::from(key), wanted);
    } else if !present && held.as_ref().is_some_and(|each| pyval::eq(each, &wanted)) {
        document.shift_remove(key);
    } else {
        return Ok(());
    }
    files.write(&path, &Value::Object(document))
}

fn removable(document: &Option<Value>, paths: &Paths) -> bool {
    let Some(document) = document else {
        return false;
    };
    match commands_in(document) {
        Some(commands) => {
            let ours = ours(paths);
            !commands.is_empty() && commands.iter().all(|each| ours.contains(each))
        }
        None => false,
    }
}

/// `write(paths, codex_home, found)`: the declaration written into every root where it is not already as it should be: how
/// many were written.
pub fn write(
    paths: &Paths,
    codex_home: Option<&Path>,
    found: &HookFormat,
    files: &dyn Files,
) -> std::io::Result<usize> {
    let document = declaration(&command(paths, found), found);
    let mut written = 0;
    for root in roots(paths, codex_home, found) {
        let Some(path) = target(&root, found) else {
            continue;
        };
        let current = read(&path);
        if current
            .as_ref()
            .is_some_and(|each| pyval::eq(each, &document))
        {
            continue;
        }
        // `_read(path) if path.exists() else None`; a file that exists and is not one of ours is never replaced.
        if path.exists() && !removable(&current, paths) {
            continue;
        }
        files.write(&path, &document)?;
        manifest(&root, found, true, files)?;
        written += 1;
    }
    Ok(written)
}

/// `remove(paths, codex_home, found)`: every declaration of ours removed from every root: how many were.
pub fn remove(
    paths: &Paths,
    codex_home: Option<&Path>,
    found: &HookFormat,
    files: &dyn Files,
) -> std::io::Result<usize> {
    let mut removed = 0;
    for root in roots(paths, codex_home, found) {
        let Some(path) = target(&root, found) else {
            continue;
        };
        if !path.is_file() || !removable(&read(&path), paths) {
            continue;
        }
        files.remove(&path)?;
        manifest(&root, found, false, files)?;
        removed += 1;
    }
    Ok(removed)
}

/// `present(paths, codex_home, found)`: whether a declaration of ours stands in any root.
pub fn present(paths: &Paths, codex_home: Option<&Path>, found: &HookFormat) -> bool {
    roots(paths, codex_home, found).iter().any(|root| {
        target(root, found).is_some_and(|path| path.is_file() && removable(&read(&path), paths))
    })
}

/// `follow(paths, codex_home, armed, found)`: the declarations made to match the capability: written while `armed`, removed
/// otherwise. Never raises (a panic is caught here too, D15).
pub fn follow(
    paths: &Paths,
    codex_home: Option<&Path>,
    armed: bool,
    found: &HookFormat,
    files: &dyn Files,
) -> usize {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if armed {
            write(paths, codex_home, found, files)
        } else {
            remove(paths, codex_home, found, files)
        }
    }))
    .ok()
    .and_then(Result::ok)
    .unwrap_or(0)
}

/// `follow(paths, codex_home, armed)` with the shipped format and the real files: what `Edges::hook_follow` calls.
pub fn follow_real(paths: &Paths, codex_home: Option<&Path>, armed: bool) -> usize {
    follow(paths, codex_home, armed, &FORMAT, &Real)
}
