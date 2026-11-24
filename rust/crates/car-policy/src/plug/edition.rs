//! `edition.py`: which edition an installation is, and the plug it runs with.
//!
//! The advanced edition is the standard edition with one more package beside core's, in the same `src` folder; nothing
//! is stamped anywhere to say which. [`name`] looks, exactly as Python's path finder looks (the package's folder by
//! its exact name in the listing, and its first `__init__` file the source one), so the installer, the bootstrap and
//! the core agree, and [`cached_copy`] reads the edition of Codex's newest copy of this plugin the same way.
//!
//! In Rust the advanced code is compiled into the advanced binaries (D2), so [`load`] takes the advanced crate's
//! factory where Python imported a package: the standard binaries pass none and run NULL; an installation the look
//! calls advanced, whose plug cannot be made - no factory in this binary, another PLUG_API, a factory that fails or
//! makes no advanced plug - runs as the standard edition with a [`DamagedPlug`] that says why, and is never half loaded.

use std::path::Path;
use std::time::UNIX_EPOCH;

use super::vocab_gen::edition as words;
use super::{DamagedPlug, Edition, Guarded, PLUG_API, Plug, PlugFailure};

pub const ADVANCED_PACKAGE: &str = "codex_auto_resume_advanced";
pub const NOT_LOADED: &str = words::NOT_LOADED;
pub const MARKETPLACE: &str = "codex-auto-resume-windows";
pub const PLUGIN: &str = "codex-auto-resume";
/// The `__init__` files Python's path finder tries, in its order (CPython 3.13 on 64-bit Windows: extension modules,
/// then source, then bytecode). Only the source one makes the folder a package of this edition.
pub const INIT_SUFFIXES: &[&str] = &[".cp313-win_amd64.pyd", ".pyd", ".py", ".pyw", ".pyc"];

/// `_beside(src)`: whether the advanced package sits in `src` - its folder in the listing by its exact name, and the
/// first `__init__` file the path finder would take the `.py` one.
pub fn beside(src: &Path) -> bool {
    let Ok(listing) = std::fs::read_dir(src) else {
        return false;
    };
    let named = listing
        .filter_map(Result::ok)
        .any(|entry| entry.file_name().to_str() == Some(ADVANCED_PACKAGE));
    if !named {
        return false;
    }
    let base = src.join(ADVANCED_PACKAGE);
    for suffix in INIT_SUFFIXES {
        if std::fs::metadata(base.join(format!("__init__{suffix}")))
            .is_ok_and(|found| found.is_file())
        {
            return *suffix == ".py";
        }
    }
    false
}

/// `name(src)`: ADVANCED when the advanced package sits beside core's, else STANDARD.
pub fn name(src: &Path) -> Edition {
    if beside(src) {
        Edition::Advanced
    } else {
        Edition::Standard
    }
}

/// The advanced crate's factory, as an advanced binary hands it to [`load`]: the PLUG_API it was written for, and
/// the function that makes its plug.
pub struct Factory {
    pub api: i64,
    pub create: fn() -> Result<Box<dyn Plug>, super::HookFailed>,
}

/// The log's line for an advanced installation that runs as the standard edition: `advanced_not_loaded <reason>`.
pub fn not_loaded_line(reason: PlugFailure) -> String {
    format!("{NOT_LOADED} {}", reason.as_str())
}

fn damaged(reason: PlugFailure) -> Guarded {
    Guarded::new(Box::new(DamagedPlug { reason }))
}

/// `load(paths)`: the plug for the installation whose `src` folder is `src`: NULL for the standard edition, the
/// advanced crate's own plug, or a DamagedPlug when it cannot be taken as it is. Never fails.
pub fn load(src: &Path, factory: Option<&Factory>) -> Guarded {
    if !beside(src) {
        return Guarded::null();
    }
    let Some(factory) = factory else {
        return damaged(PlugFailure::ImportFailed);
    };
    if factory.api != PLUG_API {
        return damaged(PlugFailure::ApiMismatch);
    }
    match std::panic::catch_unwind(factory.create) {
        Ok(Ok(made)) if made.damaged().is_none() && made.edition() == Edition::Advanced => {
            Guarded::new(made)
        }
        _ => damaged(PlugFailure::FactoryFailed),
    }
}

/// `shown(plug)`: the edition every surface names beside the version - `standard` or `advanced`, or NOT_LOADED for
/// an advanced installation whose plug could not be made.
pub fn shown(plug: &Guarded) -> &'static str {
    let held = plug.held();
    if held.damaged().is_some() {
        return NOT_LOADED;
    }
    held.edition().as_str()
}

/// `st_mtime` as CPython computes it: whole seconds plus the nanoseconds times 1e-9, as a float.
fn mtime(path: &Path) -> Option<f64> {
    let since = std::fs::metadata(path)
        .ok()?
        .modified()
        .ok()?
        .duration_since(UNIX_EPOCH)
        .ok()?;
    Some(since.as_secs() as f64 + f64::from(since.subsec_nanos()) * 1e-9)
}

/// `cached_copy(codex_home)`: the edition of the newest copy Codex keeps of this plugin, or None when it keeps none or
/// it cannot be read. `is_symlink` is `os.path.islink` (a real symbolic link only).
pub fn cached_copy(codex_home: &Path, is_symlink: &dyn Fn(&Path) -> bool) -> Option<Edition> {
    let root = codex_home
        .join("plugins")
        .join("cache")
        .join(MARKETPLACE)
        .join(PLUGIN);
    let mut newest: Option<(f64, std::path::PathBuf)> = None;
    for entry in std::fs::read_dir(&root).ok()? {
        let path = entry.ok()?.path();
        let copy = std::fs::metadata(&path).is_ok_and(|found| found.is_dir())
            && !is_symlink(&path)
            && std::fs::metadata(path.join("src").join("codex_auto_resume"))
                .is_ok_and(|found| found.is_dir());
        if !copy {
            continue;
        }
        let when = mtime(&path)?;
        if newest.as_ref().is_none_or(|(best, _)| when > *best) {
            newest = Some((when, path));
        }
    }
    newest.map(|(_, path)| name(&path.join("src")))
}
