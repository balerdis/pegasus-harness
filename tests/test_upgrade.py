"""Fetching, verifying, and placing a newly published `pegasus` binary.

Mirrors `pegasus.core.dependencies`'s own discipline: fetch, verify a digest,
only then write -- and never at the final destination until the verified
bytes already sit next to it.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from fakes import EXECUTABLE_MODE, FakeDownloader, FakeFileSystem

from pegasus.core import ownership, upgrade
from pegasus.ports.downloader import DownloaderError

DESTINATION = Path("/home/probe/.local/bin/pegasus")
VERSION = "5.11.0"


def sha256sum_line(content: bytes, filename: str = "pegasus") -> bytes:
    """The exact shape a real `pegasus.sha256` asset carries: a `sha256sum`-style line."""
    digest = ownership.digest_of_bytes(content).removeprefix(ownership.PREFIX)
    return f"{digest}  {filename}\n".encode("utf-8")


class UrlsTest(unittest.TestCase):
    def test_binary_url_names_the_tag_and_asset(self):
        self.assertEqual(
            upgrade.binary_url(VERSION),
            f"https://github.com/balerdis/pegasus-harness/releases/download/v{VERSION}/pegasus",
        )

    def test_checksum_url_names_the_tag_and_asset(self):
        self.assertEqual(
            upgrade.checksum_url(VERSION),
            f"https://github.com/balerdis/pegasus-harness/releases/download/v{VERSION}/pegasus.sha256",
        )


class FetchAndVerifyTest(unittest.TestCase):
    def test_a_matching_checksum_returns_the_fetched_bytes(self):
        content = b"the new pegasus binary"
        downloader = FakeDownloader(
            {
                upgrade.checksum_url(VERSION): sha256sum_line(content),
                upgrade.binary_url(VERSION): content,
            }
        )
        self.assertEqual(upgrade.fetch_and_verify(downloader, VERSION), content)

    def test_a_mismatched_checksum_raises_and_names_expected_and_actual(self):
        content = b"the new pegasus binary"
        wrong = sha256sum_line(b"something else entirely")
        downloader = FakeDownloader(
            {
                upgrade.checksum_url(VERSION): wrong,
                upgrade.binary_url(VERSION): content,
            }
        )
        with self.assertRaises(upgrade.UpgradeError) as caught:
            upgrade.fetch_and_verify(downloader, VERSION)
        message = str(caught.exception)
        expected_digest = wrong.split()[0].decode("ascii")
        actual_digest = ownership.digest_of_bytes(content).removeprefix(ownership.PREFIX)
        self.assertIn(expected_digest, message)
        self.assertIn(actual_digest, message)

    def test_a_checksum_fetch_failure_raises_before_ever_fetching_the_binary(self):
        downloader = FakeDownloader({upgrade.binary_url(VERSION): b"never reached"})
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.fetch_and_verify(downloader, VERSION)
        self.assertNotIn(upgrade.binary_url(VERSION), downloader.calls)

    def test_a_binary_fetch_failure_raises(self):
        downloader = FakeDownloader({upgrade.checksum_url(VERSION): sha256sum_line(b"whatever")})
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.fetch_and_verify(downloader, VERSION)

    def test_a_non_utf8_checksum_body_raises_a_clean_upgrade_error(self):
        """A malformed checksum asset must refuse cleanly, exactly like an
        empty or tokenless one -- never propagate `UnicodeDecodeError` as an
        unhandled traceback. Nothing is written at this point either way:
        the checksum is fetched before the binary, so a decode failure here
        never reaches `replace_binary` at all."""
        downloader = FakeDownloader({upgrade.checksum_url(VERSION): b"\xff\xfe not valid utf-8"})
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.fetch_and_verify(downloader, VERSION)
        self.assertNotIn(upgrade.binary_url(VERSION), downloader.calls)


class ReplaceBinaryTest(unittest.TestCase):
    def test_a_destination_with_no_existing_file_gets_the_executable_mode(self):
        """There is nothing to preserve when the destination does not exist
        yet, so this falls back to the platform's own executable mode --
        exactly what it did before mode preservation existed."""
        filesystem = FakeFileSystem()
        upgrade.replace_binary(filesystem, DESTINATION, b"new bytes")
        self.assertEqual(filesystem.files[DESTINATION], b"new bytes")
        self.assertEqual(filesystem.modes[DESTINATION], filesystem.mode_for(executable=True))

    def test_an_already_executable_destination_keeps_its_own_executable_mode(self):
        filesystem = FakeFileSystem(files={DESTINATION: b"old bytes"}, modes={DESTINATION: EXECUTABLE_MODE})
        upgrade.replace_binary(filesystem, DESTINATION, b"new bytes")
        self.assertEqual(filesystem.files[DESTINATION], b"new bytes")
        self.assertEqual(filesystem.modes[DESTINATION], EXECUTABLE_MODE)

    def test_a_restrictive_existing_mode_survives_the_upgrade(self):
        """An admin who narrowed a binary's mode -- to `0o750`, say, to
        restrict execution to one group -- must get exactly that back.
        `os.replace` swaps the inode outright, so nothing about the old
        file's mode survives on its own; this is what makes an upgrade
        non-destructive to a choice somebody already made."""
        filesystem = FakeFileSystem(files={DESTINATION: b"old bytes"}, modes={DESTINATION: 0o750})
        upgrade.replace_binary(filesystem, DESTINATION, b"new bytes")
        self.assertEqual(filesystem.modes[DESTINATION], 0o750)

    def test_a_preserved_mode_with_no_execute_bit_gains_only_the_owners_own(self):
        """A carried-through mode with no execute bit at all would leave an
        unrunnable `pegasus` after every upgrade -- worse than the widening
        this whole preservation exists to avoid. The fix adds back only the
        owner's own execute bit, enough to run, and leaves every other bit
        -- including any narrowed group/other permission -- exactly as it
        was, rather than reverting to the full `0o755` default."""
        filesystem = FakeFileSystem(files={DESTINATION: b"old bytes"}, modes={DESTINATION: 0o640})
        upgrade.replace_binary(filesystem, DESTINATION, b"new bytes")
        self.assertEqual(filesystem.modes[DESTINATION], 0o740)

    def test_the_temporary_write_lands_through_write_atomic_in_the_same_directory(self):
        """`write_atomic` is the one place a temp file is ever created, and it
        already writes it in `path.parent` before the final rename -- this
        pins that `replace_binary` hands it the real destination rather than
        some other path, so that guarantee actually applies here too."""
        filesystem = FakeFileSystem(files={DESTINATION: b"old bytes"})
        upgrade.replace_binary(filesystem, DESTINATION, b"new bytes")
        self.assertEqual(filesystem.writes, [DESTINATION])
        self.assertEqual(DESTINATION.parent, Path("/home/probe/.local/bin"))

    def test_a_write_failure_raises_and_leaves_the_original_untouched(self):
        filesystem = FakeFileSystem(files={DESTINATION: b"old bytes"}, fail_always={DESTINATION})
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.replace_binary(filesystem, DESTINATION, b"new bytes")
        self.assertEqual(filesystem.files[DESTINATION], b"old bytes")


if __name__ == "__main__":
    unittest.main()
