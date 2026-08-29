---
name: skill-creator
description: Create or update an OpenCode skill using the bundled skill-creator workflow
runs_as: orchestrator
execution: isolated
---

Load `skill-creator` first, then use it to create or update an OpenCode skill from the user's request.

If the request is ambiguous, ask one focused clarification before editing files.
