//! `codex/pairing.py`: binding the configured Codex to exactly one Windows Store package, and the inventory it reads.
//!
//! Every rule is the reference's, over the same rows: the dicts `processes_named` lists, read as Python reads a dict
//! (a row that is no dict, a path that is no text, a time that is no int each answer as the reference answers them,
//! the exception it would raise included). The outside world - the process list, who holds a file, a process's
//! identity, a file's signer, the environment, this process's id and the clock - is asked of a [`System`].

use std::cmp::Ordering;
use std::os::windows::fs::MetadataExt;
use std::sync::Mutex;

use car_config::winpath;
use car_machine::domain::ids::codex_app_family;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_machine::vocab_gen::domain_ids::CODEX_APP_PUBLISHER;

use crate::errors::{Error, Result};
use crate::refold::{self, points};
use crate::system::{PolicyOs, System, object};

/// The two program files the inventory lists: the Codex app's (ChatGPT.exe) and every Codex engine's (codex.exe).
pub const INVENTORY_NAMES: [&str; 2] = ["ChatGPT.exe", "codex.exe"];
/// How long, in seconds, one process list answers every caller in this process.
pub const INVENTORY_SECONDS: f64 = 3.0;
/// The one signer whose signature makes a codex.exe outside the official folder official.
pub const OPENAI_SIGNER: &str = "OpenAI OpCo, LLC";
/// A signature answer that can change while the file does not, kept a minute only.
pub const PASSING: [&str; 2] = ["signature_unreadable", "signature_untrusted"];
pub const PASSING_SECONDS: f64 = 60.0;

/// `INVENTORY_FAMILIES`.
pub fn inventory_families() -> Vec<String> {
    vec![codex_app_family()]
}

type Answer = (bool, String);
/// A file by its case-folded path, size and modification time.
type FileKey = (String, u64, u64);

/// The module's state: the list one read made, how often it was forgotten, the signers by file and the servers of
/// our own.
#[derive(Default)]
struct State {
    listed: Option<(f64, Vec<Value>)>,
    forgotten: u64,
    official: Vec<(FileKey, (Answer, Option<f64>))>,
    own: Vec<(Value, Value)>,
}

static STATE: Mutex<State> = Mutex::new(State {
    listed: None,
    forgotten: 0,
    official: Vec::new(),
    own: Vec::new(),
});

fn state() -> std::sync::MutexGuard<'static, State> {
    STATE
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// A fresh process's module state (for the harness and tests: `_LISTED`, `_FORGOTTEN`, `_OFFICIAL`, `_OWN`).
pub fn reset() {
    *state() = State::default();
}

// ------------------------------------------------------------------------------------------------ the inventory
/// `inventory()`: every ChatGPT.exe and codex.exe running and every process of the Codex app's package family. One
/// list serves every caller for `INVENTORY_SECONDS`; `AdapterError("process_inventory_unavailable")` where the list
/// cannot be made.
pub fn inventory(system: &dyn System) -> Result<Vec<Value>> {
    let (listed, forgotten) = {
        let held = state();
        (held.listed.clone(), held.forgotten)
    };
    if let Some((at, rows)) = listed {
        let age = system.monotonic() - at;
        if (0.0..=INVENTORY_SECONDS).contains(&age) {
            return Ok(rows);
        }
    }
    let families = inventory_families();
    let families: Vec<&str> = families.iter().map(String::as_str).collect();
    let rows = match system.processes_named(&INVENTORY_NAMES, &families) {
        Ok(rows) => rows,
        Err(Error::Adapter(_) | Error::Os | Error::Python("ValueError")) => {
            return Err(Error::Adapter("process_inventory_unavailable"));
        }
        Err(other) => return Err(other),
    };
    let mut held = state();
    if forgotten == held.forgotten {
        held.listed = Some((system.monotonic(), rows.clone()));
    }
    Ok(rows)
}

/// `forget_inventory()`: the next `inventory` reads the processes afresh.
pub fn forget_inventory() {
    let mut held = state();
    held.listed = None;
    held.forgotten += 1;
}

