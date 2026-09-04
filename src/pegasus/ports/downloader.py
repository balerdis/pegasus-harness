"""The port through which Pegasus fetches a released binary it did not ship.

A server's descriptor can pin a version and a checksum, but nothing above
this port may go and get the bytes those describe -- fetching is I/O, and the
whole reason this is a port rather than a call to some HTTP library directly
is so every decision built on top of it (which byte-for-byte match, what the
failure message says, what gets rolled back) is provable against a table of
canned answers instead of a real network.
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


class DownloaderError(Exception):
    """The bytes at a URL could not be fetched."""


@runtime_checkable
class Downloader(Protocol):
    """Everything Pegasus needs to bring a remote asset's bytes home."""

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> bytes:
        """Fetch the whole content at ``url``. Raises :class:`DownloaderError` if it cannot be fetched.

        ``timeout_seconds`` is optional so every caller written before it
        existed keeps its exact behaviour: ``None`` means "use whatever this
        implementation already considered its default" -- for
        :class:`~pegasus.infra.downloader_http.HttpDownloader` that is the
        30 seconds tuned for an MCP server archive. A caller with a tighter
        deadline, such as a background version check, passes an explicit
        value instead of inheriting that default.

        ``on_progress`` is optional for the same reason: every caller written
        before it existed -- both production call sites and every fake in the
        test suite -- keeps its exact current behaviour when it is omitted,
        which is why it defaults to ``None`` rather than becoming a required
        param the moment one caller wants it. When given, it is called zero
        or more times while the bytes arrive, each time with
        ``(bytes_downloaded_so_far, total_bytes_or_None)`` -- the total is
        ``None`` whenever the server never said how large the response is,
        never a guess an implementation invented to fill the gap. This exists
        for exactly one reason: an MCP server's `download` distribution can
        be several megabytes on a slow link, and a caller rendering that as a
        single opaque unit of work has no way to tell "slow" apart from
        "hung" until it finally returns.
        """
