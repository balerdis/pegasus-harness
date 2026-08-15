# Handoff — Lazy-load refactor of Sergio's live OpenCode install

**Date:** 2026-08-14 / 2026-08-15
**Source:** field work on the live install at `~/.config/opencode`, not on this repo
**Status:** complete and runtime-validated (13 probes)

## How to use this document

This is field evidence for v4 planning. Everything here was measured or probe-verified
against a running system; nothing is projected. Save it to this project's engram —
suggested `topic_key`: `architecture/sdd-prompt-lazy-load-findings`.

Sections 6, 7 and 8 are the ones that should change v4's design. Sections 2–5 explain
what was done and why it worked. Section 11 records what was deliberately left alone,
which matters as much as what was changed.

---

## 1. Outcome

| Layer | Before | After |
|---|---:|---:|
| `prompts/sdd/` (10 phase prompts) | 85.281 b / ~16.175 tok | 20.068 b / **~3.810 tok** |
| `AGENTS.md` | 13.015 b / ~2.591 tok | 10.486 b / **~2.109 tok** |
| `agents/pegasus-AGENTS.md` | 6.236 b / ~1.260 tok | 1.692 b / **~350 tok** |
| Duplication between those two | 82 identical lines | **0** |
| Always-on for `pegasus-orchestrator` | ~2.743 tok | **~2.390 tok** |
| Always-on for `king-gentleman` | ~3.851 tok | **~2.459 tok** |

For reference, the same treatment on the Claude Code side took `~/.claude/CLAUDE.md`
from 31.379 b (~11,6k tokens per request) to 5.903 b (~2,6k).

Token estimates use `ceil(words * 1.33)`, the formula in `lazy-load-framework.md`.

---

## 2. The central finding — the fat prompts contained nothing of their own

`prompts/sdd/sdd-tasks.md` was byte-identical to `skills/sdd-tasks/SKILL.md`.
`sdd-apply` differed in exactly one line (a path-prefix variant). Across all 10 phases
only 12 lines existed in a prompt but not in its skill, and all 12 were the same rules
rewritten with a `../../skills/...` prefix — plus `sdd-verify`'s genuine Pegasus identity
text, which was preserved verbatim.

So this was never a risky identity/procedure split. The procedure already lived in the
skills; the prompt copy was pure duplicated always-on cost. Deleting a copy is a much
lower-risk operation than splitting a fused document, and v4 should frame it that way.

---

## 3. Root cause of the duplication

8 of the 10 skills open with an ORCHESTRATOR GATE:

> If you loaded this skill via the `skill()` tool, you are the ORCHESTRATOR — STOP.

followed by an Executor Override telling the executor not to call the Skill tool. The
executor was therefore forbidden from calling `skill()`, and copying the skill body into
its system prompt was the only way to give it the procedure.

The fix is not to remove the gate. It is to have the executor obtain the procedure by
**direct file read of an absolute path**, which satisfies both the gate and lazy loading.
v4 should make this the sanctioned mechanism rather than an accident of workaround.

---

## 4. The macro shape that worked (~350–440 tokens per phase)

1. **Identity** — role and what the phase owns, 2–3 sentences derived from the skill's
   Purpose/Activation section.
2. **Non-delegation** — not the orchestrator; no sub-agents; explicitly no `skill()`,
   *with the reason* (the ORCHESTRATOR GATE names you as the executor).
3. **Required loading gate** — "your FIRST tool call must read `<absolute path>`", a
   one-line inventory of the concerns that file owns, and fail-closed behavior naming the
   exact project literal (`blocked`), plus "do not infer, do not search for substitutes".
4. **Path resolution** — per-phase; see section 6.
5. **Result identity** — the exact return heading plus one truthfulness constraint.

Every one of the ten macros fits in 27–33 lines, against the framework's 80-line /
800-word / 1.050-token specialist budget.

---

## 5. Where the same treatment applied to the agent layer

`AGENTS.md` is OpenCode's global instruction file and loads for **every** agent. That was
probe-verified, not assumed: `king-gentleman` answered questions whose content exists only
in `AGENTS.md` (the CBM Priority Order, the "Persona Scope" section) *and* a question whose
content exists only in `pegasus-AGENTS.md` ("Never build after changes").

