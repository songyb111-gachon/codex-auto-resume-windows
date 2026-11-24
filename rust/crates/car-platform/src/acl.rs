//! Who Windows lets open the state folder (`win/acl.py`, Diagnostics).
//!
//! One documented Win32 question, asked only when Diagnostics is shown: the folder's access list
//! (`GetNamedSecurityInfoW`, the DACL only), read and never written. Each entry that lets someone in is compared
//! with the few that are expected there - this account, Windows itself (SYSTEM), the computer's administrators and
//! CREATOR OWNER - and an app's own sandbox (S-1-15-...), which runs as this account and is no other person. Anyone
//! else means other accounts on this PC can open the folder where the settings, the pending tasks and the logs are
//! kept. Codex's Windows sandbox group, `CodexSandboxUsers`, is told apart while every entry for it only reads.
//!
//! Only the verdict leaves this module: no security identifier, no account name and no path is kept or returned.
//! Nothing here fails: what cannot be read is UNKNOWN.

use windows::Win32::Foundation::{HLOCAL, LocalFree};
use windows::Win32::Security::Authorization::{
    ConvertStringSecurityDescriptorToSecurityDescriptorW, ConvertStringSidToSidW,
    GetNamedSecurityInfoW, SDDL_REVISION_1, SE_FILE_OBJECT,
};
use windows::Win32::Security::{
    ACCESS_ALLOWED_ACE, ACE_HEADER, ACL, ACL_SIZE_INFORMATION, AclSizeInformation,
    DACL_SECURITY_INFORMATION, GetAce, GetAclInformation, GetSecurityDescriptorDacl,
    LookupAccountSidW, PSECURITY_DESCRIPTOR, PSID, SID_NAME_USE,
};
use windows::Win32::System::WindowsProgramming::GetComputerNameW;
use windows::core::{PCWSTR, PWSTR};

use crate::kernel::{sid_text, user_sid};
use crate::paths::{from_wide, wide_os};
use car_machine::vocab_gen::domain_vocabulary::StateAccess;

const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const ACCESS_DENIED_ACE_TYPE: u8 = 1;
/// Windows itself, the administrators, and CREATOR OWNER - the three expected beside this account.
pub const EXPECTED: [&str; 3] = ["S-1-5-18", "S-1-5-32-544", "S-1-3-0"];
/// The prefix of an app sandbox's package and capability identifiers, which are not accounts.
pub const SANDBOX: &str = "S-1-15-";
pub const CODEX_SANDBOX_GROUP: &str = "codexsandboxusers";
/// The folder's contents listed, its files read and run, their attributes and its security read, and the generic
/// read and execute rights that map onto those. Any other bit is more than reading.
pub const READ_ONLY: u32 = 0x0012_00A9 | 0x8000_0000 | 0x2000_0000;
/// Every right, for an entry handed in as an identifier alone.
pub const EVERYTHING: u32 = 0xFFFF_FFFF;
pub const SID_TYPE_ALIAS: i32 = 4;

/// (name, domain, SID_NAME_USE) Windows gives for an account.
pub type Account = (String, String, i32);

/// (identifier as text, access mask).
pub type Entry = (String, u32);

/// (identifier, mask) for each entry of a DACL that lets someone in - or None when one cannot be read. A missing
/// DACL (NULL) lets everyone in everything: Everyone's, every right.
fn dacl_entries(dacl: *const ACL) -> Option<Vec<Entry>> {
    if dacl.is_null() {
        return Some(vec![("S-1-1-0".to_string(), EVERYTHING)]);
    }
    let mut size = ACL_SIZE_INFORMATION::default();
    // SAFETY: a structure of our own, sized as passed.
    unsafe {
        GetAclInformation(
            dacl,
            &mut size as *mut _ as *mut _,
            std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
            AclSizeInformation,
        )
    }
    .ok()?;
    let mut found = Vec::new();
    for index in 0..size.AceCount.min(1024) {
        let mut ace: *mut core::ffi::c_void = std::ptr::null_mut();
        // SAFETY: an index below the ACL's own count.
        unsafe { GetAce(dacl, index, &mut ace) }.ok()?;
        // SAFETY: every ACE begins with a header.
        let header = unsafe { *(ace as *const ACE_HEADER) };
        if header.AceType == ACCESS_DENIED_ACE_TYPE {
            continue; // a refusal lets no one in
        }
        if header.AceType != ACCESS_ALLOWED_ACE_TYPE {
            return None; // a kind this does not read: unknown, never "only you"
        }
        // SAFETY: an access-allowed ACE.
        let allowed = unsafe { &*(ace as *const ACCESS_ALLOWED_ACE) };
        if allowed.Mask == 0 {
            continue;
        }
        // SAFETY: the SID starts at SidStart.
        let sid =
            PSID(
                unsafe { (ace as *mut u8).add(std::mem::offset_of!(ACCESS_ALLOWED_ACE, SidStart)) }
                    as *mut _,
            );
        found.push((sid_text(sid)?, allowed.Mask));
    }
    Some(found)
}

