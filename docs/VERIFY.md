# Verifying a release

How to check that the archive you are about to install is the one this project published,
what the Codex plugin checks for you, how to rebuild a release yourself, and what none of
that covers.

## Why it is worth doing

What you extract from the release archive runs as you. It installs a watcher that, unless
you opt out, starts at every sign-in and can queue messages to your Codex conversations,
and it registers a plugin that Codex runs.

`Install.cmd` does not check the archive it came in. By the time it runs, the archive has
already been unpacked, and the installer cannot tell a genuine download from a modified
one. The check has to happen before you extract, and on the manual route you are the one
who makes it.

The programs and scripts this project builds are not code-signed (the bundled Python
interpreter keeps the signatures it was published with: the Python Software Foundation's,
and Microsoft's on the two Visual C++ runtime DLLs; see [Code signing](#code-signing)), so
the Windows dialog that would normally name a publisher has no publisher to name for them.
The digest is the check.

## Before you extract a downloaded archive

From the [releases page](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases),
download `CodexAutoResume-vX.Y.Z-win-x64.zip` and the `.sha256` file published beside it.
Do not extract anything yet. In PowerShell, in the folder you saved them to:

1. **Hash the archive.**

   ```powershell
   (Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
   ```

   `Get-FileHash` prints the digest in upper case; the published values are lower case.
   Compare them ignoring case. PowerShell's `-eq` already does, so each comparison below
   prints `True` or `False`.

2. **Compare it with the `.sha256` published beside the archive.**

   ```powershell
   $hash = (Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
   $hash -eq ((Get-Content .\CodexAutoResume-vX.Y.Z-win-x64.zip.sha256 -Raw) -split '\s+')[0]
   ```

   The release page also shows a SHA-256 digest beside each asset, computed by GitHub from
   the file it stores. It should be the same value.

3. **Compare it with the digest pinned for that version on `main`.** Open
   [`scripts/release.json` on the main branch](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json)
   and find the version, without its leading `v`, in the `sha256` table. Then:

   ```powershell
   $hash -eq '<the value listed for X.Y.Z>'
   ```

   Read it from `main`. The archive contains `release.json` itself, so it cannot contain
   its own digest. The pin is committed after the release is published, so the copy at
   the tag, committed before that, does not have that version's digest either (at most a
   `null` placeholder, which the bootstrap treats as absent). v0.5.0 and v0.5.1 have no
   entry at all; see the note after these steps.

