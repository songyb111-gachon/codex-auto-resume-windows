//! `codex/__init__.py`, `schema.py` and `history.py`: Codex's own files, read.
//!
//! [`LocalSource`] is the reference's reader composed of its two mixins: it finds Codex's databases and refuses one
//! whose schema has moved (`SchemaMixin`), and it asks every statement this product sends to Codex - and nowhere
//! else (`HistoryMixin`). Everything is read-only - the connections are opened `mode=ro`, with `query_only` set - and
//! nothing here writes to Codex, ever.
//!
//! The statements are the reference's, word for word, so what Codex's tables answer is what they answered there; the
//! values are Python's (a column's type is its Python type: [`crate::sql::Cell`]).

use std::collections::BTreeSet;
use std::path::Path;
use std::sync::{Arc, Mutex};

use car_config::winpath;
use car_machine::domain::{ids, skips, states};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_policy::classify::{failures, guards, projects};
use car_policy::settings::os::Os;
use rusqlite::Connection;

use crate::chains::{ChainMemory, memory};
use crate::eligibility::{self, ThreadRow};
use crate::errors::{Error, Result};
use crate::labels::label;
use crate::paths::{DB_KINDS, Kind, child, name_of, newest_generation, parent_of, safe_path};
use crate::payload::{detect, judge, later_turn, marker_row, queue_has_marker, unknown_reset};
use crate::rollout::{self, SPAN};
use crate::sql::{self, Cell, Param, Row};
use crate::values::{
    AGENT_CREATED_THREAD, COMPOSER, PROGRESS_ITEM_TYPES, epoch, json_of, normalize, row_status,
};
use crate::workspace;

/// Why a conversation is not taken up: a `domain/skips.py` reason and its kind word.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Why {
    pub reason: &'static str,
    pub kind: Option<String>,
}

impl Why {
    fn new(reason: &'static str, kind: Option<String>) -> Why {
        Why { reason, kind }
    }
}

/// `(its file, None)` for a conversation taken up, or `(None, why not)`.
pub type Verdict = (Option<String>, Option<Why>);

/// Two facts of Codex's home (`written`): when the newest state and history databases were last written.
pub struct Written {
    pub state_written: Option<f64>,
    pub history_written: Option<f64>,
}

fn obj(pairs: Vec<(&str, Value)>) -> Map {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    map
}

fn is_uuid(text: &str) -> bool {
    ids::is_uuid(&Value::from(text))
}

fn proof(text: &str) -> bool {
    ids::is_delivery_proof(&Value::from(text))
}

/// `column IN (?,?,...)` for `chain`.
fn of(chain: &[String], column: &str) -> String {
    format!("{column} IN ({})", vec!["?"; chain.len()].join(","))
}

fn texts(list: &[String]) -> Vec<Param<'_>> {
    list.iter().map(|each| Param::Text(each)).collect()
}

/// An int value as the number it is, where it fits (an ordinal, a count).
fn whole(value: &Value) -> Option<i128> {
    match value {
        Value::Int(number) => number.to_string().parse().ok(),
        _ => None,
    }
}

/// Python's `seq[index]` for an int `index` of any sign: None where it would raise IndexError.
fn at(length: usize, index: i128) -> Option<usize> {
    let length = length as i128;
    let resolved = if index < 0 { index + length } else { index };
    (0..length).contains(&resolved).then_some(resolved as usize)
}

/// Python's `seq[start:]`.
fn from_start(length: usize, start: i128) -> usize {
    let length = length as i128;
    let resolved = if start < 0 {
        (start + length).max(0)
    } else {
        start.min(length)
    };
    resolved as usize
}

/// The number a time bound is, as a parameter: an int stays an INTEGER, a float a REAL.
fn number_param(value: &Value) -> Param<'static> {
    match value {
        Value::Int(number) => number.as_i64().map_or_else(
            || Param::Real(number.to_string().parse().unwrap_or(f64::INFINITY)),
            Param::Int,
        ),
        Value::Float(number) => Param::Real(*number),
        Value::Bool(on) => Param::Int(i64::from(*on)),
        _ => Param::Null,
    }
}

/// Codex's own files, read read-only.
pub struct LocalSource {
    /// `_safe_path(Path(codex_home))`: the Codex home, resolved.
    pub home: String,
    os: Arc<dyn Os + Send + Sync>,
    chains: Arc<Mutex<ChainMemory>>,
    /// P19 (v0.6.16-beta.3): which conversations besides a person's own `eligibility` takes up - the engine sets it
    /// from its plug each tick; empty, the standard edition's always, it is A15 as ever.
    pub widened: BTreeSet<String>,
    /// P18 (v0.6.16-beta.4): the kinds of conversation besides the app's `eligibility` takes up, set by the engine
    /// from its plug each tick; empty, the standard edition's always.
    pub session_kinds: BTreeSet<String>,
}

impl LocalSource {
    /// `LocalSource(codex_home, chains=None)`. `chains` is the watcher's file of split ids, or this process's own.
    pub fn new(
        os: Arc<dyn Os + Send + Sync>,
        codex_home: &str,
        chains: Option<Arc<Mutex<ChainMemory>>>,
    ) -> Result<LocalSource> {
        let home = safe_path(os.as_ref(), codex_home)?;
        Ok(LocalSource {
            home,
            os,
            chains: chains.unwrap_or_else(|| memory(None, true)),
            widened: BTreeSet::new(),
            session_kinds: BTreeSet::new(),
        })
    }

    fn os(&self) -> &dyn Os {
        self.os.as_ref()
    }

    /// `elsewhere(codex_home)`: a reader of another Codex home, made as this one is (v0.6.15-beta): for the labels of
    /// that home's records, where the control layer, which builds no reader of its own, is handed this one.
    pub fn elsewhere(&self, codex_home: &str) -> Result<LocalSource> {
        let mut other = LocalSource::new(
            Arc::clone(&self.os),
            codex_home,
            Some(Arc::clone(&self.chains)),
        )?;
        // `type(self)(codex_home, chains=self.chains)`: a fresh reader, its own plug sets empty.
        other.widened = BTreeSet::new();
        other.session_kinds = BTreeSet::new();
        Ok(other)
    }

    // ------------------------------------------------------------------------------------------------ schema.py
    fn chain_get(&self, thread_id: &str) -> Result<Vec<String>> {
        let mut held = self
            .chains
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        Ok(held.get(self.os(), &self.home, thread_id)?)
    }

    fn chain_extend(&self, thread_id: &str, chain: &[String]) -> Result<Vec<String>> {
        let mut held = self
            .chains
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        Ok(held.extend(self.os(), &self.home, thread_id, chain)?)
    }

    fn schema_ok(connection: &Connection, kind: &Kind) -> rusqlite::Result<bool> {
        for (table, required) in kind.tables {
            if !table.starts_with(|c: char| c.is_ascii_alphabetic() || c == '_')
                || !table.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
            {
                return Ok(false);
            }
            let found = sql::columns(connection, table)?;
            if !required
                .iter()
                .all(|column| found.iter().any(|each| each == column))
            {
                return Ok(false);
            }
        }
        Ok(true)
    }

    /// `resolve(kind)`: the newest generation, only if its current schema is supported (the file's name).
    ///
    /// Older files can survive a Codex migration. They are not a fallback: their history and queue can be stale.
    /// Discover on every read so a running watcher never stays attached to the pre-migration database.
    pub fn resolve(&self, kind: &str) -> Result<String> {
        let found = crate::paths::kind(kind).ok_or(Error::Python("KeyError"))?;
        let path = match newest_generation(self.os(), &self.home, kind) {
            Ok(path) => path,
            Err(_) => return Err(Error::unavailable()),
        };
        if let Some(path) = path {
            let supported = (|| -> Option<bool> {
                let resolved = safe_path(self.os(), &path).ok()?;
                let connection = sql::connect(Path::new(&resolved)).ok()?;
                Self::schema_ok(&connection, found).ok()
            })();
            if supported == Some(true) {
                return Ok(name_of(&path));
            }
        } else if kind == "history" && self.history_not_made() {
            return Err(Error::history_not_yet());
        }
        Err(Error::source(&format!(
            "No Codex {kind} database with the required schema"
        )))
    }

    /// `_history_not_made()` (v0.6.26 final): whether a home with no history database is one Codex has not made it in
    /// yet - its newest state database read, and holding no conversation (`HistoryNotYet`). Anything that cannot be
    /// read is no: the refusal as it always was.
    fn history_not_made(&self) -> bool {
        self.no_conversation().unwrap_or(false)
    }

    /// `_no_conversation()` (`history.py`, v0.6.26 final): whether the newest state database holds no conversation - a
    /// row's being only, never a column of one.
    fn no_conversation(&self) -> Result<bool> {
        self.with_db("state", |connection| {
            Ok(sql::query(connection, "SELECT 1 FROM threads LIMIT 1", &[])?.is_empty())
        })
    }

    /// `_db(kind)`: a read-only connection to the newest generation of one of `DB_KINDS`, for the length of `body`.
    /// A failed read of Codex's files is the one refusal (`SourceError`), never what Codex's files said.
    fn with_db<T>(&self, kind: &str, body: impl FnOnce(&Connection) -> Result<T>) -> Result<T> {
        let name = self.resolve(kind)?;
        let run = || -> Result<T> {
            let path = safe_path(self.os(), &child(&self.home, &name))?;
            if !winpath::same_path(&parent_of(&path), &self.home) {
                return Err(Error::source(
                    "Codex database path is outside configured home",
                ));
            }
            let connection = sql::connect(Path::new(&path))?;
            body(&connection)
        };
        match run() {
            Err(Error::Sqlite | Error::Os | Error::Python("ValueError")) => {
                Err(Error::unavailable())
            }
            other => other,
        }
    }

    /// `written()`: when this home's newest state and history databases were last written: their files' - and their
    /// write-ahead logs' - modification times, one stat each, nothing opened; None where there is none.
    pub fn written(&self) -> Result<Written> {
        let mut found = [None, None];
        for (slot, kind) in found.iter_mut().zip(["state", "history"]) {
            let path = newest_generation(self.os(), &self.home, kind)?;
            let mut times: Vec<f64> = Vec::new();
            if let Some(path) = path {
                for each in [path.clone(), format!("{path}-wal")] {
                    if let Some(seconds) = std::fs::metadata(&each)
                        .ok()
                        .and_then(|facts| facts.modified().ok())
                        .and_then(|moment| moment.duration_since(std::time::UNIX_EPOCH).ok())
                    {
                        times.push(
                            seconds.as_secs() as f64 + f64::from(seconds.subsec_nanos()) * 1e-9,
                        );
                    }
                }
            }
            *slot = times.into_iter().reduce(f64::max);
        }
        Ok(Written {
            state_written: found[0],
            history_written: found[1],
        })
    }

