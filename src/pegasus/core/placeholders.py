"""The closed vocabulary the installer fills in, split by who may ask for what.

Two audiences share the same `{{name}}` syntax and are not the same
vocabulary. `BODY_NAMES` is what a content body -- an agent, a command, a
skill's frontmatter, an MCP descriptor, the system prompt -- may ask its
installer to fill in. `ASSET_NAMES` is what an asset an adapter bundles of
its own (a plugin, a package manifest) may ask for, on top of `BODY_NAMES`.
`NAMES` is
their union, for a check that is about whether a name is a placeholder at
all rather than about which audience may use it.

A body is written once and installed by every adapter, so it must not name a
path: an absolute directory under somebody's home is one product, one machine
and one user. It names a fact instead -- `{{skills_root}}`, today the only
name in `BODY_NAMES` -- and each adapter answers it from its own layout.

`{{orchestrator}}` is the same idea applied to identity rather than a path:
the agent a session starts in is content-declared (`Agent.default`), never a
literal an adapter or one of its bundled assets picks for itself -- see
`core.catalog._orchestrator_name`, the one place that reads it off the
content core. It is in `ASSET_NAMES`, not `BODY_NAMES`: no shipped body names
it, and the only things that do are assets an adapter bundles of its own.

`{{program_name}}`, `{{display_name}}`, `{{program_module_name}}`,
`{{program_pascal_name}}` and `{{program_npm_name}}` are the same idea again,
applied to a distribution's own `Identity` (`core.identity.Identity`) rather
than to content: a bundled asset that names the running product -- a log
prefix, a toast title, an exported symbol, a filename it references by name --
asks for one of these instead of hardcoding one distribution's own brand.
They too are `ASSET_NAMES`, not `BODY_NAMES`: where a shipped body names the
brand, it does so in prose that the distribution step rewrites by text
substitution, never by asking an adapter to fill a placeholder.
`program_module_name`, `program_pascal_name` and `program_npm_name` are
`program_name` reshaped for a context `program_name` itself cannot satisfy: a
valid Python module stem (hyphens are not legal in an import), a PascalCase
identifier (for a plugin's exported symbol), and an npm-legal package name
(npm rejects uppercase in `package.json`'s `name` field, which
`PROGRAM_NAME_PATTERN` otherwise allows), respectively -- derived by whichever
adapter's own naming helper needs them, never by this module.

Double braces, because single ones are already spoken for. `{change-name}` and
`{topic}` are addressed to the model reading the body, and confusing the two
audiences is how a prompt ends up with a literal brace where a path belongs.

Each vocabulary is closed on purpose. A name outside a caller's set is a typo
or a name asked of the wrong audience, and either one travels verbatim into an
agent's loading gate and dies at runtime in the middle of somebody's task.
Refusing it while the offending file still has a name costs nothing.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

#: Every fact a content body may ask for. It is installed by `render._body`,
#: which fills it from `render.facts` -- so this set must name exactly what
#: that function answers. Today that is `skills_root` alone: the six identity
#: and orchestrator facts below are answered only for an asset an adapter
#: bundles of its own, never for a body, because nothing a
#: body embeds is the running distribution's own brand -- where a body names
#: it, it does so in prose the distribution step rewrites by text
#: substitution, not by asking an adapter to fill a placeholder.
BODY_NAMES = frozenset({"skills_root"})

#: Every fact an adapter's own bundled asset may ask for on top of
#: `BODY_NAMES`. Answered only by the adapter that bundles those assets, which
#: extends what a body gets with these -- so a body naming one of them fails at
#: content load, not at install, because no body has anywhere it is filled.
ASSET_NAMES = frozenset(
    {
        "orchestrator",
        "program_name",
        "display_name",
        "program_module_name",
        "program_pascal_name",
        "program_npm_name",
    }
)

#: The full vocabulary, body and asset facts together. Used where a check is
#: about whether a name is a placeholder at all, not about who may ask for it
#: -- e.g. a skill's verbatim reference files, which never get filled by
#: anyone and so refuse every name in this union alike.
NAMES = BODY_NAMES | ASSET_NAMES

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


def unknown_in(body: str, vocabulary: frozenset[str] = NAMES) -> tuple[str, ...]:
    """The placeholders nobody in `vocabulary` promised to answer.

    Defaults to the full vocabulary; a caller checking one audience only --
    a content body against `BODY_NAMES`, say -- passes that set explicitly.
    """
    return tuple(name for name in names_in(body) if name not in vocabulary)


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
