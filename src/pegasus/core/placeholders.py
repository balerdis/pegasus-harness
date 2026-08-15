"""The closed vocabulary a content body may ask its installer to fill in.

A body is written once and installed by every adapter, so it must not name a
path: an absolute directory under somebody's home is one product, one machine
and one user. It names a fact instead -- `{{skills_root}}` -- and each adapter
answers it from its own layout.

Double braces, because single ones are already spoken for. `{change-name}` and
`{topic}` are addressed to the model reading the body, and confusing the two
audiences is how a prompt ends up with a literal brace where a path belongs.

The vocabulary is closed on purpose. An unknown name is a typo, and a typo here
travels verbatim into an agent's loading gate and dies at runtime in the middle
of somebody's task. Refusing it while the offending file still has a name costs
nothing.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

#: Every fact a body may ask for. Adding one obliges every adapter to answer it.
NAMES = frozenset({"skills_root"})

#: The lookarounds refuse a pair with another brace stuck to it. Without them
#: `{{{skills_root}}}` matches the inner pair and fills into stray braces, which
#: reads as a successful substitution and is not one.
PATTERN = re.compile(r"(?<!\{)\{\{\s*([^{}]*?)\s*\}\}(?!\})")


def names_in(body: str) -> tuple[str, ...]:
    """Every placeholder the body uses, in order of first appearance."""
    found: dict[str, None] = {}
    for match in PATTERN.finditer(body):
        found.setdefault(match.group(1), None)
    return tuple(found)


def unknown_in(body: str) -> tuple[str, ...]:
    """The placeholders nobody promised to answer."""
    return tuple(name for name in names_in(body) if name not in NAMES)


def malformed_in(text: str) -> bool:
    """Whether an opener survives that the pattern could not read.

    `{{ oops` and `{{{name}}}` name nothing, so neither validation nor filling
    sees them, and they ship as the literal braces this module exists to stop.

    Only an opener counts. A stray `}}` is how ordinary nested prose ends -- a
    JSON object, a dict, a jq filter -- and this content is prompts about a
    JSON-configured CLI, so flagging it would refuse the most obvious thing an
    author writes. Nothing can be a placeholder without an opener anyway.
    """
    return "{{" in PATTERN.sub("", text)


def answerable_in(text: str) -> tuple[str, ...]:
    """The facts this text asks for that somebody has actually promised to answer.

    Narrower than `names_in` on purpose: it is for content that is installed
    verbatim, where the question is not whether a name is spelled right but
    whether the text is asking at all.
    """
    folded = {name.casefold() for name in NAMES}
    return tuple(name for name in names_in(text) if name.casefold() in folded)


class Unanswered(KeyError):
    """Nobody could answer a placeholder. A `KeyError` so callers may still catch broadly."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def fill(body: str, values: Mapping[str, str]) -> str:
    """Answer every placeholder, or raise `Unanswered` naming the first one that has none.

    The caller decides what an unanswered placeholder means. For an adapter it
    means its layout has no such concept, which is a refusal, not a blank.
    """

    def answer(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise Unanswered(name)
        return values[name]

    return PATTERN.sub(answer, body)
