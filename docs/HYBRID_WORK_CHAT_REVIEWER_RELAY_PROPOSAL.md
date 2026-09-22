# Hybrid Work / Chat Reviewer Relay Proposal

Updated: 2026-09-23
Repository: kamiyusense/multi-ai-council-phase0
Status: P1 STATIC IMPLEMENTED / WORK VALIDATION PENDING
Live browser-to-Chat POC: NOT STARTED

## 0. Decision

Do not make Work the sole long-form reviewer by default.

Use:
- Work / Luna-class role: event receiver, deterministic controller, GitHub readback/write, exact tree reconstruction, test execution, schema validation, receipt/state persistence.
- Chat / Sol-class role: semantic review, architecture decisions, diff/evidence inspection, root-cause analysis, and generation of the next bounded command.
- GitHub: durable source of truth and mailbox between the two.

Correctness must never depend on a specific Chat ID, Work session, browser tab, or Jules task.

## 1. Why hybrid

The Phase 0 workload has two different cost/skill profiles.

Mechanical work:
- read PR heads/trees
- reconstruct blobs
- run unittest/compileall/diff checks
- validate JSON/schema/correlation
- write receipts/state
- fast-forward write/readback

Reasoning-heavy work:
- inspect regressions
- decide whether a diff weakens safety
- design the next bounded implementation batch
- resolve architecture tradeoffs
- write precise implementation instructions

The first category is appropriate for Work/Luna. The second benefits from Chat/Sol. Keeping both in Work wastes the scarce Work budget and makes long-running Work sessions heavier.

## 2. Durable GitHub protocol

Suggested paths:

automation/command_bus/review_requests/<loop>/<id>.json
automation/command_bus/review_claims/<loop>/<id>.json
automation/command_bus/review_responses/<loop>/<id>.json
automation/command_bus/review_receipts/<loop>/<id>.json
automation/command_bus/reviewer_state/<loop>.json

Required request identity:
- schema_version
- request_id
- loop_id
- round
- correlation_id
- expected_target_head
- expected_target_tree when mutation-related
- reviewer_role
- review_kind
- evidence_refs
- allowed_decisions
- expires_at
- retry=0
- fallback=disabled

Required response identity:
- response_id
- request_id
- loop_id
- round
- correlation_id
- expected_target_head
- reviewer_role
- decision
- rationale_summary
- evidence_refs
- next_command_proposal or null
- model_route_evidence when available
- submitted_at

Malformed/missing/mismatched records => UNKNOWN. Never infer a response from free-form browser text.

## 3. Transport independence

The transport used to wake Chat is not a correctness input.

Supported future transports may include:

A. Browser Reviewer Relay
GitHub review_request
-> Work event
-> Work Cloud Browser opens/creates Sol reviewer Chat
-> Work submits a bounded instruction that tells Chat to read the GitHub request and write a structured review_response back to GitHub
-> Work does not parse the Chat answer from the UI
-> Work waits only for the GitHub review_response

B. Direct Work-to-Chat fast path
If a supported direct thread/message route becomes reliable:
GitHub review_request
-> Work
-> direct Chat delivery
-> Chat writes GitHub review_response
-> Work validates the GitHub response

C. Human-opened replacement Chat
If automated wake is unavailable:
human opens any suitable Chat
-> one short instruction: recover pending review from GitHub
-> Chat writes review_response
-> Work continues from GitHub

All three routes produce the same durable response schema.

## 4. Chat replacement policy

A Chat is disposable.

If a Chat becomes slow, reaches context limits, or is unavailable:
- do not migrate the full transcript;
- open/use a fresh Chat;
- point it to current GitHub handover + exact pending review_request;
- require exact loop/round/correlation/target-head matching;
- old Chat identity becomes irrelevant.

This is intentionally stronger than transcript-seeding systems because GitHub, not conversation history, is canonical.

## 5. Work replacement policy

A Work session/run is also disposable.

