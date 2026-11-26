//! `config.py`, the rest of it: the installation root and the product version, Codex's home, and the one official
//! `codex.exe` the product drives.
//!
//! No network, no auth files, no Codex writes. `discover_codex_exe` is handed what only the platform knows how to
//! ask: whether a build passes the engine checks (`compatible`), and which images the ChatGPT app runs (`running`).

use std::collections::BTreeSet;
use std::fs;
use std::path::Path;
use std::sync::{Mutex, OnceLock, PoisonError};

use car_machine::compat::loads;
use car_machine::json::Value;

use crate::paths::{ConfigError, ENV_CODEX_EXE, Os};
use crate::winpath::{self, Env};

/// The plugin manifest, relative to the installation it describes: the one place the product version is written.
pub const PLUGIN_MANIFEST: &str = ".codex-plugin\\plugin.json";
/// How many directories, starting with this module's own, are looked at for the manifest.
pub const ROOT_SEARCH_LEVELS: usize = 5;

/// `module.parents`: the file's folders, nearest first, as pathlib lists them.
fn parents(module: &str) -> Vec<String> {
    let (drive, root, tail) = winpath::parse(module);
    let anchor = format!("{drive}{root}");
    let mut found = Vec::new();
    for keep in (0..tail.len().max(1)).rev() {
        if tail.is_empty() {
            break;
        }
        let rest = tail[..keep].join("\\");
        found.push(if anchor.is_empty() && rest.is_empty() {
            ".".to_owned()
        } else {
            format!("{anchor}{rest}")
        });
    }
    found
}

/// `_project_root(module, levels, package)`: the installation root: the nearest directory above `module` that holds
/// the plugin manifest and whose `src/<package>/` holds `module`; with none, `module.parents[2]`. `Err` is the
/// IndexError of a path too shallow to have one.
pub fn project_root(module: &str, levels: usize, package: &str) -> Result<String, &'static str> {
    let above = parents(module);
    for candidate in above.iter().take(levels) {
        let holder = winpath::join(&winpath::join(candidate, "src"), package);
        let manifest = winpath::join(candidate, PLUGIN_MANIFEST);
        if above.iter().any(|each| winpath::same_path(each, &holder))
            && Path::new(&manifest).is_file()
        {
            return Ok(candidate.clone());
        }
    }
    above.get(2).cloned().ok_or("IndexError")
}

/// `read_version(manifest)`: the version a plugin manifest declares, or the one sentence that says why it cannot be read.
pub fn read_version(manifest: &str) -> Result<String, ConfigError> {
    let raw = match car_machine::pyfile::read(manifest) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err(ConfigError("the plugin manifest is missing".into()));
        }
        Err(_) => return Err(ConfigError("the plugin manifest could not be read".into())),
    };
    let body = raw.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(&raw);
    let Ok(text) = std::str::from_utf8(body) else {
        return Err(ConfigError("the plugin manifest could not be read".into()));
    };
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    let document =
        loads(&text).map_err(|_| ConfigError("the plugin manifest is not JSON".into()))?;
    let Value::Object(map) = document else {
        return Err(ConfigError(
            "the plugin manifest is not a JSON object".into(),
        ));
    };
    match map.get("version") {
        Some(Value::Str(declared)) => {
            let shown = String::from_utf8_lossy(declared.as_bytes()).into_owned();
            if car_machine::pytext::strip(&shown).is_empty() {
                Err(ConfigError(
                    "the plugin manifest has no version string".into(),
                ))
            } else {
                Ok(shown)
            }
        }
        _ => Err(ConfigError(
            "the plugin manifest has no version string".into(),
        )),
    }
}

fn reported() -> &'static Mutex<BTreeSet<String>> {
    static REPORTED: OnceLock<Mutex<BTreeSet<String>>> = OnceLock::new();
    REPORTED.get_or_init(|| Mutex::new(BTreeSet::new()))
}

/// Forget which sentences `version` has told (the Python's `_reported.clear()`), for tests and the harness.
pub fn reset_warnings() {
    reported()
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .clear();
}

/// `version()`: the product version, read from the manifest at the installation root. `unknown` in two cases: no
/// manifest (said quietly) or one that cannot be read as one, which is told once per process through `warn` before
/// the answer.
pub fn version(project_root: &str, warn: &mut dyn FnMut(&str)) -> String {
    let manifest = winpath::join(project_root, PLUGIN_MANIFEST);
    if !Path::new(&manifest).exists() {
        return "unknown".into();
    }
    match read_version(&manifest) {
        Ok(found) => found,
        Err(refused) => {
            if reported()
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .insert(refused.0.clone())
            {
                warn(&format!(
                    "{refused}; the product version is shown as unknown"
                ));
            }
            "unknown".into()
        }
    }
}

