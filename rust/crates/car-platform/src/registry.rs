//! The registry, behind a seam (brief rule 3: nothing of ours writes the real per-user registry from a test).
//!
//! Every module that reads or writes a key - `startup`, `addremove`, `policykeys`, `userenv`, `textsize` - asks a
//! [`Registry`], never Windows. There are two of them:
//!
//! * [`FakeRegistry`]: in memory, records every call in the order made. Tests (and
//!   `tests/rustdiff/platform_diffs.py`, which compares the calls with the reference's own, run with its `winreg`
//!   replaced by a recording stand-in with the same rules) use only this one, or the next.
//! * [`WinRegistry`]: the real calls of `Win32::System::Registry`. It is made over roots it is given
//!   ([`WinRegistry::current_user`] is the product's; [`PrivateHive`] makes a hive of a scratch file that a test
//!   points the roots at, so the real writers are exercised without HKCU ever being opened).
//!
//! The call shape is `winreg`'s own - `OpenKey`, `CreateKeyEx`, `QueryValueEx`, `SetValueEx`, `DeleteValue`,
//! `DeleteKey`, close - so a recorded sequence can be held equal to the reference's call by call.

use std::cell::RefCell;
use std::collections::BTreeMap;

use windows::Win32::Foundation::{
    ERROR_FILE_NOT_FOUND, ERROR_MORE_DATA, ERROR_PATH_NOT_FOUND, ERROR_SUCCESS, WIN32_ERROR,
};
use windows::Win32::System::Registry::{
    HKEY, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, REG_DWORD, REG_EXPAND_SZ, REG_OPTION_NON_VOLATILE,
    REG_QWORD, REG_SAM_FLAGS, REG_SZ, REG_VALUE_TYPE, RegCloseKey, RegCreateKeyExW, RegDeleteKeyW,
    RegDeleteValueW, RegOpenKeyExW, RegQueryValueExW, RegSetValueExW,
};
use windows::core::PCWSTR;

use crate::paths::wide;

pub const KEY_READ: u32 = 0x0002_0019;
pub const KEY_SET_VALUE: u32 = 0x0002;
pub const KEY_WOW64_64KEY: u32 = 0x0100;
pub const TYPE_SZ: u32 = 1;
pub const TYPE_EXPAND_SZ: u32 = 2;
pub const TYPE_DWORD: u32 = 4;
/// `winreg.REG_BINARY` and `winreg.REG_QWORD`.
pub const TYPE_BINARY: u32 = 3;
pub const TYPE_QWORD: u32 = 11;

/// Which hive a path is under.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Root {
    CurrentUser,
    LocalMachine,
}

impl Root {
    pub fn name(self) -> &'static str {
        match self {
            Root::CurrentUser => "HKCU",
            Root::LocalMachine => "HKLM",
        }
    }
}

/// A value as `winreg.QueryValueEx` hands it back: text, a number, or the bytes of a type nothing here reads.
/// A REG_QWORD is a number too (winreg gives an int), which the administrator's policy keys honour (S2.2).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Value {
    Str(String),
    Int(u32),
    Qword(u64),
    Bytes(Vec<u8>),
}

/// A value and its registry type.
pub type Typed = (Value, u32);

/// Why a call failed: `FileNotFoundError` (the key or value is not there) or any other `OSError`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RegError {
    NotFound,
    Other(u32),
}

/// An open key.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct KeyId(pub u64);

/// `winreg`, as far as the product uses it.
pub trait Registry {
    fn open_key(&self, root: Root, path: &str, access: u32) -> Result<KeyId, RegError>;
    fn create_key_ex(&self, root: Root, path: &str, access: u32) -> Result<KeyId, RegError>;
    fn query_value(&self, key: KeyId, name: &str) -> Result<Typed, RegError>;
    /// `SetValueEx(key, name, 0, kind, value)` with `kind` REG_SZ for a string and REG_DWORD for a number.
    fn set_value(&self, key: KeyId, name: &str, value: &Value) -> Result<(), RegError>;
    fn delete_value(&self, key: KeyId, name: &str) -> Result<(), RegError>;
    fn delete_key(&self, root: Root, path: &str) -> Result<(), RegError>;
    fn close(&self, key: KeyId);
}

/// An open key that closes itself (`with winreg.OpenKey(...) as key`).
pub struct Open<'a> {
    registry: &'a dyn Registry,
    pub id: KeyId,
}

