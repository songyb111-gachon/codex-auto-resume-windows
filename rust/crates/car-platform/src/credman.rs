//! Windows Credential Manager (seat S7.2a; the advanced edition's `credentials.py`, `WindowsCredentials`): generic
//! credentials of the signed-in user, persisted on this machine, under targets the caller built.
//!
//! [`Backend`] is what the caller stores through; [`Windows`] is the real one (`CredReadW`, `CredWriteW`,
//! `CredDeleteW`), refusing any target outside the prefix it was made with; [`Memory`] is the stand-in every test and
//! probe hands in. No test reaches the real Credential Manager (P7-DESIGN 4): [`Windows`] has no test here, and its one
//! live round trip, if ever, is the main session's in acceptance.

use std::collections::BTreeMap;
use std::sync::Mutex;

use windows::Win32::Foundation::ERROR_NOT_FOUND;
use windows::Win32::Security::Credentials::{
    CRED_FLAGS, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC, CREDENTIALW, CredDeleteW, CredFree,
    CredReadW, CredWriteW,
};
use windows::core::{PCWSTR, PWSTR};

/// A secret that could not be named, read, written or deleted (`SecretError`). Never says what it was.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CredError(pub &'static str);

impl std::fmt::Display for CredError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for CredError {}

/// Where secrets are stored: `read`, `write`, `delete` by target.
pub trait Backend: Send + Sync {
    /// The secret under `target`, or None where there is none.
    fn read(&self, target: &str) -> Result<Option<String>, CredError>;
    fn write(&self, target: &str, secret: &str) -> Result<(), CredError>;
    /// Whether there was one to delete.
    fn delete(&self, target: &str) -> Result<bool, CredError>;
}

/// The real Credential Manager, for targets under `prefix` alone.
pub struct Windows {
    pub prefix: &'static str,
}

const NOT_OURS: CredError = CredError("not a target of this edition");

fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

fn not_found(error: &windows::core::Error) -> bool {
    error.code() == ERROR_NOT_FOUND.to_hresult()
}

impl Windows {
    fn ours(&self, target: &str) -> Result<Vec<u16>, CredError> {
        if !target.starts_with(self.prefix) {
            return Err(NOT_OURS);
        }
        Ok(wide(target))
    }
}

impl Backend for Windows {
    fn read(&self, target: &str) -> Result<Option<String>, CredError> {
        let name = self.ours(target)?;
        let mut found: *mut CREDENTIALW = std::ptr::null_mut();
        // SAFETY: `name` is NUL-terminated and outlives the call; `found` is freed with CredFree below.
        let read = unsafe { CredReadW(PCWSTR(name.as_ptr()), CRED_TYPE_GENERIC, None, &mut found) };
        if let Err(error) = read {
            return if not_found(&error) {
                Ok(None)
            } else {
                Err(CredError("the secret could not be read"))
            };
        }
        // SAFETY: CredReadW succeeded, so `found` points at a credential whose blob is `CredentialBlobSize` bytes.
        let blob = unsafe {
            let credential = &*found;
            let blob = if credential.CredentialBlob.is_null() {
                Vec::new()
            } else {
                std::slice::from_raw_parts(
                    credential.CredentialBlob,
                    credential.CredentialBlobSize as usize,
                )
                .to_vec()
            };
            CredFree(found.cast());
            blob
        };
        String::from_utf8(blob)
            .map(Some)
            .map_err(|_| CredError("the secret could not be read"))
    }

    fn write(&self, target: &str, secret: &str) -> Result<(), CredError> {
        let mut name = self.ours(target)?;
        let mut user = wide("codex-auto-resume");
        let mut data = secret.as_bytes().to_vec();
        let credential = CREDENTIALW {
            Flags: CRED_FLAGS(0),
            Type: CRED_TYPE_GENERIC,
            TargetName: PWSTR(name.as_mut_ptr()),
            CredentialBlobSize: data.len() as u32,
            CredentialBlob: data.as_mut_ptr(),
            Persist: CRED_PERSIST_LOCAL_MACHINE,
            UserName: PWSTR(user.as_mut_ptr()),
            ..Default::default()
        };
        // SAFETY: every pointer in `credential` points at a buffer that outlives the call.
        unsafe { CredWriteW(&credential, 0) }
            .map_err(|_| CredError("the secret could not be written"))
    }

    fn delete(&self, target: &str) -> Result<bool, CredError> {
        let name = self.ours(target)?;
        // SAFETY: `name` is NUL-terminated and outlives the call.
        match unsafe { CredDeleteW(PCWSTR(name.as_ptr()), CRED_TYPE_GENERIC, None) } {
            Ok(()) => Ok(true),
            Err(error) if not_found(&error) => Ok(false),
            Err(_) => Err(CredError("the secret could not be deleted")),
        }
    }
}

/// A Credential Manager of the caller's own, in memory: what every test and probe stores through.
#[derive(Default)]
pub struct Memory {
    pub secrets: Mutex<BTreeMap<String, String>>,
}

impl Backend for Memory {
    fn read(&self, target: &str) -> Result<Option<String>, CredError> {
        Ok(self
            .secrets
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .get(target)
            .cloned())
    }

    fn write(&self, target: &str, secret: &str) -> Result<(), CredError> {
        self.secrets
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .insert(target.to_owned(), secret.to_owned());
        Ok(())
    }

    fn delete(&self, target: &str) -> Result<bool, CredError> {
        Ok(self
            .secrets
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .remove(target)
            .is_some())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_stand_in_keeps_what_it_was_given() {
        let memory = Memory::default();
        assert_eq!(memory.read("t"), Ok(None));
        memory.write("t", "s").expect("write");
        assert_eq!(memory.read("t"), Ok(Some("s".into())));
        assert_eq!(memory.delete("t"), Ok(true));
        assert_eq!(memory.delete("t"), Ok(false));
    }

    /// The real backend refuses a target outside its prefix before any call is made - the only part of it a test may
    /// reach (it makes no Windows call on this path).
    #[test]
    fn the_real_backend_refuses_a_target_outside_its_prefix_without_calling_windows() {
        let real = Windows {
            prefix: "Test/prefix/",
        };
        assert_eq!(real.read("Other/x"), Err(NOT_OURS));
        assert_eq!(real.write("Other/x", "s"), Err(NOT_OURS));
        assert_eq!(real.delete(""), Err(NOT_OURS));
    }
}
