"""`HttpDownloader`: chunked reading and progress reporting.

`downloader_http`'s own module docstring explains why nothing here ever opens
a real socket -- the suite refuses one structurally (`no_network`, imported
through `fakes`), and this module is what would fail loudly if that refusal
ever slipped. So the boundary under test here is `urllib.request.urlopen`
itself, patched to a fake response object that behaves like a real HTTP
response closely enough to prove the chunking and the callback -- no socket,
loopback or otherwise, is ever asked to open. Checksum verification and
placement, the parts of a `download` server's materialization that do not
care how the bytes arrived, stay proven against `FakeDownloader` in
`test_dependencies.py` and `test_cli_downloads.py`, exactly as before.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fakes import FakeDownloader  # noqa: F401 -- imports `no_network` for the whole process

from pegasus.infra.downloader_http import HttpDownloader
from pegasus.ports.downloader import DownloaderError

URL = "https://example.test/releases/probe-linux-x64"


class _FakeHttpResponse:
    """Just enough of `http.client.HTTPResponse` for `HttpDownloader.fetch`
    to read from: a context manager, `.read(size)` handed out in the chunks
    the test pre-cut, and a `.headers` mapping `Content-Length` the way a
    real response's headers do.
    """

    def __init__(self, chunks: list[bytes], *, content_length: int | None):
        self._chunks = list(chunks)
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def _urlopen(response: _FakeHttpResponse):
    return patch("pegasus.infra.downloader_http.urllib.request.urlopen", return_value=response)


class FetchWithoutACallbackTest(unittest.TestCase):
    """Every caller written before `on_progress` existed must keep working
    unchanged when it omits the param entirely."""

    def test_the_full_body_is_still_returned_in_one_piece(self):
        response = _FakeHttpResponse([b"first-chunk-", b"second-chunk"], content_length=24)
        with _urlopen(response):
            downloader = HttpDownloader()
            self.assertEqual(downloader.fetch(URL), b"first-chunk-second-chunk")

    def test_a_fetch_failure_still_raises_downloader_error(self):
        with patch("pegasus.infra.downloader_http.urllib.request.urlopen", side_effect=OSError("boom")):
            downloader = HttpDownloader()
            with self.assertRaises(DownloaderError):
                downloader.fetch(URL)


class FetchWithACallbackTest(unittest.TestCase):
    def test_bytes_downloaded_increase_across_calls_and_the_total_is_correct(self):
        response = _FakeHttpResponse([b"a" * 10, b"b" * 5, b"c" * 1], content_length=16)
        observed: list[tuple[int, int | None]] = []
        with _urlopen(response):
            downloader = HttpDownloader()
            body = downloader.fetch(URL, on_progress=lambda done, total: observed.append((done, total)))
        self.assertEqual(body, b"a" * 10 + b"b" * 5 + b"c" * 1)
        self.assertEqual(observed, [(10, 16), (15, 16), (16, 16)])

    def test_a_response_with_no_content_length_reports_the_total_as_none(self):
        response = _FakeHttpResponse([b"only-chunk"], content_length=None)
        observed: list[tuple[int, int | None]] = []
        with _urlopen(response):
            downloader = HttpDownloader()
            downloader.fetch(URL, on_progress=lambda done, total: observed.append((done, total)))
        self.assertEqual(observed, [(len(b"only-chunk"), None)])

    def test_a_failed_fetch_never_calls_the_callback(self):
        observed: list[tuple[int, int | None]] = []
        with patch("pegasus.infra.downloader_http.urllib.request.urlopen", side_effect=OSError("boom")):
            downloader = HttpDownloader()
            with self.assertRaises(DownloaderError):
                downloader.fetch(URL, on_progress=lambda done, total: observed.append((done, total)))
        self.assertEqual(observed, [])


if __name__ == "__main__":
    unittest.main()