impl<'a> Open<'a> {
    pub fn read(
        registry: &'a dyn Registry,
        root: Root,
        path: &str,
        access: u32,
    ) -> Result<Self, RegError> {
        Ok(Open {
            registry,
            id: registry.open_key(root, path, access)?,
        })
    }

    pub fn create(
        registry: &'a dyn Registry,
        root: Root,
        path: &str,
        access: u32,
    ) -> Result<Self, RegError> {
        Ok(Open {
            registry,
            id: registry.create_key_ex(root, path, access)?,
        })
    }

    pub fn query(&self, name: &str) -> Result<Typed, RegError> {
        self.registry.query_value(self.id, name)
    }

    pub fn set(&self, name: &str, value: &Value) -> Result<(), RegError> {
        self.registry.set_value(self.id, name, value)
    }

    pub fn delete_value(&self, name: &str) -> Result<(), RegError> {
        self.registry.delete_value(self.id, name)
    }
}

impl Drop for Open<'_> {
    fn drop(&mut self) {
        self.registry.close(self.id);
    }
}

// ---------------------------------------------------------------------------------------------- the stand-in

/// One call, as the reference's recording stand-in writes it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Call {
    OpenKey {
        root: Root,
        path: String,
        access: u32,
    },
    CreateKeyEx {
        root: Root,
        path: String,
        access: u32,
    },
    QueryValueEx {
        key: String,
        name: String,
    },
    SetValueEx {
        key: String,
        name: String,
        kind: u32,
        value: Value,
    },
    DeleteValue {
        key: String,
        name: String,
    },
    DeleteKey {
        root: Root,
        path: String,
    },
    Close {
        key: String,
    },
}

#[derive(Default)]
struct Store {
    /// "HKCU|path" -> value name -> (value, type). A key exists when its entry does.
    keys: BTreeMap<String, BTreeMap<String, Typed>>,
    open: BTreeMap<u64, String>,
    next: u64,
    calls: Vec<Call>,
    /// Keys every open, create or delete of which is refused (`OSError`, not "not found").
    deny_keys: Vec<String>,
    /// Values whose read is refused.
    deny_values: Vec<(String, String)>,
}

fn slot(root: Root, path: &str) -> String {
    format!("{}|{}", root.name(), path)
}

/// In-memory registry that records every call. The rules (shared with the reference's stand-in, `platform_diffs`):
/// a key exists when it has been created (with every ancestor) or seeded; opening a missing key is `NotFound`; a
/// key with a subkey is not deleted (`Other(5)`); a refused key or value answers `Other(5)`.
#[derive(Default)]
pub struct FakeRegistry {
    store: RefCell<Store>,
}

impl FakeRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Seed a key (and its ancestors) with values, as if it had been there.
    pub fn seed(&self, root: Root, path: &str, values: &[(&str, Value, u32)]) {
        let mut store = self.store.borrow_mut();
        Self::create_all(&mut store, root, path);
        let entry = store.keys.get_mut(&slot(root, path)).expect("just created");
        for (name, value, kind) in values {
            entry.insert((*name).to_string(), (value.clone(), *kind));
        }
    }

    pub fn deny_key(&self, root: Root, path: &str) {
        self.store.borrow_mut().deny_keys.push(slot(root, path));
    }

    pub fn deny_value(&self, root: Root, path: &str, name: &str) {
        self.store
            .borrow_mut()
            .deny_values
            .push((slot(root, path), name.to_string()));
    }

    /// Every call made so far, in order.
    pub fn calls(&self) -> Vec<Call> {
        self.store.borrow().calls.clone()
    }

    /// The whole store: "HKCU|path" -> (value name -> (value, type)), keys and values in order.
    pub fn dump(&self) -> BTreeMap<String, BTreeMap<String, Typed>> {
        self.store.borrow().keys.clone()
    }

    fn create_all(store: &mut Store, root: Root, path: &str) {
        let mut so_far = String::new();
        for part in path.split('\\') {
            if !so_far.is_empty() {
                so_far.push('\\');
            }
            so_far.push_str(part);
            store.keys.entry(slot(root, &so_far)).or_default();
        }
    }
}

