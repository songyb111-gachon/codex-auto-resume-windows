//! `notice_presence.py`'s probes: what Windows says about drawing a notification card now (car-surface's
//! `seam::Presence`, D3).
//!
//! Every probe only reads: nothing is written, registered or shown, no window is touched and focus is never moved.
//! Each answers one of the closed values `notice_presence` lists, or `None` for "cannot tell" (which keeps the card
//! away: the toast is raised instead). The pure decision over these answers is car-surface's `card_allowed`.
//!
//! | here | the reference |
//! |---|---|
//! | [`notification_state`] | `SHQueryUserNotificationState`, a value of `NOTIFICATION_STATES` |
//! | [`notification_mode`] | WinRT `ToastNotificationManager.GetDefault().NotificationMode` (IIDs and slots as `notice_presence`'s) |
//! | [`app_notifications`] | WinRT `ToastNotificationManager.CreateToastNotifier(aumid).Setting` (`Show` is never called) |
//! | [`screen_reader`], [`message_duration_ms`] | `SystemParametersInfoW(SPI_GETSCREENREADER / SPI_GETMESSAGEDURATION)` |
//! | [`remote_session`] | `GetSystemMetrics(SM_REMOTESESSION)` |
//! | [`session_locked`] | the input desktop's name is not `Default` (a desktop that cannot be opened is locked) |
//! | [`battery_saver`] | `GetSystemPowerStatus`'s `SystemStatusFlag & 1` |
//!
//! COM comes up multithreaded for each WinRT read, or is used as it is where the thread has it in another mode, and
//! goes down again only where this brought it up (`_WinRT`). Every interface is released and every string deleted on
//! the way out (the `windows` crate's owned types).

use std::ffi::c_void;

use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::Power::{GetSystemPowerStatus, SYSTEM_POWER_STATUS};
use windows::Win32::System::StationsAndDesktops::{
    CloseDesktop, DESKTOP_ACCESS_FLAGS, DESKTOP_CONTROL_FLAGS, GetUserObjectInformationW,
    OpenInputDesktop, UOI_NAME,
};
use windows::Win32::System::WinRT::{
    RO_INIT_MULTITHREADED, RoGetActivationFactory, RoInitialize, RoUninitialize,
};
use windows::Win32::UI::Shell::SHQueryUserNotificationState;
use windows::Win32::UI::WindowsAndMessaging::{
    GetSystemMetrics, SM_REMOTESESSION, SPI_GETSCREENREADER, SYSTEM_PARAMETERS_INFO_ACTION,
    SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS, SystemParametersInfoW,
};
use windows::core::{GUID, HRESULT, HSTRING, IInspectable, Interface};

/// QUERY_USER_NOTIFICATION_STATE: `NOTIFICATION_STATES` (1..=7); 5 is QUNS_ACCEPTS_NOTIFICATIONS.
pub const NOTIFICATION_STATES: [i32; 7] = [1, 2, 3, 4, 5, 6, 7];
/// ToastNotificationMode: Unrestricted, PriorityOnly, AlarmsOnly.
pub const NOTIFICATION_MODES: [i32; 3] = [0, 1, 2];
/// NotificationSetting: Enabled and the four ways it is off.
pub const APP_SETTINGS: [i32; 5] = [0, 1, 2, 3, 4];
const SPI_GETMESSAGEDURATION: u32 = 0x2016;
const DESKTOP_READOBJECTS: u32 = 0x0001;
const INPUT_DESKTOP: &str = "Default";
const TOAST_MANAGER_CLASS: &str = "Windows.UI.Notifications.ToastNotificationManager";
/// RPC_E_CHANGED_MODE: COM is already up on this thread in another mode.
const RPC_E_CHANGED_MODE: HRESULT = HRESULT(0x8001_0106_u32 as i32);

