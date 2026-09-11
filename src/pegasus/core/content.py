"""Loading the content core.

Every category is a markdown file with YAML frontmatter: the frontmatter is the
descriptor, the rest is the body. One format, one parser.

Nothing here names a CLI. A field that only makes sense for one product does not
belong in a descriptor, so this loader rejects it rather than passing it through
and letting an adapter guess.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from importlib.resources import files as _package_files
from pathlib import Path, PurePosixPath
from typing import Any

from pegasus.core import frontmatter, placeholders

#: Whatever `importlib.resources` hands back: a real `pathlib.Path` when the
#: package sits on a filesystem, a `zipfile.Path` when it is read straight out
#: of an archive. Both answer `iterdir`, `is_dir`, `is_file`, `read_text`,
#: `read_bytes`, `joinpath` and `.name`; neither call is spelled here in a way
#: that only one of the two could answer -- `resolve`, `relative_to`, `parent`,
#: `glob` and `rglob` exist on the filesystem one and not the other, so this
#: module never reaches for them. Every relative path this module reports is
#: instead threaded through as it is discovered, rather than computed after
#: the fact from an absolute one.
ContentRoot = Any

DEFAULT_ROOT: ContentRoot = _package_files("pegasus") / "content"
MARKER = "---"
SKILL_FILE = "SKILL.md"
SYSTEM_PROMPT_DIR = "system-prompt"

SYSTEM_PROMPT_MCP_DIR = "mcp"
"""Where the system prompt keeps the sections that belong to one server each.

A subdirectory rather than more files beside `AGENTS.md`, for the same reason
`_shared/mcp/` is one: the base prompt is exactly one file, and a sibling would
have to be told apart from it by name.
"""

AGENT_MCP_DIR = "mcp"
"""Where agent prompts keep the sections that belong to one server each.

The same idea as `SYSTEM_PROMPT_MCP_DIR`, moved to the tree that has twelve
files instead of one: an agent prompt is unconditional prose the moment it is
written, so a server's ambient half has to live beside it rather than inside
it, or a user who never selected that server would still be told to follow a
convention file that was never installed. `_markdown_files` only ever looks at
files directly inside the directory it is given -- it does not recurse -- so
this subdirectory is invisible to `_load_agents`'s own scan of `agents/` by
construction, never by a name it has to remember to exclude.
"""

_AGENT_MCP_OVERRIDE = re.compile(r"^(?P<mcp_id>[^@]+)@(?P<agent>[^@]+)$")
"""How an agent-specific section names itself: `<id>@<agent>.md`. A file with
no `@` in its stem is the shared section for that id, read by every agent
that declares it and does not narrow it further."""

_MCP_CONVENTION_DIR = PurePosixPath("_shared") / "mcp"
"""Where every server's usage convention lands, relative to the skills root.

`_shared/` also holds hand-authored convention files that the skills renderer
writes by copying an asset verbatim (`openspec-convention.md`). A server's
convention is a different kind of write: the loader derives it from the
server's own descriptor body. Landing both writers in that same flat namespace
means a server whose id happens to match one of those stems collides with a
file it has nothing to do with -- `cbm` and `engram` once did, before their
conventions moved into their own descriptor bodies. A subdirectory of its own
makes that collision impossible to express, rather than something a catalog
build has to notice after the fact.
"""


def mcp_convention_path(server_id: str) -> PurePosixPath:
    """Where one server's convention lands, relative to the skills root."""
    return _MCP_CONVENTION_DIR / f"{server_id}-convention.md"


_MCP_REFERENCE_PATTERN = re.compile(
    r"\{\{skills_root\}\}/"
    + re.escape(_MCP_CONVENTION_DIR.as_posix())
    + r"/([^/\s]+?)-convention\.md"
)
"""Built from the same directory `mcp_convention_path` writes into, so the two
can never drift apart: a change to where a convention lands changes what this
matches too, instead of leaving a second, hand-copied guess of the shape.
"""


def _referenced_mcp_ids(body: str) -> set[str]:
    """Every server id an agent body names as a convention path.

    This is a containment check, not a comprehension check: it proves the exact
    path string is present somewhere in the body, never that the surrounding
    prose says anything useful about it. A fenced code block or a sentence
    telling the agent NOT to do this would satisfy it just the same. That is
    accepted here because the failure this guards against is an author who
    never mentioned the server at all -- catching more than that would mean
    judging prose, which this project deliberately leaves untested.
    """
    return set(_MCP_REFERENCE_PATTERN.findall(body))

SESSION_STARTS_IN = (_package_files("pegasus") / "content" / "session-start.txt").read_text(
    encoding="utf-8"
).strip()
"""The agent a session opens in.

Which agent that is, is a fact about the set of agents rather than about any one
of them: a CLI names it in a single-valued setting. A per-agent frontmatter flag
could not hold it, because no file can see whether another already claimed it --
two claims and no claim at all are both writable, and neither is refusable
without a validator that reads the whole directory back. Naming it once, here,
makes both unrepresentable.

Read from packaged content, not written as a literal here, for the same reason
a distribution's own name never is: a distribution that renames its
orchestrator agent must be free to say so in data, without a change to
`core/`, which never learns any agent's name is special except by reading this
file back.
"""


class ContentError(ValueError):
    """The content on disk would mislead an adapter, so it is refused."""


class AgentMode(str, Enum):
    PRIMARY = "primary"
    SUBAGENT = "subagent"


class RunsAs(str, Enum):
    """Which role executes a command. The adapter maps these to real agent names."""

    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    BUILDER = "builder"
    DEFAULT = "default"


class Execution(str, Enum):
    """Whether a command opens its own session or runs in the current conversation."""

    ISOLATED = "isolated"
    INLINE = "inline"


class Distribution(str, Enum):
    """How an MCP server reaches the user's machine.

    One member per mechanism the installer can actually execute, so a descriptor
    cannot declare a mechanism nothing can carry out.
    """

    REMOTE = "remote"
    DOWNLOAD = "download"
    NPM = "npm"


@dataclass(frozen=True)
class Asset:
    """One file belonging to a content item, already read into memory.

    The loader does the reading so adapters stay free of I/O and can be tested
    without a filesystem.
    """

    relative_path: PurePosixPath
    content: bytes


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    assets: tuple[Asset, ...]
    source: PurePosixPath


@dataclass(frozen=True)
class Agent:
    """`requires_tools` and `optional_tools` name native tools only.

    A tool that exists because an MCP server is installed is never in either list:
    it is named through `optional_mcp` instead, by the server's id rather than by
    a tool name that only happens to be true today. `optional_mcp` is derived,
    not declared -- see the field.
    """

    name: str
    description: str
    body: str
    mode: AgentMode
    source: PurePosixPath
    requires_tools: tuple[str, ...] = ()
    optional_tools: tuple[str, ...] = ()
    optional_mcp: tuple[str, ...] = ()
    """The mcp servers this agent may be granted, by server id, sorted.

    **Derived, never authored.** An agent file carrying either `optional_mcp`
    or `reaches` is refused at load time
    (`_refuse_relation_keys_in_an_agent`): the
    declaration lives in the other direction now, in the `reaches` list of
    each descriptor under `content/mcp/`, and this field is the inverse of
    those lists computed once in `_load_agents`. Sorted by server id, which
    is what the alphabetical hand-written lists used to produce, so the
    rendered output is unchanged by the move.

    Everything downstream -- `select_mcp`, `_denied_mcp_tools`,
    `mcp_sections` resolution, `render.py`, the whole adapter -- reads this
    field exactly as it always did. Only the authoring direction changed.
    """

    may_delegate_to: tuple[str, ...] = ()
    model_configurable: bool = False
    mcp_sections: tuple[McpSection, ...] = ()
    """This agent's own ambient half, one per server it was granted.

    The same split `McpSection` already draws for the system prompt, carried
    down to the level that actually grants the tools: an agent's own body is
    unconditional prose the moment it is written, so the paragraph telling it
    to follow a server's convention has to live beside the grant instead of
    inside the prompt, or it ships to every agent whether or not anyone chose
    that server. Resolved from `optional_mcp` at load time -- shared unless an
    override exists naming this agent specifically -- and pruned by
    `select_mcp` in lockstep with `optional_mcp` itself, so a grant and the
    instruction to use it can never disagree.
    """

    granted_mcp: tuple[str, ...] = ()
    """Server keys the user administers, granted through `grant_mcp` -- never
    through `optional_mcp`, and the difference is the point of this field
    existing at all.

    `optional_mcp` means "a server Pegasus ships a descriptor and a
    convention for, which the user chose": it is derived from those
    descriptors' `reaches` lists and policed by
    `_require_reaches_known_agents` (every name in `reaches` must be a
    shipped agent), `_require_mcp_convention_referenced` (the set of ids
    reaching an agent must equal the set its own body actually references)
    and the reachability rule alongside them. A key in `granted_mcp`
    satisfies none of that, by construction -- Pegasus never shipped a
    descriptor for it, so there is no convention for any body to reference,
    and no `reaches` list it could ever appear in. Putting a user's own key
    into `optional_mcp` is not even representable any more -- the field is
    derived and an agent file declaring it is refused -- and the equivalent,
    naming an agent in a `reaches` list for a server nobody described, would
    trip `_require_mcp_convention_referenced` the instant no agent body
    mentions it, and that refusal would be *correct*: it exists to catch
    exactly an id that grants a permission no prose ever tells an agent to
    use. That correctness is
    why this is a second field rather than a widening of the first -- the two
    invariant sets must keep reading `optional_mcp` only, forever, and this
    field must never be added to either check's input.

    `grant_mcp` is the only writer, the same way `select_mcp` is the only
    writer of `optional_mcp`'s resolved form: applied once, before anything
    is rendered, so every adapter renders a grant without ever knowing a
    choice was made. It sets this field identically on every agent -- the
    repository owner's explicit decision, made because a per-agent grant
    would make adding one more MCP server tedious in a way nobody wants."""

    granted_directories: tuple[str, ...] = ()
    """Absolute paths the person declared through `pegasus directory grant`,
    for a runtime's own `external_directory` permission -- the same problem
    `granted_mcp` already solves, for a different fact Pegasus cannot know on
    its own.

    Every rendered agent's `external_directory` map opens with a baseline
    that reaches every path on the machine except the skills directory this
    installation writes into. A working directory an agent legitimately needs
    -- a linked worktree elsewhere, a scratch tree outside the project -- is
    invisible to that map by construction: Pegasus never heard of it, and the
    runtime's own settings file cannot add an exception either, because
    Pegasus claims the agent's whole rendered entry and the next
    `install`/`update` overwrites whatever a person edited in by hand. This
    field is the supported way to hand an agent its own directory instead --
    a fact the person declares once, that survives every reinstall the same
    way `granted_mcp` already does.

    `grant_directories` is the only writer, set identically on every agent
    for the same reason `grant_mcp` is: a per-agent path would make granting
    one more directory as tedious as granting one more MCP server was before
    that field existed, and the repository owner's decision here is the same
    one made there."""

    denied_mcp_tools: tuple[str, ...] = ()
    """Fully-qualified tool names a wildcard grant of this agent's servers
    must not reach, in `<key>_<tool>` form.

    Empty at load time, the same way `mcp_sections` starts as one thing and
    becomes another: a descriptor's `withheld_tools` names tools bare, because
    it is written before any binding exists to qualify them against, and this
    agent has not yet been told which key any of its servers will resolve
    under. `select_mcp` is the one place that knows both -- the descriptor's
    `withheld_tools` and the key (bound, or the id itself) each server in
    `optional_mcp` ends up granted under -- so it is the only place that can
    fill this in, mirroring exactly how it resolves `mcp_sections` and
    rewrites `optional_mcp` itself in the same pass.
    """

    @property
    def default(self) -> bool:
        """Whether a session starts in this agent. Read off the name, so only one can."""
        return self.name == SESSION_STARTS_IN

    @property
    def hidden(self) -> bool:
        """Whether the runtime keeps this agent out of the chooser.

        That is exactly what being a subagent means, with no exception, so it is
        read off `mode` rather than declared beside it where the two could drift.
        """
        return self.mode is AgentMode.SUBAGENT


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    body: str
    runs_as: RunsAs
    execution: Execution
    source: PurePosixPath


