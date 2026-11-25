//! The stand-in records each kind of value under the type the real writer gives it (review 4, note 3): a QWORD as
//! REG_QWORD (11) and bytes as REG_BINARY (3), as `WinRegistry::set_value` writes them, not as REG_SZ.

use car_platform::registry::{Call, FakeRegistry, KEY_SET_VALUE, Registry, Root, Value};

#[test]
fn every_kind_is_recorded_under_the_type_the_real_writer_gives_it() {
    let registry = FakeRegistry::new();
    let key = registry
        .create_key_ex(Root::CurrentUser, "Software/Scratch", KEY_SET_VALUE)
        .unwrap();
    let values = [
        ("text", Value::Str("x".into()), 1),
        ("dword", Value::Int(7), 4),
        ("qword", Value::Qword(1 << 40), 11),
        ("bytes", Value::Bytes(vec![1, 2]), 3),
    ];
    for (name, value, _) in &values {
        registry.set_value(key, name, value).unwrap();
    }
    let kinds: Vec<(String, u32)> = registry
        .calls()
        .into_iter()
        .filter_map(|call| match call {
            Call::SetValueEx { name, kind, .. } => Some((name, kind)),
            _ => None,
        })
        .collect();
    let expected: Vec<(String, u32)> = values
        .iter()
        .map(|(name, _, kind)| (name.to_string(), *kind))
        .collect();
    assert_eq!(kinds, expected);
    for (name, value, kind) in values {
        assert_eq!(registry.query_value(key, name), Ok((value, kind)));
    }
}
