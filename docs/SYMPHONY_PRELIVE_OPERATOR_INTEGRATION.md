# Pre-LIVE real candidate verifier and narrow sender — STATIC integration

Work order: PR #343 comment6098391733. Starting source HEAD
`07735ea07af0b6e0ce01917032ac60f48e2b65d3`. The final append-only PR receipt
binds the resulting development commit, full remote blobs and exact-head CI.
This batch runs no actual worker candidate or model, publishes no candidate,
creates no proof identity, and performs no real runtime Git object/ref write.

## Material gaps closed

`OperatorCandidateVerifier` is one operator-owned acquisition entry point around
original ReadOnlyGitObjectReader, snapshot load, fresh target/task inspection,
and PinnedSourceCIVerifier. Its independently configured immutable contract
includes repo/node/nondefault target/ledger, target tree, candidate tree/OID,
pre-close snapshot SHA, operator source commit and workflow/test/config/image
pins, run/attempt/job/required steps, artifact ID/full ZIP SHA, expiry and
correlation. Worker output supplies none of these selectors or trust roots.
The original unsigned single-parent UTC candidate reconstruction limit is
unchanged: an unreconstructible foreign/signed commit is refused, not coerced.

Every candidate commit/tree/blob is reconstructed and rehashed through the
original reader; full candidate inventory must equal the preserved snapshot.
The candidate tree must actually contain the identical pinned workflow bytes.
Trusted tests/scanner config are GET-hashed at the operator source commit,
never selected from the candidate. Original same-candidate run-head, exact
successful same-job steps, whole ZIP, strict legacy attestation and independent
verification checks remain. Original inspector binds scope/request and the
completed Official worker lifetime; STATIC_SIMULATION is refused. Snapshot
and lifetime are rechecked after CI along with fresh target/task validity.

`export_real_attestation` defines the separate
SYMPHONY_OPERATOR_REAL_CANDIDATE_V1 / synthetic:false archive member
operator-attestation.json. It binds all lifetime/source/result/snapshot/pin
identities to the strict original attestation.json digest. Both members must
match the operator contract exactly, with strict JSON and no extra selectors.
Synthetic archives/protocols/renames cannot become VerificationEvidence.
The exporter itself is an integrity formatter, never an authority. Only the
independent pinned-source CI/archive reader can produce the OFF verification
result. The full ZIP digest is detached in the contract/receipt, avoiding an
impossible self-digest embedded inside the ZIP. File, strict canonical
attestation, full ZIP and result receipt digests are distinct.

No actual candidate code is executed by this reader. Future execution is an
operator-owned isolated Local/trusted-CI operation using the now-proven pinned
policy: UID65534, network none, readonly root/source/candidate, no credentials
or sockets, capabilities dropped, no-new-privileges, CPU2/memory256MiB/PIDs64
and tmpfs64MiB noexec/nosuid. The workflow/test/config/image pins describe and
bind that reviewed execution; no worker-provided tests/config become trusted.
A real eligible job and emitted attestation do not exist in this STATIC batch.

`OperatorEnvelopeVerifier` parses a separate externally issued direct-human
schema with an independently injected issuer/key-ID signature verifier. The
signature covers canonical domain-separated bytes, including issuer/key-ID,
nonce/correlation/expiry, all verified candidate bindings, exact plan and object
operation descriptors/body hashes, create-only ledger namespaces and exactly
one fixed nondefault updateRefs(beforeOid,afterOid,force:false). No Issue/Merge,
contents, default ref or generic GraphQL permission can be added. An approval
self-hash, PR text, ADMIN/flag or development push is never a signature.
No signer, real signing key, API key, PAT, token or credential is generated,
read or stored by this interface. The test issuer is a fixed fake byte registry.

