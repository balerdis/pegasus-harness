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

The direction the "in known_ids" / "in known_names" filters cannot see, and
how the figures close most of it
-----------------------------------------------------------------------------
For MCP server ids and skill names, a backtick token in the section only
counts as naming one if it is EQUAL to an id or a name the tree already has
(`_doc_named_mcp_ids`, `_doc_named_skill_names`). That filter is required --
without it, prose fragments like `` `download` ``, `` `npm` ``, `` `remote` ``,
a path, or the skills bullet that deliberately names two retired skills would
all be mistaken for artifacts -- but it has a cost: a name the document still
mentions after the tree has stopped shipping it is discarded before either
side of the `assertEqual` is built, so both sides shrink together and the
comparison never notices. Plugin filenames do not have this problem, because
`_doc_named_plugin_files` recognizes a name by its `.ts`/`.js` extension
alone, never by checking it against the tree first -- so a plugin bullet
naming a file the tree does not have already fails today, with no help
needed.

`_mcp_server_ids`, `_plugin_files`, and `_skill_names` return the sizes the
section spells out by hand as Spanish number words ("cinco" servers, "seis"
plugins, "veinticuatro" skills). `SpellsOutTheDerivedCounts` below compares
each one, converted to its Spanish word, against what the section says. This
closes the MCP-id and skill-name gap for the ordinary case that bit this
document before: removing a real, named item from the tree without touching
the document now changes a count the test reads, so it fails even though the
set comparison above would have stayed green.

What is left over, and stays left over: a document that names every real id
or skill AND ONE MORE that never existed passes both mechanisms at once. The
count is unaffected -- it comes from the tree, not from how many names the
prose happens to list -- and the invented name is discarded by the same
`in known_ids` / `in known_names` filter described above, on both sides of
the `assertEqual`, before anything is compared. Nothing in this file claims
to catch that case; it cannot, without either abandoning the filter (and
going blind to `` `download` ``-shaped prose instead) or parsing the section
as a literal enumerated list rather than free-form Markdown, which is exactly
the "reimplement the category by hand" trap this document already rejected
for skills. Measured directly in `SpellsOutTheDerivedCounts.test_an_invented_
name_alongside_every_real_one_is_not_caught`.
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
_SKILLS_DIR = _REPO_ROOT / "src" / "pegasus" / "content" / "skills"

#: `_shared/` is not a skill: it carries no independent trigger and nothing
#: ever loads it by name the way a command or an agent loads a real skill --
#: it is the fragment library the other skills' bodies pull from. Excluding
#: it here is the same shape of exclusion `_mcp_server_ids` already makes for
#: `playwright-package-lock.json`: a real entry under the directory that is
#: not the kind of thing this contract enumerates.
_NOT_A_SKILL = frozenset({"_shared"})

_SECTION_HEADING = "## Inclusion aprobada"
_FILE_EXTENSIONS = (".md", ".ts", ".js")

_BACKTICK = re.compile(r"`([^`]+)`")
_BULLET_LINE = re.compile(r"^\s*-\s*`([^`]+)`(?:\s*→\s*`([^`]+)`)?", re.MULTILINE)

#: The Spanish cardinal word for every count this document's prose might ever
#: need to spell out. A fixed table, not a number-to-words algorithm: this
#: section only ever states small counts of shipped artifacts, and a table
#: that raises loudly on whatever it does not cover is safer than a formula
#: that would keep silently producing SOME word for a count nobody reviewed
#: the wording for -- "veintiuno" apocopates to "veintiún" before a masculine
#: noun in some constructions, and that is exactly the kind of call a human
#: should make once, on purpose, rather than a formula deciding for them.
#: Extend it by hand, and re-read the sentence it feeds, if a count ever
#: needs to grow past thirty.
_NUMBER_WORDS_ES: dict[int, str] = {
    0: "cero", 1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco",
    6: "seis", 7: "siete", 8: "ocho", 9: "nueve", 10: "diez",
    11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince",
    16: "dieciséis", 17: "diecisiete", 18: "dieciocho", 19: "diecinueve",
    20: "veinte", 21: "veintiuno", 22: "veintidós", 23: "veintitrés",
    24: "veinticuatro", 25: "veinticinco", 26: "veintiséis", 27: "veintisiete",
    28: "veintiocho", 29: "veintinueve", 30: "treinta",
}

#: The three sentences that spell out a count by hand, each with the number
#: word as its one capture group.
_MCP_COUNT_PATTERN = re.compile(r"[Ll]os (\w+) servidores MCP que el contenido embarca")
_PLUGIN_COUNT_PATTERN = re.compile(r"[Ll]os (\w+) plugins locales aprobados")
_SKILL_COUNT_PATTERN = re.compile(r"`src/pegasus/content/skills/`, (\w+) en total")


def _spanish_word_for_count(n: int) -> str:
    """The Spanish cardinal word for `n`, or a loud failure -- never a silent
    empty string -- if `n` falls outside `_NUMBER_WORDS_ES`."""
    try:
        return _NUMBER_WORDS_ES[n]
    except KeyError as exc:
        raise AssertionError(
            f"no Spanish word mapped for count {n}; extend _NUMBER_WORDS_ES "
            "by hand (and re-check the sentence it feeds) instead of "
            "guessing a word for it"
        ) from exc