@dataclass(frozen=True)
class Mcp:
    """``endpoint`` is where this distribution reaches: a service URL for
    ``remote``, the asset to fetch for ``download``, the tarball npm itself
    would resolve for ``npm``.

    ``version`` and ``checksum`` exist only for ``download`` -- what proves
    the bytes that arrived are the ones that were meant to.

    ``package``, ``integrity``, ``entry``, ``npm_lockfile`` and
    ``npm_package_name`` exist only for ``npm``, the same idea through npm's
    own chain: ``package`` and ``version`` are what gets installed,
    ``integrity`` is the hash npm verifies the tarball against, ``entry`` is
    the script inside it a CLI ends up pointing at, ``npm_lockfile`` is the
    real lockfile the descriptor's ``lockfile`` field names -- the bytes
    `npm ci` reads verbatim, pinning every transitive package the top one
    actually needs, not just the one this descriptor names -- and
    ``npm_package_name`` is that same lockfile's own root package name,
    which the synthesized `package.json` reuses verbatim rather than
    deriving from the descriptor's file stem.

    ``archive_members`` and ``archive_executable`` exist only for a `download`
    server whose asset is a compressed archive rather than a bare binary:
    ``archive_members`` names every file the archive is expected to hold, and
    ``archive_executable`` names which one of those is the program to run. A
    plain `download` server -- one asset, one file -- leaves both empty.

    ``argv`` exists for `download` and `npm`, the two forms that actually
    start a local process: the command-line arguments that process is
    started with, in order, after its own path. A `remote` server starts
    nothing, so declaring `argv` there would name arguments for a process
    that is never launched. Left empty, a server starts exactly as it did
    before this field existed -- some programs default to running an MCP
    server with no arguments at all, but at least one shipped server prints
    its usage and exits unless told which mode to run in, which is what
    `argv` exists to declare.
    """

    name: str
    description: str
    body: str
    distribution: Distribution
    endpoint: str
    source: PurePosixPath
    version: str | None = None
    checksum: str | None = None
    package: str | None = None
    integrity: str | None = None
    entry: str | None = None
    npm_lockfile: bytes | None = None
    npm_package_name: str | None = None
    archive_members: tuple[str, ...] = ()
    archive_executable: str | None = None
    argv: tuple[str, ...] = ()
    withheld_tools: tuple[str, ...] = ()
    """Tools this server exposes that a grant must never reach, named bare.

    An agent that declares this server's id is granted every tool it exposes,
    through the wildcard `_tools` and `_permission` write (`render.py`) --
    that wildcard is what lets a descriptor avoid enumerating a server's whole
    surface just to grant it. `withheld_tools` exists for the exception, not
    the rule: naming here is how a descriptor takes back the one or two tools
    that wildcard should never have reached in the first place -- typically
    something destructive or irreversible enough that no agent should get it
    merely by being granted the server's ordinary, cheap-to-use tools. Absent
    means the wildcard is trusted as written, which stays true for almost
    every server this repository ships.

    Named bare (`delete_project`, not `cbm_delete_project`): the qualified
    form only exists once a grant resolves against an actual key, and that key
    is decided at selection time -- the descriptor itself is written before
    any binding exists to qualify against.
    """
    reaches: tuple[str, ...] = ()
    """The agents this server is granted to, named by agent name.

    The declaration lives here, on the server, rather than on each agent,
    and the direction is the whole point. An agent file is engine-owned: a
    distribution overlays extra content files onto this tree but must never
    edit the files the engine ships. With the arrow pointing the other way --
    every agent listing the servers it wanted -- shipping one more server
    meant editing every agent file that should reach it, which a
    distribution cannot do. Pointing it this way makes adding a server an
    act of *adding files only*: one descriptor, one convention, one
    `reaches` list, and nothing the engine owns is touched.

    Required, and required to be non-empty -- a descriptor that reaches
    nobody installs a server no selection can ever grant (see
    `_require_mcp_reaches_an_agent`). Every name in it must be a shipped
    agent (see `_require_reaches_known_agents`).

    `Agent.optional_mcp` is the inverse of this field, computed once at load
    time; nothing downstream reads `reaches` directly.
    """

    bound_to: str | None = None
    """The key an installation already uses for this server, when it runs its own.

    A release describes a server two ways: how to obtain it, and how agents
    must behave once its tools exist. Only the first belongs to Pegasus by
    necessity. An installation that already administers this server has it
    under a key of its own choosing, at a version of its own choosing, and
    fetching a second copy is how two versions end up writing one store.

    Set, this says: the contract still travels, the tools are still granted --
    under this key, because that is what the runtime resolves -- and nothing
    is fetched, verified or written into the settings for it. Never a fact
    about the release, always about one installation, which is why it arrives
    through `select_mcp` and not from the descriptor.
    """

    @property
    def is_bound(self) -> bool:
        return self.bound_to is not None


@dataclass(frozen=True)
class McpSection:
    """One server's ambient half of the system prompt.

    A server's contract has two halves that are read at different moments. The
    ambient half is what every agent has to know the instant those tools exist
    in the session -- that memory is mandatory, that the graph comes before
    grep -- and it is worth the context it costs on every turn. The operational
    half is field formats, tool order, lifecycle states, and it is only needed
    on the turns that actually act; that half stays in
    `_shared/mcp/<id>-convention.md` and is read on demand.

    Kept out of the base body because a server nobody installed must leave no
    instruction behind: an ambient section for absent tools would tell agents
    to reach for something they were never granted, and they would have no way
    to tell that from their own mistake.
    """

    name: str
    body: str
    source: PurePosixPath


@dataclass(frozen=True)
class SystemPrompt:
    body: str
    source: PurePosixPath
    mcp_sections: tuple[McpSection, ...] = ()


@dataclass(frozen=True)
class Content:
    skills: tuple[Skill, ...] = ()
    agents: tuple[Agent, ...] = ()
    commands: tuple[Command, ...] = ()
    mcp: tuple[Mcp, ...] = ()
    system_prompt: SystemPrompt | None = None


def split_frontmatter(text: str, source: str = "<text>") -> tuple[dict[str, Any], str]:
    """Separate the descriptor from the body. Text without a marker has no descriptor."""
    if not text.startswith(MARKER + "\n"):
        return {}, text
    closing = text.find(f"\n{MARKER}\n", len(MARKER))
    if closing == -1:
        raise ContentError(f"{source}: frontmatter is never closed")
    try:
        fields = frontmatter.parse(text[len(MARKER) + 1 : closing + 1], source)
    except frontmatter.FrontmatterError as error:
        raise ContentError(str(error)) from error
    if not isinstance(fields, dict):
        raise ContentError(f"{source}: frontmatter must be a mapping of fields")
    return fields, text[closing + len(MARKER) + 2 :].lstrip("\n")


