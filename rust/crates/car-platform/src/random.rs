//! The operating system's random source (seat S7.2a): `os.urandom` and `secrets.token_hex`, which the advanced
//! edition draws its tokens, salts and pairing codes from. Windows' system-preferred generator (`BCryptGenRandom` with
//! `BCRYPT_USE_SYSTEM_PREFERRED_RNG`), which is what CPython's `os.urandom` calls on Windows.

use windows::Win32::Security::Cryptography::{BCRYPT_USE_SYSTEM_PREFERRED_RNG, BCryptGenRandom};

/// The generator refused (`os.urandom` raises OSError then).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RandomError(pub i32);

impl std::fmt::Display for RandomError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "the system's random source refused (NTSTATUS {:#010x})",
            self.0
        )
    }
}

impl std::error::Error for RandomError {}

/// `os.urandom(len(buffer))`, into `buffer`.
pub fn fill(buffer: &mut [u8]) -> Result<(), RandomError> {
    // BCryptGenRandom takes at most u32::MAX bytes a call; os.urandom asks in chunks of the same size.
    for chunk in buffer.chunks_mut(u32::MAX as usize) {
        // SAFETY: `chunk` is a live, writable slice for the whole call; no algorithm handle is passed, as the flag asks.
        let status = unsafe { BCryptGenRandom(None, chunk, BCRYPT_USE_SYSTEM_PREFERRED_RNG) };
        if status.is_err() {
            return Err(RandomError(status.0));
        }
    }
    Ok(())
}

/// `os.urandom(count)`.
pub fn bytes(count: usize) -> Result<Vec<u8>, RandomError> {
    let mut buffer = vec![0u8; count];
    fill(&mut buffer)?;
    Ok(buffer)
}

/// `secrets.token_hex(count)`: `count` random bytes as lowercase hex.
pub fn token_hex(count: usize) -> Result<String, RandomError> {
    Ok(hex(&bytes(count)?))
}

/// `bytes.hex()`.
pub fn hex(data: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut text = String::with_capacity(data.len() * 2);
    for byte in data {
        text.push(DIGITS[usize::from(byte >> 4)] as char);
        text.push(DIGITS[usize::from(byte & 15)] as char);
    }
    text
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_hex_is_lowercase_hex_of_the_length_asked() {
        for count in [0, 1, 16, 32, 100] {
            let token = token_hex(count).expect("random");
            assert_eq!(token.len(), count * 2);
            assert!(
                token
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            );
        }
        assert_ne!(
            token_hex(32).expect("random"),
            token_hex(32).expect("random")
        );
        assert_eq!(hex(&[0, 15, 16, 255]), "000f10ff");
    }
}
