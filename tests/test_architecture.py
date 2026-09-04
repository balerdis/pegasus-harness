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


#: The documented flow is `tui -> cli -> {core, infra, ports, adapters}`, with `core/`
#: allowed to see only itself and `ports/` -- the one rule the whole hexagonal split exists
#: to keep true, because an engine that can import `infra/`, an adapter, or `cli.py` is an
#: engine that has stopped being ignorant of the runtime around it. Every other entry below
#: was not invented; it was read off the tree with `grep` before this rule was written, so
#: the rule matches what the code already does rather than a stricter shape someone wished
#: it did:
#:
#: - `ports/` imports `core` (for the types a port's signature is built from) and itself;
#:   never `infra/` or an adapter, or a port would stop being an interface a driven adapter
#:   is free to implement however it likes.
#: - `infra/` imports `core` and `ports` -- an adapter to a port implemented in terms of the
#:   core types it moves -- plus itself (`snapshot_store_file.py` reuses a constant from
#:   `journal_store_file.py`). Never `adapters/`, `tui/`, or `cli.py`.
#: - `adapters/` (the CLI adapters, e.g. `adapters/opencode/`) imports `core` and itself
#:   only. It satisfies the `CliAdapter` protocol structurally -- Python's `Protocol` needs
#:   no import from the implementer -- so it has never needed `ports/`, and this rule does
#:   not grant an allowance nothing exercises.
#: - `tui/` imports `core`, `adapters` (`tui/session.py` calls `pegasus.adapters.available()`
#:   directly to build the registry a session runs against) and, as the one named exemption
#:   below, `cli`.
#: - `cli.py` imports `core`, `ports`, `infra`, `adapters` and, as the same named exemption,
#:   `tui`.
#:
#: The exemption: this is not a strict DAG between `cli` and `tui`. `cli.py` imports
#: `pegasus.tui.app` and calls `tui_app.main()` as the interactive entry point -- the
#: installer always finishes in the TUI, never in a bare CLI prompt, which is the whole
#: point of the "instalador abre siempre la TUI" change this rule arrived after. `tui/app.py`
#: and `tui/session.py` import back into `cli` to reuse its argument parsing and execution
#: rather than duplicating it. Two modules calling into each other is not layering, so this
#: is named here rather than left implicit, and `test_the_only_named_exemption_is_the_cli_tui_entry_point`
#: below fails the moment either side's allowance grows past exactly this pair.
LAYER_ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "core": frozenset({"core", "ports"}),
    "ports": frozenset({"ports", "core"}),
    "infra": frozenset({"infra", "core", "ports"}),
    "adapters": frozenset({"adapters", "core"}),
    "tui": frozenset({"tui", "core", "adapters", "cli"}),
    "cli": frozenset({"cli", "core", "ports", "infra", "adapters", "tui"}),
}


def _layer_of_path(path: Path, source: Path) -> str | None:
    """Which policed layer `path` belongs to, or `None` for a module this rule does not
    police (the package root `__init__.py`/`__main__.py`, or `content/`, neither of which
    is part of the `tui -> cli -> {core, infra, ports, adapters}` direction this rule
    enforces)."""
    relative = path.relative_to(source).parts
    if relative == ("cli.py",):
        return "cli"
    head = relative[0]
    return head if head in LAYER_ALLOWED_IMPORTS else None