4. **If you have the [GitHub CLI](https://cli.github.com/), check the build provenance.**

   ```powershell
   gh attestation verify .\CodexAutoResume-vX.Y.Z-win-x64.zip `
       --repo songyb111-gachon/codex-auto-resume-windows `
       --signer-workflow songyb111-gachon/codex-auto-resume-windows/.github/workflows/release.yml `
       --source-ref refs/tags/vX.Y.Z
   ```

   This succeeds only if an attestation exists for exactly this file's digest, signed for
   a run of `.github/workflows/release.yml` in this repository for the tag `vX.Y.Z`.
   Without `--signer-workflow` and `--source-ref`, the command accepts an attestation from
   any workflow run in the repository, on any branch or tag. Every archive from v0.5.4
   onwards has an attestation.

   The attestation also names a commit. For an archive published by a tag push, that is the
   commit that was built. The earlier single-job workflow, which built every archive from
   v0.5.0 through v0.5.7, could also publish from a manual run: among its versions that attest
   (v0.5.4 on), a run started on the tag, while that version had no assets yet, could publish
   and attest a build of any ref whose `plugin.json` declared that tag's version. The
   attestation records which event started the run. The workflow from v0.6.0 publishes only
   from a tag push; that change is new in v0.6.0.

Extract the archive and run `Install.cmd` only when every check you made agrees. If any of
them disagrees, do not extract it: delete the file and open an issue with the version and
the values you got.

v0.5.0 and v0.5.1 predate the `sha256` pin table and have no entry. For them only the `.sha256`
and the release-page digest apply (they have no attestation either). Any other version
that is on the releases page but missing from the table was published recently, and its
pin commit has not landed yet. You
can wait for it, or rely on the `.sha256` and the attestation, knowing what each one does
and does not prove:

| Check | What it tells you | What it does not |
| --- | --- | --- |
| `.sha256` beside the archive | The download is intact: you have the file GitHub is serving. | Who put it there. It comes from the same place as the archive, so a replaced archive can come with a matching replaced `.sha256`. |
| Digest on the release page | The same, computed by GitHub rather than by the workflow. | The same. |
| Digest pinned in `release.json` on `main` | The file is the one the maintainer recorded after publication, through a separate channel: a commit in the repository's history rather than a release file. Changing it takes another commit on `main`, which shows in the history unless someone with write access rewrites that history with a force-push; whether the branch is protected against that has not been verified. | That the file was built from the tagged source. The maintainer took the digest from the published file. |
| `gh attestation verify`, with the options in step 4 | The file was built by a run of the release workflow in this repository for that tag. For an archive published by a tag push, it was built from the commit the attestation names; the earlier single-job workflow could also publish from a manual run on the tag that built another ref whose `plugin.json` declared that version, and the attestation records which event started the run. | That the commit contains what you would want it to. |
| Rebuilding it yourself | For a release whose tag contains `build/normalize_pe.py`: the bytes come from the tagged source. | It applies to no release from v0.5.0 through v0.5.7, because none of their tags contains that file. See [the limitation](#what-a-rebuild-can-and-cannot-show-today) below. |

## What the plugin route checks for you

When you install from Codex, the plugin's `scripts/bootstrap.ps1` makes these checks
itself, before anything from the archive runs:

- It downloads from one URL shape, built from constants in `scripts/release.json` and the
  version in the plugin's own manifest. There is no "latest", and nothing you type becomes
  part of the URL.
- It uses HTTPS with TLS 1.2 at minimum, and refuses the download unless the final host,
  after redirects, is `github.com`, `objects.githubusercontent.com` or
  `release-assets.githubusercontent.com`.
- It compares the archive's SHA-256 with the digest pinned in the plugin's copy of
  `scripts/release.json`. A plugin added from the GitHub marketplace carries the pins that
  were on `main` when Codex last fetched it. If it was added before the pin commit landed,
  it falls back to the `.sha256` and says so. Installing, by either route, normally
  re-registers the plugin from the installed copy, whose `release.json` comes from the archive and so
  cannot hold its own version's digest. A later `-Force` or `-ArchivePath` run through
  that copy falls back to the `.sha256`, or compares against nothing, and says so.
- It checks that the archive holds the files every release must contain (the interpreter,
  the MCP server, its launcher and `.mcp.json`, the settings window, the plugin manifest,
  the setup script and the installer), that the payload root holds the settings window and
  its icon and nothing else — the installer copies that root into the installation home —
  that the manifest inside names this product at this version, and that no entry escapes
  the folder it is extracted into.
- Any failure stops, and the script then deletes its working copy of the download.

It does not check the attestation. When the installed version already matches, it
downloads nothing and re-runs setup instead, unless you pass `-Force`.

If you downloaded the archive yourself and also have the plugin, you can hand the file to
the same script with `-ArchivePath`. It is then checked against the pinned digest when
that version has one; in the plugin copy an install registered, the installed version has
none (see above). When it has none there is no published checksum to fetch for a local
file, so the script prints that the SHA-256 was not checked against anything, and only
the contents checks apply. When the installed version already matches, the script does
not use the file at all and re-runs setup instead, unless you also pass `-Force`.
[`docs/PLUGIN.md`](PLUGIN.md) describes the script in full.

## Rebuilding a release yourself

A rebuild compares a published archive with what its tagged source produces. It can match only
for a release whose tag contains `build/normalize_pe.py`, and no release from v0.5.0 through
v0.5.7 does. Reproducible builds - `build/normalize_pe.py`, the CRLF checkout and the release
workflow's second build - are new in v0.6.0. Every archive published so far, v0.5.0 through
v0.5.7, was built by the earlier single-job release workflow, which referred to its actions by
floating tags rather than pinned commits, and its executables carry a build time and a random
GUID that no rebuild reproduces. For those releases, the digest checks above apply, and the
attestation check applies from v0.5.4 on (there is no pinned digest for v0.5.0 or v0.5.1).

For a release whose tag has `build/normalize_pe.py`, you need:

- Windows 10 or 11 with .NET Framework 4.8, whose C# compiler the build uses. Windows 11
  and Windows 10 version 1903 or later include it; an older Windows 10 build, such as
  LTSC 2019, comes with 4.7.2, so for a digest comparison install 4.8 first.
- Git.
- Python on `PATH`. The build runs on Python 3.12 or newer, but for a digest comparison
  use Python 3.13, the line the release workflow uses. The archive is written by the
  `zipfile` and `zlib` modules of the Python that runs `build/make_release.py`, and on
  Windows, Python 3.14 and later use a different zlib implementation (zlib-ng), so a
  newer Python can write a different archive from identical files.
  `python -c "import zlib; print(zlib.ZLIB_RUNTIME_VERSION)"` prints the zlib yours uses;
  the builds compared so far all used zlib 1.3.1. The workflow does not pin the 3.13 patch
  release, and its run log names the one it installed.

No administrator rights are needed. The build downloads the embeddable Python it bundles
from python.org and refuses it unless its SHA-256 matches the one written in
`build/make_release.py`.

Start from a fresh clone. The archive packs source files, so their line endings are part
of its bytes, and an existing working tree may have been checked out under different
settings (see [below](#how-the-build-is-made-reproducible)).

```powershell
git clone --branch vX.Y.Z --depth 1 https://github.com/songyb111-gachon/codex-auto-resume-windows.git
cd codex-auto-resume-windows
git rev-parse HEAD
powershell -ExecutionPolicy Bypass -File build/make_gui.ps1
python build/make_release.py
Get-Content .\build\dist\CodexAutoResume-vX.Y.Z-win-x64.zip.sha256
```

`git rev-parse HEAD` prints the commit you built; it should be the commit the attestation
names. The last line should match the published `.sha256` and the digest pinned on
`main`. If it does, the published archive is exactly what that source produces.

`build/make_gui.ps1` prints the compiler it used (a `compiler` line with its version) and the
SHA-256 of each executable it built. The release run's log in the repository's Actions tab has
the same lines while GitHub retains the run's logs, which is for the repository's retention
period (90 days unless the repository sets otherwise), and GitHub shows them only to signed-in
users. In that log, the step that builds the executables a second time prints each one's digest
again. Comparing those tells you whether a difference is in the two compiled programs or
somewhere else. These lines and the second build are new in v0.6.0; the runs that built v0.5.0
through v0.5.7 print each executable's size, with no `compiler` line and no executable digest.

### How the build is made reproducible

These are new in v0.6.0.

- The in-box C# compiler has no `/deterministic` switch. Two builds of the same source
  differ, as measured, in exactly two fields: the PE header's timestamp and the module's random version
  GUID (MVID). `build/normalize_pe.py` sets the timestamp to a constant and replaces the
  GUID with one derived from the module's own content. It refuses a file that fails its
  structural checks, for example one with a debug directory or a PE checksum.
- `build/make_release.py` writes the archive with a fixed file order, fixed entry
  timestamps and a fixed compression level, and puts no path from the build machine in
  it. The compressed bytes still come from the zlib of the Python that runs it.
- `.gitattributes` checks every text file out with CRLF whatever the machine's Git
  settings, so the source files packed into the archive have the same line endings on
  every fresh checkout. The repository itself stores LF.
- The release workflow builds the executables twice and refuses to continue if the two
  builds differ.

### What a rebuild can and cannot show today

Two builds from two fresh clones of one commit, on one machine with the same compiler and
Python, produced a byte-identical archive, executables included. That is the extent of
what has been checked. Whether GitHub's runner
and your machine produce the same bytes has **not** been
verified. The result depends on the build of the in-box compiler, which can differ from
one Windows installation to another, and on the Python that writes the archive.

So a match is strong evidence. A mismatch is a reason to look closer, not proof of
tampering:

- **The tag predates reproducible builds.** That is the case for every release from
  v0.5.0 through v0.5.7. If the tag's source has no `build/normalize_pe.py`, its executables were
  stamped with a build time and a random GUID, and no rebuild of them will match.
- **A different compiler build.** Compare the `compiler` line your build printed with the
  one in the release run's log, while that log is retained.
- **A different Python or zlib build.** If every file inside the two archives is
  identical (the comparison below prints nothing) but the archive digests differ, the
  difference is in how the archive was written, which points to the compressor. Check
  that you built with Python 3.13 and which zlib it reports.
- **Which files differ.** This compares the files inside two archives without extracting
  either. Run it in the clone, with `$published` set to where you saved the download. It
  prints nothing when every file is identical, and otherwise lists each differing file
  with the side it came from: a file whose content differs appears once for each archive,
  and a file missing from one archive appears once.

  ```powershell
  function Get-ZipDigests([string]$Zip) {
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      $archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path $Zip))
      try {
          foreach ($entry in $archive.Entries) {
              $stream = $entry.Open()
              try { $digest = (Get-FileHash -InputStream $stream -Algorithm SHA256).Hash }
              finally { $stream.Dispose() }
              [pscustomobject]@{ Name = $entry.FullName; SHA256 = $digest }
          }
      } finally { $archive.Dispose() }
  }
  $published = "$HOME\Downloads\CodexAutoResume-vX.Y.Z-win-x64.zip"   # where you saved it
  Compare-Object (Get-ZipDigests $published) `
                 (Get-ZipDigests .\build\dist\CodexAutoResume-vX.Y.Z-win-x64.zip) -Property Name, SHA256
  ```

  For a tag built reproducibly, the Python, PowerShell and batch files in the archive are
  copied from the checked-out source unchanged, so a difference in one of those is worth
  an issue.

