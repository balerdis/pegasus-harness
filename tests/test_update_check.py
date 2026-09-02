"""`cli.check_for_update`: the one place Pegasus ever asks the network what
the newest published release is.

Every failure mode this module can hit -- disabled, no cache and no network,
a network error, a malformed response, a stale cache the network cannot
refresh -- must resolve to a plain value the caller can act on without ever
raising. Real HTTP is never reached: `no_network` (imported through `fakes`)
refuses any real socket outright, and every test here drives `cli.check_for_update`
through `FakeDownloader` and `FakeFileSystem` instead.
"""
from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

from fakes import FakeDownloader, FakeFileSystem
from pegasus import cli

AT = "2026-08-14T00:00:00+00:00"
LATER = "2026-08-14T12:00:00+00:00"  # 12h after AT: inside the cache's TTL.
MUCH_LATER = "2026-08-16T00:00:00+00:00"  # 2 days after AT: outside the cache's TTL.
HOME = Path("/home/person")


def _release_body(tag: str) -> bytes:
    return json.dumps({"tag_name": tag}).encode("utf-8")


class CheckForUpdateTestCase(unittest.TestCase):
    def runtime(self, *, now: str = AT, downloader=None, filesystem=None, variables=None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=filesystem if filesystem is not None else FakeFileSystem(),
            home=HOME,
            now=now,
            out=io.StringIO(),
            variables=dict(variables or {}),
            downloader=downloader if downloader is not None else FakeDownloader(),
        )


class TimeoutTest(CheckForUpdateTestCase):
    """The version check must never wait as long as an archive download --
    see `cli.UPDATE_CHECK_TIMEOUT_SECONDS` for why a few seconds is enough."""

    def test_the_version_check_asks_for_the_short_timeout(self):
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v5.11.0")})
        runtime = self.runtime(downloader=downloader)
        cli.check_for_update(runtime)
        self.assertEqual(downloader.timeouts, [cli.UPDATE_CHECK_TIMEOUT_SECONDS])

    def test_an_archive_download_still_gets_the_default_long_timeout(self):
        from pegasus.infra.downloader_http import TIMEOUT_SECONDS

        downloader = FakeDownloader({"https://example.test/archive": b"bytes"})
        downloader.fetch("https://example.test/archive")
        self.assertEqual(downloader.timeouts, [TIMEOUT_SECONDS])


class FreshLookupTest(CheckForUpdateTestCase):
    def test_a_successful_fetch_reports_the_tag_with_its_v_prefix_stripped(self):
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v5.11.0")})
        runtime = self.runtime(downloader=downloader)
        self.assertEqual(cli.check_for_update(runtime), "5.11.0")

    def test_a_tag_with_no_v_prefix_is_reported_unchanged(self):
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("5.11.0")})
        runtime = self.runtime(downloader=downloader)
        self.assertEqual(cli.check_for_update(runtime), "5.11.0")

    def test_a_successful_fetch_writes_the_cache(self):
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v5.11.0")})
        filesystem = FakeFileSystem()
        runtime = self.runtime(downloader=downloader, filesystem=filesystem)
        cli.check_for_update(runtime)
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        self.assertTrue(filesystem.exists(cache_path))
        cached = json.loads(filesystem.files[cache_path])
        self.assertEqual(cached["latest_version"], "5.11.0")
        self.assertEqual(cached["success_checked_at"], AT)


class SilentFailureTest(CheckForUpdateTestCase):
    """Every one of these must answer `None` -- never raise, never print."""

    def test_no_network_reachable_answers_none(self):
        from pegasus.ports.downloader import DownloaderError

        class _Unreachable:
            def fetch(self, url: str, *, timeout_seconds=None) -> bytes:
                raise DownloaderError("no route to host")

        runtime = self.runtime(downloader=_Unreachable())
        self.assertIsNone(cli.check_for_update(runtime))

    def test_a_malformed_json_body_answers_none(self):
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: b"not json at all"})
        runtime = self.runtime(downloader=downloader)
        self.assertIsNone(cli.check_for_update(runtime))

    def test_a_response_missing_tag_name_answers_none(self):
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: json.dumps({"nope": True}).encode()})
        runtime = self.runtime(downloader=downloader)
        self.assertIsNone(cli.check_for_update(runtime))

    def test_a_timeout_like_error_answers_none(self):
        class _TimesOut:
            def fetch(self, url: str, *, timeout_seconds=None) -> bytes:
                raise TimeoutError("timed out")

        runtime = self.runtime(downloader=_TimesOut())
        self.assertIsNone(cli.check_for_update(runtime))

    def test_an_unrelated_url_registered_leaves_this_one_unanswered(self):
        # A rate-limited or wrong response is exactly what an absent fake
        # entry already reproduces: `FakeDownloader` raises `DownloaderError`.
        downloader = FakeDownloader({"https://example.invalid/other": b"{}"})
        runtime = self.runtime(downloader=downloader)
        self.assertIsNone(cli.check_for_update(runtime))


