"""The routing corpus, checked against the file that decides every route.

`_shared/flow-applicability.md` owns the route ladder: four routing facts, the
fixed order they are asked in, one clause per route, the ambiguous cases and
the promotions between routes. `tests/fixtures/routing-corpus/cases.json` holds
requests paraphrased from real work, each with the four facts it answers to,
the route it takes, the clause that decides it (`decided_by`, quoted
literally), and its `surface` -- a decoy recorded only to show that it never
mattered. Transition cases add `during` (the route the work was on), the
`new_fact` that promoted it, and whether the new route `requires_acceptance`.

Every citable clause is DERIVED from the file -- one list item of one of its
decision sections -- and never retyped here. A citation must also AGREE with
the case that makes it: the file marks what a clause resolves to with a bold
route word (`**FTD**`) or, for a promotion, a bold `**origin → targets**`
lead, and a case may cite a clause only when its own route -- and, for a
promotion, its `during` -- is what that clause resolves to. Editing a cited clause breaks the
cases that cite it, and that is the point: the edit carries its `decided_by`
updates in the same commit. A size rule cannot be written in the vocabulary of
the four facts, so no coherent case can cite one and coverage rejects it.

What this proves is static and nothing more: that the rules are written, that
every case is labelled consistently with them, and that every rule has a case.

Declared residue -- NOT covered here: that a model, given a real request,
answers the four facts correctly. Measuring that means running the corpus
requests by hand against a real model and comparing the facts, outside the
suite, like the release checks. The corpus carries the same note.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOW_APPLICABILITY = ROOT / "src" / "pegasus" / "content" / "skills" / "_shared" / "flow-applicability.md"
CORPUS = ROOT / "tests" / "fixtures" / "routing-corpus" / "cases.json"
EXPLORER = ROOT / "src" / "pegasus" / "content" / "agents" / "pegasus-explorer.md"

ROUTES = ("query", "l0", "ftd", "sdd")
#: The order a promotion climbs. A query sits below every change route: the
#: investigation that leaves an executable proposal is where work comes from,
#: and nothing ever promotes back into one.
CLIMB = ("query", "l0", "ftd", "sdd")
#: Where a promotion can start. Never SDD: nothing leaves SDD on its own.
DURING = ("query", "l0", "ftd")
SURFACES = ("small", "medium", "large")

CASE_KEYS = frozenset({"request", "facts", "route", "decided_by", "surface"})
TRANSITION_KEYS = frozenset({"during", "new_fact", "requires_acceptance"})
CORPUS_KEYS = frozenset({"not_covered", "cases"})

#: The sections whose list items are the citable clauses. Section NAMES are
#: the structure this suite relies on; the clauses themselves are read from
#: the file.
FACTS_SECTION = "Routing facts"
ORDER_SECTION = "Decision order"
ROUTES_SECTION = "The routes"
AMBIGUOUS_SECTION = "Ambiguous cases"
PROMOTIONS_SECTION = "Promotions"
DECISION_SECTIONS = (ORDER_SECTION, ROUTES_SECTION, AMBIGUOUS_SECTION, PROMOTIONS_SECTION)

#: Declared residue: the clauses that resolve to no route of their own, keyed
#: by their bold lead. "A bug fix with an unclear cause" orders the work --
#: investigate first -- and hands the route back to the facts once the cause is
#: confirmed, so the cases citing it can only be checked for coherence, never
#: for agreeing with a route the clause does not name.
ROUTELESS_CLAUSES = frozenset({"A bug fix with an unclear cause."})

_ITEM = re.compile(r"^(?:- |\d+\. )")
_LEADING_FACT = re.compile(r"^`([a-z_]+)`")
_FIRST_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_LEAD = re.compile(r"^\*\*([^*]+)\*\*")
_WORD = re.compile(r"[A-Za-z0-9]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_NEGATION = re.compile(r"\b(?:not|never|instead)\b")
_SDD = re.compile(r"\bSDD\b")


def flow_text() -> str:
    return FLOW_APPLICABILITY.read_text(encoding="utf-8")


def sections(text: str) -> dict[str, str]:
    """Each `## ` section's body, keyed by its heading."""
    found: dict[str, str] = {}
    name: str | None = None
    body: list[str] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            if name is not None:
                found[name] = "\n".join(body)
            name, body = line[3:].strip(), []
        elif name is not None:
            body.append(line)
    if name is not None:
        found[name] = "\n".join(body)
    return found


