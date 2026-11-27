//! The kernel objects this product opens, and what Windows has wrapped it in (`win/kernel.py`).
//!
//! `process_context` is the one that matters: a watcher started from inside a job object that kills on close dies
//! when whatever opened it closes, which is how Codex ends the MCP servers its plugins start. The rest are the
//! handles and the integrity check every named object here is opened through.

use std::collections::HashMap;

use windows::Win32::Foundation::{
    CloseHandle, HANDLE, HLOCAL, LocalFree, WAIT_TIMEOUT, WIN32_ERROR,
};
use windows::Win32::Security::Authorization::{
    ConvertSidToStringSidW, GetSecurityInfo, SE_KERNEL_OBJECT,
};
use windows::Win32::Security::{
    ACL, GetAce, GetSidSubAuthority, GetSidSubAuthorityCount, GetTokenInformation,
    LABEL_SECURITY_INFORMATION, OWNER_SECURITY_INFORMATION, PSECURITY_DESCRIPTOR, PSID,
    TOKEN_INFORMATION_CLASS, TOKEN_USER,
};
use windows::Win32::Storage::Packaging::Appx::{
    GetCurrentPackageFamilyName, GetCurrentPackageFullName, GetPackageFamilyName,
    GetPackagePathByFullName, GetPackagesByPackageFamily,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, PROCESSENTRY32W, Process32FirstW, Process32NextW, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::JobObjects::{
    IsProcessInJob, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
    QueryInformationJobObject,
};
use windows::Win32::System::Threading::{
    GetCurrentProcess, GetCurrentProcessId, GetProcessTimes, OpenProcess, PROCESS_ACCESS_RIGHTS,
    PROCESS_NAME_WIN32, QueryFullProcessImageNameW, WaitForSingleObject,
};
use windows::core::{PCWSTR, PWSTR};

use car_machine::domain::errors::AdapterError;

pub use crate::spawn::{CREATE_BREAKAWAY_FROM_JOB, CREATE_NO_WINDOW as NO_WINDOW};

// The job-object limit bits `process_context` reports, and the error that says "no package".
pub const JOB_BREAKAWAY_OK: u32 = 0x0800;
pub const JOB_SILENT_BREAKAWAY_OK: u32 = 0x1000;
pub const JOB_KILL_ON_CLOSE: u32 = 0x2000;
pub const APPMODEL_ERROR_NO_PACKAGE: u32 = 15700;

pub const HOST_MAX_STEPS: usize = 32;
const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
/// 100-ns intervals between 1601-01-01 (FILETIME) and 1970-01-01 (the epoch).
const EPOCH_AS_FILETIME: i64 = 116_444_736_000_000_000;
pub const INSIDE: &str = "inside";
pub const OUTSIDE: &str = "outside";
pub const UNKNOWN: &str = "unknown";

pub const ERROR_ALREADY_EXISTS: u32 = 183;
pub const SECURITY_MANDATORY_MEDIUM_RID: u32 = 0x2000;
const SYSTEM_MANDATORY_LABEL_ACE_TYPE: u8 = 0x11;
/// Owners an existing object may have and still be this account's own: the computer's administrators and Windows.
pub const TRUSTED_OWNERS: [&str; 2] = ["S-1-5-32-544", "S-1-5-18"];

fn close(handle: HANDLE) {
    // SAFETY: a handle this module opened.
    unsafe {
        let _ = CloseHandle(handle);
    }
}

fn filetime(low: u32, high: u32) -> u64 {
    (u64::from(high) << 32) | u64::from(low)
}

/// An identity of a live process: its id, its image (lower case) and when it was created (a FILETIME).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessIdentity {
    pub pid: u32,
    pub path: String,
    pub created: u64,
}

/// `process_identity`: the process must be alive (not signalled).
pub fn process_identity(pid: u32) -> Result<ProcessIdentity, AdapterError> {
    // SAFETY: plain query call.
    let handle = unsafe { OpenProcess(PROCESS_ACCESS_RIGHTS(0x101000), false, pid) }
        .map_err(|_| AdapterError("process_identity_unavailable"))?;
    let result = (|| {
        // SAFETY: the handle is ours.
        if unsafe { WaitForSingleObject(handle, 0) } != WAIT_TIMEOUT {
            return Err(AdapterError("process_exited"));
        }
        let path = image_of(handle).ok_or(AdapterError("process_path_unavailable"))?;
        let created = process_created(handle).ok_or(AdapterError("process_time_unavailable"))?;
        Ok(ProcessIdentity {
            pid,
            path: path.to_lowercase(),
            created,
        })
    })();
    close(handle);
    result
}

