# Hybrid Work / Chat Reviewer Relay — P1 Checkpoint

Updated: 2026-09-23
Repository: `kamiyusense/multi-ai-council-phase0`
Branch: `feature/chat-work-command-bus`
Status: STATIC IMPLEMENTED / WORK VALIDATION PENDING
Live Browser POC: NOT STARTED

## 1. Current canonical target

PR #4:
- head: `f288ff552b9bdccecb614c84cdd2071b9e7db08f`
- tree: `7a03419c25ff1618a7d53724aa11b3de0e2eb995`

The Relay static batch `relay-static-apply-005` is terminal DONE and must not
be replayed.

Its durable Work receipt proves:
- TREE_IDENTITY_V1: PASS
- exact starting tree reconstruction: PASS
- baseline unittest: 22/22 PASS
- post-change unittest: 25/25 PASS
- compileall: PASS
- diff check: PASS
- remote fast-forward readback: PASS
- live provider/model/Jules/API-key: NO
- retry: 0
- fallback: disabled

Sol semantic review evidence:
`automation/command_bus/evidence/relay-static-apply-005-sol-review-20260923.json`

## 2. Durable reviewer V2

The existing reviewer protocol remains backward compatible with the earlier
reviewer smoke records.

A stricter profile was added for semantic review:

`DURABLE_REVIEW_V2`

V2 requests bind:
- request_id
- loop_id
- round
- correlation_id
- expected_target_head
- expected_target_tree
- reviewer_role
- review_kind
- evidence_refs
- allowed_decisions
- expires_at
- retry=0
- fallback=disabled

V2 responses bind:
- response_id
- request_id
- loop / round / correlation
- expected_target_head
- expected_target_tree
- reviewer identity + generation
- reviewer_role
- review_kind
- decision
- rationale_summary
- evidence_refs
- next_command_proposal or null
- model_route_evidence or null
- submitted_at

The request and response reject Chat/thread/browser-session identity as a
correctness field, including nested identity keys.

The durable backend revalidates target tree, reviewer role, review kind,
allowed decision, claim ownership/generation, expiry, predecessors, and record
graph during fresh-session recovery.

## 3. Transport-neutral wake layer

Added:
`automation/command_bus/reviewer_transport.py`

The transport wake contains only enough information to tell a reviewer to read
the canonical GitHub review_request. The authoritative response channel is:

`GITHUB_DURABLE_ONLY`

The transport layer does not parse free-form browser/Chat output.

Static P1 provides interchangeable mock routes:
- browser
- direct
- manual

All use the same durable wake contract.

The static coordinator:
- allows one logical wake attempt per request
- marks the request attempted before invoking a transport
- does not retry an ambiguous send
- keeps fallback disabled
- requires the eventual review_response to come from GitHub
- blocks live-capable transports entirely in P1

Therefore no live Browser/Chat/model POC is introduced by this checkpoint.

## 4. Regression fixtures

Added:
- `automation/command_bus/tests/test_reviewer_transport.py`
- `automation/command_bus/tests/test_reviewer_v2_backend.py`

Coverage includes:
- Browser and Direct route contract equivalence
- no Chat/thread/browser-session correctness identity
- duplicate wake => no second send
- wrong durable request path => fail closed before transport
- live-capable transport => blocked before send
- V2 happy path with target-tree binding
- wrong target tree => blocked
- disallowed decision => not consumable / not durably appendable
- wrong reviewer role => blocked
- nested session identity => blocked
- fresh durable recovery preserves tree identity
- corrupted recovered target tree => UNKNOWN

## 5. Validation state

A deterministic Work validation command exists:

`automation/command_bus/commands/hybrid-reviewer-p1-validation-001/000001.json`

Expected target:
- PR #4 head `f288ff552b9bdccecb614c84cdd2071b9e7db08f`

At this checkpoint the command state remains RUNNING and no terminal receipt
exists. The connected event-trigger task's observed last-run timestamp predates
the command commit. One wake-only PR comment was emitted; the logical command
was not duplicated or replayed.

Until a durable terminal receipt exists:
- full command-bus unittest result: UNKNOWN
- compileall result for the current P1 head: UNKNOWN
- diff-check result for the current P1 head: UNKNOWN

Do not promote these to PASS from static inspection.

## 6. Safety state

- PR #4 mutation after relay-static-apply-005: NO
- live Browser POC: NO
- live provider/model: NO
- Jules: NO
- API key: NO
- package install: NO
- Billing/Credits/Overages/settings/permissions changes: NO
- Merge: NO
- main direct write: NO
- force push: NO
- retry: 0
- fallback: disabled

## 7. Next safe actions

If `hybrid-reviewer-p1-validation-001` returns terminal PASS:
1. read back receipt/state and exact carrier head tested;
2. inspect the current PR #6 diff against this checkpoint;
3. create one durable V2 semantic review fixture/request-response flow using
   GitHub records only;
4. validate fresh-session recovery and receipt consumption;
5. keep Browser route mock-only.

If validation returns FAIL/UNKNOWN:
1. do not replay the command;
2. isolate the exact deterministic failure;
3. fix only PR #6 reviewer P1 scope;
4. create a new validation command only after the failure cause is understood.

Live Browser POC remains a separate explicit approval boundary.