// The WinRT interfaces, by identifier and vtable slot as `notice_presence` reads them (each slot after IInspectable's
// six, in the declaration order read from the system's own metadata; both reads checked against PowerShell's projection
// there). Only these slots are ever called: `IToastNotifier.Show` (slot 6) never is.
/// IToastNotificationManagerStatics: `CreateToastNotifierWithId(HSTRING)` is slot 7.
const IID_MANAGER_STATICS: GUID = GUID::from_u128(0x50AC103F_D235_4598_BBEF_98FE4D1A3AD4);
/// IToastNotificationManagerStatics5: `GetDefault()` is slot 6.
const IID_MANAGER_STATICS5: GUID = GUID::from_u128(0xD6F5F569_D40D_407C_8989_88CAB42CFD14);
/// IToastNotificationManagerForUser3: `get_NotificationMode` is slot 6.
const IID_MANAGER_FOR_USER3: GUID = GUID::from_u128(0x3EFCB176_6CC1_56DC_973B_251F7AACB1C5);
const INSPECTABLE_SLOTS: usize = 6;
const SLOT_CREATE_NOTIFIER_WITH_ID: usize = INSPECTABLE_SLOTS + 1;
/// IToastNotifier: after `Show` and `Hide`.
const SLOT_NOTIFIER_SETTING: usize = INSPECTABLE_SLOTS + 2;

/// A COM method by its vtable slot (`_method`): `this` first, an HRESULT back.
///
/// # Safety
/// `object` must be a live interface whose vtable has `slot`, and `F` that slot's signature.
unsafe fn method<F: Copy>(object: &IInspectable, slot: usize) -> F {
    // SAFETY: the caller's; a COM object's first field is its vtable pointer.
    unsafe {
        let table = *(object.as_raw() as *const *const *const c_void);
        std::mem::transmute_copy(&*table.add(slot))
    }
}

/// `QueryInterface(iid)` on `object`: the interface asked for, owned (released when dropped).
fn query(object: &IInspectable, iid: &GUID) -> Option<IInspectable> {
    let mut found: *mut c_void = std::ptr::null_mut();
    // SAFETY: a live interface; `found` is written by the call before it is read.
    let answer = unsafe { object.query(iid, &mut found) };
    if answer.is_err() || found.is_null() {
        return None;
    }
    // SAFETY: QueryInterface handed out one reference, now this value's.
    Some(unsafe { IInspectable::from_raw(found) })
}

/// The activation factory of the toast manager, as the interface `iid` (`RoGetActivationFactory`).
fn factory(iid: &GUID) -> Option<IInspectable> {
    let class = HSTRING::from(TOAST_MANAGER_CLASS);
    // SAFETY: the class name outlives the call; the factory is owned.
    let any: IInspectable = unsafe { RoGetActivationFactory(&class) }.ok()?;
    query(&any, iid)
}

type OutPointer = unsafe extern "system" fn(*mut c_void, *mut *mut c_void) -> HRESULT;
type WithIdOut = unsafe extern "system" fn(*mut c_void, *mut c_void, *mut *mut c_void) -> HRESULT;
type OutInt = unsafe extern "system" fn(*mut c_void, *mut i32) -> HRESULT;

/// `notification_state()`: one of [`NOTIFICATION_STATES`], or None when Windows could not be asked.
pub fn notification_state() -> Option<i32> {
    // SAFETY: a plain query of the shell; the answer is written by value.
    let state = unsafe { SHQueryUserNotificationState() }.ok()?;
    NOTIFICATION_STATES.contains(&state.0).then_some(state.0)
}

/// One WinRT read on this thread (`_WinRT`): COM up for it where this brought it up, down again after.
fn with_winrt<T>(read: impl FnOnce() -> Option<T>) -> Option<T> {
    // SAFETY: RoInitialize on the calling thread, balanced below only where it succeeded.
    let started = unsafe { RoInitialize(RO_INIT_MULTITHREADED) };
    let ours = match started {
        Ok(()) => true,
        Err(error) if error.code() == RPC_E_CHANGED_MODE => false,
        Err(_) => return None,
    };
    let answer = read();
    if ours {
        // SAFETY: balances the RoInitialize above, after every interface of the read was released.
        unsafe { RoUninitialize() };
    }
    answer
}

