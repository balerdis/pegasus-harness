"""Closed-world pin: who writes to Engram, and when a session closes.

7.1.0 changed a decision that used to read as blanket pressure -- "save NOW",
"waiting to be asked is the failure mode" -- into a conditional one: a
sub-agent (an agent launched by another agent) makes no memory write unless
its own brief asks for one, and only the agent talking with the person calls
`mem_session_summary`, only at a real close. The prose that carries this now
lives in two places every agent reads: the ambient system-prompt block
(`system-prompt/mcp/engram.md`) and the convention it points at
(`mcp/engram.md`). Both are closed-world here: the unit is the paragraph
(blank-line separated), not the sentence, because a heading glued to its own
paragraph and a fenced template inside a paragraph make sentence-splitting
unreliable over this content -- the same reason `test_orchestrator_routing.py`
warns a naive scan does not follow prose across units it was not built to
read. A rewording of a pinned paragraph, an inverted clause, or a second
paragraph that touches the same subject elsewhere in the file fails here,
whatever it says.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "pegasus" / "content"
PLUGIN = ROOT / "src/pegasus/adapters/opencode/assets/plugins/engram.ts"

AMBIENT = CONTENT / "system-prompt/mcp/engram.md"
CONVENTION = CONTENT / "mcp/engram.md"
FRAGMENT = CONTENT / "agents/mcp/engram.md"
PERSISTENCE = CONTENT / "skills/_shared/persistence-contract.md"
PHASE_COMMON = CONTENT / "skills/_shared/sdd-phase-common.md"

#: A paragraph that grants or denies a sub-agent (an agent launched by
#: another agent) standing to write memory.
SUBAGENT_WRITE_STEM = re.compile(
    r"launched by another agent|launched you|\bsub[- ]?agents?\b",
    re.IGNORECASE,
)

#: A paragraph that says when `mem_session_summary` may be called.
SESSION_CLOSE_STEM = re.compile(
    r"mem_session_summary|real close|\bnot a close\b",
    re.IGNORECASE,
)

#: A paragraph that mandates a non-SDD sub-agent write to memory before
#: returning, regardless of its brief -- the shape an independent review
#: found still shipped in the orchestrator's Non-SDD launch template
#: ("you MUST save them to engram before returning ... Do NOT return
#: without saving what you learned"). An SDD phase's own artifact mandate
#: ("you MUST call: mem_save(title: \"sdd/...")) does not use any of this
#: phrasing -- it names its artifact, never "to engram" or "before
#: returning" or "what you learned" -- so it never trips this stem.
NON_SDD_MANDATE_STEM = re.compile(
    r"must save (them |it |your \w+ )?to engram"
    r"|save (it |them |your \w+ )?before returning"
    r"|without saving what you learned"
    r"|do not return without saving",
    re.IGNORECASE,
)

#: Phrasing 7.1.0 retired: every task end read as a save trigger, and any
#: session end (a reply, a "done") read as a close. None of it may survive
#: anywhere in shipped content -- not reworded, not restated with new words.
RETIRED_PRESSURE_PHRASES = (
    "save NOW",
    "Self-check after",
    "the failure mode this protocol exists to prevent",
    'Before ending a session or saying "done"',
    'before ending a session or saying "done"',
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def paragraphs_of(text: str) -> list[str]:
    """Blank-line separated blocks of `text`, each whitespace-collapsed."""
    found = []
    for block in re.split(r"\n\s*\n", text):
        collapsed = " ".join(block.split())
        if collapsed:
            found.append(collapsed)
    return found


def paragraphs_on(text: str, stem: re.Pattern[str]) -> set[str]:
    return {p for p in paragraphs_of(text) if stem.search(p)}


def memory_instructions() -> str:
    """The `MEMORY_INSTRUCTIONS` template literal body, extracted from the
    plugin source rather than retyped -- the plugin ships this text
    unrendered, so lifting it is the only way to check it without a JS
    runtime (see `EngramPluginMemoryScopeTest` below)."""
    source = read(PLUGIN)
    match = re.search(
        r"const MEMORY_INSTRUCTIONS = `(.*?)`\n\n// ─── HTTP Client",
        source,
        re.DOTALL,
    )
    assert match is not None, "engram.ts no longer defines MEMORY_INSTRUCTIONS this way"
    return match.group(1)


#: The two paragraphs `system-prompt/mcp/engram.md` carries on each subject,
#: pinned as written. The heading-only block above the first is not itself
#: on either subject (it names the section, it does not state the rule).
AMBIENT_SUBAGENT_WRITE_PARAGRAPHS = frozenset(
    {
        "### If you were launched by another agent",
        "You make no memory writes — no `mem_save`, `mem_update`, `mem_session_summary`, nor the "
        "`mem_judge` that follows a save — unless your brief asks for one. You may still read memory: "
        "`mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping goes in your reply; "
        "whoever launched you decides what to save.",
    }
)
AMBIENT_SESSION_CLOSE_PARAGRAPHS = frozenset(
    {
        "You make no memory writes — no `mem_save`, `mem_update`, `mem_session_summary`, nor the "
        "`mem_judge` that follows a save — unless your brief asks for one. You may still read memory: "
        "`mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping goes in your reply; "
        "whoever launched you decides what to save.",
        'Only you call `mem_session_summary`, and only at a real close: the person says the session is '
        'ending, or asks for it. Finishing a task, getting a delegation back, or delivering a reply is '
        'not a close, and neither is saying "done" or "listo".',
        "If you hit a compaction, call `mem_session_summary` with the compacted summary FIRST, so what "
        "happened before it is not lost, then `mem_context`, and only then continue working.",
    }
)

#: Same two subjects, for `mcp/engram.md` (the convention).
CONVENTION_SUBAGENT_WRITE_PARAGRAPHS = frozenset(
    {
        "If you were launched by another agent, you make no memory writes — no `mem_save`, `mem_update`, "
        "`mem_session_summary`, nor the `mem_judge` that follows a save — unless your brief asks for one. "
        "You may still read: `mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping "
        "goes in your reply; whoever launched you decides what to save.",
        "NOTE: Critical engram calls (`mem_search`, `mem_save`, `mem_get_observation`) are inlined "
        "directly in each skill's SKILL.md. This section is supplementary reference — sub-agents do NOT "
        "need to read it to function.",
        "Do not skip step 1. Without it, everything done before compaction is lost from memory. A "
        "sub-agent that hits compaction follows the Memory Scope rule above instead: no "
        "`mem_session_summary` unless its brief asks for one.",
        "For an SDD phase sub-agent, the `Artifact store mode` line in your launch — `engram` or "
        "`hybrid` — is the brief asking for exactly this artifact write; it is not a license to save "
        "anything else. Ad-hoc discovery saves and `mem_session_summary` stay the launching agent's job, "
        "not yours, per the Memory Scope rule above.",
    }
)
CONVENTION_SESSION_CLOSE_PARAGRAPHS = frozenset(
    {
        "If you were launched by another agent, you make no memory writes — no `mem_save`, `mem_update`, "
        "`mem_session_summary`, nor the `mem_judge` that follows a save — unless your brief asks for one. "
        "You may still read: `mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping "
        "goes in your reply; whoever launched you decides what to save.",
        "Only the agent talking with the person calls `mem_session_summary`, and only at a real close: "
        "the person says the session is ending, or asks for it (or the equivalent in the user's "
        'language). Finishing a task, getting a delegation back, or delivering a reply is not a close, '
        'and neither is saying "done" / "listo" / "that\'s it". At a real close, call '
        "`mem_session_summary` with this shape:",
        # Gated (Blocking 2 fix): unlike the retired ungated form -- "If you
        # see a compaction message or ..." -- this now names who it is for
        # in the same paragraph the closed-world stem matches, so an
        # ungated rewrite fails the exact-set equality below.
        'If you are the agent talking with the person and you see a compaction message or "FIRST ACTION '
        'REQUIRED": 1. IMMEDIATELY call `mem_session_summary` with the compacted summary content — this '
        "persists what was done before compaction 2. Call `mem_context` to recover additional context "
        "from previous sessions 3. Only THEN continue working",
        "Do not skip step 1. Without it, everything done before compaction is lost from memory. A "
        "sub-agent that hits compaction follows the Memory Scope rule above instead: no "
        "`mem_session_summary` unless its brief asks for one.",
        "For an SDD phase sub-agent, the `Artifact store mode` line in your launch — `engram` or "
        "`hybrid` — is the brief asking for exactly this artifact write; it is not a license to save "
        "anything else. Ad-hoc discovery saves and `mem_session_summary` stay the launching agent's job, "
        "not yours, per the Memory Scope rule above.",
    }
)


class AmbientBlockScopeTest(unittest.TestCase):
    def setUp(self):
        self.text = read(AMBIENT)

    def test_subagent_write_paragraphs_are_exactly_the_pinned_one(self):
        self.assertEqual(paragraphs_on(self.text, SUBAGENT_WRITE_STEM), AMBIENT_SUBAGENT_WRITE_PARAGRAPHS)

    def test_session_close_paragraphs_are_exactly_the_pinned_three(self):
        self.assertEqual(paragraphs_on(self.text, SESSION_CLOSE_STEM), AMBIENT_SESSION_CLOSE_PARAGRAPHS)

    def test_the_section_opens_with_a_level_two_heading(self):
        # test_content.py:test_every_agent_mcp_section_opens_with_its_own_heading
        # pins this shape; guard it here too so a rewrite of this file cannot
        # silently break the composed agent prompt.
        after_marker = self.text.split("pegasus-harness:engram -->", 1)[1]
        self.assertTrue(after_marker.lstrip().startswith("## "))


class ConventionScopeTest(unittest.TestCase):
    def setUp(self):
        self.text = read(CONVENTION)

    def test_subagent_write_paragraphs_are_exactly_the_pinned_four(self):
        self.assertEqual(paragraphs_on(self.text, SUBAGENT_WRITE_STEM), CONVENTION_SUBAGENT_WRITE_PARAGRAPHS)

    def test_session_close_paragraphs_are_exactly_the_pinned_five(self):
        self.assertEqual(paragraphs_on(self.text, SESSION_CLOSE_STEM), CONVENTION_SESSION_CLOSE_PARAGRAPHS)


class EngramPluginMemoryScopeTest(unittest.TestCase):
    """The plugin injects its own copy of the protocol (`MEMORY_INSTRUCTIONS`)
    because the ambient block and the plugin are not installed under the same
    condition (the plugin ships on every OpenCode install; the ambient block
    only when `engram` is a selected MCP) -- so both copies must independently
    say the same thing on these two subjects."""

    def setUp(self):
        self.text = memory_instructions()

    def test_it_states_the_subagent_write_rule(self):
        paragraphs = paragraphs_on(self.text, SUBAGENT_WRITE_STEM)
        self.assertTrue(
            any("unless your brief asks for one" in p for p in paragraphs),
            "MEMORY_INSTRUCTIONS no longer states the sub-agent write rule",
        )

    def test_it_states_the_session_close_rule(self):
        paragraphs = paragraphs_on(self.text, SESSION_CLOSE_STEM)
        self.assertTrue(
            any("only at a real close" in p for p in paragraphs),
            "MEMORY_INSTRUCTIONS no longer states the real-close rule",
        )

    def test_it_no_longer_makes_session_close_mandatory_on_every_task_end(self):
        for phrase in RETIRED_PRESSURE_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.text)

    def test_its_after_compaction_section_is_gated_to_the_root_agent(self):
        # Blocking 2's plugin-side counterpart: the plugin's own copy of the
        # after-compaction nudge must name who it is for too, not just the
        # convention file.
        paragraphs = paragraphs_on(self.text, SESSION_CLOSE_STEM)
        self.assertTrue(
            any(
                "agent talking with the person" in p and "FIRST ACTION REQUIRED" in p
                for p in paragraphs
            ),
            "MEMORY_INSTRUCTIONS' after-compaction paragraph is not gated to the root agent",
        )


class EngramPluginFailsClosedTest(unittest.TestCase):
    """Blocking 3: `experimental.chat.system.transform`'s subagent guard used
    to read `input.sessionID && subAgentSessions.has(...)`, which fails OPEN
    when `sessionID` is absent (it is optional on this hook) -- an unknown
    session got the write-triggering protocol injected instead of being
    skipped. The fixed guard must return early on a falsy `sessionID` too."""

    def setUp(self):
        self.text = read(PLUGIN)

    def _transform_hook_body(self) -> str:
        match = re.search(
            r'"experimental\.chat\.system\.transform": async \(input, output\) => \{(.*?)\n    \},',
            self.text,
            re.DOTALL,
        )
        assert match is not None, "chat.system.transform hook not found in this shape"
        return match.group(1)

    def test_the_guard_fails_closed_on_a_missing_session_id(self):
        body = self._transform_hook_body()
        self.assertIn("if (!input.sessionID || subAgentSessions.has(input.sessionID)) return", body)

    def test_the_old_fail_open_guard_is_gone(self):
        body = self._transform_hook_body()
        self.assertNotIn("if (input.sessionID && subAgentSessions.has(input.sessionID)) return", body)


class NonSDDWriteMandateGoneTest(unittest.TestCase):
    """Blocking 1: the orchestrator's Non-SDD launch template used to read
    "you MUST save them to engram before returning ... Do NOT return without
    saving what you learned" -- a blanket mandate on the most common
    delegation path, contradicting the Memory Scope rule for every other
    sub-agent that reads it. `NON_SDD_MANDATE_STEM` is deliberately narrow:
    an SDD phase's own artifact mandate (`you MUST call: mem_save(title:
    "sdd/...")`) never says "to engram", "before returning" or "what you
    learned", so it never trips this stem -- only a re-opened blanket
    mandate does."""

    def test_no_content_file_carries_a_non_sdd_write_mandate(self):
        for path in CONTENT.rglob("*.md"):
            text = read(path)
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(paragraphs_on(text, NON_SDD_MANDATE_STEM), set())

    def test_the_plugin_source_carries_no_non_sdd_write_mandate(self):
        self.assertEqual(paragraphs_on(read(PLUGIN), NON_SDD_MANDATE_STEM), set())


class UnreadableConventionFallbackIsScopedTest(unittest.TestCase):
    """Non-blocking 4: "save anyway" / "still save rather than skipping the
    write" read, to a literal sub-agent, as "write regardless of scope" --
    exactly the license the Memory Scope rule takes away. Both fallbacks now
    name which write is already the agent's own before saying to make it
    anyway."""

    def test_the_fragment_fallback_names_the_write_that_is_already_yours(self):
        text = read(FRAGMENT)
        self.assertIn("still make whatever write is already yours", text)
        self.assertNotIn("save anyway rather than skipping the write", text)

    def test_the_ambient_fallback_names_the_write_that_is_already_yours(self):
        text = read(AMBIENT)
        self.assertIn("still make whatever write is already yours", text)
        self.assertNotIn("still save rather than skipping the write", text)


class RetiredPressurePhrasesGoneTest(unittest.TestCase):
    """None of 7.1.0's retired pressure phrasing survives anywhere shipped."""

    def test_no_shipped_content_file_carries_retired_pressure_phrasing(self):
        for path in CONTENT.rglob("*.md"):
            text = read(path)
            for phrase in RETIRED_PRESSURE_PHRASES:
                with self.subTest(path=path.relative_to(ROOT), phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_the_plugin_source_carries_no_retired_pressure_phrasing(self):
        text = read(PLUGIN)
        for phrase in RETIRED_PRESSURE_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)


class SubagentScopeReachesSharedSkillFilesTest(unittest.TestCase):
    """`persistence-contract.md` and `sdd-phase-common.md` are not closed-world
    here (both use "sub-agent" densely for unrelated things: skill loading,
    response ordering), but each MUST state that the artifact-store-mode line
    is the brief asking, and neither may re-open a blanket save mandate."""

    def test_persistence_contract_names_the_artifact_mode_as_the_brief(self):
        text = read(PERSISTENCE)
        self.assertIn(
            "IS the brief asking for that phase's own artifact write — nothing else.",
            text,
        )

    def test_phase_common_names_the_artifact_write_as_the_one_brief_ask(self):
        text = read(PHASE_COMMON)
        self.assertIn(
            "This is the one memory write your launch brief asks for, per the ambient memory-scope rule",
            text,
        )

    def test_the_fragment_names_the_launched_by_another_agent_condition(self):
        text = read(FRAGMENT)
        self.assertIn("whether you were launched by another agent", text)
        self.assertIn("you make no memory writes unless your brief asks for one", text)

    def test_the_non_sdd_template_asks_for_findings_not_a_mandate(self):
        text = read(PERSISTENCE)
        self.assertIn("Return durable findings in your reply", text)
        self.assertIn("You make no memory write; the launcher decides what to save", text)

    def test_the_who_writes_line_no_longer_says_sub_agents_always_write(self):
        text = read(PERSISTENCE)
        self.assertNotIn("Sub-agents always write:", text)
        self.assertIn(
            "SDD phases write their own artifact: the `Artifact store mode` line in their launch asks "
            "for exactly that write",
            text,
        )


if __name__ == "__main__":
    unittest.main()
