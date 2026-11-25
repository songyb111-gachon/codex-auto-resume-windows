//! car-surface: the pure halves of the tray, the popup, the notice card and the notifications (PLAN 1.2 row 13, seat
//! S6.0) - what the watcher itself reads of the surfaces the C# watcher host draws (D1, PLAN 1.5).
//!
//! Replaces the implementation, not the behaviour, of the v0.6.26 final's:
//!
//! | here | the reference |
//! |---|---|
//! | `codex_link` | `codex_link.py` |
//! | `notice_uris` | `notice_uris.py` (with `pyurl`: `urllib.parse.urlsplit` and `parse_qs` as CPython 3.13 has them) |
//! | `notice_inbox` | `notice_inbox.py` |
//! | `notice_presence` | `notice_presence.py`'s decision and numbers; its probes are the `seam::Presence` car-platform answers |
//! | `notify` | `notify.py`: every toast's content, the XML document, the constant script and `show` |
//! | `notifier` | `notifier.py` |
//! | `notice_card` | `notice_card.py`: the card's words, layout, motion, stack, floating shadow and corner |
//! | `popup::model` | `ui/popup/model.py`, with the pure parts of `ui/popup/words.py` and `placement.py` it and the card read |
//! | `tray::model`, `tray::stored` | `ui/tray/model.py`, `ui/tray/stored.py` |
//!
//! Nothing here draws, raises or registers anything on the desktop: the card's window and text measure, the icon's
//! thread, the presence probes, the toast's PowerShell and explorer.exe are each a trait of [`seam`], implemented by
//! the C# host or by car-platform. Held to the reference tag by `tests/rustdiff/diffs_surface_*.py`.

pub mod codex_link;
pub mod notice_card;
pub mod notice_inbox;
pub mod notice_presence;
pub mod notice_uris;
pub mod notifier;
pub mod notify;
pub mod popup;
pub mod py;
pub mod pyurl;
pub mod seam;
pub mod speech;
pub mod tray;
pub mod usage;