The persistent event-trigger task may start fresh runs. Each run must recover only from:
- current PR #6 head
- current PR #4 head/tree
- command/request/state/receipt/evidence
- current handover/checkpoint docs

No previous Work conversation is required.

## 6. Browser Reviewer Relay safety

Before any live POC:
- no API key
- no paid API route
- no permission/billing/settings changes
- one review request only
- retry=0
- no automatic resend
- response must be written to GitHub
- browser UI success is not proof
- missing GitHub response => UNKNOWN
- do not scrape or trust free-form Chat output as the durable result
- exact request/correlation/head matching required
- no PR Merge
- no main write

The first live browser-to-Chat POC remains an explicit live-model action and is not authorized by this design document alone.

## 7. Current immediate Relay path

Current Relay development should not wait for Browser Reviewer Relay.

Continue the bounded GitHub -> Work path for deterministic implementation batches.

For the current pytest-free transition, the correct repository-root unittest command is:

PYTHONPATH=src python -m unittest discover -s tests -t . -v

The -t . anchor prevents tests/relay from being placed on sys.path as the top-level relay package and avoids shadowing src/relay.

After the deterministic Relay static batch completes, Chat/Sol should perform semantic review of:
- exact PR #4 diff
- safety invariants
- test evidence
- remote readback
- remaining live blockers

Then Chat writes the next bounded command to GitHub.

## 8. Implementation phases

Current P1 implementation checkpoint:
- `DURABLE_REVIEW_V2` request/response contract is implemented on PR #6.
- target head + target tree binding is implemented.
- reviewer role/kind/allowed-decision validation is implemented.
- Browser/Direct/Manual transport-neutral mock wake layer is implemented.
- free-form browser output is not a correctness input.
- live-capable reviewer transports are blocked by the static P1 coordinator.
- durable wake reservation is append-only and keyed by review request identity,
  so fresh Work sessions cannot replay an ambiguous Browser/Direct wake.
- static command-bus validation is bounded to code/tests/schema/README; the
  append-only operational ledger is validated through its durable record
  protocol rather than re-materialized in full on every run.
- regression fixtures are added.
- deterministic Work validation is pending; see
  `docs/HYBRID_WORK_CHAT_REVIEWER_P1_CHECKPOINT.md`.
- no live Browser/Chat POC has been run.

P0 — now
- Keep GitHub -> Work deterministic execution path.
- Add/keep durable review request/response schemas independent of Chat identity.
- Fix pytest-free unittest discovery at repo root.
- Complete Relay static batch.
- Chat/Sol reviews the resulting PR #4 evidence and writes next command.

P1 — static implementation
- Add Browser Reviewer Relay request/response contract.
- Add validators, duplicate/replay guards, expiry, stale-target rejection.
- Add fixture tests with a fake browser/reviewer adapter.
- No live Chat browser execution.

P2 — explicit POC
- One harmless review_request.
- Work Cloud Browser opens one Sol Chat.
- Sol reads GitHub request and writes one structured response.
- Work verifies GitHub response.
- No second send if response missing.
- Record evidence and limitations.

P3 — production routing
- Browser route as optional transport.
- Direct Chat route as optional fast path when reliable.
- Manual fresh-Chat route as recovery fallback.
- GitHub remains canonical.

## 9. Non-goals

Do not:
- make a specific Chat thread a permanent controller;
- make Work parse free-form Chat UI text for correctness;
- keep unlimited bot-to-bot loops;
- retry failed Chat sends blindly;
- require browser transport for deterministic Work-only commands;
- block independent safe Work while a semantic review is pending.

## 10. Recommended operating model

GitHub event
-> Work/Luna deterministic processing
-> if deterministic: continue automatically
-> if semantic review needed: write review_request
-> Sol Chat reviewer
-> write structured review_response to GitHub
-> Work/Luna validates response
-> execute next bounded command
-> evidence/receipt/readback
-> repeat

Human is needed only for explicit approval boundaries or when all safe routes are exhausted.
