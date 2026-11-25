//! Which conversations besides the Codex app's the engine watches (P18, v0.6.16-beta.4; P19, v0.6.20)
//! (`engine/kinds.py`).
//!
//! The standard edition watches the app's own conversations alone (A15), and the NULL plug keeps it so. A kind (or a
//! widening) that leaves ends, cancelled, the waiting records of its conversations (session_kind_off). A watcher that
//! starts does not know what the one before it watched, so at its first ask every kind may have been.

use std::collections::BTreeSet;

use car_machine::json::Value;
use car_machine::pyval::Py;
use car_machine::vocab_gen::domain_states::WAITING;
use car_policy::plug::{SessionKind, Widening};

use crate::py::s;
use crate::{Engine, Row};

/// The reason a kind no longer watched cancels its waiting records with.
pub const OFF: &str = "session_kind_off";

impl Engine {
    /// `newer_than_engine(row)`: whether `row`'s conversation is of a kind the plug names and a Codex newer than the
    /// engine's wrote it (the version skew guard). False with no kind named - the standard edition's always.
    pub fn newer_than_engine(&self, row: &Row) -> bool {
        let Some(kinds) = self
            .session_kinds
            .as_ref()
            .filter(|kinds| !kinds.is_empty())
        else {
            return false;
        };
        self.source
            .newer_than_engine(&s(row, "thread_id"), kinds, &self.backend.engine_version())
            .unwrap_or(false)
    }

    /// `session_kinds()`: P18 and P19, asked once a tick while not paused, and set on the reader.
    pub fn session_kinds(&mut self) -> Py<()> {
        let kinds: BTreeSet<String> = self.plug.sessions().into_iter().collect();
        let widened: BTreeSet<String> = self.plug.eligibility().into_iter().collect();
        let before = self.session_kinds.clone().unwrap_or_else(|| {
            SessionKind::ALL
                .iter()
                .map(|kind| kind.as_str().to_owned())
                .collect()
        });
        let wider = self.widened.clone().unwrap_or_else(|| {
            Widening::ALL
                .iter()
                .map(|kind| kind.as_str().to_owned())
                .collect()
        });
        self.source.set_kinds(&kinds, &widened);
        self.session_kinds = Some(kinds.clone());
        self.widened = Some(widened.clone());
        if kinds == before && widened == wider {
            return Ok(());
        }
        // `gone = (before - kinds) or (wider - widened)`: either has a member.
        let gone = !before.is_subset(&kinds) || !wider.is_subset(&widened);
        let mut left = Vec::new();
        if gone {
            let every: BTreeSet<String> = before.union(&kinds).cloned().collect();
            let wide: BTreeSet<String> = wider.union(&widened).cloned().collect();
            for row in self.records(WAITING)? {
                let thread = s(&row, "thread_id");
                // Taken now first: the app's own conversation, and every one still watched, costs one read.
                let found = (|| -> Py<bool> {
                    Ok(!self.source.taken(&thread, &kinds, &widened)?
                        && self.source.taken(&thread, &every, &wide)?)
                })();
                if found == Ok(true) {
                    left.push(row);
                }
            }
        }
        for row in left {
            // One at a time, each told to the plug as it moves (none moved if it left waiting meanwhile).
            let now = self.now();
            let cancelled = self
                .store
                .cancel_waiting(&[s(&row, "interruption_id")], now, OFF)?;
            if !cancelled.is_empty() {
                self.moved(&row, "cancelled");
                self.log(Some(&s(&row, "thread_id")), "cancelled", Value::from(OFF));
            }
        }
        Ok(())
    }
}
