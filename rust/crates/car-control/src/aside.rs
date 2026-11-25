//! `control/policy.py`'s `set_aside` and `_prune_set_aside`: where Restore defaults keeps a settings file the
//! product cannot read before it writes the defaults (v0.6.23, audit K1) - beside it, never over another.

use std::path::{Path, PathBuf};

use car_policy::settings::SettingsError;
use car_policy::settings::os::Os;

use crate::host::Host;

pub const SET_ASIDE_PREFIX: &str = "settings.unreadable-";
/// The newest few are kept and a new copy deletes the older ones (v0.6.26).
pub const SET_ASIDE_KEEP: usize = 5;

/// `time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(seconds))`.
pub fn stamp(seconds: f64) -> String {
    let whole = seconds.floor() as i64;
    let days = whole.div_euclid(86_400);
    let rest = whole.rem_euclid(86_400);
    // Howard Hinnant's civil_from_days.
    let shifted = days + 719_468;
    let era = shifted.div_euclid(146_097);
    let day_of_era = shifted.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_part = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_part + 2) / 5 + 1;
    let month = if month_part < 10 {
        month_part + 3
    } else {
        month_part - 9
    };
    let year = if month <= 2 { year + 1 } else { year };
    format!(
        "{year:04}{month:02}{day:02}T{:02}{:02}{:02}Z",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    )
}

/// `_SET_ASIDE_NAME.fullmatch(name)`: `settings.unreadable-<8 digits>T<6 digits>Z[-<digits>].json`.
fn parsed(name: &str) -> Option<(String, u64)> {
    let rest = name.strip_prefix(SET_ASIDE_PREFIX)?.strip_suffix(".json")?;
    let (when, number) = match rest.split_once('-') {
        Some((when, number)) => (when, Some(number)),
        None => (rest, None),
    };
    let bytes = when.as_bytes();
    let shaped = bytes.len() == 16
        && bytes[8] == b'T'
        && bytes[15] == b'Z'
        && bytes[..8].iter().all(|b| b.is_ascii_digit())
        && bytes[9..15].iter().all(|b| b.is_ascii_digit());
    if !shaped {
        return None;
    }
    let number = match number {
        None => 0,
        Some(digits) => {
            if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            digits.parse().unwrap_or(u64::MAX)
        }
    };
    Some((when.to_owned(), number))
}

fn is_link(path: &Path) -> bool {
    car_config::paths::is_link(&path.to_string_lossy())
}

/// `_prune_set_aside(folder, made)`: delete all but the newest `SET_ASIDE_KEEP` copies, oldest first; the copy
/// just made is always one of those kept.
fn prune(folder: &Path, made: &Path) {
    let mut found: Vec<(String, u64, PathBuf)> = Vec::new();
    let Ok(listing) = std::fs::read_dir(folder) else {
        return;
    };
    for entry in listing {
        let Ok(entry) = entry else { return };
        let name = entry.file_name().to_string_lossy().into_owned();
        let Some((stamp, number)) = parsed(&name) else {
            continue;
        };
        let path = entry.path();
        if Some(name.as_str()) != made.file_name().and_then(|each| each.to_str())
            && path.is_file()
            && !is_link(&path)
        {
            found.push((stamp, number, path));
        }
    }
    found.sort_by(|a, b| (&a.0, a.1).cmp(&(&b.0, b.1)));
    let drop = found.len().saturating_sub(SET_ASIDE_KEEP - 1);
    for (_, _, path) in found.into_iter().take(drop) {
        let _ = std::fs::remove_file(path);
    }
}

fn refused() -> SettingsError {
    SettingsError::Refused("the settings file could not be set aside; nothing was written".into())
}

/// `set_aside(path)`: the settings file renamed to `settings.unreadable-<UTC time>.json` beside it: its new path,
/// or None when there is no file (a link is never followed).
pub fn set_aside(
    host: &dyn Host,
    os: &dyn Os,
    path: &Path,
    now: f64,
) -> Result<Option<PathBuf>, SettingsError> {
    if !path.is_file() || os.is_symlink(path) {
        return Ok(None);
    }
    let when = stamp(now);
    for number in 0..100 {
        let suffix = if number > 0 {
            format!("-{number}")
        } else {
            String::new()
        };
        let aside = path.with_file_name(format!("{SET_ASIDE_PREFIX}{when}{suffix}.json"));
        if aside.exists() {
            continue;
        }
        match host.rename(path, &aside) {
            Ok(()) => {
                prune(path.parent().unwrap_or(Path::new(".")), &aside);
                return Ok(Some(aside));
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(_) => return Err(refused()),
        }
    }
    Err(refused())
}
