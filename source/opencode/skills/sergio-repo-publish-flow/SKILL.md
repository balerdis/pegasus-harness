---
name: sergio-repo-publish-flow
description: "Trigger: subir cambios, publicar repo, commit push, sync testing, stable. Publish Sergio's repo changes from stable to testing."
license: Apache-2.0
metadata:
  author: "sergio"
  version: "1.0"
---

## Activation Contract

Use when the user asks to publish/upload repo changes, commit and push, sync `testing`, or move a production `stable/<numero_version>` branch forward.

## Hard Rules

- Do not edit application files as part of this workflow.
- Start by checking the current branch. Require a production branch named `stable/<numero_version>`.
- Treat the `stable/<numero_version>` branch as part of the release decision, not just a place to push. Before committing, classify the pending change and confirm the target version branch:
  - New feature, SDD feature slice, or change that exceeds the 400-line review budget and is being sliced as feature work -> next minor branch, e.g. `stable/0.2.0` from `stable/0.1.x`.
  - Small fix, bugfix, safe refinement, docs-only correction, or patch-level maintenance -> next patch branch, e.g. `stable/0.1.1` from `stable/0.1.0`.
  - Breaking change or incompatible behavior -> ask whether this is a major version branch, e.g. `stable/1.0.0`.
- Before any commit, push, checkout, merge, rebase, or reset, ask the user to confirm that the detected or proposed `stable/<numero_version>` is the correct current production branch.
- If the branch is wrong for the change type/version, switch or create only the user-approved target stable branch first. Never commit next-version work onto the previous production stable branch.
- Inspect `git status`, `git diff`, and recent log before staging. Stage only intended files.
- Exclude AI/tooling evidence, local artifacts, secrets, debug dumps, temp files, and unrelated changes.
- Run relevant validation for changed files when available.
- For small changes, use at most a simple pre-commit review. Do not invoke 4R, reliability, risk, or adversarial review patterns unless explicitly requested.
- Commit messages must be in Spanish, in Sergio's practical voice, with no AI attribution and no `Co-Authored-By`.
- Repo-facing comments, docs, PR text, and uploaded prose must be Spanish and follow `sergio-client-communication`; source code may stay English when the existing code context requires it.

## Decision Gates

| Situation | Do |
|---|---|
| Current branch is not `stable/<numero_version>` | Stop and ask for the correct production stable branch. |
| Detected stable branch is unconfirmed | Stop before branch-changing or publishing commands. |
| Current branch is an older stable branch, but the pending work belongs to a new version | Stop; ask whether to create/switch to the target branch such as `stable/0.1.1` or `stable/0.2.0`. Do not commit on the old branch. |
| Pending work is a new feature or oversized SDD feature slice | Prefer a next-minor target branch such as `stable/0.2.0`; ask before using a patch branch. |
| Pending work is a bugfix or small maintenance fix | Prefer a next-patch target branch such as `stable/0.1.1`; ask before using a minor branch. |
| Unexpected files are modified | Ask whether to exclude, keep, or abort. |
| Validation command is unclear | Run only safe obvious checks; report what was not validated. |

## Execution Steps

1. Check branch: `git branch --show-current` and confirm it matches `stable/<numero_version>`.
2. Inspect `git status --short`, `git diff`, and `git log --oneline -10` before deciding the target version.
3. Classify the pending work as feature/minor, fix/patch, breaking/major, or explicitly user-directed exception.
4. Propose the target stable branch from that classification and ask whether it is the correct current release branch. Wait for confirmation.
5. If needed, switch to or create the user-approved stable branch, then re-check branch and status.
6. Review changed files for secrets, local artifacts, AI/tooling evidence, and unrelated edits.
7. Run relevant validation for the changed files when available.
8. Stage only intended files and re-check `git diff --cached`.
9. Commit in Spanish using Sergio's voice. Do not include AI attribution.
10. Push the approved target stable branch.
11. Sync the pushed commit to `testing` using the repo's safe branch strategy, with validated branch context.
12. Checkout back to the approved target stable branch.
13. Verify final branch and clean status.

Compact command template; branch-changing/destructive steps require confirmed branch context:

```bash
git branch --show-current
git status --short
git diff
git log --oneline -10
# classify pending work and ask user to confirm target stable/<numero_version>
# if target differs from current branch, switch/create only after confirmation
git add <intended-files>
git diff --cached
git commit -m "<mensaje en español, voz Sergio>"
git push origin stable/<numero_version>
# confirmed sync to testing:
git checkout testing
git merge --ff-only stable/<numero_version> || git merge stable/<numero_version>
git push origin testing
git checkout stable/<numero_version>
git status --short
```

## Output Contract

Return the approved stable branch, commit hash, pushed branches, validation performed, excluded files, final branch, and final clean/dirty status.

## References

- `../sergio-client-communication/SKILL.md` — Sergio voice for Spanish repo-facing prose.
