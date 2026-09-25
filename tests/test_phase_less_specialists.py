"""Three phase-less specialists ship beside the SDD phase agents.

`sdd-explore`, `sdd-verify` and `sdd-apply` each own a phase of a change's
lifecycle: they return a phase-shaped artifact, assume a chain around them, and
block on a required loading gate. A person who only wants one thing looked at,
one check run, or one small change made had no shipped agent to reach, so the
only way in was the whole SDD flow.

`pegasus-explorer`, `pegasus-verifier` and `pegasus-implementer` close that gap.
Each practises the same craft as its SDD namesake -- the craft files are shared,
pointed at, never restated -- and differs in exactly one thing: what it returns.
`sdd-verify` returns a verdict and is an authority; `pegasus-verifier` returns
evidence and says plainly that it declares nothing ready, which is what makes it
safe to reach from an agent that writes.

Every assertion here is about a FACT rather than a proxy for one:

- Read-only is asserted against the RENDERED permission and tool maps the
  runtime actually resolves a call against, not against a word missing from
  front matter.
- "No phase envelope" is asserted with markers proven to still exist in the SDD
  agents they were taken from, so a typo cannot make the guard vacuous.
- "Points at its craft without restating it" is asserted as a uniqueness fact
  over the whole shipped content tree plus a body-size ceiling, because a body
  can name a file and paste its contents underneath.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from pegasus import cli
from pegasus.adapters.opencode import Adapter
from pegasus.adapters.opencode import render as render_module
from pegasus.core import content as content_module
from pegasus.core.content import AgentMode
from pegasus.core.types import ConfigKeyArtifact, Environment
from test_orchestrator_routing import READINESS_STEM, RECORD_STEM, sentences_on

#: Slice (c): inside an FTD, whoever coordinates keeps the record and a
#: specialist returns evidence. Pinned as written, in `## Result identity`.
SPECIALIST_RECORD = "Inside an FTD, whoever coordinates it keeps the record; you return evidence for it."
#: The writers this applies to. `pegasus-verifier` is left out on purpose: it
#: never writes and does not change in slice (c).
RECORD_RETURNERS = ("pegasus-implementer", "pegasus-general")
#: Every sentence of each writer on the readiness subject, as written, all of
#: them from before slice (c). Closed world: nothing may join them unpinned.
SPECIALIST_READINESS_SENTENCES = {
    "pegasus-implementer": frozenset(
        {
            "Read before you write, and prove the change works before you call it done.",
            "The evidence you get back is evidence, never a sign-off: no agent you can reach has the standing to "
            "call a change ready, and neither do you.",
            "Not a narration of the diff, and not a claim about the change being ready.",
        }
    ),
    "pegasus-general": frozenset(
        {
            "This is deliberate — the ten SDD phase agents each own a phase and return a phase-shaped result "
            "(`sdd-explore` an `## Exploration: {topic}`, `sdd-verify` a `## Verification Report`), so a fan-out "
            "of phase-agent copies would produce several competing phase reports, `sdd-verify` copies included, "
            "each declaring the same change ready to archive.",
        }
    ),
}


ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "pegasus" / "content"
AGENTS = CONTENT / "agents"
SKILLS = CONTENT / "skills"

HOME = Path("/home/probe")
ENVIRONMENT = Environment(home=HOME, data_dir=HOME / ".local" / "share" / "pegasus-harness")

SPECIALISTS = ("pegasus-explorer", "pegasus-verifier", "pegasus-implementer")

#: Each specialist and the craft reference it must defer to, lazily.
CRAFT = {
    "pegasus-explorer": "_shared/exploration-craft.md",
    "pegasus-verifier": "_shared/verification-craft.md",
    "pegasus-implementer": "_shared/implementation-craft.md",
}

#: A distinctive instruction from each craft file. Restating the craft in an
#: agent body would land one of these in a second file.
CRAFT_NEEDLE = {
    "_shared/exploration-craft.md": "INVESTIGATE:",
    "_shared/verification-craft.md": "Compare specs first, design second, task completion third.",
    "_shared/implementation-craft.md": "MUST produce a **Work Unit Evidence** table",
}

#: What a phase agent carries and a phase-less specialist must not: a
#: phase-shaped result heading, a blocking loading gate, and the artifact chain
#: those two exist to serve. Held against the SDD agents below so a marker that
#: matches nothing anywhere fails loudly instead of passing silently.
PHASE_MARKERS = (
    "## Exploration: {topic}",
    "## Verification Report",
    "Required loading gate",
    "return `blocked`",
)

#: A self-declared "I am THE authority" claim, the same shape
#: `test_readiness_authority_scope.py` refuses outside its owner.
AUTHORITY_CLAIM = re.compile(r"\bsole\b.{0,60}\bauthority\b", re.IGNORECASE | re.DOTALL)

#: Word count, not line count. A line ceiling is defeated by reflow alone --
#: `tests/test_orchestrator_routing.py` proves this in this same repository:
#: hand-wrapping (or collapsing) a paragraph moves the line count without
#: moving a single word. Word count cannot be bought that way: joining or
#: splitting physical lines never changes how many whitespace-separated
#: tokens the prose holds. Front matter is not counted: it is a fixed
#: declaration block, not the lazy-load contract this budget exists to hold.
#:
#: The heaviest specialist today (`pegasus-verifier`) is 428 words. The
#: retired line ceiling carried roughly 20.6% headroom over its measured
#: baseline (6.5 / 31.5); applied to word count that same proportion gives
#: 428 * 1.206 ~= 516, rounded to 516. That is room for a body that carries
#: identity and a compact IF, not one that inlined the craft it was told to
#: point at.
BODY_WORD_CEILING = 516


def whole(name: str) -> str:
    """The shipped file, front matter included.

    For ABSENCE checks. A phase envelope or a fail-closed word is just as wrong
    in a `description:` as in the prose, so forbidding it everywhere is strictly
    stronger than forbidding it in one half.
    """
    return (AGENTS / f"{name}.md").read_text(encoding="utf-8")


def prose_of(text: str) -> str:
    """Everything after the front matter block."""
    parts = text.split("---\n", 2)
    return parts[2] if len(parts) == 3 else parts[0]


def description_of(text: str) -> str:
    """The one front-matter line a contract may legitimately also live on."""
    parts = text.split("---\n", 2)
    front = parts[1] if len(parts) == 3 else ""
    return next(
        (
            line.split(":", 1)[1].strip()
            for line in front.splitlines()
            if line.startswith("description:")
        ),
        "",
    )


def body(name: str) -> str:
    """The prose only, for PRESENCE checks.

    This helper used to return the whole file, which made every presence check
    satisfiable by the `description:` line. An adversarial review removed every
    occurrence of "what changed" from `pegasus-implementer.md`'s prose, left its
    description untouched, and `WhatEachOneReturnsTest` stayed fully green. A
    guard about what the agent is told now reads what the agent is told.
    """
    return prose_of(whole(name))


def description(name: str) -> str:
    return description_of(whole(name))


def content_documents() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted([*SKILLS.rglob("*.md"), *AGENTS.rglob("*.md")])
        if "__pycache__" not in path.parts
    }


def occurrences(needle: str) -> list[Path]:
    return [path for path, text in content_documents().items() if needle in text]


def resolve(rules: dict, name: str):
    """What the runtime lands on: the narrower rule if written, else the baseline."""
    return rules.get(name, rules["*"])


def requires_tools_of(name: str) -> set[str]:
    """The front matter list the renderer itself turns into the `permission`
    and `tools` maps `RenderedPermissionTest` reads back. Reading it here,
    rather than hard-coding a set of tool names in this module, is what makes
    the honesty guard below a derived fact instead of a second, independent
    guess that could quietly drift away from what the agent actually ships
    with."""
    front = whole(name).split("---\n", 2)[1]
    line = next(l for l in front.splitlines() if l.startswith("requires_tools:"))
    raw = line.split(":", 1)[1].strip().strip("[]")
    return {t.strip() for t in raw.split(",") if t.strip()}


def optional_tools_of(name: str) -> set[str]:
    """The sibling field to `requires_tools_of`: tools the renderer grants but
    does not mandate (`sdd-explore` is the one shipped agent that carries
    one, `optional_tools: [write]`). Absent for most agents, so the missing
    line means the empty set rather than an error -- the same "front matter
    is the source of truth, a missing field is a fact about that agent, not a
    parse failure" stance `requires_tools_of` takes."""
    front = whole(name).split("---\n", 2)[1]
    line = next((l for l in front.splitlines() if l.startswith("optional_tools:")), None)
    if line is None:
        return set()
    raw = line.split(":", 1)[1].strip().strip("[]")
    return {t.strip() for t in raw.split(",") if t.strip()}


