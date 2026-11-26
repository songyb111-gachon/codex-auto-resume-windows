//! `Runtime.eligibility` (P19) and `Runtime.sessions` (P18) (`runtime.py`).

use std::collections::BTreeSet;

use car_policy::plug::Point;
use car_policy::plug::hands::{kinds_of, widening_of};

use super::{Py, Runtime};
use crate::capabilities::Said;
use crate::vocabulary::{ArmingState, JournalCode};

impl Runtime {
    /// `eligibility()`: the Widening words every capability on at ELIGIBILITY names, together - or None (DEFER).
    pub fn eligibility(&self) -> Py<Option<Vec<String>>> {
        self.words_at(Point::Eligibility, widening_of)
    }

    /// `sessions()`: the SessionKind words every capability on at SESSIONS names, together - or None (DEFER).
    pub fn sessions(&self) -> Py<Option<Vec<String>>> {
        self.words_at(Point::Sessions, kinds_of)
    }

    fn words_at(
        &self,
        point: Point,
        words_of: fn(Option<&[car_machine::json::Value]>) -> Vec<String>,
    ) -> Py<Option<Vec<String>>> {
        let definitions = self.registry.at(point);
        if definitions.is_empty() {
            return Ok(None);
        }
        let states = self.states(false, &[]);
        let mut found: BTreeSet<String> = BTreeSet::new();
        for definition in definitions {
            let state = states.state_of(&definition.id);
            if state == ArmingState::Off {
                continue;
            }
            let said = match self.call(definition, |code| {
                if point == Point::Sessions {
                    code.sessions()
                } else {
                    code.eligibility()
                }
            }) {
                Ok(said) => said,
                Err(raised) => {
                    self.tripped(definition, None, &raised);
                    continue;
                }
            };
            // `kinds_of` / `widening_of`: the words in a set, a frozenset or a tuple, and nothing for anything else.
            let answer = match &said {
                Said::Tuple(items) | Said::Set(items) => words_of(Some(items)),
                _ => Vec::new(),
            };
            if answer.is_empty() {
                continue;
            }
            if state == ArmingState::Shadow {
                self.once(
                    JournalCode::WouldHave,
                    definition,
                    point,
                    point.as_str(),
                    None,
                )?;
                continue;
            }
            self.once(JournalCode::Acted, definition, point, point.as_str(), None)?;
            found.extend(answer);
        }
        Ok(if found.is_empty() {
            None
        } else {
            Some(found.into_iter().collect())
        })
    }
}
