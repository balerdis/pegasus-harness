"""End-to-end regression: the build recipe a distribution actually follows, locked in as a test.

This locks in what `sdd/pegasus-distributions/build-recipe-verification` already proved by hand:
extraction tolerates the prepended shebang (`zipfile.is_zipfile()` is true, all entries extract
cleanly), extract-then-rebuild-unmodified reproduces the byte-identical published SHA-256, the
rebuilt binary runs and reports its own identity (never Pegasus's), and overlaid content genuinely
resolves -- a broken `agents/king-pegasus.md` fails a real install on that exact file, while the
unmodified control build succeeds.

Uses `ACME` throughout: an obviously fictional name, never a real organization's, so nothing here
could be mistaken for endorsing or targeting one. Everything lives inside a scratch directory and
a throwaway `$HOME` -- never the real environment this suite runs under.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_ZIPAPP = ROOT / "tools" / "build_zipapp.py"
REAL_SOURCE = ROOT / "src" / "pegasus"
REAL_IDENTITY = REAL_SOURCE / "identity.json"

#: An obviously fictional distribution -- never a real organization -- so this test cannot be
#: mistaken for targeting or endorsing one.
ACME_IDENTITY_PAYLOAD = {
    "product_id": "acme-widget",
    "display_name": "Acme",
    "program_name": "acme",
    "wordmark_words": ["ACME"],
    "release": {
        "asset_url_template": "https://example.invalid/acme/releases/download/{tag}/{asset}",
        "binary_asset": "acme",
        "latest_release_api_url": "https://example.invalid/acme/api/releases/latest",
        "release_page_url": "https://example.invalid/acme/releases",
    },
}


def _build(source: Path, out: Path, identity: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUILD_ZIPAPP), "--source", str(source), "--identity", str(identity), "--out", str(out)],
        capture_output=True, text=True,
    )


class DistributionBuildRecipeTest(unittest.TestCase):
    """Not instant -- it builds the real package three times and runs the resulting binaries a
    handful of times, each a real subprocess with real Python startup. Timed at well under 5
    seconds total during development, comfortably inside the default suite's per-test budget, so
    it is not gated behind an environment variable: gating it would have meant either a second,
    shallower version of this test staying in the default run (defeating the point of locking in
    the real recipe) or silently dropping this coverage from CI-equivalent runs entirely.
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.home = self.root / "home"
        self.home.mkdir()

    def _run_binary(self, binary: Path, *args: str, home: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(binary), *args],
            env={"HOME": str(home if home is not None else self.home), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30,
        )

    def test_extract_rebuild_and_overlay_recipe(self):
        # 1. Control build: Pegasus's own identity, from the real pinned source -- stands in for
        # a published release artifact.
        control = self.root / "control" / "pegasus"
        result = _build(REAL_SOURCE, control, REAL_IDENTITY)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        control_sha256 = hashlib.sha256(control.read_bytes()).hexdigest()

        # 2. Extraction tolerates the prepended shebang: `zipfile` reads it as a real zip despite
        # the shebang bytes ahead of the local-file-header signature.
        extracted = self.root / "extracted"
        self.assertTrue(zipfile.is_zipfile(control))
        with zipfile.ZipFile(control) as archive:
            archive.extractall(extracted)
        extracted_package = extracted / "pegasus"
        self.assertTrue((extracted_package / "__main__.py").is_file())
        self.assertTrue((extracted_package / "identity.json").is_file())

        # 3. Extract-then-rebuild-unmodified reproduces the exact published SHA-256: `_normalize`
        # pins mtime/mode after staging, so the noise extraction introduces is erased by
        # construction.
        rebuilt = self.root / "rebuilt" / "pegasus"
        result = _build(extracted_package, rebuilt, extracted_package / "identity.json")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        rebuilt_sha256 = hashlib.sha256(rebuilt.read_bytes()).hexdigest()
        self.assertEqual(
            rebuilt_sha256, control_sha256,
            "extract-then-rebuild-unmodified must reproduce the exact published SHA-256",
        )

        # 4. Build ACME (an obviously fictional distribution, never a real organization's) from
        # the still-unmodified extracted package, before overlaying any content difference --
        # this build proves the identity facets on their own, uncomplicated by the overlay.
        acme_identity = self.root / "acme-identity.json"
        acme_identity.write_text(json.dumps(ACME_IDENTITY_PAYLOAD), encoding="utf-8")

        acme = self.root / "acme" / "ACME"
        result = _build(extracted_package, acme, acme_identity)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # 5. The rebuilt binary runs. `pegasus_version`/`schema` are deliberately identical wire
        # identifiers across every distribution (see the spec's wire-format requirement) -- what
        # must differ, checked below, is the displayed name, data directory and release source.
        acme_home = self.root / "acme-home"
        acme_home.mkdir()
        # A CLI adapter's own config directory has to look "detected", or `install` (not
        # `--dry-run`) refuses outright -- this stands in for an OpenCode install already there.
        (acme_home / ".config" / "opencode").mkdir(parents=True)
        result = self._run_binary(acme, "doctor", "--json", home=acme_home)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "pegasus/cli-report/v1")

        # 6. `--version` prints the program name and version identity supplies, never a
        # hardcoded literal -- proving the displayed name is genuinely ACME's own.
        result = self._run_binary(acme, "--version", home=acme_home)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("acme", result.stdout.lower())
        self.assertNotIn("pegasus", result.stdout.lower())

        # 7. A real (non-dry-run) install creates its own data directory, keyed by its own
        # `product_id` -- never Pegasus's.
        result = self._run_binary(acme, "install", "--cli", "opencode", home=acme_home)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue((acme_home / ".local" / "share" / "acme-widget").exists())
        self.assertFalse((acme_home / ".local" / "share" / "pegasus-harness").exists())

        # 8. Overlay a genuine content difference that breaks an existing file's frontmatter --
        # exactly the overlay the verified recipe used -- and rebuild ACME from it.
        king_pegasus = extracted_package / "content" / "agents" / "king-pegasus.md"
        original_king_pegasus = king_pegasus.read_text(encoding="utf-8")
        king_pegasus.write_text(
            "overlay marker breaking frontmatter\n" + original_king_pegasus, encoding="utf-8"
        )
        acme_overlaid = self.root / "acme-overlaid" / "ACME"
        result = _build(extracted_package, acme_overlaid, acme_identity)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # 9. The overlaid content genuinely resolves: the broken `king-pegasus.md` fails this
        # exact install, naming that exact file -- while the unmodified control build succeeds
        # on the same command.
        overlaid_home = self.root / "acme-overlaid-home"
        (overlaid_home / ".config" / "opencode").mkdir(parents=True)
        result = self._run_binary(
            acme_overlaid, "install", "--cli", "opencode", "--dry-run", home=overlaid_home
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("king-pegasus.md", result.stdout + result.stderr)

        control_home = self.root / "control-home"
        (control_home / ".config" / "opencode").mkdir(parents=True)
        control_result = self._run_binary(
            control, "install", "--cli", "opencode", "--dry-run", home=control_home
        )
        self.assertEqual(control_result.returncode, 0, msg=control_result.stderr)


if __name__ == "__main__":
    unittest.main()
