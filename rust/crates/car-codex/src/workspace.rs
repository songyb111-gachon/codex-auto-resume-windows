//! `codex/workspace.py`: the one file of a conversation's folder that is ever read: its git HEAD, as a digest
//! (v0.6.11).
//!
//! Read only for the task-changed guard (`guards`), which is off by default, and only as a file - git is never
//! started (standard F6), and nothing is written. `.git/HEAD` names the branch a folder is on, or the commit it has
//! checked out; a worktree's `.git` is a file naming the folder that holds its HEAD, which is followed once. At most
//! a few kilobytes are read, a link is never followed, and a folder named by a share path (`\\server\share`) is not
//! read at all. A folder on a drive letter is read as Codex itself reads it; this module opens no connection of its
//! own (standard C1).
//!
//! The answer is a word or a digest: "none" for a folder that is no git checkout, "unreadable" for one that cannot
//! be read, or the SHA-256 of the HEAD file's bytes. The bytes themselves - a branch name - never leave this module.

use std::io::Read;
use std::os::windows::fs::MetadataExt;
use std::path::Path;

use car_config::winpath;
use car_machine::hash;
use car_machine::pytext;

pub const MAX_HEAD_BYTES: usize = 4096;
pub const NONE: &str = "none";
pub const UNREADABLE: &str = "unreadable";

const FILE_ATTRIBUTE_DIRECTORY: u32 = 0x10;
const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
const NAME_SURROGATE: u32 = 0x2000_0000;

/// What `os.lstat` of a path says it is, as `stat.S_ISREG` and `stat.S_ISDIR` read the mode on Windows (3.13): a
/// symbolic link is neither; a junction is a folder; a reparse point of another kind is followed to what it names.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Kind {
    File,
    Folder,
    Other,
}

struct Stat {
    kind: Kind,
    size: u64,
}

fn lstat(path: &Path) -> std::io::Result<Stat> {
    let found = std::fs::symlink_metadata(path)?;
    let attributes = found.file_attributes();
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        match car_platform::links::reparse_tag(path) {
            Some(car_platform::links::SYMLINK_TAG) => {
                return Ok(Stat {
                    kind: Kind::Other,
                    size: found.len(),
                });
            }
            Some(tag) if tag & NAME_SURROGATE != 0 => {}
            // A reparse point that is no name surrogate (a cloud placeholder, an app link) is opened by what it names.
            _ => {
                let followed = std::fs::metadata(path)?;
                return Ok(stat_of(&followed));
            }
        }
    }
    Ok(stat_of(&found))
}

fn stat_of(found: &std::fs::Metadata) -> Stat {
    let attributes = found.file_attributes();
    Stat {
        kind: if attributes & FILE_ATTRIBUTE_DIRECTORY != 0 {
            Kind::Folder
        } else {
            Kind::File
        },
        size: found.len(),
    }
}

/// `_local_folder(text)`: a local, absolute folder, or None: no extended-path prefix, no share, nothing that is not
/// a path.
fn local_folder(text: &str) -> Option<String> {
    if text.trim_matches(pytext::is_space).is_empty() || text.contains(['\r', '\n', '\0']) {
        return None;
    }
    let mut plain = pytext::strip(text).to_owned();
    if let Some(rest) = plain.strip_prefix("\\\\?\\") {
        plain = rest.to_owned();
        let head: String = plain.chars().take(4).collect();
        if head.eq_ignore_ascii_case("UNC\\") {
            return None;
        }
    }
    let plain = plain.replace('/', "\\");
    if plain.starts_with("\\\\") || !winpath::isabs(&plain) {
        return None;
    }
    Some(winpath::path_str(&plain))
}

/// `_small_file(path)`: the bytes of a regular file of at most MAX_HEAD_BYTES that is not a link, or None.
fn small_file(path: &str) -> Option<Vec<u8>> {
    let found = lstat(Path::new(path)).ok()?;
    if found.kind != Kind::File || found.size > MAX_HEAD_BYTES as u64 {
        return None;
    }
    let mut data = Vec::new();
    std::fs::File::open(path)
        .ok()?
        .take(MAX_HEAD_BYTES as u64 + 1)
        .read_to_end(&mut data)
        .ok()?;
    (data.len() <= MAX_HEAD_BYTES).then_some(data)
}

/// Python's `str.splitlines()[0]` of a text that has something in it: up to the first line boundary
/// (`\n`, `\r`, `\v`, `\f`, `\x1c`-`\x1e`, `\x85`, ` `, ` `).
fn first_line(text: &str) -> &str {
    let end = text
        .find(|each: char| {
            matches!(
                each,
                '\n' | '\r'
                    | '\u{0B}'
                    | '\u{0C}'
                    | '\u{1C}'
                    | '\u{1D}'
                    | '\u{1E}'
                    | '\u{85}'
                    | '\u{2028}'
                    | '\u{2029}'
            )
        })
        .unwrap_or(text.len());
    &text[..end]
}

/// What `_git_folder` found.
enum Holder {
    NoGit,
    Unreadable,
    Folder(String),
}

/// `_git_folder(folder)`: the folder that holds this checkout's HEAD: `.git` itself, or the one a worktree's `.git`
/// file names. NONE for a folder with no `.git`, None for one that cannot be read.
fn git_folder(folder: &str) -> Holder {
    let marker = winpath::path_str(&winpath::join(folder, ".git"));
    let found = match lstat(Path::new(&marker)) {
        Ok(found) => found,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Holder::NoGit,
        Err(_) => return Holder::Unreadable,
    };
    match found.kind {
        Kind::Folder => return Holder::Folder(marker),
        Kind::File => {}
        Kind::Other => return Holder::Unreadable,
    }
    let Some(data) = small_file(&marker) else {
        return Holder::Unreadable;
    };
    // `data.strip()` on bytes strips ASCII white space only.
    let blank = data
        .iter()
        .all(|byte| matches!(byte, b' ' | b'\t' | b'\n' | b'\r' | 0x0B | 0x0C));
    let Ok(text) = std::str::from_utf8(&data) else {
        return Holder::Unreadable;
    };
    let line = if blank {
        ""
    } else {
        pytext::strip(first_line(text))
    };
    let Some(target) = line.strip_prefix("gitdir:") else {
        return Holder::Unreadable;
    };
    let target = pytext::strip(target);
    if target.is_empty() || target.replace('/', "\\").starts_with("\\\\") {
        return Holder::Unreadable;
    }
    // `os.path.isabs(target)` reads the text as written; a relative one is joined to the folder first.
    let joined = if winpath::isabs(target) {
        target.to_owned()
    } else {
        winpath::path_str(&winpath::join(folder, target))
    };
    match local_folder(&joined) {
        Some(found) => Holder::Folder(found),
        None => Holder::Unreadable,
    }
}

/// `head_digest(cwd)`: NONE, UNREADABLE, or the SHA-256 of the HEAD of the checkout `cwd` is in.
pub fn head_digest(cwd: &str) -> String {
    let Some(folder) = local_folder(cwd) else {
        return UNREADABLE.to_owned();
    };
    match git_folder(&folder) {
        Holder::NoGit => NONE.to_owned(),
        Holder::Unreadable => UNREADABLE.to_owned(),
        Holder::Folder(holder) => {
            let head = winpath::path_str(&winpath::join(&holder, "HEAD"));
            match small_file(&head) {
                Some(data) => hash::hex(&hash::sha256(&data)),
                None => UNREADABLE.to_owned(),
            }
        }
    }
}
