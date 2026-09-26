"""The FTD procedure: how an FTD runs, read only on that route.

`_shared/flow-applicability.md` decides the route; `_shared/ftd-procedure.md`
says how an FTD runs once it is chosen -- the record, where it lives, its
sections and states, the evidence rules, and how the change closes. It is read
on every FTD, so it has to stay dense and point at the owners it depends on
rather than restate them.

Where a check guards a prohibition or a precise instruction, it pins the
clause as written and closes the world around it: the pinned clause must be
there exactly once, and no other sentence may speak of the same thing. A
lexical negation check approves by shape; a pinned clause fails on any
rewording, which is the point -- a legitimate rewording is a deliberate edit of
the pin here.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from pegasus.core import content as content_module
from test_flow_routing import ROUTES_SECTION, clauses, flow_text, lead, list_items, sections
from test_readiness_authority_scope import AUTHORITY_CLAIM

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "pegasus" / "content"
SHARED = CONTENT / "skills" / "_shared"
PROCEDURE = SHARED / "ftd-procedure.md"
LADDER = SHARED / "flow-applicability.md"
PROCEDURE_NAME = PROCEDURE.name

RECORD_PATH = "`docs/ftd/<YYYY-MM-DD>-<slug>.md`"
RECORD_SECTIONS = ("Intent", "Scope", "Decisions", "Checklist", "Evidence", "Next")
NEXT_STATES = frozenset({"Open debt", "Resolved", "Accepted limitation"})

#: The pinned clauses, as written in the procedure.
CHECKBOX = "**A checkbox is not evidence.**"
NOT_RUN = "A check that could not run is recorded `not-run`, `blocked` or `failed`, never as done."
VERBATIM = "Evidence keeps every command verbatim with its exit status."
PROMOTION_RULE = (
    "Never write it as if FTD had been there from the start, and never mark a check nobody observed."
)
GRADUATION_FALLBACK = "With neither, it stays in the record, and the record says so."
WITHOUT_ENGRAM = "Without Engram, the record is the durable source: report its exact path in the conversation."
READINESS = (
    "Whoever asked for the work declares it ready, reading those observations; whoever signs something "
    "they also wrote says so, instead of presenting it as independent verification."
)
VERIFIER = "`pegasus-verifier` returns evidence, never that call."
SECRETS_RULE = (
    "Never copy a secret, or the content of a sensitive file, into Evidence: record the command and its "
    "exit status, omit the output that carries it, and say it was omitted."
)

#: A phrase that belongs to the procedure alone. Finding it anywhere else in
#: the content tree means a body swallowed what it was meant to point at.
PROCEDURE_NEEDLE = "A checkbox is not evidence"

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
#: Marking a check, by the words for it: "mark", "tick the box", "check it
#: off", "cross it off", "[x]", "flag it as done".
_MARKING = re.compile(
    r"\bmark(?:s|ed|ing)?\b|\btick(?:s|ed|ing)?\b|\bcheck(?:s|ed|ing)? (?:it |them |each |an item |items )?off\b"
    r"|\bcheck(?:s|ed|ing)? the (?:check)?box|\bcross(?:es|ed|ing)? (?:it |them )?off\b|\[x\]"
    r"|\bflag(?:s|ged|ging)? (?:it |them )?as done|\bfill(?:s|ed|ing)? in the (?:check)?box",
    re.IGNORECASE,
)
#: Secrets by the words people actually use for them. A stem list forgets a
#: word ("paste a private key or an API key" named none of the first five), so
#: it is wide on purpose, and a bare "key" counts: the procedure has no other
#: reason to say it ("topic_key" is one word and does not match).
_SECRET_STEM = re.compile(
    r"secret|sensitive|credential|passw|passphrase|token|\bkeys?\b|api[\s_-]?keys?|\.env"
    r"|\bauth\b|authentica|authoriz|bearer|cookie|certificat|\bssh\b"
    r"|oauth|\bjwt\b|\bpem\b|id_rsa|\bgpg\b|\bpgp\b|\bpii\b|personal data|confidential|private"
    r"|connection string|\bdsn\b|keychain|keyring|keystore|\bvault\b|\.netrc|\.npmrc|kubeconfig"
    r"|\bpin\b|\botp\b|one-time code|\b2fa\b|\bmfa\b|seed phrase|session[ _-]?id",
    re.IGNORECASE,
)


def procedure_text() -> str:
    return PROCEDURE.read_text(encoding="utf-8")


def unfenced(text: str) -> str:
    """The text with its fenced blocks removed: a template's headings are not
    the file's structure."""
    return _FENCE.sub("", text)


