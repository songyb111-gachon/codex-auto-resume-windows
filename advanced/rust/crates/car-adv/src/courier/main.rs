//! `courier/__main__.py` (seat S7.3b): the courier process - `codex-auto-resume.exe courier --home <home> [--feed |
//! --test <channel> | --pair | --serve | --check]` (the alpha's start, PLAN 1.7, in place of `pythonw.exe -c
//! <BOOTSTRAP> ...`).
//!
//! It takes this home's courier mutex first - a second courier for the same home exits at once with [`EXIT_BUSY`] -
//! then does one round and exits: the outbox drained while push_notices stands on and recovery is not paused; with
//! `--feed`, OpenAI's status page read once too; `--test <channel>`, the fixed test notice; `--pair`, Telegram's
//! pairing; `--serve`, the resident roles under the resident's own mutex; `--check`, every part a round needs linked,
//! then 0, nothing read or written. Nothing is printed.
//!
//! [`Runtime`] is what the courier's parts ask of the advanced runtime (`runtime.state`, `.clock()`, `.registry`,
//! `.states(fresh=True)`, `._unreadable`, `.arming.trip`, `.paths`): the real one is `crate::runtime::Runtime`; a diff
//! hands its own over the same state.

#![allow(clippy::result_unit_err)]

use car_config::Paths;

use crate::arming::States;
use crate::registry::Registry;
use crate::state::AdvancedState;
use crate::vocabulary::OffReason;

pub const EXIT_DONE: i32 = 0;
pub const EXIT_BUSY: i32 = 3;
pub const EXIT_REFUSED: i32 = 4;
pub const EXIT_NOT_PAIRED: i32 = 9;
pub const PUSH: &str = "push_notices";
pub const FEED: &str = "status_feed";

/// `EXIT_TEST[word]`: a test notice's outcome as its exit code.
pub fn exit_test(word: &str) -> Option<i32> {
    match word {
        "2xx" => Some(0),
        "4xx" => Some(5),
        "5xx" => Some(6),
        "timeout" => Some(7),
        "tls" => Some(8),
        _ => None,
    }
}

/// What the courier's parts ask of the runtime.
pub trait Runtime {
    fn state(&self) -> &AdvancedState;
    fn registry(&self) -> &Registry;
    fn paths(&self) -> &Paths;
    /// `runtime.clock()`.
    fn clock(&self) -> f64;
    /// `runtime.states(fresh=True)`; `Err` where it raised.
    fn states(&self) -> Result<States, ()>;
    /// `runtime._unreadable`: the last read of the states failed.
    fn unreadable(&self) -> bool;
    /// `runtime.arming.trip(capability, reason)`; `Err` where it raised.
    fn trip(&self, capability: &str, reason: OffReason) -> Result<bool, ()>;
}

impl Runtime for crate::runtime::Runtime {
    fn state(&self) -> &AdvancedState {
        &self.state
    }

    fn registry(&self) -> &Registry {
        &self.registry
    }

    fn paths(&self) -> &Paths {
        &self.paths
    }

    fn clock(&self) -> f64 {
        self.now()
    }

    fn states(&self) -> Result<States, ()> {
        Ok(crate::runtime::Runtime::states(self, true, &[]))
    }

    fn unreadable(&self) -> bool {
        self.unreadable.get()
    }

    fn trip(&self, capability: &str, reason: OffReason) -> Result<bool, ()> {
        self.arming().trip(capability, reason).map_err(|_| ())
    }
}

/// A runtime the resident's threads share (the poll's thread and the server's beside the check loop).
pub type SharedRuntime = std::sync::Arc<dyn Runtime + Send + Sync>;

/// The runtime as the plug holds it (`runtime::Shared`), seen as the courier's [`Runtime`]: every call under its lock.
pub struct SharedAdapter {
    shared: std::sync::Arc<crate::runtime::Shared>,
    registry: std::sync::Arc<Registry>,
    paths: Paths,
    state: *const AdvancedState,
}

