//! Seat S7.4: `runtime.py`'s `run_measurement` and `complete_measurement` (the owner's Q2 (a)), over `crate::measure`.
//!
//! The reference keeps the measurement's seams on the runtime (`measure_session_factory=`, `measure_backend=`,
//! `measure_launcher=`, `measure_cli=`, `measure_ipc=`, `measure_hands=`, `evidence_dir=`) and, where one is not given,
//! builds the live one (`measure.live_backend`, `live_session_factory`, `live_launcher`, `live_cli`, `live_ipc`,
//! `live_hands`). Here they are a [`Measuring`] the entry point keeps beside the runtime (`runtime/mod.rs` is S7.2a's),
//! and the live builders are a [`Live`] it hands in: the product's is S7.3d's to write (the real session over
//! car-codex's backend, MW's WMI chain, the hands). Without a `Live`, a seam not given stays absent - the probe then
//! answers as the reference does for a seam that is not there (`no session was provided`, the launcher not wired).

use std::collections::BTreeMap;
use std::path::PathBuf;

use car_config::Paths;
use car_machine::json::{Map, Value};

use super::Runtime;
use crate::measure::{
    self, BackendView, Cli, Hand, Look, Raised, Request, Res, RestartHand, Seams, SessionFactory,
    Timing, World,
};
use crate::vocabulary::{Measurement, Verdict};

/// The product's live builders (`measure.live_*`), and what `_versions` reads of the running product.
pub trait Live {
    fn backend(&mut self, paths: &Paths) -> Option<BackendView>;
    fn session_factory(
        &mut self,
        paths: &Paths,
        backend: Option<&BackendView>,
    ) -> Box<dyn SessionFactory>;
    fn launcher(&mut self, paths: &Paths) -> Look;
    fn cli(&mut self, backend: Option<&BackendView>, paths: &Paths) -> Cli;
    fn ipc(&mut self) -> Look;
    fn hands(&mut self, backend: Option<&BackendView>, paths: &Paths) -> BTreeMap<String, Hand>;
    /// `live_hands`' `codex_restart` (MALR), the one hand handed a callable; None: MALR finds no hand.
    fn restart(&mut self, _backend: Option<&BackendView>, _paths: &Paths) -> Option<RestartHand> {
        None
    }
    /// `config.version()`.
    fn product_version(&self) -> String;
    /// `sys.getwindowsversion()` as `major.minor.build`, or None.
    fn windows_build(&self) -> Option<String>;
}

/// The runtime's measurement seams (`Runtime(..., measure_*=..., evidence_dir=...)`).
#[derive(Default)]
pub struct Measuring {
    pub session_factory: Option<Box<dyn SessionFactory>>,
    pub backend: Option<BackendView>,
    pub launcher: Option<Look>,
    pub cli: Option<Cli>,
    pub ipc: Option<Look>,
    pub hands: Option<BTreeMap<String, Hand>>,
    /// The `codex_restart` hand (given with the hands: a runtime given hands is given this one or none).
    pub restart: Option<RestartHand>,
    pub evidence_dir: Option<PathBuf>,
    pub live: Option<Box<dyn Live>>,
    /// The module's timing constants (the tests patch them in the reference).
    pub timing: Timing,
}

/// The runtime's clock as a measurement's `World`: `time` is the runtime's own (`clock=self.clock`); the monotonic
/// clock, the sleeps and the random ids are the system's (`measure.time`, `uuid.uuid4`).
struct RuntimeClock<'a> {
    runtime: &'a Runtime,
    system: measure::SystemWorld,
}

impl World for RuntimeClock<'_> {
    fn time(&mut self) -> f64 {
        self.runtime.now()
    }
    fn monotonic(&mut self) -> f64 {
        self.system.monotonic()
    }
    fn sleep(&mut self, seconds: f64) {
        self.system.sleep(seconds);
    }
    fn uuid4(&mut self) -> String {
        self.system.uuid4()
    }
}

impl Measuring {
    fn product(&self) -> (String, Option<String>) {
        match &self.live {
            Some(live) => (live.product_version(), live.windows_build()),
            None => ("0.0.0".to_owned(), None),
        }
    }
}

