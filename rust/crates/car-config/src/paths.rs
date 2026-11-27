//! `config.py`'s `Paths`: all the files this tool owns, under one root, and what an uninstall may take.
//!
//! Every name is the Python's, resolved the way `Path(root).expanduser().resolve()` resolves it (`winpath`). The
//! provenance marker is what makes a deletion safe: nothing is deleted from a directory that does not carry it,
//! that is a link or a junction, or that resolves outside the home. `load_settings`, `save_settings` and
//! `update_settings` of the Python module read `settings`, which this crate may not (cut C2): they are
//! car-policy's.

use std::collections::BTreeSet;
use std::fs;
use std::path::Path;
use std::sync::Arc;

use car_machine::compat::loads;
use car_machine::json::Value;

use crate::winpath::{self, Env};

pub const ENV_HOME: &str = "CODEX_AUTO_RESUME_HOME";
pub const ENV_CODEX_EXE: &str = "CODEX_AUTO_RESUME_CODEX_EXE";
/// Provenance marker: uninstall deletes ONLY inside a directory this tool created.
pub const OWNER_MARKER: &str = ".owned-by-codex-auto-resume";
pub const OWNER_TEXT: &str =
    "Created by codex-auto-resume. Deleting this file makes `uninstall` skip this directory.\n";
/// What `write_text` puts on disk: the text with Windows' line end (text mode).
pub const OWNER_TEXT_ON_DISK: &str =
    "Created by codex-auto-resume. Deleting this file makes `uninstall` skip this directory.\r\n";
const REPARSE_POINT: u32 = 0x400;

/// Static reason only; never includes file contents.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConfigError(pub String);

impl std::fmt::Display for ConfigError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for ConfigError {}

/// What `ensure()` raised: its own refusal (`ConfigError`), or the `OSError` of a `mkdir` - FileExistsError where a file
/// has the folder's name (`config` a file), which stops it before `logs/` is made, as `directory.mkdir(parents=True,
/// exist_ok=True)` does.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EnsureError {
    Config(ConfigError),
    /// The exception's class (car-machine's `os_error_class`) and its text.
    Os {
        class: &'static str,
        message: String,
    },
}

impl EnsureError {
    /// The class the reference raises.
    pub fn class(&self) -> &'static str {
        match self {
            EnsureError::Config(_) => "ConfigError",
            EnsureError::Os { class, .. } => class,
        }
    }

    /// `str(exc)`, as near as the error says it.
    pub fn message(&self) -> String {
        match self {
            EnsureError::Config(refused) => refused.0.clone(),
            EnsureError::Os { message, .. } => message.clone(),
        }
    }
}

impl From<ConfigError> for EnsureError {
    fn from(refused: ConfigError) -> EnsureError {
        EnsureError::Config(refused)
    }
}

impl std::fmt::Display for EnsureError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message())
    }
}

impl std::error::Error for EnsureError {}

/// What the operating system is asked: where relative paths start, and whether a path past 260 characters
/// is taken without its `\\?\` prefix (the registry's LongPathsEnabled, which car-platform reads).
#[derive(Clone, Debug)]
pub struct Os {
    pub cwd: String,
    pub long_paths: bool,
    /// The link probe: `Path.is_symlink()` (see [`Links`]).
    pub links: Arc<dyn Links>,
}

