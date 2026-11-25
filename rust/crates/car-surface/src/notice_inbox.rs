//! `notice_inbox.py`: the handover of a notice from any thread to the card host on the icon's thread.
//!
//! The icon's thread owns every window it draws, so nothing else may touch the card. A notice is put here and the
//! host is woken - `wake` posts one message to a window on the icon's thread (the C# host's
//! [`CardHost::wake`](crate::seam::CardHost::wake)), which then calls `take`. `post` says whether the host has it:
//! false when no host is attached, when it has fallen `LIMIT` notices behind, or when it could not be woken, and the
//! caller then raises the toast instead. A notice `post` accepted is the host's to end, including when the host goes
//! away before taking it: `detach` hands those back.

use std::collections::VecDeque;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Mutex, MutexGuard};

/// `wake()`: true when the host was woken.
pub type Wake = Arc<dyn Fn() -> bool + Send + Sync>;

struct Inside<T> {
    waiting: VecDeque<T>,
    wake: Option<Wake>,
}

/// `Inbox`: notices on their way to the card host.
pub struct Inbox<T> {
    inside: Mutex<Inside<T>>,
}

impl<T: Clone + PartialEq> Default for Inbox<T> {
    fn default() -> Self {
        Inbox::new()
    }
}

impl<T: Clone + PartialEq> Inbox<T> {
    pub const LIMIT: usize = 8;

    pub fn new() -> Inbox<T> {
        Inbox {
            inside: Mutex::new(Inside {
                waiting: VecDeque::new(),
                wake: None,
            }),
        }
    }

    fn lock(&self) -> MutexGuard<'_, Inside<T>> {
        self.inside
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// `attach(wake)`: called on the icon's thread once its host window exists.
    pub fn attach(&self, wake: Wake) {
        self.lock().wake = Some(wake);
    }

    /// `detach()`: nothing more is accepted, and what was waiting is handed back, oldest first.
    pub fn detach(&self) -> Vec<T> {
        let mut inside = self.lock();
        inside.wake = None;
        inside.waiting.drain(..).collect()
    }

    /// `attached`.
    pub fn attached(&self) -> bool {
        self.lock().wake.is_some()
    }

    /// `post(notice)`: whether the host has it. A wake that panics is a wake that failed (D15: caught here).
    pub fn post(&self, notice: T) -> bool {
        let wake = {
            let mut inside = self.lock();
            let Some(wake) = inside.wake.clone() else {
                return false;
            };
            if inside.waiting.len() >= Self::LIMIT {
                return false;
            }
            inside.waiting.push_back(notice.clone());
            wake
        };
        let woken = catch_unwind(AssertUnwindSafe(|| wake())).unwrap_or(false);
        if woken {
            return true;
        }
        let mut inside = self.lock();
        match inside.waiting.iter().position(|each| *each == notice) {
            Some(at) => {
                inside.waiting.remove(at);
                false
            }
            // The host took it anyway, woken by an earlier message.
            None => true,
        }
    }

    /// `take()`: everything posted since the last call, oldest first. Called on the icon's thread.
    pub fn take(&self) -> Vec<T> {
        self.lock().waiting.drain(..).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn handover() {
        let inbox: Inbox<i32> = Inbox::new();
        assert!(!inbox.post(1));
        inbox.attach(Arc::new(|| true));
        assert!(inbox.attached());
        for each in 0..8 {
            assert!(inbox.post(each));
        }
        assert!(!inbox.post(9));
        assert_eq!(inbox.take().len(), 8);
        inbox.attach(Arc::new(|| false));
        assert!(!inbox.post(3));
        inbox.attach(Arc::new(|| panic!("a wake that breaks")));
        assert!(!inbox.post(4));
        assert!(inbox.take().is_empty());
        inbox.attach(Arc::new(|| true));
        assert!(inbox.post(5));
        assert_eq!(inbox.detach(), vec![5]);
        assert!(!inbox.attached());
    }
}
