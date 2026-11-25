//! The floats every repr is held to against Python's own `repr` (car-machine's writer and `pytext::float_repr`,
//! car-brand's `pyfmt::repr`), and the reference that answers them.
//!
//! Random bits alone seldom reach the floats where a shortest-digits rule goes wrong: a power of two is one draw in
//! 2^52, and a decimal boundary as rare. So the corpus is built, not drawn, where it matters:
//!
//! * every power of two in the f64 range (2^-1074 to 2^1023), both signs, and the four doubles around each;
//! * the subnormals: the 4,096 smallest, the 4,096 largest and the first normals after them;
//! * every decimal exponent: the doubles nearest 1e{k}, 5e{k}, 9.999999999999999e{k}, 9.9999999999999999e{k} and
//!   1.0000000000000002e{k} for k from -324 to 308, and the four doubles around each;
//! * `CAR_FLOAT_COUNT` random values (default 1,000,000; `CAR_FLOAT_SEED` in hex): finite bits drawn at random,
//!   random subnormals, decimals of 1 to 17 digits, and doubles a few steps from a random power of two.
//!
//! The reference is `python -I` (`CAR_JSON_PYTHON` names another): one 16-hex-digit line of bits in, one
//! `repr(x)` line out.

#![allow(dead_code)]

use std::io::{BufRead, BufReader, BufWriter, Write};
use std::process::{Command, Stdio};

pub const SEED: u64 = 0xF10A_7E5E_2026_1125;

/// SplitMix64: small, seeded, the same on every machine.
pub struct Rng(pub u64);

impl Rng {
    pub fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    pub fn below(&mut self, bound: u64) -> u64 {
        self.next() % bound
    }
}

fn setting(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|value| !value.is_empty())
}

/// `x` and the `steps` doubles on each side of it (finite ones only), both signs.
fn around(out: &mut Vec<f64>, x: f64, steps: i64) {
    for step in -steps..=steps {
        let y = f64::from_bits(x.abs().to_bits().wrapping_add_signed(step));
        if y.is_finite() && y >= 0.0 {
            out.push(y);
            out.push(-y);
        }
    }
}

/// What the built part of the corpus holds: (name, how many), in order.
pub fn built() -> Vec<(&'static str, Vec<f64>)> {
    let mut powers = Vec::new();
    for exponent in -1074..=1023 {
        around(&mut powers, 2f64.powi(exponent), 2);
    }
    // powi underflows to zero below 2^-1022 in some builds; the subnormal powers by their bits.
    for shift in 0..52 {
        around(&mut powers, f64::from_bits(1u64 << shift), 2);
    }
    let mut subnormals = Vec::new();
    for bits in 1..=4096u64 {
        subnormals.push(f64::from_bits(bits));
        subnormals.push(f64::from_bits(0x000F_FFFF_FFFF_FFFF - (bits - 1)));
        subnormals.push(f64::from_bits(0x0010_0000_0000_0000 + (bits - 1)));
    }
    let mut decimal = Vec::new();
    for k in -324..=308 {
        for mantissa in [
            "1",
            "5",
            "9.999999999999999",
            "9.9999999999999999",
            "1.0000000000000002",
        ] {
            let x: f64 = format!("{mantissa}e{k}").parse().expect("a decimal");
            if x.is_finite() && x != 0.0 {
                around(&mut decimal, x, 2);
            }
        }
    }
    let mut odd = vec![
        0.0,
        -0.0,
        f64::MAX,
        f64::MIN,
        f64::MIN_POSITIVE,
        f64::EPSILON,
    ];
    // The tie the first rule was written for: 224335367548872.625, half way between two 17-digit forms.
    odd.push(f64::from_bits(0x42E9_8104_BC95_F914));
    vec![
        ("powers of two and their neighbours", powers),
        ("subnormals and the first normals", subnormals),
        ("decimal boundaries and their neighbours", decimal),
        ("zeros, extremes and a tie", odd),
    ]
}

