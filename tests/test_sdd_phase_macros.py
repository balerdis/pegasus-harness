"""The fail-closed sentence every SDD phase macro must share byte for byte.

Ten agent prompts under `content/agents/` each carry a required loading gate: a
path the phase must read before doing any work, and a sentence for what happens
when that path is missing. The lazy-load framework's "Macro Versus Reference"
table assigns fail-closed behavior to the MACRO itself, not to a shared file the
macro would have to go fetch to learn what "unreadable" means -- that would just
recreate the missing-file problem one level down. So the sentence is copied
into all ten prompts on purpose, and it is the one line in this tree that must
stay byte-identical everywhere it appears.

This test only compares bytes. It does not read the surrounding prose, judge
phrasing, or care whether the sentence sits on line 10 or line 30 -- each
macro's own identity (title, role, must-read path, result literal) is free to
differ, and does.
"""
from __future__ import annotations

import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content" / "agents"

PHASES = (
    "sdd-apply",
    "sdd-archive",
    "sdd-design",
    "sdd-explore",
    "sdd-init",
    "sdd-onboard",
    "sdd-propose",
    "sdd-spec",
    "sdd-tasks",
    "sdd-verify",
)

#: A substring unique to the fail-closed sentence, used to find it regardless of
#: which line it lands on in any given macro.
MARKER = "STOP and return `blocked` naming the unreadable path."


def fail_closed_line(document: Path) -> str:
    lines = [
        line
        for line in document.read_text(encoding="utf-8").splitlines()
        if MARKER in line
    ]
    if not lines:
        raise AssertionError(f"{document}: no fail-closed sentence found")
    if len(lines) > 1:
        raise AssertionError(f"{document}: fail-closed sentence appears more than once")
    return lines[0]


class FailClosedSentenceTest(unittest.TestCase):
    def test_every_phase_macro_exists(self):
        """Without this, a missing file would silently drop out of the comparison below."""
        missing = [phase for phase in PHASES if not (AGENTS / f"{phase}.md").is_file()]
        self.assertEqual(missing, [], f"missing phase macros: {missing}")

    def test_fail_closed_sentence_is_byte_identical_across_phases(self):
        lines = {phase: fail_closed_line(AGENTS / f"{phase}.md") for phase in PHASES}
        distinct = set(lines.values())
        self.assertEqual(
            len(distinct),
            1,
            "the fail-closed sentence diverged across phase macros:\n"
            + "\n".join(f"{phase}: {line!r}" for phase, line in lines.items()),
        )


if __name__ == "__main__":
    unittest.main()
