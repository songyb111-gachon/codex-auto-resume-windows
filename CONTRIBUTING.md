# Contributing

Thanks for looking. This is a small, deliberately conservative tool, so the most useful
contributions are usually bug reports with a reproduction, and fixes that keep the safety
properties intact.

## Development environment

- Windows 10/11. The product is Windows-only, and so is most of the test suite.
- Python 3.12 or newer, standard library only. There are no third-party runtime dependencies
  and no build step for the Python side.
- The ChatGPT/Codex desktop app, if you want to run anything beyond the unit tests.
- .NET Framework 4.8 (already on every supported Windows) to build the two small C#
  executables — the window and the MCP launcher (`gui/McpLauncher.cs`). The window is
  compiled from three sources: `gui/SettingsApp.cs` for the form and the Settings page,
  `gui/Dashboard.cs` for the navigation and the Overview, Pending, History, Statistics and
  Diagnostics pages, and `gui/Brand.cs` for the palette.

Nothing here needs administrator rights.

## Running the tests

```bash
python -m unittest discover -s tests
```

Set `PYTHONPATH=src` first, or run from a checkout where `src` is importable.

The suite uses fakes and temporary directories. It never contacts the ChatGPT app, never
sends a message to a Codex conversation, and never writes to your real registry. The live
read-only checks stay skipped unless you set `CODEX_AR_LIVE=1` on Windows.

Other parts skip quietly when the tool they need is missing, so a green run is not always a
full run. The schema-migration and downgrade tests build their databases from the store
code of real tagged releases, so those tags have to be in the checkout (`git fetch --tags`;
a shallow clone has none, which is why CI checks out the full history).
`tests/test_mcp.py` needs Node to run the panel's own code, and `tests/test_reproducible.py`
and `tests/test_gui_json.py` need the in-box C# compiler.

## Validating plugin metadata

The plugin manifest, the marketplace index and the MCP companion file are covered by
`tests/test_plugin.py`. Run the suite after touching any of them; it checks the manifest
against the fields Codex actually accepts, and it fails if the repository manifest starts
declaring an MCP server (see below).

## Building a release

This section describes the release process on the main branch. The split of the release
workflow into build and publish jobs, the actions pinned to commits, Dependabot, the
reproducible executables, the CRLF checkout and the executables' version resources are on
the main branch and ship in the release after v0.5.7. Every archive published so far,
v0.5.0 through v0.5.7, was built by the earlier single-job workflow, which referred to its
actions by floating tags, and with executables that cannot be reproduced.

```bash
powershell -ExecutionPolicy Bypass -File build/make_gui.ps1
python build/make_release.py
```

The first builds `CodexAutoResumeSettings.exe` and `codex-auto-resume-mcp.exe`, makes them
reproducible (below), and prints the compiler it used and each executable's SHA-256; it
needs `python` on `PATH` for that step. The second downloads the pinned embeddable Python
(checksum-verified), assembles the payload, and writes the ZIP and its SHA-256 into
`build/dist/`.

Releases are published by the tagged GitHub Actions workflow, not from a developer machine.
On the main branch it has two jobs. `build` runs the repository's code - the tests and the
build scripts - with a read-only token that checkout does not leave on disk. `publish`
holds the rights to create the release and attest it, runs none of the repository's
scripts or tests, and runs only on a tag push. Every action the workflows use is pinned to
a full commit SHA. Dependabot proposes updates as pull requests; `.github/dependabot.yml`
turns on no automatic merging, and each one is meant to be reviewed and merged by a person.
Nothing in the repository checks its own settings on GitHub.

### Making the build reproducible

The build is designed so that, from a fresh clone, with the same build of the in-box
compiler and the same Python build, the same source produces the same archive, byte for
byte, and a rebuild of a tag can be compared with the published digest. How far that has
been verified is set out below. It applies only to a tag whose source contains
`build/normalize_pe.py`, and no release from v0.5.0 through v0.5.7 has one. What it
relies on:

- **The executables.** The in-box C# compiler has no `/deterministic` switch, and two builds
  of the same source differ, as measured, in exactly two fields: the COFF header's timestamp and the
  module's random MVID. `build/normalize_pe.py` sets the first to a constant and the second
  to a GUID derived from the module's own content, as Roslyn's `/deterministic` does for the
  MVID. It locates both by parsing the PE and CLI metadata, and refuses a file that fails
  its structural checks, for example one with a debug directory or a PE checksum.
  `make_gui.ps1` runs it on both executables. The version resource they carry is
  generated from the manifest, so it depends on the source alone.
