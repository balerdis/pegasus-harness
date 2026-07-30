# Migration TODOs

Historical upstream terminology appears in this document only; it is not a
runtime instruction.

1. The active legacy registry plugin remains outside this frozen Pegasus source.
   Phase 2 provides a non-active replacement template; follow
   `skill-registry-migration.md` for a future cutover and rollback.
2. The active `model-variants.ts` cache integration is intentionally not
   adopted because it depends on `~/.gentle-ai/cache/model-variants.json`.
3. `.gentle-ai-default-agent.json` remains in the active config for the rollback
   window and is intentionally not copied here.
4. Upstream intake is deliberately separate at the sibling
   `pegasus-harness-upstream-gentle/` location. It is never installed or a
   Pegasus runtime dependency.

No installer, activation procedure, or upstream adoption occurs in Phase 2.
