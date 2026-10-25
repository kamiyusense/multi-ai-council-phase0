# Symphony Actions: historical seal repair

AI-Agent: codex

## Cause and trust boundaries

Main `fab6f17a979bcfacd6b07804eb90bfa80edee446` failed all three current
validator commands because the G6.2 manifest describes the former Blue Work
workflow while commit `e0880da5d848cf7381a7424cf71550d4f0c25e13` made that
workflow manual-only. This repair changes no workflow and no historical evidence.

- Historical Blue bytes are read with `git show` at the existing immutable G6.2
  source pin `db578364c3bb22d5ed1af382085645cfb952f36e` and checked against the
  original byte count and SHA-256. Missing history fails; no current-file fallback.
- Current Blue bytes must separately match the exact approved manual-only commit.
  This retains all commands, read-only permissions, concurrency and evidence steps;
  a trigger, permission or body modification is refused.
- Historical manifests referring to the three repaired validators retain the
  pre-repair validator bytes at `fab6f17a979bcfacd6b07804eb90bfa80edee446`, unless
  an older explicit source pin already applies.
- The first repair's new `manifest.json` is also preserved, with its source at
  `17e50259742ff7b8061fcc8b9b5d3175c6562114`. The current repair and tamper tests
  have a separate `docs/evidence/symphony-actions-seal-repair/draft-compatibility.json`.
  No prior receipt or manifest is updated. Missing, duplicate, unexpected or altered
  current repair entries fail closed.
- Historical manifests referencing the controller, synthetic or installation CI
  use their pre-change main bytes. Current CI must match those exact bytes or only
  the approved three-line Draft/ready transition delta. All commands, permissions,
  concurrency, OFF gates and evidence remain byte-identical. Any other delta fails.

This is offline evidence validation, not LIVE authorization, worker permission,
result adoption, a billing change or proof of production readiness.

## Local validation

```sh
python -m automation.command_bus.scripts.validate_symphony_g63 --historical-only
python -m automation.command_bus.scripts.validate_symphony_g73
python -m automation.command_bus.scripts.validate_symphony_operator_static
python -m unittest automation.command_bus.tests.test_symphony_seal_history -v
```

The 20 repair tests include real immutable Git-object reads, historical/current
tampering, missing history, current source changes, missing/duplicate/traversal
manifest entries, and unchanged OFF/approval refusal. Related sender, approval,
ledger, host-recovery, Blue and trigger regressions add 126 existing tests.
All three validators also pass with the PR #476 delta and with all three permitted
workflow deltas combined. This is local integration proof, not a GitHub ready run.
No old evidence is rewritten, no provider runs and no GitHub Actions is manually
dispatched by these commands. Local PASS and GitHub CI evidence remain distinct.

## Merge dependency

Review and merge this repair before treating ready-for-review runs of the Draft
economy PRs as expected to pass the historical checks. Each PR requires separate
human merge authorization; creating Draft PRs does not activate production.