fn image_of(handle: HANDLE) -> Option<String> {
    let mut buffer = vec![0u16; 32768];
    let mut size = buffer.len() as u32;
    // SAFETY: the buffer is ours and as long as `size` says.
    unsafe {
        QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            PWSTR(buffer.as_mut_ptr()),
            &mut size,
        )
    }
    .ok()?;
    let text = String::from_utf16_lossy(&buffer[..size as usize]);
    (!text.is_empty()).then_some(text)
}

fn process_created(handle: HANDLE) -> Option<u64> {
    let mut times = [windows::Win32::Foundation::FILETIME::default(); 4];
    let [creation, exit, kernel, user] = &mut times;
    // SAFETY: four FILETIMEs of our own.
    unsafe { GetProcessTimes(handle, creation, exit, kernel, user) }.ok()?;
    Some(filetime(times[0].dwLowDateTime, times[0].dwHighDateTime))
}

/// What Windows has wrapped this process in: a job object and its limits, and a package. Each field is None where
/// Windows would not say.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct ProcessContext {
    pub in_job: Option<bool>,
    pub kill_on_close: Option<bool>,
    pub breakaway_ok: Option<bool>,
    pub silent_breakaway_ok: Option<bool>,
    pub packaged: Option<bool>,
}

/// `process_context`: content-free by construction (booleans). Only the immediate job is read.
pub fn process_context() -> ProcessContext {
    let mut facts = ProcessContext::default();
    let mut inside = windows::core::BOOL(0);
    // SAFETY: the pseudo handle of this process and a BOOL of our own.
    if unsafe { IsProcessInJob(GetCurrentProcess(), None, &mut inside) }.is_ok() {
        facts.in_job = Some(inside.as_bool());
    }
    match facts.in_job {
        Some(false) => {
            facts.kill_on_close = Some(false);
            facts.breakaway_ok = Some(false);
            facts.silent_breakaway_ok = Some(false);
        }
        Some(true) => {
            let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
            // 9 is JobObjectExtendedLimitInformation; a NULL job is the caller's own.
            // SAFETY: the structure is ours and as large as the size passed.
            let asked = unsafe {
                QueryInformationJobObject(
                    None,
                    JobObjectExtendedLimitInformation,
                    &mut limits as *mut _ as *mut _,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                    None,
                )
            };
            if asked.is_ok() {
                let flags = limits.BasicLimitInformation.LimitFlags.0;
                facts.kill_on_close = Some(flags & JOB_KILL_ON_CLOSE != 0);
                facts.breakaway_ok = Some(flags & JOB_BREAKAWAY_OK != 0);
                facts.silent_breakaway_ok = Some(flags & JOB_SILENT_BREAKAWAY_OK != 0);
            }
        }
        None => {}
    }
    let mut length = 0u32;
    // SAFETY: asks the length only.
    let answer = unsafe { GetCurrentPackageFullName(&mut length, None) };
    facts.packaged = Some(answer.0 != APPMODEL_ERROR_NO_PACKAGE);
    facts
}

// ------------------------------------------------------------------------------ inside another app (v0.6.17)

/// `(parent id, creation FILETIME - 0 where it could not be opened - and package family name or None)`.
pub type HostRow = (u32, u64, Option<String>);

/// The package family name of `start`, or of its nearest live ancestor that has one, or None
/// (`gui/HostApp.cs` `Decide`, line for line). Pure.
pub fn decide_host(start: u32, table: &HashMap<u32, HostRow>) -> Option<String> {
    let mut row = table.get(&start)?;
    if let Some(family) = &row.2 {
        return Some(family.clone());
    }
    let mut seen = vec![start];
    for _step in 0..HOST_MAX_STEPS {
        let parent = table.get(&row.0)?;
        if parent.1 == 0 {
            return None;
        }
        if seen.contains(&row.0) {
            return None;
        }
        seen.push(row.0);
        if parent.1 > row.1 {
            return None;
        }
        if let Some(family) = &parent.2 {
            return Some(family.clone());
        }
        row = parent;
    }
    None
}

/// The app's name for a person: the family name without its publisher id ("OpenAI.Codex").
pub fn app_name(family: Option<&str>) -> String {
    let Some(family) = family.filter(|f| !f.is_empty()) else {
        return String::new();
    };
    match family.rfind('_') {
        Some(cut) if cut > 0 => family[..cut].to_string(),
        _ => family.to_string(),
    }
}

