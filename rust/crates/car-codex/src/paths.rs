//! `codex/paths.py`: where Codex keeps its files, and which of them this product may open.
//!
//! `KINDS` is the whole list: three databases, and for each the columns that must be there. Anything outside a real
//! path under the Codex home is refused before it is opened.

use std::path::Path;

use car_config::winpath;
use car_machine::pytext::decimal_value;
use car_policy::settings::os::Os;

use crate::errors::{Error, Result};

/// One of `DB_KINDS`: the file name `<prefix><generation>.sqlite`, and the tables with the columns each must have.
pub struct Kind {
    pub name: &'static str,
    pub prefix: &'static str,
    pub suffix: &'static str,
    pub tables: &'static [(&'static str, &'static [&'static str])],
}

/// Codex names its databases with a schema generation suffix (state_5, queue_1, ...). An app update can bump that
/// number, so the file is discovered by pattern and then validated by the columns this tool actually reads. Extra
/// columns are fine (Codex adds them over time); a MISSING required column means the schema moved and we refuse.
pub const DB_KINDS: [Kind; 3] = [
    Kind {
        name: "state",
        prefix: "state_",
        suffix: ".sqlite",
        tables: &[(
            "threads",
            &[
                "id",
                "rollout_path",
                "source",
                "thread_source",
                "archived",
                "history_mode",
            ],
        )],
    },
    Kind {
        name: "history",
        prefix: "thread_history_",
        suffix: ".sqlite",
        tables: &[
            (
                "thread_turns",
                &[
                    "thread_id",
                    "turn_id",
                    "status",
                    "error_json",
                    "started_at",
                    "completed_at",
                    "rollout_ordinal",
                    "rollout_end_byte_offset",
                    "first_user_item_id",
                ],
            ),
            (
                "thread_items",
                &["thread_id", "turn_id", "item_id", "item_type", "item_json"],
            ),
        ],
    },
    Kind {
        name: "queue",
        prefix: "queue_",
        suffix: ".sqlite",
        tables: &[("queued_items", &["id", "thread_id", "payload_json"])],
    },
];

/// `DB_KINDS[kind]`.
pub fn kind(name: &str) -> Option<&'static Kind> {
    DB_KINDS.iter().find(|each| each.name == name)
}

/// The value of the digits of a generation, as the decimal text `int()` reads them to, leading zeros gone (a number
/// of any length, compared as text).
pub fn generation(name: &str, found: &Kind) -> Option<String> {
    let digits = name
        .strip_prefix(found.prefix)?
        .strip_suffix(found.suffix)?;
    if digits.is_empty() {
        return None;
    }
    let mut value = String::new();
    for each in digits.chars() {
        // `\d` is any decimal digit of any script, and `int()` reads them all.
        value.push(char::from_digit(decimal_value(each)?, 10)?);
    }
    let trimmed = value.trim_start_matches('0');
    Some(if trimmed.is_empty() { "0" } else { trimmed }.to_owned())
}

/// Whether the generation `a` is greater than `b` (both as decimal text without leading zeros).
fn greater(a: &str, b: &str) -> bool {
    (a.len(), a) > (b.len(), b)
}

/// `Path(home) / name`, as the text pathlib gives.
pub fn child(parent: &str, name: &str) -> String {
    winpath::path_str(&winpath::join(parent, name))
}

/// `_safe_path(path)`: SQLite stores Windows extended paths; normalize before confinement checks. The text of
/// `Path(raw).resolve()`; a path that cannot be resolved is an OSError.
pub fn safe_path(os: &dyn Os, path: &str) -> Result<String> {
    let raw = winpath::path_str(path);
    let raw = raw.strip_prefix("\\\\?\\").unwrap_or(&raw).to_owned();
    if raw.contains('\0') {
        // gh-106242: a path Windows cannot be asked about is not resolved, only made absolute (3.13.15 `realpath`).
        let normal = winpath::normpath(&raw);
        let absolute = if winpath::isabs(&normal) {
            normal
        } else {
            let cwd = std::env::current_dir()
                .map(|found| found.to_string_lossy().into_owned())
                .unwrap_or_default();
            winpath::join(&cwd, &normal)
        };
        return Ok(winpath::path_str(&absolute));
    }
    let units: Vec<u16> = winpath::path_str(&raw).encode_utf16().collect();
    match os.resolve(&units) {
        Ok(resolved) => Ok(winpath::path_str(&String::from_utf16_lossy(&resolved))),
        Err("OSError") => Err(Error::Os),
        Err(class) => Err(Error::Python(class)),
    }
}

/// `newest_generation(home, kind)`: the newest generation of one of `DB_KINDS` in the Codex home, or None: a regular
/// file, never a link. This only finds it; it is not opened here. `resolve` reads this one file or none - an older
/// generation is never a fallback - and the desktop pairing asks who holds this same file open. An OSError where the
/// home cannot be listed.
pub fn newest_generation(os: &dyn Os, home: &str, name: &str) -> Result<Option<String>> {
    let found = kind(name).ok_or(Error::Python("KeyError"))?;
    let mut newest: Option<(String, String)> = None;
    for entry in std::fs::read_dir(home)? {
        let entry = entry?;
        let file_name = entry.file_name().to_string_lossy().into_owned();
        let Some(number) = generation(&file_name, found) else {
            continue;
        };
        let full = child(home, &file_name);
        if Path::new(&full).is_file() && !os.is_symlink(Path::new(&full)) {
            let better = match &newest {
                None => true,
                Some((best, _)) => greater(&number, best),
            };
            if better {
                newest = Some((number, full));
            }
        }
    }
    Ok(newest.map(|(_, path)| path))
}

/// The last component of a path text (`Path(text).name`).
pub fn name_of(path: &str) -> String {
    winpath::parse(path).2.last().cloned().unwrap_or_default()
}

/// `Path(text).parent` of a path with a parent, as text; the path itself where it has none.
pub fn parent_of(path: &str) -> String {
    let (drive, root, mut tail) = winpath::parse(path);
    if tail.is_empty() {
        return winpath::path_str(path);
    }
    tail.pop();
    winpath::path_str(&format!("{drive}{root}{}", tail.join("\\")))
}
