//! `credentials.py` (seat S7.2a): where a capability's secret goes - Windows Credential Manager, and nowhere else.
//!
//! A secret never touches advanced.sqlite, a settings file, a log or the journal, and it is never read from Codex's
//! own credentials (standard B11) - only from an entry this edition wrote, under a name of its own:
//! `CodexAutoResume/advanced/<capability id>/<name>`. [`Secrets`] checks the capability and the name and builds that
//! target; a backend (car-platform's `credman`) stores it. The real backend is made only by [`Secrets::windows`], which
//! the entry points call (S7.3d); every test and probe hands in `credman::Memory`.
//!
//! Also here: [`SystemTokens`], the state's `Tokens` (`secrets.token_hex`) over car-platform's random source.

use std::sync::Arc;

use car_machine::json::Value;
use car_platform::credman::{Backend, CredError, Windows};

use crate::registry::Registry;

/// `TARGET_PREFIX`.
pub const TARGET_PREFIX: &str = "CodexAutoResume/advanced/";
/// `MAX_SECRET_BYTES`: CRED_MAX_CREDENTIAL_BLOB_SIZE, 5 * 512 bytes.
pub const MAX_SECRET_BYTES: usize = 2560;

/// `SecretError`: a secret that could not be named, read, written or deleted. Never says what it was.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SecretError(pub &'static str);

impl std::fmt::Display for SecretError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for SecretError {}

impl From<CredError> for SecretError {
    fn from(error: CredError) -> Self {
        SecretError(error.0)
    }
}

/// `NAME_SHAPE.fullmatch(name)`: `[a-z][a-z0-9_]{0,31}`.
pub fn name_shape(name: &str) -> bool {
    let bytes = name.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 32
        && bytes[0].is_ascii_lowercase()
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'_')
}

/// `Secrets(registry, backend)`.
pub struct Secrets<'a> {
    pub registry: &'a Registry,
    backend: Arc<dyn Backend>,
}

impl<'a> Secrets<'a> {
    /// A store over the caller's backend (a test's `credman::Memory`).
    pub fn new(registry: &'a Registry, backend: Arc<dyn Backend>) -> Secrets<'a> {
        Secrets { registry, backend }
    }

    /// `Secrets(registry)`: over the real Credential Manager. Production entry points only.
    pub fn windows(registry: &'a Registry) -> Secrets<'a> {
        Secrets::new(
            registry,
            Arc::new(Windows {
                prefix: TARGET_PREFIX,
            }),
        )
    }

    /// `target(capability, name)`: the one name a capability's secret is kept under.
    pub fn target(&self, capability: &str, name: &Value) -> Result<String, SecretError> {
        if self.registry.get(capability).is_none() {
            return Err(SecretError("unknown capability"));
        }
        match name {
            Value::Str(name) => match name.as_str() {
                Some(name) if name_shape(name) => Ok(format!("{TARGET_PREFIX}{capability}/{name}")),
                _ => Err(SecretError("invalid secret name")),
            },
            _ => Err(SecretError("invalid secret name")),
        }
    }

    pub fn read(&self, capability: &str, name: &Value) -> Result<Option<String>, SecretError> {
        Ok(self.backend.read(&self.target(capability, name)?)?)
    }

    pub fn write(&self, capability: &str, name: &Value, secret: &Value) -> Result<(), SecretError> {
        let Value::Str(secret) = secret else {
            return Err(SecretError("invalid secret"));
        };
        // `len(secret.encode("utf-8"))`; a lone surrogate, which Python cannot encode, is no secret either.
        let Some(secret) = secret.as_str() else {
            return Err(SecretError("invalid secret"));
        };
        if secret.is_empty() || secret.len() > MAX_SECRET_BYTES {
            return Err(SecretError("invalid secret"));
        }
        Ok(self
            .backend
            .write(&self.target(capability, name)?, secret)?)
    }

    pub fn delete(&self, capability: &str, name: &Value) -> Result<bool, SecretError> {
        Ok(self.backend.delete(&self.target(capability, name)?)?)
    }
}

/// `secrets.token_hex`, from the operating system's random source (the state's `Tokens`, at the entry points).
pub struct SystemTokens;

impl crate::state::seam::Tokens for SystemTokens {
    fn hex(&self, count: usize) -> String {
        // os.urandom raising ends the reference's call; here a refusal panics, caught at its boundary (D15).
        car_platform::random::token_hex(count).expect("the system's random source")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_platform::credman::Memory;

    #[test]
    fn a_secret_is_kept_under_its_capability_and_name_alone() {
        let registry = Registry::new(crate::registry::definitions()).expect("registry");
        let secrets = Secrets::new(&registry, Arc::new(Memory::default()));
        let name = Value::Str("salt".into());
        let target = secrets.target("account_switch", &name);
        assert_eq!(
            target,
            Ok("CodexAutoResume/advanced/account_switch/salt".into())
        );
        assert_eq!(
            secrets.target("nobody", &name),
            Err(SecretError("unknown capability"))
        );
        let long = "a".repeat(33);
        for bad in ["", "Salt", "1salt", "a-b", long.as_str()] {
            let refused = secrets.target("account_switch", &Value::Str(bad.into()));
            assert_eq!(refused, Err(SecretError("invalid secret name")), "{bad}");
        }
        assert!(name_shape(&"a".repeat(32)));
        let refused = secrets.target("account_switch", &Value::from(1));
        assert_eq!(refused, Err(SecretError("invalid secret name")));
        assert_eq!(secrets.read("account_switch", &name), Ok(None));
        let secret = Value::Str("é".repeat(1280).into());
        assert_eq!(secrets.write("account_switch", &name, &secret), Ok(()));
        assert_eq!(
            secrets.read("account_switch", &name),
            Ok(Some("é".repeat(1280)))
        );
        for bad in [
            Value::Str("".into()),
            Value::Str("é".repeat(1281).into()),
            Value::Null,
        ] {
            let refused = secrets.write("account_switch", &name, &bad);
            assert_eq!(refused, Err(SecretError("invalid secret")));
        }
        assert_eq!(secrets.delete("account_switch", &name), Ok(true));
        assert_eq!(secrets.delete("account_switch", &name), Ok(false));
    }
}