// ------------------------------------------------------------------------------------------------ the engine
/// `at_official_location(path)`: `%LOCALAPPDATA%\OpenAI\Codex\bin\<hex>\codex.exe`, both resolved first.
pub fn at_official_location(system: &dyn System, path: &str) -> bool {
    let Some(profile) = system.env("LOCALAPPDATA").filter(|each| !each.is_empty()) else {
        return false;
    };
    let bin = winpath::path_str(&winpath::join(&profile, "OpenAI/Codex/bin"));
    let (Some(local), Some(found)) = (system.resolve(&bin), system.resolve(path)) else {
        return false;
    };
    let text = points(&found);
    let Some(mut at) = refold::literal(&text, 0, &local) else {
        return false;
    };
    if text.get(at) != Some(&u32::from(b'\\')) {
        return false;
    }
    at += 1;
    let start = at;
    while text.get(at).is_some_and(|c| {
        char::from_u32(*c).is_some_and(|c| c.is_ascii_digit())
            || (u32::from(b'a')..=u32::from(b'f')).contains(&refold::simple_lower(*c))
    }) {
        at += 1;
    }
    at > start && refold::exactly(&text, at, "\\codex.exe")
}

/// The modification time of a file as `st_mtime_ns` keys it (its FILETIME is as good a key).
fn stat(text: &str) -> Option<(bool, u64, u64)> {
    let found = std::fs::metadata(text).ok()?;
    Some((!found.is_dir(), found.len(), found.last_write_time()))
}

/// `official_engine(path)`: whether the codex.exe at `path` is an official Codex engine, and why.
pub fn official_engine(system: &dyn System, path: &str) -> Answer {
    if at_official_location(system, path) {
        return (true, "official_location".into());
    }
    let Some((regular, size, written)) = stat(path) else {
        return (false, "engine_unreadable".into());
    };
    if !regular {
        return (false, "engine_unreadable".into());
    }
    let key = (car_platform::paths::normcase(path), size, written);
    {
        let held = state();
        if let Some((_, (answer, until))) = held.official.iter().find(|(each, _)| *each == key) {
            let fresh = match until {
                None => true,
                Some(until) => (0.0..=PASSING_SECONDS).contains(&(until - system.monotonic())),
            };
            if fresh {
                return answer.clone();
            }
        }
    }
    let answer: Answer = match system.signer(path) {
        Ok(name) if name == OPENAI_SIGNER => (true, "openai_signature".into()),
        Ok(_) => (false, "wrong_signer".into()),
        Err(Some(code)) => (false, code.into()),
        Err(None) => (false, "signature_unreadable".into()),
    };
    let until = PASSING
        .contains(&answer.1.as_str())
        .then(|| system.monotonic() + PASSING_SECONDS);
    let mut held = state();
    if held.official.len() >= 32 {
        held.official.clear();
    }
    if let Some(slot) = held.official.iter_mut().find(|(each, _)| *each == key) {
        slot.1 = (answer.clone(), until);
    } else {
        held.official.push((key, (answer.clone(), until)));
    }
    answer
}

// ------------------------------------------------------------------------------------------------ who holds what
fn field<'a>(row: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match row {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// `row[key]` of a dict: a KeyError where it is not there, a TypeError of anything else.
fn index<'a>(row: &'a Value, key: &str) -> Result<&'a Value> {
    match row {
        Value::Object(map) => map.get(key).ok_or(Error::Python("KeyError")),
        _ => Err(Error::Python("TypeError")),
    }
}

fn is_dict(value: &Value) -> bool {
    matches!(value, Value::Object(_))
}

fn path_text(row: &Value) -> Option<String> {
    match field(row, "path") {
        Value::Str(text) => Some(lossy(text)),
        _ => None,
    }
}

fn lossy(text: &Str) -> String {
    text.as_str().map_or_else(
        || String::from_utf8_lossy(text.as_bytes()).into_owned(),
        str::to_owned,
    )
}

/// `text.lower()` of a path, compared as Python compares two texts.
fn lower(text: &str) -> Vec<u32> {
    refold::lower_points(&points(text))
}

/// The newest generation of a database kind; `Err(true)` where the home is not there or is no folder
/// (FileNotFoundError, NotADirectoryError), `Err(false)` for any other OSError.
fn databases(codex_home: &str) -> std::result::Result<Vec<String>, bool> {
    if let Err(error) = std::fs::read_dir(codex_home) {
        return Err(matches!(error.raw_os_error(), Some(2 | 3 | 267)));
    }
    let os = PolicyOs;
    let mut found = Vec::new();
    for kind in ["queue", "state"] {
        match crate::paths::newest_generation(&os, codex_home, kind) {
            Ok(Some(path)) => found.push(path),
            Ok(None) => {}
            Err(_) => return Err(false),
        }
    }
    Ok(found)
}

