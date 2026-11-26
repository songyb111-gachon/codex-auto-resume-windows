//! car-watcher: the watcher runtime (P6-DESIGN 2.1, seat S6.1) - `runtime/` of the v0.6.26 final, with `checkup.py`,
//! `rescan.py`, `setaside.py` and the logic of `scripts/watcher_launcher.py`.
//!
//! Every Windows call is car-platform's; everything the watcher asks of the machine goes through a trait here (a
//! "port", as the reference's modules take a `port=` and a `clock=`), so a test runs any of it with a world of its own:
//! no named object of the product's, no timer, no window.

pub mod afterwork;
pub mod api;
pub mod app;
pub mod checkup;
pub mod clock;
pub mod events;
pub mod fail;
pub mod health;
pub mod homes;
pub mod join;
pub mod launcher;
pub mod plugnotices;
pub mod rescan;
pub mod setaside;
pub mod surface;
pub mod toasts;
pub mod trip;
pub mod waking;
pub mod watchloop;
