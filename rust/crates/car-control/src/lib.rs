//! car-control: the layer every surface asks, and the bridge over it (PLAN 1.2 row 11; seat S5.1a).
//!
//! The quiet half: the commands whose answer is read from the state, the settings, the store, Codex's files and
//! the vocabulary, without the engine acting, the watcher running or a process starting.
//!
//! | Python | here |
//! |---|---|
//! | `controlcli.py` (framing, `PLAIN`, `WITH_ARGUMENT`, `dispatch`, `serve`) | [`bridge`], [`commands`] |
//! | `control/errors.py` | [`error`] |
//! | `control/layer.py`, `state.py`, `policy.py` | [`layer`], [`aside`] |
//! | `control/seen.py` | [`seen`] |
//! | the outside world (clock, Windows, policy keys) | [`host`] |

pub mod actions;
pub mod aside;
pub mod bridge;
pub mod codexstart;
pub mod commands;
pub mod compat;
pub mod diagnostics;
pub mod error;
pub mod homefind;
pub mod host;
pub mod layer;
pub mod lifecycle;
pub mod localclock;
pub mod mcp;
pub mod oncewords;
pub mod ownreport;
pub mod power;
pub mod preview;
pub mod records;
pub mod seen;
pub mod status;
pub mod tools;

pub use error::{ControlError, Failure};
pub use layer::Control;