/// `_database_holders(codex_home)`: who holds the home's newest queue or state database open, this process left out.
pub fn database_holders(system: &dyn System, codex_home: Option<&str>) -> Result<Vec<Value>> {
    let ambiguous = Error::Adapter("desktop_server_missing_or_ambiguous");
    let Some(home) = codex_home else {
        return Err(ambiguous);
    };
    let listed = match databases(home) {
        Ok(found) => found,
        Err(true) => Vec::new(),
        Err(false) => return Err(ambiguous),
    };
    let holders = if listed.is_empty() {
        Vec::new()
    } else {
        match system.resource_users(&listed) {
            Ok(found) => found,
            Err(Error::Adapter(_) | Error::Os) => return Err(ambiguous),
            Err(other) => return Err(other),
        }
    };
    let own = Value::from(system.own_pid());
    Ok(holders
        .into_iter()
        .filter(|holder| is_dict(holder) && !pyval::eq(field(holder, "pid"), &own))
        .collect())
}

/// `_held(rows, holders)`: (row, holder) for each row a holder names by pid.
fn held<'a>(rows: &[&'a Value], holders: &'a [Value]) -> Vec<(&'a Value, &'a Value)> {
    let mut found = Vec::new();
    for row in rows {
        for holder in holders {
            if pyval::eq(field(holder, "pid"), field(row, "pid")) {
                found.push((*row, holder));
            }
        }
    }
    found
}

// ------------------------------------------------------------------------------------------------ the package
/// `_windows_apps()`: the folder Store apps are installed in.
pub fn windows_apps(system: &dyn System) -> String {
    let program_files = system
        .env("ProgramW6432")
        .filter(|each| !each.is_empty())
        .or_else(|| system.env("ProgramFiles"))
        .unwrap_or_else(|| "C:\\Program Files".into());
    winpath::path_str(&winpath::join(&program_files, "WindowsApps"))
}

/// The package folder's name after `<WindowsApps>\OpenAI.Codex_`, and what follows it.
fn package_parts<'a>(system: &dyn System, text: &'a [u32]) -> Option<(&'a [u32], &'a [u32])> {
    let prefix = format!("{}\\OpenAI.Codex_", windows_apps(system));
    let at = refold::literal(text, 0, &prefix)?;
    let rest = &text[at..];
    let end = rest
        .iter()
        .position(|c| *c == u32::from(b'\\'))
        .unwrap_or(rest.len());
    Some((&rest[..end], &rest[end..]))
}

/// `[^\\]+__<publisher>`: a name that ends in the publisher, with something before it.
fn ends_with_publisher(segment: &[u32]) -> bool {
    let tail = format!("__{CODEX_APP_PUBLISHER}");
    let size = tail.chars().count();
    segment.len() > size && refold::exactly(segment, segment.len() - size, &tail)
}

/// `(\\[^\\]+)+`: the components after the package folder, each named, at least one.
fn components(rest: &[u32]) -> Option<Vec<&[u32]>> {
    let rest = rest.strip_prefix(&[u32::from(b'\\')])?;
    let parts: Vec<&[u32]> = refold::split(rest);
    parts.iter().all(|part| !part.is_empty()).then_some(parts)
}

/// `_package_app(path)`: a ChatGPT.exe of the Codex app's own Windows Store package.
pub fn package_app(system: &dyn System, path: &str) -> bool {
    let text = points(path);
    let Some((segment, rest)) = package_parts(system, &text) else {
        return false;
    };
    // `[0-9.]+_(x64|arm64)__<publisher>`
    let digits = segment
        .iter()
        .take_while(|c| **c == u32::from(b'.') || (0x30..=0x39).contains(*c))
        .count();
    if digits == 0 || segment.get(digits) != Some(&u32::from(b'_')) {
        return false;
    }
    let after = digits + 1;
    let tail = format!("__{CODEX_APP_PUBLISHER}");
    let arch = ["x64", "arm64"].iter().any(|word| {
        refold::literal(segment, after, word)
            .is_some_and(|end| refold::exactly(segment, end, &tail))
    });
    arch && refold::exactly(rest, 0, "\\app\\ChatGPT.exe")
}

