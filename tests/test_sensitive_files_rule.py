"""Closed-world pin: the sensitive-files rule `AGENTS.md` gains in 7.3.4.

Pegasus shipped no rule about secret-bearing files, so an agent asked to "look
around" read `.env`, listed `~/.ssh` or grepped a `secrets/` tree like any other
path. The person's own global rule is the model: never read, search, print,
edit, copy, stage, commit or expose the contents of those files, treat their
names as sensitive too, and the only way past is the person's explicit,
file-specific permission. The shipped system prompt is CLI-neutral and reaches
every agent and sub-agent under both CLIs, so the rule lives there.

It is a rule about FILES. A credential the person pastes into the chat is not
one: `## Credential Transport` still says to use it, and this section says so
instead of contradicting it. Editing a remote file over SSH or a privileged
file with `sudo` still needs the person's request; for one of these files it
needs their file-specific permission too.

`SENSITIVE_FILES_STEM` names the subject, never a negation of it: a file name
the rule protects, or the words "sensitive file". Sanctioning is proven by
exact paragraph membership, and the subject is held closed-world across the
whole system-prompt tree: the pinned paragraphs are the only ones allowed to
name those files.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "pegasus" / "content"
AGENTS_MD = CONTENT / "system-prompt" / "AGENTS.md"
SYSTEM_PROMPT = CONTENT / "system-prompt"

HEADING = "## Sensitive Files"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def paragraphs_of(text: str) -> list[str]:
    return [" ".join(block.split()) for block in re.split(r"\n\s*\n", text) if block.strip()]


#: The subject: the files the rule protects, by name, or the phrase "sensitive
#: file". Names the subject, never a negation of how it may be touched.
SENSITIVE_FILES_STEM = re.compile(
    r"\.env\b|\.ssh/|\.credentials/|\.aws/|hosts\.yml|\.pem\b|\.key\b|\bsecrets/|\bsensitive (?:files?|paths?)\b",
    re.IGNORECASE,
)


def paragraphs_on(text: str, stem: re.Pattern[str]) -> set[str]:
    return {paragraph for paragraph in paragraphs_of(text) if stem.search(paragraph)}


RULE_PARAGRAPH = (
    "Never read, search, print, edit, copy, stage, commit, or expose the contents of `.env`, `.env.*`, "
    "`.ssh/`, `.credentials/`, `.aws/credentials`, `.config/gh/hosts.yml`, `*.pem`, `*.key`, or any "
    "directory named `secrets/`. Their filenames and paths are sensitive too: run no broad search and no "
    "shell command that could print their contents."
)
PERMISSION_PARAGRAPH = (
    "The only way past this rule is explicit permission from the person, for that specific file. If access "
    "is genuinely required, stop and ask for it. A general task, a request to explore, or a shell with "
    "elevated rights is not that permission. Once it is granted, open the file with your file-reading or "
    "file-editing tool, never through a shell command: the confirmation for these files covers those tools, "
    "not the shell."
)
SCOPE_PARAGRAPH = (
    "This rule is about files, not about a credential the person gives you in this conversation: that one "
    "is used as Credential Transport says. Editing a remote file over SSH, or a privileged file with "
    "`sudo`, when the person asked for that change does not extend to these files: for them the permission "
    "must name the file. Every agent already receives this rule with this prompt; put it in a brief only "
    "for an agent that does not load this prompt."
)
PINNED = frozenset({HEADING, RULE_PARAGRAPH, PERMISSION_PARAGRAPH, SCOPE_PARAGRAPH})


class SensitiveFilesSectionTest(unittest.TestCase):
    def setUp(self):
        self.text = read(AGENTS_MD)
        self.assertIn(HEADING, self.text)
        self.section = self.text.split(HEADING, 1)[1].split("\n## ", 1)[0]

    def test_there_is_exactly_one_such_section(self):
        self.assertEqual(self.text.count(HEADING), 1)

    def test_the_section_is_exactly_its_heading_and_the_pinned_paragraphs(self):
        self.assertEqual(
            paragraphs_of(HEADING + self.section),
            [HEADING, RULE_PARAGRAPH, PERMISSION_PARAGRAPH, SCOPE_PARAGRAPH],
        )

    def test_the_rule_names_every_protected_file_verbatim(self):
        for name in (".env", ".env.*", ".ssh/", ".credentials/", ".aws/credentials", ".config/gh/hosts.yml", "*.pem", "*.key", "secrets/"):
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", RULE_PARAGRAPH)

    def test_the_rule_names_every_forbidden_act(self):
        for act in ("read", "search", "print", "edit", "copy", "stage", "commit", "expose"):
            with self.subTest(act=act):
                self.assertRegex(RULE_PARAGRAPH, rf"\b{act}\b")

    def test_the_only_way_past_is_file_specific_permission(self):
        self.assertIn("explicit permission from the person, for that specific file", PERMISSION_PARAGRAPH)

    def test_granted_access_goes_through_the_file_tools_never_the_shell(self):
        self.assertIn(
            "open the file with your file-reading or file-editing tool, never through a shell command",
            PERMISSION_PARAGRAPH,
        )
        self.assertIn("covers those tools, not the shell", PERMISSION_PARAGRAPH)
        self.assertIn(PERMISSION_PARAGRAPH, paragraphs_of(self.section))

    def test_it_still_lets_a_pasted_credential_be_used(self):
        self.assertIn("not about a credential the person gives you in this conversation", SCOPE_PARAGRAPH)
        self.assertIn("Credential Transport", SCOPE_PARAGRAPH)

    def test_it_covers_ssh_and_sudo_editing_and_when_a_brief_needs_it(self):
        for word in ("SSH", "`sudo`", "already receives this rule with this prompt", "only for an agent that does not load this prompt"):
            with self.subTest(word=word):
                self.assertIn(word, SCOPE_PARAGRAPH)

    def test_it_never_names_a_cli(self):
        self.assertNotIn("OpenCode", self.section)
        self.assertNotIn("Claude Code", self.section)

    def test_it_sits_before_credential_transport_and_the_delivery_guarantee(self):
        self.assertLess(self.text.index(HEADING), self.text.index("## Credential Transport"))
        self.assertLess(self.text.index(HEADING), self.text.index("## DELIVERY GUARANTEE"))

    def test_the_credential_transport_section_is_untouched(self):
        self.assertIn("never refuse to use it because it appeared in the conversation", self.text)


class SensitiveFilesIsClosedWorldTest(unittest.TestCase):
    """The pinned paragraphs are the only ones in the always-on system prompt
    that may name the protected files."""

    def test_only_the_pinned_paragraphs_touch_the_subject_anywhere_in_the_system_prompt(self):
        offenders: dict[str, set[str]] = {}
        for path in sorted(SYSTEM_PROMPT.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = read(path)
            except UnicodeDecodeError:
                continue
            extra = paragraphs_on(text, SENSITIVE_FILES_STEM) - PINNED
            if extra:
                offenders[str(path.relative_to(CONTENT))] = extra
        self.assertEqual(offenders, {})

    def test_the_pinned_rule_paragraph_is_found_by_the_stem(self):
        self.assertEqual(paragraphs_on(read(AGENTS_MD), SENSITIVE_FILES_STEM) & PINNED, {HEADING, RULE_PARAGRAPH})


if __name__ == "__main__":
    unittest.main()