## Code signing

Nothing this project builds is Authenticode-signed: not the two executables, not
`Install.cmd` or `Uninstall.cmd`, and not the PowerShell scripts. The bundled Python interpreter - `pythonw.exe`, `python.exe` and its DLLs,
from the python.org embeddable runtime - keeps the signatures it was published with: the
Python Software Foundation's, and Microsoft's on the two Visual C++ runtime DLLs
(`vcruntime140.dll` and `vcruntime140_1.dll`).

- **The process that starts at sign-in is the signed interpreter.** For an installation from
the release archive with sign-in start on, Windows starts its bundled `pythonw.exe`. The Python
code it runs is this project's own and is not signed. - **What is not signed:** the settings
window `CodexAutoResumeSettings.exe`, the MCP launcher `codex-auto-resume-mcp.exe` that Codex
starts for the plugin's tools and panel, `Install.cmd` and `Uninstall.cmd`, and the project's
scripts. A `.cmd` file cannot carry an Authenticode signature at all. - From v0.6.0, the two
executables carry a version resource, so **Properties → Details** shows the product name, the
version, and a copyright line naming the author. That ships in v0.6.0; the executables in
v0.5.0 through v0.5.7 were built without that product information. It is text in the file, not
a signature: anyone can write it, and Windows' security prompts still name the publisher as
unknown.

