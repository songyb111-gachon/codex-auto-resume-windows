//! A record made later, held for a person and let go, and a person's usage check (store/schedule.py).

use std::path::PathBuf;

use car_machine::json::{Options, Value, to_string};
use rusqlite::Connection;

use crate::actions::{Answer, not_waiting};
use crate::errors::Result;
use crate::journal::{Event, event};
use crate::machine::vocab::{TERMINAL, WAITING};
use crate::machine::{has, ids, own_postponement};
use crate::seam::postponement_problem;
use crate::session::{Store, is_symlink};
use crate::validate::{now as check_now, timestamp, uuid_text};
use crate::value::{Row, execute, get, number, or_zero, string, text_of, truthy};

/// The folder beside the state a person's usage-check request is written in.
pub const USAGE_CHECKS: &str = "usage-checks";
pub const USAGE_READ_AVAILABLE: &str = "usage_available";
pub const USAGE_READ_LIMITED: &str = "usage_unavailable";
pub const USAGE_READ_UNKNOWN: &str = "usage_unknown";
pub const USAGE_READS: &[&str] = &[USAGE_READ_AVAILABLE, USAGE_READ_LIMITED, USAGE_READ_UNKNOWN];
/// Why a request was not served, as the journal keeps it (its value, an index here).
pub const NOT_CHECKED: &[&str] = &[
    "paused",
    "conversation_off",
    "observe_only",
    "quiet_hours",
    "offline",
    "busy",
    "held",
];
pub const USAGE_BY_RETRY: &str = "retry_now";
pub const USAGE_BY_RESCAN: &str = "rescan";
pub const USAGE_RESCAN_FLAG: i64 = 4;
pub const EARLY_CHECK: &str = "early";
pub const EARLY_CHECK_LONGEST: f64 = 300.0;

/// `repr(float(now))`.
fn float_repr(now: f64) -> String {
    to_string(&Value::Float(now), &Options::new()).unwrap_or_else(|_| now.to_string())
}

/// A file's text read as ASCII, or None (an OSError or a UnicodeDecodeError).
fn read_ascii(path: &std::path::Path) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    bytes
        .is_ascii()
        .then(|| String::from_utf8(bytes).expect("ascii"))
}

impl Store {
    /// `_bound(connection, interruption_id, thread_id)`: the row and why it cannot be acted on.
    fn bound(
        &self,
        connection: &Connection,
        interruption_id: &str,
        thread_id: &str,
    ) -> Result<(Option<Row>, Option<&'static str>)> {
        let Some(row) = self.row(connection, interruption_id)? else {
            return Ok((None, Some("unknown_record")));
        };
        let problem = if text_of(&row, "thread_id") != Some(thread_id) {
            Some("thread_mismatch")
        } else if has(TERMINAL, text_of(&row, "state").unwrap_or_default()) {
            Some("finished")
        } else if truthy(get(&row, "cancel_requested")) {
            Some("cancel_requested")
        } else {
            None
        };
        Ok((Some(row), problem))
    }

    /// `postpone(interruption_id, thread_id, until, now, actor="gui")`: only ever later.
    pub fn postpone(
        &self,
        interruption_id: &str,
        thread_id: &str,
        until: &Value,
        now: f64,
        actor: &str,
    ) -> Result<Answer> {
        uuid_text(thread_id, "thread_id")?;
        check_now(now)?;
        self.transaction(|connection| {
            let (row, problem) = self.bound(connection, interruption_id, thread_id)?;
            if let Some(problem) = problem {
                return Ok((false, string(problem)));
            }
            let row = row.expect("bound");
            let state = text_of(&row, "state").unwrap_or_default();
            if !has(WAITING, state) {
                return Ok((false, string(not_waiting(state))));
            }
            if let Some(problem) = postponement_problem(until, now, get(&row, "not_before")) {
                return Ok((false, string(problem)));
            }
            let until = number(until).expect("a time");
            execute(
                connection,
                "UPDATE interruptions SET not_before=? WHERE interruption_id=?",
                &[Value::Float(until), string(interruption_id)],
            )?;
            event(
                connection,
                now,
                "postponed",
                Event {
                    record: Some(&row),
                    from_state: Some(state),
                    to_state: Some(state),
                    actor,
                    value: Some(until),
                    ..Event::default()
                },
            )?;
            Ok((true, Value::Float(until)))
        })
    }

    /// `unpostpone(interruption_id, thread_id, now, actor="gui")`: a person's postponement taken away.
    pub fn unpostpone(
        &self,
        interruption_id: &str,
        thread_id: &str,
        now: f64,
        actor: &str,
    ) -> Result<Answer> {
        uuid_text(thread_id, "thread_id")?;
        check_now(now)?;
        self.transaction(|connection| {
            let (row, problem) = self.bound(connection, interruption_id, thread_id)?;
            if let Some(problem) = problem {
                return Ok((false, string(problem)));
            }
            let row = row.expect("bound");
            let state = text_of(&row, "state").unwrap_or_default();
            if !has(WAITING, state) {
                return Ok((false, string(not_waiting(state))));
            }
            if own_postponement(&row, Some(now))?.is_none() {
                return Ok((false, string("not_postponed")));
            }
            let window = get(&row, "objection_until");
            let left = match number(window) {
                Some(until) if !matches!(window, Value::Null) && until > now => window.clone(),
                _ => Value::Null,
            };
            execute(
                connection,
                "UPDATE interruptions SET not_before=? WHERE interruption_id=?",
                &[left.clone(), string(interruption_id)],
            )?;
            event(
                connection,
                now,
                "unpostponed",
                Event {
                    record: Some(&row),
                    from_state: Some(state),
                    to_state: Some(state),
                    actor,
                    value: number(&left),
                    ..Event::default()
                },
            )?;
            Ok((true, left))
        })
    }