def list_items(body: str) -> list[str]:
    """Every top-level list item in `body`, marker stripped, whitespace collapsed.

    An item runs from its marker to the next marker or blank line; indented
    continuation lines belong to it. A paragraph after the list is not an item.
    """
    items: list[list[str]] = []
    current: list[str] | None = None
    for line in body.split("\n"):
        if _ITEM.match(line):
            current = [_ITEM.sub("", line, count=1)]
            items.append(current)
        elif current is not None and line.startswith(" ") and line.strip():
            current.append(line.strip())
        else:
            current = None
    return [" ".join(" ".join(item).split()) for item in items]


def clauses(text: str) -> dict[str, str]:
    """Every citable clause, mapped to the decision section it lives in."""
    found: dict[str, str] = {}
    by_section = sections(text)
    for section in DECISION_SECTIONS:
        for item in list_items(by_section.get(section, "")):
            found[item] = section
    return found


def declared_facts(text: str) -> list[str]:
    """The fact names `## Routing facts` declares, in the order it lists them."""
    names = []
    for item in list_items(sections(text).get(FACTS_SECTION, "")):
        match = _LEADING_FACT.match(item)
        if match:
            names.append(match.group(1))
    return names


def decision_order(text: str) -> list[tuple[str | None, str, str]]:
    """`(fact, route, clause)` per step of `## Decision order`.

    The fact is the item's leading backticked name, or None for the fallback
    step; the route is the item's first bold word, lower-cased.
    """
    steps = []
    for item in list_items(sections(text).get(ORDER_SECTION, "")):
        fact = _LEADING_FACT.match(item)
        route = _FIRST_BOLD.search(item)
        steps.append((fact.group(1) if fact else None, route.group(1).lower() if route else "", item))
    return steps


def decide(facts: dict[str, bool], order: list[tuple[str | None, str, str]]) -> tuple[str, str]:
    """`(route, deciding clause)`: the first step whose fact is true, else the fallback."""
    for fact, route, clause in order:
        if fact is None or facts.get(fact):
            return route, clause
    raise AssertionError("the decision order has no fallback step")


def sdd_clauses(text: str) -> list[str]:
    """The clauses that send work to SDD: the SDD route and every SDD step of the order."""
    routes = [item for item in list_items(sections(text).get(ROUTES_SECTION, "")) if item.startswith("**SDD**")]
    steps = [clause for _, route, clause in decision_order(text) if route == "sdd"]
    return routes + steps


def lead(clause: str) -> str:
    """The clause's leading bold span, or "" when it does not open with one."""
    match = _LEAD.match(clause)
    return match.group(1) if match else ""


def bold_routes(clause: str) -> set[str]:
    """The routes a clause resolves to: its bold spans that are exactly a route word."""
    return {span.lower() for span in _FIRST_BOLD.findall(clause) if span.lower() in ROUTES}


def promotion(clause: str) -> tuple[str, set[str]] | None:
    """`(origin, targets)` from a `**origin → targets**` lead, or None."""
    if "→" not in lead(clause):
        return None
    origin, targets = lead(clause).split("→", 1)
    return origin.strip().lower(), {word.lower() for word in _WORD.findall(targets) if word.lower() in ROUTES}


