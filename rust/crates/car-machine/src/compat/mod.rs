//! `codex_auto_resume/compat/model.py` (cut C3: the registry's data types live here, below car-policy and car-codex).

mod decode;
pub mod model;

pub use decode::{
    DocumentError, LOADS_LIST_LEVELS, LOADS_OBJECT_LEVELS, LoadsError, MAX_DOCUMENT_BYTES, decode,
    loads, raw_decode,
};
