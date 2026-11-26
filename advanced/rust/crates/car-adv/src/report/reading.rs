//! `ownreport/reading.py` (core's, which the advanced report reads through): car-control's `ownreport::reading`, the
//! one port of it. Integration 8 folded S7.3c's copy into car-control: the functions `records.py` imports take the home's
//! `Paths`, the local clock and the watcher's report ([`WatcherView`], the seam S3.3's `compatio.reader_view` fills) as
//! arguments there, so no `Control` is needed here; this module re-exports them under the name `report/` uses.

pub use car_control::ownreport::reading::*;