/// `_package_file(path)`: a file anywhere in a folder of the Codex app's Windows Store package.
pub fn package_file(system: &dyn System, path: &str) -> bool {
    let text = points(path);
    if refold::split(&text)
        .iter()
        .any(|part| *part == points("..").as_slice())
    {
        return false;
    }
    let Some((segment, rest)) = package_parts(system, &text) else {
        return false;
    };
    ends_with_publisher(segment) && components(rest).is_some()
}

/// `_main_slot(path)`: a file directly in the package's `app` folder.
pub fn main_slot(system: &dyn System, path: &str) -> bool {
    if !package_file(system, path) {
        return false;
    }
    let text = points(path);
    let Some((segment, rest)) = package_parts(system, &text) else {
        return false;
    };
    ends_with_publisher(segment)
        && components(rest)
            .is_some_and(|parts| parts.len() == 2 && refold::exactly(parts[0], 0, "app"))
}

/// `_main_place(path)`: directly in the package's `app` folder, or directly in the package's own folder.
pub fn main_place(system: &dyn System, path: &str) -> bool {
    if main_slot(system, path) {
        return true;
    }
    let text = points(path);
    let one = package_parts(system, &text).is_some_and(|(segment, rest)| {
        ends_with_publisher(segment) && components(rest).is_some_and(|parts| parts.len() == 1)
    });
    package_file(system, path) && one
}

fn named_codex(path: &str) -> bool {
    lower(&crate::paths::name_of(path)) == points("codex.exe")
}

/// `engine_row(row)`: a process of a file called codex.exe, whatever its case, but not where the app's main is.
pub fn engine_row(system: &dyn System, row: &Value) -> bool {
    match path_text(row) {
        Some(path) if is_dict(row) => named_codex(&path) && !main_slot(system, &path),
        _ => false,
    }
}

/// `app_process(row)`: a process of the Codex app's own package - a main or a helper.
pub fn app_process(system: &dyn System, row: &Value) -> bool {
    let Some(path) = path_text(row).filter(|_| is_dict(row)) else {
        return false;
    };
    if named_codex(&path) && !main_slot(system, &path) {
        return false;
    }
    if package_app(system, &path) {
        return true;
    }
    let family = match field(row, "family") {
        Value::Str(text) => Some(lossy(text)),
        _ => None,
    };
    family.is_some_and(|family| {
        refold::casefold_points(&points(&family))
            == refold::casefold_points(&points(&codex_app_family()))
    }) && package_file(system, &path)
}

/// `_born(row)`: the creation time, `None` where it could not be read, `Untimed` where the row carries none.
enum Born<'a> {
    Untimed,
    Unread,
    At(&'a Value),
}

fn born(row: &Value) -> Born<'_> {
    let Value::Object(map) = row else {
        return Born::Untimed;
    };
    let Some(value) = map.get("created") else {
        return Born::Untimed;
    };
    match value {
        Value::Int(_) if pyval::greater(value, &Value::from(0)).unwrap_or(false) => Born::At(value),
        _ => Born::Unread,
    }
}

/// `_started(parent, child, to_main=)`: whether the process of `parent` can be the one that started `child`.
fn started(parent: &Value, child: &Value, to_main: bool) -> bool {
    match (born(parent), born(child)) {
        (Born::Untimed, _) | (_, Born::Untimed) => to_main,
        (Born::At(up), Born::At(down)) => pyval::less_or_equal(up, down).unwrap_or(false),
        _ => false,
    }
}

/// A dict keyed by Python's equality: the pids the rows list.
fn find<'a, T>(table: &'a [(Value, T)], key: &Value) -> Option<&'a T> {
    table
        .iter()
        .find(|(each, _)| pyval::eq(each, key))
        .map(|(_, item)| item)
}

