# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The pictures of a queued prompt (v0.6.20, #50 item 1): the product's own copies, kept until the message is delivered.

A person adds pictures to a scheduled message in the Dashboard's editor - pasted, chosen or dropped. The bridge checks
each by its bytes (PNG, JPEG, GIF, WebP - never by its name), at most MOST_BYTES each and MOST_IMAGES to a message,
and copies it into the advanced state folder (config.Paths.advanced_dir) - directly in it, as every file of that folder
is, so core's purge takes the copies with the rest (config.owned_advanced_files follows nothing below it):

    image-<prompt id>-<place>-<count>-<32 hex>.<ext>
                                               a copy of a prompt still to go: its prompt's id (AUTOINCREMENT, never
                                               reused), its place among the message's pictures and how many it has -
                                               so a copy gone is seen - an opaque id of its own, and the extension its
                                               bytes say
    image-new-<32 hex>.<ext>                   a copy made while a save is in progress, before its prompt has an id

The person's own path and file name are never kept, logged or answered back. The state file is not changed: the copies
are the prompt's by the id in their names (plans/v0620-images-design.md says why no version step).

A copy lives only while its prompt is still to go (waiting, ready or held): `sweep` removes every copy whose prompt is
not - delivered, ended any other way, cancelled, deleted or never there - and every save's copy older than an hour. The
watcher sweeps at each P2 (engine/promptqueue.py), the bridge after each add, edit, cancel and Delete completed.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import time

from codex_auto_resume import config

# How many pictures a message holds, and how large one may be.
MOST_IMAGES = 4
MOST_BYTES = 5 * 1024 * 1024
# A save's copy left this long is one a save cut short left behind.
STAGED_FOR = 3600
PREFIX = "image-"
NAME = re.compile(r"image-(?P<prompt>[1-9][0-9]{0,17}|new)-(?:(?P<place>[0-9]{1,2})-(?P<count>[0-9]{1,2})-)?"
                  r"(?P<id>[0-9a-f]{32})\.(?P<ext>png|jpg|gif|webp)")
ID = re.compile(r"[0-9a-f]{32}")


class ImageRefused(Exception):
    """A picture refused, with the refusal's word (vocabulary.Refusal): image_refused, image_too_large or images_full."""

    def __init__(self, refusal):
        super().__init__(str(refusal))
        self.refusal = refusal


def kind(data) -> str | None:
    """The extension the bytes `data` say - png, jpg, gif or webp - or None for anything else."""
    if not isinstance(data, (bytes, bytearray)):
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def read(source) -> tuple:
    """The bytes of the file at `source` and the extension they say - (data, ext) - or ImageRefused: image_refused for a
    path that is not a plain readable file of a picture this product sends (a link, a folder, empty, other bytes),
    image_too_large for one over MOST_BYTES."""
    if not isinstance(source, str) or not source or "\0" in source or len(source) > 32767:
        raise ImageRefused("image_refused")
    path = Path(source)
    try:
        if not path.is_absolute() or config.is_link(path) or not path.is_file():
            raise ImageRefused("image_refused")
        with open(path, "rb") as handle:
            data = handle.read(MOST_BYTES + 1)
    except ImageRefused:
        raise
    except (OSError, ValueError):
        raise ImageRefused("image_refused") from None
    if len(data) > MOST_BYTES:
        raise ImageRefused("image_too_large")
    ext = kind(data)
    if ext is None:
        raise ImageRefused("image_refused")
    return data, ext


def _folder(paths) -> Path:
    return Path(paths.advanced_dir)


def _entries(paths):
    """Every copy in the folder, as (path, match) - nothing else of it."""
    folder = _folder(paths)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = []
    for name in names:
        match = NAME.fullmatch(name) if name.startswith(PREFIX) else None
        if match is not None:
            found.append((folder / name, match))
    return found


def stage(paths, data, ext) -> str:
    """`data`, a picture's bytes, written as a save's copy; its opaque id. The folder must already be the state's (made
    by its first write, with its owner's marker); OSError where it cannot be written."""
    folder = _folder(paths)
    if config.is_link(folder) or not folder.is_dir():
        raise OSError("the advanced state folder is not there")
    image = secrets.token_hex(16)
    target = folder / ("%snew-%s.%s" % (PREFIX, image, ext))
    with open(target, "xb") as handle:
        handle.write(data)
    return image


def _own(paths, prompt_id) -> list:
    """Prompt `prompt_id`'s copies as found: (place, count, id, path), in their places."""
    found = []
    for path, match in _entries(paths):
        if match["prompt"] == str(prompt_id) and match["place"] is not None:
            found.append((int(match["place"]), int(match["count"]), match["id"], path))
    return sorted(found)


def of(paths, prompt_id) -> list:
    """The copies of prompt `prompt_id`, in their places: [{"id": opaque id, "path": the copy's path}]."""
    return [{"id": image, "path": str(path)} for _place, _count, image, path in _own(paths, prompt_id)]


def count(paths, prompt_id) -> int:
    return len(of(paths, prompt_id))


def place(paths, prompt_id, images) -> None:
    """Prompt `prompt_id`'s pictures made exactly `images` - opaque ids, in order, each a save's copy or one of this
    prompt's own - and every other copy of it removed. OSError where a copy cannot be moved; ImageRefused
    (image_refused) for an id that is neither."""
    entries = _entries(paths)
    by_id = {}
    for path, match in entries:
        if match["prompt"] in ("new", str(prompt_id)):
            by_id[match["id"]] = (path, match)
    if len(images) > MOST_IMAGES:
        raise ImageRefused("images_full")
    if len(set(images)) != len(images) or any(image not in by_id for image in images):
        raise ImageRefused("image_refused")
    folder = _folder(paths)
    for index, image in enumerate(images, 1):
        path, match = by_id[image]
        target = folder / ("%s%d-%d-%d-%s.%s" % (PREFIX, prompt_id, index, len(images), image, match["ext"]))
        if path != target:
            os.replace(path, target)
    kept = set(images)
    for path, match in entries:
        if match["prompt"] == str(prompt_id) and match["id"] not in kept:
            _remove(path)


def drop(paths, images) -> None:
    """Save's copies `images` (opaque ids) removed: a save that was refused."""
    wanted = set(images)
    for path, match in _entries(paths):
        if match["prompt"] == "new" and match["id"] in wanted:
            _remove(path)


def problem(paths, prompt_id) -> bool:
    """Whether prompt `prompt_id`'s copies cannot be sent as they are: one gone (their places are not 1 to the count each
    names), unreadable, or no longer a picture of an allowed kind or size. False for a prompt with none."""
    found = _own(paths, prompt_id)
    if [(place, count) for place, count, _image, _path in found] != [(n, len(found)) for n in range(1, len(found) + 1)]:
        return True
    for _place, _count, _image, path in found:
        try:
            read(str(path))
        except ImageRefused:
            return True
    return False


def sweep(paths, pending) -> int:
    """Every copy whose prompt is not one of `pending` (the ids still to go) removed, and every save's copy older than
    STAGED_FOR by the files' own clock (the wall clock, whatever the runtime's says); how many."""
    pending = {str(prompt) for prompt in pending}
    now = time.time()
    removed = 0
    for path, match in _entries(paths):
        if match["prompt"] == "new":
            try:
                old = now - path.stat().st_mtime >= STAGED_FOR
            except OSError:
                continue
            if not old:
                continue
        elif match["prompt"] in pending:
            continue
        removed += _remove(path)
    return removed


def _remove(path) -> int:
    try:
        if config.is_link(path):
            return 0
        path.unlink()
        return 1
    except OSError:
        return 0
