"""Every closed-world subject regex, held against the words people use.

The v7 text checks are closed-world: each pins the permitted sentences on a
subject as written and fails on any other sentence that touches the subject.
Which sentences touch it is decided by a regex of word stems, and a stem list
forgets a word. Every v7 slice shipped such a gap that only review found --
handoff, private key and API key, shippable, skip TDD, always write tests
before code, settle which route applies -- and each one was a hole in its
closed world: a sentence the list does not match is a sentence the check never
looks at.

`tests/fixtures/closed-world-vocabulary.json` keeps, per topic, natural
phrasings its regexes MUST match: every phrase a review found missing, and the
obvious synonyms of the register. The regexes are imported from the tests that
use them, never retyped, so widening one here widens the check itself, and a
phrase a regex misses fails here, before review.

Which regexes need a topic is derived, not listed. Every test module that
declares a closed-world check is read as source, and a regex counts when it
filters a file's units: the receiver of a `.search`, `.match` or `.findall`
in a comprehension's condition or in a negative assertion, or a regex handed
to a helper that filters that way. Each one found must be named by a topic.

Declared residue: the corpus is finite too. It proves the lists match what
was thought of, not what was not; the next gap a review finds is a new phrase
here first, then a widened list. And the derivation sees module-level regexes
only: one compiled inside a test, or iterated from a tuple, is not found.
"""
from __future__ import annotations

import ast
import importlib
import json
import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
CORPUS = TESTS / "fixtures" / "closed-world-vocabulary.json"
CORPUS_KEYS = frozenset({"about", "topics"})
TOPIC_KEYS = frozenset({"stems", "must_match"})

#: How a module declares a closed-world check, in its docstrings and comments.
CLOSED_WORLD = re.compile(r"closed[- ]world", re.IGNORECASE)
_MATCHING = frozenset({"search", "match", "fullmatch", "findall"})
_NEGATIVE_ASSERTIONS = frozenset({"assertFalse", "assertIsNone"})

#: The stem lists the debt named, each one found missing a word in review.
#: Guards the derivation from passing vacuously: it must find at least these.
REVIEWED_STEMS = (
    "test_flow_routing.FTD_STEMS",
    "test_flow_routing._CHOICE_STEM",
    "test_flow_routing._ROUTE_STEM",
    "test_ftd_procedure._SECRET_STEM",
    "test_orchestrator_routing.READINESS_STEM",
    "test_craft_extraction.CRAFT_RULE_SUBJECT",
    "test_craft_extraction.TDD_SUBJECT",
)


def corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def resolve(reference: str) -> object:
    """The object `module.NAME` names, imported from the module itself."""
    module, _, name = reference.rpartition(".")
    return getattr(importlib.import_module(module), name)


def identity(pattern: re.Pattern[str]) -> tuple[str, int]:
    """What makes two regexes the same regex. An imported alias shares it; a
    retyped copy shares it only while it stays identical."""
    return pattern.pattern, pattern.flags


def closed_world_modules() -> list[Path]:
    return sorted(
        path
        for path in TESTS.glob("test_*.py")
        if path.resolve() != Path(__file__).resolve() and CLOSED_WORLD.search(path.read_text(encoding="utf-8"))
    )


def _receivers(node: ast.AST) -> set[str]:
    """Every name whose matching method is called anywhere under `node`."""
    return {
        sub.func.value.id
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr in _MATCHING
        and isinstance(sub.func.value, ast.Name)
    }


