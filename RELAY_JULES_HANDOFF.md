# Relay Implementation Handoff for Jules

Updated: 2026-09-21
Repository: `kamiyusense/multi-ai-council-phase0`
Branch: `feature/relay-transport`
Base/checkpoint commit: `230026f53f412cd52d8e2eac45457236c916b64d`

## 0. Read this first

Before changing code, read the following from the same repository/checkpoint:

1. `HANDOVER_CURRENT.md`
2. `docs/ARCHITECTURE.md`
3. `docs/PHASE0_IMPLEMENTATION_SPEC.md`
4. `docs/PHASE0_IMPLEMENTATION_CHECKLIST.md`
5. `docs/DEVELOPMENT_WORKFLOW.md`
6. `docs/CHAT_WORK_AUTONOMY_RULES.md`
7. `docs/PIONEER_OSS_RESEARCH_HANDOVER.md`

If this handoff conflicts with the formal Phase 0 spec/architecture, do not silently resolve it. Preserve the formal Phase 0 boundary and report the conflict.

## 1. Mission

Continue the Relay subsystem of Multi-AI Council Phase 0 using static/mock/fixture/test only.

Relay is a subsystem of Phase 0, not a separate product/repository at this stage.

Target relationship:

```text
Council Orchestrator
  -> Safety / Fan-out Gate
  -> Relay
       -> Provider Adapter: OpenAI/Codex
       -> Provider Adapter: Anthropic/Claude
       -> Provider Adapter: Google/agy
  <- raw provider result
  -> Evidence / Comparison / Reporting
  -> Human final decision
```

Relay is transport/dispatch infrastructure. It must not become the Council decision-maker.

## 2. Relay responsibilities

Relay MAY:

- accept an already-approved packet/context from the caller
- preserve provider identity and provider-specific isolation
- invoke a selected Provider Adapter through a fixed interface
- propagate finite timeout information
- propagate abort/stop signals
- return raw result material to the caller
- preserve request/task/correlation identifiers
- expose transport evidence needed by the caller
- support mock/dry/static verification without live provider execution

Relay MUST NOT decide:

- whether fan-out is allowed
- whether private/secret/PII/private-code content may be sent
- whether 2/3 agreement becomes formal Council consensus
- whether a safety warning may be ignored
- whether model mismatch is acceptable
- whether retry or fallback should occur
- whether a paid/API-key path may be used
- the human's final decision

These decisions belong to Safety / Orchestrator / Human, not Relay.

## 3. Non-negotiable Phase 0 safety constraints

Keep all of these:

- automatic retry = 0
- automatic restart after ambiguous send = 0
- model fallback = disabled
- paid fallback = disabled
- API-key route = disabled
- unknown billing/auth/permission safety boundary => fail closed
- live provider execution requires separate explicit user approval
- runtime GitHub write prohibited
- development GitHub write is limited to this authorized feature branch/PR scope
- no force push
- no branch deletion
- no Merge
- no unrelated repository write
- no settings/permissions mutation
- no Billing/Credits/Overages mutation
- no permission-bypass flags such as `--dangerously-*`
- no arbitrary command generation from user/provider output
- no provider workspace sharing
- no hidden retry/fallback inside Provider Adapters
- no success claim from UI state alone
- UNKNOWN must remain UNKNOWN when backend evidence is insufficient

## 4. Relay engineering carry-forward requirements

The following are Relay-specific engineering requirements learned from the earlier Relay prototype work and are to be carried forward unless they conflict with the formal Phase 0 spec.

### 4.1 Correlation / receipt / duplicate guard

Design the interfaces so future runtime can support:

- `task_id`
- sequence/slot identifier
- target/provider identity
- deterministic payload/request hash
- correlation id
- receipt/evidence references

For dispatch slots:

- reserve/record intent before an external send in future live mode
- same slot + same deterministic hash may be recognized as the same request
- same slot + different hash is a conflict and must not be silently resent
- do not claim exactly-once delivery unless backend evidence proves it
- post-send ambiguity must become UNKNOWN, not an automatic retry

