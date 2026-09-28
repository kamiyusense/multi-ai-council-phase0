# Relay Static Checkpoint

Updated: 2026-09-21
Scope: static/mock Relay skeleton only

## Implemented in this checkpoint

- provider static profiles constructed without live authorization
- deterministic dispatch envelope and payload SHA-256
- dispatch-slot duplicate/conflict semantics
- transport-neutral Relay protocol
- mock transport with explicit `live_process_started=false`
- one-attempt mock lifecycle
- provider-specific pinned policy descriptors
- subscription-only auth-kind allowlist
- Claude dangerous bypass option forced false in session metadata
- Antigravity official binary platform selector
- static tests covering duplicate, provider isolation, one-prompt, auth policy, and platform selection

## Evidence status

The test files are committed as executable tests, but this Chat session did not execute the repository test suite after writing the Relay skeleton.

Therefore:

- code review/static inspection: PASS
- tests present: PASS
- static safety baseline and post-change tests: **PASS (unittest, compileall, diff check)**
- GitHub CI: UNKNOWN unless a workflow later reports a result
- live model/provider execution: NO
- live Relay POC: NO
- API-key route: NO
- billing/settings/permission mutation: NO
- Merge: NO

Do not convert the unexecuted Relay tests to PASS without test output or CI evidence.

## Next static batch

A runner capable of executing repository tests may:

1. install/use the pinned ACP Python SDK in an isolated development environment;
2. replace/mock the ACP transport behind the same Relay interface;
3. add ACP initialize/session/prompt/cancel fixtures;
4. run `tests/relay/**`;
5. map the Relay adapter to the Core ProviderAdapter contract;
6. run Core + Relay full mock integration;
7. save exact command output and hashes;
8. stop before live provider execution.

## Static/Mock Factory Boundaries
- The profile -> adapter factory boundary is strictly mock/static only.
- Core PR #3 integration remains a separate checkpoint.

## Live boundary

All provider live blockers in `RELAY_LIVE_BLOCKERS.md` remain in force.


## Integrated Python bridge checkpoint
- Integrated into PR #4 from PR #2 safety foundation: YES
- Deterministic payload hash: SHA-256
- malformed/UNKNOWN/duplicate results: non-success states
- retry count: 0
- fallback: disabled
- live_ready: false
- live model execution: NO
- API key route: NO
- Repository-root unittest discovery is the package-free validation path.
- Raw provider evidence is retained before classification.
- Provider failure does not discard successful peer evidence or enable fallback.
- STOP blocks new dispatch, and cancel/timeout abort is scoped to its provider/session.
- Package-free repository-root verification: 25 tests PASS; compileall and diff check PASS

- Implemented static ProviderAdapterBundle for three-provider fan-out integration.
- Bundle construction validates exactly openai, anthropic, and google.
- Bundle is strictly static/mock only. Real Core fan-out integration remains a separate checkpoint.

## Static/Mock Core Integration Checkpoint
- Static/mock round-trip integration using RelayCoreAdapter duck typing is PASS.
- Note: Independent Chat validation is required before acceptance.

## Static/Mock ACP Client Integration Checkpoint
- Implemented deterministic test-double ACPClient transport
- Short corrective static/mock ACP batch
- Note: Independent Chat validation is required before acceptance.

## Provider Preflight Static Checkpoint
- Implemented static preflight configuration checks for openai, anthropic, and google.
- Provider preflight is wired only for static/mock dispatch and live remains BLOCKED.
- Live execution, external cloud auth, gateways, and provider/SDK retries remain UNKNOWN/BLOCKED.

## Static/Mock Core PR #3 Integration Checkpoint
- Core boundary mapping completed.
- Pinned against exact Core PR #3 head 494b7296f32dce1c173a7699e4bd2d87f70d31a9.
- PASS

## Core PR3 Overlay Runner Checkpoint
- Overlay runner prepared
- Real cross-branch run is still NOT_RUN/UNKNOWN until the next dedicated exact-head workflow executes it. The exact workflow has been prepared.
- Pinned Core head: `494b7296f32dce1c173a7699e4bd2d87f70d31a9`
- Relay parent: `f0eb3b08d240d8f407c51f9f8847684bf2e34bae`
- No Merge/live authorization implied


## Core PR3 Real Cross-Branch Overlay Checkpoint
- happy-path cross-branch static/mock overlay: PASS
- pinned Core head: `494b7296f32dce1c173a7699e4bd2d87f70d31a9`
- Relay code SHA: `223ff60cdde0bf08e980a004be6cb3b8abee89ae`
- request commit: `8d120942a4df83a07270ddeebce60412740bee5c`
- GitHub Actions run: `36380669299` SUCCESS
- exact Core/Relay checkout binding: PASS
- provider order openai/anthropic/google: PASS
- participant_count=3 / agreement_count=3: PASS
- human_required=true / formal_consensus=false: PASS
- raw SHA-256 evidence for all three providers: PASS
- live_turn_executed=false / retry_count=0 / fallback_state=disabled: PASS
- first real run `36380485605` exposed a test-only import-path defect; corrected without retrying that request
- live provider execution: BLOCKED

## Core PR3 Overlay Matrix Checkpoint
- negative-path matrix runner prepared: YES
- negative-path matrix workflow prepared: YES
- real cross-branch matrix run: NOT_RUN/UNKNOWN
- The negative matrix is prepared only and awaits independent acceptance before triggering.

## Isolation Canary Checkpoint
- Core PR3 negative-path matrix run 36383797774 succeeded.
- Relay code SHA validated by that run: 565ba16ed59d5ff979552e7c6524559caa4cf423.
- Pinned Core PR3 head: 494b7296f32dce1c173a7699e4bd2d87f70d31a9.
- Trigger request commit: f8ad5adda400d7f0fafa91aa363dce03442b107a.
- timeout_openai isolated OpenAI TIMEOUT and preserved exact healthy-peer RAW evidence.
- collect_error_anthropic isolated Anthropic ERROR_UNKNOWN and preserved exact healthy-peer RAW evidence.
- invalid_output_google isolated Google INVALID_OUTPUT and preserved exact healthy-peer RAW evidence, including malformed Google RAW.
- every scenario had retry_count=0, fallback_state=disabled, live_turn_executed=false, participant_count=2, agreement_count=2, human_required=true, formal_consensus=false.
- Three delayed Jules-bot direct writes to the canonical Relay branch were detected and rejected/recovered append-only.
- latest recovery commit is c3312b73f91eff45593ebf6472d1460614ae8617 and its tree is 3b706e31739b1b36cdd3882ea9e4cb0cd264bfc9.
- root cause of the direct writes remains UNKNOWN.
- isolation policy: canonical target branch is read-only identity; Jules starts only from an exact per-command jules-work snapshot branch.
- live provider/model execution remains BLOCKED.
