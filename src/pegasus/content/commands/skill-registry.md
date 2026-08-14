---
name: skill-registry
description: Rebuild the OpenCode skill registry for the current project and installed skills
runs_as: orchestrator
execution: isolated
---

Load `skill-registry` first, then rebuild the skill registry for the current project and configured skill directories.

Return the registry path, skill count, cache status, and whether Engram was updated.