A SQLite ledger may be used later by the controller. The Relay interface should not block that design.

### 4.2 Transport/evidence states

Keep transport evidence distinct from Council answer state.

A future live path should be able to distinguish at least:

```text
prepared/reserved
preflight-ok
sent
backend-completed
readback-verified
delivered
blocked
failed
unknown
```

Exact enum names may evolve, but mock/dry/static success must never be confused with real live delivery.

### 4.3 Mock / dry / live separation

Tests must demonstrate:

- mock mode does not start a real provider
- dry/static validation does not create a live client/process/network/model turn
- simulated success uses simulation-specific state/result, not real `DELIVERED`
- missing SDK/CLI does not silently fall back to a dummy provider in the production path
- production and test doubles are structurally separable

### 4.4 Backend evidence, not fabricated evidence

Never manufacture evidence that looks like a provider/backend response.

Do not:

- fabricate `turn/completed`
- fabricate thread/read equivalents
- fabricate provider receipts
- infer success only because a process was started
- infer success only because a UI showed completion

Future live success must come from real backend/process evidence and readback/correlation appropriate to that provider.

### 4.5 Provider API/CLI integration

Provider-specific behavior belongs behind Provider Adapters.

Prefer official typed APIs/CLI contracts where available.

Do not keep generic calls that bypass the supported public interface when a typed method exists.

For OpenAI/Codex-related adapter work, prior prototype review found that using unsupported generic methods can create false confidence. Static/mock tests should verify the adapter contract without pretending that an unavailable SDK is installed.

Do not run a live provider model in this task.

### 4.6 Execution flags/evidence timing

Fields equivalent to:

- transport executed
- provider/model executed
- request sent

must only become true after the corresponding action actually occurs.

Do not set execution flags during object construction, preflight, or before permission/live gates.

### 4.7 Approval requests

If a future provider/tool requests approval:

- Relay must not auto-accept
- Relay must not auto-deny on behalf of the human unless formal policy explicitly defines that behavior
- preserve the approval request as evidence/state
- stop/fail closed according to caller policy

### 4.8 Request override protection

Design the request boundary so provider/output text cannot silently override execution policy.

Do not accept arbitrary overrides for things such as:

- model / modelProvider
- service tier
- reasoning/effort/thinking
- approval policy
- sandbox/sandbox policy
- cwd/base/config
- developer/general instructions
- disabled plugins
- billing/auth route

Unknown execution-control fields should be rejected or surfaced to the caller, not silently forwarded.

### 4.9 Timeout / abort / stop

Relay must:

- receive provider-specific timeout from the caller/manifest
- reject or surface invalid timeout values according to the formal validator
- propagate abort/stop to the active Provider Adapter
- not start a new dispatch when a stop/no-new-dispatch signal is active
- not retry after timeout
- not fall back after timeout

Provider timeout values remain independent per provider.

### 4.10 Failure isolation

One provider's failure must not erase or rewrite another provider's result.

Keep provider-specific process/result/evidence objects isolated.

## 5. Provider Adapter boundary

Minimum conceptual contract from the Phase 0 spec:

```text
prepare(case_context) -> prepared_context
preflight(prepared_context) -> preflight_result
dispatch(prepared_context) -> process_handle
collect(process_handle) -> raw_result
abort(process_handle) -> abort_result
classify(raw_result) -> provider_state
```

For this Relay-focused branch, avoid moving Council policy into these methods.

Adapter implementations must not independently:

- retry
- fallback
- write to GitHub
- mutate settings
- mutate permissions
- select paid/API-key routes
- construct arbitrary shell from untrusted text

## 6. OSS-first / reuse-first requirement

Before rebuilding generic Relay plumbing from scratch, inspect the existing research in `docs/PIONEER_OSS_RESEARCH_HANDOVER.md`.

Audit candidates before code reuse, especially:

1. ACP
2. codex-acp
3. claude-agent-acp
4. Gemini CLI ACP
5. OpenHands ACP/server pieces
6. Open Orchestrator
7. conduct
8. multi-agent-orchestrator-skill
9. CAID