def sdd_sentences(text: str) -> list[str]:
    """Every sentence, in any decision section, that sends work to SDD -- with its subject.

    - A step of the decision order whose route is SDD: the whole step.
    - The SDD route's clause: all of it.
    - A promotion whose targets include SDD: the sentence its lead opens.
    - Anywhere else: a sentence that names SDD without negating it ("not",
      "never", "instead"), prefixed by the item's lead when that lead is a
      sentence of its own -- an ambiguous case names its subject there, and
      the sentence that resolves it to SDD only says "it".

    The negation check is lexical: a sentence that sends work to SDD while
    negating something else ("SDD, never L0") is skipped. That is a declared
    blind spot, not a guarantee.
    """
    found = []
    by_section = sections(text)
    for section in DECISION_SECTIONS:
        for item in list_items(by_section.get(section, "")):
            head = lead(item)
            parsed = promotion(item)
            if section == ORDER_SECTION:
                if "sdd" in bold_routes(item):
                    found.append(item)
                continue
            if head == "SDD":
                found.append(item)
                continue
            rest = item[len(head) + 4 :].strip() if head else item
            subject = f"{head} " if head and parsed is None and head.lower() not in ROUTES else ""
            for index, sentence in enumerate(part for part in _SENTENCE_END.split(rest) if part):
                if parsed is not None and index == 0 and "sdd" in parsed[1]:
                    found.append(f"**{head}** {sentence}")
                elif _SDD.search(sentence) and not _NEGATION.search(sentence):
                    found.append(subject + sentence)
    return found


#: A routing-fact name as prose writes it: a backticked snake_case identifier.
_FACT_NAME = re.compile(r"`([a-z]+(?:_[a-z]+)+)`")
#: The one clause in the explorer's whole file allowed to mention choosing a
#: route, pinned as written. Closed world: every OTHER sentence of the file
#: must not mention route choice at all, in any voice or form.
FORBIDDING_CLAUSE = "never choose the route yourself: that decision is the caller's"
#: The one clause allowed to speak of returning the facts, pinned the same way.
RETURNING_CLAUSE = "When the brief asks for routing facts, return each one"

#: A route, as a noun or a verb ("route", "routes", "routed", "routing").
_ROUTE_STEM = re.compile(r"\brout(?:e|es|ed|ing)\b", re.IGNORECASE)
#: Choosing, matched by stem so no inflection or voice slips past: "chosen",
#: "chose", "picked", "decides", "decision", "selection", "elected".
_CHOICE_STEM = re.compile(r"choos|chose|pick|decid|decis|select|elect", re.IGNORECASE)
#: Routing used as a verb on the work itself: "route it", "route the request".
_ROUTE_AS_VERB = re.compile(
    r"\brout(?:e|es|ed|ing)\s+(?:it|them|this|that|the\s+(?:request|work|brief|change))\b", re.IGNORECASE
)
_FACT_STEM = re.compile(r"\bfacts?\b", re.IGNORECASE)
#: Anything done with the facts, returning or withholding them, by stem.
_HANDLING_STEM = re.compile(r"return|report|give|hand|send|withh|omit|skip|hold|keep|leav|hid|conceal|drop", re.IGNORECASE)


def explorer_text() -> str:
    """The explorer's whole file, whitespace collapsed -- front matter included."""
    return " ".join(EXPLORER.read_text(encoding="utf-8").split())


def split_around(text: str, clause: str) -> tuple[list[str], list[str]]:
    """`(host remainders, other sentences)`: the sentence holding the pinned
    `clause`, with the clause cut out, and every other sentence of `text`."""
    hosts, others = [], []
    for sentence in (part for part in _SENTENCE_END.split(text) if part.strip()):
        (hosts if clause in sentence else others).append(sentence.replace(clause, " "))
    return hosts, others


def corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def cases() -> list[dict]:
    return corpus()["cases"]


def is_transition(case: dict) -> bool:
    return "during" in case


class FlowApplicabilityCase(unittest.TestCase):
    """Loads the decider once per test, failing (not erroring) when it is absent."""

    def setUp(self):
        self.assertTrue(FLOW_APPLICABILITY.is_file(), f"{FLOW_APPLICABILITY} does not exist")
        self.text = flow_text()
        self.clauses = clauses(self.text)
        self.order = decision_order(self.text)
        self.facts = declared_facts(self.text)
        self.cases = cases()


