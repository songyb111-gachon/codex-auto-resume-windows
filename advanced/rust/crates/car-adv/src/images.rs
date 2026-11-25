//! The pictures of a queued prompt (`images.py`, #50 item 1): the product's own copies, kept until the message is
//! delivered, directly in the advanced state folder:
//!
//! `image-<prompt id>-<place>-<count>-<32 hex>.<ext>` (a copy of a prompt still to go) and `image-new-<32 hex>.<ext>`
//! (a save's copy before its prompt has an id). The person's own path and file name are never kept.

use std::path::{Path, PathBuf};
use std::time::SystemTime;

use car_config::paths::is_link;

use crate::state::seam::Tokens;

pub const MOST_IMAGES: usize = 10;
pub const MOST_BYTES: usize = 20 * 1024 * 1024;
pub const STAGED_FOR: f64 = 3600.0;
pub const PREFIX: &str = "image-";

/// What a picture is refused with (`ImageRefused`'s word), or the OSError a write met.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ImageError {
    Refused(&'static str),
    Os(String),
}

/// `kind(data)`: png, jpg, gif or webp by the bytes, or None.
pub fn kind(data: &[u8]) -> Option<&'static str> {
    if data.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Some("png");
    }
    if data.starts_with(b"\xff\xd8\xff") {
        return Some("jpg");
    }
    if data.starts_with(b"GIF87a") || data.starts_with(b"GIF89a") {
        return Some("gif");
    }
    if data.len() >= 12 && &data[..4] == b"RIFF" && &data[8..12] == b"WEBP" {
        return Some("webp");
    }
    None
}

/// `NAME.fullmatch(name)`: the parts of a copy's name.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Name {
    pub prompt: String,
    pub place: Option<String>,
    pub count: Option<String>,
    pub id: String,
    pub ext: String,
}

fn digits(text: &str) -> bool {
    !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit())
}

fn hex32(text: &str) -> bool {
    text.len() == 32
        && text
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// `NAME.fullmatch(name)`.
pub fn parse(name: &str) -> Option<Name> {
    let rest = name.strip_prefix(PREFIX)?;
    let (prompt, rest) = rest.split_once('-')?;
    let prompt_ok =
        prompt == "new" || (digits(prompt) && prompt.len() <= 18 && !prompt.starts_with('0'));
    if !prompt_ok {
        return None;
    }
    let (stem, ext) = rest.rsplit_once('.')?;
    if !["png", "jpg", "gif", "webp"].contains(&ext) {
        return None;
    }
    if hex32(stem) {
        return Some(Name {
            prompt: prompt.into(),
            place: None,
            count: None,
            id: stem.into(),
            ext: ext.into(),
        });
    }
    let mut parts = stem.splitn(3, '-');
    let (place, count, id) = (parts.next()?, parts.next()?, parts.next()?);
    let small = |text: &str| digits(text) && text.len() <= 2;
    if small(place) && small(count) && hex32(id) {
        return Some(Name {
            prompt: prompt.into(),
            place: Some(place.into()),
            count: Some(count.into()),
            id: id.into(),
            ext: ext.into(),
        });
    }
    None
}

/// `read(source)`: the bytes of the picture at `source` and the extension they say.
pub fn read(source: &str) -> Result<(Vec<u8>, &'static str), ImageError> {
    let refused = ImageError::Refused("image_refused");
    if source.is_empty() || source.contains('\0') || source.chars().count() > 32767 {
        return Err(refused);
    }
    let path = Path::new(source);
    if !path.is_absolute() || is_link(source) || !path.is_file() {
        return Err(refused);
    }
    let data = {
        use std::io::Read;
        let Ok(handle) = std::fs::File::open(path) else {
            return Err(refused);
        };
        let mut data = Vec::new();
        if handle
            .take(MOST_BYTES as u64 + 1)
            .read_to_end(&mut data)
            .is_err()
        {
            return Err(refused);
        }
        data
    };
    if data.len() > MOST_BYTES {
        return Err(ImageError::Refused("image_too_large"));
    }
    match kind(&data) {
        Some(ext) => Ok((data, ext)),
        None => Err(refused),
    }
}

/// `_entries(paths)`: every copy in the folder, as (path, its name's parts).
fn entries(folder: &Path) -> Vec<(PathBuf, Name)> {
    let Ok(listed) = std::fs::read_dir(folder) else {
        return Vec::new();
    };
    listed
        .filter_map(|entry| entry.ok())
        .filter_map(|entry| {
            let name = entry.file_name().to_string_lossy().into_owned();
            parse(&name).map(|parts| (folder.join(&name), parts))
        })
        .collect()
}

/// `stage(paths, data, ext)`: a picture's bytes written as a save's copy; its opaque id.
pub fn stage(
    folder: &Path,
    tokens: &dyn Tokens,
    data: &[u8],
    ext: &str,
) -> Result<String, ImageError> {
    if is_link(&folder.to_string_lossy()) || !folder.is_dir() {
        return Err(ImageError::Os(
            "the advanced state folder is not there".into(),
        ));
    }
    let image = tokens.hex(16);
    let target = folder.join(format!("{PREFIX}new-{image}.{ext}"));
    let written = (|| -> std::io::Result<()> {
        use std::io::Write;
        let mut handle = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)?;
        handle.write_all(data)
    })();
    written.map_err(|error| ImageError::Os(error.to_string()))?;
    Ok(image)
}