Consequently `pegasus-AGENTS.md` needed no sharing mechanism — only deletion. Of its 6.236
bytes, 83% was a copy of `AGENTS.md`; 17 lines were genuinely its own.

It was also **divergent, not merely duplicated**:

- an older Engram protocol, missing DELIVERY GUARANTEE, `capture_prompt`, prompt-capture
  behavior and the memory lifecycle rules;
- a stale 2-row skill auto-load table, superseded by AGENTS.md's `<available_skills>`
  mechanism;
- two rules that **contradicted** AGENTS.md — "use construction analogies to explain
  concepts" vs "when they clarify the point, not by default", and "(3) mention
  tools/resources" vs "only when they materially help".

Resolution: keep AGENTS.md's restrained version as the global rule, and re-state
king-gentleman's as an explicit, labelled **override** rather than a silent contradiction.

`agents/pegasus-orchestrator.md` was already correctly thin (834 b) and was left alone
apart from the preflight gate added in section 9.

---

## 6. Hazard v4 must solve — path conventions differ per skill

There is no single resolution rule. `sdd-apply` mixes **three forms in one file**:

| Form | Example | Resolves against |
|---|---|---|
| config-root relative | `skills/_shared/sdd-phase-common.md` | `~/.config/opencode/` |
| skills-root relative | `sdd-apply/references/cbm-index-coherence.md` | `~/.config/opencode/skills/` |
| skill-directory relative | `strict-tdd.md` | `~/.config/opencode/skills/sdd-apply/` |

`sdd-design` adds `references/threat-matrix.md`. `sdd-init` and `sdd-verify` use
`../_shared/...`. The other five use only `skills/...`.

While the procedure was pre-injected this was invisible. Once lazy, an unresolvable nested
reference is a Critical broken-reference smell. Each thin prompt had to spell out its own
skill's forms, which is why the ten macros could not share one template.

**v4 should normalize on ONE convention across all skills.** That single change would turn
ten bespoke macros into one generated template — plausibly converting a unit of manual
authoring into a render step.

Every macro must also state that `proposal.md`, `spec.md`, `design.md`, `tasks.md` and
`exploration.md` are **project artifacts** in the change's planning home, not files under
the skills root — and for `sdd-init`, that `.atl/skill-registry.md` lives in the target
project. Without that line an executor hunts for them in the skills tree.

### Second hazard — absolute paths are hardcoded today

The live macros hardcode `/home/serg/.config/opencode/skills/...` because it is a
single-user install. v4's renderer must template the skills root per installation and per
adapter layout, or the generated macros are not portable.

### Third hazard — ownership gap

`src/pegasus/content/agents/` currently ships only `pegasus-orchestrator.md` and
`sdd-verify.md`. The other 9 phase prompts came from gentle-ai. If v4 is to replace the
live install it must own all 11 prompts. The 10 rewritten macros are working drafts.

> Note: the gentle-ai *reinstall* risk is closed by decision, not by mitigation. Sergio
> controls this machine, has separated from gentle-ai entirely, and will not reinstall or
> update it. Treat the ownership gap as a migration item, not a live threat.

---

## 7. Runtime facts about OpenCode (measured, not documented)

### 7.1 Prompts and instruction files are cached per process

OpenCode loads agent `prompt: {file:...}` definitions and instruction files at **process
start** and never re-reads them. Editing a prompt has no effect until OpenCode is fully
restarted.

Proven by controlled before/after: `sdd-init.md` was rewritten at 23:57 containing the
sentence *"If that required path is missing or unreadable, STOP and return `blocked`
naming the unreadable path."* In the pre-existing session the `sdd-init` executor asserted
**twice** that no such rule existed in its system prompt. After a full restart the same
executor quoted that exact sentence and returned `blocked`.

**v4 actions:** the installer/renderer must tell the user to restart OpenCode after
writing prompts, and any automated harness test must spawn a fresh process or it validates
stale state.

### 7.2 Cross-runtime skill discovery — and its precedence

