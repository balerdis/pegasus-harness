# Pegasus Harness Claude Code Adapter

This adapter installs Pegasus canonical skills from `~/.claude/skills/`.

- Use the bundled skills and their local references as the authoritative Pegasus
  distribution inputs.
- Do not install or load Pegasus plugins for Claude Code.
- The ASI version skill is organization-private policy. It is not public or
  general-purpose guidance; apply it only when the requesting organization has
  authorized its policy.
- Keep credentials in the user's supported secret or environment mechanism,
  never in this file or a skill.