def _filtering_names(tree: ast.AST) -> set[str]:
    """Names that filter units: in a comprehension's condition, or in the first
    argument of a negative assertion ("no other sentence may say this")."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.comprehension):
            for condition in node.ifs:
                names |= _receivers(condition)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _NEGATIVE_ASSERTIONS
            and node.args
        ):
            names |= _receivers(node.args[0])
    return names


def _filtering_helpers(trees: list[ast.Module]) -> dict[str, set[int]]:
    """Module-level functions that filter by a regex they are handed, with the
    positions of the parameters that carry it (`sentences_on(text, stem)`)."""
    helpers: dict[str, set[int]] = {}
    for tree in trees:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                used = _filtering_names(node)
                positions = {index for index, arg in enumerate(node.args.args) if arg.arg in used}
                if positions:
                    helpers.setdefault(node.name, set()).update(positions)
    return helpers


def closed_world_stems() -> dict[str, re.Pattern[str]]:
    """`module.NAME` for every module-level regex a closed-world check filters by."""
    trees = {path.stem: ast.parse(path.read_text(encoding="utf-8")) for path in closed_world_modules()}
    helpers = _filtering_helpers(list(trees.values()))
    found: dict[str, re.Pattern[str]] = {}
    for module_name, tree in trees.items():
        names = _filtering_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in helpers:
                for position in helpers[node.func.id]:
                    if position < len(node.args) and isinstance(node.args[position], ast.Name):
                        names.add(node.args[position].id)
        module = importlib.import_module(module_name)
        for name in names:
            value = getattr(module, name, None)
            if isinstance(value, re.Pattern):
                found[f"{module_name}.{name}"] = value
    return found


class CorpusShapeTest(unittest.TestCase):
    def setUp(self):
        self.corpus = corpus()
        self.topics = self.corpus["topics"]

    def test_the_corpus_has_exactly_its_keys(self):
        self.assertEqual(set(self.corpus), CORPUS_KEYS)
        self.assertIn("not what was not", self.corpus["about"])

    def test_every_topic_has_stems_and_phrases(self):
        for topic, entry in self.topics.items():
            with self.subTest(topic=topic):
                self.assertEqual(set(entry), TOPIC_KEYS)
                self.assertTrue(entry["stems"])
                self.assertTrue(entry["must_match"])

    def test_phrases_are_unique_within_a_topic(self):
        for topic, entry in self.topics.items():
            with self.subTest(topic=topic):
                self.assertEqual(len(entry["must_match"]), len(set(entry["must_match"])))

    def test_every_stem_is_a_real_regex_of_a_test_module(self):
        """Named, never retyped: the corpus holds references, not patterns."""
        for topic, entry in self.topics.items():
            for reference in entry["stems"]:
                with self.subTest(topic=topic, stem=reference):
                    self.assertTrue(reference.startswith("test_"), reference)
                    self.assertIsInstance(resolve(reference), re.Pattern)


class VocabularyTest(unittest.TestCase):
    def test_every_stem_matches_every_phrase_of_its_topic(self):
        for topic, entry in corpus()["topics"].items():
            for reference in entry["stems"]:
                stem = resolve(reference)
                for phrase in entry["must_match"]:
                    with self.subTest(topic=topic, stem=reference, phrase=phrase):
                        self.assertIsNotNone(stem.search(phrase), f"{reference} misses {phrase!r}")


class EveryClosedWorldStemHasATopicTest(unittest.TestCase):
    def setUp(self):
        self.derived = closed_world_stems()
        self.named = {
            identity(resolve(reference)): reference
            for entry in corpus()["topics"].values()
            for reference in entry["stems"]
        }

    def test_the_derivation_finds_the_stems_review_widened(self):
        derived = {identity(pattern) for pattern in self.derived.values()}
        for reference in REVIEWED_STEMS:
            with self.subTest(stem=reference):
                self.assertTrue(identity(resolve(reference)) in derived, f"the derivation missed {reference}")

    def test_every_derived_stem_is_named_by_a_topic(self):
        for reference, pattern in sorted(self.derived.items()):
            with self.subTest(stem=reference):
                self.assertTrue(identity(pattern) in self.named, f"{reference} filters a closed world and has no topic")

    def test_every_topic_guards_a_derived_stem(self):
        """A topic whose regexes no closed-world check uses any more is stale."""
        derived = {identity(pattern) for pattern in self.derived.values()}
        for topic, entry in corpus()["topics"].items():
            with self.subTest(topic=topic):
                self.assertTrue(any(identity(resolve(reference)) in derived for reference in entry["stems"]))


if __name__ == "__main__":
    unittest.main()
