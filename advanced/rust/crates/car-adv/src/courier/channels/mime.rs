//! What `email.message.EmailMessage` and `smtplib` make of one plain-text notice, as far as the courier's e-mail reads
//! them: `set_content`'s choice of transfer encoding (`email.contentmanager._encode_text` under `policy.default`),
//! quoted-printable (`email.quoprimime.body_encode`) and base64 (`binascii.b2a_base64`, `a2b_base64`), the flattened
//! message `BytesGenerator` writes, and HMAC-MD5 for CRAM-MD5. Pure byte work, no network.

#![allow(clippy::result_unit_err)]

/// `policy.default.max_line_length`.
const MAX_LINE: usize = 78;

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// `binascii.b2a_base64(data)`: one line, a newline after it.
pub fn b2a_base64(data: &[u8], newline: bool) -> String {
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4 + 1);
    for chunk in data.chunks(3) {
        let b = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let n = (u32::from(b[0]) << 16) | (u32::from(b[1]) << 8) | u32::from(b[2]);
        out.push(B64[(n >> 18) as usize & 63] as char);
        out.push(B64[(n >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            B64[(n >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            B64[n as usize & 63] as char
        } else {
            '='
        });
    }
    if newline {
        out.push('\n');
    }
    out
}

/// `binascii.a2b_base64(data)` (not strict): characters outside the alphabet skipped, the first complete padding
/// ends it; `Err` is binascii.Error (a ValueError): bits left over, or padding where none can be.
pub fn a2b_base64(data: &[u8]) -> Result<Vec<u8>, ()> {
    let mut out = Vec::new();
    let mut quad = 0usize;
    let mut left: u32 = 0;
    let mut pads = 0usize;
    for &c in data {
        if c == b'=' {
            if quad >= 2 {
                pads += 1;
                if quad + pads >= 4 {
                    // The group the padding completes: two characters make one byte, three make two.
                    if quad == 2 {
                        out.push((left >> 4) as u8);
                    } else {
                        out.extend_from_slice(&[(left >> 10) as u8, (left >> 2) as u8]);
                    }
                    return Ok(out);
                }
            }
            continue;
        }
        let Some(value) = B64.iter().position(|each| *each == c) else {
            continue;
        };
        pads = 0;
        left = (left << 6) | value as u32;
        quad += 1;
        if quad == 4 {
            out.extend_from_slice(&[(left >> 16) as u8, (left >> 8) as u8, left as u8]);
            quad = 0;
            left = 0;
        }
    }
    match quad {
        0 => Ok(out),
        _ => Err(()),
    }
}

/// `quoprimime.body_encode(body, maxlinelen, eol="\n")` over a body of latin-1 code points (one a byte).
pub fn qp_body_encode(body: &[u8], maxlinelen: usize) -> String {
    if body.is_empty() {
        return String::new();
    }
    let safe = |c: u8| c == b'\t' || (b' '..=b'~').contains(&c) && c != b'=';
    let mut translated = String::new();
    for &c in body {
        if safe(c) || c == b'\r' || c == b'\n' {
            translated.push(c as char);
        } else {
            translated.push_str(&format!("={c:02X}"));
        }
    }
    let quote = |c: char| format!("={:02X}", c as u32);
    let maxlinelen1 = maxlinelen - 1;
    let mut encoded: Vec<String> = Vec::new();
    // str.splitlines(): after the translation only CR, LF and CRLF are left to split on.
    let mut lines: Vec<&str> = Vec::new();
    let mut rest = translated.as_str();
    while !rest.is_empty() {
        match rest.find(['\r', '\n']) {
            Some(at) => {
                lines.push(&rest[..at]);
                let skip = if rest[at..].starts_with("\r\n") { 2 } else { 1 };
                rest = &rest[at + skip..];
            }
            None => {
                lines.push(rest);
                rest = "";
            }
        }
    }
    for line in lines {
        let bytes = line.as_bytes();
        let mut start: i64 = 0;
        let laststart = bytes.len() as i64 - 1 - maxlinelen as i64;
        while start <= laststart {
            let stop = (start + maxlinelen1 as i64) as usize;
            let begin = start as usize;
            if bytes[stop - 2] == b'=' {
                encoded.push(line[begin..stop - 1].to_owned());
                start = stop as i64 - 2;
            } else if bytes[stop - 1] == b'=' {
                encoded.push(line[begin..stop].to_owned());
                start = stop as i64 - 1;
            } else {
                encoded.push(format!("{}=", &line[begin..stop]));
                start = stop as i64;
            }
        }
        let begin = start as usize;
        match line.chars().last() {
            Some(last @ (' ' | '\t')) => {
                let room = start - laststart;
                let q = if room >= 3 {
                    quote(last)
                } else if room == 2 {
                    format!("{last}=\n")
                } else {
                    format!("=\n{}", quote(last))
                };
                encoded.push(format!("{}{}", &line[begin..line.len() - 1], q));
            }
            _ => encoded.push(line[begin..].to_owned()),
        }
    }
    if matches!(body.last(), Some(b'\r' | b'\n')) {
        encoded.push(String::new());
    }
    encoded.join("\n")
}

/// `bytes.splitlines()`: on LF, CR and CRLF.
fn byte_lines(data: &[u8]) -> Vec<&[u8]> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut at = 0;
    while at < data.len() {
        match data[at] {
            b'\n' => {
                lines.push(&data[start..at]);
                at += 1;
                start = at;
            }
            b'\r' => {
                lines.push(&data[start..at]);
                at += if data.get(at + 1) == Some(&b'\n') {
                    2
                } else {
                    1
                };
                start = at;
            }
            _ => at += 1,
        }
    }
    if start < data.len() {
        lines.push(&data[start..]);
    }
    lines
}

/// `_encode_text(text, "utf-8", None, policy.default)`: the transfer encoding and the payload's bytes (an 8bit
/// payload is the text's own UTF-8, as `surrogateescape` carries it).
pub fn encode_text(text: &str) -> (&'static str, Vec<u8>) {
    let lines = byte_lines(text.as_bytes());
    let joined = |lines: &[&[u8]]| {
        let mut body = lines.join(&b"\n"[..]);
        body.push(b'\n');
        body
    };
    let normal = joined(&lines);
    if lines.iter().map(|line| line.len()).max().unwrap_or(0) <= MAX_LINE {
        return if normal.is_ascii() {
            ("7bit", normal)
        } else {
            ("8bit", normal)
        };
    }
    let sniff = joined(&lines[..lines.len().min(10)]);
    let sniff_qp = qp_body_encode(&sniff, MAX_LINE);
    let sniff_base64 = b2a_base64(&sniff, true);
    if sniff_qp.len() > sniff_base64.len() {
        let per_line = MAX_LINE / 4 * 3;
        let encoded: String = normal
            .chunks(per_line)
            .map(|chunk| b2a_base64(chunk, true))
            .collect();
        return ("base64", encoded.into_bytes());
    }
    if lines.len() <= 10 {
        return ("quoted-printable", sniff_qp.into_bytes());
    }
    (
        "quoted-printable",
        qp_body_encode(&normal, MAX_LINE).into_bytes(),
    )
}

/// The message `smtplib.send_message` flattens (`BytesGenerator`, `linesep="\r\n"`, `mangle_from_` on): the
/// Subject, From and To set in that order, then `set_content(text)`'s Content-Type, Content-Transfer-Encoding and
/// MIME-Version, a blank line and the payload, each line ended by CRLF and a line starting `From ` written `>From `.
pub fn flatten(subject: &str, from: &str, to: &str, text: &str) -> Vec<u8> {
    let (cte, payload) = encode_text(text);
    let mut out = Vec::new();
    for (name, value) in [
        ("Subject", subject),
        ("From", from),
        ("To", to),
        ("Content-Type", "text/plain; charset=\"utf-8\""),
        ("Content-Transfer-Encoding", cte),
        ("MIME-Version", "1.0"),
    ] {
        out.extend_from_slice(format!("{name}: {value}\r\n").as_bytes());
    }
    out.extend_from_slice(b"\r\n");
    // NLCRE.split(payload): every CRLF, CR or LF a line end; the last piece written only where it is not empty.
    let mut lines = byte_lines(&payload);
    let ends_open = !matches!(payload.last(), Some(b'\r' | b'\n'));
    let last = if ends_open { lines.pop() } else { None };
    for line in lines {
        if line.starts_with(b"From ") {
            out.push(b'>');
        }
        out.extend_from_slice(line);
        out.extend_from_slice(b"\r\n");
    }
    if let Some(line) = last {
        if line.starts_with(b"From ") {
            out.push(b'>');
        }
        out.extend_from_slice(line);
    }
    out
}

// ------------------------------------------------------------------------------------------ MD5
/// MD5 (RFC 1321), for HMAC-MD5 alone.
pub fn md5(data: &[u8]) -> [u8; 16] {
    const S: [u32; 64] = [
        7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5,
        9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10,
        15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
    ];
    let k: Vec<u32> = (0..64)
        .map(|i| ((i as f64 + 1.0).sin().abs() * 4_294_967_296.0) as u32)
        .collect();
    let mut message = data.to_vec();
    let bits = (data.len() as u64).wrapping_mul(8);
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&bits.to_le_bytes());
    let (mut a0, mut b0, mut c0, mut d0) =
        (0x67452301u32, 0xefcdab89u32, 0x98badcfeu32, 0x10325476u32);
    for block in message.chunks(64) {
        let m: Vec<u32> = block
            .chunks(4)
            .map(|w| u32::from_le_bytes([w[0], w[1], w[2], w[3]]))
            .collect();
        let (mut a, mut b, mut c, mut d) = (a0, b0, c0, d0);
        for i in 0..64 {
            let (f, g) = match i / 16 {
                0 => ((b & c) | (!b & d), i),
                1 => ((d & b) | (!d & c), (5 * i + 1) % 16),
                2 => (b ^ c ^ d, (3 * i + 5) % 16),
                _ => (c ^ (b | !d), (7 * i) % 16),
            };
            let f = f.wrapping_add(a).wrapping_add(k[i]).wrapping_add(m[g]);
            a = d;
            d = c;
            c = b;
            b = b.wrapping_add(f.rotate_left(S[i]));
        }
        a0 = a0.wrapping_add(a);
        b0 = b0.wrapping_add(b);
        c0 = c0.wrapping_add(c);
        d0 = d0.wrapping_add(d);
    }
    let mut out = [0u8; 16];
    for (i, word) in [a0, b0, c0, d0].iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&word.to_le_bytes());
    }
    out
}