class CorpusSchemaTest(unittest.TestCase):
    """The corpus's shape, independent of the file it cites."""

    def setUp(self):
        self.corpus = corpus()
        self.cases = self.corpus["cases"]

    def test_the_corpus_declares_what_it_does_not_cover(self):
        self.assertEqual(set(self.corpus), CORPUS_KEYS)
        self.assertIn("does not prove", self.corpus["not_covered"])

    def test_the_corpus_is_not_empty(self):
        self.assertGreaterEqual(len(self.cases), 30)

    def test_every_case_has_exactly_the_case_keys_or_the_transition_keys_too(self):
        for index, case in enumerate(self.cases):
            with self.subTest(case=index):
                self.assertIn(set(case), (CASE_KEYS, CASE_KEYS | TRANSITION_KEYS))

    def test_no_case_carries_a_provenance_field(self):
        """Where a case came from never ships: any key outside the schema is
        refused, whatever it is called."""
        allowed = CASE_KEYS | TRANSITION_KEYS
        for index, case in enumerate(self.cases):
            with self.subTest(case=index):
                self.assertEqual(set(case) - allowed, set(), "a key outside the schema")

    def test_values_are_in_their_vocabularies(self):
        fact_names = set(self.cases[0]["facts"])
        for index, case in enumerate(self.cases):
            with self.subTest(case=index):
                self.assertIsInstance(case["request"], str)
                self.assertTrue(case["request"].strip())
                self.assertIsInstance(case["decided_by"], str)
                self.assertTrue(case["decided_by"].strip())
                self.assertIn(case["route"], ROUTES)
                self.assertIn(case["surface"], SURFACES)
                self.assertEqual(set(case["facts"]), fact_names)
                self.assertTrue(all(isinstance(value, bool) for value in case["facts"].values()))
                if is_transition(case):
                    # A query, L0 or FTD -- never SDD: nothing leaves SDD on its own.
                    self.assertIn(case["during"], DURING)
                    self.assertNotEqual(case["during"], "sdd")
                    self.assertIn(case["new_fact"], fact_names)
                    self.assertIsInstance(case["requires_acceptance"], bool)

    def test_requests_are_unique(self):
        requests = [case["request"] for case in self.cases]
        self.assertEqual(len(requests), len(set(requests)))


class CoherenceTest(FlowApplicabilityCase):
    def test_every_case_is_routed_by_the_decision_order(self):
        for case in self.cases:
            with self.subTest(request=case["request"]):
                route, _ = decide(case["facts"], self.order)
                self.assertEqual(route, case["route"])

    def test_a_case_citing_a_step_of_the_order_is_decided_at_that_step(self):
        steps = {clause for _, _, clause in self.order}
        for case in self.cases:
            if case["decided_by"] in steps:
                with self.subTest(request=case["request"]):
                    _, clause = decide(case["facts"], self.order)
                    self.assertEqual(clause, case["decided_by"])