/// The random part: `CAR_FLOAT_COUNT` values from `CAR_FLOAT_SEED`.
pub fn random() -> Vec<f64> {
    let count: u64 =
        setting("CAR_FLOAT_COUNT").map_or(1_000_000, |text| text.parse().expect("CAR_FLOAT_COUNT"));
    let seed = setting("CAR_FLOAT_SEED").map_or(SEED, |text| {
        u64::from_str_radix(text.trim_start_matches("0x"), 16).expect("CAR_FLOAT_SEED, in hex")
    });
    let mut rng = Rng(seed);
    let mut out = Vec::with_capacity(count as usize);
    while (out.len() as u64) < count {
        let x = match rng.below(10) {
            0..=4 => f64::from_bits(rng.next()),
            5 => f64::from_bits(rng.below(0x0010_0000_0000_0000)),
            6 | 7 => {
                let width = 1 + rng.below(17) as u32;
                let mantissa = rng.below(10u64.pow(width.min(19)));
                let exponent = rng.below(640) as i64 - 330;
                format!("{mantissa}e{exponent}").parse().expect("a decimal")
            }
            _ => {
                let power = 2f64.powi(rng.below(2046) as i32 - 1022);
                let step = rng.below(9) as i64 - 4;
                f64::from_bits(power.to_bits().wrapping_add_signed(step))
            }
        };
        if x.is_finite() {
            out.push(if rng.below(2) == 0 { x } else { -x });
        }
    }
    out
}

/// The first of `python`, `python3`, `py` that runs (a Windows PC's `python` can be the Store's stub).
fn default_python() -> String {
    for name in ["python", "python3", "py"] {
        let mut probe = Command::new(name);
        probe.args(["-I", "-c", "import sys; sys.stdout.write(repr(0.5))"]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            probe.creation_flags(0x0800_0000);
        }
        if let Ok(out) = probe.output()
            && out.status.success()
            && out.stdout == b"0.5"
        {
            return name.to_owned();
        }
    }
    "python".to_owned()
}

const SCRIPT: &str = r#"
import struct, sys
out = sys.stdout
for line in sys.stdin:
    out.write(repr(struct.unpack(">d", bytes.fromhex(line.strip()))[0]))
    out.write("\n")
out.flush()
"#;

/// Python's `repr` of each value, in order, and the interpreter's version.
pub fn python_reprs(values: &[f64]) -> (Vec<String>, String) {
    let python = setting("CAR_JSON_PYTHON").unwrap_or_else(default_python);
    let mut command = Command::new(&python);
    command
        .args(["-I", "-c", SCRIPT])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let mut child = command
        .spawn()
        .unwrap_or_else(|error| panic!("the reference, `{python} -I`, did not start: {error}"));
    let mut stdin = BufWriter::with_capacity(1 << 20, child.stdin.take().expect("stdin"));
    let bits: Vec<u64> = values.iter().map(|x| x.to_bits()).collect();
    let feeder = std::thread::spawn(move || {
        for each in bits {
            writeln!(stdin, "{each:016x}").expect("the reference reads");
        }
        stdin.flush().expect("the reference reads");
    });
    let reader = BufReader::with_capacity(1 << 20, child.stdout.take().expect("stdout"));
    let answers: Vec<String> = reader.lines().map(|line| line.expect("a line")).collect();
    feeder.join().expect("the feeder");
    let status = child.wait().expect("the reference ends");
    assert!(status.success(), "the reference ended with {status}");
    let version = Command::new(&python)
        .args(["-I", "-c", "import sys; print(sys.version.split()[0])"])
        .output()
        .map(|out| String::from_utf8_lossy(&out.stdout).trim().to_owned())
        .unwrap_or_default();
    (answers, version)
}

/// Every value of the corpus through `ours`, against Python: panics naming the first ten that differ.
pub fn hold(name: &str, ours: impl Fn(f64) -> String) {
    let mut groups = built();
    groups.push(("random values", random()));
    let all: Vec<f64> = groups
        .iter()
        .flat_map(|(_, values)| values.iter().copied())
        .collect();
    let (python, version) = python_reprs(&all);
    assert_eq!(
        python.len(),
        all.len(),
        "the reference answered every value"
    );
    let mut at = 0;
    let mut differ = Vec::new();
    let mut counts = Vec::new();
    for (group, values) in &groups {
        let mut wrong = 0;
        for x in values {
            let got = ours(*x);
            if got != python[at] {
                wrong += 1;
                if differ.len() < 10 {
                    differ.push(format!(
                        "{group}: bits {:016x} python {} ours {got}",
                        x.to_bits(),
                        python[at]
                    ));
                }
            }
            at += 1;
        }
        counts.push(format!("{group} {} ({wrong} differ)", values.len()));
    }
    eprintln!("{name} against Python {version}: {}", counts.join(", "));
    assert!(
        differ.is_empty(),
        "{name} differs from Python's repr:\n{}",
        differ.join("\n")
    );
}
