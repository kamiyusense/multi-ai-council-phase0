# Runtime Transition Publisher v1 — static checkpoint

## Baseline

- Baseline main: `58075061fea400121497b49bd029223fef432917`.
- PR #57 was merged before this batch.
- Issue #33 remained `STOPPED` with zero comments.
- PR #4 and PR #25 were not modified by this batch.

## Implemented publication flow

The provider-neutral Runtime Transition Publisher accepts a pre-existing
canonical command-bus receipt, an explicitly authorized owner context, a fresh
target-PR snapshot, independently verified provider evidence, and a canonical
evidence document.

It does **not** infer ownership from PR activity, timestamps, Chat silence,
Jules commits, Claude commits, or provider activity.

With all trust boundaries supplied, the single-attempt sequence is:

1. Validate request identities, prior/desired state and append-only owner chain.
2. Fresh-read state, target PR and source receipt.
3. Require an injected `OwnerAuthority`; missing/mismatched authority returns
   `NOT_WIRED` before mutation.
4. For active ACQUIRE/RENEW/HANDOFF, require an injected independent
   `ProviderVerifier`; caller input cannot set `verified=true`.
5. Run deterministic transition preflight before mutation.
6. Create/read back canonical evidence.
7. For active ownership, create/read back canonical provider observation.
8. Append/read back exactly the next owner generation using the existing
   `LoopOwnerGitHubBackend`.
9. Compare-and-swap mutable state using the freshly read GitHub blob SHA.
10. Re-read state, receipt, evidence, owner chain, provider observation and
    target; run final deterministic transition validation.
11. Only after full validation, prepare the Status refresh boundary.

No blind retry is used. Ambiguous writes are resolved by readback; unresolved
results stop as UNKNOWN.

## Additional Merge-prep hardening

Chat-side review added and exact-head CI verified the following before Merge:

- PR #59 files are included in the existing exact-PR-head GitHub Actions test
  workflow.
- Runtime evidence schema is parsed by CI.
- Target readback is canonicalized so richer PR snapshots may include tree,
  branch and other metadata without false mismatch.
- Active ownership requires the target PR to be OPEN and not merged.
- Initial deterministic target mismatch is BLOCKED; target drift after partial
  publication is UNKNOWN and does not prepare Status.
- Status-boundary failure is caught as UNKNOWN with `do not retry`; it cannot
  crash through the publisher.
- Verified TERMINAL closure may publish a BLOCKED Runtime state and close the
  owner without fabricating an active provider observation.
- RELEASE still requires a DONE receipt.
- Close generations can represent COMPLETE / RECONCILED_LATE_RESULT / HALTED /
  EXPIRED / BLOCKED / FAILED / UNKNOWN / WAITING_FOR_HUMAN_AUTH /
  HUMAN_COMPLETED_UNVERIFIED.
- Active generations remain restricted to RUNNING / WAITING_FOR_EVIDENCE /
  VERIFYING_POST_AUTH.

## Recovery / idempotency

- Identical immutable evidence already present: recover by readback, no create.
- Identical provider observation already present: recover by readback, no create.
- Identical owner generation already present: do not append a duplicate.
- Conflicting immutable record: BLOCKED/UNKNOWN.
- Ambiguous state CAS: read back exactly once; if desired state is present,
  recover, otherwise UNKNOWN and do not resend.
- If evidence/observation/owner append succeeded but state CAS did not, a later
  invocation may reconcile from exact readback without replaying immutable
  writes.
- Final target drift prevents Status preparation.

## Explicit trust boundaries still not wired

- `OwnerAuthority`: no production durable authority adapter yet.
- `ProviderVerifier`: no production independent provider-verification adapter
  yet.
- `StatusRefreshBoundary`: prepare-only; no live workflow dispatch adapter in
  this PR.
- Jules adapter: prepares canonical secret-free evidence only. Existing Jules
  terminal receipt semantics remain unchanged; a canonical owner receipt,
  authority and provider readback are still required before publication.

No runtime owner event/provider observation was created. No live
provider/model/Jules/Claude execution occurred. Issue #33 was not modified.

## Exact-head verification

- Exact tested code head:
  `c11a1b8be39f2f1435bc53e8480767ac0c53075c`
- GitHub Actions run:
  `36362855956` — **SUCCESS**
- Focused Status/owner/writer/transition/publisher/scope tests:
  **125/125 PASS**
- Full command-bus suite:
  **412 tests run**
- Exactly one known pre-existing error remained:
  `automation.command_bus.tests.test_jules_api_request.JulesApiRequestTests.test_prompt_binds_head_tree_and_allowlist`
- CI explicitly rejects any additional/unexpected failure.
- JSON schema parse: **PASS**, including
  `runtime_transition_evidence.schema.json`.
- Python compileall: **PASS**.
- `git diff --check`: **PASS**.
- PR #59 was OPEN / mergeable=true at exact-head readback.

Any commit after this tested code head must be documentation-only and must be
compared/read back before Merge.

## Remaining live blockers

1. Production durable owner authority.
2. Independent provider verifier.
3. Canonical owner receipt adapter for Jules/other runtime providers.
4. Live Status workflow dispatch/readback adapter.
5. Explicit live authorization before real SEMI_AUTO/AUTO ownership or takeover.

AUTO takeover remains disabled.