What you may see because of that:

- **SmartScreen, on the manual route.** Extracting a downloaded ZIP with Explorer carries
  the download's mark of the web onto the extracted files, so running `Install.cmd` may
  show *Windows protected your PC* with an unknown publisher. That warning says the file
  is unsigned and not widely seen. It does not say the file failed a check. The digest
  checks above are what tell you it is the published file.
- **Smart App Control.** On a PC where it is on, it may block the unsigned programs and
  scripts, and it offers no exception for a single file. The watcher's process is the
  signed interpreter. A block applies to what it hits - for example the settings window,
  the plugin's tools and panel, `Install.cmd`, the installer's PowerShell scripts, or the
  C# code that setup compiles through PowerShell to create the Start Menu shortcut. That
  list has not been tested against Smart App Control. This project does not ask you to turn Smart App
  Control off.

If either one blocks you, please open an issue naming the file and the message.

## What is not verified

- **The releases are not GitHub immutable releases.** GitHub reports every release from
  v0.5.0 through v0.5.7 as not immutable. Immutability is the repository setting that
  makes GitHub itself refuse to change a published release's files or move its tag.
  The release workflow, from v0.5.4 on, refuses to publish over a version that already
  has assets. Its v0.5.2 and v0.5.3 versions did the opposite: a dispatch given a tag
  rebuilt that tag and replaced the release's assets (`--clobber`), and those copies of
  the workflow remain at those tags. Either way the rule binds the workflow, not everyone
  with write access to the repository, who can replace an asset by hand, or run one of
  those earlier copies from a branch that holds it (dispatched on its own tag, it stops
  when it tries to create a release that already exists). What would reveal a replaced archive is the digest pinned on `main`, and an
  attestation checked against the release workflow and the tag as in step 4, which is why
  the steps above use both.
