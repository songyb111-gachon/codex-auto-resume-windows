//! A conversation the app does not hold, continued by a route the edition's plug names (P16) (`engine/routes.py`).
//!
//! Core has always waited for the app to open such a conversation (A11); the plug may name a route instead, taken where
//! core would wait once every gate before that one has passed, and carried out as a send is: the one claim, the
//! pre-send look, and the route called once, handed core's own look at whether the conversation is still not held.
//! The standard edition's plug names no route, so none of this runs for it.

use std::cell::Cell;

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_policy::classify::gates::{PASS, PLUGGED, Vector, gate};
use car_policy::plug::{Alternative, Answer, Point, UnloadedAnswer};

use crate::dispatch::Route;
use crate::options::{LimitsMap, limits_of};
use crate::py::{self, get, row, s, text, text_of, truthy, with};
use crate::seam::{Claim, Correlate};
use crate::{Engine, Row};

/// Where P16 is asked: a conversation the running app does not hold, and one nothing holds while the app is not
/// running (Backend.holder's word for it). OURS: an app server this process started and holds.
pub const APP_FREE: &str = "app_free";
pub const NOBODY: &str = "none";
pub const OURS: &str = "ours";

/// The words a route that takes them carries: (message, worded, the words for this time, the plain message).
pub type Words = (String, bool, Option<Value>, String);

fn route_of(answer: UnloadedAnswer) -> Option<Route> {
    match answer {
        UnloadedAnswer::Defer => None,
        UnloadedAnswer::Queued(word) => Some(Route::Queued(word)),
        UnloadedAnswer::Route { route, words } => Some(Route::Plugged { route, words }),
    }
}

impl Engine {
    /// `_route(row, app, vector)`: (the route the plug names for `row`, or None; what the app said of it).
    pub(crate) fn route(
        &mut self,
        row: &Row,
        app: &Value,
        vector: &mut Vector,
    ) -> Py<(Option<Route>, Value)> {
        if !truthy(app) {
            return Ok((self.unheld(row, vector)?, Value::from("notLoaded")));
        }
        let loaded = self.backend.loaded(&s(row, "thread_id"), app)?;
        // v0.6.16-beta.4: or held by another Codex session (engine/tosession.rs).
        let route = match self.unloaded(row, &loaded, vector) {
            Some(route) => Some(route),
            None => self.session(row, &loaded, vector),
        };
        Ok((route, loaded))
    }

    /// `_still_where(thread_id, app, route)`: the re-check under the dispatch lock.
    pub(crate) fn still_where(
        &mut self,
        thread_id: &str,
        app: &Value,
        route: Option<&Route>,
    ) -> Py<bool> {
        if matches!(app, Value::Null) {
            return Ok(self.unheld_now(thread_id, false));
        }
        if !py::eq(&self.backend.app_identity()?, app) {
            return Ok(false);
        }
        let loaded = self.backend.loaded(thread_id, app)?;
        if route.is_some_and(|route| route.is(Alternative::ToSession)) {
            let kept = self.session_holders.remove(thread_id);
            return Ok(pyval::is(&loaded, "elsewhere")
                && kept.is_some_and(|kept| py::eq(&self.backend.session_holder(), &kept)));
        }
        Ok(pyval::is(
            &loaded,
            if route.is_none() {
                "loaded"
            } else {
                "notLoaded"
            },
        ))
    }

    /// `_unloaded(row, loaded, vector)`: P16 - the route the plug names for a conversation the app does not hold.
    fn unloaded(&mut self, row: &Row, loaded: &Value, vector: &mut Vector) -> Option<Route> {
        if !pyval::is(loaded, "notLoaded") || vector.or_unknown("consent").0 != PASS {
            return None;
        }
        let told = with(
            row,
            vec![
                ("holder", Value::from(APP_FREE)),
                ("app", Value::Bool(true)),
            ],
        );
        let route = route_of(self.plug.unloaded(&Value::Object(told)))?;
        if route.is(Alternative::ToSession) {
            return None;
        }
        vector.set("thread_available", gate(PASS, PLUGGED));
        Some(route)
    }

    /// `_unheld(row, vector)`: P16 with the Codex app closed - asked only where the plug wants P16 at all.
    fn unheld(&mut self, row: &Row, vector: &mut Vector) -> Py<Option<Route>> {
        if !self.home_key.is_empty()
            || vector.or_unknown("consent").0 != PASS
            || !self.plug.wants(Point::Unloaded)
        {
            return Ok(None);
        }
        if !pyval::is(&self.holder(&s(row, "thread_id"))?, NOBODY) {
            return Ok(None);
        }
        let told = with(
            row,
            vec![("holder", Value::from(NOBODY)), ("app", Value::Bool(false))],
        );
        let Some(route) = route_of(self.plug.unloaded(&Value::Object(told))) else {
            return Ok(None);
        };
        if route.queued() {
            return Ok(None);
        }
        vector.set("thread_available", gate(PASS, PLUGGED));
        Ok(Some(route))
    }