class OffSwitchTest(CheckForUpdateTestCase):
    def test_the_environment_variable_disables_the_check_with_no_network_touched(self):
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v9.9.9")})
        runtime = self.runtime(downloader=downloader, variables={"PEGASUS_NO_UPDATE_CHECK": "1"})
        self.assertIsNone(cli.check_for_update(runtime))
        self.assertEqual(downloader.calls, [])

    def test_read_through_runtime_variables_not_the_real_environment(self):
        """The seam is `runtime.variables`, the same one every other engine
        function reads through -- never `os.environ` directly, so this stays
        provable without ever touching the real process environment."""
        import os

        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v9.9.9")})
        # Set in the real environment but NOT in `runtime.variables`: if the
        # implementation ever reached for `os.environ` this would wrongly
        # disable the check.
        os.environ["PEGASUS_NO_UPDATE_CHECK"] = "1"
        self.addCleanup(lambda: os.environ.pop("PEGASUS_NO_UPDATE_CHECK", None))
        runtime = self.runtime(downloader=downloader, variables={})
        self.assertEqual(cli.check_for_update(runtime), "9.9.9")


class CacheTest(CheckForUpdateTestCase):
    def test_a_fresh_cache_is_reused_without_touching_the_network(self):
        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(cache_path, json.dumps({"success_checked_at": AT, "latest_version": "5.9.0"}).encode())
        downloader = FakeDownloader()  # empty: any fetch attempt fails the test.
        runtime = self.runtime(now=LATER, downloader=downloader, filesystem=filesystem)
        self.assertEqual(cli.check_for_update(runtime), "5.9.0")
        self.assertEqual(downloader.calls, [])

    def test_a_stale_cache_triggers_a_fresh_lookup(self):
        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(cache_path, json.dumps({"success_checked_at": AT, "latest_version": "5.9.0"}).encode())
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v5.12.0")})
        runtime = self.runtime(now=MUCH_LATER, downloader=downloader, filesystem=filesystem)
        self.assertEqual(cli.check_for_update(runtime), "5.12.0")
        self.assertEqual(len(downloader.calls), 1)

    def test_a_stale_cache_still_answers_as_a_fallback_when_the_network_fails(self):
        from pegasus.ports.downloader import DownloaderError

        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(cache_path, json.dumps({"success_checked_at": AT, "latest_version": "5.9.0"}).encode())

        class _Unreachable:
            def fetch(self, url: str, *, timeout_seconds=None) -> bytes:
                raise DownloaderError("offline")

        runtime = self.runtime(now=MUCH_LATER, downloader=_Unreachable(), filesystem=filesystem)
        self.assertEqual(cli.check_for_update(runtime), "5.9.0")

    def test_a_malformed_cache_is_treated_as_no_cache_at_all(self):
        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(cache_path, b"not json")
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v5.12.0")})
        runtime = self.runtime(downloader=downloader, filesystem=filesystem)
        self.assertEqual(cli.check_for_update(runtime), "5.12.0")


