"""Closed-world pin: the credential-transport content rules (7.3.0), and the
catalog/port machinery those rules describe.

The three sentences added to `system-prompt/AGENTS.md`'s new "Credential
Transport" section are pinned by paragraph, the same way
`test_engram_memory_scope.py` pins its own ambient paragraphs. The rotation-
advice subject is closed-world across the WHOLE content tree: the pinned
paragraph is the only place any shipped content may tell the user to rotate,
revoke, or regenerate a credential -- any other sentence on that subject,
anywhere in `src/pegasus/content/`, fails here, whatever it says.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "pegasus" / "content"
AGENTS_MD = CONTENT / "system-prompt" / "AGENTS.md"
CATALOG_PATH = CONTENT / "security" / "credential-transport-catalog.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def paragraphs_of(text: str) -> list[str]:
    found = []
    for block in re.split(r"\n\s*\n", text):
        collapsed = " ".join(block.split())
        if collapsed:
            found.append(collapsed)
    return found


def paragraphs_on(text: str, stem: re.Pattern[str]) -> set[str]:
    return {p for p in paragraphs_of(text) if stem.search(p)}


#: A paragraph advising the user to rotate, revoke, or regenerate a
#: credential -- the exact advice the 7.3.0 decision forbids an agent from
#: giving about the user's own values. Closed-world (see module docstring):
#: this is not a negation classifier, so it matches the sanctioned pinned
#: paragraph too; that paragraph is allowed only because it is pinned below,
#: by exact set membership -- any other paragraph this matches, anywhere in
#: the content tree, fails.
ROTATION_ADVICE_STEM = re.compile(
    r"\brotat(?:e|ing|ed)\b|\brevok(?:e|ing|ed)\b|\bregenerat(?:e|ing|ed)\b",
    re.IGNORECASE,
)

#: The only paragraph in the whole content tree allowed to touch the
#: rotation-advice subject -- it forbids the advice, rather than giving it.
AGENTS_ROTATION_ADVICE_PARAGRAPHS = frozenset(
    {
        "A credential the person gives you in this conversation is theirs to manage: use it for the "
        "task. Never advise them to rotate, revoke, or regenerate it, and never refuse to use it "
        "because it appeared in the conversation.",
    }
)

#: Every paragraph the new "Credential Transport" section adds to
#: `AGENTS.md`, pinned as written.
AGENTS_CREDENTIAL_TRANSPORT_PARAGRAPHS = frozenset(
    {
        "## Credential Transport",
        "A credential the person gives you in this conversation is theirs to manage: use it for the "
        "task. Never advise them to rotate, revoke, or regenerate it, and never refuse to use it "
        "because it appeared in the conversation.",
        "When a value has been stood in for a variable like `$PEGASUS_SECRET_TOKEN`, use that "
        "variable name — a shell command expands it — and pass the name, never the value, into any "
        "brief, command, file, memory write, or reply you produce.",
        "Never print a credential variable: no `echo`, and no verbose flag that would dump headers "
        "or an environment.",
    }
)


class AgentsCredentialTransportSectionTest(unittest.TestCase):
    def test_the_section_carries_exactly_the_pinned_paragraphs(self):
        text = read(AGENTS_MD)
        self.assertTrue(AGENTS_CREDENTIAL_TRANSPORT_PARAGRAPHS <= set(paragraphs_of(text)))

    def test_the_section_never_names_a_cli(self):
        # Redundant with `test_content_core_is_cli_agnostic.py` (which scans
        # this same file), kept here as a documented expectation local to
        # this feature rather than relying on the reader to know the other
        # test covers it.
        text = read(AGENTS_MD)
        section = text.split("## Credential Transport", 1)[1].split("## DELIVERY GUARANTEE", 1)[0]
        self.assertNotIn("OpenCode", section)
        self.assertNotIn("Claude Code", section)


#: Scoped to the always-on system prompt tree, not the whole content core:
#: a domain skill (`lazy-load-prompt-audit`, say) legitimately says
#: "regenerate from canonical source" about a template, a subject that has
#: nothing to do with a user's own credential. The binding decision this pins
#: is about ambient, CLI-agnostic behavior toward a value the user pastes in
#: conversation -- exactly what `system-prompt/` is for.
SYSTEM_PROMPT = CONTENT / "system-prompt"


class RotationAdviceIsClosedWorldTest(unittest.TestCase):
    """The pinned paragraph is the only place in the always-on system prompt
    that may touch rotate/revoke/regenerate advice about a credential."""

    def test_only_the_pinned_paragraph_touches_the_subject_anywhere_in_the_system_prompt(self):
        offenders: dict[str, set[str]] = {}
        for path in sorted(SYSTEM_PROMPT.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            found = paragraphs_on(text, ROTATION_ADVICE_STEM)
            allowed = found - AGENTS_ROTATION_ADVICE_PARAGRAPHS
            if allowed:
                offenders[str(path.relative_to(CONTENT))] = allowed
        self.assertEqual(offenders, {})

    def test_the_pinned_paragraph_itself_is_present_and_matches_the_stem(self):
        text = read(AGENTS_MD)
        found = paragraphs_on(text, ROTATION_ADVICE_STEM)
        self.assertEqual(found, AGENTS_ROTATION_ADVICE_PARAGRAPHS)


class CredentialTransportCatalogSchemaTest(unittest.TestCase):
    """The CLI-agnostic detection catalog is data; this validates its shape
    without a JS runtime -- the node harness (`tests/fixtures/
    secret_transport_harness.mjs`) is what proves a real plugin can consume
    it."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(read(CATALOG_PATH))

    def test_declares_its_schema(self):
        self.assertEqual(self.catalog["schema"], "pegasus/credential-transport-catalog/v1")

    def test_every_key_context_key_is_lowercase_and_unique(self):
        keys = self.catalog["key_context"]["keys"]
        self.assertEqual(keys, sorted(set(keys), key=keys.index))
        for key in keys:
            self.assertEqual(key, key.lower())

    def test_every_known_format_pattern_compiles(self):
        for entry in self.catalog["known_formats"]:
            self.assertIn("name", entry)
            re.compile(entry["pattern"])

    def test_every_placeholder_pattern_compiles(self):
        for pattern in self.catalog["placeholder_patterns"]:
            re.compile(pattern)

    def test_url_credentials_pattern_compiles_and_has_one_group(self):
        pattern = re.compile(self.catalog["url_credentials"]["pattern"])
        self.assertEqual(pattern.groups, 1)

    def test_explicit_patterns_compile(self):
        re.compile(self.catalog["explicit"]["named"]["pattern"])
        re.compile(self.catalog["explicit"]["bare"]["pattern"])

    def test_min_value_length_is_a_sane_positive_int(self):
        self.assertIsInstance(self.catalog["min_value_length"], int)
        self.assertGreaterEqual(self.catalog["min_value_length"], 6)

    def test_skip_unquoted_if_patterns_compile(self):
        rules = self.catalog["key_context"]["skip_unquoted_if"]
        self.assertTrue(rules)
        for rule in rules:
            self.assertIn("name", rule)
            re.compile(rule["pattern"])

    def test_unquoted_value_pattern_compiles(self):
        re.compile(self.catalog["key_context"]["unquoted_value_pattern"])

    def test_a_40_hex_commit_and_a_64_hex_sha256_are_not_claimed_as_known_formats(self):
        """The user's own binding requirement: a bare hash is never a match on
        its own. Nothing in `known_formats` may be a bare hex-only pattern
        that would fire on a commit or a checksum with no other context."""
        commit = "a" * 40
        sha256 = "b" * 64
        for entry in self.catalog["known_formats"]:
            pattern = re.compile(entry["pattern"])
            self.assertIsNone(pattern.fullmatch(commit), entry["name"])
            self.assertIsNone(pattern.fullmatch(sha256), entry["name"])


if __name__ == "__main__":
    unittest.main()