/// `app_mains(rows)`: every row that may be the Windows Store app main.
pub fn app_mains<'a>(system: &dyn System, rows: &'a [Value]) -> Result<Vec<&'a Value>> {
    let apps: Vec<&Value> = rows.iter().filter(|row| app_process(system, row)).collect();
    let mut by_pid: Vec<(Value, Vec<&Value>)> = Vec::new();
    for row in &apps {
        let pid = index(row, "pid")?;
        pyval::hashable(pid).map_err(Error::Python)?;
        match by_pid.iter_mut().find(|(each, _)| pyval::eq(each, pid)) {
            Some((_, list)) => list.push(row),
            None => by_pid.push((pid.clone(), vec![row])),
        }
    }
    let mut mains = Vec::new();
    for row in apps {
        let path = path_text(row).unwrap_or_default();
        if !main_place(system, &path) {
            continue;
        }
        let parent = field(row, "parent");
        pyval::hashable(parent).map_err(Error::Python)?;
        let ups = find(&by_pid, parent).map(Vec::as_slice).unwrap_or(&[]);
        if !ups.iter().any(|up| started(up, row, true)) {
            mains.push(row);
        }
    }
    Ok(mains)
}

/// `_app_main(rows)`: the one Windows Store app main. None, or several, fails closed.
pub fn app_main<'a>(system: &dyn System, rows: &'a [Value]) -> Result<&'a Value> {
    let mains = app_mains(system, rows)?;
    if mains.len() != 1 {
        return Err(Error::Adapter("desktop_main_missing_or_ambiguous"));
    }
    Ok(mains[0])
}

/// `under_app(rows, row, main)`: whether the process `row` is one the app main whose pid is `main` runs itself.
pub fn under_app(system: &dyn System, rows: &[Value], row: &Value, main: &Value) -> Result<bool> {
    if !is_dict(row) {
        return Ok(false);
    }
    let mut listed: Vec<(Value, Option<&Value>)> = Vec::new();
    for each in rows.iter().filter(|each| is_dict(each)) {
        let pid = field(each, "pid");
        pyval::hashable(pid).map_err(Error::Python)?;
        match listed.iter_mut().find(|(key, _)| pyval::eq(key, pid)) {
            Some(slot) => slot.1 = None,
            None => listed.push((pid.clone(), Some(each))),
        }
    }
    let (mut child, mut at) = (row, field(row, "parent").clone());
    let mut seen: Vec<Value> = Vec::new();
    loop {
        pyval::hashable(&at).map_err(Error::Python)?;
        if seen.iter().any(|each| pyval::eq(each, &at)) {
            return Ok(false);
        }
        seen.push(at.clone());
        let up = find(&listed, &at).copied().flatten();
        if pyval::eq(&at, main) {
            return Ok(match up {
                None => true,
                Some(up) => started(up, child, true),
            });
        }
        let Some(up) = up else {
            return Ok(false);
        };
        if matches!(main, Value::Null) || !app_process(system, up) || !started(up, child, false) {
            return Ok(false);
        }
        child = up;
        at = field(up, "parent").clone();
    }
}

/// `server_engines(rows)`: the image path of every codex.exe the one Windows Store app main runs.
pub fn server_engines(system: &dyn System, rows: &[Value]) -> Result<Vec<String>> {
    let main = app_main(system, rows)?;
    let pid = index(main, "pid")?;
    let mut found = Vec::new();
    for row in rows {
        if engine_row(system, row) && under_app(system, rows, row, pid)? {
            found.push(path_text(row).unwrap_or_default());
        }
    }
    found.sort();
    found.dedup();
    Ok(found)
}

/// `app_engines()`: `server_engines` of the processes running now.
pub fn app_engines(system: &dyn System) -> Result<Vec<String>> {
    server_engines(system, &inventory(system)?)
}

/// How deep below a package's folder a codex.exe is looked for: `app\resources\codex.exe` is three names down (#58).
pub const PACKAGE_ENGINE_DEPTH: usize = 4;

/// `os.scandir(folder)` as `package_engines` reads it: each entry's path (the folder and the name joined as scandir
/// joins them), name, and whether it is a folder (`is_dir(follow_symlinks=False) and not is_symlink()`: a junction is
/// a folder, a symbolic link is neither) or a file (`is_file(follow_symlinks=False)`). None where the folder cannot be
/// opened (the reference's `OSError`, then `continue`).
fn listed(folder: &str) -> Option<Vec<(String, String, bool, bool)>> {
    use car_policy::settings::os::Os;
    let mut found = Vec::new();
    for entry in std::fs::read_dir(folder).ok()? {
        // An error met while listing ends the listing; what was listed before it stays (the reference appends as it
        // iterates, then `continue`s past the OSError).
        let Ok(entry) = entry else {
            break;
        };
        let name = entry.file_name().to_string_lossy().into_owned();
        // `join_path_filenameW`: a separator is added unless the folder ends in one or in a drive's colon.
        let path = if folder.is_empty() || folder.ends_with(['\\', '/', ':']) {
            format!("{folder}{name}")
        } else {
            format!("{folder}\\{name}")
        };
        let attributes = entry.metadata().map_or(0, |facts| facts.file_attributes());
        let link = PolicyOs.is_symlink(std::path::Path::new(&path));
        let directory = attributes & 0x10 != 0;
        found.push((path, name, directory && !link, !directory && !link));
    }
    Some(found)
}