fn free(descriptor: PSECURITY_DESCRIPTOR) {
    if !descriptor.0.is_null() {
        // SAFETY: allocated by the API that gave it.
        unsafe {
            let _ = LocalFree(Some(HLOCAL(descriptor.0)));
        }
    }
}

/// (identifier, access mask) for each entry of the folder's access list that lets someone in - or None when the list
/// cannot be read. An empty list is a folder nobody may open.
pub fn allowed_entries(path: &std::path::Path) -> Option<Vec<Entry>> {
    let name = wide_os(path.as_os_str());
    let mut descriptor = PSECURITY_DESCRIPTOR::default();
    let mut dacl: *mut ACL = std::ptr::null_mut();
    // SAFETY: out pointers of our own; the descriptor is freed below.
    let status = unsafe {
        GetNamedSecurityInfoW(
            PCWSTR(name.as_ptr()),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            Some(&mut dacl),
            None,
            &mut descriptor,
        )
    };
    if status.0 != 0 {
        return None;
    }
    let entries = dacl_entries(dacl);
    free(descriptor);
    entries
}

/// `allowed_entries` for a security descriptor written as SDDL rather than read from a folder: the same reading of
/// the same structures, over a descriptor that exists only in this process - how the tests hold it without changing
/// any folder's access list.
pub fn described_entries(sddl: &str) -> Option<Vec<Entry>> {
    let text = crate::paths::wide(sddl);
    let mut descriptor = PSECURITY_DESCRIPTOR::default();
    // SAFETY: `text` is NUL-terminated; the descriptor is freed below.
    unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            PCWSTR(text.as_ptr()),
            SDDL_REVISION_1,
            &mut descriptor,
            None,
        )
    }
    .ok()?;
    let mut present = windows::core::BOOL(0);
    let mut dacl: *mut ACL = std::ptr::null_mut();
    let mut defaulted = windows::core::BOOL(0);
    // SAFETY: out values of our own.
    let asked =
        unsafe { GetSecurityDescriptorDacl(descriptor, &mut present, &mut dacl, &mut defaulted) };
    let entries = if asked.is_ok() {
        dacl_entries(if present.as_bool() {
            dacl
        } else {
            std::ptr::null()
        })
    } else {
        None
    };
    free(descriptor);
    entries
}

/// The identifiers `allowed_entries` names, as text, or None.
pub fn allowed_sids(path: &std::path::Path) -> Option<Vec<String>> {
    allowed_entries(path).map(|entries| entries.into_iter().map(|(sid, _)| sid).collect())
}

/// Whether an account Windows names (`name`, `domain`, SID_NAME_USE `kind`) is Codex's sandbox group on this
/// computer: a local group (an alias) of this computer - its domain is the computer's name - called
/// CodexSandboxUsers, in any case. Pure.
pub fn is_sandbox_group(name: &str, domain: &str, kind: i32, computer: &str) -> bool {
    name.to_lowercase() == CODEX_SANDBOX_GROUP
        && kind == SID_TYPE_ALIAS
        && !computer.is_empty()
        && domain.to_lowercase() == computer.to_lowercase()
}