def load(root: ContentRoot = DEFAULT_ROOT) -> Content:
    """Read the whole content core, or refuse with the offending file named.

    ``root`` answers to the `Traversable` interface `importlib.resources`
    defines: `iterdir`, `is_dir`, `is_file`, `read_text`, `read_bytes` and
    `joinpath` (and the `/` operator that mirrors it). A real `pathlib.Path`
    satisfies that interface too, which is exactly what lets a test build a
    content tree on a real filesystem and hand its root here unchanged.
    """
    mcp = _load_mcp(root / "mcp", PurePosixPath("mcp"))
    agents = _load_agents(root / "agents", PurePosixPath("agents"), mcp)
    _require_reaches_known_agents(agents, mcp)
    _require_mcp_convention_referenced(agents, mcp)
    _require_mcp_reaches_an_agent(mcp)
    system_prompt = _load_system_prompt(root / SYSTEM_PROMPT_DIR, PurePosixPath(SYSTEM_PROMPT_DIR))
    _require_known_system_prompt_mcp(system_prompt, mcp)
    return Content(
        skills=_load_skills(root / "skills", PurePosixPath("skills")),
        agents=agents,
        commands=_load_commands(root / "commands", PurePosixPath("commands")),
        mcp=mcp,
        system_prompt=system_prompt,
    )


#: What a bound server's key may hold. Deliberately narrower than "anything
#: non-blank": the key becomes a permission rule verbatim, and the runtime reads
#: `*` and `?` inside a rule name as a pattern. Everything real keys are made of
#: -- `codebase-memory-mcp`, `engram`, `context7` -- fits inside this.
_SERVER_KEY = re.compile(r"[A-Za-z0-9._-]+")


def parse_mcp_choice(spelling: str) -> tuple[str, str | None]:
    """One `--mcp` value, as an id and the key it is bound to, if any.

    Two spellings, and the second is the whole point of the first being
    ambiguous today: `cbm` asks Pegasus to obtain and administer the server,
    `cbm=codebase-memory-mcp` asks it only for the contract, against a server
    the installation already runs under that key.

    A key that is blank, or a value with more than one `=`, is refused rather
    than guessed: both would otherwise produce a grant naming a server no
    runtime resolves, which fails as tools quietly missing rather than as a
    message anyone reads.

    A key carrying a character the runtime reads as a wildcard is refused for a
    heavier reason. The key is spliced verbatim into a permission rule -- the
    grant is written `f"{key}*"` -- and the runtime matches a rule *name* by
    wildcard. So `=*` renders `**`, a rule matching every action name there is,
    written after the deny baseline and therefore beating it for everything the
    agent was never granted: not a weakened grant but the removal of the whole
    per-agent restriction that baseline exists to impose. The same key is
    spliced into the other side of the grant too -- a withheld tool is denied
    as `f"{key}_{tool}"` -- where the failure is the mirror image: a deny that
    matches nothing while looking exactly like protection. A rule cannot be
    told apart from one somebody meant once it is in the map, so the refusal
    has to happen here, where the value is still something a person typed.
    """
    if "=" not in spelling:
        return spelling.strip(), None
    parts = spelling.split("=")
    if len(parts) != 2:
        raise ContentError(
            f"cannot read mcp choice {spelling!r}: expected 'id' or 'id=server-key'"
        )
    server_id, key = (part.strip() for part in parts)
    if key and not _SERVER_KEY.fullmatch(key):
        raise ContentError(
            f"cannot read mcp choice {spelling!r}: {key!r} is not usable as a server key; "
            f"a key may hold letters, digits, '.', '_' and '-', and nothing a runtime "
            f"reads as a wildcard"
        )
    if not server_id or not key:
        raise ContentError(
            f"cannot read mcp choice {spelling!r}: both an id and a server key are required"
        )
    return server_id, key


def select_mcp(content: Content, chosen: Iterable[str]) -> Content:
    """Keep only the mcp servers the user chose, and only the `optional_mcp`
    entries that name them.

    An adapter renders one item at a time -- one `Mcp`, one `Agent` -- and never
    sees the whole content tree, so it has no way to know which servers the user
    picked; a per-item renderer could not apply this choice even if it wanted to.
    Applying it once, here, before anything is rendered, is what lets every
    adapter -- and a future interactive surface -- stay unaware that a choice was
    ever made: they only ever see the servers that survived it.

    Choosing nothing is the default this returns: a `Content` with no servers and
    no agent declaring one, because a server nobody named does not install.
    """
    known = {server.name for server in content.mcp}
    bindings = dict(parse_mcp_choice(spelling) for spelling in chosen)
    unknown = sorted(name for name in bindings if name not in known)
    if unknown:
        raise ContentError(
            f"chose unknown mcp server(s) {', '.join(unknown)}; "
            f"the servers this release ships are: {', '.join(sorted(known)) or 'none'}"
        )
    kept = set(bindings)
    by_name = {server.name: server for server in content.mcp}
    return replace(
        content,
        mcp=tuple(
            replace(server, bound_to=bindings[server.name])
            for server in content.mcp
            if server.name in kept
        ),
        agents=tuple(
            replace(
                agent,
                optional_mcp=tuple(
                    bindings[name] or name for name in agent.optional_mcp if name in kept
                ),
                mcp_sections=tuple(
                    section for section in agent.mcp_sections if section.name in kept
                ),
                denied_mcp_tools=_denied_mcp_tools(agent, by_name, bindings, kept),
            )
            for agent in content.agents
        ),
        system_prompt=_select_system_prompt_mcp(content.system_prompt, kept),
    )


def _denied_mcp_tools(
    agent: Agent, by_name: dict[str, Mcp], bindings: dict[str, str | None], kept: set[str]
) -> tuple[str, ...]:
    """The fully-qualified names this agent's grants must not extend to.

    Built here rather than left for the renderer because this is the one place
    that holds both halves of the fact: the descriptor's own `withheld_tools`
    -- bare names, since the descriptor is written before any binding exists
    -- and the key each granted server actually resolves under once selection
    and binding are settled, exactly the key `optional_mcp` itself is rewritten
    to two lines above. A tool named under the id when the server was bound to
    a different key would deny something the runtime never matches, leaving
    the wildcard grant it was meant to narrow fully intact.
    """
    return tuple(
        f"{bindings[server_id] or server_id}_{tool}"
        for server_id in agent.optional_mcp
        if server_id in kept
        for tool in by_name[server_id].withheld_tools
    )


def _select_system_prompt_mcp(
    system_prompt: SystemPrompt | None, kept: set[str]
) -> SystemPrompt | None:
    """The same choice, applied to the ambient half.

    The base body is never touched: it says what is true whatever the user
    installed. Only the per-server sections answer to the choice, and they
    answer to it exactly as `optional_mcp` does -- so an agent's grant and the
    instruction telling it to use that grant can never disagree about which
    servers exist.
    """
    if system_prompt is None:
        return None
    return replace(
        system_prompt,
        mcp_sections=tuple(
            section for section in system_prompt.mcp_sections if section.name in kept
        ),
    )


def per_agent_mcp_keys(content: Content) -> frozenset[str]:
    """Every mcp key this installation already reaches on a *per-agent*
    basis: a shipped server's own id (`content.mcp`, already narrowed by
    `select_mcp` to what this install actually chose) or a key already
    resolved into some agent's `optional_mcp` -- an id or a bound key,
    `select_mcp` writes the same value either way. Granting any of these
    again, uniformly to every agent, would undo whatever per-agent shape is
    already in place: one agent may carry a server another does not, or have
    some of its tools withheld through `denied_mcp_tools`.

    Pure and non-raising on purpose, with exactly two callers meant to agree
    forever: `grant_mcp` below turns a collision against this same set into
    a refusal, and `cli.mcp_list` asks the identical question to report
    which of a CLI's own declared keys are already covered rather than
    actually grantable -- the fact `mcp list` must never advertise as
    available a key `mcp grant` would then refuse. Both ask this function,
    not each other and not a second computation of their own, so the two can
    never drift apart.
    """
    shipped = {server.name for server in content.mcp}
    bound = {name for agent in content.agents for name in agent.optional_mcp}
    return frozenset(shipped | bound)


