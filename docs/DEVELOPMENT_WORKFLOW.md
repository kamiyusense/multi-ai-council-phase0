# Development Workflow

## Purpose

Use GitHub as the shared development checkpoint between Chat, Jules, and future implementation sessions.

## Normal flow

```text
main
  -> feature branch
  -> edit / test
  -> commit
  -> push/update remote branch
  -> PR
  -> review
  -> merge after approval
```

## Rules for this repository

- `main` is the accepted line.
- Work happens on a dedicated branch.
- A commit SHA identifies an exact saved version of tracked repository contents.
- A PR is the review boundary before merging to `main`.
- No force push.
- No automatic branch deletion.
- No secrets.
- No `phase0-runs/` evidence directory in Git.
- Do not write to AIBO or the Council RAW repository from Phase 0 implementation code.
- Runtime GitHub write remains prohibited.

## Checkpoint convention

When handing work between agents, report:

- repository
- branch
- commit SHA
- changed files
- test status
- PASS / FAIL / UNKNOWN
- blockers
- whether live models were executed

If tests were not actually run, record **UNKNOWN**, not PASS.

## PR policy

At the current stage, user authorization is **PRまで**.

That means:

- branch writes: allowed within the requested development scope
- commits: allowed on the feature branch
- PR creation: allowed
- Merge: stop and wait for explicit approval

## Handoff policy

Prefer commit SHA over ZIP transport when the needed state is fully tracked in Git.

A ZIP may still be useful for:

- generated artifacts not meant for Git
- evidence bundles
- offline transfer
- preserving exact build outputs

But source-of-work checkpoints should normally use Git commit SHA.