    /// `cloud_tasks()`: how many cloud tasks the app knows: the entries under its `CLOUD_PREFIX` keys in the home's
    /// GLOBAL_STATE file, a count and nothing of them - or None where the file cannot be read as JSON.
    pub fn cloud_tasks(&self) -> Option<i64> {
        const PREFIX: &str = "cloud-thread-prototype-threads-by-account-v1.";
        const MAX_GLOBAL_STATE: u64 = 16 * 1024 * 1024;
        let path = child(&self.home, ".codex-global-state.json");
        if self.os().is_symlink(Path::new(&path)) {
            return None;
        }
        let size = std::fs::metadata(&path).ok()?.len();
        if size > MAX_GLOBAL_STATE {
            return None;
        }
        let text = String::from_utf8(car_machine::pyfile::read(&path).ok()?).ok()?;
        let data = car_machine::compat::loads(&text).ok()?;
        let (mut count, mut stack) = (0i64, vec![(&data, 0u32)]);
        while let Some((value, depth)) = stack.pop() {
            let Value::Object(map) = value else {
                continue;
            };
            if depth > 4 {
                continue;
            }
            for (key, held) in map {
                if key.as_str().is_some_and(|word| word.starts_with(PREFIX)) {
                    count += match held {
                        Value::Array(items) => items.len() as i64,
                        Value::Object(items) => items.len() as i64,
                        _ => 1,
                    };
                } else {
                    stack.push((held, depth + 1));
                }
            }
        }
        Some(count)
    }

    // -------------------------------------------------------------------------------------------- __init__.py
    /// `newer_than_engine(thread_id, kinds, engine_version)`: whether a conversation of one of `kinds` (P18) says a
    /// Codex newer than `engine_version` (the engine's `codex --version`) wrote it - the version skew guard.
    pub fn newer_than_engine(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        engine_version: &Value,
    ) -> Result<bool> {
        if kinds.is_empty() {
            return Ok(false);
        }
        let written = match self.written_by(thread_id, kinds)? {
            Some(version) => Value::from(version.as_str()),
            None => Value::Null,
        };
        Ok(eligibility::newer_than_engine(&written, engine_version))
    }

    /// `written_by(thread_id, kinds)`: the Codex version a conversation of one of `kinds` (P18) - a terminal's, VS
    /// Code's, never the app's own - says wrote it: its file's first line's `cli_version`, or None. Read only for a
    /// kind a plug names, so the standard edition, which names none, never reads it.
    pub fn written_by(&self, thread_id: &str, kinds: &BTreeSet<String>) -> Result<Option<String>> {
        let none = BTreeSet::new();
        if kinds.is_empty()
            || self.taken(thread_id, &none, None)?
            || !self.taken(thread_id, kinds, None)?
        {
            return Ok(None);
        }
        let Some(path) = self.rollout_path(thread_id)? else {
            return Ok(None);
        };
        let payload = rollout::session_meta(&path)?;
        Ok(
            match payload.as_ref().and_then(|map| map.get("cli_version")) {
                Some(Value::Str(text)) => text.as_str().map(str::to_owned),
                _ => None,
            },
        )
    }

    /// `_composed(thread_id, row, turn_id, strict)`: whether a conversation an agent made (thread_source
    /// agent_created_thread) is the person's in the turn `turn_id` - else its latest, the one a recovery is about -
    /// which they started from the input box, by the trigger the rollout records for it (issue #54). Unknown, and any
    /// other kind, is False; a strict read that cannot read raises SourceError, so the engine defers.
    fn composed(
        &self,
        thread_id: &str,
        row: &Row,
        turn_id: Option<&str>,
        strict: bool,
    ) -> Result<bool> {
        if row.get("thread_source").text() != Some(AGENT_CREATED_THREAD) {
            return Ok(false);
        }
        let outcome = (|| -> Result<bool> {
            let path =
                rollout::confined(self.os(), &self.home, thread_id, &row.value("rollout_path"))?;
            match path {
                Some(path) => {
                    Ok(rollout::turn_trigger(&path, turn_id)?.as_deref() == Some(COMPOSER))
                }
                None => Ok(false),
            }
        })();
        match outcome {
            Err(Error::Os) if strict => Err(Error::unavailable()),
            Err(Error::Os) => Ok(false),
            other => other,
        }
    }

