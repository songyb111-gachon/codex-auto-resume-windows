//! `engine/`: the capabilities' code that answers at the plug's points, each a module of the Python package's
//! `engine/` (P7-DESIGN 1). The skeleton (seat S7.2a) lists every module of the plan; each file says the seat that owns
//! it (P7-DESIGN 2.2) and holds the `make` its capability's registry entry names (`crate::capabilities::make`). No seat
//! edits this file.

pub mod account;
pub mod admitted;
pub mod analytics;
pub mod anchor;
pub mod autoswitch;
pub mod capacity;
pub mod chat;
pub mod compact;
pub mod continued;
pub mod credits;
pub mod earlyreset;
pub mod emptyreply;
pub mod everyconversation;
pub mod fallback;
pub mod feed;
pub mod fleet;
pub mod foropen;
pub mod goal;
pub mod headless;
pub mod hookclaims;
pub mod keepgoing;
pub mod markerfree;
pub mod oncemore;
pub mod opentarget;
pub mod parallel;
pub mod powertasks;
pub mod promptqueue;
pub mod push;
pub mod remote;
pub mod resetmessage;
pub mod resetwatch;
pub mod retries;
pub mod sessions;
pub mod silent;
pub mod steer;
pub mod subagent;
pub mod supervise;
pub mod updatecheck;
pub mod usage;
pub mod usagestop;
pub mod wake;
pub mod wrapwords;
