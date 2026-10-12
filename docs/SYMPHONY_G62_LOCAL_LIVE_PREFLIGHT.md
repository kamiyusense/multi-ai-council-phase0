# G6.2 Local LIVE preflight — prepare-only, no launch authority

Current batch: LIVE 0 / actual Git result adoption 0. No proof Issue, workspace,
branch, campaign, provider or model is created by this plan. Old one-shot
approvals are consumed and cannot authorize a new run. G4 #336, G5 #341 and
G5.1 #342, their artifacts and ledgers must never be reused/adopted.

## Remaining technical gates before requesting LIVE approval

1. Review a restricted write sender for exactly the prepared non-default target,
   repository identity, non-zero expected old/candidate HEAD, force=false and
   one updateRefs request. The current adapter has no sender; mode/flag changes
   cannot enable it. Object SHA mismatch must prevent any ref call. A default
   branch change between last GET and server mutation is still an external race;
   freeze/control that identity inside the approved proof envelope or hold.
2. Independently pin the actual verifier workflow and qualify its candidate
   checkout, syntax/tests/full secret scanner and digest-bound attestation.json.
   Qualify archive GET without forwarding GitHub credentials to signed redirects.
   Successful ordinary development CI is not itself a real candidate attestation.
3. Fresh-read repository/default/PR320/343 exact heads, applicable rulesets,
   target write constraints and exact-head Symphony/Blue CI. Previously unreadable
   rulesets remain UNKNOWN. Do not treat expected repo permissions as exercised.
4. Confirm Ubuntu secure snapshot primitives, storage outside worker workspace,
   restrictive access and successful disk fsync/readback. Windows no-follow
   support is not assumed: unsupported primitives hold the close gate.
5. Check current subscription login and child route selector presence by name
   only. No OPENAI_API_KEY/CODEX_API_KEY/AZURE_OPENAI_API_KEY/custom base/paid
   fallback; no key values or observer MAC in evidence. Missing quota telemetry
   alone is not exhaustion. No Billing/Credits/Overages/Secrets/permissions change.

## Fresh one-run envelope after separate explicit authorization

- Record new Issue/campaign/task/generation/attempt/worker/workspace identities,
  source starting HEAD, exact allowed artifact path and independent request/scope
  digest. Use separate non-default proof/result target and append-only observer/
  adoption ledgers. Main, PR320/343/344 and old proof refs are excluded targets.
- Fresh readback/preflight -> create one new Issue/readback -> proof refs/empty
  workspace -> observer binding/config/key/event file outside worker -> observer
  ready -> sole Official Symphony launch. Worker cannot commit/push/close/adopt.
- Official Symphony naturally schedules and works. Preserve its multi-turn,
  continuation, retry/backoff/stall recovery/concurrency and workspace cleanup.
  The one-run limit belongs to this proof authorization, not the product campaign.
- Observe real signed STARTED/durable STARTED. Independently inspect the approved
  artifact, unchanged worker HEAD, full diff/check and unauthorized mutation 0.
  Capture/read back full bytes outside workspace **before tracker close**; only
  a verified, complete, anomaly-free snapshot releases the close gate.
- Separately authorized tracker close -> natural Orchestrator lifetime TERMINAL
  -> durable UNKNOWN/RECOVERABLE_UNKNOWN. Do not reinterpret worker stop as task
  success. Explicit current adoption relevance after close is independently read.
- Snapshot -> bound RESULT -> fresh canonical target/task -> actual independent
  verifier/attestation -> sealed OFF preparation -> reviewed authorized sender.
  Persist create-only intent/target lock; create/read deterministic Git objects;
  repeat fresh inspection; persist fence; one qualified updateRefs call; GET ref,
  parent/tree/blobs; create/read durable receipt. Only receipt permits task DONE.
- Ambiguous response/fence/crash: GET-only recovery, no blind resend. Old/unknown
  target stays recoverable UNKNOWN and isolates this result; safe independent
  work remains eligible. No second model proof launch or metered fallback.
- Observer/controller-only restart with model stopped -> signed event duplicates
  NOOP; verified result/receipt replay NOOP; new model dispatch 0; extra ref/object
  writes 0. Never restart Official Symphony as a second LIVE proof.
- Read processes/ports stopped, Issue/ref/ledger/HEAD/full bytes, protected refs,
  mutation/adoption counts and hashes; preserve evidence with no destructive
  cleanup. Save through approved normal commit/FF push and exact-head CI.

PASS requires the real lifecycle, snapshot, independent verifier, qualified CAS,
verified receipt and restart evidence with zero unauthorized/default/paid/model
replay. Real write/rules/CI qualification remains UNKNOWN until exercised under
new explicit approval. This document grants no action or provider permission.
