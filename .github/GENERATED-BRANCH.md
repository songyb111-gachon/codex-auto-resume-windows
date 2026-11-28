# This branch is generated

`ko` is built from `main` by `scripts/ko_sync.py` every time main's tests pass, and it is
force-updated. Nothing here is edited directly: an edit made on this branch is lost at the
next sync, without a conflict and without a warning.

* The code, the installer, the workflows and the tests are main's, at the commit named in
  the sync commit message.
* The documents are the Korean sources of the `dev` commit that main was promoted from -
  `README.ko.md` becomes `README.md`, and so on. `scripts/ko_branch.json` is the mapping, and
  its `intentionally_english` list says which pages stay English here, and why.

To change something on this branch, change it on `dev`: the English source for code, or the
`.ko.md` file beside it for Korean prose. main is English only, and ko follows main.