def grant_mcp(
    content: Content, keys: Iterable[str], *, droppable: Iterable[str] = ()
) -> tuple[Content, tuple[str, ...]]:
    """Grant a fixed set of user-administered MCP server keys to every agent.

    Mirrors `select_mcp`'s own reasoning, reused rather than restated: an
    adapter renders one `Agent` at a time and never sees the whole content
    tree, so applying this choice once, here, before anything is rendered, is
    what lets every adapter -- and a future interactive surface -- stay
    unaware a choice was ever made. Unlike `select_mcp`, this never touches
    `content.mcp` or `optional_mcp`: it only sets `Agent.granted_mcp`, and it
    sets it identically on every agent, because per-agent granting was
    rejected as the whole point of this feature -- adding one more server a
    person administers themselves must never mean editing more than one
    place.

    A key's *shape* is refused through `_SERVER_KEY` -- the same regex
    `parse_mcp_choice` uses, imported rather than restated, so the two never
    have a chance to disagree about what a safe key looks like. This is the
    same class of bug `parse_mcp_choice`'s own docstring describes: a key is
    spliced verbatim into a permission rule (`f"{key}*"`), and the runtime
    reads `*`/`?` inside a rule name as a wildcard, so an unvalidated key such
    as `*` renders `**` -- a rule that matches every action there is, beating
    the per-agent deny baseline for everything the agent was never granted.
    The guard has to live *here*, in `core`, rather than only at the CLI
    layer that first collects a key from a person: `cli.mcp_grant` is one way
    a key reaches this function, but the journal is another (`update` and
    `mcp revoke` both replay a previous install's `granted_mcp` straight
    through this same call), and a CLI-level check cannot protect a replay
    that never goes through the CLI's own validation again. Whatever
    survives to be a `keys` argument here -- typed fresh or replayed from
    disk -- must be safe on its own, so the check belongs where every caller
    is forced through it.

    A key is refused for *collision* when `per_agent_mcp_keys(content)`
    already names it -- see that function's own docstring for exactly what
    it covers and its other caller. Every such key is a server Pegasus
    already grants on a *per-agent* basis, deliberately: one agent may carry
    a server another does not, or may have some of its tools withheld
    through `denied_mcp_tools`. Granting the same key again here would apply
    it uniformly to every agent regardless of that per-agent shape, silently
    undoing whatever narrowing the release or the user's own `--mcp` binding
    put in place.

    `droppable` names the subset of `keys` this call may silently drop on a
    collision instead of raising -- the caller's way of saying "this key
    is only carried forward from a previous install, not something the
    person just asked for in this exact call". A grant a person carried
    forward (a plain `install` with no `--grant` flag of its own, or `update`
    replaying a previous install verbatim) that a fresh `--mcp` binding has
    made redundant is dropped rather than aborting the whole operation: the
    server stays reachable through the agents that now declare it, so
    nothing the person wanted is lost, and failing an unrelated install over
    a now-redundant grant is disproportionate. A key outside `droppable` --
    something named explicitly in this same call, such as the key argument
    to `cli.mcp_grant` -- still raises on collision, because there the
    collision is a real contradiction in what was just asked for, not a
    leftover. The second element of the return value is exactly the keys
    this call dropped, so a caller can both report them and keep whatever it
    records (a journal, a report) from claiming a grant this call did not
    actually apply.
    """
    granted = tuple(keys)
    if not granted:
        return (
            replace(content, agents=tuple(replace(agent, granted_mcp=()) for agent in content.agents)),
            (),
        )
    malformed = sorted(key for key in set(granted) if not _SERVER_KEY.fullmatch(key))
    if malformed:
        raise ContentError(
            f"cannot grant {', '.join(map(repr, malformed))}: not usable as a server key; a key may "
            f"hold letters, digits, '.', '_' and '-', and nothing a runtime reads as a wildcard -- the "
            f"same shape `--mcp id=key` requires, refused here because a key becomes a permission rule "
            f"verbatim and this is the one place every granted key, typed fresh or replayed from a "
            f"journal, is forced through"
        )
    collisions = set(granted) & per_agent_mcp_keys(content)
    droppable_set = frozenset(droppable)
    raising = sorted(collisions - droppable_set)
    if raising:
        raise ContentError(
            f"cannot grant {', '.join(raising)}: already granted per-agent by this "
            f"installation (a shipped mcp server or a key already bound); re-granting it to "
            f"every agent here would undo whatever per-agent narrowing is already in place"
        )
    dropped = tuple(sorted(collisions & droppable_set))
    kept = tuple(key for key in granted if key not in collisions)
    return (
        replace(content, agents=tuple(replace(agent, granted_mcp=kept) for agent in content.agents)),
        dropped,
    )


#: Characters the runtime's own glob-to-regex translation gives special
#: meaning to inside a permission rule name. `*` and `?` are confirmed by
#: `_SERVER_KEY` above, for the identical reason -- a granted directory
#: reaches `f"{path}/*": "allow"` exactly as verbatim as a bound server key
#: reaches its own rule. `[` and `]` are not confirmed the same way, but a
#: value that lands in a permission rule unexamined is exactly the place to
#: refuse more than the runtime is proven to special-case rather than less:
#: rejecting a bracket a real path was never going to contain costs nothing,
#: and guessing wrong in the other direction costs a permission escape.
_DIRECTORY_GLOB_METACHARACTERS = frozenset("*?[]")


def validate_granted_directory(raw: Any, *, config_dir: Path, data_dir: Path | None = None) -> str:
    """Refuse anything that could not safely become an
    `f"{path}/*": "allow"` entry in a rendered `external_directory` map, and
    return the one normalized spelling every caller must agree to persist.

    The one place every granted directory -- typed fresh through `pegasus
    directory grant`, or replayed from a journal by `update`/`directory
    revoke`, neither of which ever asks the CLI-level checks again -- is
    forced through, the same discipline `grant_mcp` already applies to a
    key's shape for the same reason: a value that reaches a permission rule
    verbatim must be safe on its own, not merely safe the one time a person
    typed it.

    Absolute and free of `..`, the same two structural checks
    `journal._contained` already makes for every other path this codebase
    persists -- judged by shape alone, never by resolving anything against a
    disk this module never touches.

    Free of every glob metacharacter the runtime's own pattern matching
    treats specially (`_DIRECTORY_GLOB_METACHARACTERS`, above) -- `*` above
    all: the runtime's glob-to-regex translation lets `*` cross `/`, so a
    granted directory that itself contains `*` can widen the single
    `f"{path}/*": "allow"` entry this function's caller writes into a rule
    that reaches far more than the one directory the person meant to name.
    `/` alone is refused by the identical fact stated as its own case just
    below, because a bare `/` carries no metacharacter for this check to
    catch on its own.

    `/` is refused by name: `*` crosses `/` in the runtime's own glob
    matching, so `f"{path}/*"` for `path == "/"` renders `"/*"`, a pattern
    that matches every absolute path there is -- not a working directory
    grant at that point, but a second, wide-open deny baseline with the
    opposite value.

    The CLI's own configuration directory, and any path that is an ancestor
    of it, are refused for a narrower reason: that directory holds the
    settings file with whatever the person configured of their own servers,
    and `_permission` above already grants only the skills subtree beneath
    it, deliberately, rather than the configuration directory that contains
    it -- see its own docstring. Granting an ancestor of that directory would
    reopen exactly the exception this product already decided against, only
    through a different door. A directory *inside* the configuration
    directory that is not one of its ancestors -- some other subtree beside
    skills -- is not refused here: nothing about this check claims to know
    every such subtree's purpose, only that the configuration directory
    itself, and anything wide enough to contain it, must stay closed.

    Pegasus's own data directory -- `data_dir`, where `FileJournalStore`
    keeps this journal itself -- is refused the identical way, for the
    identical shape of reason: `write` on that directory is `write` on the
    journal `uninstall` later reads uncritically to decide what it may
    delete. Granting it (or an ancestor of it) to every agent turns an
    ordinary file write into arbitrary deletion at the next `uninstall`,
    which is a worse outcome than anything the configuration-directory
    refusal above guards against, not a smaller version of it. `data_dir` is
    optional -- `None` when a caller has no journal-store context to ask,
    `validate_granted_directory` used directly from a unit test, say -- and
    the check is simply skipped then, the same way the config-directory
    check already requires its own caller to supply `config_dir`. No other
    directory on the machine is refused this way: the two closed here are
    closed because Pegasus itself depends on them staying intact, not
    because either is otherwise sensitive, and widening this list to
    "anything that looks important" would refuse the very thing this field
    exists to grant.

    Deliberately not checked against the person's home directory the way
    `journal._contained` checks every other path this codebase owns: a
    legitimate working directory -- a linked worktree, a scratch tree a
    tool writes into -- can sit anywhere on the machine, outside the home
    entirely, and refusing that here would refuse the very thing this field
    exists to grant.

    The path returned is always `Path(raw).as_posix()` -- the one normalized
    spelling `pathlib` collapses a trailing slash, a repeated `/`, and a bare
    `.` component down to. Every caller that persists a granted directory --
    the journal, the render, `directory grant`'s own report, `directory
    revoke`'s own comparison -- must persist and compare this return value
    and never the raw string a person typed, or two equivalent spellings of
    the same directory silently fail to match each other.
    """
    if not isinstance(raw, str) or not raw:
        raise ContentError("cannot grant a directory: a granted directory needs a non-empty path")
    path = Path(raw)
    if not path.is_absolute():
        raise ContentError(f"cannot grant {raw!r}: a granted directory must be an absolute path")
    if ".." in path.parts:
        raise ContentError(f"cannot grant {raw!r}: a granted directory must not climb out of itself with '..'")
    found = sorted(_DIRECTORY_GLOB_METACHARACTERS.intersection(raw))
    if found:
        raise ContentError(
            f"cannot grant {raw!r}: it contains {''.join(found)!r}, a character the runtime's own glob "
            f"matching treats specially in a permission rule -- a granted directory reaches a rendered "
            f"rule verbatim, so a metacharacter here could widen the grant far past the one directory "
            f"this was meant to name"
        )
    if path == Path(path.anchor):
        raise ContentError(
            f"cannot grant {raw!r}: granting the filesystem root would concede every path there is, "
            f"since a runtime whose glob patterns cross '/' resolves '/*' as matching everything"
        )
    if config_dir == path or config_dir.is_relative_to(path):
        raise ContentError(
            f"cannot grant {raw!r}: it is the CLI's own configuration directory, or an ancestor of "
            f"it -- that directory holds the settings file with whatever the person configured of "
            f"their own servers, and this product already grants only the skills subtree beneath it, "
            f"on purpose, not the configuration directory that contains it; granting an ancestor here "
            f"would reopen exactly that door"
        )
    if data_dir is not None and (data_dir == path or data_dir.is_relative_to(path)):
        raise ContentError(
            f"cannot grant {raw!r}: it is this product's own data directory, or an ancestor of it -- "
            f"that directory holds the journal that `uninstall` reads to decide what it may delete, "
            f"and granting write access to it would let an agent's own write turn into arbitrary "
            f"deletion at the next uninstall"
        )
    return path.as_posix()


