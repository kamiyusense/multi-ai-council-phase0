# Chat/Work GitHub command bus

GitHub is the durable control plane. Commands and receipts are append-only; only loop state is mutable.
The processor validates the repository, the target PR, `expected_target_head` (the current head of `expected_pr`), correlation, expiry, STOP, terminal receipts, and the six-round ceiling before processing.
The carrier/implementation PR head is separate metadata and is never compared through `expected_target_head`.
Unknown or ambiguous conditions are blocked without retry or fallback.

Reviewer work is represented by append-only `review_request`, `review_claim`,
and `review_response` records. A reviewer is identified only by its instance,
generation, role, and capability; no Chat or thread ID is part of correctness.
Only one non-expired claim is active, stale generations and duplicate
responses are rejected, and Work consumes a response only after exact
loop/round/correlation/target-head validation. Missing, empty, or unverifiable
responses are `UNKNOWN` and fail closed.
Claims must expire strictly after their claim time and no later than the
request expiry. Request, claim, and response operations reuse the shared
`StateMachine` gate, so STOP, HALTED, EXPIRED, and the six-round ceiling block
progress. Records can be serialized and reconstructed in a fresh session
without a thread binding.

The GitHub-backed adapter maps records to `review_requests/<loop>/<request>.json`,
`review_claims/<loop>/<claim>.json`, `review_responses/<loop>/<response>.json`,
and `review_receipts/<loop>/<receipt>.json`; mutable loop state is stored at
`state/<loop>.json`. It rejects unsafe path components, duplicate append
writes, malformed or missing records, and invalid state readback.

The runtime is intentionally limited to `automation/command_bus/**`; it does not execute Jules, providers, live models, API keys, or GitHub workflows.


Durable-boundary hardening:
- every append/state write requires an independent branch readback; unverifiable
  writes return `UNKNOWN` and are not retried automatically;
- persisted request/response/receipt context is checked against loop, round,
  correlation, and target head, and claims/responses/receipts must reference
  durable predecessors in the same loop;
- the controller's connected GitHub capability is the production transport
  implementing `GitHubContentsClient`; no API key or repository secret is
  embedded in this package. The direct Chat thread remains an optional fast
  path and is not part of correctness.


## Exchangeable executor handoff

Implementation work is represented by durable executor-role records:
`execution_requests/<loop>/<request>.json`,
`execution_claims/<loop>/<claim>.json`,
`execution_results/<loop>/<result>.json`, and
`execution_receipts/<loop>/<receipt>.json`, sharing mutable `state/<loop>.json`.

The protocol is independent of Chat/thread/browser session identity. It supports
fresh-session recovery, generation-based executor replacement, exact
loop/round/correlation/target-head matching, and terminal receipt replay
protection. The current executable policy is intentionally `PREPARE_ONLY`:
`requires_live_model=true` or `execution_mode=LIVE` is rejected. A future
Jules/browser/ACP adapter must be separately authorized before it can perform a
live execution. Carrier PR head is not part of correctness; target PR head is.

Every request declares durable `target_role="executor"`, a provider-neutral
`executor_kind`, capability, objective, input/evidence references, allowed and
prohibited actions, and an explicit user-approval boundary. Request, claim,
result, and receipt records include matching `execution_*_id` aliases. Prepared
results prove that no model, external send, retry, fallback, or live start
occurred. All execution records are append-only; only loop state is mutable.