/// `package_engines()` (v0.6.26 final, live acceptance R2b): every file called codex.exe in the folders of the Codex
/// app's package installed for this account (`package_roots`), up to [`PACKAGE_ENGINE_DEPTH`] names below a folder,
/// that may be an engine (`engine_row`, `_main_place`) and is a file of the package's own folder in WindowsApps, as
/// written and as resolved (`_package_file`): whether or not the app runs. Only folder names are read; nothing is
/// opened, hashed or started. Nothing where the package manager cannot answer (AdapterError, OSError); any other
/// exception of it leaves, as the reference's would.
pub fn package_engines(system: &dyn System) -> Result<Vec<String>> {
    let roots = match system.package_roots(&codex_app_family()) {
        Ok(roots) => roots,
        Err(Error::Adapter(_) | Error::Os) => return Ok(Vec::new()),
        Err(other) => return Err(other),
    };
    let mut found = Vec::new();
    for root in roots {
        let mut level = vec![root];
        for _depth in 0..PACKAGE_ENGINE_DEPTH {
            let mut below = Vec::new();
            for folder in &level {
                let Some(entries) = listed(folder) else {
                    continue;
                };
                for (path, name, directory, file) in entries {
                    if directory {
                        below.push(path);
                    } else if name.to_lowercase() == "codex.exe" && file {
                        found.push(path);
                    }
                }
            }
            level = below;
        }
    }
    let mut engines = Vec::new();
    for path in found {
        let Some(resolved) = system.resolve(&path) else {
            continue;
        };
        if [&path, &resolved].iter().all(|each| {
            package_file(system, each)
                && engine_row(system, &object(vec![("path", Value::from(each.as_str()))]))
                && !main_place(system, each)
        }) {
            engines.push(resolved);
        }
    }
    Ok(engines)
}

/// `engines_instead(rows, codex_exe)`: the codex.exe paths the app main runs where none of them is `codex_exe`.
pub fn engines_instead(
    system: &dyn System,
    rows: &[Value],
    codex_exe: &str,
) -> Result<Vec<String>> {
    let served = match server_engines(system, rows) {
        Ok(served) => served,
        Err(Error::Adapter(_) | Error::Python("KeyError" | "TypeError")) => return Ok(Vec::new()),
        Err(other) => return Err(other),
    };
    let held = lower(codex_exe);
    Ok(if served.iter().any(|path| lower(path) == held) {
        Vec::new()
    } else {
        served
    })
}

/// `_extension_engine(path)`: a codex.exe of the VS Code extension's own.
pub fn extension_engine(system: &dyn System, path: &str) -> bool {
    let Some(profile) = system.env("USERPROFILE").filter(|each| !each.is_empty()) else {
        return false;
    };
    let prefix = winpath::path_str(&winpath::join(
        &winpath::join(&profile, ".vscode"),
        "extensions",
    ));
    let text = points(path);
    let Some(at) = refold::literal(&text, 0, &format!("{prefix}\\openai.chatgpt-")) else {
        return false;
    };
    let rest = &text[at..];
    let Some(end) = rest.iter().position(|c| *c == u32::from(b'\\')) else {
        return false;
    };
    if end == 0 {
        return false;
    }
    let Some(parts) = components(&rest[end..]) else {
        return false;
    };
    parts
        .last()
        .is_some_and(|last| refold::exactly(last, 0, "codex.exe"))
}

