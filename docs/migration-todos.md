# Migration TODOs

Historical upstream terminology appears in this document only; it is not a
runtime instruction.

1. `pegasus migrate` now materializes the Pegasus registry replacement with an
   exact-path rollback manifest. It has no legacy subprocess invocation.
2. `model-variants.ts` is retired only after the replacement is live and the
   active config is proved not to reference it; rollback restores its backup.
3. `.gentle-ai-default-agent.json` remains in the active config for the rollback
   window, and `~/.gentle-ai/` is intentionally not deleted.
4. Upstream intake is deliberately separate at the sibling
   `pegasus-harness-upstream-gentle/` location. It is never installed or a
   Pegasus runtime dependency.

No migration invokes the historical sync tool or an upstream uninstaller.