def _module_dotted_name(path: Path, source: Path) -> str:
    """The dotted module name Python itself would give `path`, e.g.
    `pegasus/core/catalog.py` -> `pegasus.core.catalog`, and a package's own `__init__.py`
    -> the package name with no trailing `.__init__`. Relative-import resolution below needs
    this to find the package a level climbs from."""
    relative = path.relative_to(source.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_import_from(path: Path, node: ast.ImportFrom, source: Path) -> str:
    """The absolute dotted module `node` names, resolving `node.level` the way Python's own
    import machinery does. `level == 0` (`from pegasus.infra import x`) is already absolute.
    A relative import climbs from the package *containing* `path` -- itself, if `path` is a
    package's own `__init__.py`, otherwise its parent -- one extra level per point beyond the
    first, exactly as `from . import x` inside a module means "this package" while
    `from .. import x` means "the package above it". Skipping this and treating every
    `ImportFrom` as already absolute is the gap named in the brief: a relative import that
    crosses a forbidden boundary would silently resolve to nothing and never be judged, which
    is exactly what `test_a_relative_import_crossing_the_boundary_is_caught` below exists to
    catch.
    """
    if node.level == 0:
        return node.module or ""
    package_parts = _module_dotted_name(path, source).split(".")
    if path.name != "__init__.py":
        package_parts = package_parts[:-1]
    if node.level > 1:
        package_parts = package_parts[: len(package_parts) - (node.level - 1)]
    if node.module:
        package_parts = package_parts + node.module.split(".")
    return ".".join(package_parts)


def _layer_of_module(dotted: str, root_package: str) -> str | None:
    """Which policed layer an absolute dotted module name (e.g. `pegasus.infra.fs_posix`)
    lives in, or `None` for a bare `import pegasus` (carries no layer -- `pegasus/__init__.py`
    is a version constant, not a dependency) or a name outside `root_package` entirely (a
    third-party or stdlib import, which this rule has no opinion about)."""
    if dotted == root_package:
        return None
    prefix = root_package + "."
    if not dotted.startswith(prefix):
        return None
    head = dotted[len(prefix):].split(".", 1)[0]
    return head if head in LAYER_ALLOWED_IMPORTS else None


def _all_modules(source: Path) -> list[Path]:
    return sorted(path for path in source.rglob("*.py") if "__pycache__" not in path.parts)


def _modules_by_layer(source: Path) -> dict[str, list[Path]]:
    layered: dict[str, list[Path]] = {name: [] for name in LAYER_ALLOWED_IMPORTS}
    for path in _all_modules(source):
        layer = _layer_of_path(path, source)
        if layer is not None:
            layered[layer].append(path)
    return layered


def _import_direction_violations(source: Path) -> list[str]:
    """Every import, anywhere under `source`, whose target layer is not in the importing
    module's own `LAYER_ALLOWED_IMPORTS` entry -- the one scan this whole rule exists to
    run."""
    root_package = source.name
    offenders: list[str] = []
    for path in _all_modules(source):
        layer = _layer_of_path(path, source)
        if layer is None:
            continue
        allowed = LAYER_ALLOWED_IMPORTS[layer]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _layer_of_module(alias.name, root_package)
                    if target is not None and target not in allowed:
                        offenders.append(
                            f"{path.relative_to(source)}:{node.lineno} {layer}/ imports "
                            f"{target}/ via 'import {alias.name}'"
                        )
            elif isinstance(node, ast.ImportFrom):
                resolved = _resolve_import_from(path, node, source)
                target = _layer_of_module(resolved, root_package)
                if target is not None and target not in allowed:
                    spelled = "from " + "." * node.level + (node.module or "") + " import ..."
                    offenders.append(
                        f"{path.relative_to(source)}:{node.lineno} {layer}/ imports "
                        f"{target}/ via {spelled!r}"
                    )
    return sorted(offenders)


def _write_scratch_pegasus(test: unittest.TestCase, files: dict[str, str]) -> Path:
    """A throwaway `pegasus/` tree under a temp directory, holding only the files a
    self-test needs. Named `pegasus` (not the real package's name by coincidence, but
    because `_layer_of_module` keys off `source.name`) so the same resolution code this
    rule runs against `src/pegasus` also runs, unmodified, against a tree small enough to
    hold one deliberate violation."""
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    root = Path(directory.name) / "pegasus"
    for relative_path, content in files.items():
        full_path = root / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
    return root


class ImportDirectionTest(unittest.TestCase):
    """The rule `NoCliNamesOutsideAdaptersTest` and `AdapterIsolationTest` both assume but
    never check: that dependencies only ever point the one documented way,
    `tui -> cli -> {core, infra, ports, adapters}`, with `core/` importing only `core` and
    `ports`. Everything else those two tests catch is a *symptom* of an engine that already
    knows too much; this is the rule that keeps the cause from happening at all. `core/`
    importing `infra/` would not mention a CLI by name and would slip straight past
    `NoCliNamesOutsideAdaptersTest`, yet it is the more fundamental break: the engine would
    now depend on a runtime -- a filesystem, a subprocess, an HTTP client -- it exists
    specifically to stay ignorant of, and every one of `core/`'s claims to be provable by a
    table of canned answers (see `NoClockReadsInDeterministicModulesTest`) would stop being
    true the moment that import could reach an adapter's side effects.

    The allowed table is `LAYER_ALLOWED_IMPORTS` above, together with the one named
    exemption in its own comment. It was read off the tree, not designed in the abstract:
    at the time this test was written, the real `src/pegasus` tree already obeyed it in
    full.
    """

    def test_every_policed_layer_has_modules_to_scan(self):
        """Without this, a typo in `LAYER_ALLOWED_IMPORTS` or `_layer_of_path` that made a
        layer scan nothing would leave `test_no_import_crosses_a_forbidden_layer_boundary`
        passing vacuously, the same failure mode `test_agnostic_packages_are_scanned` and
        `test_deterministic_packages_are_scanned` already guard elsewhere in this file."""
        layered = _modules_by_layer(SOURCE)
        for layer in LAYER_ALLOWED_IMPORTS:
            self.assertTrue(layered[layer], f"no modules found under {layer}/ -- this rule would pass vacuously")

    def test_no_import_crosses_a_forbidden_layer_boundary(self):
        offenders = _import_direction_violations(SOURCE)
        self.assertEqual(
            offenders,
            [],
            "an import crossed a forbidden hexagonal-layer boundary:\n" + "\n".join(offenders),
        )

    def test_the_only_named_exemption_is_the_cli_tui_entry_point(self):
        """Guards the one exemption this rule grants the way `test_app_py_is_not_scanned_at_all`
        guards the clock-read rule's exemption: if either side of the `cli`/`tui` pair grows a
        new allowance beyond exactly its partner, this fails and forces whoever widened it to
        say why in writing, here, rather than let the direction rule quietly get looser."""
        self.assertEqual(LAYER_ALLOWED_IMPORTS["cli"] - {"cli", "core", "ports", "infra", "adapters"}, {"tui"})
        self.assertEqual(LAYER_ALLOWED_IMPORTS["tui"] - {"tui", "core", "adapters"}, {"cli"})

    def test_core_importing_infra_is_caught(self):
        root = _write_scratch_pegasus(self, {"core/probe.py": "from pegasus.infra import fs_posix\n"})
        offenders = _import_direction_violations(root)
        self.assertEqual(
            offenders,
            ["core/probe.py:1 core/ imports infra/ via 'from pegasus.infra import ...'"],
        )

    def test_core_importing_an_adapter_is_caught(self):
        root = _write_scratch_pegasus(self, {"core/probe.py": "import pegasus.adapters.opencode\n"})
        offenders = _import_direction_violations(root)
        self.assertEqual(
            offenders,
            ["core/probe.py:1 core/ imports adapters/ via 'import pegasus.adapters.opencode'"],
        )

    def test_core_importing_cli_is_caught(self):
        root = _write_scratch_pegasus(self, {"core/probe.py": "from pegasus.cli import main\n"})
        offenders = _import_direction_violations(root)
        self.assertEqual(
            offenders,
            ["core/probe.py:1 core/ imports cli/ via 'from pegasus.cli import ...'"],
        )

    def test_a_relative_import_crossing_the_boundary_is_caught(self):
        """The case named in the brief: `from ..infra import ...` never spells `pegasus.infra`
        anywhere in the source text, so a resolver that judged the raw `node.module` string
        instead of resolving `node.level` first would let this straight through."""
        root = _write_scratch_pegasus(self, {"core/probe.py": "from ..infra import fs_posix\n"})
        offenders = _import_direction_violations(root)
        self.assertEqual(
            offenders,
            ["core/probe.py:1 core/ imports infra/ via 'from ..infra import ...'"],
        )

    def test_a_permitted_import_is_not_flagged(self):
        """The rule must stay quiet on exactly what the real tree already does, or it is too
        strict to ship: `infra/` reusing a constant from a sibling `infra/` module, and
        `core/` importing `ports/`."""
        root = _write_scratch_pegasus(
            self,
            {
                "infra/probe.py": "from pegasus.infra import journal_store_file\n",
                "core/probe.py": "from pegasus.ports import filesystem\n",
            },
        )
        self.assertEqual(_import_direction_violations(root), [])


if __name__ == "__main__":
    unittest.main()
