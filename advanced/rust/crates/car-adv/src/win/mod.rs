//! `win/`: the advanced edition's own Windows pieces (seat S7.2c remainder): [`stopflag`] (the supervisor's look at
//! the watcher's stop event) and [`waketimer`] (a timer that wakes the PC, and whether Windows allows one). Their
//! Windows calls are car-platform's `wake` traits (D3); nothing here calls Windows itself. [`appclose`] (the Restart
//! Manager's close of the app, no force) is seat S7.2b's over car-platform's `restart`; the skeleton (S7.2a) lists it.
//! [`dpapi`] (seat S7.2a) is `win/dpapi.py`: this product's label over car-platform's `dpapi`.

pub mod appclose;
pub mod dpapi;
pub mod stopflag;
pub mod waketimer;

#[cfg(test)]
mod tests {
    use std::path::Path;

    fn sources(folder: &Path, found: &mut Vec<(String, String)>) {
        for entry in std::fs::read_dir(folder).expect("src") {
            let path = entry.expect("entry").path();
            if path.is_dir() {
                sources(&path, found);
            } else if path.extension().is_some_and(|ext| ext == "rs") {
                let text = std::fs::read_to_string(&path).expect("source");
                found.push((path.display().to_string(), text));
            }
        }
    }

    /// P7-DESIGN 3.5 and 4: car-adv imports no suspend or shutdown call - the wake timer wakes, it never sleeps or
    /// shuts the PC down, and car-adv makes no Windows call of its own at all (D3).
    #[test]
    fn car_adv_names_no_suspend_or_shutdown_call() {
        let mut found = Vec::new();
        sources(
            &Path::new(env!("CARGO_MANIFEST_DIR")).join("src"),
            &mut found,
        );
        sources(
            &Path::new(env!("CARGO_MANIFEST_DIR")).join("examples"),
            &mut found,
        );
        assert!(found.len() > 20);
        let banned = [
            ["Set", "SuspendState"].concat(),
            ["Exit", "WindowsEx"].concat(),
            ["Initiate", "SystemShutdown"].concat(),
            ["Initiate", "Shutdown"].concat(),
            ["Set", "SystemPowerState"].concat(),
            ["windows", "::Win32"].concat(),
        ];
        for (path, text) in &found {
            for name in &banned {
                assert!(!text.contains(name.as_str()), "{path} names {name}");
            }
        }
    }
}
