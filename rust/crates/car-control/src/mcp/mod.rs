//! `mcp/`: the settings panel Codex shows, and the server that hands it over (PLAN 1.2 row 11; seat S5.2).
//!
//! | Python | here |
//! |---|---|
//! | `mcp/tools.py` (the tools, their schemas, the one resource, the plug's tools) | [`tools`] |
//! | `mcp/server.py` (`Server`: the JSON-RPC loop and every tool's body) | [`server`] |
//! | `mcp/panel.py` and `mcp/assets/` (the page) | [`panel`], `assets/` of this crate |
//! | `compat.mcp_view` (S3.3's, behind a seam) | [`seam`] |
//!
//! `mcpserver.py`'s `main` - the command line, the streams and the start with Codex beside the handshake - is
//! `codex-auto-resume.exe mcp` (car-bin).

pub mod panel;
pub mod seam;
pub mod server;
pub mod tools;

pub use server::Server;