def procedure_sections() -> dict[str, str]:
    return sections(unfenced(procedure_text()))


def collapsed(text: str) -> str:
    return " ".join(text.split())


def sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_END.split(collapsed(text)) if part.strip()]


def template() -> str:
    """The fenced record template: the first fence after `## The record`.

    Found on the raw text, since the template's own `##` lines would cut a
    section split in the middle of the fence."""
    text = procedure_text()
    start = text.find("\n## The record\n")
    match = _FENCE.search(text, start) if start != -1 else None
    return match.group(1) if match else ""


def always_on_bodies() -> dict[str, str]:
    """Every body loaded into an agent's context on every turn, read from how
    the content is actually loaded: each agent's prompt and its MCP sections,
    and the system prompt and its MCP sections. Skills, commands and `_shared`
    references load on demand and are not in this set."""
    loaded = content_module.load()
    bodies = {}
    for agent in loaded.agents:
        bodies[f"agent:{agent.name}"] = agent.body
        for section in agent.mcp_sections:
            bodies[f"agent:{agent.name}:mcp:{section.name}"] = section.body
    if loaded.system_prompt is not None:
        bodies["system-prompt"] = loaded.system_prompt.body
        for section in loaded.system_prompt.mcp_sections:
            bodies[f"system-prompt:mcp:{section.name}"] = section.body
    return bodies


def content_files_containing(needle: str) -> set[Path]:
    found = set()
    for path in CONTENT.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and needle.encode("utf-8") in path.read_bytes():
            found.add(path)
    return found


class ProcedureCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PROCEDURE.is_file(), f"{PROCEDURE} does not exist")
        self.text = procedure_text()
        self.flat = collapsed(unfenced(self.text))
        self.sections = procedure_sections()


class FtdProcedureConventionsTest(ProcedureCase):
    def test_it_follows_the_house_conventions_of_shared_owners(self):
        self.assertIn("Scope", self.sections)
        self.assertIn("Authority", self.sections)

    def test_it_fails_open(self):
        self.assertIn("missing or unreadable", self.sections.get("Fail-open", ""))

    def test_it_points_at_the_owners_it_depends_on_instead_of_restating_them(self):
        authority = self.sections.get("Authority", "")
        for owner in (
            "_shared/implementation-craft.md",
            "_shared/verification-craft.md",
            "_shared/persistence-contract.md",
        ):
            with self.subTest(owner=owner):
                self.assertIn(owner, authority)
                self.assertTrue((SHARED.parent / owner).is_file(), f"{owner} does not resolve")


class RecordTemplateTest(ProcedureCase):
    def test_the_template_has_the_six_sections_in_order(self):
        headings = [line[3:].strip() for line in template().splitlines() if line.startswith("## ")]
        self.assertEqual(headings, list(RECORD_SECTIONS))

    def test_decisions_is_optional(self):
        body = sections(template()).get("Decisions", "")
        self.assertIn("optional", body.lower())

    def test_the_template_lives_under_the_record_section(self):
        self.assertIn("The record", self.sections)
        self.assertTrue(template(), "no fenced template in `## The record`")


class NextStatesTest(ProcedureCase):
    def test_next_has_exactly_the_three_states(self):
        leads = {lead(item).rstrip(".") for item in list_items(self.sections.get("The record", "")) if lead(item)}
        self.assertEqual(leads, NEXT_STATES)

    def test_each_state_says_what_it_carries(self):
        items = {lead(item): item for item in list_items(self.sections.get("The record", "")) if lead(item)}
        self.assertIn("what unblocks it", items.get("Open debt", ""))
        self.assertIn("its evidence", items.get("Resolved", ""))
        self.assertIn("nothing that unblocks it", items.get("Accepted limitation", ""))


class GraduationTest(ProcedureCase):
    def test_a_lasting_decision_graduates_and_the_record_links_there(self):
        graduation = collapsed(self.sections.get("Graduation", ""))
        self.assertIn("living document", graduation)
        self.assertIn("stable Engram topic", graduation)
        self.assertIn("the record links there", graduation)

    def test_with_neither_it_stays_in_the_record_and_says_so(self):
        self.assertEqual(self.flat.count(GRADUATION_FALLBACK), 1)


