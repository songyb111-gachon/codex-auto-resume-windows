# Contributing

Thanks for looking. This is a small, deliberately conservative tool, so the most useful
contributions are usually bug reports with a reproduction, and fixes that keep the safety
properties intact.

## Development environment

- Windows 10/11. The product is Windows-only, and so is most of the test suite.
- Python 3.12 or newer, standard library only. There are no third-party runtime dependencies
  and no build step for the Python side. What that promise covers is decided in one file,
  `scripts/python_support.json`: CI runs every non-live test on Python 3.12, 3.13 and 3.14 as
  blocking jobs, and on the 3.15 pre-release as an advisory one whose result is shown but does
  not block; releases are built with 3.13; and the archive bundles Python 3.13.15, so nobody
  installing a release needs a Python of their own. Adding a tested version never moves the
  bundled runtime. `tests/test_python_support.py` fails if the workflows, or the minimum this
  page and the README state, stop agreeing with that file.
- The ChatGPT/Codex desktop app, if you want to run anything beyond the unit tests.
- .NET Framework 4.8 (already on every supported Windows) to build the two small C#
  executables — the window and the MCP launcher (`gui/McpLauncher.cs`). The window is
  `gui/SettingsApp.cs` for the form and the Settings page and `gui/Dashboard.cs` for the
  navigation and the Overview, Pending, History, Statistics and Diagnostics pages; the soft
  controls both are drawn with are `gui/SoftTheme.cs` (the colours, sizes and motion),
  `gui/SoftDepth.cs` (the shadows), `gui/SoftLayout.cs` (what holds what), `gui/SoftFields.cs`
  (buttons, check boxes, choices and text), `gui/SoftCombo.cs` (the drop-down),
  `gui/SoftCallout.cs` (the callout, a notice set apart), `gui/SoftList.cs` and `gui/Marks.cs`
  (the status light); and `gui/Brand.cs` is the palette, generated. The compile list is
  `gui/window.sources` and only there — a new window source is added to that one file, and
  `build/make_gui.ps1` and every test read it.

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

What a green run does and does not establish is set out capability by capability in
[`docs/FEATURE_MATRIX.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/FEATURE_MATRIX.md), and the checks
no suite can make - a real install, a real interruption, a real send - are the procedure in
[`docs/LIVE_ACCEPTANCE.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/LIVE_ACCEPTANCE.md).

## Measuring the window

Speed is a claim like any other, and `build/measure_window.py` is how it is checked rather than
believed. It builds `gui/*.cs` into a scratch folder and walks the real window page by page and
section by section - `SettingsForm.LayoutAudit`, off screen, with no bridge and no timers - at two
languages and two scales, and prints the medians:

```bash
py build/measure_window.py
py build/measure_window.py --tree <another checkout>
```

Timings belong to a machine, so the suite asserts none of them; what it holds is the behaviour the
speed comes from, such as `tests/test_gui_v069_idle.py`, which fails if an unchanged snapshot makes
the window fill a list or rebuild the safety checks again. The v0.6.9 numbers are in that file's
header and in the changelog.

## Validating plugin metadata

The plugin manifest, the marketplace index and the MCP companion file are covered by
`tests/test_plugin.py`. Run the suite after touching any of them; it checks the manifest
against the fields Codex actually accepts, and it fails if the repository manifest starts
declaring an MCP server (see below).

## Building a release

This section describes the release process as it is from v0.6.0. The split of the release
workflow into build and publish jobs, the actions pinned to commits, Dependabot, the
reproducible executables, the CRLF checkout and the executables' version resources are new in
v0.6.0. Every archive published so far, v0.5.0 through v0.5.7, was built by the earlier
single-job workflow, which referred to its actions by floating tags, and with executables that
cannot be reproduced.

```bash
powershell -ExecutionPolicy Bypass -File build/make_gui.ps1
python build/make_release.py
python build/smoke_archive.py build/dist/CodexAutoResume-v<version>-win-x64.zip <version>
```