/// `codex_home()`: `CODEX_HOME`, else `<profile>\.codex`, resolved. `Err` is the Python's exception's name.
pub fn codex_home(env: Env, os: &Os) -> Result<String, &'static str> {
    let resolve = |text: &str| {
        os.resolve(text)
            .map(|found| winpath::path_str(&found))
            .map_err(|_| "OSError")
    };
    if let Some(value) = env("CODEX_HOME").filter(|each| !each.is_empty()) {
        return resolve(&winpath::expanduser(&value, env)?);
    }
    let profile = match env("USERPROFILE").filter(|each| !each.is_empty()) {
        Some(found) => found,
        None => winpath::expanduser("~", env)?,
    };
    resolve(&winpath::join(&profile, ".codex"))
}

/// `codex_bin_dir()`: `%LOCALAPPDATA%\OpenAI\Codex\bin`.
pub fn codex_bin_dir(env: Env) -> Result<String, ConfigError> {
    let Some(local) = env("LOCALAPPDATA").filter(|each| !each.is_empty()) else {
        return Err(ConfigError(
            "LOCALAPPDATA is not set; cannot locate the official Codex binary".into(),
        ));
    };
    Ok(winpath::path_str(&winpath::join(
        &winpath::join(&winpath::join(&local, "OpenAI"), "Codex"),
        "bin",
    )))
}

/// `candidate_codex_exes()`: every `<bin>\<hex build>\codex.exe` that is a file and not a link, resolved.
pub fn candidate_codex_exes(env: Env, os: &Os) -> Result<Vec<String>, ConfigError> {
    let bin = codex_bin_dir(env)?;
    if !Path::new(&bin).is_dir() {
        return Ok(Vec::new());
    }
    let mut children: Vec<String> = match fs::read_dir(&bin) {
        Ok(listing) => listing
            .filter_map(Result::ok)
            .map(|each| each.file_name().to_string_lossy().into_owned())
            .collect(),
        Err(_) => Vec::new(),
    };
    children.sort_by_key(|name| name.to_lowercase());
    let mut found = Vec::new();
    for name in children {
        let child = winpath::path_str(&winpath::join(&bin, &name));
        let hex = !name.is_empty()
            && name
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
        if Path::new(&child).is_dir() && !os.links.is_symlink(Path::new(&child)) && hex {
            let exe = winpath::path_str(&winpath::join(&child, "codex.exe"));
            if Path::new(&exe).is_file()
                && !os.links.is_symlink(Path::new(&exe))
                && let Ok(real) = os.resolve(&exe)
            {
                let real = winpath::path_str(&real);
                // The real-engine guard: this PC's own build is not found where the guard is on.
                if !crate::paths::engine_refused(os, &exe)
                    && !crate::paths::engine_refused(os, &real)
                {
                    found.push(real);
                }
            }
        }
    }
    Ok(found)
}

/// What `os.path.normcase` makes of a path on Windows.
fn normcase(path: &str) -> String {
    path.replace('/', "\\").to_lowercase()
}

/// Whether a build passes the engine checks: `Ok`, or the text of the refusal (`str(exception)`).
pub type Compatible<'a> = &'a dyn Fn(&str) -> Result<(), String>;
/// The image paths the ChatGPT app runs as its engine, or none where the question failed.
pub type Running<'a> = &'a dyn Fn() -> Option<Vec<String>>;

fn code_shaped(reason: &str) -> bool {
    (1..=48).contains(&reason.chars().count())
        && reason.chars().all(|c| c.is_ascii_lowercase() || c == '_')
}

/// `_passing(candidates, compatible)`: the candidates that pass, and the reason codes of those that do not.
fn passing(candidates: &[String], compatible: Compatible) -> (Vec<String>, BTreeSet<String>) {
    let (mut usable, mut failed) = (Vec::new(), BTreeSet::new());
    for candidate in candidates {
        match compatible(candidate) {
            Ok(()) => usable.push(candidate.clone()),
            Err(reason) => {
                failed.insert(if code_shaped(&reason) {
                    reason
                } else {
                    "check_failed".to_owned()
                });
            }
        }
    }
    (usable, failed)
}

/// `_served(usable, running)`: of the builds in `usable`, the one the ChatGPT app main runs, when that is exactly one.
fn served(usable: &[String], running: Option<Running>) -> Option<String> {
    let running = running?;
    let live: BTreeSet<String> = running()?
        .iter()
        .map(|path| normcase(&winpath::path_str(path)))
        .collect();
    let chosen: Vec<&String> = usable
        .iter()
        .filter(|path| live.contains(&normcase(path)))
        .collect();
    (chosen.len() == 1).then(|| chosen[0].clone())
}

