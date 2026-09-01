"""A convention must not teach an agent to invent the one value it cannot invent.

Engram resolves the project itself, once, from the git remote of the tree the
server was started in. `mem_save` then refuses a project it does not recognise
rather than creating it, which makes an explicit `project` argument the single
riskiest field in the call: right, it changes nothing; wrong, the write is
refused and the memory is lost with the turn.

This was not hypothetical. A phase agent working in a repo whose engram project
did not exist yet filled the argument with the project name Codebase Memory had
just handed it -- a different server, whose names are derived from the
filesystem path rather than the git remote -- and the save came back
`unknown_project`. Nothing had told it the two namespaces are not the same one,
and the convention's own templates spelled the argument as `{project}`: a
placeholder with no stated source, which is an invitation to fill it from
whatever is nearby.

What this file checks is structural, never a judgment about English: whether a
shipped convention still spells that argument as a placeholder for the agent to
resolve. Whether the surrounding prose explains the namespaces well is a
question this repository's tests do not answer.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content"

#: `project: "{anything}"` or `project="{anything}"`, the shapes an agent copies
#: out of a template verbatim. A literal name in quotes is deliberate and fine;
#: only a brace placeholder says "you work out what goes here".
TEMPLATED_PROJECT = re.compile(r"""project\s*[:=]\s*["']?\{[^}]*\}""")


class EngramProjectArgumentTest(unittest.TestCase):
    def test_no_shipped_content_templates_the_project_argument(self):
        """The whole tree, not just engram's own descriptor.

        An agent reads a prompt, an ambient section and a convention in the
        same session, and copies the call shape from whichever it saw last.
        A single surviving `project: "{project}"` anywhere is enough to teach
        the habit back.
        """
        offenders = []
        for path in sorted(CONTENT.rglob("*.md")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if TEMPLATED_PROJECT.search(line):
                    offenders.append(f"{path.relative_to(CONTENT).as_posix()}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
