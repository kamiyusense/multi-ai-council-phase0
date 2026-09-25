# Chat -> Jules API semi-auto smoke — 2026-09-26

Status: PASS for the bounded human-awake transport slice.

## Scope

This smoke proves one bounded cycle only:

```text
interactive Chat review/decision
  -> append one Jules command JSON on PR #6 branch
  -> GitHub push workflow
  -> exact target HEAD/tree gates
  -> one Jules API session creation
  -> Jules-created GitHub PR
  -> Chat/GitHub readback
  -> human decision boundary
```

It does **not** authorize unattended successor commands or Merge.

## Durable command

Command:

`chat-jules-semiauto-smoke-001`

Carrier command commit:

`5ef09b61a49d358a21feb9ede7b46e004ab7edf7`

Target:

- repository: `kamiyusense/multi-ai-council-phase0`
- branch: `feature/relay-transport-7070955470193506982`
- expected HEAD: `b8b7bb16f65039e6bf4c9425753a496abf70bea9`
- expected tree: `fccb1b57d31e98d4feac5e90e3d4e7e01edfce33`
- allowed path: `tests/relay/test_dispatcher.py`
- retry: `0`
- fallback: `disabled`
- Merge: forbidden
- force push: forbidden

## GitHub Actions evidence

Workflow:

`Phase 0 Chat to Jules semi-auto`

Run:

`36197977556`

Job:

`108278072545`

Observed gates:

1. exactly one newly-added command file — PASS
2. strict request validation — PASS
3. fresh exact target HEAD — PASS
4. fresh exact target tree — PASS
5. one Jules session POST — PASS

The Jules API response returned:

`sessions/8843876465361563911`

and returned the exact requested starting branch.

## Jules publication evidence

Jules created PR #14:

`test: cover repeated dispatch block for aborted slot`

PR #14 body identifies task/session:

`8843876465361563911`

Publication checks:

- PR base branch: exact target branch — PASS
- PR base SHA: `b8b7bb16f65039e6bf4c9425753a496abf70bea9` — PASS
- Jules commit: `d4232fae1d170c15ba4d41cc33793a098ef5a7ac`
- Jules commit parent: exact expected target HEAD — PASS
- compare from expected target HEAD: ahead by 1, behind by 0 — PASS
- changed files: exactly one — PASS
- changed path: `tests/relay/test_dispatcher.py` — PASS
- implementation/source changes: none — PASS
- Merge: not performed — PASS

## Semantic/readback validation

The new regression verifies:

1. first dispatch with `abort_signal={"aborted": True}` is BLOCKED;
2. the same slot remains BLOCKED on a second attempt;
3. second reason is `cancelled`;
4. provider `dispatch_count` stays `0`.

A reconstructed focused execution from the PR #14 source produced:

```text
first=BLOCKED
second=BLOCKED
second_reason=cancelled
dispatch_count=0
```

Focused unittest: PASS.

Relevant Python compile check: PASS.

No GitHub-hosted CI/check was present on the PR #14 head, so a full repository CI result is not claimed.

## Transport hardening after smoke

The first smoke used pinned:

`google-labs-code/jules-action@bff7875eaa123cac6742b7cfc51005b95ba4d566`

The run exposed concrete limitations for this carrier pattern:

- the action added carrier-branch commit/log context to the Jules prompt;
- session ID was visible in logs but not promoted as a durable workflow output;
- strict HTTP failure handling was not explicit enough for this route.

The PR #6 workflow was therefore changed, without replaying the smoke command, to a minimal direct Jules REST POST with:

- `curl --fail-with-body --retry 0`;
- exact response session-name validation;
- returned starting-branch validation;
- session ID written to step output/job summary;
- no carrier commit/log appended to the model prompt.

A readback-discovered branch-output typo in the hardened workflow was fixed before any command used that version. No second Jules session was launched for the same smoke.

## Completion boundary

The **human-awake semi-auto transport core is proven**:

```text
Chat -> durable command -> GitHub Actions -> Jules API -> Jules PR -> Chat readback -> human
```

Still out of scope:

- sleeping/unattended successor generation;
- automatic Merge;
- default-branch direct write;
- force push/history rewrite;
- permission/billing changes;
- automatic retry/fallback.

Human remains the final semantic/merge authority.