/// Why discovery gave no build: the product's own refusal, or the check of a named path, whose exception the caller
/// of the Python receives as it was raised.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DiscoverError {
    Config(ConfigError),
    /// `compatible(path)` of a path that was named raised: its own text.
    Check(String),
}

impl From<ConfigError> for DiscoverError {
    fn from(error: ConfigError) -> DiscoverError {
        DiscoverError::Config(error)
    }
}

/// `discover_codex_exe(explicit, compatible, running, ask_app, ask_app_if_none)`: exactly one official codex.exe that
/// passes `compatible`; ambiguity fails closed. A path that is named (the argument or the environment) is never
/// second-guessed. Where several pass and `running` is given, the one the app runs is driven, if exactly one is.
pub fn discover_codex_exe(
    explicit: Option<&str>,
    compatible: Compatible,
    running: Option<Running>,
    ask_app: bool,
    ask_app_if_none: bool,
    env: Env,
    os: &Os,
) -> Result<String, DiscoverError> {
    let chosen = explicit
        .filter(|each| !each.is_empty())
        .map(str::to_owned)
        .or_else(|| env(ENV_CODEX_EXE).filter(|each| !each.is_empty()));
    if let Some(chosen) = chosen {
        let expanded = winpath::expanduser(&chosen, env).map_err(|why| ConfigError(why.into()))?;
        let path = os
            .resolve(&expanded)
            .map(|found| winpath::path_str(&found))
            .map_err(|code| ConfigError(format!("OSError {code}")))?;
        // The real-engine guard: a named build that is this PC's own is as if it were not there.
        if !Path::new(&path).is_file()
            || crate::paths::engine_refused(os, &expanded)
            || crate::paths::engine_refused(os, &path)
        {
            return Err(ConfigError("Configured codex.exe does not exist".into()).into());
        }
        compatible(&path).map_err(DiscoverError::Check)?;
        return Ok(path);
    }
    let mut candidates = candidate_codex_exes(env, os)?;
    let (mut usable, mut failed) = passing(&candidates, compatible);
    let mut seen: Option<Vec<String>> = None;
    if let Some(ask) = running
        && (ask_app || (ask_app_if_none && usable.is_empty()))
    {
        // `[str(path) for path in running()]`: the paths as pathlib writes them.
        let listed: Vec<String> = ask()
            .unwrap_or_default()
            .iter()
            .map(|path| winpath::path_str(path))
            // The real-engine guard: what the app runs on this PC is not listed where the guard is on.
            .filter(|path| !crate::paths::engine_refused(os, path))
            .collect();
        let known: BTreeSet<String> = candidates.iter().map(|path| normcase(path)).collect();
        let extra: Vec<String> = listed
            .iter()
            .filter(|path| !known.contains(&normcase(path)))
            .cloned()
            .collect();
        let (more, why) = passing(&extra, compatible);
        candidates.extend(extra);
        usable.extend(more);
        failed.extend(why);
        seen = Some(listed);
    }
    if candidates.is_empty() {
        return Err(ConfigError(
            "No official Codex desktop engine found under %LOCALAPPDATA%\\OpenAI\\Codex\\bin, and the ChatGPT app runs none signed by OpenAI"
                .into(),
        )
        .into());
    }
    if usable.len() > 1 {
        let once = || seen.clone();
        let answer: Option<Running> = if seen.is_some() { Some(&once) } else { running };
        if let Some(found) = served(&usable, answer) {
            return Ok(found);
        }
        return Err(ConfigError(format!(
            "{} official codex.exe builds pass the engine checks, so which one to drive is ambiguous; pass --codex-exe explicitly",
            usable.len()
        ))
        .into());
    }
    if usable.is_empty() {
        let reasons: Vec<String> = failed.into_iter().collect();
        return Err(ConfigError(format!(
            "No official codex.exe passed the engine checks ({}); the official location or OpenAI's signature, `codex --version` and `codex queue` offering --thread and --message are required",
            reasons.join(", ")
        ))
        .into());
    }
    Ok(usable.remove(0))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_parent_chain() {
        assert_eq!(parents("C:\\a\\b\\c.py"), ["C:\\a\\b", "C:\\a", "C:\\"]);
        assert_eq!(parents("a\\b\\c.py"), ["a\\b", "a", "."]);
        assert_eq!(
            project_root("C:\\x\\src\\pkg\\config.py", 5, "pkg"),
            Ok("C:\\x".to_owned())
        );
        assert_eq!(project_root("C:\\c.py", 5, "pkg"), Err("IndexError"));
    }
}
