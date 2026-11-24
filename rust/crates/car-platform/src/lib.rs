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
//! | `network`, `ownprocess`, `power`, `powerdown`, `acl`, `authenticode`, `inventory`, `typeface`, `handover` | the module of the same name in `win/` |
//!
//! Not ported: `win/dll.py` (a cache of ctypes handles and the window-class declarations the C# surfaces use: Rust
//! has no `ctypes`, and the surfaces are C#), `windows.py` (a re-export front over `codex/` and `win/`; the codex
//! half is car-codex's), and the interpreter-only half of `startup.py` (`python_launcher`, PEP 768).

pub mod acl;
pub mod addremove;
pub mod authenticode;
pub mod cmdline;
pub mod handover;
pub mod homelock;
pub mod inventory;
pub mod kernel;
pub mod names;
pub mod network;
pub mod ownprocess;
pub mod paths;
pub mod power;
pub mod powerdown;
pub mod pwsh;
pub mod registry;
pub mod registry_reads;
pub mod shortcut;
pub mod spawn;
pub mod startup;
pub mod sync;
pub mod typeface;
