# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""python.org's list of releases and the Windows embeddable package of one of them (v0.6.23, python_choice).

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

from . import http

RELEASES = "https://www.python.org/api/v2/downloads/release/?version=3&is_published=true"
FILES = "https://www.python.org/api/v2/downloads/release_file/?release=%d"
PACKAGE = "https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip"
RELEASE_ADDRESS = re.compile(r"https://www\.python\.org/api/v2/downloads/release/([0-9]{1,9})/", re.ASCII)
FILE_NAME = "Windows embeddable package (64-bit)"
NAME = re.compile(r"Python (3\.[1-9][0-9]\.(?:0|[1-9][0-9]{0,2}))", re.ASCII)
DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)
ANSWER_MOST = 2 * 1024 * 1024               # bytes of one answer of the API (2026-11-10: 148 KB for the whole list)
PACKAGE_MOST = 64 * 1024 * 1024             # bytes of one package (2026-11-10: 13.7 MB for 3.15.2)
LIST_TIMEOUT = 30                           # seconds, each read
DOWNLOAD_TIMEOUT = 60
# The step a refusal is of, as the card names it (control/pythons.STEPS).
LIST, SOURCE, DOWNLOAD = "list", "source", "download"


class Refused(Exception):
    """python.org could not be read, or answered something not to be followed; `step` says which."""

    def __init__(self, step):
        self.step = step
        super().__init__(step)


def _answer(url, opener):
    try:
        raw = http.get(url, timeout=LIST_TIMEOUT, opener=opener, most=ANSWER_MOST)
        found = json.loads(raw.decode("utf-8"))
    except (http.Failed, ValueError, RecursionError):
        raise Refused(LIST) from None
    if not isinstance(found, list):
        raise Refused(LIST)
    return found


def _order(version) -> tuple:
    return tuple(int(part) for part in version.split("."))


def newest(lines, *, opener=None) -> dict:
    """{line: {"version", "release"}}: for each of `lines`, its newest final release python.org has published, and the
    number python.org lists its files under. A pre-release, or a name not exactly "Python 3.X.Y", is passed over."""
    best = {}
    for row in _answer(RELEASES, opener):
        if not isinstance(row, dict) or row.get("pre_release") is not False or not isinstance(row.get("name"), str):
            continue
        named = NAME.fullmatch(row["name"])
        address = RELEASE_ADDRESS.fullmatch(row.get("resource_uri") or "") if isinstance(row.get("resource_uri"), str) else None
        if named is None or address is None:
            continue
        version = named.group(1)
        line = ".".join(version.split(".")[:2])
        if line in lines and (line not in best or _order(version) > _order(best[line]["version"])):
            best[line] = {"version": version, "release": int(address.group(1))}
    return best


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
    piece, with the bytes truly written. Refused DOWNLOAD on any failure or past the size python.org gave."""
    size = found["size"]
    got = 0
    try:
        with open(target, "xb") as sink:
            def wrote(piece):
                nonlocal got
                got += len(piece)
                if got > size:
                    raise Refused(DOWNLOAD)
                sink.write(piece)
                if progress is not None:
                    progress(got, size)
            http.stream(found["url"], wrote, timeout=DOWNLOAD_TIMEOUT, opener=opener)
    except (http.Failed, OSError, ValueError):
        raise Refused(DOWNLOAD) from None
    if got != size:
        raise Refused(DOWNLOAD)
    return got
