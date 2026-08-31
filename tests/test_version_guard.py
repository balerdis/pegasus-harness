"""Tests for the Python-version floor guard at the top of src/pegasus/__main__.py.

`_too_old_message` is exercised directly with fabricated version tuples, so the guard's logic is
provable without a second interpreter binary. `GuardWiringTest` then confirms the wiring: the
normal path still runs on the interpreter actually available here, and a fabricated old
`sys.version_info`, injected in a subprocess before `pegasus.__main__` is ever imported, is
rejected with one clear line on stderr and no traceback -- before `pegasus.cli` (or anything it
imports) gets a chance to run.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pegasus.__main__ import MINIMUM_PYTHON, _too_old_message  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class TooOldMessageTest(unittest.TestCase):
    def test_accepts_the_minimum_version(self):
        self.assertIsNone(_too_old_message((3, 12, 0, "final", 0)))

    def test_accepts_a_newer_version(self):
        self.assertIsNone(_too_old_message((3, 13, 1, "final", 0)))

    def test_rejects_an_older_minor(self):
        message = _too_old_message((3, 9, 0, "final", 0))
        self.assertEqual(message, "pegasus requires Python 3.12 or newer; this is Python 3.9")

    def test_rejects_an_older_major(self):
        message = _too_old_message((2, 7, 18, "final", 0))
        self.assertIn("this is Python 2.7", message)


class PyprojectAgreementTest(unittest.TestCase):
    """The guard's floor and pyproject.toml's `requires-python` must never silently drift apart."""

    def test_minimum_python_matches_requires_python(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        requires = pyproject["project"]["requires-python"]
        self.assertEqual(requires, ">=%s.%s" % MINIMUM_PYTHON)


class GuardWiringTest(unittest.TestCase):
    def test_the_normal_path_still_imports_and_runs(self):
        with tempfile.TemporaryDirectory() as scratch_home:
            environment = dict(os.environ, PYTHONPATH=str(SRC), HOME=scratch_home,
                                XDG_DATA_HOME=str(Path(scratch_home) / "data"))
            result = subprocess.run(
                [sys.executable, "-m", "pegasus", "doctor", "--json"],
                cwd=str(ROOT), env=environment, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_fabricated_old_interpreter_is_rejected_before_pegasus_cli_imports(self):
        script = (
            "import sys\n"
            "sys.version_info = (3, 9, 0, 'final', 0)\n"
            "sys.path.insert(0, %r)\n"
            "import pegasus.__main__\n"
        ) % str(SRC)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "pegasus requires Python 3.12 or newer; this is Python 3.9\n")
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