/// The one question the config asks of Windows about a path that it cannot ask by itself: whether the path is a
/// symbolic link as Python's `Path.is_symlink()` says (cut C3, as car-store's `Links`). A junction is not one, so a
/// junction inside the home passes `ensure()`, `claim_home()` and `owns_home()`, as in the reference; the reference's
/// own `config.is_link` - any reparse point at all - is [`is_link`], which needs no tag. car-platform has the one
/// probe (`car_platform::links::is_symlink`); the harness and the entry points wire it in.
pub trait Links: Send + Sync + std::fmt::Debug {
    /// `Path(path).is_symlink()`.
    fn is_symlink(&self, path: &Path) -> bool;
    /// `os.readlink(path)` for `Path.resolve()`'s walk (std reads the reparse data as CPython does).
    fn readlink(&self, path: &str) -> winpath::Readlink {
        winpath::os_readlink(path)
    }
    /// `nt._findfirstfile(path)`: the last component's real name. Only a probe of the platform can ask it; without one
    /// the walk splits the name off as written (the error a FindFirstFileW that fails would give).
    fn find_first_file(&self, path: &str) -> Result<String, i32> {
        let _ = path;
        Err(50)
    }
    /// Whether discovery leaves `path` out, as if it were not installed: this PC's installed Codex where the
    /// real-engine guard is on (car-platform's `realengine::refused`: the switch `CAR_NO_REAL_ENGINE`, or the probe's
    /// own crate's tests). A probe that does not know answers no.
    fn engine_refused(&self, path: &str) -> bool {
        let _ = path;
        false
    }
}

/// Whether discovery leaves `path` out (the probe's [`Links::engine_refused`]).
pub fn engine_refused(os: &Os, path: &str) -> bool {
    os.links.engine_refused(path)
}

/// The questions `Path.resolve()` asks, through this `Os`: the final path by std, links and real names by the probe.
struct Asked<'a>(&'a Os);

impl winpath::NtOs for Asked<'_> {
    fn final_path(&self, path: &str) -> Result<String, i32> {
        winpath::os_final_path(path)
    }
    fn readlink(&self, path: &str) -> winpath::Readlink {
        self.0.links.readlink(path)
    }
    fn is_symlink(&self, path: &str) -> bool {
        self.0.links.is_symlink(Path::new(path))
    }
    fn find_first_file(&self, path: &str) -> Result<String, i32> {
        self.0.links.find_first_file(path)
    }
    fn long_paths(&self) -> bool {
        self.0.long_paths
    }
}

impl Os {
    /// This process's working directory, and long paths and the link probe as the caller says.
    pub fn here(long_paths: bool, links: Arc<dyn Links>) -> Os {
        Os {
            cwd: std::env::current_dir()
                .map(|found| found.to_string_lossy().into_owned())
                .unwrap_or_default(),
            long_paths,
            links,
        }
    }

    /// `Path(p).resolve()`: the path made absolute and real as far as it exists; `Err` is the Windows error number.
    pub fn resolve(&self, path: &str) -> Result<String, i32> {
        let normal = winpath::path_str(path);
        winpath::realpath_os(&normal, &self.cwd, &Asked(self))
    }
}

/// `is_link(path)`: whether `path` is a symbolic link or any other reparse point - an NTFS junction above all.
pub fn is_link(path: &str) -> bool {
    link_attributes(Path::new(path))
}

#[cfg(windows)]
fn link_attributes(path: &Path) -> bool {
    use std::os::windows::fs::MetadataExt;
    fs::symlink_metadata(path).is_ok_and(|found| found.file_attributes() & REPARSE_POINT != 0)
}

#[cfg(not(windows))]
fn link_attributes(path: &Path) -> bool {
    let _ = REPARSE_POINT;
    fs::symlink_metadata(path).is_ok_and(|found| found.file_type().is_symlink())
}

fn is_dir(path: &str) -> bool {
    Path::new(path).is_dir()
}

fn is_file(path: &str) -> bool {
    Path::new(path).is_file()
}

/// `a / b` as pathlib writes it.
fn child(parent: &str, name: &str) -> String {
    winpath::path_str(&winpath::join(parent, name))
}

/// The key `sorted()` orders paths by: their components, lower-cased.
fn order_key(path: &str) -> Vec<String> {
    let (drive, root, tail) = winpath::parse(path);
    let mut key = vec![format!("{drive}{root}").to_lowercase()];
    key.extend(tail.iter().map(|part| part.to_lowercase()));
    key
}