- **The archive.** `build/make_release.py` fixes the file order, the entry timestamps and
  the compression level, and writes no build-host path. The `zipfile` and `zlib` modules
  that write it still come from the Python that runs it, so for a comparison use the
  Python line the release workflow uses, 3.13, or at least the same zlib build: on
  Windows, Python 3.14 and later use zlib-ng, which can compress the same files to
  different bytes.
- **Line endings.** The archive packs source files, so their line endings are part of its
  bytes. `.gitattributes` checks every text file out with CRLF whatever the machine's
  `core.autocrlf` says; the repository still stores LF.
- **Checked, not assumed.** The release workflow builds the executables twice and refuses to
  continue if the digests differ, and `tests/test_reproducible.py` compiles a real program
  twice with the real compiler and holds the normaliser to the two-field claim.

How far that has been verified: two local builds, and a build from a separate clone,
produced identical executables; the archive writer reproduced a published archive byte
for byte from its entries with the same zlib (1.3.1). Whether GitHub's runner produces the
same bytes as a local build has not been verified. It depends on the build of the in-box
compiler, which is why `make_gui.ps1` prints it, and on the Python that writes the archive.

### Rebuilding a tag and comparing digests

For a tag whose source contains `build/normalize_pe.py`, start from a fresh clone, so
`.gitattributes` decides the line endings rather than an old checkout, and build with
Python 3.13:

```powershell
git clone --branch v<version> --depth 1 https://github.com/songyb111-gachon/codex-auto-resume-windows.git
cd codex-auto-resume-windows
powershell -ExecutionPolicy Bypass -File build/make_gui.ps1
python build/make_release.py
Get-Content .\build\dist\CodexAutoResume-v<version>-win-x64.zip.sha256
```

Compare the digest with the published `.sha256` and with the version's entry in
[`scripts/release.json` on `main`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json).
If they differ, compare the `compiler` line and the two executable digests `make_gui.ps1`
printed with the same lines in the release run's log, while GitHub still retains that log,
and compare the files inside the two archives;
[`docs/VERIFY.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md)
has a snippet that does that without extracting either. If every file matches and the
archive digest still differs, look at the Python and zlib that wrote the archive. A tag
whose source has no `build/normalize_pe.py` predates all of this - that is every release
published so far, v0.5.0 through v0.5.7 - and its executables will not match.

### After a release is published: pin its digest

The Codex plugin installs the release by downloading it, so it needs to know what the
archive should hash to. `scripts/release.json` maps a version to that digest, and a version
has no entry there until its archive exists (the v0.5.2 to v0.5.4 tags carried a `null`
placeholder, which the bootstrap treats the same as no entry; v0.5.0 and v0.5.1, published
before the table existed, have none at all). The archive contains `release.json`
itself, so it cannot carry its own digest, and the pin is taken from the published file
rather than from a local rebuild because it has to describe the bytes people download - and
a runner build matching a local one is the part that has not been verified. Absent and
`null` mean the same thing to the bootstrap, so there is no placeholder to add before
tagging and none to find afterwards: publishing adds the key.

So, once the release is up:

1. Download the published `CodexAutoResume-v<version>-win-x64.zip`.
2. `Get-FileHash <zip> -Algorithm SHA256` — and check it against the published `.sha256`.
3. Put that digest in `scripts/release.json` under the version, and commit.

Until that commit exists, the plugin verifies against the published `.sha256` sidecar
instead and says so when it runs. That is weaker — the sidecar comes from the same origin
as the archive — so it is worth closing rather than leaving. The commit does not reach the
plugin copy an install registers: that copy carries the archive's own `release.json`, so
for its own version it keeps falling back to the sidecar (or, with `-ArchivePath`, to no
comparison) and says so.

### Do not change a published version

`v0.5.4` is meant to name one archive, with one SHA-256, for as long as the release exists.
There is no supported way to change the bytes behind a published version, and the release
workflow, since v0.5.4, refuses to try: publishing stops if the version already has
assets.

This is not tidiness. The plugin's bootstrap pins a version's digest and refuses anything
else, so replacing a published archive either breaks every install of that version or -
worse - succeeds with bytes the pinned digest does not describe. Two people installing
"v0.5.4" a month apart have to get the same thing.

So a correction gets a new version. If a published archive turns out to be wrong, bump the
version, tag, and publish that; the mistaken release stays as a record of what was actually
released, which is the point of a release.

That refusal is the workflow's rule, not GitHub's. The releases from v0.5.0 through v0.5.7
are not GitHub "immutable releases" - a repository setting; GitHub reports each of them as
not immutable - so someone with write access could still replace an asset by hand. What
would show it is the digest pinned on `main`, and the build provenance attestation checked
against the release workflow and the tag, which is why
[`docs/VERIFY.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md)
tells users to check both.

