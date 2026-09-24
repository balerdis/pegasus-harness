"""Tests that pegasus's non-interactive surface works when `_curses` is unavailable.

This reproduces a real user report: a hand-built Python 3.12, compiled in `/usr/local`
without the ncurses headers, has no `_curses` extension module at all. Before the fix,
`pegasus.cli` imported `pegasus.tui.app` at module load time (`from pegasus.tui import
app as tui_app`), and `pegasus.tui.app` does `import curses` at its own module level --
so the import chain ran on every invocation of the CLI, whether or not the TUI was ever
opened. `--version`, `doctor --json` and `install` all failed with the same
`ModuleNotFoundError: No module named '_curses'`, even though none of them touch a
terminal screen.

`_curses` is blocked with a `sys.meta_path` hook installed in a subprocess before
`pegasus` is ever imported -- the same shape `tests/test_version_guard.py` uses to
fabricate an old interpreter before `pegasus.__main__` runs, so the hook is in place
for the *first* import of anything under `pegasus`, not retrofitted after the fact.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: Installed before anything under `pegasus` is imported, so the very first `import
#: curses` (transitively or directly) anywhere in the process sees `_curses` as absent
#: -- exactly what the reported interpreter actually has.
_BLOCK_CURSES_PRELUDE = (
    "import sys, importlib.abc\n"
    "class _BlockCurses(importlib.abc.MetaPathFinder):\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name == '_curses' or name.startswith('_curses.'):\n"
    "            raise ModuleNotFoundError(\"No module named '_curses'\")\n"
    "        return None\n"
    "sys.meta_path.insert(0, _BlockCurses())\n"
    "sys.path.insert(0, %r)\n"
) % str(SRC)


def _run_blocked(argv: list[str], home: Path, *, path: str = "/usr/bin:/bin") -> subprocess.CompletedProcess:
    script = _BLOCK_CURSES_PRELUDE + (
        "import runpy\n"
        "sys.argv = ['pegasus'] + %r\n"
        "runpy.run_module('pegasus.__main__', run_name='__main__')\n"
    ) % list(argv)
    env = {
        "PATH": path,
        "HOME": str(home),
        "XDG_DATA_HOME": str(home / "data"),
    }
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
    )


def _stub_opencode(stub_dir: Path) -> None:
    """A fake `opencode` on `PATH`, just present enough for `install` to find
    it -- `install` refuses to write configuration for a CLI it cannot see
    on this machine, which has nothing to do with the defect under test
    here."""
    stub_dir.mkdir(parents=True, exist_ok=True)
    opencode = stub_dir / "opencode"
    opencode.write_text("#!/bin/sh\necho opencode 1.0.0\n", encoding="utf-8")
    opencode.chmod(0o755)


class NonInteractiveSurfaceWithoutCursesTest(unittest.TestCase):
    """Every command reachable without opening the TUI must not need `_curses`."""

    def test_version_works_without_curses(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run_blocked(["--version"], Path(home))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("_curses", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_doctor_json_works_without_curses(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run_blocked(["doctor", "--json"], Path(home))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("_curses", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_install_works_without_curses(self):
        with tempfile.TemporaryDirectory() as home:
            stub_dir = Path(home) / "stub-bin"
            _stub_opencode(stub_dir)
            result = _run_blocked(
                ["install", "--cli", "opencode", "--mcp", "none"],
                Path(home),
                path=f"{stub_dir}:/usr/bin:/bin",
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("_curses", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