def grant_directories(
    content: Content, paths: Iterable[str], *, config_dir: Path, data_dir: Path | None = None
) -> Content:
    """Grant a fixed set of directories, of the person's own choosing, to
    every agent's `external_directory` permission.

    Mirrors `grant_mcp`'s own shape: applied once here, before anything is
    rendered, so every adapter renders the grant without ever knowing a
    choice was made, and set identically on every agent for the reason
    `Agent.granted_directories` documents. Unlike `grant_mcp`, there is no
    collision to refuse -- a granted directory shares no namespace with
    anything Pegasus already renders per-agent -- so every path this call
    validates is simply carried onto every agent, in the order given.

    Each path is validated by `validate_granted_directory`, imported by
    `journal` rather than restated there, so the two can never drift apart
    about what a safe directory grant looks like. That import is why the name
    carries no leading underscore: a rule two modules share is part of this
    one's interface, whatever its first character would otherwise claim.
    """
    validated = tuple(
        validate_granted_directory(raw, config_dir=config_dir, data_dir=data_dir) for raw in paths
    )
    return replace(
        content, agents=tuple(replace(agent, granted_directories=validated) for agent in content.agents)
    )


def _load_skills(directory: ContentRoot, relative_dir: PurePosixPath) -> tuple[Skill, ...]:
    skills = []
    for item in _subdirectories(directory):
        item_relative = relative_dir / item.name
        descriptor = item / SKILL_FILE
        source = item_relative / SKILL_FILE
        if not descriptor.is_file():
            raise ContentError(f"{item_relative}: a skill directory needs a {SKILL_FILE}")
        fields, _ = split_frontmatter(descriptor.read_text(encoding="utf-8"), str(source))
        _require_name(fields, item.name, source)
        assets = _assets(item)
        _refuse_verbatim_placeholders(assets, source)
        skills.append(
            Skill(
                name=item.name,
                description=_text(fields, "description", source),
                assets=assets,
                source=source,
            )
        )
    return tuple(skills)


def _load_agents(
    directory: ContentRoot, relative_dir: PurePosixPath, mcp: tuple[Mcp, ...]
) -> tuple[Agent, ...]:
    paths = _markdown_files(directory)
    agent_names = {_stem(path) for path in paths}
    known_mcp = {server.name for server in mcp}
    shared, overrides = _load_agent_mcp_sections(
        directory / AGENT_MCP_DIR, relative_dir / AGENT_MCP_DIR, agent_names, known_mcp
    )
    reached_by = _reached_by(mcp)
    agents = []
    for path in paths:
        fields, body, source = _descriptor(path, relative_dir)
        _refuse_derived_fields(fields, source)
        _refuse_relation_keys_in_an_agent(fields, source)
        name = _stem(path)
        optional_mcp = reached_by.get(name, ())
        mcp_sections = tuple(
            overrides[(mcp_id, name)] if (mcp_id, name) in overrides else shared[mcp_id]
            for mcp_id in optional_mcp
            if mcp_id in shared or (mcp_id, name) in overrides
        )
        agents.append(
            Agent(
                name=name,
                description=_text(fields, "description", source),
                body=body,
                mode=_choice(fields, "mode", AgentMode, source),
                source=source,
                requires_tools=_names(fields, "requires_tools", source),
                optional_tools=_names(fields, "optional_tools", source),
                optional_mcp=optional_mcp,
                may_delegate_to=_names(fields, "may_delegate_to", source),
                model_configurable=_flag(fields, "model_configurable", source),
                mcp_sections=mcp_sections,
            )
        )
    _require_every_override_is_wired(overrides, tuple(agents), mcp)
    _require_the_session_start(tuple(agents), relative_dir)
    return tuple(agents)


def _reached_by(mcp: tuple[Mcp, ...]) -> dict[str, tuple[str, ...]]:
    """Invert every descriptor's `reaches` into one agent-name -> server-ids map.

    Built once for the whole directory rather than re-walked per agent, and
    sorted by server id so the order is deterministic and reproduces exactly
    what the alphabetical hand-written `optional_mcp` lists used to produce.

    Names here are not validated against the shipped agents: a `reaches`
    entry naming nothing is a real failure, but it is one
    `_require_reaches_known_agents` reports against the descriptor that wrote
    it, which is the file an author has to edit. Silently landing in this map
    and reaching nobody is exactly what that invariant exists to prevent.
    """
    reached: dict[str, list[str]] = {}
    for server in sorted(mcp, key=lambda item: item.name):
        for agent_name in server.reaches:
            reached.setdefault(agent_name, []).append(server.name)
    return {name: tuple(ids) for name, ids in reached.items()}


def _load_agent_mcp_sections(
    directory: ContentRoot,
    relative_dir: PurePosixPath,
    agent_names: set[str],
    known_mcp: set[str],
) -> tuple[dict[str, McpSection], dict[tuple[str, str], McpSection]]:
    """Every agent-side section this tree ships, shared or narrowed to one agent.

    Returns the two maps `_load_agents` resolves each agent's `mcp_sections`
    from: `id -> McpSection` for a file with no `@` in its stem, and
    `(id, agent) -> McpSection` for one that names an override. Kept apart
    rather than merged into one lookup keyed by `(id, agent | None)`, because
    the two failure modes below read from different sets -- `known_mcp` alone
    for the first, `agent_names` alone for the second -- and merging the maps
    would not have merged the checks.

    Both checks run the moment a file is read, before any agent even asks for
    it: a section for a server nothing ships, or an override for an agent that
    was renamed or removed, would otherwise sit in the tree looking wired in
    and reach nobody -- the same silent failure `_require_reaches_known_agents`
    and `_require_the_session_start` each exist to turn into a load-time
    refusal instead.

    The third way an override reaches nobody cannot be checked here, and is
    checked in `_require_every_override_is_wired` once the agents exist: an
    override addressed to an agent that never declared that id. Naming a real
    agent is not the same as naming a listening one, and at this point no
    agent has been parsed yet, so there is nothing here to ask.
    """
    shared: dict[str, McpSection] = {}
    overrides: dict[tuple[str, str], McpSection] = {}
    for path in _markdown_files(directory):
        source = relative_dir / path.name
        stem = _stem(path)
        match = _AGENT_MCP_OVERRIDE.match(stem)
        mcp_id = match.group("mcp_id") if match else stem
        if mcp_id not in known_mcp:
            raise ContentError(
                f"{source}: is an agent section for {mcp_id!r}, which no mcp server declares"
            )
        _, body = split_frontmatter(path.read_text(encoding="utf-8"), str(source))
        _require_known_placeholders(body, source)
        section = McpSection(name=mcp_id, body=body, source=source)
        if match is None:
            shared[mcp_id] = section
            continue
        agent_name = match.group("agent")
        if agent_name not in agent_names:
            raise ContentError(
                f"{source}: overrides the {mcp_id!r} section for {agent_name!r}, "
                f"which is not one of the shipped agents"
            )
        overrides[(mcp_id, agent_name)] = section
    return shared, overrides


def _require_every_override_is_wired(
    overrides: dict[tuple[str, str], McpSection],
    agents: tuple[Agent, ...],
    servers: tuple[Mcp, ...],
) -> None:
    """An override addressed to an agent that never declared the id reaches nobody.

    `_load_agent_mcp_sections` already refuses an override naming a server
    nothing ships and one naming an agent that does not exist. This is the
    third way the same file can be dead on arrival, and the likeliest of the
    three: the agent is real and the server is real, but that server's
    `reaches` list never names that agent, so the resolution -- which walks
    the agent's derived `optional_mcp`, not the directory -- never looks the
    file up. An author who writes the framing and forgets the grant gets no
    error, no section, and no way to tell that from having written the
    framing badly.

    Still true under derivation, and still worth checking: `optional_mcp` is
    now the inverse of the `reaches` lists rather than a hand-written line,
    but an override file is not part of that relation at all -- it is a third
    file naming a pair, and nothing about deriving the pair from one end
    guarantees some *other* file spelled the same pair correctly. What
    changed is only where the fix goes, so the message says so -- naming the
    descriptor by its own `source`, the way `_require_mcp_convention_referenced`
    does, rather than rebuilding that path from the id and trusting the two to
    keep the same shape.

    It cannot be checked where the other two are: at that point no agent has
    been parsed, so nothing knows what any of them was granted.
    """
    granted = {(mcp_id, agent.name) for agent in agents for mcp_id in agent.optional_mcp}
    source_of = {server.name: server.source for server in servers}
    for (mcp_id, agent_name), section in sorted(overrides.items()):
        if (mcp_id, agent_name) not in granted:
            raise ContentError(
                f"{section.source}: overrides the {mcp_id!r} section for {agent_name!r}, "
                f"which the 'reaches' list of {source_of[mcp_id]} does not name"
            )