impl Registry for FakeRegistry {
    fn open_key(&self, root: Root, path: &str, access: u32) -> Result<KeyId, RegError> {
        let mut store = self.store.borrow_mut();
        store.calls.push(Call::OpenKey {
            root,
            path: path.to_string(),
            access,
        });
        let key = slot(root, path);
        if store.deny_keys.contains(&key) {
            return Err(RegError::Other(5));
        }
        if !store.keys.contains_key(&key) {
            return Err(RegError::NotFound);
        }
        store.next += 1;
        let id = store.next;
        store.open.insert(id, key);
        Ok(KeyId(id))
    }

    fn create_key_ex(&self, root: Root, path: &str, access: u32) -> Result<KeyId, RegError> {
        let mut store = self.store.borrow_mut();
        store.calls.push(Call::CreateKeyEx {
            root,
            path: path.to_string(),
            access,
        });
        let key = slot(root, path);
        if store.deny_keys.contains(&key) {
            return Err(RegError::Other(5));
        }
        Self::create_all(&mut store, root, path);
        store.next += 1;
        let id = store.next;
        store.open.insert(id, key);
        Ok(KeyId(id))
    }

    fn query_value(&self, key: KeyId, name: &str) -> Result<Typed, RegError> {
        let mut store = self.store.borrow_mut();
        let path = store.open.get(&key.0).cloned().unwrap_or_default();
        store.calls.push(Call::QueryValueEx {
            key: path.clone(),
            name: name.to_string(),
        });
        if store
            .deny_values
            .contains(&(path.clone(), name.to_string()))
        {
            return Err(RegError::Other(5));
        }
        store
            .keys
            .get(&path)
            .and_then(|values| values.get(name))
            .cloned()
            .ok_or(RegError::NotFound)
    }

    fn set_value(&self, key: KeyId, name: &str, value: &Value) -> Result<(), RegError> {
        let mut store = self.store.borrow_mut();
        let path = store.open.get(&key.0).cloned().unwrap_or_default();
        // The type WinRegistry::set_value writes each kind of value as (review 4, note 3).
        let kind = match value {
            Value::Int(_) => TYPE_DWORD,
            Value::Qword(_) => TYPE_QWORD,
            Value::Bytes(_) => TYPE_BINARY,
            Value::Str(_) => TYPE_SZ,
        };
        store.calls.push(Call::SetValueEx {
            key: path.clone(),
            name: name.to_string(),
            kind,
            value: value.clone(),
        });
        store
            .keys
            .entry(path)
            .or_default()
            .insert(name.to_string(), (value.clone(), kind));
        Ok(())
    }

    fn delete_value(&self, key: KeyId, name: &str) -> Result<(), RegError> {
        let mut store = self.store.borrow_mut();
        let path = store.open.get(&key.0).cloned().unwrap_or_default();
        store.calls.push(Call::DeleteValue {
            key: path.clone(),
            name: name.to_string(),
        });
        match store
            .keys
            .get_mut(&path)
            .and_then(|values| values.remove(name))
        {
            Some(_) => Ok(()),
            None => Err(RegError::NotFound),
        }
    }

    fn delete_key(&self, root: Root, path: &str) -> Result<(), RegError> {
        let mut store = self.store.borrow_mut();
        store.calls.push(Call::DeleteKey {
            root,
            path: path.to_string(),
        });
        let key = slot(root, path);
        if store.deny_keys.contains(&key) {
            return Err(RegError::Other(5));
        }
        if !store.keys.contains_key(&key) {
            return Err(RegError::NotFound);
        }
        let child = format!("{key}\\");
        if store.keys.keys().any(|other| other.starts_with(&child)) {
            return Err(RegError::Other(5));
        }
        store.keys.remove(&key);
        Ok(())
    }

    fn close(&self, key: KeyId) {
        let mut store = self.store.borrow_mut();
        let path = store.open.remove(&key.0).unwrap_or_default();
        store.calls.push(Call::Close { key: path });
    }
}

// ---------------------------------------------------------------------------------------------- the real one

/// The real registry, over two root handles.
pub struct WinRegistry {
    current_user: HKEY,
    local_machine: HKEY,
    open: RefCell<BTreeMap<u64, HKEY>>,
    next: RefCell<u64>,
}

fn failure(code: WIN32_ERROR) -> RegError {
    if code == ERROR_FILE_NOT_FOUND || code == ERROR_PATH_NOT_FOUND {
        RegError::NotFound
    } else {
        RegError::Other(code.0)
    }
}

