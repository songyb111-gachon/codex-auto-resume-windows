//! A person's message from the edition's plug, sent marker-free through its channel (v0.6.19, the in-app chat)
//! (`engine/recordchannel.py`; seat S7.2a2).
//!
//! A record of the plug's (P2, [`crate::plugrecords`]) goes through core's own backend, its words ending in its
//! marker, and a channel the plug names for one waits instead - but a person's own MESSAGE for which the plug names a
//! channel (P5) and answers CLIENT_ID at P15: its words go with no marker, under the client id core derives from the
//! record's id, and every look that proves, follows, takes back or settles it is made for that id.

use car_machine::domain::ids;
use car_machine::json::{Map, Value};
use car_machine::pyval::{self, Py};
use car_policy::plug::{Alternative, Answer, RecordMove, RecordPurpose};

use crate::Engine;
use crate::plugrecords::{NOTED_LIMIT, field, later_of, text_field};
use crate::py::with;

/// v0.6.26 (review K3): how long after a watcher's start a record of the plug's gone from Codex's queue, which this
/// watcher never saw there, waits for its marker in Codex's history before it is unproven.
pub const RESTART_GRACE: f64 = 3600.0;

/// Who the one send of a record goes to, as `_marker_free` asks it: handed in flight (no sender), core's backend, or
/// a channel the plug named.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Carrier {
    InFlight,
    Backend,
    Channel,
}

/// `record.get("purpose", RecordPurpose.MESSAGE) == RecordPurpose.MESSAGE`.
fn is_message(record: &Map) -> bool {
    match record.get("purpose") {
        None => true,
        Some(purpose) => pyval::text(purpose) == Some(RecordPurpose::Message.as_str()),
    }
}

impl Engine {
    /// `_marker_free(record, sender)`: whether a person's MESSAGE the plug named a channel for (or handed in flight)
    /// goes marker-free - P15 asked once; a look that raises is no.
    pub(crate) fn marker_free(&self, record: &Map, carrier: Carrier) -> bool {
        if !is_message(record) || carrier == Carrier::Backend {
            return false;
        }
        matches!(
            self.plug.delivery(&Value::Object(record.clone())),
            Answer::Is(Alternative::ClientId)
        )
    }

    /// `_record_carried(record, sender)`: `record` with the client id core derives from its id where it goes
    /// marker-free, else with none.
    pub(crate) fn record_carried(&self, record: Map, carrier: Carrier) -> Py<Map> {
        let client = if self.marker_free(&record, carrier) {
            Value::from(ids::continuation_client_id(text_field(&record, "record_id")?).as_str())
        } else {
            Value::Null
        };
        Ok(with(&record, vec![("client_id", client)]))
    }

    /// `_record_queued(record)`: a record handed in flight, with the queue item Codex said it took at its send where
    /// the plug kept none, and when it was last seen in Codex's queue (B1, K3).
    pub(crate) fn record_queued(&mut self, record: Map) -> Py<Map> {
        let id = text_field(&record, "record_id")?.to_owned();
        let known = match self.flying().get(id.as_str()) {
            Some(Value::Object(known)) => known.clone(),
            _ => Map::new(),
        };
        let mut record = record;
        let absent = |found: Option<&Value>| matches!(found, None | Some(Value::Null));
        if absent(record.get("queue_id")) && !absent(known.get("queue_id")) {
            record = with(&record, vec![("queue_id", known["queue_id"].clone())]);
        }
        let seen_known = known.get("seen_at").is_some_and(pyval::truthy);
        if !absent(record.get("sent_at")) && (!absent(record.get("queue_id")) || seen_known) {
            let seen = if seen_known {
                known["seen_at"].clone()
            } else {
                Value::Float(
                    self.watching_since + RESTART_GRACE
                        - self.options.unknown_reconcile_window_seconds,
                )
            };
            let sent = field(&record, "sent_at")?.clone();
            record = with(&record, vec![("seen_at", later_of(&sent, &seen)?)]);
        }
        Ok(record)
    }

    /// `_record_client(record)`: the client id `record` goes under with no marker - the one core derives from its id.
    pub(crate) fn record_client(record: &Map) -> Py<Option<String>> {
        let Some(client) = record
            .get("client_id")
            .filter(|found| !matches!(found, Value::Null))
        else {
            return Ok(None);
        };
        if !is_message(record) {
            return Ok(None);
        }
        let derived = ids::continuation_client_id(text_field(record, "record_id")?);
        Ok((pyval::text(client) == Some(derived.as_str())).then_some(derived))
    }

    /// `_record_proof(record)`: its derived client id marker-free, else its marker.
    pub(crate) fn record_proof(record: &Map) -> Py<String> {
        match Engine::record_client(record)? {
            Some(client) => Ok(client),
            None => Ok(text_field(record, "marker")?.to_owned()),
        }
    }

    /// `_record_words(record)`: the words alone marker-free, else the words, a blank line and the marker.
    pub(crate) fn record_words(record: &Map) -> Py<String> {
        let words = text_field(record, "words")?;
        if Engine::record_client(record)?.is_some() {
            return Ok(words.to_owned());
        }
        Ok(format!("{words}\n\n{}", text_field(record, "marker")?))
    }

    /// `_take_back(record)`: a record still in Codex's queue a person cancelled - or any while recovery is paused (but
    /// one marked `pause_keeps`) or its conversation off - taken back out of the queue: WITHDRAWN once Codex deleted
    /// it and its marker is nowhere in the history, WITHDRAW_REFUSED where Codex would not. True where asked.
    pub(crate) fn take_back(&mut self, record: &Map) -> Py<bool> {
        let thread = text_field(record, "thread_id")?.to_owned();
        let settings = self.store.settings()?;
        let enabled = pyval::truthy(settings.get("enabled").unwrap_or(&Value::Null));
        let keeps = record.get("pause_keeps").is_some_and(pyval::truthy);
        let paused = (!enabled || self.managed.disable_auto_resume) && !keeps;
        let asked = pyval::truthy(field(record, "withdraw")?)
            || paused
            || !self.store.thread_enabled(&thread)?;
        if !asked {
            return Ok(false);
        }
        let id = text_field(record, "record_id")?.to_owned();
        if self.back_refused.contains(&id) {
            return Ok(false); // asked once and refused: watched as it is, never asked every tick
        }
        let queue_id = match field(record, "queue_id")? {
            Value::Str(queue) => queue.as_str().unwrap_or_default().to_owned(),
            _ => return Err("TypeError"),
        };
        let deleted = self.backend.delete_queue(&thread, &queue_id)?;
        let gone = matches!(deleted, Value::Bool(true))
            && self
                .source
                .marker_rows(&thread, &Engine::record_proof(record)?)?
                .is_empty();
        if gone {
            let reason = if paused { "paused" } else { "user_cancelled" };
            self.record_told(record, RecordMove::Withdrawn, Some(("consent", reason)))?;
            self.log(Some(&thread), "plug_record_withdrawn", Value::Null);
        } else {
            if self.back_refused.len() >= NOTED_LIMIT {
                self.back_refused.clear();
            }
            self.back_refused.insert(id);
            self.record_told(
                record,
                RecordMove::WithdrawRefused,
                Some(("consent", "withdraw_unconfirmed")),
            )?;
            self.log(Some(&thread), "plug_record_withdraw_refused", Value::Null);
        }
        Ok(true)
    }
}
