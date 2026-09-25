"""Renaming a `_shared` reference leaves nothing behind on a machine that
already has the old name installed.

The `_shared` reference that decides routes was renamed to
`flow-applicability.md` (`OLD_NAME` below is the name it had). To the planner
that is one artifact retired and another created: a skill asset's `id`
carries its file name (`skill:_shared:<name>`), `planner.retirements` marks a
journal entry whose `id` the new render no longer produces as stale, and
`install` -- which `update` delegates to -- retires it. This module proves the
whole event end to end, once per adapter, against a real throwaway `$HOME`:
install the content exactly as the release before the rename shipped it, run
`update` with the real content, and look at the disk, the journal and the
report.

"The release before the rename" is derived, not frozen: the real content from
`content.load()`, with the `_shared` asset renamed back to its old name and the
agent bodies pointing at that name, injected with
`patch("pegasus.core.content.load", ...)` for the install only. A frozen copy
would drift from the product; this one differs from it by the rename alone.
"""
from __future__ import annotations

import io
import json
import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import content as content_module
from pegasus.core import journal as journal_module
from pegasus.core.types import Environment
from real_home import RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
NO_BINARY = {"PATH": ""}

SHARED = "_shared"
#: The one place the retired name is still spelled out: this module exists to
#: prove an installation that has it on disk loses it.
#: `TheRetiredNameLivesOnlyInOldNameTest` enforces that it is the only one.
OLD_NAME = "sdd-applicability.md"
NEW_NAME = "flow-applicability.md"
OLD_ID = f"skill:{SHARED}:{OLD_NAME}"

MODULE = Path(__file__).resolve()
ROOT = MODULE.parents[1]
SCANNED = (ROOT / "src", ROOT / "tests")


def _generated(path: Path) -> bool:
    """Build output an editable install or the interpreter writes, gitignored and
    never shipped: bytecode, and the `*.egg-info` metadata whose file list still
    names whatever was installed when it was last generated."""
    return any(part == "__pycache__" or part.endswith(".egg-info") for part in path.relative_to(ROOT).parts)


def occurrences_of_the_retired_name() -> list[tuple[Path, str]]:
    """`(file, stripped line)` once per occurrence of `OLD_NAME` under `src/` and
    `tests/`, read from the filesystem -- tracked, untracked, text or not."""
    needle = OLD_NAME.encode("utf-8")
    found = []
    for base in SCANNED:
        for path in sorted(base.rglob("*")):
            if not path.is_file() or _generated(path):
                continue
            data = path.read_bytes()
            if needle not in data:
                continue
            for line in data.split(b"\n"):
                found.extend([(path, line.decode("utf-8", "replace").strip())] * line.count(needle))
    return found


def content_before_the_rename() -> content_module.Content:
    """The real content, with the rename undone and nothing else changed."""
    real = content_module.load()
    shared = next(skill for skill in real.skills if skill.name == SHARED)
    new_path, old_path = PurePosixPath(NEW_NAME), PurePosixPath(OLD_NAME)
    if new_path not in {asset.relative_path for asset in shared.assets}:
        raise AssertionError(f"the real `{SHARED}` ships no {NEW_NAME}: there is no rename to migrate from")
    assets = tuple(
        replace(asset, relative_path=old_path) if asset.relative_path == new_path else asset
        for asset in shared.assets
    )
    skills = tuple(replace(skill, assets=assets) if skill.name == SHARED else skill for skill in real.skills)
    agents = tuple(
        replace(agent, body=agent.body.replace(f"{SHARED}/{NEW_NAME}", f"{SHARED}/{OLD_NAME}"))
        for agent in real.agents
    )
    return replace(real, skills=skills, agents=agents)


class RenamedSharedReferenceMigrates:
    """The four facts, for whichever adapter `CLI` names."""

    CLI: str

    def runtime(self) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=NO_BINARY
        )

    def layout(self):
        return available().get(self.CLI).layout(Environment(home=self.home))

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def journal(self):
        return journal_module.install_for(cli.journal_store(self.runtime()).load(), self.CLI)

    def setUp(self):
        super().setUp()
        before = content_before_the_rename()
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)
        self.shared = self.layout().skills_dir / SHARED
        with patch("pegasus.core.content.load", return_value=before):
            code, report = self.run_cli("install", "--cli", self.CLI)
        self.assertEqual(code, cli.OK, report)
        self.assertTrue((self.shared / OLD_NAME).is_file(), "the old release never installed the old name")
        self.assertFalse((self.shared / NEW_NAME).exists(), "the old release already had the new name")

        code, self.update_report = self.run_cli("update", "--cli", self.CLI)
        self.assertEqual(code, cli.OK, self.update_report)

    def test_the_old_file_is_gone_from_disk(self):
        self.assertFalse((self.shared / OLD_NAME).exists())

    def test_the_new_file_is_present(self):
        self.assertTrue((self.shared / NEW_NAME).is_file())

    def test_the_journal_no_longer_claims_the_old_file(self):
        install = self.journal()
        self.assertIsNotNone(install)
        self.assertNotIn(OLD_ID, {entry.id for entry in install.entries})
        self.assertFalse(any(str(entry.target).endswith(f"/{SHARED}/{OLD_NAME}") for entry in install.entries))

    def test_the_update_report_retires_the_old_file(self):
        self.assertIn(OLD_ID, {entry["id"] for entry in self.update_report["retired"]})


class TheRetiredNameLivesOnlyInOldNameTest(unittest.TestCase):
    """The rename left no stale reference behind: the old file name survives in
    exactly one place under `src/` and `tests/`, the `OLD_NAME` constant above,
    which this module needs to install it. A grep someone has to remember -- and
    that skips untracked files -- is not a check; this is."""

    def test_the_only_occurrence_is_the_old_name_constant(self):
        self.assertEqual(occurrences_of_the_retired_name(), [(MODULE, f'OLD_NAME = "{OLD_NAME}"')])


class OpencodeRenamedSharedReferenceTest(RenamedSharedReferenceMigrates, RealHomeTestCase):
    CLI = "opencode"


class ClaudecodeRenamedSharedReferenceTest(RenamedSharedReferenceMigrates, RealHomeTestCase):
    CLI = "claudecode"


if __name__ == "__main__":
    unittest.main()