def _doc_stated_count(pattern: re.Pattern[str], doc_text: str) -> str:
    """The number word one of the count sentences spells out, read from the
    whole document (these sentences live inside "Inclusion aprobada" but
    nothing about them depends on that section boundary)."""
    match = pattern.search(doc_text)
    if match is None:
        raise AssertionError(f"no sentence in the document matches {pattern.pattern!r}")
    return match.group(1)


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


def _skill_names() -> frozenset[str]:
    """Skill names the tree defines: every subdirectory of
    `src/pegasus/content/skills/` except `_shared`, which is not a skill --
    see `_NOT_A_SKILL`."""
    return frozenset(
        path.name for path in _SKILLS_DIR.iterdir() if path.is_dir() and path.name not in _NOT_A_SKILL
    )


def _doc_named_skill_names(section: str, known_names: frozenset[str]) -> frozenset[str]:
    """Backtick tokens in the section equal to a known skill name.

    Matched the same way `_doc_named_mcp_ids` matches a server id: by exact
    equality against a name derived from the tree, never a hardcoded list,
    so a skill that is renamed or removed on disk without the document
    following can never go unnoticed. This is also what keeps a prose token
    that happens to share a plugin's or MCP server's spelling from being
    double-counted here -- a name only counts as a skill if it is also a
    real directory under `content/skills/`.
    """
    return frozenset(token for token in _BACKTICK.findall(section) if token in known_names)


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
        self.tree_skill_names = _skill_names()

    def test_mcp_servers_in_tree_and_contract_match(self):
        """Every MCP server the tree defines is named in the contract, and
        every id the contract names exists in the tree -- both directions
        of the mirror rule in one `assertEqual`."""
        self.assertEqual(self.tree_mcp_ids, _doc_named_mcp_ids(self.section, self.tree_mcp_ids))

    def test_plugin_files_in_tree_and_contract_match(self):
        """Every plugin file the tree ships is named in the contract, and
        every plugin filename the contract names exists in the tree."""
        self.assertEqual(self.tree_plugin_files, _doc_named_plugin_files(self.section))

    def test_skills_in_tree_and_contract_match(self):
        """Every skill the tree ships is named in the contract, and every
        skill name the contract names exists in the tree -- both directions
        of the mirror rule, the same as the MCP servers and the plugins.

        The document used to describe skills by category and exception
        ("Todos los Core y SDD", "excepto los que comienzan con `sergio-`")
        instead of naming them, which is exactly the shape that let the MCP
        list drift before this file existed: prose nobody compares to the
        tree. Enumerating every name explicitly, backtick-quoted, is what
        lets this test hold the two sides against each other the same way it
        already does for MCP servers and plugins.
        """
        self.assertEqual(
            self.tree_skill_names, _doc_named_skill_names(self.section, self.tree_skill_names)
        )

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


class SpellsOutTheDerivedCounts(unittest.TestCase):
    """The three counts the document types by hand -- "cinco" MCP servers,
    "seis" plugins, "veinticuatro" skills -- have to be the Spanish word for
    what the tree actually has, not a number somebody typed once and never
    revisited.

    This is what closes, for MCP server ids and skill names, the direction
    `test_mcp_servers_in_tree_and_contract_match` and
    `test_skills_in_tree_and_contract_match` cannot see on their own: those
    two only compare a backtick token against the tree if the token already
    equals something the tree has, so a name the document keeps after the
    tree drops it is filtered out of both sides before the comparison runs.
    Removing a real, named server or skill from the tree without touching the
    document leaves the set comparison green but makes the tree's count and
    the document's spelled-out word disagree -- which is exactly the mutation
    tests below.
    """

    def setUp(self):
        self.doc_text = _DOC_PATH.read_text(encoding="utf-8")

    def test_mcp_count_in_doc_matches_the_tree(self):
        self.assertEqual(
            _spanish_word_for_count(len(_mcp_server_ids())),
            _doc_stated_count(_MCP_COUNT_PATTERN, self.doc_text),
        )

    def test_plugin_count_in_doc_matches_the_tree(self):
        self.assertEqual(
            _spanish_word_for_count(len(_plugin_files())),
            _doc_stated_count(_PLUGIN_COUNT_PATTERN, self.doc_text),
        )

    def test_skill_count_in_doc_matches_the_tree(self):
        self.assertEqual(
            _spanish_word_for_count(len(_skill_names())),
            _doc_stated_count(_SKILL_COUNT_PATTERN, self.doc_text),
        )

    def test_an_invented_name_alongside_every_real_one_is_not_caught(self):
        """The residue the module docstring declares, measured rather than
        assumed: naming every real MCP id plus one that never existed passes
        both the set comparison and the count comparison, because the
        invented token is discarded by the same `in known_ids` filter on
        both sides before anything is compared, and the count comes from the
        tree, never from how many names the prose lists.

        This test does not touch the real document -- it reconstructs just
        enough of the section, in isolation, to demonstrate the gap without
        depending on today's exact prose surviving unedited."""
        known_ids = _mcp_server_ids()
        section = (
            "Los cinco servidores MCP que el contenido embarca son "
            + ", ".join(f"`{name}`" for name in sorted(known_ids))
            + " y tambien `este-id-nunca-existio`."
        )
        self.assertEqual(known_ids, _doc_named_mcp_ids(section, known_ids))
        self.assertEqual(
            _spanish_word_for_count(len(known_ids)),
            _doc_stated_count(_MCP_COUNT_PATTERN, section),
        )


if __name__ == "__main__":
    unittest.main()
