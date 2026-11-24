//! The administrator's policy keys read from a REG_QWORD (S2.2), on a private hive (brief rule 3: never HKCU).
//!
//! Python's winreg hands a REG_QWORD back as an int, and `managed.parse` honours a switch or a ceiling of that type. The
//! real reader must too: read as bytes, an administrator's `DisableAutoResume` written as a QWORD would be lifted.

use car_platform::registry::{KEY_SET_VALUE, PrivateHive, Registry, Root, Value};
use car_platform::registry_reads::{POLICY_KEY, PolicyValue, read_policies};

#[test]
fn a_qword_policy_value_is_read_as_its_number() {
    let scratch = std::env::temp_dir().join(format!("car-platform-qword-{}", std::process::id()));
    std::fs::create_dir_all(&scratch).unwrap();
    let hive = PrivateHive::load(&scratch.join("private.hiv"))
        .expect("RegLoadAppKey: Windows refused a private hive");
    let registry = hive.registry();
    let key = registry
        .create_key_ex(Root::CurrentUser, POLICY_KEY, KEY_SET_VALUE)
        .expect("the key is made");
    registry
        .set_value(key, "DisableAutoResume", &Value::Qword(1))
        .expect("a QWORD is written");
    registry
        .set_value(key, "MaxRecoveryAttempts", &Value::Qword(3))
        .expect("a QWORD is written");
    registry
        .set_value(key, "ForceObserveOnly", &Value::Int(1))
        .expect("a DWORD is written");
    registry.close(key);
    // Both roots are the one hive here, so each place reads the same three values.
    for place in read_policies(&registry) {
        let found = |name: &str| {
            place
                .iter()
                .find(|(each, _)| each == name)
                .map(|(_, value)| value.clone())
        };
        assert_eq!(
            found("DisableAutoResume"),
            Some(PolicyValue::Data((Value::Qword(1), 11)))
        );
        assert_eq!(
            found("MaxRecoveryAttempts"),
            Some(PolicyValue::Data((Value::Qword(3), 11)))
        );
        assert_eq!(
            found("ForceObserveOnly"),
            Some(PolicyValue::Data((Value::Int(1), 4)))
        );
    }
    drop(hive);
    let _ = std::fs::remove_dir_all(&scratch);
}
