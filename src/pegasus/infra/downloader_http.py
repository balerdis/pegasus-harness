"""The real downloader: plain HTTP(S), for a released binary Pegasus does not ship.

The suite refuses any real socket connection outright (see ``tests/no_network.py``,
imported through ``tests/fakes.py``) -- so proving *this* class correct
against a real server is outside what a hermetic suite can promise, and is
not attempted here. Every test that needs a
:class:`~pegasus.ports.downloader.Downloader` for the rest of the pipeline
(checksum verification, placement) reaches for the fake in ``tests/fakes.py``
instead; only ``tests/test_downloader_http.py`` reaches into this module
itself, and even that stays inside the refusal by patching
`urllib.request.urlopen` to a fake response object rather than opening a
socket at all -- it proves the chunked reading and the progress callback,
never a live fetch.
"""
from __future__ import annotations

import urllib.request
from typing import Callable

from pegasus.ports.downloader import DownloaderError

TIMEOUT_SECONDS = 30

#: How much of the body to read per `response.read()` call. A single call
#: covering the whole body -- the previous behaviour -- reports nothing to
#: `on_progress` until it is already finished, which is exactly the bug this
#: module exists to fix. The other extreme, reading a handful of bytes at a
#: time, would call `on_progress` thousands of times a second for a multi-
#: megabyte archive, burning cycles a render loop never asked for. 64KB sits
#: between those: small enough that even a slow link updates a few times a
#: second (the engram archive this exists for is ~6.9MB, so ~110 calls total),
#: large enough that a fast one never turns the callback into the bottleneck.
_CHUNK_SIZE = 65536


class HttpDownloader:
    """Fetches a URL's whole body over HTTP(S), in chunks so a caller can
    watch the bytes arrive instead of blocking on one opaque `.read()`."""

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> bytes:
        timeout = TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
                total = _content_length(response)
                downloaded = 0
                chunks: list[bytes] = []
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if on_progress is not None:
                        on_progress(downloaded, total)
                return b"".join(chunks)
        except (OSError, ValueError) as error:
            raise DownloaderError(f"cannot fetch {url}: {error}") from error


def _content_length(response) -> int | None:
    """The response's declared size, or `None` when it did not declare one --
    never a guessed number in its place. A malformed header (present but not
    an integer) is treated the same as an absent one: an untrustworthy total
    is no better than no total at all.
    """
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
