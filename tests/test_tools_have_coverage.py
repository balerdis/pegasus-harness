"""Guard: every script under `tools/` must be IMPORTED or ACTUALLY EXECUTED by at
least one test file -- not merely *named* somewhere in a test file's source text,
and not merely *passed to some arbitrary call* either.

History of this guard's false positives, weakest first:

1.  The original version checked `entry.stem in raw_test_source_text`, which a
    stray comment such as `# ver build_catalog.py` satisfies just as well as a
    real `subprocess.run([sys.executable, str(SCRIPT), ...])`.
2.  A first AST-based revision fixed (1) but replaced "anywhere in the text"
    with "anywhere inside *any* `ast.Call`" -- which is still satisfiable
    without running or importing anything at all: `print("build_catalog.py")`
    is a call, so it counted. A script could "pass" this guard by having a
    test file `print()` its filename once, with zero execution.

This version closes that hole by requiring the call to belong to one of two
recognized families, each of which corresponds to an actual way of exercising
the script:

1.  Import family -- proves the script's code was loaded, so Python at least
    parsed and executed its module-level statements:
    - A direct `import <stem>` or `from <stem> import ...` (only applicable
      to `.py` scripts, whose stem is a valid Python identifier).
    - A dynamic load via `importlib`, recognized by the *called function's*
      attribute/name being `spec_from_file_location` or `import_module`, with
      the script's name (or a tracked variable holding it, see below) among
      that call's arguments.
2.  Process-execution family -- proves the script is actually invoked as a
    subprocess: the *called function's* attribute/name is one of `run`,
    `Popen`, `check_call`, or `check_output` (matched on the attribute/name
    itself, e.g. `subprocess.run(...)`, `sp.run(...)`, or a bare `run(...)`
    after `from subprocess import run` -- not on the imported module, so this
    does not depend on how `subprocess` was imported), with the script's name
    (or a tracked variable) among that call's arguments.

For both families, "the script's name is among that call's arguments" accepts
two shapes:

- The literal filename (e.g. `"build_catalog.py"`, or `"tools/build_catalog.py"`)
  appears as a string constant anywhere inside the call's argument subtree
  (so it also matches nested shapes like a list argument, or a `str(...)`
  wrapper around a `Path`).
- A module-level or local variable is assigned an expression containing that
  literal (e.g. `SCRIPT = ROOT / "tools" / "build_catalog.py"`), and that
  *same variable name* is later read (`ast.Load`) anywhere inside the
  argument subtree of a recognized call (e.g.
  `subprocess.run([sys.executable, str(SCRIPT), ...])`). This is a
  name-based, not a data-flow, match: it does not verify the variable was not
  reassigned to something else in between.

Recognition of "belongs to a recognized call" walks the full chain of
enclosing `ast.Call` nodes (not just the nearest one), so a literal or
variable buried inside a helper call -- e.g. `str(SCRIPT)` as one element of
the list passed to `subprocess.run([...])` -- still counts: `str(...)` itself
is not a recognized call, but `subprocess.run(...)` further up the chain is.

What this deliberately does NOT recognize as coverage, by construction:

- A script name that appears only in a `# comment` or a docstring.
- A script name passed to any call outside the two recognized families --
  e.g. `print(name)`, `logging.debug(name)`, `self.assertIn(name, ...)`, or
  any other incidental call. This is the exact hole the previous revision
  left open, and closing it is the point of this version.
- A script name assigned to a variable that is only ever read outside a call
  (e.g. only compared with `==`, or only interpolated into an f-string that
  is never itself an argument to a recognized call).

Known, named limitation: this guard proves the script's name/variable reaches
the argument list of a call shaped like `subprocess.run`/`Popen`/
`check_call`/`check_output` or an `importlib` loader -- it does not execute
that call itself, so it cannot detect a call that is dead code (e.g. inside
an `if False:` branch, or a helper method that is defined but never invoked
by any actual test method). Verifying that the call *runs* during the suite
would require executing the test file under coverage instrumentation, which
this guard -- a static AST check -- does not do. Every script covered under
this repository's tests today reaches this guard via a call that a real test
method does invoke, so this residual gap is theoretical for the current
suite, but a future test file could reintroduce it by defining an unused
helper. That gap is intentionally left named here rather than silently
tolerated.

Any legitimate exclusion belongs in `NOT_A_COVERED_SCRIPT` below, with a
comment explaining why it is exempt. Nothing is ever skipped silently.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
TESTS_DIR = ROOT / "tests"

NOT_A_COVERED_SCRIPT = {
    # Bytecode cache, not a script; regenerated by the interpreter and never
    # itself a thing that could carry an untested behavior change.
    "__pycache__",
}

# Recognized by the attribute/name of the *called function*, deliberately not
# by which module it was imported from -- so `subprocess.run(...)`,
# `sp.run(...)` (module imported under an alias), and a bare `run(...)`
# after `from subprocess import run` are all recognized alike.
PROCESS_CALL_NAMES = {"run", "Popen", "check_call", "check_output"}
IMPORTLIB_CALL_NAMES = {"spec_from_file_location", "import_module"}


def _literal_matches(value: str, name: str) -> bool:
    """True if the string literal `value` identifies the script `name`, either
    standalone (e.g. "build_catalog.py") or as the final path component of
    something like "tools/build_catalog.py"."""
    if value == name:
        return True
    return value.rsplit("/", 1)[-1] == name


def _attach_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]


def _called_name(call: ast.Call) -> str | None:
    """The attribute or bare name of the function being called, e.g. `"run"`
    for both `subprocess.run(...)` and a bare `run(...)`."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_recognized_call(call: ast.Call) -> bool:
    name = _called_name(call)
    if name is None:
        return False
    return name in PROCESS_CALL_NAMES or name in IMPORTLIB_CALL_NAMES