/// `ERROR_INSUFFICIENT_BUFFER`: what the package calls answer when asked for the size first.
pub const ERROR_INSUFFICIENT_BUFFER: u32 = 122;

/// A wide string up to its first NUL (`ctypes`' `.value` of a buffer or an `LPWSTR`).
fn wide_value(buffer: &[u16]) -> String {
    let end = buffer
        .iter()
        .position(|unit| *unit == 0)
        .unwrap_or(buffer.len());
    String::from_utf16_lossy(&buffer[..end])
}

/// `package_roots(family)` (v0.6.26 final, live acceptance R2b): the folder of every package of the family `family`
/// installed for this account, as Windows' package manager names it (GetPackagesByPackageFamily, then
/// GetPackagePathByFullName for each full name), whether or not any process of the package runs. Nothing is opened,
/// read or started - the two calls ask the account's package repository - and nothing is answered where the family
/// has no package, or the list changed between the calls. Never an error on Windows (the reference raises
/// AdapterError only off Windows; a Windows without the two calls, before 8, is not one this product runs on).
pub fn package_roots(family: &str) -> Vec<String> {
    let name: Vec<u16> = family.encode_utf16().chain(std::iter::once(0)).collect();
    let mut count: u32 = 0;
    let mut length: u32 = 0;
    // SAFETY: the size query: no buffers, two counts this frame owns.
    let first = unsafe {
        GetPackagesByPackageFamily(pcwstr(&name), &raw mut count, None, &raw mut length, None)
    };
    if first.0 != ERROR_INSUFFICIENT_BUFFER || count == 0 || length == 0 {
        return Vec::new();
    }
    let mut names: Vec<PWSTR> = vec![PWSTR::null(); count as usize];
    let mut buffer: Vec<u16> = vec![0; length as usize];
    // SAFETY: `names` holds `count` pointers and `buffer` `length` units, the sizes the first call asked for; the
    // call writes no more than the counts it is given and answers ERROR_INSUFFICIENT_BUFFER where they grew.
    let second = unsafe {
        GetPackagesByPackageFamily(
            pcwstr(&name),
            &raw mut count,
            Some(names.as_mut_ptr()),
            &raw mut length,
            Some(PWSTR(buffer.as_mut_ptr())),
        )
    };
    if second.0 != 0 {
        return Vec::new();
    }
    let mut found = Vec::new();
    for each in names.iter().take(count as usize) {
        if each.is_null() {
            continue;
        }
        let mut size: u32 = 0;
        // SAFETY: `each` points into `buffer`, a NUL-terminated full name the second call wrote.
        let asked = unsafe { GetPackagePathByFullName(PCWSTR(each.0), &raw mut size, None) };
        if asked.0 != ERROR_INSUFFICIENT_BUFFER || size == 0 {
            continue;
        }
        let mut path: Vec<u16> = vec![0; size as usize];
        // SAFETY: `path` holds the `size` units the size query asked for.
        let answered = unsafe {
            GetPackagePathByFullName(
                PCWSTR(each.0),
                &raw mut size,
                Some(PWSTR(path.as_mut_ptr())),
            )
        };
        let value = wide_value(&path);
        if answered.0 == 0 && !value.is_empty() {
            found.push(value);
        }
    }
    found
}

/// `[A-Za-z0-9.\-]{1,64}_[a-z0-9]{13}\Z`.
fn is_family(text: &str) -> bool {
    let Some(cut) = text.len().checked_sub(14) else {
        return false;
    };
    if !text.is_char_boundary(cut) {
        return false;
    }
    let (name, tail) = text.split_at(cut);
    let Some(id) = tail.strip_prefix('_') else {
        return false;
    };
    (1..=64).contains(&name.len())
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
        && id.len() == 13
        && id
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
}

/// `{"state", "family", "app"}` of `host_verdict`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HostVerdict {
    pub state: &'static str,
    pub family: Option<String>,
    pub app: Option<String>,
}

fn unknown_host() -> HostVerdict {
    HostVerdict {
        state: UNKNOWN,
        family: None,
        app: None,
    }
}

