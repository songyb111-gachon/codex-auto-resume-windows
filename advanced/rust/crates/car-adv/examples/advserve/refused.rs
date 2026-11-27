//! How advserve makes each shipped capability's code (completion part 2, step 0: safety first). Every code made in
//! this process reaches nothing of this PC: its world is asked of the test ([`Made::Asked`], worlds.rs), its own hands
//! refuse every reach outside the test's scratch paths ([`Made::Refused`], here), or car-adv's own `make` is used
//! because its defaults reach nothing but those paths ([`Made::Bare`], each one read); a capability whose car-adv
//! defaults reach this PC - a process started, a waitable timer, a named event, the registry, Credential Manager, the
//! real Codex home or its app - and has no refusing world here yet gets no code under the proxy ([`Made::Withheld`]).
//! An id none of the lists names is withheld: a new capability is safe before anybody reads its `make`.

use std::path::{Path, PathBuf};

use car_adv::capabilities::Code;
use car_adv::codex::account::{self, Opener, Session};
use car_adv::codex::authfile::Fault;
use car_adv::codex::swap;
use car_adv::engine::{account as watch, autoswitch};
use car_codex::system::System;
use car_config::Paths;
use car_machine::json::Value;

/// How a shipped code is made under the proxy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Made {
    /// Its world is the test's, seam by seam (worlds.rs).
    Asked,
    /// car-adv's code with hands of this module's that refuse.
    Refused,
    /// car-adv's own `make`: its defaults reach only the test's scratch paths, or refuse.
    Bare,
    /// No code: car-adv's defaults reach this PC and no refusing world is built here yet.
    Withheld,
}

/// The codes whose world the test answers (worlds.rs `make`).
pub const ASKED: &[&str] = &[
    "usage_meter",
    "usage_wrap_up",
    "usage_pause",
    "reset_message",
    "reset_credit",
    "empty_response",
    "subagent_parent",
    "goal_continuation",
    "prompt_queue",
];

/// The codes made here with hands that refuse.
pub const REFUSED: &[&str] = &["account_switch", "account_auto_switch"];

/// The codes car-adv's own `make` makes here, each `make` read: no session (`no_session`, the `bare` worlds, a refusing
/// opener), pure rules over the test's state, the told pair of the scratch home, or no code at all.
pub const BARE: &[&str] = &[
    "start_with_codex",
    "queue_for_open",
    "compact_continue",
    "model_fallback",
    "headless_run",
    "other_sessions",
    "marker_free_continuation",
    "capacity_retry",
    "structured_rules",
    "unknown_failure_budget",
    "codex_gave_up",
    "sign_in_retry",
    "long_reset_message",
    "early_reset",
    "once_more_when_unsure",
    "send_now",
    "parallel_dispatch",
    "keep_going",
    "every_conversation",
    "silent_continuation",
    "codex_retry_settings",
    "steer_send",
    "open_to_send",
    "open_codex_button",
    "codex_chat",
    "window_anchor",
    "local_api_actions",
    "local_api_lan",
    "telegram_continue",
    "stop_hook_continuation",
    "compat_report",
    "python_choice",
];

/// The codes withheld, with what car-adv's default reaches (the record the tests hold to car-adv's `MADE`; `made` withholds
/// every id the other lists do not name).
#[cfg_attr(not(test), allow(dead_code))]
pub const WITHHELD: &[(&str, &str)] = &[
    ("crash_restart", "named events (StopFlag over car_platform::wake::SystemEvents)"),
    ("usage_analytics", "the watched Codex homes of this PC (tokens::watched_homes, LocalSource)"),
    ("wake_for_reset", "a waitable timer that wakes this PC (system_timer)"),
    ("idle_update_check", "the managed policy in this user's registry"),
    ("fleet_view", "the Codex home of this PC's environment (guarded_homes)"),
    ("power_after_tasks", "the Codex home in use and its turns (supervise::codex_home)"),
    ("push_notices", "the courier process (courier::launch::start_due)"),
    ("status_feed", "the courier process (courier::launch::start_due)"),
    ("local_api", "the courier's server process (courier::launch::start)"),
    ("telegram_remote", "the courier's server process (courier::launch::start)"),
];

