"""Guard: nothing under core/ or ports/ names a specific CLI.

Hexagonal architecture means the core describes concepts in CLI-agnostic terms;
a specific product's vocabulary belongs to its adapter, never to the core or the
ports it depends on. This test does not check prose or intent, only that the
substring never appears, so it stays true even as new modules are added.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "pegasus"
CHECKED_DIRECTORIES = ("core", "ports")
FORBIDDEN_SUBSTRING = "opencode"


class CoreIsCliAgnosticTest(unittest.TestCase):
    def test_no_module_under_core_or_ports_mentions_a_specific_cli(self):
        offenses = []
        for directory_name in CHECKED_DIRECTORIES:
            directory = ROOT / directory_name
            for path in sorted(directory.rglob("*.py")):
                lines = path.read_text(encoding="utf-8").splitlines()
                for line_number, line in enumerate(lines, start=1):
                    if FORBIDDEN_SUBSTRING in line.lower():
                        offenses.append(f"{path}:{line_number}: {line.strip()}")
        self.assertEqual(
            offenses,
            [],
            f"found {FORBIDDEN_SUBSTRING!r} outside its adapter:\n" + "\n".join(offenses),
        )


if __name__ == "__main__":
    unittest.main()