/// The verdict for the process `start` over `table`: INSIDE with the app's family name and name, OUTSIDE, or UNKNOWN
/// where `start` itself is not in the table or could not be opened - or, given `started_by` (the epoch second the
/// process says it started), was created after it. Pure.
pub fn host_verdict(
    start: u32,
    table: &HashMap<u32, HostRow>,
    started_by: Option<f64>,
) -> HostVerdict {
    let Some(row) = table.get(&start) else {
        return unknown_host();
    };
    if row.1 == 0 {
        return unknown_host();
    }
    if started_by
        .is_some_and(|started| (row.1 as i64 - EPOCH_AS_FILETIME) as f64 / 1e7 > started + 2.0)
    {
        return unknown_host();
    }
    let Some(family) = decide_host(start, table) else {
        return HostVerdict {
            state: OUTSIDE,
            family: None,
            app: None,
        };
    };
    let family = is_family(&family).then_some(family);
    let app = app_name(family.as_deref());
    HostVerdict {
        state: INSIDE,
        family,
        app: (!app.is_empty()).then_some(app),
    }
}

/// (process id, parent id, program file name) of every process, from one Toolhelp snapshot; empty where none can be
/// made.
fn toolhelp() -> Vec<(u32, u32, String)> {
    // SAFETY: a snapshot handle closed below.
    let Ok(snapshot) = (unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) }) else {
        return Vec::new();
    };
    let mut found = Vec::new();
    let mut entry = PROCESSENTRY32W {
        dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    // SAFETY: `entry` is ours with its size set.
    let mut more = unsafe { Process32FirstW(snapshot, &mut entry) }.is_ok();
    while more {
        found.push((
            entry.th32ProcessID,
            entry.th32ParentProcessID,
            crate::paths::from_wide(&entry.szExeFile),
        ));
        // SAFETY: as above.
        more = unsafe { Process32NextW(snapshot, &mut entry) }.is_ok();
    }
    close(snapshot);
    found
}

fn open_limited(pid: u32) -> Option<HANDLE> {
    // SAFETY: plain query call.
    unsafe {
        OpenProcess(
            PROCESS_ACCESS_RIGHTS(PROCESS_QUERY_LIMITED_INFORMATION),
            false,
            pid,
        )
    }
    .ok()
}

/// The full path of the program file process `pid` runs, or None where it cannot be opened for limited query.
pub fn process_image(pid: u32) -> Option<String> {
    let handle = open_limited(pid)?;
    let image = image_of(handle);
    close(handle);
    image
}

/// The program file of every process this account may look at, each a full path in lower case - or None where the
/// list cannot be made.
pub fn running_images() -> Option<Vec<String>> {
    let processes = toolhelp();
    if processes.is_empty() {
        return None;
    }
    let mut found = Vec::new();
    for (pid, _, _) in processes {
        if pid == 0 {
            continue;
        }
        let Some(handle) = open_limited(pid) else {
            continue;
        };
        let image = image_of(handle);
        close(handle);
        if let Some(image) = image {
            found.push(image.to_lowercase());
        }
    }
    Some(found)
}

/// `{"pid", "parent", "path", "created", "family"}` of one process of `processes_named`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NamedProcess {
    pub pid: u32,
    pub parent: u32,
    pub path: Option<String>,
    pub created: Option<u64>,
    pub family: Option<String>,
}

/// (image path, creation FILETIME, package family name) of process `pid`, from one handle opened for limited query.
fn facts(pid: u32) -> (Option<String>, Option<u64>, Option<String>) {
    let Some(handle) = open_limited(pid) else {
        return (None, None, None);
    };
    let path = image_of(handle);
    let created = process_created(handle).filter(|created| *created != 0);
    let mut buffer = vec![0u16; 256];
    let mut length = 256u32;
    // SAFETY: the buffer is ours.
    let answer =
        unsafe { GetPackageFamilyName(handle, &mut length, Some(PWSTR(buffer.as_mut_ptr()))) };
    let family = (answer == WIN32_ERROR(0))
        .then(|| crate::paths::from_wide(&buffer))
        .filter(|name| !name.is_empty());
    close(handle);
    (path, created, family)
}