The OpenCode binary (1.18.18) discovers skills from **three roots**, not just its
configured `skills.paths`:

```
~/.claude/skills/<name>/SKILL.md
~/.agents/skills/<name>/SKILL.md
~/.config/opencode/skill(s)/<name>/SKILL.md
```

Verified by string-inspecting the binary and observed live — the `pegasus-orchestrator`
loaded a skill that exists only in `~/.claude/skills/`.

**Precedence was then probe-tested and resolved: local OpenCode skills WIN.** Two colliding
skills were checked with content-level discriminators, and both resolved to
`/home/serg/.config/opencode/skills/...`, with one entry each and no ambiguity. So
`~/.claude/skills` acts as a **fallback for names that do not exist locally**.

Consequences:

- The 17 name collisions between the two roots — including all 10 SDD phase skills, whose
  contents differ by 6 to 68 lines — are **harmless**. OpenCode always gets its own copy.
- The real exposure is limited to names that exist *only* in the Claude tree. There were
  two: `sdd-orchestration` (created during this work, now carrying a runtime gate telling
  any OpenCode agent to stop and use its own contract) and `judgment-day`, which was
  inspected and is benign — it names no Claude-specific agents or tools.
- This still argues **for** the absolute-path loading gate: loading by path always gets the
  intended copy; loading by name depends on a precedence rule that is undocumented and
  could change between OpenCode versions. v4 should treat path-based loading as the
  contract, not a convenience.
- If v4 ships skills whose names could collide with another runtime's, consider a
  `pegasus-` prefix, or a runtime gate at the top of anything discoverable elsewhere.

### 7.3 The system prompt is wrapped

OpenCode prepends its own preamble to the agent prompt. Executors asked for "the first line
of your instructions" answered `"You are an AI assistant accessed via an API."` or
`# Instructions` — never the macro's own first line. See section 8.

---

## 8. Probe design rules (earned the hard way)

An entire first probe round was discarded. It appeared to pass, but ran against
stale cached prompts *and* its payloads spelled out the paths, byte counts and rules to
check — so a stale-prompt executor could pass every gate by following the payload instead
of its macro. The probes could not distinguish "the macro is live" from "the payload
substituted for it".

The rules that survived:

1. **Name no path, no byte count and no rule in the payload.** Ask open questions; verify
   the answers against disk afterwards.
2. **Include an introspection block that forbids file reads** and asks whether the
   step-by-step procedure is already present. A thin macro must answer
   `NOT IN MY INSTRUCTIONS`; a fat prompt answers `YES`. This is the single most reliable
   discriminator.
3. **Never use the system prompt's first line as a discriminator** (section 7.3). Ask about
   the phase-specific section explicitly, and even then expect noise.
4. **For a phase whose old prompt was already thin** (`sdd-verify`, 637 b of pure identity),
   "does it contain the procedure" does not discriminate. Use the loading gate, the path
   rules and the fail-closed literal instead — none of those existed in the original.
5. **Ask for byte sizes of everything read, and for every file deliberately NOT read
   together with the exact condition that would activate it.** The non-loads are the real
   evidence of lazy loading.
6. **Scope the probe so the fail-closed path is the expected outcome** (give no change
   name). That keeps it non-mutating by contract rather than by instruction — important for
   write-heavy phases like `sdd-init` and `sdd-archive`.
7. **Expect and welcome honest failures.** Two executors declined to fabricate: one refused
   to supply a literal it could not source, another reported that its file-read tool
   exposed no byte metadata instead of inventing numbers. Both are the desired behavior.

A probe that a stale or fat prompt can also pass is not a probe.

---

## 9. The undefined contract that was closed

Eleven command files under `commands/sdd-*.md` assert:

> SDD Session Preflight must already be complete for this session. It must include
> execution mode, artifact store, chained PR strategy, and review budget. If missing, ask
> the exact orchestrator preflight prompt and STOP.

**No file anywhere defined what preflight is, and no "exact orchestrator preflight prompt"
existed.** Every command asserted a precondition nobody owned.

