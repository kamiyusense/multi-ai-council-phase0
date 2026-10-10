# 💙 Official Symphony / New Chinponey — Pre-LIVE real-candidate verifier + narrow sender STATIC integration
<!-- correlation: sym-prelive-verifier-sender-static-20261010-v1 -->

**STATUS: REQUESTED / NOT EXECUTED.** This is the next safe STATIC integration batch after Local Docker isolation PASS. It does **not** authorize any new model/provider/worker LIVE, real Git Database POST, real GraphQL updateRefs mutation, real result adoption, new proof Issue/ref, PR merge, default-branch write, billing/permissions/settings/Secrets changes, or paid API fallback.

## Fresh baseline (re-read before work)
Repository: `kamiyusense/multi-ai-council-phase0`.
Authorized development workbench: Draft PR **#343**, branch `claude/symphony-g61-production-wiring-static`.
Observed current head: `07735ea07af0b6e0ce01917032ac60f48e2b65d3`.
Parent PR #320 observed head `8c53c505a21318c6133da0bef85af18ae3711103`.
Sibling #344 observed head `81bbf1ba42077d36f4942f229ac327a7d30c9892`.
Main observed head `abb5402079d4af341c349ea9e8b6a8a5c3f2d37c`.
All SHA values are observations, not future truth: fresh-read repo/PR/heads/comments/worktree/CI and discover any newer Symphony successor before editing. Do not repeat already completed work.

Latest checkpoint: PR #343 comment **6098009564**.
Confirmed state:
- Local Docker daemon PASS and actual Local isolation PASS using exact pinned Python/Gitleaks images.
- Five Local synthetic isolation cases PASS; exact images retained; no additional Docker settings/image acquisition human step remains.
- Exact-head CI success at `07735ea...`: Symphony **38055667387**, Blue **38055668050**, independent synthetic verifier **38055667483**.
- Full suite 2170 (skip1); synthetic verifier 116.
- Production code behavior changes in the Docker batch: 0.
- Current real-candidate state **NOT_QUALIFIED**; real sender **NOT_WIRED**; one-run human LIVE approval **NONE**.
- Existing read-only production ledger/recovery/receipt/object/provenance seams are STATIC PASS.
- Historical G4/G5/G5.1 proofs, main, #320/#344, historical ledgers/evidence must remain immutable.

Read first:
`docs/AUTONOMOUS_DEVELOPMENT_LOOP_NORTH_STAR.md`,
`docs/SYMPHONY_DOCKER_PRODUCTION_WIRING_READINESS.md`,
`docs/SYMPHONY_LOCAL_DOCKER_ISOLATION_RESULT.md`,
`automation/command_bus/symphony_operator_readiness.py`,
`automation/command_bus/symphony_verifier_provenance.py`,
current G6/G6.3 adoption/verifier/sender code and G7.1/G7.2/G7.3 host/campaign/receipt code.
Do not duplicate Official Symphony scheduler/poller/worker lifecycle or existing fault matrices.

## Mission A — make the future REAL candidate verifier production-shaped, still OFF
Close only meaningful code/interface gaps for a future **actual worker candidate**, without dispatching one now.

1. Define/review one operator-owned candidate acquisition interface that can accept an immutable candidate commit from an already completed worker lifetime and independently reconstruct/check exact parent/tree/blob/commit bytes using the existing read-only Git object reader. Worker output must not choose verifier workflow, tests, scanner config/images, run/job IDs or trust root.
2. Add or harden a production-shaped **operator attestation exporter/parser contract** that binds:
   - repository/node and exact nondefault target,
   - worker/campaign/task/attempt/generation/lifetime identities,
   - expected target head/tree,
   - source/result/scope digests,
   - candidate commit/tree/all blobs,
   - pre-close snapshot manifest,
   - exact verifier workflow source commit + workflow byte SHA,
   - run id / attempt / job id / exact required successful steps,
   - pinned test/scanner/image digests,
   - full artifact ZIP digest and strict attestation digest,
   - expiry and replay/correlation identity.
   Reuse `PinnedSourceCIVerifier` / G6.3 archive reader rather than building another verifier.
3. The **real** attestation format must be structurally distinct from the existing synthetic protocol or explicitly require `synthetic:false`, and synthetic archives must remain impossible to cast/rename into VerificationEvidence.
4. Future verifier candidate code execution remains Local/container or trusted CI only under the now-proven isolation policy: nonroot, no network, readonly source/candidate/root, no socket/credentials, pinned operator test/scanner. Do not run an actual worker candidate in this batch.
5. Add negative tests for candidate parent/tree/blob mismatch, untrusted/changed workflow, wrong run head, skipped/failed required step, wrong worker lifetime/scope/result/source/snapshot, replayed artifact, synthetic protocol, expired pins, and candidate-provided tests/config. Avoid duplicate tests that already exist; extend only when a real interface gap is closed.