fn sorted(mut paths: Vec<String>) -> Vec<String> {
    paths.sort_by_key(|path| order_key(path));
    paths
}

/// `name` matches `prefix*suffix`, as `glob` matches on Windows (case-insensitively).
fn globbed(name: &str, prefix: &str, suffix: &str) -> bool {
    let name = name.to_lowercase();
    name.len() >= prefix.len() + suffix.len()
        && name.starts_with(&prefix.to_lowercase())
        && name.ends_with(&suffix.to_lowercase())
}

fn base_name(path: &str) -> String {
    winpath::parse(path).2.last().cloned().unwrap_or_default()
}

/// The entries of a directory, as full paths (unsorted); `Err` where it cannot be listed.
fn entries(directory: &str) -> Result<Vec<String>, std::io::Error> {
    let mut found = Vec::new();
    for each in fs::read_dir(directory)? {
        found.push(child(directory, &each?.file_name().to_string_lossy()));
    }
    Ok(found)
}

/// All files this tool owns live under one root (default: the project directory).
#[derive(Clone, Debug)]
pub struct Paths {
    pub home: String,
    pub state_dir: String,
    pub logs_dir: String,
    pub settings_file: String,
    /// The Compatibility Registry's two files, both content-free.
    pub compat_report_file: String,
    pub compat_cache_file: String,
    pub failure_seen_file: String,
    pub status_file: String,
    pub self_check_file: String,
    pub split_chains_file: String,
    pub codex_layout_file: String,
    pub power_action_file: String,
    pub once_words_file: String,
    pub edition_left_file: String,
    /// The advanced edition's own state, named here only so a purge can take it.
    pub advanced_dir: String,
    pub accounts_dir: String,
    pub log_file: String,
    pub error_log: String,
    pub codex_start_log: String,
    pub entry_script: String,
    pub icon_file: String,
    os: Os,
}