    /// `_unheld_now(thread_id, ours)`: whether the Codex app is still not running and nothing holds `thread_id`.
    pub(crate) fn unheld_now(&self, thread_id: &str, ours: bool) -> bool {
        let look = || -> Py<bool> {
            if !matches!(self.backend.app_identity()?, Value::Null) {
                return Ok(false);
            }
            let holder = self.holder(thread_id)?;
            Ok(pyval::is(&holder, NOBODY) || (ours && pyval::is(&holder, OURS)))
        };
        look().unwrap_or(false)
    }

    /// `_holder(thread_id)`: Backend.holder's word, "unknown" from a backend with no such call.
    fn holder(&self, thread_id: &str) -> Py<Value> {
        self.backend
            .holder(thread_id)
            .unwrap_or_else(|| Ok(Value::from("unknown")))
    }

    /// `_resume_unloaded(current, vector, limits, route, app, relaxed, forced, words)`: carry out the route the plug
    /// named at P16, as `dispatch` carries out a send.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn resume_unloaded(
        &mut self,
        current: &Row,
        vector: &mut Vector,
        limits: &LimitsMap,
        route: Option<&Route>,
        app: &Value,
        relaxed: Option<&'static str>,
        forced: bool,
        words: Option<Words>,
    ) -> Py<()> {
        let Some(Route::Plugged { route, .. }) = route else {
            return Ok(());
        };
        let key = s(current, "interruption_id");
        let at = self.now();
        let given = words.is_some();
        let (mut message, worded, once, plain) = match words {
            Some((message, worded, once, plain)) => (Some(message), worded, once, Some(plain)),
            None => (None, false, None, None),
        };
        // v0.6.17: SILENT yields to any words the continuation carries that are not core's own template.
        let carries_words = worded || once.is_some();
        let silent = message.is_some() && self.silent(current, carries_words)?;
        let mut carried = std::collections::BTreeSet::from([Point::Unloaded]);
        if worded && !silent {
            carried.insert(Point::Text);
        }
        if silent {
            carried.insert(Point::Delivery);
        }
        carried.extend(Engine::relaxed_points(relaxed));
        carried.extend(Engine::relaxed_points(if forced {
            Some("forced")
        } else {
            None
        }));
        let claim = Claim {
            plugged: !self.plug.is_null(),
            limits: limits_of(&if forced {
                self.forced_limits(limits)
            } else {
                limits.clone()
            }),
            gates: vector.clone(),
            carried,
            quiet_until: self.quiet_until(at)?,
            relaxed: relaxed.map(str::to_owned),
            resend: None,
            forced,
            caps: self.caps(relaxed),
        };
        let (claimed, refusing, reason) =
            self.store.reserve_ledgered(&key, at, &claim, &self.plug)?;
        if !claimed {
            return self.refused(current, refusing.as_deref(), reason.as_deref());
        }
        self.moved(current, "submitting");
        let claim = self.store.get(&key)?;
        if let Some((target, why, delay)) = self.presend_problem(claim.as_ref(), forced)? {
            self.release(&key, claim.as_ref(), &target, &why, delay)?;
            self.log(
                Some(&s(current, "thread_id")),
                &target,
                Value::from(why.as_str()),
            );
            return Ok(());
        }
        let claim = claim.ok_or("TypeError")?;
        if given && self.once_words_moved(&claim)? {
            return Ok(()); // given back (engine/delivery.rs)
        }
        let thread_id = s(&claim, "thread_id");
        if let Some(once) = &once
            && !self.spend_once_words(&claim, once)
        {
            message = plain; // never sent twice
        }
        let refused = Cell::new(false);
        let response = {
            let still_unloaded = || -> bool {
                // Consent again, as the launch guard asks it: a Cancel, Pause or observe-only set while the route's
                // session started stops it here, before anything changes in Codex.
                let mut permitted = false;
                let entered = self.store.submission_guard(&key, &mut |allowed| {
                    permitted = allowed;
                    Value::Null
                });
                if entered.is_err() {
                    return false;
                }
                if !permitted {
                    refused.set(true);
                    return false;
                }
                if matches!(app, Value::Null) {
                    return self.unheld_now(&thread_id, true);
                }
                let look = || -> Py<bool> {
                    Ok(py::eq(&self.backend.app_identity()?, app)
                        && pyval::is(&self.backend.loaded(&thread_id, app)?, "notLoaded"))
                };
                look().unwrap_or(false)
            };
            let handed = message.as_ref().map(|message| {
                if silent {
                    String::new()
                } else {
                    format!("{message}\n\n{}", s(&claim, "marker"))
                }
            });
            let handed = handed.as_deref().map(Str::from);
            let client = message.as_ref().map(|_| ids::continuation_client_id(&key));
            // `plughands.Route.resume(thread, launch_guard=store.submission_guard(key), ...)`: the guard entered
            // first - a raise is the route's raise - and the route called only where it permitted the launch.
            let found = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let permitted = self.store.submission_guard(&key, &mut Value::Bool)?;
                if !matches!(permitted, Value::Bool(true)) {
                    return Ok(crate::plugrecords::refused_launch());
                }
                Ok::<Value, &'static str>(route.resume(
                    &thread_id,
                    Some(&still_unloaded),
                    handed.as_ref(),
                    client.as_deref(),
                ))
            }));
            match found {
                Ok(Ok(Value::Object(response))) => response,
                _ => row(vec![("outcome", Value::from("unknown"))]),
            }
        };
        let mut response = response;
        if refused.get() && text(get(&response, "outcome")) == Some("not_started") {
            // a Cancel is settled as one
            response.insert(
                Str::from("error_code"),
                Value::from("queue_consent_refused"),
            );
        }
        if self.after_resume(current, &response).is_err() {
            self.log(
                Some(&s(current, "thread_id")),
                "post_send_bookkeeping_failed",
                Value::Null,
            );
        }
        Ok(())
    }

    /// `_silent(row, yields)`: P15 for a route that takes words - SILENT is no words at all, the turn proven by the
    /// client id core derives, written into the record before the claim.
    fn silent(&mut self, row: &Row, yields: bool) -> Py<bool> {
        let key = s(row, "interruption_id");
        let derived = ids::continuation_client_id(&key);
        let silent = !yields
            && self.plug.delivery(&Value::Object(with(
                row,
                vec![("route", Value::Bool(true))],
            ))) == Answer::Is(Alternative::Silent);
        let held = text(get(row, "recovery_client_id")).map(str::to_owned);
        let at = self.now();
        if silent && held.as_deref() != Some(derived.as_str()) {
            self.store.update(
                &key,
                &row_one("recovery_client_id", Value::from(derived.as_str())),
                Some(at),
                None,
                0,
            )?;
        } else if !silent && held.as_deref() == Some(derived.as_str()) {
            self.store.update(
                &key,
                &row_one("recovery_client_id", Value::Null),
                Some(at),
                None,
                0,
            )?;
        }
        Ok(silent)
    }

    /// `_silent_proven(row, turn_id)`: a turn started with no words keeps no client id on any item: the turn id the
    /// route's turn/start returned is its proof, correlated at once.
    fn silent_proven(&mut self, row: &Row, turn_id: &str) -> Py<bool> {
        let key = s(row, "interruption_id");
        if text_of(row, "recovery_client_id") != Some(ids::continuation_client_id(&key).as_str()) {
            return Ok(false);
        }
        let Some(current) = self.store.get(&key)? else {
            return Ok(false);
        };
        let options = Correlate {
            client_id: get(row, "recovery_client_id").clone(),
            status: Value::from("inProgress"),
            ..Correlate::default()
        };
        let now = self.now();
        if !self.store.correlate(&key, turn_id, now, &options)? {
            return Ok(false);
        }
        self.moved(&current, "turn_started");
        self.log(Some(&s(row, "thread_id")), "turn_started", Value::Null);
        Ok(true)
    }

    /// `_after_resume(row, response)`: what came of a route (P16).
    fn after_resume(&mut self, row: &Row, response: &Map) -> Py<()> {
        let key = s(row, "interruption_id");
        let thread = s(row, "thread_id");
        let outcome = text(get(response, "outcome")).map(str::to_owned);
        let words = self.once_sent.remove(&key);
        if let Some(words) = &words
            && outcome.as_deref() == Some("not_started")
            && let Some(once) = self.once_words.as_ref()
        {
            let _ = once.restore(&key, words); // never handed to Codex: they wait for the next one
        }
        let reserved = self.store.get(&key)?.ok_or("TypeError")?;
        let poll = self.options.state_poll_seconds;
        match outcome.as_deref() {
            Some("accepted") => self.transition(
                &reserved,
                "waiting_retry",
                Some("notLoaded"),
                Some(poll),
                None,
                row_one("submitted_at", Value::Null),
            ),
            Some("ran") if ids::is_uuid(get(response, "turn_id")) => {
                // v0.6.16-beta.4: a route that started the one turn itself, carrying core's words.
                self.transition(
                    &reserved,
                    "queued",
                    None,
                    Some(1.0),
                    Some("submitted"),
                    row_one("queue_id", Value::Null),
                )?;
                self.log(Some(&thread), "continuation_submitted", Value::Null);
                let told = self.told_of(row);
                self.announce("starting", &reserved, told);
                self.silent_proven(&reserved, text_of(response, "turn_id").unwrap_or_default())?;
                Ok(())
            }
            Some("not_started") => {
                let refused = text(get(response, "error_code")) == Some("queue_consent_refused");
                let target = if refused && truthy(get(&reserved, "cancel_requested")) {
                    "cancelled".to_owned()
                } else {
                    self.waiting_state(&reserved)?
                };
                let reason = if target == "cancelled" {
                    "user_cancelled"
                } else {
                    "released_before_send"
                };
                self.release(&key, Some(&reserved), &target, reason, poll)?;
                self.log(Some(&thread), &target, Value::from(reason));
                Ok(())
            }
            _ => self.transition(
                &reserved,
                "submission_unknown",
                Some("queue_result_unknown_do_not_resend"),
                Some(1.0),
                None,
                Row::new(),
            ),
        }
    }
}

fn row_one(name: &str, value: Value) -> Row {
    row(vec![(name, value)])
}