/// How `id`'s code is made here; an id no list names is withheld.
pub fn made(id: &str) -> Made {
    if ASKED.contains(&id) {
        Made::Asked
    } else if REFUSED.contains(&id) {
        Made::Refused
    } else if BARE.contains(&id) {
        Made::Bare
    } else {
        Made::Withheld
    }
}

/// The refused code of `id` (one of [`REFUSED`]).
pub fn make(id: &str, paths: &Paths) -> Option<Box<dyn Code>> {
    match id {
        "account_switch" => watch::make_with(account_seams(paths)),
        "account_auto_switch" => autoswitch::make_with(autoswitch_seams(paths)),
        _ => None,
    }
}

// ------------------------------------------------------------------ the hands that refuse

const REFUSAL: &str = "AdapterError";

fn refusal() -> Fault {
    Fault::new(REFUSAL, "advserve reaches nothing outside the test's scratch paths")
}

/// Every session refused at its making: no backend, no app-server, no Codex home of this PC.
pub struct NoSessions;

impl Opener for NoSessions {
    fn open(&self, _home: Option<&Path>) -> Result<Box<dyn Session + '_>, Fault> {
        Err(refusal())
    }
}

/// Credential Manager refused.
pub struct NoSecrets;

impl watch::SaltStore for NoSecrets {
    fn read(&self, _capability: &str, _name: &str) -> Result<Option<String>, Fault> {
        Err(Fault::new("SecretError", "advserve reaches no Credential Manager"))
    }
    fn write(&self, _capability: &str, _name: &str, _secret: &str) -> Result<(), Fault> {
        Err(Fault::new("SecretError", "advserve reaches no Credential Manager"))
    }
    fn delete(&self, _capability: &str, _name: &str) -> Result<bool, Fault> {
        Err(Fault::new("SecretError", "advserve reaches no Credential Manager"))
    }
}

/// A machine with nothing on it: no environment, no process, no engine.
#[derive(Debug)]
struct Empty;

impl System for Empty {
    fn env(&self, _name: &str) -> Option<String> {
        None
    }
    fn processes_named(
        &self,
        _names: &[&str],
        _families: &[&str],
    ) -> car_codex::errors::Result<Vec<Value>> {
        Ok(Vec::new())
    }
    fn resource_users(&self, _paths: &[String]) -> car_codex::errors::Result<Vec<Value>> {
        Ok(Vec::new())
    }
    fn process_identity(&self, _pid: &Value) -> car_codex::errors::Result<Value> {
        Ok(Value::Null)
    }
    fn signer(&self, _path: &str) -> Result<String, Option<&'static str>> {
        Err(None)
    }
    fn own_pid(&self) -> i64 {
        1
    }
    fn monotonic(&self) -> f64 {
        0.0
    }
    fn resolve(&self, text: &str) -> Option<String> {
        Some(text.to_owned())
    }
    fn restart_manager_available(&self) -> bool {
        false
    }
}

/// `swap`'s world with no app, no process and no pause.
struct NoSwap(Empty);

fn private(_path: &Path) -> bool {
    false
}
fn pause(_seconds: f64) {}
fn inventory() -> Option<Vec<Value>> {
    None
}
fn own() -> Vec<Value> {
    Vec::new()
}
fn app_running() -> Option<bool> {
    None
}
fn clock() -> f64 {
    0.0
}

impl autoswitch::Worldly for NoSwap {
    fn world(&self) -> swap::World<'_> {
        swap::World {
            tokens: &car_adv::credentials::SystemTokens,
            private: &private,
            pause: &pause,
            inventory: &inventory,
            own: &own,
            system: &self.0,
            app_running: &app_running,
            clock: &clock,
            sleep: &pause,
        }
    }
}

/// account_switch's hands: the read and Credential Manager refused; core's hold and the saved accounts' record are the
/// test's scratch paths' (car-adv's own).
pub fn account_seams(paths: &Paths) -> watch::Seams {
    let mut seams = watch::live_seams(paths);
    seams.read = Box::new(|| account::read(&NoSessions));
    seams.secrets = Box::new(NoSecrets);
    seams
}

