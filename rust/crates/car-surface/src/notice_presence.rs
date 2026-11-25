//! `notice_presence.py`: may a notification card be drawn right now? One pure decision over the answers Windows gives.
//!
//! The probes themselves (`SHQueryUserNotificationState`, `ToastNotificationManagerForUser.NotificationMode` and
//! `ToastNotifier.Setting` through the WinRT ABI, `SPI_GETSCREENREADER`, `SM_REMOTESESSION`, the input desktop's name,
//! battery saver, `SPI_GETMESSAGEDURATION`) are Windows calls and car-platform's (D3): they are the
//! [`Presence`](crate::seam::Presence) seam. Whenever any answer is "no" or "cannot tell" the notice is the toast.

use car_machine::json::{Map, Value};

use crate::seam::Presence;

// QUERY_USER_NOTIFICATION_STATE
pub const QUNS_NOT_PRESENT: i64 = 1;
pub const QUNS_BUSY: i64 = 2;
pub const QUNS_RUNNING_D3D_FULL_SCREEN: i64 = 3;
pub const QUNS_PRESENTATION_MODE: i64 = 4;
pub const QUNS_ACCEPTS_NOTIFICATIONS: i64 = 5;
pub const QUNS_QUIET_TIME: i64 = 6;
pub const QUNS_APP: i64 = 7;
pub const NOTIFICATION_STATES: [i64; 7] = [1, 2, 3, 4, 5, 6, 7];

// Windows.UI.Notifications.ToastNotificationMode
pub const MODE_UNRESTRICTED: i64 = 0;
pub const MODE_PRIORITY_ONLY: i64 = 1;
pub const MODE_ALARMS_ONLY: i64 = 2;
pub const NOTIFICATION_MODES: [i64; 3] = [0, 1, 2];

// Windows.UI.Notifications.NotificationSetting
pub const APP_ENABLED: i64 = 0;
pub const APP_DISABLED_FOR_APPLICATION: i64 = 1;
pub const APP_DISABLED_FOR_USER: i64 = 2;
pub const APP_DISABLED_BY_GROUP_POLICY: i64 = 3;
pub const APP_DISABLED_BY_MANIFEST: i64 = 4;
pub const APP_SETTINGS: [i64; 5] = [0, 1, 2, 3, 4];

pub const SPI_GETSCREENREADER: u32 = 0x0046;
pub const SPI_GETMESSAGEDURATION: u32 = 0x2016;
pub const SM_REMOTESESSION: i32 = 0x1000;
pub const DESKTOP_READOBJECTS: u32 = 0x0001;
pub const UOI_NAME: i32 = 2;
pub const INPUT_DESKTOP: &str = "Default";

// The WinRT ABI the probes read (car-platform's to call; the numbers are the reference's).
pub const TOAST_MANAGER_CLASS: &str = "Windows.UI.Notifications.ToastNotificationManager";
pub const IID_MANAGER_STATICS: (u32, u16, u16, [u8; 8]) = (
    0x50AC103F,
    0xD235,
    0x4598,
    [0xBB, 0xEF, 0x98, 0xFE, 0x4D, 0x1A, 0x3A, 0xD4],
);
pub const IID_MANAGER_STATICS5: (u32, u16, u16, [u8; 8]) = (
    0xD6F5F569,
    0xD40D,
    0x407C,
    [0x89, 0x89, 0x88, 0xCA, 0xB4, 0x2C, 0xFD, 0x14],
);
pub const IID_MANAGER_FOR_USER3: (u32, u16, u16, [u8; 8]) = (
    0x3EFCB176,
    0x6CC1,
    0x56DC,
    [0x97, 0x3B, 0x25, 0x1F, 0x7A, 0xAC, 0xB1, 0xC5],
);
pub const INSPECTABLE_SLOTS: usize = 6;
pub const SLOT_CREATE_NOTIFIER_WITH_ID: usize = INSPECTABLE_SLOTS + 1;
pub const SLOT_NOTIFIER_SETTING: usize = INSPECTABLE_SLOTS + 2;
pub const RO_INIT_MULTITHREADED: i32 = 1;
pub const RPC_E_CHANGED_MODE: i32 = -2147417850;

/// The probes `card_allowed` reads, in the order `snapshot` keys them (`notifier.PROBES`).
pub const PROBES: [&str; 6] = [
    "notification_state",
    "notification_mode",
    "app_notifications",
    "screen_reader",
    "remote_session",
    "session_locked",
];

/// The answers `card_allowed` takes: each exactly what the reference's caller passes.
#[derive(Clone, Debug)]
pub struct Answers {
    pub setting: Value,
    pub tray_present: Value,
    pub notification_state: Value,
    pub notification_mode: Value,
    pub app_notifications: Value,
    pub screen_reader: Value,
    pub remote_session: Value,
    pub session_locked: Value,
}

impl Answers {
    /// `card_allowed(setting=True, tray_present=True, **{name: answers.get(name) for name in PROBES})`.
    pub fn from_probes(answers: &Map) -> Answers {
        let take = |name: &str| answers.get(name).cloned().unwrap_or(Value::Null);
        Answers {
            setting: Value::Bool(true),
            tray_present: Value::Bool(true),
            notification_state: take("notification_state"),
            notification_mode: take("notification_mode"),
            app_notifications: take("app_notifications"),
            screen_reader: take("screen_reader"),
            remote_session: take("remote_session"),
            session_locked: take("session_locked"),
        }
    }
}

fn exactly(value: &Value, wanted: i64) -> bool {
    matches!(value, Value::Int(int) if int.as_i64() == Some(wanted))
}

/// `card_allowed(...)`: True only when every answer is the one exact value that allows the card - a bool's `is`, an
/// int's `==` and `type(...) is int` - so an unknown (None) or a malformed answer keeps the card away.
pub fn card_allowed(answers: &Answers) -> bool {
    matches!(answers.setting, Value::Bool(true))
        && matches!(answers.tray_present, Value::Bool(true))
        && matches!(answers.screen_reader, Value::Bool(false))
        && matches!(answers.remote_session, Value::Bool(false))
        && matches!(answers.session_locked, Value::Bool(false))
        && exactly(&answers.notification_state, QUNS_ACCEPTS_NOTIFICATIONS)
        && exactly(&answers.notification_mode, MODE_UNRESTRICTED)
        && exactly(&answers.app_notifications, APP_ENABLED)
}

/// `snapshot(aumid)`: the probes read now, through the platform.
pub fn snapshot(presence: &dyn Presence, aumid: &str) -> Map {
    presence.snapshot(aumid)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strict() {
        let mut answers = Answers {
            setting: Value::Bool(true),
            tray_present: Value::Bool(true),
            notification_state: Value::from(5),
            notification_mode: Value::from(0),
            app_notifications: Value::from(0),
            screen_reader: Value::Bool(false),
            remote_session: Value::Bool(false),
            session_locked: Value::Bool(false),
        };
        assert!(card_allowed(&answers));
        answers.notification_mode = Value::Bool(false);
        assert!(!card_allowed(&answers));
        answers.notification_mode = Value::Float(0.0);
        assert!(!card_allowed(&answers));
    }
}
