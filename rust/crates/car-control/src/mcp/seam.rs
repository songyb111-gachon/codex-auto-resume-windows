//! The one function of S3.3's `compat/*` the MCP server reads: `compat.mcp_view(view)`, pure, a view in and the summary
//! a model may read out. S5.2 wrote it here behind a seam while car-codex's `compat/*` was another seat's; Integration 8
//! hands it to car-codex's `compat::report::mcp_view`, the one port, and keeps the name the server calls.
//!
//! The view itself is `Host::compat_view` (`compatio.reader_view`; `SystemHost` answers it over car-codex's views).

use car_machine::json::Value;

/// Why the reference's `try` around the summary gave up (its `except Exception`): the summary is then None.
#[derive(Debug, PartialEq, Eq)]
pub struct Unsummarised;

/// `compat.mcp_view(view)`: the compatibility summary a model may read - codes, one small number and one timestamp.
pub fn mcp_view(view: &Value) -> Result<Value, Unsummarised> {
    car_codex::compat::report::mcp_view(view).map_err(|_| Unsummarised)
}
