//! `codex/chains.py`: the ids a split conversation has had, remembered (v0.6.16-beta.3, issue #30).
//!
//! Codex can split a conversation more than once (`rollout.rs`): A's turns go on under B, then under C. Which ids came
//! before the current one is read from the names of A's earlier files - but a file can leave the sessions folder
//! (archived, deleted), and an id the next listing no longer finds would drop out of A's chain: A's own old failure
//! would be the latest again although the person worked under B, and every later id's place would move
//! (`rollout::SPAN`). So the chain a conversation has had is remembered here, and only ever extended: an id never
//! leaves it.
//!
//! What is kept is ids only - per Codex home (`homes::key`, a digest of its path), each conversation's ids in order -
//! in a small JSON file of the product's own state folder (config/split-chains.json), written whole and atomically, by
//! the watcher alone (the Dashboard's bridge reads it). Bounded: the newest MAX_CONVERSATIONS conversations of each
//! home and MAX_IDS ids each. Without a file (a test, the command line) it is remembered for this process only.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, LazyLock, Mutex};
use std::time::UNIX_EPOCH;

use car_machine::compat::loads;
use car_machine::domain::ids;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval::Py;
use car_policy::settings::homes;
use car_policy::settings::os::Os;
use indexmap::IndexMap;

pub const FORMAT: i64 = 1;
pub const MAX_CONVERSATIONS: usize = 2000;
pub const MAX_IDS: usize = 64;
pub const MAX_BYTES: u64 = 4 * 1024 * 1024;

type Table = IndexMap<String, Vec<String>>;

/// Each split conversation's ids, in order (its own first), as this product has seen them.
#[derive(Debug)]
pub struct ChainMemory {
    path: Option<PathBuf>,
    writable: bool,
    homes: Option<IndexMap<String, Table>>,
    stamp: Option<i128>,
}

fn is_uuid(text: &str) -> bool {
    ids::is_uuid(&Value::from(text))
}

/// `Path.stat().st_mtime_ns` on Windows: 100 ns ticks since 1970.
pub fn mtime_ns(path: &Path) -> Option<i128> {
    let modified = std::fs::metadata(path).ok()?.modified().ok()?;
    Some(match modified.duration_since(UNIX_EPOCH) {
        Ok(after) => i128::try_from(after.as_nanos()).ok()?,
        Err(before) => -i128::try_from(before.duration().as_nanos()).ok()?,
    })
}

impl ChainMemory {
    pub fn new(path: Option<&Path>, writable: bool) -> ChainMemory {
        ChainMemory {
            path: path.map(Path::to_path_buf),
            writable: writable && path.is_some(),
            homes: None,
            stamp: None,
        }
    }

    /// Whether a reader's file was written since it was read (the watcher writes; the bridge reads).
    fn changed(&mut self) -> bool {
        let stamp = self.path.as_deref().and_then(mtime_ns);
        if self.writable || stamp == self.stamp {
            return false;
        }
        self.stamp = stamp;
        true
    }

