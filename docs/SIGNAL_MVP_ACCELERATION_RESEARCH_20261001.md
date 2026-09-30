# Signal MVP acceleration research — 2026-10-01

Status: implementation-order checkpoint. This document intentionally reduces
pre-MVP work. It does not grant runtime ownership, provider authority, Merge,
default-branch writes, permission changes, billing changes, or live migration.

## Decision

Do not wait for the full durable-owner/authenticator/attestation stack before
shipping a useful Signal/Control-Tower observation surface.

Split the work into two clearly named layers:

1. **Observed development/session status (MVP first)**
   - GitHub PR/check/run facts.
   - Jules official Session state.
   - Jules Activities / agent message when needed.
   - HUMAN INPUT means the provider explicitly reports a waiting state; it is
     not inferred from silence.
   - This layer is presentation only and must never authorize runtime mutation.

2. **Verified durable runtime ownership (later, before autonomous mutation)**
   - existing state/owner/receipt/evidence contracts;
   - independent provider/authority verification where the dangerous runtime
     transition actually requires it;
   - registry DURABLE promotion and live Issue migration only after real proof.

Existing strict runtime code stays in the repository. It simply stops being a
prerequisite for the read-only/observational MVP.

## Reuse before building

### Jules — use the official API directly

Already available:
- Session states include QUEUED, PLANNING, AWAITING_USER_FEEDBACK,
  IN_PROGRESS, PAUSED, FAILED and COMPLETED.
- AUTO_CREATE_PR creates the normal Jules PR when changes are ready.
- sendMessage continues the same Session.
- Activities exposes agent/user messages, progress and completion/failure.
- root AGENTS.md is read automatically.

Therefore do not build a second Jules scheduler, PR creator, question protocol,
or progress event model.

Sources:
- https://jules.google/docs/api/reference/sessions
- https://jules.google/docs/api/reference/activities/
- https://jules.google/docs/

### GitHub webhook receiver — copy the official primitives

If/when Relay receives GitHub webhooks:
- validate X-Hub-Signature-256 with HMAC-SHA256;
- use constant-time comparison;
- use X-GitHub-Delivery as the idempotency/replay key;
- subscribe only to the events/actions actually required.

Do not invent a second delivery UUID protocol.

Sources:
- https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
- https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks

### Human approval — prefer exact-head GitHub PR Review

For a future bounded human approval source, prefer an existing submitted PR
Review:
- state=APPROVED;
- expected authorized GitHub user/association;
- review commit_id equals the current target PR head;
- if head moved, the old approval is stale for this adapter.

This is an MVP GitHub-account trust boundary, not a claim of cryptographic
attestation. Do not create a new approval service before this has been tried.

Source:
- https://docs.github.com/en/rest/pulls/reviews

### AGENTS.md — short map, not a giant manual

Add a short root AGENTS.md before continuing many more Jules loops. Keep only
stable repository rules and pointers to canonical docs. Per-task prompts should
then contain only current objective, exact snapshot, allowed paths, validations
and true stop boundaries.

Do not copy the current long task contract into AGENTS.md.

Sources:
- https://jules.google/docs/
- https://openai.com/index/harness-engineering/

## OSS parts worth stealing later

### Agetor (MIT)

Useful pattern only for current project:
- structured blocked/question state;
- one pending interaction is settled once;
- keep the same agent/session alive for follow-up;
- worktree-per-writer idea.

Do not import its desktop/Bun stack just for Signal.

Source:
- https://github.com/alamops/agetor

### VNX Orchestration (MIT)

Useful later only if a local Relay/app-server needs fast mutable coordination:
- PAST = append-only receipts;
- CURRENT = SQLite coordination state.

Phase 0 already has GitHub as durable truth, so do not replace the current
GitHub ledger now.

Source:
- https://github.com/Vinix24/vnx-orchestration

### ryderderder/orchestrator (MIT)

Useful later for local subscription CLI adapters:
- single-file Python / stdlib core;
- exact-session resume;
- busy / needs-input / idle observation;
- custom CLI provider schema;
- documented Antigravity `agy` adapter example.

Do not copy autonomous/permission-bypass flags from provider examples. Reuse
only the provider/session adapter shape if the local Claude/Gemini/Antigravity
lane actually needs it.

Source:
- https://github.com/ryderderder/orchestrator

## Explicitly deferred / not MVP dependencies

Do not make these prerequisites for the observed Signal MVP:
- artifact attestations / Sigstore;
- GitHub OIDC proof plumbing;
- a new workflow engine (Temporal/DBOS/Restate/LangGraph);
- a new database/backend server;
- a second owner/authenticator architecture;
- GitHub Projects automation;
- Windows companion before the GitHub observation contract is useful.

Artifact attestations for private/internal repositories also introduce a plan
constraint on GitHub Free/Pro/Team versus Enterprise Cloud, so they are a poor
MVP dependency.

## Jules question policy

When the current Jules Session enters AWAITING_USER_FEEDBACK:
- controller answers the same Session once when the question is a small,
  reversible contract-alignment/test/docs decision that can be resolved from
  fresh repository facts;
- escalate to the human only for Merge/default write, destructive operations,
  settings/permissions/billing/secrets, new live provider execution/spend, or a
  material scope/architecture choice;
- never start a replacement Session merely because Jules asked a minor question;
- never resend an ambiguous answer.

Loop 090 demonstrated this path successfully: same-session feedback unblocked
Jules and produced PR #189.

## Test policy for the next MVP batches

Stop enumerating every imaginable negative case before first use.

For a bounded MVP batch require:
1. direct happy path;
2. one or two high-probability conflict/recovery cases;
3. existing regression suite;
4. exact-head CI/readback.

Add further negative tests when a real failure, bug, ambiguity or integration
boundary reveals the need.

Dangerous runtime mutation boundaries keep their existing stronger tests.

## Next shortest path

1. Adopt Loop 090 persistence adapter after exact-head CI.
2. Add a short root AGENTS.md / prompt slimming.
3. Generalize the already-existing Development/GitHub-evidence presentation
   enough to show the current Signal/Jules lane.
4. Feed it direct Jules Session state + PR/check facts as **OBSERVED**, not
   durable owner truth.
5. Use same-session sendMessage for minor Jules questions.
6. Only after the visible/read-only MVP works, return to the minimum missing
   trust proof required for actual autonomous runtime mutation.