def _is_within_recognized_call(node: ast.AST) -> bool:
    """Walk every enclosing `ast.Call` ancestor -- not just the nearest one --
    so a literal/variable nested inside a helper call (e.g. `str(SCRIPT)`
    inside `subprocess.run([...])`) is still recognized via the outer call."""
    current = getattr(node, "parent", None)
    while current is not None:
        if isinstance(current, ast.Call) and _is_recognized_call(current):
            return True
        current = getattr(current, "parent", None)
    return False


def _imports_module(tree: ast.AST, stem: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if stem in (parts[0], parts[-1]):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                parts = node.module.split(".")
                if stem in (parts[0], parts[-1]):
                    return True
    return False


def _literal_referenced_in_recognized_call(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _literal_matches(node.value, name) and _is_within_recognized_call(node):
                return True
    return False


def _assignment_contains_literal(value: ast.AST, name: str) -> bool:
    return any(
        isinstance(sub, ast.Constant) and isinstance(sub.value, str) and _literal_matches(sub.value, name)
        for sub in ast.walk(value)
    )


def _variable_chain_referenced_in_recognized_call(tree: ast.AST, name: str) -> bool:
    """Follow `SCRIPT = ROOT / "tools" / "build_catalog.py"` (module-level or
    not) -- or a name buried deeper in an expression, such as
    `arguments = [str(ROOT / "tools" / "x"), ...]` -- and check whether the
    assigned variable is later *read* inside the argument subtree of a
    recognized call, e.g. `subprocess.run([sys.executable, str(SCRIPT), ...])`.
    See the module docstring for what this heuristic does not verify.
    """
    tracked_vars: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target] if node.value is not None else []
        else:
            continue
        value = node.value
        if value is None or not _assignment_contains_literal(value, name):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                tracked_vars.add(target.id)

    if not tracked_vars:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in tracked_vars and isinstance(node.ctx, ast.Load):
            if _is_within_recognized_call(node):
                return True
    return False


def _is_covered_by(tree: ast.AST, entry: Path) -> bool:
    name, stem = entry.name, entry.stem
    if _imports_module(tree, stem):
        return True
    if _literal_referenced_in_recognized_call(tree, name):
        return True
    if _variable_chain_referenced_in_recognized_call(tree, name):
        return True
    return False


class ToolsHaveTestCoverageTest(unittest.TestCase):
    def test_every_tool_is_named_by_at_least_one_test_file(self):
        trees = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            _attach_parents(tree)
            trees.append(tree)

        uncovered = []
        for entry in sorted(TOOLS_DIR.iterdir()):
            if entry.name in NOT_A_COVERED_SCRIPT:
                continue
            if entry.is_dir():
                # A directory under tools/ that isn't the exempted cache is
                # unexpected shape for this guard; fail loudly rather than
                # silently walking into it or skipping it.
                self.fail(
                    f"tools/{entry.name} is a directory this guard does not know how to "
                    "check for coverage -- add it to NOT_A_COVERED_SCRIPT with a reason, "
                    "or extend this test to look inside it."
                )
            if not any(_is_covered_by(tree, entry) for tree in trees):
                uncovered.append(entry.name)

        self.assertEqual(
            uncovered, [],
            f"tools/ scripts with no real import or execution in any test file: "
            f"{uncovered} -- this guard accepts only: (1) a direct `import`/"
            "`from ... import` of the script, (2) an `importlib.util."
            "spec_from_file_location(...)`/`importlib.import_module(...)` call "
            "naming it, or (3) a `subprocess.run`/`Popen`/`check_call`/"
            "`check_output` call naming it (directly, or via a variable that "
            "was assigned an expression containing its filename). A mere "
            "comment, docstring mention, or an unrelated call such as "
            "`print(name)` does not count -- add a tests/test_<name>.py that "
            "imports or actually runs the script that way, or document an "
            "explicit exclusion in NOT_A_COVERED_SCRIPT with a reason.",
        )


if __name__ == "__main__":
    unittest.main()
