//! `compat/__init__.py`: the Compatibility Registry's front - the model and the data format, what a document says
//! about a version, the report and its views, and what may be done at a tier. Pure: no file, process or network
//! access happens in the model half.
//!
//! Two rules decide every answer: a failed local check always wins, and registry data can never raise a capability
//! above what the local checks allow (`standing::resolve`). The model is car-machine's (cut C3) and `permits` is
//! car-policy's; this front names them where the reference's `compat.X` did. The io half - `files`, `cache`,
//! `probes`, `views`, `evaluator` - is re-exported by [`crate::compatio`] as well, as `compatio.py` re-exports it.

pub mod cache;
pub mod evaluator;
pub mod files;
pub mod probes;
pub mod report;
pub mod reported;
pub mod standing;
pub mod views;

pub use car_machine::compat::model;
pub use car_machine::compat::model::{
    DocumentError, MAX_DOCUMENT_BYTES, decode, parse_document, parse_version, product_key,
    safe_version, validate_document,
};
pub use car_policy::classify::permits::{PERMIT_REASONS, permits};
pub use report::{
    all_unknown, build_report, finite_number, mcp_view, unusable_view, validate_report, view_of,
};
pub use standing::{
    ACCEPTED_CHECKS, accepted_word, aggregate, combine, document_standing, evaluate, evidence_for,
    in_range, resolve, verified_versions,
};
