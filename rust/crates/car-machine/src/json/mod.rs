//! JSON as the Python product writes it, byte for byte (D5, D12).
//!
//! Reading goes through serde_json ([`from_str`]); writing is our own ([`to_string`]), because
//! every bridge answer, MCP reply and state file is what Python's `json.dumps` writes, and
//! serde_json's formatter writes floats, escapes and spacing its own way.
//!
//! The value model is Python's, not serde's:
//!
//! * a [`Str`] is a Python `str`: any code points, lone surrogates included (a settings file's
//!   `"\ud800"` escape, a Windows name that is not whole UTF-16);
//! * an [`Int`] is a Python `int`: i64, u64 or any size beyond, carried as its decimal text;
//! * a [`Map`] keeps the order its keys were inserted in, as a `dict` does.
//!
//! The places the product writes JSON a consumer reads, and the [`Options`] each one is
//! (every one has `allow_nan=False`, which the writer always is):
//!
//! | Python (src/codex_auto_resume/...) | what | options |
//! |---|---|---|
//! | controlcli.py:183, :186 (`encode`), mcp/server.py:126 | every bridge and MCP line | [`Options::wire`] |
//! | codex/appserver.py:248 | requests to `codex app-server` | [`Options::wire`] |
//! | mcp/panel.py:259 | data in the panel's page, then `<` as `\u003c` | [`Options::wire`] |
//! | settings.py:424 (`whole_text`) | can it be saved | [`Options::wire`] |
//! | settings.py:643 | settings.json | `wire().indent(2).sort_keys(true)` |
//! | commands/records.py:88, commands/status.py:349 | the CLI's `--json` | `wire().indent(2)` |
//! | diagnostics.py:312 | the diagnostics bundle | `wire().indent(1)` |
//! | compat/cache.py:127, compat/files.py:63 | the compatibility cache | `wire().separators(",", ":").sort_keys(true)` |
//! | oncewords.py:142 | once-words.json | `wire().sort_keys(true)` |
//! | control/poweraction.py:89, codex/layout.py:159 | power-action.json, the layout file | `new().sort_keys(true)` |
//! | codex/chains.py:87, control/seen.py:40 | chains file, failure-seen.json | [`Options::new`] |
//! | statusfile.py:137 | status.json | `new().indent(2)` |
//! | ownreport/document.py:97 | a community report | `new().indent(2)` |
//! | domain/ids.py:141, :152, domain/usage.py:67, store/watcher.py:45 | hashed ids, heartbeat columns | `new().separators(",", ":")` |
//! | domain/gates.py:314 | the gates column | `new().separators(",", ":").sort_keys(true)` |
//!
//! `json.dump` to a stream (compat/files.py, seen.py, oncewords.py, poweraction.py) runs
//! Python's pure-Python encoder rather than the C one; their bytes are the same.

pub(crate) mod depth;
mod float;
mod read;
mod value;
mod write;

pub use depth::{DUMPS_LIST_LEVELS, DUMPS_OBJECT_LEVELS};
pub use read::{ReadError, from_slice, from_str};
pub use value::{Int, Map, Str, Value};
pub use write::{Error, MAX_INT_DIGITS, Options, to_string};
