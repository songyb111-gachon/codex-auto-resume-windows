//! `courier/`: the notification courier and the remote reach (seat S7.3b, P7-DESIGN 1), the one module family that
//! talks to a network. `main` is `courier/__main__.py`; `courier/pythonorg.py` is retired (D8). The skeleton (seat S7.2a)
//! lists every module; no seat edits this file.

pub mod address;
pub mod api;
pub mod channels;
pub mod feed;
pub mod http;
pub mod keep;
pub mod launch;
pub mod main;
pub mod outbox;
pub mod page;
pub mod resident;
pub mod telegram;