impl WinRegistry {
    /// The product's own: HKEY_CURRENT_USER and HKEY_LOCAL_MACHINE. Only the product's entry points make this one;
    /// no test does.
    pub fn current_user() -> Self {
        Self::over(HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE)
    }

    /// Over roots the caller names (a private hive for a test, `PrivateHive::registry`).
    pub fn over(current_user: HKEY, local_machine: HKEY) -> Self {
        WinRegistry {
            current_user,
            local_machine,
            open: RefCell::new(BTreeMap::new()),
            next: RefCell::new(0),
        }
    }

    fn root(&self, root: Root) -> HKEY {
        match root {
            Root::CurrentUser => self.current_user,
            Root::LocalMachine => self.local_machine,
        }
    }

    fn keep(&self, handle: HKEY) -> KeyId {
        let mut next = self.next.borrow_mut();
        *next += 1;
        self.open.borrow_mut().insert(*next, handle);
        KeyId(*next)
    }

    fn handle(&self, key: KeyId) -> HKEY {
        self.open.borrow().get(&key.0).copied().unwrap_or_default()
    }
}

impl Registry for WinRegistry {
    fn open_key(&self, root: Root, path: &str, access: u32) -> Result<KeyId, RegError> {
        let name = wide(path);
        let mut handle = HKEY::default();
        // SAFETY: `name` is NUL-terminated and outlives the call.
        let code = unsafe {
            RegOpenKeyExW(
                self.root(root),
                PCWSTR(name.as_ptr()),
                None,
                REG_SAM_FLAGS(access),
                &mut handle,
            )
        };
        if code != ERROR_SUCCESS {
            return Err(failure(code));
        }
        Ok(self.keep(handle))
    }

    fn create_key_ex(&self, root: Root, path: &str, access: u32) -> Result<KeyId, RegError> {
        let name = wide(path);
        let mut handle = HKEY::default();
        // SAFETY: `name` is NUL-terminated and outlives the call.
        let code = unsafe {
            RegCreateKeyExW(
                self.root(root),
                PCWSTR(name.as_ptr()),
                None,
                PCWSTR::null(),
                REG_OPTION_NON_VOLATILE,
                REG_SAM_FLAGS(access),
                None,
                &mut handle,
                None,
            )
        };
        if code != ERROR_SUCCESS {
            return Err(failure(code));
        }
        Ok(self.keep(handle))
    }

    fn query_value(&self, key: KeyId, name: &str) -> Result<Typed, RegError> {
        let handle = self.handle(key);
        let name = wide(name);
        let mut kind = REG_VALUE_TYPE(0);
        let mut size = 0u32;
        // SAFETY: the first call only asks the size.
        let code = unsafe {
            RegQueryValueExW(
                handle,
                PCWSTR(name.as_ptr()),
                None,
                Some(&mut kind),
                None,
                Some(&mut size),
            )
        };
        if code != ERROR_SUCCESS {
            return Err(failure(code));
        }
        // winreg's QueryValueEx: a value that grew since the size was asked (ERROR_MORE_DATA) is asked again with
        // more room, until it fits (review 4, note 2).
        let mut room = size as usize + 2;
        let (mut data, got) = loop {
            let mut data = vec![0u8; room];
            let mut got = u32::try_from(room).unwrap_or(u32::MAX);
            // SAFETY: `data` is `got` bytes long.
            let code = unsafe {
                RegQueryValueExW(
                    handle,
                    PCWSTR(name.as_ptr()),
                    None,
                    Some(&mut kind),
                    Some(data.as_mut_ptr()),
                    Some(&mut got),
                )
            };
            if code == ERROR_MORE_DATA {
                room = (got as usize).max(room.saturating_mul(2)) + 2;
                continue;
            }
            if code != ERROR_SUCCESS {
                return Err(failure(code));
            }
            break (data, got);
        };
        data.truncate(got as usize);
        let value = match kind {
            REG_SZ | REG_EXPAND_SZ => {
                let units: Vec<u16> = data
                    .as_chunks::<2>()
                    .0
                    .iter()
                    .map(|pair| u16::from_le_bytes(*pair))
                    .collect();
                let end = units
                    .iter()
                    .position(|&unit| unit == 0)
                    .unwrap_or(units.len());
                Value::Str(String::from_utf16_lossy(&units[..end]))
            }
            // winreg reads a REG_DWORD or REG_QWORD of any length as the number its first 4 or 8 bytes make: none
            // is 0, and a short one is read past its end (whatever winreg's buffer holds there; zero here, AUDIT).
            REG_DWORD => Value::Int(u32::from_le_bytes(padded::<4>(&data))),
            REG_QWORD => Value::Qword(u64::from_le_bytes(padded::<8>(&data))),
            _ => Value::Bytes(data),
        };
        Ok((value, kind.0))
    }