impl Paths {
    /// `Paths(home)`: `home`, else `CODEX_AUTO_RESUME_HOME`, else the project root; expanded and resolved. `Err` names
    /// the exception the Python raises (`RuntimeError` for a home it cannot expand, `OSError` for a path the system
    /// refuses to resolve).
    pub fn new(
        home: Option<&str>,
        project_root: &str,
        env: Env,
        os: Os,
    ) -> Result<Paths, &'static str> {
        let root = home
            .filter(|each| !each.is_empty())
            .map(str::to_owned)
            .or_else(|| env(ENV_HOME).filter(|each| !each.is_empty()))
            .unwrap_or_else(|| project_root.to_owned());
        let expanded = winpath::expanduser(&root, env)?;
        let home = os.resolve(&expanded).map_err(|_| "OSError")?;
        let home = winpath::path_str(&home);
        let under = |folder: &str, name: &str| child(folder, name);
        let state_dir = under(&home, "config");
        let logs_dir = under(&home, "logs");
        Ok(Paths {
            settings_file: under(&state_dir, "settings.json"),
            compat_report_file: under(&state_dir, "compatibility.json"),
            compat_cache_file: under(&state_dir, "compat-cache.json"),
            failure_seen_file: under(&state_dir, "failure-seen.json"),
            status_file: under(&state_dir, "status.json"),
            self_check_file: under(&state_dir, "selfcheck.json"),
            split_chains_file: under(&state_dir, "split-chains.json"),
            codex_layout_file: under(&state_dir, "codex-layout.json"),
            power_action_file: under(&state_dir, "power-action.json"),
            once_words_file: under(&state_dir, "once-words.json"),
            edition_left_file: under(&state_dir, "edition-left.txt"),
            advanced_dir: under(&state_dir, "advanced"),
            accounts_dir: under(&home, "accounts"),
            log_file: under(&logs_dir, "auto-resume.log"),
            error_log: under(&logs_dir, "errors.log"),
            codex_start_log: under(&logs_dir, "codex-start.log"),
            entry_script: child(&child(project_root, "src"), "auto_resume.py"),
            icon_file: under(&home, "codex-auto-resume.ico"),
            state_dir,
            logs_dir,
            home,
            os,
        })
    }

    /// `Path(path).is_symlink()`.
    fn is_symlink(&self, path: &str) -> bool {
        self.os.links.is_symlink(Path::new(path))
    }

    fn resolved(&self, path: &str) -> Result<String, i32> {
        self.os.resolve(path)
    }

    /// `confined(path)`: true only if, after resolving ALL reparse points, the path stays in home.
    pub fn confined(&self, path: &str) -> bool {
        match self.resolved(path) {
            Ok(found) => {
                winpath::same_path(&found, &self.home)
                    || winpath::is_relative_to(&found, &self.home)
            }
            Err(_) => false,
        }
    }

    /// `ensure()`: the two owned directories and their markers. A `mkdir` that fails raises its OSError there and then
    /// (`logs/` is not made after a `config` that could not be), as the reference's does.
    pub fn ensure(&self) -> Result<(), EnsureError> {
        for directory in [&self.state_dir, &self.logs_dir] {
            let exists = Path::new(directory).exists();
            if self.is_symlink(directory) || (exists && !self.confined(directory)) {
                return Err(ConfigError(
                    "Owned directory is a link/junction escaping the home; refusing".into(),
                )
                .into());
            }
            if let Err(error) = fs::create_dir_all(directory) {
                return Err(EnsureError::Os {
                    class: car_machine::pyfile::os_error_class(&error),
                    message: error.to_string(),
                });
            }
            if !self.confined(directory) {
                return Err(ConfigError(
                    "Owned directory escapes the configured home; refusing".into(),
                )
                .into());
            }
            let marker = child(directory, OWNER_MARKER);
            if !Path::new(&marker).exists() {
                // A missing marker only makes uninstall MORE conservative.
                let _ = car_machine::pyfile::write_text(&marker, OWNER_TEXT);
            }
        }
        Ok(())
    }

    /// `owns(directory)`: uninstall may only delete inside a directory carrying our provenance marker; never one
    /// that is a link or a junction.
    pub fn owns(&self, directory: &str) -> bool {
        let marker = child(directory, OWNER_MARKER);
        is_dir(directory)
            && !is_link(directory)
            && self.confined(directory)
            && is_file(&marker)
            && !is_link(&marker)
            && self.confined(&marker)
    }

    /// `claim_home()`: mark the installation root as ours. Called when the program files are put there.
    pub fn claim_home(&self) -> bool {
        if self.is_symlink(&self.home) || !self.confined(&self.home) {
            return false;
        }
        if fs::create_dir_all(&self.home).is_err() {
            return false;
        }
        let marker = child(&self.home, OWNER_MARKER);
        Path::new(&marker).exists() || car_machine::pyfile::write_text(&marker, OWNER_TEXT).is_ok()
    }

    /// `owns_home()`: whether this installation root is one we created: its marker, `config/`'s marker, or a
    /// `runtime.json` that names this very home.
    pub fn owns_home(&self) -> bool {
        if self.is_symlink(&self.home) || !is_dir(&self.home) || !self.confined(&self.home) {
            return false;
        }
        if self.owns(&self.home) || self.owns(&self.state_dir) {
            return true;
        }
        let record = child(&self.home, "runtime.json");
        if !is_file(&record) || self.is_symlink(&record) || !self.confined(&record) {
            return false;
        }
        let Ok(raw) = car_machine::pyfile::read(&record) else {
            return false;
        };
        let Ok(text) = String::from_utf8(raw) else {
            return false;
        };
        // json.loads, which takes NaN, Infinity, a lone surrogate escape and deep nesting (review 4, S1); a file nested
        // past its depth raises RecursionError out of the reference's owns_home, and is no record here (AUDIT).
        let Ok(Value::Object(document)) = loads(&text.replace("\r\n", "\n")) else {
            return false;
        };
        let Some(Value::Str(declared)) = document.get("home") else {
            return false;
        };
        let Some(declared) = declared.as_str().filter(|each| !each.is_empty()) else {
            return false;
        };
        let env = |_: &str| -> Option<String> { None };
        match winpath::expanduser(declared, &env) {
            Ok(expanded) => self
                .resolved(&expanded)
                .is_ok_and(|found| winpath::same_path(&found, &self.home)),
            Err(_) => false,
        }
    }

    /// `owned_state_files()`: owned files that uninstall may remove.
    pub fn owned_state_files(&self) -> Vec<String> {
        if !self.owns(&self.state_dir) {
            return Vec::new();
        }
        let names = [
            "state.sqlite",
            "state.sqlite-journal",
            "state.sqlite-wal",
            "state.sqlite-shm",
            "settings.json",
            "compatibility.json",
            "compat-cache.json",
            "failure-seen.json",
            "status.json",
            "power-action.json",
            "split-chains.json",
            "once-words.json",
            "edition-left.txt",
            "codex-layout.json",
            "selfcheck.json",
        ];
        let mut files: Vec<String> = names
            .iter()
            .map(|name| child(&self.state_dir, name))
            .collect();
        let listing = entries(&self.state_dir).unwrap_or_default();
        for (prefix, suffix) in [
            ("settings.", ".tmp"),
            ("compatibility.", ".tmp"),
            ("compat-cache.", ".tmp"),
            ("failure-seen.", ".tmp"),
            ("status.", ".tmp"),
            ("power-action.", ".tmp"),
            ("split-chains.", ".tmp"),
            ("once-words.", ".tmp"),
            ("edition-left.", ".tmp"),
            ("codex-layout.", ".tmp"),
            ("selfcheck.", ".tmp"),
            ("settings.unreadable-", ".json"),
        ] {
            let matching = listing
                .iter()
                .filter(|path| {
                    globbed(&base_name(path), prefix, suffix)
                        && !is_link(path)
                        && self.confined(path)
                })
                .cloned()
                .collect();
            files.extend(sorted(matching));
        }
        files.extend(self.owned_advanced_files());
        files.push(child(&self.state_dir, OWNER_MARKER));
        files
    }

    /// `owned_advanced_files()`: what a purge takes from `advanced_dir`: every file directly in it, its marker last,
    /// and only while that marker is there.
    pub fn owned_advanced_files(&self) -> Vec<String> {
        let directory = &self.advanced_dir;
        if is_link(directory) || !self.owns(directory) {
            return Vec::new();
        }
        let Ok(listing) = entries(directory) else {
            return Vec::new();
        };
        let mut found: Vec<String> = sorted(listing)
            .into_iter()
            .filter(|path| {
                base_name(path) != OWNER_MARKER
                    && is_file(path)
                    && !is_link(path)
                    && self.confined(path)
            })
            .collect();
        found.push(child(directory, OWNER_MARKER));
        found
    }

    /// `owned_account_files()`: what a purge takes from `accounts_dir`: every file in it and in the folders below it, its
    /// marker last, and only while that marker is there. Nothing that is a link or resolves outside the home.
    pub fn owned_account_files(&self) -> Vec<String> {
        let directory = &self.accounts_dir;
        if is_link(directory) || !self.owns(directory) {
            return Vec::new();
        }
        let mut found = Vec::new();
        self.walk(directory, directory, 0, &mut found);
        found.push(child(directory, OWNER_MARKER));
        found
    }

    fn walk(&self, root: &str, folder: &str, depth: usize, found: &mut Vec<String>) {
        let Ok(listing) = entries(folder) else {
            return;
        };
        for path in sorted(listing) {
            if is_link(&path)
                || !self.confined(&path)
                || (base_name(&path) == OWNER_MARKER && winpath::same_path(folder, root))
            {
                continue;
            }
            if is_dir(&path) && depth < 8 {
                self.walk(root, &path, depth + 1, found);
            } else if is_file(&path) {
                found.push(path);
            }
        }
    }

    /// `owned_account_dirs()`: the folders a purge empties under `accounts_dir`, deepest first and that folder last. The
    /// order among folders of one depth is the Python's set order, which is not defined; here it is sorted.
    pub fn owned_account_dirs(&self) -> Vec<String> {
        let files = self.owned_account_files();
        if files.is_empty() {
            return Vec::new();
        }
        let parents: BTreeSet<String> = files
            .iter()
            .map(|file| winpath::split(file).0)
            .map(|parent| winpath::path_str(&parent))
            .collect();
        let mut folders: Vec<String> = parents.into_iter().collect();
        folders.sort_by_key(|folder| std::cmp::Reverse(winpath::parse(folder).2.len() + 2));
        let mut kept: Vec<String> = folders
            .into_iter()
            .filter(|folder| !winpath::same_path(folder, &self.accounts_dir))
            .collect();
        kept.push(self.accounts_dir.clone());
        kept
    }

    /// `owned_log_files()`: the log files and their rotations, the logs folder's marker last.
    pub fn owned_log_files(&self) -> Vec<String> {
        if !self.owns(&self.logs_dir) {
            return Vec::new();
        }
        let mut found = Vec::new();
        let listing = entries(&self.logs_dir).unwrap_or_default();
        for path in sorted(listing) {
            if log_name(&base_name(&path)) && !is_link(&path) && self.confined(&path) {
                found.push(path);
            }
        }
        found.push(child(&self.logs_dir, OWNER_MARKER));
        found
    }
}

