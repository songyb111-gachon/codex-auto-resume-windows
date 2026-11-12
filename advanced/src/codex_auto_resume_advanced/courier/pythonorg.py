# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""python.org's list of releases and the Windows embeddable package of one of them (v0.6.23, python_choice).

What is offered of a line is its newest final release whose files include the Windows embeddable package (`offered`): a
line in its security-only phase publishes source alone (3.13.18, 2026-11: no python-3.13.18-embed-amd64.zip), so the newest
release of it may be one that can never be run here, and the release before it is offered instead.

The list is read live, so no version is pinned in a release of this product; only the lines it may offer are, in
control/pythons.py. Every address here is written out or built from constants, and www.python.org is the only host this
file ever asks: what the service answers can never name another. Each answer is bounded, redirects are refused as every
courier request refuses them (http.py), and an address or digest not of the one exact shape is refused, not followed.

Lives in the courier's package because only that package may reach the network (tests/test_privacy_claims.py,
ADVANCED_NETWORK_MODULES); it is asked only by control/pythons.py, after a person pressed a button on its card.

`opener` is the seam a test fills, as in http.py. No test reaches the network.
"""
from __future__ import annotations

import json
import re
import time

from . import http

RELEASES = "https://www.python.org/api/v2/downloads/release/?version=3&is_published=true"
FILES = "https://www.python.org/api/v2/downloads/release_file/?release=%d"
PACKAGE = "https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip"
RELEASE_ADDRESS = re.compile(re.escape(RELEASES.partition("?")[0]) + r"([0-9]{1,9})/", re.ASCII)
FILE_NAME = "Windows embeddable package (64-bit)"
NAME = re.compile(r"Python (3\.[1-9][0-9]\.(?:0|[1-9][0-9]{0,2}))", re.ASCII)
DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)
# The releases of one line asked for their files at most, newest first: twice the 19 that 3.13 had on 2026-11-11, which
# covers a line's whole security-only phase of source-only releases. Each costs one read, and only on Check.
RELEASES_MOST = 40
ANSWER_MOST = 2 * 1024 * 1024               # bytes of one answer of the API (2026-11-10: 148 KB for the whole list)
PACKAGE_MOST = 64 * 1024 * 1024             # bytes of one package (2026-11-10: 13.7 MB for 3.15.2)
LIST_TIMEOUT = 30                           # seconds, each read
DOWNLOAD_TIMEOUT = 60
# v0.6.23 final (R5 of the second round's limits audit): what each read above bounds is one wait on the socket, so a Check
# could take 1 + 3 x 40 reads of 30 s each - an hour with the card busy - and a download that sends a byte a minute never
# ended. Each now has one deadline over all of it, on the monotonic clock, past which it is refused as the step it is.
# A Check: four of the 30 s reads above, so one slow answer still has room, while a Check that works asks 1 list and a
# few packaged reads that take seconds. A download: ten minutes, which takes the 64 MiB bound at about 110 KB/s and
# today's 13.7 MB package at about 23 KB/s.
CHECK_SECONDS = 4 * LIST_TIMEOUT
DOWNLOAD_SECONDS = 10 * 60
# The step a refusal is of, as the card names it (control/pythons.STEPS).
LIST, SOURCE, DOWNLOAD = "list", "source", "download"


class Refused(Exception):
    """python.org could not be read, or answered something not to be followed; `step` says which."""

    def __init__(self, step):
        self.step = step
        super().__init__(step)


def _ends(seconds) -> float:
    return time.monotonic() + seconds


def _left(ends, most, step) -> float:
    """The seconds a read may wait on the socket: at most `most`, and never past `ends`, which refuses it as `step`."""
    left = ends - time.monotonic()
    if left <= 0:
        raise Refused(step)
    return min(most, left)


def _answer(url, opener, ends=None):
    """One answer of the API, read piece by piece so the deadline `ends` (a Check's own, or CHECK_SECONDS from now) is
    looked at as it arrives, at most ANSWER_MOST bytes."""
    ends = _ends(CHECK_SECONDS) if ends is None else ends
    pieces, size = [], 0

    def take(piece):
        nonlocal size
        size += len(piece)
        if size > ANSWER_MOST or time.monotonic() > ends:
            raise Refused(LIST)
        pieces.append(piece)
    try:
        http.stream(url, take, timeout=_left(ends, LIST_TIMEOUT, LIST), opener=opener)
        found = json.loads(b"".join(pieces).decode("utf-8"))
    except (http.Failed, OSError, ValueError, RecursionError):
        raise Refused(LIST) from None
    if not isinstance(found, list):
        raise Refused(LIST)
    return found


def _order(version) -> tuple:
    return tuple(int(part) for part in version.split("."))


def newest(lines, *, opener=None) -> dict:
    """{line: {"version", "release"}}: for each of `lines`, its newest final release python.org has published, and the
    number python.org lists its files under. A pre-release, or a name not exactly "Python 3.X.Y", is passed over."""
    return {line: found[0] for line, found in finals(lines, opener=opener).items()}


def finals(lines, *, opener=None, ends=None) -> dict:
    """{line: [{"version", "release"}, ...]}: every final release of each of `lines` python.org lists, newest first, as
    `newest` reads them; a line with none is left out."""
    found = {}
    for row in _answer(RELEASES, opener, ends):
        if not isinstance(row, dict) or row.get("pre_release") is not False or not isinstance(row.get("name"), str):
            continue
        named = NAME.fullmatch(row["name"])
        address = RELEASE_ADDRESS.fullmatch(row.get("resource_uri") or "") if isinstance(row.get("resource_uri"), str) else None
        if named is None or address is None:
            continue
        version = named.group(1)
        line = ".".join(version.split(".")[:2])
        if line in lines:
            found.setdefault(line, {}).setdefault(version, int(address.group(1)))
    return {line: [{"version": version, "release": versions[version]}
                   for version in sorted(versions, key=_order, reverse=True)]
            for line, versions in found.items()}


def packaged(release, *, opener=None, ends=None) -> bool:
    """Whether the files python.org lists under `release` include a Windows embeddable package (64-bit) at all. Only
    which release to offer is decided here: `embeddable` still holds the one that is used to every check of its own."""
    if type(release) is not int or release < 0:
        raise Refused(SOURCE)
    return any(isinstance(row, dict) and row.get("name") == FILE_NAME for row in _answer(FILES % release, opener, ends))


def offered(lines, *, opener=None) -> dict:
    """{line: {"version", "release"}}: for each of `lines`, its newest final release whose files include the Windows
    embeddable package, newest first, at most RELEASES_MOST asked of a line; a line with none is left out. Read on Check
    alone, as `newest` is; a read that fails is LIST, as the list's own, and so is the whole past CHECK_SECONDS."""
    ends = _ends(CHECK_SECONDS)
    chosen = {}
    for line, found in finals(lines, opener=opener, ends=ends).items():
        for each in found[:RELEASES_MOST]:
            if packaged(each["release"], opener=opener, ends=ends):
                chosen[line] = each
                break
    return chosen


def embeddable(release, version, *, opener=None) -> dict:
    """{"url", "sha256", "size"} of the 64-bit embeddable package of `version`, whose files python.org lists under
    `release`. Refused SOURCE unless there is exactly one such file, at exactly the address that version's package has."""
    if type(release) is not int or release < 0:
        raise Refused(SOURCE)
    rows = [row for row in _answer(FILES % release, opener) if isinstance(row, dict) and row.get("name") == FILE_NAME]
    if len(rows) != 1:
        raise Refused(SOURCE)
    row = rows[0]
    url, digest, size = row.get("url"), row.get("sha256_sum"), row.get("filesize")
    if url != PACKAGE % (version, version) or not isinstance(digest, str) or DIGEST.fullmatch(digest) is None:
        raise Refused(SOURCE)
    if type(size) is not int or not 0 < size <= PACKAGE_MOST:
        raise Refused(SOURCE)
    return {"url": url, "sha256": digest, "size": size}


def download(found, target, *, progress=None, opener=None) -> int:
    """The package `embeddable` found, written to the new file `target`; how many bytes. `progress(got, size)` after each
    piece, with the bytes truly written. Refused DOWNLOAD on any failure, past the size python.org gave, or past
    DOWNLOAD_SECONDS from its start."""
    size = found["size"]
    got = 0
    ends = _ends(DOWNLOAD_SECONDS)
    try:
        with open(target, "xb") as sink:
            def wrote(piece):
                nonlocal got
                got += len(piece)
                if got > size or time.monotonic() > ends:
                    raise Refused(DOWNLOAD)
                sink.write(piece)
                if progress is not None:
                    progress(got, size)
            http.stream(found["url"], wrote, timeout=_left(ends, DOWNLOAD_TIMEOUT, DOWNLOAD), opener=opener)
    except (http.Failed, OSError, ValueError):
        raise Refused(DOWNLOAD) from None
    if got != size:
        raise Refused(DOWNLOAD)
    return got