def _require_the_session_start(agents: tuple[Agent, ...], relative_dir: PurePosixPath) -> None:
    """The agent a session opens in has to be here, and has to be able to open one.

    `SESSION_STARTS_IN` decides who that is, so nothing on disk can claim it twice
    or leave it unclaimed. What disk still decides is whether that agent exists and
    what mode it is in, and a session opens in a primary agent.

    A tree with no agents chooses between nothing and is left alone.
    """
    if not agents:
        return
    starts = next((agent for agent in agents if agent.name == SESSION_STARTS_IN), None)
    if starts is None:
        raise ContentError(
            f"{relative_dir}: no agent is named {SESSION_STARTS_IN!r}, "
            f"which is where a session starts"
        )
    if starts.mode is not AgentMode.PRIMARY:
        raise ContentError(
            f"{starts.source}: {SESSION_STARTS_IN!r} is where a session starts, so its "
            f"'mode' must be {AgentMode.PRIMARY.value!r}, not {starts.mode.value!r}"
        )


def _require_reaches_known_agents(agents: tuple[Agent, ...], servers: tuple[Mcp, ...]) -> None:
    """A `reaches` entry naming no shipped agent is a typo that costs one
    recipient, silently.

    The typo this catches changed shape when the declaration changed
    direction. It used to be an agent naming a server nothing ships -- a
    permission the agent believed might arrive and never could. Now a
    misspelled name in `reaches` cannot produce a phantom grant at all: the
    inversion in `_reached_by` simply keys it under an agent that does not
    exist, and nothing ever looks it up. The descriptor loads, the server
    installs, every other name in the list works -- and the server reaches
    one agent fewer than its author wrote down. Nothing else in the tree
    would ever say so: there is no file the missing grant is absent from,
    only a list that is one name shorter than intended. Checking here, once,
    against the agents actually shipped, is the only thing standing between
    that typo and a release.
    """
    known = {agent.name for agent in agents}
    for server in servers:
        unknown = [name for name in server.reaches if name not in known]
        if unknown:
            raise ContentError(
                f"{server.source}: 'reaches' names {', '.join(sorted(unknown))}, "
                f"which is not one of the shipped agents"
            )


def _refuse_repeated_reaches(reaches: tuple[str, ...], source: PurePosixPath) -> None:
    """A name written twice in one `reaches` list is refused, not collapsed.

    `_reached_by` inverts these lists by appending, so a repeated name arrives
    at its agent twice: the server id lands twice in `optional_mcp`, which puts
    the same section twice in `mcp_sections` and the same withheld tools twice
    in `denied_mcp_tools`. The rendered prompt then carries that server's whole
    framing twice, which nothing downstream notices and no invariant catches.

    De-duplicating quietly would hide the mistake instead of surfacing it, and
    the mistake is the interesting part: nobody means to grant one agent the
    same server twice. Refusing says so at the only moment anyone can still
    ask what the author intended.

    This is not a rule about ordering. The authored order of `reaches` is
    discarded already -- the inversion sorts by server id, so how the names sit
    in the list changes nothing. What is refused is a name *appearing more than
    once*, because that can only mean something other than what was written.

    The hazard grew with the direction. Under the old one a duplicate had to be
    written inside a single agent's list of five; `engram` now declares thirteen
    names on one line, and every agent added later appends to it.
    """
    seen: set[str] = set()
    repeated = sorted({name for name in reaches if name in seen or seen.add(name)})
    if repeated:
        raise ContentError(
            f"{source}: 'reaches' names {', '.join(repeated)} more than once; "
            f"a server reaches an agent or it does not"
        )


def _require_mcp_reaches_an_agent(servers: tuple[Mcp, ...]) -> None:
    """A shipped server that reaches no agent is a permission nobody can ever grant.

    Now that the declaration points this way, this check is very nearly the
    declaration itself: it is `reaches` being empty, nothing more. That is a
    demotion worth stating plainly -- it used to have to reconcile thirteen
    agent files against five descriptors to notice, and the fact it can no
    longer be surprised by anything is the point of the inversion, not a
    reason to drop it. It is also what makes `reaches` *required* rather than
    merely parsed: an absent key and an empty list both arrive here as `()`,
    and both are refused in one place.

    The failure it exists for is unchanged. `select_mcp` filters both
    `content.mcp` and every agent's `optional_mcp` down to what the user
    chose, once, before any adapter renders. A server that reaches nobody
    survives that filter with an empty set of recipients for every choice a
    user could make -- there is no `--mcp` selection under which it grants
    anything. Choosing it still fetches the server, writes it into the user's
    runtime config, and turns it on: the failure is not a missing file or a
    load error, it is a server that installs, configures, and reaches nobody.
    That is not hypothetical -- it is exactly how the Playwright MCP shipped:
    a descriptor, a README promise that confirming it configures the server,
    and not one of the twelve shipped agents granted it. Under the old
    direction that state took a whole cross-file reconciliation to see; under
    this one it is a blank line in the descriptor, which is the improvement.

    The old leniency for a tree with no agents at all is gone, and its reason
    went with it: it existed because the check read the agents, so with none
    there was nothing to read. This check no longer reads them. A descriptor
    with an empty `reaches` is malformed whatever else the tree contains, and
    a tree with agents in it is not what makes that true.
    """
    for server in servers:
        if not server.reaches:
            raise ContentError(
                f"{server.source}: 'reaches' names no agent, so choosing this server "
                f"would install one that reaches nobody"
            )


def _require_mcp_convention_referenced(
    agents: tuple[Agent, ...], servers: tuple[Mcp, ...]
) -> None:
    """A granted server and its convention reference have to travel together.

    The permission is granted from the descriptor's `reaches` list alone:
    naming an agent there hands it that server's tools, with nothing else read
    from either file. Left one-directional, that makes two states
    representable that should not be: a server that reaches an agent whose
    body never mentions the convention, and a body that points at a convention
    for a server that never reaches it -- an agent told to follow a convention
    for tools it will never have. Both directions have to agree, so the set of
    ids reaching an agent and the set of ids its prose references are required
    to be exactly equal.

    What that buys on the *shipped* tree is narrower than the sentence above
    sounds, and the gap is worth naming rather than leaving for a reader to
    discover. No shipped agent body references a convention at all -- a test
    forbids it, because that is exactly what moved out of twelve unconditional
    prompts -- so `referenced` comes entirely from the sections, and the
    sections are resolved from the grant. On shipped content the equality is
    therefore satisfied the moment each shared or override section carries its
    own pointer, and that is the one thing this check is really enforcing
    there: drop the pointer from `agents/mcp/<id>.md` and it fires.

    Both directions are live for a tree that does write a pointer inline,
    which the loader supports and a distribution may well use, so neither is
    dead code. But this invariant was not made stronger or weaker by the
    inversion: it read a declared set before and reads a derived one now, and
    the same one-sided softness on shipped content was already there when the
    declaration lived in the agent file.

    The two halves live in two files now, and the messages below say which:
    a grant is added or removed in `content/mcp/<id>.md`, the pointer in the
    agent's own body or its section under `agents/mcp/`. `servers` is threaded
    in for exactly that -- so the error names the descriptor's real path
    rather than one reconstructed here.

    "The body" here means the agent's own prose together with every section
    `mcp_sections` resolved for it: the pointer this invariant looks for now
    usually lives in the shared or overriding section itself, not in the
    agent's own file, because that is exactly what moved it out of twelve
    unconditional prompts. An agent that still writes the pointer inline,
    with no section behind it, still satisfies this the same way it always
    did -- the two places are read together, never one to the exclusion of
    the other.
    """
    sources = {server.name: str(server.source) for server in servers}
    for agent in agents:
        granted = set(agent.optional_mcp)
        referenced = _referenced_mcp_ids(agent.body)
        for section in agent.mcp_sections:
            referenced |= _referenced_mcp_ids(section.body)
        if granted == referenced:
            continue
        problems = []
        for server_id in sorted(granted - referenced):
            expected = "{{skills_root}}/" + mcp_convention_path(server_id).as_posix()
            where = sources.get(server_id, f"mcp/{server_id}.md")
            problems.append(
                f"is named in the 'reaches' list of {where} but its body never references "
                f"{expected!r}"
            )
        for server_id in sorted(referenced - granted):
            expected = "{{skills_root}}/" + mcp_convention_path(server_id).as_posix()
            where = sources.get(server_id, f"mcp/{server_id}.md")
            problems.append(
                f"references {expected!r} but the 'reaches' list of {where} does not name it"
            )
        raise ContentError(f"{agent.source}: " + "; ".join(problems))


def _load_commands(directory: ContentRoot, relative_dir: PurePosixPath) -> tuple[Command, ...]:
    commands = []
    for path in _markdown_files(directory):
        fields, body, source = _descriptor(path, relative_dir)
        commands.append(
            Command(
                name=_stem(path),
                description=_text(fields, "description", source),
                body=body,
                runs_as=_choice(fields, "runs_as", RunsAs, source),
                execution=_choice(fields, "execution", Execution, source),
                source=source,
            )
        )
    return tuple(commands)


_CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
_INTEGRITY = re.compile(r"^sha512-[A-Za-z0-9+/]+=*$")

_FORM_FIELDS: dict[Distribution, tuple[str, ...]] = {
    Distribution.REMOTE: (),
    Distribution.DOWNLOAD: ("version", "checksum", "archive_members", "archive_executable", "argv"),
    Distribution.NPM: ("package", "version", "integrity", "entry", "lockfile", "argv"),
}
"""Which extra fields each distribution's form declares.

Every field named here belongs to exactly one form. A stray field left over
from a copy-pasted descriptor is a refusal, not a value nothing ever reads.
"""

_ALL_FORM_FIELDS = frozenset(name for names in _FORM_FIELDS.values() for name in names)


