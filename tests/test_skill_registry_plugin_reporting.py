"""A `console.error` that is the only trace of a registry refresh failure.

`pegasus-skill-registry.ts` used to have two failure paths -- a missing
contract and a generator process that fails or times out -- and both ended in
`console.error` and nothing else. A plugin's stderr never reaches the person
running OpenCode, so the skill registry could go stale or empty in total
silence. The fix routes both paths through one reporting helper that logs
*and* raises a TUI toast (best-effort, since some clients have no TUI at all).

This file cannot check that the toast actually reaches a screen -- that needs
a running OpenCode instance, and this repository's tests never spin one up.
What it can check is the structural invariant that makes the silent-failure
regression impossible to reintroduce by accident: every `console.error` call
in the plugin lives inside the reporting helper. A future failure path added
outside that helper -- logging straight to `console.error` again -- is caught
here even though nobody wrote a test for that specific path.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PLUGIN = (
    Path(__file__).resolve().parent.parent
    / "src/pegasus/adapters/opencode/assets/plugins/pegasus-skill-registry.ts"
)

#: The helper's own name, not restated logic. If it gets renamed, this test
#: should fail loudly rather than silently stop checking anything.
HELPER_NAME = "reportFailure"


def helper_span(source: str) -> tuple[int, int]:
    """The [start, end) character range of the reporting helper's body."""
    signature = re.search(
        r"function\s+%s\s*\([^)]*\)[^{]*\{" % re.escape(HELPER_NAME), source
    )
    assert signature is not None, "the reporting helper is no longer declared as a function"
    depth = 0
    index = signature.end() - 1  # the opening brace matched by the signature
    for position in range(index, len(source)):
        char = source[position]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return signature.start(), position + 1
    raise AssertionError("the reporting helper's braces never balance")


class ConsoleErrorStaysInsideTheReportingHelperTest(unittest.TestCase):
    def setUp(self):
        self.source = PLUGIN.read_text(encoding="utf-8")
        self.start, self.end = helper_span(self.source)

    def test_the_helper_exists_and_is_non_empty(self):
        self.assertGreater(self.end, self.start)

    def test_every_console_error_call_is_inside_the_helper(self):
        offenders = [
            match.start()
            for match in re.finditer(r"console\.error\s*\(", self.source)
            if not (self.start <= match.start() < self.end)
        ]
        self.assertEqual(
            offenders,
            [],
            "found console.error outside the reporting helper -- a failure that "
            "only logs and never surfaces to the person running OpenCode",
        )

    def test_at_least_one_console_error_call_exists(self):
        # A vacuous pass (helper present, but nobody calls console.error at all
        # any more) would defeat the point: it must still be the log of record.
        self.assertRegex(self.source, r"console\.error\s*\(")

    def test_both_failure_paths_call_the_helper(self):
        calls_outside_definition = len(
            [
                match
                for match in re.finditer(r"\b%s\s*\(" % re.escape(HELPER_NAME), self.source)
                if match.start() < self.start or match.start() >= self.end
            ]
        )
        self.assertGreaterEqual(
            calls_outside_definition,
            2,
            "expected both the missing-contract path and the generator-failure "
            "path to route through the reporting helper",
        )


if __name__ == "__main__":
    unittest.main()
