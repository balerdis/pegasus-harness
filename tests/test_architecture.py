"""The rule that keeps the abstraction from rotting.

The engine must not know which CLIs exist. This test derives the list of CLI
identifiers from the adapter directories themselves, so it keeps working as
adapters are added without anyone remembering to update it.
"""
from __future__ import annotations

import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "pegasus"
ADAPTERS = SOURCE / "adapters"
CLI_AGNOSTIC_PACKAGES = ("core", "ports", "infra", "tui")


def cli_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            item.name
            for item in ADAPTERS.iterdir()
            if item.is_dir() and not item.name.startswith("_") and item.name != "__pycache__"
        )
    )


def agnostic_modules() -> list[Path]:
    return sorted(
        path
        for package in CLI_AGNOSTIC_PACKAGES
        for path in (SOURCE / package).rglob("*.py")
        if "__pycache__" not in path.parts
    )


class NoCliNamesOutsideAdaptersTest(unittest.TestCase):
    def test_at_least_one_adapter_exists(self):
        """Without this, the test below would pass by finding nothing to look for."""
        self.assertTrue(cli_ids(), "no adapter directories found under src/pegasus/adapters")

    def test_agnostic_packages_are_scanned(self):
        self.assertTrue(agnostic_modules(), "no modules found in the CLI-agnostic packages")

    def test_no_agnostic_module_names_a_cli(self):
        offenders = [
            f"{path.relative_to(SOURCE)}:{number} mentions {cli_id!r}"
            for path in agnostic_modules()
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            for cli_id in cli_ids()
            if cli_id in line.lower()
        ]
        self.assertEqual(
            offenders,
            [],
            "CLI-specific knowledge leaked out of adapters/:\n" + "\n".join(offenders),
        )


class AdapterIsolationTest(unittest.TestCase):
    """One adapter must not depend on another, or the abstraction has no boundary.

    Files sitting directly under `adapters/` are exempt: that is the composition
    root, and knowing every adapter is its whole job.
    """

    def test_no_adapter_imports_another_adapter(self):
        offenders = [
            f"{path.relative_to(SOURCE)}:{number}"
            for path in sorted(ADAPTERS.rglob("*.py"))
            if "__pycache__" not in path.parts and _owning_adapter(path)
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            for other in cli_ids()
            if other != _owning_adapter(path) and f"adapters.{other}" in line
        ]
        self.assertEqual(offenders, [], "adapters must not depend on each other")

    def test_the_composition_root_is_the_only_place_that_knows_every_adapter(self):
        root = (ADAPTERS / "__init__.py").read_text(encoding="utf-8")
        for cli_id in cli_ids():
            self.assertIn(cli_id, root, f"{cli_id} is not registered in the composition root")


def _owning_adapter(path: Path) -> str:
    """The adapter a file belongs to, or empty for the composition root itself."""
    relative = path.relative_to(ADAPTERS).parts
    return relative[0] if len(relative) > 1 else ""


if __name__ == "__main__":
    unittest.main()
