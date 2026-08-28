"""The real downloader: plain HTTP(S), for a released binary Pegasus does not ship.

Nothing in this suite exercises this module. Every test that needs a
:class:`~pegasus.ports.downloader.Downloader` reaches for the fake in
``tests/fakes.py`` instead, and the suite additionally refuses any real
socket connection outright (see ``tests/__init__.py``) -- so even a test that
somehow reached this class would fail loudly rather than reach the internet.
Proving *this* class correct against a real server is outside what a
hermetic suite can promise, and is not attempted here; only the port's
contract, exercised through the fake, is.
"""
from __future__ import annotations

import urllib.request

from pegasus.ports.downloader import DownloaderError

TIMEOUT_SECONDS = 30


class HttpDownloader:
    """Fetches a URL's whole body over HTTP(S)."""

    def fetch(self, url: str) -> bytes:
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                return response.read()
        except (OSError, ValueError) as error:
            raise DownloaderError(f"cannot fetch {url}: {error}") from error
