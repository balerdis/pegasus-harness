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

from build_zipapp import (  # noqa: E402
    build,
    stage,
    validate_identity,
    validate_source_layout,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "zipapp_source"
FIXTURE_IDENTITY = Path(__file__).resolve().parent / "fixtures" / "zipapp_source_identity.json"
REAL_SOURCE = Path(__file__).resolve().parents[1] / "src" / "pegasus"
REAL_IDENTITY = REAL_SOURCE / "identity.json"


class StageTest(unittest.TestCase):
    """Copying the package into a build directory, pruning what a build never needs."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.destination = Path(self._directory.name) / "stage"

    def test_copies_the_package_under_its_own_name(self):
        stage(FIXTURE_ROOT, self.destination, FIXTURE_IDENTITY)
        self.assertEqual(
            (self.destination / "pegasus" / "cli.py").read_text(encoding="utf-8"),
            (FIXTURE_ROOT / "cli.py").read_text(encoding="utf-8"),
        )

    def test_writes_a_root_level_entry_point_identical_to_the_packages_own(self):
        """`zipapp` looks for `__main__.py` at the archive root, not inside the package it runs --
        this is the file that makes that lookup land on the same code `python -m pegasus` runs."""
        stage(FIXTURE_ROOT, self.destination, FIXTURE_IDENTITY)
        self.assertEqual(
            (self.destination / "__main__.py").read_text(encoding="utf-8"),
            (FIXTURE_ROOT / "__main__.py").read_text(encoding="utf-8"),
        )

    def test_prunes_bytecode_caches(self):
        cache = FIXTURE_ROOT / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "cli.cpython-312.pyc").write_bytes(b"stale bytecode")
        self.addCleanup(lambda: __import__("shutil").rmtree(cache))
        stage(FIXTURE_ROOT, self.destination, FIXTURE_IDENTITY)
        self.assertFalse((self.destination / "pegasus" / "__pycache__").exists())

    def test_stages_the_given_identity_overriding_whatever_source_already_carried(self):
        """A distribution's `--identity` always wins over the pinned engine's own file."""
        stage(FIXTURE_ROOT, self.destination, FIXTURE_IDENTITY)
        self.assertEqual(
            (self.destination / "pegasus" / "identity.json").read_bytes(),
            FIXTURE_IDENTITY.read_bytes(),
        )


class ValidateSourceLayoutTest(unittest.TestCase):
    """The tightened staging guard: catch the nested-build footgun at build time, not at runtime.

    Locks in the empirically observed failure this guard exists to pre-empt: `--source
    <extraction-root>` instead of `--source <extraction-root>/pegasus` used to pass the old guard
    (it only checked for `__main__.py`, which `stage()` also copies to the extraction root) and
    build a nested `pegasus/pegasus/` archive that crashed at runtime with
    `ModuleNotFoundError: No module named 'pegasus.cli'` -- loud, but only after the artifact was
    already built and handed to someone.
    """

    def test_accepts_the_real_source_tree(self):
        validate_source_layout(REAL_SOURCE)  # must not raise

    def test_rejects_a_source_missing_main(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            with self.assertRaises(ValueError) as raised:
                validate_source_layout(Path(empty_dir))
            self.assertIn("__main__.py", str(raised.exception))

    def test_rejects_the_extraction_root_above_the_package(self):
        """The exact footgun: a directory with `__main__.py` (copied there by `stage()`) but no
        `core/content.py`, because it is the parent of the real package, not the package itself."""
        with tempfile.TemporaryDirectory() as extraction_root:
            root = Path(extraction_root)
            (root / "__main__.py").write_text("# stand-in entry point\n", encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                validate_source_layout(root)
            message = str(raised.exception)
            self.assertIn("core", message)
            self.assertIn("content.py", message)
            self.assertIn("nested", message)


class ValidateIdentityTest(unittest.TestCase):
    """Build-time identity validation, reusing `core/identity.py`'s own rules -- never a second,
    separately maintained copy of the wordmark charset."""

    def test_accepts_pegasus_own_identity_against_the_real_source(self):
        validate_identity(REAL_SOURCE, REAL_IDENTITY)  # must not raise

    def test_rejects_a_missing_identity_file(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            with self.assertRaises(ValueError) as raised:
                validate_identity(REAL_SOURCE, Path(empty_dir) / "missing-identity.json")
            self.assertIn("does not exist", str(raised.exception))

    def test_rejects_a_name_with_invalid_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            bad_identity = Path(directory) / "identity.json"
            bad_identity.write_text(
                json.dumps({
                    "product_id": "acme",
                    "display_name": "ACME",
                    "program_name": "acme",
                    "version": "1.0.0",
                    "wordmark_words": ["MI-EQUIPO"],
                    "release": {
                        "asset_url_template": "https://example.invalid/releases/download/{tag}/{asset}",
                        "binary_asset": "acme",
                        "latest_release_api_url": "https://example.invalid/api/releases/latest",
                        "release_page_url": "https://example.invalid/releases",
                    },
                }),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as raised:
                validate_identity(REAL_SOURCE, bad_identity)
            message = str(raised.exception)
            self.assertIn("letters", message)
            self.assertIn("digits", message)
            self.assertIn("hyphens", message)

    def test_rejects_a_source_with_no_identity_module_to_validate_against(self):
        with tempfile.TemporaryDirectory() as source_dir:
            with self.assertRaises(ValueError) as raised:
                validate_identity(Path(source_dir), REAL_IDENTITY)
            self.assertIn("core/identity.py", str(raised.exception))


class BuildTest(unittest.TestCase):
    """The end-to-end artifact: one executable file with a shebang, plus its checksum."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.output = Path(self._directory.name) / "pegasus"

    def test_the_artifact_starts_with_a_shebang(self):
        build(FIXTURE_ROOT, self.output, FIXTURE_IDENTITY)
        with self.output.open("rb") as handle:
            self.assertTrue(handle.read(2) == b"#!")

    def test_the_artifact_is_executable(self):
        build(FIXTURE_ROOT, self.output, FIXTURE_IDENTITY)
        mode = stat.S_IMODE(self.output.stat().st_mode)
        self.assertTrue(mode & stat.S_IXUSR)

    def test_the_artifact_runs_and_reports_its_version(self):
        build(FIXTURE_ROOT, self.output, FIXTURE_IDENTITY)
        result = subprocess.run(
            [str(self.output), "doctor", "--json"], capture_output=True, text=True, check=True
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["pegasus_version"], "9.9.9-fixture")

    def test_writes_a_matching_sha256_checksum_file(self):
        build(FIXTURE_ROOT, self.output, FIXTURE_IDENTITY)
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
        build(copy_root, output, FIXTURE_IDENTITY)
        return hashlib.sha256(output.read_bytes()).hexdigest()

    def test_builds_from_identical_content_with_different_mtimes_match(self):
        first = self._sha256_of_build_with_mtime(1_000_000_000)
        second = self._sha256_of_build_with_mtime(2_000_000_000)
        self.assertEqual(first, second)


class MainRequiresIdentityTest(unittest.TestCase):
    """`--identity` is required unconditionally, including for Pegasus's own release build --
    the only shape in which forgetting it is literally impossible: `argparse.error`, never a
    silent default that ships a distribution branded as Pegasus."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        script = Path(__file__).resolve().parents[1] / "tools" / "build_zipapp.py"
        return subprocess.run(
            [sys.executable, str(script), *args], capture_output=True, text=True
        )

    def test_missing_identity_is_an_argparse_error_not_a_silent_default(self):
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "pegasus"
            result = self._run("--out", str(out))
            self.assertEqual(result.returncode, 2)
            self.assertIn("--identity", result.stderr)
            self.assertFalse(out.exists())

    def test_pegasus_own_release_build_also_requires_identity(self):
        """Even a build with no `--source` override (Pegasus's own package) must supply
        `--identity` explicitly -- there is no default that falls back to the packaged file."""
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "pegasus"
            result = self._run("--out", str(out))
            self.assertEqual(result.returncode, 2)
            self.assertFalse(out.exists())

    def test_a_valid_identity_and_source_builds_successfully(self):
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "pegasus"
            result = self._run("--source", str(REAL_SOURCE), "--identity", str(REAL_IDENTITY), "--out", str(out))
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(out.is_file())

    def test_an_invalid_name_is_rejected_before_producing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            bad_identity = Path(directory) / "identity.json"
            bad_identity.write_text(
                json.dumps({
                    "product_id": "acme",
                    "display_name": "ACME",
                    "program_name": "acme",
                    "version": "1.0.0",
                    "wordmark_words": ["MI-EQUIPO"],
                    "release": {
                        "asset_url_template": "https://example.invalid/releases/download/{tag}/{asset}",
                        "binary_asset": "acme",
                        "latest_release_api_url": "https://example.invalid/api/releases/latest",
                        "release_page_url": "https://example.invalid/releases",
                    },
                }),
                encoding="utf-8",
            )
            out = Path(directory) / "pegasus"
            result = self._run(
                "--source", str(REAL_SOURCE), "--identity", str(bad_identity), "--out", str(out)
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(out.exists())

    def test_the_extraction_root_footgun_is_caught_at_build_time(self):
        """The empirically confirmed footgun: `--source` pointed one level too high used to pass
        the old guard silently and only fail at runtime. It must now be refused at build time."""
        with tempfile.TemporaryDirectory() as extraction_root:
            root = Path(extraction_root)
            stage(REAL_SOURCE, root, REAL_IDENTITY)
            out = root / "pegasus-artifact"
            result = self._run(
                "--source", str(root), "--identity", str(REAL_IDENTITY), "--out", str(out)
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("nested", result.stderr)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
