//! `setaside.py`: what an update moved aside and could not delete, swept when the watcher starts (v0.6.18) and from
//! the Dashboard's bridge (v0.6.24).
//!
//! An update moves `app`, `runtime` and the Dashboard's files aside as `<name>.old-<stamp>` before it copies the new
//! ones, and deletes them once the copy is in place - unless something still had them open. The watcher sweeps them
//! as it starts, once it holds its mutex. It touches nothing in a home that is not provably ours, while an
//! installation runs (or whether one does cannot be told), while the installer's copy journal is there, that is not a
//! direct child named `<name>.old-<14 digits>`, or that is a link or junction; a folder any running program's file
//! lies in is left for a later look, and every folder is left where that list cannot be made.

use std::path::{Path, PathBuf};

use car_config::Paths;

/// install.ps1 `$Journal`.
pub const JOURNAL: &str = ".codex-auto-resume-install-journal.json";

/// The log line, with its two counts.
pub const SWEPT_LINE: &str = "set-aside copies an update left: %d removed, %d still in use";

/// `SET_ASIDE.fullmatch(name)`: `[^\\/]+\.old-\d{14}(\.sweep)?` - `\d` being any Unicode decimal digit, as `re`
/// reads a `str` pattern.
pub fn is_set_aside(name: &str) -> bool {
    // A name ending `.sweep` has no digit last, so it can match only with the group: stripping it is the one reading.
    matches_old(name.strip_suffix(".sweep").unwrap_or(name))
}

fn matches_old(body: &str) -> bool {
    let chars: Vec<char> = body.chars().collect();
    if chars.len() < 14 {
        return false;
    }
    let (head, digits) = chars.split_at(chars.len() - 14);
    if !digits.iter().all(|c| car_machine::pytext::is_digit(*c)) {
        return false;
    }
    // `[^\\/]+` then `.old-`: the head ends with `.old-` and has at least one character before it, none a slash.
    let head: String = head.iter().collect();
    match head.strip_suffix(".old-") {
        Some(name) => !name.is_empty() && !head.contains(['\\', '/']),
        None => false,
    }
}

/// `candidates(home)`: the set-aside copies directly under `home`, by name, in `sorted(iterdir())`'s order; links
/// and junctions are never one.
pub fn candidates(home: &str) -> Vec<String> {
    let Ok(listing) = std::fs::read_dir(home) else {
        return Vec::new();
    };
    let mut entries: Vec<String> = Vec::new();
    for entry in listing {
        let Ok(entry) = entry else {
            // `iterdir` raises mid-listing: `sorted(...)` raises, and `candidates` answers [].
            return Vec::new();
        };
        entries.push(entry.file_name().to_string_lossy().into_owned());
    }
    // PureWindowsPath orders by its case-folded parts; every entry has the same parent, so the name decides.
    entries.sort_by(|a, b| {
        let (left, right) = (
            car_platform::paths::normcase(a),
            car_platform::paths::normcase(b),
        );
        left.cmp(&right)
    });
    entries
        .into_iter()
        .filter(|name| is_set_aside(name))
        .map(|name| join(home, &name))
        .filter(|path| !car_config::paths::is_link(path))
        .collect()
}

fn join(home: &str, name: &str) -> String {
    Path::new(home).join(name).to_string_lossy().into_owned()
}

/// `_holds_a_program(entry, images)`: whether a running program's file lies inside the folder, by full path,
/// case-blind.
fn holds_a_program(entry: &str, images: &[String]) -> bool {
    let resolved = car_platform::paths::realpath(entry);
    let inside = format!(
        "{}\\",
        car_platform::paths::normcase(&resolved).trim_end_matches(['\\', '/'])
    );
    images
        .iter()
        .any(|image| car_platform::paths::normcase(image).starts_with(&inside))
}

/// What the sweep asks of this machine: whether an installation runs (None: it cannot be told), and the images of
/// every running process this account can look at (None: no list).
pub trait Machine {
    fn installing(&self) -> Option<bool>;
    fn running(&self) -> Option<Vec<String>>;
    /// `os.rename(entry, target)`: refused while anything in it is open.
    fn rename(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        car_platform::files::rename(from, to)
    }
}

/// This PC.
pub struct ThisMachine;

impl Machine for ThisMachine {
    fn installing(&self) -> Option<bool> {
        Some(car_platform::homelock::install_in_progress())
    }

    fn running(&self) -> Option<Vec<String>> {
        car_platform::kernel::running_images()
    }
}

/// `shutil.rmtree(target)` as CPython does it on Windows: depth first, a file removed with `os.unlink` (refused for a
/// read-only file, as `DeleteFileW` refuses it), a link or junction removed as itself and never followed, a folder
/// with `os.rmdir` once empty; the first refusal ends it.
pub fn rmtree(target: &Path) -> std::io::Result<()> {
    std::fs::symlink_metadata(target)?;
    if link_like(target) {
        // rmtree refuses a link given as its own top ("Cannot call rmtree on a symbolic link"), OSError.
        return Err(std::io::Error::other("Cannot call rmtree on a symbolic link"));
    }
    remove_tree(target)
}