class TraceabilityTest(FlowApplicabilityCase):
    def test_every_decision_section_exists_and_carries_clauses(self):
        by_section = sections(self.text)
        for section in DECISION_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, by_section)
                self.assertTrue(list_items(by_section[section]))

    def test_every_case_cites_a_clause_that_exists_literally(self):
        for case in self.cases:
            with self.subTest(request=case["request"]):
                self.assertIn(case["decided_by"], self.clauses)

    def test_every_clause_resolves_to_a_route_except_the_declared_residue(self):
        for clause, section in self.clauses.items():
            with self.subTest(section=section, clause=clause):
                if section == PROMOTIONS_SECTION:
                    parsed = promotion(clause)
                    self.assertIsNotNone(parsed, "a promotion opens with a bold `origin → targets`")
                    origin, targets = parsed
                    self.assertIn(origin, DURING)
                    self.assertTrue(targets)
                    self.assertTrue(all(CLIMB.index(target) > CLIMB.index(origin) for target in targets))
                elif lead(clause) in ROUTELESS_CLAUSES:
                    self.assertEqual(bold_routes(clause), set(), "declared routeless, yet it names a route")
                else:
                    self.assertTrue(bold_routes(clause), "no bold route word says what this clause resolves to")

    def test_the_declared_residue_exists(self):
        """A residue entry whose clause is gone would silently excuse nothing."""
        leads = {lead(clause) for clause in self.clauses}
        self.assertLessEqual(ROUTELESS_CLAUSES, leads)

    def test_a_citation_names_the_citing_cases_route(self):
        """Decision order, routes and ambiguous cases: the case's route must be
        one the cited clause resolves to."""
        for case in self.cases:
            section = self.clauses.get(case["decided_by"])
            if section in (ORDER_SECTION, ROUTES_SECTION, AMBIGUOUS_SECTION) and lead(
                case["decided_by"]
            ) not in ROUTELESS_CLAUSES:
                with self.subTest(request=case["request"]):
                    self.assertIn(case["route"], bold_routes(case["decided_by"]))

    def test_a_promotion_is_cited_only_by_a_transition_from_its_origin_to_one_of_its_targets(self):
        for case in self.cases:
            if self.clauses.get(case["decided_by"]) == PROMOTIONS_SECTION:
                with self.subTest(request=case["request"]):
                    self.assertTrue(is_transition(case), "only a transition can cite a promotion")
                    origin, targets = promotion(case["decided_by"])
                    self.assertEqual(case["during"], origin)
                    self.assertIn(case["route"], targets)


class CoverageTest(FlowApplicabilityCase):
    def test_every_clause_is_cited_by_at_least_one_case(self):
        cited = {case["decided_by"] for case in self.cases}
        for clause, section in self.clauses.items():
            with self.subTest(section=section, clause=clause):
                self.assertIn(clause, cited)


class SizeTrapTest(FlowApplicabilityCase):
    """`surface` is a decoy: it is recorded to show that it never decided anything."""

    def test_surface_is_not_a_routing_fact(self):
        self.assertNotIn("surface", self.facts)

    def test_large_cases_that_are_not_sdd_exist(self):
        self.assertTrue([case for case in self.cases if case["surface"] == "large" and case["route"] != "sdd"])

    def test_small_cases_that_are_sdd_exist(self):
        self.assertTrue([case for case in self.cases if case["surface"] == "small" and case["route"] == "sdd"])

    def test_a_large_case_can_still_be_l0(self):
        """Many files, one trivial atomic operation: still a direct change."""
        self.assertTrue([case for case in self.cases if case["surface"] == "large" and case["route"] == "l0"])


class TransitionTest(FlowApplicabilityCase):
    def setUp(self):
        super().setUp()
        self.transitions = [case for case in self.cases if is_transition(case)]

    def test_real_promotions_cover_every_edge_of_the_ladder(self):
        edges = {(case["during"], case["route"]) for case in self.transitions}
        self.assertLessEqual({("l0", "ftd"), ("l0", "sdd"), ("ftd", "sdd")}, edges)
        self.assertTrue([edge for edge in edges if edge[0] == "query"], "no promotion out of a query")

    def test_every_transition_climbs_and_none_comes_down_from_sdd(self):
        for case in self.transitions:
            with self.subTest(request=case["request"]):
                self.assertNotEqual(case["during"], "sdd")
                self.assertGreater(CLIMB.index(case["route"]), CLIMB.index(case["during"]))

    def test_the_new_fact_is_true_and_is_what_decides_the_new_route(self):
        for case in self.transitions:
            with self.subTest(request=case["request"]):
                self.assertTrue(case["facts"][case["new_fact"]])
                _, clause = decide(case["facts"], self.order)
                deciding_fact = next(fact for fact, _, step in self.order if step == clause)
                self.assertEqual(deciding_fact, case["new_fact"])

    def test_without_the_new_fact_the_work_stays_where_it_was(self):
        """Before the promotion the work sat on `during`: the fact whose step
        routes there held -- a query's own fact, FTD's; none for L0, the
        fallback -- and the new fact did not."""
        for case in self.transitions:
            with self.subTest(request=case["request"]):
                during_fact = next(fact for fact, route, _ in self.order if route == case["during"])
                before = {**case["facts"], case["new_fact"]: False}
                if during_fact is not None:
                    before[during_fact] = True
                route, _ = decide(before, self.order)
                self.assertEqual(route, case["during"])

    def test_leaving_a_query_requires_acceptance(self):
        """A query authorizes no change: the go-ahead is always asked for."""
        for case in self.transitions:
            if case["during"] == "query":
                with self.subTest(request=case["request"]):
                    self.assertTrue(case["requires_acceptance"])

    def test_every_entry_to_sdd_by_a_reviewable_contract_requires_acceptance(self):
        for case in self.transitions:
            if case["route"] == "sdd" and case["new_fact"] == "needs_reviewable_contract":
                with self.subTest(request=case["request"]):
                    self.assertTrue(case["requires_acceptance"])

    def test_the_order_enters_sdd_by_a_reviewable_contract_only_on_acceptance(self):
        step = next(clause for fact, _, clause in self.order if fact == "needs_reviewable_contract")
        self.assertIn("explicit acceptance", step)

    def test_every_transition_is_decided_by_a_promotion(self):
        for case in self.transitions:
            with self.subTest(request=case["request"]):
                self.assertEqual(self.clauses.get(case["decided_by"]), PROMOTIONS_SECTION)


