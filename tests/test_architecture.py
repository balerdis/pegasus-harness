"""The rule that keeps the abstraction from rotting.

The engine must not know which CLIs exist. This test derives the list of CLI
identifiers from the adapter directories themselves, so it keeps working as
adapters are added without anyone remembering to update it.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "pegasus"
ADAPTERS = SOURCE / "adapters"
CLI_AGNOSTIC_PACKAGES = ("core", "ports", "infra", "tui")
PERMISSION_FREE_PACKAGES = ("core", "ports")
OCTAL_PERMISSION_LITERAL = re.compile(r"^0[oO][0-7]{3,4}$")


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


def permission_free_modules() -> list[Path]:
    return sorted(
        path
        for package in PERMISSION_FREE_PACKAGES
        for path in (SOURCE / package).rglob("*.py")
        if "__pycache__" not in path.parts
    )


class NoPermissionOctalLiteralsTest(unittest.TestCase):
    """A POSIX mode is a platform detail; naming one as a bare literal in
    `core/` or `ports/` is exactly the leak this design closes.

    Two kinds of octal are not that leak, and the rule has to let them
    through or it makes the code worse to satisfy itself. Prose that
    mentions a mode is one: reading the source as a syntax tree means a
    docstring is a string and never a number, so it cannot be mistaken for
    a value. A bound in a comparison is the other — `0 <= mode <= 0o777`
    does not choose a permission, it refuses the values that are not one,
    and deleting that check to keep this test quiet would trade a real
    guarantee for a green light. So a literal is only an offender when it
    is not standing inside a comparison.
    """

    def test_permission_free_packages_are_scanned(self):
        self.assertTrue(permission_free_modules(), "no modules found under core/ or ports/")

    def test_no_permission_octal_literal_under_core_or_ports(self):
        offenders = [
            f"{path.relative_to(SOURCE)}:{line} literal {text!r}"
            for path in permission_free_modules()
            for line, text in _chosen_permissions(path)
        ]
        self.assertEqual(
            offenders,
            [],
            "a permission octal literal leaked into core/ or ports/:\n" + "\n".join(offenders),
        )


def _chosen_permissions(path: Path) -> list[tuple[int, str]]:
    """Every octal literal in the file that names a permission it chose."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    bounds = {
        id(literal)
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        for literal in (node.left, *node.comparators)
    }
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, int) or id(node) in bounds:
            continue
        text = ast.get_source_segment(source, node) or ""
        if OCTAL_PERMISSION_LITERAL.match(text):
            found.append((node.lineno, text))
    return sorted(found)


def _owning_adapter(path: Path) -> str:
    """The adapter a file belongs to, or empty for the composition root itself."""
    relative = path.relative_to(ADAPTERS).parts
    return relative[0] if len(relative) > 1 else ""


if __name__ == "__main__":
    unittest.main()
