"""The port through which Pegasus fetches a released binary it did not ship.

A server's descriptor can pin a version and a checksum, but nothing above
this port may go and get the bytes those describe -- fetching is I/O, and the
whole reason this is a port rather than a call to some HTTP library directly
is so every decision built on top of it (which byte-for-byte match, what the
failure message says, what gets rolled back) is provable against a table of
canned answers instead of a real network.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class DownloaderError(Exception):
    """The bytes at a URL could not be fetched."""


@runtime_checkable
class Downloader(Protocol):
    """Everything Pegasus needs to bring a remote asset's bytes home."""

    def fetch(self, url: str) -> bytes:
        """Fetch the whole content at ``url``. Raises :class:`DownloaderError` if it cannot be fetched."""