The manual dispatch still exists. On the main branch it is a dry run: point it at any ref
and it builds, tests and verifies with a read-only token, then keeps the archive as a
workflow artifact. The publish job runs only on a tag push, so a dispatch of the
main-branch workflow cannot create or change a release. That is on the main branch and
ships in the release after v0.5.7. In the earlier single-job workflow, which built every
archive from v0.5.0 through v0.5.7, a dispatch ran with the workflow's write permissions.
In its v0.5.2 and v0.5.3 versions, a dispatch given a tag rebuilt that tag and replaced
the release's assets (`--clobber`). Those copies of the workflow remain at those tags, and
someone with write access can still dispatch them. Dispatched on its own tag, such a copy
first tries to create that version's release, which fails because the release exists, so
it reaches the replace step only when run from a branch that holds it. In its v0.5.0 to
v0.5.3 versions, a dispatch started on a tag with no release yet could also create that
release (in v0.5.2 and v0.5.3, from a build of the ref named in its `tag` input), with no
attestation. In its versions from v0.5.4 on, a dispatch started on a tag, while that version had no assets yet, could
publish and attest a build of any ref whose `plugin.json` declared that tag's version;
the attestation records which event started the run.

> Actions → **release** → Run workflow → optionally set **ref**.

### Changing anything visual

