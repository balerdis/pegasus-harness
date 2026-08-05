# Pegasus Harness Claude Code Adapter

Use the bundled canonical skills and local references.

- Claude Code receives no Pegasus plugins.
- Keep credentials in the user's supported secret or environment mechanism.
- For structural code discovery, caller and flow analysis, impact analysis, and test targeting, use CBM first when it is available. Direct file or search fallback is limited to literals, non-code files, configuration, unindexed or stale graph data, or CBM failure.
- CBM is code intelligence only. Runtime checks and tests prove behavior.