    fn set_value(&self, key: KeyId, name: &str, value: &Value) -> Result<(), RegError> {
        let handle = self.handle(key);
        let name = wide(name);
        let (kind, data): (REG_VALUE_TYPE, Vec<u8>) = match value {
            Value::Str(text) => (
                REG_SZ,
                wide(text)
                    .iter()
                    .flat_map(|unit| unit.to_le_bytes())
                    .collect(),
            ),
            Value::Int(number) => (REG_DWORD, number.to_le_bytes().to_vec()),
            Value::Qword(number) => (REG_QWORD, number.to_le_bytes().to_vec()),
            Value::Bytes(bytes) => (REG_VALUE_TYPE(3), bytes.clone()),
        };
        // SAFETY: `name` and `data` outlive the call.
        let code =
            unsafe { RegSetValueExW(handle, PCWSTR(name.as_ptr()), None, kind, Some(&data)) };
        if code != ERROR_SUCCESS {
            return Err(failure(code));
        }
        Ok(())
    }

    fn delete_value(&self, key: KeyId, name: &str) -> Result<(), RegError> {
        let name = wide(name);
        // SAFETY: `name` outlives the call.
        let code = unsafe { RegDeleteValueW(self.handle(key), PCWSTR(name.as_ptr())) };
        if code != ERROR_SUCCESS {
            return Err(failure(code));
        }
        Ok(())
    }

    fn delete_key(&self, root: Root, path: &str) -> Result<(), RegError> {
        let name = wide(path);
        // SAFETY: `name` outlives the call.
        let code = unsafe { RegDeleteKeyW(self.root(root), PCWSTR(name.as_ptr())) };
        if code != ERROR_SUCCESS {
            return Err(failure(code));
        }
        Ok(())
    }

    fn close(&self, key: KeyId) {
        if let Some(handle) = self.open.borrow_mut().remove(&key.0) {
            // SAFETY: a handle this registry opened and has not closed.
            unsafe {
                let _ = RegCloseKey(handle);
            }
        }
    }
}

// ------------------------------------------------------------------------------------------ a private hive

/// A registry hive of its own, loaded from a scratch file (`RegLoadAppKey`): a root a test can point
/// [`WinRegistry::over`] at so that the real writers run, with neither HKCU nor HKLM opened. The hive is private
/// to the process and is gone with the handle; nothing of Windows' registry is changed.
pub struct PrivateHive {
    handle: HKEY,
}

impl PrivateHive {
    /// Load (creating the file if it is not there) `file` as an application hive. None where Windows refuses.
    pub fn load(file: &std::path::Path) -> Option<Self> {
        use windows::Win32::System::Registry::RegLoadAppKeyW;
        let name = wide(&file.to_string_lossy());
        let mut handle = HKEY::default();
        // KEY_ALL_ACCESS, no options, reserved 0.
        // SAFETY: `name` outlives the call.
        let code = unsafe { RegLoadAppKeyW(PCWSTR(name.as_ptr()), &mut handle, 0xF003F, 0, None) };
        (code == ERROR_SUCCESS).then_some(PrivateHive { handle })
    }

    /// The real registry code, over this hive for both roots.
    pub fn registry(&self) -> WinRegistry {
        WinRegistry::over(self.handle, self.handle)
    }
}

impl Drop for PrivateHive {
    fn drop(&mut self) {
        // SAFETY: the handle `load` opened.
        unsafe {
            let _ = RegCloseKey(self.handle);
        }
    }
}

/// The first `N` bytes of `data`, zero past its end.
fn padded<const N: usize>(data: &[u8]) -> [u8; N] {
    let mut bytes = [0u8; N];
    for (slot, byte) in bytes.iter_mut().zip(data) {
        *slot = *byte;
    }
    bytes
}