/// `hmac.HMAC(key, message, "md5").hexdigest()`.
pub fn hmac_md5_hex(key: &[u8], message: &[u8]) -> String {
    let mut key = if key.len() > 64 {
        md5(key).to_vec()
    } else {
        key.to_vec()
    };
    key.resize(64, 0);
    let inner: Vec<u8> = key
        .iter()
        .map(|b| b ^ 0x36)
        .chain(message.iter().copied())
        .collect();
    let inner = md5(&inner);
    let outer: Vec<u8> = key
        .iter()
        .map(|b| b ^ 0x5c)
        .chain(inner.iter().copied())
        .collect();
    car_machine::hash::hex(&md5(&outer))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn md5_and_hmac_are_rfc_s() {
        assert_eq!(
            car_machine::hash::hex(&md5(b"")),
            "d41d8cd98f00b204e9800998ecf8427e"
        );
        assert_eq!(
            car_machine::hash::hex(&md5(b"The quick brown fox jumps over the lazy dog")),
            "9e107d9d372bb6826bd81d3542a419d6"
        );
        // RFC 2104's second test case.
        assert_eq!(
            hmac_md5_hex(b"Jefe", b"what do ya want for nothing?"),
            "750c783e6ab0b503eaa86e310a5db738"
        );
    }

    #[test]
    fn base64_is_binascii_s() {
        assert_eq!(b2a_base64(b"\0user\0pass", false), "AHVzZXIAcGFzcw==");
        assert_eq!(
            a2b_base64(b"AHVzZXIAcGFzcw=="),
            Ok(b"\0user\0pass".to_vec())
        );
        assert_eq!(a2b_base64(b"AHV"), Err(()));
    }
}