/// `notification_mode()`: one of [`NOTIFICATION_MODES`] (Do not disturb and Focus are not Unrestricted), or None.
pub fn notification_mode() -> Option<i32> {
    with_winrt(|| {
        let statics = factory(&IID_MANAGER_STATICS5)?;
        let mut manager: *mut c_void = std::ptr::null_mut();
        // SAFETY: slot 6 of IToastNotificationManagerStatics5 is GetDefault(out manager).
        let get_default: OutPointer = unsafe { method(&statics, INSPECTABLE_SLOTS) };
        // SAFETY: `manager` is written before it is read.
        unsafe { get_default(statics.as_raw(), &mut manager) }
            .ok()
            .ok()?;
        if manager.is_null() {
            return None;
        }
        // SAFETY: GetDefault handed out one reference, now this value's.
        let manager = unsafe { IInspectable::from_raw(manager) };
        let modes = query(&manager, &IID_MANAGER_FOR_USER3)?;
        let mut mode = -1i32;
        // SAFETY: slot 6 of IToastNotificationManagerForUser3 is get_NotificationMode(out int).
        let get_mode: OutInt = unsafe { method(&modes, INSPECTABLE_SLOTS) };
        // SAFETY: `mode` is ours.
        unsafe { get_mode(modes.as_raw(), &mut mode) }.ok().ok()?;
        NOTIFICATION_MODES.contains(&mode).then_some(mode)
    })
}

/// `app_notifications(aumid)`: one of [`APP_SETTINGS`] - Windows' own "may this app notify" - or None (no identity
/// to ask about, a Windows without the call, any failure). A notifier object is made and asked one property; nothing
/// is shown, registered or changed.
pub fn app_notifications(aumid: Option<&str>) -> Option<i32> {
    let aumid = aumid.filter(|text| !text.trim().is_empty())?;
    with_winrt(|| {
        let statics = factory(&IID_MANAGER_STATICS)?;
        let id = HSTRING::from(aumid);
        let mut notifier: *mut c_void = std::ptr::null_mut();
        // SAFETY: slot 7 of IToastNotificationManagerStatics is CreateToastNotifierWithId(HSTRING, out notifier).
        let create: WithIdOut = unsafe { method(&statics, SLOT_CREATE_NOTIFIER_WITH_ID) };
        // SAFETY: the identity's HSTRING outlives the call (passed as its ABI handle); `notifier` is written first.
        unsafe {
            create(
                statics.as_raw(),
                std::mem::transmute_copy(&id),
                &mut notifier,
            )
        }
        .ok()
        .ok()?;
        if notifier.is_null() {
            return None;
        }
        // SAFETY: the call handed out one reference, now this value's.
        let notifier = unsafe { IInspectable::from_raw(notifier) };
        let mut setting = -1i32;
        // SAFETY: slot 8 of IToastNotifier is get_Setting(out int).
        let get_setting: OutInt = unsafe { method(&notifier, SLOT_NOTIFIER_SETTING) };
        // SAFETY: `setting` is ours.
        unsafe { get_setting(notifier.as_raw(), &mut setting) }
            .ok()
            .ok()?;
        APP_SETTINGS.contains(&setting).then_some(setting)
    })
}

fn parameter_u32(action: u32) -> Option<u32> {
    let mut value = 0u32;
    // SAFETY: the buffer is a u32 of ours, as both actions write.
    unsafe {
        SystemParametersInfoW(
            SYSTEM_PARAMETERS_INFO_ACTION(action),
            0,
            Some(std::ptr::from_mut(&mut value).cast()),
            SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0),
        )
    }
    .ok()
    .map(|()| value)
}

/// `screen_reader()`: True while a screen reader says it is running, False when none is, None if unknown.
pub fn screen_reader() -> Option<bool> {
    parameter_u32(SPI_GETSCREENREADER.0).map(|value| value != 0)
}

/// `remote_session()`: True in a Remote Desktop session, False at the console.
pub fn remote_session() -> Option<bool> {
    // SAFETY: a plain metric.
    Some(unsafe { GetSystemMetrics(SM_REMOTESESSION) } != 0)
}