def _load_mcp(directory: ContentRoot, relative_dir: PurePosixPath) -> tuple[Mcp, ...]:
    servers = []
    for path in _markdown_files(directory):
        fields, body, source = _descriptor(path, relative_dir)
        distribution = _choice(fields, "distribution", Distribution, source)
        _refuse_foreign_form_fields(fields, distribution, source)
        version, checksum = _download_form(fields, distribution, source)
        package, npm_version, integrity, entry, npm_lockfile, npm_package_name = _npm_form(
            fields, distribution, directory, source
        )
        archive_members, archive_executable = _archive_form(fields, distribution, source)
        argv = _names(fields, "argv", source)
        withheld_tools = _names(fields, "withheld_tools", source)
        reaches = _names(fields, "reaches", source)
        _refuse_repeated_reaches(reaches, source)
        servers.append(
            Mcp(
                name=_stem(path),
                description=_text(fields, "description", source),
                body=body,
                distribution=distribution,
                endpoint=_text(fields, "endpoint", source),
                source=source,
                version=version if version is not None else npm_version,
                checksum=checksum,
                package=package,
                integrity=integrity,
                entry=entry,
                npm_lockfile=npm_lockfile,
                npm_package_name=npm_package_name,
                archive_members=archive_members,
                archive_executable=archive_executable,
                argv=argv,
                withheld_tools=withheld_tools,
                reaches=reaches,
            )
        )
    return tuple(servers)


def _refuse_foreign_form_fields(
    fields: dict[str, Any], distribution: Distribution, source: PurePosixPath
) -> None:
    """A field belonging to a different form's distribution is a refusal."""
    allowed = _FORM_FIELDS[distribution]
    stray = sorted(key for key in _ALL_FORM_FIELDS if key in fields and key not in allowed)
    if stray:
        raise ContentError(
            f"{source}: {', '.join(stray)} do not apply to the {distribution.value!r} distribution"
        )


def _download_form(
    fields: dict[str, Any], distribution: Distribution, source: PurePosixPath
) -> tuple[str | None, str | None]:
    """The extra fields the `download` form needs, all declared or none.

    A version with no checksum -- or the reverse -- would let a descriptor
    pin what it fetches without ever proving what arrived, which is worse
    than not declaring the form at all: it looks verified and is not.
    """
    if distribution is not Distribution.DOWNLOAD:
        return None, None
    version = _text(fields, "version", source)
    checksum = _text(fields, "checksum", source)
    if not _CHECKSUM.fullmatch(checksum):
        raise ContentError(
            f"{source}: 'checksum' must be 'sha256:' followed by 64 hex characters, got {checksum!r}"
        )
    return version, checksum


def _archive_form(
    fields: dict[str, Any], distribution: Distribution, source: PurePosixPath
) -> tuple[tuple[str, ...], str | None]:
    """The extra fields a `download` server declares when its asset is an
    archive rather than a bare binary, all declared or none.

    ``archive_members`` without ``archive_executable`` -- or the reverse --
    would leave the installer either not knowing what to run or promising a
    listing it never checks, so the two are required together exactly like
    `version` and `checksum` are.
    """
    if distribution is not Distribution.DOWNLOAD:
        return (), None
    declares_members = "archive_members" in fields
    declares_executable = "archive_executable" in fields
    if not declares_members and not declares_executable:
        return (), None
    if declares_members != declares_executable:
        raise ContentError(
            f"{source}: 'archive_members' and 'archive_executable' must be declared together"
        )
    members = _names(fields, "archive_members", source)
    if not members:
        raise ContentError(f"{source}: 'archive_members' must name at least one file")
    for member in members:
        if PurePosixPath(member).is_absolute() or ".." in PurePosixPath(member).parts:
            raise ContentError(
                f"{source}: 'archive_members' entry {member!r} must be a relative path "
                f"inside the archive, with no '..' segment"
            )
    executable = _text(fields, "archive_executable", source)
    if executable not in members:
        raise ContentError(
            f"{source}: 'archive_executable' {executable!r} must be one of 'archive_members'"
        )
    return members, executable


def _npm_form(
    fields: dict[str, Any], distribution: Distribution, directory: ContentRoot, source: PurePosixPath
) -> tuple[str | None, str | None, str | None, str | None, bytes | None, str | None]:
    """The extra fields the `npm` form needs, all declared or none.

    `package` and `version` are what npm installs, `entry` is the script a
    CLI's configuration ends up pointing at, `integrity` is the hash npm
    itself verifies the fetched tarball against, and `lockfile` names the
    real lockfile that ships beside the descriptor -- a plain file, read the
    same way a skill's own `Asset` is: the loader does the reading so nothing
    downstream ever has to.

    A synthesized lockfile pinning only ``package`` would prove nothing about
    whatever ``package`` itself depends on -- exactly the gap that let a
    driverless install through before this field existed. Requiring the real
    lockfile, and checking it here against the very fields it must agree
    with, is what closes that gap at load time instead of at `npm ci`.
    """
    if distribution is not Distribution.NPM:
        return None, None, None, None, None, None
    package = _text(fields, "package", source)
    version = _text(fields, "version", source)
    integrity = _text(fields, "integrity", source)
    entry = _text(fields, "entry", source)
    endpoint = _text(fields, "endpoint", source)
    if not _INTEGRITY.fullmatch(integrity):
        raise ContentError(
            f"{source}: 'integrity' must be 'sha512-' followed by base64, got {integrity!r}"
        )
    lockfile_name = _text(fields, "lockfile", source)
    if PurePosixPath(lockfile_name).name != lockfile_name:
        raise ContentError(
            f"{source}: 'lockfile' must be a bare filename beside the descriptor, got {lockfile_name!r}"
        )
    lockfile_path = directory / lockfile_name
    if not lockfile_path.is_file():
        raise ContentError(f"{source}: 'lockfile' names {lockfile_name!r}, which does not exist beside it")
    npm_lockfile = lockfile_path.read_bytes()
    npm_package_name = _require_lockfile_pins(package, version, integrity, endpoint, npm_lockfile, source)
    return package, version, integrity, entry, npm_lockfile, npm_package_name


def _require_lockfile_pins(
    package: str, version: str, integrity: str, endpoint: str, npm_lockfile: bytes, source: PurePosixPath
) -> str:
    """The shipped lockfile has to pin the very package the descriptor names,
    and returns the root package's own ``name`` -- the value the synthesized
    `package.json` must use for its own ``name``, not the descriptor's file
    stem.

    `npm ci` itself refuses `package.json` and its lockfile when the two
    disagree, and that disagreement is not only about dependencies: recent
    npm releases check the root package's own `name` too, comparing it
    against `package.json`'s. Pegasus synthesizes `package.json` from
    ``package`` and ``version`` alone -- it never reads the lockfile to build
    it -- so deriving that name from the descriptor's own file stem, as a
    naive synthesis would, only agrees with the lockfile by coincidence: a
    lockfile whose real npm-generated root name is ``playwright-mcp-root``
    would disagree with a descriptor named ``playwright.md``, exactly the
    mismatch `npm ci` exists to refuse. Returning the lockfile's own name
    here, for `package.json` to reuse verbatim, is what keeps the two in
    agreement by construction instead of by luck.

    One consequence of reusing it verbatim: the name is whatever directory
    `npm install` happened to run in, so it carries no meaning and must carry
    no brand either. The shipped lockfile says `playwright-mcp-root` rather
    than the engine's name it originally recorded, because a rebranded
    distribution materializes this tree too and its `package.json` would
    otherwise name a product the person never installed. Regenerating the
    lockfile means running `npm install` in a directory named that, not
    editing the name afterwards -- the whole point above is that the two files
    agree because one is copied from the other.
    """
    try:
        document = json.loads(npm_lockfile)
    except json.JSONDecodeError as error:
        raise ContentError(f"{source}: 'lockfile' is not valid JSON: {error}") from error
    packages = document.get("packages")
    if not isinstance(packages, dict):
        raise ContentError(f"{source}: 'lockfile' has no top-level 'packages' object")
    root = packages.get("", {})
    if not isinstance(root, dict) or root.get("dependencies", {}).get(package) != version:
        raise ContentError(
            f"{source}: 'lockfile' root package does not pin {package}@{version}, "
            f"the same pair the descriptor itself declares"
        )
    root_name = root.get("name")
    if not isinstance(root_name, str) or not root_name.strip():
        raise ContentError(f"{source}: 'lockfile' root package has no non-empty 'name'")
    key = f"node_modules/{package}"
    entry = packages.get(key)
    if not isinstance(entry, dict):
        raise ContentError(f"{source}: 'lockfile' has no {key!r} entry")
    mismatched = [
        field
        for field, expected in (("version", version), ("integrity", integrity), ("resolved", endpoint))
        if entry.get(field) != expected
    ]
    if mismatched:
        raise ContentError(
            f"{source}: 'lockfile' entry {key!r} disagrees with the descriptor on "
            f"{', '.join(mismatched)}"
        )
    return root_name


def _load_system_prompt(directory: ContentRoot, relative_dir: PurePosixPath) -> SystemPrompt | None:
    files = _markdown_files(directory)
    if not files:
        return None
    if len(files) > 1:
        raise ContentError(
            f"{relative_dir}: exactly one system prompt is allowed, found {len(files)}"
        )
    source = relative_dir / files[0].name
    _, body = split_frontmatter(files[0].read_text(encoding="utf-8"), str(source))
    _require_known_placeholders(body, source)
    return SystemPrompt(
        body=body,
        source=source,
        mcp_sections=_load_mcp_sections(
            directory / SYSTEM_PROMPT_MCP_DIR, relative_dir / SYSTEM_PROMPT_MCP_DIR
        ),
    )


