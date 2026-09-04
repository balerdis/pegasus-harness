"""The rule that keeps the abstraction from rotting.

The engine must not know which CLIs exist. This test derives the list of CLI
identifiers from the adapter directories themselves, so it keeps working as
adapters are added without anyone remembering to update it.
"""
from __future__ import annotations

import ast
import re
import tempfile
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
    a value. A range bound is the other — `0 <= mode <= 0o777` does not
    choose a permission, it refuses the values that are not one, and
    deleting that check to keep this test quiet would trade a real
    guarantee for a green light. So a literal standing in a range bound
    (`<`, `<=`, `>`, `>=`) is not an offender.

    An equality is not a bound, and this test does not treat it as one: `if
    filesystem.mode_of(path) == 0o644` chooses a permission exactly as much
    as `mode = 0o644` does, just spelled as a question. Exempting every
    literal beside a comparison operator, of any kind, would have reopened
    the leak this test exists to close the moment `mode` stopped being an
    `int` the engine could assign directly.
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

    def test_a_range_bound_is_not_flagged(self):
        offenders = _chosen_permissions(_write_probe(self, "assert 0 <= mode <= 0o777\n"))
        self.assertEqual(offenders, [])

    def test_an_equality_against_a_chosen_permission_is_flagged(self):
        """The gap a naive `it's inside a comparison` exemption would reopen:
        asking `mode_of(path) == 0o644` chooses 0o644 exactly as much as
        assigning it would, so this must still be caught."""
        offenders = _chosen_permissions(_write_probe(self, "chosen = mode_of(path) == 0o644\n"))
        self.assertEqual([text for _, text in offenders], ["0o644"])


def _write_probe(test: unittest.TestCase, source: str) -> Path:
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    probe = Path(directory.name) / "probe.py"
    probe.write_text(source, encoding="utf-8")
    return probe


_RANGE_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _chosen_permissions(path: Path) -> list[tuple[int, str]]:
    """Every octal literal in the file that names a permission it chose."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    bounds = {
        id(literal)
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare) and all(isinstance(op, _RANGE_OPS) for op in node.ops)
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


#: The three pure `tui` modules -- see each one's own module docstring for
#: the promise: given the same input they always return the same value, and
#: nothing in them can fail for lack of a terminal. `tui/app.py` is the one
#: module in this package explicitly exempted: it already owns the real
#: clock for its animation frame loop (`time.monotonic()` driving
#: `PROGRESS_TICK_MS`) and is where a download's bytes/second rate is
#: computed for exactly that reason -- see `_DownloadRateTracker`'s own
#: docstring. `tui/session.py` is impure too (it bridges to `cli`) but reads
#: no clock today, so it is left out of this rule rather than exempted from
#: it: adding it back the moment it does read one is exactly the point.
PURE_TUI_MODULE_NAMES = ("navigator.py", "view.py", "wordmark.py")


def deterministic_modules() -> list[Path]:
    """Every module this suite requires to stay clock-free: all of `core/`,
    plus the pure trio under `tui/` named above. `ports/` and `infra/` are
    deliberately absent -- a port may describe a clock-shaped capability and
    an adapter may read a real one (`infra/mcp_process_subprocess.py` times
    out a subprocess this way today, entirely legitimately), and neither is
    the boundary this test exists to guard.
    """
    core_modules = sorted(path for path in (SOURCE / "core").rglob("*.py") if "__pycache__" not in path.parts)
    pure_tui_modules = [SOURCE / "tui" / name for name in PURE_TUI_MODULE_NAMES]
    return core_modules + pure_tui_modules


#: `(owner, attribute)` pairs that read the current wall-clock or monotonic
#: time -- as opposed to `datetime.fromisoformat`, which both `navigator.py`
#: and `tui/session.py` already call today to parse a timestamp they were
#: handed, never to ask what time it is right now. That distinction is the
#: whole reason this test matches specific call shapes with `ast.Call`
#: rather than merely forbidding the word "datetime" or "time" outright --
#: the latter would also forbid a module from parsing a string one of its
#: own callers already read off a real clock somewhere else.
_CLOCK_READ_CALLS = {
    ("time", "time"),
    ("time", "monotonic"),
    ("time", "monotonic_ns"),
    ("time", "perf_counter"),
    ("time", "perf_counter_ns"),
    ("datetime", "now"),
    ("datetime", "utcnow"),
}


def _clock_reads(path: Path) -> list[tuple[int, str]]:
    """Every line in `path` that imports the `time` module outright, or calls
    one of `_CLOCK_READ_CALLS` -- an `import time`/`from time import ...` is
    flagged unconditionally, on the same reasoning `NoPermissionOctalLiteralsTest`
    already applies to a bare octal: a module with no legitimate reason to
    read a clock has no legitimate reason to import the module that would let
    it, either.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "time":
                    offenders.append((node.lineno, "import time"))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "time":
                offenders.append((node.lineno, "from time import ..."))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and (owner.id, node.func.attr) in _CLOCK_READ_CALLS:
                offenders.append((node.lineno, f"{owner.id}.{node.func.attr}(...)"))
    return sorted(offenders)