/// Every process whose program file is called one of `names` (compared without case), plus every one whose package
/// family is one of `families`.
pub fn processes_named(
    names: &[&str],
    families: &[&str],
) -> Result<Vec<NamedProcess>, AdapterError> {
    let wanted: Vec<String> = names.iter().map(|name| name.to_lowercase()).collect();
    let kinds: Vec<String> = families
        .iter()
        .map(|family| family.to_lowercase())
        .collect();
    let entries = toolhelp();
    if entries.is_empty() {
        return Err(AdapterError("process_inventory_unavailable"));
    }
    let mut found = Vec::new();
    for (pid, parent, exe) in entries {
        let named = wanted.contains(&exe.to_lowercase());
        if pid == 0 || (!named && kinds.is_empty()) {
            continue;
        }
        let (path, created, family) = facts(pid);
        let by_family = path.is_some()
            && family
                .as_ref()
                .is_some_and(|f| kinds.contains(&f.to_lowercase()));
        if named || by_family {
            found.push(NamedProcess {
                pid,
                parent,
                path,
                created,
                family,
            });
        }
    }
    Ok(found)
}

/// (creation FILETIME, package family name or None) of one process: (0, None) where it cannot be opened.
fn opened(pid: u32, own: bool) -> (u64, Option<String>) {
    let Some(handle) = open_limited(pid) else {
        return (0, None);
    };
    let created = process_created(handle).unwrap_or(0);
    let mut buffer = vec![0u16; 256];
    let mut length = 256u32;
    // SAFETY: the buffer is ours.
    let answer = unsafe {
        if own {
            GetCurrentPackageFamilyName(&mut length, Some(PWSTR(buffer.as_mut_ptr())))
        } else {
            GetPackageFamilyName(handle, &mut length, Some(PWSTR(buffer.as_mut_ptr())))
        }
    };
    let family = (answer == WIN32_ERROR(0))
        .then(|| crate::paths::from_wide(&buffer))
        .filter(|name| !name.is_empty());
    close(handle);
    (created, family)
}

/// `start` and its ancestors as the walk sees them, as `HostApp.LiveTable` gathers them.
pub fn host_table(start: u32) -> HashMap<u32, HostRow> {
    let parents: HashMap<u32, u32> = toolhelp()
        .into_iter()
        .map(|(pid, parent, _)| (pid, parent))
        .collect();
    // SAFETY: plain query.
    let own = unsafe { GetCurrentProcessId() };
    let mut table = HashMap::new();
    let mut pid = start;
    for _step in 0..HOST_MAX_STEPS + 2 {
        if table.contains_key(&pid) || !parents.contains_key(&pid) {
            break;
        }
        let (created, family) = opened(pid, pid == own);
        table.insert(pid, (parents[&pid], created, family));
        if created == 0 {
            break;
        }
        pid = parents[&pid];
    }
    table
}

/// Whether the process `pid` - this one when None - runs inside another app's private view, and which. Never
/// fails: UNKNOWN where Windows would not say.
pub fn host_app(pid: Option<u32>, started_by: Option<f64>) -> HostVerdict {
    // SAFETY: plain query.
    let start = pid.unwrap_or_else(|| unsafe { GetCurrentProcessId() });
    host_verdict(start, &host_table(start), started_by)
}

// ----------------------------------------------------------------------------------------------- integrity

/// The mandatory integrity level of a kernel object, as the label SID's last RID. An object with no explicit label is
/// Medium.
pub fn integrity_rid(handle: HANDLE) -> Result<u32, AdapterError> {
    let mut sacl: *mut ACL = std::ptr::null_mut();
    let mut descriptor = PSECURITY_DESCRIPTOR::default();
    // SAFETY: out pointers of our own; the descriptor is freed below.
    let status = unsafe {
        GetSecurityInfo(
            handle,
            SE_KERNEL_OBJECT,
            LABEL_SECURITY_INFORMATION,
            None,
            None,
            None,
            Some(&mut sacl),
            Some(&mut descriptor),
        )
    };
    if status.0 != 0 {
        return Err(AdapterError("object_label_unreadable"));
    }
    let mut rid = SECURITY_MANDATORY_MEDIUM_RID;
    if !sacl.is_null() {
        // SAFETY: the ACL the descriptor holds, alive until it is freed.
        let count = unsafe { (*sacl).AceCount };
        for index in 0..count {
            let mut ace: *mut core::ffi::c_void = std::ptr::null_mut();
            // SAFETY: an index below the ACL's own count.
            if unsafe { GetAce(sacl, u32::from(index), &mut ace) }.is_err() || ace.is_null() {
                continue;
            }
            // SAFETY: an ACE header begins every ACE.
            if unsafe { *(ace as *const u8) } != SYSTEM_MANDATORY_LABEL_ACE_TYPE {
                continue;
            }
            // ACE_HEADER (4 bytes) + Mask (4 bytes), then the SID.
            let sid = PSID(unsafe { (ace as *mut u8).add(8) } as *mut _);
            // SAFETY: a SID inside a mandatory-label ACE.
            let last = unsafe { *GetSidSubAuthorityCount(sid) } as u32 - 1;
            rid = unsafe { *GetSidSubAuthority(sid, last) };
            break;
        }
    }
    if !descriptor.0.is_null() {
        // SAFETY: allocated by GetSecurityInfo.
        unsafe {
            let _ = LocalFree(Some(HLOCAL(descriptor.0)));
        }
    }
    Ok(rid)
}