// SAFETY: `state` points into the boxed state the `Shared` this adapter holds keeps for its whole life; the state guards
// its own connection with a mutex (Python shares it between threads the same way). Every other call takes the lock.
unsafe impl Send for SharedAdapter {}
// SAFETY: as above.
unsafe impl Sync for SharedAdapter {}

impl SharedAdapter {
    pub fn new(shared: std::sync::Arc<crate::runtime::Shared>) -> SharedAdapter {
        let (registry, paths, state) = shared.enter(|runtime| {
            (
                runtime.registry.clone(),
                runtime.paths.clone(),
                &*runtime.state as *const AdvancedState,
            )
        });
        SharedAdapter {
            shared,
            registry,
            paths,
            state,
        }
    }
}

impl Runtime for SharedAdapter {
    fn state(&self) -> &AdvancedState {
        // SAFETY: see the type's note.
        unsafe { &*self.state }
    }

    fn registry(&self) -> &Registry {
        &self.registry
    }

    fn paths(&self) -> &Paths {
        &self.paths
    }

    fn clock(&self) -> f64 {
        self.shared.enter(|runtime| runtime.now())
    }

    fn states(&self) -> Result<States, ()> {
        self.shared
            .enter(|runtime| Ok(crate::runtime::Runtime::states(runtime, true, &[])))
    }

    fn unreadable(&self) -> bool {
        self.shared.enter(|runtime| runtime.unreadable.get())
    }

    fn trip(&self, capability: &str, reason: OffReason) -> Result<bool, ()> {
        self.shared
            .enter(|runtime| runtime.arming().trip(capability, reason).map_err(|_| ()))
    }
}

/// What `parse(argv)` found: the home, the mode (`drain`, `feed`, `pair`, `serve`, `check`, `test`) and the channel.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Found {
    pub home: String,
    pub mode: &'static str,
    pub channel: Option<&'static str>,
}

/// `parse(argv)`: exactly `--home <path>` and at most one of `--feed`, `--test <channel>`, `--pair`, `--serve`,
/// `--check`; None for anything else.
pub fn parse(argv: &[String]) -> Option<Found> {
    let mut home: Option<String> = None;
    let mut mode = "drain";
    let mut channel = None;
    let mut at = 0;
    while at < argv.len() {
        let word = argv[at].as_str();
        at += 1;
        if word == "--home" && at < argv.len() && home.is_none() {
            home = Some(argv[at].clone());
            at += 1;
        } else if mode == "drain" && matches!(word, "--feed" | "--pair" | "--serve" | "--check") {
            mode = match word {
                "--feed" => "feed",
                "--pair" => "pair",
                "--serve" => "serve",
                _ => "check",
            };
        } else if word == "--test"
            && at < argv.len()
            && mode == "drain"
            && crate::vocabulary::CourierChannel::parse(&argv[at]).is_some()
        {
            mode = "test";
            channel = crate::vocabulary::CourierChannel::parse(&argv[at]).map(|c| c.as_str());
            at += 1;
        } else {
            return None;
        }
    }
    home.filter(|home| !home.is_empty()).map(|home| Found {
        home,
        mode,
        channel,
    })
}

/// What a round needs beyond its arguments: the entry point's world (the runtime over the home, the secrets' backend,
/// the senders, whether recovery is paused, the clock). S7.3d hands the product's; a test its own.
pub trait World {
    /// `Runtime(paths, clock=clock)`; `Err` where it cannot be made.
    fn runtime(&self, paths: &Paths) -> Result<SharedRuntime, ()>;
    fn backend(&self) -> std::sync::Arc<dyn car_platform::credman::Backend>;
    fn opener(&self) -> std::sync::Arc<dyn crate::courier::http::Opener>;
    fn smtp(&self) -> Box<dyn crate::courier::channels::smtp::Wire>;
    fn catalogs(&self) -> &crate::statement::Catalogs;
    fn local(&self) -> &dyn car_machine::localclock::LocalClock;
    /// `_paused(paths)`: whether recovery is paused (None where that cannot be told).
    fn paused(&self, paths: &Paths) -> Option<bool>;
    fn clock(&self) -> f64;
    fn sleep(&self, seconds: f64);
    /// `--serve`'s two roles.
    fn server(&self) -> crate::courier::resident::ServerFactory;
    fn poller(&self) -> crate::courier::resident::Poller;
    /// The home's courier mutex (the resident's for `--serve`), taken: `Err("mutex_busy")` where another holds it.
    fn lock(&self, paths: &Paths, serve: bool) -> Result<Box<dyn std::any::Any>, &'static str>;
    /// `config.Paths(home)`.
    fn paths(&self, home: &str) -> Result<Paths, ()>;
}