    /// `open_objection_window(interruption_id, until, now)`: whether it was opened.
    pub fn open_objection_window(
        &self,
        interruption_id: &str,
        until: f64,
        now: f64,
    ) -> Result<bool> {
        check_now(now)?;
        timestamp(&Value::Float(until), "until", false)?;
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else { return Ok(false) };
            if !has(WAITING, text_of(&row, "state").unwrap_or_default())
                || !matches!(get(&row, "objection_at"), Value::Null)
                || !matches!(get(&row, "submitted_at"), Value::Null)
                || until <= now
            {
                return Ok(false);
            }
            let later = until.max(or_zero(get(&row, "not_before")));
            execute(
                connection,
                "UPDATE interruptions SET not_before=?, objection_at=?, objection_until=? WHERE interruption_id=?",
                &[Value::Float(later), Value::Float(now), Value::Float(until), string(interruption_id)],
            )?;
            let state = text_of(&row, "state");
            event(connection, now, "postponed", Event {
                record: Some(&row),
                from_state: state,
                to_state: state,
                value: Some(later),
                ..Event::default()
            })?;
            Ok(true)
        })
    }

    /// `release_hold(interruption_id, thread_id, now, actor="gui")`: (released, the record's state).
    pub fn release_hold(
        &self,
        interruption_id: &str,
        thread_id: &str,
        now: f64,
        actor: &str,
    ) -> Result<Answer> {
        uuid_text(thread_id, "thread_id")?;
        check_now(now)?;
        self.transaction(|connection| {
            let (row, problem) = self.bound(connection, interruption_id, thread_id)?;
            if let Some(problem) = problem {
                return Ok((false, string(problem)));
            }
            let row = row.expect("bound");
            if matches!(get(&row, "hold"), Value::Null) {
                return Ok((false, string("not_held")));
            }
            execute(
                connection,
                "UPDATE interruptions SET hold=NULL WHERE interruption_id=?",
                &[string(interruption_id)],
            )?;
            let state = text_of(&row, "state");
            event(
                connection,
                now,
                "hold_released",
                Event {
                    record: Some(&row),
                    from_state: state,
                    to_state: state,
                    actor,
                    ..Event::default()
                },
            )?;
            Ok((true, get(&row, "state").clone()))
        })
    }

    /// `_usage_checks()`: the folder, refused when it is a symbolic link.
    fn usage_checks(&self) -> std::io::Result<PathBuf> {
        let folder = self.state_dir.join(USAGE_CHECKS);
        if is_symlink(&folder) {
            return Err(std::io::Error::other(
                "the usage checks' folder is a symbolic link",
            ));
        }
        Ok(folder)
    }

    /// `ask_usage_check(interruption_id, now, source=USAGE_BY_RETRY)`: whether it could be asked.
    pub fn ask_usage_check(&self, interruption_id: &str, now: f64, source: &str) -> Result<bool> {
        if !ids::is_digest_text(interruption_id) {
            return Ok(false);
        }
        check_now(now)?;
        let written = (|| {
            let folder = self.usage_checks()?;
            match std::fs::create_dir(&folder) {
                Err(error) if error.kind() != std::io::ErrorKind::AlreadyExists => {
                    return Err(error);
                }
                _ => {}
            }
            let said = float_repr(now)
                + if source == USAGE_BY_RESCAN {
                    " rescan"
                } else {
                    ""
                };
            std::fs::write(folder.join(interruption_id), said)
        })();
        Ok(written.is_ok())
    }

    /// `usage_checks_asked(now)`: {id: when it was asked} (0 where the time cannot be read).
    pub fn usage_checks_asked(&self, _now: f64) -> Result<Row> {
        let mut found = Row::new();
        let Ok(folder) = self.usage_checks() else {
            return Ok(found);
        };
        if !folder.is_dir() {
            return Ok(found);
        }
        let Ok(entries) = std::fs::read_dir(&folder) else {
            return Ok(found);
        };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            let path = entry.path();
            if !ids::is_digest_text(&name) || is_symlink(&path) {
                continue;
            }
            let at = read_ascii(&path)
                .and_then(|said| {
                    crate::seam::python::split(&said)
                        .first()
                        .and_then(|word| crate::seam::python::float(word))
                })
                .unwrap_or(0.0);
            found.insert(crate::value::key(&name), Value::Float(at));
        }
        Ok(found)
    }

    /// `usage_not_checked(interruption_id, now, why)`: a request the watcher could not serve, taken and journaled.
    pub fn usage_not_checked(&self, interruption_id: &str, now: f64, why: &str) -> Result<()> {
        check_now(now)?;
        let source = self.usage_check_taken(interruption_id);
        let index = NOT_CHECKED
            .iter()
            .position(|word| *word == why)
            .unwrap_or(NOT_CHECKED.len() - 1);
        self.transaction(|connection| {
            if let Some(row) = self.row(connection, interruption_id)? {
                let state = text_of(&row, "state");
                event(
                    connection,
                    now,
                    "usage_checked",
                    Event {
                        record: Some(&row),
                        from_state: state,
                        to_state: state,
                        flags: 2 | if source.as_deref() == Some(USAGE_BY_RESCAN) {
                            USAGE_RESCAN_FLAG
                        } else {
                            0
                        },
                        value: Some(index as f64),
                        ..Event::default()
                    },
                )?;
            }
            Ok(())
        })
    }

    /// `usage_check_taken(interruption_id)`: the request taken; who asked it, or None.
    pub fn usage_check_taken(&self, interruption_id: &str) -> Option<String> {
        if !ids::is_digest_text(interruption_id) {
            return None;
        }
        let entry = self.usage_checks().ok()?.join(interruption_id);
        if !entry.is_file() || is_symlink(&entry) {
            return None;
        }
        let words: Vec<String> = read_ascii(&entry)
            .map(|said| {
                crate::seam::python::split(&said)
                    .into_iter()
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default();
        match std::fs::remove_file(&entry) {
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => return None,
            _ => {}
        }
        Some(
            if words.get(1).map(String::as_str) == Some(USAGE_BY_RESCAN) {
                USAGE_BY_RESCAN
            } else {
                USAGE_BY_RETRY
            }
            .to_string(),
        )
    }

    /// `ask_early_check(now)`: whether it could be asked.
    pub fn ask_early_check(&self, now: f64) -> Result<bool> {
        check_now(now)?;
        let written = (|| {
            let folder = self.usage_checks()?;
            match std::fs::create_dir(&folder) {
                Err(error) if error.kind() != std::io::ErrorKind::AlreadyExists => {
                    return Err(error);
                }
                _ => {}
            }
            std::fs::write(folder.join(EARLY_CHECK), float_repr(now))
        })();
        Ok(written.is_ok())
    }

    /// `early_check_asked(now)`: whether such a request stands; an older one is dropped.
    pub fn early_check_asked(&self, now: f64) -> bool {
        let Ok(folder) = self.usage_checks() else {
            return false;
        };
        let entry = folder.join(EARLY_CHECK);
        if !entry.is_file() || is_symlink(&entry) {
            return false;
        }
        let Some(at) = read_ascii(&entry).and_then(|said| crate::seam::python::float(&said)) else {
            return false;
        };
        if 0.0 <= now - at && now - at < EARLY_CHECK_LONGEST {
            return true;
        }
        self.early_check_taken();
        false
    }

    /// `early_check_taken()`.
    pub fn early_check_taken(&self) {
        if let Ok(folder) = self.usage_checks() {
            let _ = std::fs::remove_file(folder.join(EARLY_CHECK));
        }
    }

    /// `usage_checked(interruption_id, now, read, source=USAGE_BY_RETRY)`: the record after, or None.
    pub fn usage_checked(
        &self,
        interruption_id: &str,
        now: f64,
        read: &str,
        source: &str,
    ) -> Result<Option<Row>> {
        check_now(now)?;
        let read = if USAGE_READS.contains(&read) {
            read
        } else {
            USAGE_READ_UNKNOWN
        };
        self.transaction(|connection| {
            let Some(row) = self.row(connection, interruption_id)? else {
                return Ok(None);
            };
            if truthy(get(&row, "cancel_requested"))
                || !has(WAITING, text_of(&row, "state").unwrap_or_default())
            {
                return Ok(None);
            }
            let reset = get(&row, "reset_at");
            let lifted = read == USAGE_READ_AVAILABLE
                && number(reset).is_some_and(|reset| reset > now)
                && matches!(get(&row, "submitted_at"), Value::Null);
            if lifted {
                execute(
                    connection,
                    "UPDATE interruptions SET reset_at=?, next_retry_at=? WHERE interruption_id=?",
                    &[
                        Value::Float(now),
                        Value::Float(now),
                        string(interruption_id),
                    ],
                )?;
            }
            let state = text_of(&row, "state");
            event(
                connection,
                now,
                "usage_checked",
                Event {
                    record: Some(&row),
                    from_state: state,
                    to_state: state,
                    reason: if read == USAGE_READ_AVAILABLE {
                        Value::Null
                    } else {
                        string(read)
                    },
                    flags: i64::from(lifted)
                        | if source == USAGE_BY_RESCAN {
                            USAGE_RESCAN_FLAG
                        } else {
                            0
                        },
                    value: number(reset),
                    ..Event::default()
                },
            )?;
            self.row(connection, interruption_id)
        })
    }
}