/// `_rmtree_islink`, and what `os.walk(..., followlinks=_walk_symlinks_as_files)` reports as a file: a symbolic link
/// or a junction, never another kind of reparse point.
fn link_like(path: &Path) -> bool {
    matches!(
        car_platform::links::reparse_tag(path),
        Some(car_platform::links::SYMLINK_TAG | car_platform::links::MOUNT_POINT_TAG)
    )
}

/// The entry's own FILE_ATTRIBUTE_DIRECTORY, a link's included: `Py_DeleteFileW` removes such a link with
/// `RemoveDirectoryW`.
#[cfg(windows)]
fn folder_attribute(path: &Path) -> bool {
    use std::os::windows::fs::MetadataExt;
    std::fs::symlink_metadata(path).is_ok_and(|meta| meta.file_attributes() & 0x10 != 0)
}

#[cfg(not(windows))]
fn folder_attribute(path: &Path) -> bool {
    std::fs::symlink_metadata(path).is_ok_and(|meta| meta.is_dir())
}

/// A removal that found nothing to remove: rmtree passes over it.
fn gone(result: std::io::Result<()>) -> std::io::Result<()> {
    match result {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        other => other,
    }
}

/// `os.walk(folder, topdown=False)` with each folder's subfolders removed before its files, as rmtree does; a link
/// or junction is a file there, and `os.unlink` removes a folder link as itself (`RemoveDirectoryW`).
fn remove_tree(folder: &Path) -> std::io::Result<()> {
    let mut folders: Vec<PathBuf> = Vec::new();
    let mut files: Vec<PathBuf> = Vec::new();
    let listing = match std::fs::read_dir(folder) {
        Ok(listing) => listing,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };
    for entry in listing {
        let path = entry?.path();
        if !link_like(&path) && path.is_dir() {
            folders.push(path);
        } else {
            files.push(path);
        }
    }
    for child in &folders {
        remove_tree(child)?;
    }
    for child in &files {
        if folder_attribute(child) {
            gone(std::fs::remove_dir(child))?;
        } else {
            gone(std::fs::remove_file(child))?;
        }
    }
    gone(std::fs::remove_dir(folder))
}

/// `sweep(paths, log, installing=..., running=...)`: delete what an update set aside in `paths.home`, where nothing
/// holds it. (swept, left in use).
pub fn sweep(paths: &Paths, log: Option<&dyn Fn(&str)>, machine: &dyn Machine) -> (i64, i64) {
    let home = &paths.home;
    let found = candidates(home);
    if found.is_empty() {
        return (0, 0);
    }
    if Path::new(home).join(JOURNAL).exists()
        || machine.installing() != Some(false)
        || !paths.owns_home()
    {
        return (0, 0);
    }
    let mut images: Option<Option<Vec<String>>> = None;
    let (mut swept, mut left) = (0, 0);
    for entry in found {
        if !paths.confined(&entry) || car_config::paths::is_link(&entry) {
            continue;
        }
        let path = Path::new(&entry);
        let outcome: std::io::Result<()> = (|| {
            if path.is_dir() {
                let listed = images.get_or_insert_with(|| machine.running());
                match listed {
                    None => return Err(std::io::Error::other("held")),
                    Some(list) if holds_a_program(&entry, list) => {
                        return Err(std::io::Error::other("held"));
                    }
                    Some(_) => {}
                }
                let name = path
                    .file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default();
                let target = if name.ends_with(".sweep") {
                    path.to_path_buf()
                } else {
                    path.with_file_name(format!("{name}.sweep"))
                };
                if target != path {
                    machine.rename(path, &target)?;
                }
                rmtree(&target)
            } else {
                std::fs::remove_file(path)
            }
        })();
        match outcome {
            Ok(()) => swept += 1,
            Err(_) => left += 1,
        }
    }
    if let Some(log) = log {
        log(&format!(
            "set-aside copies an update left: {swept} removed, {left} still in use"
        ));
    }
    (swept, left)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names() {
        for good in [
            "app.old-20261126010203",
            "runtime.old-20261126010203.sweep",
            "a.b.old-20261126010203",
            "x.old-٢٠٢٦١١٢٦٠١٠٢٠٣",
        ] {
            assert!(is_set_aside(good), "{good}");
        }
        for bad in [
            ".old-20261126010203",
            "app.old-2026112601020",
            "app.old-202611260102034",
            "app.old-20261126010203.sweep.sweep",
            "app.old-20261126010203x",
            "app.OLD-20261126010203",
            "app",
        ] {
            assert!(!is_set_aside(bad), "{bad}");
        }
    }
}