Colours, the icon and the generated files that carry them are covered in
[`docs/BRAND.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/BRAND.md).
The short version: the palette lives in `src/codex_auto_resume/brand.py`, `gui/Brand.cs`
and `assets/brand/icon.svg` are generated from it, and `tests/test_brand.py` regenerates
both and compares. Do not write a colour literal into the window or the panel stylesheet.
There is a test for that too, but it reads `gui/SettingsApp.cs` only — neither it nor the
test that catches sizes written in raw pixels looks at `gui/Dashboard.cs`, so a colour or a
raw pixel size written there is on you. Other tests do read that file: every Paint handler
must sit on a buffered control, every class that draws itself must be double-buffered, and
the long-lived bridge's command line is executed for real.

## The MCP declaration is added at build time

The repository manifest declares only `skills`. The release build adds `mcpServers` to the
copy it packs beside the bundled interpreter. That split is deliberate: the MCP server runs
on the interpreter that ships in the release archive, so declaring it in the repository would
make a marketplace install from GitHub register a command that is not there. Please do not
"fix" that by moving the declaration into the manifest — the build refuses to run if both
declare it.

## The Korean branch is generated

`ko` is built from `main`, by `.github/workflows/sync-ko.yml`, every time main's tests
pass — and it is force-updated. A pull request against `ko` cannot be merged and an edit
made there is lost at the next sync, so please do not spend an evening on one.

It was an independent fork until v0.5.5, with its own copy of the engine, the installer,
the workflows and the tests. It ended up three releases behind while still telling Korean
readers that the tool made no network request and that installing meant downloading a
release archive. That is what a second copy of a codebase does when somebody has to
remember to merge it.

So the code on `ko` is main's code, and the only difference is the language of the
documents. To change something there:

- **code, installer, workflows, tests** — change them on `main`; they reach `ko` unchanged.
- **Korean prose** — change the `.ko.md` file on `main`. `scripts/ko_branch.json` maps each
  one to the English page it replaces. What stays English is listed there too, with the
  reason: the licence, because a translated licence is a second licence, and the Codex
  skill, because it instructs Codex rather than a person.

`python scripts/ko_sync.py --check` shows what a sync would do without writing anything.
Adding a Korean page means adding the file and its mapping entry in the same commit;
`tests/test_korean.py` fails if a Korean page exists that nothing maps.

The mapping also records which English revision each translation was made from. Change an
English document and the suite fails naming both files, because a translation that goes
stale quietly is how `ko` spent three releases describing a tool that no longer existed.
Update the Korean, then record it:

```bash
python scripts/ko_sync.py --reviewed README.md
```

Nothing here is machine-translated. A person decides what the Korean says; the digest only
records that somebody did.

## Screenshots

`python build/make_screenshots.py` renders the whole set from the working tree: the Codex
panel, and the window's Overview, Pending and Settings pages, in English and Korean, into
`assets/` with copies in `docs/images/`. Nothing is captured by hand and nothing is edited
afterwards.

It needs Windows, Microsoft Edge (it is what renders the panel), and
`build/CodexAutoResumeSettings.exe` already built — run
`powershell -ExecutionPolicy Bypass -File build/make_gui.ps1` first. The first run also
downloads the pinned embeddable Python into `build/cache/`.

They are pinned to light. The product follows the reader's Windows and Codex themes at
runtime; the pictures do not, so that a gallery looks like one product and a build on a
machine in dark mode produces the same bytes as a build on one in light mode.

`assets/screenshots.json` records a digest of every input each image was rendered from —
the window's two sources, its palette, its DPI manifest, the plugin manifest, the icon, the
capture and build scripts, the rendered panel markup, and the engine modules the window's
figures and rows are computed from. `WINDOW_INPUTS` in `build/make_screenshots.py` is the
list. Change one and `tests/test_screenshots.py` fails telling you to re-run the generator.
It is the mechanism that stops a screenshot describing a version of the product that no
longer exists.

**One image is not generated: `docs/images/notification.png`.** It is a real Windows toast,
raised by the product and drawn by the shell, so it takes the machine's theme and cannot be
pinned — it is dark in a gallery that is otherwise light. Faking it in HTML would produce a
picture that is not a screenshot, which is worse. To retake it on a machine already in light
mode, raise one with example data and capture the banner:

```bash
python -c "import time; from codex_auto_resume import notify; notify.scheduled('00000000-0000-4000-8000-000000000000', 'example', time.time()+3600, 'usage_limit', {'name': 'example-project', 'project': 'example'})"
```

Use that nil-style UUID and those labels. Never photograph a real conversation: the toast
shows a thread identifier, and a screenshot of a real one publishes it permanently.

Note that Windows may add the notification without showing a banner — Do Not Disturb, or
banners turned off for this app in Settings → Notifications. It then lands in the Action
Center only, and there is nothing on screen to capture.

## Fixtures and privacy

Everything committed here is public, including test fixtures and documentation examples. They
are written on a developer's machine, and that machine's own paths and identifiers leak into
them very easily. `tests/test_repo_hygiene.py` enforces the conventions below, so please keep
to them rather than working around it.

- **Home directories in examples are placeholders.** Use `ExampleUser`, `Example User` (when
  you need a path containing a space), `someone`, `<user>`, or `%USERPROFILE%`. Never a real
  account name.
- **UUIDs in tracked files are obviously synthetic.** Use the project's fixture family,
  `0a1b2c3d-0001-7000-8000-000000000001` and friends, or a repeated-nibble value such as
  `22222222-2222-7222-8222-222222222222`. Never a conversation id copied out of real Codex
  state — real ones are UUIDv7 values with a timestamp prefix and are trivially recognisable.
- **No copied runtime state.** Databases, logs and `config/` are never tracked. If you need
  evidence that something behaves a certain way, write a fixture that shows the structure with
  synthetic values, the way `docs/evidence/` does.
- **No real process ids, ports or machine-specific paths** in comments, docs or fixtures.

## Changes that need extra care

The recovery engine is small on purpose, and several of its properties are the whole reason
the tool is safe to leave running. A change that touches any of these needs a test that would
fail without it:

- a conversation is identified by its exact UUID, and by nothing else — never `--last`, never a
  title, project, working directory or recency;
- a failure that cannot be classified is never retried;
- user cancellation, permission, approval, content policy, invalid requests, context length and
  permanent authentication failures are never retried;
- a submission whose outcome is unknown is never automatically resent;
- every gate is re-checked immediately before sending, inside the dispatch lock;
- settings are policy only. Nothing in the settings schema may reach a safety limit, and the
  worst a malformed settings file can do is make recovery more conservative.

If you are unsure whether a change crosses one of those lines, open an issue first and say
what you are trying to achieve — there is usually a way to get there that keeps the property.

## Commit and pull requests

- One change per commit, with a message that says what changed and why.
- Run the full suite before pushing.
- If you fixed something a user could hit, add the regression test in the same commit.