`PrepareOnlySenderAcquisition` validates the verification and signed envelope
interfaces but cannot acquire or execute a real sender. The third separate
operator-only real write capability/credential factory is absent. Flags or a
caller-proposed credential cannot change this. `IssuedEnvelopeMockSender`
composes the new issuer check with the original RestrictedMockSender and
original bridge's durable intent/target lock/ref fence/receipt/GET recovery.
Nonce consumption reuses create-only original ledger primitives; conflicting
issued envelopes cannot overwrite. Candidate validation precedes consumption.
Expired authorization/verification permits only already-fenced GET recovery,
never another ref dispatch. Receipt replay after later advancement stays NOOP.
There is no new scheduler, retry engine, ledger database or transport client.

## Verification and immutable evidence

Sixteen added integration tests cover the newly connected boundaries using the
original World/CI/Git simulator fixtures. A test-only recorded LIVE-format
lifetime is explicitly fabricated in memory, not a real signed event or an
edit to historical records; all remote publication in these tests is MOCK.
Positive tests exercise new production code and original inspector/readers.
Negative cases cover parent/tree/blob/commit mismatch, source/candidate
workflow changes, trusted test/scanner pins, wrong lifetime/worker/scope/result/
source/snapshot, skipped/failed step/wrong run head, replayed or expired ZIP,
synthetic protocol/rename/static observation, candidate-supplied selectors,
invalid/absent/wrong issuer signature, object/plan/ref/namespace tampering,
expired/duplicate nonce, stale head/default/task, response loss before/after
fence, and recovery/replay with zero extra mock ref/model dispatch.

Local focused suite: 418 tests PASS. Full command-bus: 2186 tests PASS (skip1).
A fixed cached Gitleaks image also scanned the changed trusted source/docs and
decompressed logs in a dedicated nonroot/no-network/readonly fixture: PASS.
The first scan did not run because its temporary directory was inaccessible
to UID65534; that diagnostic is preserved in Windows, and a newly created
readable trusted-only fixture resolved it without changing existing permissions.
No image was pulled and both stopped scan containers were removed/readback.
Compile/diff/current-source and unchanged historical evidence checks are saved
under docs/evidence/symphony-prelive-static. Exact-head automatic CI includes
these tests in the existing controller and hardened independent container job;
images, isolation, Actions pins and read-only permissions remain unchanged.
Historical G7.3 workflows/validator are authenticated at the last immutable
source HEAD above; old manifests are unchanged. A separate current manifest
and validation step authenticate this batch's source/workflow/evidence bytes.

## Exact technical gate packet

| Gate | Current result |
| --- | --- |
| Local Docker isolation | PASS, prior actual Local proof comment6098009564 |
| Production read-only ledger/recovery | PASS, existing code and integration |
| Real candidate verifier code/interface | STATIC PASS |
| Actual real candidate qualification | NOT_QUALIFIED, no real candidate/job |
| Sender capability envelope interface | STATIC PASS |
| Actual real write capability/sender | NOT_WIRED, no credential/factory |
| Subscription child route | Fresh selector-only check immediately before future worker |
| Future proof ref protection/ownership/default/head | Fresh readback at future boundary |
| Human one-run approval | NONE |
| LIVE GO | NO |

STOP_NO_MORE_MEANINGFUL_STATIC for this authorized interface batch. The next
runtime packet must separately supply a fresh real worker/candidate/snapshot,
operator-approved eligible verifier job/archive, externally issued direct-human
envelope with an independently reviewed real issuer verifier, and separately
reviewed operator-only narrow write capability. Preparation is not authority.
Do not reuse G4/G5/G5.1 identity or infer a new LIVE approval from this document.
Real issuer/root/credential and runtime transport installation are not wired
by a fake test signature or this development push. No new permissions/settings
are inferred as necessary; any proposed changes need separate review.

Official Symphony polling/scheduling/continuation/retry/backoff/stall/concurrency
and workspace/worker lifecycle are unchanged. Its autonomous continuation is
not per-turn gated by these post-lifetime verification interfaces.
