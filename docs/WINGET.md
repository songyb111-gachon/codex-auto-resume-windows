# winget manifests

How the manifests for the Windows Package Manager community repository
([microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs)) are made, and how the maintainer submits them.
This is a maintainer's note, kept in English like the other build notes; it is not part of what the release ships.

## What is made

Two packages, one per edition, each a multi-file manifest (version, installer, the en-US default locale and a
ko-KR locale), schema 1.12.0:

| Edition | Package identifier | Installer it points at |
| --- | --- | --- |
| Standard | `songyb111-gachon.CodexAutoResume` | `CodexAutoResume-Setup-vX.Y.Z.exe` |
| Advanced | `songyb111-gachon.CodexAutoResume.Advanced` | `CodexAutoResume-Advanced-Setup-vX.Y.Z.exe` |

Both are the release's one-file Setup programs, installer type `exe`, scope `user`, no elevation, x64. The ZIP
archives do not fit: winget can run a nested installer of a known type from inside a ZIP, and `Install.cmd` is
none of them. Nor is either a portable package: the installer registers a sign-in start, a Start Menu entry and
the Codex plugin, none of which a portable layout carries.

`scripts/release.json` pins the archives, not the Setup programs, so each Setup program's SHA-256 comes from the
`.sha256` file published beside it (the same `<sha256>  <name>` file every release asset has).

## What the installer gives winget

From v0.6.16 both Setup programs meet what the community repository asks of an installer:

- **Silent install.** `CodexAutoResume-Setup-vX.Y.Z.exe -Silent` (and the Advanced one) asks nothing and waits for
  no key, and shows no window: without it the Setup program is the installer window, which winget never sees.
  The manifest's `Silent` and `SilentWithProgress` switches are both `-Silent`. Exit codes are the ones the
  installer has always had; 14, the other edition being installed (nothing changed, nobody to ask), is listed under
  `ExpectedReturnCodes` with a link to EDITIONS.md.
- **An entry in Add or remove programs**, so `winget list`, `winget upgrade` and `winget uninstall` find the
  installation: HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexAutoResume (the advanced edition:
  CodexAutoResumeAdvanced), with `DisplayName` "Codex Auto Resume" ("Codex Auto Resume Advanced"), `DisplayVersion`,
  `Publisher` "songyb111-gachon", `InstallLocation`, `UninstallString`, `QuietUninstallString` (with `-Silent`),
  `NoModify`, `NoRepair` and `DisplayIcon` (the installed program's icon). The manifest's `AppsAndFeaturesEntries` repeats the name, publisher and version, which is
  how winget matches them. Both uninstall commands run the installer's kept copy of itself in
  `%USERPROFILE%\.codex-auto-resume\uninstall\`: the quiet one directly, with `-Silent` and no window, and the other
  through the installation's Dashboard program (`CodexAutoResumeSettings.exe --uninstall <that script>`), which shows
  it in the installer window. An installation under `CODEX_AUTO_RESUME_PLUGIN_HOME` has no
  entry, and so is not one winget sees.

`build/winget_manifests.py` writes nothing for an earlier version without `--draft` (`UNATTENDED_FROM` in it is
0.6.16). The switch and the entry are held by `tests/test_add_remove.py` and `tests/test_winget_manifests.py`.

## Making the files, after a final release

1. The release is published and its archives are pinned in `scripts/release.json` (CONTRIBUTING, "After a release
   is published: pin its digest"). The generator refuses a version whose archive has no pin, and a pre-release.
2. Download the two small files `CodexAutoResume-Setup-vX.Y.Z.exe.sha256` and
   `CodexAutoResume-Advanced-Setup-vX.Y.Z.exe.sha256` into an empty folder (the Setup programs themselves are
   not needed), for instance with `gh release download vX.Y.Z --pattern "*Setup*.sha256" --dir <folder>`.
3. `python build/winget_manifests.py --version X.Y.Z --from-dir <folder>` writes
   `build/dist/winget/manifests/s/songyb111-gachon/CodexAutoResume/X.Y.Z/` and
   `.../CodexAutoResume/Advanced/X.Y.Z/` (`--out` changes the base; `--sha256 standard=<hex>` gives a digest by
   hand).

## Checking and submitting

On a machine where installing it for real is fine, such as Windows Sandbox:

- `winget validate --manifest <folder>` checks the files against the schema.
- `winget settings --enable LocalManifestFiles`, then `winget install --manifest <folder>` installs from them. It runs
  the real Setup program: do it in a sandbox or a virtual machine, not on a machine whose installation matters.
- `winget list`, `winget upgrade` and `winget uninstall` can be tried the same way, now that the entry exists.

Then, for each package (the repository takes one pull request per package version), fork microsoft/winget-pkgs,
copy that package's `manifests/s/songyb111-gachon/...` folder in, and open the pull request. The validation
pipeline runs on the pull request and reports there. `wingetcreate submit <folder>` does the same from a command
line. The Setup programs are unsigned (VERIFY.md, "Code signing"), so the pipeline's antivirus and reputation checks
may need a comment from the maintainer; the build provenance attestation is the evidence to point to.

Each later release is the same three steps with the new version. Nothing in the repository submits anything by
itself.

## Where the files come from

The files are written to manifest schema 1.12.0 (`SCHEMA` in `build/winget_manifests.py`: it has every field used
here, and the repository's current schema, 1.28.0, only adds two this does not write, so the files satisfy both).
The schema and the community repository's rules were read on 2026-10-16 from the
[Learn page on manifests](https://learn.microsoft.com/windows/package-manager/package/manifest), the repository's
[schema notes](https://github.com/microsoft/winget-pkgs/tree/master/doc/manifest/schema/1.28.0) and
[Authoring.md](https://github.com/microsoft/winget-pkgs/blob/master/doc/Authoring.md). `tests/test_winget_manifests.py`
holds the required fields of each file kind from that schema, with no network.