class PromotionIntoFtdTest(ProcedureCase):
    def test_the_record_starts_from_the_current_state(self):
        self.assertIn("the record starts from the current state", collapsed(self.sections.get("Promotion into FTD", "")))

    def test_it_never_marks_a_check_nobody_observed(self):
        """Pinned, and the only sentence of the file that speaks of marking."""
        self.assertEqual(self.flat.count(PROMOTION_RULE), 1)
        others = [s for s in sentences(self.flat.replace(PROMOTION_RULE, " ")) if _MARKING.search(s)]
        self.assertEqual(others, [])


class EvidenceRulesTest(ProcedureCase):
    def test_a_checkbox_is_not_evidence(self):
        self.assertEqual(self.flat.count(CHECKBOX), 1)

    def test_an_unrun_check_is_never_recorded_as_done(self):
        self.assertEqual(self.flat.count(NOT_RUN), 1)

    def test_commands_are_kept_verbatim_with_their_exit_status(self):
        self.assertEqual(self.flat.count(VERBATIM), 1)

    def test_nine_numbered_rules(self):
        body = self.sections.get("Evidence rules", "")
        numbers = [int(match.group(1)) for match in re.finditer(r"^(\d+)\. ", body, re.MULTILINE)]
        self.assertEqual(numbers, list(range(1, 10)))


class RecordLocationTest(ProcedureCase):
    def test_the_record_path(self):
        self.assertIn(RECORD_PATH, collapsed(self.sections.get("The record", "")))

    def test_the_notice_names_both_exclusions_and_comes_only_with_the_directory(self):
        notice = [s for s in sentences(self.sections.get("The record", "")) if "`.git/info/exclude`" in s]
        self.assertEqual(len(notice), 1, notice)
        self.assertIn("`.gitignore`", notice[0])
        self.assertIn("The FTD that creates `docs/ftd/` says once", notice[0])


class EngramLinkTest(ProcedureCase):
    def test_engram_gets_the_exact_record_path(self):
        engram = collapsed(self.sections.get("Engram", ""))
        self.assertIn(RECORD_PATH, engram)

    def test_without_engram_the_path_is_reported_in_the_conversation(self):
        self.assertEqual(self.flat.count(WITHOUT_ENGRAM), 1)


class ClosingTest(ProcedureCase):
    """Readiness outside SDD, option (a): whoever asked declares it from the
    record's observations; whoever signs what they wrote says so; the verifier
    returns evidence only. Never phrased as an authority."""

    def test_whoever_asked_declares_readiness_and_self_signing_is_said(self):
        self.assertEqual(self.flat.count(READINESS), 1)

    def test_the_verifier_stays_evidence_only(self):
        self.assertEqual(self.flat.count(VERIFIER), 1)

    def test_closing_claims_no_authority(self):
        self.assertNotIn("authority", self.sections.get("Closing", "").lower())
        self.assertIsNone(AUTHORITY_CLAIM.search(self.text))


class SecretsRuleTest(ProcedureCase):
    def test_evidence_never_copies_a_secret(self):
        self.assertEqual(self.flat.count(SECRETS_RULE), 1)

    def test_no_other_sentence_speaks_of_secrets(self):
        others = [s for s in sentences(self.flat.replace(SECRETS_RULE, " ")) if _SECRET_STEM.search(s)]
        self.assertEqual(others, [])


class ProcedureIsLazyTest(unittest.TestCase):
    """Closed world: the procedure is reached through one pointer only."""

    def test_the_always_on_set_is_real(self):
        """Guards the next test from passing vacuously."""
        bodies = always_on_bodies()
        for key in ("agent:pegasus-orchestrator", "agent:king-pegasus", "system-prompt"):
            with self.subTest(body=key):
                self.assertIn(key, bodies)

    def test_no_always_on_body_names_the_procedure(self):
        for key, body in always_on_bodies().items():
            with self.subTest(body=key):
                self.assertNotIn(PROCEDURE_NAME, body)

    def test_the_only_content_file_naming_it_is_the_ladder(self):
        self.assertEqual(content_files_containing(PROCEDURE_NAME), {LADDER})

    def test_the_ladder_names_it_once_at_the_ftd_exit(self):
        self.assertEqual(flow_text().count(PROCEDURE_NAME), 1)
        ftd_route = [clause for clause, section in clauses(flow_text()).items() if section == ROUTES_SECTION and lead(clause) == "FTD"]
        self.assertEqual(len(ftd_route), 1)
        self.assertIn(f"_shared/{PROCEDURE_NAME}", ftd_route[0])

    def test_a_distinctive_phrase_lives_only_in_the_procedure(self):
        self.assertEqual(content_files_containing(PROCEDURE_NEEDLE), {PROCEDURE})


if __name__ == "__main__":
    unittest.main()