/// `app_running(rows)`: whether any process of the Codex app's package is among the rows.
pub fn app_running(system: &dyn System, rows: &[Value]) -> Result<bool> {
    match app_main(system, rows) {
        Ok(_) => return Ok(true),
        Err(Error::Adapter("desktop_main_missing_or_ambiguous")) => {}
        Err(Error::Adapter(_)) => return Ok(true),
        Err(other) => return Err(other),
    }
    let mut root = lower(&windows_apps(system));
    root.extend(points("\\openai.codex_"));
    let names = [points("chatgpt.exe"), points("codex.exe")];
    Ok(rows.iter().any(|row| {
        let Some(path) = path_text(row).filter(|_| is_dict(row)) else {
            return false;
        };
        lower(&path).starts_with(&root)
            && (names.contains(&lower(&crate::paths::name_of(&path)))
                || (app_process(system, row) && main_place(system, &path)))
    }))
}

/// `app_running_now()`: True, False, or None where the process list could not be read.
pub fn app_running_now(system: &dyn System) -> Option<bool> {
    inventory(system)
        .and_then(|rows| app_running(system, &rows))
        .ok()
}

// ------------------------------------------------------------------------------------------------ our own servers
/// `own_server(pid)`: count a process this one has just started and holds as an app server of our own.
pub fn own_server(system: &dyn System, pid: &Value) -> Result<Option<(Value, Value)>> {
    if !pyval::is_int(pid) || !pyval::greater(pid, &Value::from(0)).unwrap_or(false) {
        return Ok(None);
    }
    let held = match system.process_identity(pid) {
        Ok(held) => held,
        Err(Error::Adapter(_) | Error::Os | Error::Python("ValueError")) => return Ok(None),
        Err(other) => return Err(other),
    };
    let mark = (
        index(&held, "pid")?.clone(),
        index(&held, "created")?.clone(),
    );
    state().own.push(mark.clone());
    forget_inventory();
    Ok(Some(mark))
}

/// `own_server_gone(mark)`.
pub fn own_server_gone(mark: &(Value, Value)) {
    state()
        .own
        .retain(|each| !(pyval::eq(&each.0, &mark.0) && pyval::eq(&each.1, &mark.1)));
    forget_inventory();
}

/// `own_holder(user)`: the same pid AND creation time as at our spawn.
pub fn own_holder(user: &Value) -> Result<bool> {
    if !is_dict(user) {
        return Ok(false);
    }
    let (pid, created) = (field(user, "pid"), field(user, "created"));
    pyval::hashable(pid).map_err(Error::Python)?;
    pyval::hashable(created).map_err(Error::Python)?;
    Ok(state()
        .own
        .iter()
        .any(|each| pyval::eq(&each.0, pid) && pyval::eq(&each.1, created)))
}

/// `session_kind(rows, user, codex_exe)`: whether the one holder `user` of a writer lock is another Codex session.
pub fn session_kind(
    system: &dyn System,
    rows: Option<&[Value]>,
    user: &Value,
    codex_exe: &str,
) -> Result<bool> {
    let Some(rows) = rows.filter(|_| is_dict(user)) else {
        return Ok(false);
    };
    let found: Vec<&Value> = rows
        .iter()
        .filter(|row| engine_row(system, row) && pyval::eq(field(row, "pid"), field(user, "pid")))
        .collect();
    if found.len() != 1 || pyval::eq(field(found[0], "parent"), &Value::from(system.own_pid())) {
        return Ok(false);
    }
    let row = found[0];
    let main = match app_main(system, rows).and_then(|main| index(main, "pid").cloned()) {
        Ok(pid) => pid,
        Err(Error::Adapter(_) | Error::Python("KeyError" | "TypeError")) => Value::Null,
        Err(other) => return Err(other),
    };
    let path = path_text(row).unwrap_or_default();
    let configured = lower(&path) == lower(codex_exe) && !under_app(system, rows, row, &main)?;
    if !(configured || extension_engine(system, &path)) {
        return Ok(false);
    }
    let held = match system.process_identity(index(row, "pid")?) {
        Ok(held) => held,
        Err(Error::Adapter(_) | Error::Os) => return Ok(false),
        Err(other) => return Err(other),
    };
    let same_path = match index(&held, "path")? {
        Value::Str(text) => text.code_points().collect::<Vec<u32>>() == lower(&path),
        _ => false,
    };
    Ok(same_path && pyval::eq(index(&held, "created")?, field(user, "created")))
}