/// `check()`: every part a round can need is linked into this program; nothing is read or written.
pub fn check() -> i32 {
    EXIT_DONE
}

/// `main(argv, **seams)`: one round of the courier, as its arguments say; its exit code.
pub fn main_with(argv: &[String], world: &dyn World) -> i32 {
    let Some(found) = parse(argv) else {
        return EXIT_REFUSED;
    };
    let Ok(paths) = world.paths(&found.home) else {
        return EXIT_REFUSED;
    };
    if found.mode == "check" {
        return check();
    }
    let lock = match world.lock(&paths, found.mode == "serve") {
        Ok(lock) => lock,
        Err("mutex_busy") => return EXIT_BUSY,
        Err(_) => return EXIT_REFUSED,
    };
    let done =
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| work(&paths, &found, world)));
    drop(lock);
    match done {
        Ok(Ok(code)) => code,
        _ => EXIT_REFUSED,
    }
}

/// `work(paths, found, **seams)`: the round itself, under the mutex. `Err` is any exception out of it.
pub fn work(paths: &Paths, found: &Found, world: &dyn World) -> Result<i32, ()> {
    use crate::courier::{channels, feed, outbox};
    use crate::vocabulary::ArmingState;
    let runtime = world.runtime(paths)?;
    if found.mode == "serve" {
        let sleep = |seconds: f64| world.sleep(seconds);
        return Ok(crate::courier::resident::serve(
            runtime,
            world.server(),
            world.poller(),
            &sleep,
            None,
        ));
    }
    let states = runtime.states()?;
    let has_push = runtime.registry().get(PUSH).is_some();
    if !has_push && matches!(found.mode, "test" | "pair") {
        return Ok(EXIT_REFUSED);
    }
    let push = states.state_of(PUSH);
    let paused = world.paused(paths);
    let secrets = crate::credentials::Secrets::new(runtime.registry(), world.backend());
    let opener = world.opener();
    let smtp = || world.smtp();
    let seams = channels::Seams {
        opener: opener.as_ref(),
        smtp: &smtp,
        words: channels::Words {
            catalogs: world.catalogs(),
            locale: None,
            local: world.local(),
        },
    };
    if matches!(found.mode, "test" | "pair") {
        if push == ArmingState::Off {
            return Ok(EXIT_REFUSED);
        }
        if found.mode == "test" {
            return Ok(channels::test(
                runtime.as_ref(),
                found.channel.unwrap_or(""),
                &secrets,
                &seams,
            ));
        }
        let clock = || world.clock();
        let sleep = |seconds: f64| world.sleep(seconds);
        return channels::pair(runtime.as_ref(), &secrets, opener.as_ref(), &clock, &sleep)
            .map_err(|_| ());
    }
    if push == ArmingState::Armed && paused == Some(false) {
        channels::drain(runtime.as_ref(), &secrets, &seams, Some(world.clock())).map_err(|_| ())?;
    } else if has_push && let Ok(dropped) = outbox::expire(runtime.state(), world.clock()) {
        for channel in dropped {
            let code = format!("dropped_{}", car_machine::pytext::py_str(&channel));
            let _ = runtime.state().counted(
                &crate::state::sql::string(PUSH),
                &crate::state::sql::string(&code),
                &car_machine::json::Value::Null,
            );
        }
    }
    if found.mode == "feed"
        && runtime.registry().get(FEED).is_some()
        && states.state_of(FEED) == ArmingState::Armed
        && paused == Some(false)
    {
        feed::refresh(runtime.as_ref(), opener.as_ref(), Some(world.clock())).map_err(|_| ())?;
    }
    Ok(EXIT_DONE)
}