/// `_own(paths, prompt_id)`: (place, count, id, path) of a prompt's copies, sorted.
fn own(folder: &Path, prompt_id: &str) -> Vec<(i64, i64, String, PathBuf)> {
    let mut found: Vec<(i64, i64, String, PathBuf)> = entries(folder)
        .into_iter()
        .filter(|(_, name)| name.prompt == prompt_id && name.place.is_some())
        .map(|(path, name)| {
            let number = |text: &Option<String>| {
                text.as_deref()
                    .and_then(|text| text.parse().ok())
                    .unwrap_or(0)
            };
            (number(&name.place), number(&name.count), name.id, path)
        })
        .collect();
    found.sort();
    found
}

/// `of(paths, prompt_id)`: [(opaque id, the copy's path)] in their places.
pub fn of(folder: &Path, prompt_id: &str) -> Vec<(String, String)> {
    own(folder, prompt_id)
        .into_iter()
        .map(|(_, _, id, path)| (id, path.to_string_lossy().into_owned()))
        .collect()
}

/// `count(paths, prompt_id)`.
pub fn count(folder: &Path, prompt_id: &str) -> usize {
    of(folder, prompt_id).len()
}

/// `kept(paths, pending)`: (how many copies, their bytes) of the prompts still to go.
pub fn kept(folder: &Path, pending: &[String]) -> (i64, u64) {
    let (mut found, mut size) = (0, 0);
    for (path, name) in entries(folder) {
        if !pending.contains(&name.prompt) || name.place.is_none() {
            continue;
        }
        let Ok(meta) = std::fs::metadata(&path) else {
            continue;
        };
        size += meta.len();
        found += 1;
    }
    (found, size)
}

/// `place(paths, prompt_id, images)`: the prompt's pictures made exactly `images`.
pub fn place(folder: &Path, prompt_id: &str, images: &[String]) -> Result<(), ImageError> {
    let listed = entries(folder);
    let by_id: Vec<(&String, &PathBuf, &Name)> = listed
        .iter()
        .filter(|(_, name)| name.prompt == "new" || name.prompt == prompt_id)
        .map(|(path, name)| (&name.id, path, name))
        .collect();
    let lookup = |id: &str| {
        by_id
            .iter()
            .rev()
            .find(|(each, _, _)| each.as_str() == id)
            .copied()
    };
    if images.len() > MOST_IMAGES {
        return Err(ImageError::Refused("images_full"));
    }
    let distinct = images
        .iter()
        .enumerate()
        .all(|(index, one)| !images[..index].contains(one));
    if !distinct || images.iter().any(|image| lookup(image).is_none()) {
        return Err(ImageError::Refused("image_refused"));
    }
    for (index, image) in images.iter().enumerate() {
        let (_, path, name) = lookup(image).expect("checked above");
        let target = folder.join(format!(
            "{PREFIX}{prompt_id}-{}-{}-{image}.{}",
            index + 1,
            images.len(),
            name.ext
        ));
        if *path != target {
            std::fs::rename(path, &target).map_err(|error| ImageError::Os(error.to_string()))?;
        }
    }
    for (path, name) in &listed {
        if name.prompt == prompt_id && !images.contains(&name.id) {
            remove(path);
        }
    }
    Ok(())
}

/// `drop(paths, images)`: save's copies removed.
pub fn drop_staged(folder: &Path, images: &[String]) {
    for (path, name) in entries(folder) {
        if name.prompt == "new" && images.contains(&name.id) {
            remove(&path);
        }
    }
}

/// `problem(paths, prompt_id)`: whether the prompt's copies cannot be sent as they are.
pub fn problem(folder: &Path, prompt_id: &str) -> bool {
    let found = own(folder, prompt_id);
    let total = found.len() as i64;
    if found
        .iter()
        .enumerate()
        .any(|(index, (place, count, _, _))| *place != index as i64 + 1 || *count != total)
    {
        return true;
    }
    found
        .iter()
        .any(|(_, _, _, path)| read(&path.to_string_lossy()).is_err())
}

/// `sweep(paths, pending)`: every copy whose prompt is not still to go removed, and every save's copy older than
/// STAGED_FOR by the files' own clock; how many.
pub fn sweep(folder: &Path, pending: &[String]) -> i64 {
    let now = SystemTime::now();
    let mut removed = 0;
    for (path, name) in entries(folder) {
        if name.prompt == "new" {
            let Ok(changed) = std::fs::metadata(&path).and_then(|meta| meta.modified()) else {
                continue;
            };
            let age = now
                .duration_since(changed)
                .map_or(0.0, |age| age.as_secs_f64());
            if age < STAGED_FOR {
                continue;
            }
        } else if pending.contains(&name.prompt) {
            continue;
        }
        removed += remove(&path);
    }
    removed
}

/// `_remove(path)`: 1 where it was removed, never through a link.
fn remove(path: &Path) -> i64 {
    if is_link(&path.to_string_lossy()) {
        return 0;
    }
    i64::from(std::fs::remove_file(path).is_ok())
}
