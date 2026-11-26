//! P6 step 0's done-check, the Rust half: the built `car_core.dll` exports exactly the six names of `abi::EXPORTS`
//! and nothing else, read from its PE export directory (the DLL is never loaded), and the six have the types
//! `gui/HostCore.cs` imports them with. `tests/test_host_contract.py` is the C# half.
//!
//! The DLL read is the one this `cargo test` built beside this test (the newest `car_core.dll` of this profile's
//! folder), or the one `CAR_CORE_DLL` names (a release build, the other edition's).

use std::path::{Path, PathBuf};

use car_core::abi::{self, ABI, ActionKind, EXPORTS, EventKind};

/// The six, each pinned to the type `export_core!` gives it: a change of any parameter or result fails to compile.
#[test]
fn the_six_have_the_contracts_types() {
    let start: unsafe extern "C" fn(*const u8, usize, *mut usize) -> *mut u8 = car_core::car_start;
    let stop: extern "C" fn() -> i32 = car_core::car_stop;
    let bridge: unsafe extern "C" fn(*const u8, usize, *mut usize) -> *mut u8 =
        car_core::car_bridge;
    let next_event: unsafe extern "C" fn(u32, *mut usize) -> *mut u8 = car_core::car_next_event;
    let post_action: unsafe extern "C" fn(*const u8, usize, *mut usize) -> *mut u8 =
        car_core::car_post_action;
    let free: unsafe extern "C" fn(*mut u8, usize) = car_core::car_free;
    assert_eq!(stop(), 0);
    // A request the core refuses before it starts anything: this test never starts a watcher (tests/host_watcher.rs
    // does, on a scratch home).
    let request = br#"{"argv": "run"}"#;
    let mut length = 0usize;
    // SAFETY: `request` lives for the call; `length` is the test's.
    let reply = unsafe { start(request.as_ptr(), request.len(), &mut length) };
    // SAFETY: the reply is `length` bytes the core handed out.
    let text = unsafe { std::slice::from_raw_parts(reply, length) }.to_vec();
    assert_eq!(text, br#"{"abi": 1, "ok": false, "error": "bad_request"}"#);
    assert!(abi::is_live(reply));
    // SAFETY: handed back once with its own length.
    unsafe { free(reply, length) };
    assert!(!abi::is_live(reply));
    for call in [bridge, post_action] {
        // SAFETY: as above.
        let reply = unsafe { call(request.as_ptr(), request.len(), &mut length) };
        assert!(!reply.is_null());
        // SAFETY: as above.
        unsafe { free(reply, length) };
    }
    // SAFETY: `length` is the test's.
    assert!(unsafe { next_event(0, &mut length) }.is_null());
    assert_eq!(length, 0);
    assert_eq!(ABI, 1);
    assert_eq!(EventKind::ALL.len(), 8);
    assert_eq!(ActionKind::ALL.len(), 14);
}

/// P6-DESIGN 1.3's second test: the shipped DLL carries no panic wire (the feature `panic-test` names
/// `CAR_CORE_PANIC` and its own message; neither may be in a release build). Run with `CAR_CORE_DLL` naming the release
/// DLL of each edition; a debug build may have been made with the feature by the panic test, so it is not read here.
#[test]
fn the_release_dll_has_no_panic_wire() {
    let Some(named) = std::env::var_os("CAR_CORE_DLL").filter(|value| !value.is_empty()) else {
        eprintln!("CAR_CORE_DLL is not set: no release DLL to read");
        return;
    };
    let bytes = std::fs::read(&named).unwrap_or_else(|error| panic!("{named:?}: {error}"));
    for wire in [&b"CAR_CORE_PANIC"[..], &b"the panic test tripped"[..]] {
        assert!(
            !bytes.windows(wire.len()).any(|window| window == wire),
            "{named:?} carries the panic test's wire {:?}",
            String::from_utf8_lossy(wire)
        );
    }
}

#[test]
fn the_built_dll_exports_the_six_and_nothing_else() {
    let dll = built_dll();
    let bytes = std::fs::read(&dll).unwrap_or_else(|error| panic!("{}: {error}", dll.display()));
    let table = exports(&bytes).unwrap_or_else(|why| panic!("{}: {why}", dll.display()));
    let mut expected: Vec<String> = EXPORTS.iter().map(|name| (*name).to_owned()).collect();
    expected.sort();
    assert_eq!(table.names, expected, "{}", dll.display());
    assert_eq!(
        table.functions,
        EXPORTS.len(),
        "{}: an export by ordinal only",
        dll.display()
    );
    assert_eq!(table.forwarded, 0, "{}: a forwarded export", dll.display());
    assert_eq!(table.dll_name, "car_core.dll");
}

/// The DLL this test reads: `CAR_CORE_DLL`, else the newest `car_core.dll` in this test's profile folder.
fn built_dll() -> PathBuf {
    if let Some(named) = std::env::var_os("CAR_CORE_DLL").filter(|value| !value.is_empty()) {
        return PathBuf::from(named);
    }
    let exe = std::env::current_exe().expect("the test's own path");
    let profile = exe
        .ancestors()
        .find(|folder| {
            folder.parent().and_then(Path::file_name) == Some("target".as_ref())
                || folder.join("car_core.dll").is_file()
        })
        .unwrap_or_else(|| panic!("no profile folder above {}", exe.display()));
    let mut found: Vec<(std::time::SystemTime, PathBuf)> = Vec::new();
    let mut look = |path: PathBuf| {
        if let Ok(meta) = std::fs::metadata(&path)
            && meta.is_file()
        {
            found.push((meta.modified().expect("a modified time"), path));
        }
    };
    look(profile.join("car_core.dll"));
    look(profile.join("deps").join("car_core.dll"));
    if let Ok(units) = std::fs::read_dir(profile.join("build").join("car-host")) {
        for unit in units.flatten() {
            look(unit.path().join("out").join("car_core.dll"));
        }
    }
    found
        .into_iter()
        .max()
        .map(|(_, path)| path)
        .unwrap_or_else(|| panic!("no car_core.dll under {}", profile.display()))
}

struct Table {
    dll_name: String,
    /// The export names, sorted (the PE format keeps them sorted).
    names: Vec<String>,
    /// NumberOfFunctions: exports by name and by ordinal.
    functions: usize,
    /// Exports whose address is inside the export directory: forwarders to another DLL.
    forwarded: usize,
}

fn u16_at(bytes: &[u8], at: usize) -> Result<u16, String> {
    bytes
        .get(at..at + 2)
        .map(|b| u16::from_le_bytes([b[0], b[1]]))
        .ok_or_else(|| format!("short file at {at:#x}"))
}

fn u32_at(bytes: &[u8], at: usize) -> Result<u32, String> {
    bytes
        .get(at..at + 4)
        .map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .ok_or_else(|| format!("short file at {at:#x}"))
}

/// The export directory of a PE32+ image, read from its bytes.
fn exports(bytes: &[u8]) -> Result<Table, String> {
    if bytes.get(0..2) != Some(b"MZ") {
        return Err("no MZ header".into());
    }
    let pe = u32_at(bytes, 0x3c)? as usize;
    if bytes.get(pe..pe + 4) != Some(b"PE\0\0") {
        return Err("no PE signature".into());
    }
    let coff = pe + 4;
    let sections = u16_at(bytes, coff + 2)? as usize;
    let optional_size = u16_at(bytes, coff + 16)? as usize;
    let optional = coff + 20;
    if u16_at(bytes, optional)? != 0x20b {
        return Err("not PE32+".into());
    }
    if u32_at(bytes, optional + 108)? < 1 {
        return Err("no data directories".into());
    }
    let export_rva = u32_at(bytes, optional + 112)?;
    let export_size = u32_at(bytes, optional + 116)?;
    if export_rva == 0 {
        return Err("no export directory".into());
    }
    let table = optional + optional_size;
    let mut spans = Vec::new();
    for index in 0..sections {
        let header = table + index * 40;
        let virtual_size = u32_at(bytes, header + 8)?;
        let address = u32_at(bytes, header + 12)?;
        let raw_size = u32_at(bytes, header + 16)?;
        let raw = u32_at(bytes, header + 20)?;
        spans.push((address, virtual_size.max(raw_size), raw));
    }
    let offset = |rva: u32| -> Result<usize, String> {
        spans
            .iter()
            .find(|(address, size, _)| rva >= *address && rva - address < *size)
            .map(|(address, _, raw)| (rva - address + raw) as usize)
            .ok_or_else(|| format!("RVA {rva:#x} is in no section"))
    };
    let text = |rva: u32| -> Result<String, String> {
        let at = offset(rva)?;
        let end = bytes[at..]
            .iter()
            .position(|byte| *byte == 0)
            .ok_or("an unterminated name")?;
        String::from_utf8(bytes[at..at + end].to_vec())
            .map_err(|_| "a name that is not UTF-8".to_string())
    };
    let directory = offset(export_rva)?;
    let dll_name = text(u32_at(bytes, directory + 12)?)?;
    let functions = u32_at(bytes, directory + 20)? as usize;
    let named = u32_at(bytes, directory + 24)? as usize;
    let addresses = offset(u32_at(bytes, directory + 28)?)?;
    let name_table = offset(u32_at(bytes, directory + 32)?)?;
    let mut names = Vec::new();
    for index in 0..named {
        names.push(text(u32_at(bytes, name_table + index * 4)?)?);
    }
    let mut forwarded = 0;
    for index in 0..functions {
        let rva = u32_at(bytes, addresses + index * 4)?;
        if rva >= export_rva && rva - export_rva < export_size {
            forwarded += 1;
        }
    }
    Ok(Table {
        dll_name,
        names,
        functions,
        forwarded,
    })
}
