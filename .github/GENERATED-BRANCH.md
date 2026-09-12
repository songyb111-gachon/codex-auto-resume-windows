# This branch is generated

`ko` is built from `main` by `scripts/ko_sync.py` every time main's tests pass, and it is
force-updated. Nothing here is edited directly: an edit made on this branch is lost at the
next sync, without a conflict and without a warning.

* The code, the installer, the workflows and the tests are main's, at the commit named in
  the sync commit message.
* The documents are main's Korean ones - `README.ko.md` becomes `README.md`, and so on.
  `scripts/ko_branch.json` on main is the mapping, and its `not_yet_translated` list says
  which pages are still English here.

To change something on this branch, change it on `main`: the English source for code, or
the `.ko.md` file for Korean prose.