- **The published archives came from the earlier release workflow.** Every archive
  published so far, v0.5.0 through v0.5.7, was built by a single job that referred to its
  actions by floating tags rather than pinned commits, and with executables that cannot be
  reproduced. The split into a build job and a publish job, the actions pinned to full
  commit SHAs, and Dependabot are new in v0.6.0.
- **Tags are not signed.** Cloning `vX.Y.Z` trusts that the tag still points where it
  did. For an archive published by a tag push, the attestation records the commit that
  was built, which is why the rebuild prints `git rev-parse HEAD`. The earlier single-job
  workflow, which built every archive from v0.5.0 through v0.5.7, could also publish from
  a manual run on the tag that built another ref whose `plugin.json` declared that
  version; the attestation records which event started the run.
- **A new release has no pin for a while.** The pin is committed after publication. Until
  then, and in a plugin copy fetched before it, the plugin route falls back to the
  published `.sha256` and says so. The plugin copy an install registers carries the
  archive's `release.json`, which cannot hold its own version's digest, so a later
  `-Force` run through it falls back to the `.sha256` and an `-ArchivePath` run compares
  against nothing, even once `main` has the pin; each says so.
- **Reproducibility across machines**, as described above, and no release from v0.5.0
  through v0.5.7 can be rebuilt to its published bytes.
- **`Install.cmd` does not check the archive**, and **the plugin route does not check the
  attestation.**
- **Archives before v0.5.4 have no attestation.**
- **Four proposed action upgrades were deferred past v0.6.0, deliberately.** Dependabot has
  open pull requests raising `actions/checkout` to v7.0.1, `actions/setup-python` to v7.0.0,
  `actions/attest-build-provenance` to v4.2.2, and the artifact pair to
  `upload-artifact` v7.0.1 with `download-artifact` v8.0.1. All four keep the full-commit
  pinning and its version comment, and none of them is a published security fix.

  v0.6.0 is the first release the split build-and-publish workflow has ever made. The
  artifact pair is what carries the archive from the unprivileged build job to the
  privileged publish job, and the attestation action is what the publish job signs with;
  changing either at the same moment as the first real use of that path would make a
  failure impossible to attribute to one of the two changes. The one concrete pressure is
  that GitHub now forces `checkout` and `setup-python` onto Node 24 because the Node 20
  they declare is deprecated, and says so on every run - but they run, and nothing about
  this release depends on that changing.

  After v0.6.0 is published and verified they go in one at a time, `checkout` and
  `setup-python` first because of that deprecation, then the artifact pair together -
  never one without the other - then the attestation, each with a `workflow_dispatch` dry
  run before the next tag.

Verifying tells you the file is the one this project published. It does not tell you the
code is safe; for what the code is allowed to do, and how that is enforced, see
[`SECURITY.md`](../SECURITY.md).