Outcome must remain **REAL_CANDIDATE_NOT_QUALIFIED** until a separately approved real worker produces a candidate and the independent verifier actually checks it.

## Mission B — narrow real sender acquisition interface, credential-free and OFF
The existing G6/G6.3 prepare/restricted sender semantics are already tested. Do not add a general-purpose GitHub mutation client.

1. Implement/review the minimum **operator-owned capability envelope and verifier** needed for a future sender acquisition step. The envelope must be externally issued, issuer-verifiable and bind at least:
   - repository/node,
   - exact fixed nondefault ref,
   - expected beforeOid/afterOid,
   - exact plan/object/result/source/scope/worker/campaign/task/attempt/generation identities,
   - allowed create-only ledger namespaces,
   - exact Git Database object operations,
   - exactly one `updateRefs(beforeOid, afterOid, force:false)`,
   - expiry, nonce/correlation, max_ref_updates=1,
   - no Issue/Merge/default branch/generic GraphQL/contents mutations.
2. Self-hash, worker-supplied JSON, config flag, PR comment text, viewer ADMIN, development push capability, or synthetic fixture must **not** become authority. No secret/key material is generated or stored in candidate/model workspace.
3. If a signature/MAC verification interface is needed, implement only verifier/parser/injected fake signer for tests. Do not create or display a real signing key, API key, PAT, token, Secrets setting or runtime credential.
4. Compose the envelope verifier with existing durable intent/target lock/ref intent/fence and GET-only uncertain-response recovery in an OFF integration harness. Prove: stale target/head/task/default/ref, mismatched plan/object/afterOid, expired/duplicate envelope, wrong issuer, response lost before/after fence, replay after later ref advance. No real remote POST/mutation.
5. Sender acquisition must remain impossible without three separately supplied reviewed inputs: valid real candidate verification, valid direct operator authorization envelope, operator-only real write capability/credential. Current batch may prepare interfaces only; **REAL_SENDER_NOT_WIRED** remains honest if actual transport/capability is absent.

## Mission C — exact pre-LIVE technical gate packet
After A/B, produce a concise binary gate table, not another giant mock campaign:
- Local Docker isolation: PASS.
- Production read-only ledger/recovery: PASS.
- Real candidate verifier code/interface: PASS/FAIL/UNKNOWN, but actual real candidate qualification remains NOT_QUALIFIED unless a real candidate exists (it should not in this batch).
- Sender capability interface: PASS/FAIL/UNKNOWN; actual real write capability remains NOT_WIRED unless separately authorized (it is not in this batch).
- Subscription child route: requires fresh selector-only preflight immediately before future worker; no secrets/API keys/values.
- Future exact proof ref protection/ownership/default/head: fresh readback at future proof boundary.
- Human one-run approval: NONE.
- LIVE GO only if all true runtime gates plus explicit separate approval are satisfied.

If, after review, all remaining gaps inherently require a real candidate, real credential, new proof identity or live model, **STOP_NO_MORE_MEANINGFUL_STATIC**. Do not invent G7.x safety layers just to continue.

## Safe execution / GitHub persistence
Within existing authorized #343 scope: fresh remote HEAD and worktree check → meaningful code/docs/tests only → focused/full/regression/negative tests → fixes/retest → evidence/hashes → ordinary commit + FF push → remote commit/tree/blob readback → exact-head Symphony/Blue/independent CI → safe repair/reverify if needed.
If no meaningful code change is warranted, no-op commit is forbidden; append-only assessment/checkpoint is enough.
Ambiguous external write: read back before any retry. No blind retry. Preserve old evidence.
Do not modify main, #320, #344, historical ledger/proof refs.

## Prohibited
No PR Merge, default branch write, force push/rebase/destructive clean/reset, new live worker/provider/model, real candidate publication/adoption, real Git Database POST/GraphQL updateRefs, new proof Issue/ref, permission/settings/Secrets/Billing/API key changes, paid API/provider fallback, review/approval bypass.

## Final report
One Japanese consolidated report with exact final HEAD, changed paths, tests/CI/artifact hashes/readback, what material integration gap was closed, what remains technically impossible without LIVE/real authority, and the exact next human approval if and only if needed.

**🟢 Codex推奨モデル：Sol 6.1 High.** This batch contains authority/trust-boundary design and integration, not routine regression work. Use Luna High only for deterministic regression/evidence substeps if model switching is available without disrupting the same reviewed development context.
