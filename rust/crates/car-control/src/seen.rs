//! `control/seen.py`: a certain failure stays red until a person has seen it, and where that is written.
//!
//! v0.6.8. The acknowledgement is one number in a file of its own (`config/failure-seen.json`), out of the store
//! because it is a display's business and out of settings.json because it is not policy. A missing or unreadable
//! file shows nothing, and the watcher writes its start as the baseline when there is none.

use std::io::Write;
use std::path::{Path, PathBuf};

use car_machine::compat::{LoadsError, loads};
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_store::value::get;

use crate::error::{Failure, Res};
use crate::layer::{Control, State};

/// `SEEN_LIMIT`: the file holds one number.
pub const SEEN_LIMIT: u64 = 4096;
/// `SEEN_SKEW`: a seen time more than this past now was written while the clock was ahead.
pub const SEEN_SKEW: f64 = 300.0;

/// Why a read of the file says what it says.
pub type Why = &'static str;

/// The file's identity as last read and what it said (`Control._seen`).
#[derive(Clone, Debug)]
pub struct Remembered {
    stamp: (Option<u128>, u64),
    answer: (Option<f64>, Why),
}

/// A new file in `folder` whose name starts `prefix` and ends `suffix`, made exclusively (`tempfile.mkstemp`).
pub(crate) fn temporary(
    folder: &Path,
    prefix: &str,
    suffix: &str,
) -> std::io::Result<(PathBuf, std::fs::File)> {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    const LETTERS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789_";
    let seed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |since| since.as_nanos() as u64)
        ^ u64::from(std::process::id()).rotate_left(32);
    let mut last = None;
    for attempt in 0..10_000u64 {
        let mut state = seed
            ^ COUNTER
                .fetch_add(1, Ordering::Relaxed)
                .wrapping_mul(0x9E37_79B9_7F4A_7C15)
            ^ attempt;
        let name: String = (0..8)
            .map(|_| {
                state = state
                    .wrapping_mul(6_364_136_223_846_793_005)
                    .wrapping_add(1_442_695_040_888_963_407);
                char::from(LETTERS[((state >> 33) % LETTERS.len() as u64) as usize])
            })
            .collect();
        let path = folder.join(format!("{prefix}{name}{suffix}"));
        // `mkstemp`'s `os.open(O_RDWR | O_CREAT | O_EXCL)`: shared as Python shares (car-machine's pyfile).
        match car_machine::pyfile::options()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(file) => return Ok((path, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => last = Some(error),
            Err(error) => return Err(error),
        }
    }
    Err(last.unwrap_or_else(|| std::io::Error::other("no temporary name")))
}

/// `_replace_seen(path, value)`: write `{"seen_at": value}` to `path` whole: a temporary file, flushed to disk, then
/// moved over it. False where Windows refused, with nothing left behind.
fn replace_seen(path: &Path, value: f64) -> bool {
    let folder = path.parent().unwrap_or(Path::new("."));
    let Ok((temporary, mut file)) = temporary(folder, "failure-seen.", ".tmp") else {
        return false;
    };
    let mut body = Map::new();
    body.insert(Str::from("seen_at"), Value::Float(value));
    let written = to_string(&Value::Object(body), &Options::new())
        .ok()
        .map(|text| {
            file.write_all(text.as_bytes())
                .and_then(|_| file.flush())
                .and_then(|_| file.sync_all())
        });
    drop(file);
    if matches!(written, Some(Ok(()))) && car_platform::files::replace(&temporary, path).is_ok() {
        // `os.replace`: MoveFileExW alone (car-platform), which refuses a target another handle holds open.
        return true;
    }
    let _ = std::fs::remove_file(&temporary);
    false
}

fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Float(x) => Some(*x),
        Value::Int(int) => match int.as_i64() {
            Some(small) => Some(small as f64),
            // `float(int)` of an int too large for a float is an OverflowError, which the reader catches.
            None => int
                .to_string()
                .parse::<f64>()
                .ok()
                .filter(|x| x.is_finite()),
        },
        _ => None,
    }
}

/// `unseen_failure(marks, seen_at)`: the failure time the icon should still show, or None.
pub fn unseen_failure(marks: Option<&Map>, seen_at: Option<f64>) -> Option<f64> {
    let marks = marks?;
    let seen_at = seen_at?;
    let failed = match marks.get("failed_at") {
        Some(Value::Float(x)) => *x,
        Some(Value::Int(int)) => int.as_i64()? as f64,
        _ => return None,
    };
    let started = match marks.get("started_at") {
        Some(Value::Float(x)) => Some(*x),
        Some(Value::Int(int)) => Some(int.as_i64()? as f64),
        _ => None,
    };
    if started.is_some_and(|started| started > failed) {
        return None;
    }
    (failed > seen_at).then_some(failed)
}

/// `unseen_unconfirmed(marks, seen_at)`: the time of a sending nobody has confirmed, or None.
pub fn unseen_unconfirmed(marks: Option<&Map>, seen_at: Option<f64>) -> Option<f64> {
    let marks = marks?;
    seen_at?;
    let mut derived = Map::new();
    derived.insert(
        Str::from("failed_at"),
        marks.get("unconfirmed_at").cloned().unwrap_or(Value::Null),
    );
    derived.insert(
        Str::from("started_at"),
        marks.get("started_at").cloned().unwrap_or(Value::Null),
    );
    unseen_failure(Some(&derived), seen_at)
}

