"""The shell analogue of `NoProductIdentityOutsideCompositionRootTest`.

`install.sh` is not Python, so it cannot be scanned by `ast`. The rule it
enforces is the same one anyway: no distribution's identity may leak outside
the one place that is allowed to name it. For `cli.py` that place is a
Python module; for `install.sh` it is the identity header block delimited by
the two `# ====...====` banner lines near the top of the file -- everything
below those banners must reference `PRODUCT_ID`, `PRODUCT_DISPLAY_NAME`,
`PRODUCT_PROGRAM_NAME` or `PRODUCT_RELEASE_BASE_URL_DEFAULT`, never a literal
brand.

`BuildInstallerTest` then proves the behavioural half: `tools/build_installer.py`
takes an `identity.json` and produces a runnable installer whose header (and
nothing else) carries that identity -- exercised with the fictional `ACME`
identity `tests/test_distribution_e2e.py` already uses, never a real
organization's name.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"
BUILD_INSTALLER = ROOT / "tools" / "build_installer.py"
REAL_IDENTITY = ROOT / "src" / "pegasus" / "identity.json"

#: The banner line bracketing the identity header block in install.sh. Exactly two
#: of these must appear: the block starts right after the first and ends right
#: before the second.
HEADER_BANNER = "# " + "=" * 76

#: Case-insensitive brand fragments that must never survive outside the identity
#: header block -- the same list `tests/test_architecture.py` scans Python source
#: for, applied here to the shell installer.
BANNED_FRAGMENTS = ("pegasus", "harness", "balerdis")

#: An obviously fictional distribution -- never a real organization -- so this
#: test cannot be mistaken for targeting or endorsing one. Mirrors the payload
#: `tests/test_distribution_e2e.py` already uses.
ACME_IDENTITY_PAYLOAD = {
    "product_id": "acme-widget",
    "display_name": "Acme",
    "program_name": "acme",
    "version": "1.0.0",
    "wordmark_words": ["ACME"],
    "release": {
        "asset_url_template": "https://example.invalid/acme/releases/download/{tag}/{asset}",
        "binary_asset": "acme",
        "latest_release_api_url": "https://example.invalid/acme/api/releases/latest",
        "release_page_url": "https://example.invalid/acme/releases",
        "install_base_url_default": "https://example.invalid/acme/releases/latest/download",
    },
}


def _body_outside_header(text: str) -> str:
    """`install.sh`'s content with the identity header block removed.

    Splits on `HEADER_BANNER`: the header lives strictly between the first and
    second occurrence. Everything before the first banner (the top-of-file
    usage comment, `set -euo pipefail`) and everything after the second
    banner (the rest of the script) is "outside" and must never name a brand.
    """
    parts = text.split(HEADER_BANNER)
    if len(parts) != 3:
        raise AssertionError(
            f"expected exactly two {HEADER_BANNER!r} banner lines delimiting the "
            f"identity header block, found {len(parts) - 1}"
        )
    before, _header, after = parts
    return before + after


class NoProductIdentityOutsideHeaderTest(unittest.TestCase):
    """`install.sh`'s composition root is its identity header block. Nothing
    below it may spell a distribution's name -- see `tools/build_installer.py`,
    which regenerates only that block from a different `identity.json`."""

    def test_install_sh_exists(self):
        self.assertTrue(INSTALL_SH.is_file())

    def test_no_brand_literal_survives_outside_the_identity_header(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        body = _body_outside_header(text)
        offenders = []
        for number, line in enumerate(body.splitlines(), 1):
            lowered = line.lower()
            for fragment in BANNED_FRAGMENTS:
                if fragment in lowered:
                    offenders.append(f"{number}: {line.strip()!r}")
        self.assertEqual(offenders, [], "brand literal(s) found outside the identity header:\n" + "\n".join(offenders))

    def test_the_header_block_itself_still_carries_pegasus_own_identity(self):
        """Sanity check on the extraction itself: the banner-delimited block is
        exactly where Pegasus's own identity values live today, so a change that
        accidentally widened or narrowed the header boundaries would be caught
        here rather than by a silently-passing scan above."""
        text = INSTALL_SH.read_text(encoding="utf-8")
        parts = text.split(HEADER_BANNER)
        self.assertEqual(len(parts), 3)
        header = parts[1]
        self.assertIn("pegasus-harness", header)
        self.assertIn("Pegasus", header)


class BuildInstallerTest(unittest.TestCase):
    """`tools/build_installer.py`: generate a distribution's own `install.sh`
    from its `identity.json`, mirroring `tools/build_zipapp.py`'s discipline."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(BUILD_INSTALLER), *args], capture_output=True, text=True
        )

    def _acme_identity(self) -> Path:
        path = self.root / "acme-identity.json"
        path.write_text(json.dumps(ACME_IDENTITY_PAYLOAD), encoding="utf-8")
        return path

    def test_missing_identity_is_an_argparse_error_not_a_silent_default(self):
        out = self.root / "install.sh"
        result = self._run("--out", str(out))
        self.assertEqual(result.returncode, 2)
        self.assertIn("--identity", result.stderr)
        self.assertFalse(out.exists())

    def test_missing_out_is_an_argparse_error(self):
        result = self._run("--identity", str(REAL_IDENTITY))
        self.assertEqual(result.returncode, 2)
        self.assertIn("--out", result.stderr)

    def test_refuses_to_overwrite_an_existing_out(self):
        out = self.root / "install.sh"
        out.write_text("already here\n", encoding="utf-8")
        result = self._run("--identity", str(REAL_IDENTITY), "--out", str(out))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(out.read_text(encoding="utf-8"), "already here\n")

    def test_rejects_an_invalid_identity_before_writing_anything(self):
        bad_identity = self.root / "bad-identity.json"
        bad_identity.write_text(
            json.dumps({**ACME_IDENTITY_PAYLOAD, "wordmark_words": ["MI-EQUIPO"]}), encoding="utf-8"
        )
        out = self.root / "install.sh"
        result = self._run("--identity", str(bad_identity), "--out", str(out))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(out.exists())

    def test_pegasus_own_identity_reproduces_the_committed_installer(self):
        """Building with Pegasus's own `identity.json` must yield the exact same
        header values already committed in `install.sh` -- the generator and the
        checked-in file can never be allowed to drift apart."""
        out = self.root / "install.sh"
        result = self._run("--identity", str(REAL_IDENTITY), "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        generated = out.read_text(encoding="utf-8")
        committed = INSTALL_SH.read_text(encoding="utf-8")
        self.assertEqual(generated, committed)

    def test_generated_installer_is_executable_and_syntactically_valid_bash(self):
        out = self.root / "install.sh"
        result = self._run("--identity", str(self._acme_identity()), "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = out.stat().st_mode
        self.assertTrue(mode & 0o100, "generated installer is not executable")
        check = subprocess.run(["bash", "-n", str(out)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_generated_acme_installer_contains_no_engine_brand(self):
        out = self.root / "install.sh"
        result = self._run("--identity", str(self._acme_identity()), "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = out.read_text(encoding="utf-8")
        lowered = text.lower()
        for fragment in BANNED_FRAGMENTS:
            self.assertNotIn(fragment, lowered, f"generated ACME installer still contains {fragment!r}")

    def test_generated_acme_installer_carries_acmes_own_identity(self):
        out = self.root / "install.sh"
        result = self._run("--identity", str(self._acme_identity()), "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = out.read_text(encoding="utf-8")
        self.assertIn("PRODUCT_ID='acme-widget'", text)
        self.assertIn("PRODUCT_DISPLAY_NAME='Acme'", text)
        self.assertIn("PRODUCT_PROGRAM_NAME='acme'", text)
        self.assertIn(
            "PRODUCT_RELEASE_BASE_URL_DEFAULT="
            "'https://example.invalid/acme/releases/latest/download'",
            text,
        )

    def test_install_base_url_default_is_used_directly_not_derived(self):
        """`build_installer.py` must read `release.install_base_url_default`
        straight off the identity, never derive it by splitting
        `release_page_url` (or `asset_url_template`) -- see that field's own
        docstring in `core/identity.py`. Proven here with a non-GitHub host
        whose 'latest' download path does not follow GitHub's
        `/latest/download` convention at all: if the generator were still
        deriving instead of reading, this value would come out wrong."""
        payload = {
            **ACME_IDENTITY_PAYLOAD,
            "release": {
                **ACME_IDENTITY_PAYLOAD["release"],
                "release_page_url": "https://example.invalid/acme/downloads",
                "install_base_url_default": "https://cdn.example.invalid/acme/stable",
            },
        }
        identity_path = self.root / "acme-identity-custom.json"
        identity_path.write_text(json.dumps(payload), encoding="utf-8")
        out = self.root / "install.sh"
        result = self._run("--identity", str(identity_path), "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = out.read_text(encoding="utf-8")
        self.assertIn(
            "PRODUCT_RELEASE_BASE_URL_DEFAULT='https://cdn.example.invalid/acme/stable'", text
        )
        self.assertNotIn("example.invalid/acme/downloads/latest/download", text)

    def test_generated_installer_with_a_valid_program_name_runs_help_successfully(self):
        """The assertion that would have caught the digit-leading
        `program_name` bug: `install.sh` builds a bash variable name out of
        `PRODUCT_PROGRAM_NAME` and reads it back with `${!...}` indirect
        expansion, which fails under `set -euo pipefail` for a name that is
        not a legal identifier once uppercased -- aborting the script before
        argument parsing even runs, so even `--help` would die. `core/
        identity.py::parse()` now rejects such a `program_name` at build
        time (see `tests/test_identity.py`), but this test proves the other
        half end-to-end: a *valid* name must still produce an installer
        whose `--help` actually runs, not just one that statically looks
        right."""
        out = self.root / "install.sh"
        result = self._run("--identity", str(self._acme_identity()), "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        home = self.root / "acme-home-help"
        home.mkdir()
        run = subprocess.run(
            ["bash", str(out), "--help"],
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("install.sh", run.stdout)

    def test_generated_acme_installer_help_mentions_acme_not_pegasus(self):
        """Behavioural, not just textual: running the generated installer's
        `--help` under a throwaway HOME must print ACME's own usage text."""
        out = self.root / "install.sh"
        result = self._run("--identity", str(self._acme_identity()), "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        home = self.root / "acme-home"
        home.mkdir()
        run = subprocess.run(
            ["bash", str(out), "--help"],
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn("pegasus", run.stdout.lower())


if __name__ == "__main__":
    unittest.main()