/// `(auto-resume|errors)\.log(\.\d+)?` fullmatched, `\d` being any script's decimal digit.
fn log_name(name: &str) -> bool {
    for stem in ["auto-resume.log", "errors.log"] {
        if let Some(rest) = name.strip_prefix(stem) {
            if rest.is_empty() {
                return true;
            }
            if let Some(digits) = rest.strip_prefix('.') {
                return !digits.is_empty() && digits.chars().all(car_machine::pytext::is_digit);
            }
        }
    }
    false
}

/// `installed_home()`: the runtime home of an installed copy: the directory above `app/`, or none for a checkout.
pub fn installed_home(project_root: &str) -> Option<String> {
    let (head, name) = winpath::split(project_root);
    (name == "app").then(|| winpath::path_str(&head))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(name: &str) -> Option<String> {
        (name == "USERPROFILE").then(|| "C:\\Users\\ExampleUser".to_owned())
    }

    /// A probe that says nothing is a symbolic link; the real one is car-platform's.
    #[derive(Debug)]
    struct NoLinks;

    impl Links for NoLinks {
        fn is_symlink(&self, _path: &Path) -> bool {
            false
        }
    }

    #[test]
    fn names_are_the_pythons() {
        let scratch = std::env::temp_dir().join("car-config-paths-test");
        let _ = std::fs::create_dir_all(&scratch);
        let os = Os::here(false, Arc::new(NoLinks));
        let paths = Paths::new(scratch.to_str(), "C:\\root", &env, os).unwrap();
        assert!(paths.settings_file.ends_with("config\\settings.json"));
        assert!(paths.log_file.ends_with("logs\\auto-resume.log"));
        assert!(paths.entry_script.ends_with("root\\src\\auto_resume.py"));
        assert_eq!(installed_home("C:\\x\\app").as_deref(), Some("C:\\x"));
        assert_eq!(installed_home("C:\\x\\y"), None);
        assert!(
            log_name("auto-resume.log.3")
                && log_name("errors.log")
                && !log_name("errors.log.")
                && !log_name("x.log")
        );
        let _ = std::fs::remove_dir_all(&scratch);
    }
}
