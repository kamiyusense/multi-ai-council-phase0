# ChatGPT Semi-Auto stable identity: STATIC E2E checkpoint

This checkpoint is based on main `6617bfa4dd64b2dca69fb3593d8f6295f401f6fe`.
It does not adopt a production loop ID or authorize live runtime publication.

## Static composition

`semiauto_stable_identity.prepare_adopted_semiauto_acquire` validates an
explicit ChatGPT/Semi-Auto/Jules lane against an independently supplied
registry snapshot before calling the existing prepare-only ACQUIRE function.
It does not derive the lane ID from the human Loop number, origin loop,
command, correlation, PR, branch, session, or thread. The same fixture lane ID
can be reused across request turns. The current repository registry remains
`PLACEHOLDER`, so this adapter rejects it; only a hypothetical `DURABLE`
registry fixture can pass the positive static test.

The offline E2E composes existing components: V2 origin-correlation binding,
Jules acceptance, PREPARED initializer, generation-1 ACQUIRE preparation,
receipt/evidence, later Session GET candidate, source normalization,
independent direct-readback authenticator, source-bound provider verifier,
RuntimeTransitionPublisher, durable collector, accepted projection, and
registration readiness. The source normalizer emits `UNKNOWN`; the test alone
supplies a simulated `VERIFIED` source and independent fake readers. The owner
authority is likewise a test-only fixture. No production verification or
authority is issued by this change.

Candidate proof references now include the exact PR and head already checked
by the direct authenticator. For later Session GETs, the authenticator binds
`updateTime` to the source observation time, and can additionally bind the
session `createTime` to the original acceptance/owner-claim time. Older
acceptance-time sources without `updateTime` keep their existing check.
The positive fixture uses explicit raw `RUNNING`; whether live Jules GETs
produce that exact state remains unproven here. No live provider call occurs.

## Fail-closed evidence

Tests reject a placeholder registry, wrong lane/origin/correlation, target
PR/head drift, session identity drift, provider state drift, expired lease,
future/stale observation, missing receipt/evidence/owner/observation, missing
independent authenticator, and caller-supplied source text alone. Source
receipt retry remains `0` and fallback remains disabled. Existing owner-chain,
generation/fencing, malformed record, and duplicate/replay regression tests
remain in the full command-bus suite.

## Deferred decisions / production gates

- `FINAL_LOOP_ID = UNKNOWN`; `CONTROL-TOWER-REAL-LOOP-IDS-001 = UNKNOWN`.
- The real Control Tower registry stays `identity_state=PLACEHOLDER`.
- A separately authorized stable-lane identity source, real owner-authority
  grant/verification, exact live provider vocabulary/readback proof, and
  authorized runtime data branch are still required before production use.
- This branch does not mutate Issue #33, promote the registry, start Jules,
  request OIDC tokens, publish runtime status, or perform a live takeover.

---

# Connector writeback reproduction fixture

This disposable branch intentionally adds this documentation path from the pre-PR-121 main commit so the test pull request conflicts with current main. It must not be merged.