impl Runtime {
    /// `run_measurement(measurement, thread=None, may_spend=False)`.
    pub fn run_measurement(
        &self,
        measuring: &mut Measuring,
        measurement: Measurement,
        thread: Option<&Value>,
        may_spend: bool,
    ) -> Res<Map> {
        let paths = &self.paths;
        let mut backend = measuring.backend.clone();
        // What was given is lent to this run and kept; what the live builders make is made again each run, as the
        // reference's `run_measurement` makes it.
        let given = (
            measuring.session_factory.is_some(),
            measuring.launcher.is_some(),
            measuring.cli.is_some(),
            measuring.ipc.is_some(),
            measuring.hands.is_some(),
        );
        let mut seams = Seams {
            session_factory: measuring.session_factory.take(),
            launcher: measuring.launcher.take(),
            backend: None,
            cli: measuring.cli.take(),
            ipc: measuring.ipc.take(),
            hands: measuring.hands.take().unwrap_or_default(),
            restart: measuring.restart.take(),
            ..Seams::default()
        };
        if let Some(live) = measuring.live.as_mut() {
            if seams.session_factory.is_none() {
                if backend.is_none() {
                    backend = live.backend(paths);
                }
                seams.session_factory = Some(live.session_factory(paths, backend.as_ref()));
            }
            if seams.launcher.is_none() {
                seams.launcher = Some(live.launcher(paths));
            }
            if seams.cli.is_none() {
                seams.cli = Some(live.cli(backend.as_ref(), paths));
            }
            if seams.ipc.is_none() {
                seams.ipc = Some(live.ipc());
            }
            if !given.4 {
                seams.hands = live.hands(backend.as_ref(), paths);
                seams.restart = live.restart(backend.as_ref(), paths);
            }
        }
        seams.backend = backend;
        let (product, windows) = measuring.product();
        let directory = measuring.evidence_dir.clone();
        let request = Request {
            versions: None,
            product_version: &product,
            windows_build: windows.as_deref(),
            thread,
            may_spend,
            directory: directory.as_deref(),
            timing: measuring.timing.clone(),
        };
        let mut clock = RuntimeClock {
            runtime: self,
            system: measure::SystemWorld,
        };
        let answer = measure::run(measurement, &mut seams, request, &mut clock);
        if given.0 {
            measuring.session_factory = seams.session_factory.take();
        }
        if given.1 {
            measuring.launcher = seams.launcher.take();
        }
        if given.2 {
            measuring.cli = seams.cli.take();
        }
        if given.3 {
            measuring.ipc = seams.ipc.take();
        }
        if given.4 {
            measuring.hands = Some(std::mem::take(&mut seams.hands));
            measuring.restart = seams.restart.take();
        }
        answer
    }

    /// `complete_measurement(measurement, verdict, note)`: no session is opened, no process started.
    pub fn complete_measurement(
        &self,
        measuring: &mut Measuring,
        measurement: Measurement,
        verdict: Verdict,
        note: &str,
    ) -> Res<Map> {
        let mut backend = measuring.backend.clone();
        if backend.is_none()
            && measuring.session_factory.is_none()
            && let Some(live) = measuring.live.as_mut()
        {
            backend = live.backend(&self.paths);
        }
        let (product, windows) = measuring.product();
        let directory = measuring.evidence_dir.clone();
        let request = Request {
            versions: None,
            product_version: &product,
            windows_build: windows.as_deref(),
            thread: None,
            may_spend: false,
            directory: directory.as_deref(),
            timing: Timing::default(),
        };
        let mut clock = RuntimeClock {
            runtime: self,
            system: measure::SystemWorld,
        };
        measure::complete(
            measurement,
            verdict,
            note,
            backend.as_ref(),
            request,
            &mut clock,
        )
    }
}

/// What a raised measurement is to a surface: the class (`EvidenceUnavailable`, `EvidenceError`, ...).
pub fn raised_class(raised: &Raised) -> String {
    raised.class()
}