def all_agent_names() -> list[str]:
    """Every shipped agent, read off the content tree rather than a list
    maintained in this module -- the subject set below is derived FROM this,
    not filtered down to a pair chosen in advance."""
    return sorted(path.stem for path in AGENTS.glob("*.md"))


def overclaimable_tools_of(name: str) -> set[str]:
    """The write-capable tools this agent holds (required or optional) that
    the render permission maps do NOT deny -- the gap a body may not paper
    over with a no-write claim."""
    tools = requires_tools_of(name) | optional_tools_of(name)
    return (tools & WRITE_CAPABLE_TOOLS) - PERMISSION_DENIED_WRITE_TOOLS


def no_write_claim_subjects() -> list[str]:
    """The derived subject set for `ProseDoesNotOverclaimEnforcementTest`.

    An agent belongs here when BOTH hold, both read off its own shipped
    front matter rather than named by this module:

    - it holds no `edit` and no `write` itself, so "I do not write" would be
      a true statement about its own tool set in the first place -- an agent
      that holds `edit`/`write` (`pegasus-implementer`, the SDD phase agents)
      makes no such claim to check, and this excludes it automatically; and
    - despite that, it holds a write-capable tool
      (`WRITE_CAPABLE_TOOLS`) the render permission maps do not deny
      (`PERMISSION_DENIED_WRITE_TOOLS`) -- the gap a "the permissions agree"
      claim would be lying about.

    Naming no agent here is what makes this a fact about the shipped tree
    instead of a second, independent guess this module could get out of sync
    with: add a third agent with the same shape tomorrow and it joins this
    set the moment its front matter says so, with no edit to this file.
    """
    return [
        name
        for name in all_agent_names()
        if not (requires_tools_of(name) | optional_tools_of(name)) & PERMISSION_DENIED_WRITE_TOOLS
        and overclaimable_tools_of(name)
    ]