class FailureCacheTest(CheckForUpdateTestCase):
    """A failed lookup is remembered too, with its own short TTL -- see
    `cli.UPDATE_CHECK_FAILURE_TTL_SECONDS` -- so an offline machine stops
    paying the network timeout on every single launch."""

    def test_a_failed_lookup_writes_a_negative_cache_entry(self):
        from pegasus.ports.downloader import DownloaderError

        class _Unreachable:
            def fetch(self, url: str, *, timeout_seconds=None) -> bytes:
                raise DownloaderError("offline")

        filesystem = FakeFileSystem()
        runtime = self.runtime(downloader=_Unreachable(), filesystem=filesystem)
        self.assertIsNone(cli.check_for_update(runtime))
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        self.assertTrue(filesystem.exists(cache_path))
        cached = json.loads(filesystem.files[cache_path])
        self.assertEqual(cached["failure_checked_at"], AT)

    def test_a_fresh_negative_entry_skips_the_network_entirely(self):
        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(
            cache_path, json.dumps({"failure_checked_at": AT, "latest_version": None}).encode()
        )
        downloader = FakeDownloader()  # empty: any fetch attempt fails the test.
        soon_after = "2026-08-14T00:30:00+00:00"  # 30m after AT: inside the failure TTL (1h).
        runtime = self.runtime(now=soon_after, downloader=downloader, filesystem=filesystem)
        self.assertIsNone(cli.check_for_update(runtime))
        self.assertEqual(downloader.calls, [])

    def test_a_fresh_negative_entry_alongside_an_older_success_still_yields_the_older_version(self):
        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(
            cache_path,
            json.dumps(
                {
                    "success_checked_at": AT,
                    "failure_checked_at": LATER,
                    "latest_version": "5.9.0",
                }
            ).encode(),
        )
        downloader = FakeDownloader()  # empty: any fetch attempt fails the test.
        just_after_later = "2026-08-14T12:05:00+00:00"
        runtime = self.runtime(now=just_after_later, downloader=downloader, filesystem=filesystem)
        self.assertEqual(cli.check_for_update(runtime), "5.9.0")
        self.assertEqual(downloader.calls, [])

    def test_an_expired_negative_entry_triggers_a_fresh_lookup(self):
        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(
            cache_path, json.dumps({"failure_checked_at": AT, "latest_version": None}).encode()
        )
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v5.12.0")})
        runtime = self.runtime(now=MUCH_LATER, downloader=downloader, filesystem=filesystem)
        self.assertEqual(cli.check_for_update(runtime), "5.12.0")
        self.assertEqual(len(downloader.calls), 1)

    def test_a_failure_after_a_stale_success_preserves_the_older_version(self):
        from pegasus.ports.downloader import DownloaderError

        class _Unreachable:
            def fetch(self, url: str, *, timeout_seconds=None) -> bytes:
                raise DownloaderError("offline")

        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(
            cache_path, json.dumps({"success_checked_at": AT, "latest_version": "5.9.0"}).encode()
        )
        runtime = self.runtime(now=MUCH_LATER, downloader=_Unreachable(), filesystem=filesystem)
        self.assertEqual(cli.check_for_update(runtime), "5.9.0")
        cached = json.loads(filesystem.files[cache_path])
        self.assertEqual(cached["latest_version"], "5.9.0")
        self.assertEqual(cached["failure_checked_at"], MUCH_LATER)

    def test_a_corrupt_cache_behaves_as_no_cache_for_the_negative_path_too(self):
        from pegasus.ports.downloader import DownloaderError

        class _Unreachable:
            def fetch(self, url: str, *, timeout_seconds=None) -> bytes:
                raise DownloaderError("offline")

        filesystem = FakeFileSystem()
        cache_path = filesystem.data_dir(HOME) / "update-check.json"
        filesystem.write_atomic(cache_path, b"not json")
        runtime = self.runtime(downloader=_Unreachable(), filesystem=filesystem)
        self.assertIsNone(cli.check_for_update(runtime))


class OffSwitchReadsNothingTest(CheckForUpdateTestCase):
    def test_the_off_switch_never_reads_the_cache_either(self):
        downloader = FakeDownloader({cli.UPDATE_CHECK_URL: _release_body("v9.9.9")})
        cache_path = FakeFileSystem().data_dir(HOME) / "update-check.json"
        filesystem = FakeFileSystem(fail_exists={cache_path})
        runtime = self.runtime(downloader=downloader, filesystem=filesystem, variables={"PEGASUS_NO_UPDATE_CHECK": "1"})
        self.assertIsNone(cli.check_for_update(runtime))
        self.assertEqual(downloader.calls, [])


if __name__ == "__main__":
    unittest.main()
