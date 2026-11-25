//! The popup's pure halves: its model (`ui/popup/model.py`), and the parts of `ui/popup/words.py` and
//! `ui/popup/placement.py` the model, the card and the icon read. Its window, renderer, motion and accessibility are
//! the C# host's (D1).

pub mod model;
pub mod placement;
pub mod words;

/// The popup's width in device-independent pixels at 96 DPI: the card and 12 px around it (`layout.WIDTH`).
pub const WIDTH: i64 = 360;
/// The box the state dot sits in, beside the product's name (`layout.MARK`).
pub const MARK: i64 = 22;
/// About thirty frames a second, and only while something moves (`window.FRAME_MS`).
pub const FRAME_MS: i64 = 33;
