"""What this adapter delivers for Claude Code.

The manifest is not Claude Code's feature list: it is the list of capabilities
this adapter actually implements today. The registry refuses to register an
adapter that claims more than it implements, so a capability stays False until
its render and the content it needs both exist.
"""
from __future__ import annotations

from pegasus.core.types import Capability, CapabilityManifest

CLI_ID = "claudecode"
DISPLAY_NAME = "Claude Code"

#: The person-facing reason this adapter declares `per_agent_model=False`
#: below -- read back through `CapabilityManifest.reason_for`, and shown
#: verbatim (never developer wording like "does not declare the
#: capability") in every surface that gates on it: `cli
#: ._require_per_agent_model`'s own refusal, `tui.session._models_screen`'s
#: placeholder, and the disabled row `tui.navigator.models_menu` shows
#: before a person ever walks into either of those.
_NO_PER_AGENT_MODEL_REASON = (
    f"{DISPLAY_NAME} has no local model catalog to read; it resolves provider and model against its own "
    "API at run time, so no model can be assigned per agent there."
)

MANIFEST = CapabilityManifest(
    cli_id=CLI_ID,
    skills=True,
    system_prompt=True,
    slash_commands=True,
    sub_agents=True,
    # Claude Code puts an agent's prompt in the body of the agent's own .md
    # file: one artifact, not two. So no `prompts_dir` in the layout and no
    # `render_prompt` method -- the registry rejects both if this capability
    # is not declared.
    prompts=False,
    # Claude Code has no documented location inside ~/.claude/ for a
    # session-wide MCP server definition: user scope lives in ~/.claude.json,
    # a SIBLING of that directory, and core.catalog._entries() hard-fails on
    # any artifact outside layout.config_dir. The in-tree alternative --
    # `mcpServers:` inside each agent's own frontmatter -- is what this
    # adapter now uses: `core.catalog.render` resolves, per agent, the `Mcp`
    # descriptors its own `optional_mcp` names and hands them to
    # `render_agent` as its `mcp` parameter (see `ports.cli_adapter.
    # CliAdapter.render_agent`'s own docstring), so this adapter carries no
    # per-machine state of its own between `render_mcp` and `render_agent` --
    # the fact travels through the port, not through anything this module
    # remembers.
    mcp=True,
    # Claude Code resolves models live or from env vars -- "no local cached
    # models.json file" (code.claude.com/docs/en/model-config.md) -- and its
    # `model:` field takes aliases (sonnet, opus, haiku, fable, inherit) or
    # full ids, while `ModelAssignment` is provider/model shaped. There is no
    # honest on-disk source to read a catalog from, so no `model_catalog`
    # method.
    per_agent_model=False,
    reasons={Capability.PER_AGENT_MODEL: _NO_PER_AGENT_MODEL_REASON},
)