#: How each write-capable tool may be named in prose, for the positive
#: "you must say which tool this is" check. `bash` is the only tool the
#: derived subject set currently grants ungoverned, and this codebase's own
#: prose (`pegasus-explorer.md`) calls it "the shell" as often as "bash", so
#: both count. A tool with no entry here falls back to its own front-matter
#: name -- the fallback is untested today because no shipped agent exercises
#: it, which is disclosed rather than silently assumed correct.
TOOL_MENTION_WORDS = {
    "bash": ("bash", "shell"),
}


#: Tools that can alter the tree if granted. `edit` and `write` are the ones
#: the renderer's `permission`/`tools` maps actually deny for a read-and-search
#: agent; `bash` is not denied by that mechanism at all -- a shell can run `rm`
#: or redirect output into a file just as easily as it can run `git log` -- so
#: a tool set that grants `bash` while omitting `edit`/`write` has NOT closed
#: off writing by permission, only by the tool it happened to pick.
WRITE_CAPABLE_TOOLS = {"edit", "write", "bash"}

#: Of those, the two the renderer's permission maps genuinely deny for
#: `pegasus-explorer` (see `RenderedPermissionTest`). The gap between this and
#: `WRITE_CAPABLE_TOOLS` is exactly the set a body may describe as enforced
#: without lying, and exactly the set a body may NOT extend that claim to.
PERMISSION_DENIED_WRITE_TOOLS = {"edit", "write"}

#: Phrases that describe writing as impossible without qualification -- the
#: shape of claim that was true of `pegasus-explorer` when it held only
#: `read`, `grep`, `glob`, and stops being true the moment a write-capable
#: tool the permission maps do not deny (namely `bash`) is granted alongside
#: it. Matched only when that condition actually holds, so the guard is a
#: derived fact about the shipped front matter, not a standing ban on these
#: words.
UNQUALIFIED_NO_WRITE_CLAIMS = (
    re.compile(r"you do not write", re.IGNORECASE),
    re.compile(r"\bcannot write\b", re.IGNORECASE),
    re.compile(r"permissions[^.]*agree", re.IGNORECASE | re.DOTALL),
)


class SpecialistsShipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = content_module.load()
        cls.by_name = {agent.name: agent for agent in cls.content.agents}

    def test_each_specialist_ships_as_a_subagent(self):
        for name in SPECIALISTS:
            with self.subTest(agent=name):
                self.assertIn(name, self.by_name)
                self.assertIs(self.by_name[name].mode, AgentMode.SUBAGENT)

    def test_each_specialist_declares_the_fan_out_its_work_divides_into(self):
        expected = {
            "pegasus-explorer": ("pegasus-explorer",),
            "pegasus-verifier": ("pegasus-verifier",),
            "pegasus-implementer": ("pegasus-explorer", "pegasus-verifier"),
        }
        for name, targets in expected.items():
            with self.subTest(agent=name):
                self.assertEqual(self.by_name[name].may_delegate_to, targets)