/// `session_locked()`: True unless the desktop receiving input is the user's own `Default` desktop; one that cannot be
/// opened or named (the lock screen, the sign-in screen, an elevation prompt's) reads as locked.
pub fn session_locked() -> Option<bool> {
    // SAFETY: the desktop handle is closed below; the name buffer is ours.
    unsafe {
        let Ok(desktop) = OpenInputDesktop(
            DESKTOP_CONTROL_FLAGS(0),
            false,
            DESKTOP_ACCESS_FLAGS(DESKTOP_READOBJECTS),
        ) else {
            return Some(true);
        };
        let mut buffer = [0u16; 64];
        let mut needed = 0u32;
        let named = GetUserObjectInformationW(
            HANDLE(desktop.0),
            UOI_NAME,
            Some(buffer.as_mut_ptr().cast()),
            std::mem::size_of_val(&buffer) as u32,
            Some(&mut needed),
        );
        let _ = CloseDesktop(desktop);
        if named.is_err() {
            return Some(true);
        }
        let length = buffer
            .iter()
            .position(|unit| *unit == 0)
            .unwrap_or(buffer.len());
        let name = String::from_utf16_lossy(&buffer[..length]);
        Some(name.to_lowercase() != INPUT_DESKTOP.to_lowercase())
    }
}

/// `battery_saver()`: True while Windows' battery saver is on; False where it cannot say.
pub fn battery_saver() -> bool {
    let mut status = SYSTEM_POWER_STATUS::default();
    // SAFETY: the structure is ours.
    unsafe { GetSystemPowerStatus(&mut status) }.is_ok() && status.SystemStatusFlag & 1 != 0
}

/// `message_duration_ms()`: Windows' "Dismiss notifications after this amount of time", in ms, or None.
pub fn message_duration_ms() -> Option<i64> {
    parameter_u32(SPI_GETMESSAGEDURATION)
        .filter(|seconds| *seconds != 0)
        .map(|seconds| i64::from(seconds) * 1000)
}

/// `snapshot(aumid)`'s six answers, each None for "cannot tell".
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Snapshot {
    pub notification_state: Option<i32>,
    pub notification_mode: Option<i32>,
    pub app_notifications: Option<i32>,
    pub screen_reader: Option<bool>,
    pub remote_session: Option<bool>,
    pub session_locked: Option<bool>,
}

/// `snapshot(aumid)`: the probes `card_allowed` reads, read now. Without an identity Windows cannot be asked about
/// this app, and that answer is "cannot tell".
pub fn snapshot(aumid: Option<&str>) -> Snapshot {
    Snapshot {
        notification_state: notification_state(),
        notification_mode: notification_mode(),
        app_notifications: app_notifications(aumid),
        screen_reader: screen_reader(),
        remote_session: remote_session(),
        session_locked: session_locked(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_probe_answers_a_closed_value_or_cannot_tell() {
        let found = snapshot(Some("CodexAutoResume.Watcher"));
        eprintln!(
            "presence here: {found:?}, battery saver {}, duration {:?}",
            battery_saver(),
            message_duration_ms()
        );
        if let Some(state) = found.notification_state {
            assert!(NOTIFICATION_STATES.contains(&state));
        }
        if let Some(mode) = found.notification_mode {
            assert!(NOTIFICATION_MODES.contains(&mode));
        }
        if let Some(setting) = found.app_notifications {
            assert!(APP_SETTINGS.contains(&setting));
        }
        assert_eq!(app_notifications(None), None);
        assert_eq!(app_notifications(Some("  ")), None);
        let _ = battery_saver();
        if let Some(ms) = message_duration_ms() {
            assert!(ms >= 1000 && ms % 1000 == 0);
        }
    }

    #[test]
    fn the_winrt_reads_answer_on_a_thread_that_has_com_in_another_mode() {
        // An STA thread (the icon's would be one): RoInitialize answers RPC_E_CHANGED_MODE and the read goes on.
        std::thread::spawn(|| {
            // SAFETY: this thread's own apartment, left up until the thread ends.
            let _ = unsafe { RoInitialize(windows::Win32::System::WinRT::RO_INIT_SINGLETHREADED) };
            let mode = notification_mode();
            assert!(mode.is_none_or(|mode| NOTIFICATION_MODES.contains(&mode)));
        })
        .join()
        .unwrap();
    }
}