/// account_auto_switch's hands: the Codex home, every session, the real read, the swap's world, the restart, the
/// idle time and the busy rule refused; the saved accounts are the scratch home's (car-adv's own).
pub fn autoswitch_seams(paths: &Paths) -> autoswitch::Seams {
    let mut seams = autoswitch::live_seams(paths);
    seams.home = Box::new(|| -> Result<PathBuf, Fault> { Err(refusal()) });
    seams.session_for = Box::new(NoSessions);
    seams.read_real = Box::new(|| account::read(&NoSessions));
    seams.world = Box::new(NoSwap(Empty));
    seams.hands.restart = Some(Box::new(|_between| Err(refusal())));
    seams.hands.idle = Box::new(|| Value::Null);
    seams.hands.busy = Box::new(|| Err(refusal()));
    seams
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_adv::capabilities::MADE;

    /// Paths under a scratch folder nothing here creates (the refused hands never reach it).
    fn paths() -> Paths {
        let root = std::env::temp_dir().join("car-v0627-proxy2-refused-unused");
        let home = root.to_string_lossy().into_owned();
        Paths::new(
            Some(&home),
            &home,
            &|_| None,
            car_config::Os::here(false, std::sync::Arc::new(crate::Links)),
        )
        .expect("scratch paths")
    }

    fn present(found: &Value) -> Option<Value> {
        match found {
            Value::Object(map) => map.get("present").cloned(),
            _ => None,
        }
    }

    #[test]
    fn every_shipped_id_is_named_once_and_nothing_else_is_named() {
        let mut named: Vec<&str> = ASKED.to_vec();
        named.extend(REFUSED);
        named.extend(BARE);
        named.extend(WITHHELD.iter().map(|(id, _)| *id));
        let mut sorted = named.clone();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(sorted.len(), named.len(), "an id is named twice");
        for id in MADE {
            assert!(named.contains(id), "{id}: car-adv makes it, advserve names no way to make it safely");
        }
        for id in &named {
            assert!(MADE.contains(id), "{id}: named here, car-adv does not make it");
        }
    }

    #[test]
    fn an_id_nobody_read_is_withheld() {
        assert_eq!(made("a_capability_added_tomorrow"), Made::Withheld);
        for (id, _) in WITHHELD {
            assert_eq!(made(id), Made::Withheld, "{id}");
        }
    }

    #[test]
    fn the_refused_hands_open_nothing() {
        let paths = paths();
        let account = account_seams(&paths);
        assert!(matches!(present(&(account.read)()), Some(Value::Null)));
        assert!(account.secrets.read("account_switch", "salt").is_err());
        assert!(account.secrets.write("account_switch", "salt", "x").is_err());
        assert!(account.secrets.delete("account_switch", "salt").is_err());

        let mut switch = autoswitch_seams(&paths);
        assert!((switch.home)().is_err());
        assert!(switch.session_for.open(None).is_err());
        assert!(switch.session_for.open(Some(Path::new("x"))).is_err());
        assert!(matches!(present(&(switch.read_real)()), Some(Value::Null)));
        let restart = switch.hands.restart.as_mut().expect("refused, never the live restart");
        let mut between_ran = false;
        assert!(
            restart(&mut || {
                between_ran = true;
                Ok(())
            })
            .is_err()
        );
        assert!(!between_ran, "the refused restart ran what follows the close");
        assert!((switch.hands.busy)().is_err());
        assert!(matches!((switch.hands.idle)(), Value::Null));
        let world = switch.world.world();
        assert!((world.inventory)().is_none());
        assert!((world.app_running)().is_none());
        assert!(world.system.env("CODEX_HOME").is_none());
        assert!(world.system.env("USERPROFILE").is_none());
    }

    #[test]
    fn the_installed_world_refuses_reset_credit_s_session() {
        car_adv::engine::usage::install_world(crate::worlds::refusing());
        let world = car_adv::engine::usage::World::installed();
        assert!((world.open)(&paths(), "reset_credit").is_err());
        assert!((world.backend)(&paths()).is_err());
        assert!((world.home)(&paths()).is_err());
    }
}