For each candidate considered, record:

- license
- exact reusable module
- dependency weight
- Windows support
- subscription-login compatibility
- API-key/paid-route assumptions
- permission bypass behavior
- automatic retry/restart behavior
- GitHub write/merge side effects
- destructive cleanup behavior
- secret handling
- test coverage

Do not copy license-UNKNOWN/unlicensed code.

If reuse safety is not proven, prefer a small internal interface/adapter skeleton rather than vendoring uncertain code.

Do not replace Google/agy with Gemini CLI merely because Gemini CLI has ACP support. agy/Antigravity compatibility remains UNKNOWN.

## 7. Static implementation scope for this branch

Allowed now:

- `src/relay/` interfaces and transport abstractions
- `src/providers/` adapter interfaces/stubs that do not execute live providers
- deterministic request envelope/hash helpers
- correlation/receipt data models
- duplicate/conflict guard logic
- timeout/abort/stop plumbing
- provider isolation models
- mock providers
- fixture providers
- static/dry-run transport tests
- malformed/UNKNOWN response tests
- no-retry/no-fallback regression tests
- docs for Relay boundary and known limitations

Recommended file ownership for this branch:

```text
src/relay/**
src/providers/**   # only adapter boundary/mock/static pieces for Relay scope
tests/relay/**
fixtures/relay/**
docs/RELAY_*.md
```

Avoid unrelated Council comparison/reporting/fan-out policy files unless a minimal interface change is strictly required.

## 8. Required tests

At minimum, add deterministic tests proving:

- approved packet passes through unchanged except documented envelope metadata
- provider identity does not cross-contaminate another provider
- correlation id survives dispatch/collect path
- deterministic payload hash is stable
- duplicate same-slot/same-hash is not treated as a new independent send
- same-slot/different-hash is a conflict
- timeout is provider-specific
- abort reaches only the intended active adapter
- stop/no-new-dispatch prevents the next dispatch
- timeout does not trigger retry
- failure does not trigger fallback
- one provider failure does not erase another provider result
- malformed result does not become success
- UNKNOWN result remains UNKNOWN
- mock/static mode does not perform live execution
- no production dummy fallback when provider SDK/CLI is unavailable
- simulation result cannot be mistaken for real delivery
- execution flags are not set before corresponding action
- request policy override fields are rejected/surfaced, not silently applied

If a test is not actually run, report UNKNOWN, not PASS.

## 9. Deferred/UNKNOWN items

Do not guess:

- actual provider timeout values
- exact minimum CLI permission profile
- exact executed-model verification mechanism
- exact subscription-auth verification method
- agy/Antigravity ACP compatibility
- provider network restriction feasibility
- exact production provider SDK/CLI lifecycle
- exactly-once semantics

These UNKNOWNs block future live execution where safety-relevant, but do not block static/mock/interface implementation.

## 10. GitHub workflow for Jules

Work only in:

`kamiyusense/multi-ai-council-phase0`

Work only on:

`feature/relay-transport`

Do not write to:

- `kamiyusense/AIBO-MkII`
- `kamiyusense/multi-ai-council-raw-records`
- other branches owned by other agents

No force push.
No branch deletion.
No Merge.

Create normal commits/checkpoints. A commit SHA is the handoff identity.

PR creation is allowed when the static Relay batch is complete and tests/evidence are recorded.

## 11. Completion report

At the end report exactly:

- repository
- branch
- base/checkpoint commit SHA
- head commit SHA
- changed files
- tests actually run
- PASS / FAIL / UNKNOWN
- blockers
- deferred decisions
- live model execution: YES/NO
- API-key route used: YES/NO
- retry/fallback added: YES/NO
- PR number/URL if created
- Merge performed: NO

## 12. Current authorization boundary

Authorized in this task:

- static/mock/fixture/test only
- branch commits in this repository
- PR creation
- no live provider model execution

Not authorized:

- Merge
- force push
- branch deletion
- settings/permissions changes
- Billing/Credits/Overages changes
- API key creation/use
- other repository writes
- live Relay/app-server/provider POC