/// `desktop_pair(rows, codex_exe, codex_home, require_holder, seen)`: bind the configured official engine to exactly
/// one Windows Store app main. `seen` is told whether the paired server was among the holders (`server_holds`).
pub fn desktop_pair(
    system: &dyn System,
    rows: &[Value],
    codex_exe: &str,
    codex_home: Option<&str>,
    require_holder: bool,
    seen: Option<&mut Map>,
) -> Result<Value> {
    let ambiguous = || Error::Adapter("desktop_server_missing_or_ambiguous");
    let main = app_main(system, rows)?;
    let main_pid = index(main, "pid")?;
    let mut engines = Vec::new();
    for row in rows {
        if engine_row(system, row) && under_app(system, rows, row, main_pid)? {
            engines.push(row);
        }
    }
    let wanted = lower(codex_exe);
    let is_ours = |row: &Value| lower(&path_text(row).unwrap_or_default()) == wanted;
    let mut servers: Vec<&Value> = engines.iter().copied().filter(|row| is_ours(row)).collect();
    let others: Vec<&Value> = engines
        .iter()
        .copied()
        .filter(|row| !is_ours(row))
        .collect();
    let holders;
    let mut holder: Option<&Value> = None;
    if servers.len() > 1 || (require_holder && !servers.is_empty()) {
        holders = database_holders(system, codex_home)?;
        let found = held(&servers, &holders);
        if found.len() != 1 || !held(&others, &holders).is_empty() {
            return Err(ambiguous());
        }
        servers = vec![found[0].0];
        holder = Some(found[0].1);
    } else if servers.len() == 1 && codex_home.is_some() {
        holders = database_holders(system, codex_home)?;
        let found = held(&servers, &holders);
        let mut codex_pids: Vec<&Value> = Vec::new();
        for row in rows.iter().filter(|row| engine_row(system, row)) {
            let pid = field(row, "pid");
            pyval::hashable(pid).map_err(Error::Python)?;
            codex_pids.push(pid);
        }
        if !held(&others, &holders).is_empty() {
            return Err(ambiguous());
        }
        if found.is_empty() {
            for each in &holders {
                let pid = field(each, "pid");
                pyval::hashable(pid).map_err(Error::Python)?;
                if codex_pids.iter().any(|known| pyval::eq(known, pid)) {
                    return Err(ambiguous());
                }
            }
        }
        holder = found.first().map(|(_, holder)| *holder);
    }
    if servers.len() != 1 {
        return Err(ambiguous());
    }
    let app = system.process_identity(main_pid)?;
    let server = system.process_identity(index(servers[0], "pid")?)?;
    let main_path = match index(main, "path")? {
        Value::Str(text) => refold::lower_points(&text.code_points().collect::<Vec<u32>>()),
        _ => return Err(Error::Python("AttributeError")),
    };
    let text_of = |value: &Value| match value {
        Value::Str(text) => Some(text.code_points().collect::<Vec<u32>>()),
        _ => None,
    };
    if text_of(index(&app, "path")?) != Some(main_path)
        || text_of(index(&server, "path")?) != Some(wanted.clone())
    {
        return Err(Error::Adapter("process_identity_changed"));
    }
    let server_created = index(&server, "created")?;
    if let Some(holder) = holder
        && !pyval::eq(field(holder, "created"), server_created)
    {
        return Err(Error::Adapter("process_identity_changed"));
    }
    if pyval::order(server_created, index(&app, "created")?).map_err(Error::Python)?
        == Some(Ordering::Less)
    {
        return Err(Error::Adapter("process_parent_identity_invalid"));
    }
    if let Some(seen) = seen {
        seen.insert(Str::from("server_holds"), Value::Bool(holder.is_some()));
    }
    let mut paired = match app {
        Value::Object(map) => map,
        _ => Map::new(),
    };
    paired.insert(Str::from("server"), server);
    Ok(Value::Object(paired))
}

/// A row as the inventory lists it (for tests and the harness).
pub fn row(pid: i64, parent: i64, path: &str, created: Option<i64>, family: Option<&str>) -> Value {
    object(vec![
        ("pid", Value::from(pid)),
        ("parent", Value::from(parent)),
        ("path", Value::from(path)),
        ("created", created.map_or(Value::Null, Value::from)),
        ("family", family.map_or(Value::Null, Value::from)),
    ])
}
