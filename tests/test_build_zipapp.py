"""Tests for tools/build_zipapp.py: staging the package and zipping it into one runnable file."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_zipapp import build, stage  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "zipapp_source"


class StageTest(unittest.TestCase):
    """Copying the package into a build directory, pruning what a build never needs."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.destination = Path(self._directory.name) / "stage"

    def test_copies_the_package_under_its_own_name(self):
        stage(FIXTURE_ROOT, self.destination)
        self.assertEqual(
            (self.destination / "pegasus" / "cli.py").read_text(encoding="utf-8"),
            (FIXTURE_ROOT / "cli.py").read_text(encoding="utf-8"),
        )

    def test_writes_a_root_level_entry_point_identical_to_the_packages_own(self):
        """`zipapp` looks for `__main__.py` at the archive root, not inside the package it runs --
        this is the file that makes that lookup land on the same code `python -m pegasus` runs."""
        stage(FIXTURE_ROOT, self.destination)
        self.assertEqual(
            (self.destination / "__main__.py").read_text(encoding="utf-8"),
            (FIXTURE_ROOT / "__main__.py").read_text(encoding="utf-8"),
        )

    def test_prunes_bytecode_caches(self):
        cache = FIXTURE_ROOT / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "cli.cpython-312.pyc").write_bytes(b"stale bytecode")
        self.addCleanup(lambda: __import__("shutil").rmtree(cache))
        stage(FIXTURE_ROOT, self.destination)
        self.assertFalse((self.destination / "pegasus" / "__pycache__").exists())


class BuildTest(unittest.TestCase):
    """The end-to-end artifact: one executable file with a shebang, plus its checksum."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.output = Path(self._directory.name) / "pegasus"

    def test_the_artifact_starts_with_a_shebang(self):
        build(FIXTURE_ROOT, self.output)
        with self.output.open("rb") as handle:
            self.assertTrue(handle.read(2) == b"#!")

    def test_the_artifact_is_executable(self):
        build(FIXTURE_ROOT, self.output)
        mode = stat.S_IMODE(self.output.stat().st_mode)
        self.assertTrue(mode & stat.S_IXUSR)

    def test_the_artifact_runs_and_reports_its_version(self):
        build(FIXTURE_ROOT, self.output)
        result = subprocess.run(
            [str(self.output), "doctor", "--json"], capture_output=True, text=True, check=True
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["pegasus_version"], "9.9.9-fixture")

    def test_writes_a_matching_sha256_checksum_file(self):
        build(FIXTURE_ROOT, self.output)
        checksum_path = self.output.with_name(self.output.name + ".sha256")
        self.assertTrue(checksum_path.exists())
        expected = subprocess.run(
            ["sha256sum", self.output.name], cwd=self.output.parent, capture_output=True, text=True, check=True
        ).stdout
        self.assertEqual(checksum_path.read_text(encoding="utf-8"), expected)


class ReproducibilityTest(unittest.TestCase):
    """Byte-identical source must produce a byte-identical artifact, mtimes notwithstanding.

    `zipapp.create_archive` bakes each staged file's mtime into its `ZipInfo`, so two checkouts
    of the same content -- a fresh `git clone` today and one tomorrow, say -- used to produce two
    different SHA-256 hashes of the final artifact. That defeats the whole point of publishing a
    checksum: it could only prove "these are the exact bytes you downloaded", never "these bytes
    are what the tagged source actually produces".
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def _sha256_of_build_with_mtime(self, mtime: float) -> str:
        copy_root = self.root / f"source-{mtime}"
        shutil.copytree(FIXTURE_ROOT, copy_root)
        for path in copy_root.rglob("*"):
            os.utime(path, (mtime, mtime))
        output = self.root / f"pegasus-{mtime}"
        build(copy_root, output)
        return hashlib.sha256(output.read_bytes()).hexdigest()

    def test_builds_from_identical_content_with_different_mtimes_match(self):
        first = self._sha256_of_build_with_mtime(1_000_000_000)
        second = self._sha256_of_build_with_mtime(2_000_000_000)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
