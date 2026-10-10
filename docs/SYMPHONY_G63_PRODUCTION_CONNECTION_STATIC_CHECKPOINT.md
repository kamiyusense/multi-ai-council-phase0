# G6.3 Production Connection Final STATIC checkpoint

Workbench: Draft PR #343, `claude/symphony-g61-production-wiring-static`, stacked
on #320. Fresh starting HEAD `db578364c3bb22d5ed1af382085645cfb952f36e`;
PR320 `8c53c505a21318c6133da0bef85af18ae3711103`; fresh main
`4bb5cd72ee0d9912376b0bb3b989cbb028806392` (advanced since G6.2).
Historical G6.2 checkpoint remains evidence of its own interval, not current main.
Final HEAD, exact CI and remote bytes belong to the final read-back PR checkpoint.

## Implementation and authority

- `symphony_g63_sender.py`: a separate restricted MOCK sender contract around
  the unchanged G6 bridge. Independent explicit envelope binds repo/node/branch,
  campaign/task/attempt/generation/runner/worker, old HEAD, candidate, scope,
  result/source and sealed OFF plan. UTC-aware expiry, immutable approval ID
  lock, durable intent/target lock/fence, local SHA checks, fresh target/task
  inspection and exactly one mock CAS. An existing fence makes a restarted
  sender GET-only. Expired authorization still permits receipt readback; it
  cannot permit another send. Approved identity cannot be rebound. Successful
  receipt replay writes nothing; uncertain replies recover through GET only.
  **No HTTP sender or LIVE capability exists. `execute` always refuses.**
- `symphony_g63_verifier.py`: independent workflow ID/content SHA, exact
  run/attempt/job/head and successful individual steps. Reject duplicate IDs,
  malformed/skipped/failed/duplicate steps, worker verifier ID, extra JSON keys,
  duplicate JSON/checks, booleans masquerading as IDs and rebound attestations.
  The existing G6.2 binding/record checks remain in force. Trusted pins must come
  from the operator, never the worker; self-hashes supply integrity only.
- `symphony_g63_archive.py`: fixed official API artifact metadata GET; ID,
  expiry/size/archive digest; explicit limited redirects without credentials;
  HTTPS/signed-host allowlist/userinfo/port/fragment checks; bounded bytes and
  complete response. ZIP inspection checks **all** members, aliases, duplicates,
  paths, symlinks/special/encrypted entries, decompression ratios/count/size,
  CRC/truncation and strict JSON. No extraction, provider or write route.
- `symphony_g63_snapshot.py`: a strict close/source policy over the unchanged
  create-only G6.2 store. Symlink target text can remain forensic evidence, but
  no target is followed/copied and any link makes source incomplete and refuses
  Issue close/result generation. Existing junction/reparse/special/nested-Git
  anomalies, descriptor anchoring, two reads, fsync/readback and identity checks
  are reused. Historical bytes/format and Official cleanup are untouched.

Approval hashes are not signatures or human authorization. This batch's mock
approval objects are fixtures. No configuration/flag can provide a real sender.
A race after task/default GET and before a future server write cannot be solved
by a local check alone: fresh server CAS protects the HEAD, while default/task
identity needs an explicit proof freeze or a hold if it cannot be established.

## Qualification

The **new production GET adapter** fetched official existing artifact
`11659300894` from Symphony run `38023687825`. Archive SHA-256
`729f9c51bd4ede50ef4905a5614924b582c286fec9b07a784eaeb17b326f5fb5`;
60,353 bytes; all four members checked. One validated redirect; forwarded
credentials 0; GitHub writes 0. This is archive acquisition qualification,
**not an actual worker candidate attestation**.

Read-only REST rulesets and branch protection both still return HTTP 403.
GraphQL freshly confirms repository/node, default/main, viewer permission and
RefUpdate fields. Viewer ADMIN is not an exercised write or readable rule.
Actual target constraints, error shape on CAS mismatch and deterministic
Git Database write behavior remain UNKNOWN; no mutation was sent.

The separate `symphony-g63-synthetic-verifier.yml` runs STATIC synthetic tests
only, with read-only permissions and pinned checkout/image/scanner digests.
Test code runs as UID 65534 in a no-network, read-only, capability-dropped
container; no credential environment or host Docker socket is mounted.
Runtime checks inspect mounts, interfaces, UID and selector absence. The full
Gitleaks default rules run against clean and deliberately false-secret synthetic
fixtures in another no-network container, with trusted config and ignore rules
unavailable. Only a SYNTHETIC qualification report is published, never an
attestation granting real adoption. GitHub CI green and real candidate authority
remain separate. Local Docker is NOT_RUN: existing WSL integration unavailable;
no settings were changed. GitHub exact-head CI qualifies the isolation instead.

## Tests and protected history

G6.3 suite 33; optional G7 suite 3. Existing 18 K/L recovery cases preserved;
10 new M sender cases give 28 observed matrix cases. Additional unit/subtest
negatives cover approval/branch/candidate/SHA tampering, archive credential
leak/traversal/bombs, verifier spoof/rebound, source links/races/tampering,
unknown durability/isolation and expired read-only recovery.
Focused/full test counts and actual logs are in the evidence checkpoint.
An UNKNOWN fence deliberately remains UNKNOWN when GET cannot prove publication.
There is no automatic re-arm or blind resend.

Old manifests bind old implementation. The G6.3 validator reads ONLY the explicitly
superseded controller workflow at immutable G6.2 commit `db578364...`; every
historical evidence file and other previously indexed source remains checked in
place. G6.3 source/workflow bytes have their own SHA manifest. No old manifest,
ledger, receipt, proof artifact or fail result is rewritten.

Official pin `be10a1b79df723d6d7612b5651c8522704dafb2e` and observation patch SHA
`404b4001d279351c8b800816142862ee47dfd209615b0f9211fbe6ccc5170f3b` unchanged;
pinned patch check PASS. Polling/scheduling/selection/workspaces/multi-turn/
continuation/retry/backoff/stall/concurrency/cleanup changes **NO**.
PR320/PR344 and real observer ledger are excluded from development writes.

**New model/provider LIVE 0, real worker 0, result adoption 0, updateRefs 0,
Git Database write trial 0, paid fallback 0.** Development commit/FF push to
PR343 and checkpoint publication are separately authorized, not runtime writes.

## Recovery and known limits

Restore immutable source/attempt/intent/lock/fence/receipt first. Verify every
binding and SHA. A receipt yields NOOP; a fence permits GET only, candidate HEAD
and all objects permit receipt completion, old/unknown HEAD stays recoverable
UNKNOWN. Isolate that result and continue independent safe work. Never consume
an approval ID for another identity or turn G5 terminal UNKNOWN directly into
DONE. Before fence, a valid unexpired mock envelope may resume the existing
bridge; no real publication is wired here.

[Readiness and minimal next proof](SYMPHONY_G63_LOCAL_LIVE_READINESS.md).
[Optional G7 reuse checkpoint](SYMPHONY_G7_STATIC_CHECKPOINT.md).
STATIC PASS is not LIVE PASS or authorization.

Sources: [official CAS contract](https://docs.github.com/en/graphql/reference/git#updaterefs),
[artifact GET](https://docs.github.com/en/rest/actions/artifacts#download-an-artifact),
[untrusted Actions isolation](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target),
[pinned Gitleaks package](https://github.com/gitleaks/gitleaks/pkgs/container/gitleaks).