> **Homonym warning for v4:** `docs/pegasus-v4/arquitectura.md` and `src/pegasus/cli.py`
> also use the word "preflight", but that is the CLI installer's `ensure_writable()`
> journal check — an unrelated concept. Grepping for "preflight" in v4 docs finds the
> wrong thing.

Resolution: the commands keep the **gate** (whether work may proceed); a new
`skills/_shared/sdd-session-preflight.md` owns the **definition** — the four decisions,
their option literals and defaults, caching rules, ordering against the `sdd-init` guard,
and the exact prompt text. The orchestrator carries a ~10-line eager pointer.

**Why the gate is eager in the orchestrator and not only behind command files:** a
natural-language SDD request ("haceme un SDD para X") never loads a command file. If the
definition lived only behind `commands/`, NL requests would silently skip preflight. This
was probe-confirmed both ways — the orchestrator stated the rule applies to slash commands
*and* NL requests, and when given an NL SDD request it asked the four decisions and stopped
rather than starting an exploration.

Cost: +129 tokens always-on for the orchestrator, to close a contract 11 commands assumed.

**Two self-corrections during this work, both instances of "never invent wire labels":**

1. The first draft used `artifact_store.mode`, `delivery_strategy` and `chain_strategy` as
   parameter names. Those come from the Claude-side skill and appear in **zero** OpenCode
   files. OpenCode uses prose labels: `Artifact store mode`, `Delivery strategy`,
   `Chain strategy`.
2. The first draft listed two `Chain strategy` values. OpenCode defines **four**:
   `stacked-to-main | feature-branch-chain | size-exception | pending`, and `sdd-apply`
   returns `blocked` when neither a delivery decision nor a chain strategy is present.

Final check: 16/16 literals used in the definition verified to exist in the OpenCode tree.

---

## 10. Contract rules observed

From Sergio's `lazy-load-prompt-audit` skill and `references/lazy-load-framework.md`:

- Never hand-edit generated copies; the durable fix belongs in the canonical source.
- The macro must name exact path + WHEN + concern owned + fail-closed result.
- **Ownership:** the framework's "Macro Versus Reference" table assigns *required-path
  fail-closed behavior* to the **macro**, not to the reference. Do not duplicate it into
  skills — one canonical owner only. A probe initially mis-scoped this and produced a false
  finding against `sdd-init`; the fix was to the probe wording, not to any file.
- **Preserve exact wire literals, never invent them.** Preserved here: `blocked`,
  `## Implementation Progress`, `## Exploration: {topic}`, `## Proposal Created`,
  `## Specs Created`, `## Design Created`, `## Tasks Created`, `## Change Archived`,
  `## Onboarding Complete! 🎉`, `## Verification Report`, and
  `PASS` / `PASS WITH WARNINGS` / `FAIL`.
- **Macro growth requires a recorded measured exception.** One was recorded: `sdd-verify`
  grew 124 → 389 tokens because it gained a loading gate, fail-closed behavior and path
  resolution it never had; it previously relied on implicit skill auto-invocation with no
  failure contract.
- A proposal to append a `procedure loaded: <path> (<bytes>)` line to each return report was
  **rejected**: it would alter the wire contract the orchestrator parses. The gate instead
  requires the skill read to be the executor's FIRST tool call, which is observable in the
  TUI without changing any contract.

---

## 11. What was deliberately NOT changed, and why

**`commands/*.md` duplication.** Sixteen command files carry ~4.698 bytes of repeated
material — the `git rev-parse --show-toplevel` cwd workaround appears in 9 files, the
"current project" line in 10. It was left alone. Commands are **lazy and mutually
exclusive**: exactly one loads per invocation, never two together, so the duplication costs
**zero tokens at runtime**. Centralizing it would add a file read to every command
invocation in order to save maintenance on lines that rarely change.

This is the same framework criterion producing the opposite verdict from the phase prompts,
and the distinction is worth carrying into v4: **phase prompts were paid on every request;
commands are paid once, when used.** Optimize the first, leave the second.

**The CBM protocol layering.** An early claim that CBM had "five owners / High-severity
ambiguous ownership" was **wrong and retracted**. `AGENTS.md` holds the general preference,
and `sdd-explore`, `sdd-design`, `sdd-apply` and `sdd-verify` each specialize it with a
different WHEN, a different tool subset and a different negative guard. That is correct
layering — general eager, specialization lazy. **Do not consolidate them.**

