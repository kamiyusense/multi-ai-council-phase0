# Hybrid Work / Chat Reviewer Relay — P1 Checkpoint

Updated: 2026-09-23
Repository: `kamiyusense/multi-ai-council-phase0`
Branch: `feature/chat-work-command-bus`
Status: STATIC IMPLEMENTED / WORK VALIDATION PENDING
Live Browser POC: NOT STARTED

## 1. Current canonical target

PR #4 latest observed:
- head: `2fc399ac7b415746763114c3951aa2e3b45adee7`
- tree: `9e2d22b7caf001449d1a5aa4fd374fec81a415fe`

The immediately preceding Relay implementation head
`f288ff552b9bdccecb614c84cdd2071b9e7db08f` remains terminally validated by
`relay-static-apply-005`. The newer `2fc399ac...` commit adds only static
hardening/regression work for pre-classification raw-evidence snapshots,
payload/correlation preservation, and provider-specific timeout isolation.
Its deterministic Work validation is pending under
`relay-static-regression-validation-006`.

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

Durable cross-session no-replay support is also implemented:

- `automation/command_bus/reviewer_wake_backend.py`
- one canonical append-only reservation path per review request:
  `review_wake_attempts/<loop>/<request_id>.json`
- the record contains a unique attempt_id but the GitHub path is keyed by
  request_id, so competing attempt IDs collide on the same durable create
  point
- only a reservation freshly created and independently read back by the
  current execution is eligible for a transport send
- a fresh Work/session that merely recovers an existing reservation receives
  `fresh_reservation=false` and must not send again
- an ambiguous reservation write/readback returns UNKNOWN and never triggers
  an automatic second send
- transport exceptions after reservation return UNKNOWN with retry=0
- Browser/Direct/Manual remain mock-only; live-capable transports are blocked

Therefore no live Browser/Chat/model POC is introduced by this checkpoint.

## 4. Regression fixtures

Added:
- `automation/command_bus/tests/test_reviewer_transport.py`
- `automation/command_bus/tests/test_reviewer_v2_backend.py`
- `automation/command_bus/tests/test_reviewer_wake_backend.py`

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
- one canonical wake reservation per review_request
- ambiguous reservation write => UNKNOWN / no resend
- recovered reservation => no transport authorization
- fresh verified reservation => at most one mock wake
- reservation path/route mismatch => UNKNOWN

## 5. Validation state

The first P1 command:

`hybrid-reviewer-p1-validation-001`

was never observed running. PR #4 subsequently advanced, making its
expected_target_head stale. Its mutable state was closed as UNKNOWN/STale; the
command must not be replayed.

A current read-only Relay regression validation now exists:

`automation/command_bus/commands/relay-static-regression-validation-006/000001.json`

It binds:
- PR #4 head `2fc399ac7b415746763114c3951aa2e3b45adee7`
- PR #4 tree `9e2d22b7caf001449d1a5aa4fd374fec81a415fe`
- blob count 39
- unittest command `PYTHONPATH=src python -m unittest discover -s tests -t . -v`
- compileall
- diff check
- retry=0 / fallback disabled / no live model

At this checkpoint the command is RUNNING with no terminal receipt. Its command
creation occurred after the last observed Work run, so one append-only
wake-only event marker was created. The logical command itself was not
duplicated or replayed.

Until durable terminal receipts exist:
- PR #4 regression commit `2fc399ac...` execution tests: UNKNOWN
- latest full command-bus unittest result for the current P1 code: UNKNOWN
- latest P1 compileall/diff-check: UNKNOWN

Do not promote these to PASS from static inspection. After Relay validation is
terminal, create a fresh P1 command-bus validation bound to the then-current
PR #4 head; do not revive validation-001.

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
