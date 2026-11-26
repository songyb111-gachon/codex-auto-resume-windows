//! Records of the edition's own, tried like core's (P2, v0.6.14) (`engine/plugrecords.py`), as far as core reads them.
//!
//! What core itself reads of this mixin is ported: the wrap-ups delivered in this process (`persons_turns`,
//! `wrap_up_markers`), and what a Pause watches of the plug's records in flight (`paused_records`, none until one is
//! handed over). Carrying out a record of the plug's - its gates, its one claim (`reserve_record`, `record_guard`, the
//! advanced store's), its send through `recordchannel.py` - is the advanced edition's alone and comes with S7.2: here
//! a record the plug hands over costs itself, as one that raises does in the reference (`plug_record_check_failed`).

use std::collections::{BTreeSet, HashMap};

use car_machine::json::{Map, Value};

use crate::Engine;
use crate::py::{get, text_of};

/// The most wrap-ups, flying records and noted records kept (`NOTED_LIMIT`).
pub const NOTED_LIMIT: usize = 4096;

impl Engine {
    /// `plug_records(view)`: P2 - every record the plug hands over, each costing only itself.
    pub fn plug_records(&mut self, now: f64) {
        let records = {
            let view = self.view(now);
            self.plug.records(&view)
        };
        let Ok(records) = records else {
            return;
        };
        for record in records {
            let thread = match &record {
                Value::Object(record) => text_of(record, "thread_id").map(str::to_owned),
                _ => None,
            };
            self.log(thread.as_deref(), "plug_record_check_failed", Value::Null);
        }
    }

    /// `_wrap_up_markers()`: the markers of the wrap-ups delivered in each conversation in this process, by thread.
    pub(crate) fn wrap_up_markers(&mut self) -> &HashMap<String, BTreeSet<String>> {
        if self.wrap_ups.len() > NOTED_LIMIT {
            self.wrap_ups.clear();
        }
        &self.wrap_ups
    }

    /// `persons_turns(thread, turns)`: `turns` less those a wrap-up of this product's started (v0.6.16-beta.3).
    pub fn persons_turns(&mut self, thread: &str, turns: Vec<Map>) -> Vec<Map> {
        let markers: Vec<String> = self
            .wrap_up_markers()
            .get(thread)
            .map(|found| found.iter().cloned().collect())
            .unwrap_or_default();
        if markers.is_empty() {
            return turns;
        }
        turns
            .into_iter()
            .filter(|turn| {
                let ours = match text_of(turn, "turn_id") {
                    Some(turn_id) if !matches!(get(turn, "turn_id"), Value::Null) => self
                        .source
                        .turn_markers(thread, turn_id, &markers)
                        .is_ok_and(|found| !found.is_empty()),
                    _ => false,
                };
                !ours
            })
            .collect()
    }

    /// `paused_records()`: while recovery is paused, the plug's records core watched in flight (none here: they are
    /// handed over by P2, which comes with S7.2).
    pub fn paused_records(&mut self) {}
}