class RenderedPermissionTest(unittest.TestCase):
    """Read-only asserted where the runtime reads it, not where a human wrote it.

    Omitting `write` from front matter is not the fact under test -- the fact is
    that the rendered `permission` and `tools` maps resolve an edit to a refusal.
    `write` and `edit` fold onto one `edit` permission in this runtime, so `edit`
    is the name both must be checked under.
    """

    @classmethod
    def setUpClass(cls):
        cls.layout = Adapter().layout(ENVIRONMENT)
        cls.identity = cli.default_identity()
        cls.by_name = {agent.name: agent for agent in content_module.load().agents}

    def rendered(self, name: str) -> dict:
        artifacts = render_module.agent(self.layout, self.by_name[name])
        return [a for a in artifacts if isinstance(a, ConfigKeyArtifact)][0].value

    def test_the_explorer_and_the_verifier_cannot_write(self):
        for name in ("pegasus-explorer", "pegasus-verifier"):
            with self.subTest(agent=name):
                value = self.rendered(name)
                self.assertEqual(value["permission"]["*"], "deny")
                self.assertEqual(resolve(value["permission"], "edit"), "deny")
                self.assertIs(value["tools"]["*"], False)
                self.assertIs(resolve(value["tools"], "edit"), False)
                self.assertIs(resolve(value["tools"], "write"), False)

    def test_the_two_agents_denied_write_still_render_what_they_do_need(self):
        """Without this the assertions above would also pass for an agent that
        was denied everything, including its own trade.

        Named for what the two share -- `edit`/`write` denial -- rather than
        "read-only": the explorer also renders `bash`, granted so it can run
        the shell to investigate (`git log`, `git blame`, a check to see what
        it prints), which is not a read-only tool in general, only one this
        agent is trusted to use without altering the tree.
        """
        explorer = self.rendered("pegasus-explorer")
        self.assertEqual(resolve(explorer["permission"], "read"), "allow")
        self.assertEqual(resolve(explorer["permission"], "grep"), "allow")
        self.assertEqual(resolve(explorer["permission"], "bash"), "allow")
        verifier = self.rendered("pegasus-verifier")
        self.assertEqual(resolve(verifier["permission"], "read"), "allow")
        self.assertEqual(resolve(verifier["permission"], "bash"), "allow")

    def test_the_implementer_can_write(self):
        value = self.rendered("pegasus-implementer")
        self.assertEqual(resolve(value["permission"], "edit"), "allow")
        self.assertIs(resolve(value["tools"], "write"), True)


