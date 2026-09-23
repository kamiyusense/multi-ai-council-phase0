# Jules Branch Smoke 002 Plan

Status: PREPARED ONLY — DO NOT LAUNCH UNTIL CONNECTOR VALIDATION PASSES
Updated: 2026-09-23

## Purpose

Prove that Work/Luna can start a fresh Jules task from the exact non-default
Relay target branch through the Jules web UI, without using the GitHub Issue
label route and without an API key.

## Current target snapshot

Repository:
`kamiyusense/multi-ai-council-phase0`

PR #4 branch:
`feature/relay-transport-7070955470193506982`

Expected head:
`2fc399ac7b415746763114c3951aa2e3b45adee7`

Expected tree:
`9e2d22b7caf001449d1a5aa4fd374fec81a415fe`

These values are not permanent. Fresh-read immediately before command creation
and launch. Any mismatch requires a new command identity or BLOCKED/UNKNOWN;
never silently retarget.

## Launch route

Required:
`WORK_CLOUD_BROWSER_JULES_UI`

Forbidden:
- GitHub Issue `jules` label
- Jules REST API
- API key
- implicit/default branch
- old Jules task reuse

Work must select:
- repository `kamiyusense/multi-ai-council-phase0`
- starting branch `feature/relay-transport-7070955470193506982`

If exact branch selection cannot be confirmed before submit:
BLOCKED/UNKNOWN, no Jules task.

## One bounded implementation task

Modify exactly:
`tests/relay/test_dispatcher.py`

Operation:
`MODIFY`

Add exactly one unittest regression proving:
`abort_signal={"aborted": True}`

blocks before:
- slot reservation
- provider dispatch

No implementation code change.

## Required deterministic tests

`PYTHONPATH=src python -m unittest discover -s tests -t . -v`

`python -m compileall -q src tests`

`git diff --check`

## Mandatory gates

Before Jules:
- current PR #4 head/tree == command expected head/tree
- fresh/disposable workspace
- TREE_IDENTITY_V1
- baseline tests PASS
- fresh append-only Jules launch reservation written and read back
- branch selection evidence preserved
- retry=0
- fallback disabled

After Jules publication:
- commit parent == expected target head
- source/base corresponds to target branch, not main
- target-relative changed path count == 1
- path == tests/relay/test_dispatcher.py
- operation == MODIFY
- no implementation changes
- post tests PASS
- remote readback PASS

No Merge. No automatic cherry-pick/rebase.

## Predecessor gate

Do not create/execute the live command until:
`jules-branch-route-validation-002`

has a terminal DONE/COMPLETE receipt proving the current PR #6 static contract
and tests pass.

If validation-002 is UNKNOWN/BLOCKED/FAIL:
do not launch Jules; isolate and repair under a new validation logical command.