pub(crate) fn sid_text(sid: PSID) -> Option<String> {
    let mut text = PWSTR::null();
    // SAFETY: a valid SID; the string is freed below.
    unsafe { ConvertSidToStringSidW(sid, &mut text) }.ok()?;
    // SAFETY: NUL-terminated by the call.
    let result = unsafe { text.to_string() }.ok();
    // SAFETY: allocated by the call above.
    unsafe {
        let _ = LocalFree(Some(HLOCAL(text.0 as *mut _)));
    }
    result
}

/// The owner of a kernel object, as SID text; None where Windows would not say.
pub fn owner_sid(handle: HANDLE) -> Option<String> {
    let mut owner = PSID::default();
    let mut descriptor = PSECURITY_DESCRIPTOR::default();
    // SAFETY: out pointers of our own.
    let status = unsafe {
        GetSecurityInfo(
            handle,
            SE_KERNEL_OBJECT,
            OWNER_SECURITY_INFORMATION,
            Some(&mut owner),
            None,
            None,
            None,
            Some(&mut descriptor),
        )
    };
    if status.0 != 0 {
        return None;
    }
    let text = if owner.0.is_null() {
        None
    } else {
        sid_text(owner)
    };
    if !descriptor.0.is_null() {
        // SAFETY: allocated by GetSecurityInfo.
        unsafe {
            let _ = LocalFree(Some(HLOCAL(descriptor.0)));
        }
    }
    text
}

/// This account's SID text, from this process's own token (TokenUser); None where it is unreadable.
pub fn user_sid() -> Option<String> {
    let token = HANDLE(-4isize as *mut _); // GetCurrentProcessToken(): a pseudo-handle, never closed
    let mut needed = 0u32;
    // SAFETY: asks the size.
    let _ = unsafe { GetTokenInformation(token, TOKEN_INFORMATION_CLASS(1), None, 0, &mut needed) };
    if needed == 0 || needed > 4096 {
        return None;
    }
    let mut buffer = vec![0u8; needed as usize];
    // SAFETY: the buffer is as long as the size asked.
    unsafe {
        GetTokenInformation(
            token,
            TOKEN_INFORMATION_CLASS(1),
            Some(buffer.as_mut_ptr() as *mut _),
            needed,
            &mut needed,
        )
    }
    .ok()?;
    // SAFETY: TOKEN_USER begins the buffer; its first field is the SID's address.
    let user = unsafe { std::ptr::read_unaligned(buffer.as_ptr() as *const TOKEN_USER) };
    sid_text(user.User.Sid)
}

/// Whether a named object whose owner is `owner` was made by this account `user` (or by someone with more rights).
/// An owner or user that could not be read is not trusted. Pure.
pub fn trusted_owner(owner: Option<&str>, user: Option<&str>) -> bool {
    match (owner, user) {
        (Some(owner), Some(user)) if !owner.is_empty() && !user.is_empty() => {
            owner == user || TRUSTED_OWNERS.contains(&owner)
        }
        _ => false,
    }
}

/// Refuse a named object that a lower-integrity process created before we did (or that another account made): the
/// only opening is getting there first, and it is detectable - the object then carries the creator's label or owner.
/// The handle is closed when it is refused.
pub fn refuse_if_squatted(handle: HANDLE, existed: bool) -> Result<(), AdapterError> {
    if existed
        && (integrity_rid(handle)? < SECURITY_MANDATORY_MEDIUM_RID
            || !trusted_owner(owner_sid(handle).as_deref(), user_sid().as_deref()))
    {
        close(handle);
        return Err(AdapterError("named_object_squatted"));
    }
    Ok(())
}

/// A static check for a name given as `PCWSTR`, kept so callers need not build one themselves.
pub fn pcwstr(buffer: &[u16]) -> PCWSTR {
    PCWSTR(buffer.as_ptr())
}