    /// `rescan_evidence(thread_id, turn_id)`: what the conversation's current file says of the failed turn `turn_id`
    /// (`rollout::superseded_in`), for a person's Rescan and reconcile (v0.6.16, issue #39) while Codex's history is
    /// behind it: the file `eligibility` names, so one confined to the sessions folder whose first line says it is
    /// this conversation's - a split's A_B file too (issue #30). `unreadable` for anything that cannot be read, or for
    /// a conversation not taken up.
    pub fn rescan_evidence(&self, thread_id: &str, turn_id: &str) -> &'static str {
        if !is_uuid(turn_id) {
            return rollout::UNREADABLE;
        }
        match self.eligibility(thread_id, true, None, None, None) {
            Ok((Some(path), _)) => rollout::superseded_in(&path, turn_id, None),
            _ => rollout::UNREADABLE,
        }
    }

    // ------------------------------------------------------------------------------------------- history.py
    /// `_eligibility(thread_id, strict, kinds, turn_id, widened)`: `(its file, None)` for a conversation taken up - a
    /// person's own desktop one (A15), a kind (P18, `kinds`) or label (P19, `widened`) the plug names, else this
    /// tick's - or `(None, why not)`. `strict` (latest) re-raises transient I/O as SourceError, so the engine defers;
    /// agent-made: `turn_id` (#54).
    pub fn eligibility(
        &self,
        thread_id: &str,
        strict: bool,
        kinds: Option<&BTreeSet<String>>,
        turn_id: Option<&str>,
        widened: Option<&BTreeSet<String>>,
    ) -> Result<Verdict> {
        let kinds = kinds.unwrap_or(&self.session_kinds);
        let widened = widened.unwrap_or(&self.widened);
        let not =
            |reason, kind: Option<String>| -> Verdict { (None, Some(Why::new(reason, kind))) };
        if !is_uuid(thread_id) {
            return Ok(not(skips_unknown(), None));
        }
        let row = self.with_db("state", |connection| {
            Ok(sql::first(
                connection,
                "SELECT rollout_path,source,thread_source,archived,history_mode FROM threads WHERE id=?",
                &[Param::Text(thread_id)],
            )?)
        })?;
        let Some(row) = row else {
            return Ok(not(skips_unknown(), None));
        };
        let composed = self.composed(thread_id, &row, turn_id, strict)?;
        let problem = eligibility::row_problem(
            &ThreadRow {
                source: row.get("source"),
                archived: row.get("archived"),
                thread_source: row.get("thread_source"),
                history_mode: row.get("history_mode"),
            },
            kinds,
            widened,
            composed,
        )?;
        if let Some(word) = problem {
            return Ok(not(skips_other_kind(), Some(word)));
        }
        let outcome = (|| -> Result<Verdict> {
            let path =
                rollout::confined(self.os(), &self.home, thread_id, &row.value("rollout_path"))?;
            let payload = match &path {
                None => None,
                Some(path) => rollout::session_meta(path)?,
            };
            let Some(payload) = payload else {
                return Ok(not(skips_other_kind(), Some("file".to_owned())));
            };
            if !payload
                .get("id")
                .is_some_and(|held| pyval::is(held, thread_id))
            {
                return Ok(not(skips_other_kind(), Some("file".to_owned())));
            }
            let first = Value::Object(payload.clone());
            let source = row.value("source");
            if !eligibility::originator_taken(&source, &first, kinds, widened)? {
                let word = skips::kind(payload.get("originator").unwrap_or(&Value::Null));
                return Ok(not(skips_other_kind(), Some(format!("originator {word}"))));
            }
            let own = row.value("thread_source");
            let found = eligibility::kind_of(&source, &first, kinds, widened)?;
            if found.is_none()
                || !pyval::eq(payload.get("thread_source").unwrap_or(&Value::Null), &own)
            {
                let word = skips::kind(payload.get("thread_source").unwrap_or(&Value::Null));
                return Ok(not(skips_other_kind(), Some(format!("file {word}"))));
            }
            Ok((path, None))
        })();
        match outcome {
            // Transient (AV scanner, sharing violation) vs a genuinely ineligible thread.
            Err(Error::Os) if strict => Err(Error::unavailable()),
            Err(Error::Os) => Ok(not(skips_other_kind(), Some("file".to_owned()))),
            Err(Error::Python("ValueError" | "UnicodeError")) => {
                Ok(not(skips_other_kind(), Some("file".to_owned())))
            }
            other => other,
        }
    }

    /// `taken(thread_id, kinds, widened)`: whether `thread_id` is taken up with `kinds` watched (P18) and `widened`
    /// (P19), else this tick's.
    pub fn taken(
        &self,
        thread_id: &str,
        kinds: &BTreeSet<String>,
        widened: Option<&BTreeSet<String>>,
    ) -> Result<bool> {
        Ok(self
            .eligibility(thread_id, false, Some(kinds), None, widened)?
            .0
            .is_some())
    }

    /// `_chain(thread_id, strict, turn_id)`: (its file, every id its turns are recorded under - its own first, each
    /// split id oldest first, the current last -, why not); the file None for a conversation this does not recover.
    /// Split ids (`rollout.rs`, issue #30) count only when every guard holds: its current file is named exactly
    /// A_B.jsonl, its session_meta says A, no split id has a `threads` row and no other conversation's file names the
    /// current one. Any doubt is A alone, today's read. The queue and the app's hold stay under A always.
    pub fn chain(
        &self,
        thread_id: &str,
        strict: bool,
        turn_id: Option<&str>,
    ) -> Result<(Option<String>, Vec<String>, Option<Why>)> {
        let (path, why) = self.eligibility(thread_id, strict, None, turn_id, None)?;
        let current = path
            .as_deref()
            .and_then(|file| rollout::continued_id(thread_id, &name_of(file)));
        let Some(current) = current else {
            return Ok((path, vec![thread_id.to_owned()], why));
        };
        // What was seen before is kept (`chains.rs`); an earlier file's id joins only if it says it is A's.
        let held = self.chain_get(thread_id)?;
        let found: Vec<String> = rollout::earlier(self.os(), &self.home, thread_id, &current)
            .into_iter()
            .filter(|(other, file)| {
                !held.contains(other) && rollout::meta_id(file).as_deref() == Some(thread_id)
            })
            .map(|(other, _)| other)
            .collect();
        let mut chain: Vec<String> = Vec::new();
        for each in held.iter().chain(&found).chain(std::iter::once(&current)) {
            if !chain.contains(each) {
                chain.push(each.clone());
            }
        }
        let rows = self.with_db("state", |connection| {
            let matches = vec!["instr(rollout_path,?)>0"; chain.len()].join(" OR ");
            let statement = format!(
                "SELECT id,rollout_path FROM threads WHERE {} OR (id<>? AND ({matches}))",
                of(&chain, "id")
            );
            let mut parameters = texts(&chain);
            parameters.push(Param::Text(thread_id));
            parameters.extend(texts(&chain));
            Ok(sql::query(connection, &statement, &parameters)?)
        })?;
        let pairs: Vec<(Option<String>, Option<String>)> = rows
            .iter()
            .map(|row| {
                (
                    row.at(0).text().map(str::to_owned),
                    row.at(1).text().map(str::to_owned),
                )
            })
            .collect();
        let taken = rollout::taken(&chain, &pairs);
        if held
            .iter()
            .chain(std::iter::once(&current))
            .any(|each| taken.contains(each))
        {
            return Ok((path, vec![thread_id.to_owned()], why));
        }
        let wanted: Vec<String> = chain
            .iter()
            .filter(|other| !taken.contains(*other))
            .cloned()
            .collect();
        let chain = self.chain_extend(thread_id, &wanted)?;
        let mut all = vec![thread_id.to_owned()];
        all.extend(chain.iter().cloned());
        if !chain.contains(&current) {
            all.push(current);
        }
        Ok((path, all, why))
    }

    /// `_ids(thread_id)`: every id a conversation's turns are recorded under (`chain`): every read of its turns asks
    /// this.
    fn ids(&self, thread_id: &str) -> Result<Vec<String>> {
        if is_uuid(thread_id) {
            Ok(self.chain(thread_id, false, None)?.1)
        } else {
            Ok(vec![thread_id.to_owned()])
        }
    }

    /// `turn_chain(thread_id)`: `_ids`, for the advanced edition's turn reader, which reads a split conversation as
    /// core does.
    pub fn turn_chain(&self, thread_id: &str) -> Result<Vec<String>> {
        self.ids(thread_id)
    }

    /// `_after(chain, ordinal, prefix)`: (condition, parameters) for the turns after the one at `ordinal`
    /// (`rollout::SPAN`): later in its own id, and every turn of each later id.
    fn after<'a>(
        chain: &'a [String],
        ordinal: &Value,
        prefix: &str,
    ) -> Result<(String, Vec<Param<'a>>)> {
        let ordinal = whole(ordinal).ok_or(Error::Python("OverflowError"))?;
        let (index, own) = (ordinal.div_euclid(SPAN), ordinal.rem_euclid(SPAN));
        let last = chain.len() as i128 - 1;
        let pick = index.min(last);
        let later = &chain[from_start(chain.len(), pick + 1)..];
        let own_id = &chain[at(chain.len(), pick).ok_or(Error::Python("IndexError"))?];
        let extra = if later.is_empty() {
            String::new()
        } else {
            format!(" OR {}", of(later, &format!("{prefix}thread_id")))
        };
        let condition = format!("({prefix}thread_id=? AND {prefix}rollout_ordinal>?{extra})");
        let mut parameters = vec![Param::Text(own_id), Param::Int(own as i64)];
        parameters.extend(texts(later));
        Ok((condition, parameters))
    }

    /// `_latest_row(connection, chain, columns)`: (its index in `chain`, its row) for a conversation's latest turn: the
    /// latest of the newest id with one.
    fn latest_row(
        connection: &Connection,
        chain: &[String],
        columns: &str,
    ) -> Result<(usize, Option<Row>)> {
        for index in (0..chain.len()).rev() {
            let row = sql::first(
                connection,
                &format!(
                    "SELECT {columns} FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal DESC LIMIT 1"
                ),
                &[Param::Text(&chain[index])],
            )?;
            if row.is_some() {
                return Ok((index, row));
            }
        }
        Ok((0, None))
    }

    /// `_owner(turns_id, turn_id)`: (conversation, None, index) for the conversation this recovers whose turns are
    /// recorded under `turns_id`, at that index of its `chain` - itself, or the one conversation whose file names it -
    /// or (its id or None, why not, 0). With `turn_id`, that turn must be the conversation's latest: a turn of an id
    /// split away from is not (A17), and an id no file names any more is nobody's.
    pub fn owner(
        &self,
        turns_id: Option<&str>,
        turn_id: Option<&str>,
    ) -> Result<(Option<String>, Option<Why>, usize)> {
        let unknown = (None, Some(Why::new(skips_unknown(), None)), 0);
        let Some(turns_id) = turns_id.filter(|each| is_uuid(each)) else {
            return Ok(unknown);
        };
        let rows = self.with_db("state", |connection| {
            Ok(sql::query(
                connection,
                "SELECT id FROM threads WHERE id=? OR instr(rollout_path,?)>0",
                &[Param::Text(turns_id), Param::Text(turns_id)],
            )?)
        })?;
        // `{row[0] for row in ...}`: a set - equal values once.
        let mut found: Vec<Cell> = Vec::new();
        for row in &rows {
            if !found.contains(row.at(0)) {
                found.push(row.at(0).clone());
            }
        }
        let named = if found.is_empty() {
            rollout::named_after(self.os(), &self.home, turns_id)
        } else {
            Vec::new()
        };
        let owner: Option<Cell> = if found.iter().any(|each| each.text() == Some(turns_id)) {
            Some(Cell::Text(turns_id.to_owned()))
        } else if found.len() == 1 {
            Some(found[0].clone())
        } else if named.len() == 1 {
            Some(Cell::Text(named[0].clone()))
        } else {
            None
        };
        let Some(owner) = owner
            .as_ref()
            .and_then(Cell::text)
            .filter(|each| is_uuid(each))
        else {
            return Ok(unknown);
        };
        let (path, chain, why) = self.chain(owner, false, turn_id)?;
        if path.is_none() {
            return Ok((Some(owner.to_owned()), why, 0));
        }
        let Some(place) = chain.iter().position(|each| each == turns_id) else {
            return Ok((
                Some(owner.to_owned()),
                Some(Why::new(skips_continued(), None)),
                0,
            ));
        };
        if let Some(turn) = turn_id
            && chain.len() > 1
        {
            let row = self.with_db("history", |connection| {
                Ok(Self::latest_row(connection, &chain, "turn_id")?.1)
            })?;
            if row
                .as_ref()
                .is_none_or(|each| each.get("turn_id").text() != Some(turn))
            {
                return Ok((
                    Some(owner.to_owned()),
                    Some(Why::new(skips_newer(), None)),
                    place,
                ));
            }
        }
        Ok((Some(owner.to_owned()), None, place))
    }

    /// `owner_of(turns_id)`: the conversation whose turns are recorded under `turns_id` (`owner`), or None - for the
    /// advanced edition's list of conversations that finished a turn lately.
    pub fn owner_of(&self, turns_id: &str) -> Result<Option<String>> {
        let (owner, why, _) = self.owner(Some(turns_id), None)?;
        Ok(if why.is_none() { owner } else { None })
    }

    /// `_rollout_path(thread_id)`: where a conversation's file is, confined to the Codex sessions folder
    /// (`rollout::confined`). Only for the size comparison behind projection freshness: the file is not opened, and
    /// whether the thread is still eligible does not matter - a settle must tell, for an archived thread too, whether
    /// Codex's history has caught up.
    pub fn rollout_path(&self, thread_id: &str) -> Result<Option<String>> {
        if !is_uuid(thread_id) {
            return Ok(None);
        }
        let row = self.with_db("state", |connection| {
            Ok(sql::first(
                connection,
                "SELECT rollout_path FROM threads WHERE id=?",
                &[Param::Text(thread_id)],
            )?)
        })?;
        match row {
            None => Ok(None),
            Some(row) => {
                rollout::confined(self.os(), &self.home, thread_id, &row.value("rollout_path"))
            }
        }
    }

    /// `latest(thread_id)`: a conversation's latest turn, read as `normalize` reads one.
    pub fn latest(&self, thread_id: &str) -> Result<Option<Map>> {
        if !is_uuid(thread_id) {
            return Ok(None);
        }
        let (path, chain, _) = self.chain(thread_id, true, None)?;
        if path.is_none() {
            return Ok(None);
        }
        let (index, row) = self.with_db("history", |connection| {
            Self::latest_row(
                connection,
                &chain,
                "thread_id,turn_id,status,started_at,completed_at,rollout_ordinal,error_json",
            )
        })?;
        match row {
            Some(row) => {
                let placed = rollout::placed(&row.dict(), &Value::from(thread_id), index);
                Ok(normalize(&Value::Object(placed))?)
            }
            None => Ok(None),
        }
    }

    /// `latest_failures(since, needs_you, admissible, shapes)`: every conversation's latest turn that failed since
    /// `since` and that this product would recover (`detect`). `needs_you` (v0.6.11) adds those of these categories,
    /// normalized the same way with the id `detect` would give, but never through it: none can become a record
    /// (A14).
    ///
    /// v0.6.14, only while the plug wants P17: `admissible` adds, marked so, those it may take up, and `shapes` gives
    /// each entry its error's shape - never a word of a message; each through the same check of its conversation
    /// (A15).
    pub fn latest_failures(
        &self,
        since: &Value,
        needs_you: &BTreeSet<String>,
        admissible: bool,
        shapes: bool,
    ) -> Result<Vec<Map>> {
        if !epoch(since)? {
            return Err(Error::source("Invalid detection start timestamp"));
        }
        // Read only failure metadata; no transcript scanning or folder traversal.
        let rows = self.with_db("history", |connection| {
            Ok(sql::query(
                connection,
                "SELECT t.thread_id,t.turn_id,t.status,t.started_at,t.completed_at,\
                 t.rollout_ordinal,t.error_json FROM thread_turns t \
                 WHERE t.status='failed' AND t.completed_at>=? \
                 AND NOT EXISTS (SELECT 1 FROM thread_turns n \
                 WHERE n.thread_id=t.thread_id AND n.rollout_ordinal>t.rollout_ordinal)",
                &[number_param(since)],
            )?)
        })?;
        let mut result = Vec::new();
        for row in &rows {
            // A turn recorded under another id is read as its conversation's (`owner`); no owner, no failure.
            let dict = row.dict();
            let (owner, why, index) = if judge(&dict, needs_you, admissible, shapes)?.is_some() {
                self.owner(row.get("thread_id").text(), row.get("turn_id").text())?
            } else {
                (None, None, 0)
            };
            if let Some(owner) = owner
                && why.is_none()
            {
                let placed = rollout::placed(&dict, &Value::from(owner.as_str()), index);
                if let Some(found) = judge(&placed, needs_you, admissible, shapes)? {
                    result.push(found);
                }
            }
        }
        Ok(result)
    }

    /// `passed_over(since, before, every_status, known, newest, deadline)`: what `latest_failures` does not bring, and
    /// why (v0.6.16-beta.3, issue #27). "passed": each failed turn completed at `before` or later - or, with
    /// `every_status` (the Diagnostics check), every conversation's latest turn - whose turn id is not in `known`,
    /// with the reason (`domain/skips.py`) it stops at, in the order `latest_failures` decides: a later turn (A17),
    /// before `since` (A16), its conversation (A15, `owner`), its kind (A13); None where it would be brought, or is no
    /// failure. "seen": how many failed latest turns from `since` on the read held. Lifecycle columns, ids and kind
    /// words only. With `newest` (every_status only) the most recent that many conversations, "more" saying how many
    /// are left out; past `deadline` (`rollout::monotonic`) nothing more is explained, "unchecked" saying how many were
    /// not.
    pub fn passed_over(
        &self,
        since: &Value,
        before: &Value,
        every_status: bool,
        known: &BTreeSet<String>,
        newest: Option<usize>,
        deadline: Option<f64>,
    ) -> Result<Map> {
        if !epoch(since)? || !epoch(before)? {
            return Err(Error::source("Invalid detection start timestamp"));
        }
        let newest = newest.filter(|each| *each != 0);
        let rows = self.with_db("history", |connection| {
            let ending = if newest.is_some() {
                " AND NOT EXISTS (SELECT 1 FROM thread_turns n WHERE n.thread_id=t.thread_id AND n.rollout_ordinal\
                 >t.rollout_ordinal) ORDER BY coalesce(t.completed_at,t.started_at) DESC"
            } else {
                ""
            };
            Ok(sql::query(
                connection,
                &format!(
                    "SELECT t.thread_id,t.turn_id,t.status,t.started_at,t.completed_at,t.rollout_ordinal,t.error_json,\
                     EXISTS (SELECT 1 FROM thread_turns n WHERE n.thread_id=t.thread_id \
                     AND n.rollout_ordinal>t.rollout_ordinal) AS later FROM thread_turns t \
                     WHERE (t.status='failed' OR ?) AND coalesce(t.completed_at,t.started_at)>=?{ending}"
                ),
                &[Param::Int(i64::from(every_status)), number_param(before)],
            )?)
        })?;
        let total = rows.len();
        let kept = newest.unwrap_or(total);
        let more = total.saturating_sub(kept);
        let rows = &rows[..kept.min(total)];
        let (mut seen, mut found, mut unchecked) = (0i64, Vec::new(), 0i64);
        for row in rows {
            if let Some(limit) = deadline
                && rollout::monotonic() > limit
            {
                unchecked += 1;
                continue;
            }
            let failed = row.get("status").text() == Some("failed");
            let when = row.value("completed_at");
            let later = row.get("later").truthy();
            let inside = epoch(&when)? && pyval::less_or_equal(since, &when)?;
            seen += i64::from(failed && inside && !later);
            let turn = row.get("turn_id");
            if (every_status && later) || turn.text().is_some_and(|word| known.contains(word)) {
                continue;
            }
            let dict = row.dict();
            let category: Option<&'static str> = if failed {
                normalize(&Value::Object(dict.clone()))?
                    .and_then(|found| found.get("category").cloned())
                    .and_then(|held| match held {
                        Value::Str(text) => text.as_str().and_then(|word| {
                            failures::CATEGORIES
                                .iter()
                                .find(|each| **each == word)
                                .copied()
                        }),
                        _ => None,
                    })
            } else {
                None
            };
            let thread_value = row.value("thread_id");
            let (owner, why, index): (Value, Option<Why>, usize) = if later {
                (thread_value.clone(), Some(Why::new(skips_newer(), None)), 0)
            } else if failed && !inside {
                (
                    thread_value.clone(),
                    Some(Why::new(skips_before(), None)),
                    0,
                )
            } else {
                let (owner, why, index) = self.owner(row.get("thread_id").text(), turn.text())?;
                (
                    owner.map_or(Value::Null, |each| Value::from(each.as_str())),
                    why,
                    index,
                )
            };
            let mut why = why;
            if why.is_none() && failed {
                let placed = rollout::placed(&dict, &owner, index);
                if judge(&placed, &BTreeSet::new(), false, false)?.is_none() {
                    why = Some(Why::new(
                        skips_not_recovered(),
                        Some(skips::kind(&category.map_or(Value::Null, Value::from))),
                    ));
                }
            }
            let owner_or = if pyval::truthy(&owner) {
                owner.clone()
            } else {
                thread_value.clone()
            };
            let turns_id = if !pyval::eq(&owner, &Value::Null) && !pyval::eq(&owner, &thread_value)
            {
                thread_value.clone()
            } else {
                Value::Null
            };
            let status = row_status(&row.value("status"))?;
            found.push(Value::Object(obj(vec![
                ("thread_id", owner_or),
                ("turn_id", row.value("turn_id")),
                ("turns_id", turns_id),
                ("status", status.map_or(Value::Null, Value::from)),
                ("category", category.map_or(Value::Null, Value::from)),
                (
                    "completed_at",
                    if epoch(&when)? {
                        when.clone()
                    } else {
                        Value::Null
                    },
                ),
                (
                    "reason",
                    why.as_ref()
                        .map_or(Value::Null, |each| Value::from(each.reason)),
                ),
                (
                    "kind",
                    why.as_ref()
                        .and_then(|each| each.kind.as_deref())
                        .map_or(Value::Null, Value::from),
                ),
            ])));
        }
        Ok(obj(vec![
            ("seen", Value::from(seen)),
            ("passed", Value::Array(found)),
            ("more", Value::from(more as i64)),
            ("unchecked", Value::from(unchecked)),
        ]))
    }

    /// `stalled_turns(since, quiet_seconds, now)`: conversations whose latest turn is still in progress and recorded
    /// nothing new for `quiet_seconds` (v0.6.11, a needs-you notice): lifecycle columns and its newest item's time,
    /// never content (B7, B9); only a person's own desktop conversation (A15), none where items carry no time (B5).
    pub fn stalled_turns(
        &self,
        since: &Value,
        quiet_seconds: &Value,
        now: &Value,
    ) -> Result<Vec<Map>> {
        let quiet_ok = whole(quiet_seconds).is_some_and(|seconds| seconds > 0);
        if !epoch(since)? || !pyval::is_int(quiet_seconds) || !quiet_ok {
            return Err(Error::source("Invalid stall window"));
        }
        let rows = self.with_db("history", |connection| {
            let columns = sql::columns(connection, "thread_items")?;
            if !columns.iter().any(|each| each == "created_at_ms") {
                return Ok(Vec::new());
            }
            // `now - quiet_seconds` is asked only once the items are known to carry a time.
            let limit = pyval::minus(now, quiet_seconds)?;
            let bound = match (now, quiet_seconds) {
                (Value::Int(each), Value::Int(quiet)) => match (each.as_i64(), quiet.as_i64()) {
                    (Some(now), Some(quiet)) => now
                        .checked_sub(quiet)
                        .map_or(Param::Real(limit), Param::Int),
                    _ => Param::Real(limit),
                },
                _ => Param::Real(limit),
            };
            Ok(sql::query(
                connection,
                "SELECT t.thread_id,t.turn_id,t.started_at,\
                 (SELECT max(i.created_at_ms) FROM thread_items i WHERE i.thread_id=t.thread_id \
                 AND i.turn_id=t.turn_id) AS last_item_ms FROM thread_turns t \
                 WHERE t.status='inProgress' AND t.started_at>=? AND t.started_at<=? \
                 AND NOT EXISTS (SELECT 1 FROM thread_turns n \
                 WHERE n.thread_id=t.thread_id AND n.rollout_ordinal>t.rollout_ordinal)",
                &[number_param(since), bound],
            )?)
        })?;
        let mut found = Vec::new();
        for row in &rows {
            let (thread, turn, started) = (
                row.get("thread_id"),
                row.get("turn_id"),
                row.value("started_at"),
            );
            let (Some(thread), Some(turn)) = (thread.text(), turn.text()) else {
                continue;
            };
            if !is_uuid(thread) || !is_uuid(turn) || !epoch(&started)? {
                continue;
            }
            let item = match row.get("last_item_ms") {
                Cell::Int(last) if epoch(&Value::from(last.div_euclid(1000)))? => {
                    Some(Value::Float(*last as f64 / 1000.0))
                }
                _ => None,
            };
            let moved = match &item {
                Some(item) => pyval::max(&[&started, item])?.clone(),
                None => started.clone(),
            };
            let (owner, why, _) =
                if pyval::minus(now, &moved)? >= pyval::minus(quiet_seconds, &Value::from(0))? {
                    self.owner(Some(thread), Some(turn))?
                } else {
                    (None, None, 0)
                };
            if let Some(owner) = owner
                && why.is_none()
            {
                found.push(obj(vec![
                    ("thread_id", Value::from(owner.as_str())),
                    ("turn_id", Value::from(turn)),
                    ("moved_at", moved),
                ]));
            }
        }
        Ok(found)
    }

    /// `identity(thread_id)`: human-facing labels for one thread, never used to *find* one. Only `threads.name` is
    /// read as a title: `title`, `preview` and `first_user_message` hold the raw first prompt (up to 67 KB seen), so
    /// they are never touched; `name` is capped and single-line-checked anyway. A missing column is no error.
    pub fn identity(&self, thread_id: &str) -> Result<Map> {
        let blank = || {
            obj(vec![
                ("name", Value::Null),
                ("project", Value::Null),
                ("cwd_basename", Value::Null),
            ])
        };
        if !is_uuid(thread_id) {
            return Ok(blank());
        }
        let found = self.with_db("state", |connection| {
            let columns = sql::columns(connection, "threads")?;
            let wanted: Vec<&str> = ["name", "cwd", "project_id"]
                .into_iter()
                .filter(|name| columns.iter().any(|each| each == name))
                .collect();
            if wanted.is_empty() {
                return Ok(blank());
            }
            let row = sql::first(
                connection,
                &format!("SELECT {} FROM threads WHERE id=?", wanted.join(",")),
                &[Param::Text(thread_id)],
            )?;
            let Some(row) = row else {
                return Ok(blank());
            };
            let mut project = Value::Null;
            let project_id = if row.has("project_id") {
                row.get("project_id").clone()
            } else {
                Cell::Null
            };
            if project_id != Cell::Null {
                let has_projects = sql::first(
                    connection,
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'",
                    &[],
                )?;
                if has_projects.is_some() {
                    let named = sql::first(
                        connection,
                        "SELECT name FROM projects WHERE id=?",
                        &[project_id.param()],
                    )?;
                    if let Some(named) = named {
                        project = label(&named.value("name")).map_or(Value::Null, Value::from);
                    }
                }
            }
            let cwd = if row.has("cwd") {
                row.get("cwd").clone()
            } else {
                Cell::Null
            };
            let mut base = Value::Null;
            if let Cell::Text(cwd) = &cwd
                && !car_machine::pytext::strip(cwd).is_empty()
            {
                // SQLite stores Windows extended paths; the prefix is not part of a name.
                let plain = cwd.strip_prefix("\\\\?\\").unwrap_or(cwd);
                base =
                    label(&Value::from(name_of(plain).as_str())).map_or(Value::Null, Value::from);
            }
            let name = if row.has("name") {
                row.value("name")
            } else {
                Value::Null
            };
            Ok(obj(vec![
                ("name", label(&name).map_or(Value::Null, Value::from)),
                ("project", project),
                ("cwd_basename", base),
            ]))
        });
        match found {
            Err(Error::Source(_) | Error::Sqlite | Error::Os | Error::Python("ValueError")) => {
                Ok(blank())
            }
            other => other,
        }
    }

    /// `project_key(thread_id)`: the key of the project a conversation is filed under (`projects::key_for`), or None:
    /// its project id or else its folder, digested here - the key is all that leaves, and nothing is found by it (B8).
    /// Asked only when Settings let some projects resume and not others; the two columns the labels read.
    pub fn project_key(&self, thread_id: &str) -> Result<Option<String>> {
        if !is_uuid(thread_id) {
            return Ok(None);
        }
        let found = self.with_db("state", |connection| {
            let columns = sql::columns(connection, "threads")?;
            let wanted: Vec<&str> = ["project_id", "cwd"]
                .into_iter()
                .filter(|name| columns.iter().any(|each| each == name))
                .collect();
            if wanted.is_empty() {
                return Ok(None);
            }
            Ok(sql::first(
                connection,
                &format!("SELECT {} FROM threads WHERE id=?", wanted.join(",")),
                &[Param::Text(thread_id)],
            )?)
        });
        let row = match found {
            Err(Error::Source(_) | Error::Sqlite | Error::Os | Error::Python("ValueError")) => {
                return Ok(None);
            }
            Err(other) => return Err(other),
            Ok(row) => row,
        };
        let Some(row) = row else {
            return Ok(None);
        };
        let project = if row.has("project_id") {
            row.value("project_id")
        } else {
            Value::Null
        };
        let cwd = if row.has("cwd") {
            row.value("cwd")
        } else {
            Value::Null
        };
        Ok(projects::key_for(&project, &cwd))
    }

    /// `task_facts(thread_id, fingerprint, tokens)`: what the two guards of v0.6.11 read of a conversation
    /// (`guards`), and only what they ask: "print", the digest of its model, approval mode and folder's git HEAD
    /// (`workspace.rs`), and "tokens", Codex's own count where `tokens_used` is a numeric column - each None where it
    /// cannot be read. Each column only if it is there (B5); only the digest and the count leave, and neither guard is
    /// on at the defaults.
    pub fn task_facts(&self, thread_id: &str, fingerprint: bool, tokens: bool) -> Result<Map> {
        let mut found = obj(vec![("print", Value::Null), ("tokens", Value::Null)]);
        if !is_uuid(thread_id) || !(fingerprint || tokens) {
            return Ok(found);
        }
        let read = self.with_db("state", |connection| {
            let columns = sql::column_types(connection, "threads")?;
            let has = |name: &str| columns.iter().any(|(each, _)| each == name);
            let mut wanted: Vec<&str> = ["cwd", "model", "approval_mode"]
                .into_iter()
                .filter(|name| fingerprint && has(name))
                .collect();
            let counted = tokens
                && columns
                    .iter()
                    .find(|(each, _)| each == "tokens_used")
                    .is_some_and(|(_, declared)| declared.contains("INT"));
            if counted {
                wanted.push("tokens_used");
            }
            if wanted.is_empty() {
                return Ok(None);
            }
            Ok(sql::first(
                connection,
                &format!("SELECT {} FROM threads WHERE id=?", wanted.join(",")),
                &[Param::Text(thread_id)],
            )?
            .map(|row| (row, counted)))
        });
        let (row, counted) = match read {
            Err(Error::Source(_) | Error::Sqlite | Error::Os | Error::Python("ValueError")) => {
                return Ok(found);
            }
            Err(other) => return Err(other),
            Ok(None) => return Ok(found),
            Ok(Some(pair)) => pair,
        };
        if counted {
            found.insert(
                Str::from("tokens"),
                guards::tokens(&row.value("tokens_used")).map_or(Value::Null, Value::from),
            );
        }
        if fingerprint {
            let text = |name: &str| match row.get(name) {
                Cell::Text(each) if row.has(name) => Value::from(each.as_str()),
                _ => Value::Null,
            };
            let (cwd, model, approval) = (text("cwd"), text("model"), text("approval_mode"));
            let head = match &cwd {
                Value::Str(folder) if !folder.is_empty() => {
                    workspace::head_digest(folder.as_str().unwrap_or(""))
                }
                _ => workspace::UNREADABLE.to_owned(),
            };
            let print = guards::fingerprint(&model, &approval, &Value::from(head.as_str()))?;
            found.insert(Str::from("print"), Value::from(print));
        }
        Ok(found)
    }

    /// `progress(thread_id, after_ordinal)`: content-free evidence that something happened after a given turn:
    /// whether a later turn exists, one completed, and a completed one recorded a final agent item - lifecycle
    /// columns only.
    pub fn progress(&self, thread_id: &str, after_ordinal: &Value) -> Result<Map> {
        let empty = || {
            obj(vec![
                ("later_turn", Value::Bool(false)),
                ("later_completed", Value::Bool(false)),
                ("assistant_reply", Value::Bool(false)),
            ])
        };
        if !is_uuid(thread_id) || !pyval::is_int(after_ordinal) {
            return Ok(empty());
        }
        let outcome = (|| -> Result<(Vec<Row>, bool)> {
            let chain = self.ids(thread_id)?;
            let (condition, parameters) = Self::after(&chain, after_ordinal, "")?;
            self.with_db("history", |connection| {
                let columns = sql::columns(connection, "thread_turns")?;
                let last = columns.iter().any(|each| each == "final_agent_item_id");
                let rows = sql::query(
                    connection,
                    &format!(
                        "SELECT status, completed_at{} FROM thread_turns WHERE {condition}",
                        if last { ", final_agent_item_id" } else { "" }
                    ),
                    &parameters,
                )?;
                Ok((rows, last))
            })
        })();
        let (rows, last) = match outcome {
            Err(Error::Source(_) | Error::Sqlite | Error::Os | Error::Python("ValueError")) => {
                return Ok(empty());
            }
            Err(other) => return Err(other),
            Ok(pair) => pair,
        };
        let mut result = empty();
        result.insert(Str::from("later_turn"), Value::Bool(!rows.is_empty()));
        for row in &rows {
            if row.get("status").text() == Some("completed")
                && *row.get("completed_at") != Cell::Null
            {
                result.insert(Str::from("later_completed"), Value::Bool(true));
                if last && row.get("final_agent_item_id").truthy() {
                    result.insert(Str::from("assistant_reply"), Value::Bool(true));
                }
            }
        }
        Ok(result)
    }

    /// `reset_hint(thread_id, turn_id)`: when the usage limit a turn failed on says it resets, from the file its turn
    /// was written to.
    pub fn reset_hint(&self, thread_id: &str, turn_id: &str) -> Result<Map> {
        if !is_uuid(thread_id) || !is_uuid(turn_id) {
            return Ok(unknown_reset());
        }
        let (path, chain, _) = self.chain(thread_id, false, None)?;
        let Some(path) = path else {
            return Ok(unknown_reset());
        };
        let row = self.with_db("history", |connection| {
            let mut parameters = texts(&chain);
            parameters.push(Param::Text(turn_id));
            Ok(sql::first(
                connection,
                &format!(
                    "SELECT thread_id,turn_id,status,started_at,completed_at,\
                     rollout_ordinal,error_json,rollout_end_byte_offset \
                     FROM thread_turns WHERE {} AND turn_id=?",
                    of(&chain, "thread_id")
                ),
                &parameters,
            )?)
        })?;
        let eligible = match &row {
            Some(row) => {
                let mut dict = row.dict();
                dict.insert(Str::from("thread_id"), Value::from(thread_id));
                detect(&Value::Object(dict))?
            }
            None => None,
        };
        // A reset timestamp only means anything for a usage limit - read from the file its turn was written to.
        let last = chain.last().cloned().unwrap_or_default();
        let files: Vec<(String, String)> = if chain.len() > 1 {
            rollout::earlier(self.os(), &self.home, thread_id, &last)
        } else {
            Vec::new()
        };
        let held = match &row {
            Some(row) if row.get("thread_id").text() == Some(last.as_str()) => Some(path.clone()),
            Some(row) => row
                .get("thread_id")
                .text()
                .and_then(|id| files.iter().rev().find(|(other, _)| other == id))
                .map(|(_, file)| file.clone()),
            None => None,
        };
        let usage = eligible.as_ref().is_some_and(|found| {
            pyval::is(
                found.get("category").unwrap_or(&Value::Null),
                failures::USAGE_LIMIT,
            )
        });
        let (Some(row), Some(held), true) = (&row, held, usage) else {
            return Ok(unknown_reset());
        };
        Ok(rollout::reset_scan(
            &held,
            &row.value("rollout_end_byte_offset"),
            turn_id,
            &row.value("completed_at"),
        )?)
    }

    // ------------------------------------------------------------------------------------------------------
    // Following our own continuation.
    //
    // Every query below that returns stored content is bounded by `instr(...,marker)>0`, so the only message text
    // that can ever leave SQL is our own continuation. Every query over anyone else's rows returns counts, booleans
    // and ids - never content.
    //
    // `marker` is what proves a continuation is ours (`ids::is_delivery_proof`): the marker at the end of its words,
    // or - for one the advanced edition sent with none (P15) - the client id it was queued under, which Codex keeps
    // on the message. Either is looked for the same way, so the bound is the same: a row that holds our proof.
    // ------------------------------------------------------------------------------------------------------
    fn identity_of(thread_id: &str, marker: &str) -> Result<()> {
        if !is_uuid(thread_id) || !proof(marker) || marker == thread_id {
            return Err(Error::source("Invalid delivery identity"));
        }
        Ok(())
    }

    /// `_following(thread_id, marker)`: `identity_of`, then every id the conversation's turns are recorded under,
    /// none the marker.
    fn following(&self, thread_id: &str, marker: &str) -> Result<Vec<String>> {
        Self::identity_of(thread_id, marker)?;
        let chain = self.ids(thread_id)?;
        if chain.iter().any(|each| each == marker) {
            return Err(Error::source("Invalid delivery identity"));
        }
        Ok(chain)
    }

    /// `marker_rows(thread_id, marker)`: every history row that holds our marker, with the facts about its own turn:
    /// the turn a continuation started is that row's, never "the latest turn" - a person may already have started
    /// another.
    pub fn marker_rows(&self, thread_id: &str, marker: &str) -> Result<Vec<Map>> {
        let chain = self.following(thread_id, marker)?;
        let rows = self.with_db("history", |connection| {
            let mut parameters = texts(&chain);
            parameters.push(Param::Text(marker));
            Ok(sql::query(
                connection,
                &format!(
                    "SELECT i.thread_id, i.turn_id, i.item_id, i.item_json, t.rollout_ordinal, t.status, \
                     t.first_user_item_id IS NULL AS first_unset, \
                     coalesce(t.first_user_item_id = i.item_id, 0) AS starts_turn \
                     FROM thread_items i LEFT JOIN thread_turns t \
                     ON t.thread_id=i.thread_id AND t.turn_id=i.turn_id \
                     WHERE {} AND i.item_type='userMessage' AND instr(i.item_json,?)>0",
                    of(&chain, "i.thread_id")
                ),
                &parameters,
            )?)
        })?;
        let mut found = Vec::new();
        for row in &rows {
            let index = row
                .get("thread_id")
                .text()
                .and_then(|id| chain.iter().position(|each| each == id))
                .ok_or(Error::Python("ValueError"))?;
            let placed = rollout::placed(&row.dict(), &Value::from(thread_id), index);
            if let Some(one) = marker_row(&placed, marker)? {
                found.push(one);
            }
        }
        Ok(found)
    }

    /// `queued_rows(thread_id, marker)`: our own queued items: ids and client ids only.
    pub fn queued_rows(&self, thread_id: &str, marker: &str) -> Result<Vec<Map>> {
        Self::identity_of(thread_id, marker)?;
        self.with_db("queue", |connection| {
            let rows = sql::query(
                connection,
                "SELECT id,payload_json FROM queued_items WHERE thread_id=? AND instr(payload_json,?)>0",
                &[Param::Text(thread_id), Param::Text(marker)],
            )?;
            let mut found = Vec::new();
            for row in &rows {
                let payload = json_of(&row.value("payload_json")).unwrap_or(Value::Null);
                let queue_id = row.value("id");
                if ids::is_uuid(&queue_id) && queue_has_marker(&payload, marker) {
                    let client = match &payload {
                        Value::Object(map) => match map.get("UserInput") {
                            Some(Value::Object(input)) => input.get("client_id").cloned().unwrap_or(Value::Null),
                            _ => Value::Null,
                        },
                        _ => Value::Null,
                    };
                    found.push(obj(vec![
                        ("id", queue_id),
                        ("client_id", if ids::is_client_id(&client) { client } else { Value::Null }),
                    ]));
                }
            }
            Ok(found)
        })
    }

    /// `queue_row(thread_id, queue_id, marker)`: whether the queued item with this exact id still exists, and still
    /// is ours: one with our id but not our marker is one somebody edited in Codex, and only that fact is returned.
    pub fn queue_row(&self, thread_id: &str, queue_id: &str, marker: &str) -> Result<Map> {
        Self::identity_of(thread_id, marker)?;
        if !is_uuid(queue_id) {
            return Err(Error::source("Invalid queue identity"));
        }
        let row = self.with_db("queue", |connection| {
            Ok(sql::first(
                connection,
                "SELECT instr(payload_json,?)>0 AS has_marker FROM queued_items WHERE thread_id=? AND id=?",
                &[Param::Text(marker), Param::Text(thread_id), Param::Text(queue_id)],
            )?)
        })?;
        Ok(obj(vec![
            ("exists", Value::Bool(row.is_some())),
            (
                "has_marker",
                Value::Bool(
                    row.as_ref()
                        .is_some_and(|each| each.get("has_marker").truthy()),
                ),
            ),
        ]))
    }

    /// `foreign_queued(thread_id, marker)`: how many items on this thread's queue are not ours. A number only.
    pub fn foreign_queued(&self, thread_id: &str, marker: &str) -> Result<i64> {
        Self::identity_of(thread_id, marker)?;
        self.with_db("queue", |connection| {
            let row = sql::first(
                connection,
                "SELECT count(*) FROM queued_items WHERE thread_id=? AND instr(payload_json,?)=0",
                &[Param::Text(thread_id), Param::Text(marker)],
            )?;
            Ok(match row.as_ref().map(|each| each.at(0)) {
                Some(Cell::Int(count)) => *count,
                _ => 0,
            })
        })
    }

    /// `later_turns(thread_id, after_ordinal, marker)`: turns after the failed one, each ours, someone else's, or not
    /// yet knowable - booleans and ids only. One whose first user message is not projected yet is "undetermined" while
    /// it runs (it cannot have started our item); finished without any user message (a hook blocked it, or Codex
    /// started it), someone else's.
    pub fn later_turns(
        &self,
        thread_id: &str,
        after_ordinal: &Value,
        marker: &str,
    ) -> Result<Vec<Map>> {
        let chain = self.following(thread_id, marker)?;
        if !pyval::is_int(after_ordinal) {
            return Err(Error::source("Invalid ordinal"));
        }
        let (condition, values) = Self::after(&chain, after_ordinal, "t.")?;
        let rows = self.with_db("history", |connection| {
            let mut parameters = vec![Param::Text(marker)];
            parameters.extend(values.iter().copied());
            Ok(sql::query(
                connection,
                &format!(
                    "SELECT t.thread_id, t.turn_id, t.status, t.rollout_ordinal, \
                     t.first_user_item_id IS NOT NULL AS has_first, \
                     EXISTS(SELECT 1 FROM thread_items i WHERE i.thread_id=t.thread_id \
                     AND i.item_id=t.first_user_item_id AND i.item_type='userMessage' \
                     AND instr(i.item_json,?)>0) AS first_is_ours \
                     FROM thread_turns t WHERE {condition}"
                ),
                &parameters,
            )?)
        })?;
        let mut placed: Vec<Map> = Vec::new();
        for row in &rows {
            let index = row
                .get("thread_id")
                .text()
                .and_then(|id| chain.iter().position(|each| each == id))
                .ok_or(Error::Python("ValueError"))?;
            placed.push(rollout::placed(&row.dict(), &Value::from(thread_id), index));
        }
        // `sorted(placed, key=rollout_ordinal)`: numbers sort, a list holding any other pair of values does not.
        let mut failure: Option<&'static str> = None;
        placed.sort_by(|a, b| {
            let (x, y) = (
                a.get("rollout_ordinal").unwrap_or(&Value::Null),
                b.get("rollout_ordinal").unwrap_or(&Value::Null),
            );
            match pyval::order(x, y) {
                Ok(Some(order)) => order,
                Ok(None) => std::cmp::Ordering::Equal,
                Err(class) => {
                    failure = Some(class);
                    std::cmp::Ordering::Equal
                }
            }
        });
        if let Some(class) = failure {
            return Err(Error::Python(class));
        }
        placed.iter().map(|row| Ok(later_turn(row)?)).collect()
    }

    /// `turn_observation(thread_id, turn_id, marker)`: what happened in one exact turn, content-free: progress is an
    /// assistant message, command, file change or tool call in *that* turn, never a later one; a user message in it
    /// that is not ours is a person.
    pub fn turn_observation(&self, thread_id: &str, turn_id: &str, marker: &str) -> Result<Map> {
        let chain = self.following(thread_id, marker)?;
        if !is_uuid(turn_id) {
            return Err(Error::source("Invalid turn identity"));
        }
        self.with_db("history", |connection| {
            let mut parameters = texts(&chain);
            parameters.push(Param::Text(turn_id));
            let turn = sql::first(
                connection,
                &format!(
                    "SELECT thread_id, status, completed_at, rollout_ordinal FROM thread_turns WHERE {} AND turn_id=?",
                    of(&chain, "thread_id")
                ),
                &parameters,
            )?;
            let Some(turn) = turn else {
                return Ok(obj(vec![("found", Value::Bool(false))]));
            };
            let turns = turn.get("thread_id").text().ok_or(Error::Python("ValueError"))?.to_owned();
            let index = chain
                .iter()
                .position(|each| *each == turns)
                .ok_or(Error::Python("ValueError"))?;
            let turn = rollout::placed(&turn.dict(), &Value::from(thread_id), index);
            let rows = sql::query(
                connection,
                "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? GROUP BY item_type",
                &[Param::Text(&turns), Param::Text(turn_id)],
            )?;
            // `{row[0]: row[1] ... if isinstance(row[0], str)}`: the last count of a kind wins.
            let mut counts: Vec<(String, i64)> = Vec::new();
            for row in &rows {
                if let Cell::Text(kind) = row.at(0) {
                    let count = match row.at(1) {
                        Cell::Int(each) => *each,
                        _ => 0,
                    };
                    match counts.iter_mut().find(|(each, _)| each == kind) {
                        Some(held) => held.1 = count,
                        None => counts.push((kind.clone(), count)),
                    }
                }
            }
            let progress_marks = vec!["?"; PROGRESS_ITEM_TYPES.len()].join(",");
            let mut parameters = vec![
                Param::Text(&turns),
                Param::Text(turn_id),
                Param::Text(car_machine::vocab_gen::domain_ids::MARKER_PREFIX),
                Param::Text(&turns),
                Param::Text(turn_id),
            ];
            parameters.extend(PROGRESS_ITEM_TYPES.iter().map(|each| Param::Text(each)));
            parameters.extend([
                Param::Text(&turns),
                Param::Text(turn_id),
                Param::Text(marker),
                Param::Text(&turns),
                Param::Text(turn_id),
                Param::Text(marker),
            ]);
            let counted = sql::first(
                connection,
                &format!(
                    "SELECT count(*), EXISTS(SELECT 1 FROM thread_items WHERE thread_id=? AND turn_id=? AND item_type='userMessage' \
                     AND instr(item_json,?)>0), EXISTS(SELECT 1 FROM thread_items p WHERE thread_id=? AND turn_id=? AND item_type \
                     IN ({progress_marks}) AND NOT EXISTS(SELECT 1 FROM thread_items WHERE thread_id=? AND turn_id=? AND item_type='userMessage' \
                     AND instr(item_json,?)=0 AND coalesce(rollout_ordinal<=p.rollout_ordinal,1))) FROM thread_items WHERE \
                     thread_id=? AND turn_id=? AND item_type='userMessage' AND instr(item_json,?)=0"
                ),
                &parameters,
            )?;
            let counted = counted.ok_or(Error::Python("TypeError"))?;
            let (foreign, branded, worked) = (
                counted.at(0).clone(),
                counted.at(1).clone(),
                counted.at(2).clone(),
            );
            let ordinal = turn.get("rollout_ordinal").cloned().unwrap_or(Value::Null);
            let (after, values) = if pyval::is_int(&ordinal) {
                Self::after(&chain, &ordinal, "")?
            } else {
                ("0".to_owned(), Vec::new())
            };
            let mut twice = values.clone();
            twice.extend(values.iter().copied());
            let later = sql::first(
                connection,
                &format!(
                    "SELECT EXISTS(SELECT 1 FROM thread_turns WHERE {after} AND status IN ('completed','failed','interrupted')), \
                     EXISTS(SELECT 1 FROM thread_turns WHERE {after})"
                ),
                &twice,
            )?
            .ok_or(Error::Python("TypeError"))?;
            let (later_terminal, later_started) = (later.at(0).truthy(), later.at(1).truthy());
            let has = |kind: &str| counts.iter().any(|(each, count)| each == kind && *count > 0);
            let others: BTreeSet<&str> = counts.iter().map(|(each, _)| each.as_str()).collect();
            let foreign_count = match &foreign {
                Cell::Int(each) => *each,
                _ => 0,
            };
            let completed = turn.get("completed_at").cloned().unwrap_or(Value::Null);
            Ok(obj(vec![
                ("found", Value::Bool(true)),
                ("ordinal", ordinal.clone()),
                ("status", row_status(turn.get("status").unwrap_or(&Value::Null))?.map_or(Value::Null, Value::from)),
                ("completed_at", if epoch(&completed)? { completed } else { Value::Null }),
                ("progress", Value::Bool(PROGRESS_ITEM_TYPES.iter().any(|kind| has(kind)))),
                ("foreign_user_messages", Value::from(foreign_count)),
                ("branded_user_messages", Value::from(i64::from(branded.truthy()))),
                (
                    "progress_before_foreign",
                    Value::Bool(foreign_count != 0 && worked.truthy()),
                ),
                ("later_terminal", Value::Bool(later_terminal)),
                ("later_started", Value::Bool(later_started)),
                (
                    "compaction_only",
                    Value::Bool(
                        counts.iter().any(|(each, _)| each == "contextCompaction")
                            && others.iter().all(|each| matches!(*each, "contextCompaction" | "reasoning")),
                    ),
                ),
            ]))
        })
    }

    /// `turn_progress(thread_id, turn_id)`: whether one turn produced anything: True, False, or None when unreadable.
    pub fn turn_progress(&self, thread_id: &str, turn_id: &str) -> Result<Option<bool>> {
        if !is_uuid(thread_id) || !is_uuid(turn_id) {
            return Ok(None);
        }
        let outcome = (|| -> Result<bool> {
            let chain = self.ids(thread_id)?;
            self.with_db("history", |connection| {
                let mut parameters = texts(&chain);
                parameters.push(Param::Text(turn_id));
                parameters.extend(PROGRESS_ITEM_TYPES.iter().map(|each| Param::Text(each)));
                let row = sql::first(
                    connection,
                    &format!(
                        "SELECT EXISTS(SELECT 1 FROM thread_items WHERE {} AND turn_id=? AND item_type IN ({}))",
                        of(&chain, "thread_id"),
                        vec!["?"; PROGRESS_ITEM_TYPES.len()].join(",")
                    ),
                    &parameters,
                )?;
                Ok(row.is_some_and(|each| each.at(0).truthy()))
            })
        })();
        match outcome {
            Err(Error::Source(_) | Error::Sqlite | Error::Os | Error::Python("ValueError")) => {
                Ok(None)
            }
            Err(other) => Err(other),
            Ok(found) => Ok(Some(found)),
        }
    }

    /// `turn_item_counts(thread_id, turn_id)`: how many items of each kind one turn left, counts only (B7), or None:
    /// v0.6.14, for the edition's plug's samples of failures it took up. Core itself never asks it.
    pub fn turn_item_counts(&self, thread_id: &str, turn_id: &str) -> Result<Option<Map>> {
        if !is_uuid(thread_id) || !is_uuid(turn_id) {
            return Ok(None);
        }
        // `{kind: 0 for kind in sorted(PROGRESS_ITEM_TYPES) + ["userMessage", "other"]}`: the progress kinds sorted,
        // then the two - in that order, not sorted together.
        let mut ordered: Vec<(String, i64)> = {
            let mut kinds: Vec<&str> = PROGRESS_ITEM_TYPES.to_vec();
            kinds.sort_unstable();
            kinds.into_iter().map(|each| (each.to_owned(), 0)).collect()
        };
        ordered.push(("userMessage".to_owned(), 0));
        ordered.push(("other".to_owned(), 0));
        let outcome = (|| -> Result<Vec<Row>> {
            let chain = self.ids(thread_id)?;
            self.with_db("history", |connection| {
                let mut parameters = texts(&chain);
                parameters.push(Param::Text(turn_id));
                Ok(sql::query(
                    connection,
                    &format!(
                        "SELECT item_type, count(*) FROM thread_items WHERE {} AND turn_id=? GROUP BY item_type",
                        of(&chain, "thread_id")
                    ),
                    &parameters,
                )?)
            })
        })();
        let rows = match outcome {
            Err(Error::Source(_) | Error::Sqlite | Error::Os | Error::Python("ValueError")) => {
                return Ok(None);
            }
            Err(other) => return Err(other),
            Ok(rows) => rows,
        };
        for row in &rows {
            let count = match row.at(1) {
                Cell::Int(each) => *each,
                _ => 0,
            };
            let name = match row.at(0) {
                Cell::Text(kind) if ordered.iter().any(|(each, _)| each == kind) => kind.clone(),
                _ => "other".to_owned(),
            };
            if let Some(held) = ordered.iter_mut().find(|(each, _)| *each == name) {
                held.1 += count;
            }
        }
        let mut found = Map::new();
        for (kind, count) in ordered {
            found.insert(Str::from(kind.as_str()), Value::from(count));
        }
        Ok(Some(found))
    }

    /// `turn_markers(thread_id, turn_id, markers)`: which of these markers - or client ids a marker-free
    /// continuation was queued under - appear in a user message of one turn. Booleans only.
    pub fn turn_markers(
        &self,
        thread_id: &str,
        turn_id: &str,
        markers: &[String],
    ) -> Result<Vec<String>> {
        if !is_uuid(thread_id) || !is_uuid(turn_id) {
            return Err(Error::source("Invalid turn identity"));
        }
        let chain = self.ids(thread_id)?;
        let wanted: Vec<&String> = markers
            .iter()
            .filter(|marker| proof(marker) && !chain.contains(marker) && marker.as_str() != turn_id)
            .collect();
        let mut found = Vec::new();
        self.with_db("history", |connection| {
            for marker in &wanted {
                let mut parameters = texts(&chain);
                parameters.push(Param::Text(turn_id));
                parameters.push(Param::Text(marker));
                let row = sql::first(
                    connection,
                    &format!(
                        "SELECT EXISTS(SELECT 1 FROM thread_items WHERE {} AND turn_id=? \
                         AND item_type='userMessage' AND instr(item_json,?)>0)",
                        of(&chain, "thread_id")
                    ),
                    &parameters,
                )?;
                if row.is_some_and(|each| each.at(0).truthy()) {
                    found.push((*marker).clone());
                }
            }
            Ok(())
        })?;
        Ok(found)
    }

    /// `marker_presence(thread_id, marker)`: how many copies of our marker exist anywhere on this thread, counts
    /// only: checked just before a send, a copy already there means another installation derived the same marker and
    /// got there first.
    pub fn marker_presence(&self, thread_id: &str, marker: &str) -> Result<Map> {
        let chain = self.following(thread_id, marker)?;
        let history = self.with_db("history", |connection| {
            let mut parameters = texts(&chain);
            parameters.push(Param::Text(marker));
            let row = sql::first(
                connection,
                &format!(
                    "SELECT count(*) FROM thread_items WHERE {} AND instr(item_json,?)>0",
                    of(&chain, "thread_id")
                ),
                &parameters,
            )?;
            Ok(row.map_or(Cell::Null, |each| each.at(0).clone()))
        })?;
        let queue = self.with_db("queue", |connection| {
            let row = sql::first(
                connection,
                "SELECT count(*) FROM queued_items WHERE thread_id=? AND instr(payload_json,?)>0",
                &[Param::Text(thread_id), Param::Text(marker)],
            )?;
            Ok(row.map_or(Cell::Null, |each| each.at(0).clone()))
        })?;
        Ok(obj(vec![
            ("history", history.value()),
            ("queue", queue.value()),
        ]))
    }

    /// `projection(thread_id)`: whether Codex's history tables have caught up with the conversation's file: the
    /// file's size from one stat call against the byte offset the projection reached - content-free. Behind, nothing
    /// may be decided from the tables; `fresh` is None when it cannot be told.
    pub fn projection(&self, thread_id: &str) -> Result<Map> {
        let answer = |table: Value, fresh: Value| obj(vec![("table", table), ("fresh", fresh)]);
        if !is_uuid(thread_id) {
            return Ok(answer(Value::Null, Value::Null));
        }
        let outcome = (|| -> Result<(Option<Row>, bool, Option<String>)> {
            // The current file's projection: a split's newest id.
            let turns = self.ids(thread_id)?.last().cloned().unwrap_or_default();
            let (row, table) = self.with_db("history", |connection| {
                let table = sql::first(
                    connection,
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='thread_history_projection_state'",
                    &[],
                )?;
                if table.is_none() {
                    return Ok((None, false));
                }
                Ok((
                    sql::first(
                        connection,
                        "SELECT next_rollout_byte_offset FROM thread_history_projection_state WHERE thread_id=?",
                        &[Param::Text(&turns)],
                    )?,
                    true,
                ))
            })?;
            if !table {
                return Ok((None, false, None));
            }
            Ok((row, true, self.rollout_path(thread_id)?))
        })();
        let (row, table, path) = match outcome {
            Err(Error::Source(_) | Error::Sqlite | Error::Os | Error::Python("ValueError")) => {
                return Ok(answer(Value::Null, Value::Null));
            }
            Err(other) => return Err(other),
            Ok(found) => found,
        };
        if !table {
            return Ok(answer(Value::Bool(false), Value::Null));
        }
        let offset = row.as_ref().and_then(|each| match each.at(0) {
            Cell::Int(value) => Some(*value),
            _ => None,
        });
        let (Some(offset), Some(path)) = (offset, path) else {
            return Ok(answer(Value::Bool(true), Value::Null));
        };
        let Ok(facts) = std::fs::metadata(&path) else {
            return Ok(answer(Value::Bool(true), Value::Null));
        };
        Ok(answer(
            Value::Bool(true),
            Value::Bool(i128::from(facts.len()) == i128::from(offset)),
        ))
    }

    /// `activity(threads, now, recent, booted)`: whether anything may still run in this Codex home, for the power
    /// action (v0.6.12): sizes, times and counts, never content (B7). First Codex's history has caught up (A18): every
    /// conversation whose file was written in the last `recent` seconds, and each of `threads` (the batch's own) at
    /// any age, projected exactly - its file's size, one stat call, nothing opened, is the projection's offset, with no
    /// grace; a missing row is behind too. `history` is True when all are current, False when one is behind, None
    /// when it cannot be told. Then the latest turns in progress and the items queued since Windows started
    /// (`booted`, the heartbeat's; v0.6.20 final: one from before it is gone, by created_at_ms where Codex keeps it) -
    /// None if unread or with no boot time.
    pub fn activity(
        &self,
        threads: &[String],
        now: &Value,
        recent: &Value,
        booted: &Value,
    ) -> Result<Map> {
        let result = |history: Value, running: Value, queued: Value| {
            obj(vec![
                ("history", history),
                ("running", running),
                ("queued", queued),
            ])
        };
        let unknown = || result(Value::Null, Value::Null, Value::Null);
        let recent_ok = pyval::is_number(recent) && pyval::less_or_equal(&Value::from(0), recent)?;
        if !epoch(now)? || !recent_ok {
            return Ok(unknown());
        }
        let wanted: BTreeSet<&str> = threads
            .iter()
            .map(String::as_str)
            .filter(|each| is_uuid(each))
            .collect();
        type Read = (Vec<(Cell, Cell)>, Vec<Row>);
        let read = (|| -> Result<Read> {
            let offsets = self.with_db("history", |connection| {
                let table = sql::first(
                    connection,
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='thread_history_projection_state'",
                    &[],
                )?;
                if table.is_none() {
                    return Ok(None);
                }
                Ok(Some(
                    sql::query(
                        connection,
                        "SELECT thread_id,next_rollout_byte_offset FROM thread_history_projection_state",
                        &[],
                    )?
                    .iter()
                    .map(|row| (row.at(0).clone(), row.at(1).clone()))
                    .collect::<Vec<_>>(),
                ))
            })?;
            let Some(offsets) = offsets else {
                return Err(Error::Python("NoTable"));
            };
            let conversations = self.with_db("state", |connection| {
                Ok(sql::query(
                    connection,
                    "SELECT id,rollout_path FROM threads",
                    &[],
                )?)
            })?;
            Ok((offsets, conversations))
        })();
        let (offsets, conversations) = match read {
            Err(
                Error::Python("NoTable" | "ValueError")
                | Error::Source(_)
                | Error::Sqlite
                | Error::Os,
            ) => {
                return Ok(unknown());
            }
            Err(other) => return Err(other),
            Ok(found) => found,
        };
        let (now_f, recent_f) = (
            pyval::minus(now, &Value::from(0))?,
            pyval::minus(recent, &Value::from(0))?,
        );
        for row in &conversations {
            let identifier = row.value("id");
            let path = match &identifier {
                Value::Str(id) => match id.as_str() {
                    Some(id) => {
                        rollout::confined(self.os(), &self.home, id, &row.value("rollout_path"))
                    }
                    None => Ok(None),
                },
                _ => Ok(None),
            };
            let path = match path {
                Ok(Some(path)) => path,
                Ok(None) => continue,
                Err(Error::Os | Error::Python("ValueError")) => return Ok(unknown()),
                Err(other) => return Err(other),
            };
            let facts = match std::fs::metadata(&path) {
                Ok(facts) => facts,
                // No file: nothing Codex could still be projecting.
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                Err(_) => return Ok(unknown()),
            };
            let id = row.get("id").text().unwrap_or("");
            let modified = facts
                .modified()
                .ok()
                .and_then(|moment| moment.duration_since(std::time::UNIX_EPOCH).ok())
                .map_or(0.0, |each| {
                    each.as_secs() as f64 + f64::from(each.subsec_nanos()) * 1e-9
                });
            if !wanted.contains(id) && modified < now_f - recent_f {
                continue;
            }
            // Its file projected under B (issue #30).
            let split = rollout::continued_id(id, &name_of(&path));
            let key = match &split {
                Some(other)
                    if offsets
                        .iter()
                        .any(|(held, _)| held.text() == Some(other.as_str())) =>
                {
                    other.as_str()
                }
                _ => id,
            };
            let offset = offsets
                .iter()
                .rev()
                .find(|(held, _)| held.text() == Some(key))
                .map(|(_, value)| value.clone());
            match offset {
                Some(Cell::Int(value)) if i128::from(value) == i128::from(facts.len()) => {}
                _ => return Ok(result(Value::Bool(false), Value::Null, Value::Null)),
            }
        }
        let mut found = result(Value::Bool(true), Value::Null, Value::Null);
        if !epoch(booted)? {
            return Ok(found);
        }
        let mut running = None;
        if let Ok(rows) = self.with_db("history", |connection| {
            Ok(sql::query(
                connection,
                "SELECT t.started_at FROM thread_turns t WHERE t.status='inProgress' \
                 AND NOT EXISTS (SELECT 1 FROM thread_turns n \
                 WHERE n.thread_id=t.thread_id AND n.rollout_ordinal>t.rollout_ordinal)",
                &[],
            )?)
        }) {
            let mut count = 0i64;
            for row in &rows {
                count += i64::from(!states::ended_by_boot(&row.value("started_at"), booted)?);
            }
            running = Some(count);
        }
        found.insert(
            Str::from("running"),
            running.map_or(Value::Null, Value::from),
        );
        let queued = self.with_db("queue", |connection| {
            let kept = sql::columns(connection, "queued_items")?
                .iter()
                .any(|each| each == "created_at_ms");
            let since = if kept {
                let moment =
                    (pyval::minus(booted, &Value::from(0))? - states::BOOT_MARGIN) * 1000.0;
                format!(
                    " WHERE created_at_ms IS NULL OR created_at_ms>={}",
                    moment as i64
                )
            } else {
                String::new()
            };
            let row = sql::first(
                connection,
                &format!("SELECT count(*) FROM queued_items{since}"),
                &[],
            )?;
            Ok(row.map_or(Cell::Null, |each| each.at(0).clone()))
        });
        if let Ok(count) = queued {
            found.insert(Str::from("queued"), count.value());
        }
        Ok(found)
    }
}

fn skips_unknown() -> &'static str {
    car_machine::vocab_gen::domain_skips::UNKNOWN_CONVERSATION
}

fn skips_other_kind() -> &'static str {
    car_machine::vocab_gen::domain_skips::OTHER_KIND
}

fn skips_continued() -> &'static str {
    car_machine::vocab_gen::domain_skips::CONTINUED_ELSEWHERE
}

fn skips_newer() -> &'static str {
    car_machine::vocab_gen::domain_skips::NEWER_TURN
}

fn skips_before() -> &'static str {
    car_machine::vocab_gen::domain_skips::BEFORE_WINDOW
}

fn skips_not_recovered() -> &'static str {
    car_machine::vocab_gen::domain_skips::NOT_RECOVERED
}

/// Whether a kind of Codex's database exists in `DB_KINDS` (the three).
pub fn kinds() -> impl Iterator<Item = &'static str> {
    DB_KINDS.iter().map(|each| each.name)
}
