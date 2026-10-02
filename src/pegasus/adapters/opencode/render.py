"""How OpenCode spells what the content core means.

Every table in this module is a translation from an agnostic concept to an
OpenCode name. This is the only place those names are allowed to appear.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pegasus.core import placeholders
from pegasus.core.content import (
    Agent,
    AgentMode,
    Command,
    DENY_FLOOR_DIRECTORIES,
    Distribution,
    Execution,
    Mcp,
    RunsAs,
    Skill,
    SystemPrompt,
    delegation_capabilities_path,
    mcp_convention_path,
)
from pegasus.core.dependencies import npm_script_path, program_path
from pegasus.core.identity import Identity
from pegasus.core.types import Artifact, ConfigKeyArtifact, FileArtifact, Layout, ModelAssignment

#: `RunsAs.ORCHESTRATOR` is deliberately absent here: which agent that role
#: names is content-declared data (the agent whose name the loaded content
#: marks as where a session starts), never an engine constant, so `command`
#: takes it as a required parameter instead of looking it up in this table.
AGENT_FOR_ROLE: dict[RunsAs, str | None] = {
    RunsAs.PLANNER: "plan",       # native to OpenCode
    RunsAs.BUILDER: "build",      # native to OpenCode
    RunsAs.DEFAULT: None,         # key omitted; the CLI decides
}

MODE_NAME: dict[AgentMode, str] = {
    AgentMode.PRIMARY: "primary",
    AgentMode.SUBAGENT: "subagent",
}

TOOL_NAME: dict[str, str] = {
    "read": "read",
    "write": "write",
    "edit": "edit",
    "bash": "bash",
    "grep": "grep",
    "glob": "glob",
    # Two the runtime offers that are not file work, and that the deny baseline
    # therefore takes away by omission rather than by decision. `skill` is what
    # puts the installed inventory in front of an agent at all -- without it the
    # skills Pegasus placed are invisible, however plainly the system prompt
    # calls consulting them mandatory. `ask` is the runtime's own way of putting
    # a question to the person and waiting, which is what a gate that says "ask,
    # and STOP" needs to exist to mean anything.
    "skill": "skill",
    "ask": "question",
}

# Every Pegasus tool name whose runtime counterpart asks the runtime's own
# `external_directory` permission against its target before it asks for its
# own permission name. Verified by reading the runtime's own source rather
# than assumed -- most of the six call `assertExternalDirectory` directly
# (`read`, `grep`, `glob`, `edit`, `write`), but `bash` does not: its own
# runtime counterpart (`packages/opencode/src/tool/shell.ts`) calls
# `ctx.ask({permission: "external_directory", ...})` itself instead, which
# reaches the identical permission name by a different path. This constant
# used to hold only `read`, `grep` and `glob`; `edit`, `write` and `bash` were
# added afterward as a correction going forward, once reading the runtime's
# source directly (rather than assuming it from the first three) showed the
# set was incomplete -- not because any of the three previously missing was
# ever observed to fail against the catalog this codebase ships today. See
# `content/agents/sdd-verify.md`'s own `requires_tools` for why: it already
# declared `bash` and `write` alongside `read`, so it always carried this key
# regardless of which of the three the constant above named, and comparing
# the rendered `opencode.json` for the catalog before and after this widening
# shows not one byte of difference. The gap this widening closes is for an
# agent this codebase does not yet ship -- one that declares `edit`, `write`
# or `bash` without `read` -- which the old, narrower set would have sent to
# the outer `"*": "deny"` baseline with no `external_directory` key at all.
# The runtime also gates two tools that are not names Pegasus renders at all
# -- `apply_patch` and `lsp` -- which is why they are absent here rather than
# mapped to something: there is no Pegasus tool name for either. For
# `apply_patch` this is not just a naming gap this table happens to leave
# open: the runtime folds `edit`, `write` and `apply_patch` onto the single
# `edit` permission before it ever asks `external_directory` (`_tools` and
# `_permission` below give the full account), so there is no independent
# permission here to name even if Pegasus minted a tool called `apply_patch`.
# `lsp` carries no such story -- it is simply a tool this codebase has never
# had reason to declare. `skill` and `ask` stay absent too, but for the
# opposite reason: neither reads, writes or executes a path at all, so
# neither runtime counterpart has a target to ask `external_directory` about.
# A sub-agent's `bash` is allowed, except that a `git push` asks the person.
# Product decision (docs/arquitectura/arquitectura.md, 7.5.0): a sub-agent
# must not publish on its own, yet a full block was rejected because the
# person sometimes asks an agent to push. The coordinator (`mode: primary`)
# keeps the plain `"allow"`.
#
# Verified in the runtime's own source (v1.18.32):
# - `tool/shell.ts` parses the command with tree-sitter and asks `bash` once
#   with one pattern per `command` node (`commands`, `collect`: lines
#   123-125 and 408), so `a && git push`, `a; git push` and `$(git push)`
#   are each checked on their own text.
# - `permission/index.ts:28-37` (`evaluate`) takes the LAST rule matching
#   both name and pattern, so the `"*"` allow comes first; one `"ask"`
#   among the patterns makes the whole call ask (`ask`, lines 73-83).
# - `util/wildcard.ts:3-19`: `*` is `.*`, the match is anchored, and a
#   trailing ` *` makes the tail optional, so `git push *` matches both
#   `git push` and `git push origin main`.
# Not caught: aliases, wrapper scripts, a push inside a script file or an
# `sh -c "..."` / `eval` string (the inner text is an argument, not a
# command node), `gh` commands, and `FOO=1 git push` (the command node text
# starts with the env assignment, so neither anchored pattern matches).
# `git * push *` also asks for harmless lines whose arguments contain the
# word, such as `git log --grep push x` or `git checkout push` -- a false
# positive, never a miss. Commits are protected: the parallel-delivery
# procedure has every writer commit with `-F <message file>`, so a message
# that says "push" never reaches the command line.
SUBAGENT_BASH_PERMISSION: dict[str, str] = {
    "*": "allow",
    "git push *": "ask",
    "git * push *": "ask",
}

EXTERNAL_DIRECTORY_TOOLS = frozenset({"read", "grep", "glob", "edit", "write", "bash"})

# The deny floor `_permission` writes last under `external_directory`, once the
# baseline for that permission flipped from `"ask"` to `"allow"` (see that
# function's docstring for the upstream bug this works around). Every entry
# here is directory-granular -- `*/<name>/*`, never a bare `*/<name>` and
# never a file-shaped pattern like `*.pem` -- because the runtime never asks
# `external_directory` about a file. `packages/opencode/src/tool
# /external-directory.ts` always evaluates `path.join(dir, "*")`, where `dir`
# is already `path.dirname(target)` for anything that is not itself a
# directory: the filename is discarded before the ask ever happens, and the
# glob it builds always ends in `/*`, never in the bare directory name. A
# pattern here that named a file (`*.pem`, `*.key`, `.env`) could therefore
# never match anything this permission is ever asked to evaluate, and a bare
# `*/<name>` (no trailing `/*`) is equally dead: `Wildcard.match` anchors both
# ends, so `^.*/<name>$` cannot match an input that always ends in `/*`. Do
# not add either shape here -- it would be a guard that protects nothing,
# which is exactly the defect this project hunts for elsewhere. This list is
# the directory-shaped subset of the user's own standing security rule
# (`.ssh/`, `.credentials/`, `.aws/credentials`, `.config/gh/hosts.yml`,
# `secrets/`); the file-shaped members of that rule (`.env`, `.env.*`,
# `*.pem`, `*.key`) are inexpressible through this permission and are not
# listed for the same reason -- and are consequently reachable, not merely
# unguarded in the abstract, the moment they live anywhere outside these five
# directories, which is most places a file can live.
#
# The five directory names themselves are not retyped here: they are
# `pegasus.core.content.DENY_FLOOR_DIRECTORIES`, the one CLI-agnostic list
# every adapter's own deny floor derives from (see its own docstring for
# why a second, independently-typed list of the same five words would be a
# silent way for two adapters to drift apart about what "the floor" means).
# This dict comprehension is OpenCode's own translation of that list into
# its runtime's wildcard vocabulary -- `f"*/{name}/*"` keyed to `"deny"` --
# and nothing else in this module, or in the tests that pin its rendered
# byte shape, changed when the list moved here from a dict literal.
#
# What this floor actually is, said without overclaiming: a guard against an
# agent that wanders into one of these five directories BY ACCIDENT, not a
# boundary against one that means to get there. Matching here is on the
# LITERAL path string -- `Wildcard.match` builds a regex from the pattern and
# tests it against the exact bytes of `path.dirname(target) + "/*"`; neither
# it nor `packages/opencode/src/tool/external-directory.ts` ever calls
# `realpath`. Any spelling of the same underlying location that does not
# literally contain, say, `/.ssh/` walks straight past this floor to the
# `"*": "allow"` baseline: a symlink, a bind mount, a hard link, or an
# environment variable the runtime or a program it shells out to honours
# (`GH_CONFIG_DIR`, `AWS_SHARED_CREDENTIALS_FILE`) pointing the real read
# somewhere this floor never named. And an agent that already holds `bash`
# under this same `"allow"` baseline can construct that indirection itself --
# nothing below stops an agent from symlinking its way around its own floor.
# This is not a defect in this dict; it is what the runtime's own matching
# strategy makes possible for anyone to build, and this comment exists so
# nobody reads five denied strings as a boundary that holds against an agent
# that is trying to get past it.
EXTERNAL_DIRECTORY_DENY_FLOOR: dict[str, str] = {f"*/{name}/*": "deny" for name in DENY_FLOOR_DIRECTORIES}

#: Regex metacharacters the runtime's own `Wildcard.match`
#: (`packages/core/src/util/wildcard.ts`) escapes before turning a pattern
#: into a regex, in the exact order that function applies: escape first, then
#: `*` -> `.*`, then `?` -> `.`. Matches on Python's `re` module's own
#: metacharacter set, which is a superset of the TS source's -- fine, since
#: none of the extra characters (`)`, `(`, `|`, ...) can appear in a directory
#: pattern this codebase ever builds.
_WILDCARD_METACHARACTERS = re.compile(r"[.+^${}()|\[\]\\]")


def _wildcard_match(candidate: str, pattern: str) -> bool:
    """Python port of OpenCode's own `Wildcard.match`, faithfully, not
    approximated: escape `pattern`'s regex metacharacters, turn `*` into
    `.*` and `?` into `.`, anchor both ends, and let `.` cross `/` the same
    way the runtime's own `s` (dotAll) flag does -- Python's `.` already
    matches `/` without it, so `re.fullmatch` alone reproduces the anchoring
    and `re.DOTALL` reproduces the dotAll flag for the one character class
    (`.`) it actually changes.

    Deliberately not a path-component check (`".ssh" in Path(p).parts`): that
    is a proxy for this match, not the match itself, and a proxy is exactly
    what has bitten this codebase before -- it would flag a directory merely
    named `sshfoo`, or miss a pattern this project never anticipated, while
    this function only ever answers what the runtime's own regex would.

    Two behaviours of the original are deliberately NOT reproduced, named
    here rather than left for someone to discover the day they matter:

    - `wildcard.ts` rewrites a pattern ending in `" .*"` (after the `*`
      substitution) into `"( .*)?"`, so a trailing `" *"` matches nothing as
      well as something -- `match("foo", "foo *")` is true there and false
      here. No `EXTERNAL_DIRECTORY_DENY_FLOOR` pattern ends in `" *"`, and
      none can while the floor stays directory-shaped, so the divergence is
      unreachable from the one caller this function has.
    - The original compiles case-insensitively on Windows only. This one is
      always case-sensitive, i.e. it hardcodes the POSIX side of that split.

    Both are safe for the five static patterns this serves and for no more
    than that. Widening the floor, or calling this from anywhere else, means
    re-reading `wildcard.ts` first -- this is a faithful port of the part
    that is reachable from here, not of the whole function.
    """
    escaped = _WILDCARD_METACHARACTERS.sub(lambda match: "\\" + match.group(0), pattern.replace("\\", "/"))
    escaped = escaped.replace("*", ".*").replace("?", ".")
    return re.fullmatch(escaped, candidate.replace("\\", "/"), flags=re.DOTALL) is not None


def deny_floor_shadows(path: str) -> bool:
    """Whether granting `path` through `pegasus directory grant` would render
    an `external_directory` entry (`f"{path}/*": "allow"`, `_permission`
    below) that `EXTERNAL_DIRECTORY_DENY_FLOOR` -- written last into that same
    map, so the runtime's last-match resolution always lands on it -- would
    still resolve to `deny` for.

    A grant this shadows is never dormant the way an ordinary grant is while
    the baseline is `"allow"` (see `_permission`'s own docstring): an
    ordinary grant would regain its meaning if the baseline were ever
    `"ask"` again, because the floor is the only thing written after it
    today. A floor-shadowed grant never regains anything -- the floor is
    written last regardless of what the baseline is, so this grant can never
    win the match, no matter what the baseline becomes.

    `path` is expected already normalized by `content.validate_granted_directory`
    (absolute, free of glob metacharacters and of `..`) -- the same value
    every caller of this function already holds before it ever reaches a
    rendered permission.
    """
    key = f"{path}/*"
    return any(_wildcard_match(key, pattern) for pattern in EXTERNAL_DIRECTORY_DENY_FLOOR)

PERMISSION_NAME: dict[str, str] = {
    "read": "read",
    # The runtime's own config loader folds `write`, `edit` and `patch` onto a
    # single `edit` permission when it derives one from `tools` -- its
    # `permission` schema has no `write` key at all. Naming both onto the same
    # target here is what keeps that collapse from being an accident this
    # module's own translation could get wrong: `write` has to land exactly
    # where `edit` does, or a granted write silently governs nothing.
    "write": "edit",
    "edit": "edit",
    "bash": "bash",
    "grep": "grep",
    "glob": "glob",
    "skill": "skill",
    "ask": "question",
}


class RenderError(ValueError):
    """The content asks for something this CLI has no name for."""


def skill(layout: Layout, item: Skill) -> list[Artifact]:
    """Skills travel verbatim: OpenCode reads the same SKILL.md format."""
    return [
        FileArtifact(
            id=f"skill:{item.name}:{asset.relative_path}",
            path=layout.skills_dir / item.name / asset.relative_path,
            content=asset.content,
            executable=False,
        )
        for asset in item.assets
    ]


def prompt(layout: Layout, item: Agent) -> list[Artifact]:
    """The agent's body, in the separate file OpenCode expects."""
    return [
        FileArtifact(
            id=f"prompt:{item.name}",
            path=_prompt_path(layout, item),
            content=_agent_body(layout, item).encode("utf-8"),
            executable=False,
        )
    ]


def agent(
    layout: Layout, item: Agent, assignment: ModelAssignment | None = None, separate_prompt: bool = True
) -> list[Artifact]:
    """One entry under the settings file's agent map, plus the default when it is one.

    `mode` and `default` say different things: `primary` says the agent can run at top
    level, `default_agent` says which single one a session opens in.

    `assignment` is a fact about one machine -- a preference from Pegasus's own
    state, its model already resolved and validated against what this machine can
    actually reach -- never a fact the content core carries. Absent, both keys are
    omitted entirely and OpenCode falls back to whatever it would have chosen
    anyway, exactly as if this agent had never been assigned a model at all.

    An effort is spelled here as ``variant``: OpenCode's own schema names a
    per-agent reasoning effort that way, and this is the one place that
    translation is allowed to happen. It is written only alongside a model,
    matching the schema's own caveat that a variant "applies only when using
    the agent's configured model".
    """
    value: dict[str, Any] = {"description": item.description, "mode": MODE_NAME[item.mode]}
    if item.hidden:
        value["hidden"] = True
    if item.body.strip():
        value["prompt"] = (
            "{file:./%s}" % _prompt_path(layout, item).relative_to(layout.config_dir).as_posix()
            if separate_prompt
            else _agent_body(layout, item)
        )
    value["tools"] = _tools(item)
    value["permission"] = _permission(layout, item)
    if assignment is not None:
        value["model"] = assignment.full_id
        if assignment.effort is not None:
            value["variant"] = assignment.effort

    artifacts: list[Artifact] = [
        ConfigKeyArtifact(
            id=f"agent:{item.name}",
            path=layout.settings_file,
            pointer=f"/agent/{item.name}",
            value=value,
        )
    ]
    if item.default:
        artifacts.append(
            ConfigKeyArtifact(
                id="default-agent",
                path=layout.settings_file,
                pointer="/default_agent",
                value=item.name,
            )
        )
    return artifacts


def command(layout: Layout, item: Command, orchestrator_name: str) -> list[Artifact]:
    """A markdown file whose frontmatter is rebuilt in OpenCode's own vocabulary.

    `orchestrator_name` is required, with no default: it is the name the
    loaded content itself declares for the agent a session starts in (see
    `pegasus.core.content.SESSION_STARTS_IN`), and it names the `agent:` field
    for `RunsAs.ORCHESTRATOR`. A default here would be exactly the kind of
    silently-substitutable wrong identity this parameter exists to rule out.
    """
    fields: dict[str, Any] = {"description": item.description}
    executor = orchestrator_name if item.runs_as is RunsAs.ORCHESTRATOR else AGENT_FOR_ROLE[item.runs_as]
    if executor:
        fields["agent"] = executor
    if item.execution is Execution.ISOLATED:
        fields["subtask"] = True
    return [
        FileArtifact(
            id=f"command:{item.name}",
            path=layout.commands_dir / f"{item.name}.md",
            content=(_frontmatter(fields) + "\n" + _body(layout, item.body, item.name)).encode("utf-8"),
            executable=False,
        )
    ]


def system_prompt(layout: Layout, item: SystemPrompt, identity: Identity) -> list[Artifact]:
    """A file of its own, wired in by appending to OpenCode's instructions list.

    Appending rather than replacing is what keeps this additive: the user's own
    AGENTS.md and any instruction files they already listed stay untouched.

    The value is the absolute path, not a relative one. OpenCode resolves a
    relative entry in this list by walking up from the directory being worked
    in -- the project, never the configuration root -- so `./{identity.
    program_name}-AGENTS.md` written into the global configuration names a
    file that exists nowhere the runtime looks, and the whole system prompt is
    dropped without a word. An absolute entry is resolved against itself,
    which is the only spelling that means the file this artifact actually
    places.

    The filename itself comes from `identity`, not from `layout.system_prompt_
    file`: `layout` is built with no `Identity` in reach (see `adapter.layout`,
    called from many places that never carry one), so its own anchor stays the
    fixed, identity-unaware default -- correct only for the packaged
    distribution, and never consulted for what this function actually writes.

    The artifact's `id` carries the filename (`system-prompt:{name}`) rather
    than staying the bare, identity-blind `"system-prompt"` it used to be:
    `planner.retirements` marks a journal entry stale precisely when its `id`
    is absent from a new render, so an id that never changed across an
    identity change would read as an ordinary update at the *new* filename and
    silently orphan the *old* one on disk -- the exact rename-as-retire-and-
    create shape every other identity-derived artifact in this module already
    gets right because its own id already carries its filename.
    """
    path = layout.config_dir / f"{identity.program_name}-AGENTS.md"
    return [
        FileArtifact(
            id=f"system-prompt:{path.name}",
            path=path,
            content=_system_prompt_body(layout, item).encode("utf-8"),
            executable=False,
        ),
        ConfigKeyArtifact(
            id="system-prompt-instruction",
            path=layout.settings_file,
            pointer="/instructions/-",
            value=str(path),
        ),
    ]


def _system_prompt_body(layout: Layout, item: SystemPrompt) -> str:
    """The base prompt, then one section per server the user chose."""
    return _with_mcp_sections(layout, item.body, item.mcp_sections, "system-prompt")


def _agent_body(layout: Layout, item: Agent) -> str:
    """The agent's own prose, then one section per server it was granted.

    Composed exactly the way `_system_prompt_body` composes the base prompt:
    the two are the same idea at two different levels of the tree, and letting
    them diverge would be an accident of which one this module wrote first,
    not a real difference between an agent's own prompt and the shared one.
    """
    return _with_mcp_sections(layout, item.body, item.mcp_sections, item.name)


def _with_mcp_sections(
    layout: Layout, body: str, sections: tuple[Any, ...], owner: str
) -> str:
    """One prose body, then one section per server that survived selection.

    Concatenated here rather than composed in the content core because the
    separator is a fact about the file being written, not about the text: the
    core hands over bodies, and how they sit on a page is this adapter's
    business. Order follows the content core's, which is the filename order
    `_markdown_files` guarantees -- so two installs of the same selection
    produce the same bytes, and the digest that attests them means something.
    """
    parts = [_body(layout, body, owner)]
    parts += [_body(layout, section.body, str(section.source)) for section in sections]
    return "\n\n".join(part.strip("\n") for part in parts) + "\n"


MCP_VALUE: dict[Distribution, Any] = {
    # No `headers`: a remote server's authentication is the runtime's business,
    # not the descriptor's. OpenCode owns the OAuth handshake -- a person runs
    # `opencode mcp auth <key>` once and it keeps the token itself -- so a
    # secret never has to travel in a repository descriptor, which is the only
    # place it could not safely go. Not "needs none": the first remote server
    # shipped here needed none, and this comment used to say so.
    Distribution.REMOTE: lambda item, layout: {"type": "remote", "url": item.endpoint, "enabled": True},
    # The command points at where the fetched program will land, not where
    # it is right now: `render` never fetches, so this is the same path
    # arithmetic `materialize` uses to place it, computed here without ever
    # touching a filesystem. A bare binary places itself there directly; an
    # archive places its declared executable member there instead.
    Distribution.DOWNLOAD: lambda item, layout: {
        "type": "local",
        "command": [str(_download_command(layout, item)), *item.argv],
        "enabled": True,
    },
    # Same path arithmetic as `download`, pointed at the script `npm ci`
    # installs rather than a fetched binary: `render` never runs `npm`.
    Distribution.NPM: lambda item, layout: {
        "type": "local",
        "command": [str(_npm_command(layout, item)), *item.argv],
        "enabled": True,
    },
}
"""How to spell each distribution mechanism as an OpenCode server value.

Keyed by `Distribution` rather than branched with `if`, so a member added to
the core without a matching entry here fails at import instead of falling
through to whatever branch happened to run last.
"""

_UNMAPPED_DISTRIBUTIONS = [item for item in Distribution if item not in MCP_VALUE]
if _UNMAPPED_DISTRIBUTIONS:
    # Same reasoning as the catalog's own import-time invariant: a member the
    # core grows without teaching this adapter must be impossible to import,
    # not a silent fallthrough discovered in a user's installation.
    raise RenderError(
        "no OpenCode value for distribution(s): "
        + ", ".join(sorted(item.value for item in _UNMAPPED_DISTRIBUTIONS))
    )


def _download_command(layout: Layout, item: Mcp) -> Path:
    if layout.dependencies_dir is None:
        raise RenderError(f"{item.name}: this layout has no dependencies directory")
    return program_path(layout.dependencies_dir, item)


def _npm_command(layout: Layout, item: Mcp) -> Path:
    if layout.dependencies_dir is None:
        raise RenderError(f"{item.name}: this layout has no dependencies directory")
    return npm_script_path(layout.dependencies_dir, item)


def mcp(layout: Layout, item: Mcp) -> list[Artifact]:
    """The server as a settings key, plus its usage convention as a shared skill file.

    No guard around the lookup: the import-time invariant above already proves
    every mechanism has an entry, so a miss cannot happen and a branch for it
    would be unreachable code with a test that has to forge its own subject.

    A bound server contributes the convention alone. Writing `/mcp/<id>` for a
    server the user administers would stand a second definition beside the one
    they maintain, and the address arithmetic above would resolve a binary this
    install is never going to fetch. The convention travels either way, and it
    is named by the id, because that is the path agent bodies reference.
    """
    convention = FileArtifact(
        id=f"mcp-convention:{item.name}",
        path=_convention_path(layout, item),
        content=_body(layout, item.body, item.name).encode("utf-8"),
        executable=False,
    )
    if item.is_bound:
        return [convention]
    value = MCP_VALUE[item.distribution](item, layout)
    return [
        ConfigKeyArtifact(
            id=f"mcp:{item.name}",
            path=layout.settings_file,
            pointer=f"/mcp/{item.name}",
            value=value,
        ),
        convention,
    ]


def _convention_path(layout: Layout, item: Mcp) -> Path:
    """Where a server's convention lands, inside this layout's skills root.

    The layout inside the content tree -- `_shared/mcp/<id>-convention.md` -- is
    the core's call, made once in `mcp_convention_path`. This adapter's job stays
    what it always was: answering where the skills root itself lives on disk.
    """
    if layout.skills_dir is None:
        raise RenderError(f"{item.name}: this layout has no skills directory")
    return layout.skills_dir / mcp_convention_path(item.name)


def _mcp_cell(target: Any) -> str:
    """One target's MCP column: every key it reaches, flagging what a
    wildcard grant of that key does not actually cover.

    `target.withheld_mcp_tools` already carries the key-to-tools association
    -- this function's only job is formatting, per the split
    `delegation_capabilities`'s docstring states. A key with nothing withheld
    renders bare, exactly as it always did; a key that withholds anything
    never renders bare, because bare is what a delegator reads as "granted in
    full" and that reading would be false.
    """
    withheld = dict(target.withheld_mcp_tools)
    parts = [
        f"{key} (withholds: {', '.join(withheld[key])})" if key in withheld else key
        for key in target.mcp
    ]
    return ", ".join(parts) or "none"


def delegation_capabilities(layout: Layout, targets: tuple[Any, ...]) -> list[Artifact]:
    """The generated reference every delegating body's pointer names.

    `targets` is `core.catalog._delegation_targets(content)`, computed once
    after `select_mcp`/`grant_mcp` have already pruned and granted -- this
    function never reasons about which servers the user chose or an agent's
    `may_delegate_to`, only about how the facts it was handed sit on a page.
    That split mirrors `_with_mcp_sections`: the core hands over facts, and how
    they read as a markdown table for this CLI's prompts is this adapter's own
    business.

    A markdown table, not a bare list, because a delegator scanning for one
    target's row is the whole point of the file existing at all -- a wall of
    prose would cost exactly the read time this design exists to save.

    `target.withheld_mcp_tools` is the same kind of already-made fact as
    `target.mcp` itself: `core.catalog` decides which withheld tool belongs to
    which server key (a fact, not a presentation choice), and this function
    only decides how that association reads on the page (`_mcp_cell`). This is
    the same split `_with_mcp_sections` draws for a body's per-server prose --
    the core hands over the fact already associated, the adapter only ever
    formats it.
    """
    if layout.skills_dir is None:
        raise RenderError("delegation-capabilities: this layout has no skills directory")
    header = "| Agent | Native tools | MCP servers |\n| --- | --- | --- |\n"
    rows = "".join(
        "| `{name}` | {tools} | {mcp} |\n".format(
            name=target.name,
            tools=", ".join(sorted({*target.requires_tools, *target.optional_tools})) or "none",
            mcp=_mcp_cell(target),
        )
        for target in targets
    )
    text = (
        "# Delegation Target Capabilities\n\n"
        "Generated -- never hand-edited, and never a snapshot: every install regenerates\n"
        "this from the content core's own agent declarations, after this machine's own\n"
        "MCP selection and grants have already been applied. One row per agent that is\n"
        "the declared target of at least one other agent's `may_delegate_to`: what it\n"
        "reads here is what an install actually grants it, `granted_mcp` included\n"
        "alongside `optional_mcp`, because a target that can do something a delegator\n"
        "did not know about is cheap, and a target a delegator wrongly assumed could do\n"
        "something is the expensive direction this file exists to close.\n\n"
        "A server listed with `(withholds: ...)` still grants every tool it exposes\n"
        "except the ones named -- a wildcard grant with a tool or two taken back out,\n"
        "never the whole server refused. Assuming one of those named tools is\n"
        "reachable is exactly the wrongly-assumed-capability mistake this file exists\n"
        "to close, so it is never left off the row.\n\n"
        "Read this before writing a brief that assumes a target can run a command, open\n"
        "a browser, or write a file. If this reference is missing or unreadable, do not\n"
        "assume the capability: verify it directly, or ask for less.\n\n"
        + header
        + rows
    )
    return [
        FileArtifact(
            id="own:delegation-capabilities",
            path=layout.skills_dir / delegation_capabilities_path(),
            content=text.encode("utf-8"),
            executable=False,
        )
    ]


def _body(layout: Layout, body: str, owner: str) -> str:
    """Answer the placeholders a body left for its installer.

    A body names facts, not paths, so that one text installs under every CLI.
    This is where those facts become this layout's directories.
    """
    try:
        return placeholders.fill(body, facts(layout))
    except placeholders.Unanswered as missing:
        raise RenderError(
            f"{owner}: this layout has no {missing.name}, so the body cannot be filled"
        ) from None


def facts(layout: Layout) -> dict[str, str]:
    """What this layout can answer. An absent anchor answers nothing, never a blank.

    Public to this package so `adapter.own_artifacts` answers a bundled asset's
    `skills_root` from this one function rather than from a second copy of the
    same rule -- two copies is how one of them ends up drifting.
    """
    facts: dict[str, str] = {}
    if layout.skills_dir is not None:
        facts["skills_root"] = str(layout.skills_dir)
    return facts


def _prompt_path(layout: Layout, item: Agent):
    if layout.prompts_dir is None:
        raise RenderError(f"{item.name}: this layout has no prompts directory")
    return layout.prompts_dir / f"{item.name}.md"


def _tools(item: Agent) -> dict[str, bool]:
    """A deny baseline, then exactly the declared tools turned back on.

    Without the baseline, naming a tool only ever adds to the runtime's own
    defaults: it can grant, never restrict. Starting from `{"*": False}` is what
    makes "declare nothing" mean "nothing", instead of "whatever the runtime
    would have given anyway".

    `tools` is deprecated in the runtime's own schema in favour of `permission`
    (see `_permission` below), but it still keeps being rendered: a runtime old
    enough to only read `tools` would otherwise lose every restriction this
    agent declares, silently turning it unrestricted. A runtime that reads both
    derives its own permission set from this map first and then applies the
    explicit `permission` block on top key by key, so rendering both is never a
    conflict -- only ever the same restriction expressed twice, once for each
    reader.

    `apply_patch` is absent from `TOOL_NAME` on purpose, and the reason is the
    one thing `"*": False` cannot be read as fixing. The runtime does not carry
    `apply_patch` as a permission of its own: `packages/opencode/src/permission
    /index.ts` folds `edit`, `write` and `apply_patch` onto one `"edit"`
    permission before it ever asks this dict anything, so granting any one of
    the three grants all three. For every tool this module actually names, the
    deny baseline closes what the agent did not ask for; for `apply_patch` there
    is nothing here for it to close, because the collapse happens upstream of
    this map entirely, on a runtime you cannot instruct from `tools` at all.
    Reading `"*": False` as though it reached `apply_patch` too is exactly the
    mistake this docstring exists to head off.

    That also means adding `"apply_patch": False` to `TOOL_NAME` would not
    plug the gap -- it would produce a `permission.apply_patch` key the
    runtime never consults, because its own config loader (`packages/core/src
    /v1/config/agent.ts`, `normalize`) checks the literal string `"patch"`,
    not `"apply_patch"`, when it decides whether that permission was declared.
    A key spelled `apply_patch` there is a silent no-op: present in the
    rendered JSON, read by nothing. The only lever that actually reaches
    `apply_patch` is denying `edit` itself -- which also takes writing away
    from the agent entirely, since the two are the same permission. There is
    no way to keep `edit` and lose `apply_patch` beside it. So every agent
    this map grants `edit` or `write` to also receives `apply_patch`, and that
    is not an escalation this table failed to prevent: `apply_patch` can only
    ever write what `edit` already allows.
    """
    names = (*item.requires_tools, *item.optional_tools)
    unknown = [name for name in names if name not in TOOL_NAME]
    if unknown:
        raise RenderError(f"{item.name}: no OpenCode name for tools {', '.join(sorted(unknown))}")
    granted = {TOOL_NAME[name]: True for name in names}
    # No table needed here: `mcp()` below writes each server at `/mcp/<id>`, so the
    # id IS the server key OpenCode matches tools against, and `f"{id}*"` is that
    # same key with the wildcard OpenCode uses to grant every tool under it.
    granted.update({f"{mcp_id}*": True for mcp_id in item.optional_mcp})
    # `granted_mcp` writes the same shape of wildcard, for a server the user
    # administers rather than one Pegasus ships -- see `content.grant_mcp`'s
    # docstring for why it is a separate field. Written after the shipped
    # `optional_mcp` wildcards above (nothing to order against there: the two
    # sets never share a key, `grant_mcp` refuses that collision) and before
    # `denied_mcp_tools` below for the same resolution-order reason as
    # everything else here: a user's own server carries no `denied_mcp_tools`
    # of its own, but a shipped server's already-denied tool must still win
    # over this wildcard if the two ever named the same qualified tool.
    granted.update({f"{key}*": True for key in item.granted_mcp})
    # `denied_mcp_tools` is already the fully-qualified names `select_mcp`
    # resolved for this agent (`content.py`), so nothing here needs to know
    # which server a name belongs to or which key it was granted under.
    # Written after the wildcard above for the same resolution-order reason
    # the deny baseline is written first: the runtime keeps the *last* rule
    # that matches a given name, so a narrower `False` only wins over the
    # broader `f"{mcp_id}*": True` grant by being the later entry.
    granted.update({name: False for name in item.denied_mcp_tools})
    return {"*": False, **granted}


def _permission(layout: Layout, item: Agent) -> dict[str, Any]:
    """The one map the runtime actually resolves tool calls against.

    Everything `_tools` expresses is repeated here directly, rather than left
    for the runtime's own `tools`-to-`permission` translation to infer, because
    that translation is exactly the trap: a plain rename of a granted `write`
    into a `permission["write"]` key would govern nothing, since the schema
    folds `write` onto `edit` (`PERMISSION_NAME` above), and this agent would
    silently lose the ability to write.

    `apply_patch` is missing from `PERMISSION_NAME` for the same reason it is
    missing from `TOOL_NAME`, and it is worth restating here rather than only
    in `_tools`, because this is the map a reader might reach for first to
    look for a permission by name. `edit`, `write` and `apply_patch` are not
    three permissions in this runtime; they are one -- the fold happens in
    `packages/opencode/src/permission/index.ts`, upstream of everything this
    function writes -- so granting `edit` (or `write`, which lands on the same
    key) already hands an agent `apply_patch` too, and there is no name this
    dict could withhold to stop that. Writing `"apply_patch": "deny"` here
    would not withhold it either: the runtime's config loader looks for the
    literal key `"patch"`, not `"apply_patch"` (`packages/core/src/v1/config
    /agent.ts`, `normalize` -- see `_tools` above for the full citation), so a
    key spelled `apply_patch` would sit in the rendered JSON governing
    nothing a real tool call ever checks. The only way to actually take
    `apply_patch` away is denying `edit`, and that removes the agent's ability
    to write outright -- `apply_patch` was never a separate grant to revoke.
    None of this is an escalation this map is failing to close: `apply_patch`
    can only replay what `edit` already permits, so `"*": "deny"` below is not
    lying about what it denies -- it is simply silent about a name this
    runtime never lets it address on its own.

    The deny baseline has to come first for the same reason `_tools` puts it
    first: resolution takes the *last* matching rule, so `"*": "deny"` only
    ever loses to a grant written after it.

    `task` is the one entry this module has always authored straight into
    `permission`, never through `tools` -- delegation has no native-tool
    equivalent to derive it from -- and it keeps landing last, unaffected by
    the tool and MCP grants next to it: it is resolved against a delegate's
    name, not against the tool-call action namespace the rest of this map
    shares with the deny baseline.

    `external_directory` is authored the same way, and for the opposite reason
    to `task`: it is not a tool at all, so nothing in `tools` could ever derive
    it, yet the deny baseline still reaches it. Granting a tool is not granting
    every path it can be pointed at -- the runtime asks separately, under this
    name, the moment a target sits outside the project worktree -- and a
    baseline that says `*` says this too.

    That inner baseline used to split by `item.mode`: `"deny"` for a
    sub-agent, `"ask"` for a primary. Reported wrong from real use -- a
    sub-agent (`sdd-verify`) was pointed at a working directory outside its
    worktree and refused outright, with no prompt, even though its own `bash`
    permission was `allow`. The reasoning behind the split was that a
    sub-agent has nobody to prompt, so a clean, immediate refusal beats a
    hang. That is not what a config-level `"deny"` actually does, though: the
    runtime's own `ask()` returns a `DeniedError` the instant it sees one,
    before it would ever publish a prompt, and an approval only ever
    concatenates onto the *end* of that same rule list -- so a `"deny"` can
    only be beaten by an approval that already exists, granted earlier by
    another session that happened to ask about the exact same path. For a
    directory only one sub-agent's session ever touches, no session asks
    first, so no approval to out-rank it is ever created -- `"deny"` there is
    not "refuse this once", it is "make asking about this path impossible for
    the rest of the runtime's life", with no session, restart, or person able
    to reverse it. (On the newer engine the two engines both ship, V2, a
    configured `"deny"` is checked *before* any approval is even consulted,
    so there the refusal is absolute regardless of what anyone approved --
    which only makes writing `"deny"` here worse, never safer.) The runtime's
    own agents do not carry this split either: they all default to `"ask"`
    (`packages/opencode/src/agent/agent.ts`). So every agent, sub-agent
    included, now gets `"ask"` -- a sub-agent has nobody in its own session to
    answer the prompt, but `"ask"` still leaves the door open for a person to
    approve it from wherever they can (a primary session naming the same
    path, or a future surface that lists pending asks), which is exactly the
    difference between a refusal and a refusal that can never be undone. With
    both modes now resolving to the same value, the split itself carries no
    information any more, so `item.mode` no longer has a say here at all --
    `AgentMode` is still imported for `MODE_NAME` above, just not read by this
    function any more.

    Every path Pegasus hands an agent -- a phase agent's own SKILL.md, the
    `_shared` conventions each prompt defers its detail to -- lives under the
    skills directory, which is outside every worktree, so the lazy-loading
    contract is unreadable by construction without this. The grant is scoped
    to that directory and not to the config directory above it, even though
    both sit outside the worktree: the settings file is the config
    directory's own resident, and it carries whatever a server the user
    administers was configured with. Nothing shipped needs to read it, so
    nothing shipped is allowed to. It is earned rather than given, too -- only
    a tool that actually asks under this name (`EXTERNAL_DIRECTORY_TOOLS`
    above) brings it, so declaring nothing keeps meaning nothing -- except for
    `item.granted_directories` just below, which brings it on its own.

    `item.granted_directories` -- paths the person declared through
    `pegasus directory grant`, the same shape `Install.granted_mcp` already
    established for a fact Pegasus cannot know on its own -- are written into
    this same map, one `f"{path}/*": "allow"` entry per granted directory,
    after the baseline and the skills exception. Order is the only thing that
    makes them win (the runtime keeps the *last* rule matching both name and
    target), and it is why they are written last rather than folded into the
    dict literal below. They reach every agent, primary or sub-agent alike --
    a working directory a sub-agent needs is exactly the case this whole
    mechanism exists for -- and they earn the `external_directory` key on
    their own even for an agent whose declared tools would not otherwise
    trigger it, since a directory the person explicitly granted must still
    reach an agent that, say, only writes.

    The inner baseline is the same shape `task` uses, and writing it out is
    deliberate even though the outer baseline already denies this name too:
    the runtime flattens every key of this map into one ordered rule list and
    keeps the last rule matching both name and target, so an unlisted path
    outside the worktree already falls to the outer baseline regardless.
    Writing `"ask"` where the exception lives makes the boundary a property
    of this entry rather than an inference across two, which is what lets a
    test assert it directly.

    That inner baseline has since moved again, from `"ask"` to `"allow"`, and
    this second move is the product's own deliberate choice, surfaced by a
    named upstream bug rather than dictated by it -- not a second round of
    the same reasoning as the paragraph above; that reasoning is not
    repudiated, it is superseded at one depth and left standing at two
    others. The bug that forced the choice into the open is upstream issue
    #39112 ("Sub-sub-agents (depth: 2)
    'ask' permission doesn't surface to user and stalls"), still open, plus
    the same-shaped #43996 and #44747, and one predecessor, #30635, that
    OpenCode closed by fixing only one level of the problem. The cause lives
    in `packages/tui/src/routes/session/index.tsx`: the view that lists
    pending permissions only ever walks one level of the session tree --

        const children = createMemo(() => {
          const parentID = session()?.parentID ?? session()?.id
          return sync.data.session.filter((x) => x.parentID === parentID || x.id === parentID)
        })
        const permissions = createMemo(() => {
          if (session()?.parentID) return []
          return children().flatMap((x) => sync.data.permission[x.id] ?? [])
        })

    -- so a permission raised by a session two levels below the root (a
    sub-agent's own sub-agent) is never in `children()`, never reaches
    `permissions()`, and is never rendered in any view, root or otherwise.
    Nothing times the wait out on the other side: the tool call that
    triggered the ask just hangs forever, because the runtime is correctly
    waiting for an approval that no surface will ever let a person give.
    Pegasus ships `subagent_depth: 10` (since 5.39.0), which is what turns a
    depth-two chain from an edge case into an ordinary shape -- the failure
    was hit live through exactly that chain, `pegasus-orchestrator` ->
    `pegasus-general` -> `pegasus-explorer`, where the explorer's own
    `external_directory` ask simply never appeared anywhere and the run sat
    stuck. Pegasus created the exposure by shipping a depth deep enough to
    reach the bug on every ordinary run; it did not create the bug itself,
    which is OpenCode's to fix.

    The paragraph above about `"ask"` beating a bare config `"deny"` is still
    true and still the reason this map never goes back to `"deny"` -- at
    depth zero and depth one, `"ask"` still renders a real prompt a person can
    answer, exactly as argued there. What changes here is narrower: at depth
    two or deeper, `"ask"` is not a slower `"deny"`, it is a hang with no
    floor under it at all, and that is strictly worse than either alternative
    this function has ever written for this key. `"allow"` is the one value
    available that fails safe under the bug instead of failing stuck, so the
    baseline moves to it, with `EXTERNAL_DIRECTORY_DENY_FLOOR` (module level,
    above) written last -- after the skills exception and after
    `item.granted_directories` -- so that resolution's last-match rule always
    lands on the floor for the handful of paths it names, regardless of what
    a grant written earlier in this same dict claims. This is a deliberate,
    reaffirmed choice, made after the depth-two hang was reproduced and the
    tradeoff was shown plainly: it removes the `external_directory` gate at
    every depth, including zero and one, where the gate used to work, in
    exchange for never hanging at depth two or deeper. The floor does not
    restore what is given up, and it is worth being exact about how little it
    does restore (see `EXTERNAL_DIRECTORY_DENY_FLOOR`'s own comment above for
    the full account): it denies the CANONICAL spelling of five directory
    names, by literal string match, with no `realpath` anywhere in the
    runtime's own check -- so it is a guard against an agent that wanders
    into one of them by accident, never a boundary against one that means to
    get there, since a symlink, bind mount, or an environment variable
    (`GH_CONFIG_DIR`, `AWS_SHARED_CREDENTIALS_FILE`) walks straight past it,
    and an agent already holding `bash` under this same `"allow"` baseline
    can build that indirection itself. It is also worth being honest about
    what this permission was already not doing before this change: it only
    ever fires for a path outside the project worktree, so it never guarded
    an in-worktree `.env` either before this flip or after it -- nothing that
    was actually protected by this permission is being unprotected by this
    flip. What the flip does add to the exposure is everything the floor
    cannot reach by construction: a `*.pem`, `*.key`, or `.env` living
    anywhere outside these five directory names -- which is most places a
    file can live -- is now reachable by any agent this map grants a file
    tool to, not merely unguarded in the abstract.

    One more consequence worth stating plainly, verified by re-reading this
    function rather than assumed: before this change, `external_directory`'s
    `"*": "ask"` was the only place anywhere in the map this function returns
    that ever wrote the permission value `"ask"` -- `task`'s own baseline is
    `"deny"`, and every tool and MCP entry above resolves to `"allow"` or
    `"deny"`. With that one site now `"allow"`, no Pegasus agent's rendered
    `permission` block contains the value `"ask"` anywhere, for any key. That
    means no Pegasus-shipped agent, at any depth, can still cause the runtime
    to raise a permission prompt at all -- every tool call this map governs
    now either proceeds or is refused outright, and there is nothing left in
    this configuration for a person to be asked to approve.

    Superseded in one place by the 7.5.0 decision: a sub-agent's `bash` now
    carries `SUBAGENT_BASH_PERMISSION`, whose `git push` patterns are
    `"ask"` (see that constant). It is the only `"ask"` Pegasus renders. The
    depth-two hang above applies to it too: at depth one the prompt surfaces
    in the root session; a sub-agent two levels down that pushes would wait
    on a prompt nobody sees.

    This baseline is not a stopgap awaiting an upstream fix. Keeping
    `external_directory` permissive by default is a deliberate product
    decision: the product's own reason for it is that having it enabled by
    default is an advantage in daily use, and that reason holds regardless
    of what happens to #39112 upstream. The analysis above of #39112 and its
    siblings is not a pending-revert clause attached to this baseline -- it
    stays because it explains how Pegasus arrived here, and fixing the bug
    upstream does not by itself argue for undoing the choice.
    `EXTERNAL_DIRECTORY_DENY_FLOOR` remains a separate question either way:
    nothing here, upstream fix or not, decides it one way or the other.

    One more thing worth being explicit about: `item.granted_directories`
    keeps being written into this dict for as long as the baseline itself is
    `"allow"`, even though its own entry is now a no-op everywhere the
    baseline already grants the same thing. That is deliberate, not an
    oversight to clean up -- a directory a person granted through `pegasus
    directory grant` stays recorded in the journal and keeps being rendered
    here, dormant rather than useless, so that grant is never silently lost:
    this dict does not depend on anyone remembering to re-run `directory
    grant` for it to mean something again, whatever the baseline does in the
    future. Removing `granted_directories` from this map while the baseline
    is `"allow"` would look like a harmless simplification -- it changes
    nothing observable today -- and would silently discard every grant on
    file, which nobody would notice until the day the baseline ever did
    change, when it would be too late to notice why access broke.
    """
    names = (*item.requires_tools, *item.optional_tools)
    unknown = [name for name in names if name not in PERMISSION_NAME]
    if unknown:
        raise RenderError(f"{item.name}: no OpenCode name for tools {', '.join(sorted(unknown))}")
    granted: dict[str, Any] = {PERMISSION_NAME[name]: "allow" for name in names}
    if granted.get("bash") == "allow" and item.mode is AgentMode.SUBAGENT:
        granted["bash"] = dict(SUBAGENT_BASH_PERMISSION)
    # Same reasoning as `_tools`: the MCP server id is the key the runtime
    # matches its tool-call actions against, and the wildcard grants every
    # tool that server exposes.
    granted.update({f"{mcp_id}*": "allow" for mcp_id in item.optional_mcp})
    # Same fact, same ordering reason as `_tools` above: a user-administered
    # server's wildcard, written after the shipped `optional_mcp` grants and
    # before `denied_mcp_tools` below, so a shipped server's withheld tool
    # keeps winning even if it ever shared a qualified name with this grant.
    granted.update({f"{key}*": "allow" for key in item.granted_mcp})
    # Same fact, same ordering reason as `_tools` above: a name already
    # qualified by `select_mcp`, written after the wildcard it narrows so the
    # runtime's last-match resolution lands on the deny, and before `task` and
    # `external_directory` below since neither of those shares this
    # namespace and their own position is unaffected by it either way.
    granted.update({name: "deny" for name in item.denied_mcp_tools})
    if any(name in EXTERNAL_DIRECTORY_TOOLS for name in names) or item.granted_directories:
        granted["external_directory"] = {
            "*": "allow",
            f"{layout.skills_dir.as_posix()}/*": "allow",
            **{f"{path}/*": "allow" for path in item.granted_directories},
            **EXTERNAL_DIRECTORY_DENY_FLOOR,
        }
    granted["task"] = {"*": "deny", **{name: "allow" for name in item.may_delegate_to}}
    return {"*": "deny", **granted}


def _frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    lines += [f"{key}: {_scalar(value)}" for key, value in fields.items()]
    lines.append("---")
    return "\n".join(lines) + "\n"


def _scalar(value: Any) -> str:
    """JSON is a subset of YAML, so this quotes exactly when quoting is needed."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)
