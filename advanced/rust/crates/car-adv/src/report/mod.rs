//! The in-app compatibility report (`report/`, seat S7.3c): this PC's own records, written up as codex-compat-reporter
//! writes them, for the person to read whole and, only if they type send, send to the project.
//!
//! | Python | here |
//! |---|---|
//! | `report/records.py` | [`records`]: the files read for it, read-only |
//! | core's `ownreport/evidence.py`, `reading.py` | [`evidence`], [`reading`]: what those records say, counted as the reporter counts them; the state, logs and engine |
//! | `report/document.py` and the part of core's `ownreport/document.py` it imports | [`document`]: the file, and the self-check every report passes |
//! | `report/github.py` | [`github`]: gh, the GitHub CLI the person installed |
//! | `report/flow.py` | [`flow`]: the Dashboard's jobs - write, check, send |
//!
//! The seams (rust/GROUNDWORK.md, "Seat S7.3c"): [`reading::WatcherView`] (S3.3's `compatio.reader_view`),
//! [`document::Facts`] (`config.version()`, `sys.getwindowsversion()`), and for the flow the runtime and the mutex.

pub mod document;
pub mod evidence;
pub mod flow;
pub mod github;
pub mod reading;
pub mod records;
pub mod seam;
