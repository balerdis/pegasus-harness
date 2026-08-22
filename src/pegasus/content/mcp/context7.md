---
name: context7
description: Up-to-date documentation for third-party libraries, frameworks, and CLIs
distribution: remote
endpoint: https://mcp.context7.com/mcp
---

# Context7 Convention (reference documentation)

Context7 serves the current documentation of third-party libraries, frameworks, SDKs, APIs,
and CLI tools, read from the source rather than recalled from training data. Prefer it over
your own memory for any external dependency: an API you last saw during training may have
been renamed, deprecated, or given a different signature since.

Context7 is documentation, not behavioral proof. It tells you what an interface claims to
be; only running the code proves the interface behaves that way in this project, on this
version, with this configuration. Never present a documented signature as a verified one.

Context7 is for code you did not write. For this project's own structure — callers, flows,
symbols, impact — use the codebase tooling and direct reads instead.

## Tool Order

1. `resolve-library-id` — turn a product name into a library id
2. `query-docs` — ask that library a single, specific question

Always resolve before querying. The only exception is a query that already carries an
explicit id in `/org/project` or `/org/project/version` form.

## Querying Well

- Ask one concept per call. Split a question that spans several, unless the question is
  precisely about how they interact.
- Be specific. "How to configure MCP servers in opencode.json" earns an answer; "mcp"
  does not.
- When this project pins a dependency, query that pinned version's docs. Documentation for
  a version you are not running is a plausible answer to the wrong question.
- Spend at most three calls per tool on one question. If three did not answer it, the
  remaining gap is unlikely to be a documentation gap — say what is missing and move on.

## Never Send Secrets

A query leaves this machine. Never put credentials, tokens, API keys, passwords, personal
data, or proprietary source into one. Describe the shape of the problem instead of pasting
the material that carries the secret.

## When Not to Use It

- Questions about this project's own code, conventions, or history
- General programming concepts that do not depend on a specific library's current API
- Refactoring, debugging, or reasoning about logic you or this project wrote
- Anything you can settle by reading a file in this repository
