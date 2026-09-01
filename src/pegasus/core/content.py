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
from pathlib import PurePosixPath
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

SESSION_STARTS_IN = "pegasus-orchestrator"
"""The agent a session opens in.

Which agent that is, is a fact about the set of agents rather than about any one
of them: a CLI names it in a single-valued setting. A per-agent frontmatter flag
could not hold it, because no file can see whether another already claimed it --
two claims and no claim at all are both writable, and neither is refusable
without a validator that reads the whole directory back. Naming it once, here,
makes both unrepresentable.
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
    a tool name that only happens to be true today.
    """

    name: str
    description: str
    body: str
    mode: AgentMode
    source: PurePosixPath
    requires_tools: tuple[str, ...] = ()
    optional_tools: tuple[str, ...] = ()
    optional_mcp: tuple[str, ...] = ()
    may_delegate_to: tuple[str, ...] = ()
    model_configurable: bool = False

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
    agents = _load_agents(root / "agents", PurePosixPath("agents"))
    mcp = _load_mcp(root / "mcp", PurePosixPath("mcp"))
    _require_known_optional_mcp(agents, mcp)
    _require_mcp_convention_referenced(agents)
    system_prompt = _load_system_prompt(root / SYSTEM_PROMPT_DIR, PurePosixPath(SYSTEM_PROMPT_DIR))
    _require_known_system_prompt_mcp(system_prompt, mcp)
    return Content(
        skills=_load_skills(root / "skills", PurePosixPath("skills")),
        agents=agents,
        commands=_load_commands(root / "commands", PurePosixPath("commands")),
        mcp=mcp,
        system_prompt=system_prompt,
    )


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
    """
    if "=" not in spelling:
        return spelling.strip(), None
    parts = spelling.split("=")
    if len(parts) != 2:
        raise ContentError(
            f"cannot read mcp choice {spelling!r}: expected 'id' or 'id=server-key'"
        )
    server_id, key = (part.strip() for part in parts)
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
            )
            for agent in content.agents
        ),
        system_prompt=_select_system_prompt_mcp(content.system_prompt, kept),
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


def _load_agents(directory: ContentRoot, relative_dir: PurePosixPath) -> tuple[Agent, ...]:
    agents = []
    for path in _markdown_files(directory):
        fields, body, source = _descriptor(path, relative_dir)
        _refuse_derived_fields(fields, source)
        agents.append(
            Agent(
                name=_stem(path),
                description=_text(fields, "description", source),
                body=body,
                mode=_choice(fields, "mode", AgentMode, source),
                source=source,
                requires_tools=_names(fields, "requires_tools", source),
                optional_tools=_names(fields, "optional_tools", source),
                optional_mcp=_names(fields, "optional_mcp", source),
                may_delegate_to=_names(fields, "may_delegate_to", source),
                model_configurable=_flag(fields, "model_configurable", source),
            )
        )
    _require_the_session_start(tuple(agents), relative_dir)
    return tuple(agents)


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


def _require_known_optional_mcp(agents: tuple[Agent, ...], servers: tuple[Mcp, ...]) -> None:
    """An `optional_mcp` id nothing provides is a typo that would ship as a
    silently ungranted tool: the agent would run believing a server's tools
    might arrive, and no installation could ever grant them. Checking here,
    once, is what makes that typo a load-time refusal instead of a permission
    nobody notices is missing.
    """
    known = {server.name for server in servers}
    for agent in agents:
        unknown = [name for name in agent.optional_mcp if name not in known]
        if unknown:
            raise ContentError(
                f"{agent.source}: 'optional_mcp' names {', '.join(sorted(unknown))}, "
                f"which no mcp server declares"
            )


def _require_mcp_convention_referenced(agents: tuple[Agent, ...]) -> None:
    """A declared server and its convention reference have to travel together.

    The permission is granted from the declaration alone: `optional_mcp: [id]`
    hands the agent a server's tools with nothing else read from the descriptor.
    Left one-directional, that makes two states representable that should not
    be: a declared server whose convention the body never mentions, and a body
    that points at a convention for a server it never declared -- an agent told
    to follow a convention for tools it will never have. Both directions have to
    agree, so the set of ids declared and the set of ids referenced are required
    to be exactly equal.
    """
    for agent in agents:
        declared = set(agent.optional_mcp)
        referenced = _referenced_mcp_ids(agent.body)
        if declared == referenced:
            continue
        problems = []
        for server_id in sorted(declared - referenced):
            expected = "{{skills_root}}/" + mcp_convention_path(server_id).as_posix()
            problems.append(
                f"declares 'optional_mcp: [{server_id}]' but its body never references "
                f"{expected!r}"
            )
        for server_id in sorted(referenced - declared):
            expected = "{{skills_root}}/" + mcp_convention_path(server_id).as_posix()
            problems.append(
                f"references {expected!r} but never declares 'optional_mcp: [{server_id}]'"
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
    lockfile whose real npm-generated root name is ``pegasus-playwright-mcp``
    would disagree with a descriptor named ``playwright.md``, exactly the
    mismatch `npm ci` exists to refuse. Returning the lockfile's own name
    here, for `package.json` to reuse verbatim, is what keeps the two in
    agreement by construction instead of by luck.
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

    The same invariant `_require_known_optional_mcp` holds for an agent's
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