    fn read_file(&self) -> Result<Option<IndexMap<String, Table>>, &'static str> {
        let Some(path) = self.path.as_deref() else {
            return Ok(None);
        };
        if !path.is_file() {
            return Ok(None);
        }
        let Ok(found) = std::fs::metadata(path) else {
            return Ok(None);
        };
        if found.len() > MAX_BYTES {
            return Ok(None);
        }
        let Ok(bytes) = std::fs::read(path) else {
            return Ok(None);
        };
        let Ok(text) = String::from_utf8(bytes) else {
            return Ok(None);
        };
        let Ok(Value::Object(document)) = loads(&text) else {
            return Ok(None);
        };
        // `found.get("format") == FORMAT`: 1 is 1.0 is True.
        if !document
            .get("format")
            .is_some_and(|held| car_machine::pyval::eq(held, &Value::from(FORMAT)))
        {
            return Ok(None);
        }
        let mut homes: IndexMap<String, Table> = IndexMap::new();
        // `(found.get("homes") or {}).items()`: a truthy value that is no dict has no `items`.
        let held_homes = match document.get("homes") {
            None | Some(Value::Null) => None,
            Some(Value::Object(map)) if map.is_empty() => None,
            Some(Value::Object(map)) => Some(map),
            Some(other) if !car_machine::pyval::truthy(other) => None,
            Some(_) => return Err("AttributeError"),
        };
        for (home, held) in held_homes.into_iter().flatten() {
            let (Some(home), Value::Object(held)) = (home.as_str(), held) else {
                continue;
            };
            let mut table = Table::new();
            for (owner, chain) in held {
                let (Some(owner), Value::Array(chain)) = (owner.as_str(), chain) else {
                    continue;
                };
                if !is_uuid(owner) {
                    continue;
                }
                let kept: Vec<String> = chain
                    .iter()
                    .filter_map(|each| match each {
                        Value::Str(text) => text.as_str().filter(|word| is_uuid(word)),
                        _ => None,
                    })
                    .take(MAX_IDS)
                    .map(str::to_owned)
                    .collect();
                table.insert(owner.to_owned(), kept);
            }
            homes.insert(home.to_owned(), table);
        }
        Ok(Some(homes))
    }

    fn load(&mut self) -> Py<&mut IndexMap<String, Table>> {
        if self.homes.is_none() || self.changed() {
            self.homes = Some(IndexMap::new());
            match self.read_file() {
                Ok(Some(found)) => self.homes = Some(found),
                Ok(None) => {}
                Err(class) => return Err(class),
            }
        }
        Ok(self.homes.get_or_insert_with(IndexMap::new))
    }

    /// `get(home, thread_id)`: the ids after `thread_id`'s own that its turns have been recorded under, oldest first -
    /// none for none.
    pub fn get(&mut self, os: &dyn Os, home: &str, thread_id: &str) -> Py<Vec<String>> {
        let key = homes::key(os, &Str::from(home))?;
        Ok(self
            .load()?
            .get(&key)
            .and_then(|table| table.get(thread_id))
            .cloned()
            .unwrap_or_default())
    }

    /// `extend(home, thread_id, chain)`: `chain` (the ids after its own, oldest first) joined to what is remembered,
    /// which it only extends: what is remembered keeps its place, a new id goes after it. Returns the remembered
    /// chain, saved if it grew.
    pub fn extend(
        &mut self,
        os: &dyn Os,
        home: &str,
        thread_id: &str,
        chain: &[String],
    ) -> Py<Vec<String>> {
        let held = self.get(os, home, thread_id)?;
        let mut grown = held.clone();
        let mut seen: Vec<&String> = Vec::new();
        for each in chain {
            if seen.contains(&each) {
                continue;
            }
            seen.push(each);
            if !held.contains(each) && each != thread_id {
                grown.push(each.clone());
            }
        }
        if grown != held && grown.len() <= MAX_IDS {
            let key = homes::key(os, &Str::from(home))?;
            let table = self.load()?.entry(key).or_default();
            table.shift_remove(thread_id);
            table.insert(thread_id.to_owned(), grown.clone());
            while table.len() > MAX_CONVERSATIONS {
                table.shift_remove_index(0);
            }
            self.save();
            return Ok(grown);
        }
        Ok(held)
    }

    fn save(&mut self) {
        if !self.writable {
            return;
        }
        let (Some(path), Some(homes)) = (self.path.clone(), self.homes.as_ref()) else {
            return;
        };
        let mut all = Map::new();
        for (home, held) in homes {
            let mut table = Map::new();
            for (owner, chain) in held {
                table.insert(
                    Str::from(owner.as_str()),
                    Value::Array(
                        chain
                            .iter()
                            .map(|each| Value::from(each.as_str()))
                            .collect(),
                    ),
                );
            }
            all.insert(Str::from(home.as_str()), Value::Object(table));
        }
        let mut document = Map::new();
        document.insert(Str::from("format"), Value::from(FORMAT));
        document.insert(Str::from("homes"), Value::Object(all));
        let Ok(text) = to_string(&Value::Object(document), &Options::new()) else {
            return;
        };
        // Remembered for this process; written again on the next change.
        let _ = write_atomically(&path, &text);
    }
}

fn write_atomically(path: &Path, text: &str) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let stem = path
        .file_stem()
        .map(|each| each.to_string_lossy().into_owned())
        .unwrap_or_default();
    let temporary = path.with_file_name(format!("{stem}.{}.tmp", std::process::id()));
    std::fs::write(&temporary, text.as_bytes())?;
    car_platform::files::replace(&temporary, path)
}

type Key = (Option<String>, bool);

/// One memory per file in a process, and one for a source given none.
static MEMORIES: LazyLock<Mutex<HashMap<Key, Arc<Mutex<ChainMemory>>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// `memory(path, writable=)`: the `ChainMemory` of `path` (the state folder's file), shared by every reader in this
/// process - or the process's own where there is no file.
pub fn memory(path: Option<&Path>, writable: bool) -> Arc<Mutex<ChainMemory>> {
    let key = (path.map(winpathed), writable);
    let mut held = MEMORIES
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    Arc::clone(
        held.entry(key)
            .or_insert_with(|| Arc::new(Mutex::new(ChainMemory::new(path, writable)))),
    )
}

fn winpathed(path: &Path) -> String {
    car_config::winpath::path_str(&path.to_string_lossy())
}
