//! Needs-you notices (v0.6.11), as the engine raises them: once, and never as a recovery (`engine/notices.py`).
//!
//! A failure this product will not resume, and a turn that has recorded nothing new for a time a person chose, are told
//! through the one notification path there is - one event, NEEDS_YOU - and kept in the notices table so each is told
//! once, restarts included. At the defaults it reads nothing and writes nothing.

use car_machine::domain::ids;
use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_policy::classify::needsyou;

use crate::Engine;
use crate::py::{self, get, row, s, text_of};

impl Engine {
    /// `tell_needs_you(failures, since)`: raise each notice not raised before. A notice that cannot be raised costs
    /// its notice; a failure a record holds needs no notice of its own.
    pub fn tell_needs_you(&mut self, failures: &[Map], since: f64) {
        let values = self.values();
        if !needsyou::told(&values) {
            return;
        }
        let now = self.now();
        if self.needs_you(failures, since, now, &values).is_err() {
            self.log(None, "needs_you_unavailable", Value::Null);
        }
    }

    fn needs_you(&mut self, failures: &[Map], since: f64, now: f64, values: &Value) -> Py<()> {
        let kinds = needsyou::kinds(values);
        for failure in failures {
            let done = get(failure, "completed_at");
            let category = text_of(failure, "category").unwrap_or_default().to_owned();
            if kinds.contains(&category.as_str())
                && !matches!(done, Value::Null)
                && now - py::num(done)? <= needsyou::WINDOW_SECONDS as f64
                && self.store.thread_enabled(&s(failure, "thread_id"))?
            {
                let keyed = self.keyed(Some(failure.clone()))?.ok_or("TypeError")?;
                if self.store.get(&s(&keyed, "interruption_id"))?.is_none() {
                    let key = s(failure, "interruption_id");
                    self.notice(&key, &s(failure, "thread_id"), &category, now, Map::new())?;
                }
            }
        }
        let Some(quiet) = needsyou::stall_seconds(values) else {
            return Ok(());
        };
        let start = since.max(now - needsyou::WINDOW_SECONDS as f64);
        for turn in self.source.stalled_turns(start, quiet as f64, now)? {
            let thread = s(&turn, "thread_id");
            if self.store.thread_enabled(&thread)? {
                let key = ids::stalled_id(
                    get(&turn, "thread_id"),
                    get(&turn, "turn_id"),
                    &Value::from(self.home_key.as_str()),
                )?;
                let minutes = needsyou::minutes(&Value::from(quiet))?;
                let detail = row(vec![("minutes", Value::from(minutes as i64))]);
                self.notice(&key, &thread, needsyou::STALLED, now, detail)?;
            }
        }
        Ok(())
    }

    /// `_notice(key, thread_id, kind, now, **detail)`: one notice, kept and told the first time only.
    fn notice(&mut self, key: &str, thread_id: &str, kind: &str, now: f64, detail: Map) -> Py<()> {
        if !self.store.raise_notice(key, thread_id, kind, now)? {
            return Ok(());
        }
        self.log(Some(thread_id), "needs_you_notice", Value::from(key));
        let told = row(vec![
            ("interruption_id", Value::from(key)),
            ("thread_id", Value::from(thread_id)),
            ("category", Value::from(kind)),
        ]);
        self.announce(needsyou::EVENT, &told, detail);
        Ok(())
    }
}
