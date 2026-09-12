"""The mirror rule applied to `docs/contrato-inclusion-artifacts.md`.

The "Inclusion aprobada" section names, by hand, the MCP servers and the
OpenCode plugins the release embarks. Nothing derived either side from the
other, so the two drifted before: a past revision of that section named
three MCP servers while the tree already shipped five, and it omitted two
plugins for several published releases.

This module holds the two derived sets against the document's own text, in
both directions, the same way `_content_error_raise_sites` in
`tests/test_content.py` holds every `raise ContentError(...)` site against
`ContentErrorSitesTest.CASES`: derive a set from the tree (or from AST for
the raise sites), derive the matching set from what a human wrote, and
`assertEqual` the two so an addition on either side that the other did not
follow fails loudly.

Reading the document -- design decision
----------------------------------------
The section is free-form Spanish prose with names quoted in backticks. Two
extremes are both wrong: parsing the prose itself (matching on wording like
"sin prefijo" as a full sentence) breaks on any harmless rewording, while
scanning the whole document for any backtick-quoted token is too loose --
it would also pick up prose fragments never meant to name an artifact
("`download`", "`npm`", a path like "`src/pegasus/content/mcp/`").

The compromise struck here:

- Extraction is scoped to the "Inclusion aprobada" section only (between its
  `## ` heading and the next `## ` heading), so an unrelated backtick term
  elsewhere in the document (there are several, e.g. in "Rollback y
  limpieza") can never leak in.
- Within that section, a backtick-quoted token counts as naming a *file*
  only if it ends in `.md`, `.ts`, or `.js` -- the extensions the two
  directories in question actually use. This is deliberately narrow: a
  path fragment, a distribution kind (`download`, `npm`, `remote`), or a
  prose word never has one of those extensions, so it is never mistaken for
  an artifact name; a real added or removed plugin or MCP descriptor, on
  the other hand, always does, so the test cannot go blind to it.
- A backtick-quoted token counts as naming an MCP *server id* only if it is
  exactly equal to an id derived from the tree (the stem of one of
  `src/pegasus/content/mcp/*.md`) -- never hardcoded, so a sixth server
  renames or removes an id without silently going unnoticed.
- The plugin bullets are the one place the prose has a load-bearing shape
  worth reading structurally rather than by extension alone: each is a
  list line of the form `` `source-name` `` or `` `source-name` → `target-
  name` ``. The first backtick token is the tree filename; a second one,
  introduced by the arrow, is the renamed install-time name -- never a
  filename in the tree, so it is kept out of the "does this file exist"
  comparison and used only to check the renaming claim against
  `_RENAMED_ASSETS`.

This is strict enough that adding a plugin or an MCP descriptor to the tree
without touching the document flips the test red (mutations 1 and 2 below),
and lenient enough that rewording the surrounding prose, or moving a bullet,
never does.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from pegasus.adapters.opencode.adapter import _RENAMED_ASSETS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC_PATH = _REPO_ROOT / "docs" / "contrato-inclusion-artifacts.md"
_MCP_DIR = _REPO_ROOT / "src" / "pegasus" / "content" / "mcp"
_PLUGINS_DIR = _REPO_ROOT / "src" / "pegasus" / "adapters" / "opencode" / "assets" / "plugins"

_SECTION_HEADING = "## Inclusion aprobada"
_FILE_EXTENSIONS = (".md", ".ts", ".js")

_BACKTICK = re.compile(r"`([^`]+)`")
_BULLET_LINE = re.compile(r"^\s*-\s*`([^`]+)`(?:\s*→\s*`([^`]+)`)?", re.MULTILINE)


def _inclusion_section(doc_text: str) -> str:
    """The text of the "Inclusion aprobada" section, heading excluded, up to
    (excluding) the next `## ` heading or the end of the document.
    """
    start = doc_text.index(_SECTION_HEADING) + len(_SECTION_HEADING)
    rest = doc_text[start:]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _mcp_server_ids() -> frozenset[str]:
    """Server ids the tree defines: the stem of every `*.md` descriptor
    under `src/pegasus/content/mcp/` (excluding non-descriptor files such as
    `playwright-package-lock.json`)."""
    return frozenset(path.stem for path in _MCP_DIR.glob("*.md"))


def _plugin_files() -> frozenset[str]:
    """Plugin filenames the tree ships, under
    `src/pegasus/adapters/opencode/assets/plugins/`."""
    return frozenset(path.name for path in _PLUGINS_DIR.iterdir() if path.is_file())


def _doc_named_mcp_ids(section: str, known_ids: frozenset[str]) -> frozenset[str]:
    """Backtick tokens in the section equal to a known MCP server id."""
    return frozenset(token for token in _BACKTICK.findall(section) if token in known_ids)


def _doc_plugin_bullets(section: str) -> list[tuple[str, str | None]]:
    """Each `- \\`source\\`` or `- \\`source\\` -> \\`target\\`` bullet line in the
    section, as (source, target-or-None), restricted to tokens that look
    like a plugin filename (a `.ts` or `.js` extension) -- this is what
    keeps a skill bullet like `` `api-service-contract-documentation` ``,
    which has the same list shape but no such extension, out of the result.
    """
    bullets = []
    for source, target in _BULLET_LINE.findall(section):
        if source.endswith((".ts", ".js")):
            bullets.append((source, target or None))
    return bullets


def _doc_named_plugin_files(section: str) -> frozenset[str]:
    return frozenset(source for source, _ in _doc_plugin_bullets(section))


def _doc_renamed_plugin_files(section: str) -> frozenset[str]:
    """Plugin filenames the document describes as installed with a prefix
    (a `source` -> `target` bullet)."""
    return frozenset(source for source, target in _doc_plugin_bullets(section) if target)


class InclusionContractTest(unittest.TestCase):
    def setUp(self):
        self.doc_text = _DOC_PATH.read_text(encoding="utf-8")
        self.section = _inclusion_section(self.doc_text)
        self.tree_mcp_ids = _mcp_server_ids()
        self.tree_plugin_files = _plugin_files()

    def test_mcp_servers_in_tree_and_contract_match(self):
        """Every MCP server the tree defines is named in the contract, and
        every id the contract names exists in the tree -- both directions
        of the mirror rule in one `assertEqual`."""
        self.assertEqual(self.tree_mcp_ids, _doc_named_mcp_ids(self.section, self.tree_mcp_ids))

    def test_plugin_files_in_tree_and_contract_match(self):
        """Every plugin file the tree ships is named in the contract, and
        every plugin filename the contract names exists in the tree."""
        self.assertEqual(self.tree_plugin_files, _doc_named_plugin_files(self.section))

    def test_contract_renaming_claim_matches_renamed_assets(self):
        """For each plugin file, whether the contract describes it as
        installed "sin prefijo" or with a prefix (an arrow bullet) has to
        agree with whether `_RENAMED_ASSETS` actually renames it -- the
        prose and the renaming table describe the same fact and must not
        diverge."""
        doc_renamed = _doc_renamed_plugin_files(self.section)
        for plugin_file in self.tree_plugin_files:
            with self.subTest(plugin_file=plugin_file):
                described_as_renamed = plugin_file in doc_renamed
                actually_renamed = plugin_file in _RENAMED_ASSETS
                self.assertEqual(
                    described_as_renamed,
                    actually_renamed,
                    f"{plugin_file}: contract says renamed={described_as_renamed}, "
                    f"_RENAMED_ASSETS says renamed={actually_renamed}",
                )


if __name__ == "__main__":
    unittest.main()