The first builds `CodexAutoResumeSettings.exe` and `codex-auto-resume-mcp.exe`, makes them
reproducible (below), and prints the compiler it used and each executable's SHA-256; it
needs `python` on `PATH` for that step. The second downloads the pinned embeddable Python
(checksum-verified), assembles the payload, and writes the ZIP and its SHA-256 into
`build/dist/`.

The third drives the archive's own bytes: it extracts the ZIP and runs the engine inside
it with the interpreter inside it, against a state directory that exists only for that run,
and reads the version resource off both executables. Nothing outside that directory is
touched - no registration, no watcher, and `plugin_setup.py` is never run, because a smoke
test that repoints the sign-in entry at a temporary folder and then deletes the folder has
broken the installation it was checking. Run it again on the **published** archive once the
release exists: "the build works" and "what people download works" are different sentences,
and only the second is a promise to anybody.

Releases are published by the tagged GitHub Actions workflow, not from a developer machine.
From v0.6.0 it has two jobs. `build` runs the repository's code - the tests and the build
scripts - with a read-only token that checkout does not leave on disk. `publish` holds the
rights to create the release and attest it, runs none of the repository's scripts or tests, and
runs only on a tag push. Every action the workflows use is pinned to a full commit SHA.
Dependabot proposes updates as pull requests; `.github/dependabot.yml` turns on no automatic
merging, and each one is meant to be reviewed and merged by a person. Nothing in the repository
checks its own settings on GitHub.

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
  its structural checks, for example one with a debug directory or a PE checksum. One
  construct adds a third varying value that no after-the-fact edit can fix: a string `switch`
  with enough cases makes the compiler emit a class named `<PrivateImplementationDetails>{GUID}`
  with a fresh random GUID (measured: six cases did, four did not). The normaliser refuses any
  executable that holds such a class, so the build fails on the machine that made it.
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
  twice with the real compiler and holds the normaliser to the two-field claim. It also
  compiles a program with a long string `switch` and checks the normaliser refuses it, and
  holds the window's own source to having no such `switch`. That rule was learned from the
  first v0.6.3 release run, whose two builds differed and which published nothing.

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

A planned pre-release - a suffixed tag such as `v0.6.9-alpha` - is not pinned at all. The
table's keys are releases, `releases/latest` never answers with a pre-release, so nothing is
served one, and the check that a tagged version carries a pin is told about it by the
`prerelease` list in `scripts/release.json` instead. That list may name the version under
development and nothing else, so the next bump has to remove the entry
(`tests/test_convergence.py` fails until it does).

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

The manual dispatch still exists. From v0.6.0 it is a dry run: point it at any ref and it
builds, tests and verifies with a read-only token, then keeps the archive as a workflow
artifact. The publish job runs only on a tag push, so a dispatch of the main-branch workflow
cannot create or change a release. That is new in v0.6.0. In the earlier single-job workflow,
which built every archive from v0.5.0 through v0.5.7, a dispatch ran with the workflow's write
permissions. In its v0.5.2 and v0.5.3 versions, a dispatch given a tag rebuilt that tag and
replaced the release's assets (`--clobber`). Those copies of the workflow remain at those tags,
and someone with write access can still dispatch them. Dispatched on its own tag, such a copy
first tries to create that version's release, which fails because the release exists, so it
reaches the replace step only when run from a branch that holds it. In its v0.5.0 to v0.5.3
versions, a dispatch started on a tag with no release yet could also create that release (in
v0.5.2 and v0.5.3, from a build of the ref named in its `tag` input), with no attestation. In
its versions from v0.5.4 on, a dispatch started on a tag, while that version had no assets yet,
could publish and attest a build of any ref whose `plugin.json` declared that tag's version;
the attestation records which event started the run.

> Actions → **release** → Run workflow → optionally set **ref**.

### Changing anything visual