def _load_mcp_sections(
    directory: ContentRoot, relative_dir: PurePosixPath
) -> tuple[McpSection, ...]:
    """Each file is one server's ambient section, named by its own stem.

    `_descriptor` is what makes the name a fact rather than a convention: it
    already refuses a descriptor whose `name` disagrees with its filename, so
    the id this section belongs to cannot drift from the file it lives in.
    """
    sections = []
    for path in _markdown_files(directory):
        _, body, source = _descriptor(path, relative_dir)
        sections.append(McpSection(name=_stem(path), body=body, source=source))
    return tuple(sections)


def _require_known_system_prompt_mcp(
    system_prompt: SystemPrompt | None, mcp: tuple[Mcp, ...]
) -> None:
    """An ambient section has to belong to a server this release ships.

    The same invariant `_require_reaches_known_agents` holds for an agent's
    declaration, for the same reason: a section naming a server nobody ships
    would never be selected by any `--mcp` flag, so it would sit in the tree
    looking installed and reach nobody -- the failure being silent is exactly
    what makes it worth refusing at load.
    """
    if system_prompt is None:
        return
    known = {server.name for server in mcp}
    for section in system_prompt.mcp_sections:
        if section.name not in known:
            raise ContentError(
                f"{section.source}: is the ambient section for {section.name!r}, "
                f"which no mcp server declares"
            )


def _descriptor(path: ContentRoot, relative_dir: PurePosixPath) -> tuple[dict[str, Any], str, PurePosixPath]:
    source = relative_dir / path.name
    fields, body = split_frontmatter(path.read_text(encoding="utf-8"), str(source))
    if not fields:
        raise ContentError(f"{source}: a descriptor is required")
    _require_name(fields, _stem(path), source)
    _require_known_placeholders(body, source)
    return fields, body, source


def _refuse_derived_fields(fields: dict[str, Any], source: PurePosixPath) -> None:
    """A field the loader derives is not the file's to declare.

    Reading the line and dropping it would leave a descriptor stating a fact it has
    no say in, and an author who wrote the opposite of what happens would be told
    nothing -- the same silence `_flag` exists to prevent.
    """
    for key in ("default", "hidden"):
        if key in fields:
            raise ContentError(
                f"{source}: {key!r} is derived, not declared, and declaring it decides nothing"
            )


#: The two spellings of the agent-to-server relation, and what an agent file is
#: told when it carries either. One table rather than one function per key: the
#: rule is a single one -- an agent file does not declare which servers reach it
#: -- and the two keys differ only in the history behind the sentence.
#: `optional_mcp` used to live in an agent file and is now derived;
#: `reaches` never lived there and is the descriptor's own key. Keeping them
#: apart would have meant two near-identical functions whose only real
#: difference was a clause, and would have let one direction be added,
#: renamed or deleted without the other -- which is precisely how the
#: half-guarded state below came to exist in the first place.
_RELATION_KEYS_NOT_AN_AGENTS: dict[str, str] = {
    "optional_mcp": (
        "is no longer declared by an agent; it is derived from the 'reaches' list of "
        "each server's own descriptor"
    ),
    "reaches": (
        "belongs to a server's descriptor, not to an agent; it is the descriptor's "
        "list of the agents that server reaches"
    ),
}


def _refuse_relation_keys_in_an_agent(fields: dict[str, Any], source: PurePosixPath) -> None:
    """Neither end of the agent-to-server relation is an agent file's to declare.

    The relation is authored in exactly one place: each descriptor under
    `content/mcp/` lists the agents it reaches, and `Agent.optional_mcp` is the
    inverse of those lists, computed at load time. An agent file carrying
    either key is therefore read by nobody and changes nothing, while looking
    exactly like a working declaration -- the precise silent failure this
    codebase keeps paying for.

    Both spellings fail that way, and the second is the likelier mistake once
    the inversion lands: an author who half-remembers "the key is `reaches`
    now" writes it where the old key lived, gets a clean load, and gets no
    grant. Refusing `optional_mcp` alone would have left the mirror of the
    refusal wide open, and an invariant that holds in only one direction is
    where the bug walks in -- that is the lesson this repository keeps
    relearning, which is why the two live in one table read by one loop rather
    than in two functions that could drift apart.

    Each message names the file, says what the key really is, and names
    `content/mcp/<id>.md` as the file to write it in.
    """
    for key, explanation in _RELATION_KEYS_NOT_AN_AGENTS.items():
        if key in fields:
            raise ContentError(
                f"{source}: {key!r} {explanation}, so it is written in content/mcp/<id>.md"
            )


def _require_known_placeholders(body: str, source: PurePosixPath) -> None:
    """A placeholder nobody promised to answer would ship as literal braces."""
    unknown = placeholders.unknown_in(body)
    if unknown:
        named = ", ".join(repr(name) for name in unknown)
        allowed = ", ".join(sorted(placeholders.NAMES))
        raise ContentError(f"{source}: unknown placeholder {named}; expected one of {allowed}")
    if placeholders.malformed_in(body):
        raise ContentError(f"{source}: a '{{{{' that names nothing would ship as literal braces")


def _refuse_verbatim_placeholders(assets: tuple[Asset, ...], source: PurePosixPath) -> None:
    """A skill is copied byte for byte, so a fact it asks for is never answered.

    The engine fills bodies, not assets, and a skill has no body it keeps. Asking
    here anyway is not a typo the adapter would catch later — it is a request
    nobody is listening to, and it lands in the user's home as literal braces.
    """
    for asset in assets:
        try:
            text = asset.content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        where = f"{source.parent}/{asset.relative_path}"
        asked = placeholders.answerable_in(text)
        if asked:
            raise ContentError(
                f"{where}: skills are installed verbatim, "
                f"so {asked[0]!r} would ship as literal braces"
            )
        # Held to the same standard as a body. A malformed opener is refused in
        # an agent prompt, and the same typo reaching the user's home from a
        # skill instead would be the same mistake with a kinder answer.
        if placeholders.malformed_in(text):
            raise ContentError(f"{where}: a '{{{{' that names nothing would ship as literal braces")


def _subdirectories(directory: ContentRoot) -> list[ContentRoot]:
    if not directory.is_dir():
        return []
    return sorted((item for item in directory.iterdir() if item.is_dir()), key=lambda item: item.name)


def _markdown_files(directory: ContentRoot) -> list[ContentRoot]:
    if not directory.is_dir():
        return []
    return sorted(
        (item for item in directory.iterdir() if item.is_file() and item.name.endswith(".md")),
        key=lambda item: item.name,
    )


def _walk_files(node: ContentRoot) -> list[tuple[ContentRoot, tuple[str, ...]]]:
    """Every file below `node`, each paired with its path relative to `node`.

    Stands in for `Path.rglob`, which a `Traversable` -- the interface a zip
    entry actually implements -- does not promise. Written once here instead
    of at each of the two call sites that used to reach for it directly.
    """
    found: list[tuple[ContentRoot, tuple[str, ...]]] = []
    if not node.is_dir():
        return found
    for child in node.iterdir():
        if child.is_dir():
            found.extend((file, (child.name, *rest)) for file, rest in _walk_files(child))
        elif child.is_file():
            found.append((child, (child.name,)))
    return found


def _assets(item: ContentRoot) -> tuple[Asset, ...]:
    """Every file under a content directory, with SKILL.md first."""
    ordered = sorted(_walk_files(item), key=lambda pair: (pair[0].name != SKILL_FILE, pair[1]))
    return tuple(
        Asset(relative_path=PurePosixPath(*parts), content=file.read_bytes()) for file, parts in ordered
    )


def _stem(path: ContentRoot) -> str:
    """The file name without its extension, without relying on `Path.stem`.

    `Traversable` promises `.name`, not `.stem` -- every caller here already
    knows the name ends in `.md`, so trimming it is enough.
    """
    return PurePosixPath(path.name).stem


def _require_name(fields: dict[str, Any], expected: str, source: PurePosixPath) -> None:
    declared = fields.get("name")
    if declared != expected:
        raise ContentError(
            f"{source}: declares name {declared!r} but its path says {expected!r}"
        )


def _text(fields: dict[str, Any], key: str, source: PurePosixPath) -> str:
    value = fields.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{source}: {key!r} is required and must be a non-empty string")
    return value.strip()


def _choice(fields: dict[str, Any], key: str, options: type[Enum], source: PurePosixPath) -> Any:
    value = fields.get(key)
    try:
        return options(value)
    except ValueError:
        allowed = ", ".join(item.value for item in options)
        raise ContentError(f"{source}: {key!r} is {value!r}; expected one of {allowed}") from None


def _flag(fields: dict[str, Any], key: str, source: PurePosixPath) -> bool:
    """A flag is a YAML boolean or nothing at all.

    `bool()` would read the string 'false', the string '0' and a misspelling as true,
    and turn an author saying "not this one" into the opposite claim with no diagnostic.
    """
    value = fields.get(key, False)
    if not isinstance(value, bool):
        raise ContentError(f"{source}: {key!r} is {value!r}; expected true or false")
    return value


def _names(fields: dict[str, Any], key: str, source: PurePosixPath) -> tuple[str, ...]:
    value = fields.get(key, [])
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ContentError(f"{source}: {key!r} must be a list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ContentError(f"{source}: {key!r} must contain non-empty names")
    return tuple(value)
