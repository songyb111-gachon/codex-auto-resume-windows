//! car-platform: the Windows layer (PLAN 1.2 row 5, seat S3.1).
//!
//! Replaces the implementation, not the behaviour, of the Python reference's `win/*`, `pwsh.py`, `shortcut.py`,
//! `startup.py` and `addremove.py`. D3: every Windows call of the core is made here, through the typed `windows`
//! crate. D15: a panic is caught where Windows calls us back (`power::WakeListener`).
//!
//! | here | the reference |
//! |---|---|
//! | `paths`, `names` | `os.path.normcase`/`realpath`, the object names of `win/sync.py` and `win/homelock.py` |
//! | `cmdline`, `spawn`, `pwsh` | `subprocess.list2cmdline`, every process started (always `CREATE_NO_WINDOW`), `pwsh.py` |
//! | `registry`, `startup`, `addremove`, `registry_reads`, `shortcut` | the registry and shortcut writers, behind a stand-in |
//! | `kernel`, `sync`, `homelock` | `win/kernel.py`, `win/sync.py`, `win/homelock.py`, `win/folderid.py` |
//! | `links` | `Path.is_symlink()` on Windows: the one link probe (a junction is not a link) |
//! | `localclock` | `time.localtime` and `time.mktime`: the C runtime's `_localtime64_s` and `_mktime64` |
//! | `ipc_pipe` | the advanced edition's `codex/ipc.py` pipe calls (a pipe of the caller's name; the Desktop's refused in tests) |
//! | `presence` | `notice_presence.py`'s probes (the pure `card_allowed` is car-surface's) |
//! | `realengine` | (none: the guard that keeps every test away from this PC's installed Codex, `CAR_NO_REAL_ENGINE`) |
//! | `wake` | the advanced edition's `win/waketimer.py` and `win/stopflag.py` calls, behind traits a test fills |
//! | `dpapi`, `credman`, `random` | the advanced edition's `win/dpapi.py`, `credentials.py`'s Credential Manager, `secrets` (S7.2a) |
//! | `restart`, `job`, `winhttp`, `tls` | the advanced edition's Restart Manager (S7.2b), the courier's job object, HTTPS and STARTTLS (S7.3b) |
//! | `network`, `ownprocess`, `power`, `powerdown`, `acl`, `authenticode`, `inventory`, `typeface`, `handover` | the module of the same name in `win/` |
//!
//! Not ported: `win/dll.py` (a cache of ctypes handles and the window-class declarations the C# surfaces use: Rust
//! has no `ctypes`, and the surfaces are C#), `windows.py` (a re-export front over `codex/` and `win/`; the codex
//! half is car-codex's), and the interpreter-only half of `startup.py` (`python_launcher`, PEP 768).

pub mod acl;
pub mod addremove;
pub mod authenticode;
pub mod cmdline;
pub mod credman;
pub mod dpapi;
pub mod files;
pub mod handover;
pub mod homelock;
pub mod inventory;
pub mod ipc_pipe;
pub mod job;
pub mod kernel;
pub mod links;
pub mod localclock;
pub mod names;
pub mod network;
pub mod ownprocess;
pub mod paths;
pub mod power;
pub mod powerdown;
pub mod presence;
#[rustfmt::skip]
mod printable_gen;
pub mod pwsh;
pub mod random;
pub mod realengine;
pub mod registry;
pub mod registry_reads;
pub mod restart;
pub mod shortcut;
pub mod spawn;
pub mod startup;
pub mod sync;
pub mod tls;
pub mod typeface;
pub mod wake;
pub mod widepath;
pub mod winhttp;