The only CBM change made was to strengthen the eager block: four illustrative examples with
invented identifiers (`OrderHandler`) were moved to a lazy reference, and an **Index
freshness** subsection was added — check `index_status`, treat stale graph results as
provisional, never invoke CBM through Bash. That safety rule existed only inside the
per-phase SDD skills; the always-on copy was the weakest version of the protocol.

**The CBM Priority Order was not compressed.** It is routing that governs the first tool
call of any task, so its one-line tool descriptions are what make it actionable.
Compressing it would trade correctness for ~80 tokens.

---

## 12. Runtime evidence — 13 probes, all after a full restart

**All 10 SDD phases validated:** apply, design, init, verify, tasks, archive, propose,
spec, explore, onboard. Plus both primary agents and the preflight gate.

- Each executor quoted **its own** macro's first line and reported "under 40 lines".
- Each answered `NOT IN MY INSTRUCTIONS` when asked whether its prompt already contained
  the phase procedure.
- Each recited a **different** path-resolution rule set — its own — which rules out a
  shared or hallucinated macro.
- **Every reported byte count matched disk exactly**: sdd-apply 16.237, sdd-design 8.562,
  sdd-init 4.212, sdd-tasks 11.555, sdd-archive 10.640, sdd-propose 9.575, sdd-spec 9.407,
  sdd-explore 6.297, sdd-onboard 7.976, `_shared/sdd-phase-common` 6.152.
- **Conditional lazy loading held everywhere.** Resolved but not loaded, each with its exact
  activation condition stated: `strict-tdd.md` (18.533 b), `strict-tdd-verify.md`
  (12.876 b), `threat-matrix.md`, `init-details.md`, `engram-convention.md`,
  `openspec-convention.md`, `report-format.md`, `sdd-status-contract.md`,
  `.atl/skill-registry.md`.
- `sdd-init` — the most write-prone phase — wrote no file and saved no Engram observation.
- `sdd-verify` independently surfaced **four** stop triggers, two more than expected: two
  from its macro and two from its skill (pending tasks → `blocked`; `actionContext.mode:
  workspace-planning` → STOP). Both skill triggers were confirmed against disk.
- `sdd-explore` answered "what must you return with no change name?" with
  `NOT IN MY INSTRUCTIONS`. Correct — `grep -c 'return \`blocked\`'` on its skill returns 0,
  because exploration does not require a change name. It declined to invent a literal.

---

## 13. Suggested v4 unit shape

A unit that:

1. **normalizes skill reference paths to one convention** across all skills — the single
   highest-leverage change, because it collapses ten bespoke macros into one template;
2. **adds a thin identity macro per phase** to `content/agents/`, generated with a
   **templated skills root** rather than a hardcoded one;
3. **takes ownership of all 11 prompts** instead of the current 2;
4. **ships a reusable loading-probe fixture** built on the section-8 rules, so each phase's
   gate is proven at build time rather than by hand;
5. **forces a fresh-process check** so that fixture cannot validate cached prompts;
6. **defines SDD Session Preflight in the canonical content tree**, since v4 will ship the
   commands that assert it.

---

## 14. File inventory

Live install, after the work:

| Path | Role |
|---|---|
| `prompts/sdd/*.md` | 10 thin identity macros with absolute-path loading gates |
| `AGENTS.md` | eager identity, persona, Engram triggers, CBM gate + index freshness |
| `agents/pegasus-orchestrator.md` | thin orchestrator identity + preflight gate |
| `agents/pegasus-AGENTS.md` | king-gentleman persona only, with declared overrides |
| `skills/engram-operations/SKILL.md` | new — lazy Engram operational detail |
| `skills/_shared/sdd-session-preflight.md` | new — canonical preflight definition |
| `skills/sdd-*/SKILL.md` | unchanged; they always held the real procedure |

Rollback points: `/home/serg/backups/opencode-config-20260814-212052.tar.gz` and
`/home/serg/backups/opencode-agents-20260815-015823.tar.gz`.
