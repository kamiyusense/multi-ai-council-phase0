# Runtime takeover static E2E v1 — checkpoint

## Dependency

This is a stacked static test layer on top of:

- PR #71 takeover preflight — merged
- PR #74 takeover request preparation — open dependency

The stacked PR should remain based on
`feature/runtime-takeover-prepare-v1` until PR #74 is merged.

## Purpose

Prove the complete takeover code path with deterministic fakes/mocks only:

`preflight_takeover`
→ `prepare_takeover_transition`
→ source-bound AuthorityGrantVerifier
→ source-bound ProviderVerifier
→ `RuntimeTransitionPublisher`
→ Status prepare-only boundary

## Mock-only guarantees

The E2E test uses:

- in-memory fake GitHub contents client;
- fake target reader;
- fake Status prepare boundary;
- deterministic source readers;
- deterministic source authenticators;
- no network;
- no live provider;
- no live GitHub workflow dispatch;
- no real runtime ledger;
- no Issue #33 mutation.

## Positive path

The test begins with generation 1 SEMI_AUTO owner state and prepares an expired
owner HANDOFF to generation 2 AUTO.

The full mock pipeline verifies:

- current generation 1 chain/state/receipt/provider history;
- generation 2 HANDOFF/fencing;
- canonical takeover evidence;
- explicit authority grant;
- independently authenticated authority source;
- independently authenticated provider source;
- desired state binding;
- publisher evidence write;
- provider-observation write;
- owner generation append;
- state CAS;
- final deterministic validation;
- Status prepare plan with AUTO / generation 2.

## Negative paths

The static E2E also requires fail-closed behavior for:

- missing authority authenticator;
- missing provider authenticator;
- stale/moved target head.

All negative paths must stop before durable mutation in the fake client.

## Explicitly not performed

- no production source reader/authenticator;
- no authority issuer;
- no runtime GitHub mutation;
- no workflow_dispatch;
- no Issue #33 mutation;
- no real provider/model execution;
- no real takeover;
- no default-branch write;
- no Merge.

## Exact-head verification

- Exact tested code head:
  `81233217ced60df0de138074307d17556033d0f4`.
- GitHub Actions run:
  `36373340889` — **SUCCESS**.
- Focused Status/runtime/validation suite:
  **186/186 PASS**.
- Full command-bus suite:
  **473/473 PASS**.
- Command-bus JSON schemas parsed:
  **18/18 PASS**.
- Python compileall:
  **PASS**.
- `git diff --check`:
  **PASS**.
- PR #75 was OPEN / mergeable=true at exact-head readback.
- Any commit after this exact tested head must be documentation-only and compared
  before Merge.

## Deferred Decision

`decision_id: RUNTIME-VERIFIER-SOURCE-001`

**内容:** productionで使う Authority / Provider verification source と、その
独立Authenticatorの実体を決める。

**判断が必要な理由:** static codeは source reader / authenticatorを注入する
fail-closed契約まで完成したが、どの外部事実をproduction trust sourceとするかは
repository内の自己申告だけから決定できない。

**選択肢:** production controller / provider API・session readback /
GitHub Actions等の外部実行証拠 / human-approved authority sourceのうち、
独立性・readback・expiry・identity bindingを証明できるものを採用する。
現時点ではどれを正式採用するかは **UNKNOWN**。

**安全なdefault:** verifier source未選定のままなら `NOT_WIRED` を維持し、
real SEMI_AUTO/AUTO takeoverを開始しない。

**影響範囲:** authority grant issuer、ProviderVerifier、
SourceBoundAuthorityGrantVerifier / SourceBoundProviderVerifierのproduction
adapter、real takeover、live Status更新。

## Control Tower v2 compatibility

This static E2E proves the durable takeover/control-plane chain only. It is not
a Control Tower renderer test and it must not become one.

The Multi-loop Control Tower must aggregate already verified per-loop
projections. Presentation metadata and aggregate counts must never replace the
state/owner/receipt/evidence/provider/target/authority/fencing path exercised
here.

CT-1 remains separately bounded to static registry/model/rendering/snapshot
work. No live Issue #33 migration is authorized by this E2E.
