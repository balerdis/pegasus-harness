"""Turning content plus an adapter into the list of artifacts an install will place.

The catalog is a derived artifact: it is generated from the content core, never
written by hand. Its digests are what later lets an installation prove that what
it placed is what the release declared.

Nothing here names a CLI. The build walks the capabilities an adapter declares
and asks that adapter to render each one.

An artifact lands in one of two legitimate territories: a CLI's own
configuration root, or Pegasus's own directory -- the second is where a
materialized dependency will live, placed by the engine rather than by an
adapter. Anything outside both is a leak regardless of which one it was
aiming for.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePath, PurePosixPath
from typing import Any

from pegasus.core import ownership
from pegasus.core.content import Content, Distribution, Mcp
from pegasus.core.identity import Identity
from pegasus.core.types import Capability, ConfigKeyArtifact, Environment, FileArtifact

SCHEMA = "pegasus/artifact-catalog/v4"
APPEND_TOKEN = "/-"

SOURCES: dict[Capability, tuple[str, str]] = {
    Capability.SKILLS: ("skills", "render_skill"),
    Capability.SUB_AGENTS: ("agents", "render_agent"),
    Capability.PROMPTS: ("agents", "render_prompt"),
    Capability.SLASH_COMMANDS: ("commands", "render_command"),
    Capability.SYSTEM_PROMPT: ("system_prompt", "render_system_prompt"),
    Capability.MCP: ("mcp", "render_mcp"),
}
"""Which part of the content core feeds each capability, and what renders it."""

INTERACTIVE = frozenset({Capability.PER_AGENT_MODEL})
"""Capabilities configured after installing, so they contribute no artifacts."""


class CatalogError(ValueError):
    """The catalog cannot be built, or would place two artifacts at one address."""


_UNSOURCED = [
    capability
    for capability in Capability
    if capability not in INTERACTIVE and capability not in SOURCES
]
if _UNSOURCED:
    # Checked once, at import time, rather than where `render` used to look the
    # capability up: a `KeyError` caught at runtime would only ever be found in a
    # user's installation, on whichever CLI first declared the missing capability.
    # An import-time invariant makes the same mistake impossible to ship at all --
    # the author's own machine refuses to import the module.
    raise CatalogError(
        "no content source for capability(ies): "
        + ", ".join(sorted(capability.value for capability in _UNSOURCED))
    )


@dataclass(frozen=True)
class DelegationTarget:
    """One agent's real capabilities, as an install will actually grant them.

    Exists to answer the question a delegating agent's brief keeps getting wrong:
    can the agent I am about to hand this to actually do what I am about to ask?
    `requires_tools`/`optional_tools` are native tools, exactly as `Agent` declares
    them. `mcp` folds `optional_mcp` (a shipped server the user chose) and
    `granted_mcp` (a server the user administers) into one set, because the
    question a delegator asks is "can this agent reach it", never "which of two
    mechanisms granted it" -- and treating them separately risks a delegator
    reading only `optional_mcp`, missing a `granted_mcp` server, and concluding a
    target cannot do something it actually can. That false negative is the
    expensive direction this whole file exists to close, so the two are never
    split back apart here.

    `withheld_mcp_tools` closes the other, symmetric direction of the same
    mistake: a server named bare in `mcp` reads as "granted in full", which is
    only true when nothing in `Mcp.withheld_tools` takes part of it back. Pairs
    of (key, tools), one pair per server in `mcp` that withholds anything --
    never every server, and never keyed by a tuple a `dict` could not also
    represent, so a frozen dataclass instance stays hashable. The key is each
    server's *resolved* key (`Mcp.bound_to` or its `name`, exactly what `mcp`
    itself already lists), computed here from the same descriptor fields
    `content._denied_mcp_tools` resolves a grant against -- never by splitting
    an already-qualified `Agent.denied_mcp_tools` string back apart, which
    `<key>_<tool>` cannot support unambiguously the moment a key itself
    contains an underscore.
    """

    name: str
    requires_tools: tuple[str, ...]
    optional_tools: tuple[str, ...]
    mcp: tuple[str, ...]
    withheld_mcp_tools: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    target: PurePosixPath
    digest: str
    pointer: str | None = None
    codec: str | None = None
    mode: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            key: (str(value) if isinstance(value, PurePosixPath) else value)
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass(frozen=True)
class Catalog:
    """Everything one CLI would receive, addressed relative to its config root."""

    cli: str
    entries: tuple[Entry, ...]
    schema: str = SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "cli": self.cli,
            "entries": [entry.as_dict() for entry in self.entries],
        }

    @property
    def digest(self) -> str:
        """One digest for the whole catalog, so a release can be compared as a unit."""
        return ownership.digest_of_value(self.as_dict())

    def __len__(self) -> int:
        return len(self.entries)


def render(
    content: Content,
    adapter: Any,
    environment: Environment,
    identity: Identity,
    model_overrides: dict[str, Any] | None = None,
) -> list[Any]:
    """Everything the adapter declares it supports, plus what it ships itself.

    This is the output of the adapt-and-decorate steps: finished artifacts,
    addressed at real paths for this environment. The catalog turns them into a
    portable manifest; an installation hands them to the planner instead.

    `identity` is `Runtime.identity`, threaded through from the composition
    root (`cli.py`) rather than read by the adapter on its own. `own_artifacts`
    and `render_system_prompt` are the two places an adapter names a file that
    does not simply mirror the content core one-for-one -- the first ships
    files of its own, the second names *which* file the base system prompt is
    -- so those are the two renderers this function passes it to. `Identity` is
    a `core` dataclass (see `tests/test_architecture.py`'s layer rules), so
    passing it through `core` to an `adapters/` implementation is legal; it
    carries no CLI-specific or distribution-literal knowledge of its own, so
    threading it here does not teach `core.catalog` which distribution is
    running.

    `model_overrides` maps an agent's name to an already-resolved
    ``ModelAssignment`` -- model and effort together, a fact about one
    machine, never about the release, which is exactly why `build` below
    never passes one. This function never looks inside the value: it is
    opaque here, and only the adapter's `render_agent` knows what to do with
    it.

    `render_agent` also receives, as its fourth argument, every `Mcp`
    descriptor `_mcp_for_agent` resolves for that agent -- both halves of
    what it may reach: `_mcp_by_key(content)` for `item.optional_mcp` (a
    shipped server the user chose; see that helper's own docstring for why
    the lookup key is `Mcp.bound_to or Mcp.name`, never the bare name alone)
    and one synthesized bound descriptor per key in `item.granted_mcp` (a
    server the user administers themselves, granted through `mcp grant` --
    see `content.grant_mcp`'s own docstring). `content` at this point has
    already been through `select_mcp`/`grant_mcp` (see `cli.py`'s ordering),
    exactly the same precondition `_delegation_targets` below relies on, so
    both fields are what an install will really grant, not the shipped
    superset -- an agent's rendered grant and the descriptors handed to
    `render_agent` for it can never disagree about which servers survived
    selection. Threading `granted_mcp` through here, rather than leaving it
    for each adapter to read off `item` directly, is what lets an adapter
    whose own per-agent configuration has a place for a bound server's
    definition actually receive one; an adapter whose own `render_agent`
    ignores this parameter entirely, and reads `item.granted_mcp` off the
    `Agent` it already has instead (see that adapter's own docstring for
    why), is unaffected by what this tuple now contains, so widening it
    cannot alter that adapter's rendered bytes. Every other capability's
    renderer keeps its original two-argument shape.

    `_delegation_targets(content)` is computed here, the same moment
    `orchestrator_name` is, and for the same reason: `content` at this point has
    already been through `select_mcp` and `grant_mcp` (see `cli.py`'s ordering),
    so `optional_mcp` and `granted_mcp` are what an install will actually grant,
    not the shipped superset. Deriving it any earlier -- at `content.load()` time
    -- would advertise a server the user never chose, which is the exact defect
    this value exists to close, inverted. It is threaded to `own_artifacts`
    alongside `orchestrator_name` rather than sourced from a new `Capability`:
    it is one aggregate fact over every agent, not a per-item render, so it does
    not fit the `SOURCES` loop above, and `own_artifacts` is already the
    established seam for a value `render` derives from the whole content tree
    and hands to the adapter to place and format.
    """
    layout = adapter.layout(environment)
    manifest = adapter.capabilities()
    overrides = model_overrides or {}
    artifacts: list[Any] = []
    orchestrator_name = _orchestrator_name(content)
    delegation_targets = _delegation_targets(content)
    mcp_by_key = _mcp_by_key(content)

    for capability in sorted(manifest.enabled - INTERACTIVE, key=lambda item: item.value):
        attribute, renderer = SOURCES[capability]
        for item in _items(content, attribute):
            if capability is Capability.SUB_AGENTS:
                granted = _mcp_for_agent(item, mcp_by_key)
                artifacts.extend(
                    getattr(adapter, renderer)(layout, item, overrides.get(item.name), mcp=granted)
                )
            elif capability is Capability.SLASH_COMMANDS:
                artifacts.extend(getattr(adapter, renderer)(layout, item, orchestrator_name))
            elif capability is Capability.SYSTEM_PROMPT:
                artifacts.extend(getattr(adapter, renderer)(layout, item, identity))
            else:
                artifacts.extend(getattr(adapter, renderer)(layout, item))

    artifacts.extend(adapter.own_artifacts(layout, orchestrator_name, identity, delegation_targets))
    return artifacts


#: The frame every catalog is built in. Not a real directory, and never written to.
CANONICAL_HOME = PurePosixPath("/pegasus/catalog-build")

#: The second frame alongside `CANONICAL_HOME`: the shape of Pegasus's own
#: directory in the canonical build. Never real, and never computed through a
#: filesystem -- for the same reason `CANONICAL_HOME` is not real either. The
#: real path (`FileSystem.data_dir`) varies by platform and environment, which
#: is exactly what a release digest must not depend on.
CANONICAL_DATA_DIR = CANONICAL_HOME / ".pegasus-data"

CANONICAL_PROGRAM_MODE = "0755"
CANONICAL_TEXT_MODE = "0644"


@dataclass(frozen=True)
class Territory:
    """The roots an artifact may legitimately land under.

    A single root used to be enough to describe "not a leak"; a materialized
    dependency makes that untrue, so this holds every root that counts as
    legitimate and answers which one, if any, contains a given path.
    """

    roots: tuple[PurePath, ...]

    def root_of(self, path: PurePath) -> PurePath | None:
        """The one root that contains ``path``, or ``None`` outside every root."""
        for root in self.roots:
            if path.is_relative_to(root):
                return root
        return None


def build(content: Content, adapter: Any, identity: Identity) -> Catalog:
    """The portable manifest of what one CLI would receive.

    Built in a canonical frame on purpose, because this is release identity: two
    machines must agree on it for the digest to mean anything. It used to be
    home-independent by luck, since nothing an adapter rendered happened to
    contain a path. A body that asks the installer for one -- the whole point of
    `core.placeholders` -- would end that quietly, giving every user a different
    digest for the same release. Taking the environment away makes the property
    structural instead of accidental.

    The frame is what makes two machines agree; it is not what makes the digest
    unique. `identity` is the other half, and it belongs in the digest rather
    than beside it: artifact names derive from the product's own name, so two
    distributions of one engine legitimately receive different files and must
    not be able to claim the same catalog.

    The permission a program and a plain file are written with is spelled
    here as a constant of the format, the same way the home is: what a given
    platform would really choose is a question for the machine that installs,
    and asking it here would make the digest depend on where it was built.

    What a machine actually receives comes from `render` with its own
    environment, and that is what the journal records.

    An artifact may also land in Pegasus's own directory rather than the CLI's
    configuration root -- `CANONICAL_DATA_DIR` stands in for it here, the same
    way `CANONICAL_HOME` stands in for a real home: `FileSystem.data_dir` is a
    filesystem method, computed per platform and environment, and the digest
    of a release must not vary with either.
    """
    # PurePosixPath end to end: `Path` takes the flavour of whatever machine runs
    # the build, and a canonical frame that spells itself differently on Windows
    # is not canonical.
    canonical = Environment(home=CANONICAL_HOME, data_dir=CANONICAL_DATA_DIR)
    artifacts = render(content, adapter, canonical, identity)
    config_root = adapter.layout(canonical).config_dir
    territory = Territory(roots=(config_root, CANONICAL_DATA_DIR))
    return Catalog(cli=adapter.id, entries=_entries(artifacts, territory, adapter.id))


def _orchestrator_name(content: Content) -> str:
    """The name of the agent this content declares a session starts in.

    Read off `Agent.default`, which is itself content-declared (see
    `pegasus.core.content.SESSION_STARTS_IN`), never a literal picked here --
    this is the one place a `render_command` capability build learns what to
    put in a rendered `agent:` field for `RunsAs.ORCHESTRATOR`.
    """
    starts = next((agent for agent in content.agents if agent.default), None)
    if starts is None:
        raise CatalogError("no agent starts the session; cannot render slash commands")
    return starts.name


def _delegation_targets(content: Content) -> tuple[DelegationTarget, ...]:
    """Every agent named in at least one `may_delegate_to`, with its real capabilities.

    The subject set is the union of every agent's `may_delegate_to`, including a
    name an agent lists for itself: `pegasus-general` naming itself is still a real
    delegation another agent's brief may target through `pegasus-general`'s own
    fan-out, and the row exists so THAT delegator can look it up too. An agent
    nobody's `may_delegate_to` ever names -- the two primaries this content ships,
    `king-pegasus` and `pegasus-orchestrator` -- is never the answer to "what can my
    delegation target do", so it earns no row: listing it would be noise with no
    question it answers.

    A name with no matching agent in `content.agents` is skipped rather than
    raised: `may_delegate_to` carries no `_require_reaches_known_agents`-style
    invariant the way an `Mcp` descriptor's `reaches` list does, so this stays as
    forgiving of an unknown name as the rest of this module already is.
    """
    known = {agent.name: agent for agent in content.agents}
    names = sorted({target for agent in content.agents for target in agent.may_delegate_to})
    withheld_by_key = {
        server.bound_to or server.name: server.withheld_tools
        for server in content.mcp
        if server.withheld_tools
    }
    return tuple(
        DelegationTarget(
            name=name,
            requires_tools=known[name].requires_tools,
            optional_tools=known[name].optional_tools,
            mcp=tuple(sorted({*known[name].optional_mcp, *known[name].granted_mcp})),
            withheld_mcp_tools=tuple(
                (key, withheld_by_key[key])
                for key in sorted({*known[name].optional_mcp, *known[name].granted_mcp})
                if key in withheld_by_key
            ),
        )
        for name in names
        if name in known
    )


def _mcp_by_key(content: Content) -> dict[str, Any]:
    """Every server this content ships, keyed by its *resolved* binding key.

    `Mcp.bound_to or Mcp.name` -- not the bare `Mcp.name` alone -- because
    `select_mcp` rewrites every granted agent's `optional_mcp` to that same
    resolved key the instant a server is bound to one (see `content.
    select_mcp` and `content._denied_mcp_tools`, which resolve a grant
    against this identical key). Looking this map up by `name` alone would
    silently miss every bound server's real key and grant the wrong agent
    nothing, which is exactly the mismatch this function exists to rule out.

    Computed once per `render` call, the same moment `orchestrator_name` and
    `_delegation_targets` are, and for the same reason: `content` at this
    point has already been through `select_mcp`/`grant_mcp` (see `cli.py`'s
    ordering, and `_delegation_targets`'s own docstring), so this map holds
    exactly what an install would actually grant, never the shipped
    superset.
    """
    return {server.bound_to or server.name: server for server in content.mcp}


def _mcp_for_agent(item: Any, mcp_by_key: dict[str, Mcp]) -> tuple[Mcp, ...]:
    """Every `Mcp` descriptor one agent may reach: shipped, then granted.

    `item.optional_mcp` resolves against `mcp_by_key` exactly as it always
    has. `item.granted_mcp` -- a key the person administers themselves,
    identical on every agent (`content.grant_mcp`) -- has no descriptor in
    `content.mcp` by construction (`grant_mcp` refuses a key `per_agent_mcp_
    keys` already covers), so there is nothing to look up: a bound-reference
    descriptor is synthesized instead, the same shape `select_mcp` itself
    produces for a server the user configured on their own. Appended after
    the shipped set, never merged into it or reordered: the two key spaces
    are disjoint by that same refusal, so there is no collision to resolve,
    only a fixed order to keep the rendered list stable across the same
    input.
    """
    shipped = tuple(mcp_by_key[key] for key in item.optional_mcp if key in mcp_by_key)
    granted = tuple(_granted_mcp_descriptor(key) for key in item.granted_mcp)
    return shipped + granted


def _granted_mcp_descriptor(key: str) -> Mcp:
    """A bound-reference `Mcp` for a key the person administers themselves.

    Pegasus never shipped a descriptor for this key -- there is no
    `description`, `body`, or `distribution` to state a fact about, because
    none of those facts are Pegasus's to know for a server it neither
    fetches nor defines. `bound_to=key` is the only field an adapter reading
    a granted server actually consults -- one adapter's own bound-reference
    render branch, another's own wildcard over `item.granted_mcp`, neither
    of which ever looks at this object's other fields at all -- every
    adapter that names a bound server writes only the key that installation
    already runs it under, never a definition of its own. `distribution`/
    `endpoint` still need placeholder values the dataclass accepts --
    `Distribution.REMOTE` and an empty string -- but no renderer this
    codebase ships ever reads either for a descriptor whose `is_bound` is
    true.
    """
    return Mcp(
        name=key,
        description="a server the person administers themselves, granted through `mcp grant`",
        body="",
        distribution=Distribution.REMOTE,
        endpoint="",
        source=PurePosixPath("mcp") / f"{key}-granted",
        bound_to=key,
    )


def _items(content: Content, attribute: str) -> tuple[Any, ...]:
    """A category is a sequence; a singleton is one item, or nothing when absent."""
    value = getattr(content, attribute)
    if value is None:
        return ()
    return tuple(value) if isinstance(value, (tuple, list)) else (value,)


def _entries(artifacts: list[Any], territory: Territory, cli: str) -> tuple[Entry, ...]:
    entries, seen_ids, seen_addresses = [], set(), set()
    for artifact in artifacts:
        root = territory.root_of(artifact.path)
        if root is None:
            allowed = " or ".join(str(candidate) for candidate in territory.roots)
            raise CatalogError(f"{cli!r} would place {artifact.path} outside {allowed}")
        entry = _entry(artifact, root)

        if entry.id in seen_ids:
            raise CatalogError(f"{cli!r} produced two artifacts with the id {entry.id!r}")
        seen_ids.add(entry.id)

        # Appending to a list is legitimately repeatable; every other address is
        # a single slot and two artifacts claiming it would mean one is lost.
        address = (entry.target, entry.pointer)
        if entry.pointer is None or not entry.pointer.endswith(APPEND_TOKEN):
            if address in seen_addresses:
                raise CatalogError(f"{cli!r} would place two artifacts at {address}")
            seen_addresses.add(address)

        entries.append(entry)
    return tuple(sorted(entries, key=lambda item: item.id))


def _entry(artifact: Any, root: Any) -> Entry:
    target = PurePosixPath(artifact.path.relative_to(root).as_posix())
    if isinstance(artifact, FileArtifact):
        return Entry(
            id=artifact.id,
            kind="file",
            target=target,
            digest=ownership.digest(artifact),
            mode=CANONICAL_PROGRAM_MODE if artifact.executable else CANONICAL_TEXT_MODE,
        )
    if isinstance(artifact, ConfigKeyArtifact):
        return Entry(
            id=artifact.id,
            kind="config-key",
            target=target,
            digest=ownership.digest(artifact),
            pointer=artifact.pointer,
            codec=artifact.codec.value,
        )
    raise CatalogError(f"unsupported artifact shape: {type(artifact).__name__}")
