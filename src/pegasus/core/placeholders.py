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

PATTERN = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


def names_in(body: str) -> tuple[str, ...]:
    """Every placeholder the body uses, in order of first appearance."""
    found: dict[str, None] = {}
    for match in PATTERN.finditer(body):
        found.setdefault(match.group(1), None)
    return tuple(found)


def unknown_in(body: str) -> tuple[str, ...]:
    """The placeholders nobody promised to answer."""
    return tuple(name for name in names_in(body) if name not in NAMES)


def fill(body: str, values: Mapping[str, str]) -> str:
    """Answer every placeholder, or raise `KeyError` naming the first one that has none.

    The caller decides what an unanswered placeholder means. For an adapter it
    means its layout has no such concept, which is a refusal, not a blank.
    """

    def answer(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(name)
        return values[name]

    return PATTERN.sub(answer, body)