/// (name, domain, kind) Windows gives for an identifier on this machine, or None.
fn account(sid_text: &str) -> Option<Account> {
    let text = crate::paths::wide(sid_text);
    let mut sid = PSID::default();
    // SAFETY: `text` is NUL-terminated; the SID is freed below.
    unsafe { ConvertStringSidToSidW(PCWSTR(text.as_ptr()), &mut sid) }.ok()?;
    let mut name = vec![0u16; 256];
    let mut domain = vec![0u16; 256];
    let (mut name_size, mut domain_size) = (256u32, 256u32);
    let mut kind = SID_NAME_USE::default();
    // SAFETY: buffers of our own, sized as passed.
    let looked = unsafe {
        LookupAccountSidW(
            PCWSTR::null(),
            sid,
            Some(PWSTR(name.as_mut_ptr())),
            &mut name_size,
            Some(PWSTR(domain.as_mut_ptr())),
            &mut domain_size,
            &mut kind,
        )
    };
    // SAFETY: allocated by ConvertStringSidToSidW.
    unsafe {
        let _ = LocalFree(Some(HLOCAL(sid.0)));
    }
    looked.ok()?;
    Some((from_wide(&name), from_wide(&domain), kind.0))
}

/// This computer's NetBIOS name, which LookupAccountSidW gives as a local account's domain.
fn computer() -> Option<String> {
    let mut buffer = vec![0u16; 256];
    let mut size = 256u32;
    // SAFETY: a buffer of our own.
    unsafe { GetComputerNameW(Some(PWSTR(buffer.as_mut_ptr())), &mut size) }.ok()?;
    Some(from_wide(&buffer))
}

/// The identifiers among `entries` that name Codex's sandbox group on this computer. Only a machine's own
/// identifiers (S-1-5-21-...) are looked up; `lookup` and `computer_name` stand in for Windows' answers.
pub fn sandbox_sids_with(
    entries: &[Entry],
    lookup: &dyn Fn(&str) -> Option<Account>,
    computer_name: Option<&str>,
) -> std::collections::BTreeSet<String> {
    let computer_name = computer_name
        .map(str::to_string)
        .or_else(computer)
        .unwrap_or_default();
    let mut found = std::collections::BTreeSet::new();
    let unique: std::collections::BTreeSet<&str> =
        entries.iter().map(|(sid, _)| sid.as_str()).collect();
    for sid in unique {
        if !sid.starts_with("S-1-5-21-") {
            continue;
        }
        if let Some((name, domain, kind)) = lookup(sid)
            && is_sandbox_group(&name, &domain, kind, &computer_name)
        {
            found.insert(sid.to_string());
        }
    }
    found
}

/// `sandbox_sids` over Windows' own answers.
pub fn sandbox_sids(entries: &[Entry]) -> std::collections::BTreeSet<String> {
    sandbox_sids_with(entries, &account, None)
}

/// OWNER_ONLY, CODEX_SANDBOX, SHARED or UNKNOWN for what an access list lets in and this account's identifier.
/// Pure: the rule, apart from the asking.
pub fn verdict(
    allowed: Option<&[Entry]>,
    own: Option<&str>,
    sandbox: &std::collections::BTreeSet<String>,
) -> StateAccess {
    let (Some(allowed), Some(own)) = (allowed, own.filter(|own| !own.is_empty())) else {
        return StateAccess::Unknown;
    };
    let others: Vec<&Entry> = allowed
        .iter()
        .filter(|(sid, _)| {
            sid != own && !EXPECTED.contains(&sid.as_str()) && !sid.starts_with(SANDBOX)
        })
        .collect();
    if others.is_empty() {
        return StateAccess::OwnerOnly;
    }
    if others
        .iter()
        .all(|(sid, mask)| sandbox.contains(sid) && mask & !READ_ONLY == 0)
    {
        return StateAccess::CodexSandbox;
    }
    StateAccess::Shared
}

/// Who may open the folder at `path`: OWNER_ONLY, CODEX_SANDBOX, SHARED or UNKNOWN. Never fails.
pub fn state_access(path: &std::path::Path) -> StateAccess {
    let entries = allowed_entries(path);
    let sandbox = entries.as_deref().map(sandbox_sids).unwrap_or_default();
    verdict(entries.as_deref(), user_sid().as_deref(), &sandbox)
}