class ProseDoesNotOverclaimEnforcementTest(unittest.TestCase):
    """Pegasus refuses to ship a sentence that claims an enforcement it does
    not have -- a guard, or a prose claim, approving by proxy instead of by
    the thing itself is the recurring defect class this codebase keeps
    finding and fixing.

    The subject set is derived, not named: `no_write_claim_subjects()` reads
    every shipped agent's own `requires_tools`/`optional_tools` and picks out
    the ones that both (a) make no `edit`/`write` claim of their own to check
    and (b) hold a write-capable tool (`bash`) the render permission maps do
    not deny. That is `pegasus-explorer` and `pegasus-verifier` today,
    pinned by the drift guard below; `pegasus-implementer` and the SDD phase
    agents hold `edit`/`write` themselves and make no such claim to check.

    Two layers, for two different failure modes:

    - POSITIVE (the real teeth): a subject's body must NAME the tool its
      permissions do not govern -- for `bash`, the words "bash" or "shell",
      via `TOOL_MENTION_WORDS`. An adversarial review confirmed by execution
      that five independent rewordings ("There is no way for you to write to
      the tree...", "Nothing you do here can alter the repository...", and
      three more) all make the exact same false claim this guard exists to
      catch and matched NONE of the negative patterns below -- a blacklist of
      phrasings is a proxy for the true statement, not the statement itself,
      and a paraphrase escapes a proxy by construction. Requiring the tool's
      own name closes that: there is no way to satisfy "mention bash" without
      writing the word.
    - NEGATIVE (kept as a second, cheaper layer): the three literal shapes
      this codebase actually shipped and had to retract stay banned, so a
      regression back to that exact wording is caught even before a review
      would need to notice the missing tool name.

    Disclosed honestly, in the register `_wildcard_match` in
    `src/pegasus/adapters/opencode/render.py` uses for its own two
    unreproduced behaviours, rather than hidden: this does NOT prove a body
    is honest about what is and is not enforced. A body could name "bash" in
    a sentence about something unrelated to writing and still pass the
    positive check -- whether the disclosure is semantically truthful is not
    machine-checkable, only whether the tool is named where the contract
    claims "I do not write", and whether the one exact false shape already
    found is absent. Mutate `bash` out of a subject's `requires_tools` and it
    leaves the subject set entirely, both checks stop applying to it, and the
    old bare claim becomes true again -- that ceasing-to-apply is itself a
    fact about the shipped tree, not a hole in this guard.
    """

    def test_the_derived_subject_set_is_exactly_the_two_agents_with_this_shape(self):
        """Pins the criterion's output against the shipped front matter today.
        A change to any agent's tool list that alters who this guard watches
        should show up here as a failing assertion, not silently -- the same
        role `PHASE_MARKERS`' drift guard plays elsewhere in this file."""
        self.assertEqual(set(no_write_claim_subjects()), {"pegasus-explorer", "pegasus-verifier"})

    def test_a_subject_names_the_tool_its_permissions_do_not_govern(self):
        for name in no_write_claim_subjects():
            overclaimable = overclaimable_tools_of(name)
            prose = body(name).lower()
            with self.subTest(agent=name, tools=overclaimable):
                self.assertTrue(
                    any(
                        word in prose
                        for tool in overclaimable
                        for word in TOOL_MENTION_WORDS.get(tool, (tool,))
                    ),
                    f"{name}'s body makes a no-write claim without naming "
                    f"{overclaimable}, the tool its rendered permissions do not deny",
                )

    def test_a_subject_does_not_claim_permission_enforced_no_writing(self):
        for name in no_write_claim_subjects():
            overclaimable = overclaimable_tools_of(name)
            prose = body(name)
            for pattern in UNQUALIFIED_NO_WRITE_CLAIMS:
                with self.subTest(agent=name, pattern=pattern.pattern, granted=overclaimable):
                    self.assertIsNone(
                        pattern.search(prose),
                        f"{name}'s prose claims writing is permission-enforced away while "
                        f"{overclaimable} is granted and not permission-denied",
                    )


class NoPhaseEnvelopeTest(unittest.TestCase):
    def test_the_markers_still_exist_where_they_were_taken_from(self):
        """Drift guard: a marker nothing matches would make the test below
        pass while checking nothing at all."""
        sdd = "\n".join(
            (AGENTS / f"{name}.md").read_text(encoding="utf-8")
            for name in ("sdd-explore", "sdd-verify", "sdd-apply")
        )
        for marker in PHASE_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, sdd)

    def test_no_specialist_carries_a_phase_envelope(self):
        for name in SPECIALISTS:
            for marker in PHASE_MARKERS:
                with self.subTest(agent=name, marker=marker):
                    self.assertNotIn(marker, whole(name))

    def test_no_specialist_assumes_the_artifact_chain(self):
        for name in SPECIALISTS:
            with self.subTest(agent=name):
                text = whole(name)
                self.assertNotIn("persistence-contract.md", text)
                self.assertNotIn("artifact store", text.lower())


class CraftIsPointedAtNotRestatedTest(unittest.TestCase):
    def test_each_specialist_points_at_its_craft_file(self):
        for name, reference in CRAFT.items():
            with self.subTest(agent=name):
                self.assertIn(f"{{{{skills_root}}}}/{reference}", body(name))

    def test_no_craft_instruction_lives_in_two_places(self):
        for reference, needle in CRAFT_NEEDLE.items():
            with self.subTest(craft=reference):
                self.assertEqual(occurrences(needle), [SKILLS / reference])

    def test_each_specialist_body_stays_small_enough_to_be_a_pointer(self):
        """The lazy-load contract as a measurable fact: a body that inlined the
        craft it points at cannot fit in this."""
        for name in SPECIALISTS:
            with self.subTest(agent=name):
                words = len(body(name).split())
                self.assertLessEqual(words, BODY_WORD_CEILING, f"{name}.md grew past its budget")

    def test_the_craft_pointer_fails_open(self):
        """A craft reference is a lazy-loaded reference, not a required gate:
        an unreadable one costs judgement, never the assignment.

        Presence is asserted on the prose -- that is where the agent is told
        what to do -- and absence on the whole file, because a fail-closed word
        would be just as wrong on a `description:` line."""
        for name in SPECIALISTS:
            with self.subTest(agent=name):
                self.assertIn("missing or unreadable", body(name))
                self.assertNotIn("blocked", whole(name))
                self.assertNotIn("STOP", whole(name))