class NoClockReadsInDeterministicModulesTest(unittest.TestCase):
    """`core/` and the pure trio under `tui/` must produce the same output
    for the same input, forever -- that promise is what lets every one of
    them be proven by a table of canned answers instead of a real clock or a
    real terminal. A download's transfer rate is bytes divided by elapsed
    wall-clock time, which needs a clock read from *somewhere*, and
    `tui/app.py` is the one and only correct place for that read to live: it
    already owns a real clock for its animation frame loop, and it is the
    only layer that observes a `Progress` live off a worker thread rather
    than replaying one from a finished report. Moving that read into `core/`
    or `cli.py` would make the engine's own output depend on how much real
    time happened to pass while a caller was watching it -- breaking `--json`
    and every dry run, which read the very same `Progress` and must not
    depend on wall-clock time at all. Moving it into a pure `tui` module
    would break the same promise one layer up: `view.py` renders only
    numbers already computed, on purpose, so a screenshot test can hand it
    two different `Progress` values and expect two different outputs with no
    clock, no thread, and no sleep anywhere involved.

    This test exists so that the next person who finds a rate computed in
    the wrong place and "simplifies" it by moving the clock read closer to
    where the number is used gets a failing test instead of a silent
    architecture decay.
    """

    def test_deterministic_packages_are_scanned(self):
        self.assertTrue(deterministic_modules(), "no modules found under core/ or the pure tui trio")

    def test_no_clock_read_under_core_or_the_pure_tui_modules(self):
        offenders = [
            f"{path.relative_to(SOURCE)}:{line} reads a clock via {text}"
            for path in deterministic_modules()
            for line, text in _clock_reads(path)
        ]
        self.assertEqual(
            offenders,
            [],
            "a clock read leaked into core/ or a pure tui module:\n" + "\n".join(offenders),
        )

    def test_a_parsed_timestamp_is_not_flagged(self):
        """`datetime.fromisoformat(taken_at)` reads a string, not a clock --
        the exact case `navigator.py` and `tui/session.py` already rely on."""
        offenders = _clock_reads(_write_probe(self, "from datetime import datetime\ndatetime.fromisoformat(taken_at)\n"))
        self.assertEqual(offenders, [])

    def test_a_bare_import_of_time_is_flagged_even_if_unused_so_far(self):
        offenders = _clock_reads(_write_probe(self, "import time\n"))
        self.assertEqual(offenders, [(1, "import time")])

    def test_time_monotonic_is_flagged(self):
        offenders = _clock_reads(_write_probe(self, "import time\nstarted = time.monotonic()\n"))
        self.assertEqual([text for _, text in offenders], ["import time", "time.monotonic(...)"])

    def test_datetime_now_is_flagged(self):
        offenders = _clock_reads(_write_probe(self, "from datetime import datetime, timezone\ndatetime.now(timezone.utc)\n"))
        self.assertEqual([text for _, text in offenders], ["datetime.now(...)"])

    def test_app_py_is_not_scanned_at_all(self):
        """The one exemption this rule names explicitly -- see
        `deterministic_modules`'s own docstring for why `tui/app.py` is
        where a download's rate belongs, clock read and all."""
        self.assertNotIn(SOURCE / "tui" / "app.py", deterministic_modules())


def _owning_adapter(path: Path) -> str:
    """The adapter a file belongs to, or empty for the composition root itself."""
    relative = path.relative_to(ADAPTERS).parts
    return relative[0] if len(relative) > 1 else ""


if __name__ == "__main__":
    unittest.main()