class FactsContractTest(FlowApplicabilityCase):
    """The explorer -> orchestrator contract and the corpus speak one vocabulary."""

    def test_the_file_declares_exactly_the_facts_the_corpus_uses(self):
        for case in self.cases:
            with self.subTest(request=case["request"]):
                self.assertEqual(set(case["facts"]), set(self.facts))

    def test_the_file_declares_four_facts_once_each(self):
        self.assertEqual(len(self.facts), 4)
        self.assertEqual(len(set(self.facts)), 4)

    def test_the_order_asks_every_declared_fact_once_then_falls_back(self):
        asked = [fact for fact, _, _ in self.order]
        self.assertEqual(asked[-1], None, "the last step must be the fallback")
        self.assertEqual(sorted(asked[:-1]), sorted(self.facts))

    def test_every_step_names_a_route_of_the_ladder(self):
        for fact, route, clause in self.order:
            with self.subTest(clause=clause):
                self.assertIn(route, ROUTES)

    def test_every_route_has_its_own_clause(self):
        leads = {_FIRST_BOLD.match(item).group(1).lower() for item in list_items(sections(self.text)[ROUTES_SECTION])}
        self.assertEqual(leads, set(ROUTES))


class ExplorerReturnsRoutingFactsTest(unittest.TestCase):
    """The explorer -> orchestrator half of the routing-facts contract.

    When a brief asks for routing facts, `pegasus-explorer` returns exactly the
    facts `## Routing facts` declares -- the set is read from
    `flow-applicability.md`, never retyped -- each as true or false with its
    evidence, and never the route: choosing it is the caller's.

    Closed world, because every open-world version -- "each mention of choosing
    the route must be negated" -- was defeated by shape: a negation merely
    nearby, the passive voice ("the route may be chosen by you"), a double
    negation ("no reason not to choose the route"). So two clauses are pinned
    as written, `FORBIDDING_CLAUSE` and `RETURNING_CLAUSE`, each exactly once,
    and no other sentence of the whole file may mention route choice, or what
    happens to the facts, in any form: stems, not inflections. The sentence
    that hosts a pinned clause gets no loophole either: the forbidding clause
    must end its sentence, and nothing else in either host sentence may carry a
    choosing or handling stem.

    Fail-safe by design: any rewording fails loudly, including a harmless one.
    "The caller decides the route, not you" added as a second sentence fails
    too, and that is intended -- a legitimate rewording is a deliberate edit of
    the pinned clause here, never a sentence the check has to judge.
    """

    @classmethod
    def setUpClass(cls):
        cls.section = sections(EXPLORER.read_text(encoding="utf-8")).get("Result identity", "")
        cls.collapsed = " ".join(cls.section.split())
        cls.facts = declared_facts(flow_text())
        cls.sentences = [part for part in _SENTENCE_END.split(cls.collapsed) if part]

    def facts_sentence(self) -> str:
        naming = [s for s in self.sentences if all(f"`{fact}`" in s for fact in self.facts)]
        self.assertEqual(len(naming), 1, "one sentence must name every routing fact")
        return naming[0]

    def test_the_prose_names_exactly_the_declared_facts(self):
        self.assertEqual(len(self.facts), 4)
        self.assertEqual(set(_FACT_NAME.findall(self.section)), set(self.facts))

    def test_each_fact_is_asked_as_true_or_false_with_its_evidence(self):
        sentence = self.facts_sentence()
        self.assertIn("true or false", sentence)
        self.assertIn("evidence", sentence)

    def test_it_applies_only_when_the_brief_asks_for_routing_facts(self):
        """An ordinary exploration brief is unaffected: the instruction opens on
        its condition."""
        sentence = self.facts_sentence()
        self.assertRegex(sentence, r"^(?:When|If)\b")
        self.assertLess(sentence.index("routing facts"), sentence.index(f"`{self.facts[0]}`"))

    def test_the_returning_clause_is_there_exactly_once(self):
        self.assertEqual(explorer_text().count(RETURNING_CLAUSE), 1, RETURNING_CLAUSE)

    def test_no_other_sentence_speaks_of_returning_or_withholding_the_facts(self):
        hosts, others = split_around(explorer_text(), RETURNING_CLAUSE)
        for remainder in hosts:
            with self.subTest(host=remainder):
                self.assertIsNone(_HANDLING_STEM.search(remainder), "the pinned clause's own sentence qualifies it")
        for sentence in others:
            with self.subTest(sentence=sentence):
                self.assertFalse(
                    _FACT_STEM.search(sentence) and _HANDLING_STEM.search(sentence),
                    "only the pinned clause may say what happens to the facts",
                )

    def test_the_forbidding_clause_is_there_exactly_once_and_closes_its_sentence(self):
        """Closing the sentence leaves nothing after it to qualify the clause."""
        self.assertEqual(explorer_text().count(FORBIDDING_CLAUSE), 1, FORBIDDING_CLAUSE)
        self.assertEqual(explorer_text().count(f"{FORBIDDING_CLAUSE}."), 1, "the clause must end its sentence")

    def test_no_other_sentence_mentions_route_choice(self):
        hosts, others = split_around(explorer_text(), FORBIDDING_CLAUSE)
        for remainder in hosts:
            with self.subTest(host=remainder):
                self.assertIsNone(_CHOICE_STEM.search(remainder), "the pinned clause's own sentence qualifies it")
                self.assertIsNone(_ROUTE_AS_VERB.search(remainder), "the pinned clause's own sentence qualifies it")
        for sentence in others:
            with self.subTest(sentence=sentence):
                self.assertFalse(
                    _ROUTE_STEM.search(sentence) and _CHOICE_STEM.search(sentence),
                    "only the pinned clause may mention choosing a route",
                )
                self.assertIsNone(_ROUTE_AS_VERB.search(sentence), "routing the work, outside the pinned clause")

    def test_the_word_route_lives_only_in_the_pinned_clause(self):
        """The choosing stems above are a list, and a list forgets a synonym:
        "settle which route applies" names no stem and passes them. The
        explorer has no other reason to say "route" at all, so the word itself
        is the closed world -- outside the pinned clause it does not appear,
        and "routing" appears only as the name "routing facts". A new sentence
        that needs the word is a deliberate edit of this test, not a slip."""
        rest = explorer_text().replace(FORBIDDING_CLAUSE, " ")
        self.assertEqual(re.findall(r"\broute[sd]?\b", rest, re.IGNORECASE), [])
        self.assertEqual(re.findall(r"\brouting\b(?!\s+facts\b)", rest, re.IGNORECASE), [])

    def test_the_pointer_to_the_ladder_fails_open(self):
        self.assertIn("{{skills_root}}/_shared/flow-applicability.md", self.section)
        self.assertIn("missing or unreadable", self.section)


if __name__ == "__main__":
    unittest.main()