fn modified_ns(info: &std::fs::Metadata) -> Option<u128> {
    info.modified()
        .ok()?
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .map(|since| since.as_nanos())
}

impl Control {
    fn failure_seen_path(&self) -> PathBuf {
        PathBuf::from(&self.paths.failure_seen_file)
    }

    /// `_seen_file()`: (time, why): when a person last saw a failure and "ok"; or None and "missing", "invalid" or
    /// "unreadable". Read again only when the file changed.
    pub fn seen_file(&self) -> Res<(Option<f64>, Why)> {
        let path = self.failure_seen_path();
        if self.host.is_symlink(&path) {
            return Ok((None, "invalid"));
        }
        let info = match std::fs::metadata(&path) {
            Ok(info) => info,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok((None, "missing"));
            }
            Err(_) => return Ok((None, "unreadable")),
        };
        let stamp = (modified_ns(&info), info.len());
        if let Some(kept) = self.seen.borrow().as_ref()
            && kept.stamp == stamp
        {
            return Ok(kept.answer);
        }
        let mut value = None;
        if info.len() <= SEEN_LIMIT {
            let bytes = match car_machine::pyfile::read(&path) {
                Ok(bytes) => bytes,
                Err(_) => return Ok((None, "unreadable")),
            };
            // `read_text(encoding="utf-8")` raises a ValueError for bytes that are not text, which is "invalid".
            if let Ok(text) = String::from_utf8(bytes) {
                match loads(&text) {
                    Ok(Value::Object(map)) => {
                        value = map.get("seen_at").and_then(number);
                    }
                    Ok(_) => {}
                    Err(LoadsError::Recursion) => {
                        return Err(Failure::Other("RecursionError".into()));
                    }
                    Err(_) => {}
                }
            }
        }
        let answer = match value {
            Some(found) if found.is_finite() && found >= 0.0 => (Some(found), "ok"),
            _ => (None, "invalid"),
        };
        *self.seen.borrow_mut() = Some(Remembered { stamp, answer });
        Ok(answer)
    }

    /// `failure_seen_at()`.
    pub fn failure_seen_at(&self) -> Res<Option<f64>> {
        Ok(self.seen_file()?.0)
    }

    /// `failure_unseen(marks)`.
    pub fn failure_unseen(&self, marks: Option<&Map>) -> Res<bool> {
        Ok(unseen_failure(marks, self.failure_seen_at()?).is_some())
    }

    /// `unconfirmed_unseen(marks)`.
    pub fn unconfirmed_unseen(&self, marks: Option<&Map>) -> Res<bool> {
        Ok(unseen_unconfirmed(marks, self.failure_seen_at()?).is_some())
    }

    /// `_newest_failure()`.
    fn newest_failure(&self) -> Option<f64> {
        let State::Current(store) = self.open(true).ok()? else {
            return None;
        };
        let marks = store.failure_marks().ok()?;
        let times: Vec<f64> = ["failed_at", "unconfirmed_at"]
            .iter()
            .filter_map(|name| number(get(&marks, name)))
            .collect();
        times.into_iter().reduce(f64::max)
    }

    /// `acknowledge_failure(now=None, baseline=False)`: record that a person has seen every failure so far. The
    /// time only moves forward, and both processes that write it take one named lock.
    pub fn acknowledge_failure(&self, now: Option<f64>, baseline: bool) -> Res<Value> {
        let now = now.unwrap_or_else(|| self.host.now());
        let path = self.failure_seen_path();
        let reply = |seen: Option<f64>, written: bool| {
            let mut map = Map::new();
            map.insert(Str::from("seen_at"), seen.map_or(Value::Null, Value::Float));
            map.insert(Str::from("written"), Value::Bool(written));
            Value::Object(map)
        };
        let (seen, why) = self.seen_file()?;
        let settled = |seen: Option<f64>, why: Why| {
            baseline
                && (why == "unreadable" || (why == "ok" && seen.unwrap_or(0.0) <= now + SEEN_SKEW))
        };
        if settled(seen, why) {
            return Ok(reply(seen, false));
        }
        if !path.parent().is_some_and(Path::is_dir) {
            return Ok(reply(seen, false));
        }
        let newest = if baseline {
            None
        } else {
            self.newest_failure()
        };
        let lock = self.host.lock(&path.to_string_lossy(), 2.0).ok();
        let outcome = (|| -> Res<Value> {
            *self.seen.borrow_mut() = None;
            let (seen, why) = self.seen_file()?;
            if settled(seen, why) {
                return Ok(reply(seen, false));
            }
            let believed = seen.filter(|found| *found <= now + SEEN_SKEW);
            let value = [believed, Some(now), newest]
                .into_iter()
                .flatten()
                .reduce(f64::max)
                .unwrap_or(now);
            if !replace_seen(&path, value) {
                return Ok(reply(seen, false));
            }
            *self.seen.borrow_mut() = None;
            Ok(reply(Some(value), true))
        })();
        drop(lock);
        outcome
    }
}