Colours, the icon and the generated files that carry them are covered in
[`docs/BRAND.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/BRAND.md).
The short version: the palette lives in `src/codex_auto_resume/brand/`, `gui/Brand.cs`
and `assets/brand/icon.svg` are generated from it, and `tests/test_brand.py` regenerates
both and compares. Do not write a colour literal into the window or the panel stylesheet.
`tests/test_gui_theme.py` refuses one - a literal, a named colour, or a light brand colour
drawn directly - in every hand-written source of the window: the `[settings]`, `[dashboard]`
and `[controls]` groups of `gui/window.sources`, so a file added to a group is covered without
an edit. The test that catches sizes written in raw pixels (`tests/test_brand.py`) reads the
`[settings]` half only, so a raw pixel size written in the Dashboard's files is on you. Other
tests do read those: every Paint handler must sit on a buffered control, every class that
draws itself must be double-buffered, and the long-lived bridge's command line is executed for
real.

## The MCP declaration is added at build time

The repository manifest declares only `skills`. The release build adds `mcpServers` to the
copy it packs beside the bundled interpreter. That split is deliberate: the MCP server runs
on the interpreter that ships in the release archive, so declaring it in the repository would
make a marketplace install from GitHub register a command that is not there. Please do not
"fix" that by moving the declaration into the manifest — the build refuses to run if both
declare it.

## Translations

The interface speaks nine languages, and every word of it - the Dashboard, the popup and
menu, notifications, the panel in Codex and the continuation message - comes from a catalog:
`src/codex_auto_resume/locales/<locale>.json`, one per language. English (`en.json`) is the
source. Every other catalog is a translation of it, and at runtime English fills in any key a
translation has not reached yet. A new sentence a user will read is a new key in `en.json`.

A translation is only as current as the English it was made from, so `build/l10n.py` records,
key by key, a digest of that English in `build/l10n/<locale>.basis.json`:

```bash
python build/l10n.py status                 # missing, stale and extra keys, per language
python build/l10n.py export ja > work.json  # only the keys that need a translator
python build/l10n.py import ja work.json    # merge, validate, record the basis
python build/l10n.py mark ja KEY [KEY ...]  # reviewed: still right for the new English
python build/l10n.py prune ja               # drop keys English no longer has
python build/l10n.py check                  # exit 1 if anything is incomplete
```

So adding an English string, or changing one, is not finished until every catalog has caught
up: the key is missing or stale in the other eight, and `tests/test_l10n.py` fails until each
has been translated and imported, or marked as reviewed. An import that loses or invents a
placeholder is refused. Nothing here reaches the network, and a test holds the localization
modules and this tool to that.

## Branches and languages

Three branches carry the documents three ways:

- **`dev`** holds every document in both languages: `X.md` and its Korean sibling `X.ko.md`,
  written and reviewed in the same commit. Work happens here, and every Korean check runs here.
- **`main`** is English only. It is the repository's front page, the branch the plugin
  installs from and the one releases are tagged on. It receives dev by a *promotion*, never a
  fast-forward: `python scripts/promote.py to-main --title "..."` merges dev, deletes every
  `*.ko.md`, and names the dev commit in a `Korean-sources:` trailer. What main receives on its
  own - the compatibility data, published by pull request - goes back with
  `python scripts/promote.py into-dev`, which keeps dev's Korean documents exactly as they were.
- **`ko`** is generated from `main`, by `.github/workflows/sync-ko.yml`, every time main's
  tests pass - and it is force-updated: main's code, with the Korean sources of the dev commit
  main was promoted from written over the English pages. A pull request against `ko` cannot be
  merged and an edit made there is lost at the next sync, so please do not spend an evening on
  one.

CI holds the split: on a push to `main` no `*.ko.md` may exist, and on a push to `dev` every
mapped one must (`tests/languages.py`, `tests/test_korean.py`), so dev cannot quietly skip its
Korean checks and main cannot grow a Korean file back.

`ko` was an independent fork until v0.5.5, with its own copy of the engine, the installer,
the workflows and the tests. It ended up three releases behind while still telling Korean
readers that the tool made no network request and that installing meant downloading a
release archive. That is what a second copy of a codebase does when somebody has to
remember to merge it.

So the code on `ko` is main's code, and the only difference is the language of the
documents. To change something there:

- **code, installer, workflows, tests** — change them on `dev`; they reach `main` at the
  next promotion and `ko` at the sync after it.
- **Korean prose** — change the `.ko.md` file on `dev`, beside its English page.
  `scripts/ko_branch.json` maps each one to the English page it replaces. What stays English is listed there too, with the
  reason: the licence, because a translated licence is a second licence, and the Codex
  skill, because it instructs Codex rather than a person.

`python scripts/ko_sync.py --check` on dev shows what a sync would do without writing anything.
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
machine in dark mode produces the same bytes as a build on one in light mode. The notification
card is the one exception: it floats over whatever desktop the reader has, so it is pictured in
both themes, each picture named for its theme and drawn in it.

`assets/screenshots.json` records a digest of every input each image was rendered from.
The window is recorded in two halves. One is the files it is compiled from — its three
sources, its palette, its DPI manifest, the plugin manifest, the icon, and the capture and
build scripts; `WINDOW_INPUTS` in `build/make_screenshots.py` is that list. The other is what
the bridge tells it: the generator asks the bridge the window's own questions against a
scratch installation, with the clock, the paths and the machine's answers pinned, and records
a hash of the replies (`<bridge envelope:*>`). The panel is recorded as its rendered markup,
and the popup as the view it draws plus a digest of the code that draws it, pooled by
definition name across the popup's modules and the palette's, and across what those import by
name from the rest of the package, wherever it is defined. So moving code from one module
to another leaves the manifest alone, while a change to anything a picture shows — a word, a
row, a figure, a status, a colour — does not. Change one and `tests/test_screenshots.py`
fails telling you to re-run the generator. It is the mechanism that stops a screenshot
describing a version of the product that no longer exists.

To see what a `<bridge envelope:*>` entry is made of, run this from the repository root; it
prints the questions and the replies the digest is taken over:

```
python -X utf8 -c "import sys; sys.path.insert(0, 'build'); import make_screenshots as m; print(m.bridge_envelope('en'))"
```

**The notification card is rendered, not photographed.** The generator draws it off-screen
the way `tests/test_notice_card.py` does — a `notice_window.Card` with no windows, painted by
the popup's renderer, with its floating shadow over the theme's canvas — from the notice the
watcher's own builder makes for the sample's usage limit, with the reset time read on a clock
pinned to UTC. `<card render:*>` records what it says and a digest of the code that draws it,
pooled the way the popup's is, across the card's modules, the package they move into and the
popup's renderer and palette. To make only those pictures and their manifest entries, which
needs neither Edge nor the window:

```
python build/make_screenshots.py --cards
```

Windows' own notification, which appears instead wherever a card must not, is not pictured. The
shell draws it in the machine's theme, so a capture cannot be pinned, and the one this
repository carried until v0.6.5 had fallen behind the product — no Open Dashboard button, the
old identifier line — before anything noticed. If you photograph one for an issue, never
photograph a real conversation: it shows the conversation's identifier, and a screenshot of a
real one publishes it permanently.

**Every surface is pictured from one set of records.** The window's sample records
(`seed_window_state`) are written once, at the moment the popup and the panel are drawn at, and read
back the way each surface reads them: the popup's rows and the panel's rows are the window's two
waiting recoveries, with the same names, states and times, and the panel's page is told that moment
and reads clock times in UTC, as the card does. The window itself is seeded again when it is
photographed, with the same offsets, because the bridge behind it runs on the real clock. So a
countdown, a chip and a count say the same on all four pictures, but a wall-clock time need not: the
times the window prints, such as History's, are those of the day the pictures were drawn. Compare
the four by their relative times only.

**To audit the look, draw both themes side by side.** The committed pictures are the light theme's
only. For a change to how the product looks, draw contact sheets of the window's Overview and
Pending pages, the top of the panel, the popup and the card, in the light and the dark theme, every
surface at the scale the window is captured at:

```
python build/make_screenshots.py --audit <folder>
python build/make_screenshots.py --audit <another folder> --before <folder>
```

The second form adds a before-and-after sheet per theme. It needs what a whole run needs - Windows,
Edge and the compiled window, run from PowerShell - and writes only into the folder it is given: it
refuses a folder in `docs/` or `assets/` and never touches the manifest. The window is captured from
a scratch installation, as for the published pictures, so your own installation is never touched.

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
  worst a malformed settings file can do is make recovery more conservative;
- the text of a Custom message is written only through the Dashboard's control layer, never
  through an MCP tool, and its placeholders stay a whitelist;
- no front end - the Dashboard, the notification-area popup, the panel in Codex - gains a way
  to put a continuation into Codex. The watcher is the only thing that sends.

If you are unsure whether a change crosses one of those lines, open an issue first and say
what you are trying to achieve — there is usually a way to get there that keeps the property.

## How the code is layered

The Python package is built in layers, and its imports point one way: down or sideways,
never up.

- **Domain** — the rules with no side effects, gathered in `domain/`: the stored states and
  the legal moves between them (`domain/states.py`), the gates a record passes before
  anything is sent (`domain/gates.py`), what a person is shown for a record
  (`domain/public.py`), every identifier (`domain/ids.py`) and every closed list of words
  (`domain/vocabulary.py`), beside how a failure is classified (`failures.py`) and which
  reasons are recoverable (`reasons.py`). `machine.py` is the front over the first three.
  The standard library only, and only the parts of it that touch no clock, file or process.
- **Policy and translation** — the settings schema, the continuation builder, the catalogs,
  paths and the product version, and the log.
- **Adapters** — everything that touches the outside: the store, Codex's files and processes,
  Windows (the registry, the Start menu shortcut, PowerShell, notifications), and the
  compatibility registry.
- **The engine** — decides and schedules. It reaches Codex and the store through what it is
  given rather than by importing them.
- **Control** — the one layer a front end calls.
- **Front ends** — the command line, the bridge the settings window talks to, the MCP server
  and its panel, the watcher's runtime, the notification-area icon, its popup and the card.

`tests/test_layers.py` places every module in one of these, and fails an import that points
up, a module with no layer, and an import cycle. Where the code does not match the map yet,
the test lists the real exceptions, and each one fails the test once it is gone, so those
lists only shrink. A rule about a module holds for everything inside it once it is a package,
and for the packages the split creates (`codex/`, `win/`, `ui/`, `mcp/`) before they exist, so
moving code under a new name does not take it out of a rule. The same file lists every import
made inside a function, with its reason; a new one needs a line there. `tests/test_sizes.py`
gives every module a budget of 700 lines, and holds each module already over it to exactly the
length it has now: a commit that shrinks one lowers its ceiling, so it cannot grow back.

`tests/test_stack.py` asks the other question: not which way a call points, but which binary
the code ends up inside. `docs/ROADMAP.md` names the eight parts the Rust core is planned to be
built from, and that file places every module on exactly one of them — or on one of the parts
the Windows interface keeps, or on the few that are neither. It then holds the placement four
ways, each of which only shrinks: items with no package of their own, packages whose modules
are not all one item, single modules doing two items' work, and the graph of which item calls
which. A module can sit in the right layer and still belong to two items, so a new one needs a
line there as well as in `test_layers.py`.

The window's C# is held the same way. `gui/window.sources` is the compile list and the only
place it is written, divided into `[settings]`, `[dashboard]`, `[controls]` and `[generated]`;
`tests/guiscan.py` reads it, and a rule about the window's code asks for a group rather than
naming a file, so a file added to a group joins every rule about it. `guiscan.type_body` and `guiscan.member_body`
find a type or a member by its braces and raise where it is not there — which is what a slice
that ended at "the next `private void`" did not.

A test that asserts something about the source itself — that only the watcher sends, that the
popup reaches nothing that can submit, that no module builds its own PowerShell command —
reads it through `tests/srcscan.py`: every tracked `.py` file under `src/`, at any depth, and
for each import also the package `__init__.py` files Python runs to reach its target. Do
not read one module by name, or glob one directory, to assert that something is absent: when
the code moves, a test like that keeps passing and stops checking. `tests/test_srcscan.py`
refuses both shapes, and fails when a `.py` file under `src/` is not tracked, because an
untracked module is invisible to every scan while the suite still runs it.

Some paths are contracts with programs outside the package and do not move:
`src/auto_resume.py` (it is in users' sign-in entries) and `src/codex_auto_resume/cli.py` (an
older launcher, already installed in a user's home, looks for both), and the module names
the settings window, the MCP launcher, the bootstrap and the release check call.
`tests/test_structural_invariants.py` pins them.

What the bridge and the MCP server answer is a contract too: the settings window and the
panel in Codex read those answers by field name, and nothing else connects them to the Python.
`tests/golden/` holds one file per bridge command and per MCP tool, made by
`tests/wiregolden.py` in a scratch installation with the clock, the paths and the machine
pinned. `tests/test_wire_goldens.py` makes them again on every run and compares them byte for
byte, and `tests/test_consumer_fields.py` fails when the window or the panel reads a field no
golden answer carries. Moving code leaves every one of them exactly as it was. A change that
means to alter an answer regenerates them with `python -X utf8 tests/wiregolden.py --write`,
and the diff is reviewed with the change.

Some rules are stated in one place on purpose: which wait a record goes back to, what a claim
costs its budgets, whether a record may be sitting in Codex's queue, how a command opens the
state, which settings are the user's own words, and a few more. `tests/test_single_rules.py`
pins what every caller gets from each of them, and fails when a second implementation of one
appears anywhere in the package. Call the one that exists - `machine.waiting_state`,
`machine.may_be_queued`, `openstate.open_state`, `settings.is_custom_text` and the rest the
test names - rather than writing the rule again. Every JSON writer passes `allow_nan=False`
and no `default`, which `tests/test_json_writers.py` checks: a value that is not JSON is a bug
to fix where the value is made, not text to write.

Reading an identifier is one of those rules. A conversation id, an interruption id, the marker
a continuation carries and a client id are read only through `domain/ids.py`, which also
computes an interruption's id; where two readers accept different spellings, the parser takes a
parameter rather than the reader keeping a pattern of its own. `tests/test_domain_vectors.py`
holds the exact bytes of those ids, the gate vector and `settings.json`, and what each reader
takes. The closed lists of words - states, codes, reasons, gates, categories, refusals,
choices - are one `StrEnum` each in `domain/vocabulary.py`. The module that used a list keeps
it under its old name, made from the enum (`machine.STATES = frozenset(RecordState)`), so a
word is added in one place; `tests/test_vocabulary.py` holds every list to its members and
every member to hashing, comparing and being written exactly as its string.

## Commit and pull requests

- One change per commit, with a message that says what changed and why.
- Run the full suite before pushing.
- If you fixed something a user could hit, add the regression test in the same commit.
- A commit that only moves code — lines moved verbatim into another file, nothing else
  changed — is listed in `.git-blame-ignore-revs` by a later commit, so that `git blame`
  credits each line to the change that last really touched it. Run this once in your clone:

  ```bash
  git config blame.ignoreRevsFile .git-blame-ignore-revs
  ```

## Reading the history

The full history is kept: every commit that landed is still there, with its own message, so
`git bisect` finds the commit that changed a behaviour and `git blame` names the change that
wrote a line.

To read it by release instead:

- from v0.6.5 on, each release arrives on `main` as one merge commit, so
  `git log --first-parent main` is one line per release;
- for every release, including the older ones, the changelog entry links the commits it
  contains, and `git log --oneline v0.6.3..v0.6.4` shows the same range in a clone;
- `git tag` lists the releases themselves.

Nothing about the history is rewritten to make it shorter: the published tags, the digests
pinned beside them and anybody's existing clone all point at these commits.