class WhatEachOneReturnsTest(unittest.TestCase):
    """The single contract that separates a specialist from its SDD namesake."""

    def test_the_verifier_returns_evidence_and_says_it_declares_nothing_ready(self):
        self.assertIn("I do not declare anything ready", body("pegasus-verifier"))
        self.assertIn("evidence", body("pegasus-verifier").lower())

    def test_the_verifier_makes_no_readiness_authority_claim(self):
        self.assertIsNone(AUTHORITY_CLAIM.search(whole("pegasus-verifier")))

    def test_sdd_verify_still_makes_the_claim_the_specialist_refuses(self):
        """The contrast is the point: if the claim vanished from `sdd-verify`,
        the assertion above would be measuring an empty distinction."""
        self.assertIsNotNone(AUTHORITY_CLAIM.search(whole("sdd-verify")))

    def test_the_explorer_returns_a_finding_and_the_implementer_what_changed(self):
        self.assertIn("finding", body("pegasus-explorer").lower())
        self.assertIn("what changed", body("pegasus-implementer").lower())

    def test_a_writer_leaves_the_record_to_whoever_coordinates_and_returns_evidence(self):
        for name in RECORD_RETURNERS:
            with self.subTest(agent=name):
                identity = " ".join(body(name).split("## Result identity", 1)[1].split())
                self.assertIn(SPECIALIST_RECORD, identity)
                self.assertEqual(" ".join(whole(name).split()).count(SPECIALIST_RECORD), 1)

    def test_no_other_sentence_of_a_writer_speaks_of_the_record(self):
        for name in RECORD_RETURNERS:
            with self.subTest(agent=name):
                self.assertEqual(sentences_on(whole(name), RECORD_STEM), {SPECIALIST_RECORD})

    def test_no_new_readiness_sentence_joins_a_writer(self):
        for name in RECORD_RETURNERS:
            with self.subTest(agent=name):
                self.assertEqual(sentences_on(whole(name), READINESS_STEM), set(SPECIALIST_READINESS_SENTENCES[name]))

    def test_each_contract_is_advertised_where_a_caller_reads_it_too(self):
        """The one place a contract legitimately lives twice.

        A caller picking an agent sees the `description:`, never the prose, so
        what each one returns has to be stated there as well. Asserted on
        purpose rather than inherited from a helper that happened to read the
        whole file -- that accident is what let the prose lose the contract
        while every guard stayed green."""
        for name, promise in (
            ("pegasus-explorer", "finding"),
            ("pegasus-verifier", "evidence"),
            ("pegasus-implementer", "what changed"),
        ):
            with self.subTest(agent=name):
                self.assertIn(promise, description(name).lower())


class HelperReadsTheBodyTest(unittest.TestCase):
    """The split itself, held against the leak it once had.

    `body()` returned the whole file, so every PRESENCE check in this module was
    satisfiable by a word on the `description:` line. These pin the contract so
    the split cannot quietly collapse back. Asserted against a literal fixture
    rather than a file written into the shipped content tree -- the functions
    under test take text, so there is nothing to stage on disk.
    """

    FIXTURE = (
        "---\n"
        "name: probe\n"
        "description: returns a finding about the thing\n"
        "mode: subagent\n"
        "---\n"
        "\n"
        "# Probe\n"
        "\n"
        "Prose that says something else entirely.\n"
    )

    def test_the_body_excludes_the_front_matter(self):
        text = prose_of(self.FIXTURE)
        self.assertIn("Prose that says something else entirely.", text)
        self.assertNotIn("description:", text)
        self.assertNotIn("returns a finding", text)

    def test_the_description_is_read_on_its_own(self):
        self.assertEqual(description_of(self.FIXTURE), "returns a finding about the thing")

    def test_every_shipped_specialist_actually_has_both_halves(self):
        """Guards against a parse that silently returns "" for everything."""
        for name in SPECIALISTS:
            with self.subTest(agent=name):
                self.assertTrue(body(name).strip())
                self.assertTrue(description(name).strip())
                self.assertNotIn("description:", body(name))


if __name__ == "__main__":
    unittest.main()
